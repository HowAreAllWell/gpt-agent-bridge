"""Project-local admission; synthetic projects never contact a real Agent."""
import asyncio
import contextlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault("BRIDGE_PATH_TOKEN", "test-token-abcdefghijklmnopqrstuvwxyz-012345")
_import_store = tempfile.TemporaryDirectory(prefix="bridge-capacity-registry-")
os.environ["BRIDGE_WORKSPACE_STORE_PATH"] = str(Path(_import_store.name) / "registry.json")

from gpt_agent_bridge import server
from tests.work_observation import delegate_item
from tests.work_observation import finished_work
from gpt_agent_bridge import work_reports
from tests.test_manual_agents import manual_backend
from tests.test_work_surface import git_worktree, _slow_watch
from gpt_agent_bridge.workspace_context import WorkspaceRegistry, WorkspaceRegistryStore


class WorkCapacityTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        base = Path(self.temp.name)
        self.roots = {ref: git_worktree(base / ref) for ref in ('a', 'b')}
        self.registry = WorkspaceRegistry(self.roots['a'], json.dumps(
            {ref: str(root) for ref, root in self.roots.items()}),
            store=WorkspaceRegistryStore(base / 'registry.json'))
        self.backends = {}
        self.states = {}
        for ref, root in self.roots.items():
            self.backends[str(root)], self.states[ref] = manual_backend(root)
        self.store = work_reports.ReportStore()
        self.addCleanup(self.store.close)
        self.stack = contextlib.ExitStack()
        self.addCleanup(self.stack.close)
        for name, value in (
            ('_WORKSPACE_REGISTRY', self.registry), ('_WORKSPACE_BACKENDS', self.backends),
            ('_WORK_REGISTRY', {}), ('_RESULT_INBOX', {}), ('_HANDOFF_REGISTRY', {}),
            ('_REPORT_STORE', self.store), ('_CLASSIFICATION_TASKS', set()),
            ('_CLASSIFICATION_INFLIGHT', set()), ('_WORK_WATCH_WAITERS', {}), ('_WORK_WATCHES', {}),
            ('_REPORT_EVIDENCE_EXTRA_ATTEMPTS', 0),
            ('_MANUAL_AGENT_CANDIDATES', {}), ('MAX_TERMINAL_WORK_RECORDS', 2),
            ('_EXPIRED_WORK_REFS', {}),
            ('MAX_ACTIVE_WORK_RECORDS', 1), ('MAX_HANDOFF_RECORDS', 2),
        ):
            self.stack.enter_context(patch.object(server, name, value))
        for backend in self.backends.values():
            self.stack.enter_context(patch.object(backend, 'watch_manual_agent_turn', _slow_watch))

    async def asyncTearDown(self):
        for entry in list(server._HANDOFF_REGISTRY.values()):
            task = entry.get('watcher_task')
            if task is not None:
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task

        tasks = list(server._CLASSIFICATION_TASKS)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    async def consume_deliveries(self, ref):
        """Claim original delegate cohorts, never register a history-wide substitute."""
        await asyncio.gather(*list(server._CLASSIFICATION_TASKS))
        scope = (ref, str(self.registry.resolve(ref).root))
        with server._WORK_REGISTRY_LOCK:
            watch_refs = [watch['watch_ref'] for watch in server._WORK_WATCHES.values()
                          if watch['scope'] == scope and not watch['consumed']]
        claims = []
        for watch_ref in watch_refs:
            result = await server.mcp.call_tool('claim_work_watch', {
                'project_ref': ref, 'watch_ref': watch_ref})
            claim = result.structured_content
            self.assertTrue(claim['ok'], claim)
            self.assertTrue(claim['granted'], claim)
            claims.append(claim)
        return claims

    async def delegate(self, ref):
        discovered = await server._discover_project_candidates(workspace_ref=ref)
        self.assertTrue(discovered['ok'], discovered)
        agent = discovered['candidates'][0]['candidate_id']
        await asyncio.gather(*list(server._CLASSIFICATION_TASKS))
        # Capacity fixtures publish no reports. Serve current diagnostics before
        # deliberate reuse, so this suite exercises capacity rather than the gate.
        if any(server._diagnostic_condition(w) for w in server._WORK_REGISTRY.values()
               if w['project_ref'] == ref):
            self.assertTrue((await server.agent_terminal_read(ref, agent))['ok'])
        return await delegate_item(ref, assignments=[{'agent_ref': agent, 'task': 'capacity test'}])

    def settle(self, work_ref):
        work = server._WORK_REGISTRY[work_ref]
        server._update_handoff_entry(work['handoff_id'], state='done',
            reason='state_transition_proven', herdr_status='idle', post_seq=2, post_rev=2)

    def prompts(self, ref):
        return [c for c in self.states[ref]['calls'] if c[:2] == ('agent', 'prompt')]

    async def test_consumed_terminal_pressure_preserves_active_admission(self):
        async def instant(*args, **kwargs):
            return {'state': 'done', 'reason': 'settled'}
        for backend in self.backends.values():
            self.stack.enter_context(patch.object(backend, 'watch_manual_agent_turn', instant))
        first = await self.delegate('a')
        await finished_work('a', first['work_ref'])
        await asyncio.sleep(0)
        receipt = await finished_work('a', first['work_ref'])
        self.assertEqual(len(await self.consume_deliveries('a')), 1)
        second = await self.delegate('a')
        await finished_work('a', second['work_ref'])
        await asyncio.sleep(0)
        self.assertEqual(await finished_work('a', first['work_ref']), receipt)
        self.assertEqual(len(await self.consume_deliveries('a')), 1)
        third = await self.delegate('a')
        self.assertTrue(third['ok'], third)
        await finished_work('a', third['work_ref'])
        await asyncio.sleep(0)
        self.assertEqual((await finished_work('a', first['work_ref']))['error_type'], 'WorkRefExpired')
        self.assertTrue((await finished_work('a', second['work_ref']))['state'] in server.WORK_TERMINAL_STATES)
        self.assertEqual(len(self.prompts('a')), 3)
        self.assertTrue((await self.delegate('b'))['ok'])

    async def test_original_cohorts_release_ownership_across_capacity_cycles(self):
        async def instant(*args, **kwargs):
            return {'state': 'done', 'reason': 'settled'}
        for backend in self.backends.values():
            self.stack.enter_context(patch.object(backend, 'watch_manual_agent_turn', instant))
        refs = []
        for _ in range(6):
            dispatched = await self.delegate('a')
            self.assertTrue(dispatched['ok'], dispatched)
            ref = dispatched['work_ref']
            refs.append(ref)
            receipt = await finished_work('a', ref)
            await asyncio.gather(*list(server._CLASSIFICATION_TASKS))
            work = server._WORK_REGISTRY[ref]
            self.assertEqual(len(work['watch_refs']), 1)
            watch_ref = next(iter(work['watch_refs']))
            original = server._WORK_WATCHES[watch_ref]
            self.assertEqual(original['members'], (ref,))
            self.assertFalse(original['consumed'])
            self.assertTrue(server._delivery_protected(work))
            registered = set(server._WORK_WATCHES)
            await self.consume_deliveries('a')
            self.assertEqual(set(server._WORK_WATCHES), registered)
            self.assertTrue(original['consumed'])
            self.assertTrue(work['delivery_consumed'])
            self.assertEqual(work['watch_refs'], set())
            self.assertFalse(server._delivery_protected(work))
            duplicate = await server.claim_work_watch('a', watch_ref)
            self.assertFalse(duplicate['granted'])
            self.assertEqual(duplicate['reason'], 'already_consumed')
            self.assertEqual(await finished_work('a', ref), receipt)
            if len(refs) > 2:
                self.assertEqual((await finished_work('a', refs[0]))['error_type'], 'WorkRefExpired')
            await asyncio.sleep(0)
        self.assertEqual(len(self.prompts('a')), 6)
        self.assertEqual(len(server._WORK_REGISTRY), 2)
        self.assertEqual(len(server._EXPIRED_WORK_REFS), 4)
        self.assertTrue(all(watch['consumed'] for watch in server._WORK_WATCHES.values()))

    async def test_active_full_fails_before_prompt_without_blocking_other_project(self):
        # An earlier reservation for another resource consumes A's active slot.
        server._reserve_work('a', self.registry.resolve('a'), 'other-agent',
                             {'resource_key': 'other-resource'})
        blocked = await self.delegate('a')
        self.assertEqual(blocked['error_type'], 'WorkRegistryFull')
        self.assertEqual(blocked['capacity']['dimension'], 'work_active')
        self.assertEqual(blocked['capacity']['count'], 1)
        self.assertEqual(blocked['capacity']['limit'], 1)
        self.assertEqual(self.prompts('a'), [])
        self.assertTrue((await self.delegate('b'))['ok'])
        self.assertEqual(len(self.prompts('b')), 1)

    async def test_full_unconsumed_handoff_pool_does_not_block_other_project(self):
        # Internal admission cannot impose a hidden process-global limit.
        for i in range(2):
            server._HANDOFF_REGISTRY[f'handoff-a-{i}'] = {
                'workspace_ref': 'a', 'workspace_root': str(self.roots['a']),
                'state': 'running', 'joined_once': False}
        blocked = await self.delegate('a')
        self.assertEqual(blocked['error_type'], 'WorkDispatchBlocked')
        self.assertEqual(blocked['capacity'], {
            'scope': 'project', 'dimension': 'handoff_retained', 'count': 2, 'limit': 2})
        self.assertEqual(self.prompts('a'), [])
        self.assertEqual(server._WORK_REGISTRY, {})
        self.assertTrue((await self.delegate('b'))['ok'])
        self.assertEqual(len(server._HANDOFF_REGISTRY), 3)

    async def test_handoff_pruning_never_drops_a_running_watcher(self):
        first = await self.delegate('a')
        self.settle(first['work_ref'])
        other = await self.delegate('b')
        self.settle(other['work_ref'])
        other_hid = server._WORK_REGISTRY[other['work_ref']]['handoff_id']
        with patch.object(server, 'MAX_HANDOFF_RECORDS', 1):
            blocked = await self.delegate('a')
        self.assertEqual(blocked['error_type'], 'WorkDispatchBlocked')
        self.assertIn(other_hid, server._HANDOFF_REGISTRY)
        self.assertTrue((await finished_work('a', first['work_ref']))['state'] in server.WORK_TERMINAL_STATES)
