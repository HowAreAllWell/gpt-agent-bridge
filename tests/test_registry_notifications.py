"""Skill-owned registration -> live notification catalog; synthetic roots only.

Set BRIDGE_REGISTRY_FIXTURE_OUTPUT to an owner-private file to pass actual feed
responses to browser-extension/tests/registry-handoff.test.js, without sockets.
"""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch, AsyncMock
from starlette.applications import Starlette
from tests.test_preparation import prep, ROOT
from gpt_agent_bridge import server
from gpt_agent_bridge.browser_notifications import BrowserNotifications
from gpt_agent_bridge.workspace_context import WorkspaceRegistry, WorkspaceRegistryStore

class RegistryNotifications(unittest.IsolatedAsyncioTestCase):
    async def test_live_skill_registration_catalog_and_scoped_feed_without_local_list_or_restart(self):
        with tempfile.TemporaryDirectory() as tmp:
            base=Path(tmp);state=base/'state';state.mkdir(mode=0o700)
            config=base/'config.json';prep.prepare_extension(ROOT,state,config)
            self.assertIs(server._BROWSER_NOTIFICATIONS.registered_projects,server._browser_notification_projects)
            original=config.read_bytes();self.assertNotIn('projects',json.loads(original))
            registry=WorkspaceRegistry(base,raw='',store=WorkspaceRegistryStore(base/'registry.json'))
            feed=BrowserNotifications(prep.notification_config(config),server._browser_notification_projects)
            feed.config_path=config;works=[]
            async def read(w):return {'ok':True,'file_sha256':'b'*64}
            app=Starlette(routes=feed.routes(lambda ref,root:[w for w in works if (w['project_ref'],w['workspace_root'])==(ref,root)],read,lambda ref:str(registry.resolve(ref).root)))
            async def request(path='projects',query=''):
                scope={'type':'http','method':'GET','path':'/browser-notifications/v1/'+path,'query_string':query.encode(),'headers':[(b'host',b'127.0.0.1:8765'),(b'authorization',('Bearer '+feed.config['token']).encode())],'client':('127.0.0.1',1),'server':('127.0.0.1',8765),'scheme':'http'}
                out=[]
                async def receive():return {'type':'http.request','body':b'','more_body':False}
                async def send(m):out.append(m)
                await app(scope,receive,send)
                return out[0]['status'],json.loads(b''.join(m.get('body',b'') for m in out))
            started=server.BRIDGE_STARTED_AT
            with patch.object(server,'_WORKSPACE_REGISTRY',registry),patch.object(server,'_deployment_snapshot',return_value={}),patch.object(server,'_discover_project_candidates',AsyncMock(return_value={'ok':False,'error_type':'SyntheticHostClosed'})),patch.object(registry.store,'save',wraps=registry.store.save) as save:
                empty=(await request())[1];self.assertEqual(empty,{'projects':[]})
                for ref in ['alpha','beta']:
                    root=base/ref;root.mkdir();subprocess.run(['git','init','-q',str(root)],check=True)
                    result=await server.project_register(ref,str(root))
                    self.assertTrue(result['ok']);self.assertEqual(result['task_authority'],'not_granted')
                    self.assertIn(ref,result['project_instructions_snippet']);self.assertFalse((root/'.principal').exists())
                    # Follow the unchanged Skill: register only if needed. A
                    # repeat connection observes confirmed mapping via tools;
                    # deliberately re-calling the mutation tool is not that flow.
                    count=save.call_count;stored=registry.store.path.read_bytes()
                    again=await server.bridge_overview(ref)
                    self.assertEqual(again['project_state']['registration']['relation'],'matched')
                    context=await server.context(ref,include_continuity=False)
                    self.assertEqual(context['root'],str(root));self.assertFalse(context['agents_complete'])
                    self.assertEqual(save.call_count,count);self.assertEqual(registry.store.path.read_bytes(),stored)
                catalog=(await request())[1];self.assertEqual(len(catalog['projects']),2)
                self.assertEqual(server.BRIDGE_STARTED_AT,started);self.assertEqual(config.read_bytes(),original)
                before={};after={}
                for i,p in enumerate(catalog['projects'],1):
                    q='project_ref='+p['project_ref']+'&scope_id='+p['scope_id']
                    before[p['project_ref']]=(await request('events',q))[1]
                    w={'work_ref':'work-'+str(i).zfill(16),'project_ref':p['project_ref'],'workspace_root':p['root'],'result_class':'result_ready','report_status':'readable','settled_at':1}
                    works.append(w);feed.publish(w)
                    after[p['project_ref']]=(await request('events',q))[1]
                    self.assertEqual([e['project_ref'] for e in after[p['project_ref']]['events']],[p['project_ref']])
                self.assertIsNotNone(feed.begin_batch('beta',catalog['projects'][1]['root'],2))
                self.assertIsNone(feed.begin_batch('unregistered',str(base),1))
                self.assertEqual((await request('events','project_ref=alpha&scope_id='+catalog['projects'][1]['scope_id']))[0],410)
                later={}
                for i,p in enumerate(catalog['projects'],3):
                    q='project_ref='+p['project_ref']+'&scope_id='+p['scope_id']
                    w={'work_ref':'work-'+str(i).zfill(16),'project_ref':p['project_ref'],'workspace_root':p['root'],'result_class':'result_ready','report_status':'readable','settled_at':2}
                    works.append(w);feed.publish(w);later[p['project_ref']]=(await request('events',q))[1]
                fixture={'empty':empty,'catalog':catalog,'before':before,'after':after,'later':later}
                output=os.environ.get('BRIDGE_REGISTRY_FIXTURE_OUTPUT')
                if output:Path(output).write_text(json.dumps(fixture))
                # Lost canonical Git identity affects only that row, not beta.
                (base/'alpha/.git').rename(base/'alpha/lost-git')
                self.assertEqual([p['project_ref'] for p in (await request())[1]['projects']],['beta'])
                self.assertEqual(config.read_bytes(),original)

    async def test_existing_configs_are_pinned_until_explicit_metadata_upgrade_and_keep_identity(self):
        for legacy in [True,False]:
            with tempfile.TemporaryDirectory() as tmp:
                base=Path(tmp);state=base/'state';state.mkdir(mode=0o700);old=base/'original';old.mkdir(mode=0o700)
                prep.publish(old/'manifest.json',b'{"manifest_version":3,"version":"0.3.4"}')
                config=base/'config.json';p={'project_ref':'alpha','root':'/synthetic/original'}
                value={'port':8765,'token':'t'*48,'extension_id':'a'*32,**(p if legacy else {'version':2,'projects':[p]})}
                prep.publish(config,prep.json_bytes(value));original=config.read_bytes()
                receipt=prep.prepare_extension(ROOT,state,config,old)
                self.assertEqual(config.read_bytes(),original)
                feed=BrowserNotifications(value,lambda:[{'project_ref':'beta','root':'/synthetic/beta'}])
                self.assertEqual(feed.projects(),[p])
                receipt=prep.prepare_extension(ROOT,state,config,registry_discovery=True)
                upgraded=prep.notification_config(config)
                self.assertEqual(upgraded,{'version':3,'discovery':'registered','port':8765,'token':'t'*48,'extension_id':'a'*32})
                self.assertEqual((state/'notification-config-before-registry.json').read_bytes(),original)
                if legacy:self.assertEqual(receipt['legacy_identity']['root'],p['root'])
                saved=config.read_bytes();self.assertEqual(prep.prepare_extension(ROOT,state,config,registry_discovery=True),receipt)
                self.assertEqual(config.read_bytes(),saved)

    def test_registry_config_is_strict_and_has_no_default_disk_discovery(self):
        value={'version':3,'discovery':'registered','port':8765,'token':'t'*48,'extension_id':'a'*32}
        self.assertEqual(BrowserNotifications(BrowserNotifications.validate_config(value)).projects(),[])
        for extra in [{'projects':[]},{'root':'/x'},{'discovery':'all-disk'}]:
            with self.assertRaises(ValueError):BrowserNotifications.validate_config({**value,**extra})
