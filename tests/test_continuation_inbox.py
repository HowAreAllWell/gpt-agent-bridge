"""Phase-1 request correlation/inbox projection; no host wake or retention changes."""
import asyncio
import copy
import json
import unittest
from unittest.mock import AsyncMock, patch

from mcp.server.context import ServerRequestContext
from mcp.server.mcpserver.context import Context
from mcp.types import CallToolRequest, CallToolRequestParams, CallToolResult

from tests import test_work_classification as classification
from tests import test_submission_evidence as submissions
from tests.test_file_attachment import memory_client
from gpt_agent_bridge import server


def request_context(value=None, *, meta=None):
    if meta is None and value is not None:
        meta = {'openai/session': value}
    return Context(request_context=ServerRequestContext(
        session=object(), lifespan_context={}, protocol_version='2025-11-25',
        method='tools/call', meta=meta), mcp_server=server.mcp)


class ResultInboxTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        classification.WorkClassificationTests.setUp(self)
        patch.object(server, '_project_agent_observation', AsyncMock(return_value={})).start()

    asyncTearDown = classification.WorkClassificationTests.asyncTearDown
    work = classification.WorkClassificationTests.work
    path = classification.WorkClassificationTests.path
    settle = classification.WorkClassificationTests.settle
    classified = classification.WorkClassificationTests.classified

    def reserve_for(self, value=None, **kwargs):
        token = server._REQUEST_SESSION_CORRELATION.set(
            server._host_session_correlation(request_context(value)))
        try:
            return self.work(**kwargs)
        finally:
            server._REQUEST_SESSION_CORRELATION.reset(token)

    async def observe(self, value=None):
        result = await server.mcp.call_tool('context', {'project_ref': 'p'}, request_context(value))
        self.assertIsNone(result.meta)  # Context remains UI-free.
        return result.structured_content['continuation_inbox']

    async def test_absent_invalid_and_oversized_metadata_are_unknown(self):
        self.assertIsNone(server._host_session_correlation(None))
        self.assertIsNone(server._host_session_correlation(Context(mcp_server=server.mcp)))
        for value in (None, '', 42, False, {}, [], 'x' * 4097, '中' * 1366, '\ud800'):
            with self.subTest(shape=type(value).__name__):
                self.assertIsNone(server._host_session_correlation(request_context(
                    meta={'openai/session': value})))
        self.assertIsNone(server._host_session_correlation(request_context(
            meta={'other/session': 'never-use-transport-identity'})))
        self.assertIsNone(server._host_session_correlation(request_context(meta=[])))

    async def test_correlation_is_opaque_stable_and_process_keyed(self):
        raw = 'RAW-HOST-SESSION-中文-PRIVATE'
        digest = server._host_session_correlation(request_context(raw))
        self.assertRegex(digest, r'^[0-9a-f]{64}$')
        self.assertEqual(digest, server._host_session_correlation(request_context(raw)))
        self.assertNotEqual(digest, server._host_session_correlation(request_context(raw + '2')))
        with patch.object(server, '_HOST_SESSION_HASH_KEY', b'other-process-key'):
            self.assertNotEqual(digest, server._host_session_correlation(request_context(raw)))
        work = self.reserve_for(raw)
        self.assertEqual(work['inbox_key'], ('p', str(self.root), digest))
        self.assertNotIn(raw, str(server._RESULT_INBOX))
        self.assertNotIn(raw, str(work))

    async def test_same_session_cross_session_and_unbound_count(self):
        own = self.reserve_for('session-a', state='agent_turn_settled', text='own')
        other = self.reserve_for('session-b', state='needs_attention', agent='b')
        unbound = self.reserve_for(state='needs_attention', agent='unbound')
        active = self.reserve_for('session-a', agent='active')
        await self.classified()
        view = await self.observe('session-a')
        self.assertEqual(view, {'binding': 'session', 'classified_count': 1,
            'retained_classified': [{'work_ref': own['work_ref'], 'result_class': 'result_ready',
                                     'classification_report_status': 'readable'}],
            'has_more': False, 'proves': 'final_classification_only'})
        self.assertNotIn(other['work_ref'], str(view))
        self.assertNotIn(unbound['work_ref'], str(view))
        self.assertNotIn(active['work_ref'], str(view))
        self.assertEqual((await self.observe('session-b'))['retained_classified'][0]['work_ref'], other['work_ref'])
        self.assertEqual((await self.observe('never-registered'))['classified_count'], 0)
        self.assertEqual(await self.observe(), {'binding': 'unknown', 'unbound_classified_count': 1})
        self.assertEqual((await server.context('p'))['continuation_inbox'],
                         {'binding': 'unknown', 'unbound_classified_count': 1})

    async def test_exact_project_root_partition(self):
        work = self.reserve_for('same', state='needs_attention')
        await self.classified()
        token = server._REQUEST_SESSION_CORRELATION.set(work['inbox_key'][2])
        try:
            self.assertEqual(server._continuation_inbox_observation('q', str(self.root))['classified_count'], 0)
            self.assertEqual(server._continuation_inbox_observation('p', str(self.linked))['classified_count'], 0)
            self.assertEqual(server._continuation_inbox_observation('p', str(self.root))['classified_count'], 1)
        finally:
            server._REQUEST_SESSION_CORRELATION.reset(token)

    async def test_final_classification_projection_and_late_report_immutability(self):
        work = self.reserve_for('same')
        entered, release = asyncio.Event(), asyncio.Event()
        async def probe(targets):
            entered.set()
            await release.wait()
            return [{'work_ref': targets[0][0], 'status': 'missing'}]
        with patch.object(server, '_probe_requested_reports', probe):
            self.settle(work)
            await entered.wait()
            self.assertEqual(work['inbox_event']['result_class'], None)
            self.assertEqual((await self.observe('same'))['classified_count'], 0)
            release.set()
            await self.classified()
        self.assertEqual(work['inbox_event'], {'work_ref': work['work_ref'],
            'result_class': 'attention_required', 'report_status': 'missing'})
        self.path(work).write_text('late report')
        await server.work_report('p', work['work_ref'])
        self.assertEqual((await self.observe('same'))['retained_classified'][0], {
            'work_ref': work['work_ref'], 'result_class': 'attention_required',
            'classification_report_status': 'missing'})
        self.assertEqual(work['inbox_event']['report_status'], 'missing')

    async def test_context_does_not_consume_renew_or_schedule_classification(self):
        work = self.reserve_for('same', state='agent_turn_settled', text='report')
        await self.classified()
        before_work = copy.deepcopy({k: work[k] for k in (
            'settled_at', 'result_class', 'inbox_event')})
        with patch.object(server, '_schedule_work_classification') as schedule:
            self.assertEqual(await self.observe('same'), await self.observe('same'))
            schedule.assert_not_called()
        self.assertEqual(before_work, {k: work[k] for k in before_work})

    async def test_unread_report_remains_visible_and_read_does_not_discharge(self):
        work = self.reserve_for('same', text='unread complete report')
        self.settle(work)
        await self.classified()
        recovered = await self.observe('same')
        self.assertEqual(recovered['retained_classified'], [{
            'work_ref': work['work_ref'], 'result_class': 'result_ready',
            'classification_report_status': 'readable'}])
        self.assertEqual((await server.work_report('p', work['work_ref']))['content'], 'unread complete report')
        self.assertEqual(await self.observe('same'), recovered)


    async def test_immediately_settled_unread_report_needs_no_delivery_state(self):
        work = self.reserve_for('same', state='agent_turn_settled', text='unread report')
        await self.classified()
        with patch.object(server, 'work_report', AsyncMock(side_effect=AssertionError('no retrieval'))) as report:
            view = await self.observe('same')
            report.assert_not_awaited()
        self.assertEqual(view['retained_classified'], [{
            'work_ref': work['work_ref'], 'result_class': 'result_ready',
            'classification_report_status': 'readable'}])
        self.assertNotIn('delivery_consumed', work)
        self.assertNotIn('watch_refs', work)


    async def test_attention_late_report_keeps_classification_snapshot_and_becomes_readable(self):
        work = self.reserve_for('same')
        self.settle(work, 'continuity_lost')
        await self.classified()
        before = (await self.observe('same'))['retained_classified'][0]
        self.assertEqual(before, {'work_ref': work['work_ref'],
            'result_class': 'attention_required', 'classification_report_status': 'unknown'})
        self.path(work).write_text('late recovered report')
        report = await server.work_report('p', work['work_ref'])
        self.assertEqual(report['content'], 'late recovered report')
        self.assertEqual((await self.observe('same'))['retained_classified'][0], before)

    async def test_no_input_discard_and_existing_pressure_expiry_remove_index(self):
        reserved = self.reserve_for('same')
        key = reserved['inbox_key']
        server._discard_work(reserved['work_ref'])
        self.assertNotIn(key, server._RESULT_INBOX)
        with patch.object(server, 'MAX_TERMINAL_WORK_RECORDS', 1):
            first = self.reserve_for('same', state='needs_attention')
            await self.classified()
            second = self.reserve_for('other', state='needs_attention', agent='next')
            await self.classified()
        self.assertNotIn(first['work_ref'], server._WORK_REGISTRY)
        self.assertNotIn(first['inbox_key'], server._RESULT_INBOX)
        self.assertIn(second['work_ref'], server._RESULT_INBOX[second['inbox_key']])

    async def test_bounded_context_output_has_more_without_consumption(self):
        for index in range(53):
            self.reserve_for('same', state='needs_attention', agent=str(index))
            await self.classified()
        view = await self.observe('same')
        self.assertEqual(view['classified_count'], 53)
        self.assertEqual(len(view['retained_classified']), 50)
        self.assertTrue(view['has_more'])

    async def test_concurrent_requests_and_asyncio_to_thread_remain_local(self):
        arrived, release = asyncio.Event(), asyncio.Event()
        correlations = []
        async def admission(project_ref, workspace, agent_ref, task):
            correlation = server._REQUEST_SESSION_CORRELATION.get()
            correlations.append(correlation)
            if len(correlations) == 3:
                arrived.set()
            await release.wait()
            def in_worker():
                self.assertEqual(server._REQUEST_SESSION_CORRELATION.get(), correlation)
                return server._reserve_work(project_ref, workspace, agent_ref, {'resource_key': agent_ref})
            work = await asyncio.to_thread(in_worker)
            return {'ok': True, 'work_ref': work['work_ref']}
        with patch.object(server, '_delegate_work', admission):
            tasks = [asyncio.create_task(server.mcp.call_tool('delegate',
                {'project_ref': 'p', 'assignments': [{'agent_ref': str(i), 'task': 'task'}]}, request_context(value)))
                for i, value in enumerate(('a', 'b', None))]
            await arrived.wait()
            self.assertIsNone(server._REQUEST_SESSION_CORRELATION.get())
            release.set()
            results = await asyncio.gather(*tasks)
        for value, result in zip(('a', 'b', None), results):
            work = server._WORK_REGISTRY[result.structured_content['items'][0]['work_ref']]
            self.assertEqual(work['inbox_key'][2], server._host_session_correlation(request_context(value)))
        self.assertEqual(len(server._RESULT_INBOX), 3)
        self.assertIsNone(server._REQUEST_SESSION_CORRELATION.get())

    async def test_request_context_reset_on_exception_cancellation_and_nested_unknown(self):
        outer = 'f' * 64
        token = server._REQUEST_SESSION_CORRELATION.set(outer)
        try:
            for error in (RuntimeError('synthetic'), asyncio.CancelledError()):
                async def failed(*args, **kwargs):
                    self.assertNotEqual(server._REQUEST_SESSION_CORRELATION.get(), outer)
                    raise error
                with patch.object(server.MCPServer, 'call_tool', failed):
                    with self.assertRaises(type(error)):
                        await server.mcp.call_tool('context', {'project_ref': 'p'}, request_context('inner'))
                self.assertEqual(server._REQUEST_SESSION_CORRELATION.get(), outer)
            # No supplied SDK Context is unknown, not inherited from the caller.
            self.assertEqual((await server.mcp.call_tool('context', {'project_ref': 'p'}))
                             .structured_content['continuation_inbox']['binding'], 'unknown')
            self.assertEqual(server._REQUEST_SESSION_CORRELATION.get(), outer)
        finally:
            server._REQUEST_SESSION_CORRELATION.reset(token)

    async def test_real_memory_wire_meta_routes_without_model_argument_or_raw_id(self):
        raw = 'PRIVATE-WIRE-HOST-SESSION'
        wire = []
        async def admission(project_ref, workspace, agent_ref, task):
            work = server._reserve_work(project_ref, workspace, agent_ref, {'resource_key': agent_ref})
            work['report_key'] = self.store.allocate()
            self.settle(work, 'needs_attention')
            await self.classified()
            return {'ok': True, 'work_ref': work['work_ref']}
        async def call(client, name, args, session):
            return await client.send_request(CallToolRequest(params=CallToolRequestParams(
                name=name, arguments=args, _meta={'openai/session': session})), CallToolResult)
        with patch.object(server, '_delegate_work', admission):
            async with memory_client(wire) as client:
                delegated = await call(client, 'delegate', {'project_ref': 'p', 'assignments': [{'agent_ref': 'a', 'task': 't'}]}, raw)
                own = await call(client, 'context', {'project_ref': 'p'}, raw)
                other = await call(client, 'context', {'project_ref': 'p'}, 'another-session')
                unknown = await client.call_tool('context', {'project_ref': 'p'})
        self.assertEqual(own.structured_content['continuation_inbox']['retained_classified'][0]['work_ref'],
                         delegated.structured_content['items'][0]['work_ref'])
        self.assertEqual(other.structured_content['continuation_inbox']['classified_count'], 0)
        self.assertEqual(unknown.structured_content['continuation_inbox'],
                         {'binding': 'unknown', 'unbound_classified_count': 0})
        self.assertNotIn(raw, json.dumps(wire))
        tools = {tool.name: tool for tool in await server.mcp.list_tools()}
        self.assertEqual(set(tools['delegate'].input_schema['properties']), {'project_ref', 'assignments'})
        self.assertEqual(set(tools['context'].input_schema['properties']), {'project_ref', 'include_continuity'})
        self.assertTrue(delegated.structured_content['ok'])
        self.assertNotIn('continuation', delegated.structured_content)
        self.assertIsNone(delegated.meta)


class FixtureIsolationTests(unittest.TestCase):
    def test_work_and_inbox_fixtures_restore_together_between_cases(self):
        original_work = server._WORK_REGISTRY
        original_inbox = server._RESULT_INBOX
        before_work = dict(original_work)
        before_inbox = copy.deepcopy(original_inbox)
        cases = (
            classification.WorkClassificationTests('test_classification_matrix_and_late_report_is_not_reclassified'),
            ActualDispatchInboxTests('test_real_dispatch_success_and_uncertainty_register_before_prompt'),
        )
        for case in cases:
            with self.subTest(fixture=type(case).__name__):
                result = unittest.TestResult()
                case.run(result)
                self.assertTrue(result.wasSuccessful(), result.errors + result.failures)
                self.assertIs(server._WORK_REGISTRY, original_work)
                self.assertIs(server._RESULT_INBOX, original_inbox)
                self.assertEqual(server._WORK_REGISTRY, before_work)
                self.assertEqual(server._RESULT_INBOX, before_inbox)


class ActualDispatchInboxTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await submissions.SubmissionEvidenceTests.asyncSetUp(self)

    asyncTearDown = submissions.SubmissionEvidenceTests.asyncTearDown

    async def test_real_dispatch_success_and_uncertainty_register_before_prompt(self):
        for acknowledged in (True, False):
            server._WORK_REGISTRY.clear()
            server._HANDOFF_REGISTRY.clear()
            server._RESULT_INBOX.clear()
            def prompted(*args):
                work = next(iter(server._WORK_REGISTRY.values()))
                self.assertIn(work['work_ref'], server._RESULT_INBOX[work['inbox_key']])
                return submissions.SubmissionEvidenceTests.ack(self) if acknowledged else {}
            self.state['prompt_handler'] = prompted
            with patch.object(self.backend, 'watch_manual_agent_turn', AsyncMock(return_value={
                    'state': 'needs_attention', 'reason': 'fixture'})):
                result = await server.mcp.call_tool('delegate',
                    {'project_ref': 'p', 'assignments': [{'agent_ref': self.ref, 'task': 'private-task'}]}, request_context('same'))
                work = server._WORK_REGISTRY[result.structured_content['items'][0]['work_ref']]
                await server._HANDOFF_REGISTRY[work['handoff_id']]['watcher_task']
                await asyncio.gather(*list(server._CLASSIFICATION_TASKS))
            self.assertEqual(work['inbox_key'][2], server._host_session_correlation(request_context('same')))
            self.assertEqual(work['inbox_event']['result_class'], 'attention_required')
            self.assertTrue(result.structured_content['ok'])
            self.assertEqual(result.structured_content['items'][0]['ok'], acknowledged)
            self.assertEqual(len([call for call in self.state['calls'] if call[:2] == ('agent', 'prompt')]),
                             1 if acknowledged else 2)
