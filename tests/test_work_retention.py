"""In-process retention only: disposable Git and synthetic Agents, no live calls."""
import asyncio
import contextvars
import gc
import json
import os
import sys
import subprocess
import weakref
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from tests import test_work_capacity as capacity_tests
from tests import test_convergence_final as convergence_tests
from gpt_agent_bridge import server
from tests.work_observation import finished_work, work_record
from gpt_agent_bridge import commit_candidate
from gpt_agent_bridge.evidence_target import EvidenceCheckout


class WorkRetentionTests(unittest.IsolatedAsyncioTestCase):
    setUp = capacity_tests.WorkCapacityTests.setUp
    asyncTearDown = capacity_tests.WorkCapacityTests.asyncTearDown
    delegate = capacity_tests.WorkCapacityTests.delegate
    prompts = capacity_tests.WorkCapacityTests.prompts

    def reserve(self, ref='a', state='done', checkout=None):
        w = server._reserve_work(ref, self.registry.resolve(ref), 'fixture', {'resource_key': 'fixture'})
        w['execution_identity'] = 'bound'
        w['evidence_checkout'] = checkout or EvidenceCheckout.capture(self.registry.resolve(ref), str(self.roots[ref]))
        w['submission_evidence'].update(state='delivery_unknown', mutation_possible=True, proves='delivery_unknown')
        server._latch_work_from_handoff(w['work_ref'], {
            'state': state, 'reason': 'synthetic observation', 'post_state_change_seq': 23})
        return w

    @unittest.skipUnless(os.environ.get('BRIDGE_MAINTAINER_SUITE') == '1',
                         'maintainer lane: full 600-delegation retention stress '
                         '(BRIDGE_MAINTAINER_SUITE=1)')
    async def test_600_real_delegations_receipt_window_and_no_read_renewal(self):
        async def instant(*args, **kwargs):
            return {'state': 'done', 'reason': 'state_transition_proven', 'post_state_change_seq': 2}
        for backend in self.backends.values():
            self.stack.enter_context(patch.object(backend, 'watch_manual_agent_turn', instant))
        self.stack.enter_context(patch.object(server, 'MAX_TERMINAL_WORK_RECORDS', 512))
        self.stack.enter_context(patch.object(server, 'MAX_EXPIRED_WORK_RECORDS', 512))
        refs = []
        first_receipt = None
        for i in range(600):
            dispatched = await self.delegate('a')
            self.assertTrue(dispatched['ok'], dispatched)
            ref = dispatched['work_ref']; refs.append(ref)
            receipt = await finished_work('a', ref)
            self.assertTrue(receipt['state'] in server.WORK_TERMINAL_STATES)
            await asyncio.sleep(0)  # done callback releases the handoff, never an await side effect
            self.assertFalse(server._HANDOFF_REGISTRY)
            if i == 0:
                first_receipt = receipt
            if i < 512:
                self.assertEqual(await finished_work('a', refs[0]), first_receipt)
            if i == 512:
                self.assertEqual((await finished_work('a', refs[0]))['error_type'], 'WorkRefExpired')
                self.assertTrue((await finished_work('a', refs[1]))['state'] in server.WORK_TERMINAL_STATES)
        self.assertEqual(len(self.prompts('a')), 600)
        self.assertEqual(len(server._WORK_REGISTRY), 512)
        self.assertEqual(len(server._EXPIRED_WORK_REFS), 88)
        self.assertTrue((await finished_work('a', refs[-1]))['state'] in server.WORK_TERMINAL_STATES)
        context = await server.context('a')
        capacity = context['work_capacity']
        self.assertEqual(capacity['active']['count'], 0)
        self.assertEqual(capacity['terminal_receipts'], {'count': 512, 'limit': 512})
        self.assertEqual(capacity['expired_tombstones'], {'count': 88, 'limit': 512})
        self.assertEqual(capacity['handoffs']['count'], 0)
        self.assertNotIn('work-', json.dumps(capacity))
        self.assertEqual((await server.context('b'))['work_capacity']['terminal_receipts']['count'], 0)
        # Current file evidence still resolves through a recent frozen Work after 600 turns.
        (self.roots['a']/'evidence.txt').write_text('latest evidence\n')
        self.assertTrue((await server.read('a', 'evidence.txt', work_ref=refs[-1]))['ok'])
        self.assertTrue((await server.diff('a', work_ref=refs[-1]))['ok'])

    async def test_delegation_receipt_window_across_retirement_boundary(self):
        """Contracted default-suite form of the 600-cycle retention stress.

        Keeps the real delegate/latch/delivery sequence and the exact 512/513
        retirement boundary; the full-scale loop stays behind
        BRIDGE_MAINTAINER_SUITE=1 in test_600_real_delegations_receipt_window_and_no_read_renewal.
        """
        async def instant(*args, **kwargs):
            return {'state': 'done', 'reason': 'state_transition_proven', 'post_state_change_seq': 2}
        for backend in self.backends.values():
            self.stack.enter_context(patch.object(backend, 'watch_manual_agent_turn', instant))
        self.stack.enter_context(patch.object(server, 'MAX_TERMINAL_WORK_RECORDS', 512))
        self.stack.enter_context(patch.object(server, 'MAX_EXPIRED_WORK_RECORDS', 512))
        # 511 synthetic terminals pre-fill the budget in settled order, so four
        # real cycles cross the 512/513 boundary with the same eviction order
        # (oldest settled_at first) the full lane exercises at scale. One
        # captured checkout is shared by every seeded Work: retention only
        # needs the frozen checkout identity, not a fresh capture per Work.
        seeded_checkout = EvidenceCheckout.capture(self.registry.resolve('a'), str(self.roots['a']))
        seeded = []
        for _ in range(511):
            w = server._reserve_work('a', self.registry.resolve('a'), 'fixture', {'resource_key': 'fixture'})
            w['execution_identity'] = 'bound'
            w['evidence_checkout'] = seeded_checkout
            # Synthetic terminal history has no report slot; eviction is read-neutral.
            w['submission_evidence'].update(state='delivery_unknown', mutation_possible=True,
                                            proves='delivery_unknown')
            server._latch_work_from_handoff(w['work_ref'], {
                'state': 'done', 'reason': 'synthetic observation', 'post_state_change_seq': 23})
            seeded.append(w)
        refs = []
        first_receipt = None
        for _ in range(4):
            dispatched = await self.delegate('a')
            self.assertTrue(dispatched['ok'], dispatched)
            ref = dispatched['work_ref']; refs.append(ref)
            receipt = await finished_work('a', ref)
            self.assertTrue(receipt['state'] in server.WORK_TERMINAL_STATES)
            await asyncio.sleep(0)  # done callback releases the handoff, never an await side effect
            self.assertFalse(server._HANDOFF_REGISTRY)
            if first_receipt is None:
                first_receipt = receipt
            else:
                # No read renewal: the first real receipt stays readable while
                # it is still inside the retention window.
                self.assertEqual(await finished_work('a', refs[0]), first_receipt)
        # 511 seeded + 4 real = 515 terminals: the three oldest seeded receipts
        # expired, in settled order, as each real cycle crossed the boundary.
        for expired_ref in (seeded[0]['work_ref'], seeded[1]['work_ref'], seeded[2]['work_ref']):
            self.assertEqual((await finished_work('a', expired_ref))['error_type'], 'WorkRefExpired')
        self.assertTrue((await finished_work('a', seeded[3]['work_ref']))['state'] in server.WORK_TERMINAL_STATES)
        self.assertEqual(await finished_work('a', refs[0]), first_receipt)
        self.assertEqual(len(self.prompts('a')), 4)
        self.assertEqual(len(server._WORK_REGISTRY), 512)
        self.assertEqual(len(server._EXPIRED_WORK_REFS), 3)
        self.assertTrue((await finished_work('a', refs[-1]))['state'] in server.WORK_TERMINAL_STATES)
        context = await server.context('a')
        capacity = context['work_capacity']
        self.assertEqual(capacity['active']['count'], 0)
        self.assertEqual(capacity['terminal_receipts'], {'count': 512, 'limit': 512})
        self.assertEqual(capacity['expired_tombstones'], {'count': 3, 'limit': 512})
        self.assertEqual(capacity['handoffs']['count'], 0)
        self.assertNotIn('work-', json.dumps(capacity))
        self.assertEqual((await server.context('b'))['work_capacity']['terminal_receipts']['count'], 0)
        # Current file evidence still resolves through a recent frozen Work.
        (self.roots['a']/'evidence.txt').write_text('latest evidence\n')
        self.assertTrue((await server.read('a', 'evidence.txt', work_ref=refs[-1]))['ok'])
        self.assertTrue((await server.diff('a', work_ref=refs[-1]))['ok'])

    async def test_all_terminals_oldest_settled_not_created_and_bounded_tombstones(self):
        self.stack.enter_context(patch.object(server, 'MAX_EXPIRED_WORK_RECORDS', 2))
        first = self.reserve(state='failed')
        late = server._reserve_work('a', self.registry.resolve('a'), 'late', {})
        late['created_at'] = -1
        second = self.reserve('b', state='needs_attention')
        server._latch_work_from_handoff(late['work_ref'], {'state': 'needs_attention', 'reason': 'unknown'})
        receipt = await finished_work('a', late['work_ref'])
        for _ in range(2):
            self.assertEqual(await finished_work('a', late['work_ref']), receipt)
        self.reserve()
        self.assertEqual((await finished_work('a', first['work_ref']))['error_type'], 'WorkRefExpired')
        self.assertEqual((await finished_work('b', first['work_ref']))['error_type'], 'WorkRefProjectMismatch')
        self.assertTrue((await finished_work('b', second['work_ref']))['state'] in server.WORK_TERMINAL_STATES)
        self.assertEqual(receipt['state'], 'needs_attention')
        self.reserve(); self.reserve()
        self.assertEqual((await finished_work('a', first['work_ref']))['error_type'], 'WorkRefUnavailable')
        self.assertEqual(len(server._EXPIRED_WORK_REFS), 2)

    async def test_settlement_order_and_active_sixteen_are_independent(self):
        with patch.object(server, 'MAX_ACTIVE_WORK_RECORDS', 16), patch.object(server, 'MAX_TERMINAL_WORK_RECORDS', 32):
            old = server._reserve_work('a', self.registry.resolve('a'), 'first-created', {})
            newer = self.reserve()
            server._latch_work_from_handoff(old['work_ref'], {'state': 'done', 'reason': 'later'})
            self.reserve()
            self.assertIn(old['work_ref'], server._WORK_REGISTRY)
            with patch.object(server, 'MAX_TERMINAL_WORK_RECORDS', 2):
                server._expire_terminal_work('a', str(self.roots['a']))
            self.assertNotIn(newer['work_ref'], server._WORK_REGISTRY)
            active = [server._reserve_work('a', self.registry.resolve('a'), str(i), {}) for i in range(16)]
            active[0]['state'] = 'delivery_unknown'
            with self.assertRaises(server.WorkRegistryFullError) as raised:
                server._reserve_work('a', self.registry.resolve('a'), 'seventeen', {})
            self.assertEqual(raised.exception.capacity['dimension'], 'work_active')
            self.assertEqual(raised.exception.capacity['count'], 16)
            self.assertTrue(all(w['work_ref'] in server._WORK_REGISTRY for w in active))
            with patch.object(server, '_deployment_snapshot', return_value={}):
                snapshot = await server.bridge_overview('a')
            diagnostic = snapshot['project_state']['work_capacity']
            self.assertEqual(diagnostic['active'], {'count': 16, 'limit': 16})
            self.assertEqual(diagnostic['terminal_receipts']['count'], 2)

    async def test_frozen_linked_evidence_and_expiration_never_fallback(self):
        root = self.roots['a']; linked = root.parent/'linked'
        def git(*args):
            return subprocess.check_output(['git', '-c', 'core.hooksPath=/dev/null',
                '-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid', *args], cwd=root)
        (root/'sample').write_text('root\n'); git('add', 'sample'); git('commit', '-qm', 'fixture')
        git('worktree', 'add', '-qb', 'linked', str(linked))
        (linked/'sample').write_text('linked only\n')
        checkout = EvidenceCheckout.capture(self.registry.resolve('a'), str(linked))
        for state in ('done', 'needs_attention', 'failed'):
            w = self.reserve(state=state, checkout=checkout)
            ref = w['work_ref']; receipt = await finished_work('a', ref)
            self.assertEqual(receipt['submission_evidence']['state'], 'delivery_unknown')
            result = await server.read('a', 'sample', work_ref=ref)
            self.assertEqual(result['content'], 'linked only\n')
            self.assertEqual(result['execution_target'], str(linked))
            self.assertTrue((await server.diff('a', work_ref=ref))['ok'])
            self.assertEqual(await finished_work('a', ref), receipt)
        self.reserve(); self.reserve()
        calls = [(server.read, {'path': 'sample'}), (server.search, {'query': 'root'}),
                 (server.search, {'query': 'root', 'include_untracked': True}), (server.diff, {}),
                 (server.commit_prepare, {})]
        with patch.object(server, '_discover_project_candidates', side_effect=AssertionError('no rediscovery')):
            for call, args in calls:
                result = await call('a', work_ref=ref, **args)
                self.assertEqual(result['error_type'], 'WorkRefExpired', result)
                self.assertNotIn('content', result)
        # Fresh process-equivalent registries do not restore refs or infer restart as the only cause.
        with patch.object(server, '_WORK_REGISTRY', {}), patch.object(server, '_RESULT_INBOX', {}), \
                patch.object(server, '_EXPIRED_WORK_REFS', {}):
            self.assertEqual((await finished_work('a', ref))['error_type'], 'WorkRefUnavailable')
            self.assertEqual((await server.read('a', 'sample', work_ref=ref))['error_type'], 'WorkRefUnavailable')

    async def test_unknown_nonterminal_is_never_collected_or_unlocked(self):
        w = server._reserve_work('a', self.registry.resolve('a'), 'unknown', {})
        w.update(state='delivery_unknown', created_at=0, settled_at=0,
                 evidence_checkout=EvidenceCheckout.capture(self.registry.resolve('a'), str(self.roots['a'])))
        for _ in range(20): self.reserve('b')
        server._expire_terminal_work('a', str(self.roots['a']))
        self.assertIs(server._WORK_REGISTRY[w['work_ref']], w)
        self.assertNotIn(w['state'], server.WORK_TERMINAL_STATES)
        self.assertEqual(w['evidence_checkout'].root, self.roots['a'])
        blocked = await self.delegate('a')
        self.assertEqual(blocked['error_type'], 'WorkRegistryFull')
        self.assertEqual(self.prompts('a'), [])

    async def test_expiration_preserves_held_latched_object(self):
        w = server._reserve_work('a', self.registry.resolve('a'), 'held', {})
        server._latch_work_from_handoff(w['work_ref'], {'state': 'failed', 'reason': 'identity mismatch'})
        before = work_record(w)
        self.reserve(); self.reserve()
        self.assertEqual(work_record(w), before)
        self.assertEqual(w['state'], 'continuity_lost')
        self.assertEqual((await finished_work('a', w['work_ref']))['error_type'], 'WorkRefExpired')

    async def test_done_callback_frees_task_context_without_cancelling_live_watcher(self):
        class Payload: pass
        context = contextvars.ContextVar('retention_test')
        async def completed(*args, **kwargs): return {'state': 'done', 'reason': 'done'}
        w = server._reserve_work('a', self.registry.resolve('a'), 'fixture', {})
        h = server._reserve_handoff('fixture', {}, 'a', 0, 0, str(self.roots['a']))
        h['work_ref'] = w['work_ref']; w['handoff_id'] = h['handoff_id']
        payload = Payload(); payload_ref = weakref.ref(payload)
        token = context.set(payload)
        task = server._start_handoff_watcher(SimpleNamespace(watch_manual_agent_turn=completed), h)
        task_ref = weakref.ref(task)
        context.reset(token); del payload
        server._release_completed_handoff(h['handoff_id'], task)
        self.assertIn(h['handoff_id'], server._HANDOFF_REGISTRY)
        self.assertFalse(task.cancelled())
        await task; await asyncio.sleep(0)
        self.assertNotIn(h['handoff_id'], server._HANDOFF_REGISTRY)
        self.assertIsNone(h['watcher_task'])
        del task
        await asyncio.sleep(0); gc.collect()
        self.assertIsNone(task_ref())
        self.assertIsNone(payload_ref())
        self.assertTrue((await finished_work('a', w['work_ref']))['state'] in server.WORK_TERMINAL_STATES)

    async def test_watcher_release_precedes_delegate_response_without_losing_receipt(self):
        async def completed(*args, **kwargs): return {'state': 'done', 'reason': 'fast'}
        backend = self.backends[str(self.roots['a'])]
        released = asyncio.Event(); reply = asyncio.Event()
        original = server._AccessLease.release
        async def delayed(lease):
            await original(lease)
            released.set()
            await reply.wait()
        with patch.object(backend, 'watch_manual_agent_turn', completed), patch.object(
                server._AccessLease, 'release', delayed):
            dispatch = asyncio.create_task(self.delegate('a'))
            await asyncio.wait_for(released.wait(), 2)
            work = next(iter(server._WORK_REGISTRY.values()))
            receipt = await finished_work('a', work['work_ref'])
            await asyncio.sleep(0)
            self.assertFalse(server._HANDOFF_REGISTRY)
            self.assertFalse(dispatch.done())
            reply.set()
            result = await dispatch
        self.assertEqual(result['work_ref'], work['work_ref'])
        self.assertEqual(await finished_work('a', result['work_ref']), receipt)

    async def test_new_python_process_has_no_work_or_tombstone_recovery(self):
        work = self.reserve()
        code = ("import json; from gpt_agent_bridge import server; print(json.dumps({'works':len(server._WORK_REGISTRY),"
                "'expired':len(server._EXPIRED_WORK_REFS), 'inbox':len(server._RESULT_INBOX),"
                "'lookup':server._lookup_work('a'," + repr(str(self.roots['a'])) + ","
                + repr(work['work_ref']) + ")}))")
        env = {'PATH': os.defpath, 'LANG': 'C.UTF-8', 'PYTHONDONTWRITEBYTECODE': '1',
               'BRIDGE_PATH_TOKEN': 'synthetic-restart-only-0123456789abcdef',
               'BRIDGE_WORKSPACE': str(self.roots['a']),
               'BRIDGE_WORKSPACE_STORE_PATH': str(self.roots['a'].parent/'fresh-registry.json')}
        result = await asyncio.to_thread(subprocess.run, [sys.executable, '-B', '-c', code],
                                         env=env, capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads(result.stdout)
        self.assertEqual((data['works'], data['expired'], data['inbox']), (0, 0, 0))
        self.assertEqual(data['lookup']['error_type'], 'WorkRefUnavailable')


    async def test_already_finished_watcher_callback_registration(self):
        # Simulate eager task completion before _start_handoff_watcher assigns it.
        w = server._reserve_work('a', self.registry.resolve('a'), 'fixture', {})
        h = server._reserve_handoff('fixture', {}, 'a', 0, 0, str(self.roots['a']))
        h['work_ref'] = w['work_ref']
        async def completed(*args, **kwargs): return {'state': 'needs_attention', 'reason': 'unknown'}
        backend = SimpleNamespace(watch_manual_agent_turn=completed)
        done = asyncio.create_task(server._watch_handoff_task(backend, h['handoff_id']))
        await done
        def create(coro):
            coro.close()
            return done
        with patch.object(server.asyncio, 'create_task', create):
            server._start_handoff_watcher(backend, h)
        await asyncio.sleep(0)
        self.assertNotIn(h['handoff_id'], server._HANDOFF_REGISTRY)
        self.assertIsNone(h['watcher_task'])


class WorkRetentionCandidateTests(unittest.IsolatedAsyncioTestCase):
    setUp = convergence_tests.ConvergenceFinalTests.setUp
    git = convergence_tests.ConvergenceFinalTests.git
    wire = convergence_tests.ConvergenceFinalTests.wire
    stage = convergence_tests.ConvergenceFinalTests.stage
    preview = convergence_tests.ConvergenceFinalTests.preview

    def terminal(self):
        w = server._WORK_REGISTRY['w']
        w.update(work_ref='w', state='agent_turn_settled', settled_at=1,
                 reason='settled', post_state_change_seq=2, submission_evidence={})
        p = patch.object(server, '_EXPIRED_WORK_REFS', {}); p.start(); self.addCleanup(p.stop)

    def expire(self):
        with patch.object(server, 'MAX_TERMINAL_WORK_RECORDS', 0):
            server._expire_terminal_work('p', str(self.root))

    async def assert_cached_history(self, token, message, result):
        # Work lookup and Git are forbidden, including when its tombstone is gone.
        with patch.object(server, '_resolve_evidence_target', side_effect=AssertionError('no Work resolution')), \
             patch.object(commit_candidate, '_run_git', side_effect=AssertionError('no Git')) as git:
            for unavailable in (False, True):
                if unavailable:
                    server._EXPIRED_WORK_REFS.clear()
                self.assertEqual(await server.commit('p', token, message), result)
                different = await server.commit('p', token, message + ' changed')
                self.assertEqual(different['reason'], 'candidate-already-attempted-with-different-message')
                events = []; offset = 0
                while True:
                    page = await server.commit_prepare('p', work_ref='w', candidate_id=token,
                                                       view='receipt', offset=offset, limit=1)
                    self.assertEqual(page['status'], result['status'])
                    self.assertEqual(page['result'], self.store._items[token]['receipt']['result'])
                    events.extend(page['events'])
                    if page['next_offset'] is None: break
                    offset = page['next_offset']
                self.assertEqual(len(events), page['total'])
                for view in ('summary', 'patch'):
                    page = await server.commit_prepare('p', work_ref='w', candidate_id=token, view=view, limit=1)
                    self.assertEqual(page['status'], 'previewed')
                    self.assertEqual(page['execution_target'], str(self.link))
                wrong = await server.commit_prepare('p', candidate_id=token, view='receipt')
                self.assertEqual(wrong['reason'], 'candidate-project-work-mismatch')
            self.assertEqual(git.call_count, 0)

    async def test_candidate_eviction_is_unavailable_and_does_not_recapture(self):
        self.terminal(); self.stage(self.link)
        old = await self.preview('w'); token = old['candidate_id']
        with patch.object(commit_candidate, 'MAX_CANDIDATES', 1):
            newer = await self.preview('w')
        self.assertNotEqual(token, newer['candidate_id'])
        self.assertNotIn(token, self.store._items)
        with patch.object(server, '_resolve_evidence_target', side_effect=AssertionError('no lookup')), \
             patch.object(commit_candidate, '_run_git', side_effect=AssertionError('no Git')):
            result = await server.commit('p', token, 'lost')
            self.assertEqual(result['reason'], 'candidate-unavailable-no-recapture')
            for view in ('summary', 'patch', 'receipt'):
                result = await server.commit_prepare('p', work_ref='w', candidate_id=token, view=view)
                self.assertEqual(result['reason'], 'candidate-unavailable-no-recapture')

    async def test_terminal_candidate_commits_and_replays_after_expiry_without_rebinding(self):
        self.terminal(); self.stage(self.link)
        candidate = await self.preview('w'); token = candidate['candidate_id']
        result = await server.commit('p', token, 'terminal linked candidate')
        self.assertEqual(result['status'], 'committed', result)
        self.expire()
        with patch.object(commit_candidate, '_run_git', side_effect=AssertionError('no new Git')):
            await self.assert_cached_history(token, 'terminal linked candidate', result)
        self.assertEqual(self.store._items[token]['receipt']['status'], 'committed')

    async def test_unattempted_candidate_after_expiry_never_executes_or_recaptures(self):
        self.terminal(); self.stage(self.link)
        candidate = await self.preview('w'); token = candidate['candidate_id']
        self.expire()
        with patch.object(commit_candidate, '_run_git', side_effect=AssertionError('no mutation or recapture')):
            result = await server.commit('p', token, 'must not execute')
            self.assertEqual(result['error_type'], 'WorkRefExpired')
        self.assertNotIn('receipt', self.store._items[token])

    async def test_unknown_candidate_quarantine_survives_work_gc(self):
        self.terminal(); self.stage(self.link)
        candidate = await self.preview('w'); token = candidate['candidate_id']
        original = commit_candidate._run_git
        def uncertain(*args, **kwargs):
            if 'update-ref' in args[1]:
                raise TimeoutError('synthetic unknown mutation')
            return original(*args, **kwargs)
        with patch.object(commit_candidate, '_run_git', side_effect=uncertain):
            result = await server.commit('p', token, 'unknown terminal candidate')
        self.assertEqual(result['status'], 'unknown', result)
        self.expire()
        self.assertEqual(self.store._items[token]['receipt']['status'], 'unknown')
        # New project-root route to the same branch cannot escape the unknown target quarantine.
        target = self.store._items[token]['target']
        self.assertTrue(self.store._quarantined(target))
        with patch.object(commit_candidate, '_run_git', side_effect=AssertionError('no retry')):
            await self.assert_cached_history(token, 'unknown terminal candidate', result)
        self.assertIn(token, self.store._items)
        replacement = server._reserve_work('p', self.registry.resolve('p'), 'new', {})
        replacement.update(state='agent_turn_settled', settled_at=2,
                           execution_identity='bound', evidence_checkout=server.EvidenceCheckout.capture(
                               self.registry.resolve('p'), str(self.link)))
        rejected = await server.commit_prepare('p', work_ref=replacement['work_ref'])
        self.assertEqual(rejected['status'], 'rejected', rejected)
        self.assertEqual(rejected['reason'], 'checkout-quarantined-unknown-attempt')
