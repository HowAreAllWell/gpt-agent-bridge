"""Canonical cognition routing through public tools; all writes stay in disposable fixtures."""
import hashlib
import json
import unittest
from unittest.mock import patch

from tests import test_project_continuity as fixtures
from tests.continuity_fixture import MEMORY_TEXT, STATE_TEXT, write_canonical_cognition
import server
from project_continuity import classify_state_slot

class CognitionCutoverTests(unittest.IsolatedAsyncioTestCase):
    setUp = fixtures.ProjectContinuityTests.setUp

    def copy_cognition(self):
        return write_canonical_cognition(self.root)

    async def overview(self, ref=None):
        with patch.object(server, '_deployment_snapshot', return_value={'observed': False}):
            return await server.bridge_overview(ref)

    async def test_context_and_default_overview_route_cognition_without_ledger(self):
        manifest = self.copy_cognition()
        context = await server.context('project')
        result = await self.overview()
        projection = result['project_state']
        self.assertTrue(result['ok'])
        self.assertEqual(projection['continuity'], context['continuity'])
        self.assertNotIn('manifest_version', projection['continuity'])
        self.assertNotIn('evolution_findings', projection)
        self.assertFalse(hasattr(server, '_evolution_findings_summary'))
        self.assertFalse(hasattr(server, '_valid_iso_date'))
        docs = {row['name']: row for row in projection['documents']}
        for path in manifest['rules'] + [manifest['current_state'], manifest['memory']]:
            self.assertTrue(docs[path]['available'])
            self.assertEqual(docs[path]['path'], str(self.root / path))
        self.assertNotIn('methods', context['continuity']['canonical_pointers'])
        self.assertFalse(any(path.startswith('.principal/methods/') for path in docs))
        serialized = json.dumps(projection['continuity'])
        self.assertNotIn('Standing checkpoint authority', serialized)
        self.assertNotIn('Bridge current decision position', serialized)
        self.assertNotIn('takeover', serialized)
        self.assertNotIn(STATE_TEXT.strip(), serialized)
        self.assertNotIn(MEMORY_TEXT.strip(), serialized)

    async def test_noncanonical_manifest_is_not_adopted(self):
        self.copy_cognition()
        (self.root / 'legacy.md').write_text('legacy state', encoding='utf-8')
        (self.root / '.principal/project.json').write_text(json.dumps({
            'version': 1, 'rules': ['README.md'], 'takeover': ['legacy.md'],
            'current_state': 'legacy.md'}), encoding='utf-8')
        projection = (await self.overview())['project_state']
        docs = {row['name'] for row in projection['documents']}
        self.assertNotIn('legacy.md', docs)
        self.assertNotIn('.principal/state.md', docs)
        self.assertNotIn('.principal/memory.md', docs)
        self.assertNotIn('manifest_version', projection['continuity'])
        self.assertFalse(projection['continuity']['ready'])
        self.assertEqual(projection['continuity']['status'], 'manifest_invalid')

    async def test_missing_invalid_or_unsafe_manifest_keeps_diagnostics_honest(self):
        manifest = self.copy_cognition()
        path = self.root / '.principal/project.json'
        path.unlink()
        for value, status in ((None, 'manifest_missing'), ({**manifest, 'memory': None}, 'manifest_invalid'),
                              ({**manifest, 'memory': 'absent.md'}, 'canonical_pointer_unavailable')):
            if value is not None:
                path.write_text(json.dumps(value), encoding='utf-8')
            result = await self.overview()
            self.assertTrue(result['ok'])
            continuity = result['project_state']['continuity']
            self.assertFalse(continuity['ready'])
            self.assertEqual(continuity['status'], status)
            self.assertNotIn('evolution_findings', result['project_state'])

    async def test_slotless_publication_preserves_memory_and_revision_guard(self):
        manifest = self.copy_cognition()
        state = self.root / manifest['current_state']
        memory = self.root / manifest['memory']
        before = memory.read_bytes()
        original = state.read_bytes()
        self.assertEqual(classify_state_slot(original)['kind'], 'absent')
        revision = 'sha256:' + hashlib.sha256(original).hexdigest()
        result = await server.mcp.call_tool('current_state_update', {
            'project_ref': 'project', 'expected_revision': revision,
            'content': 'A replacement current position.\n'})
        self.assertTrue(result.structured_content['ok'])
        stale = await server.checkpoint('project', 'stale overwrite', revision)
        self.assertEqual(stale['error_type'], 'CheckpointConflict')
        self.assertEqual(state.read_text(), 'A replacement current position.\n')
        self.assertEqual(memory.read_bytes(), before)
        self.assertEqual(classify_state_slot(state.read_bytes())['kind'], 'absent')
