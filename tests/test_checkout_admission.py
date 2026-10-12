"""Checkout sharing is not a dispatch restriction."""
import unittest
from unittest.mock import patch
from tests import test_work_evidence
from gpt_agent_bridge.evidence_target import EvidenceCheckout
from gpt_agent_bridge import server
from tests.work_observation import delegate_item

class CheckoutAdmissionTests(unittest.IsolatedAsyncioTestCase):
    setUp = test_work_evidence.WorkEvidenceTests.setUp
    work = test_work_evidence.WorkEvidenceTests.work

    async def test_dispatch_admits_second_resource_sharing_bound_checkout(self):
        from tests.test_manual_agents import manual_backend
        backend, state = manual_backend(self.root)
        with patch.object(server, '_WORKSPACE_BACKENDS', {str(self.root): backend}):
            agent = (await server.context('p'))['agents'][0]['handle']
            existing = self.work()
            existing.update(state='running', agent_ref='other', resource_key='other')
            existing['evidence_checkout'] = EvidenceCheckout.capture(self.project, str(self.root))
            accepted = await delegate_item('p', assignments=[{'agent_ref': agent, 'task': 'shared checkout task'}])
            self.assertTrue(accepted['ok'], accepted)
            self.assertEqual(len(server._WORK_REGISTRY), 2)
            self.assertEqual([c[:2] for c in state['calls']].count(('agent', 'prompt')), 1)
            work = server._WORK_REGISTRY[accepted['work_ref']]
            await server._HANDOFF_REGISTRY[work['handoff_id']]['watcher_task']
