"""Fixed delegate membership, dispatch sealing and report availability; no Agent execution."""
import asyncio
import unittest
from unittest.mock import patch
from tests import test_browser_notifications as feed_fixtures
from tests import test_work_classification as fixtures
from gpt_agent_bridge.browser_notifications import BrowserNotifications
from gpt_agent_bridge import server


class BatchFeedTests(unittest.IsolatedAsyncioTestCase):
    setUp = feed_fixtures.BrowserNotificationTests.setUp
    request = feed_fixtures.BrowserNotificationTests.request

    def batch(self, count):
        b = self.feed.begin_batch('p', '/project', count)
        works = []
        for _ in range(count):
            w = {'work_ref': 'work-' + f'{len(self.works):016x}', 'project_ref': 'p', 'workspace_root': '/project',
                 'state': 'running', 'result_class': None, 'report_status': None, 'settled_at': None}
            self.feed.reserve(b, w); self.works.append(w); works.append(w)
        return b, works

    def finish(self, w, state='agent_turn_settled', report='readable'):
        w.update(state=state, result_class='result_ready' if state=='agent_turn_settled' and report=='readable'
                 else 'attention_required', report_status=report, settled_at=100)
        self.feed.publish(w)

    async def test_four_out_of_order_only_last_classification_publishes(self):
        b, ws = self.batch(4); self.feed.seal(b)
        for i in (2, 0, 3):
            self.finish(ws[i]); self.assertEqual((await self.request()).json()['events'], [])
        self.finish(ws[1]); self.feed.publish(ws[1])
        r = (await self.request()).json()
        self.assertEqual(len(r['events']), 1); self.assertEqual(r['cursor'], 1)
        self.assertEqual([m['work_ref'] for m in r['events'][0]['members']], [w['work_ref'] for w in ws])
        self.assertTrue(all('browser_notification_sequence' not in w for w in ws))
        self.assertEqual((await self.request('?after=1')).json()['events'], [])

    async def test_two_interleaved_batches_and_singleton(self):
        a, aa = self.batch(2); b, bb = self.batch(2); single, ss = self.batch(1)
        for batch in (a,b,single): self.feed.seal(batch)
        for w in (aa[0],bb[1],ss[0],bb[0],aa[1]): self.finish(w)
        r = (await self.request()).json()['events']
        self.assertEqual([e['batch_ref'] for e in r], [single['batch_ref'],b['batch_ref'],a['batch_ref']])
        self.assertEqual([len(e['members']) for e in r], [1,2,2])

    async def test_finished_members_never_publish_before_dispatch_seal(self):
        b, ws = self.batch(2)
        for w in ws: self.finish(w)
        self.assertEqual((await self.request()).json()['events'], [])
        self.feed.seal(b); self.assertEqual(len((await self.request()).json()['events']), 1)

    async def test_abnormal_and_missing_are_not_success_or_invented_readable_reports(self):
        b, ws = self.batch(3); self.feed.seal(b)
        self.finish(ws[0]); self.finish(ws[1], 'continuity_lost', 'unknown'); self.finish(ws[2], report='missing')
        async def read(w):
            return {'ok':True,'file_sha256':'b'*64} if w is ws[0] else {'ok':False,'error_type':'WorkReportMissing'}
        self.app.router.routes = self.feed.routes(lambda p,r:self.works, read)
        event = (await self.request()).json()['events'][0]
        self.assertEqual([m['report_status'] for m in event['members']], ['readable','missing','missing'])
        self.assertEqual([m['result_class'] for m in event['members']], ['result_ready','attention_required','attention_required'])
        self.assertNotIn('report_sha256', event['members'][1])

    async def test_temporary_read_holds_batch_cursor_later_batch_and_send_check(self):
        a, aa = self.batch(4); b, bb = self.batch(1)
        for batch in (a,b): self.feed.seal(batch)
        for w in aa+bb: self.finish(w)
        aa[2]['readable'] = False
        r = (await self.request()).json(); self.assertEqual(r['cursor'],0); self.assertEqual(r['events'],[])
        r = (await self.request('?check='+a['batch_ref'])).json(); self.assertEqual(r['check']['state'],'retry')
        aa[2]['readable'] = True
        r = (await self.request('?after=0')).json(); self.assertEqual(r['cursor'],2)
        self.assertEqual([e['batch_ref'] for e in r['events']],[a['batch_ref'],b['batch_ref']])
        self.assertEqual((await self.request('?check='+a['batch_ref'])).json()['check']['state'],'readable')

    async def test_existing_528_bound_includes_expired_members_without_pinning_reports(self):
        b, ws = self.batch(server.MAX_TERMINAL_WORK_RECORDS + server.MAX_ACTIVE_WORK_RECORDS)
        self.assertEqual(len(ws),528)
        for w in ws: self.finish(w)
        for w in ws[:16]: self.feed.expire(w); self.works.remove(w)
        self.feed.seal(b)
        e = (await self.request()).json()['events'][0]
        self.assertEqual(len(e['members']),528); self.assertEqual(e['not_submitted'],0)
        self.assertTrue(all(m['state']=='expired' and m['report_status']=='unavailable' for m in e['members'][:16]))
        self.assertEqual(len(self.reads),512)
        self.works.clear()
        self.assertEqual((await self.request('?check='+b['batch_ref'])).json()['check']['state'],'unavailable')
        self.assertTrue((await self.request('?epoch=old')).json()['reset'])

    async def test_expiry_before_classification_never_claims_success_or_waits_forever(self):
        b, ws = self.batch(2); self.feed.seal(b)
        ws[0].update(state='agent_turn_settled',settled_at=99)
        self.feed.expire(ws[0]); self.works.remove(ws[0])
        self.assertEqual((await self.request()).json()['events'], [])
        self.finish(ws[1])
        self.assertEqual((await self.request()).json()['events'][0]['members'][0]['result_class'],'unavailable')


class DelegateBatchTests(unittest.IsolatedAsyncioTestCase):
    setUp = fixtures.WorkClassificationTests.setUp
    asyncTearDown = fixtures.WorkClassificationTests.asyncTearDown
    work = fixtures.WorkClassificationTests.work
    path = fixtures.WorkClassificationTests.path
    settle = fixtures.WorkClassificationTests.settle
    classified = fixtures.WorkClassificationTests.classified

    def feed(self):
        f=BrowserNotifications({'project_ref':'p','root':str(self.root),'extension_id':'a'*32,'token':'t'*48,'port':8765})
        patch.object(server,'_BROWSER_NOTIFICATIONS',f).start()
        return f

    async def test_real_reservation_classifier_partial_unknown_and_existing_ref_membership(self):
        feed=self.feed(); existing=self.work(agent='existing'); admitted=[]
        async def dispatch(project,workspace,agent,task):
            if agent=='existing':return {'ok':False,'work_ref':existing['work_ref']}
            w=self.work(agent=agent);admitted.append(w)
            if agent=='not-sent':
                server._discard_work(w['work_ref']);return {'ok':False}
            if agent=='uncertain':
                return {'ok':False,'work_ref':w['work_ref'],'submission_evidence':{'mutation_possible':True}}
            self.path(w).write_text('early report');self.settle(w);await self.classified()
            self.assertEqual(feed.sequence,0)  # dispatch loop still open
            return {'ok':True,'work_ref':w['work_ref']}
        with patch.object(server,'_delegate_work',dispatch):
            r=await server.delegate('p',[{'agent_ref':a,'task':'fixture'} for a in ['early','existing','not-sent','uncertain']])
        batch=admitted[0]['browser_notification_batch']
        self.assertTrue(batch['sealed']);self.assertEqual(feed.sequence,0)
        self.assertEqual(list(batch['members']),[admitted[0]['work_ref'],admitted[2]['work_ref']])
        self.assertEqual(r['items'][1]['existing_work_ref'],existing['work_ref'])
        self.assertEqual(r['items'][3]['outcome'],'delivery_unknown')
        self.path(admitted[2]).write_text('uncertain submission actually settled')
        self.settle(admitted[2]);await self.classified();self.assertEqual(feed.sequence,1)
        self.assertIsNone(server._DELEGATE_NOTIFICATION_BATCH.get())

    async def test_exception_and_cancel_seal_surviving_reservations_not_just_returned_receipts(self):
        feed=self.feed()
        for error in (RuntimeError('fixture'),asyncio.CancelledError()):
            admitted=[]
            async def dispatch(project,workspace,agent,task):
                w=self.work(agent=agent);admitted.append(w)
                if len(admitted)==2:raise error
                self.path(w).write_text('early');self.settle(w);await self.classified()
                return {'ok':True,'work_ref':w['work_ref']}
            with patch.object(server,'_delegate_work',dispatch),self.assertRaises(type(error)):
                await server.delegate('p',[{'agent_ref':str(i),'task':'fixture'} for i in range(4)])
            b=admitted[0]['browser_notification_batch'];self.assertTrue(b['sealed']);self.assertEqual(len(b['members']),2)
            self.assertNotIn('sequence',b);self.assertIsNone(server._DELEGATE_NOTIFICATION_BATCH.get())
            self.settle(admitted[1],'needs_attention');await self.classified()
            self.assertIn('sequence',b)

    async def test_no_admission_has_no_notification_and_actual_expiry_removes_members_identity(self):
        feed=self.feed()
        async def refused(*args):return {'ok':False}
        with patch.object(server,'_delegate_work',refused):
            await server.delegate('p',[{'agent_ref':'none','task':'fixture'}])
        self.assertEqual(feed.sequence,0)
        admitted=[]
        async def dispatch(project,workspace,agent,task):
            w=self.work(agent=agent);admitted.append(w)
            self.path(w).write_text('report');self.settle(w);await self.classified()
            return {'ok':True,'work_ref':w['work_ref']}
        with patch.object(server,'_delegate_work',dispatch),patch.object(server,'MAX_TERMINAL_WORK_RECORDS',1):
            await server.delegate('p',[{'agent_ref':str(i),'task':'fixture'} for i in range(3)])
        b=admitted[-1]['browser_notification_batch'];self.assertTrue(b['sealed']);self.assertEqual(feed.sequence,1)
        self.assertEqual([m['state'] for m in b['members'].values()],['expired','expired','agent_turn_settled'])
        self.assertNotIn(admitted[0]['work_ref'],server._WORK_REGISTRY)
