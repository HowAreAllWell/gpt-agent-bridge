"""Actual SDK adapter composition; only disposable Git repositories and synthetic workers."""
import asyncio
import hashlib
import json
import os
from pathlib import Path
import threading
import unittest
from unittest.mock import patch
from mcp.types import CallToolRequestParams
from tests import test_file_observation as fixtures
from tests import test_tool_surface_integration as integration
import commit_candidate as capability
import server
from workspace_context import WorkspaceRegistry, WorkspaceRegistryStore


class ConvergenceFinalTests(unittest.IsolatedAsyncioTestCase):
    git = fixtures.FileObservationTests.git
    wire = integration.IntegratedEvidenceTests.wire

    def setUp(self):
        clean = {key: value for key, value in os.environ.items() if not key.startswith('GIT_')}
        clean.update(GIT_CONFIG_GLOBAL='/dev/null', GIT_CONFIG_SYSTEM='/dev/null', GIT_CONFIG_NOSYSTEM='1')
        env = patch.dict(os.environ, clean, clear=True)
        env.start(); self.addCleanup(env.stop)
        fixtures.FileObservationTests.setUp(self)
        self.git('config','user.name','Fixture')
        self.git('config','user.email','fixture@example.invalid')
        store=capability.CandidateStore(lambda p,w: server._resolve_evidence_target(p,w))
        p=patch.object(server,'_commit_candidates',store);p.start();self.addCleanup(p.stop)
        self.store=store

    def stage(self,root):
        (root/'selected').write_bytes(b'accepted\n')
        self.git('add','selected',root=root)
        (root/'selected').write_bytes(b'accepted\nUNSTAGED\n')
        return Path(self.git('rev-parse','--path-format=absolute','--git-path','index',root=root).decode().strip())

    async def preview(self, work_ref=None):
        _,p=await self.wire('commit_prepare',project_ref='p',work_ref=work_ref)
        self.assertEqual(p['status'],'previewed',p)
        return p

    async def test_sdk_text_edit_selected_prepare_review_commit_and_cached_receipt(self):
        for root, work in ((self.root, None), (self.link, 'w')):
            with self.subTest(work=work):
                path = 'chosen.txt'; original = 'before 字\r\n'.encode()
                (root / path).write_bytes(original)
                _, edited = await self.wire('project_text_edit', project_ref='p', work_ref=work,
                    path=path, expected_sha256=hashlib.sha256(original).hexdigest(),
                    edits=[{'old_text':'before', 'new_text':'accepted'}])
                self.assertTrue(edited['ok'], edited)
                _, prepared = await self.wire('commit_prepare', project_ref='p', work_ref=work, paths=[path])
                self.assertEqual(prepared['status'], 'previewed', prepared)
                self.assertTrue(prepared['index_updated'])
                index = Path(self.git('rev-parse','--path-format=absolute','--git-path','index',root=root).decode().strip())
                saved = index.read_bytes()
                (root / path).write_bytes(b'later unstaged\n')
                _, page = await self.wire('commit_prepare', project_ref='p', work_ref=work,
                                         candidate_id=prepared['candidate_id'], view='patch', limit=16384)
                self.assertFalse(page['repository_writes'])
                self.assertIn('accepted', page['text']); self.assertNotIn('later unstaged', page['text'])
                _, published = await self.wire('commit', project_ref='p', candidate_id=prepared['candidate_id'], message='selected wire')
                self.assertEqual(published['status'], 'committed', published)
                self.assertEqual(self.git('show','HEAD:' + path,root=root), 'accepted 字\r\n'.encode())
                self.assertEqual((root / path).read_bytes(), b'later unstaged\n')
                self.assertEqual(index.read_bytes(), saved)
                _, receipt = await self.wire('commit_prepare', project_ref='p', work_ref=work,
                                            candidate_id=prepared['candidate_id'], view='receipt')
                self.assertEqual(receipt['status'], 'committed')

    async def test_sdk_observe_checkpoint_staged_preview_commit_and_receipt(self):
        (self.root/'.principal').mkdir()
        (self.root/'.principal/project.json').write_text(json.dumps({
            'rules':['RULES.md'],'current_state':'STATE.md','memory':'MEMORY.md'}))
        (self.root/'RULES.md').write_text('fixture')
        (self.root/'MEMORY.md').write_text('fixture memory')
        (self.root/'STATE.md').write_bytes('next: old\r\n字\r\n'.encode())
        _,state=await self.wire('read',project_ref='p',path='STATE.md')
        _,publication=await self.wire('current_state_update',project_ref='p',expected_revision='sha256:'+state['file_sha256'],
                                     edits=[{'old_text':'next: old','new_text':'next: accepted'}])
        self.assertTrue(publication['ok'])
        for root,work in [(self.root,None),(self.link,'w')]:
            with self.subTest(work=work):
                (root/'logs').mkdir();name='logs/new 字.log';body='unique evidence 😀\nsecond page\n'
                (root/name).write_text(body)
                _,listing=await self.wire('list_entries',project_ref='p',work_ref=work,path='logs')
                self.assertEqual(listing['entries'][0]['path'],name)
                _,found=await self.wire('search',project_ref='p',work_ref=work,query='unique evidence',include_untracked=True)
                self.assertEqual(found['matches'][0]['read_locator']['path'],name)
                _,digest=await self.wire('inspect_file',project_ref='p',work_ref=work,path=name)
                _,page=await self.wire('read',project_ref='p',work_ref=work,path=name,limit=8,expected_sha256=digest['sha256'])
                _,rest=await self.wire('read',project_ref='p',work_ref=work,path=name,offset=page['content_next_offset'],expected_sha256=digest['sha256'])
                self.assertEqual(page['content']+rest['content'],body)
                index=self.stage(root);index_before=index.read_bytes();files={p:p.read_bytes() for p in root.rglob('*') if p.is_file() and '.git' not in p.parts}
                candidate=await self.preview(work)
                _,patchpage=await self.wire('commit_prepare',project_ref='p',work_ref=work,candidate_id=candidate['candidate_id'],view='patch',limit=16384)
                self.assertIn('+accepted',patchpage['text']);self.assertNotIn('UNSTAGED',patchpage['text'])
                self.assertNotIn('dirty',patchpage);self.assertNotIn('state_id',patchpage)
                wire,result=await self.wire('commit',project_ref='p',candidate_id=candidate['candidate_id'],message='accepted staged fixture')
                self.assertEqual(result['status'],'committed',result)
                self.assertTrue(result['side_effects']['ref_updated'])
                self.assertIn('Candidate committed',wire['content'][0]['text'])
                self.assertEqual(self.git('show','HEAD:selected',root=root),b'accepted\n')
                self.assertEqual(index.read_bytes(),index_before)
                self.assertEqual({p:p.read_bytes() for p in files},files)
                with patch.object(capability,'_run_git',side_effect=AssertionError('no second attempt')):
                    _,replay=await self.wire('commit',project_ref='p',candidate_id=candidate['candidate_id'],message='accepted staged fixture')
                    self.assertEqual(replay,result)
                    _,receipt=await self.wire('commit_prepare',project_ref='p',work_ref=work,candidate_id=candidate['candidate_id'],view='receipt')
                    self.assertEqual(receipt['status'],'committed')
                    self.assertEqual(receipt['result']['commit'],result['commit'])

    async def test_cached_project_authority_mismatch_and_lost_id(self):
        self.stage(self.root);p=await self.preview();token=p['candidate_id']
        _,r=await self.wire('commit',project_ref='p',candidate_id=token,message='one')
        self.assertEqual(r['status'],'committed')
        other=WorkspaceRegistry(self.root,json.dumps({'alias':str(self.root)}),
                                store=WorkspaceRegistryStore(self.area/'other-registry.json'))
        with patch.object(server,'_WORKSPACE_REGISTRY',other),patch.object(capability,'_run_git',side_effect=AssertionError('cache must not execute')):
            for tool,kw in [('commit',{'message':'one'}),('commit_prepare',{})]:
                _,result=await self.wire(tool,project_ref='alias',candidate_id=token,**kw)
                self.assertEqual(result['status'],'rejected',result)
                self.assertIn('mismatch',result['reason'])
        with patch.object(server,'_required_project_context',return_value={'ok':False,'error_type':'RegistryRemoved'}):
            _,result=await self.wire('commit',project_ref='p',candidate_id=token,message='one')
            self.assertEqual(result['error_type'],'RegistryRemoved')
        with patch.object(capability,'_run_git',side_effect=AssertionError('no recapture')):
            _,lost=await self.wire('commit',project_ref='p',candidate_id='lost',message='one')
            self.assertEqual(lost['reason'],'candidate-unavailable-no-recapture')

    async def test_invalid_message_parameters_no_attempt_and_index_drift(self):
        self.stage(self.link);p=await self.preview('w');token=p['candidate_id']
        with patch.object(self.store,'commit',side_effect=AssertionError('no mutation')):
            for message in ['', '\0', ' ', 'x'*65537]:
                _,result=await self.wire('commit',project_ref='p',candidate_id=token,message=message)
                self.assertEqual(result['status'],'rejected')
            for name,args in [('commit',{'candidate_id':token,'message':'x'}),('commit_prepare',{})]:
                result=await server.mcp._handle_call_tool(None,CallToolRequestParams(name=name,arguments={'project_ref':'p',**args,'argv':['forbidden']}))
                self.assertTrue(result.is_error)
            self.assertIsNone(self.store.cached_result('p',token,'x'))
        # A nonterminal Work no longer gates commit; only actual candidate
        # snapshot drift may reject the mutation.
        server._WORK_REGISTRY['w']['state']=server.WORK_STATE_RUNNING
        head_before=self.git('rev-parse','HEAD',root=self.link)
        (self.link/'drift').write_text('drift\n')
        self.git('add','drift',root=self.link)
        _,drift=await self.wire('commit',project_ref='p',candidate_id=token,message='x')
        self.assertEqual(drift['status'],'rejected',drift)
        self.assertEqual(drift['reason'],'index-semantic-drift')
        self.assertFalse(drift['side_effects']['ref_updated'])
        self.assertEqual(self.git('rev-parse','HEAD',root=self.link),head_before)

    async def test_unknown_wire_is_sealed_and_not_success(self):
        self.stage(self.root);p=await self.preview();real=capability._run_git
        def lost(root,args,env,deadline,input_bytes=None):
            result=real(root,args,env,deadline,input_bytes)
            if args[0]=='update-ref':raise capability.GitFailure('timeout')
            return result
        with patch.object(capability,'_run_git',side_effect=lost):
            wire,result=await self.wire('commit',project_ref='p',candidate_id=p['candidate_id'],message='lost reply')
        self.assertEqual(result['status'],'unknown',result)
        self.assertIsNone(result['side_effects']['ref_updated'])
        self.assertTrue(result['side_effects']['objects_may_remain'])
        self.assertIn('Candidate unknown',wire['content'][0]['text'])
        self.assertNotIn('OK',wire['content'][0]['text'])
        with patch.object(capability,'_run_git',side_effect=AssertionError('no unknown retry')):
            _,again=await self.wire('commit',project_ref='p',candidate_id=p['candidate_id'],message='lost reply')
            self.assertEqual(result,again)

    async def test_preview_and_commit_cancellation_hold_gate_until_worker_ends(self):
        self.stage(self.root);candidate=await self.preview()
        for name in ['preview','commit']:
            for fails in [False,True]:
                started,finish=threading.Event(),threading.Event()
                def worker(*args,**kwargs):
                    started.set()
                    if not finish.wait(3):raise AssertionError('test worker timeout')
                    if fails:raise ValueError('worker terminal failure')
                    return {'status':'rejected','reason':'synthetic'}
                gate=server._access_gate(self.root)
                with patch.object(self.store,name,worker):
                    call=(server.commit_prepare('p') if name=='preview' else server.commit('p',candidate['candidate_id'],'test'))
                    task=asyncio.create_task(call);waiting=None
                    try:
                        self.assertTrue(await asyncio.to_thread(started.wait,2))
                        task.cancel();await asyncio.sleep(.02);task.cancel()
                        waiting=asyncio.create_task(gate.acquire('writer'))
                        await asyncio.sleep(.02)
                        self.assertFalse(task.done());self.assertFalse(waiting.done())
                        finish.set()
                        with self.assertRaises(asyncio.CancelledError):await task
                        lease=await waiting;await lease.release()
                    finally:
                        finish.set();await asyncio.gather(task,return_exceptions=True)
                        if waiting and not waiting.done():waiting.cancel();await asyncio.gather(waiting,return_exceptions=True)
                self.assertFalse(gate.writer_active);self.assertEqual(gate.active_readers,0)

    async def test_cached_target_change_and_malformed_ids_never_execute(self):
        self.stage(self.link);candidate=await self.preview('w');token=candidate['candidate_id']
        with patch.object(self.store,'commit',side_effect=AssertionError('must not execute')):
            for args in [{'candidate_id':None,'message':'one'}, {'candidate_id':{},'message':'one'},
                         {'candidate_id':token,'message':[]}, {'candidate_id':token,'message':None}]:
                result=await server.mcp._handle_call_tool(None,CallToolRequestParams(name='commit',arguments={'project_ref':'p',**args}))
                self.assertTrue(result.is_error)
            original=server._WORK_REGISTRY.pop('w')
            try:
                for tool,args in [('commit',{'message':'one'}),('commit_prepare',{'work_ref':'w'})]:
                    _,result=await self.wire(tool,project_ref='p',candidate_id=token,**args)
                    if tool == 'commit':
                        self.assertEqual(result['error_type'],'WorkRefUnavailable')
                    else:
                        self.assertEqual(result['status'],'previewed')
            finally:
                server._WORK_REGISTRY['w']=original
        self.assertIsNone(self.store.cached_result('p',token,'one'))
        _,result=await self.wire('commit',project_ref='p',candidate_id=token,message='one')
        self.assertEqual(result['status'],'committed')
        with patch.object(capability,'_run_git',side_effect=AssertionError('cached target must not execute')):
            server._WORK_REGISTRY.pop('w')
            _,result=await self.wire('commit',project_ref='p',candidate_id=token,message='one')
            self.assertEqual(result['status'],'committed')

    async def test_sdk_matching_required_filters_staged_objects_main_and_linked(self):
        (self.root/'.principal').mkdir()
        (self.root/'.principal/project.json').write_text(json.dumps({
            'rules':['RULES.md'],'current_state':'STATE.md','memory':'MEMORY.md'}))
        (self.root/'RULES.md').write_text('fixture')
        (self.root/'MEMORY.md').write_text('fixture memory')
        (self.root/'STATE.md').write_bytes(b'next: old\r\n')
        _,state=await self.wire('read',project_ref='p',path='STATE.md')
        _,state=await self.wire('current_state_update',project_ref='p',expected_revision='sha256:'+state['file_sha256'],
                              edits=[{'old_text':'next: old','new_text':'next: R3'}])
        self.assertTrue(state['ok'])
        marker=self.area/'helper-ran';helper=self.area/'filter-helper'
        helper.write_text(f'#!/bin/sh\nprintf invoked > "{marker}"\nexit 97\n');helper.chmod(0o755)
        for root,work in [(self.root,None),(self.link,'w')]:
            for process in [True,False]:
                with self.subTest(work=work,process=process):
                    text=(f'accepted {process}\n').encode();binary=b'\0accepted\xff'+bytes([int(process)])
                    (root/'selected').write_bytes(text);(root/'binary').write_bytes(binary)
                    (root/'.gitattributes').write_text('selected filter=fixture\nbinary filter=fixture\n')
                    self.git('add','selected','binary','.gitattributes',root=root)
                    (root/'selected').write_bytes(text+b'UNSTAGED\n')
                    (root/'binary').write_bytes(binary+b'\0UNSTAGED\xff')
                    log='new log.txt';(root/log).write_text('R3 unique evidence\npage two\n')
                    _,found=await self.wire('search',project_ref='p',work_ref=work,query='R3 unique evidence',include_untracked=True)
                    self.assertEqual(found['matches'][0]['read_locator']['path'],log)
                    _,digest=await self.wire('inspect_file',project_ref='p',work_ref=work,path=log)
                    _,first=await self.wire('read',project_ref='p',work_ref=work,path=log,limit=5,expected_sha256=digest['sha256'])
                    _,rest=await self.wire('read',project_ref='p',work_ref=work,path=log,offset=first['content_next_offset'],expected_sha256=digest['sha256'])
                    self.assertEqual(first['content']+rest['content'],(root/log).read_text())
                    keys=['filter.fixture.clean','filter.fixture.required']
                    self.git('config',keys[0],str(helper));self.git('config',keys[1],'true')
                    if process:keys.append('filter.fixture.process');self.git('config',keys[-1],str(helper))
                    index=Path(self.git('rev-parse','--path-format=absolute','--git-path','index',root=root).decode().strip())
                    before=index.read_bytes();config=(self.root/'.git/config').read_bytes()
                    try:
                        _,read=await self.wire('read',project_ref='p',work_ref=work,path='selected')
                        self.assertEqual(read['content'],(text+b'UNSTAGED\n').decode())
                        candidate=await self.preview(work)
                        _,page=await self.wire('commit_prepare',project_ref='p',work_ref=work,candidate_id=candidate['candidate_id'],view='patch',limit=16384)
                        self.assertNotIn('UNSTAGED',page['text'])
                        real=capability._run_git;calls=[]
                        def observe(root,args,env,deadline,input_bytes=None):
                            calls.append(args)
                            return real(root,args,env,deadline,input_bytes)
                        with patch.object(capability,'_run_git',side_effect=observe):
                            wire,result=await self.wire('commit',project_ref='p',candidate_id=candidate['candidate_id'],message='SDK R3 exact staged objects')
                        self.assertEqual(result['status'],'committed',result)
                        self.assertFalse(marker.exists())
                        self.assertEqual([a for a in calls if a[0]=='mktree'],[['mktree','-z','--batch']])
                        self.assertFalse(any(a[0]=='write-tree' for a in calls))
                        self.assertEqual(self.git('show','HEAD:selected',root=root),text)
                        self.assertEqual(self.git('show','HEAD:binary',root=root),binary)
                        self.assertEqual(self.git('show','HEAD:.gitattributes',root=root),(root/'.gitattributes').read_bytes())
                        self.assertEqual(self.git('rev-parse','HEAD^{tree}',root=root).decode().strip(),candidate['tree'])
                        self.assertEqual(index.read_bytes(),before);self.assertEqual((self.root/'.git/config').read_bytes(),config)
                        self.assertEqual((root/'selected').read_bytes(),text+b'UNSTAGED\n')
                        self.assertEqual((root/'binary').read_bytes(),binary+b'\0UNSTAGED\xff')
                        with patch.object(capability,'_run_git',side_effect=AssertionError('no replay mutation')):
                            _,replayed=await self.wire('commit',project_ref='p',candidate_id=candidate['candidate_id'],message='SDK R3 exact staged objects')
                            self.assertEqual(result,replayed)
                        self.assertFalse(marker.exists())
                    finally:
                        for key in keys:self.git('config','--unset',key)
