"""Real isolated repositories exercise the new observations through existing authority."""
import asyncio
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import threading
import unittest
from unittest.mock import AsyncMock, patch

os.environ.setdefault('BRIDGE_PATH_TOKEN', 'synthetic-file-observation-test-token-0123456789')
import server
import file_observation as fo
from evidence_target import EvidenceCheckout
from workspace_context import WorkspaceRegistry, WorkspaceRegistryStore


class FileObservationTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.area = Path(self.temp.name)
        self.root = self.area/'root'; self.root.mkdir()
        self.link = self.area/'linked'
        self.outside = self.area/'other'; self.outside.mkdir()
        self.git('init', '-b', 'main')
        self.git('commit', '--allow-empty', '-m', 'synthetic fixture')
        self.git('worktree', 'add', '-b', 'linked', str(self.link))
        self.registry = WorkspaceRegistry(self.root, json.dumps({'p': str(self.root)}),
            store=WorkspaceRegistryStore(self.area/'registry.json'))
        frozen = EvidenceCheckout.capture(self.registry.resolve('p'), str(self.link))
        for name,value in [('_WORKSPACE_REGISTRY',self.registry),('_RESULT_INBOX',{}),('_WORK_REGISTRY',{'w':{
            'project_ref':'p','workspace_root':str(self.root),'state':'agent_turn_settled',
            'execution_identity':'bound','evidence_checkout':frozen}})]:
            p=patch.object(server,name,value); p.start(); self.addCleanup(p.stop)
        p=patch.object(server.HerdrBackend,'_call',AsyncMock(side_effect=AssertionError('no host I/O')))
        p.start(); self.addCleanup(p.stop)
        self.service=fo.FileObservation(server._resolve_evidence_target,server._access_gate)

    def git(self,*args,root=None):
        return subprocess.check_output(['git','--no-optional-locks','-c','core.hooksPath=/dev/null',
            '-c','user.name=Synthetic Fixture','-c','user.email=fixture@example.invalid',
            '-c','commit.gpgsign=false',*args],cwd=root or self.root,stderr=subprocess.PIPE)

    def unchanged_index(self):
        return [hashlib.sha256(Path(self.git('rev-parse','--path-format=absolute','--git-path','index',root=r).decode().strip()).read_bytes()).hexdigest()
                if Path(self.git('rev-parse','--path-format=absolute','--git-path','index',root=r).decode().strip()).exists() else None for r in (self.root,self.link)]

    def good(self,result):
        self.assertTrue(result['ok'],result)
        self.assertLessEqual(fo.json_size(result),fo.MAX_JSON_BYTES)
        self.assertFalse(result['provenance']['atomic_snapshot'])
        self.assertNotIn('content',result)
        return result

    def bad(self,result,kind=None):
        self.assertFalse(result['ok'],result)
        if kind: self.assertEqual(result['error_type'],kind)
        for field in ('sha256','entries','matches','content','coverage'):
            self.assertNotIn(field,result)
        self.assertLess(fo.json_size(result),1024)

    async def test_exact_pages_root_linked_read_and_diff(self):
        names=[' space ', ' \t\n ', 'quote"', 'tab\t', 'line\nend', '字😀', 'literal -> end']
        baseline=self.unchanged_index()
        for root,work in [(self.root,None),(self.link,'w')]:
            for name in names: (root/name).write_text(root.name+'\n'+name)
            (root/'nested').mkdir(); (root/'nested/hidden').write_text('not a direct entry')
            entries=[]; offset=0
            while True:
                page=self.good(await self.service.list_entries('p',work_ref=work,offset=offset,limit=3))
                self.assertEqual(page['provenance']['execution_target'],str(root))
                self.assertEqual(page['coverage']['total_entries'],8)
                entries.extend(page['entries']); offset=page['pagination']['next_offset']
                if offset is None: break
            self.assertEqual({e['name'] for e in entries},set(names+['nested']))
            self.assertFalse(any('hidden' in e['path'] for e in entries))
            for e in entries:
                if e['type']=='file':
                    read=await server.read('p',e['path'],work_ref=work)
                    self.assertTrue(read['ok'],read)
                    self.assertEqual(read['content'],(root/e['name']).read_text())
                    meta=self.good(await self.service.inspect_file('p',e['path'],work_ref=work))
                    self.assertEqual(meta['sha256'],read['file_sha256'])
            (root/'plain').write_text('artifact\n')
            diff=await server.diff('p',path='plain',view='patch',work_ref=work)
            self.assertTrue(diff['ok'],diff); self.assertIn('+artifact',diff['patch'])
        self.assertEqual(self.unchanged_index(),baseline)

    async def test_binary_23_mib_and_exact_limit_streaming(self):
        path=self.link/'binary'; block=b'\0binary\xff'+b'x'*65528
        digest=hashlib.sha256()
        with path.open('wb') as f:
            for _ in range(368): f.write(block); digest.update(block)
        path.chmod(0o640)
        real=fo._read_chunk; reads=[]
        def bounded(fd,n): reads.append(n); return real(fd,n)
        with patch.object(fo,'_read_chunk',side_effect=bounded):
            result=self.good(await self.service.inspect_file('p','binary',work_ref='w'))
        self.assertEqual(result['sha256'],digest.hexdigest())
        self.assertEqual(result['byte_size'],23*1024*1024)
        self.assertEqual(result['mode'],'0640'); self.assertLessEqual(max(reads),65536)
        self.assertGreater(len(reads),300)
        small=self.root/'exact'; small.write_bytes(b'\0abc')
        with patch.object(fo,'MAX_FILE_BYTES',4):
            exact=self.good(await self.service.inspect_file('p','exact'))
            self.assertEqual(exact['sha256'],hashlib.sha256(b'\0abc').hexdigest())
            small.write_bytes(b'12345')
            with patch.object(fo,'_read_chunk',side_effect=AssertionError('oversize must not read')):
                self.bad(await self.service.inspect_file('p','exact'),'FileTooLarge')
        huge=self.root/'huge'
        with huge.open('wb') as f: f.truncate(64*1024*1024+1)
        self.bad(await self.service.inspect_file('p','huge'),'FileTooLarge')
        with huge.open('wb') as f: f.truncate(64*1024*1024)
        expected=hashlib.sha256()
        for _ in range(1024): expected.update(b'\0'*65536)
        maximum=self.good(await self.service.inspect_file('p','huge'))
        self.assertEqual(maximum['byte_size'],64*1024*1024)
        self.assertEqual(maximum['sha256'],expected.hexdigest())

    async def test_scan_and_json_budgets_never_truncate_names(self):
        for i in range(120): (self.root/(f'{i:03}'+('😀"'*45))).touch()
        with patch.object(fo,'MAX_JSON_BYTES',12000):
            offset=0; names=[]
            while True:
                page=self.good(await self.service.list_entries('p',limit=100,offset=offset))
                self.assertLess(len(page['entries']),100)
                names.extend(e['name'] for e in page['entries'])
                offset=page['pagination']['next_offset']
                if offset is None: break
            self.assertEqual(set(names),{p.name for p in self.root.iterdir() if p.name!='.git'})
            self.assertEqual(len(names),120)
        with patch.object(fo,'MAX_ENTRIES',5):
            self.bad(await self.service.list_entries('p'),'DirectoryTooLarge')
        with patch.object(fo,'MAX_NAMES_BYTES',20):
            self.bad(await self.service.list_entries('p'),'DirectoryTooLarge')
        with patch.object(fo,'MAX_JSON_BYTES',8500):
            self.bad(await self.service.list_entries('p'),'ResponseTooLarge')

    async def test_invalid_inputs_before_resolution_and_no_side_effects(self):
        resolver=unittest.mock.Mock(side_effect=AssertionError('invalid input must not resolve'))
        service=fo.FileObservation(resolver,server._access_gate)
        cases=[{'offset':True},{'offset':-1},{'offset':4097},{'limit':0},{'limit':101},{'limit':True},
               {'path':'../other'},{'path':'/tmp'},{'path':'.git/config'},{'path':'nested/.git'},
               {'path':'bad\0name'},{'path':'x'*4097},{'path':'\udcff'},{'path':None}]
        for args in cases:
            with self.subTest(args=args): self.bad(await service.list_entries('p',**args))
        for path in ('','.','..','/tmp','.git/config','\0'):
            self.bad(await service.inspect_file('p',path))
        self.bad(await service.list_entries('',path='.'))
        self.bad(await service.inspect_file('p','file',work_ref=[]))
        resolver.assert_not_called()

    async def test_links_fifo_directories_missing_and_escape(self):
        (self.root/'inside').write_text('inside')
        (self.outside/'secret').write_text('outside sentinel')
        (self.root/'internal-link').symlink_to('inside')
        (self.root/'escape').symlink_to(self.outside,target_is_directory=True)
        (self.root/'broken').symlink_to('missing')
        os.mkfifo(self.root/'fifo')
        page=self.good(await self.service.list_entries('p'))
        kinds={e['name']:e['type'] for e in page['entries']}
        self.assertEqual(kinds['internal-link'],'link'); self.assertEqual(kinds['escape'],'link')
        self.assertEqual(kinds['fifo'],'special')
        for name in ('internal-link','escape','broken'):
            self.bad(await self.service.inspect_file('p',name),'SymlinkRejected')
        self.bad(await self.service.inspect_file('p','fifo'),'NotARegularFile')
        self.bad(await self.service.list_entries('p','escape'),'SymlinkRejected')
        self.bad(await self.service.inspect_file('p','escape/secret'),'SymlinkRejected')
        self.bad(await self.service.inspect_file('p','missing'),'PathUnavailable')
        self.assertEqual((await server.read('p','internal-link'))['content'],'inside')
        self.assertFalse((await server.read('p','escape/secret'))['ok'])

    async def test_mutation_during_hash_and_path_replacement(self):
        file=self.root/'data'; file.write_bytes(b'a'*100000)
        real=fo._read_chunk
        for mode in ('content','file','directory'):
            parent=self.root/'dir'; parent.mkdir(exist_ok=True)
            file=parent/'data'; file.write_bytes(b'a'*100000)
            changed=False
            def mutate(fd,n):
                nonlocal changed
                chunk=real(fd,n)
                if not changed:
                    changed=True
                    if mode=='content':
                        with file.open('r+b') as out: out.write(b'b')
                    elif mode=='file':
                        replacement=parent/'new'; replacement.write_bytes(b'z'*100000); replacement.replace(file)
                    else:
                        parent.rename(self.root/'saved')
                        parent.symlink_to(self.outside,target_is_directory=True)
                return chunk
            with patch.object(fo,'_read_chunk',side_effect=mutate):
                self.bad(await self.service.inspect_file('p','dir/data'))
            if mode=='directory':
                parent.unlink(); (self.root/'saved').rename(parent)
        # Detect directory mutation during enumeration instead of claiming complete coverage.
        real_scan=fo.os.scandir
        class ChangingScan:
            def __init__(self,fd): self.it=real_scan(fd)
            def __enter__(self): return self
            def __exit__(self,*a): self.it.close()
            def __iter__(self): return self
            def __next__(self):
                entry=next(self.it)
                (self_root/'new-during-scan').touch()
                return entry
        self_root=self.root
        with patch.object(fo.os,'scandir',ChangingScan):
            self.bad(await self.service.list_entries('p'),'DirectoryChanged')

    async def test_frozen_work_and_registered_root_replacement(self):
        (self.link/'work-only').write_text('work')
        self.assertEqual(self.good(await self.service.inspect_file('p','work-only',work_ref='w'))['byte_size'],4)
        self.bad(await self.service.inspect_file('p','work-only'))
        self.bad(await self.service.inspect_file('p','work-only',work_ref='missing'))
        self.link.rename(self.area/'saved-link'); self.link.mkdir()
        self.bad(await self.service.list_entries('p',work_ref='w'))
        self.root.rename(self.area/'saved-root'); self.root.mkdir()
        self.bad(await self.service.list_entries('p'))

    async def test_post_admission_target_change_and_timeout(self):
        target=server._resolve_evidence_target('p')
        resolver=unittest.mock.Mock(side_effect=[target,target,{'ok':False,'error_type':'Changed'}])
        service=fo.FileObservation(resolver,server._access_gate)
        self.bad(await service.list_entries('p'),'TargetChanged')
        (self.root/'data').write_text('test')
        with patch.object(fo,'OBSERVATION_SECONDS',-1):
            self.bad(await self.service.inspect_file('p','data'),'ObservationTimedOut')

    async def test_cancel_does_not_release_gate_before_worker_finishes(self):
        started=threading.Event(); finish=threading.Event(); released=[]
        class Lease:
            async def release(self): released.append(True)
        class Gate:
            async def acquire(self,mode): return Lease()
        def slow(*args): started.set(); finish.wait(2); return {'ok':True}
        service=fo.FileObservation(server._resolve_evidence_target,lambda root:Gate())
        with patch.object(fo,'_list_entries',slow):
            task=asyncio.create_task(service.list_entries('p'))
            await asyncio.to_thread(started.wait,2)
            task.cancel(); await asyncio.sleep(.02)
            task.cancel(); await asyncio.sleep(.02)
            self.assertFalse(released)
            finish.set()
            with self.assertRaises(asyncio.CancelledError): await task
        self.assertEqual(released,[True])

    async def test_mcp_registration_has_two_direct_interfaces(self):
        from mcp.server import MCPServer
        mcp=MCPServer('synthetic-file-observation')
        fo.register_file_observation(mcp,server._resolve_evidence_target,server._access_gate)
        tools=await mcp.list_tools()
        self.assertEqual({t.name for t in tools},{'list_entries','inspect_file'})
        for t in tools:
            self.assertTrue(t.annotations.model_dump(by_alias=True)['readOnlyHint'])
            self.assertNotIn('action',t.input_schema['properties'])
            self.assertNotIn('argv',t.input_schema['properties'])
        (self.root/'artifact').write_bytes(b'\0binary')
        for tool,args in [('list_entries',{}),('inspect_file',{'path':'artifact'})]:
            result=await mcp.call_tool(tool,{'project_ref':'p',**args})
            wire=json.loads(result.model_dump_json(by_alias=True))
            self.assertFalse(wire['isError'])
            data=json.loads(wire['content'][0]['text'])
            self.good(data)
