"""Unified delegate, reuse evidence gates and token-bound client telemetry."""
import asyncio
import copy
import json
from pathlib import Path
import unittest
from unittest.mock import AsyncMock, patch

from tests import test_continuation_inbox as inbox
from tests import test_submission_evidence as submissions
import server
import widget_watcher
from tool_presentation import compact_result

request_context = inbox.request_context


class DelegateCohortTests(unittest.IsolatedAsyncioTestCase):
    setUp = inbox.ResultInboxTests.setUp
    asyncTearDown = inbox.ResultInboxTests.asyncTearDown
    work = inbox.ResultInboxTests.work
    path = inbox.ResultInboxTests.path
    settle = inbox.ResultInboxTests.settle
    classified = inbox.ResultInboxTests.classified
    reserve_for = inbox.ResultInboxTests.reserve_for
    observe = inbox.ResultInboxTests.observe
    watch = inbox.ResultInboxTests.watch
    ref = inbox.ResultInboxTests.ref

    async def admit(self, project, workspace, agent, task):
        if agent == 'refused':
            return {'ok': False, 'error_type': 'WorkAlreadyInFlight', 'work_ref': 'work-ffffffffffffffff'}
        work = self.work(agent=agent)
        if agent == 'uncertain':
            work['submission_evidence'].update(state='delivery_unknown', mutation_possible=True)
            return {'ok': False, 'work_ref': work['work_ref'], 'error_type': 'WorkDispatchTransportUncertain',
                    'submission_evidence': dict(work['submission_evidence'])}
        return {'ok': True, 'work_ref': work['work_ref']}

    async def test_one_and_n_one_fixed_cohort_and_internal_registration_reuse(self):
        with patch.object(server, '_delegate_work', self.admit):
            for n in (1, 3, 12):
                server._WORK_REGISTRY.clear()
                server._RESULT_INBOX.clear()
                server._WORK_WATCHES.clear()
                result = await server.mcp.call_tool('delegate', {'project_ref': 'p', 'assignments': [
                    {'agent_ref': str(i), 'task': 'independent question'} for i in range(n)]})
                payload = result.structured_content
                self.assertEqual(len(payload['items']), n)
                refs = [item['work_ref'] for item in payload['items']]
                self.assertEqual(payload['continuation']['work_refs'], refs)
                self.assertEqual(payload['continuation']['status'], 'armed')
                self.assertEqual(len(server._WORK_WATCHES), 1)
                hydration = result.meta[widget_watcher.WORK_WATCH_META_KEY]
                self.assertEqual(hydration['work_refs'], refs)
                reused = server._register_work_watch('p', server._required_project_context('p'), list(reversed(refs)))
                self.assertEqual(reused.meta, result.meta)
                later = self.work(agent='later')
                self.assertNotIn(later['work_ref'], server._WORK_WATCHES[hydration['watch_ref']]['members'])

    async def test_partial_uncertain_and_no_older_work_adoption(self):
        with patch.object(server, '_delegate_work', self.admit):
            result = await server.delegate('p', assignments=[
                {'agent_ref': a, 'task': 'task'} for a in ('normal', 'refused', 'uncertain')])
        payload = result.structured_content
        self.assertEqual([i['outcome'] for i in payload['items']], ['submitted', 'not_submitted', 'delivery_unknown'])
        self.assertEqual(payload['items'][1]['existing_work_ref'], 'work-ffffffffffffffff')
        self.assertEqual(len(payload['continuation']['work_refs']), 2)
        self.assertNotIn('work-ffffffffffffffff', payload['continuation']['work_refs'])
        uncertain = server._WORK_REGISTRY[payload['items'][2]['work_ref']]
        self.assertTrue(uncertain['submission_evidence']['mutation_possible'])

    async def test_ready_auto_delivery_and_all_refused_without_card_hydration(self):
        async def ready(*args):
            work = self.work('agent_turn_settled', 'report')
            await self.classified()
            return {'ok': True, 'work_ref': work['work_ref']}
        with patch.object(server, '_delegate_work', ready):
            result = await server.delegate('p', assignments=[{'agent_ref': 'a', 'task': 'task'}])
        self.assertEqual(result.structured_content['continuation']['status'], 'ready')
        self.assertIn(result.structured_content['continuation']['notice'], compact_result(result, 'delegate').content[-1].text)
        self.assertIsNone(result.meta)
        self.assertEqual(server._WORK_WATCHES, {})
        self.assertTrue(next(iter(server._WORK_REGISTRY.values()))['delivery_consumed'])
        with patch.object(server, '_delegate_work', self.admit):
            refused = await server.delegate('p', assignments=[{'agent_ref': 'refused', 'task': 'task'}])
        self.assertIsNone(refused.structured_content['continuation'])
        self.assertIsNone(refused.meta)

    async def test_duplicate_alias_preflight_and_argument_guards_no_input(self):
        records = {'a': {'candidate': {'resource_key': 'same'}}, 'alias': {'candidate': {'resource_key': 'same'}}}
        with patch.object(server, '_manual_candidate_record', records.get), \
                patch.object(server, '_delegate_work', AsyncMock()) as dispatch:
            result = await server.delegate('p', assignments=[{'agent_ref': a, 'task': 'task'} for a in records])
            self.assertEqual(result.structured_content['error_type'], 'DelegateDuplicateResource')
            dispatch.assert_not_awaited()
        for args in ({'assignments': []}, {'agent_ref': 'a', 'task': 't', 'assignments': []}, {'agent_ref': 'a'}):
            with self.assertRaises(Exception):
                await server.mcp.call_tool('delegate', {'project_ref': 'p', **args})
        for assignment in ({'agent_ref': 'a', 'task': 't', 'extra': 1}, {'agent_ref': 4, 'task': 't'}):
            with self.assertRaises(Exception):
                await server.mcp.call_tool('delegate', {'project_ref': 'p', 'assignments': [assignment]})

    async def test_schema_signature_and_runtime_are_assignments_only(self):
        tool = server.mcp._tool_manager.get_tool('delegate')
        listed = {t.name: t for t in await server.mcp.list_tools()}
        schema = listed['delegate'].input_schema
        self.assertEqual(set(schema['properties']), {'project_ref', 'assignments'})
        self.assertEqual(set(schema['required']), {'project_ref', 'assignments'})
        self.assertFalse(schema['additionalProperties'])
        self.assertNotIn('runtime', schema.get('description', ''))
        self.assertNotIn('cached', schema.get('description', ''))
        assignments = schema['properties']['assignments']
        self.assertEqual(assignments['minItems'], 1)
        self.assertEqual(assignments['maxItems'], server.MAX_ACTIVE_WORK_RECORDS + server.MAX_TERMINAL_WORK_RECORDS)
        self.assertEqual(assignments['type'], 'array')
        item = schema['$defs']['DelegateAssignment']
        self.assertEqual(set(item['required']), {'agent_ref', 'task'})
        self.assertFalse(item['additionalProperties'])
        self.assertNotIn('compatibility form', listed['delegate'].description)
        self.assertEqual(set(tool.fn_metadata.arg_model.model_fields), {'project_ref', 'assignments'})
        self.assertEqual(schema, tool.fn_metadata.arg_model.model_json_schema(by_alias=True))
        import inspect
        self.assertEqual(set(inspect.signature(server.delegate).parameters), {'project_ref', 'assignments'})
        with patch.object(server, '_delegate_work', AsyncMock()) as dispatch:
            for arguments in (
                {'project_ref': 'p', 'agent_ref': 'old', 'task': 't'},
                {'project_ref': 'p', 'agent_ref': 'old', 'task': 't', 'assignments': [{'agent_ref': 'a', 'task': 't'}]},
                {'project_ref': 'p', 'assignments': []},
                {'project_ref': 'p', 'assignments': None},
                {'project_ref': 'p', 'assignments': [], 'unexpected': True},
                {'project_ref': 'p', 'assignments': [{'agent_ref': 'a', 'task': 't', 'extra': 1}]},
                {'project_ref': 'p', 'assignments': [{'agent_ref': 4, 'task': 't'}]},
                {'project_ref': 'p', 'assignments': [{'agent_ref': None, 'task': 't'}]},
                {'project_ref': 'p', 'assignments': [{'agent_ref': 'a', 'task': 't'}] * (assignments['maxItems'] + 1)},
            ):
                with self.subTest(arguments=arguments), self.assertRaises(Exception):
                    await server.mcp.call_tool('delegate', arguments)
            with self.assertRaises(TypeError):
                await server.delegate('p', 'old', 't')
            with self.assertRaises(TypeError):
                await server.delegate(project_ref='p', agent_ref='old', task='t')
            from mcp.types import CallToolRequestParams
            wire = await server.mcp._handle_call_tool(None, CallToolRequestParams(
                name='delegate', arguments={'project_ref': 'p', 'agent_ref': 'old', 'task': 't'}))
            self.assertTrue(wire.is_error)
            self.assertIsNone(wire.structured_content)
            dispatch.assert_not_awaited()
        self.assertEqual(server._WORK_REGISTRY, {})
        self.assertEqual(server._WORK_WATCHES, {})

    async def test_cancellation_retains_only_own_work_and_no_second_dispatch(self):
        unrelated = self.work(agent='unrelated')
        async def cancelled(*args):
            work = self.work(agent='cancelled')
            work['handoff_id'] = 'attempted'
            raise asyncio.CancelledError()
        with patch.object(server, '_delegate_work', cancelled) as dispatch:
            with self.assertRaises(asyncio.CancelledError):
                await server.delegate('p', assignments=[{'agent_ref': 'a', 'task': 't'}, {'agent_ref': 'b', 'task': 't'}])
        self.assertEqual(server._WORK_WATCHES, {})
        survivor = next(w for w in server._WORK_REGISTRY.values() if w is not unrelated)
        self.assertFalse(survivor['delivery_consumed'])
        self.assertNotIn(survivor['state'], server.WORK_TERMINAL_STATES)
        self.assertFalse(survivor['watch_refs'])
        self.assertIs(server._lookup_work('p', str(self.project.root), survivor['work_ref']), survivor)
        self.assertIsNone(server._DELEGATE_RESERVATIONS.get())
        self.settle(survivor, 'needs_attention')
        await self.classified()
        self.assertTrue(server._delivery_protected(survivor))
        self.assertFalse(survivor['delivery_consumed'])
        self.assertEqual(server._WORK_WATCHES, {})

    async def test_registration_race_preserves_receipts_without_partial_arm(self):
        unrelated = self.work(agent='other-client')
        async def interleaved(project, workspace, agent, task):
            receipt = await self.admit(project, workspace, agent, task)
            if agent == 'a':
                await self.watch(server._WORK_REGISTRY[receipt['work_ref']], unrelated)
            return receipt
        with patch.object(server, '_delegate_work', interleaved):
            result = await server.delegate('p', assignments=[{'agent_ref': a, 'task': 't'} for a in ('a', 'b')])
        payload = result.structured_content
        self.assertEqual(len(payload['items']), 2)
        self.assertTrue(all(item['ok'] for item in payload['items']))
        self.assertIsNone(payload['continuation'])
        self.assertEqual(payload['continuation_error']['error_type'], 'WorkWatchOverlap')
        self.assertEqual(len(server._WORK_WATCHES), 1)
        self.assertEqual(len(server._WORK_REGISTRY), 3)

    async def test_public_report_page_marker_cross_chat_empty_failure_and_probe(self):
        work = self.reserve_for('origin', state='agent_turn_settled', text='report')
        await self.classified()
        self.assertNotIn('report_evidence_served', work)
        for session, args in (('other', {'offset': 99}), ('origin', {'expected_sha256': '0' * 64})):
            await server.mcp.call_tool('work_report', {'project_ref': 'p', 'work_ref': work['work_ref'], **args}, request_context(session))
            self.assertNotIn('report_evidence_served', work)
        before = copy.deepcopy(work['inbox_event'])
        await server.mcp.call_tool('work_report', {'project_ref': 'p', 'work_ref': work['work_ref'], 'limit': 1}, request_context('other'))
        self.assertTrue(work['report_evidence_served'])
        self.assertEqual(work['inbox_event'], before)
        self.assertFalse(work['delivery_consumed'])

    async def test_compact_mixed_receipts_advisory_and_continuation_error(self):
        with patch.object(server, '_delegate_work', self.admit):
            result = await server.mcp.call_tool('delegate', {'project_ref': 'p', 'assignments': [
                {'agent_ref': a, 'task': 'private prompt body'} for a in ('normal', 'refused', 'uncertain')]})
        summary = result.content[-1].text
        for fact in ('1 submitted', '1 not_submitted', '1 delivery_unknown', 'WorkAlreadyInFlight', 'Cohort armed'):
            self.assertIn(fact, summary)
        self.assertNotIn('private prompt body', summary)
        payload = result.structured_content
        payload['items'][0]['prior_work_advisory'] = {'work_ref': 'work-1111111111111111', 'additional_count': 2}
        payload['items'][2]['prior_work_advisory'] = {'work_ref': 'work-2222222222222222', 'additional_count': 1}
        payload['continuation'] = None
        payload['continuation_error'] = {'ok': False, 'error_type': 'WorkWatchOverlap'}
        presented = compact_result(widget_watcher.watch_tool_result(payload), 'delegate')
        text = presented.content[-1].text
        self.assertIn('4 additional gaps', text)
        self.assertIn('Bridge has no recorded report evidence serving', text)
        self.assertIn('work-1111111111111111', text)
        self.assertNotIn('work-2222222222222222', text)
        self.assertIn('Continuation error: WorkWatchOverlap', text)
        self.assertEqual(presented.structured_content, payload)
        payload['items'].append({'index': 3, 'outcome': 'not_submitted', 'ok': False,
            'error_type': 'PriorWorkDiagnosticsRequired', 'prior_work': {'work_ref':'work-3333333333333333',
            'additional_count': 3}})
        text = compact_result(widget_watcher.watch_tool_result(payload), 'delegate').content[-1].text
        self.assertIn('2 not_submitted', text)
        self.assertIn('Primary refusal item 3: PriorWorkDiagnosticsRequired', text)
        self.assertIn('prior Work work-3333333333333333; 3 additional gaps', text)
        self.assertIn('Use agent_terminal_read', text)

    async def test_attempt_outcome_token_idempotence_conflict_and_no_effects(self):
        work = self.work()
        ref = self.ref(await self.watch(work))
        bad = await server.record_work_watch_send_outcome('p', ref, 'bad', 'host_accepted')
        self.assertEqual(bad['error_type'], 'WorkWatchAttemptMismatch')
        self.settle(work, 'needs_attention')
        await self.classified()
        claim = await server.claim_work_watch('p', ref)
        token = claim['attempt_token']
        self.assertRegex(token, r'^attempt-[0-9a-f]{32}$')
        frozen = copy.deepcopy(work)
        for _ in range(2):
            outcome = await server.record_work_watch_send_outcome('p', ref, token, 'host_accepted')
            self.assertEqual(outcome['proves'], 'client_reported_send_only')
        conflict = await server.record_work_watch_send_outcome('p', ref, token, 'unavailable')
        self.assertEqual(conflict['error_type'], 'WorkWatchOutcomeConflict')
        self.assertEqual(work, frozen)
        self.assertFalse((await server.claim_work_watch('p', ref))['granted'])
        for value in ('unavailable', 'host_rejected_or_unknown'):
            other = self.work(agent=value)
            other_ref = self.ref(await self.watch(other))
            self.settle(other, 'needs_attention')
            await self.classified()
            other_claim = await server.claim_work_watch('p', other_ref)
            self.assertTrue((await server.record_work_watch_send_outcome('p', other_ref, other_claim['attempt_token'], value))['ok'])
            self.assertFalse((await server.record_work_watch_send_outcome('p', ref, other_claim['attempt_token'], value))['ok'])
        self.assertEqual((await server.record_work_watch_send_outcome('p', ref, '中文', 'host_accepted'))['error_type'],
                         'WorkWatchAttemptMismatch')



class ReuseEvidenceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await submissions.SubmissionEvidenceTests.asyncSetUp(self)
        self.project = server._WORKSPACE_REGISTRY.resolve('p')
        self.state['text'] = 'current terminal diagnostics'
        self.watcher = patch.object(self.backend, 'watch_manual_agent_turn', AsyncMock(return_value={
            'state': 'done', 'reason': 'fixture'})).start()

    asyncTearDown = submissions.SubmissionEvidenceTests.asyncTearDown

    async def prior(self, state='continuity_lost', text=None, uncertain=False):
        work = server._reserve_work('p', self.project, self.ref, self.candidate)
        work['report_key'] = self.report_store.allocate()
        if text:
            (Path(self.report_store._root) / work['report_key']).write_text(text)
        work['submission_evidence'].update(state='delivery_unknown' if uncertain else 'native_acknowledged', mutation_possible=True)
        server._latch_work_from_handoff(work['work_ref'], {'state': 'failed' if state == 'continuity_lost' else 'done', 'reason': 'fixture'})
        await asyncio.gather(*list(server._CLASSIFICATION_TASKS))
        return work

    def prompts(self):
        return [c for c in self.state['calls'] if c[:2] == ('agent', 'prompt')]

    async def test_all_ready_survivor_abort_preserves_evidence_without_delivery(self):
        real_dispatch = server._delegate_work
        for failure in (asyncio.CancelledError(), RuntimeError('unexpected later dispatch failure')):
            with self.subTest(failure=type(failure).__name__):
                release = asyncio.Event()
                async def settle_after_report(*args, **kwargs):
                    await release.wait()
                    return {'state': 'done', 'reason': 'fixture'}
                first = None
                async def dispatch(project, workspace, agent, task):
                    nonlocal first
                    if agent == 'later-raise':
                        raise failure
                    receipt = await real_dispatch(project, workspace, agent, task)
                    self.assertTrue(receipt['ok'], receipt)
                    first = server._WORK_REGISTRY[receipt['work_ref']]
                    (Path(self.report_store._root) / first['report_key']).write_text('normal report')
                    release.set()
                    await server._HANDOFF_REGISTRY[first['handoff_id']]['watcher_task']
                    await asyncio.gather(*list(server._CLASSIFICATION_TASKS))
                    self.assertEqual(first['result_class'], server.RESULT_READY)
                    return receipt
                before = len(self.prompts())
                with patch.object(self.backend, 'watch_manual_agent_turn', settle_after_report), \
                        patch.object(server, '_delegate_work', dispatch):
                    with self.assertRaises(type(failure)):
                        await server.delegate('p', assignments=[{'agent_ref': a, 'task': 'one input'}
                            for a in (self.ref, 'later-raise')])
                self.assertEqual(len(self.prompts()), before + 1)
                self.assertIs(server._WORK_REGISTRY[first['work_ref']], first)
                self.assertFalse(first['delivery_consumed'])
                self.assertTrue(server._delivery_protected(first))
                self.assertFalse(first['watch_refs'])
                self.assertEqual(server._WORK_WATCHES, {})
                self.assertIsNone(server._DELEGATE_RESERVATIONS.get())
                self.assertTrue((await server.work_report('p', first['work_ref']))['ok'])
                self.assertFalse(first['delivery_consumed'])
                self.assertTrue(server._delivery_protected(first))

    async def test_actual_partial_dispatch_prompts_exactly_once(self):
        result = await server.mcp.call_tool('delegate', {'project_ref': 'p', 'assignments': [
            {'agent_ref': self.ref, 'task': 'one real fixture prompt'},
            {'agent_ref': 'unknown-agent', 'task': 'must not send'}]})
        payload = result.structured_content
        self.assertEqual([i['outcome'] for i in payload['items']], ['submitted', 'not_submitted'])
        self.assertEqual(payload['continuation']['work_refs'], [payload['items'][0]['work_ref']])
        self.assertEqual(len(self.prompts()), 1)

    async def test_older_abnormal_gap_gates_before_prompt_even_after_late_report(self):
        old = await self.prior()
        newer = await self.prior('agent_turn_settled', 'normal')
        await server.work_report('p', newer['work_ref'])
        (Path(self.report_store._root) / old['report_key']).write_text('late report')
        self.assertTrue((await server.work_report('p', old['work_ref']))['ok'])
        result = (await server.delegate('p', assignments=[{'agent_ref': self.ref, 'task': 'new task'}])).structured_content['items'][0]
        self.assertEqual(result['error_type'], 'PriorWorkDiagnosticsRequired')
        self.assertEqual(result['prior_work']['work_ref'], old['work_ref'])
        self.assertFalse(result['submission_evidence']['mutation_possible'])
        self.assertEqual(self.prompts(), [])
        self.assertEqual(old['result_class'], 'attention_required')
        self.assertEqual(old['report_status'], 'unknown')
        diagnostic = await server.agent_terminal_read('p', self.ref)
        self.assertTrue(diagnostic['ok'], diagnostic)
        self.assertEqual(diagnostic['attribution'], 'unattributed_current_terminal_output')
        self.assertTrue((await server.delegate('p', assignments=[{'agent_ref': self.ref, 'task': 'new task'}])).structured_content['items'][0]['ok'])
        self.assertEqual(len(self.prompts()), 1)

    async def test_normal_report_gap_advisory_nonblocking_and_older_gap_count(self):
        first = await self.prior('agent_turn_settled', 'first')
        await self.prior('agent_turn_settled', 'second')
        newest = await self.prior('agent_turn_settled', 'observed')
        await server.work_report('p', newest['work_ref'])
        result = (await server.delegate('p', assignments=[{'agent_ref': self.ref, 'task': 'new task'}])).structured_content['items'][0]
        self.assertTrue(result['ok'], result)
        self.assertEqual(result['prior_work_advisory']['work_ref'], first['work_ref'])
        self.assertEqual(result['prior_work_advisory']['additional_count'], 1)
        self.assertEqual(len(self.prompts()), 1)

    async def test_uncertain_normal_result_still_requires_diagnostics(self):
        work = await self.prior('agent_turn_settled', 'normal', uncertain=True)
        await server.work_report('p', work['work_ref'])
        result = (await server.delegate('p', assignments=[{'agent_ref': self.ref, 'task': 'new task'}])).structured_content['items'][0]
        self.assertEqual(result['error_type'], 'PriorWorkDiagnosticsRequired')
        self.assertEqual(self.prompts(), [])

    async def test_missing_classification_late_report_does_not_clear_diagnostic_gate(self):
        work = await self.prior('agent_turn_settled')
        self.assertEqual(work['result_class'], 'attention_required')
        self.assertEqual(work['report_status'], 'missing')
        (Path(self.report_store._root) / work['report_key']).write_text('late readable evidence')
        self.assertTrue((await server.work_report('p', work['work_ref']))['ok'])
        self.assertEqual((await server.delegate('p', assignments=[{'agent_ref': self.ref, 'task': 'new task'}])).structured_content['items'][0]['error_type'],
                         'PriorWorkDiagnosticsRequired')
        self.assertEqual(work['report_status'], 'missing')
        self.assertEqual(self.prompts(), [])

    async def test_diagnostic_read_failure_wrong_project_and_resource_change_do_not_mark(self):
        work = await self.prior()
        self.assertFalse((await server.agent_terminal_read('wrong-project', self.ref))['ok'])
        with patch.object(server, '_read_agent_candidate', AsyncMock(return_value={'ok': False,
                'error_type': 'ManualCandidateReadUnavailable'})):
            self.assertFalse((await server.agent_terminal_read('p', self.ref))['ok'])
        record = server._manual_candidate_record(self.ref)
        async def changed(**kwargs):
            record['candidate'] = dict(record['candidate'], resource_key='changed-resource')
            return {'ok': True, 'read': {'text': 'other resource text'}}
        with patch.object(server, '_read_agent_candidate', changed):
            await server.agent_terminal_read('p', self.ref)
        self.assertNotIn('terminal_diagnostics_served_condition', work)

    async def test_attention_condition_arriving_during_read_does_not_qualify(self):
        work = server._reserve_work('p', self.project, self.ref, self.candidate)
        work['report_key'] = self.report_store.allocate()
        work['state'] = 'agent_turn_settled'
        work['settled_at'] = 1
        work['submission_evidence']['state'] = 'native_acknowledged'
        async def newly_classified(**kwargs):
            await server._classify_latched_work(work['work_ref'])
            return {'ok': True, 'read': {'text': 'text returned after the new condition'}}
        with patch.object(server, '_read_agent_candidate', newly_classified):
            await server.agent_terminal_read('p', self.ref)
        self.assertEqual(work['result_class'], 'attention_required')
        self.assertNotIn('terminal_diagnostics_served_condition', work)

    async def test_cross_chat_diagnostics_never_erase_prior_observation(self):
        work = await self.prior()
        for session in ('a', 'b'):
            result = await server.mcp.call_tool('agent_terminal_read', {'project_ref': 'p', 'agent_ref': self.ref}, request_context(session))
            self.assertTrue(result.structured_content['ok'])
            self.assertEqual(work['terminal_diagnostics_served_condition'], server._diagnostic_condition(work))
        reused = await server.mcp.call_tool('delegate', {'project_ref': 'p', 'assignments': [
            {'agent_ref': self.ref, 'task': 'new task'}]}, request_context('a'))
        self.assertTrue(reused.structured_content['items'][0]['ok'], reused)
        self.assertEqual(len(self.prompts()), 1)

    async def test_concurrent_diagnostic_read_orders_keep_shared_fact(self):
        work = await self.prior()
        for finish_order in (('a', 'b'), ('b', 'a')):
            with self.subTest(finish_order=finish_order):
                events = {name: asyncio.Event() for name in ('a', 'b')}
                entered = {name: asyncio.Event() for name in ('a', 'b')}
                async def read_in_lane(name):
                    token = server._REQUEST_SESSION_CORRELATION.set(name * 64)
                    try:
                        return await server.agent_terminal_read('p', self.ref)
                    finally:
                        server._REQUEST_SESSION_CORRELATION.reset(token)
                async def read(**kwargs):
                    name = server._REQUEST_SESSION_CORRELATION.get()[0]
                    entered[name].set()
                    await events[name].wait()
                    return {'ok': True, 'read': {'text': 'weak current diagnostics'}}
                with patch.object(server, '_read_agent_candidate', read):
                    tasks = {name: asyncio.create_task(read_in_lane(name)) for name in events}
                    await asyncio.gather(*(event.wait() for event in entered.values()))
                    for name in finish_order:
                        events[name].set()
                        self.assertTrue((await tasks[name])['ok'])
                        self.assertEqual(work['terminal_diagnostics_served_condition'], server._diagnostic_condition(work))
                current = dict(project_ref='p', workspace_root=str(self.root))
                self.assertIsNone(server._prior_evidence_gap(current, self.candidate['resource_key']))

    async def test_diagnostic_condition_changes_and_new_work_do_not_qualify(self):
        work = await self.prior()
        entered, release = asyncio.Event(), asyncio.Event()
        async def read(**kwargs):
            entered.set()
            await release.wait()
            return {'ok': True, 'read': {'text': 'current evidence'}}
        with patch.object(server, '_read_agent_candidate', read):
            task = asyncio.create_task(server.agent_terminal_read('p', self.ref))
            await entered.wait()
            new = await self.prior()
            release.set()
            await task
        self.assertIn('terminal_diagnostics_served_condition', work)
        self.assertNotIn('terminal_diagnostics_served_condition', new)
        before = copy.deepcopy(new)
        with patch.object(server, '_read_agent_candidate', AsyncMock(return_value={'ok': True, 'read': {'text': ''}})):
            await server.agent_terminal_read('p', self.ref)
        self.assertEqual(new, before)
        new['reason'] = 'changed diagnostic condition'
        self.assertEqual(server._prior_evidence_gap(dict(project_ref='p', workspace_root=str(self.root)),
            self.candidate['resource_key'])['work_ref'], new['work_ref'])
        await server.agent_terminal_read('p', self.ref)
        new['state'] = 'needs_attention'
        self.assertNotEqual(new['terminal_diagnostics_served_condition'], server._diagnostic_condition(new))
        self.assertEqual((await server.delegate('p', assignments=[{'agent_ref': self.ref, 'task': 'new task'}])).structured_content['items'][0]['error_type'],
                         'PriorWorkDiagnosticsRequired')

    async def test_report_served_in_other_chat_prevents_normal_advisory(self):
        work = await self.prior('agent_turn_settled', 'normal')
        report = await server.mcp.call_tool('work_report', {'project_ref': 'p', 'work_ref': work['work_ref']}, request_context('other'))
        self.assertTrue(report.structured_content['ok'])
        reused = await server.mcp.call_tool('delegate', {'project_ref': 'p', 'assignments': [
            {'agent_ref': self.ref, 'task': 'next task'}]}, request_context('resumed'))
        self.assertTrue(reused.structured_content['items'][0]['ok'])
        self.assertNotIn('prior_work_advisory', reused.structured_content['items'][0])
