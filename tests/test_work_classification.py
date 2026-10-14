"""Final classification, manual observation and notification-free retention."""
import asyncio
import concurrent.futures
from pathlib import Path
import unittest
from unittest.mock import patch
from tests import test_read_contract as fixtures
from gpt_agent_bridge import server
from gpt_agent_bridge import work_reports


class WorkClassificationTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        fixtures.ReadContractTests.setUp(self)
        self.store = work_reports.ReportStore()
        self.addCleanup(self.store.close)
        for name, value in (('_REPORT_STORE', self.store), ('_EXPIRED_WORK_REFS', {}),
                            ('_CLASSIFICATION_TASKS', set()), ('_CLASSIFICATION_INFLIGHT', set())):
            patch.object(server, name, value).start()
        patch.object(server, '_REPORT_EVIDENCE_EXTRA_ATTEMPTS', 0).start()

    async def asyncTearDown(self):
        tasks = list(server._CLASSIFICATION_TASKS)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    def work(self, state='running', text=None, agent='a', project='p'):
        work = server._reserve_work(project, self.project, agent, {'resource_key': agent})
        work['report_key'] = self.store.allocate()
        if text is not None:
            self.path(work).write_text(text, encoding='utf-8')
        if state != 'running':
            self.settle(work, state)
        return work

    def path(self, work):
        return Path(self.store._root) / work['report_key']

    def settle(self, work, state='agent_turn_settled'):
        handoff = {'state': {'agent_turn_settled': 'done', 'continuity_lost': 'failed'}.get(state, state),
                   'reason': 'fixture'}
        server._latch_work_from_handoff(work['work_ref'], handoff)

    async def classified(self):
        await asyncio.gather(*list(server._CLASSIFICATION_TASKS))

    async def test_classification_matrix_and_late_report_is_not_reclassified(self):
        for state in ('agent_turn_settled', 'needs_attention', 'continuity_lost'):
            for text in ('readable', '', None):
                with self.subTest(state=state, text=text):
                    work = self.work(state, text)
                    await self.classified()
                    self.assertEqual(work['result_class'], server.RESULT_READY if
                        state == 'agent_turn_settled' and text else server.ATTENTION_REQUIRED)
        late = self.work('agent_turn_settled')
        await self.classified()
        self.assertEqual(late['report_status'], 'missing')
        self.path(late).write_text('late report')
        self.assertEqual((await server.work_report('p', late['work_ref']))['content'], 'late report')
        self.assertEqual(late['result_class'], server.ATTENTION_REQUIRED)
        self.assertEqual(late['report_status'], 'missing')

    async def test_invalid_missing_and_running_reports(self):
        work = self.work()
        self.assertEqual((await server.work_report('p', work['work_ref']))['error_type'], 'WorkReportNotTerminal')
        self.path(work).write_bytes(b'\xffinvalid')
        self.settle(work)
        await self.classified()
        self.assertEqual(work['result_class'], server.ATTENTION_REQUIRED)
        self.assertEqual(work['report_status'], 'invalid')
        self.assertEqual((await server.work_report('p', work['work_ref']))['error_type'], 'WorkReportInvalidUTF8')
        missing = self.work('agent_turn_settled')
        await self.classified()
        self.assertEqual((await server.work_report('p', missing['work_ref']))['error_type'], 'WorkReportMissing')

    async def test_independent_classification_has_no_all_of_gate(self):
        attention = self.work('needs_attention')
        await self.classified()
        entered, release = asyncio.Event(), asyncio.Event()
        original = server._probe_requested_reports
        async def held(targets):
            entered.set()
            await release.wait()
            return await original(targets)
        with patch.object(server, '_probe_requested_reports', held):
            normal = self.work('agent_turn_settled', 'report', agent='normal')
            await entered.wait()
            running = self.work(agent='running')
            self.assertEqual(attention['result_class'], server.ATTENTION_REQUIRED)
            self.assertIsNone(normal['result_class'])
            self.assertIsNone(running['result_class'])
            release.set()
            await self.classified()
        self.assertEqual(normal['result_class'], server.RESULT_READY)
        self.assertEqual(running['state'], 'running')

    async def test_classifier_after_expiry_cannot_republish_or_resurrect_index(self):
        entered, release = asyncio.Event(), asyncio.Event()
        async def held(targets):
            entered.set()
            await release.wait()
            return [{'work_ref': targets[0][0], 'status': 'readable'}]
        with patch.object(server, 'MAX_TERMINAL_WORK_RECORDS', 1), patch.object(server, '_probe_requested_reports', held):
            old = self.work('agent_turn_settled', 'old')
            await entered.wait()
            newer = self.work('needs_attention', agent='new')
            self.assertNotIn(old['work_ref'], server._WORK_REGISTRY)
            release.set()
            await self.classified()
        self.assertIsNone(old['result_class'])
        self.assertNotIn(old['work_ref'], server._RESULT_INBOX.get(old['inbox_key'], {}))
        self.assertEqual(newer['result_class'], server.ATTENTION_REQUIRED)

    async def test_unread_and_partly_read_reports_expire_oldest_without_pins(self):
        with patch.object(server, 'MAX_TERMINAL_WORK_RECORDS', 2):
            unread = self.work('agent_turn_settled', 'unread report')
            partial = self.work('agent_turn_settled', 'partly read', agent='partial')
            await self.classified()
            before = partial['settled_at']
            page = await server.work_report('p', partial['work_ref'], limit=1)
            self.assertEqual(page['content'], 'p')
            self.assertTrue(partial['report_evidence_served'])
            self.assertEqual(partial['settled_at'], before)
            active = self.work(agent='active')
            self.assertEqual(active['state'], 'running')
            newer = self.work('needs_attention', agent='newer')
            await self.classified()
            self.assertEqual((await server.work_report('p', unread['work_ref']))['error_type'], 'WorkRefExpired')
            self.assertFalse(self.path(unread).exists())
            newest = self.work('needs_attention', agent='newest')
            await self.classified()
            self.assertEqual((await server.work_report('p', partial['work_ref'],
                offset=page['content_next_offset'], expected_sha256=page['file_sha256']))['error_type'], 'WorkRefExpired')
            self.assertFalse(self.path(partial).exists())
            self.assertEqual(server._lookup_work('other', str(self.root), partial['work_ref'])['error_type'], 'WorkRefProjectMismatch')
            for old in (unread, partial):
                self.assertNotIn(old['work_ref'], server._RESULT_INBOX.get(old['inbox_key'], {}))
            self.assertEqual({w['work_ref'] for w in server._WORK_REGISTRY.values()}, {active['work_ref'],newer['work_ref'],newest['work_ref']})
            self.assertNotIn('undelivered_terminal_reports', server._work_capacity('p', str(self.root)))

    async def test_active_admission_is_atomic_and_independent_of_terminal_limit(self):
        with patch.object(server, 'MAX_TERMINAL_WORK_RECORDS', 1), patch.object(server, 'MAX_ACTIVE_WORK_RECORDS', 3):
            def reserve(index):
                try: return server._reserve_work('p', self.project, str(index), {})
                except server.WorkRegistryFullError as exc:
                    self.assertEqual(exc.capacity['dimension'], 'work_active')
                    return None
            with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
                results = list(pool.map(reserve, range(8)))
            self.assertEqual(sum(w is not None for w in results), 3)
            with patch.object(server, 'MAX_TERMINAL_WORK_RECORDS', 0):
                server._expire_terminal_work('p', str(self.root))
            self.assertEqual(len(server._WORK_REGISTRY), 3)
