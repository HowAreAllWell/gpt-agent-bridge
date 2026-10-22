"""FULL packaging with synthetic sources only; never import test_preparation."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import stat
import tempfile
import unittest
from unittest.mock import patch
import zipfile

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('distribution_builder', ROOT / 'scripts/build-distribution.py')
build = importlib.util.module_from_spec(spec)
spec.loader.exec_module(build)
SKILLS = ('project-onboarding', 'project-resume', 'handoff-preparation', 'team-deliberation')
MATERIAL = tuple('skills/' + name + '/SKILL.md' for name in SKILLS) + ('LICENSE',)


class DistributionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='bridge-distribution-')
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.source = self.base / 'source'
        self.source.mkdir(mode=0o700)
        self.names = {'prepare', 'scripts/prepare-bridge.py', 'scripts/prepare-system.py',
                      'scripts/release-assets.json', 'src/gpt_agent_bridge/browser_notifications.py',
                      'browser-extension/extension/manifest.json', 'browser-extension/extension/projects.js',
                      'browser-extension/extension/connection.js', 'browser-extension/extension/private-note.txt',
                      'templates/WEB-PRINCIPAL-CORE.md', 'plugin.json', '.app.example.json',
                      'skills/project-onboarding/notes.md', *MATERIAL}
        for name in self.names - {'browser-extension/extension/connection.js'}:
            path = self.source / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(('synthetic public fixture: ' + name + '\n').encode())
        (self.source / 'prepare').chmod(0o700)
        self.addCleanup(patch.stopall)
        patch.object(build.subprocess, 'check_output', side_effect=lambda *a, **kw:
                     ('\0'.join(sorted(self.names)) + '\0').encode()).start()
        patch.object(build.subprocess, 'run', side_effect=AssertionError('external command forbidden')).start()

    def freeze(self, name='output'):
        output = self.base / name
        manifest = build.build(self.source, output)
        return output, manifest

    def test_material_zip_exact_regular_entries_and_frozen_bytes(self):
        output, manifest = self.freeze()
        archive = output / 'Bridge-Skills.zip'
        with zipfile.ZipFile(archive) as z:
            self.assertIsNone(z.testzip())
            self.assertEqual(z.namelist(), list(MATERIAL))
            self.assertEqual(len(z.namelist()), 5)
            self.assertEqual(len(z.namelist()), len(set(z.namelist())))
            self.assertTrue(set(z.namelist()).isdisjoint({
                'plugin.json', '.app.json', '.app.example.json',
                'browser-extension/extension/private-note.txt',
                'skills/project-onboarding/notes.md'}))
            for entry in z.infolist():
                self.assertFalse(entry.is_dir())
                self.assertTrue(stat.S_ISREG(entry.external_attr >> 16))
                self.assertEqual(entry.compress_type, zipfile.ZIP_STORED)
                self.assertFalse(entry.filename.startswith('/'))
                self.assertNotIn('..', Path(entry.filename).parts)
                self.assertEqual(z.read(entry), (output / entry.filename).read_bytes())
        record = json.loads((output / 'release-manifest.json').read_text())
        self.assertEqual(record, {'version': 1, 'files': manifest, 'executables': ['prepare']})
        self.assertEqual(set(manifest), self.names | {'.app.json', 'Bridge-Skills.zip'})
        for name, digest in manifest.items():
            self.assertEqual(hashlib.sha256((output / name).read_bytes()).hexdigest(), digest)

    def test_material_zip_deterministic_despite_source_metadata_changes(self):
        first, _ = self.freeze('first')
        for name in MATERIAL:
            os.utime(self.source / name, (1700000000, 1700000000))
            (self.source / name).chmod(0o644)
        second, _ = self.freeze('second')
        self.assertEqual((first / 'Bridge-Skills.zip').read_bytes(), (second / 'Bridge-Skills.zip').read_bytes())

    def test_archive_uses_frozen_payload_if_source_changes_after_copy(self):
        original = Path.read_bytes
        changed = self.source / MATERIAL[0]
        staged = self.base / 'output' / MATERIAL[0]
        observed = []
        def read(path):
            data = original(path)
            if path == staged:
                changed.write_bytes(b'source edited after copy\n')
                observed.append(path)
            return data
        with patch.object(Path, 'read_bytes', read):
            output, _ = self.freeze()
        self.assertEqual(observed, [staged])
        with zipfile.ZipFile(output / 'Bridge-Skills.zip') as z:
            self.assertEqual(z.read(MATERIAL[0]), (output / MATERIAL[0]).read_bytes())
            self.assertNotEqual(z.read(MATERIAL[0]), changed.read_bytes())

    def test_connection_and_app_generated_without_source_metadata_or_reads(self):
        protected = {self.source / 'browser-extension/extension/connection.js', self.source / '.app.json'}
        protected_names = {path.name for path in protected}
        original_open = build.os.open
        def guard(method):
            def call(path, *args, **kwargs):
                if path in protected:
                    raise AssertionError('protected source path accessed')
                return method(path, *args, **kwargs)
            return call
        def open_guard(path, flags, *args, **kwargs):
            if Path(os.fspath(path)) in protected or \
                    (kwargs.get('dir_fd') is not None and os.fspath(path) in protected_names):
                raise AssertionError('protected source path opened')
            return original_open(path, flags, *args, **kwargs)
        with patch.object(build.os, 'open', open_guard), \
             patch.object(Path, 'stat', guard(Path.stat)), \
             patch.object(Path, 'lstat', guard(Path.lstat)), \
             patch.object(Path, 'is_symlink', guard(Path.is_symlink)), \
             patch.object(Path, 'resolve', guard(Path.resolve)), \
             patch.object(Path, 'open', guard(Path.open)):
            output, _ = self.freeze()
        self.assertEqual((output / 'browser-extension/extension/connection.js').read_bytes(), b'export const connection = null;\n')
        self.assertEqual((output / '.app.json').read_bytes(), build.PLACEHOLDER)

    def test_missing_license_refused_before_destination_created(self):
        self.names.remove('LICENSE')
        with self.assertRaisesRegex(ValueError, 'INCOMPLETE_CANDIDATE'):
            self.freeze()
        self.assertFalse((self.base / 'output').exists())

    def test_duplicate_or_traversing_candidate_names_rejected(self):
        for inventory in (sorted(self.names) + [sorted(self.names)[0]],
                          sorted(self.names | {'skills/../outside'})):
            with self.subTest(inventory=inventory[-2:]):
                result = ('\0'.join(inventory) + '\0').encode()
                with patch.object(build.subprocess, 'check_output', return_value=result):
                    with self.assertRaisesRegex(ValueError, 'UNSAFE_CANDIDATE_PATH'):
                        self.freeze()
                self.assertFalse((self.base / 'output').exists())

    def test_symlink_material_input_rejected(self):
        skill = self.source / MATERIAL[0]
        skill.unlink()
        skill.symlink_to(self.source / 'LICENSE')
        with self.assertRaisesRegex(ValueError, 'SOURCE_NOT_REGULAR'):
            self.freeze()

    def test_symlinked_material_parent_cannot_read_outside_source(self):
        shipped = self.source / 'skills/project-onboarding'
        outside = self.base / 'outside-material'
        outside.mkdir(mode=0o700)
        (outside / 'SKILL.md').write_bytes(b'outside sentinel\n')
        shipped.rename(self.base / 'held-onboarding')
        shipped.symlink_to(outside, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, 'SOURCE_NOT_REGULAR'):
            self.freeze()
        self.assertFalse((self.base / 'output' / 'Bridge-Skills.zip').exists())

    def test_material_leaf_swapped_to_symlink_before_open_rejected(self):
        leaf = self.source / 'LICENSE'
        outside = self.base / 'outside-license'
        outside.write_bytes(b'outside sentinel\n')
        original_open = build.os.open
        observed = []
        def swapping_open(path, flags, *args, **kwargs):
            if not observed and kwargs.get('dir_fd') is not None and os.fspath(path) == 'LICENSE':
                leaf.unlink()
                leaf.symlink_to(outside)
                observed.append(path)
            return original_open(path, flags, *args, **kwargs)
        with patch.object(build.os, 'open', swapping_open):
            with self.assertRaisesRegex(ValueError, 'SOURCE_NOT_REGULAR'):
                self.freeze()
        self.assertEqual(observed, ['LICENSE'])
        self.assertFalse((self.base / 'output' / 'Bridge-Skills.zip').exists())

    def test_material_changed_during_read_rejected(self):
        leaf = self.source / 'LICENSE'
        leaf_stat = leaf.stat()
        leaf_identity = (leaf_stat.st_dev, leaf_stat.st_ino)
        original_read = build.os.read
        observed = []
        def changing_read(fd, size):
            data = original_read(fd, size)
            opened = os.fstat(fd)
            if data and not observed and (opened.st_dev, opened.st_ino) == leaf_identity:
                observed.append(fd)
                with leaf.open('ab') as stream:
                    stream.write(b'changed during read\n')
            return data
        with patch.object(build.os, 'read', side_effect=changing_read):
            with self.assertRaisesRegex(ValueError, 'SOURCE_CHANGED'):
                self.freeze()
        self.assertEqual(len(observed), 1)

    def test_bilingual_docs_preserve_named_safe_source_bytes(self):
        for english in ('README.md', 'docs/GETTING-STARTED.md', 'docs/TECHNICAL-REFERENCE.md'):
            chinese = str(Path(english).with_suffix('.zh-CN.md'))
            for name in (english, chinese):
                target = self.source / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes((ROOT / name).read_bytes())
                self.names.add(name)
        output, _ = self.freeze()
        for name in self.names:
            if name.endswith('.md'):
                self.assertEqual((output / name).read_bytes(), (self.source / name).read_bytes())
