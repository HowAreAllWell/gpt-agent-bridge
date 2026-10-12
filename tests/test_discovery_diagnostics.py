"""Provider parity and sanitized rejected-candidate explanations, without host I/O."""
import copy
import json
import os
import subprocess
from pathlib import Path
import unittest
from unittest.mock import AsyncMock, patch
os.environ.setdefault('BRIDGE_PATH_TOKEN', 'test-token-abcdefghijklmnopqrstuvwxyz-012345')
from gpt_agent_bridge import server
from tests.work_observation import delegate_item
from gpt_agent_bridge import herdr_backend
from tests import test_discovery_coverage as coverage_tests
from tests.test_work_surface import git_repo_with_two_linked_worktrees


class DiscoveryDiagnosticsTests(unittest.IsolatedAsyncioTestCase):
    setUp = coverage_tests.DiscoveryCoverageTests.setUp
    agent = coverage_tests.DiscoveryCoverageTests.agent

    async def test_all_providers_share_linked_cwd_semantics(self):
        container = Path(self.temp.name) / 'pairs'; container.mkdir()
        root, one, two = git_repo_with_two_linked_worktrees(container)
        for kind in ('pi', 'codex', 'agy', 'other'):
            for reported, foreground in ((root,root),(one,one),(root,one),
                                         (one,root),(one,two),(one,None)):
                with self.subTest(kind=kind, reported=reported, foreground=foreground):
                    agent=self.agent(reported,1);agent.update(agent=kind,
                        foreground_cwd=str(foreground) if foreground else None)
                    identity=herdr_backend.HerdrBackend._manual_agent_identity(agent,root)
                    self.assertEqual(identity['cwd'],str(foreground or reported))
                    # Foreign paired checkouts are exclusions, with no process queries.
                    self.agents=[agent];self.calls.clear()
                    result=await server.context('p')
                    self.assertTrue(result['agents_complete'])
                    self.assertEqual(result['agents_coverage_counts']['out_of_project'],1)
                    self.assertEqual(self.calls,[('api','snapshot')])

    async def views(self):
        context=await server.context('p')
        snapshot=await server.bridge_overview(project_ref='p')
        self.assertEqual(context['agents_rejection_diagnostics'],snapshot['observation']['rejection_diagnostics'])
        return context, context['agents_rejection_diagnostics']

    async def test_local_details_are_bounded_and_foreign_unknown_count_only(self):
        self.agents=[]
        for n in range(12):
            a=self.agent(self.root,n+1);a['agent_session']={'kind':'path','value':{'SECRET':'/private'}}
            self.agents.append(a)
        foreign=self.agent(self.foreign,20);foreign['name']='SECRET /private';self.agents.append(foreign)
        self.agents.append(None)
        context,diag=await self.views()
        self.assertFalse(context['agents_complete'])
        self.assertEqual(diag['reason_counts']['identity_session'],12)
        self.assertEqual(len(diag['details']),8)
        self.assertEqual(diag['omitted_local_count'],4)
        self.assertEqual(diag['unlocalized_count'],2)
        self.assertEqual(sum(diag['reason_counts'].values()),context['agents_skipped_count'])
        text=json.dumps(diag)
        for secret in ('SECRET','/private',str(self.foreign),'term-', 'w-manual', 'handle'):
            self.assertNotIn(secret,text)
        self.assertTrue(all(c==('api','snapshot') for c in self.calls))

    async def test_duplicate_cwd_process_and_snapshot_reasons_are_not_exception_text(self):
        duplicate=self.agent(self.root,3)
        self.agents=[duplicate,copy.deepcopy(duplicate),self.agent(self.root,4)]
        self.agents[-1]['foreground_cwd']=str(self.foreign)
        _,diag=await self.views()
        self.assertEqual(diag['reason_counts']['snapshot_duplicate'],2)
        self.assertEqual(diag['reason_counts']['identity_cwd_git'],1)
        self.assertEqual(diag['unlocalized_count'],3)
        self.agents=[self.agent(self.root,1)]
        original=self.backend._call
        async def call(*args,**kwargs):
            if args[:2]==('pane','process-info'):
                return {'process_info':{'pane_id':'w-manual:p1','foreground_process_group_id':1,
                    'foreground_processes':[{'pid':1,'argv':['SECRET']}],
                    'foreground_cwd':'/private/SECRET'}}
            return await original(*args,**kwargs)
        with patch.object(self.backend,'_call',call):
            context,diag=await self.views()
        self.assertTrue(context['agents_complete'])
        self.assertEqual(sum(diag['reason_counts'].values()), 0)
        self.assertEqual(diag['details'], [])
        self.assertNotIn('SECRET',json.dumps(context))
        with patch.object(self.backend,'_call',AsyncMock(return_value={'snapshot':{'agents':'SECRET'}})):
            context,diag=await self.views()
        self.assertFalse(context['agents_complete'])
        self.assertEqual(diag,{'status':'unavailable'})
        self.assertNotIn('SECRET',json.dumps(context))

    async def test_wrapper_leader_cwd_is_not_a_rejection_in_both_views(self):
        self.agents = [self.agent(self.root, 1)]
        original = self.backend._call
        async def call(*args, **kwargs):
            if args[:2] == ('pane', 'process-info'):
                return {'process_info': {'pane_id': 'w-manual:p1',
                    'foreground_process_group_id': 1, 'foreground_cwd': str(self.root),
                    'foreground_processes': [
                        {'pid': 1, 'argv': ['agent'], 'cwd': '/private/SECRET'},
                        {'pid': 2, 'argv': ['git'], 'cwd': str(self.root)}]}}
            return await original(*args, **kwargs)
        with patch.object(self.backend, '_call', call):
            context, diag = await self.views()
        self.assertTrue(context['agents_complete'])
        self.assertEqual(sum(diag['reason_counts'].values()), 0)
        self.assertEqual(diag['details'], [])
        self.assertNotIn('SECRET', json.dumps(context))

    async def test_diagnostics_contract_failure_does_not_invent_coverage(self):
        payload=await self.backend.manual_agent_candidates()
        for value in (None,{}, {'status':'available','details':['SECRET']}):
            data=copy.deepcopy(payload);data['rejection_diagnostics']=value
            with patch.object(self.backend,'manual_agent_candidates',AsyncMock(return_value=data)):
                context,diag=await self.views()
            self.assertEqual(diag,{'status':'unavailable'})
            self.assertTrue(context['agents_complete']) # roster itself was still proven complete
            self.assertEqual(context['agents_coverage_counts'],payload['coverage_counts'])
        data=copy.deepcopy(payload);data['candidates'].append(None)
        with patch.object(self.backend,'manual_agent_candidates',AsyncMock(return_value=data)):
            context,diag=await self.views()
        self.assertFalse(context['agents_complete'])
        self.assertEqual(diag['reason_counts']['projection_invalid'],1)
        self.assertEqual(diag['unlocalized_count'],1)
        data=copy.deepcopy(payload)
        data['rejection_diagnostics']['details']=[{'stage':'identity','reason':'identity_name',
            'kind':'pi','hint':'SECRET /private'}]
        data['rejection_diagnostics']['reason_counts']['identity_name']=1
        data['skipped_count']=1;data['coverage_counts']['invalid_or_unavailable']=1
        with patch.object(self.backend,'manual_agent_candidates',AsyncMock(return_value=data)):
            context,diag=await self.views()
        self.assertEqual(diag,{'status':'unavailable'})
        self.assertFalse(context['agents_complete'])
        self.assertNotIn('SECRET',json.dumps(context))

    async def test_truncation_and_unavailable_process_do_not_gain_false_certainty(self):
        self.agents=[self.agent(self.foreign,n) for n in range(35)]
        context,diag=await self.views()
        self.assertFalse(context['agents_complete'])
        self.assertEqual(diag['truncated_candidates'],3)
        self.assertEqual(diag['details'],[])
        self.agents=[self.agent(self.root,1)]
        original=self.backend._call
        async def call(*args,**kwargs):
            if args[:2]==('pane','process-info'): raise herdr_backend.HerdrError('SECRET')
            return await original(*args,**kwargs)
        with patch.object(self.backend,'_call',call):
            result=await self.backend.manual_agent_candidates()
        # Existing pane-only discovery is retained, not turned into rejection.
        self.assertEqual(result['candidate_count'],1)
        self.assertFalse(result['candidates'][0]['process']['available'])
        self.assertEqual(result['rejection_diagnostics']['reason_counts']['candidate_unavailable'],0)

    async def test_pi_work_freezes_linked_checkout_and_rejects_replacement(self):
        self.agents=[self.agent(self.root,1)]
        self.agents[0].update(agent='pi',foreground_cwd=str(self.linked),
                              agent_session={'kind':'id','value':'session-value'})
        listed=await server.context('p');ref=listed['agents'][0]['handle']
        record=server._MANUAL_AGENT_CANDIDATES[ref]
        self.assertEqual(record['candidate']['identity']['cwd'],str(self.linked))
        with patch.object(server,'_WORK_REGISTRY',{}),patch.object(server,'_RESULT_INBOX',{}), \
             patch.object(server,'_WORK_WATCHES',{}),patch.object(server,'_WORK_WATCH_WAITERS',{}), \
             patch.object(server,'_HANDOFF_REGISTRY',{}), \
             patch.object(self.backend,'prompt_manual_agent',AsyncMock(return_value={})), \
             patch.object(self.backend,'watch_manual_agent_turn',AsyncMock(return_value={'state':'done'})):
            work=await delegate_item('p', assignments=[{'agent_ref': ref, 'task': 'mocked task'}])
            entry=server._WORK_REGISTRY[work['work_ref']]
            await server._HANDOFF_REGISTRY[entry['handoff_id']]['watcher_task']
            self.assertEqual(entry['evidence_checkout'].root,self.linked)
            (self.linked/'only.txt').write_text('linked only')
            result=await server.read('p','only.txt',work_ref=work['work_ref'])
            self.assertEqual(result['execution_target'],str(self.linked))
            self.linked.rename(self.linked.with_name('moved'));self.linked.mkdir()
            result=await server.read('p','only.txt',work_ref=work['work_ref'])
            self.assertFalse(result['ok'])
            self.assertNotIn('content',result)

    async def test_all_providers_retain_invalid_identity_rejections(self):
        bare=Path(self.temp.name)/'bare.git'
        subprocess.run(['git','init','--bare','--quiet',str(bare)],check=True)
        for kind in ('pi','codex','agy','other'):
            for updates in ({'foreground_cwd':str(self.foreign)},
                            {'cwd':str(self.foreign),'foreground_cwd':str(self.root)},
                            {'foreground_cwd':str(bare)}, {'foreground_cwd':False},
                            {'agent_session':{'kind':'invalid','value':'SECRET'}},
                            {'terminal_id':'invalid locus'}, {'name':'invalid name'}):
                with self.subTest(kind=kind,updates=updates):
                    agent=self.agent(self.root,1);agent.update(agent=kind,**updates)
                    with self.assertRaises(herdr_backend.HerdrError):
                        self.backend._manual_agent_identity(agent,self.root)
        (self.linked/'.git').write_text('gitdir: /nonexistent/git-dir\n')
        for kind in ('pi','codex','other'):
            agent=self.agent(self.root,1);agent.update(agent=kind,foreground_cwd=str(self.linked))
            with self.assertRaises(herdr_backend.HerdrError):
                self.backend._manual_agent_identity(agent,self.root)
