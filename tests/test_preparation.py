"""Preparation effects are confined to synthetic private directories and fake installers."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
def module(name):
    p=ROOT/'scripts'/name;s=importlib.util.spec_from_file_location(name,p);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m
prep=module('prepare-bridge.py');system=module('prepare-system.py')

class PreparationTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
        self.state=self.root/'state';self.state.mkdir(mode=0o700);self.config=self.root/'config/browser-notifications.json'
    def test_new_and_repeated_extension_keep_identity_secret_and_load_path(self):
        first=prep.prepare_extension(ROOT,self.state,self.config)
        token=prep.notification_config(self.config)['token'];before=self.config.read_bytes()
        second=prep.prepare_extension(ROOT,self.state,self.config)
        self.assertEqual(first,second);self.assertEqual(self.config.read_bytes(),before)
        self.assertEqual(prep.notification_config(self.config)['token'],token)
        self.assertEqual(os.stat(self.config).st_mode&0o777,0o600)
        self.assertNotIn(token,json.dumps(first));self.assertEqual(len(first['extension_id']),32)
        self.assertNotIn(token,(ROOT/'browser-extension/extension/connection.js').read_text())
    def test_interrupted_extension_resumes_same_pending_identity(self):
        original=prep.publish
        def stop(path,data,*args,**kw):
            if path.name=='automation.js':raise OSError('synthetic interruption')
            return original(path,data,*args,**kw)
        with patch.object(prep,'publish',side_effect=stop):
            with self.assertRaises(OSError):prep.prepare_extension(ROOT,self.state,self.config)
        token=prep.notification_config(self.config)['token']
        final=prep.prepare_extension(ROOT,self.state,self.config)
        self.assertEqual(prep.notification_config(self.config)['token'],token)
        self.assertEqual(len(final['files']),len(list((ROOT/'browser-extension/extension').iterdir())))
    def test_changed_file_never_overwritten_or_rotates_secret(self):
        r=prep.prepare_extension(ROOT,self.state,self.config);file=Path(r['path'])/'automation.js';file.write_text('user change')
        before=self.config.read_bytes()
        with self.assertRaises(prep.Refusal):prep.prepare_extension(ROOT,self.state,self.config)
        self.assertEqual(file.read_text(),'user change');self.assertEqual(before,self.config.read_bytes())
    def test_legacy_load_path_key_and_token_preserved_with_original_backup(self):
        old=self.root/'old';old.mkdir(mode=0o700)
        prep.publish(old/'manifest.json',b'{"manifest_version":3,"version":"0.3.4"}')
        prep.publish(old/'automation.js',b'legacy executable')
        prep.publish(self.config,prep.json_bytes({'project_ref':'gpt-agent-bridge','root':'/old-root','port':8765,'extension_id':'a'*32,'token':'t'*48}))
        r=prep.prepare_extension(ROOT,self.state,self.config,old)
        self.assertEqual(r['path'],str(old));self.assertEqual(r['extension_id'],'a'*32)
        self.assertNotIn('key',json.loads((old/'manifest.json').read_text()))
        self.assertEqual((self.state/'extension-before-migration/automation.js').read_bytes(),b'legacy executable')
        self.assertEqual(prep.prepare_extension(ROOT,self.state,self.config),r)
        self.assertIn('gpt-agent-bridge',(old/'connection.js').read_text())
    def test_project_add_is_idempotent_and_keeps_old_project_and_secret(self):
        prep.prepare_extension(ROOT,self.state,self.config);calls=[]
        roots=[]
        for name in ['one','two']:
            root=self.root/name;root.mkdir();prep.command(['git','init','-q',root]);roots.append(root)
        def call(name,args):
            calls.append((name,args));return {'ok':True,'project_ref':args['project_ref'],'canonical_root':args['path'],
              'persistence':{'durability':'directory_fsynced'},'project_instructions_snippet':'Binding '+args['project_ref']}
        a=prep.add_project(roots[0],self.config,self.state,call);b=prep.add_project(roots[1],self.config,self.state,call)
        before=self.config.read_bytes();self.assertEqual(prep.add_project(roots[0],self.config,self.state,call),a)
        self.assertEqual(self.config.read_bytes(),before);self.assertNotEqual(a[0],b[0])
        self.assertEqual(len(prep.notification_config(self.config)['projects']),2)
        self.assertTrue(all(name=='project_register' for name,_ in calls))
    def test_concurrent_config_change_is_retained_after_registration(self):
        prep.prepare_extension(ROOT,self.state,self.config);root=self.root/'project';root.mkdir();prep.command(['git','init','-q',root])
        changed=prep.notification_config(self.config);changed['projects']=[{'project_ref':'concurrent','root':'/other'}]
        def call(name,args):
            self.config.write_bytes(prep.json_bytes(changed))
            return {'ok':True,'project_ref':args['project_ref'],'canonical_root':args['path'], 'persistence':{'durability':'directory_fsynced'},'project_instructions_snippet':'synthetic'}
        with self.assertRaises(prep.Refusal):prep.add_project(root,self.config,self.state,call)
        self.assertEqual(prep.notification_config(self.config),changed)

    def test_unknown_registration_does_not_authorize_notification_or_retry(self):
        prep.prepare_extension(ROOT,self.state,self.config);root=self.root/'project';root.mkdir();prep.command(['git','init','-q',root]);before=self.config.read_bytes();calls=[]
        def fail(*args):calls.append(args);raise OSError('lost transport')
        with self.assertRaises(OSError):prep.add_project(root,self.config,self.state,fail)
        self.assertEqual(len(calls),1);self.assertEqual(self.config.read_bytes(),before)
    def test_plugin_complete_repeatable_own_app_without_source_secret(self):
        path=prep.prepare_plugin(ROOT,self.state,'connector_synthetic_own_app');before=path.read_bytes()
        self.assertEqual(prep.prepare_plugin(ROOT,self.state,'connector_synthetic_own_app').read_bytes(),before)
        import zipfile
        with zipfile.ZipFile(path) as z:
            self.assertEqual(len([n for n in z.namelist() if n.endswith('/SKILL.md')]),4)
            self.assertEqual(json.loads(z.read('.app.json'))['apps']['bridge']['id'],'connector_synthetic_own_app')
            self.assertIn('LICENSE',z.namelist());self.assertIn('plugin.json',z.namelist())
        with self.assertRaises(Exception):prep.prepare_plugin(ROOT,self.state,'connector_different')
    def test_secret_symlinks_and_unknown_existing_files_refused(self):
        target=self.root/'secret';prep.publish(target,b'original')
        link=self.root/'link';link.symlink_to(target)
        with self.assertRaises(OSError):prep.publish(link,b'changed')
        with self.assertRaises(prep.Refusal):prep.publish(target,b'changed')
        self.assertEqual(target.read_bytes(),b'original')
    def test_missing_read_never_creates_source_directories(self):
        absent=self.root/'missing'/'nested'/'file'
        with self.assertRaises(FileNotFoundError):prep.read(absent)
        self.assertFalse(absent.parent.exists())

    def test_download_digest_checked_before_executable_publication(self):
        class Response:
            url='https://release-assets.githubusercontent.com/synthetic'
            def __enter__(self):return self
            def __exit__(self,*a):pass
            def read(self,n):return b'wrong bytes'
        target=self.state/'asset'
        with patch.object(prep.urllib.request,'urlopen',return_value=Response()):
            with self.assertRaises(prep.Refusal):prep.download({'url':'https://github.com/example/release','sha256':'a'*64},target)
        self.assertFalse(target.exists())

class RecoveryTests(unittest.TestCase):
    def test_first_repeat_and_interrupted_service_preparation_observe_before_actions(self):
        state=None;calls=[]
        def observe():return dict(state) if state else None
        def install():
            nonlocal state
            calls.append('install');state={'active':'inactive','enabled':'disabled'}
        def enable():calls.append('enable');state['enabled']='enabled'
        def start():calls.append('start');state['active']='active'
        system.reconcile(observe,install,enable,start);self.assertEqual(calls,['install','enable','start'])
        system.reconcile(observe,install,enable,start);self.assertEqual(len(calls),3)
        state['active']='inactive';state['enabled']='disabled';calls.clear()
        def interrupted():enable();raise OSError('lost result after enable')
        with self.assertRaises(OSError):system.reconcile(observe,install,interrupted,start)
        system.reconcile(observe,install,enable,start);self.assertEqual(calls,['enable','start'])
    def test_failed_transition_unknown_or_other_installation_never_started(self):
        for state in [None,{'active':'failed','enabled':'enabled'},{'active':'activating','enabled':'enabled'}]:
            calls=[]
            with self.assertRaises(ValueError):system.reconcile(lambda:state,lambda:calls.append('install'),lambda:calls.append('enable'),lambda:calls.append('start'))
            self.assertNotIn('start',calls)

class HandoffTests(unittest.TestCase):
    def test_binding_check_is_scoped_recent_and_does_not_send_a_message(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);state=root/'state';state.mkdir(mode=0o700);config=root/'config.json'
            prep.publish(config,prep.json_bytes({'version':2,'projects':[{'project_ref':'alpha','root':'/a'}], 'port':8765,'extension_id':'a'*32,'token':'t'*48}))
            epoch='a'*32;calls=[]
            body={'epoch':epoch,'status':{'received_at':prep.time.time(),'extension_observation':{'enabled':True,'epoch':epoch,'route':'https://chatgpt.com/c/synthetic','binding':{'route':'https://chatgpt.com/c/synthetic','documentId':'doc'}}}}
            class Response:
                def __init__(self,url):self.url=url
                def __enter__(self):return self
                def __exit__(self,*a):pass
                def read(self,n):return json.dumps(body).encode()
            def request(req,**kw):calls.append(req);return Response(req.full_url)
            self.assertEqual(prep.binding_observation(config,'alpha',request),'recent_extension_binding_observed_not_delivery')
            self.assertEqual(calls[0].method if hasattr(calls[0],'method') else calls[0].get_method(),'GET')
            self.assertIn('project_ref=alpha',calls[0].full_url);self.assertNotIn('t'*48,calls[0].full_url)
            body['status']['received_at']-=200
            with self.assertRaises(prep.Refusal):prep.binding_observation(config,'alpha',request)
            body['status']['received_at']=prep.time.time();body['status']['extension_observation']['binding']['route']='different'
            with self.assertRaises(prep.Refusal):prep.binding_observation(config,'alpha',request)
    def test_creator_attachments_are_four_exact_skill_texts_and_license(self):
        with tempfile.TemporaryDirectory() as d:
            out=prep.creator_material(ROOT,Path(d));self.assertEqual(len(list(out.iterdir())),5)
            for name in ['project-onboarding','project-resume','handoff-preparation','team-deliberation']:
                self.assertEqual((out/(name+'.md')).read_bytes(),(ROOT/'skills'/name/'SKILL.md').read_bytes())
    def test_existing_agents_never_launch_or_require_codex(self):
        agent=module('prepare-agent.py')
        with patch.object(agent.shutil,'which',side_effect=AssertionError('must not detect/launch')):
            self.assertEqual(agent.prepare(prep,Path('/unused'),Path('/a'),'a','herdr',lambda *a:{'ok':True,'agents':[{'handle':'synthetic'}]}),'existing_agents_observed')
    def test_unknown_agent_creation_is_not_retried_on_resume(self):
        agent=module('prepare-agent.py')
        with tempfile.TemporaryDirectory() as d,patch.object(agent.shutil,'which',return_value='/synthetic/agent'):
            state=Path(d);prep.publish(state/'agent-p.json',b'{"stage":"workspace_creation_attempted"}')
            with patch.object(prep,'command',side_effect=AssertionError('must not create again')):
                result=agent.prepare(prep,state,Path('/a'),'p','herdr',lambda *a:{'ok':True,'agents':[]},lambda *a:'pi')
                self.assertEqual(result,'previous_attempt_observation_required')

class RegistrationReuseTests(unittest.TestCase):
    def test_registered_root_is_reused_without_asking_user_for_a_ref(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);state=root/'state';state.mkdir(mode=0o700);config=root/'config.json'
            prep.prepare_extension(ROOT,state,config);project=root/'project';project.mkdir();prep.command(['git','init','-q',project]);calls=[]
            def call(name,args):
                calls.append(args)
                return {'ok':True,'project_ref':args['project_ref'],'canonical_root':args['path'], 'persistence':{'durability':'directory_fsynced'},'project_instructions_snippet':'Binding existing'}
            ref,_=prep.add_project(project,config,state,call,{'my-existing-project':{'canonical_root':str(project)}})
            self.assertEqual(ref,'my-existing-project');self.assertEqual(calls[0]['project_ref'],ref)
