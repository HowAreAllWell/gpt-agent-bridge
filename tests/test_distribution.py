"""A complete release, not an editable checkout accidentally finding untracked files."""
from pathlib import Path
import tempfile
import unittest
from tests.test_preparation import module,prep,ROOT
build=module('build-distribution.py')

class DistributionTests(unittest.TestCase):
    def test_release_prepare_first_repeat_interruption_and_identity(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);source=root/'release';target=root/'installed'
            manifest=build.build(ROOT,source)
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
