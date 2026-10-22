#!/usr/bin/env python3
"""Interactive, resumable local preparation. No Web automation or automatic Work.

Source trust/sudo, account credentials and destination consent belong to the
user. This program performs the mechanical steps and verifies them on re-entry.
"""
from __future__ import annotations
import argparse
import asyncio
import base64
import fcntl
import getpass
import hashlib
import importlib.util
import json
import os
from pathlib import Path, PureWindowsPath
import platform
import pwd
import re
import secrets
import shutil
import stat
import subprocess
import sys
import tempfile
import urllib.request
import zipfile

SOURCE = Path(__file__).resolve().parents[1]
PORT = 8765
MAX_FILE = 150_000_000


class Refusal(Exception): pass


def require(ok, code):
    if not ok: raise Refusal(code)


def digest(data): return hashlib.sha256(data).hexdigest()


def directory(path, private=False, create=True, *, release_input=False):
    """Never follow symlinks or chmod existing paths; release input is copied, not executed here."""
    path = Path(path)
    require(path.is_absolute() and '..' not in path.parts, 'ABSOLUTE_PATH_REQUIRED')
    current = Path('/')
    for name in path.parts[1:]:
        current /= name
        if create and not current.exists() and not current.is_symlink(): current.mkdir(mode=0o700)
        st = current.lstat()
        reason = None
        if not stat.S_ISDIR(st.st_mode): reason = 'not a real directory; symlinks are unsupported'
        elif not release_input or private:
            if st.st_uid not in (0,os.getuid()): reason = 'owned by another account'
            elif st.st_mode & 0o022: reason = 'group/other-writable'
        if reason:
            raise Refusal(f'UNSAFE_DIRECTORY: {str(current)!r} ({reason}). Have its owner correct this directory only; no permissions were changed.')
    if private:
        st=path.stat();require(st.st_uid==os.getuid() and not st.st_mode&0o077,
                              f'PRIVATE_DIRECTORY_REQUIRED: {str(path)!r} (must be owned by this account with owner-only permissions). No permissions were changed.')
    return path


def read(path, private=True, limit=MAX_FILE, *, release_input=False):
    path=Path(path)
    directory(path.parent,create=False,release_input=release_input and not private)
    flags=os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK
    if release_input and not private:
        # Pin each component: a writable source parent may change after the
        # descriptive directory check, so an absolute leaf open is insufficient.
        directory_flags=os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW|os.O_CLOEXEC
        directory_fd=os.open('/',directory_flags)
        try:
            for name in path.parts[1:-1]:
                previous_fd=directory_fd
                directory_fd=os.open(name,directory_flags,dir_fd=previous_fd)
                os.close(previous_fd)
            fd=os.open(path.name,flags,dir_fd=directory_fd)
        finally:
            os.close(directory_fd)
    else:
        fd=os.open(path,flags)
    with os.fdopen(fd,'rb') as f:
        st=os.fstat(f.fileno())
        require(stat.S_ISREG(st.st_mode) and st.st_nlink==1 and st.st_size<=limit, 'UNSAFE_FILE')
        if private: require(st.st_uid==os.getuid() and not st.st_mode&0o077,'PRIVATE_FILE_REQUIRED')
        data=f.read(limit+1);require(len(data)<=limit,'FILE_TOO_LARGE');return data


def publish(path, data, previous=None, mode=0o600):
    """Compare/replace under the shared preparation lock, NOT a filesystem CAS.

    Same-owner editors must acquire prepare.lock too. A noncooperating writer
    between comparison and rename cannot be excluded by this POSIX protocol.
    """
    directory(path.parent)
    present = path.exists() or path.is_symlink()
    if present:
        current=read(path)
        if current==data: return
        require(previous is not None and current==previous,'EXISTING_FILE_NO_OVERWRITE')
    else: require(previous is None,'FILE_CHANGED')
    fd,tmp=tempfile.mkstemp(prefix='.prepare-',dir=path.parent)
    try:
        with os.fdopen(fd,'wb') as f:
            os.fchmod(f.fileno(),mode);f.write(data);f.flush();os.fsync(f.fileno())
        if present:
            require(read(path)==previous,'FILE_CHANGED');os.replace(tmp,path)
        else: os.link(tmp,path,follow_symlinks=False);os.unlink(tmp)
        d=os.open(path.parent,os.O_RDONLY|os.O_DIRECTORY);os.fsync(d);os.close(d)
    finally:
        if os.path.exists(tmp):os.unlink(tmp)


def json_bytes(value): return (json.dumps(value,sort_keys=True,indent=2)+'\n').encode()


def command(args, *, interactive=False, env=None, private=False):
    result=subprocess.run([str(x) for x in args],env=env,check=False,
                          stdout=None if interactive else subprocess.PIPE,
                          stderr=None if interactive else subprocess.PIPE, text=True,
                          umask=0o077 if private else -1)
    require(result.returncode==0,'COMMAND_FAILED_OR_OUTCOME_UNKNOWN')
    return result.stdout or ''


def load_script(name, source=SOURCE):
    path=source/'scripts'/name
    spec=importlib.util.spec_from_file_location(name.replace('-','_'),path)
    m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m


def release_files(source):
    # Release manifest is a completeness check, not a signature/trust decision.
    m=json.loads(read(source/'release-manifest.json',private=False,release_input=True))
    require(m.get('version')==1 and isinstance(m.get('files'),dict),'INVALID_RELEASE')
    for name,sha in m['files'].items():
        p=Path(name)
        require(not p.is_absolute() and '..' not in p.parts and p.parts[0] not in ('.git','.principal'), 'UNSAFE_RELEASE_PATH')
        require(re.fullmatch('[0-9a-f]{64}',sha) and digest(read(source/p,private=False,release_input=True))==sha,'RELEASE_DIGEST_MISMATCH')
    require(isinstance(m.get('executables',[]),list) and set(m.get('executables',[]))<=m['files'].keys(),'INVALID_RELEASE_MODES')
    require({'prepare','scripts/prepare-system.py','scripts/release-assets.json','browser-extension/extension/projects.js','templates/WEB-PRINCIPAL-CORE.md','Bridge-Skills.zip'}<=m['files'].keys(),'INCOMPLETE_RELEASE')
    return m


def prepare_copy(source,destination):
    m=release_files(source);directory(destination,private=True)
    # Every existing product file must match; interrupted exact copies may continue.
    for name in m['files']:
        data=read(source/name,private=False,release_input=True)
        require(digest(data)==m['files'][name],'RELEASE_DIGEST_MISMATCH')
        publish(destination/name,data,mode=0o700 if name in m.get('executables',['prepare']) else 0o600)
    publish(destination/'release-manifest.json',json_bytes(m))
    if not (destination/'.git').exists():command(['git','init','-q','-b','main',destination],private=True)
    require(command(['git','-C',destination,'rev-parse','--show-toplevel']).strip()==str(destination),'PRODUCT_CHECKOUT_CHANGED')
    return destination


def download(asset,path):
    if path.exists() or path.is_symlink():
        require(digest(read(path))==asset['sha256'],'DOWNLOAD_CHANGED');return path
    require(asset['url'].startswith('https://github.com/') and re.fullmatch('[0-9a-f]{64}',asset['sha256']),'INVALID_ASSET_PIN')
    with urllib.request.urlopen(asset['url'],timeout=60) as r:
        require(r.url.startswith('https://'),'INSECURE_DOWNLOAD_REDIRECT')
        data=r.read(MAX_FILE+1)
    require(len(data)<=MAX_FILE and digest(data)==asset['sha256'],'DOWNLOAD_DIGEST_MISMATCH')
    publish(path,data);return path


def extension_id(manifest):
    raw=base64.b64decode(manifest['key'],validate=True)
    return ''.join(chr(ord('a')+int(c,16)) for c in digest(raw)[:32])


def notification_config(path):
    # Imported only after the candidate's package is installed, without server bootstrap.
    from gpt_agent_bridge.browser_notifications import BrowserNotifications
    return BrowserNotifications.read_config(path)


def extension_receipt(config,record,path):
    legacy_ref=config.get('project_ref')
    legacy_identity=({'project_ref':legacy_ref,'root':config['root'],
                      'scope_id':digest((legacy_ref+'\0'+config['root']).encode())} if legacy_ref else None)
    return {**(record or {}),'version':1,'path':str(path),'extension_id':config['extension_id'],
            'legacy_project_ref':legacy_ref or (record or {}).get('legacy_project_ref'),
            'legacy_identity':legacy_identity or (record or {}).get('legacy_identity')}


def extension_connection(config,receipt):
    connection={'extension_id':config['extension_id'],'token':config['token'],'url':'http://127.0.0.1:8765'}
    if receipt['legacy_project_ref']:connection['project_ref']=receipt['legacy_project_ref']
    if receipt['legacy_identity']:connection['legacy_identity']=receipt['legacy_identity']
    return b'export const connection = '+json.dumps(connection).encode()+b';\n'


def prepare_extension(source,state,config_path,existing=None,registry_discovery=False):
    config=notification_config(config_path)
    pending=state/'notification-pending.json'
    if config is None and pending.exists():config=notification_config(pending)
    record_path=state/'extension.json'
    record=json.loads(read(record_path)) if record_path.exists() else None
    path=Path(record['path']) if record else (Path(existing) if existing else state/'extension')
    directory(path,private=not existing)
    template=source/'browser-extension/extension'
    manifest=json.loads(read(template/'manifest.json',False))
    if config and (path/'manifest.json').exists():
        require(record is not None or existing is not None,'EXISTING_EXTENSION_PATH_REQUIRED_NO_NEW_ID')
        installed=json.loads(read(path/'manifest.json',False))
        # An older unpacked extension without key derives its identity from its
        # unchanged load path. Do not introduce the new release key on upgrade.
        if 'key' in installed:manifest['key']=installed['key'];require(extension_id(installed)==config['extension_id'],'EXTENSION_ID_MISMATCH')
        else:manifest.pop('key',None)
        require(config['port']==PORT,'UNSUPPORTED_EXISTING_PORT_NO_RECONFIGURE')
    elif config is None:
        require(not existing,'EXISTING_EXTENSION_WITHOUT_CONFIG_INSPECT')
        config={'version':3,'discovery':'registered','port':PORT,'token':secrets.token_urlsafe(48),'extension_id':extension_id(manifest)}
    else:
        require(config['port']==PORT and extension_id(manifest)==config['extension_id'],'EXTENSION_ID_MISMATCH')
    # Persist secret first. If interrupted, its exact installed path is already
    # reserved in the receipt; re-entry never generates another identity/token.
    receipt=extension_receipt(config,record,path)
    if not pending.exists():publish(pending,json_bytes(config))
    publish(record_path,json_bytes(receipt),previous=read(record_path) if record else None)
    if not config_path.exists():publish(config_path,json_bytes(config))
    expected={p.name:read(p,False) for p in template.iterdir() if p.is_file() and p.name!='connection.js'}
    expected['manifest.json']=json_bytes(manifest)
    expected['connection.js']=extension_connection(config,receipt)
    # Only a known release receipt authorizes repeat writes. First migration
    # preserves all previous installed bytes in one private local backup.
    backup=state/'extension-before-migration'
    if existing and not record:
        directory(backup,True)
        for name in expected:
            old=path/name
            if old.exists():publish(backup/name,read(old,False))
    for name,data in expected.items():
        target=path/name
        if target.exists():
            prior=read(target,False)
            if prior!=data:
                require(existing is not None or record is not None,'UNRECOGNIZED_EXTENSION_FILE')
                # Existing user's extension is read-only except explicit path
                # adoption or exact previously generated release bytes.
                if not existing:
                    recorded=(record or {}).get('files',{})
                    require(recorded.get(name)==digest(prior),'CHANGED_EXTENSION_NO_OVERWRITE')
                # Private copied folder is required for secret-safe replacement.
                require(target.stat().st_uid==os.getuid() and not target.stat().st_mode&0o077,'PRIVATE_EXTENSION_REQUIRED')
                publish(target,data,previous=prior)
        else:publish(target,data)
    receipt['files']={name:digest(data) for name,data in expected.items()}
    publish(record_path,json_bytes(receipt),previous=read(record_path))
    if registry_discovery and config.get('version') != 3:
        # Explicit capability expansion, not a second project registry. Preserve
        # old configuration bytes and root proof before replacing the config.
        original=read(config_path)
        publish(state/'notification-config-before-registry.json',original)
        upgraded={k:config[k] for k in ('port','token','extension_id')}
        upgraded.update(version=3,discovery='registered')
        publish(config_path,json_bytes(upgraded),previous=original)
    return receipt


def windows_record(state):
    path=state/'windows-extension.json'
    if not path.exists() and not path.is_symlink():return None
    value=json.loads(read(path))
    require(set(value)=={'version','target','nonce','spec','confirmed'} and value['version']==1
            and re.fullmatch('[0-9a-f]{32}',value['nonce']) and type(value['confirmed']) is bool,
            'WINDOWS_RECEIPT_INVALID')
    windows_target(value['target'])
    require(not value['confirmed'] or value['spec'] is not None,'WINDOWS_RECEIPT_INVALID')
    return value


def windows_target(value):
    require(isinstance(value,str) and len(value)<=180 and re.fullmatch(r'[A-Za-z]:\\[^<>:"/|?*\x00-\x1f]+',value)
            and not value.endswith(('\\',' ','.')),'WINDOWS_TARGET_INVALID')
    parts=value[3:].split('\\')
    require(all(p and p not in ('.','..') and not p.endswith((' ','.'))
                and not re.fullmatch(r'(?i:CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\..*)?',p)
                for p in parts) and PureWindowsPath(value).is_absolute(),'WINDOWS_TARGET_INVALID')
    return value


def windows_distro():
    distro=os.environ.get('WSL_DISTRO_NAME')
    require(isinstance(distro,str) and re.fullmatch(r'[^\\/:*?"<>|\x00-\x1f\x7f]+',distro)
            and distro==distro.strip() and distro not in ('.','..')
            and os.environ.get('BRIDGE_WSL_DISTRO')==distro,'WSL_DISTRO_IDENTITY_UNVERIFIED')
    return distro


def windows_spec(state):
    record=json.loads(read(state/'extension.json'))
    require(record['path']==str(state/'extension') and record.get('version')==1,
            'WINDOWS_SOURCE_CHANGED')
    files=record['files']
    require(isinstance(files,dict) and 1<=len(files)<=64
            and {'manifest.json','connection.js','worker.js'}<=files.keys(),'WINDOWS_SOURCE_INVALID')
    for name,sha in files.items():
        require(re.fullmatch(r'[A-Za-z0-9_-]+\.(?:js|json|html|css)',name)
                and re.fullmatch('[0-9a-f]{64}',sha),'WINDOWS_SOURCE_INVALID')
        data=read(state/'extension'/name)
        require(len(data)<=1_000_000 and digest(data)==sha,'WINDOWS_SOURCE_CHANGED')
    manifest=json.loads(read(state/'extension/manifest.json'))
    require(extension_id(manifest)==record['extension_id'],'EXTENSION_ID_MISMATCH')
    return {'extension_id':record['extension_id'],'files':files}


def windows_proof(record):
    return digest(json_bytes({k:record[k] for k in ('target','nonce','spec')}))


def windows_pairing_consistent(state,deployment,configs):
    """Compare future pairing bytes to every surviving generation anchor, read-only."""
    code='WINDOWS_PAIRING_AUTHORITY_INCONSISTENT'
    path=state/'extension';record_path=state/'extension.json'
    record=json.loads(read(record_path)) if record_path.exists() else None
    if record:
        require(record.get('path')==str(path) and record.get('version')==1,code)
    expected=[]
    for config in configs:
        if config is None:continue
        require(config['port']==PORT and (not record or record['extension_id']==config['extension_id']),code)
        expected.append(extension_connection(config,extension_receipt(config,record,path)))
    if not expected:return  # First generation has not created an authority yet.
    require(all(data==expected[0] for data in expected),code)
    sha=digest(expected[0]);connection=path/'connection.js'
    if connection.exists() or connection.is_symlink():
        require(read(connection)==expected[0],code)
    recorded=(record or {}).get('files',{}).get('connection.js')
    if recorded is not None:require(recorded==sha,code)
    if deployment['spec'] is not None:
        require(windows_spec(state)==deployment['spec'],'WINDOWS_SOURCE_CHANGED')
        require(deployment['spec']['files']['connection.js']==sha,code)


def windows_control(phase,state,config_path,target=None,proof=None):
    """Internal nonsecret metadata only. Never export connection bytes to stdout."""
    windows_distro()
    record=windows_record(state)
    authority=[state/n for n in ('extension.json','notification-pending.json','extension')]+[config_path]
    if phase=='reserve':
        windows_target(target)
        if record:
            require(record['target']==target,'WINDOWS_TARGET_CHANGED')
        else:
            require(not any(p.exists() or p.is_symlink() for p in authority),
                    'EXISTING_INSTALLATION_NO_RELOCATION')
            record={'version':1,'target':target,'nonce':secrets.token_hex(16),'spec':None,'confirmed':False}
            publish(state/'windows-extension.json',json_bytes(record))
    if record is None:
        require(phase=='inspect','WINDOWS_RESERVATION_REQUIRED')
        return {'mode':'existing' if any(p.exists() or p.is_symlink() for p in authority) else 'fresh'}
    if record['spec'] is not None:
        require(windows_spec(state)==record['spec'],'WINDOWS_SOURCE_CHANGED')
    if phase=='confirm':
        require(record['spec'] is not None and proof==windows_proof(record),'WINDOWS_CONFIRMATION_CHANGED')
        previous=read(state/'windows-extension.json');record['confirmed']=True
        publish(state/'windows-extension.json',json_bytes(record),previous=previous)
    result={'mode':'windows',**record}
    if record['spec'] is not None:
        result['source']=extension_unc(str(state/'extension'))
        result['proof']=windows_proof(record)
    return result


def windows_staged(state,extension):
    previous=read(state/'windows-extension.json');record=windows_record(state)
    spec=windows_spec(state)
    require(record['spec'] is None or record['spec']==spec,'WINDOWS_SOURCE_CHANGED')
    record['spec']=spec
    publish(state/'windows-extension.json',json_bytes(record),previous=previous)


def extension_unc(path):
    distro=os.environ.get('WSL_DISTRO_NAME')
    selected=os.environ.get('BRIDGE_WSL_DISTRO')
    require(isinstance(distro,str) and re.fullmatch(r'[^\\/:*?"<>|\x00-\x1f\x7f]+',distro)
            and distro==distro.strip() and distro not in ('.','..')
            and (selected is None or selected==distro),'WSL_DISTRO_IDENTITY_UNVERIFIED')
    def convert(flag,value):
        result=subprocess.run(['wslpath',flag,value],capture_output=True,text=True,timeout=10)
        require(result.returncode==0,'WSL_PATH_CONVERSION_FAILED')
        value=result.stdout.rstrip('\r\n')
        require(value and not any(ord(c)<32 or ord(c)==127 for c in value),'WSL_PATH_CONVERSION_INVALID')
        return value
    windows=convert('-w',path)
    prefixes=['\\\\wsl.localhost\\'+distro+'\\','\\\\wsl$\\'+distro+'\\']
    prefix=next((p for p in prefixes if windows.startswith(p)),None)
    require(prefix is not None,'WSL_PATH_NOT_DISTRO_UNC')
    require(convert('-u',windows)==path,'WSL_PATH_ROUNDTRIP_MISMATCH')
    return prefixes[0]+windows[len(prefix):]


def extension_handoff(extension,windows=None):
    """Display the verified receipt, without opening connection/configuration files."""
    path=extension['path'];identity=extension['extension_id']
    require(isinstance(path,str) and Path(path).is_absolute() and '..' not in Path(path).parts
            and not any(ord(c)<32 or ord(c)==127 for c in path),'EXTENSION_DISPLAY_PATH_INVALID')
    require(isinstance(identity,str) and re.fullmatch('[a-p]{32}',identity),'EXTENSION_DISPLAY_ID_INVALID')
    print('Extension files prepared; this does not mean Chrome, services, Tunnel or Chat are connected.',flush=True)
    print('Expected extension ID: '+identity,flush=True)
    if windows:
        require(windows['confirmed'],'WINDOWS_PUBLICATION_PENDING')
        print('Private extension Windows path (copy into Chrome Load unpacked):',flush=True)
        print(windows_target(windows['target']),flush=True)
        return
    print('Private extension Linux path: '+path,flush=True)
    distro=os.environ.get('WSL_DISTRO_NAME')
    selected=os.environ.get('BRIDGE_WSL_DISTRO')
    if not (distro or selected or 'microsoft' in platform.release().lower()):return
    try:
        windows=extension_unc(path)
    except (Refusal,OSError,subprocess.SubprocessError):
        print('Windows extension path: unavailable/unverified. The Linux path above is not a Windows loading path. Check the selected WSL distro and wslpath; reminder setup has stopped.',flush=True)
        raise Refusal('WINDOWS_EXTENSION_PATH_UNVERIFIED') from None
    print('WSL distro: '+distro,flush=True)
    print('Private extension Windows path (copy into Chrome Load unpacked):',flush=True)
    print(windows,flush=True)


def prepare_venv(product):
    venv=product/'.venv';marker=product/'venv-owner.json'
    identity={'path':str(venv),'owner':os.getuid(),'purpose':'bridge-preparation-venv-v1'}
    if marker.exists():require(json.loads(read(marker))==identity,'VENV_OWNER_CHANGED')
    elif venv.exists() or venv.is_symlink():
        # Earlier successfully prepared environments can be reused, but an
        # unmarked empty/partial user directory is never adopted or deleted.
        directory(venv)
        require((venv/'bin/python').is_file() and (venv/'pyvenv.cfg').is_file(),'UNOWNED_PARTIAL_VENV_INSPECT')
    else:publish(marker,json_bytes(identity)) # intent before directory creation
    if marker.exists():
        if venv.exists():directory(venv)
        ready=(venv/'bin/python').is_file() and (venv/'pyvenv.cfg').is_file()
        if ready:
            ready=subprocess.run([str(venv/'bin/python'),'-I','-B','-c','import pip,sys; assert sys.prefix != sys.base_prefix'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL).returncode==0
        if not ready:
            command([sys.executable,'-m','venv',venv],private=True) # completes owned partial; no removal
    require((venv/'bin/python').is_file(),'VENV_INTERPRETER_UNAVAILABLE')
    return venv/'bin/python'


def replace_tunnel_credentials(product,ask=input,secret=getpass.getpass):
    tunnel=load_script('install-bridge-tunnel-autostart.py',product)
    plan=tunnel.record()['plan'];tunnel.configured_owner(plan)
    previous=read(tunnel.CREDENTIALS)
    tunnel.validate_credentials(json.loads(previous))
    require(ask('Replace the saved Tunnel credentials with your Restricted Read + Use runtime key? Services stay unchanged. [yes/no] ').strip()=='yes','CREDENTIAL_REPLACEMENT_NOT_AUTHORIZED')
    import warnings
    with warnings.catch_warnings():
        warnings.simplefilter('error',getpass.GetPassWarning)
        value={'tunnel_id':secret('Own Tunnel ID (hidden): '),'runtime_api_key':secret('Restricted runtime API key (hidden; never Admin/All): ')}
    tunnel.validate_credentials(value)
    require(not value['runtime_api_key'].startswith('sk-admin-'),'ADMIN_KEY_REFUSED')
    publish(tunnel.CREDENTIALS,json_bytes(value),previous=previous)
    print('Credentials replaced privately; services unchanged. Follow GETTING-STARTED credential activation steps. No successful connection inferred.')


def prepare_plugin(source,state,app_id):
    helper=load_script('prepare-personal-plugin.py',source);helper.validate_id(app_id)
    destination=state/'personal-plugin'
    # Reconstruct expected outputs in an isolated sibling and compare. No blind
    # overwrite of existing user settings and no read of source .app.json.
    with tempfile.TemporaryDirectory(prefix='plugin-check-',dir=state) as tmp:
        expected=Path(tmp)/'package';helper.prepare(source,expected,app_id)
        files={str(p.relative_to(expected)):p.read_bytes() for p in expected.rglob('*') if p.is_file()}
        directory(destination,True)
        for name,data in files.items():publish(destination/name,data)
    archive=state/'personal-plugin.zip'
    import io
    buffer=io.BytesIO()
    with zipfile.ZipFile(buffer,'w',zipfile.ZIP_DEFLATED) as z:
        for name,data in sorted(files.items()):
            # Native ChatGPT plugin bundle, excluding local marketplace metadata.
            if name.startswith('plugins/gpt-agent-bridge/'):
                info=zipfile.ZipInfo(name.removeprefix('plugins/gpt-agent-bridge/'));z.writestr(info,data)
    require(len(buffer.getvalue())>1000,'PLUGIN_BUNDLE_EMPTY')
    publish(archive,buffer.getvalue());return archive


def select_herdr(ask=input):
    """Configure the user's existing external host; never install or open a session."""
    found=os.environ.get('BRIDGE_HERDR_BIN') or shutil.which('herdr')
    if not found:found=ask('Absolute path to your existing Herdr executable (see GETTING-STARTED prerequisites): ').strip()
    path=Path(found).expanduser() if found else Path('.')
    require(path.is_absolute() and path.is_file() and os.access(path,os.X_OK),'EXISTING_HERDR_EXECUTABLE_REQUIRED')
    path=path.resolve(strict=True)
    require(re.search(r'\b0\.9\.0\b',command([path,'--version'])) is not None,'HERDR_CLI_COMPATIBILITY_REQUIRED')
    return path


def environment_ready(python,product):
    probe="import importlib.metadata as m,pathlib,sys; from mcp import Client; import pydantic,gpt_agent_bridge; assert pathlib.Path(sys.prefix)==pathlib.Path(sys.argv[1])/'.venv'; assert pathlib.Path(gpt_agent_bridge.__file__).resolve()==pathlib.Path(sys.argv[1])/'src/gpt_agent_bridge/__init__.py'; "+";".join("assert m.version(%r)==%r" % tuple(line.split('==')) for line in read(product/'requirements.txt',False).decode().splitlines() if line and not line.startswith('#'))
    return subprocess.run([str(python),'-I','-B','-c',probe,str(product)],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL).returncode==0


def reminder_runtime(product,home):
    """Observe the existing local core; never bootstrap, repair or probe a service."""
    try:
        directory(product,private=True,create=False)
        release_files(product)
        directory(product/'.venv/bin',create=False)
        read(product/'.venv/pyvenv.cfg',False)
        python=product/'.venv/bin/python'
        require(python.is_file() and os.access(python,os.X_OK) and environment_ready(python,product),
                'PRIVATE_PYTHON_NOT_READY')
        owner=pwd.getpwuid(os.getuid())
        identity={'user':owner.pw_name,'uid':os.getuid(),'gid':os.getgid(),'home':str(home)}
        bridge=load_script('install-bridge-autostart.py',product)
        plan=bridge.installation_record()['plan']
        require(all(plan.get(k)==v for k,v in {**identity,'repo':str(product),
                'workspace':str(product),'port':PORT,'entrypoint':'module'}.items()),'DIFFERENT_CORE')
        tunnel=load_script('install-bridge-tunnel-autostart.py',product)
        plan=tunnel.record()['plan']
        require(all(plan.get(k)==v for k,v in identity.items()),'DIFFERENT_CORE')
        tunnel.configured_owner(plan)
        return python
    except Exception as error:
        # These observations have no writes or secret output. Do not expose an
        # installer's raw exception or try to finish a partial core here.
        raise Refusal('REMINDERS_CORE_NOT_READY: Complete ./prepare first, or inspect the existing core installation. No reminder files were changed.') from error


def reenter(args,product,python):
    if SOURCE==product and Path(sys.executable)==python:return
    argv=[str(python),'-B',str(product/'scripts/prepare-bridge.py'),args.action]
    for option in ('existing_extension','windows_phase','windows_target_base64','windows_proof'):
        value=getattr(args,option,None)
        if value is not None:argv+=['--'+option.replace('_','-'),str(value)]
    os.execv(python,argv)


def remember_source_kind(state,kind):
    path=state/'source-kind';data=(kind+'\n').encode()
    publish(path,data,previous=read(path) if path.exists() or path.is_symlink() else None)


def recorded_source_kind(state):
    path=state/'source-kind'
    return 'checkout' if path.exists() and read(path)==b'checkout\n' else 'full'


def skills_upload_instruction(kind):
    if kind=='checkout':
        return 'Skills upload: this source checkout has no Bridge-Skills.zip. Obtain the FULL installation package, select Bridge-Skills.zip at its root, then in ordinary ChatGPT Web use @Plugin Creator to add the Skills to your Bridge plugin.'
    return 'Skills upload: return to the FULL package folder you extracted, select Bridge-Skills.zip at its root, then in ordinary ChatGPT Web use @Plugin Creator to add the Skills to your Bridge plugin.'


def prepare_reminders(args,home,state):
    product=state/'product';config_path=home/'.config/gpt-agent-bridge/browser-notifications.json'
    phase=getattr(args,'windows_phase',None)
    require(not phase or not args.existing_extension,'WINDOWS_PHASE_INVALID')
    python=reminder_runtime(product,home)
    reenter(args,product,python)
    if phase:
        windows_distro()
        if phase in ('inspect','reserve','confirm'):
            encoded=getattr(args,'windows_target_base64',None)
            target=base64.b64decode(encoded,validate=True).decode('utf-8') if encoded else None
            print(json.dumps(windows_control(phase,state,config_path,target,getattr(args,'windows_proof',None))),flush=True)
            return
        require(windows_record(state) is not None,'WINDOWS_RESERVATION_REQUIRED')
    deployment=windows_record(state)
    configs=[notification_config(p) for p in (config_path,state/'notification-pending.json')]
    if deployment:
        pristine=(deployment['spec'] is None and not (state/'extension.json').exists()
                  and not (state/'extension').exists())
        require(any(c is not None for c in configs) or pristine,'WINDOWS_PAIRING_AUTHORITY_MISSING')
        windows_pairing_consistent(state,deployment,configs)
        if phase!='stage':
            require(deployment['confirmed'] and windows_spec(state)==deployment['spec'],'WINDOWS_PUBLICATION_PENDING')
    else:
        record=json.loads(read(state/'extension.json')) if (state/'extension.json').exists() else None
        path=Path(record['path']) if record else (args.existing_extension or state/'extension')
        require(any(c is not None for c in configs) or not (record or path.exists() or path.is_symlink()),
                'EXISTING_EXTENSION_WITHOUT_CONFIG_INSPECT')
        require(record is not None or configs[0] is None or args.existing_extension is not None,
                'EXISTING_EXTENSION_PATH_REQUIRED_NO_NEW_ID')
        if record:
            require(all(c is None or c['extension_id']==record['extension_id'] for c in configs),'EXTENSION_ID_MISMATCH')
        paired=[extension_connection(c,extension_receipt(c,record,path)) for c in configs if c is not None]
        require(not paired or all(c==paired[0] for c in paired),'PAIRING_AUTHORITY_INCONSISTENT')
        if record and paired:
            connection=path/'connection.js'
            require(record.get('files',{}).get('connection.js') in (None,digest(paired[0]))
                    and (not (connection.exists() or connection.is_symlink()) or read(connection)==paired[0]),
                    'PAIRING_AUTHORITY_INCONSISTENT')
    saved=next((c for c in configs if c is not None),None)
    if saved is None or saved.get('version')!=3:
        require(input('Allow optional reminders to read registered project refs/canonical roots and completion metadata? No report text or task authority; each Chat still requires explicit bind/enable. [yes/no] ').strip()=='yes','REGISTRY_METADATA_AUTHORIZATION_REQUIRED')
    extension=prepare_extension(product,state,config_path,args.existing_extension,registry_discovery=True)
    if deployment:
        windows_staged(state,extension)
        if phase=='stage':
            print('Reminder files prepared privately; waiting for Windows publication.',flush=True)
            return
        deployment=windows_record(state)
        require(deployment['confirmed'],'WINDOWS_PUBLICATION_PENDING')
    extension_handoff(extension,**({'windows':deployment} if deployment else {}))
    print('Optional reminder files are ready. Load the extension in Chrome, then explicitly select and bind/enable the exact destination Chat. No service was restarted and no message was sent.')


def status_file(path, owner, private=False, *, directory=False):
    """Metadata only, through pinned real directories; never open a payload."""
    fd=None
    try:
        flags=os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW|os.O_CLOEXEC
        fd=os.open('/',flags)
        for name in path.parts[1:-1]:
            child=os.open(name,flags,dir_fd=fd);os.close(fd);fd=child
            st=os.fstat(fd)
            if st.st_uid not in (0,owner) or st.st_mode&0o022:return 'unverified'
        st=os.stat(path.name,dir_fd=fd,follow_symlinks=False)
        kind=stat.S_ISDIR if directory else stat.S_ISREG
        mode=0o700 if directory else (0o600 if private else 0o644)
        if not kind(st.st_mode) or st.st_uid!=owner or stat.S_IMODE(st.st_mode)!=mode:
            return 'unverified'
        if not directory and st.st_nlink!=1:return 'unverified'
        return 'present'
    except FileNotFoundError:return 'absent'
    except OSError:return 'unverified'
    finally:
        if fd is not None:os.close(fd)


def status_service(unit):
    properties=('LoadState','ActiveState','SubState','UnitFileState','ExecMainStatus',
                'FragmentPath','DropInPaths','NeedDaemonReload')
    try:
        result=subprocess.run(['/usr/bin/systemctl','show','--no-pager',
            '--property='+','.join(properties),unit],stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,text=True,timeout=3,
            env={'PATH':'/usr/bin:/bin','LC_ALL':'C','SYSTEMD_PAGER':'cat'},check=False)
        if result.returncode not in (0,4) or len(result.stdout)>8192:return None
        values={}
        for line in result.stdout.splitlines():
            key,sep,value=line.partition('=')
            if not sep or key not in properties or key in values:return None
            values[key]=value
        if set(values)!=set(properties):return None
        if values['LoadState'] not in ('loaded','not-found','masked','error','bad-setting'):return None
        if values['ActiveState'] not in ('active','inactive','failed','activating','deactivating','reloading','maintenance'):return None
        if not re.fullmatch('[a-z][a-z0-9-]{0,39}',values['SubState']):return None
        if not re.fullmatch('[a-z-]{0,40}',values['UnitFileState']):return None
        if not re.fullmatch('[0-9]{1,3}',values['ExecMainStatus']):return None
        if values['NeedDaemonReload'] not in ('yes','no'):return None
        return values
    except (OSError,subprocess.TimeoutExpired,UnicodeError):return None


def preparation_status(home):
    if not home.is_absolute() or home==Path('/') or '..' in home.parts:
        print('Status unavailable: this account has no supported absolute Linux home. Nothing was changed.');return
    state=home/'.local/share/gpt-agent-bridge'
    files={
        'local state':status_file(state,os.getuid(),True,directory=True),
        'product receipt':status_file(state/'product/release-manifest.json',os.getuid(),True),
        'Bridge record':status_file(Path('/usr/local/lib/gpt-agent-bridge-autostart/installation.json'),0),
        'Tunnel record':status_file(Path('/usr/local/lib/gpt-agent-bridge-tunnel-autostart/installation.json'),0),
    }
    services={name:status_service(unit) for name,unit in (
        ('Bridge','gpt-agent-bridge-autostart.service'),('Tunnel','gpt-agent-bridge-tunnel.service'))}
    if all(value=='absent' for value in files.values()) and all(
            p and p.get('LoadState')=='not-found' for p in services.values()):
        print('Not prepared. Run ./prepare to begin.')
        print('Web connection: not checked. Nothing was changed.');return
    elif 'unverified' in files.values():
        print('Preparation unverified: check file ownership and path permissions.')
    elif all(value=='present' for value in files.values()):
        print('Preparation files found (metadata only).')
    elif all(value=='absent' for value in files.values()):
        print('Preparation unverified: local files are absent; service installation is not confirmed.')
    else:print('Partial preparation: some files are present and others are missing.')
    print('Files: '+ '; '.join(name+' '+value for name,value in files.items())+'.')
    for name,p in services.items():
        if not p:print(name+': unknown (systemctl unavailable or status could not be read).');continue
        if p.get('LoadState')=='not-found':print(name+': service not found.');continue
        print(name+': '+p['ActiveState']+'/'+p['SubState']+'; boot '+(p['UnitFileState'] or 'unknown')+'; last exit '+p['ExecMainStatus']+'.')
        expected='/etc/systemd/system/'+('gpt-agent-bridge-autostart.service' if name=='Bridge' else 'gpt-agent-bridge-tunnel.service')
        if p.get('FragmentPath')!=expected or p.get('DropInPaths'):
            print(name+': unit path/drop-ins unverified; do not change it automatically.')
        if p.get('NeedDaemonReload')=='yes':print(name+': systemd reports a pending unit reload; no reload was run.')
    if any(value!='present' for value in files.values()) or any(
            not p or p.get('LoadState')!='loaded' or p.get('ActiveState')!='active' for p in services.values()):
        print('Keep existing files; inspect missing/unverified records or service failures before changing or retrying setup.')
    print('File contents and service ownership were not verified. Web connection: not checked. Nothing was changed.')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',nargs='?',default='prepare',choices=['prepare','reminders','status','credentials'])
    parser.add_argument('--existing-extension',type=Path,help='For reminders: explicitly adopt the unchanged original private loading directory')
    parser.add_argument('--windows-phase',choices=['inspect','reserve','stage','confirm','continue'],help=argparse.SUPPRESS)
    parser.add_argument('--windows-target-base64',help=argparse.SUPPRESS)
    parser.add_argument('--windows-proof',help=argparse.SUPPRESS)
    args=parser.parse_args()
    if args.action=='status':
        require(not args.windows_phase,'WINDOWS_PHASE_INVALID')
        if os.getuid()==0 or platform.system()!='Linux':
            print('Status unavailable: run as the Linux installation owner, not root. Nothing was changed.');return
        try:home=Path(pwd.getpwuid(os.getuid()).pw_dir)
        except (KeyError,OSError,TypeError,ValueError):
            print('Status unavailable: the Linux account home could not be determined. Nothing was changed.');return
        return preparation_status(home)
    require(os.getuid()!=0 and platform.system()=='Linux','RUN_AS_LINUX_OWNER_NOT_ROOT')
    home=Path(pwd.getpwuid(os.getuid()).pw_dir)
    state=home/'.local/share/gpt-agent-bridge'
    if args.action=='reminders' and not state.exists():
        raise Refusal('REMINDERS_CORE_NOT_READY: Run ./prepare before setting up optional reminders.')
    directory(state,True,create=args.action!='reminders')
    lock=os.open(state/'prepare.lock',os.O_RDWR|os.O_CREAT|os.O_NOFOLLOW,0o600)
    fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    try:
        return run_locked(args,home,state)
    finally:
        os.close(lock)


def run_locked(args,home,state):
    if args.action=='reminders':return prepare_reminders(args,home,state)
    require(not getattr(args,'windows_phase',None),'WINDOWS_PHASE_INVALID')
    if args.action=='status':
        return preparation_status(home)
    product=state/'product'
    if args.action=='credentials':
        replace_tunnel_credentials(product)
        if input('Activate the replacement by stopping/starting only the owned Tunnel service now (sudo)? [yes/no] ').strip()=='yes':
            command(['sudo','python3',product/'scripts/prepare-system.py','credentials-activate','--source',product,'--user',pwd.getpwuid(os.getuid()).pw_name],interactive=True)
        return
    if args.action=='prepare':
        source_kind=None
        if SOURCE!=product or Path(sys.executable)!=product/'.venv/bin/python':
            print('Bridge will create its own local product/venv, download pinned official assets if needed, and ask sudo to install the strict Bridge/Tunnel services. No project task or Web action is automatic.')
            require(input('Trust this release and continue local preparation? [yes/no] ').strip()=='yes','SOURCE_TRUST_REQUIRED')
            source=SOURCE
            source_kind=(('full' if (source/'release-manifest.json').exists() else 'checkout')
                         if SOURCE!=product else None)
            if source_kind=='checkout':
                # A complete clean public Git checkout is also a supported acquisition.
                # Generate the same allowlisted release automatically, never ask users
                # to assemble scripts/Skills/extensions or edit package JSON.
                require(command(['git','-C',source,'rev-parse','--show-toplevel']).strip()==str(source),'COMPLETE_RELEASE_OR_CHECKOUT_REQUIRED')
                status=command(['git','-C',source,'status','--porcelain','--','.',' :(exclude).principal'.strip(),':(exclude).principal/**',':(exclude).app.json'])
                require(not status.strip(),'SOURCE_CHECKOUT_DIRTY_BUILD_REVIEWED_RELEASE')
                revision=command(['git','-C',source,'rev-parse','HEAD']).strip()
                source=state/('release-'+revision)
                if not source.exists():load_script('build-distribution.py').build(SOURCE,source)
                release_files(source)
        else:
            print('Continuing preparation in the private Python environment.')
            source=SOURCE
        prepare_copy(source,product)
        python=prepare_venv(product)
        # pip is repeatable package preparation; service install is never repeated
        # merely because a journal says incomplete. No global environment changes.
        ready=environment_ready(python,product)
        if not ready:command([python,'-m','pip','install','-e',product],private=True)
        if source_kind:remember_source_kind(state,source_kind)
        reenter(args,product,python)
        pins=json.loads(read(product/'scripts/release-assets.json',False));arch=platform.machine();require(arch in pins,'ARCHITECTURE_NOT_SUPPORTED')
        herdr=select_herdr()
        bundle=download(pins[arch]['tunnel'],state/'tunnel-runtime-0.0.16.zip')
        helper=product/'scripts/prepare-system.py';user=pwd.getpwuid(os.getuid()).pw_name
        command(['sudo','python3',helper,'bridge','--source',product,'--user',user,'--herdr',herdr],interactive=True)
        base=['sudo','python3',helper,'tunnel-install','--source',product,'--user',user,'--bundle',bundle,'--arch',arch]
        command(base,interactive=True)
        tunnel=load_script('install-bridge-tunnel-autostart.py',product)
        if tunnel.CREDENTIALS.exists():tunnel.validate_credentials(json.loads(tunnel.read_file(tunnel.CREDENTIALS,{os.getuid()},0o600,True)))
        else:
            print('Open https://platform.openai.com/settings/organization/tunnels ; select the owning organization and target ChatGPT workspace. At https://platform.openai.com/settings/organization/api-keys create Restricted: Tunnels Read + Use. Never use Admin keys or All. Obtain the Tunnel ID and this runtime key. Associate your intended ChatGPT workspace. See docs/GETTING-STARTED.md. Enter secrets only in the following local hidden prompts.')
            tunnel.configure()
        base[3]='tunnel-start';command(base,interactive=True)
        bridge=load_script('install-bridge-autostart.py',product)
        config=bridge.load_config();health=asyncio.run(bridge.probe(config))
        print('Local checks: '+json.dumps(health))
        require(health['bridge_mcp']=='initialized_healthy','BRIDGE_MCP_NOT_READY')
        print('Create/select your private Bridge MCP plugin using Tunnel in https://chatgpt.com/plugins . Provider login, fees and official permission prompts are your decisions.')
        print(skills_upload_instruction(recorded_source_kind(state)))
        print('Unchanged Web Principal Core: '+str(product/'templates/WEB-PRINCIPAL-CORE.md'))
        print('Local service checks passed. This does not confirm the remote Web plugin or Skills are connected. No repository or running Herdr session/Agent is required; you may close this terminal.')
        print('Later, in ordinary Web use the project-onboarding Skill to connect an authorized existing Git repository. Review/save the tool-provided Host Binding with Core and your existing instructions. Fresh continuity is separate and optional.')
        print('Chrome completion reminders are optional. Later run ./prepare reminders (Windows: .\\Start-Bridge.ps1 reminders), then explicitly select and bind/enable the exact destination Chat in the extension. Daily use needs no prepare command; start your Agent in Herdr yourself, before or after opening Web.')
        return


def report_failure(error):
    reasons={
        'client_version':'The Tunnel client version was rejected',
        'client_digest':'The Tunnel client does not match its recorded digest',
        'unsafe_directory':'A Tunnel service directory has unsafe ownership or permissions',
        'installation_not_completed':'Tunnel service installation did not finish',
    }
    code=getattr(error,'code',None)
    if isinstance(error,Refusal):
        print(str(error),file=sys.stderr)
    elif isinstance(code,str) and code in reasons:
        stage=getattr(error,'stage',None)
        suffix=(' (stage: '+stage+')' if stage in
                ('preflight','unit_review','create_installation_directories',
                 'publish_runner','publish_unit','publish_manifest','reload_and_verify_disabled') else '')
        print(reasons[code]+': '+code+suffix+'.',file=sys.stderr)
    else:
        print('PREPARATION_STOPPED_INSPECT_BEFORE_RETRY',file=sys.stderr)
    print('Completed files were retained. Inspect the reported failure before continuing; do not repeat an operation with an unknown outcome.',file=sys.stderr)


if __name__=='__main__':
    try:main()
    except Exception as e:
        report_failure(e)
        raise SystemExit(1)
