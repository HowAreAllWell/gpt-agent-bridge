"""Actual registered surface has no generic executor or alias; preserved observations stay callable."""
import ast
import json
from pathlib import Path
import unittest
from unittest.mock import patch
from mcp.types import CallToolRequestParams
from mcp.server.mcpserver.exceptions import ToolError
from tests import test_file_observation as fixtures
from gpt_agent_bridge import server

TOOLS={'context','delegate','agent_terminal_read','read','search','diff',
       'bridge_overview','bridge_health','project_register','project_initialize','current_state_update',
       'list_entries','inspect_file','commit_prepare', 'project_text_edit','commit','work_report','prepare_file_attachment'}

class RunRetirementTests(unittest.IsolatedAsyncioTestCase):
    setUp = fixtures.FileObservationTests.setUp
    git = fixtures.FileObservationTests.git

    async def test_run_and_aliases_unregistered_in_catalog_and_handlers(self):
        listed=await server.mcp.list_tools()
        handled=await server.mcp._handle_list_tools(None,None)
        self.assertEqual(handled.tools,listed)
        self.assertEqual({t.name for t in listed},TOOLS)
        for t in listed:
            self.assertFalse(t.input_schema['additionalProperties'])
            self.assertEqual(server.mcp._tool_manager.get_tool(t.name).fn_metadata.arg_model.model_config['extra'],'forbid')
            self.assertNotIn('argv',t.input_schema['properties'])
            self.assertNotIn('command',t.input_schema['properties'])
            self.assertNotIn('script',t.input_schema['properties'])
        for name in ['run','workspace_exec','execute','shell','command','view_image','watch_works']:
            with self.subTest(name=name),patch.object(server,'_resolve_evidence_target',side_effect=AssertionError('no lookup')):
                args={'project_ref':'p','argv':['must-not-execute']}
                with self.assertRaises(ToolError):
                    await server.mcp.call_tool(name,args)
                result=await server.mcp._handle_call_tool(None,CallToolRequestParams(name=name,arguments=args))
                wire=json.loads(result.model_dump_json(by_alias=True))
                self.assertTrue(wire['isError'])
                self.assertIn('Unknown tool',wire['content'][0]['text'])
                self.assertIsNone(wire['structuredContent'])
        self.assertFalse(hasattr(server,'run'))
        self.assertFalse(hasattr(server, 'watch_works'))
        root=Path(server.__file__).parent
        self.assertFalse((root/'native_execution.py').exists())
        code=ast.parse((root/'server.py').read_text())
        self.assertFalse(any(isinstance(n,ast.Import) and any(a.name=='native_execution' for a in n.names) for n in ast.walk(code)))

    async def test_per_work_wait_implementation_and_aliases_are_removed(self):
        for name in ('await_work', '_work_settled_response', '_notify_work_waiters',
                     '_log_await_segment', '_WORK_PROVES_BY_SIGNAL'):
            self.assertFalse(hasattr(server, name), name)
        for name in ('await', 'await_work', 'watch_work', 'claim_work_followup'):
            with self.subTest(name=name):
                with self.assertRaises(ToolError):
                    await server.mcp.call_tool(name, {'project_ref': 'p', 'work_ref': 'work-x'})
                result = await server.mcp._handle_call_tool(None, CallToolRequestParams(
                    name=name, arguments={'project_ref': 'p', 'work_ref': 'work-x'}))
                self.assertTrue(result.is_error)
                self.assertIsNone(result.structured_content)

    async def test_observation_and_checkpoint_remain_direct(self):
        (self.root/'rule.md').write_text('fixture rule')
        (self.root/'memory.md').write_text('fixture memory')
        (self.root/'.principal').mkdir()
        (self.root/'.principal/project.json').write_text(json.dumps({
            'rules':['rule.md'],'current_state':'state.md','memory':'memory.md'}))
        result=await server.mcp.call_tool('current_state_update',{'project_ref':'p','expected_revision':'missing','content':'retained body'})
        self.assertTrue(result.structured_content['ok'],result)
        read=await server.mcp.call_tool('read',{'project_ref':'p','path':'state.md'})
        self.assertEqual(json.loads(read.model_dump_json(by_alias=True))['structuredContent']['content'],'retained body')
        self.assertEqual(read.model_dump_json().count('retained body'),1)
        for name,args in [('list_entries',{'path':'.'}),('inspect_file',{'path':'state.md'}),
                          ('search',{'query':'retained','include_untracked':True}),('diff',{})]:
            result=await server.mcp.call_tool(name,{'project_ref':'p',**args})
            self.assertTrue(result.structured_content['ok'],(name,result))
