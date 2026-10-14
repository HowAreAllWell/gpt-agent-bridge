#!/usr/bin/env python3
"""Interactive, resumable local preparation. No Web automation or automatic Work.

Source trust/sudo, account credentials and destination consent belong to the
user. This program performs the mechanical steps and verifies them on re-entry.
"""
from __future__ import annotations
import argparse
import asyncio
import base64
import contextlib
import fcntl
import getpass
import hashlib
import importlib.util
import json
import logging
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
import time
import urllib.parse
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


def prepare_extension(source,state,config_path,existing=None):
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
        config={'version':2,'projects':[],'port':PORT,'token':secrets.token_urlsafe(48),'extension_id':extension_id(manifest)}
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
    return receipt


async def call_bridge(config,name,args):
    from mcp import Client
    logging.disable(logging.CRITICAL)
    # Suppress token-bearing library diagnostics; return only structured results.
    with open(os.devnull,'w') as quiet,contextlib.redirect_stdout(quiet),contextlib.redirect_stderr(quiet):
        async with Client(f"http://127.0.0.1:{config['port']}/mcp/{config['token']}",mode='legacy') as client:
            r=await client.call_tool(name,args)
            require(not r.is_error and isinstance(r.structured_content,dict),'MCP_RESULT_UNAVAILABLE')
            return r.structured_content


def add_project(root,config_path,state,call,registered=None):
    root=Path(root).resolve(strict=True)
    require(command(['git','-C',root,'rev-parse','--show-toplevel']).strip()==str(root),'SELECT_GIT_WORKTREE_ROOT')
    original=read(config_path)
    config=notification_config(config_path);require(config is not None,'PREPARE_SOFTWARE_FIRST')
    require(read(config_path)==original,'NOTIFICATION_CONFIG_CHANGED')
    rows=config.get('projects') if 'projects' in config else [{'project_ref':config['project_ref'],'root':config['root']}]
    existing=next((p for p in rows if p['root']==str(root)),None)
    matches=[ref for ref,row in (registered or {}).items() if row.get('canonical_root')==str(root)]
    require(len(matches)<=1,'AMBIGUOUS_REGISTERED_ROOT')
    ref=existing['project_ref'] if existing else matches[0] if matches else 'p-'+digest(str(root).encode())[:20]
    if ref in (registered or {}):
        require(registered[ref].get('canonical_root')==str(root),'REGISTERED_ROOT_CHANGED')
        # A persisted record plus fresh live resolution is an observation, not a
        # second registration write after a lost acknowledgement.
        verify_project(root,ref,call)
        snippet='# Project Binding\n\nConnected Bridge project refs:\n- `project_ref="'+ref+'"`\n'
    else:
        result=call('project_register',{'project_ref':ref,'path':str(root)})
        require(result.get('ok') and result.get('project_ref')==ref and result.get('canonical_root')==str(root),'PROJECT_REGISTRATION_NOT_CONFIRMED')
        require(result.get('persistence',{}).get('durability') in ('directory_fsynced','not_applicable'),'PROJECT_PERSISTENCE_UNCONFIRMED')
        snippet=result.get('project_instructions_snippet')
    if not existing:
        require(len(rows)<32,'PROJECT_CAPACITY_REACHED')
        rows=[*rows,{'project_ref':ref,'root':str(root)}]
    desired={k:config[k] for k in ('extension_id','token','port')};desired.update(version=2,projects=rows)
    publish(config_path,json_bytes(desired),previous=original)
    require(isinstance(snippet,str),'BINDING_SNIPPET_UNAVAILABLE')
    binding=state/('Binding-'+ref+'.txt')
    publish(binding,snippet.encode())
    return ref,binding


def verify_project(root,ref,call):
    # root is the already authorized canonical path, never re-resolve an alias
    # as a new authorization after the browser handoff.
    root=Path(root)
    require(root.is_absolute() and root.resolve(strict=True)==root,'PROJECT_ROOT_CHANGED')
    require(command(['git','-C',root,'rev-parse','--show-toplevel']).strip()==str(root),'PROJECT_ROOT_CHANGED')
    observation=call('context',{'project_ref':ref,'include_continuity':False})
    require(observation.get('ok') and observation.get('project_ref')==ref and observation.get('root')==str(root),'PROJECT_IDENTITY_CHANGED')
    return observation


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


def assemble_instructions(product,state,config,selected):
    rows={p['project_ref']:p for p in config['projects']}
    require(selected and len(set(selected))==len(selected) and set(selected)<=rows.keys(),'SELECT_AUTHORIZED_PROJECTS')
    core=read(product/'templates/WEB-PRINCIPAL-CORE.md',False)
    # Original Core and individual Binding bytes remain unchanged. Only their
    # chosen composition is generated; never read or overwrite Web instructions.
    for ref in selected:
        binding=state/('Binding-'+ref+'.txt')
        if not binding.exists():publish(binding,('# Project Binding\n\nConnected Bridge project refs:\n- `project_ref="'+ref+'"`\n').encode())
    text=core+b'\n\n'+b'\n'.join(read(state/('Binding-'+ref+'.txt')) for ref in selected)
    path=state/('Project-Instructions-'+digest(text)[:16]+'.txt')
    publish(path,text);return path


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


def binding_observation(config_path,ref,request=urllib.request.urlopen):
    config=notification_config(config_path)
    require(config is not None,'NOTIFICATION_CONFIG_UNAVAILABLE')
    project=next((p for p in config.get('projects',[]) if p['project_ref']==ref),None)
    require(project is not None,'NOTIFICATION_PROJECT_UNAVAILABLE')
    scope=digest((ref+'\0'+project['root']).encode())
    url='http://127.0.0.1:8765/browser-notifications/v1/events?'+urllib.parse.urlencode({'project_ref':ref,'scope_id':scope,'status':1})
    req=urllib.request.Request(url,headers={'Authorization':'Bearer '+config['token']})
    with request(req,timeout=10) as response:
        require(response.url==url,'NOTIFICATION_REDIRECT_REFUSED')
        data=json.loads(response.read(65537))
    status=data.get('status') or {};ob=status.get('extension_observation') or {};binding=ob.get('binding') or {}
    require(isinstance(status.get('received_at'),(int,float)) and 0<=time.time()-status['received_at']<=180,'BINDING_OBSERVATION_STALE')
    require(ob.get('enabled') is True and ob.get('epoch')==data.get('epoch') and binding.get('route')==ob.get('route') and binding.get('documentId'),'BINDING_NOT_CONFIRMED')
    return 'recent_extension_binding_observed_not_delivery'


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
    parser.add_argument('action',nargs='?',default='prepare',choices=['prepare','project','status','credentials'])
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
        extension=prepare_extension(product,state,config_path,args.existing_extension)
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
        print('Load unpacked extension in chrome://extensions from: '+extension['path']+' ; expected ID: '+extension['extension_id'])
        print('Create/select your private Bridge MCP plugin using Tunnel in https://chatgpt.com/plugins . Keep this terminal open. Provider login, fees and official permission prompts are your decisions.')
        print('Four unchanged, distinctly named Skill attachments and LICENSE: '+str(creator_material(product,state)))
        print('In ordinary Web Chat select @Plugin Creator, attach these files and choose your existing Bridge App. Review that four native Skills are installed, not merely reference attachments. See the exact brief in docs/GETTING-STARTED.md.')
        app_id=getpass.getpass('If the official host provides your native own-App ID, enter it locally for a file bundle; otherwise press Enter and use Creator App selection: ').strip()
        if app_id:print('Private native plugin bundle: '+str(prepare_plugin(product,state,app_id)))
        print('Install/import this bundle only if ordinary ChatGPT Web exposes the supported native plugin path; verify all four Skills there. Work-only availability does not pass this check.')
        print('Software is prepared. Select the first existing local Git project next (nothing will be delegated).')
    # On subsequent project entry, execute under the product venv without changing it.
    python=product/'.venv/bin/python'
    if Path(sys.executable)!=python:os.execv(python,[str(python),str(product/'scripts/prepare-bridge.py'),'project'])
    bridge=load_script('install-bridge-autostart.py',product);config=bridge.load_config()
    path=input('Existing local Git project absolute path (empty to stop before choosing): ').strip()
    if not path:return
    print('This registers a local root and allows its notification metadata to the one installed extension. It grants no task authority and chooses no Chat.')
    require(input('Authorize this local project? [yes/no] ').strip()=='yes','PROJECT_AUTHORIZATION_REQUIRED')
    call=lambda name,args:asyncio.run(call_bridge(config,name,args))
    from gpt_agent_bridge.workspace_context import WorkspaceRegistryStore, WORKSPACE_STORE_FILE_NAME
    registry=WorkspaceRegistryStore(home/'.local/state/gpt-agent-bridge'/WORKSPACE_STORE_FILE_NAME).read_persisted_records()
    require(registry.get('store')!='unreadable','REGISTRATION_STORE_UNREADABLE')
    canonical=Path(path).resolve(strict=True)
    ref,binding=add_project(canonical,config_path,state,call,registry.get('records') or {})
    config_rows=notification_config(config_path)
    rows=config_rows['projects']
    for i,row in enumerate(rows,1):print(str(i)+': '+row['root'])
    choice=input('Local projects for this Web Project instructions (numbers separated by spaces; Enter selects this project): ').strip()
    selected=[rows[int(i)-1]['project_ref'] for i in choice.split() if i.isdigit() and 1<=int(i)<=len(rows)] if choice else [ref]
    require(not choice or len(selected)==len(choice.split()),'INVALID_PROJECT_SELECTION')
    for selected_ref in selected:
        selected_root=next(row['root'] for row in rows if row['project_ref']==selected_ref)
        verify_project(Path(selected_root),selected_ref,call)
    combined=assemble_instructions(product,state,config_rows,selected)
    print('Review and save Core + Binding from: '+str(combined))
    print('Open the exact ordinary Chat destination, select '+ref+' in the extension, tick its authorization and enable. Bind BEFORE the first delegation. Another local project can share this Chat or choose a different Chat explicitly. Re-enter ./prepare project (Windows: .\\Start-Bridge.ps1 project) from your original directory to add it.')
    input('After explicitly enabling this project in the extension, press Enter to check its recent observation once (no test message): ')
    print(binding_observation(config_path,ref))
    verify_project(canonical,ref,call)
    print('Project association complete. Daily use needs no prepare command: open Herdr yourself, cd to this repository and start your chosen Agent. Web Chat can be opened before or after; fresh context discovers existing Agents. Bridge never creates or restores their environment.')
    print('In that Web Chat verify Bridge tools and the four native Skills, give a real authorized task. Continuity initialization through project-onboarding is optional and requires separate project authority. Do not delegate until binding is enabled. Read every page of each work_report after the short reminder; setup itself sends no Work or message.')


if __name__=='__main__':
    try:main()
    except (Refusal,Exception) as e:
        code=str(e) if isinstance(e,Refusal) else 'PREPARATION_STOPPED_INSPECT_BEFORE_RETRY'
        print(code+' — completed objects retained. Re-enter the same release/path; unknown or changed objects are not overwritten.',file=sys.stderr)
        raise SystemExit(1)
