"""Fixed-query effect boundaries and MCP presentation; all effects in fixtures."""
import asyncio
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from mcp.types import CallToolResult, TextContent, CallToolRequestParams
import tests.test_project_continuity as fixtures
import fixed_git
import server
from tool_presentation import compact_result


class SafeGitTests(unittest.IsolatedAsyncioTestCase):
    setUp = fixtures.ProjectContinuityTests.setUp
    _write_manifest = fixtures.ProjectContinuityTests._write_manifest

    def git(self, *args):
        return subprocess.run(['git',*args],cwd=self.root,capture_output=True,check=True)

    def filtered(self, kind='clean'):
        (self.root/'f.txt').write_text('original\n')
        self.git('add','f.txt')
        self.git('commit','-m','fixture')
        (self.root/'.gitattributes').write_text('f.txt filter=touchtest\n')
        self.marker=Path(self._temp.name)/'filter-ran'
        self.git('config','filter.touchtest.'+kind,'touch '+str(self.marker)+'; cat')
        (self.root/'f.txt').write_text('changed\n')

    async def test_local_clean_filter_counterexample_and_fixed_queries(self):
        self.filtered()
        self.git('-c','core.fsmonitor=false','diff','--no-ext-diff','--no-textconv','--numstat')
        self.assertTrue(self.marker.exists())
        self.marker.unlink()
        before=(self.root/'.git/index').read_bytes()
        for args in [('status','--porcelain=v1'),('diff','--numstat'),('ls-files','-m'),('grep','-F','changed')]:
            rc,out,err=fixed_git.observe(self.root,args)
            self.assertEqual(rc,fixed_git.UNSUPPORTED,(args,out,err))
            self.assertIn(b'clean/process',err)
            self.assertFalse(self.marker.exists())
        result=await server.mcp.call_tool('read',{'project_ref':'project','path':'f.txt'})
        payload=result.structured_content
        self.assertTrue(payload['ok'],payload)
        self.assertEqual(payload['content'],'changed\n')
        self.assertEqual(payload['file_sha256'], hashlib.sha256(b'changed\n').hexdigest())
        self.assertNotIn('dirty',payload)
        self.assertNotIn('state_id',payload)
        self.assertNotIn('git_observation',payload)  # Read does not request Git status.
        search=await server.search('project','changed')
        self.assertEqual(search['error_type'],'GitObservationUnsupported')
        self.assertFalse(search['coverage']['complete'])
        context=await server.context('project')
        self.assertIsNone(context['git']['dirty'])
        boundary=server._workspace_boundary_snapshot(self.root)
        self.assertIsNone(boundary['dirty'])
        self.assertFalse(self.marker.exists())
        self.assertEqual((self.root/'.git/index').read_bytes(),before)

    async def test_process_filter_configuration_rejected_without_execution(self):
        self.filtered('process')
        rc,out,err=await fixed_git.observe_async(self.root,['status','--porcelain'])
        self.assertEqual(rc,fixed_git.UNSUPPORTED)
        self.assertFalse(self.marker.exists())

    async def test_fsmonitor_not_invoked_and_no_index_write(self):
        marker=Path(self._temp.name)/'fsmonitor-ran'
        hook=Path(self._temp.name)/'fsmonitor.sh'
        hook.write_text('#!/bin/sh\ntouch '+str(marker)+'\nexit 1\n')
        hook.chmod(0o700)
        self.git('config','core.fsmonitor',str(hook))
        (self.root/'README.md').write_text('dirty with monitor disabled\n')
        before=(self.root/'.git/index').read_bytes()
        rc,out,err=fixed_git.observe(self.root,['status','--porcelain=v1'])
        self.assertEqual(rc,0,err)
        self.assertIn(b'README.md',out)
        self.assertFalse(marker.exists())
        self.assertEqual((self.root/'.git/index').read_bytes(),before)

    async def test_stream_caps_timeout_and_bytes(self):
        deadline=time.monotonic()+1
        rc,out,err=fixed_git._capture(self.root,[sys.executable,'-c',
            'import os; os.write(1,bytes([0,255,10]))'],deadline,8,8,threading.Event())
        self.assertEqual((rc,out),(0,b'\0\xff\n'))
        for fd in (1,2):
            rc,out,err=fixed_git._capture(self.root,[sys.executable,'-c',
                'import os\nwhile True: os.write('+str(fd)+',b"x"*65536)'],
                time.monotonic()+1,1024,1024,threading.Event())
            self.assertEqual(rc,fixed_git.TOO_LARGE)
            self.assertLessEqual(len(out),1024)
            self.assertIn(b'coverage incomplete',err)
        rc,out,err=fixed_git._capture(self.root,[sys.executable,'-c','import time; time.sleep(10)'],
            time.monotonic()+.05,1024,1024,threading.Event())
        self.assertEqual(rc,-1)
        self.assertIn(b'Timeout',err)

    async def test_current_diff_and_search_report_capture_overflow(self):
        (self.root/'README.md').write_text('a'*2000+'\n')
        real=fixed_git.observe
        def tiny(root,args,timeout=5,**kw):
            return real(root,args,timeout,stdout_limit=64)
        with patch.object(fixed_git,'observe',side_effect=tiny):
            diff=await server.diff('project',view='patch')
            search=await server.search('project','a')
        self.assertFalse(diff['ok'],diff)
        self.assertFalse(search['ok'],search)
        self.assertFalse(diff['coverage']['complete'])
        self.assertFalse(search['coverage']['complete'])


class PresentationTests(unittest.IsolatedAsyncioTestCase):
    setUp = fixtures.ProjectContinuityTests.setUp

    async def test_unique_text_images_and_proven_duplicates(self):
        payload={'ok':True,'body':'body only in structure'}
        from mcp.types import ImageContent
        image=ImageContent(type='image',data='AA==',mime_type='image/png')
        result=CallToolResult(content=[
            TextContent(type='text',text=json.dumps(payload)),
            TextContent(type='text',text='UNIQUE explanation: uncertain execution'),
            image],structured_content=payload)
        converted=compact_result(result,'future_commit')
        self.assertEqual(converted.structured_content,payload)
        self.assertIn(image,converted.content)
        text=[b.text for b in converted.content if b.type=='text']
        self.assertIn('UNIQUE explanation: uncertain execution',text)
        self.assertFalse(any(t.startswith('{') for t in text))
        self.assertEqual(compact_result(converted,'future_commit'),converted)
        real = await server.mcp.call_tool('read',{'project_ref':'project','path':'README.md'})
        from unittest.mock import AsyncMock
        response = CallToolResult(content=[
            TextContent(type='text',text=json.dumps(real.structured_content)),
            TextContent(type='text',text='UNIQUE explanation: uncertain execution')],
            structured_content=real.structured_content)
        tool = server.mcp._tool_manager.get_tool('read')
        with patch.object(type(tool.fn_metadata),'call_fn_with_arg_validation',AsyncMock(return_value=response)):
            wire = (await server.mcp.call_tool('read',{})).model_dump_json(by_alias=True)
        self.assertEqual(wire.count('UNIQUE explanation: uncertain execution'),1)
        self.assertEqual(wire.count('Test Repo'),1)


    async def test_real_mcp_error_parameters(self):
        failed=await server.mcp._handle_call_tool(None,CallToolRequestParams(name='read',arguments={}))
        self.assertTrue(failed.is_error)
        self.assertIn('project_ref',failed.content[0].text)
        self.assertIsNone(failed.structured_content)
        bad=await server.mcp.call_tool('read',{'project_ref':'project','path':'missing','expected_sha256':'bad'})
        self.assertEqual(bad.structured_content['error_type'],'InvalidExpectedSHA256')

    async def test_attention_delivery_future_error_and_server_instructions(self):
        for payload,name,expected in [
            ({'ok': True, 'items': [{'index': 0, 'agent_ref': 'a', 'ok': False, 'outcome': 'delivery_unknown', 'work_ref': 'work-x', 'submission_evidence': {'mutation_possible': True}}], 'continuation': None}, 'delegate', 'Delivery unknown'),
            ({'ok':True,'granted':True,'project_ref':'project'},'claim_work_watch','grant consumed'),
            ({'ok': True, 'items': [{'index': 0, 'agent_ref': 'a', 'ok': True, 'outcome': 'submitted', 'work_ref': 'work-x'}], 'continuation': None}, 'delegate', '1 submitted'),
            ({'ok':False,'error_type':'CommitConflict','error':'unique'},'commit','CommitConflict')]:
            tool=server.mcp._tool_manager.get_tool('delegate' if name=='commit' else name)
            from unittest.mock import AsyncMock
            with patch.object(type(tool.fn_metadata),'call_fn_with_arg_validation',AsyncMock(return_value=server.widget_watcher.watch_tool_result(payload) if tool.name == 'delegate' else payload)):
                result=await server.mcp.call_tool('delegate' if name=='commit' else name,{})
            self.assertIn(expected,result.content[-1].text)
            self.assertEqual(result.structured_content,payload)
        self.assertLessEqual(len(server.mcp.instructions),512)
        self.assertIn('explicit project_ref',server.mcp.instructions)
        self.assertNotIn('default working scope',server.mcp.instructions)
        for workflow in ('Normal Principal', 'begin_decision', 'watch_decision',
                         'current_state_update', 'takeover', 'startup'):
            self.assertNotIn(workflow, server.mcp.instructions)


class BudgetTests(unittest.IsolatedAsyncioTestCase):
    setUp = fixtures.ProjectContinuityTests.setUp

    async def test_probe_and_status_reused_per_checkout_and_budgeted(self):
        import agent_placement
        project = server._workspace_context('project')
        candidates = [{'identity':{'cwd':str(self.root)}}]*4
        actual = fixed_git._capture
        with patch.object(fixed_git,'_capture',wraps=actual) as calls:
            rows = await agent_placement.observe_all(project,candidates)
        self.assertEqual(calls.call_count,2)  # One config probe + one status, not per Agent.
        self.assertTrue(all(row['status']=='observed' for row in rows))
        def delayed(*args):
            time.sleep(.04)
            return actual(*args)
        with patch.object(fixed_git,'_capture',side_effect=delayed) as calls, \
                patch.object(agent_placement,'TOTAL_SECONDS',.02):
            rows = await agent_placement.observe_all(project,candidates)
        self.assertTrue(all(row['status']=='deferred' for row in rows))
        self.assertEqual(calls.call_count,1)  # Probe consumed deadline; status not started.
