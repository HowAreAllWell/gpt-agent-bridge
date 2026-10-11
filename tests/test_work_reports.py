"""Mandatory artifact publication, scoped retrieval and bounded process-local cleanup."""
import asyncio
import hashlib
import json
import os
from pathlib import Path
import unittest
from unittest.mock import AsyncMock, patch

from tests import test_submission_evidence as fixtures
import server
from tests.work_observation import finished_work
import herdr_backend
import work_reports
from tests.work_observation import delegate_item


class WorkReportTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await fixtures.SubmissionEvidenceTests.asyncSetUp(self)
        self.store = work_reports.ReportStore()
        patch.object(server, '_REPORT_STORE', self.store).start()
        patch.object(server, '_EXPIRED_WORK_REFS', {}).start()
        self.addCleanup(self.store.close)
        self.watcher = patch.object(self.backend, 'watch_manual_agent_turn', AsyncMock(return_value={
            'state': 'done', 'reason': 'state_transition_proven', 'post_state_change_seq': 2})).start()

    asyncTearDown = fixtures.SubmissionEvidenceTests.asyncTearDown

    async def settle(self, work):
        await server._HANDOFF_REGISTRY[work['handoff_id']]['watcher_task']
        await asyncio.sleep(0)
        return await finished_work('p', work['work_ref'])

    def path(self, work):
        return Path(self.store._root) / work['report_key']

    def reserve(self, capture=True, terminal=True):
        work = server._reserve_work('p', server._WORKSPACE_REGISTRY.resolve('p'), self.ref, self.candidate)
        if capture:
            work['report_key'] = self.store.allocate()
        if terminal:
            server._latch_work_from_handoff(work['work_ref'], {'state': 'done', 'reason': 'fixture'})
        return work

    async def test_every_delegate_augments_exact_task_once_and_allocates_report(self):
        task = '  exact Unicode task 中文\nkeep trailing space '
        response = await delegate_item('p', assignments=[{'agent_ref': self.ref, 'task': task}])
        self.assertEqual(set(response), {'ok', 'work_ref', 'index', 'agent_ref', 'outcome'})
        work = server._WORK_REGISTRY[response['work_ref']]
        self.assertIn(work['report_key'], self.store._keys)
        prompts = [c[-1] for c in self.state['calls'] if c[:2] == ('agent', 'prompt')]
        self.assertTrue(prompts[-1].startswith(task + '\n\n'))
        self.assertEqual(prompts[-1].count('[Bridge final-report publication]'), 1)
        await self.settle(work)
        self.assertEqual((await server.work_report('p', work['work_ref']))['error_type'], 'WorkReportMissing')

    async def test_capture_one_augmentation_recovery_bytes_and_private_receipts(self):
        recovered = []
        async def recover(expected, pre_seq, pre_rev, *, recovery):
            self.assertIsNotNone(recovery)
            recovered.append(recovery['task'])
            # Exercise the same native prompt seam with the frozen recovery bytes.
            await self.backend.prompt_manual_agent(expected, recovery['task'])
            return {'state': 'done', 'reason': 'fixture', 'agy_recovery_reprompt': True}
        self.watcher.side_effect = recover
        response = await delegate_item('p', assignments=[{'agent_ref': self.ref, 'task': 'original task'}])
        work = server._WORK_REGISTRY[response['work_ref']]
        receipt = await self.settle(work)
        prompts = [c[-1] for c in self.state['calls'] if c[:2] == ('agent', 'prompt')]
        self.assertEqual(len(prompts), 2)
        self.assertEqual(prompts[0], prompts[1])
        self.assertEqual(recovered, [prompts[0]])
        self.assertTrue(prompts[0].startswith('original task\n\n'))
        self.assertEqual(prompts[0].count('[Bridge final-report publication]'), 1)
        # B1 authoring guidance appears exactly once and stays advisory prose.
        self.assertEqual(prompts[0].count('[Report authoring]'), 1)
        self.assertIn("Within the task's requested format, put your conclusion, decisive evidence, "
                      'and material limitations first, followed by supporting detail. '
                      'Headings are optional; keep the complete report free-form. '
                      'Publication does not establish task success, truth, or authenticated '
                      'authorship.', prompts[0])
        self.assertIn(str(self.path(work)), prompts[0])
        self.assertEqual(os.stat(self.store._root).st_mode & 0o777, 0o700)
        self.assertNotIn('bridge-reports-', json.dumps([response, receipt]))
        self.assertEqual(list(self.root.iterdir()), [self.root / '.git'])
        self.assertEqual(receipt, await finished_work('p', work['work_ref']))

    async def test_full_unicode_report_survives_next_turn_and_pages_by_hash(self):
        response = await delegate_item('p', assignments=[{'agent_ref': self.ref, 'task': 'first'}])
        work = server._WORK_REGISTRY[response['work_ref']]
        # Authoring guidance is advisory only: a heading-free free-form report whose
        # default first page opens with conclusion/decisive evidence/limitations and
        # continues into long detail must be retrieved complete with intact hashing.
        opening = ('Conclusion: the bounded fixture check completed.\n'
                   'Decisive evidence: exact byte reconstruction below.\n'
                   'Material limitations: fixture only, no live agent.\n')
        detail_line = '完整😀 report detail line\n'
        content = opening + detail_line * 2000
        # Exact fixture composition: one opening, exactly 2000 repeated detail lines.
        self.assertEqual(content.count(opening), 1)
        self.assertEqual(content.count(detail_line), 2000)
        path = self.path(work)
        staging = Path(str(path) + '.pending')
        staging.write_text(content, encoding='utf-8')
        staging.replace(path)
        receipt = await self.settle(work)
        # Omit limit: exercise the real work_report default page instead of a test-set one.
        first = await server.mcp.call_tool('work_report', {'project_ref': 'p',
            'work_ref': work['work_ref'], 'offset': 0})
        first_meta = first.structured_content
        self.assertTrue(first_meta['ok'], first)
        self.assertEqual(first_meta['content_limit'], 4096)
        self.assertEqual(first_meta['content'], content[:4096])
        self.assertTrue(first_meta['content'].startswith(opening))
        next_turn = await delegate_item('p', assignments=[{'agent_ref': self.ref, 'task': 'second'}])
        await self.settle(server._WORK_REGISTRY[next_turn['work_ref']])
        self.state['text'] = 'new unrelated terminal response'
        joined, offset, digest = [], 0, None
        while True:
            result = await server.mcp.call_tool('work_report', {'project_ref': 'p', 'work_ref': work['work_ref'],
                'offset': offset, 'limit': 4096, 'expected_sha256': digest})
            page = result.structured_content
            self.assertTrue(page['ok'], page)
            self.assertNotIn('bridge-reports-', json.dumps(page))
            joined.append(page['content'])
            digest = page['file_sha256']
            offset = page['content_next_offset']
            if offset is None:
                break
        self.assertEqual(''.join(joined), content)
        self.assertEqual(digest, hashlib.sha256(content.encode()).hexdigest())
        self.assertEqual(page['provenance']['source'], 'agent_published_report')
        self.assertFalse(page['provenance']['provider_transcript'])
        self.assertEqual(receipt, await finished_work('p', work['work_ref']))
        path.write_text('changed', encoding='utf-8')
        changed = await server.work_report('p', work['work_ref'], expected_sha256=digest)
        self.assertEqual(changed['error_type'], 'WorkReportVersionChanged')
        self.assertNotIn('content', changed)
        self.assertFalse(any(c[:2] == ('pane', 'read') for c in self.state['calls']))

    async def test_report_errors_bounds_scope_and_no_follow(self):
        work = self.reserve(terminal=False)
        ref = work['work_ref']
        self.assertEqual((await server.work_report('p', ref))['error_type'], 'WorkReportNotTerminal')
        server._latch_work_from_handoff(ref, {'state': 'needs_attention', 'reason': 'fixture'})
        self.assertEqual((await server.work_report('p', ref))['error_type'], 'WorkReportMissing')
        for raw, expected in [(b'\xff', 'WorkReportInvalidUTF8'), (b'', 'WorkReportEmpty'),
                              (b'x' * (work_reports.MAX_REPORT_BYTES + 1), 'WorkReportTooLarge')]:
            self.path(work).write_bytes(raw)
            self.assertEqual((await server.work_report('p', ref))['error_type'], expected)
        self.path(work).unlink()
        self.path(work).symlink_to('/etc/passwd')
        self.assertEqual((await server.work_report('p', ref))['error_type'], 'WorkReportSymlinkRejected')
        self.path(work).unlink()
        os.mkfifo(self.path(work))
        self.assertEqual((await server.work_report('p', ref))['error_type'], 'WorkReportNotRegular')
        self.path(work).unlink()
        self.path(work).write_text('okay')
        for args, expected in [({'offset': -1}, 'InvalidOffset'), ({'limit': 16385}, 'InvalidLimit'),
                               ({'limit': True}, 'InvalidLimit'), ({'expected_sha256': 'bad'}, 'InvalidExpectedSHA256')]:
            self.assertEqual((await server.work_report('p', ref, **args))['error_type'], expected)
        self.assertEqual((await server.work_report('p', 'unknown'))['error_type'], 'WorkRefUnavailable')
        self.assertEqual((await server.work_report('missing', ref))['error_type'], 'ProjectRefUnauthorized')
        work['project_ref'] = 'other'
        self.assertEqual((await server.work_report('p', ref))['error_type'], 'WorkRefProjectMismatch')

    async def test_cleanup_on_discard_expiry_and_close(self):
        discarded = self.reserve(terminal=False)
        path = self.path(discarded)
        path.write_text('report')
        pending = Path(str(path) + '.pending'); pending.write_text('partial')
        server._discard_work(discarded['work_ref'])
        self.assertFalse(path.exists()); self.assertFalse(pending.exists())
        work = self.reserve()
        path = self.path(work); path.write_text('report')
        work['delivery_consumed'] = True
        with patch.object(server, 'MAX_TERMINAL_WORK_RECORDS', 0):
            server._expire_terminal_work('p', str(self.root))
        self.assertFalse(path.exists())
        self.assertEqual((await server.work_report('p', work['work_ref']))['error_type'], 'WorkRefExpired')
        work = self.reserve()
        path = self.path(work); path.write_text('report')
        root = path.parent
        self.store.close()
        self.assertFalse(root.exists())

    async def test_preparation_failure_and_uncertain_dispatch_do_not_leak_or_retry(self):
        with patch.object(self.store, 'allocate', side_effect=OSError('PRIVATE')):
            result = await delegate_item('p', assignments=[{'agent_ref': self.ref, 'task': 'task'}])
        self.assertEqual(result['error_type'], 'WorkReportPreparationFailed')
        self.assertFalse(server._WORK_REGISTRY)
        result = await delegate_item('p', assignments=[{'agent_ref': self.ref, 'task': 'x' * server.MAX_MANUAL_AGENT_TASK_CHARS}])
        self.assertEqual(result['error_type'], 'WorkReportPreparationFailed')
        self.assertFalse(self.store._keys)
        self.assertFalse(server._WORK_REGISTRY)
        self.assertFalse(any(c[:2] == ('agent', 'prompt') for c in self.state['calls']))
        self.state['prompt_error'] = herdr_backend.HerdrError('PRIVATE augmented prompt and path')
        result = await delegate_item('p', assignments=[{'agent_ref': self.ref, 'task': 'task'}])
        self.assertEqual(result['error_type'], 'WorkDispatchTransportUncertain')
        self.assertNotIn('PRIVATE', json.dumps(result))
        work = server._WORK_REGISTRY[result['work_ref']]
        self.assertIn(work['report_key'], self.store._keys)
        await self.settle(work)
        self.assertEqual(len([c for c in self.state['calls'] if c[:2] == ('agent', 'prompt')]), 1)

    async def test_unknown_delivery_later_settled_readable_report_is_normal_without_resend(self):
        for outcome in ('malformed_receipt', 'unexpected_exception'):
            with self.subTest(outcome=outcome):
                server._WORK_REGISTRY.clear()
                server._RESULT_INBOX.clear()
                self.state['calls'].clear()
                self.state['prompt_handler'] = lambda *args: {}
                self.state['prompt_error'] = RuntimeError('PRIVATE prompt/path') if outcome == 'unexpected_exception' else None
                async def observed(expected, pre_seq, pre_rev, *, recovery):
                    self.assertIsNone(recovery, 'uncertain input must never authorize automatic redelivery')
                    work = next(iter(server._WORK_REGISTRY.values()))
                    self.path(work).write_text('complete dedicated report', encoding='utf-8')
                    return {'state': 'done', 'reason': 'state_transition_proven'}
                self.watcher.side_effect = observed
                result = await delegate_item('p', assignments=[{'agent_ref': self.ref, 'task': 'one task'}])
                self.assertFalse(result['ok'])
                self.assertEqual(result['error_type'], 'WorkDispatchTransportUncertain')
                self.assertEqual(result['submission_evidence']['state'], 'delivery_unknown')
                self.assertIn('agent_terminal_read', result['error'])
                self.assertNotIn('PRIVATE', json.dumps(result))
                work = server._WORK_REGISTRY[result['work_ref']]
                await self.settle(work)
                await asyncio.gather(*list(server._CLASSIFICATION_TASKS))
                claim = (server._register_work_watch('p', server._required_project_context('p'), [work['work_ref']])).structured_content
                self.assertEqual(claim['status'], 'ready')
                self.assertEqual(claim['result_ready'], [work['work_ref']])
                self.assertEqual(claim['attention_required'], [])
                self.assertEqual(work['submission_evidence']['state'], 'delivery_unknown')
                self.assertEqual(len([c for c in self.state['calls'] if c[:2] == ('agent', 'prompt')]), 1)

    async def test_cancelled_dispatch_retains_report_and_same_work(self):
        self.state['prompt_error'] = asyncio.CancelledError()
        with self.assertRaises(asyncio.CancelledError):
            await delegate_item('p', assignments=[{'agent_ref': self.ref, 'task': 'cancelled task'}])
        self.assertEqual(len(server._WORK_REGISTRY), 1)
        work = next(iter(server._WORK_REGISTRY.values()))
        self.assertIn(work['report_key'], self.store._keys)
        receipt = await self.settle(work)
        self.assertTrue(receipt['submission_evidence']['mutation_possible'])
        self.assertNotIn('bridge-reports-', json.dumps(receipt))
        self.assertEqual(len([c for c in self.state['calls'] if c[:2] == ('agent', 'prompt')]), 1)

    async def test_capture_preserves_pre_prompt_revalidation_diagnostics(self):
        for code, error_type in [('manual_candidate_read_unavailable', 'AgentRefObservationUnavailable'),
                                  ('invalid_identity', 'AgentRefRevalidationUncertain')]:
            message = 'foreground observation unavailable during writer-gated refresh'
            with self.subTest(code=code), patch.object(self.backend, 'revalidate_manual_agent_resource',
                    AsyncMock(side_effect=[self.candidate, herdr_backend.HerdrError(message, code=code)])):
                result = await delegate_item('p', assignments=[{'agent_ref': self.ref, 'task': 'task'}])
            self.assertEqual(result['error_type'], error_type)
            self.assertEqual(result['error'], message)
            self.assertFalse(server._WORK_REGISTRY)
            self.assertFalse(self.store._keys)
        self.assertFalse(any(c[:2] == ('agent', 'prompt') for c in self.state['calls']))

    async def test_capture_preserves_known_local_prompt_refusal(self):
        message = 'manual agent status is not suitable for an ordinary turn'
        # Use the real backend local-refusal branch, before its native prompt.
        self.candidate['herdr_status'] = 'blocked'
        with patch.object(self.backend, 'revalidate_manual_agent_resource', AsyncMock(return_value=self.candidate)):
            result = await delegate_item('p', assignments=[{'agent_ref': self.ref, 'task': 'task'}])
        self.assertEqual(result['error_type'], 'ManualAgentPromptNotReady')
        self.assertEqual(result['error'], message)
        self.assertFalse(server._WORK_REGISTRY)
        self.assertFalse(self.store._keys)
        self.assertFalse(any(c[:2] == ('agent', 'prompt') for c in self.state['calls']))

    async def test_report_publication_after_settlement_does_not_change_receipt(self):
        response = await delegate_item('p', assignments=[{'agent_ref': self.ref, 'task': 'task'}])
        work = server._WORK_REGISTRY[response['work_ref']]
        receipt = await self.settle(work)
        self.assertEqual((await server.work_report('p', work['work_ref']))['error_type'], 'WorkReportMissing')
        path = self.path(work)
        pending = Path(str(path) + '.pending'); pending.write_text('late publication', encoding='utf-8')
        pending.replace(path)
        result = await server.work_report('p', work['work_ref'])
        self.assertEqual(result['content'], 'late publication')
        self.assertEqual(receipt, await finished_work('p', work['work_ref']))

    async def test_capture_keeps_known_no_input_transport_diagnostic(self):
        message = 'manual agent exact pane identity is unavailable'
        async def local_failure(expected, task, submission_evidence):
            submission_evidence.update(state='not_attempted', mutation_possible=False,
                                       proves='no_input_attempted')
            raise herdr_backend.HerdrError(message)
        with patch.object(self.backend, 'prompt_manual_agent', local_failure):
            result = await delegate_item('p', assignments=[{'agent_ref': self.ref, 'task': 'task'}])
        self.assertEqual(result['error'], message)
        # Keep the existing conservative Work outcome; only diagnostic redaction
        # changes here, with no new retry/refusal classification.
        self.assertEqual(result['error_type'], 'WorkDispatchTransportUncertain')
        receipt = await self.settle(server._WORK_REGISTRY[result['work_ref']])
        self.assertFalse(receipt['submission_evidence']['mutation_possible'])
        self.assertFalse(any(c[:2] == ('agent', 'prompt') for c in self.state['calls']))

    async def test_report_replacement_during_read_rejected_and_cleanup_never_follows_links(self):
        work = self.reserve()
        path = self.path(work); path.write_text('original')
        replacement = Path(str(path) + '.pending'); replacement.write_text('new')
        original = os.read
        replaced = False
        def read_then_replace(fd, count):
            nonlocal replaced
            raw = original(fd, count)
            if not replaced:
                replacement.replace(path)
                replaced = True
            return raw
        with patch.object(work_reports.os, 'read', read_then_replace):
            result = self.store.read(work['report_key'], 0, 4096, None)
        self.assertEqual(result['error_type'], 'WorkReportChanged')
        path.unlink()
        outside = Path(self.temp.name) / 'outside'; outside.write_text('preserve')
        path.symlink_to(outside)
        self.store.discard(work['report_key'])
        self.assertEqual(outside.read_text(), 'preserve')
        self.assertFalse(path.is_symlink())
