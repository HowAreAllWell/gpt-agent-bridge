"""Explicit all-of batches, classification races, delivery and evidence lifetime."""
import asyncio
import concurrent.futures
import copy
import hashlib
import hmac
import json
import logging
from pathlib import Path
import threading
import unittest
from unittest.mock import patch

from tests import test_read_contract as fixtures
import server
import widget_watcher
import work_reports
from tests.work_observation import delegate_item


class WorkWatchTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        fixtures.ReadContractTests.setUp(self)
        self.store = work_reports.ReportStore()
        self.addCleanup(self.store.close)
        for name, value in (('_REPORT_STORE', self.store), ('_EXPIRED_WORK_REFS', {}),
                            ('_CLASSIFICATION_TASKS', set()), ('_CLASSIFICATION_INFLIGHT', set()),
                            ('_WORK_WATCHES', {}), ('_WORK_WATCH_WAITERS', {})):
            patch.object(server, name, value).start()
        patch.object(server, '_REPORT_EVIDENCE_EXTRA_ATTEMPTS', 0).start()

    async def asyncTearDown(self):
        tasks = list(server._CLASSIFICATION_TASKS)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    def work(self, state='running', text=None, agent='a', project='p'):
        work = server._reserve_work(project, self.project, agent, {'resource_key': agent})
        work['report_key'] = self.store.allocate()
        if text is not None:
            self.path(work).write_text(text, encoding='utf-8')
        if state != 'running':
            self.settle(work, state)
        return work

    def path(self, work):
        return Path(self.store._root) / work['report_key']

    def settle(self, work, state='agent_turn_settled'):
        handoff = {'state': {'agent_turn_settled': 'done', 'continuity_lost': 'failed'}.get(state, state),
                   'reason': 'fixture'}
        server._latch_work_from_handoff(work['work_ref'], handoff)

    async def classified(self):
        await asyncio.gather(*list(server._CLASSIFICATION_TASKS))

    async def watch(self, *works):
        return server._register_work_watch('p', server._required_project_context('p'), [work['work_ref'] for work in works])

    def ref(self, result):
        return result.meta[widget_watcher.WORK_WATCH_META_KEY]['watch_ref']

    async def test_one_two_n_all_ready_no_subscription_or_hydration(self):
        for n in (1, 2, 12):
            works = [self.work('agent_turn_settled', 'report', agent=str(i)) for i in range(n)]
            await self.classified()
            result = await self.watch(*works)
            self.assertEqual(result.structured_content['status'], 'ready')
            self.assertEqual(result.structured_content['result_ready'], [w['work_ref'] for w in works])
            self.assertEqual(result.structured_content['attention_required'], [])
            self.assertIsNone(result.meta)
            self.assertEqual(server._WORK_WATCHES, {})
            self.assertTrue(all(w['delivery_consumed'] for w in works))
            self.assertNotIn('watch_ref', result.structured_content)

    async def test_mixed_ready_running_attention_strict_all_of(self):
        ready = self.work('agent_turn_settled', 'ready')
        attention = self.work('needs_attention', agent='blocked')
        running = self.work(agent='running')
        await self.classified()
        result = await self.watch(ready, attention, running)
        ref = self.ref(result)
        self.assertEqual(result.structured_content['status'], 'armed')
        with patch.object(server, 'WORK_AWAIT_LEASE_SECONDS', .01):
            self.assertEqual(await server.wait_work_watch('p', ref), {'ready': False})
        self.assertFalse((await server.claim_work_watch('p', ref))['granted'])
        waiter = asyncio.create_task(server.wait_work_watch('p', ref))
        await asyncio.sleep(0)
        self.settle(running, 'continuity_lost')
        preview = await asyncio.wait_for(waiter, 2)
        self.assertTrue(preview['ready'])
        self.assertEqual(preview['result_ready'], [ready['work_ref']])
        self.assertEqual([w['work_ref'] for w in preview['attention_required']],
                         [attention['work_ref'], running['work_ref']])
        self.assertTrue(all(not w['delivery_consumed'] for w in (ready, attention, running)))
        self.assertEqual(preview['attention_required'][0]['report_status'], 'unknown')
        self.assertNotIn('missing', preview['notice'])
        claim = await server.claim_work_watch('p', ref)
        self.assertTrue(claim['granted'])
        self.assertEqual(claim['notice'], preview['notice'])

    async def test_terminal_but_probe_pending_waits_for_final_classification(self):
        entered, release = asyncio.Event(), asyncio.Event()
        original = server._probe_requested_reports
        async def held(targets):
            entered.set()
            await release.wait()
            return await original(targets)
        with patch.object(server, '_probe_requested_reports', held):
            work = self.work('agent_turn_settled', 'report')
            await entered.wait()
            self.assertIsNone(work['result_class'])
            ref = self.ref(await self.watch(work))
            with patch.object(server, 'WORK_AWAIT_LEASE_SECONDS', .01):
                self.assertEqual(await server.wait_work_watch('p', ref), {'ready': False})
            release.set()
            self.assertTrue((await asyncio.wait_for(server.wait_work_watch('p', ref), 2))['ready'])

    async def test_classification_matrix_and_late_report_is_not_reclassified(self):
        for state in ('agent_turn_settled', 'needs_attention', 'continuity_lost'):
            for text in ('readable', '', None):
                with self.subTest(state=state, text=text):
                    work = self.work(state, text)
                    await self.classified()
                    self.assertEqual(work['result_class'], server.RESULT_READY if
                        state == 'agent_turn_settled' and text else server.ATTENTION_REQUIRED)
                    result = await self.watch(work)
                    self.assertEqual(result.structured_content['status'], 'ready')
        late = self.work('agent_turn_settled')
        await self.classified()
        self.assertEqual(late['report_status'], 'missing')
        self.path(late).write_text('late report')
        self.assertEqual((await server.work_report('p', late['work_ref']))['content'], 'late report')
        self.assertEqual(late['result_class'], server.ATTENTION_REQUIRED)
        self.assertEqual((await self.watch(late)).structured_content['attention_required'][0]['report_status'], 'missing')

    async def test_invalid_utf8_report_classifies_attention(self):
        work = self.work()
        self.path(work).write_bytes(b'\xffinvalid')
        self.settle(work)
        await self.classified()
        result = (await self.watch(work)).structured_content
        self.assertEqual(result['result_ready'], [])
        self.assertEqual(result['attention_required'][0]['report_status'], 'invalid')

    async def test_report_probe_pending_with_attention_does_not_complete_batch(self):
        attention = self.work('needs_attention')
        await self.classified()
        entered, release = asyncio.Event(), asyncio.Event()
        original = server._probe_requested_reports
        async def probe(targets):
            entered.set()
            await release.wait()
            return await original(targets)
        with patch.object(server, '_probe_requested_reports', probe):
            normal = self.work('agent_turn_settled', 'report', agent='normal')
            await entered.wait()
            ref = self.ref(await self.watch(attention, normal))
            with patch.object(server, 'WORK_AWAIT_LEASE_SECONDS', .01):
                self.assertEqual(await server.wait_work_watch('p', ref), {'ready': False})
            self.assertEqual((await server.claim_work_watch('p', ref))['reason'], 'not_ready')
            release.set()
            self.assertTrue((await server.wait_work_watch('p', ref))['ready'])

    async def test_unwatched_and_post_arm_new_work_never_join_or_delay(self):
        member = self.work()
        unwatched = self.work(agent='unwatched')
        result = await self.watch(member)
        ref = self.ref(result)
        new = self.work(agent='newly-delegated')
        waiter = asyncio.create_task(server.wait_work_watch('p', ref))
        self.settle(member, 'needs_attention')
        preview = await asyncio.wait_for(waiter, 2)
        self.assertEqual(preview['work_refs'], [member['work_ref']])
        self.assertEqual(server._WORK_WATCHES[ref]['members'], (member['work_ref'],))
        self.assertEqual((unwatched['state'], new['state']), ('running', 'running'))

    async def test_invalid_batch_rejects_atomically(self):
        first, second = self.work(), self.work(agent='second')
        wrong = self.work(project='q')
        expired = 'work-0000000000000000'
        server._EXPIRED_WORK_REFS[expired] = ('p', str(self.root))
        for refs in ([], [first['work_ref']]*2, [first['work_ref'], 'work-ffffffffffffffff'],
                     [first['work_ref'], expired], [first['work_ref'], wrong['work_ref']],
                     [first['work_ref'], 'bad'], [first['work_ref'], 3]):
            before = {w['work_ref']: (w['delivery_consumed'], set(w['watch_refs'])) for w in (first, second)}
            result = server._register_work_watch('p', server._required_project_context('p'), refs)
            self.assertFalse(result.structured_content['ok'])
            self.assertIsNone(result.meta)
            self.assertEqual(server._WORK_WATCHES, {})
            self.assertEqual(before, {w['work_ref']: (w['delivery_consumed'], set(w['watch_refs'])) for w in (first, second)})

    async def test_same_membership_reuses_frozen_order_overlap_refuses(self):
        a, b, c = self.work(), self.work(agent='b'), self.work(agent='c')
        first = await self.watch(a, b)
        second = await self.watch(b, a)
        self.assertEqual(self.ref(first), self.ref(second))
        self.assertEqual(first.structured_content, second.structured_content)
        self.assertEqual(len(server._WORK_WATCHES), 1)
        before = copy.deepcopy(server._WORK_WATCHES)
        refused = await self.watch(b, c)
        self.assertEqual(refused.structured_content['error_type'], 'WorkWatchOverlap')
        self.assertEqual(server._WORK_WATCHES, before)
        self.assertEqual(c['watch_refs'], set())

    async def test_resolved_dependency_may_support_two_distinct_pending_batches(self):
        a = self.work('agent_turn_settled', 'a')
        b, c = self.work(agent='b'), self.work(agent='c')
        await self.classified()
        one = self.ref(await self.watch(a, b))
        two = self.ref(await self.watch(a, c))
        self.assertEqual(a['watch_refs'], {one, two})
        self.settle(b, 'needs_attention')
        await self.classified()
        self.assertTrue((await server.claim_work_watch('p', one))['granted'])
        self.assertTrue(server._delivery_protected(a))
        self.assertFalse((await server.claim_work_watch('p', two))['granted'])
        self.settle(c, 'needs_attention')
        await self.classified()
        self.assertTrue((await server.claim_work_watch('p', two))['granted'])
        self.assertFalse(server._delivery_protected(a))

    async def test_duplicate_claim_concurrent_and_synchronous_takeover(self):
        work = self.work()
        ref = self.ref(await self.watch(work))
        self.settle(work, 'needs_attention')
        await self.classified()
        claims = await asyncio.gather(*[server.claim_work_watch('p', ref) for _ in range(10)])
        self.assertEqual(sum(c['granted'] for c in claims), 1)
        self.assertEqual((await server.wait_work_watch('p', ref))['status'], 'consumed')
        other = self.work(agent='other')
        ref = self.ref(await self.watch(other))
        self.settle(other, 'needs_attention')
        await self.classified()
        synchronous = await self.watch(other)
        self.assertEqual(synchronous.structured_content['status'], 'ready')
        self.assertIsNone(synchronous.meta)
        self.assertEqual((await server.claim_work_watch('p', ref))['reason'], 'already_consumed')

    async def test_threaded_event_loop_claims_grant_and_release_exactly_once(self):
        works = [self.work(agent='a'), self.work(agent='b')]
        ref = self.ref(await self.watch(*works))
        for work in works:
            self.settle(work, 'needs_attention')
        await self.classified()
        watch = server._WORK_WATCHES[ref]
        self.assertFalse(watch['consumed'])
        self.assertTrue(all(work['watch_refs'] == {ref} and not work['delivery_consumed']
                            and server._delivery_protected(work) for work in works))

        workers = 8
        barrier = threading.Barrier(workers)
        transitions = []
        consume = server._consume_work_watch
        def observed_consume(subscription, members):
            before = tuple(server._delivery_protected(work) for work in members)
            consume(subscription, members)
            transitions.append((before, tuple(server._delivery_protected(work) for work in members)))
        def worker():
            async def claim():
                loop = asyncio.get_running_loop()
                barrier.wait(timeout=10)
                return threading.get_ident(), loop, await server.claim_work_watch('p', ref)
            return asyncio.run(claim())

        with patch.object(server, '_consume_work_watch', side_effect=observed_consume) as consumed:
            with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
                results = await asyncio.gather(*[asyncio.wrap_future(pool.submit(worker)) for _ in range(workers)])
            consumed.assert_called_once_with(watch, works)
        self.assertEqual(len({thread for thread, _, _ in results}), workers)
        self.assertEqual(len({loop for _, loop, _ in results}), workers)
        claims = [result for _, _, result in results]
        self.assertTrue(all(claim['ok'] for claim in claims))
        self.assertEqual(sum(claim['granted'] for claim in claims), 1)
        self.assertEqual([claim['reason'] for claim in claims if not claim['granted']],
                         ['already_consumed'] * (workers - 1))
        self.assertEqual(transitions, [((True, True), (False, False))])
        self.assertTrue(watch['consumed'])
        self.assertTrue(all(work['delivery_consumed'] and not work['watch_refs']
                            and not server._delivery_protected(work) for work in works))

    async def test_never_terminal_neutral_cancellation_scope_isolated(self):
        member = self.work()
        ref = self.ref(await self.watch(member))
        with patch.object(server, 'WORK_AWAIT_LEASE_SECONDS', .01):
            for _ in range(2):
                self.assertEqual(await server.wait_work_watch('p', ref), {'ready': False})
        one, two = [asyncio.create_task(server.wait_work_watch('p', ref)) for _ in range(2)]
        await asyncio.sleep(0)
        one.cancel()
        with self.assertRaises(asyncio.CancelledError): await one
        self.assertEqual(len(server._WORK_WATCH_WAITERS[ref]), 1)
        self.work('needs_attention', project='q')
        await self.classified()
        self.assertFalse(two.done())
        self.assertEqual(member['state'], 'running')
        two.cancel()
        with self.assertRaises(asyncio.CancelledError): await two
        self.assertEqual(server._WORK_WATCH_WAITERS, {})
        self.assertFalse(member['delivery_consumed'])

    async def test_classification_publication_registration_race(self):
        gate = asyncio.Event()
        async def probe(targets):
            await gate.wait()
            return [{'work_ref': targets[0][0], 'status': 'readable'}]
        with patch.object(server, '_probe_requested_reports', probe):
            work = self.work('agent_turn_settled', 'report')
            ref = self.ref(await self.watch(work))
            waiter = asyncio.create_task(server.wait_work_watch('p', ref))
            gate.set()  # Publication may land before the wait starts/checks.
            result = await asyncio.wait_for(waiter, 2)
            self.assertEqual(result['result_ready'], [work['work_ref']])
            self.assertEqual(server._WORK_WATCH_WAITERS, {})

    async def test_restart_and_member_loss_fail_closed(self):
        work = self.work()
        ref = self.ref(await self.watch(work))
        server._WORK_WATCHES.clear()
        self.assertEqual((await server.wait_work_watch('p', ref))['error_type'], 'WorkWatchUnavailable')
        self.assertEqual((await server.claim_work_watch('p', ref))['error_type'], 'WorkWatchUnavailable')
        work['watch_refs'].clear()
        ref = self.ref(await self.watch(work))
        server._WORK_REGISTRY.clear()
        server._RESULT_INBOX.clear()
        self.assertEqual((await server.wait_work_watch('p', ref))['error_type'], 'WorkWatchMemberUnavailable')
        self.assertEqual((await server.claim_work_watch('p', ref))['error_type'], 'WorkWatchMemberUnavailable')

    async def test_retention_backpressure_release_and_work_report_nonconsuming(self):
        with patch.object(server, 'MAX_TERMINAL_WORK_RECORDS', 2):
            a = self.work('agent_turn_settled', 'a')
            b = self.work(agent='b')
            await self.classified()
            ref = self.ref(await self.watch(a, b))
            self.assertEqual((await server.work_report('p', a['work_ref']))['content'], 'a')
            self.assertFalse(a['delivery_consumed'])
            with self.assertRaises(server.WorkRegistryFullError) as error: self.work(agent='overflow')
            self.assertEqual(error.exception.capacity['dimension'], 'delivery_retention')
            self.settle(b, 'needs_attention')
            await self.classified()
            self.assertTrue((await server.claim_work_watch('p', ref))['granted'])
            third = self.work('agent_turn_settled', 'third')
            await self.classified()
            self.assertNotIn(a['work_ref'], server._WORK_REGISTRY)
            self.assertNotIn(ref, server._WORK_WATCHES)
            self.assertEqual((await server.work_report('p', a['work_ref']))['error_type'], 'WorkRefExpired')
            self.assertEqual((await server.wait_work_watch('p', ref))['error_type'], 'WorkWatchUnavailable')
            self.assertIn(third['work_ref'], server._WORK_REGISTRY)

    async def test_synchronous_delivery_releases_budget_and_existing_consumed_member_owned(self):
        a = self.work('agent_turn_settled', 'a')
        await self.classified()
        await self.watch(a)
        self.assertFalse(server._delivery_protected(a))
        b = self.work(agent='b')
        ref = self.ref(await self.watch(a, b))
        self.assertTrue(server._delivery_protected(a))
        self.settle(b, 'needs_attention')
        await self.classified()
        await self.watch(a, b)
        self.assertFalse(server._delivery_protected(a))
        self.assertEqual((await server.claim_work_watch('p', ref))['reason'], 'already_consumed')

    async def test_atomic_resource_budget_under_threads(self):
        with patch.object(server, 'MAX_TERMINAL_WORK_RECORDS', 2):
            def reserve(index):
                try: return server._reserve_work('p', self.project, str(index), {})
                except server.WorkRegistryFullError: return None
            with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
                results = list(pool.map(reserve, range(8)))
            self.assertEqual(sum(w is not None for w in results), 2)

    async def test_concurrent_same_membership_and_conflicting_ownership(self):
        a, b, c = self.work(), self.work(agent='b'), self.work(agent='c')
        def arm(refs):
            return server._register_work_watch('p', server._required_project_context('p'), refs)
        refs = [a['work_ref'], b['work_ref']]
        results = await asyncio.gather(*[asyncio.to_thread(arm, refs[::-1] if i % 2 else refs) for i in range(8)])
        self.assertEqual(len({self.ref(r) for r in results}), 1)
        self.assertEqual(len(server._WORK_WATCHES), 1)
        refused = await asyncio.to_thread(arm, [b['work_ref'], c['work_ref']])
        self.assertEqual(refused.structured_content['error_type'], 'WorkWatchOverlap')
        self.assertEqual(c['watch_refs'], set())

    async def test_reprotecting_delivered_evidence_respects_existing_admission_budget(self):
        with patch.object(server, 'MAX_TERMINAL_WORK_RECORDS', 2):
            delivered = self.work('agent_turn_settled', 'report')
            await self.classified()
            await self.watch(delivered)
            a, b = self.work(agent='a2'), self.work(agent='b2')
            result = await self.watch(delivered, a)
            self.assertEqual(result.structured_content['error_type'], 'WorkWatchRetentionFull')
            self.assertEqual(server._WORK_WATCHES, {})
            self.assertEqual(delivered['watch_refs'], set())
            self.assertFalse(server._delivery_protected(delivered))
            self.assertEqual((a['state'], b['state']), ('running', 'running'))

    async def test_no_arbitrary_small_batch_cap(self):
        works = []
        for i in range(35):
            work = self.work('needs_attention', agent=str(i))
            await self.classified()
            works.append(work)
        running = self.work(agent='running')
        result = await self.watch(*works, running)
        self.assertEqual(len(result.structured_content['work_refs']), 36)
        self.assertEqual(len(server._WORK_WATCHES), 1)

    async def test_lifecycle_logs_preserve_membership_and_private_correlation(self):
        a, b, c = self.work(), self.work(agent='b'), self.work(agent='c')
        raw = 'PRIVATE-HOST-SESSION-DO-NOT-LOG'
        # The request correlation is already opaque at this internal seam.
        correlation = hmac.new(server._HOST_SESSION_HASH_KEY, raw.encode(), hashlib.sha256).hexdigest()
        token = server._REQUEST_SESSION_CORRELATION.set(correlation)
        try:
            with self.assertLogs('mcp.bridge.followup_claim', level='INFO') as logs:
                ref = self.ref(await self.watch(a, b))
                self.assertEqual(self.ref(await self.watch(b, a)), ref)
                self.assertEqual((await self.watch(b, c)).structured_content['error_type'], 'WorkWatchOverlap')
                for work in (a, b):
                    self.settle(work, 'needs_attention')
                await self.classified()
                claims = await asyncio.gather(*[server.claim_work_watch('p', ref) for _ in range(10)])
                self.assertEqual(sum(claim['granted'] for claim in claims), 1)
                with patch.object(server, 'MAX_TERMINAL_WORK_RECORDS', 2):
                    self.settle(c, 'needs_attention')
                    await self.classified()
        finally:
            server._REQUEST_SESSION_CORRELATION.reset(token)
        events = [json.loads(record.getMessage()) for record in logs.records]
        self.assertEqual([event['event'] for event in events], [
            'bridge.work_watch_arm', 'bridge.work_watch_reuse', 'bridge.work_watch_overlap',
            'bridge.work_watch_claim', 'bridge.work_watch_retire'])
        for event in events:
            self.assertEqual(event['project_ref'], 'p')
            self.assertEqual(event['watch_ref'], ref)
            self.assertEqual(event['work_refs'], [a['work_ref'], b['work_ref']])
            self.assertEqual(event['member_count'], 2)
            self.assertFalse(event['members_truncated'])
            self.assertEqual(event['origin_session_fingerprint'], correlation[:16])
            self.assertEqual(event['request_session_fingerprint'], correlation[:16])
        self.assertEqual(events[2]['requested_work_refs'], [b['work_ref'], c['work_ref']])
        self.assertEqual(events[2]['outcome'], 'refused')
        self.assertEqual(events[3]['outcome'], 'granted')
        self.assertEqual(events[4]['outcome'], 'member_expired')
        rendered = '\n'.join(logs.output)
        for private in (raw, correlation, str(self.root), str(self.store._root)):
            self.assertNotIn(private, rendered)

    async def test_ready_logs_existing_watch_or_null_without_creating_subscription(self):
        a = self.work('needs_attention')
        await self.classified()
        with self.assertLogs('mcp.bridge.followup_claim', level='INFO') as logs:
            await self.watch(a)
        event = json.loads(logs.records[0].getMessage())
        self.assertEqual(event['event'], 'bridge.work_watch_ready')
        self.assertEqual(event['outcome'], 'consumed')
        self.assertIsNone(event['watch_ref'])
        self.assertEqual(event['work_refs'], [a['work_ref']])
        self.assertEqual(server._WORK_WATCHES, {})
        b = self.work(agent='b')
        ref = self.ref(await self.watch(b))
        self.settle(b, 'needs_attention')
        await self.classified()
        with self.assertLogs('mcp.bridge.followup_claim', level='INFO') as logs:
            await self.watch(b)
        events = [json.loads(record.getMessage()) for record in logs.records]
        self.assertEqual([event['event'] for event in events],
                         ['bridge.work_watch_reuse', 'bridge.work_watch_ready'])
        self.assertTrue(all(event['watch_ref'] == ref for event in events))
        self.assertFalse((await server.claim_work_watch('p', ref))['granted'])

    async def test_discard_retirement_and_logging_failure_preserve_behavior(self):
        work = self.work()
        ref = self.ref(await self.watch(work))
        with self.assertLogs('mcp.bridge.followup_claim', level='INFO') as logs:
            server._discard_work(work['work_ref'])
        event = json.loads(logs.records[0].getMessage())
        self.assertEqual(event['event'], 'bridge.work_watch_retire')
        self.assertEqual(event['outcome'], 'member_discarded')
        self.assertEqual(event['work_refs'], [work['work_ref']])
        self.assertNotIn(ref, server._WORK_WATCHES)
        other = self.work(agent='other')
        with patch.object(server._FOLLOWUP_CLAIM_LOGGER, 'info', side_effect=RuntimeError('private-log-error')):
            ref = self.ref(await self.watch(other))
            self.assertEqual(self.ref(await self.watch(other)), ref)
            self.settle(other, 'needs_attention')
            await self.classified()
            self.assertTrue((await server.claim_work_watch('p', ref))['granted'])
            server._retire_work_watches(other['work_ref'], 'member_expired')
        self.assertTrue(other['delivery_consumed'])
        self.assertNotIn(ref, server._WORK_WATCHES)

    async def test_watch_log_bounds_and_invalid_refs_never_emit_arm(self):
        with patch.object(server, '_log_followup_claim_event') as log:
            with server._WORK_REGISTRY_LOCK:
                diagnostic = server._capture_work_watch_event('bridge.work_watch_ready', 'p', None, 'consumed',
                    work_refs=['work-%016x' % index for index in range(530)])
                log.assert_not_called()
            server._emit_work_watch_events((diagnostic,))
            event = json.loads(log.call_args.args[0])
            self.assertEqual(len(event['work_refs']), 528)
            self.assertEqual(event['member_count'], 530)
            self.assertTrue(event['members_truncated'])
            log.reset_mock()
            result = server._register_work_watch('p', server._required_project_context('p'), ['PRIVATE-INVALID-REF'])
            self.assertFalse(result.structured_content['ok'])
            log.assert_not_called()

    async def test_blocking_logger_never_holds_outer_registry_lock(self):
        cases = ('arm', 'reuse', 'overlap', 'ready_new', 'ready_existing', 'claim',
                 'retire_discard', 'retire_expiry', 'retire_standalone')
        for case in cases:
            with self.subTest(path=case):
                await self.classified()
                with server._WORK_REGISTRY_LOCK:
                    server._WORK_REGISTRY.clear()
                    server._RESULT_INBOX.clear()
                    server._WORK_WATCHES.clear()
                a, b, c = self.work(), self.work(agent='b'), self.work(agent='c')
                origin = 'b' * 64
                request = 'a' * 64
                ref = None
                if case not in ('arm', 'ready_new'):
                    token = server._REQUEST_SESSION_CORRELATION.set(origin)
                    try:
                        ref = self.ref(await self.watch(a, b))
                    finally:
                        server._REQUEST_SESSION_CORRELATION.reset(token)
                if case.startswith('ready') or case in ('claim', 'retire_expiry'):
                    for work in (a, b):
                        self.settle(work, 'needs_attention')
                    await self.classified()
                if case == 'retire_expiry':
                    await server.claim_work_watch('p', ref)
                target = ('bridge.work_watch_ready' if case.startswith('ready') else
                          'bridge.work_watch_retire' if case.startswith('retire') else
                          'bridge.work_watch_' + case)
                entered, release = threading.Event(), threading.Event()
                records = []
                class BlockingHandler(logging.Handler):
                    def emit(handler, record):
                        payload = json.loads(record.getMessage())
                        if payload['event'] == target:
                            records.append(record.getMessage())
                            entered.set()
                            release.wait(6)
                handler = BlockingHandler()
                server._FOLLOWUP_CLAIM_LOGGER.addHandler(handler)
                def trigger():
                    token = server._REQUEST_SESSION_CORRELATION.set(request)
                    try:
                        if case == 'claim':
                            return asyncio.run(server.claim_work_watch('p', ref))
                        if case == 'retire_discard':
                            return server._discard_work(a['work_ref'])
                        if case == 'retire_expiry':
                            with patch.object(server, 'MAX_TERMINAL_WORK_RECORDS', 1):
                                return server._expire_terminal_work('p', str(self.root))
                        if case == 'retire_standalone':
                            return server._retire_work_watches(a['work_ref'], 'member_expired')
                        refs = ([b['work_ref'], c['work_ref']] if case == 'overlap' else
                                [b['work_ref'], a['work_ref']] if case == 'reuse' else
                                [a['work_ref'], b['work_ref']])
                        return server._register_work_watch('p', server._required_project_context('p'), refs)
                    finally:
                        server._REQUEST_SESSION_CORRELATION.reset(token)
                def unrelated_registry_operation():
                    acquired = server._WORK_REGISTRY_LOCK.acquire(timeout=1)
                    if not acquired:
                        return False
                    try:
                        server._work_capacity('p', str(self.root))
                        # Change mutable registry state after capture, before emission finishes.
                        for watch in server._WORK_WATCHES.values():
                            watch['session_correlation'] = 'c' * 64
                        return True
                    finally:
                        server._WORK_REGISTRY_LOCK.release()
                with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
                    future = pool.submit(trigger)
                    try:
                        self.assertTrue(await asyncio.to_thread(entered.wait, 3), 'logger was not reached')
                        unrelated = pool.submit(unrelated_registry_operation)
                        self.assertTrue(unrelated.result(timeout=2), 'logger held the outer Work registry lock')
                        self.assertFalse(release.is_set())
                        self.assertEqual(len(records), 1)
                        captured = json.loads(records[0])
                        self.assertEqual(captured['work_refs'], [a['work_ref'], b['work_ref']])
                        self.assertEqual(captured['request_session_fingerprint'], request[:16])
                        expected_origin = request if case == 'arm' else None if case == 'ready_new' else origin
                        self.assertEqual(captured['origin_session_fingerprint'],
                                         expected_origin[:16] if expected_origin else None)
                    finally:
                        release.set()
                        try:
                            await asyncio.to_thread(future.result, 3)
                        finally:
                            server._FOLLOWUP_CLAIM_LOGGER.removeHandler(handler)


class PostArmDelegateTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        from tests.test_submission_evidence import SubmissionEvidenceTests
        await SubmissionEvidenceTests.asyncSetUp(self)
        patch.object(server, '_WORK_WATCHES', {}).start()

    async def asyncTearDown(self):
        from tests.test_submission_evidence import SubmissionEvidenceTests
        await SubmissionEvidenceTests.asyncTearDown(self)

    async def test_actual_later_delegate_does_not_join_existing_batch(self):
        from unittest.mock import AsyncMock
        from tests.test_submission_evidence import SubmissionEvidenceTests
        project = server._WORKSPACE_REGISTRY.resolve('p')
        first = server._reserve_work('p', project, 'other', {'resource_key': 'other'})
        first['report_key'] = self.report_store.allocate()
        armed = server._register_work_watch('p', server._required_project_context('p'), [first['work_ref']])
        ref = armed.meta[widget_watcher.WORK_WATCH_META_KEY]['watch_ref']
        gate = asyncio.Event()
        async def held(*args, **kwargs):
            await gate.wait()
        self.state['prompt_handler'] = lambda *args: SubmissionEvidenceTests.ack(self)
        with patch.object(self.backend, 'watch_manual_agent_turn', AsyncMock(side_effect=held)):
            later = await delegate_item('p', assignments=[{'agent_ref': self.ref, 'task': 'independent foreground delegation'}])
            self.assertTrue(later['ok'])
            server._latch_work_from_handoff(first['work_ref'], {'state':'needs_attention', 'reason':'fixture'})
            ready = await asyncio.wait_for(server.wait_work_watch('p', ref), 2)
        self.assertEqual(ready['work_refs'], [first['work_ref']])
        self.assertEqual(server._WORK_REGISTRY[later['work_ref']]['state'], 'running')
        self.assertEqual(server._WORK_WATCHES[ref]['members'], (first['work_ref'],))
