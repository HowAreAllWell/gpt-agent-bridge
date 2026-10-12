"""Review counterexamples: real timeout after cancellation and actual SDK extra fields.

Independent setup, without importing the R1 author's test fixtures or server.
"""
import asyncio
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch

from gpt_agent_bridge import file_observation as fo
from gpt_agent_bridge import search_observation as so
from gpt_agent_bridge.evidence_target import EvidenceTarget
from gpt_agent_bridge.workspace_context import WorkspaceContext, canonical_git_worktree


class ReviewCounterexamples(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        subprocess.run(['git','-c','core.hooksPath=/dev/null','init',str(self.root)],check=True,capture_output=True)
        root,identity=canonical_git_worktree(self.root)
        context=WorkspaceContext('p',root,identity,str(root))
        self.target=EvidenceTarget(context,context,None)
        self.resolve=Mock(return_value=self.target)
        self.events=[]
        events=self.events
        class Gate:
            async def acquire(self,mode): events.append('acquire'); return self
            async def release(self): events.append('release')
        self.gate=Mock(return_value=Gate())

    async def test_cancel_then_real_search_timeout_reaps_before_release(self):
        ready=threading.Event(); children=[]; actual=subprocess.Popen
        def sleeper(*args,**kwargs):
            child=actual([sys.executable,'-c','import time; time.sleep(30)'],**kwargs)
            children.append(child); ready.set(); return child
        service=so.UntrackedSearch(self.resolve,self.gate)
        with patch.object(so.fixed_git.subprocess,'Popen',side_effect=sleeper),patch.object(so,'GREP_SECONDS',.25):
            task=asyncio.create_task(service.search('p','needle'))
            try:
                self.assertTrue(await asyncio.to_thread(ready.wait,2))
                task.cancel('original caller cancellation')
                await asyncio.sleep(.02)
                self.assertNotIn('release',self.events)
                with self.assertRaises(asyncio.CancelledError) as caught:
                    await task
                self.assertTrue(all(c.poll() is not None for c in children))
                self.assertEqual(self.events,['acquire','release'])
            finally:
                # Test cleanup only; production is required to have reaped before assertion.
                for child in children:
                    if child.poll() is None: child.kill(); child.wait()
                if not task.done(): task.cancel(); await asyncio.gather(task,return_exceptions=True)

    async def test_repeated_cancel_preserves_first_after_success_or_error(self):
        for outcome in ('success','timeout','io_error'):
            with self.subTest(outcome=outcome):
                ready=threading.Event(); finish=threading.Event(); self.events.clear()
                def worker(*args):
                    ready.set(); finish.wait(2)
                    self.events.append('worker_finished')
                    if outcome=='timeout': raise fo.ObservationError('SearchTimedOut','late timeout')
                    if outcome=='io_error': raise OSError('late read failure')
                    return {'ok':True}
                with patch.object(fo,'_list_entries',side_effect=worker):
                    task=asyncio.create_task(fo.FileObservation(self.resolve,self.gate).list_entries('p'))
                    self.assertTrue(await asyncio.to_thread(ready.wait,2))
                    task.cancel('first'); await asyncio.sleep(.01)
                    task.cancel('second'); await asyncio.sleep(.01)
                    self.assertNotIn('release',self.events)
                    finish.set()
                    with self.assertRaises(asyncio.CancelledError) as caught: await task
                self.assertEqual(self.events,['acquire','worker_finished','release'])

    async def test_original_exception_object_survives_join_failure(self):
        # Python 3.10 Task boundaries may drop cancel(msg) arguments. Inject at
        # the exact shield boundary to verify object identity without that ABI.
        original=asyncio.CancelledError('original instance')
        real_shield=asyncio.shield
        first=True
        def interrupted(task):
            nonlocal first
            if first:
                first=False
                raise original
            return real_shield(task)
        def failed(*args): raise fo.ObservationError('SearchTimedOut','late timeout')
        service=fo.FileObservation(self.resolve,self.gate)
        with patch.object(fo.asyncio,'shield',side_effect=interrupted):
            with self.assertRaises(asyncio.CancelledError) as caught:
                await service._observe('p',None,failed)
        self.assertIs(caught.exception,original)
        self.assertEqual(self.events,['acquire','release'])

    async def test_schema_and_real_call_reject_unknown_fields_without_observation(self):
        from mcp.server import MCPServer
        from mcp.server.mcpserver.exceptions import ToolError
        mcp=MCPServer('r2-synthetic-wire')
        fo.register_file_observation(mcp,self.resolve,self.gate)
        descriptors={t.name:t for t in await mcp.list_tools()}
        # Test runtime before schema: R1 actually lists root here despite the typo.
        for name,args in [('list_entries',{'project_ref':'p','path_prefix':'missing'}),
                          ('inspect_file',{'project_ref':'p','path':'known','path_prefix':'missing'})]:
            with self.subTest(name=name):
                with self.assertRaises(ToolError): await mcp.call_tool(name,args)
                self.assertIs(descriptors[name].input_schema.get('additionalProperties'),False)
        self.resolve.assert_not_called(); self.gate.assert_not_called()
        self.assertEqual(self.events,[])
        # Valid calls retain original signatures and work normally.
        (self.root/'known').write_bytes(b'\0binary')
        for name,args in [('list_entries',{'project_ref':'p'}),('inspect_file',{'project_ref':'p','path':'known'})]:
            response=await mcp.call_tool(name,args)
            body=json.loads(response.content[0].text)
            self.assertTrue(body['ok'],body)
        self.assertEqual(self.events,['acquire','release','acquire','release'])
