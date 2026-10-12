"""view_image retirement after the A5 Web native-image gate.

The former view_image compatibility tool is removed from SOURCE with no hidden
alias or shim; public unified read is the only native-image route and inherits
the unique safety coverage (Work target binding, hash mismatch, cap, bad magic,
nofollow race). The historical HANDOFF locator class/test name is kept for
evidence continuity, now guarding the unified read memory wire plus retirement;
historical view_image acceptance stays in committed/frozen history.
"""
import base64
import json
import os
import unittest
from unittest.mock import patch

import anyio
from mcp import ClientSession
from mcp.shared.memory import create_client_server_memory_streams
from mcp.types import CallToolRequestParams

os.environ.setdefault('BRIDGE_PATH_TOKEN', 'test-token-abcdefghijklmnopqrstuvwxyz-012345')
from gpt_agent_bridge import server
from tests import test_read_contract as read_fixtures
from tests.test_vnext_surface import TINY_PNG
from gpt_agent_bridge.evidence_target import EvidenceCheckout


class ViewImageTests(unittest.IsolatedAsyncioTestCase):
    setUp = read_fixtures.ReadContractTests.setUp

    async def test_memory_wire_has_native_image_without_structured_payload(self):
        # HANDOFF boundary locator: the public native-image memory wire (now
        # unified read) carries one native image plus one full-metadata text
        # block with no structuredContent, and the retired view_image name is
        # absent from the raw wire catalog.
        (self.root / 'image.png').write_bytes(TINY_PNG)
        lowlevel = server.mcp._lowlevel_server
        wire_results = []
        class RecordingSend:
            def __init__(self, stream): self.stream = stream
            def __getattr__(self, name): return getattr(self.stream, name)
            async def __aenter__(self): return self
            async def __aexit__(self, *args): return await self.stream.__aexit__(*args)
            async def send(self, message):
                payload = getattr(message.message, 'root', message.message)
                result = getattr(payload, 'result', None)
                if isinstance(result, dict): wire_results.append(result)
                await self.stream.send(message)
        async with create_client_server_memory_streams() as (client_streams, server_streams):
            async with anyio.create_task_group() as group:
                group.start_soon(lowlevel.run, server_streams[0], RecordingSend(server_streams[1]),
                                 lowlevel.create_initialization_options())
                async with ClientSession(*client_streams) as client:
                    await client.initialize()
                    catalog = await client.list_tools()
                    self.assertNotIn('view_image', {tool.name for tool in catalog.tools})
                    result = await client.call_tool('read', {'project_ref': 'p', 'path': 'image.png'})
                    wire = result.model_dump(by_alias=True, exclude_none=True)
                    self.assertNotIn('structuredContent', wire)
                    self.assertEqual([b['type'] for b in wire['content']], ['image', 'text'])
                    self.assertEqual(base64.b64decode(wire['content'][0]['data']), TINY_PNG)
                    metadata = json.loads(wire['content'][1]['text'])
                    self.assertEqual(metadata['provenance']['proves'], 'observed_content_only')
                group.cancel_scope.cancel()
        self.assertFalse(any(r.get('name') == 'view_image'
                             for r in wire_results if 'tools' in r for r in r['tools']))
        raw_result = next(r for r in wire_results if 'content' in r)
        self.assertNotIn('structuredContent', raw_result)
        self.assertEqual([b['type'] for b in raw_result['content']], ['image', 'text'])

    async def test_view_image_absent_noncallable_and_unknown_at_dispatch(self):
        catalog = {tool.name for tool in await server.mcp.list_tools()}
        self.assertNotIn('view_image', catalog)
        self.assertFalse(hasattr(server, 'view_image'))
        self.assertIsNone(server.mcp._tool_manager.get_tool('view_image'))
        result = await server.mcp._handle_call_tool(None, CallToolRequestParams(
            name='view_image', arguments={'project_ref': 'p', 'path': 'image.png'}))
        wire = json.loads(result.model_dump_json(by_alias=True))
        self.assertTrue(wire['isError'])
        self.assertIsNone(wire['structuredContent'])
        self.assertIn('Unknown tool', wire['content'][0]['text'])

    async def test_read_image_safety_work_hash_cap_magic_and_nofollow(self):
        # Migrated unique view_image safety coverage; public read shares the same
        # reader gate, target binding, hash, cap, magic and nofollow behavior.
        (self.linked / 'image.png').write_bytes(TINY_PNG)
        server._WORK_REGISTRY['work-image'] = {'project_ref': 'p', 'workspace_root': str(self.root),
            'execution_identity': 'bound', 'evidence_checkout': EvidenceCheckout.capture(self.project, str(self.linked))}
        result = await server.mcp.call_tool('read', {'project_ref': 'p', 'path': 'image.png',
                                                     'work_ref': 'work-image'})
        self.assertIsNone(result.structured_content)
        self.assertEqual([block.type for block in result.content], ['image', 'text'])
        meta = json.loads(result.content[-1].text)
        self.assertEqual(meta['execution_target'], str(self.linked))
        for args, expected in [({'path': 'image.png', 'expected_sha256': '0' * 64}, 'ReadVersionChanged'),
                               ({'path': 'image.png', 'work_ref': 'unknown'}, 'WorkRefUnavailable'),
                               ({'path': '../image.png'}, 'InvalidPath'),
                               # Public read refuses PDF/DOCX before any body access.
                               ({'path': 'doc.pdf'}, 'UnsupportedReadFormat')]:
            call = {'project_ref': 'p', 'work_ref': 'work-image', **args}
            result = await server.mcp.call_tool('read', call)
            self.assertEqual(result.structured_content['error_type'], expected)
            self.assertEqual([block.type for block in result.content], ['text'])
        with patch.object(server, 'MAX_VNEXT_IMAGE_FILE_SIZE', 2):
            result = await server.mcp.call_tool('read', {'project_ref': 'p', 'path': 'image.png',
                                                         'work_ref': 'work-image'})
            self.assertEqual(result.structured_content['error_type'], 'FileTooLarge')
        (self.linked / 'bad.png').write_bytes(b'not PNG')
        result = await server.mcp.call_tool('read', {'project_ref': 'p', 'path': 'bad.png',
                                                     'work_ref': 'work-image'})
        self.assertEqual(result.structured_content['error_type'], 'UnsupportedImageFormat')
        original = server._read_bounded_workspace_bytes
        def replace_before_open(workspace, parts, path, limit):
            (self.linked / 'image.png').unlink()
            (self.linked / 'image.png').symlink_to('/etc/passwd')
            return original(workspace, parts, path, limit)
        with patch.object(server, '_read_bounded_workspace_bytes', replace_before_open):
            result = await server.mcp.call_tool('read', {'project_ref': 'p', 'path': 'image.png',
                                                         'work_ref': 'work-image'})
        self.assertEqual(result.structured_content['error_type'], 'SymlinkRejected')
