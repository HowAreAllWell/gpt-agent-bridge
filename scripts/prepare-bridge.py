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
from pathlib import Path
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


def directory(path, private=False, create=True):
    """No symlink traversal; never chmod a pre-existing directory."""
    path = Path(path)
    require(path.is_absolute() and '..' not in path.parts, 'ABSOLUTE_PATH_REQUIRED')
    current = Path('/')
    for name in path.parts[1:]:
        current /= name
        if create and not current.exists() and not current.is_symlink(): current.mkdir(mode=0o700)
        st = current.lstat()
        require(stat.S_ISDIR(st.st_mode) and st.st_uid in (0,os.getuid()) and not st.st_mode & 0o022, 'UNSAFE_DIRECTORY')
    if private:
        st=path.stat();require(st.st_uid==os.getuid() and not st.st_mode&0o077, 'PRIVATE_DIRECTORY_REQUIRED')
    return path


def read(path, private=True, limit=MAX_FILE):
    directory(path.parent,create=False)
    fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
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


def command(args, *, interactive=False, env=None):
    result=subprocess.run([str(x) for x in args],env=env,check=False,
                          stdout=None if interactive else subprocess.PIPE,
                          stderr=None if interactive else subprocess.PIPE, text=True)
    require(result.returncode==0,'COMMAND_FAILED_OR_OUTCOME_UNKNOWN')
    return result.stdout or ''


def load_script(name, source=SOURCE):
    path=source/'scripts'/name
    spec=importlib.util.spec_from_file_location(name.replace('-','_'),path)
    m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m


def release_files(source):
    # Release manifest is a completeness check, not a signature/trust decision.
    m=json.loads(read(source/'release-manifest.json',private=False))
    require(m.get('version')==1 and isinstance(m.get('files'),dict),'INVALID_RELEASE')
    for name,sha in m['files'].items():
        p=Path(name)
        require(not p.is_absolute() and '..' not in p.parts and p.parts[0] not in ('.git','.principal'), 'UNSAFE_RELEASE_PATH')
        require(re.fullmatch('[0-9a-f]{64}',sha) and digest(read(source/p,private=False))==sha,'RELEASE_DIGEST_MISMATCH')
    require(isinstance(m.get('executables',[]),list) and set(m.get('executables',[]))<=m['files'].keys(),'INVALID_RELEASE_MODES')
    require({'prepare','scripts/prepare-system.py','scripts/release-assets.json','browser-extension/extension/projects.js','templates/WEB-PRINCIPAL-CORE.md'}<=m['files'].keys(),'INCOMPLETE_RELEASE')
    return m


def prepare_copy(source,destination):
    m=release_files(source);directory(destination,private=True)
    # Every existing product file must match; interrupted exact copies may continue.
    for name in m['files']:
        publish(destination/name,read(source/name,private=False),mode=0o700 if name in m.get('executables',['prepare']) else 0o600)
    publish(destination/'release-manifest.json',json_bytes(m))
    if not (destination/'.git').exists():command(['git','init','-q','-b','main',destination])
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
    legacy_ref=config.get('project_ref') if config else None
    legacy_identity=({'project_ref':legacy_ref,'root':config['root'],
                      'scope_id':digest((legacy_ref+'\0'+config['root']).encode())} if legacy_ref else None)
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
    # Persist secret first. If interrupted, its exact installed path is already
    # reserved in the receipt; re-entry never generates another identity/token.
    receipt={**(record or {}),'version':1,'path':str(path),'extension_id':config['extension_id'],'legacy_project_ref':legacy_ref or (record or {}).get('legacy_project_ref'),
             'legacy_identity':legacy_identity or (record or {}).get('legacy_identity')}
    if not pending.exists():publish(pending,json_bytes(config))
    publish(record_path,json_bytes(receipt),previous=read(record_path) if record else None)
    if not config_path.exists():publish(config_path,json_bytes(config))
    connection={'extension_id':config['extension_id'],'token':config['token'],'url':'http://127.0.0.1:8765'}
    if receipt['legacy_project_ref']:connection['project_ref']=receipt['legacy_project_ref']
    if receipt['legacy_identity']:connection['legacy_identity']=receipt['legacy_identity']
    expected={p.name:read(p,False) for p in template.iterdir() if p.is_file() and p.name!='connection.js'}
    expected['manifest.json']=json_bytes(manifest)
    expected['connection.js']=b'export const connection = '+json.dumps(connection).encode()+b';\n'
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


def extension_handoff(extension):
    """Display the verified receipt, without opening connection/configuration files."""
    path=extension['path'];identity=extension['extension_id']
    require(isinstance(path,str) and Path(path).is_absolute() and '..' not in Path(path).parts
            and not any(ord(c)<32 or ord(c)==127 for c in path),'EXTENSION_DISPLAY_PATH_INVALID')
    require(isinstance(identity,str) and re.fullmatch('[a-p]{32}',identity),'EXTENSION_DISPLAY_ID_INVALID')
    print('Extension files prepared; this does not mean Chrome, services, Tunnel or Chat are connected.',flush=True)
    print('Private extension Linux path: '+path,flush=True)
    print('Expected extension ID: '+identity,flush=True)
    distro=os.environ.get('WSL_DISTRO_NAME')
    selected=os.environ.get('BRIDGE_WSL_DISTRO')
    if not (distro or selected or 'microsoft' in platform.release().lower()):return
    try:
        require(isinstance(distro,str) and re.fullmatch(r'[^\\/:*?"<>|\x00-\x1f\x7f]+',distro)
                and distro==distro.strip() and distro not in ('.','..')
                and (selected is None or selected==distro),'WSL_DISTRO_IDENTITY_UNVERIFIED')
        # Use argv, never a shell. Neither stdout nor stderr from a failed converter is logged.
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
        # Normalize the verified WSL alias to one copyable line, without guessing a home/path.
        windows=prefixes[0]+windows[len(prefix):]
    except (Refusal,OSError,subprocess.SubprocessError):
        print('Windows extension path: unavailable/unverified. The Linux path above is not a Windows loading path. Check the selected WSL distro and wslpath; preparation stops before service setup.',flush=True)
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
        require((venv/'bin/python').is_file() and (venv/'pyvenv.cfg').is_file(),'UNOWNED_PARTIAL_VENV_INSPECT')
    else:publish(marker,json_bytes(identity)) # intent before directory creation
    if marker.exists():
        if venv.exists():directory(venv)
        ready=(venv/'bin/python').is_file() and (venv/'pyvenv.cfg').is_file()
        if ready:
            ready=subprocess.run([str(venv/'bin/python'),'-I','-c','import pip,sys; assert sys.prefix != sys.base_prefix'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL).returncode==0
        if not ready:
            command([sys.executable,'-m','venv',venv]) # completes owned partial; no removal
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


def creator_material(source,state):
    helper=load_script('prepare-personal-plugin.py',source)
    destination=directory(state/'Creator-attachments',True)
    for skill in helper.SKILLS:
        publish(destination/(skill+'.md'),read(source/'skills'/skill/'SKILL.md',False))
    publish(destination/'LICENSE',read(source/'LICENSE',False))
    return destination


def select_herdr(ask=input):
    """Configure the user's existing external host; never install or open a session."""
    found=os.environ.get('BRIDGE_HERDR_BIN') or shutil.which('herdr')
    if not found:found=ask('Absolute path to your existing Herdr executable (see GETTING-STARTED prerequisites): ').strip()
    path=Path(found).expanduser() if found else Path('.')
    require(path.is_absolute() and path.is_file() and os.access(path,os.X_OK),'EXISTING_HERDR_EXECUTABLE_REQUIRED')
    path=path.resolve(strict=True)
    require(re.search(r'\b0\.9\.0\b',command([path,'--version'])) is not None,'HERDR_CLI_COMPATIBILITY_REQUIRED')
    return path


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',nargs='?',default='prepare',choices=['prepare','status','credentials'])
    parser.add_argument('--existing-extension',type=Path,help='Explicit adoption of the unchanged original private loading directory')
    args=parser.parse_args()
    require(os.getuid()!=0 and platform.system()=='Linux','RUN_AS_LINUX_OWNER_NOT_ROOT')
    home=Path(pwd.getpwuid(os.getuid()).pw_dir)
    state=directory(home/'.local/share/gpt-agent-bridge',True)
    lock=os.open(state/'prepare.lock',os.O_RDWR|os.O_CREAT|os.O_NOFOLLOW,0o600)
    fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    try:
        return run_locked(args,home,state)
    finally:
        os.close(lock)


def run_locked(args,home,state):
    config_path=home/'.config/gpt-agent-bridge/browser-notifications.json'
    if args.action=='status':
        for name in ['extension.json','product/release-manifest.json']:
            print(name+': '+('present; verify through prepare' if (state/name).exists() else 'not prepared'))
        print('No service, account, Chat binding or report-read success inferred.');return
    product=state/'product'
    if args.action=='credentials':
        replace_tunnel_credentials(product)
        if input('Activate the replacement by stopping/starting only the owned Tunnel service now (sudo)? [yes/no] ').strip()=='yes':
            command(['sudo','python3',product/'scripts/prepare-system.py','credentials-activate','--source',product,'--user',pwd.getpwuid(os.getuid()).pw_name],interactive=True)
        return
    if args.action=='prepare':
        print('Bridge will create its own local product/venv, download pinned official assets if needed, and ask sudo to install the strict Bridge/Tunnel services. No project task or Web action is automatic.')
        if SOURCE!=product or Path(sys.executable)!=product/'.venv/bin/python':
            require(input('Trust this release and continue local preparation? [yes/no] ').strip()=='yes','SOURCE_TRUST_REQUIRED')
        source=SOURCE
        if not (source/'release-manifest.json').exists():
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
        prepare_copy(source,product)
        python=prepare_venv(product)
        # pip is repeatable package preparation; service install is never repeated
        # merely because a journal says incomplete. No global environment changes.
        probe="import importlib.metadata as m,pathlib,sys; from mcp import Client; import pydantic,gpt_agent_bridge; assert pathlib.Path(gpt_agent_bridge.__file__).resolve()==pathlib.Path(sys.argv[1])/'src/gpt_agent_bridge/__init__.py'; "+";".join("assert m.version(%r)==%r" % tuple(line.split('==')) for line in read(product/'requirements.txt',False).decode().splitlines() if line and not line.startswith('#'))
        ready=subprocess.run([str(python),'-I','-c',probe,str(product)],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL).returncode==0
        if not ready:command([python,'-m','pip','install','-e',product])
        if Path(sys.executable)!=python:
            os.execv(python,[str(python),str(product/'scripts/prepare-bridge.py'),'prepare', '--existing-extension',str(args.existing_extension)] if args.existing_extension else [str(python),str(product/'scripts/prepare-bridge.py'),'prepare'])
        pins=json.loads(read(product/'scripts/release-assets.json',False));arch=platform.machine();require(arch in pins,'ARCHITECTURE_NOT_SUPPORTED')
        herdr=select_herdr()
        bundle=download(pins[arch]['tunnel'],state/'tunnel-runtime-0.0.16.zip')
        saved=notification_config(config_path)
        if saved is None or saved.get('version')!=3:
            require(input('Allow this installed extension to read registered project refs/canonical roots and completion metadata (including future authorized registrations)? No report text or task authority; each Chat still requires explicit bind/enable. [yes/no] ').strip()=='yes','REGISTRY_METADATA_AUTHORIZATION_REQUIRED')
        extension=prepare_extension(product,state,config_path,args.existing_extension,registry_discovery=True)
        extension_handoff(extension)
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
        print('Create/select your private Bridge MCP plugin using Tunnel in https://chatgpt.com/plugins . Keep this terminal open. Provider login, fees and official permission prompts are your decisions.')
        print('Four unchanged, distinctly named Skill attachments and LICENSE: '+str(creator_material(product,state)))
        print('In ordinary Web Chat select @Plugin Creator, attach these files and choose your existing Bridge App. Review that four native Skills are installed, not merely reference attachments. See the exact brief in docs/GETTING-STARTED.md.')
        app_id=getpass.getpass('If the official host provides your native own-App ID, enter it locally for a file bundle; otherwise press Enter and use Creator App selection: ').strip()
        if app_id:print('Private native plugin bundle: '+str(prepare_plugin(product,state,app_id)))
        print('Install/import this bundle only if ordinary ChatGPT Web exposes the supported native plugin path; verify all four Skills there. Work-only availability does not pass this check.')
        print('Unchanged Web Principal Core: '+str(product/'templates/WEB-PRINCIPAL-CORE.md'))
        print('Software preparation is complete; no repository or running Herdr session/Agent is required. You may close this terminal.')
        print('Later, in ordinary Web use the project-onboarding Skill to connect an authorized existing Git repository. Review/save the tool-provided Host Binding with Core and your existing instructions. Fresh continuity is separate and optional.')
        print('Then select that registered project and the exact destination Chat in the extension and explicitly bind/enable BEFORE delegation. No local registration or sync command is needed. Daily use needs no prepare command; start your Agent in Herdr yourself, before or after opening Web.')
        return


if __name__=='__main__':
    try:main()
    except (Refusal,Exception) as e:
        code=str(e) if isinstance(e,Refusal) else 'PREPARATION_STOPPED_INSPECT_BEFORE_RETRY'
        print(code+' — completed objects retained. Re-enter the same release/path; unknown or changed objects are not overwritten.',file=sys.stderr)
        raise SystemExit(1)
