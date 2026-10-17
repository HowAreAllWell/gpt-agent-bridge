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
        self.root=self.base/'project';self.root.mkdir()
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
        from types import SimpleNamespace
        home=self.base/'owner';home.mkdir(mode=0o700)
        entries=[]
        def body(args,actual_home,state):
            self.assertEqual(actual_home,home)
            self.assertEqual(state,home/'.local/share/gpt-agent-bridge')
            entries.append(state)
            if len(entries)==1:
                # A second main opens the same lock independently; it must not
                # reach run_locked while the first entry still owns the scope.
                with self.assertRaises(BlockingIOError):prep.main()
        with patch.object(prep.sys,'argv',['prepare','prepare']), \
                patch.object(prep.pwd,'getpwuid',return_value=SimpleNamespace(pw_dir=str(home))), \
                patch.object(prep,'run_locked',side_effect=body), \
                patch.object(prep,'command',side_effect=AssertionError('no runtime actions')):
            prep.main()
            self.assertEqual(len(entries),1)
            prep.main()  # A third entry succeeds after the first closes its lock.
            self.assertEqual(len(entries),2)
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
