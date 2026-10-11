"""Default bootstrap must obtain display facts without changing handle scope."""
import asyncio
import json
import unittest
from unittest.mock import AsyncMock, patch

import agent_placement
from workspace_context import WorkspaceContext
from tests import test_discovery_coverage
import server


class BootstrapPlacementTests(unittest.IsolatedAsyncioTestCase):
    setUp = test_discovery_coverage.DiscoveryCoverageTests.setUp
    agent = test_discovery_coverage.DiscoveryCoverageTests.agent

    async def test_default_and_registered_six_rows_have_same_placement_scoped_handles(self):
        self.agents = [self.agent(self.root if n < 3 else self.linked, n+1) for n in range(6)]
        with patch.object(server, 'ROOT', self.root), patch.object(server, 'HERDR', self.backend):
            self.assertIsNone(server._workspace_context().git)
            self.assertIsNotNone(server._workspace_context('p').git)
            with patch.object(agent_placement.fixed_git, 'execute',
                              wraps=agent_placement.fixed_git.execute) as execute:
                explicit = await server.context('p')
                self.assertEqual(execute.await_count, 2)
                execute.reset_mock()
                default = await server.bridge_overview()
                self.assertEqual(execute.await_count, 3)  # One prerequisite + two guarded tree observations (5 Git processes).
            again = await server.bridge_overview()
            self.assertIsNone(server._workspace_context().git)
        self.assertEqual(len(default['agents']), 6)
        self.assertEqual([a['checkout'] for a in default['agents']],
                         [a['checkout'] for a in explicit['agents']])
        self.assertTrue(all(a['checkout']['status'] == 'observed' for a in default['agents']))
        self.assertEqual(default['agents'], again['agents'])
        self.assertTrue({a['handle'] for a in default['agents']}.isdisjoint(
                        {a['handle'] for a in explicit['agents']}))
        self.assertTrue(all(r['_workspace_git_identity'] is None for r in
                           server._MANUAL_AGENT_CANDIDATES.values() if r['workspace_ref'] is None))

    async def test_default_identity_failure_keeps_roster_without_private_error(self):
        self.agents = [self.agent(self.root, 1), self.agent(self.linked, 2)]
        with patch.object(server, 'ROOT', self.root), patch.object(server, 'HERDR', self.backend), patch.object(
                agent_placement.fixed_git, 'execute', AsyncMock(return_value={
                    'outcome': 'exited', 'exit_code': 128, 'stderr': 'private-error'})) as execute:
            result = await server.bridge_overview()
        self.assertEqual(len(result['agents']), 2)
        self.assertEqual([a['checkout'] for a in result['agents']], [agent_placement.unavailable()]*2)
        self.assertEqual(execute.await_count, 1)
        self.assertNotIn('private-error', json.dumps(result))

    async def test_default_prerequisite_uses_shared_budget_and_no_empty_roster_probe(self):
        project = WorkspaceContext(None, self.root, None, str(self.root))
        source = {'identity': {'cwd': str(self.root)}}
        native = agent_placement.fixed_git.execute
        async def delayed(*args):
            observed = await native(*args)
            await asyncio.sleep(.05)
            return observed
        with patch.object(agent_placement.fixed_git, 'execute', side_effect=delayed) as execute, \
                patch.object(agent_placement, 'TOTAL_SECONDS', .03):
            self.assertEqual(await agent_placement.observe_all(project, [source]),
                             [agent_placement.unavailable('deferred')])
            self.assertEqual(execute.await_count, 1)
            self.assertLessEqual(execute.call_args.args[2], .03)
        with patch.object(agent_placement.fixed_git, 'execute', AsyncMock()) as execute, \
                patch.object(agent_placement, 'TOTAL_SECONDS', 0):
            self.assertEqual(await agent_placement.observe_all(project, []), [])
            self.assertEqual(await agent_placement.observe_all(project, [source]),
                             [agent_placement.unavailable('deferred')])
            execute.assert_not_awaited()

    async def test_default_linked_root_and_persistent_replacement(self):
        project = WorkspaceContext(None, self.linked, None, str(self.linked))
        source = {'identity': {'cwd': str(self.linked)}}
        result = await agent_placement.observe_all(project, [source])
        self.assertEqual(result[0]['status'], 'observed')
        self.assertEqual(result[0]['root'], str(self.linked))
        native = agent_placement.fixed_git.execute
        async def swapped(*args):
            result = await native(*args)
            self.linked.rename(self.linked.with_name('moved'))
            self.linked.symlink_to(self.foreign, target_is_directory=True)
            return result
        with patch.object(agent_placement.fixed_git, 'execute', side_effect=swapped) as execute:
            result = await agent_placement.observe_all(project, [source])
        self.assertEqual(result, [agent_placement.unavailable()])
        self.assertEqual(execute.await_count, 1)
        self.assertNotIn(str(self.foreign), json.dumps(result))

    async def test_default_prerequisite_cancellation_propagates(self):
        started = asyncio.Event()
        closed = asyncio.Event()
        async def blocked(*args):
            started.set()
            try:
                await asyncio.sleep(10)
            finally:
                closed.set()
        project = WorkspaceContext(None, self.root, None, str(self.root))
        with patch.object(agent_placement.fixed_git, 'execute', side_effect=blocked):
            task = asyncio.create_task(agent_placement.observe_all(project, [{'identity': {'cwd': str(self.root)}}]))
            await started.wait()
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
        self.assertTrue(closed.is_set())
