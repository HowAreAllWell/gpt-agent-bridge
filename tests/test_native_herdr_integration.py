"""Faithful serialized Herdr envelopes through _exec_raw; no live host calls.

Shapes: herdr-source src/api/schema/{agents.rs:184,panes.rs:441,response.rs}.
Agent detection may select children (src/detect/mod.rs:210); leader is a job anchor.
"""
import asyncio
import copy
import json
import os
import shutil
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
os.environ.setdefault('BRIDGE_PATH_TOKEN', 'test-token-abcdefghijklmnopqrstuvwxyz-012345')
from gpt_agent_bridge import herdr_backend
from gpt_agent_bridge import server
from tests.work_observation import delegate_item
from tests.work_observation import finished_work
from tests.test_work_surface import git_repo_with_two_linked_worktrees
from gpt_agent_bridge.workspace_context import WorkspaceRegistry, WorkspaceRegistryStore


class NativeHerdrIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root, self.one, self.two = git_repo_with_two_linked_worktrees(Path(self.temp.name))
        (self.one / 'evidence.txt').write_text('original checkout')
        (self.two / 'evidence.txt').write_text('different checkout')
        self.agent = {'terminal_id':'term-one', 'agent':'pi', 'agent_status':'idle',
            'workspace_id':'w-one', 'tab_id':'w-one:t2', 'pane_id':'w-one:p5',
            'focused':False, 'state_change_seq':1, 'revision':1,
            'cwd':str(self.root), 'foreground_cwd':str(self.one)}
        # Optional name, agent_session and aggregate foreground_cwd really are omitted.
        self.process = {'pane_id':'w-one:p5', 'shell_pid':90,
            'foreground_process_group_id':100, 'foreground_processes':[
                {'pid':100, 'name':'node', 'argv':['node','wrapper.js'], 'cwd':'/PRIVATE-wrapper'},
                {'pid':101, 'name':'pi', 'argv':['pi'], 'cwd':str(self.one)},
                {'pid':102, 'name':'git', 'argv':['git','status'], 'cwd':'/PRIVATE-child'}]}
        self.backend = herdr_backend.HerdrBackend(self.root)
        self.calls = []; self.fast = False; self.wait_entered = asyncio.Event(); self.release = None
        async def raw(*args, **kwargs):
            self.calls.append(args)
            if args[:2] == ('api','snapshot'):
                result = {'type':'snapshot','snapshot':{'agents':[copy.deepcopy(self.agent)]}}
            elif args[:2] == ('pane','process-info'):
                result = {'type':'pane_process_info','process_info':copy.deepcopy(self.process)}
            elif args[:2] == ('agent','read'):
                # Recovery-only detection read; this shape is deliberately NOT
                # the validated settled composer, so any triggered AGY
                # cold-path recovery declines without a reprompt.
                return 'recovery screen shape not proven', ''
            elif args[:2] == ('agent','prompt'):
                self.agent.update(agent_status='done' if self.fast else 'working', state_change_seq=2)
                result = {'type':'agent_prompted','agent':copy.deepcopy(self.agent)}
            elif args[:2] == ('agent','wait'):
                self.wait_entered.set()
                if self.release is not None: await self.release.wait()
                self.agent.update(agent_status='done', state_change_seq=3)
                result = {'type':'agent_wait','agent':copy.deepcopy(self.agent)}
            elif args[:2] == ('pane','read'):
                return 'bounded terminal report', ''
            else:
                raise AssertionError(('Unexpected host call', args))
            return json.dumps({'result':result}), ''
        self.addCleanup(patch.stopall)
        patch.object(self.backend, '_exec_raw', raw).start()
        # Settlement confirmation must not add real sleeps or client-visible
        # extra prompts; injected zero-second confirmation keeps watcher
        # semantics identical for the generic AND the AGY schedule.
        patch.object(herdr_backend, 'SETTLEMENT_CONFIRM_SECONDS', 0.0).start()
        patch.object(herdr_backend, 'SETTLEMENT_CONFIRM_ATTEMPTS', 1).start()
        patch.object(herdr_backend, 'AGY_SETTLEMENT_CONFIRM_SECONDS', 0.0).start()
        patch.object(herdr_backend, 'AGY_SETTLEMENT_CONFIRM_ATTEMPTS', 1).start()
        registry = WorkspaceRegistry(self.root, json.dumps({'p':str(self.root)}),
            store=WorkspaceRegistryStore(Path(self.temp.name)/'registry.json'))
        patch.object(server, '_WORKSPACE_REGISTRY', registry).start()
        patch.object(server, '_WORKSPACE_BACKENDS', {str(self.root):self.backend}).start()
        for field in ('_WORK_REGISTRY','_RESULT_INBOX','_HANDOFF_REGISTRY','_MANUAL_AGENT_CANDIDATES',
                      '_WORK_WATCHES','_WORK_WATCH_WAITERS'):
            patch.object(server, field, {}).start()

    async def asyncTearDown(self):
        tasks=[entry['watcher_task'] for entry in server._HANDOFF_REGISTRY.values() if entry.get('watcher_task')]
        for task in tasks:
            if not task.done(): task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    async def discover(self):
        result = await server._discover_project_candidates('p')
        self.assertEqual(result['candidate_count'], 1)
        ref = result['candidates'][0]['candidate_id']
        candidate = server._MANUAL_AGENT_CANDIDATES[ref]['candidate']
        self.assertNotIn('PRIVATE', json.dumps(result))
        self.assertEqual(candidate['identity']['cwd'], str(self.one))
        return ref, candidate

    async def settle(self, work_ref):
        work=server._WORK_REGISTRY[work_ref]
        await server._HANDOFF_REGISTRY[work['handoff_id']]['watcher_task']
        return await finished_work('p',work_ref)

    async def test_serialized_wrapper_discovery_prompt_ack_watch_read_and_work_evidence(self):
        for kind in ('pi','codex','agy','other'):
            for fast in (False,True):
                with self.subTest(kind=kind,fast=fast):
                    self.fast=fast; self.calls.clear()
                    self.agent.update(agent=kind,agent_status='idle',state_change_seq=1)
                    ref,candidate=await self.discover()
                    public=candidate['process']['public']
                    self.assertEqual(public['foreground_cwd_relation'],'absent')
                    self.assertEqual(public['processes'][0]['cwd_relation'],'differs_execution')
                    self.assertIsNone(public['processes'][0]['cwd'])
                    response=await delegate_item('p', assignments=[{'agent_ref': ref, 'task': 'one mocked task'}])
                    self.assertEqual(set(response),{'ok', 'work_ref', 'index', 'agent_ref', 'outcome'})
                    terminal=await self.settle(response['work_ref'])
                    self.assertEqual(terminal['state'],'agent_turn_settled')
                    self.assertEqual(terminal['submission_evidence']['state'],'native_acknowledged')
                    self.assertEqual(sum(c[:2]==('agent','prompt') for c in self.calls),1)
                    self.assertEqual(await finished_work('p',response['work_ref']),terminal)
                    await asyncio.gather(*list(server._CLASSIFICATION_TASKS))
                    report=await server.agent_terminal_read('p',ref)
                    self.assertTrue(report['ok'])
                    read=await server.read('p','evidence.txt',work_ref=response['work_ref'])
                    self.assertEqual(read['content'],'original checkout')
                    self.assertEqual(read['execution_target'],str(self.one))
                    self.assertNotIn('PRIVATE',json.dumps(report))
                    self.assertEqual(candidate['process']['fingerprint'],{
                        'process_group_id':100,'leader':{'pid':100,'argv':['node','wrapper.js']}})

    async def test_settlement_confirmation_rejects_transient_fallback_idle(self):
        """Generic fallback-idle shape: working -> idle candidate -> working -> idle settles."""
        barriers = iter([
            {'agent_status': 'done', 'state_change_seq': 4},
            {'agent_status': 'idle', 'state_change_seq': 6},
        ])
        snapshots = iter([
            {'agent_status': 'working', 'state_change_seq': 5},
        ])
        seen_done_revalidate = False
        async def raw(*args, **kwargs):
            nonlocal seen_done_revalidate
            self.calls.append(args)
            if args[:2] == ('api', 'snapshot'):
                if self.agent.get('state_change_seq') == 4:
                    if not seen_done_revalidate:
                        seen_done_revalidate = True
                    else:
                        mutation = next(snapshots, None)
                        if mutation is not None:
                            self.agent.update(mutation)
                result = {'type': 'snapshot', 'snapshot': {'agents': [copy.deepcopy(self.agent)]}}
            elif args[:2] == ('pane', 'process-info'):
                result = {'type': 'pane_process_info', 'process_info': copy.deepcopy(self.process)}
            elif args[:2] == ('agent', 'prompt'):
                self.agent.update(agent_status='working', state_change_seq=3)
                result = {'type': 'agent_prompted', 'agent': copy.deepcopy(self.agent)}
            elif args[:2] == ('agent', 'wait'):
                self.wait_entered.set()
                if self.release is not None:
                    await self.release.wait()
                self.agent.update(next(barriers))
                result = {'type': 'agent_wait', 'agent': copy.deepcopy(self.agent)}
            else:
                raise AssertionError(('Unexpected host call', args))
            return json.dumps({'result': result}), ''
        patch.object(self.backend, '_exec_raw', raw).start()
        patch.object(herdr_backend, 'SETTLEMENT_CONFIRM_SECONDS', 0.0).start()
        patch.object(herdr_backend, 'SETTLEMENT_CONFIRM_ATTEMPTS', 1).start()
        ref, candidate = await self.discover()
        self.assertEqual(candidate['identity']['cwd'], str(self.one))
        response = await delegate_item('p', assignments=[{'agent_ref': ref, 'task': 'one mocked task'}])
        self.assertTrue(response['ok'], response)
        terminal = await self.settle(response['work_ref'])
        self.assertEqual(terminal['state'], 'agent_turn_settled')
        self.assertEqual(terminal['post_state_change_seq'], 6)
        # The reverted fallback candidate re-armed the native settled barrier
        # exactly once; the first idle/done transition never froze a receipt.
        self.assertEqual(sum(c[:2] == ('agent', 'wait') for c in self.calls), 2)
        self.assertEqual(sum(c[:2] == ('agent', 'prompt') for c in self.calls), 1)

    async def test_settlement_confirmation_stable_fallback_idle_still_settles(self):
        async def raw(*args, **kwargs):
            self.calls.append(args)
            if args[:2] == ('api', 'snapshot'):
                result = {'type': 'snapshot', 'snapshot': {'agents': [copy.deepcopy(self.agent)]}}
            elif args[:2] == ('pane', 'process-info'):
                result = {'type': 'pane_process_info', 'process_info': copy.deepcopy(self.process)}
            elif args[:2] == ('agent', 'prompt'):
                self.agent.update(agent_status='working', state_change_seq=3)
                result = {'type': 'agent_prompted', 'agent': copy.deepcopy(self.agent)}
            elif args[:2] == ('agent', 'wait'):
                self.wait_entered.set()
                if self.release is not None:
                    await self.release.wait()
                self.agent.update(agent_status='idle', state_change_seq=4)
                result = {'type': 'agent_wait', 'agent': copy.deepcopy(self.agent)}
            else:
                raise AssertionError(('Unexpected host call', args))
            return json.dumps({'result': result}), ''
        patch.object(self.backend, '_exec_raw', raw).start()
        patch.object(herdr_backend, 'SETTLEMENT_CONFIRM_SECONDS', 0.0).start()
        patch.object(herdr_backend, 'SETTLEMENT_CONFIRM_ATTEMPTS', 2).start()
        ref, candidate = await self.discover()
        response = await delegate_item('p', assignments=[{'agent_ref': ref, 'task': 'one mocked task'}])
        self.assertTrue(response['ok'], response)
        terminal = await self.settle(response['work_ref'])
        # A genuinely fallback-idle agent settles once confirmation attempts
        # are exhausted; visible working evidence is not mandatory.
        self.assertEqual(terminal['state'], 'agent_turn_settled')
        self.assertEqual(terminal['post_state_change_seq'], 4)
        self.assertEqual(sum(c[:2] == ('agent', 'wait') for c in self.calls), 1)

    async def test_agy_provisional_rejection_keeps_await_unsettled_and_work_identity(self):
        """AGY debounce at the highest practical layer: a rejected provisional
        candidate freezes no terminal receipt, never releases/recreates the
        Work and never redelivers the prompt; the public await simply remains
        unsettled on the SAME work_ref (no new public state or field) until the
        re-armed turn confirms."""
        self.agent.update(agent='agy')
        barriers = iter([
            {'agent_status': 'done', 'state_change_seq': 4},
            {'agent_status': 'idle', 'state_change_seq': 6},
        ])
        snapshots = iter([
            {'agent_status': 'working', 'state_change_seq': 5},
        ])
        seen_done_revalidate = False
        async def raw(*args, **kwargs):
            nonlocal seen_done_revalidate
            self.calls.append(args)
            if args[:2] == ('api', 'snapshot'):
                if self.agent.get('state_change_seq') == 4:
                    if not seen_done_revalidate:
                        seen_done_revalidate = True
                    else:
                        mutation = next(snapshots, None)
                        if mutation is not None:
                            self.agent.update(mutation)
                result = {'type': 'snapshot', 'snapshot': {'agents': [copy.deepcopy(self.agent)]}}
            elif args[:2] == ('pane', 'process-info'):
                result = {'type': 'pane_process_info', 'process_info': copy.deepcopy(self.process)}
            elif args[:2] == ('agent', 'prompt'):
                self.agent.update(agent_status='working', state_change_seq=3)
                result = {'type': 'agent_prompted', 'agent': copy.deepcopy(self.agent)}
            elif args[:2] == ('agent', 'wait'):
                self.wait_entered.set()
                if self.release is not None:
                    await self.release.wait()
                self.agent.update(next(barriers))
                result = {'type': 'agent_wait', 'agent': copy.deepcopy(self.agent)}
            else:
                raise AssertionError(('Unexpected host call', args))
            return json.dumps({'result': result}), ''
        patch.object(self.backend, '_exec_raw', raw).start()
        self.release = asyncio.Event()
        ref, candidate = await self.discover()
        self.assertEqual(candidate['identity']['agent_kind'], 'agy')
        response = await delegate_item('p', assignments=[{'agent_ref': ref, 'task': 'one mocked task'}])
        self.assertTrue(response['ok'], response)
        work_ref = response['work_ref']
        work = server._WORK_REGISTRY[work_ref]
        handoff_id = work['handoff_id']
        await self.wait_entered.wait()
        self.assertEqual(work['state'], server.WORK_STATE_RUNNING)
        self.release.set()
        terminal = await self.settle(work_ref)
        self.assertEqual(terminal['state'], 'agent_turn_settled')
        self.assertEqual(terminal['post_state_change_seq'], 6)
        # Same Work object and handoff across the rejected provisional
        # candidate; exactly one prompt; the settled barrier re-armed once.
        self.assertIs(server._WORK_REGISTRY[work_ref], work)
        self.assertEqual(work['handoff_id'], handoff_id)
        self.assertEqual(sum(c[:2] == ('agent', 'prompt') for c in self.calls), 1)
        self.assertEqual(sum(c[:2] == ('agent', 'wait') for c in self.calls), 2)

    async def test_qoder_stuck_composer_nudge_keeps_work_identity_and_single_prompt(self):
        """Stuck-composer recovery at the highest practical layer: the host
        accepts the prompt but Enter never lands; ONE Enter-only nudge inside
        the watcher activates the SAME physical turn. Public await simply stays
        unsettled on the SAME Work; no release/recreation, no redelivery, no
        task text in the nudge, exactly one native prompt."""
        from types import SimpleNamespace
        self.agent.update(agent='qodercli')
        self.calls.clear()
        nudged = asyncio.Event()
        release = asyncio.Event()
        clock = [0.0]
        async def raw(*args, **kwargs):
            self.calls.append(args)
            if args[:2] == ('api', 'snapshot'):
                result = {'type': 'snapshot', 'snapshot': {'agents': [copy.deepcopy(self.agent)]}}
            elif args[:2] == ('pane', 'process-info'):
                result = {'type': 'pane_process_info', 'process_info': copy.deepcopy(self.process)}
            elif args[:2] == ('agent', 'prompt'):
                # Host accepted the submission, but the composer kept the text
                # and the Enter was lost: status stays idle, seq unadvanced.
                result = {'type': 'agent_prompted', 'agent': copy.deepcopy(self.agent)}
            elif args[:2] == ('agent', 'send-keys'):
                self.assertEqual(args[2:], ('w-one:p5', 'enter'))
                self.agent.update(agent_status='working', state_change_seq=2)
                nudged.set()
                result = {'type': 'ok'}
            elif args[:2] == ('agent', 'wait'):
                if '--timeout' in args:  # startup level wait expires the budget
                    clock[0] += int(args[args.index('--timeout') + 1]) / 1000
                    raise herdr_backend.HerdrError('timed out', code='timeout')
                self.wait_entered.set()
                await release.wait()
                self.agent.update(agent_status='done', state_change_seq=3)
                result = {'type': 'agent_wait', 'agent': copy.deepcopy(self.agent)}
            else:
                raise AssertionError(('Unexpected host call', args))
            return json.dumps({'result': result}), ''
        patch.object(self.backend, '_exec_raw', raw).start()
        with patch.object(herdr_backend, 'time',
                          SimpleNamespace(monotonic=lambda: clock[0], time=lambda: 0)):
            ref, candidate = await self.discover()
            self.assertEqual(candidate['identity']['agent_kind'], 'qodercli')
            response = await delegate_item('p', assignments=[{'agent_ref': ref, 'task': 'one mocked task'}])
            self.assertTrue(response['ok'], response)
            work_ref = response['work_ref']
            work = server._WORK_REGISTRY[work_ref]
            handoff_id = work['handoff_id']
            await asyncio.wait_for(nudged.wait(), 5)
            self.assertEqual(work['state'], server.WORK_STATE_RUNNING)
            release.set()
            terminal = await self.settle(work_ref)
        self.assertEqual(terminal['state'], 'agent_turn_settled')
        self.assertEqual(terminal['post_state_change_seq'], 3)
        self.assertIs(server._WORK_REGISTRY[work_ref], work)
        self.assertEqual(work['handoff_id'], handoff_id)
        prompts = [c for c in self.calls if c[:2] == ('agent', 'prompt')]
        self.assertEqual(len(prompts), 1)
        self.assertEqual(prompts[0][:3], ('agent', 'prompt', 'w-one:p5'))
        self.assertTrue(prompts[0][3].startswith('one mocked task\n\n'))
        self.assertEqual(prompts[0][3].count('[Bridge final-report publication]'), 1)
        self.assertEqual(prompts[0][3].count('[Report authoring]'), 1)
        nudges = [c for c in self.calls if c[:2] == ('agent', 'send-keys')]
        self.assertEqual(nudges, [('agent', 'send-keys', 'w-one:p5', 'enter')])
        for call in nudges:
            self.assertNotIn('one mocked task', call)
        # AGY cold-path recovery is exact-kind scoped: qodercli never takes
        # recovery screen reads and never issues a second prompt.
        self.assertEqual([c[:2] for c in self.calls].count(('agent', 'read')), 0)

    async def test_absent_foreground_full_context_dispatch_and_frozen_read(self):
        self.agent['cwd'] = str(self.one)
        self.agent.pop('foreground_cwd')
        self.fast = True
        context = await server.context('p')
        self.assertEqual(context['agent_count'], 1)
        ref = context['agents'][0]['handle']
        candidate = server._MANUAL_AGENT_CANDIDATES[ref]['candidate']
        self.assertIsNone(candidate['identity']['foreground_cwd'])
        response = await delegate_item('p', assignments=[{'agent_ref': ref, 'task': 'one mocked task'}])
        self.assertTrue(response['ok'], response)
        terminal = await self.settle(response['work_ref'])
        self.assertEqual(terminal['state'], 'agent_turn_settled')
        self.assertEqual(terminal['submission_evidence']['state'], 'native_acknowledged')
        read = await server.read('p', 'evidence.txt', work_ref=response['work_ref'])
        self.assertEqual(read['execution_target'], str(self.one))
        self.assertEqual(read['content'], 'original checkout')
        self.assertEqual(sum(c[:2] == ('agent','prompt') for c in self.calls), 1)

    async def test_optional_foreground_transitions_preserve_inflight_exclusion(self):
        self.agent['cwd'] = str(self.one)
        self.agent.pop('foreground_cwd')
        self.release = asyncio.Event()
        context = await server.context('p')
        ref = context['agents'][0]['handle']
        candidate = server._MANUAL_AGENT_CANDIDATES[ref]['candidate']
        original_key = server._execution_identity(str(self.root), candidate)
        self.assertIsNotNone(original_key)
        response = await delegate_item('p', assignments=[{'agent_ref': ref, 'task': 'one mocked task'}])
        self.assertTrue(response['ok'], response)
        await self.wait_entered.wait()
        for foreground in (str(self.one), None, str(self.one)):
            if foreground is None: self.agent.pop('foreground_cwd', None)
            else: self.agent['foreground_cwd'] = foreground
            context = await server.context('p')
            current_ref = context['agents'][0]['handle']
            current = server._MANUAL_AGENT_CANDIDATES[current_ref]['candidate']
            self.assertEqual(current['identity']['foreground_cwd'], foreground)
            self.assertEqual(server._execution_identity(str(self.root), current), original_key)
            denied = await delegate_item('p', assignments=[{'agent_ref': current_ref, 'task': 'must not prompt'}])
            self.assertEqual(denied['error_type'], 'WorkAlreadyInFlight')
        self.agent['foreground_cwd'] = str(self.two)
        current = await self.backend.revalidate_manual_agent_resource(candidate)
        self.assertNotEqual(server._execution_identity(str(self.root), current), original_key)
        # Even changed execution evidence cannot evade the stable resource gate.
        denied = await delegate_item('p', assignments=[{'agent_ref': ref, 'task': 'must not prompt'}])
        self.assertEqual(denied['error_type'], 'WorkAlreadyInFlight')
        self.release.set()
        terminal = await self.settle(response['work_ref'])
        self.assertEqual(terminal['state'], 'needs_attention')
        self.assertEqual(terminal['reason'], 'execution_checkout_changed')
        read = await server.read('p', 'evidence.txt', work_ref=response['work_ref'])
        self.assertEqual(read['content'], 'original checkout')
        self.assertEqual(sum(c[:2] == ('agent','prompt') for c in self.calls), 1)

    async def test_cwd_observation_churn_is_not_process_replacement(self):
        _,candidate=await self.discover()
        for cwd in (None,str(self.one),'/PRIVATE-new-wrapper'):
            self.process['foreground_cwd']=cwd
            self.process['foreground_processes'][0]['cwd']=cwd
            self.process['foreground_processes'][1]['cwd']='/PRIVATE-moved-child'
            current=await self.backend.revalidate_manual_agent(candidate)
            self.assertEqual(current['process']['fingerprint'],candidate['process']['fingerprint'])
            self.assertNotIn('PRIVATE',json.dumps(current['process']['public']))
        self.process['foreground_processes'][0]['argv']=['replacement']
        with self.assertRaises(herdr_backend.HerdrError) as error:
            await self.backend.revalidate_manual_agent(candidate)
        self.assertEqual(error.exception.code,'manual_candidate_continuity_lost')

    async def test_checkout_change_attention_never_retargets_work(self):
        ref,candidate=await self.discover()
        self.release=asyncio.Event()
        response=await delegate_item('p', assignments=[{'agent_ref': ref, 'task': 'one mocked task'}])
        await self.wait_entered.wait()
        self.agent['foreground_cwd']=str(self.two)
        with self.assertRaises(herdr_backend.HerdrError) as error:
            await self.backend.revalidate_manual_agent(candidate)
        self.assertEqual(error.exception.code,'manual_candidate_checkout_changed')
        self.release.set()
        terminal=await self.settle(response['work_ref'])
        self.assertEqual(terminal['state'],'needs_attention')
        self.assertEqual(terminal['reason'],'execution_checkout_changed')
        # Agent resource reads are explicitly current/unattributed; Work evidence stays frozen.
        current=await self.backend.read_manual_agent(candidate,limit=10)
        self.assertEqual(current['candidate']['identity']['cwd'],str(self.two))
        read=await server.read('p','evidence.txt',work_ref=response['work_ref'])
        self.assertEqual(read['content'],'original checkout')
        self.assertEqual(read['execution_target'],str(self.one))
        self.assertEqual(sum(c[:2]==('agent','prompt') for c in self.calls),1)

    async def test_frozen_git_identity_change_yields_attention(self):
        ref,_=await self.discover(); self.release=asyncio.Event()
        response=await delegate_item('p', assignments=[{'agent_ref': ref, 'task': 'one mocked task'}])
        await self.wait_entered.wait()
        saved=self.one.with_name('saved-original'); self.one.rename(saved)
        self.one.mkdir(); (self.one/'.git').write_bytes((saved/'.git').read_bytes())
        try:
            self.release.set()
            terminal=await self.settle(response['work_ref'])
            self.assertEqual(terminal['state'],'needs_attention')
            self.assertEqual(terminal['reason'],'execution_checkout_changed')
            read=await server.read('p','evidence.txt',work_ref=response['work_ref'])
            self.assertFalse(read['ok'])
        finally:
            shutil.rmtree(self.one); saved.rename(self.one)

    async def test_native_omitted_name_only_matches_expected_unnamed(self):
        _,candidate=await self.discover()
        receipt={'type':'agent_prompted','agent':copy.deepcopy(self.agent)}
        self.assertTrue(self.backend._prompt_ack_matches(receipt,candidate))
        named=copy.deepcopy(candidate);named['identity']['agent_name']='named'
        self.assertFalse(self.backend._prompt_ack_matches(receipt,named))
        for key in ('agent','workspace_id','tab_id','pane_id','terminal_id'):
            bad=copy.deepcopy(receipt);bad['agent'].pop(key)
            self.assertFalse(self.backend._prompt_ack_matches(bad,candidate))
        for bad in (dict(receipt,name='other'),dict(receipt,agent_kind='other')):
            self.assertFalse(self.backend._prompt_ack_matches(bad,candidate))

    async def test_malformed_leaders_and_changed_identity_never_promote_a_child(self):
        _,candidate=await self.discover()
        original=copy.deepcopy(self.process)
        for members in (original['foreground_processes'][1:],
                        original['foreground_processes']+[original['foreground_processes'][0]],
                        [{'pid':True,'argv':['wrapper']}],
                        [{'pid':100,'argv':[]}],
                        original['foreground_processes']*(herdr_backend.MAX_PROBE_AGENTS+1)):
            self.process['foreground_processes']=members
            with self.assertRaises(herdr_backend.HerdrError):
                await self.backend.revalidate_manual_agent_resource(candidate)
        self.process=original
        for field,value in (('agent','different'),('name','named'),('agent_session',{'kind':'id','value':7})):
            self.agent[field]=value
            with self.assertRaises(herdr_backend.HerdrError):
                await self.backend.revalidate_manual_agent(candidate)
            if field=='agent':self.agent[field]='pi'
            else:self.agent.pop(field)
