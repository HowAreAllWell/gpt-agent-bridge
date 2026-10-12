"""Submission receipts are independent of turn settlement and safe retry."""
import asyncio
import copy
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

os.environ.setdefault('BRIDGE_PATH_TOKEN', 'test-token-abcdefghijklmnopqrstuvwxyz-012345')
from gpt_agent_bridge import server
from tests.work_observation import finished_work
from gpt_agent_bridge import herdr_backend
from gpt_agent_bridge import work_reports
from tests.test_manual_agents import manual_backend
from tests.test_work_surface import git_worktree
from gpt_agent_bridge.workspace_context import WorkspaceRegistry, WorkspaceRegistryStore
from tests.work_observation import delegate_item


class SubmissionEvidenceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = git_worktree(Path(self.temp.name) / 'root')
        self.backend, self.state = manual_backend(self.root)
        registry = WorkspaceRegistry(self.root, json.dumps({'p':str(self.root)}),
            store=WorkspaceRegistryStore(Path(self.temp.name) / 'registry.json'))
        self.addCleanup(patch.stopall)
        patch.object(server, '_WORKSPACE_REGISTRY', registry).start()
        patch.object(server, '_WORKSPACE_BACKENDS', {str(self.root):self.backend}).start()
        self.report_store = work_reports.ReportStore()
        self.addCleanup(self.report_store.close)
        patch.object(server, '_REPORT_STORE', self.report_store).start()
        patch.object(server, '_CLASSIFICATION_TASKS', set()).start()
        patch.object(server, '_CLASSIFICATION_INFLIGHT', set()).start()
        patch.object(server, '_WORK_WATCH_WAITERS', {}).start()
        patch.object(server, '_WORK_WATCHES', {}).start()
        patch.object(server, '_REPORT_EVIDENCE_EXTRA_ATTEMPTS', 0).start()
        patch.object(server, '_WORK_REGISTRY', {}).start()
        patch.object(server, '_RESULT_INBOX', {}).start()
        patch.object(server, '_HANDOFF_REGISTRY', {}).start()
        patch.object(server, '_MANUAL_AGENT_CANDIDATES', {}).start()
        listed = await server._discover_project_candidates('p')
        self.ref = listed['candidates'][0]['candidate_id']
        self.candidate = server._MANUAL_AGENT_CANDIDATES[self.ref]['candidate']

    async def asyncTearDown(self):
        tasks = [h['watcher_task'] for h in server._HANDOFF_REGISTRY.values() if h.get('watcher_task')]
        for t in tasks:
            if not t.done(): t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        classifications = list(server._CLASSIFICATION_TASKS)
        for task in classifications:
            task.cancel()
        await asyncio.gather(*classifications, return_exceptions=True)

    def ack(self):
        return {'type':'agent_prompted', 'agent':copy.deepcopy(self.state['agent'])}

    async def test_native_matching_requires_full_stable_resource(self):
        good = self.ack()
        variants = [None, {}, {'agent':good['agent']}, {'type':'agent_prompted'},
            {'type':'agent_prompted','agent':{'agent':'agy','pane_id':good['agent']['pane_id']}},
            dict(good, type='other'), dict(good, pane_id='other'), dict(good, agent_kind='pi')]
        for key in ('agent','name','workspace_id','tab_id','pane_id','terminal_id'):
            bad = copy.deepcopy(good); bad['agent'].pop(key)
            if key != 'name': variants.append(bad)
            bad = copy.deepcopy(good); bad['agent'][key]='wrong'; variants.append(bad)
        for response in variants:
            with self.subTest(response=response), patch.object(self.backend, '_call', AsyncMock(return_value=response)) as call:
                evidence = {}
                await self.backend.prompt_manual_agent(self.candidate, 'private task', evidence)
                self.assertEqual(evidence['state'], 'delivery_unknown')
                self.assertTrue(evidence['mutation_possible'])
                call.assert_awaited_once()
        good['agent']['agent_session'] = {'kind':'id','value':'new-session'}
        with patch.object(self.backend, '_call', AsyncMock(return_value=good)):
            evidence = {}
            await self.backend.prompt_manual_agent(self.candidate, 'private task', evidence)
        self.assertEqual(evidence['state'], 'native_acknowledged')
        self.assertNotIn('private', json.dumps(evidence))
        self.assertNotIn(str(self.root), json.dumps(evidence))

    async def test_receipt_and_terminal_signals_remain_independent(self):
        for acknowledged in (True, False):
            for terminal in ('done','needs_attention','failed','blocked'):
                with self.subTest(acknowledged=acknowledged, terminal=terminal):
                    server._WORK_REGISTRY.clear(); server._RESULT_INBOX.clear(); server._HANDOFF_REGISTRY.clear()
                    self.state['calls'].clear()
                    self.state['prompt_handler'] = lambda *a: self.ack() if acknowledged else {}
                    # Use the real dispatch path, with only the terminal observation mocked.
                    observed = {'state':'needs_attention' if terminal=='blocked' else terminal, 'reason':'activation_observation_budget_exhausted'
                        if terminal=='needs_attention' else ('agent_blocked' if terminal=='blocked' else 'state_transition_proven'),
                        'post_state_change_seq':2, 'post_revision':2, 'post_candidate':self.candidate}
                    with patch.object(self.backend, 'watch_manual_agent_turn', AsyncMock(return_value=observed)):
                        result = await delegate_item('p', assignments=[{'agent_ref': self.ref, 'task': 'private task'}])
                        if acknowledged:
                            self.assertEqual({k: result[k] for k in ('ok', 'work_ref')}, {'ok': True, 'work_ref': result['work_ref']})
                            self.assertTrue(server._WORK_REGISTRY[result['work_ref']]['watch_refs'])
                        else:
                            self.assertFalse(result['ok'])
                            self.assertEqual(result['error_type'], 'WorkDispatchTransportUncertain')
                            self.assertEqual(result['submission_evidence']['state'], 'delivery_unknown')
                            self.assertEqual(result['agent_ref'], self.ref)
                            self.assertIn('agent_terminal_read', result['error'])
                            self.assertIn('Do not resend', result['error'])
                        work = server._WORK_REGISTRY[result['work_ref']]
                        await server._HANDOFF_REGISTRY[work['handoff_id']]['watcher_task']
                        first = await finished_work('p', result['work_ref'])
                        second = await finished_work('p', result['work_ref'])
                    self.assertEqual(first, second)
                    ev = first['submission_evidence']
                    self.assertEqual(ev['state'], 'native_acknowledged' if acknowledged else 'delivery_unknown')
                    self.assertTrue(ev['mutation_possible'])
                    self.assertEqual(len([c for c in self.state['calls'] if c[:2]==('agent','prompt')]),1)

    async def test_uncertain_and_cancelled_dispatch_retains_evidence_and_work(self):
        for error in (TimeoutError('private text'), asyncio.CancelledError(),
                      herdr_backend.HerdrError('private path', code='manual_agent_prompt_not_ready'),
                      herdr_backend.HerdrError('private', code='x'*100),
                      herdr_backend.HerdrError('private', code='/private/path')):
            with self.subTest(error=type(error).__name__):
                server._WORK_REGISTRY.clear(); server._RESULT_INBOX.clear(); server._HANDOFF_REGISTRY.clear()
                self.state['calls'].clear(); self.state['prompt_error']=error
                with patch.object(self.backend, 'watch_manual_agent_turn', AsyncMock(return_value={
                        'state':'needs_attention','reason':'startup_wait_uncertain'})):
                    if isinstance(error, asyncio.CancelledError):
                        with self.assertRaises(asyncio.CancelledError): await delegate_item('p', assignments=[{'agent_ref': self.ref, 'task': 'private task'}])
                    else:
                        result = await delegate_item('p', assignments=[{'agent_ref': self.ref, 'task': 'private task'}])
                        self.assertEqual(result['error_type'], 'WorkDispatchTransportUncertain')
                    self.assertEqual(len(server._WORK_REGISTRY),1)
                    work = next(iter(server._WORK_REGISTRY.values()))
                    await server._HANDOFF_REGISTRY[work['handoff_id']]['watcher_task']
                    result = await finished_work('p',work['work_ref'])
                ev=result['submission_evidence']
                self.assertEqual(ev['state'],'delivery_unknown');self.assertTrue(ev['mutation_possible'])
                self.assertEqual(ev['native_error_code'], 'manual_agent_prompt_not_ready'
                    if getattr(error,'code',None)=='manual_agent_prompt_not_ready' else None)
                self.assertNotIn('private',json.dumps(ev))
                self.assertEqual(len([c for c in self.state['calls'] if c[:2]==('agent','prompt')]),1)

    async def test_uncertain_wire_result_has_one_safety_instruction(self):
        self.state['prompt_handler'] = lambda *args: {}
        with patch.object(self.backend, 'watch_manual_agent_turn', AsyncMock(return_value={
                'state': 'needs_attention', 'reason': 'startup_wait_uncertain'})):
            result = await server.mcp.call_tool('delegate', {'project_ref': 'p', 'assignments': [{'agent_ref': self.ref, 'task': 'private task'}]})
        payload = result.structured_content['items'][0]
        self.assertTrue(payload['submission_evidence']['mutation_possible'])
        self.assertIn('Read agent_terminal_read', payload['error'])
        self.assertIn('Do not resend this task', payload['error'])
        self.assertEqual(len(result.content), 1)
        summary = result.content[0].text
        self.assertIn('Delivery unknown', summary)
        self.assertIn('1 delivery_unknown', summary)
        for repeated in ('Read ', 'Do not', 'agent_terminal_read'):
            self.assertNotIn(repeated, summary)
        self.assertEqual(sum(c[:2] == ('agent', 'prompt') for c in self.state['calls']), 1)

    async def test_no_send_wire_result_preserves_concrete_backend_diagnostic(self):
        reason = 'manual agent exact pane identity is unavailable'
        async def no_send(expected, task, submission_evidence):
            submission_evidence.update(state='not_attempted', mutation_possible=False,
                                       proves='no_input_attempted')
            raise herdr_backend.HerdrError(reason)
        with patch.object(self.backend, 'prompt_manual_agent', no_send), patch.object(
                self.backend, 'watch_manual_agent_turn', AsyncMock(return_value={
                    'state': 'needs_attention', 'reason': 'fixture'})):
            result = await server.mcp.call_tool('delegate', {'project_ref': 'p', 'assignments': [{'agent_ref': self.ref, 'task': 'private task'}]})
        payload = result.structured_content['items'][0]
        self.assertIs(payload['submission_evidence']['mutation_possible'], False)
        self.assertEqual(payload['error'], reason)
        self.assertEqual(len(result.content), 1)
        summary = result.content[0].text
        self.assertIn('No prompt/input was sent', summary)
        self.assertIn(payload['work_ref'], summary)
        self.assertIn(reason, summary)
        for text in (summary, payload['error']):
            for forbidden in ('Delivery unknown', 'Do not', 'resend'):
                self.assertNotIn(forbidden, text)
        self.assertFalse(any(c[:2] == ('agent', 'prompt') for c in self.state['calls']))

    def test_dispatch_summary_requires_boolean_mutation_evidence(self):
        from gpt_agent_bridge.tool_presentation import _summary
        for value in (None, 0, 1, 'false', 'true'):
            payload = {'ok': False, 'error_type': 'WorkDispatchTransportUncertain',
                       'submission_evidence': {'mutation_possible': value}}
            summary = _summary(payload, 'delegate')
            self.assertIn('Dispatch evidence unavailable', summary)
            self.assertNotIn('Delivery unknown', summary)
            self.assertNotIn('No prompt/input was sent', summary)

    async def test_local_refusal_has_no_input_attempt(self):
        candidate=copy.deepcopy(self.candidate);candidate['herdr_status']='blocked'
        with patch.object(self.backend,'_call',AsyncMock()) as call:
            evidence={}
            with self.assertRaises(herdr_backend.ManualAgentPromptNotReady):
                await self.backend.prompt_manual_agent(candidate,'task',evidence)
            call.assert_not_awaited()
        self.assertEqual(evidence['state'],'not_attempted')
        self.assertFalse(evidence['mutation_possible'])

    async def test_unknown_receipt_internal_dispatch_descriptions_are_neutral(self):
        self.state['prompt_handler'] = lambda *args: {}
        record = server._MANUAL_AGENT_CANDIDATES[self.ref]
        workspace = server._WORKSPACE_REGISTRY.resolve('p')
        work = server._reserve_work('p', workspace, self.ref, self.candidate)
        with patch.object(self.backend, 'watch_manual_agent_turn', AsyncMock(return_value={
                'state':'needs_attention','reason':'activation_observation_budget_exhausted'})):
            result = await server._dispatch_manual_turn(
                self.ref, record, 'private task', work_entry=work)
            self.assertTrue(result['ok'])
            self.assertEqual(result['state'], 'native_herdr_response_received')
            self.assertEqual(result['prompt_transport']['status'], 'native_response_received')
            self.assertEqual(result['prompt_transport']['submission_evidence']['state'], 'delivery_unknown')
            await server._HANDOFF_REGISTRY[work['handoff_id']]['watcher_task']
        settled = await finished_work('p',work['work_ref'])
        self.assertEqual(settled['submission_evidence']['state'],'delivery_unknown')
        self.assertEqual(len([c for c in self.state['calls'] if c[:2]==('agent','prompt')]),1)
