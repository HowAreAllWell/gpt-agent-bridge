"""EVO-027: level-triggered native waits under one activation observation budget."""
import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import herdr_backend as hb
from tests.test_manual_agents import AGY_SETTLED_COMPOSER_SCREEN
from tests.work_observation import delegate_item


class NativeTimeline:
    def __init__(self, initial='done', events=(), seq=1, kind=None,
                 detection_text=AGY_SETTLED_COMPOSER_SCREEN):
        self.now = 0.0
        self.status = initial
        self.seq = seq
        self.events = list(events)
        self.waits = []
        self.nudges = []
        self.reads = []
        self.read_delays = []
        self.entry_delay = 0.0
        self.wait_error = None
        self.read_error = None
        self.pauses = []
        self.prompts = []
        self.screens = []
        self.detection_text = detection_text
        self.screen_read_error = None
        self.expected = {'identity': {
            'pane_id': 'pane-exact', 'agent_name': None,
            'workspace_id': 'w-timeline', 'tab_id': 'w-timeline:t1',
            'terminal_id': 'term-timeline'}}
        if kind is not None:
            self.expected['identity']['agent_kind'] = kind
        self.backend = hb.HerdrBackend(Path.cwd())
        self.backend.revalidate_manual_agent = self.revalidate
        self.backend._call = self.wait
        self.backend._call_text = self.wait

    def advance(self, amount):
        end = self.now + amount
        while self.events and self.events[0][0] <= end:
            _, self.status, self.seq = self.events.pop(0)
        self.now = end

    async def sleep(self, amount):
        self.pauses.append(amount)
        self.advance(amount)

    async def revalidate(self, expected, **kwargs):
        assert expected is self.expected
        assert kwargs == {'allow_session_promotion': True}
        if self.read_delays:
            self.advance(self.read_delays.pop(0))
        self.reads.append(self.now)
        if self.read_error:
            raise self.read_error
        return {'identity': {'pane_id': 'pane-exact'}, 'herdr_status': self.status,
                '_raw_state_change_seq': self.seq, '_raw_revision': 999}

    async def wait(self, *args, **kwargs):
        if args[:2] == ('agent', 'send-keys'):
            # Enter-only activation nudge; recorded, never advanced by itself.
            self.nudges.append((self.now, args[2:]))
            return {}
        if args[:2] == ('agent', 'read'):
            # Bounded read-only recovery detection observation.
            assert args[3:7] == ('--source', 'detection', '--lines',
                                 str(hb.AGY_COMPOSER_RECOVERY_READ_LINES))
            assert args[7:] == ('--format', 'text')
            self.screens.append(self.now)
            if self.screen_read_error:
                raise self.screen_read_error
            return self.detection_text
        if args[:2] == ('agent', 'prompt'):
            # The single recovery reprompt; recorded verbatim, never advanced
            # by itself (timeline events model the landing). The receipt must
            # acknowledge the COMPLETE stable resource identity, exactly as
            # the first prompt's ack matching requires.
            self.prompts.append((self.now, args[3]))
            identity = self.expected['identity']
            agent = {'agent': identity.get('agent_kind'),
                     'workspace_id': identity['workspace_id'],
                     'tab_id': identity['tab_id'],
                     'pane_id': identity['pane_id'],
                     'terminal_id': identity['terminal_id']}
            if identity.get('agent_name') is not None:
                agent['name'] = identity['agent_name']
            return {'type': 'agent_prompted', 'agent': agent}
        assert args[:3] == ('agent', 'wait', 'pane-exact')
        until = [args[i+1] for i, value in enumerate(args) if value == '--until']
        ms = int(args[args.index('--timeout')+1]) if '--timeout' in args else None
        assert ms is None or ms > 0
        self.waits.append((self.now, self.status, until, ms, kwargs['timeout']))
        if self.wait_error:
            raise self.wait_error
        # A fast entire turn can occur before native wait subscribes.
        self.advance(self.entry_delay)
        self.entry_delay = 0.0
        if self.status in until:  # Real Herdr's level-triggered initial match.
            return {'agent': {'agent_status': self.status}}
        end = self.now + ms / 1000 if ms is not None else float('inf')
        while self.events and self.events[0][0] <= end:
            event_time = self.events[0][0]
            self.advance(event_time - self.now)
            if self.status in until:
                return {'agent': {'agent_status': self.status}}
        assert ms is not None, 'test omitted a settled transition'
        self.advance(end-self.now)
        raise hb.HerdrError('timed out waiting for agent status', code='timeout')

    async def run(self, baseline=1, recovery=None):
        # Do not patch the process-global time/asyncio modules used by the loop.
        with patch.object(hb, 'time', SimpleNamespace(monotonic=lambda: self.now)), \
             patch.object(hb, 'asyncio', SimpleNamespace(sleep=self.sleep)):
            return await self.backend.watch_manual_agent_turn(
                self.expected, baseline, 1, recovery=recovery)


class StartupObservationTests(unittest.IsolatedAsyncioTestCase):
    async def test_stale_done_waits_for_later_working_then_terminal(self):
        fake = NativeTimeline(events=[(2, 'working', 2), (3, 'done', 3)])
        result = await fake.run()
        self.assertEqual(result['state'], 'done')
        # The settled candidate must survive TWO full confirmation intervals
        # (2 x default 3s) after the t=3 transition, so it cannot latch before
        # ~6s of continued stability: now is 9, not the old one-shot 3 or the
        # blocked 2s-candidate 5.
        self.assertEqual(fake.now, 9)
        self.assertEqual(fake.waits[0][2], ['working', 'idle', 'blocked'])
        self.assertIsNone(fake.waits[1][3])  # Existing working barrier unchanged.

    async def test_settled_candidate_reverting_to_working_rearms_barrier(self):
        fake = NativeTimeline(events=[(1, 'idle', 2), (5, 'working', 3), (11, 'idle', 4)])
        with patch.object(hb, 'SETTLEMENT_CONFIRM_SECONDS', 5.0), \
                patch.object(hb, 'SETTLEMENT_CONFIRM_ATTEMPTS', 2):
            result = await fake.run()
        # Working evidence during confirmation rejected the candidate and the
        # native settled barrier was re-armed for the same open turn.
        self.assertEqual(result['state'], 'done')
        self.assertEqual(result['reason'], 'state_transition_proven')
        self.assertEqual(result['post_state_change_seq'], 4)
        self.assertEqual(len(fake.waits), 2)
        self.assertEqual([w[2] for w in fake.waits], [['working', 'idle', 'blocked'], ['idle', 'done', 'blocked']])
        self.assertIsNone(fake.waits[1][3])

    async def test_seq_churn_rejects_and_reestablishes_never_settles_from_exhaustion(self):
        # state_change_seq keeps advancing while status stays idle: each churned
        # candidate is REJECTED (never settled from elapsed attempts), the watcher
        # re-establishes, and only the final genuinely stable seq (4) settles
        # after two full intervals. Settling on post_seq 4 (not 2 or 3) with two
        # re-armed barriers proves no exhaustion-force-settle occurred.
        fake = NativeTimeline(events=[(1, 'idle', 2), (3, 'idle', 3), (6, 'idle', 4)])
        with patch.object(hb, 'SETTLEMENT_CONFIRM_SECONDS', 3.0), \
                patch.object(hb, 'SETTLEMENT_CONFIRM_ATTEMPTS', 2):
            result = await fake.run()
        self.assertEqual(result['state'], 'done')
        self.assertEqual(result['reason'], 'state_transition_proven')
        self.assertEqual(result['post_state_change_seq'], 4)
        self.assertEqual(len(fake.waits), 3)

    async def test_fallback_idle_gap_over_two_seconds_reverting_to_working_never_settles(self):
        # Deterministic fallback-idle gap of ~4s (>2s, <6s) that reverts to
        # working: the first confirmation interval (t=5) still sees idle seq 2
        # (a 2s one-shot candidate would have wrongly settled at t=3), but the
        # gap reverts to working at t=5 and the turn only settles much later on a
        # genuinely stable candidate (seq 4). Proves the >2s gap is not settled.
        fake = NativeTimeline(events=[(1, 'idle', 2), (5, 'working', 3), (20, 'idle', 4)])
        with patch.object(hb, 'SETTLEMENT_CONFIRM_SECONDS', 2.0), \
                patch.object(hb, 'SETTLEMENT_CONFIRM_ATTEMPTS', 2):
            result = await fake.run()
        self.assertEqual(result['state'], 'done')
        self.assertEqual(result['reason'], 'state_transition_proven')
        self.assertEqual(result['post_state_change_seq'], 4)
        self.assertEqual(len(fake.waits), 2)

    async def test_missing_or_non_exact_seq_during_confirmation_never_settles(self):
        # A candidate whose state_change_seq becomes missing/non-exact (True) at
        # the confirmation re-observation must not settle; the rejection re-arms
        # the barrier and outer fail-closed logic classifies transition_unproven.
        fake = NativeTimeline(events=[(1, 'idle', 2), (3, 'idle', True)])
        with patch.object(hb, 'SETTLEMENT_CONFIRM_SECONDS', 3.0), \
                patch.object(hb, 'SETTLEMENT_CONFIRM_ATTEMPTS', 2):
            result = await fake.run()
        self.assertEqual(result['state'], 'needs_attention')
        self.assertEqual(result['reason'], 'transition_unproven')
        self.assertIn(result['post_state_change_seq'], (2, True))

    async def test_blocked_during_confirmation_yields_attention(self):
        fake = NativeTimeline(events=[(1, 'idle', 2), (5, 'blocked', 3)])
        with patch.object(hb, 'SETTLEMENT_CONFIRM_SECONDS', 5.0), \
                patch.object(hb, 'SETTLEMENT_CONFIRM_ATTEMPTS', 2):
            result = await fake.run()
        self.assertEqual(result['state'], 'needs_attention')
        self.assertEqual(result['reason'], 'agent_blocked')
        self.assertEqual(len(fake.waits), 1)

    async def test_agy_stable_candidate_requires_one_full_60s_interval(self):
        # User-authorized AGY debounce: the provisional candidate must remain
        # identical across ONE full 60-second logical interval (not the generic
        # 2x3s, which would latch at t=9). Mocked time; no real waiting.
        fake = NativeTimeline(events=[(2, 'working', 2), (3, 'done', 3)])
        fake.expected['identity']['agent_kind'] = 'agy'
        result = await fake.run()
        self.assertEqual(result['state'], 'done')
        self.assertEqual(result['reason'], 'state_transition_proven')
        self.assertEqual(result['post_state_change_seq'], 3)
        self.assertEqual(fake.pauses, [60.0])
        self.assertEqual(fake.now, 63)

    async def test_agy_working_during_interval_rejects_and_rearms_same_turn(self):
        # Working evidence before the interval elapses rejects the provisional
        # candidate: no terminal receipt for seq 2, the SAME turn's settled
        # barrier re-arms, and the later fresh candidate starts a FRESH full
        # 60-second interval.
        fake = NativeTimeline(initial='working',
                              events=[(1, 'idle', 2), (30, 'working', 3), (70, 'idle', 4)])
        fake.expected['identity']['agent_kind'] = 'agy'
        result = await fake.run()
        self.assertEqual(result['state'], 'done')
        self.assertEqual(result['reason'], 'state_transition_proven')
        self.assertEqual(result['post_state_change_seq'], 4)
        self.assertEqual(len(fake.waits), 2)
        self.assertEqual([w[3] for w in fake.waits], [None, None])
        self.assertEqual(fake.pauses, [60.0, 60.0])
        self.assertEqual(fake.now, 130)

    async def test_agy_status_or_seq_change_rejects_and_fresh_candidate_gets_fresh_interval(self):
        for label, events, final_seq in (
            ('status_change', [(1, 'idle', 2), (30, 'done', 2)], 2),
            ('seq_change', [(1, 'idle', 2), (30, 'idle', 3)], 3),
        ):
            with self.subTest(scenario=label):
                fake = NativeTimeline(initial='working', events=events)
                fake.expected['identity']['agent_kind'] = 'agy'
                result = await fake.run()
                self.assertEqual(result['state'], 'done')
                self.assertEqual(result['post_state_change_seq'], final_seq)
                self.assertEqual(len(fake.waits), 2)
                # Rejected candidate's interval plus a FULL fresh interval for
                # the re-established candidate: 1 + 60 + 60.
                self.assertEqual(fake.pauses, [60.0, 60.0])
                self.assertEqual(fake.now, 121)

    async def test_non_agy_kinds_keep_generic_two_by_three_schedule(self):
        for kind in (None, 'pi', 'qodercli', 'AGY', 'agy-wrapper'):
            with self.subTest(kind=kind):
                fake = NativeTimeline(events=[(2, 'working', 2), (3, 'done', 3)])
                if kind is not None:
                    fake.expected['identity']['agent_kind'] = kind
                result = await fake.run()
                self.assertEqual(result['state'], 'done')
                self.assertEqual(result['post_state_change_seq'], 3)
                self.assertEqual(fake.pauses, [3.0, 3.0])
                self.assertEqual(fake.now, 9)

    async def test_agy_blocked_checkout_and_continuity_conditions_remain_immediate(self):
        # Blocked at the barrier: immediate attention, no debounce interval.
        fake = NativeTimeline(initial='working', events=[(1, 'blocked', 2)])
        fake.expected['identity']['agent_kind'] = 'agy'
        result = await fake.run()
        self.assertEqual(result['state'], 'needs_attention')
        self.assertEqual(result['reason'], 'agent_blocked')
        self.assertEqual(fake.pauses, [])
        self.assertEqual(fake.now, 1)

        # Blocked discovered by the interval's re-observation: attention at
        # once, never converted into settlement or another interval.
        fake = NativeTimeline(initial='working', events=[(1, 'idle', 2), (30, 'blocked', 3)])
        fake.expected['identity']['agent_kind'] = 'agy'
        result = await fake.run()
        self.assertEqual(result['state'], 'needs_attention')
        self.assertEqual(result['reason'], 'agent_blocked')
        self.assertEqual(fake.pauses, [60.0])
        self.assertEqual(fake.now, 61)

        # Continuity loss and checkout change stay immediate fail-closed.
        for code, state, reason in (
            ('manual_candidate_continuity_lost', 'failed', 'candidate_continuity_lost'),
            ('manual_candidate_checkout_changed', 'needs_attention', 'execution_checkout_changed'),
        ):
            with self.subTest(code=code):
                fake = NativeTimeline(initial='working')
                fake.expected['identity']['agent_kind'] = 'agy'
                fake.read_error = hb.HerdrError('condition', code=code)
                result = await fake.run()
                self.assertEqual(result['state'], state)
                self.assertEqual(result['reason'], reason)
                self.assertEqual(fake.pauses, [])
                self.assertEqual(fake.now, 0)

    def qoder_timeline(self, **kwargs):
        fake = NativeTimeline(**kwargs)
        fake.expected['identity']['agent_kind'] = 'qodercli'
        return fake

    async def test_qoder_stuck_composer_single_enter_nudge_activates_same_turn(self):
        # Stuck composer: prompt acknowledged but Enter lost — status stays
        # idle, exact seq never advances. The first 5s window expires, ONE
        # Enter-only nudge is sent (no task text), and ONE fresh bounded window
        # re-arms the SAME turn, which then activates and settles normally.
        fake = self.qoder_timeline(initial='idle',
                                   events=[(6, 'working', 2), (8, 'done', 3)])
        result = await fake.run(baseline=1)
        self.assertEqual(result['state'], 'done')
        self.assertEqual(result['reason'], 'state_transition_proven')
        self.assertEqual(result['post_state_change_seq'], 3)
        self.assertEqual([n[1] for n in fake.nudges], [('pane-exact', 'enter')])
        # One startup level wait, one fresh-window level wait, one settled barrier.
        self.assertEqual(len(fake.waits), 3)
        # Activation at t=6 plus the unchanged generic 2x3s confirmation.
        self.assertEqual(fake.now, 14)

    async def test_qoder_delayed_start_never_nudges(self):
        fake = self.qoder_timeline(initial='idle',
                                   events=[(2, 'working', 2), (4, 'done', 3)])
        result = await fake.run(baseline=1)
        self.assertEqual(result['state'], 'done')
        self.assertEqual(result['post_state_change_seq'], 3)
        self.assertEqual(fake.nudges, [])

    async def test_qoder_working_before_final_revalidation_vetoes_nudge(self):
        # The turn activates between the native timeout and the final exact
        # revalidation: the gate sees working/advanced seq and vetoes the Enter.
        fake = self.qoder_timeline(initial='idle',
                                   events=[(5.5, 'working', 2), (7, 'done', 3)])
        fake.read_delays = [0, 0, 0.6]
        result = await fake.run(baseline=1)
        self.assertEqual(result['state'], 'done')
        self.assertEqual(result['post_state_change_seq'], 3)
        self.assertEqual(fake.nudges, [])

    async def test_qoder_structured_conditions_veto_nudge_with_existing_classifications(self):
        # Blocked at the final gate: existing immediate attention, zero nudges.
        fake = self.qoder_timeline(initial='idle', events=[(5.5, 'blocked', 2)])
        fake.read_delays = [0, 0, 0.6]
        result = await fake.run(baseline=1)
        self.assertEqual(result['state'], 'needs_attention')
        self.assertEqual(result['reason'], 'agent_blocked')
        self.assertEqual(fake.nudges, [])

        # Uncertain status at the final gate: existing classification, no nudge.
        fake = self.qoder_timeline(initial='idle', events=[(5.5, 'unknown', 1)])
        fake.read_delays = [0, 0, 0.6]
        result = await fake.run(baseline=1)
        self.assertEqual(result['state'], 'needs_attention')
        self.assertEqual(result['reason'], 'startup_observation_uncertain')
        self.assertEqual(fake.nudges, [])

        # Continuity/checkout/observation failures at the final gate keep
        # their existing classifications; the nudge is never sent.
        for code, state, reason in (
            ('manual_candidate_continuity_lost', 'failed', 'candidate_continuity_lost'),
            ('manual_candidate_checkout_changed', 'needs_attention', 'execution_checkout_changed'),
            ('manual_candidate_read_unavailable', 'needs_attention', 'observation_unavailable'),
        ):
            with self.subTest(code=code):
                fake = self.qoder_timeline(initial='idle')
                reads = {'n': 0}
                original = fake.revalidate
                # The read-unavailable code is transient: one blip is retried.
                # Keep failing so exhaustion still classifies and never nudges.
                persistent = code == 'manual_candidate_read_unavailable'
                async def revalidate(expected, **kwargs):
                    reads['n'] += 1
                    if reads['n'] >= 3 if persistent else reads['n'] == 3:
                        raise hb.HerdrError('condition', code=code)
                    return await original(expected, **kwargs)
                fake.backend.revalidate_manual_agent = revalidate
                result = await fake.run(baseline=1)
                self.assertEqual(result['state'], state)
                self.assertEqual(result['reason'], reason)
                self.assertEqual(fake.nudges, [])

    async def test_qoder_nudge_exhaustion_is_terminal_after_exactly_one_enter(self):
        # Never activates: exactly one nudge, one fresh window, then honest
        # qoder-specific attention — never a second Enter, never a loop.
        fake = self.qoder_timeline(initial='idle')
        result = await fake.run(baseline=1)
        self.assertEqual(result['state'], 'needs_attention')
        self.assertEqual(result['reason'], 'qoder_activation_nudge_exhausted')
        self.assertEqual([n[1] for n in fake.nudges], [('pane-exact', 'enter')])
        self.assertEqual(len(fake.waits), 2)  # two bounded level waits, no barrier
        self.assertEqual(fake.now, 10)

    async def test_qoder_nudge_transport_failure_is_honest_attention_without_retry(self):
        fake = self.qoder_timeline(initial='idle')
        attempts = []
        original = fake.wait
        async def wait(*args, **kwargs):
            if args[:2] == ('agent', 'send-keys'):
                attempts.append(args)
                raise hb.HerdrError('transport lost')
            return await original(*args, **kwargs)
        fake.backend._call = wait
        result = await fake.run(baseline=1)
        self.assertEqual(result['state'], 'needs_attention')
        self.assertEqual(result['reason'], 'qoder_activation_nudge_uncertain')
        self.assertEqual(len(attempts), 1)
        self.assertEqual(fake.nudges, [])

    async def test_non_qoder_kinds_never_nudge_and_keep_existing_exhaustion(self):
        for kind in (None, 'pi', 'agy', 'QODERCLI', 'qoder', 'qoderclicn'):
            with self.subTest(kind=kind):
                fake = NativeTimeline(initial='idle')
                if kind is not None:
                    fake.expected['identity']['agent_kind'] = kind
                result = await fake.run(baseline=1)
                self.assertEqual(result['state'], 'needs_attention')
                self.assertEqual(result['reason'],
                                 'activation_observation_budget_exhausted')
                self.assertEqual(fake.nudges, [])
                self.assertEqual(fake.now, 5)

    async def test_opposite_terminal_with_advanced_sequence(self):
        for initial, final in [('idle', 'done'), ('done', 'idle')]:
            with self.subTest(initial=initial):
                fake = NativeTimeline(initial, [(1, final, 3)])
                result = await fake.run()
                self.assertEqual(result['state'], 'done')
                self.assertEqual(result['post_state_change_seq'], 3)
                self.assertNotIn(initial, fake.waits[0][2])

    async def test_fast_same_terminal_before_native_subscription_is_seen_after_timeout(self):
        for terminal in ('idle', 'done'):
            fake = NativeTimeline(terminal, [(0.001, 'working', 2), (0.002, terminal, 3)])
            fake.entry_delay = 0.01
            result = await fake.run()
            self.assertEqual(result['state'], 'done')
            self.assertEqual(result['post_state_change_seq'], 3)
            self.assertGreaterEqual(fake.reads[-1], 5)

    async def test_multiple_inconclusive_wakes_and_revalidation_share_deadline(self):
        fake = NativeTimeline('idle', [(1, 'done', 1), (2, 'idle', 1), (3, 'done', 1)])
        fake.read_delays = [0.4, 0.2, 0.3, 0.4, 0.1]
        result = await fake.run()
        self.assertEqual(result['reason'], 'activation_observation_budget_exhausted')
        self.assertEqual(len(fake.waits), 4)
        for started, status, until, ms, _ in fake.waits:
            self.assertNotIn(status, until)
            self.assertLessEqual(started + ms/1000, 5.001)
        self.assertLess(fake.now, 5.2)

    async def test_slow_initial_revalidation_consumes_budget_without_wait(self):
        fake = NativeTimeline()
        fake.read_delays = [6]
        result = await fake.run()
        self.assertEqual(result['reason'], 'activation_observation_budget_exhausted')
        self.assertEqual(fake.waits, [])

    async def test_invalid_sequence_and_revision_only_never_settle(self):
        for pre, post in [(1, True), (True, 3), (None, 3), (1, None), (1, 1)]:
            fake = NativeTimeline(seq=post)
            result = await fake.run(pre)
            self.assertEqual(result['state'], 'needs_attention')
            self.assertEqual(result['reason'], 'activation_observation_budget_exhausted')
            self.assertGreaterEqual(fake.now, 5)
            self.assertTrue(all(w[3] > 0 for w in fake.waits))

    async def test_native_timeout_contract_through_actual_call_parser(self):
        backend = hb.HerdrBackend(Path.cwd())
        async def raw(*args, **kwargs):
            return json.dumps({'error': {'code': 'timeout', 'message': 'timed out waiting for agent status'}}), ''
        with patch.object(backend, '_exec_raw', raw):
            with self.assertRaises(hb.HerdrError) as caught:
                await backend._call('agent', 'wait', 'pane-exact', '--timeout', '5')
        self.assertEqual(caught.exception.code, 'timeout')

    async def test_blocked_and_identity_loss_keep_existing_classification(self):
        fake = NativeTimeline(events=[(1, 'blocked', 2)])
        self.assertEqual((await fake.run())['reason'], 'agent_blocked')
        fake = NativeTimeline()
        original = fake.wait
        async def replace(*args, **kwargs):
            try:
                return await original(*args, **kwargs)
            finally:
                fake.read_error = hb.HerdrError('replacement', code='manual_candidate_continuity_lost')
        fake.backend._call = replace
        self.assertEqual((await fake.run())['state'], 'failed')

    async def test_transport_errors_are_not_native_expiry_and_revalidate(self):
        for error in (TimeoutError('subprocess deadline'), hb.HerdrError('pipe lost'),
                      hb.HerdrError('disconnected', code='connection_closed'), ValueError('malformed')):
            fake = NativeTimeline()
            fake.wait_error = error
            result = await fake.run()
            self.assertEqual(result['reason'], 'startup_wait_uncertain')
            self.assertEqual(len(fake.reads), 2)
            self.assertEqual(len(fake.waits), 1)
            self.assertEqual(fake.now, 0)

    async def test_instant_inconclusive_wakes_are_paced_and_bounded(self):
        fake = NativeTimeline()
        async def transient(*args, **kwargs):
            ms = int(args[args.index('--timeout')+1])
            self.assertGreater(ms, 0)
            return {'agent': {'agent_status': 'working'}}  # current status remains done
        fake.backend._call = transient
        result = await fake.run()
        self.assertEqual(result['reason'], 'activation_observation_budget_exhausted')
        self.assertTrue(fake.pauses)
        self.assertLessEqual(len(fake.pauses), 501)
        self.assertTrue(all(0 < delay <= 0.01 for delay in fake.pauses))

    async def test_startup_waiter_cancel_keeps_watcher_gate_release_and_other_work(self):
        import contextlib
        import tempfile
        from tests.test_manual_agents import manual_backend
        from tests.test_work_surface import git_worktree
        from workspace_context import WorkspaceRegistry, WorkspaceRegistryStore
        import server

        with tempfile.TemporaryDirectory() as directory, contextlib.ExitStack() as stack:
            base = Path(directory)
            root = git_worktree(base / 'a')
            other = git_worktree(base / 'b')
            registry = WorkspaceRegistry(root, json.dumps({'a': str(root), 'b': str(other)}),
                                         store=WorkspaceRegistryStore(base / 'registry.json'))
            backend, state = manual_backend(root)
            other_backend, other_state = manual_backend(other)
            state['agent']['agent_status'] = 'done'
            state['auto_advance_turn'] = False
            original_call = backend._call
            entered = asyncio.Event()
            release = asyncio.Event()
            wait_count = 0

            async def wait_call(*args, **kwargs):
                nonlocal wait_count
                if args[:2] != ('agent', 'wait'):
                    return await original_call(*args, **kwargs)
                wait_count += 1
                if wait_count == 1:
                    self.assertNotIn('done', args)
                    entered.set()
                    await release.wait()
                    state['agent']['agent_status'] = 'working'
                    state['agent']['state_change_seq'] = 2
                else:
                    state['agent']['agent_status'] = 'done'
                    state['agent']['state_change_seq'] = 3
                return {'agent': dict(state['agent'])}

            backend._call = wait_call
            for name, value in (
                ('_WORKSPACE_REGISTRY', registry), ('_WORKSPACE_BACKENDS',
                    {str(root): backend, str(other): other_backend}),
                ('_WORK_REGISTRY', {}), ('_RESULT_INBOX', {}), ('_HANDOFF_REGISTRY', {}),
                ('_WORK_WATCHES', {}), ('_WORK_WATCH_WAITERS', {}),
                ('_MANUAL_AGENT_CANDIDATES', {}),
            ):
                stack.enter_context(patch.object(server, name, value))
            # Confirmation must not add real sleeps to this cancellation test.
            stack.enter_context(patch.object(hb, 'SETTLEMENT_CONFIRM_SECONDS', 0.0))
            stack.enter_context(patch.object(hb, 'SETTLEMENT_CONFIRM_ATTEMPTS', 1))
            stack.enter_context(patch.object(hb, 'AGY_SETTLEMENT_CONFIRM_SECONDS', 0.0))
            stack.enter_context(patch.object(hb, 'AGY_SETTLEMENT_CONFIRM_ATTEMPTS', 1))
            try:
                discovered = await server._discover_project_candidates(workspace_ref='a')
                agent = discovered['candidates'][0]['candidate_id']
                delegated = await asyncio.wait_for(delegate_item('a', assignments=[{'agent_ref': agent, 'task': 'one prompt'}]), 2)
                self.assertTrue(delegated['ok'], delegated)
                await asyncio.wait_for(entered.wait(), 2)
                work = server._WORK_REGISTRY[delegated['work_ref']]
                handoff = server._HANDOFF_REGISTRY[work['handoff_id']]
                self.assertEqual(work['state'], 'running')
                self.assertFalse(handoff['joined_once'])
                self.assertFalse(server._access_gate(root).writer_active)
                armed = server._register_work_watch('a', server._required_project_context('a'), [work['work_ref']])
                watch_ref = armed.meta['bridge/workWatch']['watch_ref']
                waiter = asyncio.create_task(server.wait_work_watch('a', watch_ref))
                await asyncio.sleep(0)
                waiter.cancel()
                with self.assertRaises(asyncio.CancelledError):
                    await waiter
                self.assertFalse(handoff['watcher_task'].done())
                self.assertEqual(server._WORK_WATCH_WAITERS, {})
                discovered_b = await server._discover_project_candidates(workspace_ref='b')
                delegated_b = await delegate_item('b', assignments=[{'agent_ref': discovered_b['candidates'][0]['candidate_id'], 'task': 'other work'}])
                self.assertTrue(delegated_b['ok'], delegated_b)
                self.assertEqual(work['state'], 'running')
                release.set()
                await asyncio.wait_for(handoff['watcher_task'], 2)
                self.assertEqual(work['state'], 'agent_turn_settled')
                self.assertTrue(handoff['joined_once'])
                self.assertEqual(len([c for c in state['calls'] if c[:2] == ('agent', 'prompt')]), 1)
                self.assertEqual(len([c for c in other_state['calls'] if c[:2] == ('agent', 'prompt')]), 1)
            finally:
                for entry in server._HANDOFF_REGISTRY.values():
                    watcher = entry.get('watcher_task')
                    if watcher:
                        watcher.cancel()
                        with contextlib.suppress(asyncio.CancelledError):
                            await watcher


class AgyComposerRecoveryTimelineTests(unittest.IsolatedAsyncioTestCase):
    """Mocked-time AGY cold-path recovery: pacing, vetoes, at-most-once bound."""

    TASK = 'exact original task'
    INTERVAL = hb.AGY_COMPOSER_RECOVERY_READ_INTERVAL_SECONDS

    def seam(self, clear=True):
        return {'task': self.TASK, 'exclusivity_clear': lambda: clear}

    def agy(self, **kwargs):
        kwargs.setdefault('kind', 'agy')
        return NativeTimeline(**kwargs)

    async def test_absorbing_shape_reprompts_once_then_fresh_window_settles(self):
        fake = self.agy(initial='idle', events=[(6, 'working', 2), (8, 'done', 3)])
        with patch.object(hb, 'AGY_SETTLEMENT_CONFIRM_SECONDS', 0.0), \
                patch.object(hb, 'AGY_SETTLEMENT_CONFIRM_ATTEMPTS', 1):
            result = await fake.run(baseline=1, recovery=self.seam())
        self.assertEqual(result['state'], 'done')
        self.assertEqual(result['reason'], 'state_transition_proven')
        self.assertEqual(result['post_state_change_seq'], 3)
        self.assertIs(result['agy_recovery_reprompt'], True)
        # Budget exhausts at t=5; two reads spaced by the recovery interval;
        # the reprompt carries the EXACT task bytes once.
        self.assertEqual(fake.screens, [5.0, 5.0 + self.INTERVAL])
        self.assertEqual(fake.prompts, [(5.0 + self.INTERVAL, self.TASK)])
        self.assertIn(self.INTERVAL, fake.pauses)
        self.assertEqual(fake.nudges, [])

    async def test_second_window_exhaustion_is_terminal_never_third_prompt(self):
        fake = self.agy(initial='idle')  # absorbing forever
        result = await fake.run(baseline=1, recovery=self.seam())
        self.assertEqual(result['state'], 'needs_attention')
        self.assertEqual(result['reason'], 'agy_composer_recovery_exhausted')
        self.assertIs(result['agy_recovery_reprompt'], True)
        self.assertEqual([p[1] for p in fake.prompts], [self.TASK])
        self.assertEqual(len(fake.screens), 2)  # recovery never loops
        self.assertEqual(fake.nudges, [])

    async def test_healthy_activation_never_reads_screens(self):
        fake = self.agy(initial='idle', events=[(1, 'working', 2), (3, 'done', 3)])
        with patch.object(hb, 'AGY_SETTLEMENT_CONFIRM_SECONDS', 0.0), \
                patch.object(hb, 'AGY_SETTLEMENT_CONFIRM_ATTEMPTS', 1):
            result = await fake.run(baseline=1, recovery=self.seam())
        self.assertEqual(result['state'], 'done')
        self.assertNotIn('agy_recovery_reprompt', result)
        self.assertEqual(fake.screens, [])
        self.assertEqual(fake.prompts, [])

    async def test_seq_churn_between_reads_declines_reprompt(self):
        # The first prompt landed invisibly fast: seq moves during the read
        # pair, so the post-read gate sees activation and never reprompts.
        fake = self.agy(initial='idle', events=[(5.15, 'idle', 2)])
        with patch.object(hb, 'AGY_SETTLEMENT_CONFIRM_SECONDS', 0.0), \
                patch.object(hb, 'AGY_SETTLEMENT_CONFIRM_ATTEMPTS', 1):
            result = await fake.run(baseline=1, recovery=self.seam())
        self.assertEqual(result['state'], 'done')
        self.assertNotIn('agy_recovery_reprompt', result)
        self.assertEqual(fake.prompts, [])
        self.assertEqual(fake.screens, [5.0, 5.0 + self.INTERVAL])

    async def test_working_between_reads_declines_reprompt(self):
        fake = self.agy(initial='idle',
                        events=[(5.15, 'working', 1), (7, 'done', 2)])
        with patch.object(hb, 'AGY_SETTLEMENT_CONFIRM_SECONDS', 0.0), \
                patch.object(hb, 'AGY_SETTLEMENT_CONFIRM_ATTEMPTS', 1):
            result = await fake.run(baseline=1, recovery=self.seam())
        self.assertEqual(result['state'], 'done')
        self.assertNotIn('agy_recovery_reprompt', result)
        self.assertEqual(fake.prompts, [])
        self.assertEqual(len(fake.screens), 2)

    async def test_exclusivity_veto_precedes_any_screen_read(self):
        fake = self.agy(initial='idle')
        result = await fake.run(baseline=1, recovery=self.seam(clear=False))
        self.assertEqual(result['state'], 'needs_attention')
        self.assertEqual(result['reason'], 'activation_observation_budget_exhausted')
        self.assertEqual(fake.screens, [])
        self.assertEqual(fake.prompts, [])

    async def test_negative_screen_shape_declines(self):
        fake = self.agy(initial='idle',
                        detection_text=AGY_SETTLED_COMPOSER_SCREEN
                        + '\nPress up to edit queued messages')
        result = await fake.run(baseline=1, recovery=self.seam())
        self.assertEqual(result['reason'], 'activation_observation_budget_exhausted')
        self.assertEqual(fake.prompts, [])
        self.assertEqual(len(fake.screens), 1)

    async def test_screen_read_error_declines(self):
        fake = self.agy(initial='idle')
        fake.screen_read_error = hb.HerdrError('read transport lost')
        result = await fake.run(baseline=1, recovery=self.seam())
        self.assertEqual(result['reason'], 'activation_observation_budget_exhausted')
        self.assertEqual(fake.prompts, [])
        self.assertEqual(len(fake.screens), 1)

    async def test_non_agy_kinds_never_recover_even_with_seam(self):
        for kind in (None, 'pi', 'qodercli', 'AGY'):
            with self.subTest(kind=kind):
                fake = NativeTimeline(initial='idle', kind=kind)
                result = await fake.run(baseline=1, recovery=self.seam())
                self.assertEqual(fake.screens, [])
                self.assertEqual(fake.prompts, [])
                self.assertNotIn('agy_recovery_reprompt', result)
                expected_reason = ('qoder_activation_nudge_exhausted'
                                   if kind == 'qodercli'
                                   else 'activation_observation_budget_exhausted')
                self.assertEqual(result['reason'], expected_reason)
