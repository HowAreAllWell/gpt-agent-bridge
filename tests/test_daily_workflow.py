"""User-owned host lifecycle: real Bridge entry/health/context, synthetic external effects."""
import asyncio
import contextlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from tests.test_preparation import prep,module,ROOT

class DailyPreparation(unittest.TestCase):
    def test_service_preparation_accepts_closed_herdr_without_session_or_agent_commands(self):
        from gpt_agent_bridge import server
        from tests.test_manual_agents import manual_backend
        from gpt_agent_bridge.workspace_context import WorkspaceRegistry,WorkspaceRegistryStore
        with tempfile.TemporaryDirectory() as tmp:
            home=Path(tmp);state=home/'state';state.mkdir();product=state/'product';(product/'scripts').mkdir(parents=True)
            (product/'release-manifest.json').write_text('{}')
            (product/'requirements.txt').write_text('')
            (product/'scripts/release-assets.json').write_bytes((ROOT/'scripts/release-assets.json').read_bytes())
            herdr=home/'fixture-herdr';herdr.write_text('explicit command substitute; never executed');herdr.chmod(0o700)
            credentials=home/'credentials';credentials.write_text('{}')
            backend,host=manual_backend(home);host['snapshot_error']=RuntimeError('synthetic host closed')
            installer=module('install-bridge-autostart.py');commands=[];health=[]
            class Client:
                def __init__(self,*a,**kw):pass
                async def __aenter__(self):return self
                async def __aexit__(self,*a):pass
                async def call_tool(self,name,args):
                    self_result=await server.bridge_health();health.append(self_result)
                    return SimpleNamespace(is_error=False,structured_content=self_result)
            registry=WorkspaceRegistry(home,raw='',store=WorkspaceRegistryStore(home/'registry.json'))
            config={'port':8765,'token':'synthetic-not-secret','herdr_bin':str(herdr)}
            bridge=SimpleNamespace(load_config=lambda:config,probe=installer.probe)
            tunnel=SimpleNamespace(CREDENTIALS=credentials,validate_credentials=lambda v:None,read_file=lambda *a:credentials.read_bytes())
            def load(name,*a):
                if name=='install-bridge-autostart.py':return bridge
                if name=='install-bridge-tunnel-autostart.py':return tunnel
                raise AssertionError('unexpected component '+name)
            def command(args,**kw):
                commands.append(list(map(str,args)))
                if str(args[0])==str(herdr):self.assertEqual(args[1:],['--version']);return 'herdr 0.9.0'
                self.assertEqual(args[:2],['sudo','python3']);return ''
            python=product/'.venv/bin/python'
            with contextlib.ExitStack() as stack:
                for target,name,value in [(prep,'SOURCE',product),(prep.sys,'executable',str(python)),(prep,'prepare_copy',lambda *a:None),(prep,'prepare_venv',lambda *a:python),(prep,'download',lambda *a:home/'synthetic-tunnel.zip'),(prep,'prepare_extension',lambda *a,**kw:{'path':'/synthetic/extension','extension_id':'a'*32}),(prep,'load_script',load),(prep,'creator_material',lambda *a:home/'attachments'),(prep,'command',command),(prep.subprocess,'run',lambda *a,**kw:SimpleNamespace(returncode=0)),(server,'HERDR',backend),(server,'_WORKSPACE_REGISTRY',registry)]:stack.enter_context(patch.object(target,name,value))
                stack.enter_context(patch.dict(os.environ,{'BRIDGE_HERDR_BIN':str(herdr)}))
                stack.enter_context(patch.dict(sys.modules,{'mcp':SimpleNamespace(Client=Client)}))
                stack.enter_context(patch('builtins.input',side_effect=lambda prompt: 'yes' if prompt.startswith('Allow this installed extension') else self.fail('unexpected input: '+prompt)))
                stack.enter_context(patch.object(prep.getpass,'getpass',return_value=''))
                stack.enter_context(contextlib.redirect_stdout(io.StringIO()))
                prep.run_locked(SimpleNamespace(action='prepare',existing_extension=None),home,state)
            self.assertEqual(registry.refs,());self.assertFalse((home/'registry.json').exists())
            self.assertTrue(health[0]['ok']);self.assertEqual(health[0]['herdr']['status'],'unavailable')
            self.assertEqual([c[3] for c in commands if c[0]=='sudo'],['bridge','tunnel-install','tunnel-start'])
            self.assertEqual(host['calls'],[('api','snapshot')])
            self.assertFalse(list(state.glob('agent-*.json')))

    def test_existing_cli_path_selection_does_not_launch_or_download(self):
        with tempfile.TemporaryDirectory() as tmp:
            executable=Path(tmp)/'fixture-host';executable.write_text('not executable code');executable.chmod(0o700)
            with patch.dict(os.environ,{'BRIDGE_HERDR_BIN':str(executable)}),patch.object(prep,'download',side_effect=AssertionError('no host downloads')),patch.object(prep,'command',return_value='herdr 0.9.0') as cmd:
                self.assertEqual(prep.select_herdr(),executable);cmd.assert_called_once_with([executable,'--version'])
            with patch.dict(os.environ,{'BRIDGE_HERDR_BIN':str(executable)}),patch.object(prep,'command',return_value='herdr 0.9.3'):
                with self.assertRaisesRegex(prep.Refusal,'COMPATIBILITY'):prep.select_herdr()

class DailyDiscovery(unittest.IsolatedAsyncioTestCase):
    async def test_web_first_or_agent_first_and_later_user_start_need_no_restart_or_preparation(self):
        from gpt_agent_bridge import server
        from gpt_agent_bridge.workspace_context import WorkspaceRegistry,WorkspaceRegistryStore
        from tests.test_manual_agents import manual_backend
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/'repo';root.mkdir();subprocess.run(['git','init','-q',str(root)],check=True)
            registry=WorkspaceRegistry(root,raw=json.dumps({'daily':str(root)}),store=WorkspaceRegistryStore(Path(tmp)/'registry.json'))
            backend,host=manual_backend(root);original_agent=host['agent']
            started=server.BRIDGE_STARTED_AT
            with patch.object(server,'_WORKSPACE_REGISTRY',registry),patch.dict(server._WORKSPACE_BACKENDS,{str(root):backend}),patch.object(server,'HERDR',backend),patch.dict(server._MANUAL_AGENT_CANDIDATES,{},clear=True):
                for web_first in [True,False]:
                    host['calls'].clear()
                    if web_first:
                        host['snapshot_error']=RuntimeError('synthetic session closed')
                        health=await server.bridge_health();before=await server.context(project_ref='daily',include_continuity=False)
                        self.assertTrue(health['ok']);self.assertEqual(health['herdr']['status'],'unavailable')
                        self.assertTrue(before['ok']);self.assertFalse(before['agents_complete']);self.assertIn('agents_error',before)
                        # User opens the host, but has not started an Agent yet.
                        host['snapshot_error']=None;host['agent']=None
                        empty=await server.context(project_ref='daily',include_continuity=False)
                        self.assertTrue(empty['agents_complete']);self.assertEqual(empty['agents'],[])
                    host['snapshot_error']=None;host['agent']=original_agent
                    ready=await server.context(project_ref='daily',include_continuity=False)
                    self.assertTrue(ready['ok']);self.assertTrue(ready['agents_complete']);self.assertEqual(len(ready['agents']),1)
                    self.assertTrue(ready['agents'][0]['handle']);self.assertEqual(ready['root'],str(root))
                    self.assertEqual(server.BRIDGE_STARTED_AT,started)
                    self.assertFalse(any(c[:2] in [('workspace','create'),('agent','start'),('agent','prompt')] for c in host['calls']))
