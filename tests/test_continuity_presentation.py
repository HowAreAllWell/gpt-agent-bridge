"""Bounded continuity edits and actual MCP serialization, using only temporary fixtures."""
import hashlib
import json
import unittest
from unittest.mock import patch, AsyncMock
from jsonschema import Draft202012Validator
import tests.test_project_continuity as fixtures
import tests.test_read_contract as read_fixtures
from gpt_agent_bridge import server


class EditTests(unittest.IsolatedAsyncioTestCase):
    setUp = fixtures.ProjectContinuityTests.setUp
    _write_manifest = fixtures.ProjectContinuityTests._write_manifest

    async def checkpoint(self, **args):
        result = await server.mcp.call_tool('current_state_update', {'project_ref': 'project', **args})
        wire = json.loads(result.model_dump_json(by_alias=True))
        return wire['structuredContent']

    async def test_original_bytes_simultaneous_edits_and_stale_retry(self):
        self._write_manifest()
        state = self.root / 'STATE.md'
        original = '甲\r\nalpha beta\r\n尾😀\r\n'.encode()
        state.write_bytes(original)
        revision = 'sha256:' + hashlib.sha256(original).hexdigest()
        args = dict(expected_revision=revision, edits=[
            {'old_text':'alpha', 'new_text':'beta'},
            {'old_text':'beta', 'new_text':'新'},
        ])
        result = await self.checkpoint(**args)
        self.assertTrue(result['ok'], result)
        expected = '甲\r\nbeta 新\r\n尾😀\r\n'.encode()
        self.assertEqual(state.read_bytes(), expected)
        result = await self.checkpoint(**args)
        self.assertFalse(result['ok'])
        self.assertEqual(state.read_bytes(), expected)

    async def test_rejected_edits_do_not_write(self):
        self._write_manifest()
        state = self.root / 'STATE.md'
        original = b'aaa unique'
        revision = 'sha256:' + hashlib.sha256(original).hexdigest()
        cases = [
            {}, {'edits':[]}, {'content':'x','edits':[{'old_text':'unique','new_text':'x'}]},
            {'edits':[{'old_text':'','new_text':'x'}]},
            {'edits':[{'old_text':'absent','new_text':'x'}]},
            {'edits':[{'old_text':'aa','new_text':'x'}]},
            {'edits':[{'old_text':'unique','new_text':'x'}, {'old_text':'nique','new_text':'z'}]},
            {'edits':[{'old_text':'unique','new_text':'x','extra':'z'}]},
            {'edits':[{'old_text':'unique','new_text':'\ud800'}]},
        ]
        for args in cases:
            with self.subTest(args=args):
                state.write_bytes(original)
                result = await self.checkpoint(expected_revision=revision, **args)
                self.assertFalse(result['ok'], result)
                self.assertEqual(state.read_bytes(), original)

    async def test_edits_recheck_before_publish(self):
        self._write_manifest()
        state = self.root/'STATE.md'
        state.write_bytes(b'original')
        revision = 'sha256:' + hashlib.sha256(b'original').hexdigest()
        check = server._project_continuity._checkpoint_revision_at_parent
        def race(*args):
            state.write_bytes(b'external')
            return check(*args)
        with patch.object(server._project_continuity, '_checkpoint_revision_at_parent', side_effect=race):
            result = await self.checkpoint(expected_revision=revision,
                edits=[{'old_text':'original','new_text':'changed'}])
        self.assertEqual(result['error_type'],'CheckpointConflict')
        self.assertEqual(state.read_bytes(),b'external')
        self.assertEqual(list(self.root.glob('.principal-checkpoint-*.tmp')),[])

    async def test_required_revision_and_full_text_mode(self):
        self._write_manifest()
        tool = next(t for t in await server.mcp.list_tools() if t.name == 'current_state_update')
        self.assertIn('expected_revision', tool.input_schema['required'])
        self.assertNotIn('content', tool.input_schema['required'])
        result = await self.checkpoint(content='初\r\n', expected_revision='missing')
        self.assertTrue(result['ok'], result)
        self.assertEqual((self.root/'STATE.md').read_bytes(), '初\r\n'.encode())


class PagingTests(unittest.IsolatedAsyncioTestCase):
    def test_summaries_preserve_evidence_limits_without_generic_core(self):
        from gpt_agent_bridge.tool_presentation import _summary
        for name in ('read', 'search', 'diff', 'list_entries', 'inspect_file'):
            self.assertEqual(_summary({'ok': True}, name), 'Result available in structuredContent.')
        unknown = _summary({'ok': False, 'error_type': 'WorkDispatchTransportUncertain',
                            'submission_evidence': {'mutation_possible': True}}, 'delegate')
        self.assertIn('Delivery unknown', unknown)
        self.assertNotIn('Do not', unknown)
        self.assertNotIn('Read agent_terminal_read', unknown)
        edited = _summary({'ok': True, 'status': 'unknown'}, 'project_text_edit')
        self.assertIn('outcome unknown', edited)
        for name in ('claim_work_watch',):
            granted = _summary({'ok': True, 'granted': True}, name)
            denied = _summary({'ok': True, 'granted': False, 'status': 'already_consumed'}, name)
            self.assertIn('delivery is unverified', granted)
            self.assertIn('this caller', denied)
            self.assertNotIn('no follow-up will be sent', denied)

    setUp = read_fixtures.ReadContractTests.setUp
    wire = read_fixtures.ReadContractTests.wire

    async def test_default_unicode_page_and_raw_hash_guard(self):
        raw = ('中文😀\r\n'*4000).encode()
        (self.root/'page').write_bytes(raw)
        wire, first = await self.wire(path='page')
        self.assertEqual(len(first['content']),4096)
        digest = hashlib.sha256(raw).hexdigest()
        self.assertEqual(first['file_sha256'],digest)
        _, second = await self.wire(path='page',offset=first['content_next_offset'],expected_sha256=digest)
        self.assertTrue(second['ok'])
        _, expanded = await self.wire(path='page',limit=16384)
        self.assertEqual(len(expanded['content']),16384)
        (self.root/'page').write_bytes(raw.replace('中'.encode(),'甲'.encode()))
        _, changed = await self.wire(path='page',offset=first['content_next_offset'],expected_sha256=digest)
        self.assertEqual(changed['error_type'],'ReadVersionChanged')
        self.assertNotIn('content',changed)
        _, invalid = await self.wire(path='page',expected_sha256='bad')
        self.assertEqual(invalid['error_type'],'InvalidExpectedSHA256')

    async def test_image_hash_and_legacy_explicit_limit(self):
        raw = read_fixtures.TINY_PNG
        (self.root/'image.png').write_bytes(raw)
        digest = hashlib.sha256(raw).hexdigest()
        for limit in (4096,16384):
            wire, meta = await self.wire(path='image.png',limit=limit,expected_sha256=digest)
            self.assertEqual(wire['content'][0]['type'],'image')
            self.assertTrue(meta['ok'])
        wire, meta = await self.wire(path='image.png',expected_sha256='0'*64)
        self.assertEqual(meta['error_type'],'ReadVersionChanged')
        self.assertFalse(any(b['type']=='image' for b in wire['content']))

    async def test_all_registered_dictionary_outputs_keep_one_payload(self):
        # Inject synthetic results at registered function boundary: SDK validation
        # and call_tool conversion remain real; no delegate/run/host action occurs.
        for descriptor in await server.mcp.list_tools():
            if descriptor.name in {'read', 'prepare_file_attachment', 'delegate'}:
                # These return explicit CallToolResult objects, not dictionaries.
                # Real read/attach_file results have dedicated wire tests.
                continue
            tool = server.mcp._tool_manager.get_tool(descriptor.name)
            payload = {'ok':False, 'error_type':'ExecutionUncertain',
                       'error':'UNIQUE_BODY_SENTINEL', 'rerun_safe':False,
                       'proves':'unknown outcome'}
            with patch.object(type(tool.fn_metadata), 'call_fn_with_arg_validation', AsyncMock(return_value=payload)):
                result = await server.mcp.call_tool(descriptor.name, {})
            wire = json.loads(result.model_dump_json(by_alias=True))
            self.assertEqual(wire['structuredContent'],payload)
            self.assertEqual(json.dumps(wire).count('UNIQUE_BODY_SENTINEL'),1)
            self.assertFalse(wire['structuredContent']['rerun_safe'])
            Draft202012Validator(descriptor.output_schema).validate(wire['structuredContent'])
            success = {'ok':True,'content':'UNIQUE_SUCCESS_BODY'}
            with patch.object(type(tool.fn_metadata), 'call_fn_with_arg_validation', AsyncMock(return_value=success)):
                result = await server.mcp.call_tool(descriptor.name, {})
            wire = json.loads(result.model_dump_json(by_alias=True))
            self.assertEqual(wire['structuredContent'],success)
            self.assertEqual(json.dumps(wire).count('UNIQUE_SUCCESS_BODY'),1)
            Draft202012Validator(descriptor.output_schema).validate(wire['structuredContent'])
