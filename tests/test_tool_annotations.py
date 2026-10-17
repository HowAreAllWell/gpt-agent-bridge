"""Explicit behavioral catalog annotations; no calls to external tools or hosts."""
import ast
import json
import os
from pathlib import Path
import unittest
os.environ.setdefault('BRIDGE_PATH_TOKEN', 'test-token-abcdefghijklmnopqrstuvwxyz-012345')
from gpt_agent_bridge import server


class ToolAnnotationTests(unittest.IsolatedAsyncioTestCase):
    async def test_serialized_default_annotations_and_complete_catalog(self):
        listed = [json.loads(t.model_dump_json(by_alias=True)) for t in await server.mcp.list_tools()]
        response = await server.mcp._handle_list_tools(None, None)
        tools = json.loads(response.model_dump_json(by_alias=True))['tools']
        self.assertEqual(tools, listed)
        self.assertIsNone(response.next_cursor)
        self.assertEqual({t['name'] for t in tools}, {
            'context', 'bridge_overview', 'bridge_health', 'agent_terminal_read',
            'read', 'search', 'diff', 'delegate',
            'current_state_update', 'project_register', 'project_initialize',
            'list_entries', 'inspect_file', 'commit_prepare', 'project_text_edit', 'commit', 'work_report', 'prepare_file_attachment',
        })
        self.assertEqual(len(tools), 21 - 3)
        for tool in tools:
            with self.subTest(tool=tool['name']):
                ann = tool['annotations']
                write = tool['name'] in {'delegate', 'current_state_update', 'project_register', 'project_initialize', 'commit', 'commit_prepare', 'project_text_edit'}
                self.assertEqual(ann['readOnlyHint'], not write)
                self.assertEqual(ann['destructiveHint'], tool['name'] in {'delegate', 'current_state_update', 'commit', 'commit_prepare', 'project_text_edit'})
                self.assertEqual(ann['openWorldHint'], tool['name'] in {'delegate'})
                self.assertEqual(ann['idempotentHint'], tool['name'] not in {'delegate', 'current_state_update', 'commit', 'prepare_file_attachment', 'commit_prepare', 'project_text_edit'})
        # Every registered surface states its actual behavioral hints.
        source = ast.parse(Path(server.__file__).read_text())
        registrations = [n for n in ast.walk(source) if isinstance(n, ast.Call)
                         and isinstance(n.func, ast.Attribute) and n.func.attr == 'tool'
                         and isinstance(n.func.value, ast.Name) and n.func.value.id == 'mcp']
        self.assertEqual(len(registrations), 18 - 3)
        self.assertTrue(all(any(k.arg == 'annotations' for k in n.keywords) for n in registrations))

    async def test_retired_tool_names_are_absent_and_no_aliases_exist(self):
        listed = {t.name for t in await server.mcp.list_tools()}
        for retired in ('collaboration_snapshot', 'workspace_register', 'checkpoint',
                        'agent_observe', 'attach_file', 'watch_works'):
            self.assertNotIn(retired, listed)
            with self.assertRaises(Exception):
                await server.mcp.call_tool(retired, {})
        for retained in ('context', 'commit_prepare'):
            self.assertIn(retained, listed)

    async def test_new_surface_schemas_use_canonical_public_terminology(self):
        tools = {t.name: t for t in await server.mcp.list_tools()}
        for name in ('bridge_overview', 'project_register'):
            self.assertNotIn('workspace_ref', tools[name].input_schema.get('properties', {}))
            self.assertNotIn('workspace_path', tools[name].input_schema.get('properties', {}))
            self.assertNotIn('checkout_path', tools[name].input_schema.get('properties', {}))
        self.assertIn('project_ref', tools['bridge_overview'].input_schema['properties'])
        self.assertNotIn('project_ref', tools['bridge_overview'].input_schema.get('required', []))
        self.assertEqual(sorted(tools['project_register'].input_schema.get('required', [])),
                         ['path', 'project_ref'])
        self.assertEqual(list(tools['project_register'].input_schema['properties']),
                         ['project_ref', 'path'])
        prepare = tools['commit_prepare'].input_schema
        self.assertIn('candidate_id', prepare['properties'])
        delegate = tools['delegate'].input_schema['properties']
        self.assertEqual(set(delegate), {'project_ref', 'assignments'})
        self.assertEqual(set(tools['delegate'].input_schema['required']), {'project_ref', 'assignments'})
        self.assertNotIn('capture_report', delegate)
        for name, listed in tools.items():
            self.assertNotIn('capture_report', listed.input_schema.get('properties', {}), name)


if __name__ == "__main__":
    unittest.main()
