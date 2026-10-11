"""Cognition ownership and active navigation contracts."""
import json
from pathlib import Path
import re
import tempfile
import unittest

from tests.continuity_fixture import write_canonical_cognition

from project_continuity import MAX_CHECKPOINT_CONTENT_BYTES, classify_state_slot

ROOT = Path(__file__).resolve().parents[1]
RETIRED = ('GPT-Agent-Bridge-HANDOFF.md', 'PRINCIPAL-OPERATIONS.md',
           'PRINCIPAL-EVOLUTION.md', 'EVOLUTION-CONTRACT.md', 'PRINCIPAL-TOOL-CONTRACT.md')


def active_documents():
    return ([ROOT / 'README.md', ROOT / 'AGENTS.md'] + sorted((ROOT / 'docs').glob('*.md'))
            + sorted((ROOT / 'skills').rglob('*.md')))


class DocumentOwnershipTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.cognition_root = Path(temporary.name)
        write_canonical_cognition(self.cognition_root)

    def test_observation_tools_read_boundary_without_extraction(self):
        # Active public contract: read refuses PDF/DOCX by suffix; attachments
        # handle originals. The retired extractor is gone and must not return.
        text = (ROOT / "docs/OBSERVATION-TOOLS.md").read_text()
        self.assertIn("refuses PDF/DOCX", text)
        self.assertIn("UnsupportedReadFormat", text)
        self.assertIn("prepare_file_attachment", text)
        self.assertNotIn("document_observation", text)
        self.assertNotIn("PRIVATE HISTORICAL", text)
        self.assertNotIn("pdftotext", text)


    def test_synthetic_manifest_is_canonical_and_state_is_slotless(self):
        self.assertFalse((ROOT / '.principal').exists())
        manifest = json.loads((self.cognition_root / '.principal/project.json').read_text())
        self.assertEqual(set(manifest), {'rules', 'current_state', 'memory'})
        self.assertNotIn('version', manifest)
        self.assertEqual(manifest['rules'], ['AGENTS.md'])
        self.assertEqual(manifest['current_state'], '.principal/state.md')
        self.assertEqual(manifest['memory'], '.principal/memory.md')
        paths = manifest['rules'] + [manifest['current_state'], manifest['memory']]
        self.assertEqual(len(paths), len(set(paths)))
        for path in paths:
            self.assertTrue((self.cognition_root / path).is_file(), path)
        state = (self.cognition_root / manifest['current_state']).read_bytes()
        state.decode('utf-8')
        self.assertLessEqual(len(state), MAX_CHECKPOINT_CONTENT_BYTES)
        self.assertEqual(classify_state_slot(state)['kind'], 'absent')

    def test_retired_owners_and_machine_regions_are_absent(self):
        for name in RETIRED:
            self.assertFalse((ROOT / name).exists())
            self.assertFalse((ROOT / 'docs' / name).exists())
            self.assertFalse((ROOT / '.principal' / name).exists())
        self.assertFalse((ROOT / 'tests/test_evolution_contract.py').exists())
        self.assertFalse((ROOT / 'tests/test_evolution_observability.py').exists())
        for path in (self.cognition_root / '.principal/state.md', self.cognition_root / '.principal/memory.md'):
            text = path.read_text()
            for machine_region in ('## Open evolution findings', 'Next EVO ID:', 'Retired IDs:',
                                   '## Fix-now evidence ledger', 'Evidence/Rationale:', 'Last-reviewed:'):
                self.assertNotIn(machine_region, text)

    def test_shared_rules_isolate_cognition_without_role_authority(self):
        shared = (ROOT / 'AGENTS.md').read_text()
        self.assertIn('Repository purpose never assigns a role', shared)
        self.assertIn('Ordinary Agents do', shared)
        self.assertIn('not read or modify it unless their assigned task explicitly concerns', shared)
        for path in (ROOT / 'AGENTS.md', ROOT / 'docs/PROJECT-CONTINUITY.md'):
            text = path.read_text().lower()
            self.assertNotIn('standing authority', text)
            self.assertNotIn('per-commit approval', text)
            self.assertNotIn('mandatory evolution', text)
        memory = (self.cognition_root / '.principal/memory.md').read_text()
        self.assertIn('standing authority', memory)
        self.assertIn('currently authorized project/work', memory)
        self.assertIn('Narrower task restrictions', memory)
        self.assertIn('Ordinary Agents', memory)
        self.assertIn('service restart', memory)

    def test_active_document_links_resolve(self):
        for path in active_documents():
            for link in re.findall(r'\[[^\]\n]+\]\(([^)]+)\)', path.read_text()):
                if '://' in link or link.startswith('#'):
                    continue
                with self.subTest(path=str(path.relative_to(ROOT)), link=link):
                    self.assertTrue((path.parent / link.split('#', 1)[0]).exists(), link)

    def test_active_public_documents_have_no_deleted_owner_references(self):
        source_paths = active_documents() + [ROOT / name for name in
                                           ('server.py', 'widget_watcher.py', 'project_continuity.py')]
        for path in source_paths:
            text = path.read_text()
            for name in RETIRED:
                self.assertNotIn(name, text, str(path))
            self.assertNotIn('docs/web-principal-methods', text, str(path))
        server_source = (ROOT / 'server.py').read_text()
        self.assertNotIn('_evolution_findings_summary', server_source)
        self.assertNotIn('evolution_findings', server_source)
        self.assertNotIn('MAX_EVOLUTION_FINDINGS', server_source)

    def test_principal_methods_are_retired_without_local_forwarders(self):
        self.assertFalse(any((ROOT / '.principal/methods').rglob('*')))
        self.assertFalse((ROOT / 'docs/web-principal-methods').exists())
        self.assertFalse((ROOT / 'docs/web-principal-skills').exists())
        self.assertEqual(list((ROOT / '.principal').rglob('SKILL.md')), [])
        self.assertEqual(list((ROOT / '.principal').rglob('AGENTS.md')), [])
        for path in active_documents():
            text = path.read_text()
            self.assertNotIn('.principal/methods', text, str(path))
            self.assertNotIn('local methods', text, str(path))

    def test_same_plugin_source_bundle_owns_reusable_procedures(self):
        package = json.loads((ROOT / 'plugin.json').read_text())
        self.assertEqual(package['name'], 'gpt-agent-bridge')
        self.assertEqual(package['$schema'], 'https://agent-plugins.org/schemas/1.0.0/plugin.schema.json')
        skills = {path.parent.name: path for path in (ROOT / 'skills').glob('*/SKILL.md')}
        self.assertEqual(set(skills), {'project-resume', 'handoff-preparation', 'project-onboarding', 'team-deliberation'})
        for name, path in skills.items():
            frontmatter = path.read_text().split('---', 2)
            self.assertEqual(frontmatter[0], '')
            fields = dict(line.split(': ', 1) for line in frontmatter[1].strip().splitlines())
            self.assertEqual(set(fields), {'name', 'description'})
            self.assertEqual(fields['name'], name)
            self.assertTrue(fields['description'].strip())
            self.assertTrue(frontmatter[2].strip())

    def test_registered_bridge_binding_path_id_required_and_skills(self):
        package = json.loads((ROOT / 'plugin.json').read_text())
        apps_path = package['extensions']['com.openai']['apps']
        self.assertEqual(apps_path, './.app.json')
        binding = json.loads((ROOT / apps_path).read_text())
        self.assertEqual(binding, {'apps': {'bridge': {
            'id': 'asdk_app_REPLACE_WITH_OWN_APP_ID', 'required': True}}})
        self.assertEqual(binding, json.loads((ROOT / '.app.example.json').read_text()))
        self.assertFalse((ROOT / 'docs/evidence').exists())
        entry = binding['apps']['bridge']
        self.assertRegex(entry['id'], r'\Aasdk_app_[A-Za-z0-9][A-Za-z0-9_-]*\Z')
        self.assertIs(entry['required'], True)
        self.assertEqual({p.name for p in (ROOT / 'skills').iterdir() if p.is_dir()},
                         {'project-resume', 'handoff-preparation', 'project-onboarding', 'team-deliberation'})

    def test_registered_binding_has_no_endpoint_or_distribution_configuration(self):
        package = json.loads((ROOT / 'plugin.json').read_text())
        self.assertEqual(set(package), {'$schema', 'name', 'version', 'description', 'extensions'})
        self.assertEqual(set(package['extensions']['com.openai']), {'apps', 'interface'})
        self.assertEqual(set(package['extensions']['com.openai']['interface']),
                         {'displayName', 'shortDescription'})
        for path in ('mcp.json', '.mcp.json', 'marketplace.json', '.agents/plugins/marketplace.json',
                     '.claude-plugin/marketplace.json'):
            self.assertFalse((ROOT / path).exists(), path)
