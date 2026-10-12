"""Direct editor path/version/race and public frozen-target contracts."""
import asyncio
import hashlib
import json
import os
from pathlib import Path
import stat
import unittest
from unittest.mock import patch

from tests import test_project_continuity as fixtures
from gpt_agent_bridge import project_text_edit as editor
from gpt_agent_bridge import server
from gpt_agent_bridge.evidence_target import EvidenceCheckout, EvidenceTarget
from gpt_agent_bridge.workspace_context import WorkspaceContext, canonical_git_worktree


def sha(data):
    return hashlib.sha256(data).hexdigest()


class ProjectTextEditTests(unittest.IsolatedAsyncioTestCase):
    setUp = fixtures.ProjectContinuityTests.setUp

    async def edit(self, path='README.md', original=None, edits=None, **kwargs):
        if original is None:
            original = (self.root / path).read_bytes()
        return await server.project_text_edit('project', path, sha(original),
                    edits if edits is not None else [{'old_text': '# Test Repo', 'new_text': '# Edited'}], **kwargs)

    async def test_exact_multi_edits_use_original_preserve_crlf_mode_and_unedited_bytes(self):
        original = 'α one\r\nbeta two\r\nlast'.encode()
        path = self.root / 'README.md'; path.write_bytes(original); path.chmod(0o751)
        result = await self.edit(original=original, edits=[{'old_text': 'one', 'new_text': 'beta'},
                                                         {'old_text': 'beta two', 'new_text': 'γ'}])
        expected = 'α beta\r\nγ\r\nlast'.encode()
        self.assertEqual(result['status'], 'edited', result)
        self.assertEqual(path.read_bytes(), expected)
        self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o751)
        self.assertEqual((result['old_sha256'], result['new_sha256']), (sha(original), sha(expected)))
        self.assertEqual((result['old_bytes'], result['new_bytes'], result['edit_count']), (len(original), len(expected), 2))
        self.assertEqual(result['target_kind'], 'project_root')
        self.assertFalse(list(self.root.glob('.bridge-text-edit-*')))

    async def test_unique_original_matches_and_overlap_required(self):
        for original, edits, kind in [
            (b'abc abc', [{'old_text': 'abc', 'new_text': 'x'}], 'EditMismatch'),
            (b'aaa', [{'old_text': 'aa', 'new_text': 'x'}], 'EditMismatch'),
            (b'abcdef', [{'old_text': 'abc', 'new_text': 'x'}, {'old_text': 'bcde', 'new_text': 'y'}], 'EditOverlap'),
            (b'abcdef', [{'old_text': 'missing', 'new_text': 'x'}], 'EditMismatch'),
            (b'abcdef', [{'old_text': 'a', 'new_text': 'new'}, {'old_text': 'new', 'new_text': 'x'}], 'EditMismatch'),
        ]:
            with self.subTest(kind=kind):
                (self.root / 'README.md').write_bytes(original)
                result = await self.edit(original=original, edits=edits)
                self.assertEqual(result['error_type'], kind, result)
                self.assertFalse(result['file_replaced'])
                self.assertEqual((self.root / 'README.md').read_bytes(), original)

    async def test_required_full_hash_stale_hash_and_replay_rejected(self):
        for invalid in ('', 'sha256:' + 'a' * 64, 'a' * 63, 'A' * 64, 'missing'):
            result = await server.project_text_edit('project', 'README.md', invalid, [{'old_text':'#', 'new_text':'x'}])
            self.assertEqual(result['error_type'], 'InvalidHash')
        result = await server.project_text_edit('project', 'README.md', 'a' * 64, [{'old_text':'#', 'new_text':'x'}])
        self.assertEqual(result['error_type'], 'StaleHash')
        original = (self.root / 'README.md').read_bytes()
        self.assertTrue((await self.edit(original=original))['ok'])
        self.assertEqual((await self.edit(original=original))['error_type'], 'StaleHash')

    async def test_missing_directory_symlinks_traversal_and_special_paths_rejected(self):
        outside = self.root.parent / 'outside'; outside.mkdir()
        (outside / 'file').write_text('outside')
        (self.root / 'dir').mkdir()
        (self.root / 'link').symlink_to(outside / 'file')
        (self.root / 'parent').symlink_to(outside, target_is_directory=True)
        os.mkfifo(self.root / 'fifo')
        for path in ('missing', 'dir', 'link', 'parent/file', 'fifo', '../outside/file', '/etc/passwd',
                     '.git/config', 'a/../README.md', './README.md', 'a//file', 'a\\file'):
            with self.subTest(path=path):
                result = await server.project_text_edit('project', path, 'a' * 64, [{'old_text':'x','new_text':'y'}])
                self.assertFalse(result['ok'], result)
                self.assertFalse(result.get('file_replaced', False))
        self.assertEqual((outside / 'file').read_text(), 'outside')
        self.assertFalse((self.root / 'missing').exists())

    async def test_invalid_utf8_nul_and_text_size_bounds(self):
        for original, kind in ((b'\xff', 'InvalidUTF8'), (b'abc\0', 'BinaryRejected'),
                               (b'x' * (editor.MAX_TEXT_BYTES + 1), 'TextTooLarge')):
            (self.root / 'README.md').write_bytes(original)
            result = await self.edit(original=original, edits=[{'old_text':'x', 'new_text':'y'}])
            self.assertEqual(result['error_type'], kind, result)
            self.assertEqual((self.root / 'README.md').read_bytes(), original)
        (self.root / 'README.md').write_bytes(b'a')
        with patch.object(editor, 'MAX_TEXT_BYTES', 16):
            result = await self.edit(edits=[{'old_text':'a', 'new_text':'b' * 17}])
        self.assertEqual(result['error_type'], 'TextTooLarge')

    async def test_edit_shape_and_encoding_bounds(self):
        original = (self.root / 'README.md').read_bytes()
        for edits in ([], [{'old_text':'', 'new_text':'x'}], [{'old_text':'#'}],
                      [{'old_text':'#', 'new_text':'x', 'extra':'bad'}],
                      [{'old_text':'#', 'new_text':'\ud800'}], [{'old_text':'#', 'new_text':'\0'}],
                      [{'old_text':'#', 'new_text':'x'}] * 257):
            with self.subTest(edits=str(edits)[:70]):
                result = await self.edit(original=original, edits=edits)
                self.assertFalse(result['ok'], result)
                self.assertEqual((self.root / 'README.md').read_bytes(), original)

    async def test_hash_race_before_atomic_replace_preserves_external_writer(self):
        read = editor.read_bound
        count = 0
        def race(*args):
            nonlocal count
            count += 1
            if count == 2:
                (self.root / 'README.md').write_text('external writer\n')
            return read(*args)
        with patch.object(editor, 'read_bound', side_effect=race):
            result = await self.edit()
        self.assertEqual(result['error_type'], 'StaleHash', result)
        self.assertEqual((self.root / 'README.md').read_text(), 'external writer\n')
        self.assertFalse(list(self.root.glob('.bridge-text-edit-*')))

    async def test_symlink_swap_before_replace_cannot_write_outside(self):
        outside = self.root.parent / 'outside.txt'; outside.write_text('untouched\n')
        read = editor.read_bound
        count = 0
        def race(*args):
            nonlocal count
            count += 1
            if count == 2:
                (self.root / 'README.md').unlink()
                (self.root / 'README.md').symlink_to(outside)
            return read(*args)
        with patch.object(editor, 'read_bound', side_effect=race):
            result = await self.edit()
        self.assertEqual(result['status'], 'rejected', result)
        self.assertEqual(outside.read_text(), 'untouched\n')

    async def test_unknown_replace_outcome_reported_without_retry(self):
        replace = editor.os.replace
        calls = 0
        def lost(*args, **kwargs):
            nonlocal calls
            calls += 1
            replace(*args, **kwargs)
            raise OSError('lost acknowledgement')
        with patch.object(editor.os, 'replace', side_effect=lost):
            result = await self.edit()
        self.assertEqual(result['status'], 'unknown', result)
        self.assertIsNone(result['file_replaced'])
        self.assertEqual(calls, 1)
        from gpt_agent_bridge.tool_presentation import _summary
        self.assertIn('outcome unknown', _summary(result, 'project_text_edit'))
        self.assertEqual((self.root / 'README.md').read_text(), '# Edited\n')

    async def test_parent_binding_swap_refuses_detached_directory_write(self):
        directory = self.root / 'dir'; directory.mkdir()
        (directory / 'file').write_text('chosen\n')
        detached = self.root / 'detached'
        outside = self.root.parent / 'outside'; outside.mkdir(); (outside / 'file').write_text('outside\n')
        read = editor.read_bound
        count = 0
        def race(*args):
            nonlocal count
            count += 1
            if count == 2:
                directory.rename(detached)
                directory.symlink_to(outside, target_is_directory=True)
            return read(*args)
        with patch.object(editor, 'read_bound', side_effect=race):
            result = await self.edit(path='dir/file', edits=[{'old_text':'chosen', 'new_text':'edited'}])
        self.assertEqual(result['status'], 'rejected', result)
        self.assertEqual((detached / 'file').read_text(), 'chosen\n')
        self.assertEqual((outside / 'file').read_text(), 'outside\n')

    async def test_writer_gate_serializes_same_hash_edits(self):
        original = (self.root / 'README.md').read_bytes()
        results = await asyncio.gather(self.edit(original=original), self.edit(original=original))
        self.assertEqual(sorted(r['status'] for r in results), ['edited', 'rejected'])
        self.assertEqual([r['error_type'] for r in results if not r['ok']], ['StaleHash'])

    async def test_frozen_work_target_and_target_change_rejection(self):
        linked = self.root.parent / 'linked'
        fixtures.subprocess.run(['git','worktree','add','-b','linked',str(linked)], cwd=self.root,
                                check=True, capture_output=True)
        _, identity = canonical_git_worktree(self.root)
        project = WorkspaceContext('project', self.root, identity, str(self.root))
        frozen = EvidenceCheckout.capture(project, str(linked))
        target = EvidenceTarget(project, frozen.revalidate(project), 'work')
        original = (linked / 'README.md').read_bytes()
        with patch.object(server, '_resolve_evidence_target', return_value=target):
            result = await self.edit(original=original, work_ref='work')
        self.assertEqual(result['target_kind'], 'work_checkout')
        self.assertEqual((linked / 'README.md').read_text(), '# Edited\n')
        self.assertEqual((self.root / 'README.md').read_bytes(), original)
        changed = EvidenceTarget(project, project, None)
        with patch.object(server, '_resolve_evidence_target', side_effect=[target, changed]):
            result = await self.edit(original=original, work_ref='work')
        self.assertEqual(result['error_type'], 'TargetChanged')

    async def test_public_schemas_strict_arguments_and_nested_edits(self):
        tools = {t.name: t for t in await server.mcp.list_tools()}
        self.assertNotIn('commit_preview', tools)
        self.assertNotIn('stage_paths', tools)
        tool = tools['project_text_edit']
        self.assertEqual(set(tool.input_schema['required']), {'project_ref','path','expected_sha256','edits'})
        self.assertFalse(tool.input_schema['additionalProperties'])
        edits_schema = tool.input_schema['$defs']['TextEdit']
        self.assertFalse(edits_schema['additionalProperties'])
        self.assertEqual(set(edits_schema['required']), {'old_text','new_text'})
        base = {'project_ref':'project', 'path':'README.md', 'expected_sha256':sha((self.root/'README.md').read_bytes()),
                'edits':[{'old_text':'#', 'new_text':'x'}]}
        for name, args in [('project_text_edit', {**base,'commands':['x']}),
                           ('project_text_edit', {**base,'edits':[{'old_text':'#','new_text':'x','extra':'bad'}]}),
                           ('project_text_edit', {**base,'edits':[{'old_text':'#','new_text':5}]}),
                           ('project_text_edit', {k:v for k,v in base.items() if k != 'expected_sha256'}),
                           ('commit_prepare', {'project_ref':'project','paths':[5]}),
                           ('commit_prepare', {'project_ref':'project','paths':['README.md'],'argv':['-A']})]:
            with self.subTest(name=name, args=str(args)[:80]):
                with self.assertRaises(Exception) as raised:
                    await server.mcp.call_tool(name, args)
                self.assertIn("validation error", str(raised.exception))

    async def test_unavailable_work_ref_and_unknown_project_have_no_write(self):
        original = (self.root/'README.md').read_bytes()
        result = await self.edit(work_ref='unavailable')
        self.assertFalse(result['ok'])
        result = await server.project_text_edit('unknown', 'README.md', sha(original), [{'old_text':'#','new_text':'x'}])
        self.assertFalse(result['ok'])
        self.assertEqual((self.root/'README.md').read_bytes(), original)
