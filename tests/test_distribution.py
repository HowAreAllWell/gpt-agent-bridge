"""A complete release, not an editable checkout accidentally finding untracked files."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from tests.test_preparation import module,prep,ROOT
build=module('build-distribution.py')

class DistributionTests(unittest.TestCase):
    def assert_bilingual_docs(self, source, manifest):
        for english in ('README.md', 'docs/GETTING-STARTED.md', 'docs/TECHNICAL-REFERENCE.md'):
            chinese = str(Path(english).with_suffix('.zh-CN.md'))
            for path in (english, chinese):
                self.assertIn(path, manifest)
                text = (source / path).read_text(encoding='utf-8')
                for label, target in (('English', english), ('简体中文', chinese)):
                    name = Path(target).name
                    self.assertIn(f'[{label}]({name})', text)
                    self.assertTrue((source / path).parent.joinpath(name).is_file())

    def test_release_prepare_first_repeat_interruption_and_identity(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);source=root/'release';target=root/'installed'
            manifest=build.build(ROOT,source)
            self.assert_bilingual_docs(source, manifest)
            self.assertIn('scripts/prepare-system.py',manifest)
            self.assertIn('browser-extension/extension/wiring.js',manifest)
            self.assertEqual(len([n for n in manifest if n.startswith('skills/') and n.endswith('/SKILL.md')]),4)
            self.assertTrue((source/'LICENSE').is_file())
            self.assertNotIn('.principal/project.json',manifest)
            self.assertIn('asdk_app_REPLACE_WITH_OWN_APP_ID',(source/'.app.json').read_text())
            self.assertIn('connection = null',(source/'browser-extension/extension/connection.js').read_text())
            # Exact partial copy from an interrupted first entry is recoverable.
            target.mkdir(mode=0o700);prep.publish(target/'README.md',(source/'README.md').read_bytes())
            prep.prepare_copy(source,target);before=prep.release_files(target)
            prep.prepare_copy(source,target);self.assertEqual(prep.release_files(target),before)
            (target/'scripts/prepare-system.py').write_text('changed user file')
            with self.assertRaises(prep.Refusal):prep.prepare_copy(source,target)
            self.assertEqual((target/'scripts/prepare-system.py').read_text(),'changed user file')
    def test_incomplete_release_fails_before_installed_writes(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);source=root/'release';build.build(ROOT,source)
            (source/'skills/project-resume/SKILL.md').unlink()
            with self.assertRaises(FileNotFoundError):prep.prepare_copy(source,root/'installed')
            self.assertFalse((root/'installed').exists())

    def test_bilingual_docs_in_owned_fixture_without_checkout_build(self):
        # Explicit synthetic inventory: never build the dirty public checkout.
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            fixture = root / 'source'
            fixture.mkdir(mode=0o700)
            names = {'prepare', 'scripts/prepare-bridge.py', 'scripts/prepare-system.py',
                     'scripts/release-assets.json', 'src/gpt_agent_bridge/browser_notifications.py',
                     'browser-extension/extension/manifest.json', 'browser-extension/extension/projects.js',
                     'templates/WEB-PRINCIPAL-CORE.md', 'LICENSE'}
            names.update(f'skills/{name}/SKILL.md' for name in
                         ('project-resume', 'project-onboarding', 'handoff-preparation', 'team-deliberation'))
            for name in names:
                path = fixture / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b'synthetic nonsecret fixture\n')
            for english in ('README.md', 'docs/GETTING-STARTED.md', 'docs/TECHNICAL-REFERENCE.md'):
                for name in (english, str(Path(english).with_suffix('.zh-CN.md'))):
                    path = fixture / name
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_bytes((ROOT / name).read_bytes())
                    names.add(name)
            inventory = ('\0'.join(sorted(names)) + '\0').encode()
            with patch.object(build.subprocess, 'check_output', return_value=inventory) as listed:
                manifest = build.build(fixture, root / 'output')
            listed.assert_called_once()
            self.assert_bilingual_docs(root / 'output', manifest)

    def test_connection_is_generated_without_any_source_file_access(self):
        # The source pairing path need not exist and must never be inspected,
        # even to check its type, permissions, symlink target or content.
        import hashlib
        import json
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            source = root / 'source'
            source.mkdir(mode=0o700)
            names = {'prepare', 'scripts/prepare-bridge.py', 'scripts/prepare-system.py',
                     'scripts/release-assets.json', 'src/gpt_agent_bridge/browser_notifications.py',
                     'browser-extension/extension/manifest.json', 'browser-extension/extension/projects.js',
                     'templates/WEB-PRINCIPAL-CORE.md', 'browser-extension/extension/connection.js'}
            names.update(f'skills/{name}/SKILL.md' for name in
                         ('project-resume', 'project-onboarding', 'handoff-preparation', 'team-deliberation'))
            private = source / 'browser-extension/extension/connection.js'
            for name in names - {'browser-extension/extension/connection.js'}:
                path = source / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b'synthetic public file\n')
            inventory = ('\0'.join(sorted(names)) + '\0').encode()
            touched = []

            def protected(method):
                def call(path, *args, **kwargs):
                    if path == private:
                        touched.append(method.__name__)
                        raise AssertionError('SOURCE_CONNECTION_ACCESSED')
                    return method(path, *args, **kwargs)
                return call

            output = root / 'output'
            with patch.object(build.subprocess, 'check_output', return_value=inventory), \
                 patch.object(Path, 'stat', protected(Path.stat)), \
                 patch.object(Path, 'lstat', protected(Path.lstat)), \
                 patch.object(Path, 'is_symlink', protected(Path.is_symlink)), \
                 patch.object(Path, 'resolve', protected(Path.resolve)), \
                 patch.object(Path, 'open', protected(Path.open)):
                manifest = build.build(source, output)
            self.assertEqual(touched, [])
            literal = b'export const connection = null;\n'
            target = output / 'browser-extension/extension/connection.js'
            self.assertEqual(target.read_bytes(), literal)
            self.assertEqual(target.stat().st_mode & 0o777, 0o600)
            self.assertEqual(manifest['browser-extension/extension/connection.js'],
                             hashlib.sha256(literal).hexdigest())
            self.assertEqual(set(manifest), names | {'.app.json'})
            self.assertEqual(set(output.rglob('*')) - {p for p in output.rglob('*') if p.is_dir()},
                             {output / name for name in manifest} | {output / 'release-manifest.json'})
            record = json.loads((output / 'release-manifest.json').read_text())
            self.assertEqual(record, {'version': 1, 'files': manifest, 'executables': []})
            for name, digest in record['files'].items():
                self.assertEqual(hashlib.sha256((output / name).read_bytes()).hexdigest(), digest)
            self.assertFalse(private.exists())
