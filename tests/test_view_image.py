"""Unified read retains Work target, hash, cap, magic and nofollow safety.

Raw native-image wire and retired-name catalog coverage live in
ReadMemoryWireTests and RunRetirementTests rather than repeated sessions here.
"""
import json
import os
import unittest
from unittest.mock import patch

os.environ.setdefault('BRIDGE_PATH_TOKEN', 'test-token-abcdefghijklmnopqrstuvwxyz-012345')
from gpt_agent_bridge import server
from tests import test_read_contract as read_fixtures
from tests.test_vnext_surface import TINY_PNG
from gpt_agent_bridge.evidence_target import EvidenceCheckout


class ViewImageTests(unittest.IsolatedAsyncioTestCase):
    setUp = read_fixtures.ReadContractTests.setUp

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
