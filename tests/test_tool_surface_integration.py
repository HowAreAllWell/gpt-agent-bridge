"""Combined registered MCP paths; fixture Git only, no model or real Agent calls."""
import base64
import hashlib
import json
from pathlib import Path
import unittest
from unittest.mock import AsyncMock, patch
from jsonschema import Draft202012Validator
from mcp.types import CallToolRequestParams
from mcp.server.mcpserver.exceptions import ToolError

import fixed_git
from tests import test_file_observation as fixtures
import server
from tests import test_discovery_coverage as discovery
from tests.test_vnext_surface import TINY_PNG


class IntegratedEvidenceTests(unittest.IsolatedAsyncioTestCase):
    setUp = fixtures.FileObservationTests.setUp
    git = fixtures.FileObservationTests.git

    async def wire(self, name, **arguments):
        result = await server.mcp.call_tool(name, arguments)
        wire = json.loads(result.model_dump_json(by_alias=True))
        schema = next((t.output_schema for t in await server.mcp.list_tools()
                       if t.name == name and t.output_schema is not None), None)
        if schema is not None:
            Draft202012Validator(schema).validate(wire['structuredContent'])
            return wire, wire['structuredContent']
        # read no longer publishes an outputSchema: text keeps structuredContent,
        # native-image success is unstructured (image block plus metadata text).
        return wire, wire.get('structuredContent')

    async def test_state_revision_precise_edits_then_read(self):
        (self.root/'.principal').mkdir()
        (self.root/'MEMORY.md').write_text('fixture memory')
        (self.root/'.principal/project.json').write_text(json.dumps({
            'rules':['RULES.md'],'current_state':'STATE.md','memory':'MEMORY.md'}))
        (self.root/'RULES.md').write_text('fixture rules')
        raw='decision 甲\r\nnext: old\r\n'.encode()
        (self.root/'STATE.md').write_bytes(raw)
        _,read=await self.wire('read',project_ref='p',path='STATE.md')
        _,state=await self.wire('current_state_update',project_ref='p',
            expected_revision='sha256:'+read['file_sha256'],
            edits=[{'old_text':'next: old','new_text':'next: new'}])
        self.assertTrue(state['ok'],state)
        _,after=await self.wire('read',project_ref='p',path='STATE.md')
        self.assertEqual(after['content'],'decision 甲\r\nnext: new\r\n')
        self.assertEqual(after['file_sha256'],hashlib.sha256((self.root/'STATE.md').read_bytes()).hexdigest())

    async def test_directory_untracked_read_inspect_and_image_on_frozen_checkout(self):
        for root,work_ref in [(self.root,None),(self.link,'w')]:
            tag='main' if work_ref is None else 'linked'
            (root/'logs').mkdir()
            filename='logs/new \n字.log'
            body='unique_'+tag+'_body'
            (root/filename).write_text('first\n'+body+'\n')
            (root/'binary.dat').write_bytes(b'\0\xff\n')
            (root/'image.png').write_bytes(TINY_PNG)
            (root/'.gitignore').write_text('ignored.log\n')
            (root/'ignored.log').write_text(body)
            _,listing=await self.wire('list_entries',project_ref='p',path='logs',work_ref=work_ref)
            self.assertEqual(listing['entries'][0]['path'],filename)
            _,default=await self.wire('search',project_ref='p',query=body,work_ref=work_ref)
            self.assertEqual(default['match_count'],0)
            _,search=await self.wire('search',project_ref='p',query=body,include_untracked=True,work_ref=work_ref)
            self.assertEqual(search['total_matches'],1)
            self.assertEqual(search['coverage']['untracked_files'],'included_nonignored')
            wire,read=await self.wire('read',project_ref='p',work_ref=work_ref,**search['matches'][0]['read_locator'])
            self.assertEqual(read['content'],body+'\n')
            self.assertEqual(json.dumps(wire,ensure_ascii=False).count(body),1)
            _,matched=await self.wire('read',project_ref='p',path=filename,work_ref=work_ref,
                                     expected_sha256=read['file_sha256'])
            self.assertTrue(matched['ok'])
            _,binary=await self.wire('inspect_file',project_ref='p',path='binary.dat',work_ref=work_ref)
            self.assertEqual(binary['sha256'],hashlib.sha256(b'\0\xff\n').hexdigest())
            self.assertNotIn('content',binary)
            wire,image=await self.wire('read',project_ref='p',path='image.png',work_ref=work_ref)
            blocks=[b for b in wire['content'] if b['type']=='image']
            self.assertEqual(len(blocks),1)
            self.assertEqual(base64.b64decode(blocks[0]['data']),TINY_PNG)
            (root/filename).write_text('changed')
            _,changed=await self.wire('read',project_ref='p',path=filename,work_ref=work_ref,
                                     expected_sha256=read['file_sha256'])
            self.assertEqual(changed['error_type'],'ReadVersionChanged')
            self.assertNotIn('content',changed)

    async def test_all_registered_extra_parameters_rejected_before_function(self):
        descriptors=await server.mcp.list_tools()
        self.assertEqual(len(descriptors),21)
        for descriptor in descriptors:
            tool=server.mcp._tool_manager.get_tool(descriptor.name)
            arguments={name: (['echo'] if name=='argv' else 'synthetic')
                       for name in descriptor.input_schema.get('required',[])}
            arguments['unexpected_selector']='must-not-default-or-execute'
            with self.subTest(tool=descriptor.name), patch.object(tool,'fn',AsyncMock()) as body:
                self.assertFalse(descriptor.input_schema['additionalProperties'])
                with self.assertRaises(ToolError):
                    await server.mcp.call_tool(descriptor.name,arguments)
                error=await server.mcp._handle_call_tool(
                    None,CallToolRequestParams(name=descriptor.name,arguments=arguments))
                wire=json.loads(error.model_dump_json(by_alias=True))
                self.assertTrue(wire['isError'])
                self.assertIsNone(wire['structuredContent'])
                self.assertIn('unexpected_selector',wire['content'][0]['text'])
                body.assert_not_awaited()

    async def test_opt_in_filter_guard_and_stream_failure_keep_unknown(self):
        (self.root/'log').write_text('needle\n')
        self.git('config','filter.fixture.clean','false')
        _,result=await self.wire('search',project_ref='p',query='needle',include_untracked=True)
        self.assertEqual(result['error_type'],'GitObservationUnsupported')
        self.assertNotIn('matches',result)
        self.git('config','--unset','filter.fixture.clean')
        import search_observation
        with patch.object(search_observation,'MAX_STDOUT',1):
            _,result=await self.wire('search',project_ref='p',query='needle',include_untracked=True)
        self.assertEqual(result['error_type'],'SearchObservationTooLarge')
        self.assertNotIn('matches',result)

    async def test_partial_clone_missing_blob_cannot_fetch_even_file_protocol(self):
        (self.root/'tracked').write_text('original\n')
        self.git('add','tracked')
        self.git('commit','-m','fixture')
        oid=self.git('rev-parse','HEAD:tracked').decode().strip()
        obj=self.root/'.git/objects'/oid[:2]/oid[2:]
        obj.rename(self.area/'saved-object')
        self.git('config','remote.origin.url',self.outside.as_uri())
        self.git('config','remote.origin.promisor','true')
        self.git('config','extensions.partialClone','origin')
        self.git('config','remote.origin.partialclonefilter','blob:none')
        # Even repo-specific allow and inherited allowlist cannot override fixed policy.
        self.git('config','protocol.file.allow','always')
        (self.root/'tracked').write_text('changed\n')
        import subprocess
        actual = subprocess.Popen
        with patch.object(subprocess, 'Popen', wraps=actual) as spawned, patch.dict('os.environ',{'GIT_ALLOW_PROTOCOL':'file'}):
            rc,raw,err=fixed_git.observe(self.root,['diff','--','tracked'])
        self.assertNotEqual(rc,0)
        self.assertTrue(b"transport 'file' not allowed" in err or b"lazy fetching disabled" in err,err)
        self.assertTrue(all(call.kwargs["env"]["GIT_ALLOW_PROTOCOL"] == "" for call in spawned.call_args_list))
        self.assertFalse(obj.exists())


class BootstrapThreeTreesTests(unittest.IsolatedAsyncioTestCase):
    setUp = discovery.DiscoveryCoverageTests.setUp
    agent = discovery.DiscoveryCoverageTests.agent

    async def test_first_bootstrap_and_explicit_context_share_three_checkouts(self):
        third=Path(self.temp.name)/'third'
        import subprocess
        subprocess.run(['git','-c','core.hooksPath=/dev/null','worktree','add','-b','third',str(third)],
                       cwd=self.root,check=True,capture_output=True)
        roots=[self.root,self.linked,third]
        self.agents=[self.agent(root,i+1) for i,root in enumerate(roots)]
        with patch.object(server,'ROOT',self.root),patch.object(server,'HERDR',self.backend):
            first=(await server.mcp.call_tool('bridge_overview',{})).structured_content
            explicit=(await server.mcp.call_tool('context',{'project_ref':'p'})).structured_content
        self.assertEqual(len(first['agents']),3)
        self.assertEqual([a['checkout'] for a in first['agents']],[a['checkout'] for a in explicit['agents']])
        for row,root in zip(first['agents'],roots):
            self.assertEqual(row['checkout']['root'],str(root))
            self.assertEqual(row['checkout']['status'],'observed')
            self.assertEqual(len(row['checkout']['head']),40)
        self.assertTrue({a['handle'] for a in first['agents']}.isdisjoint(
            {a['handle'] for a in explicit['agents']}))
