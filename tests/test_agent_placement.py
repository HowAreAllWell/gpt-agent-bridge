"""Checkout display stays independent of resource identity and admission."""
import asyncio
import json
import os
import sys
import time
import subprocess
import unittest
from unittest.mock import AsyncMock, patch

import agent_placement
from evidence_target import EvidenceCheckout
from tests import test_discovery_coverage
import server


class AgentPlacementTests(unittest.IsolatedAsyncioTestCase):
    setUp = test_discovery_coverage.DiscoveryCoverageTests.setUp
    agent = test_discovery_coverage.DiscoveryCoverageTests.agent

    def git(self, root, *args):
        return subprocess.check_output(["git", "-C", str(root), *args]).decode().strip()

    async def test_cross_workspace_same_tab_pane_and_shared_roster(self):
        self.agents = [self.agent(self.root, 1), self.agent(self.linked, 2)]
        for n, item in enumerate(self.agents):
            item.update(workspace_id=f"ws{n}", tab_id=f"ws{n}:t1", pane_id=f"ws{n}:p1")
            item["workspace_name"] = "unverified-private-name"
        context = await server.context('p')
        roster = context['agents']
        self.assertEqual([a['workspace_id'] for a in roster], ['ws0', 'ws1'])
        self.assertEqual([a['hint'] for a in roster], ['tab 1 / pane 1'] * 2)
        self.assertNotEqual(roster[0]['handle'], roster[1]['handle'])
        for row, root in zip(roster, (self.root, self.linked)):
            self.assertEqual(row['checkout'], dict(status='observed', root=str(root),
                branch=self.git(root, 'branch', '--show-current'),
                head=self.git(root, 'rev-parse', 'HEAD'), dirty=False))
        snapshot = await server.bridge_overview(project_ref='p')
        self.assertEqual(snapshot['agents'], roster)
        self.assertNotIn('unverified-private-name', json.dumps([context, snapshot]))
        self.assertNotIn('foreground_process', json.dumps(roster))

    async def test_same_checkout_reuses_git_and_does_not_change_handle(self):
        self.agents = [self.agent(self.root, 1), self.agent(self.root, 2)]
        with patch.object(agent_placement.fixed_git, 'execute',
                          wraps=agent_placement.fixed_git.execute) as observe:
            first = await server.context('p')
            self.assertEqual(observe.await_count, 1)  # One guarded observation (config + status), one checkout.
        (self.root / 'private-untracked-name').write_text('secret')
        second = await server.context('p')
        self.assertEqual([a['handle'] for a in first['agents']], [a['handle'] for a in second['agents']])
        self.assertTrue(all(a['checkout']['dirty'] is True for a in second['agents']))
        self.assertNotIn('private-untracked-name', json.dumps(second['agents']))

    async def test_detached_and_tracked_dirty(self):
        self.agents = [self.agent(self.linked, 1)]
        self.git(self.linked, 'checkout', '--detach', '--quiet')
        tracked = self.git(self.linked, 'ls-files').splitlines()[0]
        (self.linked / tracked).write_text('changed')
        row = (await server.context('p'))['agents'][0]['checkout']
        self.assertEqual(row['status'], 'observed')
        self.assertIsNone(row['branch'])
        self.assertTrue(row['dirty'])
        self.assertEqual(row['head'], self.git(self.linked, 'rev-parse', 'HEAD'))

    async def test_restart_fresh_process_observes_idle_linked_worktree_checkout(self):
        # Model a Bridge restart: setUp rebuilds a fresh registry/backend and
        # clears the process-local candidate cache, so discovery re-derives the
        # checkout from cwd + Git common-dir from scratch. An idle Agent whose cwd
        # is a linked worktree of the registered project must still project its
        # checkout root/head/branch as observed (not lost across the restart).
        self.agents = [self.agent(self.root, 1), self.agent(self.linked, 2)]
        for agent in self.agents:
            agent['agent_status'] = 'idle'
        result = await server.context('p')
        self.assertTrue(result['agents_complete'])
        self.assertEqual(result['agents_skipped_count'], 0)
        by_root = {a['checkout']['root']: a['checkout'] for a in result['agents']}
        worktree = by_root[str(self.linked)]
        self.assertEqual(worktree['status'], 'observed')
        self.assertEqual(worktree['head'], self.git(self.linked, 'rev-parse', 'HEAD'))
        self.assertEqual(worktree['branch'], self.git(self.linked, 'branch', '--show-current'))
        self.assertFalse(worktree['dirty'])

    async def test_transient_git_timeout_projects_deferred_not_unknown(self):
        # Regression for the post-restart projection bug: an identity-valid linked
        # worktree whose guarded `git status` does not complete within the
        # per-command budget (cold/slow on a fresh process) is a transient
        # deferral, never "unknown" (which asserts host evidence is absent).
        project = server._workspace_context('p')
        checkout = EvidenceCheckout.capture(project, str(self.linked))
        source = {'identity': {'cwd': str(self.linked)}, '_placement_checkout': checkout}
        timeout = {'outcome': 'unavailable', 'exit_code': -1,
                   'stdout': {'text': '', 'capture_complete': False},
                   'stderr': {'text': 'GitObservationTimeout: coverage incomplete',
                              'capture_complete': False}}
        with patch.object(agent_placement.fixed_git, 'execute', AsyncMock(return_value=timeout)):
            rows = await agent_placement.observe_all(project, [source])
        self.assertEqual(rows, [agent_placement.unavailable('deferred')])
        self.assertNotEqual(rows[0]['status'], 'unknown')

    async def test_incomplete_but_oversized_or_unsupported_read_stays_unknown(self):
        # Non-completion sentinels other than a budget timeout (oversized -2,
        # clean/process-filter unsupported -3) mean Git facts genuinely cannot be
        # shown; they must stay "unknown", not become "deferred".
        project = server._workspace_context('p')
        checkout = EvidenceCheckout.capture(project, str(self.linked))
        source = {'identity': {'cwd': str(self.linked)}, '_placement_checkout': checkout}
        for code in (-2, -3):
            result = {'outcome': 'unavailable', 'exit_code': code,
                      'stdout': {'text': '', 'capture_complete': False},
                      'stderr': {'text': 'x', 'capture_complete': False}}
            with self.subTest(exit_code=code), patch.object(
                    agent_placement.fixed_git, 'execute', AsyncMock(return_value=result)):
                rows = await agent_placement.observe_all(project, [source])
            self.assertEqual(rows, [agent_placement.unavailable()])

    async def test_genuinely_unavailable_cwd_remains_unknown(self):
        # No authoritative checkout can be derived (cwd absent, or a cwd discovery
        # pinned no placement for): the projection stays explicit "unknown".
        project = server._workspace_context('p')
        for source in ({'identity': {'cwd': None}, '_placement_checkout': None},
                       {'identity': {'cwd': str(self.foreign)}, '_placement_checkout': None}):
            with self.subTest(source=source['identity']['cwd']):
                rows = await agent_placement.observe_all(project, [source])
            self.assertEqual(rows, [agent_placement.unavailable()])
            self.assertEqual(rows[0]['status'], 'unknown')

    def source(self, root=None, checkout=None):
        root = root or self.root
        return {'identity': {'cwd': str(root)}, '_placement_checkout': checkout}

    def output(self, head='a'*40, branch='main', tail=''):
        return dict(outcome='exited', exit_code=0, stdout={
            'capture_complete': True,
            'text': f'# branch.oid {head}\0# branch.head {branch}\0' + tail})

    async def test_unknown_truncated_error_and_changed_never_clean(self):
        project = server._workspace_context('p')
        good = self.output()
        for observed in ({}, dict(good, exit_code=128), dict(good, outcome='timeout'),
                         dict(good, stdout={'text': '', 'capture_complete': False}),
                         self.output(head='(initial)'), self.output(branch='')):
            with self.subTest(observed=observed), patch.object(
                    agent_placement.fixed_git, 'execute', AsyncMock(return_value=observed)) as execute:
                self.assertEqual(await agent_placement.observe_all(project, [self.source()]*32),
                                 [agent_placement.unavailable()]*32)
                self.assertEqual(execute.await_count, 1)
        with patch.object(agent_placement.fixed_git, 'execute', AsyncMock(side_effect=OSError('private-secret'))):
            self.assertEqual(await agent_placement.observe_all(project, [self.source()]),
                             [agent_placement.unavailable()])

    async def test_unknown_and_replaced_checkout_do_not_read_unrelated_git(self):
        project = server._workspace_context('p')
        checkout = EvidenceCheckout.capture(project, str(self.linked))
        self.linked.rename(self.linked.with_name('moved'))
        self.linked.symlink_to(self.foreign, target_is_directory=True)
        with patch.object(agent_placement.fixed_git, 'execute', AsyncMock()) as execute:
            result = await agent_placement.observe_all(project, [
                self.source(self.foreign), self.source(self.linked, checkout)])
            self.assertEqual(result, [agent_placement.unavailable(), agent_placement.unavailable('changed')])
            execute.assert_not_awaited()
        self.agents = [self.agent(self.linked, 1)]
        result = await server.context('p')
        self.assertEqual(result['agents'], [])
        self.assertNotIn(str(self.foreign), json.dumps(result))

    async def test_replacement_during_observation_discards_values(self):
        project = server._workspace_context('p')
        checkout = EvidenceCheckout.capture(project, str(self.linked))
        async def change(*args):
            self.linked.rename(self.linked.with_name('moved'))
            self.linked.symlink_to(self.foreign, target_is_directory=True)
            return self.output(branch='private-branch')
        with patch.object(agent_placement.fixed_git, 'execute', side_effect=change):
            self.assertEqual(await agent_placement.observe_all(project, [self.source(self.linked, checkout)]),
                             [agent_placement.unavailable('changed')])

    async def test_discovery_pins_checkout_before_process_observation(self):
        self.agents = [self.agent(self.linked, 1)]
        original = self.backend._call
        async def call(*args, **kwargs):
            result = await original(*args, **kwargs)
            if args[:2] == ('pane', 'process-info'):
                self.linked.rename(self.linked.with_name('moved'))
                self.linked.symlink_to(self.foreign, target_is_directory=True)
            return result
        self.backend._call = call
        with patch.object(agent_placement.fixed_git, 'execute', AsyncMock()) as execute:
            result = await server.context('p')
            execute.assert_not_awaited()
        self.assertEqual(result['agents'][0]['checkout'], agent_placement.unavailable('changed'))
        self.assertTrue(result['agents_complete'])
        self.assertNotIn(str(self.foreign), json.dumps(result))

    async def test_unknown_cwd_and_enrichment_failure_preserve_coverage(self):
        self.agents = [self.agent(self.root, 1)]
        self.agents[0]['cwd'] = None
        result = await server.context('p')
        self.assertEqual(result['agents'], [])
        self.assertFalse(result['agents_complete'])
        self.agents = [self.agent(self.root, 1), self.agent(self.linked, 2)]
        with patch.object(agent_placement, 'observe_all', AsyncMock(side_effect=RuntimeError('private-error'))):
            for result in (await server.context('p'), await server.bridge_overview('p')):
                self.assertEqual(len(result['agents']), 2)
                self.assertTrue(all(a['checkout'] == agent_placement.unavailable() for a in result['agents']))
                self.assertNotIn('private-error', json.dumps(result))
        with patch.object(agent_placement, 'TOTAL_SECONDS', 0):
            result = await server.context('p')
        self.assertEqual(result['agent_count'], 2)
        self.assertTrue(result['agents_complete'])
        self.assertEqual({a['checkout']['status'] for a in result['agents']}, {'deferred'})

    async def test_slow_failed_tree_keeps_roster_and_other_tree_metadata(self):
        self.agents = [self.agent(self.root, 1), self.agent(self.linked, 2)]
        native = agent_placement.fixed_git.execute
        async def execute(root, *args):
            if root == self.root:
                await asyncio.sleep(.03)
                raise OSError('private-error')
            return await native(root, *args)
        with patch.object(agent_placement.fixed_git, 'execute', side_effect=execute):
            result = await server.context('p')
        self.assertTrue(result['agents_complete'])
        self.assertEqual(result['agents_skipped_count'], 0)
        self.assertEqual(result['agent_count'], 2)
        self.assertEqual([a['checkout']['status'] for a in result['agents']], ['unknown', 'observed'])
        self.assertNotIn('private-error', json.dumps(result))

    async def test_pointer_change_and_special_file_never_expose_foreign_metadata(self):
        project = server._workspace_context('p')
        checkout = EvidenceCheckout.capture(project, str(self.linked))
        pointer = self.linked / '.git'
        before = pointer.read_bytes()
        for kind in ('foreign', 'symlink', 'fifo'):
            with self.subTest(kind=kind):
                pointer.unlink()
                if kind == 'foreign':
                    pointer.write_text('gitdir: ' + str(self.foreign / '.git') + '\n')
                elif kind == 'symlink':
                    pointer.symlink_to(self.root / 'README.md')
                else:
                    os.mkfifo(pointer)
                try:
                    with patch.object(agent_placement.fixed_git, 'execute', AsyncMock()) as execute:
                        rows = await agent_placement.observe_all(project, [self.source(self.linked, checkout)])
                        self.assertEqual(rows, [agent_placement.unavailable('changed')])
                        execute.assert_not_awaited()
                finally:
                    pointer.unlink()
                    pointer.write_bytes(before)

    async def test_git_config_cannot_redirect_display_to_another_worktree(self):
        project = server._workspace_context('p')
        # Reproduce a config change after discovery without replacing root/admin inodes.
        self.git(self.root, 'config', 'core.worktree', str(self.foreign))
        try:
            self.assertTrue(self.git(self.root, 'status', '--porcelain'))
            rows = await agent_placement.observe_all(project, [self.source()])
            self.assertEqual(rows[0]['status'], 'observed')
            self.assertFalse(rows[0]['dirty'])
            self.assertEqual(rows[0]['root'], str(self.root))
            self.assertNotIn(str(self.foreign), json.dumps(rows))
        finally:
            self.git(self.root, 'config', '--unset', 'core.worktree')

    async def test_reuses_identity_facts_without_added_git_validation(self):
        import workspace_context
        # Existing scope checks still run; adding the display sink adds ZERO Git calls.
        for root in (self.root, self.linked):
            agent = self.agent(root, 1)
            counts = []
            keys = []
            for cache in (None, {}):
                with patch.object(workspace_context, '_git_value', wraps=workspace_context._git_value) as git:
                    candidate = await self.backend._manual_candidate_from_agent(agent, placement_cache=cache)
                counts.append(git.call_count)
                keys.append((candidate['candidate_key'], candidate['resource_key']))
            self.assertEqual(counts[0], counts[1])
            self.assertEqual(keys[0], keys[1])
        project = server._workspace_context('p')
        with patch.object(workspace_context, '_git_value', side_effect=AssertionError('new identity Git call')), \
                patch.object(agent_placement.fixed_git, 'execute', wraps=agent_placement.fixed_git.execute) as execute:
            rows = await agent_placement.observe_all(project, [self.source()]*32)
        self.assertEqual(execute.await_count, 1)
        self.assertTrue(all(row['status'] == 'observed' for row in rows))

    def unique_sources(self, count):
        # Synthetic pinned identities isolate the budget from existing discovery cost.
        project = server._workspace_context('p')
        sources = [self.source(project.root / f'fixture-{n}',
                   EvidenceCheckout(project.root / f'fixture-{n}', project.git)) for n in range(count)]
        return project, sources

    async def test_total_work_cap_and_bounded_concurrency(self):
        project, sources = self.unique_sources(32)
        active = peak = calls = 0
        async def execute(*args):
            nonlocal active, peak, calls
            active += 1
            peak = max(peak, active)
            calls += 1
            try:
                await asyncio.sleep(.005)
                return self.output()
            finally:
                active -= 1
        with patch.object(agent_placement, '_same_objects', return_value=True), \
                patch.object(agent_placement.fixed_git, 'execute', side_effect=execute):
            rows = await agent_placement.observe_all(project, sources)
        self.assertEqual(calls, 16)
        self.assertEqual(peak, 4)
        self.assertEqual(active, 0)
        self.assertEqual([row['status'] for row in rows], ['observed']*16 + ['deferred']*16)

    async def test_shared_deadline_slow_first_tree_does_not_starve_healthy_trees(self):
        project, sources = self.unique_sources(16)
        calls, closed = [], []
        async def execute(root, argv, timeout, limit):
            calls.append(root)
            self.assertLessEqual(timeout, .08)
            try:
                if root == sources[0]['_placement_checkout'].root:
                    await asyncio.sleep(10)
                await asyncio.sleep(.001)
                return self.output()
            finally:
                closed.append(root)
        with patch.object(agent_placement, '_same_objects', return_value=True), \
                patch.object(agent_placement, 'TOTAL_SECONDS', .08), \
                patch.object(agent_placement.fixed_git, 'execute', side_effect=execute):
            start = time.monotonic()
            rows = await agent_placement.observe_all(project, sources)
            elapsed = time.monotonic() - start
        self.assertLess(elapsed, .5)  # Broad scheduling tolerance, not production SLA.
        self.assertEqual(rows[0]['status'], 'deferred')
        self.assertTrue(all(row['status'] == 'observed' for row in rows[1:]))
        self.assertEqual(set(calls), set(closed))

    async def test_all_slow_deadline_cancels_and_does_not_start_queued_work(self):
        project, sources = self.unique_sources(32)
        closed = []
        async def execute(root, *args):
            try:
                await asyncio.sleep(10)
            finally:
                closed.append(root)
        with patch.object(agent_placement, '_same_objects', return_value=True), \
                patch.object(agent_placement, 'TOTAL_SECONDS', .03), \
                patch.object(agent_placement.fixed_git, 'execute', side_effect=execute) as command:
            rows = await agent_placement.observe_all(project, sources)
        self.assertEqual(command.await_count, 4)
        self.assertEqual(len(closed), 4)
        self.assertEqual(rows, [agent_placement.unavailable('deferred')]*32)

    async def test_cancellation_joins_native_process_even_when_cancelled_twice(self):
        project = server._workspace_context('p')
        native = agent_placement.fixed_git.execute
        popen = subprocess.Popen
        processes = []
        started = asyncio.Event()
        loop = asyncio.get_running_loop()
        def spawn(*args, **kwargs):
            proc = popen([sys.executable, '-c', 'import time; time.sleep(30)'], **kwargs)
            processes.append(proc)
            loop.call_soon_threadsafe(started.set)
            return proc
        async def slow(root, *args):
            return await native(root, ['git', 'status', '--porcelain'], 60, 8192)
        with patch.object(agent_placement.fixed_git, 'execute', side_effect=slow), \
                patch.object(subprocess, 'Popen', side_effect=spawn):
            task = asyncio.create_task(agent_placement.observe_all(project, [self.source()]))
            await asyncio.wait_for(started.wait(),2)
            task.cancel()
            await asyncio.sleep(.01)
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
        self.assertEqual(len(processes), 1)
        self.assertIsNotNone(processes[0].poll())

    async def test_real_native_cleanup_on_shared_budget_expiry(self):
        project = server._workspace_context('p')
        native = agent_placement.fixed_git.execute
        popen = subprocess.Popen
        processes = []
        def spawn(*args, **kwargs):
            proc = popen([sys.executable, '-c', 'import time; time.sleep(30)'], **kwargs)
            processes.append(proc)
            return proc
        async def slow(root, *args):
            return await native(root, ['git', 'status', '--porcelain'], 60, 8192)
        with patch.object(agent_placement, 'TOTAL_SECONDS', .03), \
                patch.object(agent_placement.fixed_git, 'execute', side_effect=slow), \
                patch.object(subprocess, 'Popen', side_effect=spawn):
            rows = await agent_placement.observe_all(project, [self.source()])
        self.assertEqual(rows, [agent_placement.unavailable('deferred')])
        self.assertEqual(len(processes), 1)
        self.assertIsNotNone(processes[0].poll())

    def test_porcelain_headers_not_confused_with_rename_paths(self):
        result = agent_placement._parse(self.output(tail='2 R. N... secret\0# branch.head private\0'), self.root)
        self.assertEqual(result['branch'], 'main')
        self.assertTrue(result['dirty'])
        self.assertNotIn('private', json.dumps(result))
