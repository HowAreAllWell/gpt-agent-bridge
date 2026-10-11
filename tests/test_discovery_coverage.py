"""Project filtering is not failed observation; unknown candidates remain partial."""
import copy
import dataclasses
import json
import os
import subprocess
from pathlib import Path
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

os.environ.setdefault('BRIDGE_PATH_TOKEN', 'test-token-abcdefghijklmnopqrstuvwxyz-012345')
import herdr_backend
import server
from tests.test_manual_agents import agy_agent, process_info, git_worktree
from tests.test_work_surface import git_repo_with_linked_worktree, git_repo_with_two_linked_worktrees
from workspace_context import WorkspaceRegistry, WorkspaceRegistryStore, WorkspaceAuthorizationError


class DiscoveryCoverageTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root, self.linked = git_repo_with_linked_worktree(Path(self.temp.name))
        self.foreign = git_worktree(Path(self.temp.name) / 'private-foreign-project')
        self.backend = herdr_backend.HerdrBackend(self.root)
        self.agents = [self.agent(self.root, 1), self.agent(self.foreign, 2)]
        self.calls = []

        async def call(*args, **kwargs):
            self.calls.append(args)
            if args == ('api', 'snapshot'):
                return {'snapshot': {'agents': copy.deepcopy(self.agents), 'tabs': []}}
            if args[:2] == ('pane', 'process-info'):
                agent = next(a for a in self.agents if isinstance(a, dict) and a.get('pane_id') == args[3])
                return {'process_info': process_info(agent)}
            raise AssertionError(args)
        self.backend._call = call
        registry = WorkspaceRegistry(self.root, json.dumps({'p': str(self.root)}),
            store=WorkspaceRegistryStore(Path(self.temp.name) / 'registry.json'))
        self.addCleanup(patch.stopall)
        patch.object(server, '_WORKSPACE_REGISTRY', registry).start()
        patch.object(server, '_WORKSPACE_BACKENDS', {str(self.root): self.backend}).start()
        patch.object(server, '_MANUAL_AGENT_CANDIDATES', {}).start()
        patch.object(server, '_deployment_snapshot', return_value={}).start()

    def agent(self, root, n):
        agent = agy_agent(root, pid=1000+n)
        agent.update(pane_id=f'w-manual:p{n}', terminal_id=f'term-{n}', name=f'agent-{n}')
        return agent

    async def test_foreign_exclusion_is_complete_and_both_public_views_agree(self):
        context = await server.context('p')
        snapshot = await server.bridge_overview(project_ref='p')
        self.assertTrue(context['agents_complete'])
        self.assertEqual(context['agent_count'], 1)
        self.assertEqual(context['agents_skipped_count'], 0)
        expected = {'out_of_project': 1, 'invalid_or_unavailable': 0, 'truncated': 0}
        self.assertEqual(context['agents_coverage_counts'], expected)
        self.assertEqual(snapshot['observation']['coverage_counts'], expected)
        self.assertEqual(snapshot['observation']['health'], 'healthy')
        self.assertEqual(snapshot['agents'], context['agents'])
        public = json.dumps([context, snapshot])
        for secret in (str(self.foreign), 'agent-2', 'term-2', 'w-manual:p2'):
            self.assertNotIn(secret, public)
        self.assertNotIn(('pane', 'process-info', '--pane', 'w-manual:p2'), self.calls)

    async def test_foreign_paired_linked_cwds_are_excluded_in_both_views(self):
        container = Path(self.temp.name) / 'foreign-linked'
        container.mkdir()
        foreign, first, second = git_repo_with_two_linked_worktrees(container)
        for reported, foreground in ((foreign, first), (first, foreign), (first, second)):
            with self.subTest(reported=reported, foreground=foreground):
                self.calls.clear()
                self.agents = [self.agent(self.root, 1), self.agent(reported, 2)]
                self.agents[1]['foreground_cwd'] = str(foreground)
                await self.test_foreign_exclusion_is_complete_and_both_public_views_agree()
                public = json.dumps([await server.context('p'),
                    await server.bridge_overview(project_ref='p')])
                for secret in (str(foreign), str(first), str(second)):
                    self.assertNotIn(secret, public)
                self.assertTrue(all(call == ('api', 'snapshot') or
                    call == ('pane', 'process-info', '--pane', 'w-manual:p1')
                    for call in self.calls))

    async def test_foreign_foreground_safeguards_and_pi_boundary(self):
        container = Path(self.temp.name) / 'foreign-linked'
        container.mkdir()
        foreign, linked = git_repo_with_linked_worktree(container)
        bare = Path(self.temp.name) / 'bare.git'
        subprocess.run(['git', 'init', '--bare', '--quiet', str(bare)], check=True)
        for kind, foreground, excluded in (
            ('agy', self.root, False), ('agy', self.foreign, False),
            ('agy', bare, False), ('agy', '', False), ('agy', 123, False),
            ('pi', linked, True),
            ('pi', foreign, True),
            ('pi', None, True),
        ):
            with self.subTest(kind=kind, foreground=foreground):
                self.calls.clear()
                self.agents = [self.agent(foreign, 2)]
                self.agents[0].update(agent=kind, foreground_cwd=(
                    str(foreground) if isinstance(foreground, Path) else foreground))
                context = await server.context('p')
                snapshot = await server.bridge_overview(project_ref='p')
                expected = {'out_of_project': int(excluded),
                            'invalid_or_unavailable': int(not excluded), 'truncated': 0}
                self.assertEqual(context['agents_coverage_counts'], expected)
                self.assertEqual(snapshot['observation']['coverage_counts'], expected)
                self.assertEqual(context['agents_complete'], excluded)
                self.assertEqual(snapshot['observation']['complete'], excluded)
                self.assertTrue(all(call == ('api', 'snapshot') for call in self.calls))
        (linked / '.git').write_text('gitdir: /nonexistent/git-dir\n')
        self.agents = [self.agent(foreign, 2)]
        self.agents[0]['foreground_cwd'] = str(linked)
        context = await server.context('p')
        snapshot = await server.bridge_overview(project_ref='p')
        self.assertFalse(context['agents_complete'])
        self.assertEqual(context['agents_coverage_counts']['invalid_or_unavailable'], 1)
        self.assertEqual(snapshot['observation']['coverage_counts'], context['agents_coverage_counts'])
        self.assertTrue(all(call == ('api', 'snapshot') for call in self.calls))

    async def test_linked_same_common_git_is_included(self):
        self.agents.append(self.agent(self.linked, 3))
        result = await server.context('p')
        self.assertTrue(result['agents_complete'])
        self.assertEqual(result['agent_count'], 2)
        self.assertEqual(result['agents_coverage_counts']['out_of_project'], 1)

    async def test_malformed_missing_and_unreadable_candidates_are_not_exclusions(self):
        bad = [None, self.agent(self.root / 'missing', 3), self.agent(self.root, 4)]
        bad[-1]['agent'] = None
        self.agents = [self.agent(self.root, 1), *bad]
        result = await server.context('p')
        self.assertFalse(result['agents_complete'])
        self.assertEqual(result['agents_coverage_counts'],
                         {'out_of_project': 0, 'invalid_or_unavailable': 3, 'truncated': 0})
        self.agents = [self.agent(self.foreign, 2)]
        original = herdr_backend.canonical_git_worktree
        def unreadable(path):
            if str(path) == str(self.foreign):
                raise WorkspaceAuthorizationError('unreadable')
            return original(path)
        with patch.object(herdr_backend, 'canonical_git_worktree', side_effect=unreadable):
            result = await server.context('p')
        self.assertFalse(result['agents_complete'])
        self.assertEqual(result['agents_coverage_counts']['out_of_project'], 0)

    async def test_corrupt_same_project_linked_checkout_is_unknown(self):
        (self.linked / '.git').write_text('gitdir: /nonexistent/git-dir\n')
        self.agents = [self.agent(self.linked, 3)]
        result = await server.context('p')
        self.assertFalse(result['agents_complete'])
        self.assertEqual(result['agents_skipped_count'], 1)
        self.assertEqual(result['agents_coverage_counts']['out_of_project'], 0)

    async def test_contradictory_or_unidentifiable_foreign_entries_stay_partial(self):
        for field, value in [('foreground_cwd', str(self.root)), ('terminal_id', None),
                             ('agent', None), ('name', 'invalid name')]:
            self.agents = [self.agent(self.foreign, 2)]
            self.agents[0][field] = value
            result = await server.context('p')
            self.assertFalse(result['agents_complete'], field)
            self.assertEqual(result['agents_coverage_counts']['out_of_project'], 0, field)
        self.agents = [self.agent(self.root, 1)]
        self.agents[0]['foreground_cwd'] = str(self.foreign)
        result = await server.context('p')
        self.assertFalse(result['agents_complete'])
        self.assertEqual(result['agents_coverage_counts']['out_of_project'], 0)

    async def test_duplicate_locus_is_ambiguous_even_if_foreign(self):
        for root in (self.root, self.foreign):
            self.agents = [self.agent(root, 1), self.agent(root, 1)]
            result = await server.context('p')
            self.assertFalse(result['agents_complete'])
            self.assertEqual(result['agents_coverage_counts']['invalid_or_unavailable'], 2)
            self.assertEqual(result['agents_coverage_counts']['out_of_project'], 0)

    async def test_truncation_stays_partial_with_fixed_reason_keys(self):
        self.agents = [self.agent(self.foreign, n) for n in range(35)]
        result = await server.context('p')
        self.assertFalse(result['agents_complete'])
        self.assertEqual(result['agents_coverage_counts'],
                         {'out_of_project': 32, 'invalid_or_unavailable': 0, 'truncated': 3})
        self.assertEqual(len(self.calls), 1)  # no process lookup for excluded/unexamined entries

    async def test_registry_and_backend_failures_never_fall_back(self):
        self.assertFalse((await server.context('missing'))['ok'])
        self.assertFalse((await server.bridge_overview(project_ref='missing'))['ok'])
        self.assertEqual(self.calls, [])
        with patch.object(self.backend, '_call', AsyncMock(side_effect=herdr_backend.HerdrError('unavailable'))):
            result = await server.context('p')
            snapshot = await server.bridge_overview(project_ref='p')
        self.assertFalse(result['agents_complete'])
        self.assertIn('agents_error', result)
        self.assertEqual(snapshot['observation']['health'], 'unavailable')
        self.assertNotIn('agents_coverage_counts', result)

    async def test_malformed_coverage_is_not_healthy(self):
        for counts in ({'private-path': 1}, {'out_of_project': -1, 'invalid_or_unavailable': 0, 'truncated': 0}):
            with patch.object(self.backend, 'manual_agent_candidates', AsyncMock(return_value={
                    'candidates': [], 'skipped_count': 0, 'coverage_counts': counts})):
                result = await server.context('p')
            self.assertIn('agents_error', result)
            self.assertFalse(result['agents_complete'])

    async def test_missing_coverage_never_synthesizes_complete_roster(self):
        current = {'ok': True, 'candidates': [], 'skipped_count': 0,
                   'candidates_truncated': False}
        malformed = [None, {}, {'out_of_project': False, 'invalid_or_unavailable': 0, 'truncated': 0},
                     {'out_of_project': 0, 'invalid_or_unavailable': 1, 'truncated': 0},
                     {'out_of_project': 0, 'invalid_or_unavailable': 0, 'truncated': 1}]
        # Exercise both the retained backend boundary and compact projection boundary.
        for target, method in ((self.backend, 'manual_agent_candidates'),
                               (server, '_discover_project_candidates')):
            for payload in [current, *[dict(current, coverage_counts=c) for c in malformed]]:
                with self.subTest(method=method, payload=payload), patch.object(
                        target, method, AsyncMock(return_value=payload)):
                    context = await server.context('p')
                    snapshot = await server.bridge_overview(project_ref='p')
                self.assertFalse(context['agents_complete'])
                self.assertIn('agents_error', context)
                self.assertNotIn('agents_coverage_counts', context)
                self.assertEqual(snapshot['observation']['health'], 'unavailable')
                self.assertFalse(snapshot['observation']['complete'])
                self.assertNotIn('coverage_counts', snapshot['observation'])

    async def test_partial_git_identity_disagreement_does_not_prove_foreign_project(self):
        original = herdr_backend.canonical_git_worktree
        _, selected = original(self.root)
        foreign_root, foreign = original(self.foreign)
        for replacement in (
            dataclasses.replace(foreign, git_common_dir=selected.git_common_dir),
            dataclasses.replace(foreign, git_common_device=selected.git_common_device,
                                git_common_inode=selected.git_common_inode),
        ):
            def identity(path):
                return (foreign_root, replacement) if str(path) == str(self.foreign) else original(path)
            self.agents = [self.agent(self.foreign, 2)]
            with patch.object(herdr_backend, 'canonical_git_worktree', side_effect=identity):
                result = await server.context('p')
            self.assertFalse(result['agents_complete'])
            self.assertEqual(result['agents_coverage_counts']['out_of_project'], 0)

    async def test_replaced_registered_root_fails_before_discovery(self):
        self.root.rename(self.root.with_name('old-root'))
        self.root.mkdir()
        result = await server.context('p')
        snapshot = await server.bridge_overview(project_ref='p')
        self.assertFalse(result['ok'])
        self.assertFalse(snapshot['ok'])
        self.assertEqual(self.calls, [])
