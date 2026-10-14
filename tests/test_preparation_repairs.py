"""Review regressions: real private files; command/account/service boundaries substituted."""
import contextlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
from tests.test_preparation import prep,module,ROOT

class Repairs(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.base=Path(self.tmp.name);self.state=self.base/'state';self.state.mkdir(mode=0o700)
        self.root=self.base/'project';self.root.mkdir();subprocess.run(['git','init','-q',str(self.root)],check=True)
        self.ref='synthetic';self.calls=[];self.agents=[]
    def context(self,*args):
        return {'ok':True,'project_ref':self.ref,'root':str(self.root),'agents_complete':True,'agents':self.agents}
    def test_alias_change_cannot_replace_authorized_canonical_root(self):
        alias=self.base/'alias';alias.symlink_to(self.root);canonical=alias.resolve()
        other=self.base/'other';other.mkdir();subprocess.run(['git','init','-q',str(other)],check=True)
        alias.unlink();alias.symlink_to(other)
        with self.assertRaisesRegex(prep.Refusal,'ROOT_CHANGED'):
            prep.verify_project(alias,self.ref,self.context)
        self.assertEqual(prep.verify_project(canonical,self.ref,self.context)['root'],str(canonical))
    def test_identity_changed_after_handoff_refuses(self):
        with self.assertRaisesRegex(prep.Refusal,'IDENTITY_CHANGED'):
            prep.verify_project(self.root,self.ref,lambda *a:{**self.context(),'root':'/different'})
    def test_owned_venv_directory_interruption_is_completed_without_removal(self):
        product=self.state/'product';product.mkdir(mode=0o700)
        def interrupted(args,**kw):
            (product/'.venv').mkdir(mode=0o700);raise OSError('interrupted')
        with patch.object(prep,'command',side_effect=interrupted),self.assertRaises(OSError):prep.prepare_venv(product)
        marker=(product/'venv-owner.json').read_bytes()
        python=prep.prepare_venv(product);self.assertTrue(python.is_file())
        self.assertEqual((product/'venv-owner.json').read_bytes(),marker)
        with patch.object(prep,'command',side_effect=AssertionError('no repeat')):self.assertEqual(prep.prepare_venv(product),python)
    def test_unknown_empty_venv_not_deleted_or_adopted(self):
        product=self.state/'product';product.mkdir();(product/'.venv').mkdir()
        with self.assertRaisesRegex(prep.Refusal,'UNOWNED_PARTIAL'):prep.prepare_venv(product)
        self.assertTrue((product/'.venv').is_dir());self.assertFalse((product/'venv-owner.json').exists())
    def test_complete_binding_selection_preserves_core_and_old_bindings(self):
        for ref in ['alpha','beta']:prep.publish(self.state/('Binding-'+ref+'.txt'),('Binding '+ref).encode())
        config={'projects':[{'project_ref':r,'root':'/'+r} for r in ['alpha','beta']]}
        path=prep.assemble_instructions(ROOT,self.state,config,['beta','alpha'])
        self.assertEqual(path.read_bytes(),(ROOT/'templates/WEB-PRINCIPAL-CORE.md').read_bytes()+b'\n\nBinding beta\nBinding alpha')
        self.assertEqual(prep.assemble_instructions(ROOT,self.state,config,['beta','alpha']),path)
        self.assertNotEqual(prep.assemble_instructions(ROOT,self.state,config,['alpha']),path)
    def test_private_explicit_credential_replacement_does_not_control_service(self):
        from types import SimpleNamespace
        credentials=self.state/'credentials';old={'tunnel_id':'synthetic','runtime_api_key':'old'}
        prep.publish(credentials,prep.json_bytes(old))
        fake=SimpleNamespace(CREDENTIALS=credentials,record=lambda:{'plan':{}},configured_owner=lambda _:None,validate_credentials=lambda v:v)
        secrets=iter(['new-tunnel','new-key'])
        with patch.object(prep,'load_script',return_value=fake),patch.object(prep,'command',side_effect=AssertionError('no services')):
            prep.replace_tunnel_credentials(ROOT,lambda _:'yes',lambda _:next(secrets))
        self.assertEqual(json.loads(credentials.read_text())['runtime_api_key'],'new-key');self.assertEqual(credentials.stat().st_mode&0o777,0o600)
        secrets=iter(['new-tunnel','sk-admin-forbidden'])
        with patch.object(prep,'load_script',return_value=fake),self.assertRaisesRegex(prep.Refusal,'ADMIN_KEY_REFUSED'):
            prep.replace_tunnel_credentials(ROOT,lambda _:'yes',lambda _:next(secrets))
    def test_two_cooperating_preparers_cannot_enter_same_writer_scope(self):
        import fcntl
        path=self.state/'prepare.lock';fd=os.open(path,os.O_CREAT|os.O_RDWR,0o600)
        code="import os,fcntl,sys; f=os.open(sys.argv[1],os.O_RDWR); fcntl.flock(f,fcntl.LOCK_EX|fcntl.LOCK_NB)"
        try:
            fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
            result=subprocess.run([os.sys.executable,'-c',code,str(path)],capture_output=True)
            self.assertNotEqual(result.returncode,0);self.assertIn(b'BlockingIOError',result.stderr)
        finally:os.close(fd)
        self.assertEqual(subprocess.run([os.sys.executable,'-c',code,str(path)],capture_output=True).returncode,0)
    def test_noncooperating_late_editor_is_outside_lock_contract(self):
        path=self.state/'config';prep.publish(path,b'initial');replace=os.replace
        def editor(src,dst):
            if dst==path:path.write_bytes(b'noncooperating-editor')
            return replace(src,dst)
        with patch.object(prep.os,'replace',side_effect=editor):prep.publish(path,b'new',previous=b'initial')
        self.assertEqual(path.read_bytes(),b'new')
    def test_lost_registration_ack_is_recovered_by_actual_readonly_context(self):
        import asyncio
        with patch('pathlib.Path.home',return_value=self.state):
            from gpt_agent_bridge import server
            from gpt_agent_bridge.workspace_context import WorkspaceRegistry,WorkspaceRegistryStore
        registry=WorkspaceRegistry(self.root,raw='',store=WorkspaceRegistryStore(self.state/'registry.json'))
        config=self.state/'notifications.json';prep.prepare_extension(ROOT,self.state,config)
        writes=[];save=registry.store.save
        def counted(data):writes.append(data);return save(data)
        def real(name,args):
            if name=='context':return asyncio.run(server.context(**args))
            return asyncio.run(server.project_register(**args))
        def lost(name,args):result=real(name,args);self.assertTrue(result['ok']);raise OSError('reply lost after registration')
        with patch.object(server,'_WORKSPACE_REGISTRY',registry),patch.object(registry.store,'save',side_effect=counted):
            with self.assertRaises(OSError):prep.add_project(self.root,config,self.state,lost)
            records=registry.store.read_persisted_records()['records']
            # Discovery is unrelated to registration verification: context still
            # resolves the root even when no synthetic Herdr exists.
            from unittest.mock import AsyncMock
            with patch.object(server,'_project_agent_observation',AsyncMock(return_value={'agents':[],'agents_complete':False})):
                ref,binding=prep.add_project(self.root,config,self.state,real,records)
            self.assertEqual(len(writes),1);self.assertIn(ref,binding.read_text())
    def test_credential_activation_observes_stop_before_start_and_stops_on_unknown(self):
        from types import SimpleNamespace
        system=module('prepare-system.py');calls=[]
        for states in [['active','inactive','active'],['active','deactivating']]:
            iterator=iter(states)
            fake=SimpleNamespace(record=lambda:{},managed_properties=lambda:{'ActiveState':next(iterator)},lifecycle=lambda a:calls.append(a))
            with patch.object(system,'snapshot'),patch.object(system,'module',return_value=fake):
                if len(states)==3:
                    self.assertEqual(system.activate_credentials(ROOT,self.state)['active'],'active');self.assertEqual(calls,['stop','start'])
                else:
                    calls.clear()
                    with self.assertRaisesRegex(ValueError,'STOP_UNKNOWN'):system.activate_credentials(ROOT,self.state)
                    self.assertEqual(calls,['stop'])
    def test_owned_partial_venv_with_interpreter_but_missing_pip_recovers(self):
        product=self.state/'product';product.mkdir(mode=0o700);venv=product/'.venv'
        prep.publish(product/'venv-owner.json',prep.json_bytes({'path':str(venv),'owner':os.getuid(),'purpose':'bridge-preparation-venv-v1'}))
        subprocess.run([os.sys.executable,'-m','venv','--without-pip',str(venv)],check=True)
        python=prep.prepare_venv(product)
        self.assertEqual(subprocess.run([str(python),'-I','-c','import pip'],capture_output=True).returncode,0)
    def test_upgrade_preserves_legacy_root_scope_in_private_connection_and_receipt(self):
        import hashlib
        old=self.state/'original-extension';old.mkdir(mode=0o700)
        prep.publish(old/'manifest.json',b'{"manifest_version":3,"version":"0.3.4"}')
        config=self.state/'config.json';identity={'project_ref':'legacy','root':str(self.root)}
        prep.publish(config,prep.json_bytes({**identity,'port':8765,'token':'t'*48,'extension_id':'a'*32}))
        result=prep.prepare_extension(ROOT,self.state,config,old)
        expected={**identity,'scope_id':hashlib.sha256(('legacy\0'+str(self.root)).encode()).hexdigest()}
        self.assertEqual(result['legacy_identity'],expected)
        self.assertIn(json.dumps(expected),(old/'connection.js').read_text())
    def test_windows_embedded_entry_accepts_clean_checkout_and_forwards_actions(self):
        # Exact embedded program; no PowerShell/WSL or Windows execution claimed.
        script=(ROOT/'Start-Bridge.ps1').read_text();self.assertIn('"$release/scripts/prepare-bridge.py" $Action',script)
        code=script.split("$copy = @'\n",1)[1].split("\n'@",1)[0]
        checkout=self.base/'checkout';checkout.mkdir(mode=0o700)
        import shutil
        names=subprocess.check_output(['git','-C',str(ROOT),'ls-files','-z','--','.',':(exclude).principal',':(exclude).principal/**',':(exclude).app.json']).decode().split('\0')
        # Copy explicit candidate product paths, excluding an existing release
        # receipt so this exercises the actual clean checkout acquisition path.
        names=[n for n in names if n and n!='release-manifest.json']
        for name in names:
            dest=checkout/name;dest.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(ROOT/name,dest)
        subprocess.run(['git','init','-q',str(checkout)],check=True)
        subprocess.run(['git','add','--',*names],cwd=checkout,check=True)
        subprocess.run(['git','-c','user.name=Fixture','-c','user.email=fixture@invalid','commit','-qm','fixture'],cwd=checkout,check=True)
        home=self.state/'windows-home';home.mkdir(mode=0o700)
        with patch.object(prep.sys,'argv',['copy',str(checkout)]),patch('pathlib.Path.home',return_value=home):exec(compile(code,'Start-Bridge.ps1 embedded','exec'),{})
        manifest=prep.release_files(home/'.local/share/bridge-release');self.assertIn('scripts/prepare-system.py',manifest['files']);self.assertNotIn('scripts/prepare-provider.py',manifest['files'])
        with patch.object(prep.sys,'argv',['copy',str(checkout)]),patch('pathlib.Path.home',return_value=home):exec(compile(code,'Start-Bridge.ps1 embedded repeat','exec'),{})
