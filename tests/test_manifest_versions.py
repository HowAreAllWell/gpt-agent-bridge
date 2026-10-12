"""Canonical manifest routing; fixture files never migrate the Bridge repo."""
import hashlib
import json
from pathlib import Path
import unittest

from tests import test_project_continuity as fixtures
from gpt_agent_bridge import project_continuity as continuity
from gpt_agent_bridge import server


class CanonicalManifestTests(unittest.IsolatedAsyncioTestCase):
    setUp = fixtures.ProjectContinuityTests.setUp

    def write_manifest(self, **overrides):
        data = {'rules': ['README.md'], 'current_state': 'CURRENT.md', 'memory': 'MEMORY.md'}
        data.update(overrides)
        principal = self.root / '.principal'
        principal.mkdir(exist_ok=True)
        path = principal / 'project.json'
        path.write_text(json.dumps(data), encoding='utf-8')
        return path

    async def observe(self):
        return (await server.context(project_ref='project'))['continuity']

    async def test_projects_pointers_without_bodies(self):
        (self.root / 'MEMORY.md').write_text('private memory body')
        (self.root / 'CURRENT.md').write_text('private state body')
        manifest = self.write_manifest()
        before = manifest.read_bytes()
        result = await self.observe()
        self.assertTrue(result['ready'])
        self.assertNotIn('manifest_version', result)
        self.assertEqual(result['canonical_pointers'], {
            'rules': ['README.md'], 'memory': 'MEMORY.md'})
        self.assertEqual(result['current_state']['revision'], 'sha256:' +
                         hashlib.sha256(b'private state body').hexdigest())
        self.assertNotIn('private', json.dumps(result))
        self.assertNotIn('takeover', json.dumps(result))
        self.assertEqual(manifest.read_bytes(), before)

    async def test_retired_methods_field_refuses_observation_and_publication(self):
        memory = self.root / 'MEMORY.md'
        memory.write_bytes(b'durable memory\r\n')
        current = self.root / 'CURRENT.md'
        current.write_bytes(b'unchanged state\r\n')
        revision = 'sha256:' + hashlib.sha256(current.read_bytes()).hexdigest()
        for value in ([], ['METHOD.md'], None, 'METHOD.md', {}, False, 0):
            with self.subTest(value=value):
                manifest = self.write_manifest(methods=value)
                before = (manifest.read_bytes(), memory.read_bytes(), current.read_bytes())
                result = await self.observe()
                self.assertEqual(result['status'], 'manifest_invalid')
                self.assertEqual(result['reason'], 'ManifestSchemaInvalid')
                self.assertNotIn('canonical_pointers', result)
                wire = await server.mcp.call_tool('current_state_update', {
                    'project_ref': 'project', 'expected_revision': revision, 'content': 'overwrite'})
                self.assertEqual(wire.structured_content['error_type'], 'ProjectManifestUnavailable')
                self.assertEqual(before, (manifest.read_bytes(), memory.read_bytes(), current.read_bytes()))

    async def test_unrouted_legacy_method_files_do_not_gate_continuity(self):
        (self.root / 'MEMORY.md').write_text('memory')
        self.write_manifest()
        legacy = self.root / '.principal/methods'
        legacy.mkdir()
        # Leftover files have no routing or readability dependency.
        (legacy / 'resume.md').symlink_to(self.root / 'missing.md')
        result = await self.observe()
        self.assertEqual(result['current_state']['revision'], 'missing')
        self.assertEqual(result['canonical_pointers'], {'rules': ['README.md'], 'memory': 'MEMORY.md'})
        created = await server.checkpoint('project', 'current judgment', 'missing')
        self.assertTrue(created['ok'], created)
        self.assertTrue((await self.observe())['ready'])

    async def test_manifest_requires_exact_keys_types_and_nonempty_rules(self):
        malformed = [
            {'version': value} for value in (True, False, 1, 2, 2.0, '2', None, 0, 3)
        ] + [
            {'rules': []}, {'rules': 'README.md'}, {'rules': None},
            {'memory': []}, {'memory': None},
            {'takeover': []}, {'slot': 8192}, {'unknown': True},
        ]
        for data in malformed:
            with self.subTest(data=data):
                self.write_manifest(**data)
                self.assertEqual((await self.observe())['status'], 'manifest_invalid')
        path = self.write_manifest()
        data = json.loads(path.read_text())
        for removed in ('memory', 'current_state', 'rules'):
            with self.subTest(removed=removed):
                path.write_text(json.dumps({k: v for k, v in data.items() if k != removed}))
                self.assertEqual((await self.observe())['status'], 'manifest_invalid')
        for legacy in (
                {'version': 1, 'rules': ['README.md'], 'takeover': [], 'current_state': 'CURRENT.md'},
                {'version': 2, 'rules': ['README.md'], 'current_state': 'CURRENT.md', 'memory': 'MEMORY.md'},
        ):
            path.write_text(json.dumps(legacy))
            self.assertEqual((await self.observe())['reason'], 'ManifestSchemaInvalid')

    async def test_rejects_duplicate_json_keys_and_pointer_aliases(self):
        path = self.write_manifest()
        path.write_text('{"rules":["README.md"],"rules":["README.md"],'
                        '"current_state":"CURRENT.md","memory":"MEMORY.md"}')
        self.assertEqual((await self.observe())['reason'], 'ManifestJsonInvalid')
        for overrides in (
                {'rules': ['README.md', 'README.md']},
                {'memory': 'CURRENT.md'}, {'memory': 'README.md'},
                {'current_state': 'README.md'},
                {'memory': '.principal/project.json'},
                {'rules': ['.principal/project.json']}):
            with self.subTest(overrides=overrides):
                self.write_manifest(**overrides)
                self.assertEqual((await self.observe())['status'], 'manifest_invalid')

    async def test_path_boundaries_apply_to_all_surviving_routes(self):
        for path in ('../outside', '/absolute', '.git/config', 'nested/../file',
                     'nested//file', 'nested/./file', 'nested\\file', '', ' file',
                     'file\x00', 'a' * (continuity.MAX_PROJECT_PATH_CHARS + 1), 7):
            for field in ('memory', 'current_state', 'rules'):
                with self.subTest(path=path, field=field):
                    self.write_manifest(**{field: [path] if field == 'rules' else path})
                    self.assertEqual((await self.observe())['reason'], 'ManifestPathInvalid')

    async def test_total_pointer_budget_includes_state_and_memory(self):
        (self.root / 'MEMORY.md').write_text('memory')
        (self.root / 'CURRENT.md').write_text('state')
        rules = [f'RULE-{i}.md' for i in range(continuity.MAX_PROJECT_POINTERS - 2)]
        for path in rules:
            (self.root / path).write_text('rule')
        self.write_manifest(rules=rules)
        self.assertTrue((await self.observe())['ready'])
        self.write_manifest(rules=rules + ['EXTRA-RULE.md'])
        self.assertEqual((await self.observe())['reason'], 'ManifestPointerCountInvalid')

    async def test_manifest_paths_require_unicode_scalars(self):
        base = {'rules': ['README.md'], 'current_state': 'CURRENT.md',
                'memory': 'MEMORY.md'}
        for field in base:
            for invalid in ('bad-\ud800.md', 'bad-\udc80.md'):
                with self.subTest(field=field, invalid=repr(invalid)):
                    data = dict(base)
                    data[field] = [invalid] if field == 'rules' else invalid
                    path = self.write_manifest()
                    path.write_text(json.dumps(data), encoding='utf-8')
                    self.assertEqual((await self.observe())['reason'], 'ManifestPathInvalid')
        # Ordinary Unicode paths stay supported; no ASCII-only path policy is added.
        memory = '记忆-😀.md'
        (self.root / memory).write_text('memory', encoding='utf-8')
        (self.root / 'CURRENT.md').write_text('state', encoding='utf-8')
        self.write_manifest(memory=memory)
        result = await self.observe()
        self.assertTrue(result['ready'])
        self.assertEqual(result['canonical_pointers']['memory'], memory)

    async def test_missing_or_unsafe_dependencies_refuse_publication(self):
        current = self.root / 'CURRENT.md'
        current.write_text('unchanged')
        revision = 'sha256:' + hashlib.sha256(current.read_bytes()).hexdigest()
        outside = Path(self._temp.name) / 'outside.md'
        outside.write_text('outside')
        memory = self.root / 'MEMORY.md'
        rule = self.root / 'RULE.md'
        for field, pointer in (('memory', memory), ('rules', rule)):
            for kind in ('missing', 'symlink', 'directory'):
                with self.subTest(field=field, kind=kind):
                    memory.write_text('memory')
                    rule.write_text('rule')
                    pointer.unlink()
                    if kind == 'symlink':
                        pointer.symlink_to(outside)
                    elif kind == 'directory':
                        pointer.mkdir()
                    self.write_manifest(rules=['RULE.md'])
                    observed = await self.observe()
                    self.assertEqual(observed['status'], 'canonical_pointer_unavailable')
                    result = await server.checkpoint('project', 'overwrite', revision)
                    self.assertEqual(result['error_type'], 'ProjectManifestUnavailable')
                    self.assertEqual(current.read_text(), 'unchanged')
                    self.assertEqual(outside.read_text(), 'outside')
                    if pointer.is_dir():
                        pointer.rmdir()
                    elif pointer.is_symlink():
                        pointer.unlink()

    async def test_nested_symlink_and_missing_parent_fail_closed(self):
        outside = Path(self._temp.name) / 'outside'
        outside.mkdir()
        (outside / 'MEMORY.md').write_text('outside')
        (self.root / 'linked').symlink_to(outside, target_is_directory=True)
        for memory in ('linked/MEMORY.md', 'absent/MEMORY.md'):
            self.write_manifest(memory=memory)
            self.assertEqual((await self.observe())['status'], 'canonical_pointer_unavailable')

    async def test_state_create_edit_conflict_and_memory_isolation(self):
        memory = self.root / 'MEMORY.md'
        memory.write_bytes(b'durable memory\r\n')
        manifest = self.write_manifest()
        initial = (manifest.read_bytes(), memory.read_bytes())
        self.assertEqual((await self.observe())['current_state']['revision'], 'missing')
        wire = await server.mcp.call_tool('current_state_update', {
            'project_ref': 'project', 'expected_revision': 'missing', 'content': 'first\r\n'})
        created = wire.structured_content
        self.assertTrue(created['ok'])
        self.assertEqual(created['path'], 'CURRENT.md')
        current = self.root / created['path']
        current.chmod(0o640)
        wire = await server.mcp.call_tool('current_state_update', {
            'project_ref': 'project', 'expected_revision': created['revision'],
            'edits': [{'old_text': 'first', 'new_text': 'second'}]})
        self.assertTrue(wire.structured_content['ok'])
        self.assertEqual(current.read_bytes(), b'second\r\n')
        self.assertEqual(current.stat().st_mode & 0o777, 0o640)
        refused = await server.checkpoint('project', 'stale', created['revision'])
        self.assertEqual(refused['error_type'], 'CheckpointConflict')
        self.assertEqual(current.read_bytes(), b'second\r\n')
        self.assertEqual(initial, (manifest.read_bytes(), memory.read_bytes()))

    async def test_publication_preserves_slot_and_whole_file_guards(self):
        (self.root / 'MEMORY.md').write_text('memory')
        self.write_manifest()
        content = ('<!-- bridge-state-slot start limit=1024 -->\n'
                   'state\n<!-- bridge-state-slot end -->\n')
        created = await server.checkpoint('project', content, 'missing')
        self.assertTrue(created['ok'])
        removed = await server.checkpoint('project', 'no slot', created['revision'])
        self.assertEqual(removed['error_type'], 'CheckpointSlotRejected')
        oversized = await server.checkpoint('project', 'x' * 65537, created['revision'])
        self.assertEqual(oversized['error_type'], 'InvalidCheckpointContent')
        self.assertEqual((self.root / 'CURRENT.md').read_text(), content)

    async def test_versioned_or_takeover_shape_is_not_canonical(self):
        manifest = self.write_manifest()
        manifest.write_text(json.dumps({'version': 1, 'rules': ['README.md'],
                                        'takeover': ['README.md', 'CURRENT.md'],
                                        'current_state': 'CURRENT.md'}))
        (self.root / 'CURRENT.md').write_text('state')
        result = await self.observe()
        self.assertFalse(result['ready'])
        self.assertEqual(result['status'], 'manifest_invalid')
        self.assertEqual(result['reason'], 'ManifestSchemaInvalid')
        self.assertNotIn('manifest_version', result)
        self.assertNotIn('canonical_pointers', result)
