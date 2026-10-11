"""Explicit behavioral catalog annotations; no calls to external tools or hosts."""
import ast
import json
import os
from pathlib import Path
import unittest
os.environ.setdefault('BRIDGE_PATH_TOKEN', 'test-token-abcdefghijklmnopqrstuvwxyz-012345')
import server


class ToolAnnotationTests(unittest.IsolatedAsyncioTestCase):
    async def test_serialized_default_annotations_and_complete_catalog(self):
        listed = [json.loads(t.model_dump_json(by_alias=True)) for t in await server.mcp.list_tools()]
        response = await server.mcp._handle_list_tools(None, None)
        tools = json.loads(response.model_dump_json(by_alias=True))['tools']
        self.assertEqual(tools, listed)
        self.assertIsNone(response.next_cursor)
        self.assertEqual({t['name'] for t in tools}, {
            'wait_work_watch', 'claim_work_watch', 'record_work_watch_send_outcome', 'context', 'bridge_overview', 'bridge_health', 'agent_terminal_read',
            'read', 'search', 'diff', 'delegate',
            'current_state_update', 'project_register', 'project_initialize',
            'list_entries', 'inspect_file', 'commit_prepare', 'project_text_edit', 'commit', 'work_report', 'prepare_file_attachment',
        })
        self.assertEqual(len(tools), 21)
        for tool in tools:
            with self.subTest(tool=tool['name']):
                ann = tool['annotations']
                # The app claim only consumes process-local notice state.
                write = tool['name'] in {'delegate', 'current_state_update', 'project_register', 'project_initialize', 'commit', 'commit_prepare', 'project_text_edit', 'claim_work_watch', 'record_work_watch_send_outcome'}
                self.assertEqual(ann['readOnlyHint'], not write)
                self.assertEqual(ann['destructiveHint'], tool['name'] in {'delegate', 'current_state_update', 'commit', 'commit_prepare', 'project_text_edit'})
                self.assertEqual(ann['openWorldHint'], tool['name'] in {'delegate'})
                self.assertEqual(ann['idempotentHint'], tool['name'] not in {'delegate', 'current_state_update', 'commit', 'prepare_file_attachment', 'commit_prepare', 'project_text_edit', 'claim_work_watch'})
        # Every registered surface states its actual behavioral hints.
        source = ast.parse(Path(server.__file__).read_text())
        registrations = [n for n in ast.walk(source) if isinstance(n, ast.Call)
                         and isinstance(n.func, ast.Attribute) and n.func.attr == 'tool'
                         and isinstance(n.func.value, ast.Name) and n.func.value.id == 'mcp']
        self.assertEqual(len(registrations), 18)
        self.assertTrue(all(any(k.arg == 'annotations' for k in n.keywords) for n in registrations))

    async def test_search_descriptor_matches_actual_untracked_domain(self):
        tools = {t.name: t for t in await server.mcp.list_tools()}
        self.assertIn(
            'include_untracked additionally searches nonignored untracked text files',
            tools['search'].description,
        )
        self.assertNotIn('current logs', tools['search'].description)

    async def test_delegate_descriptor_routes_result_dependencies_without_polling(self):
        tools = {t.name: t for t in await server.mcp.list_tools()}
        description = ' '.join(tools['delegate'].description.split())
        for contract in (
            "always request each Agent's report",
            'Returns without waiting for results',
            'one immutable all-of continuation',
            'including further delegation',
            'Armed: do not poll, sleep, repeatedly delegate',
            'Ready: read result_ready reports with work_report',
            'unknown delivery is not safe to send again',
            'Serving evidence proves neither review nor resolution',
        ):
            with self.subTest(contract=contract):
                self.assertIn(contract, description)
        self.assertNotIn('watch_works', description)

    async def test_delegate_descriptor_separates_ready_judgment_from_armed_continuation(self):
        tools = {t.name: t for t in await server.mcp.list_tools()}
        description = ' '.join(tools['delegate'].description.split())
        ready, armed = description.split('Armed:', 1)
        self.assertIn('Ready: read result_ready reports with work_report', ready)
        self.assertIn('inspect relevant attention diagnostics and reassess the pending judgment', ready)
        self.assertNotIn('end this turn', ready)
        for contract in (
            'do not poll, sleep, repeatedly delegate, or inspect terminals/context merely to wait',
            'continue independent work or end this turn if none remains',
            'Later Works never join this cohort',
            'Ready iff every retained member is finally classified',
            'Attention never completes early; report-probe-pending is not ready',
            'Normal/result_ready requires agent_turn_settled plus a readable required report',
            'Unrelated Works never delay this cohort',
            'Readiness is not task success',
        ):
            with self.subTest(contract=contract):
                self.assertIn(contract, description)

    async def test_terminal_descriptor_preserves_diagnostics_without_work_monitoring(self):
        tools = {t.name: t for t in await server.mcp.list_tools()}
        description = ' '.join(tools['agent_terminal_read'].description.split())
        for contract in (
            "Reads one Agent's current terminal text without sending input",
            'Use this for diagnostics when the terminal text itself is relevant',
            'not a delegated-Work completion or progress monitor, nor a polling substitute '
            'for delegated cohort continuation',
            'unattributed to a work_ref',
            'not a progress, status or liveness polling channel',
            'does not establish task success',
            'limit is 1..400 lines (default 120)',
        ):
            with self.subTest(contract=contract):
                self.assertIn(contract, description)

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
