"""Original-byte attachments over real MCP memory transport; no live host acceptance."""
import base64
from contextlib import asynccontextmanager
from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path
import unittest
from unittest.mock import AsyncMock, patch

import anyio
from mcp import ClientSession
from mcp.shared.exceptions import MCPError
from mcp.shared.memory import create_client_server_memory_streams
from mcp.server.mcpserver.exceptions import ResourceError, ResourceNotFoundError
from mcp.types import BlobResourceContents, ResourceLink, TextContent

from gpt_agent_bridge.evidence_target import EvidenceCheckout
from gpt_agent_bridge import file_attachment as attachment
from gpt_agent_bridge import file_observation as observation
from gpt_agent_bridge import widget_watcher as watcher
os.environ.setdefault('BRIDGE_PATH_TOKEN', 'test-token-abcdefghijklmnopqrstuvwxyz-012345')
from gpt_agent_bridge import server
from tests import test_read_contract as fixtures


@asynccontextmanager
async def memory_client(responses, *, record_resources=True):
    lowlevel = server.mcp._lowlevel_server

    class RecordingSend:
        def __init__(self, stream): self.stream = stream
        def __getattr__(self, name): return getattr(self.stream, name)
        async def __aenter__(self): return self
        async def __aexit__(self, *args): return await self.stream.__aexit__(*args)
        async def send(self, message):
            payload = getattr(message.message, 'root', message.message)
            wire = payload.model_dump(mode='json', by_alias=True, exclude_none=True)
            if record_resources or 'contents' not in wire.get('result', {}):
                responses.append(wire)
            await self.stream.send(message)

    async with create_client_server_memory_streams() as (client_streams, server_streams):
        async with anyio.create_task_group() as group:
            group.start_soon(lowlevel.run, server_streams[0], RecordingSend(server_streams[1]),
                             lowlevel.create_initialization_options())
            async with ClientSession(*client_streams) as client:
                await client.initialize()
                yield client
            group.cancel_scope.cancel()


class FileAttachmentTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        fixtures.ReadContractTests.setUp(self)
        self.now = 100.0
        self.store = attachment.PendingAttachments(clock=lambda: self.now)
        patch.object(server._file_attachment, 'store', self.store).start()

    async def wire(self, path='probe.docx', **args):
        result = await server.mcp.call_tool('prepare_file_attachment', {'project_ref': 'p', 'path': path, **args})
        wire = result.model_dump(mode='json', by_alias=True, exclude_none=True)
        self.assertNotIn('structuredContent', wire)
        self.assertNotIn('_meta', wire)
        texts = [c['text'] for c in wire['content'] if c['type'] == 'text']
        self.assertLessEqual(len(texts), 1)
        return wire, json.loads(texts[0]) if texts else None

    def assert_private(self, value):
        serialized = json.dumps(value, ensure_ascii=False)
        for private in (str(self.root), str(self.linked), str(self.temp.name), 'private-dir/'):
            self.assertNotIn(private, serialized)

    async def roundtrip(self, *, work=False, byte_size=417431):
        # Intentionally invalid DOCX, never parsed. Synthetic temp fixture only.
        pattern = b'ORIGINAL-BODY-SENTINEL\0\xff\r\n'
        body = (pattern * ((byte_size + len(pattern) - 1) // len(pattern)))[:byte_size]
        target = self.linked if work else self.root
        name = '原始 probe.bin' if work else 'probe.docx'
        if byte_size != 417431:
            name = 'five-mib.bin'
        (target / 'private-dir').mkdir()
        (target / 'private-dir' / name).write_bytes(body)
        args = {'project_ref': 'p', 'path': 'private-dir/' + name,
                'expected_sha256': hashlib.sha256(body).hexdigest()}
        if work:
            server._WORK_REGISTRY['attachment-work'] = {'project_ref': 'p', 'workspace_root': str(self.root),
                'execution_identity': 'bound',
                'evidence_checkout': EvidenceCheckout.capture(self.project, str(self.linked))}
            args['work_ref'] = 'attachment-work'
            (self.root / 'private-dir').mkdir()
            (self.root / 'private-dir' / name).write_bytes(b'wrong project bytes')
        responses = []
        async with memory_client(responses) as client:
            tools = await client.list_tools()
            tool = next(t for t in tools.tools if t.name == 'prepare_file_attachment')
            descriptor = tool.model_dump(by_alias=True, exclude_none=True)
            self.assertNotIn('outputSchema', descriptor)
            self.assertNotIn('_meta', descriptor)
            self.assertEqual(set(tool.input_schema['properties']),
                             {'project_ref', 'path', 'work_ref', 'expected_sha256'})
            self.assertFalse(tool.input_schema['additionalProperties'])
            self.assertTrue(tool.annotations.read_only_hint)
            self.assertFalse(tool.annotations.idempotent_hint)
            templates = await client.list_resource_templates()
            template = next(t for t in templates.resource_templates
                            if t.uri_template == attachment.ATTACH_RESOURCE_TEMPLATE)
            self.assertEqual(template.mime_type, 'application/octet-stream')
            # The only static resource is the shared continuation widget.
            self.assertEqual(
                [(str(r.uri), r.mime_type)
                 for r in (await client.list_resources()).resources],
                [(watcher.WIDGET_RESOURCE_URI, 'text/html;profile=mcp-app')])
            result = await client.call_tool('prepare_file_attachment', args)
            self.assertFalse(result.is_error)
            self.assertIsInstance(result.content[0], ResourceLink)
            self.assertEqual([type(c) for c in result.content], [ResourceLink])
            link = result.content[0]
            self.assertEqual(link.name, name)
            self.assertEqual(link.size, byte_size)
            mime = 'application/octet-stream' if work or byte_size != 417431 else (
                'application/vnd.openxmlformats-officedocument.wordprocessingml.document')
            self.assertEqual(link.mime_type, mime)
            self.assertRegex(link.uri, r'^bridge://attach/[A-Za-z0-9_-]{43}$')
            self.assertLess(len(link.description), 100)
            resource = await client.read_resource(link.uri)
            self.assertEqual(len(resource.contents), 1)
            self.assertIsInstance(resource.contents[0], BlobResourceContents)
            self.assertEqual(base64.b64decode(resource.contents[0].blob, validate=True), body)
            self.assertEqual(resource.contents[0].uri, link.uri)
            self.assertEqual(hashlib.sha256(base64.b64decode(resource.contents[0].blob)).hexdigest(),
                             args['expected_sha256'])
            self.assertEqual(resource.contents[0].mime_type, mime)
            # Repeat fetch is allowed without renewal, and still uses original bytes.
            again = await client.read_resource(link.uri)
            self.assertEqual(again, resource)
        # Assert raw server messages, before client parsing/normalization.
        raw_catalog = next(r['result']['tools'] for r in responses if 'tools' in r.get('result', {}))
        self.assertNotIn('outputSchema', next(t for t in raw_catalog if t['name'] == 'prepare_file_attachment'))
        call_wire = next(r['result'] for r in responses if 'content' in r.get('result', {}))
        self.assertNotIn('structuredContent', call_wire)
        self.assertNotIn('_meta', call_wire)
        self.assertEqual([b['type'] for b in call_wire['content']], ['resource_link'])
        self.assertLess(len(json.dumps(call_wire)), 2048)
        self.assert_private(call_wire)
        for forbidden in ('ORIGINAL-BODY-SENTINEL', base64.b64encode(body).decode(), 'base64', 'blob', 'data'):
            self.assertNotIn(forbidden, json.dumps(call_wire))
        for response in responses:
            if 'contents' in response.get('result', {}):
                self.assert_private(response)
                self.assertEqual(set(response['result']['contents'][0]), {'uri', 'mimeType', 'blob'})
        token = link.uri.rsplit('/', 1)[-1]
        entry = self.store.get(token)
        self.assertEqual(entry.name, name)
        self.assertEqual(entry.mime_type, mime)
        self.assertEqual(entry.path, args['path'])
        self.assertEqual(entry.work_ref, args.get('work_ref'))
        self.assertFalse(any(isinstance(v, bytes) for v in vars(entry).values()))

    async def test_memory_wire_resource_link_original_bytes(self):
        await self.roundtrip()

    async def test_work_ref_memory_roundtrip_uses_frozen_checkout(self):
        await self.roundtrip(work=True)

    async def test_five_mib_binary_memory_roundtrip_keeps_tool_content_compact(self):
        await self.roundtrip(byte_size=5 * 1024 * 1024)

    async def test_retired_tool_and_resource_namespace_fail_closed_on_memory_wire(self):
        (self.root / 'probe.docx').write_bytes(b'original')
        responses = []
        async with memory_client(responses) as client:
            names = {tool.name for tool in (await client.list_tools()).tools}
            self.assertIn('prepare_file_attachment', names)
            self.assertNotIn('export_file', names)
            self.assertIsNone(server.mcp._tool_manager.get_tool('export_file'))
            with patch.object(server._file_attachment, 'resolve_target') as resolve:
                retired = await client.call_tool('export_file', {'project_ref': 'p', 'path': 'probe.docx'})
                self.assertTrue(retired.is_error)
                self.assertIn('Unknown tool', retired.content[0].text)
                resolve.assert_not_called()
            self.assertEqual(len(self.store.entries), 0)
            prepared = await client.call_tool('prepare_file_attachment', {'project_ref': 'p', 'path': 'probe.docx'})
            token = prepared.content[0].uri.rsplit('/', 1)[-1]
            templates = (await client.list_resource_templates()).resource_templates
            self.assertFalse(any(t.uri_template.startswith('bridge://export/') for t in templates))
            with self.assertRaises(MCPError) as failure:
                await client.read_resource('bridge://export/' + token)
            self.assertEqual(failure.exception.code, -32602)
        for response in responses:
            self.assert_private(response)
            self.assertNotIn('blob', json.dumps(response))

    async def test_registration_hash_and_no_capability_on_error(self):
        (self.root / 'probe.docx').write_bytes(b'original')
        for args, expected in [({'work_ref': 'missing'}, 'WorkRefUnavailable'),
                                ({'expected_sha256': '0' * 64}, 'ReadVersionChanged'),
                                ({'expected_sha256': 'ABC'}, 'InvalidExpectedSHA256')]:
            wire, meta = await self.wire(**args)
            self.assertTrue(wire['isError'])
            self.assertEqual(meta['error_type'], expected)
            self.assertEqual([b['type'] for b in wire['content']], ['text'])
            self.assert_private(wire)
        result = await server._file_attachment.prepare_file_attachment('unregistered', 'probe.docx')
        self.assertTrue(result.is_error)
        self.assertIsNone(result.structured_content)
        self.assertEqual(len(self.store.entries), 0)
        # Even a resolver error that includes a local path must be sanitized.
        with patch.object(server._file_attachment, 'resolve_target', return_value={
                'ok': False, 'error_type': 'TargetUnavailable', 'error': str(self.root)}):
            wire, _ = await self.wire()
            self.assert_private(wire)

    async def test_paths_specials_and_part_boundary_with_bounded_reads(self):
        with (self.root / 'probe.docx').open('wb') as output:
            output.truncate(attachment.MAX_ATTACH_PART_BYTES)
        with patch.object(observation, '_read_chunk', wraps=observation._read_chunk) as read:
            wire, meta = await self.wire()
            self.assertFalse(wire['isError'])
            self.assertIsNone(meta)
            self.assertEqual([c['type'] for c in wire['content']], ['resource_link'])
            self.assertEqual(wire['content'][0]['size'], attachment.MAX_ATTACH_PART_BYTES)
            token = wire['content'][0]['uri'].rsplit('/', 1)[-1]
            self.assertEqual(len(await server._file_attachment.read_attachment(token)), attachment.MAX_ATTACH_PART_BYTES)
            self.assertTrue(read.call_count > 2)
            self.assertTrue(all(0 < c.args[1] <= observation.CHUNK_BYTES for c in read.call_args_list))
        (self.root / 'link').symlink_to('probe.docx')
        (self.root / 'linked-dir').symlink_to(self.linked, target_is_directory=True)
        os.mkfifo(self.root / 'fifo')
        initial = len(self.store.entries)
        for path, expected in [('../probe.docx', 'InvalidPath'),
            ('/etc/passwd', 'InvalidPath'), ('.git/config', 'InvalidPath'), ('a\0b', 'InvalidPath'),
            ('x' * 4097, 'InvalidPath'), ('link', 'SymlinkRejected'),
            ('linked-dir/file', 'SymlinkRejected'), ('fifo', 'NotARegularFile'), ('.', 'InvalidPath'),
            ('private-dir/missing', 'PathUnavailable')]:
            with self.subTest(path=path), patch.object(observation, '_read_chunk') as read:
                wire, meta = await self.wire(path)
                self.assertEqual(meta['error_type'], expected)
                self.assert_private(wire)
                read.assert_not_called()
        self.assertEqual(len(self.store.entries), initial)

    async def test_resolver_exceptions_do_not_leak_local_paths_on_wire(self):
        (self.root / 'probe.docx').write_bytes(b'original')
        responses = []
        async with memory_client(responses) as client:
            prepared = await client.call_tool('prepare_file_attachment', {'project_ref': 'p', 'path': 'probe.docx'})
            with patch.object(server._file_attachment, 'resolve_target', side_effect=RuntimeError(str(self.root))):
                failed = await client.call_tool('prepare_file_attachment', {'project_ref': 'p', 'path': 'probe.docx'})
                self.assertTrue(failed.is_error)
                self.assertEqual(json.loads(failed.content[0].text)['error_type'], 'AttachmentPreparationFailed')
                with self.assertRaises(MCPError): await client.read_resource(prepared.content[0].uri)
        for wire in responses:
            self.assert_private(wire)
            if 'error' in wire:
                self.assertEqual(wire['error']['code'], -32602)
            self.assertNotIn('blob', json.dumps(wire))
        self.assertEqual(len(self.store.entries), 1)

    async def test_extra_arguments_memory_rejected_before_prepare(self):
        responses = []
        async with memory_client(responses) as client:
            with patch.object(server._file_attachment, 'resolve_target') as resolve:
                failed = await client.call_tool('prepare_file_attachment', {'project_ref': 'p', 'path': 'probe.docx',
                                                               'unexpected_selector': 'forbidden'})
                resolve.assert_not_called()
                self.assertTrue(failed.is_error)
        self.assertEqual(len(self.store.entries), 0)
        call_wire = next(r['result'] for r in responses if 'content' in r.get('result', {}))
        self.assertEqual([b['type'] for b in call_wire['content']], ['text'])
        self.assertNotIn('structuredContent', call_wire)
        self.assertNotIn('_meta', call_wire)
        self.assert_private(call_wire)

    async def test_resource_adapter_defers_other_routes_to_sdk(self):
        context = object()
        with patch.object(server.MCPServer, 'read_resource', AsyncMock(return_value=['SDK fallback'])) as original:
            self.assertEqual(await server.mcp.read_resource('example://other', context), ['SDK fallback'])
            original.assert_awaited_once_with('example://other', context)

    async def test_noncanonical_attachment_uris_fail_closed_on_wire(self):
        (self.root / 'probe.docx').write_bytes(b'original')
        responses = []
        async with memory_client(responses) as client:
            result = await client.call_tool('prepare_file_attachment', {'project_ref': 'p', 'path': 'probe.docx'})
            uri = result.content[0].uri
            token = uri.rsplit('/', 1)[-1]
            encoded = attachment.ATTACH_RESOURCE_PREFIX + f'%{ord(token[0]):02X}' + token[1:]
            for invalid in (uri + '/', uri + '?x=1', encoded, attachment.ATTACH_RESOURCE_PREFIX):
                with self.subTest(uri=invalid), self.assertRaises(MCPError) as failure:
                    await client.read_resource(invalid)
                self.assertEqual(failure.exception.code, -32602)
        errors = [r for r in responses if 'error' in r]
        self.assertEqual(len(errors), 4)
        for wire in errors:
            self.assert_private(wire)
            self.assertNotIn('blob', json.dumps(wire))

    async def test_multiple_mime_hints_memory_match_links_and_original_bytes(self):
        responses = []
        async with memory_client(responses) as client:
            for name, mime in [('probe.txt', 'text/plain'), ('probe.pdf', 'application/pdf'),
                               ('probe.unknownsuffix', 'application/octet-stream')]:
                with self.subTest(name=name):
                    body = b'original bytes\0\xff\r\n'
                    (self.root / name).write_bytes(body)
                    result = await client.call_tool('prepare_file_attachment', {'project_ref': 'p', 'path': name})
                    link = result.content[0]
                    self.assertEqual(link.mime_type, mime)
                    read = await client.read_resource(link.uri)
                    self.assertIsInstance(read.contents[0], BlobResourceContents)
                    self.assertEqual(read.contents[0].mime_type, link.mime_type)
                    self.assertEqual(base64.b64decode(read.contents[0].blob, validate=True), body)
        for wire in responses:
            self.assert_private(wire)

    async def test_empty_original_bytes_and_fallback_mime(self):
        (self.root / 'empty.unknownsuffix').write_bytes(b'')
        wire, meta = await self.wire('empty.unknownsuffix')
        self.assertFalse(wire['isError'])
        self.assertIsNone(meta)
        self.assertEqual([c['type'] for c in wire['content']], ['resource_link'])
        link = wire['content'][0]
        self.assertEqual(link['size'], 0)
        self.assertEqual(link['mimeType'], 'application/octet-stream')
        self.assertEqual(await server._file_attachment.read_attachment(link['uri'].rsplit('/', 1)[-1]), b'')

    async def test_mutation_replacement_and_special_between_prepare_and_fetch(self):
        directory = self.root / 'private-dir'
        directory.mkdir()
        path = directory / 'probe.docx'
        responses = []
        async with memory_client(responses) as client:
            for race in ('rewrite_same_size', 'grow', 'replace', 'symlink', 'fifo', 'parent_replace'):
                with self.subTest(race=race):
                    if path.exists() or path.is_symlink(): path.unlink()
                    path.write_bytes(b'original')
                    result = await client.call_tool('prepare_file_attachment', {'project_ref': 'p', 'path': 'private-dir/probe.docx'})
                    uri = result.content[0].uri
                    if race == 'rewrite_same_size': path.write_bytes(b'changed!')
                    if race == 'grow': path.write_bytes(b'original extra')
                    if race == 'replace':
                        replacement = directory / 'replacement'
                        replacement.write_bytes(b'replaced')
                        replacement.replace(path)
                    if race in ('symlink', 'fifo'):
                        path.unlink()
                        if race == 'symlink': path.symlink_to('/etc/passwd')
                        else: os.mkfifo(path)
                    if race == 'parent_replace':
                        directory.rename(self.root / 'old-private-dir')
                        directory.mkdir()
                        path.write_bytes(b'replaced')
                    with self.assertRaises(MCPError) as failure:
                        await client.read_resource(uri)
                    self.assertNotIn(str(self.root), str(failure.exception))
                    self.assertNotIn('/etc/passwd', str(failure.exception))
        errors = [r for r in responses if 'error' in r]
        self.assertEqual(len(errors), 6)
        for wire in errors:
            self.assert_private(wire)
            self.assertEqual(wire['error']['code'], -32602)
            self.assertNotIn('blob', json.dumps(wire))
            self.assertNotIn('original', json.dumps(wire))

    async def test_during_observation_races_discard_link_or_bytes(self):
        original = observation._read_chunk
        for phase in ('prepare', 'fetch'):
            for race in ('rewrite', 'replace', 'parent_replace', 'grow'):
                directory = self.root / (phase + '-' + race)
                directory.mkdir()
                path = directory / 'probe.docx'
                path.write_bytes(b'original\0\xff')
                relative = directory.name + '/probe.docx'
                if phase == 'fetch':
                    wire, _ = await self.wire(relative)
                    token = wire['content'][0]['uri'].rsplit('/', 1)[-1]
                changed = False
                def read_and_change(fd, count):
                    nonlocal changed
                    chunk = original(fd, count)
                    if chunk and not changed:
                        changed = True
                        if race == 'rewrite': path.write_bytes(b'rewritten!')
                        if race == 'replace':
                            path.unlink()
                            path.symlink_to('/etc/passwd')
                        if race == 'parent_replace':
                            directory.rename(self.root / ('old-' + directory.name))
                            directory.mkdir()
                            path.write_bytes(b'replacement')
                        if race == 'grow':
                            with path.open('ab') as output: output.write(b'x' * 1024)
                    return chunk
                with self.subTest(phase=phase, race=race), patch.object(observation, '_read_chunk', read_and_change):
                    if phase == 'prepare':
                        before = len(self.store.entries)
                        wire, meta = await self.wire(relative)
                        self.assertIn(meta['error_type'], {'FileChanged', 'PathChanged'})
                        self.assertEqual(len(self.store.entries), before)
                        self.assertEqual(len(wire['content']), 1)
                    else:
                        with self.assertRaises(ResourceError):
                            await server._file_attachment.read_attachment(token)

    async def test_final_target_check_discards_link_or_bytes(self):
        (self.root / 'probe.docx').write_bytes(b'original')
        resolve = server._resolve_evidence_target
        for phase in ('prepare', 'fetch'):
            if phase == 'fetch':
                wire, _ = await self.wire()
                token = wire['content'][0]['uri'].rsplit('/', 1)[-1]
            calls = 0
            def changing(*args):
                nonlocal calls
                calls += 1
                if calls == 3: return {'ok': False, 'error_type': 'TargetChanged', 'error': str(self.root)}
                return resolve(*args)
            with patch.object(server._file_attachment, 'resolve_target', changing):
                if phase == 'prepare':
                    wire, meta = await self.wire()
                    self.assertEqual(meta['error_type'], 'TargetChanged')
                    self.assertEqual(len(self.store.entries), 0)
                    self.assert_private(wire)
                else:
                    with self.assertRaises(ResourceError):
                        await server._file_attachment.read_attachment(token)

    async def test_capability_binds_checkout_and_requires_retained_work(self):
        (self.root / 'probe.docx').write_bytes(b'same bytes')
        (self.linked / 'probe.docx').write_bytes(b'same bytes')
        wire, _ = await self.wire()
        token = wire['content'][0]['uri'].rsplit('/', 1)[-1]
        from gpt_agent_bridge.evidence_target import EvidenceTarget
        different = EvidenceTarget(self.project,
            EvidenceCheckout.capture(self.project, str(self.linked)).revalidate(self.project), None)
        with patch.object(server._file_attachment, 'resolve_target', return_value=different):
            with self.assertRaises(ResourceError):
                await server._file_attachment.read_attachment(token)
        server._WORK_REGISTRY['attachment-work'] = {'project_ref': 'p', 'workspace_root': str(self.root),
            'execution_identity': 'bound',
            'evidence_checkout': EvidenceCheckout.capture(self.project, str(self.linked))}
        wire, _ = await self.wire(work_ref='attachment-work')
        token = wire['content'][0]['uri'].rsplit('/', 1)[-1]
        del server._WORK_REGISTRY['attachment-work']
        with self.assertRaises(ResourceError):
            await server._file_attachment.read_attachment(token)

    async def test_prepared_size_is_checked_independently_of_hash(self):
        (self.root / 'probe.docx').write_bytes(b'original')
        wire, _ = await self.wire()
        token = wire['content'][0]['uri'].rsplit('/', 1)[-1]
        self.store.entries[token] = replace(self.store.get(token), byte_size=9)
        with self.assertRaises(ResourceError):
            await server._file_attachment.read_attachment(token)

    @unittest.skipUnless(os.environ.get('BRIDGE_MAINTAINER_SUITE') == '1',
                         'Full 129-attachment wire run requires BRIDGE_MAINTAINER_SUITE=1')
    async def test_over_128_attachments_remain_readable_until_expiry_and_restart(self):
        (self.root / 'probe.docx').write_bytes(b'original')
        responses = []
        async with memory_client(responses) as client:
            async def prepare():
                result = await client.call_tool('prepare_file_attachment', {'project_ref': 'p', 'path': 'probe.docx'})
                self.assertEqual([type(c) for c in result.content], [ResourceLink])
                return result.content[0].uri
            uris = [await prepare() for _ in range(129)]
            self.assertEqual(len(set(uris)), 129)
            self.assertEqual(len(self.store.entries), 129)
            await client.read_resource(uris[0])
            newest = await prepare()
            self.assertEqual(len(self.store.entries), 130)
            await client.read_resource(uris[0])
            with self.assertRaises(MCPError):
                await client.read_resource(attachment.ATTACH_RESOURCE_TEMPLATE.format(capability='unknown'))
            self.now += 899
            await client.read_resource(uris[1])
            self.now += 1
            with self.assertRaises(MCPError): await client.read_resource(uris[1])
            self.assertEqual(len(self.store.entries), 0)
            fresh = await prepare()
            old_store = server._file_attachment.store
            server._file_attachment.store = attachment.PendingAttachments(clock=lambda: self.now)
            try:
                with self.assertRaises(MCPError): await client.read_resource(fresh)
            finally:
                server._file_attachment.store = old_store
            self.assertNotEqual(newest, fresh)
        errors = [r for r in responses if 'error' in r]
        self.assertEqual(len(errors), 3)
        for wire in errors:
            self.assert_private(wire)
            self.assertEqual(wire['error']['code'], -32602)
            self.assertNotIn('blob', json.dumps(wire))

    async def test_metadata_capacity_boundary_remains_readable_until_expiry_and_restart(self):
        body = b'original'
        (self.root / 'probe.docx').write_bytes(body)
        responses = []
        async with memory_client(responses) as client:
            async def prepare():
                result = await client.call_tool('prepare_file_attachment', {'project_ref': 'p', 'path': 'probe.docx'})
                self.assertFalse(result.is_error)
                self.assertEqual([type(c) for c in result.content], [ResourceLink])
                self.assertEqual(result.content[0].size, len(body))
                return result.content[0].uri

            async def read(uri):
                result = await client.read_resource(uri)
                self.assertEqual(len(result.contents), 1)
                self.assertIsInstance(result.contents[0], BlobResourceContents)
                self.assertEqual(result.contents[0].uri, uri)
                self.assertEqual(base64.b64decode(result.contents[0].blob, validate=True), body)

            first = await prepare()
            entry = self.store.get(first.rsplit('/', 1)[-1])
            self.assertIsInstance(entry.file_binding, tuple)
            self.assertTrue(entry.file_binding)
            self.assertIsInstance(entry.parts, tuple)
            self.assertEqual(entry.parts, (attachment.FilePart(1, 0, len(body), hashlib.sha256(body).hexdigest()),))
            # Reuse a real, valid binding; issue only metadata in the same live store.
            binding = {key: value for key, value in vars(entry).items() if key != 'expires_at'}
            synthetic = []
            for _ in range(127):
                token, metadata = self.store.issue(**binding)
                self.assertEqual(metadata, entry)
                self.assertFalse(any(isinstance(value, bytes) for value in vars(metadata).values()))
                self.assertTrue(all(not any(isinstance(value, bytes) for value in vars(part).values())
                                    for part in metadata.parts))
                synthetic.append(attachment.ATTACH_RESOURCE_TEMPLATE.format(capability=token))
            self.assertEqual(len(set([first, *synthetic])), 128)
            self.assertEqual(len(self.store.entries), 128)
            second = await prepare()
            self.assertEqual(len(self.store.entries), 129)
            await read(first)
            await read(synthetic[0])
            newest = await prepare()
            self.assertEqual(len(set([first, *synthetic, second, newest])), 130)
            self.assertEqual(len(self.store.entries), 130)
            for uri in (first, second, newest):
                await read(uri)
            with self.assertRaises(MCPError):
                await client.read_resource(attachment.ATTACH_RESOURCE_TEMPLATE.format(capability='unknown'))
            self.now += 899
            for uri in (first, synthetic[0], second, newest):
                await read(uri)
            # Reads of both real-wire and metadata-issued capabilities never renew expiry.
            self.assertTrue(all(metadata.expires_at == entry.expires_at
                                for metadata in self.store.entries.values()))
            self.assertEqual(entry.expires_at, self.now + 1)
            self.now += 1
            for uri in (first, synthetic[0]):
                with self.assertRaises(MCPError):
                    await client.read_resource(uri)
            self.assertEqual(len(self.store.entries), 0)
            fresh = await prepare()
            with patch.object(server._file_attachment, 'store', attachment.PendingAttachments(clock=lambda: self.now)):
                with self.assertRaises(MCPError):
                    await client.read_resource(fresh)
            self.assertNotEqual(newest, fresh)
        errors = [response for response in responses if 'error' in response]
        self.assertEqual(len(errors), 4)
        for response in responses:
            self.assert_private(response)
            if 'error' in response:
                self.assertEqual(response['error']['code'], -32602)
            if 'error' in response or 'content' in response.get('result', {}):
                serialized = json.dumps(response)
                for forbidden in ('blob', body.decode(), base64.b64encode(body).decode()):
                    self.assertNotIn(forbidden, serialized)

    async def test_expiry_or_lookup_removal_during_fetch_discards_bytes(self):
        (self.root / 'probe.docx').write_bytes(b'original')
        original = attachment._read_regular_file_part
        responses = []
        async with memory_client(responses) as client:
            for mode in ('expire', 'remove'):
                prepared = await client.call_tool('prepare_file_attachment', {'project_ref': 'p', 'path': 'probe.docx'})
                uri = prepared.content[0].uri
                token = uri.rsplit('/', 1)[-1]
                def invalidate(*args, **kwargs):
                    result = original(*args, **kwargs)
                    if mode == 'expire': self.now += attachment.ATTACH_TTL_SECONDS
                    else: self.store.entries.pop(token)
                    return result
                with self.subTest(mode=mode), patch.object(attachment, '_read_regular_file_part', invalidate):
                    with self.assertRaises(MCPError) as failure:
                        await client.read_resource(uri)
                    self.assertEqual(failure.exception.code, -32602)
        errors = [r for r in responses if 'error' in r]
        self.assertEqual(len(errors), 2)
        for wire in errors:
            self.assert_private(wire)
            self.assertNotIn('blob', json.dumps(wire))
            self.assertNotIn('original', json.dumps(wire))

    def synthetic_source(self, source, byte_size):
        digest = hashlib.sha256()
        with source.open('wb') as output:
            for offset in range(0, byte_size, observation.CHUNK_BYTES):
                # Distinct consecutive parts make incorrect assembly order observable.
                pattern = b'MULTIPART-BODY-SENTINEL\0\xff' + bytes([offset // attachment.MAX_ATTACH_PART_BYTES])
                block = (pattern * (observation.CHUNK_BYTES // len(pattern) + 1))[:min(
                    observation.CHUNK_BYTES, byte_size - offset)]
                output.write(block)
                digest.update(block)
        return digest.hexdigest()

    async def multipart_roundtrip(self, byte_size, part_count, *, work=False):
        name = '原' * 78 + '.pdf' if work else 'multipart.pdf'
        target = self.linked if work else self.root
        (target / 'private-dir').mkdir()
        source = target / 'private-dir' / name
        digest = self.synthetic_source(source, byte_size)
        args = {'project_ref': 'p', 'path': 'private-dir/' + name, 'expected_sha256': digest}
        if work:
            server._WORK_REGISTRY['multipart-work'] = {'project_ref': 'p', 'workspace_root': str(self.root),
                'execution_identity': 'bound',
                'evidence_checkout': EvidenceCheckout.capture(self.project, str(self.linked))}
            args['work_ref'] = 'multipart-work'
            (self.root / 'private-dir').mkdir()
            (self.root / 'private-dir' / name).write_bytes(b'wrong project bytes')
        responses = []
        assembled = self.root / 'assembled.bin'
        async with memory_client(responses, record_resources=False) as client:
            descriptor = next(t for t in (await client.list_tools()).tools if t.name == 'prepare_file_attachment')
            self.assertNotIn('outputSchema', descriptor.model_dump(by_alias=True, exclude_none=True))
            prepared = await client.call_tool('prepare_file_attachment', args)
            self.assertFalse(prepared.is_error)
            expected_types = [ResourceLink] * part_count + ([TextContent] if part_count > 1 else [])
            self.assertEqual([type(c) for c in prepared.content], expected_types)
            links = prepared.content[:-1] if part_count > 1 else prepared.content
            if part_count > 1:
                receipt = {'multipart': {'target': name, 'size': byte_size, 'sha256': digest,
                                        'parts': [link.name for link in links]}}
                self.assertEqual(prepared.content[-1].text,
                                 json.dumps(receipt, ensure_ascii=False, separators=(',', ':')))
            self.assertEqual(len(self.store.entries), 1)
            token = str(links[0].uri).removeprefix(attachment.ATTACH_RESOURCE_PREFIX).split('/')[0]
            entry = self.store.get(token)
            self.assertEqual(len(entry.parts), part_count)
            self.assertEqual(set(vars(entry)), {'project_ref', 'work_ref', 'path', 'target_key',
                'sha256', 'byte_size', 'mime_type', 'name', 'expires_at', 'parts', 'file_binding'})
            self.assertIsInstance(entry.parts, tuple)
            assembled_digest = hashlib.sha256()
            with assembled.open('wb') as output:
                for index, link in enumerate(links, 1):
                    expected_size = min(attachment.MAX_ATTACH_PART_BYTES,
                                        byte_size - (index - 1) * attachment.MAX_ATTACH_PART_BYTES)
                    self.assertEqual(link.size, expected_size)
                    self.assertLessEqual(link.size, 7340032)
                    self.assertLessEqual(len(link.name.encode('utf-8')), 255)
                    if part_count == 1:
                        self.assertEqual((link.name, link.mime_type), (name, 'application/pdf'))
                        self.assertEqual(str(link.uri), attachment.ATTACH_RESOURCE_PREFIX + token)
                    else:
                        self.assertEqual(link.mime_type, 'application/octet-stream')
                        self.assertEqual(link.name, attachment._part_name(name, digest, index, part_count))
                        self.assertEqual(str(link.uri), attachment.ATTACH_RESOURCE_PREFIX +
                                         token + f'/part/{index:04d}')
                    with patch.object(observation, '_read_chunk', wraps=observation._read_chunk) as read:
                        resource = await client.read_resource(link.uri)
                        self.assertEqual(sum(c.args[1] for c in read.call_args_list), expected_size)
                        self.assertTrue(all(0 < c.args[1] <= observation.CHUNK_BYTES for c in read.call_args_list))
                    self.assertEqual(len(resource.contents), 1)
                    blob = resource.contents[0]
                    self.assertIsInstance(blob, BlobResourceContents)
                    self.assertEqual((blob.uri, blob.mime_type), (link.uri, link.mime_type))
                    self.assertEqual(len(blob.blob), 4 * ((link.size + 2) // 3))
                    # A maximum part leaves the observed tunnel overhead margin.
                    self.assertLess(len(json.dumps(resource.model_dump(mode='json', by_alias=True))), 10485760)
                    raw = base64.b64decode(blob.blob, validate=True)
                    self.assertEqual(len(raw), expected_size)
                    self.assertEqual(hashlib.sha256(raw).hexdigest(), entry.parts[index - 1].sha256)
                    output.write(raw)
                    assembled_digest.update(raw)
                    del raw, blob, resource
            self.assertEqual(assembled_digest.hexdigest(), digest)
            self.assertEqual(assembled.stat().st_size, source.stat().st_size)
            with assembled.open('rb') as actual, source.open('rb') as expected:
                while block := expected.read(observation.CHUNK_BYTES):
                    self.assertEqual(actual.read(len(block)), block)
                self.assertEqual(actual.read(1), b'')
        call_wire = next(r['result'] for r in responses if 'content' in r.get('result', {}))
        serialized = json.dumps(call_wire, ensure_ascii=False)
        self.assertEqual([c['type'] for c in call_wire['content']],
                         ['resource_link'] * part_count + (['text'] if part_count > 1 else []))
        self.assertLess(len(serialized.encode()), 8192)
        for forbidden in ('structuredContent', '_meta', 'MULTIPART-BODY-SENTINEL', 'base64', 'blob'):
            self.assertNotIn(forbidden, serialized)
        self.assert_private(call_wire)
        self.assertFalse(any(isinstance(value, bytes) for value in vars(entry).values()))
        self.assertTrue(all(not any(isinstance(value, bytes) for value in vars(p).values()) for p in entry.parts))

    @unittest.skipUnless(os.environ.get('BRIDGE_MAINTAINER_SUITE') == '1',
                         'Full 14 MiB wire run requires BRIDGE_MAINTAINER_SUITE=1')
    async def test_fourteen_mib_two_part_memory_roundtrip(self):
        await self.multipart_roundtrip(14 * 1024 * 1024, 2)

    @unittest.skipUnless(os.environ.get('BRIDGE_MAINTAINER_SUITE') == '1',
                         'Full 21 MiB Work wire run requires BRIDGE_MAINTAINER_SUITE=1')
    async def test_twenty_one_mib_three_part_work_memory_roundtrip(self):
        await self.multipart_roundtrip(21 * 1024 * 1024, 3, work=True)

    async def test_small_two_part_memory_roundtrip(self):
        smallcap = 2 * observation.CHUNK_BYTES
        # Keep the cap patched across source generation, preparation and every fetch.
        with patch.object(attachment, 'MAX_ATTACH_PART_BYTES', smallcap):
            await self.multipart_roundtrip(2 * smallcap, 2)

    async def test_small_three_part_work_memory_roundtrip_uses_frozen_checkout(self):
        smallcap = 2 * observation.CHUNK_BYTES
        with patch.object(attachment, 'MAX_ATTACH_PART_BYTES', smallcap):
            await self.multipart_roundtrip(2 * smallcap + 17, 3, work=True)

    async def test_seven_mib_single_resource_memory_roundtrip(self):
        await self.multipart_roundtrip(7 * 1024 * 1024, 1)

    async def test_seven_mib_plus_one_two_part_memory_roundtrip(self):
        await self.multipart_roundtrip(7 * 1024 * 1024 + 1, 2)

    async def test_over_128_mib_preparation_has_no_logical_size_cap(self):
        # Sparse source plus fake hash results exercises prepare_file_attachment without hashing 128 MiB.
        size = 128 * 1024 * 1024 + 1
        source = self.root / 'large.bin'
        with source.open('wb') as output:
            output.truncate(size)
        digest = 'a' * 64
        descriptors = tuple(attachment.FilePart(index + 1, offset,
            min(attachment.MAX_ATTACH_PART_BYTES, size - offset), 'b' * 64)
            for index, offset in enumerate(range(0, size, attachment.MAX_ATTACH_PART_BYTES)))

        def fake_hash(target, path, *, part_bytes):
            self.assertEqual(part_bytes, attachment.MAX_ATTACH_PART_BYTES)
            with observation._open_regular_file(target, path, max_bytes=None) as (walk, _, before):
                self.assertEqual(before.st_size, size)
                return (observation._file_metadata(path, before, size, digest),
                        observation._file_binding(walk, before), descriptors)

        responses = []
        async with memory_client(responses) as client:
            with patch.object(attachment, '_hash_regular_file_parts', side_effect=fake_hash) as hashed:
                result = await client.call_tool('prepare_file_attachment', {'project_ref': 'p', 'path': source.name,
                                                             'expected_sha256': digest})
                self.assertEqual(hashed.call_count, 1)
        self.assertFalse(result.is_error)
        self.assertEqual([type(c) for c in result.content], [ResourceLink] * 19 + [TextContent])
        links = result.content[:-1]
        self.assertEqual([c.size for c in links], [7340032] * 18 + [2 * 1024 * 1024 + 1])
        self.assertEqual(json.loads(result.content[-1].text), {'multipart': {
            'target': source.name, 'size': size, 'sha256': digest, 'parts': [c.name for c in links]}})
        self.assertEqual(len(self.store.entries), 1)
        # Real lower layer must open this size too. Early EOF tests the retained size check,
        # without streaming a large fixture; the old cap would reject before this read.
        with patch.object(observation, '_read_chunk', return_value=b'') as read:
            wire, meta = await self.wire(source.name)
            self.assertTrue(wire['isError'])
            self.assertEqual(meta['error_type'], 'FileChanged')
            read.assert_called_once()
        self.assertEqual(len(self.store.entries), 1)
        for response in responses:
            self.assert_private(response)
            self.assertNotIn('blob', json.dumps(response))

    async def test_part_ordinals_above_9999_remain_canonical_and_readable(self):
        # Metadata-only fixture for a 10,000-part original; no huge body is allocated.
        part = attachment.FilePart(10000, 9999 * attachment.MAX_ATTACH_PART_BYTES, 1, 'a' * 64)
        parts = (attachment.FilePart(1, 0, attachment.MAX_ATTACH_PART_BYTES, 'b' * 64),) * 9999 + (part,)
        token, entry = self.store.issue(project_ref='p', work_ref=None, path='large.bin',
            target_key=(), sha256='c' * 64, byte_size=part.offset + 1,
            mime_type='application/octet-stream', name='large.bin', file_binding=(), parts=parts)
        self.assertEqual(attachment._part_name(entry.name, entry.sha256, 10000, 10000),
                         'large.bin.bridge-cccccccccccc-part-10000-of-10000')
        uri = attachment.ATTACH_PART_RESOURCE_TEMPLATE.format(capability=token, part_index='10000')
        responses = []
        async with memory_client(responses) as client:
            with patch.object(server._file_attachment, '_read_part', AsyncMock(return_value=b'x')) as read:
                result = await client.read_resource(uri)
                read.assert_awaited_once_with(token, 10000)
                self.assertEqual(base64.b64decode(result.contents[0].blob), b'x')
                self.assertEqual(result.contents[0].mime_type, 'application/octet-stream')
                with self.assertRaises(MCPError):
                    await client.read_resource(uri.replace('/10000', '/010000'))
                self.assertEqual(read.await_count, 1)

    async def test_multipart_noncanonical_indices_and_single_form_fail_closed(self):
        with (self.root / 'parts.bin').open('wb') as output:
            output.truncate(14 * 1024 * 1024)
        responses = []
        async with memory_client(responses) as client:
            prepared = await client.call_tool('prepare_file_attachment', {'project_ref': 'p', 'path': 'parts.bin'})
            uri = str(prepared.content[0].uri)
            group = uri.rsplit('/part/', 1)[0]
            invalid = [group, group + '/', group + '/part/0000', group + '/part/0003',
                       group + '/part/1', group + '/part/00001', group + '/part/-001',
                       group + '/part/+001', group + '/part/０００１', group + '/part/%30%30%30%31',
                       uri + '/', uri + '?x=1', uri + '#fragment',
                       attachment.ATTACH_RESOURCE_PREFIX + 'x' * 43 + '/part/0001',
                       'bridge://export/' + group.rsplit('/', 1)[-1] + '/part/0001']
            with patch.object(server._file_attachment, 'resolve_target') as resolve:
                for candidate in invalid:
                    with self.subTest(uri=candidate), self.assertRaises(MCPError):
                        await client.read_resource(candidate)
                resolve.assert_not_called()
        errors = [r for r in responses if 'error' in r]
        self.assertEqual(len(errors), len(invalid))
        for wire in errors:
            self.assert_private(wire)
            self.assertNotIn('blob', json.dumps(wire))
        self.assertEqual(len(self.store.entries), 1)

    async def test_multipart_mutation_anywhere_and_path_replacement_fail_closed(self):
        responses = []
        async with memory_client(responses) as client:
            for race in ('same_size_other_part', 'replace_same_bytes', 'parent_replace', 'symlink', 'fifo'):
                directory = self.root / race
                directory.mkdir()
                source = directory / 'parts.bin'
                with source.open('wb') as output:
                    output.truncate(14 * 1024 * 1024)
                prepared = await client.call_tool('prepare_file_attachment', {'project_ref': 'p', 'path': race + '/parts.bin'})
                links = prepared.content[:-1]
                before = source.stat()
                if race == 'same_size_other_part':
                    with source.open('r+b') as output:
                        output.seek(-1, os.SEEK_END)
                        output.write(b'x')
                    os.utime(source, ns=(before.st_atime_ns, before.st_mtime_ns))
                elif race == 'replace_same_bytes':
                    replacement = directory / 'replacement'
                    with replacement.open('wb') as output:
                        output.truncate(before.st_size)
                    replacement.replace(source)
                elif race == 'parent_replace':
                    directory.rename(self.root / ('old-' + race))
                    directory.mkdir()
                    with source.open('wb') as output:
                        output.truncate(before.st_size)
                else:
                    source.unlink()
                    if race == 'symlink': source.symlink_to('/etc/passwd')
                    else: os.mkfifo(source)
                with patch.object(observation, '_read_chunk') as read:
                    for link in links:
                        with self.subTest(race=race,uri=link.uri), self.assertRaises(MCPError):
                            await client.read_resource(link.uri)
                    read.assert_not_called()
        for wire in (r for r in responses if 'error' in r):
            self.assert_private(wire)
            self.assertNotIn('blob', json.dumps(wire))

    async def test_multipart_expiry_restart_invalidate_whole_group(self):
        with (self.root / 'parts.bin').open('wb') as output:
            output.truncate(14 * 1024 * 1024)
        responses = []
        async with memory_client(responses, record_resources=False) as client:
            for mode in ('expire', 'restart'):
                prepared = await client.call_tool('prepare_file_attachment', {'project_ref': 'p', 'path': 'parts.bin'})
                links = prepared.content[:-1]
                token = str(links[0].uri).removeprefix(attachment.ATTACH_RESOURCE_PREFIX).split('/')[0]
                entry = self.store.get(token)
                self.assertEqual(len(self.store.entries), 1)
                await client.read_resource(links[0].uri)
                self.assertIs(self.store.get(token), entry)
                self.assertEqual(entry.expires_at, self.now + 900)
                if mode == 'expire': self.now += 900
                old_store = server._file_attachment.store
                if mode == 'restart':
                    server._file_attachment.store = attachment.PendingAttachments(clock=lambda: self.now)
                try:
                    for link in links:
                        with self.assertRaises(MCPError): await client.read_resource(link.uri)
                finally:
                    server._file_attachment.store = old_store
                    self.store.entries.clear()
        errors = [r for r in responses if 'error' in r]
        self.assertEqual(len(errors), 4)
        for wire in errors:
            self.assert_private(wire)
            self.assertNotIn('blob', json.dumps(wire))

    async def test_part_hash_fails_closed_even_if_source_stat_binding_is_spoofed(self):
        source = self.root / 'parts.bin'
        with source.open('wb') as output:
            output.truncate(14 * 1024 * 1024)
        responses = []
        async with memory_client(responses) as client:
            prepared = await client.call_tool('prepare_file_attachment', {'project_ref': 'p', 'path': source.name})
            link = prepared.content[0]
            token = str(link.uri).removeprefix(attachment.ATTACH_RESOURCE_PREFIX).split('/')[0]
            entry = self.store.get(token)
            with source.open('r+b') as output:
                output.write(b'x')
            with patch.object(observation, '_file_binding', return_value=entry.file_binding):
                with self.assertRaises(MCPError):
                    await client.read_resource(link.uri)
        for wire in (r for r in responses if 'error' in r):
            self.assertNotIn('blob', json.dumps(wire))
            self.assert_private(wire)


class AttachmentStoreTests(unittest.TestCase):
    def test_no_count_eviction_random_tokens_and_internal_expiry_without_read_renewal(self):
        now = 100.0
        store = attachment.PendingAttachments(clock=lambda: now)
        binding = dict(project_ref='project-secret', work_ref='work-secret', path='private/report.docx',
            target_key=('checkout-secret',), sha256='a' * 64, byte_size=417431,
            mime_type='application/octet-stream', name='report.docx', file_binding=('stat-secret',),
            parts=(attachment.FilePart(1, 0, 417431, 'a' * 64),))
        tokens = []
        with patch.object(attachment.secrets, 'token_urlsafe', wraps=attachment.secrets.token_urlsafe) as random:
            for _ in range(129): tokens.append(store.issue(**binding)[0])
            self.assertEqual(len(store.entries), 129)
            first = store.get(tokens[0])
            self.assertEqual(first.expires_at, 1000.0)
            now += 899
            self.assertIs(store.get(tokens[0]), first)
            store.issue(**binding)
            self.assertEqual(len(store.entries), 130)
            self.assertIs(store.get(tokens[0]), first)
            now += 1
            with self.assertRaises(ResourceNotFoundError): store.get(tokens[1])
            self.assertEqual(len(store.entries), 1)
            self.assertTrue(all(c.args == (32,) for c in random.call_args_list))
        self.assertEqual(len(set(tokens)), 129)
        self.assertTrue(all(len(t) == 43 for t in tokens))
        for value in ('project-secret', 'work-secret', 'private', 'report.docx', 'checkout-secret'):
            self.assertNotIn(value, ''.join(tokens))
        # Fresh service/store state models restart; no external process is restarted.
        with self.assertRaises(ResourceNotFoundError): attachment.PendingAttachments().get(tokens[-1])

    def test_docs_keep_current_attachment_mechanics_and_retired_ui_absent(self):
        root = Path(__file__).resolve().parents[1]
        contract = (root / 'docs/OBSERVATION-TOOLS.md').read_text()
        for boundary in ('multipart {target, size, sha256, parts}', 'no TextContent',
                         'resources/read', '7 MiB', '10,485,760', 'checks are not atomic'):
            self.assertIn(boundary, contract)
        for obsolete in ('part_names', 'concatenate_parts_in_order', 'PRINCIPAL-TOOL-CONTRACT.md'):
            self.assertNotIn(obsolete, contract)
        self.assertFalse((root / 'ui/attach-file.html').exists())
        self.assertFalse((root / 'ui/export-file.html').exists())
