import asyncio
import unittest
import json
from starlette.applications import Starlette
from gpt_agent_bridge.browser_notifications import BrowserNotifications

class BrowserNotificationTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.config = {'project_ref':'p','root':'/project','extension_id':'a'*32,'token':'t'*48,'port':8765}
        self.feed = BrowserNotifications(self.config)
        self.works = []
        self.reads = []
        async def read(w):
            self.reads.append(w['work_ref'])
            return {'ok':w.get('readable',True),'file_sha256':'b'*64}
        self.app = Starlette(routes=self.feed.routes(lambda p,r:self.works, read))
        self.headers = {'Origin':'chrome-extension://'+'a'*32,'Authorization':'Bearer '+'t'*48}
    def work(self, **kw):
        w={'work_ref':'work-'+f'{len(self.works):016x}','project_ref':'p','workspace_root':'/project',
           'result_class':'result_ready','report_status':'readable','settled_at':100,**kw}
        self.works.append(w);self.feed.publish(w);return w
    async def request(self, query='', headers=None, method='GET', body=None):
        headers = {'Host':'127.0.0.1:8765', **(self.headers if headers is None else headers)}
        scope = {'type':'http','method':method,'path':'/browser-notifications/v1/events',
                 'query_string':query.lstrip('?').encode(),'headers':[(k.lower().encode(),v.encode()) for k,v in headers.items()],
                 'client':('127.0.0.1',1000),'server':('127.0.0.1',8765),'scheme':'http'}
        messages=[]
        async def receive(): return {'type':'http.request','body':json.dumps(body).encode(),'more_body':False}
        async def send(message): messages.append(message)
        await self.app(scope,receive,send)
        class Response:
            status_code=messages[0]['status']
            def json(self): return json.loads(b''.join(m.get('body',b'') for m in messages))
        return Response()
    async def test_only_ready_and_same_scope_and_publish_once(self):
        self.work(result_class=None);self.work(result_class='attention_required');self.work(project_ref='other')
        w=self.work();self.feed.publish(w)
        r=(await self.request()).json()
        self.assertEqual([e['work_ref'] for e in r['events']],[w['work_ref']]);self.assertEqual(r['cursor'],1)
        self.assertNotIn('content',str(r));self.assertEqual(self.feed.sequence,1)
    async def test_cursor_check_expiry_and_disconnect_are_non_consuming(self):
        a=self.work();b=self.work(readable=False)
        first=(await self.request()).json();self.assertEqual(first,(await self.request()).json())
        self.assertEqual(first['cursor'],1);self.assertEqual(len(first['events']),1)
        self.assertEqual(first['blocked']['work_ref'],b['work_ref'])
        self.assertEqual((await self.request('?after=1')).json()['events'],[])
        self.assertEqual((await self.request('?check='+b['work_ref'])).json()['check']['state'],'retry')
        b['readable']=True
        recovered=(await self.request('?after=1')).json()
        self.assertEqual([e['work_ref'] for e in recovered['events']],[b['work_ref']])
        self.assertEqual(recovered['cursor'],2)
        self.assertEqual(len((await self.request('?check='+a['work_ref'])).json()['events']),1)
        self.works.remove(a);expired=(await self.request('?check='+a['work_ref'])).json()
        self.assertEqual(expired['events'],[]);self.assertEqual(expired['check']['state'],'unavailable')

    async def test_real_report_store_emfile_never_skips_failed_or_later_sequences(self):
        import errno,os
        from pathlib import Path
        from unittest.mock import patch
        from gpt_agent_bridge.work_reports import ReportStore
        store=ReportStore();works=[self.work() for _ in range(3)];keys={}
        try:
            for w in works:
                key=store.allocate();keys[w['work_ref']]=key
                Path(store._root,key).write_text('Synthetic report '+w['work_ref'])
            async def read(w):return store.read(keys[w['work_ref']],0,1,None)
            self.app.router.routes=self.feed.routes(lambda p,r:self.works,read)
            original=os.open;bad=keys[works[1]['work_ref']]
            def fault(path,*args,**kwargs):
                if path==bad:raise OSError(errno.EMFILE,'synthetic transient')
                return original(path,*args,**kwargs)
            with patch('gpt_agent_bridge.work_reports.os.open',side_effect=fault):
                first=(await self.request()).json()
                self.assertEqual(first['cursor'],1)
                self.assertEqual([e['work_ref'] for e in first['events']],[works[0]['work_ref']])
                self.assertEqual((await self.request('?after=1')).json()['cursor'],1)
                self.assertEqual((await self.request('?check='+works[1]['work_ref'])).json()['check']['state'],'retry')
            resumed=(await self.request('?after=1')).json()
            self.assertEqual([e['work_ref'] for e in resumed['events']],[w['work_ref'] for w in works[1:]])
            self.assertEqual(resumed['cursor'],3)
            self.assertEqual((await self.request('?check='+works[1]['work_ref'])).json()['check']['state'],'readable')
        finally:store.close()

    async def test_batch_boundary_and_unknown_read_error_hold_cursor_until_recovery(self):
        works=[self.work() for _ in range(18)];works[16]['readable']=False
        first=(await self.request()).json();self.assertEqual(len(first['events']),16)
        blocked=(await self.request('?after=16')).json()
        self.assertEqual(blocked['cursor'],16);self.assertEqual(blocked['events'],[])
        works[16]['readable']=True
        resumed=(await self.request('?after=16')).json()
        self.assertEqual([e['sequence'] for e in resumed['events']],[17,18])

    async def test_authoritative_identity_loss_can_advance_and_close_check(self):
        lost=self.work();later=self.work()
        async def read(w):return ({'ok':False,'error_type':'WorkNotificationIdentityLost'} if w is lost else
                                 {'ok':True,'file_sha256':'b'*64})
        self.app.router.routes=self.feed.routes(lambda p,r:self.works,read)
        result=(await self.request()).json()
        self.assertEqual(result['cursor'],2);self.assertEqual([e['work_ref'] for e in result['events']],[later['work_ref']])
        self.assertEqual((await self.request('?check='+lost['work_ref'])).json()['check']['state'],'unavailable')
    async def test_restart_epoch_and_invalid_query(self):
        self.work();r=(await self.request('?epoch=old&after=99')).json()
        self.assertTrue(r['reset']);self.assertEqual(r['events'],[])
        for q in ('?after=-1','?after=oops','?check=../bad','?unknown=x'):
            self.assertEqual((await self.request(q)).status_code,400)
    async def test_capability_origin_host_and_no_disabled_feed(self):
        self.work()
        for headers in ({},{'Origin':self.headers['Origin']},{**self.headers,'Origin':'https://evil.example'},
                        {**self.headers,'Authorization':'Bearer bad'},{**self.headers,'Host':'public.example'}):
            self.assertEqual((await self.request(headers=headers)).status_code,403)
        self.assertEqual((await self.request(headers={'Authorization':self.headers['Authorization']})).status_code,200)
        self.feed.config=None;self.assertEqual((await self.request()).status_code,404)
    async def test_diagnostics_never_change_work_or_delivery(self):
        w=self.work();original=dict(w)
        self.assertEqual((await self.request(method='POST',body={'enabled':True,'deliveries':[]})).status_code,200)
        self.assertEqual(w,original);self.assertIsNotNone((await self.request('?status=1')).json()['status'])
        self.assertEqual((await self.request(method='POST',body={'dispatch':'x'})).status_code,400)
