"""Actual Work classification hook, identity/expiry and unchanged report evidence serving."""
import unittest
from unittest.mock import patch, AsyncMock
from tests import test_work_classification as fixtures
from gpt_agent_bridge.browser_notifications import BrowserNotifications
from gpt_agent_bridge import server

class BrowserNotificationIntegrationTests(unittest.IsolatedAsyncioTestCase):
    setUp = fixtures.WorkClassificationTests.setUp
    asyncTearDown = fixtures.WorkClassificationTests.asyncTearDown
    work = fixtures.WorkClassificationTests.work
    path = fixtures.WorkClassificationTests.path
    settle = fixtures.WorkClassificationTests.settle
    classified = fixtures.WorkClassificationTests.classified
    async def test_agent_discovery_can_exclude_principal_reads_and_git_scope(self):
        with patch.object(server._project_continuity,'describe',side_effect=AssertionError('Principal read forbidden')), \
             patch.object(server,'_project_agent_observation',AsyncMock(return_value={'agents':[]})), \
             patch.object(server,'_git_run_bounded',return_value=(0,'','')) as git:
            result=await server.context('p',include_continuity=False)
            self.assertTrue(result['ok']);self.assertEqual(result['continuity'],{'status':'not_requested'})
            self.assertIn(':(exclude).principal/**',git.call_args.args)

    async def test_discovery_without_continuity_skips_unscoped_checkout_enrichment(self):
        fake={'candidates':[],'skipped_count':0,'candidates_truncated':False,
              'coverage_counts':{'out_of_project':0,'invalid_or_unavailable':0,'truncated':0}}
        with patch.object(server.HerdrBackend,'manual_agent_candidates',AsyncMock(return_value=fake)), \
             patch.object(server.agent_placement,'observe_all',AsyncMock()) as checkout:
            result=await server._discover_project_candidates('p',observe_checkout=False)
            self.assertTrue(result['ok']);checkout.assert_not_called()

    async def test_actual_classification_publishes_only_readable_settled_work_and_expires(self):
        feed=BrowserNotifications({'project_ref':'p','root':str(self.root),'extension_id':'a'*32,'token':'t'*48,'port':8765})
        with patch.object(server,'_BROWSER_NOTIFICATIONS',feed):
            ready=self.work('agent_turn_settled','report bytes')
            missing=self.work('agent_turn_settled')
            running=self.work(text='not terminal')
            await self.classified()
            self.assertEqual(ready['browser_notification_sequence'],1)
            self.assertNotIn('browser_notification_sequence',missing)
            self.assertNotIn('browser_notification_sequence',running)
            read=await server._browser_notification_report(ready)
            self.assertTrue(read['ok']);self.assertFalse(ready.get('report_evidence_served',False))
            server._WORK_REGISTRY.pop(ready['work_ref'])
            self.assertFalse((await server._browser_notification_report(ready))['ok'])
