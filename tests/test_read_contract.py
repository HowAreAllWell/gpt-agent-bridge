"""Read descriptor and SDK result serialization preserve actual evidence metadata."""
import base64
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

import anyio
os.environ.setdefault('BRIDGE_PATH_TOKEN', 'test-token-abcdefghijklmnopqrstuvwxyz-012345')
from gpt_agent_bridge import server
from gpt_agent_bridge.read_schema import NativeImageEnvelopeError, ReadResultModel
from mcp import ClientSession
from mcp.shared.memory import create_client_server_memory_streams
from mcp.server.mcpserver import Image
from mcp.types import CallToolRequestParams, TextContent
from pydantic import ValidationError
from tests.test_vnext_surface import TINY_PNG
from tests.test_work_surface import git_repo_with_linked_worktree
from gpt_agent_bridge.evidence_target import EvidenceCheckout
from gpt_agent_bridge.workspace_context import WorkspaceRegistry, WorkspaceRegistryStore

_PDF_SENTINEL = b'%PDF-1.4 sentinel'
_DOCX_SENTINEL = b'PK\x03\x04 sentinel'


class ReadContractTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root, self.linked = git_repo_with_linked_worktree(Path(self.temp.name))
        registry = WorkspaceRegistry(self.root, json.dumps({'p': str(self.root)}),
            store=WorkspaceRegistryStore(Path(self.temp.name) / 'registry.json'))
        self.addCleanup(patch.stopall)
        patch.object(server, '_WORKSPACE_REGISTRY', registry).start()
        patch.object(server, '_WORK_REGISTRY', {}).start()
        patch.object(server, '_RESULT_INBOX', {}).start()
        patch.object(server.HerdrBackend, '_call', AsyncMock(side_effect=AssertionError('no host I/O'))).start()
        self.project = registry.resolve('p')

    async def wire(self, **args):
        tool = next(t for t in await server.mcp.list_tools() if t.name == 'read')
        self.assertNotIn('outputSchema', tool.model_dump(by_alias=True, exclude_none=True))
        self.assertEqual(set(tool.input_schema['properties']), {'project_ref','path','offset','limit','work_ref','start_line','expected_sha256','end_line'})
        result = await server.mcp.call_tool('read', {'project_ref': 'p', **args})
        wire = json.loads(result.model_dump_json(by_alias=True, exclude_none=True))
        self.assertFalse(wire['isError'])
        if wire.get('structuredContent') is not None:
            metadata = wire['structuredContent']
            self.assertNotIn('state_id', metadata)
            self.assertNotIn('dirty', metadata)
            if metadata.get('ok'):
                self.assertNotIn('state_id', metadata['version'])
            self.assertLess(len(wire['content'][-1]['text']), 150)
            self.assertNotIn('result', metadata)
            # No SDK output schema exists: private model validation guards the payload.
            ReadResultModel.model_validate(metadata)
            return wire, metadata
        # Native-image success: one image block plus one compact full-metadata
        # text block, no structuredContent, and no duplicated image evidence.
        self.assertEqual([b['type'] for b in wire['content']], ['image', 'text'])
        metadata = json.loads(wire['content'][1]['text'])
        self.assertNotIn('state_id', metadata)
        self.assertNotIn('dirty', metadata)
        self.assertNotIn('data', metadata)
        self.assertNotIn('content', metadata)
        image_data = wire['content'][0]['data']
        self.assertEqual(json.dumps(wire, ensure_ascii=False).count(image_data), 1)
        return wire, metadata

    async def test_text_unicode_pagination_and_work_provenance(self):
        (self.root / 'unicode.txt').write_text('one\n中文 café 😀\n')
        wire, first = await self.wire(path='unicode.txt', start_line=2, limit=3)
        self.assertEqual(first['content'], '中文 ')
        self.assertEqual(first['content_start_line'], 2)
        self.assertEqual(first['content_next_offset'], 7)
        _, last = await self.wire(path='unicode.txt', offset=7)
        self.assertEqual(last['content'], 'café 😀\n')
        self.assertIsNone(last['content_next_offset'])
        self.assertIsNone(last['work_ref'])
        self.assertFalse(last['content_has_more'])
        self.assertNotIn('kind', first)
        self.assertNotIn('error', first)
        (self.linked / 'unique.txt').write_text('linked')
        server._WORK_REGISTRY['work-test'] = {'project_ref': 'p', 'workspace_root': str(self.root),
            'execution_identity': 'bound', 'evidence_checkout': EvidenceCheckout.capture(self.project, str(self.linked))}
        _, work = await self.wire(path='unique.txt', work_ref='work-test')
        self.assertEqual(work['execution_target'], str(self.linked))
        self.assertEqual(work['project_root'], str(self.root))
        self.assertEqual(work['target_kind'], 'work_checkout')
        self.assertEqual(work['provenance']['proves'], 'observed_content_only')
        _, absent = await self.wire(path='unique.txt')
        self.assertFalse(absent['ok'])

    async def test_native_image_and_application_errors(self):
        (self.root / 'image.png').write_bytes(TINY_PNG)
        (self.root / 'bad.png').write_bytes(b'not png')
        (self.root / 'binary').write_bytes(b'\0abc')
        wire, meta = await self.wire(path='image.png')
        self.assertEqual(wire['content'][0]['type'], 'image')
        self.assertEqual(base64.b64decode(wire['content'][0]['data']), TINY_PNG)
        self.assertEqual(wire['content'][0]['mimeType'], 'image/png')
        self.assertNotIn('data', meta)
        self.assertNotIn('content', meta)
        self.assertEqual(meta['pagination'], {'unit': 'whole_image', 'next_offset': None})
        for args, error in [({'path':'bad.png'}, 'UnsupportedImageFormat'),
            ({'path':'binary'}, 'BinaryFileUnsupported'), ({'path':'missing'}, 'FileNotFound'),
            ({'path':'image.png','offset':-1}, 'InvalidOffset'),
            ({'path':'image.png','limit':0}, 'InvalidLimit'),
            ({'path':'image.png','start_line':0}, 'InvalidStartLine'),
            ({'path':'image.png','offset':1,'start_line':1}, 'AmbiguousReadPosition'),
            ({'path':'image.png','limit':2}, 'ImagePagingUnsupported'),
            ({'path':''}, 'InvalidPath'),
            ({'path':'image.png','work_ref':'never-issued'}, 'WorkRefUnavailable')]:
            with self.subTest(args=args):
                _, result = await self.wire(**args)
                self.assertFalse(result['ok'])
                self.assertEqual(result['error_type'], error)
                self.assertNotIn('content', result)
                if error == 'InvalidOffset':
                    self.assertEqual(set(result), {'ok','error_type','error'})

    async def test_descriptor_and_variant_validation(self):
        tool = next(t for t in await server.mcp.list_tools() if t.name == 'read')
        ann = tool.model_dump(mode='json', by_alias=True)['annotations']
        self.assertTrue(ann['readOnlyHint'])
        self.assertNotIn('outputSchema', tool.model_dump(by_alias=True, exclude_none=True))
        self.assertEqual(set(tool.input_schema['properties']), {'project_ref','path','offset','limit','work_ref','start_line','expected_sha256','end_line'})
        self.assertNotIn('minimum', tool.input_schema['properties']['limit'])
        (self.root / 'text').write_text('中文')
        _, valid = await self.wire(path='text')
        for field, value in [('content', 1), ('content_page_chars', '2'), ('file_sha256', False)]:
            bad = dict(valid, **{field: value})
            with self.assertRaises(ValidationError): ReadResultModel.model_validate(bad)
        for bad in (dict(valid, pagination={'unit':'whole_image', 'next_offset':'bad'}),
                    dict(valid, version={'git_head':False})):
            with self.assertRaises(ValidationError): ReadResultModel.model_validate(bad)
        for field in ('content', 'provenance', 'content_next_offset'):
            bad = dict(valid); bad.pop(field)
            with self.assertRaises(ValidationError): ReadResultModel.model_validate(bad)
        for bad in ({'ok':False}, {'ok':True,'kind':'image','mime_type':'image/png'}):
            with self.assertRaises(ValidationError): ReadResultModel.model_validate(bad)
        extra = dict(valid, diagnostic={'detail':'retained'})
        converted = server.read_tool_result(extra)
        self.assertEqual(converted.structured_content['diagnostic'], {'detail':'retained'})

    async def test_end_line_ceiling_pages_continuation_and_terminal_metadata(self):
        text = 'l1\nl2\nl3\nl4\n'
        (self.root / 'lines.txt').write_text(text)
        _, whole = await self.wire(path='lines.txt')
        self.assertEqual(whole['content'], text)
        self.assertIsNone(whole['content_next_offset'])
        # Omitted and explicit-null end_line preserve the unscoped page.
        _, null_page = await self.wire(path='lines.txt', end_line=None)
        omit = dict(whole); omit.pop('provenance')
        null = dict(null_page); null.pop('provenance')
        self.assertEqual(null, omit)
        # Exact inclusive line window keeps each selected terminating LF.
        _, window = await self.wire(path='lines.txt', start_line=2, end_line=3)
        self.assertEqual(window['content'], 'l2\nl3\n')
        self.assertIsNone(window['content_next_offset'])
        self.assertEqual(window['content_total_chars'], len(text))
        self.assertEqual(window['content_limit'], 4096)
        # Partial page inside the ceiling continues by repeating the same end_line.
        _, part = await self.wire(path='lines.txt', end_line=3, limit=2)
        self.assertEqual(part['content'], 'l1')
        self.assertEqual(part['content_next_offset'], 2)
        pieces, offset = [], 0
        while True:
            _, page = await self.wire(path='lines.txt', offset=offset, limit=2, end_line=3)
            pieces.append(page['content'])
            self.assertEqual(page['content_total_chars'], len(text))
            if page['content_next_offset'] is None:
                break
            offset = page['content_next_offset']
        self.assertEqual(''.join(pieces), 'l1\nl2\nl3\n')
        self.assertNotIn('l4', ''.join(pieces))
        # Offset at the ceiling is an empty successful terminal page.
        _, at = await self.wire(path='lines.txt', offset=9, end_line=3)
        self.assertTrue(at['ok'])
        self.assertEqual(at['content'], '')
        self.assertEqual(at['content_page_chars'], 0)
        self.assertIsNone(at['content_next_offset'])
        self.assertFalse(at['content_has_more'])
        # Offset beyond physical EOF stays an empty terminal page (existing behavior).
        _, past = await self.wire(path='lines.txt', offset=99)
        self.assertTrue(past['ok'])
        self.assertEqual(past['content'], '')

    async def test_end_line_eof_clamp_final_lf_crlf_and_unicode(self):
        (self.root / 'no_final').write_text('a\nb')
        (self.root / 'empty').write_text('')
        (self.root / 'crlf').write_text('r1\r\nr2\r\n')
        (self.root / 'unicode').write_text('one\n中文 café 😀\n')
        # end_line beyond EOF clamps to EOF instead of failing.
        _, clamp = await self.wire(path='no_final', end_line=99)
        self.assertEqual(clamp['content'], 'a\nb')
        self.assertIsNone(clamp['content_next_offset'])
        # A final line without LF is addressable and includes no trailing LF.
        _, last = await self.wire(path='no_final', end_line=2)
        self.assertEqual(last['content'], 'a\nb')
        _, first = await self.wire(path='no_final', end_line=1)
        self.assertEqual(first['content'], 'a\n')
        # Empty file: end_line 1 is an empty successful terminal page.
        _, empty = await self.wire(path='empty', end_line=1)
        self.assertTrue(empty['ok'])
        self.assertEqual(empty['content'], '')
        self.assertIsNone(empty['content_next_offset'])
        # LF alone delimits lines; CR is preserved page content.
        _, crlf = await self.wire(path='crlf', end_line=1)
        self.assertEqual(crlf['content'], 'r1\r\n')
        self.assertIsNone(crlf['content_next_offset'])
        # Unicode code-point coordinates are unchanged under the ceiling.
        _, head = await self.wire(path='unicode', start_line=2, end_line=2, limit=3)
        self.assertEqual(head['content'], '中文 ')
        self.assertEqual(head['content_next_offset'], 7)
        _, tail = await self.wire(path='unicode', offset=7, end_line=2)
        self.assertEqual(tail['content'], 'café 😀\n')
        self.assertIsNone(tail['content_next_offset'])

    async def test_end_line_validation_image_rejection_and_wire_strictness(self):
        (self.root / 'lines').write_text('one\n')
        (self.root / 'x.png').write_bytes(TINY_PNG)
        for value in (0, -1, True, '2'):
            self.assertEqual((await server.read('p', 'lines', end_line=value))['error_type'], 'InvalidEndLine')
        below = await server.read('p', 'lines', start_line=2, end_line=1)
        self.assertEqual(below['error_type'], 'InvalidEndLine')
        self.assertEqual(below['error'], 'end_line must not be below start_line')
        # Reversed huge bounds return InvalidEndLine without escaping the
        # int-to-str conversion limit as an exception.
        for huge_start, huge_end in ((10 ** 5000, 1), (10 ** 5000 + 1, 10 ** 5000)):
            reversed_huge = await server.read('p', 'lines', start_line=huge_start, end_line=huge_end)
            self.assertEqual(reversed_huge['error_type'], 'InvalidEndLine')
            self.assertEqual(reversed_huge['error'], 'end_line must not be below start_line')
        # Controls: a huge end_line alone clamps to EOF; a huge valid start_line
        # keeps LineOutOfRange.
        huge_ceiling = await server.read('p', 'lines', end_line=10 ** 5000)
        self.assertTrue(huge_ceiling['ok'], huge_ceiling)
        self.assertEqual(huge_ceiling['content'], 'one\n')
        self.assertIsNone(huge_ceiling['content_next_offset'])
        self.assertEqual((await server.read('p', 'lines', start_line=10 ** 5000))['error_type'], 'LineOutOfRange')
        # A final-LF EOF line: start_line == end_line at EOF is an empty success.
        _, eof_line = await self.wire(path='lines', start_line=2, end_line=2)
        self.assertTrue(eof_line['ok'])
        self.assertEqual(eof_line['content'], '')
        # start_line beyond EOF remains LineOutOfRange even with a valid end_line.
        self.assertEqual((await server.read('p', 'lines', start_line=3, end_line=4))['error_type'], 'LineOutOfRange')
        # A valid supplied end_line rejects image paging before image load.
        self.assertEqual((await server.read('p', 'x.png', end_line=1))['error_type'], 'ImagePagingUnsupported')
        # The advertised property is integer-or-null without numeric bounds.
        tool = next(t for t in await server.mcp.list_tools() if t.name == 'read')
        end_schema = tool.input_schema['properties']['end_line']
        self.assertIn({'type': 'integer'}, end_schema['anyOf'])
        self.assertIn({'type': 'null'}, end_schema['anyOf'])
        self.assertNotIn('minimum', end_schema)
        # The MCP wire validator is strict for the new property.
        for bad in ('2', True, 1.0):
            result = await server.mcp._handle_call_tool(None, CallToolRequestParams(
                name='read', arguments={'project_ref': 'p', 'path': 'lines', 'end_line': bad}))
            wire = json.loads(result.model_dump_json(by_alias=True))
            self.assertTrue(wire['isError'])
            self.assertIsNone(wire['structuredContent'])

    async def test_protocol_error_distinct_from_application_error(self):
        result = await server.mcp._handle_call_tool(None, CallToolRequestParams(
            name='read', arguments={'project_ref':'p', 'path':'README.md', 'offset':[]}))
        wire = json.loads(result.model_dump_json(by_alias=True))
        self.assertTrue(wire['isError'])
        self.assertIsNone(wire['structuredContent'])
        _, application = await self.wire(path='README.md', offset=-1)
        self.assertEqual(application['error_type'], 'InvalidOffset')


class ReadMemoryWireTests(unittest.IsolatedAsyncioTestCase):
    """Raw in-memory wire: read carries structured text but never structured images."""
    setUp = ReadContractTests.setUp

    async def test_memory_wire_text_structured_and_image_unstructured(self):
        (self.root / 'note.txt').write_text('plain body\n')
        (self.root / 'image.png').write_bytes(TINY_PNG)
        lowlevel = server.mcp._lowlevel_server
        wire_results = []
        class RecordingSend:
            def __init__(self, stream): self.stream = stream
            def __getattr__(self, name): return getattr(self.stream, name)
            async def __aenter__(self): return self
            async def __aexit__(self, *args): return await self.stream.__aexit__(*args)
            async def send(self, message):
                payload = getattr(message.message, 'root', message.message)
                result = getattr(payload, 'result', None)
                if isinstance(result, dict): wire_results.append(result)
                await self.stream.send(message)
        async with create_client_server_memory_streams() as (client_streams, server_streams):
            async with anyio.create_task_group() as group:
                group.start_soon(lowlevel.run, server_streams[0], RecordingSend(server_streams[1]),
                                 lowlevel.create_initialization_options())
                async with ClientSession(*client_streams) as client:
                    await client.initialize()
                    catalog = await client.list_tools()
                    tool = next(t for t in catalog.tools if t.name == 'read')
                    self.assertNotIn('outputSchema', tool.model_dump(by_alias=True, exclude_none=True))
                    self.assertEqual(set(tool.input_schema['properties']),
                                     {'project_ref', 'path', 'offset', 'limit', 'work_ref',
                                      'start_line', 'expected_sha256', 'end_line'})
                    image = await client.call_tool('read', {'project_ref': 'p', 'path': 'image.png'})
                    image_wire = image.model_dump(by_alias=True, exclude_none=True)
                    self.assertNotIn('structuredContent', image_wire)
                    self.assertFalse(image_wire['isError'])
                    self.assertEqual([b['type'] for b in image_wire['content']], ['image', 'text'])
                    self.assertEqual(base64.b64decode(image_wire['content'][0]['data']), TINY_PNG)
                    metadata = json.loads(image_wire['content'][1]['text'])
                    self.assertEqual(metadata['kind'], 'image')
                    self.assertEqual(metadata['pagination'], {'unit': 'whole_image', 'next_offset': None})
                    text = await client.call_tool('read', {'project_ref': 'p', 'path': 'note.txt'})
                    text_wire = text.model_dump(by_alias=True, exclude_none=True)
                    self.assertFalse(text_wire['isError'])
                    self.assertEqual(text_wire['structuredContent']['content'], 'plain body\n')
                    self.assertIn('Result available in structuredContent', text_wire['content'][-1]['text'])
                group.cancel_scope.cancel()
        raw_catalog = next(r['tools'] for r in wire_results if 'tools' in r)
        self.assertNotIn('outputSchema', next(t for t in raw_catalog if t['name'] == 'read'))
        raw_image = next(r for r in wire_results if 'content' in r
                         and any(b.get('type') == 'image' for b in r['content']))
        self.assertNotIn('structuredContent', raw_image)
        self.assertEqual([b['type'] for b in raw_image['content']], ['image', 'text'])
        raw_text = next(r for r in wire_results if 'structuredContent' in r)
        self.assertEqual(raw_text['structuredContent']['path'], 'note.txt')


class ReadEnvelopeRegressionTests(unittest.IsolatedAsyncioTestCase):
    """EVO-046 closed on the real registered dispatch: malformed internal image
    envelopes fail closed as isError=true protocol errors with zero native-image
    leakage, never as ordinary ok=false application responses."""
    setUp = ReadContractTests.setUp

    async def real_envelope(self):
        (self.root / 'image.png').write_bytes(TINY_PNG)
        envelope = await server.read('p', 'image.png')
        self.assertIsInstance(envelope, list)
        self.assertEqual(len(envelope), 2)
        return envelope

    async def rejected_on_wire(self, injected):
        with patch.object(server, 'read', AsyncMock(return_value=injected)):
            result = await server.mcp.call_tool('read', {'project_ref': 'p', 'path': 'image.png'})
        wire = json.loads(result.model_dump_json(by_alias=True))
        self.assertTrue(wire['isError'])
        self.assertIsNone(wire['structuredContent'])
        self.assertEqual([block['type'] for block in wire['content']], ['text'])
        serialized = json.dumps(wire)
        self.assertNotIn(base64.b64encode(TINY_PNG).decode(), serialized)
        self.assertLessEqual(len(wire['content'][0]['text']), 300)
        self.assertIn('envelope failed producer validation', wire['content'][0]['text'])
        return wire

    async def test_positive_envelope_keeps_exact_bytes_full_metadata_no_structured(self):
        envelope = await self.real_envelope()
        with patch.object(server, 'read', AsyncMock(return_value=envelope)):
            result = await server.mcp.call_tool('read', {'project_ref': 'p', 'path': 'image.png'})
        wire = json.loads(result.model_dump_json(by_alias=True, exclude_none=True))
        self.assertFalse(wire['isError'])
        self.assertNotIn('structuredContent', wire)
        self.assertEqual([block['type'] for block in wire['content']], ['image', 'text'])
        self.assertEqual(base64.b64decode(wire['content'][0]['data']), TINY_PNG)
        metadata = json.loads(wire['content'][1]['text'])
        self.assertEqual(metadata['kind'], 'image')
        self.assertEqual(metadata['file_sha256'], envelope[1]['file_sha256'])

    async def test_real_image_with_valid_error_metadata_rejected(self):
        envelope = await self.real_envelope()
        await self.rejected_on_wire(
            [envelope[0], {'ok': False, 'error_type': 'SyntheticProbe', 'error': 'injected'}])

    async def test_real_image_with_valid_text_success_metadata_rejected(self):
        envelope = await self.real_envelope()
        (self.root / 'note.txt').write_text('plain body\n')
        text_metadata = await server.read('p', 'note.txt')
        self.assertIsInstance(text_metadata, dict)
        await self.rejected_on_wire([envelope[0], text_metadata])

    async def test_envelope_arity_rejected(self):
        envelope = await self.real_envelope()
        for injected in ([], [envelope[0]], [envelope[0], envelope[1], envelope[1]]):
            with self.subTest(arity=len(injected)):
                await self.rejected_on_wire(injected)

    async def test_non_image_first_element_rejected(self):
        envelope = await self.real_envelope()
        for impostor in (TextContent(type='text', text='not an image'), object(), None):
            with self.subTest(impostor=type(impostor).__name__):
                await self.rejected_on_wire([impostor, envelope[1]])

    async def test_non_dict_metadata_rejected(self):
        envelope = await self.real_envelope()
        for metadata in (None, 'metadata', [envelope[1]]):
            with self.subTest(metadata=type(metadata).__name__):
                await self.rejected_on_wire([envelope[0], metadata])

    async def test_incomplete_or_invalid_image_metadata_rejected(self):
        envelope = await self.real_envelope()
        incomplete = {key: value for key, value in envelope[1].items() if key != 'file_sha256'}
        await self.rejected_on_wire([envelope[0], incomplete])
        await self.rejected_on_wire([envelope[0], dict(envelope[1], file_size_bytes='big')])

    async def test_mime_mismatch_between_image_and_metadata_rejected(self):
        envelope = await self.real_envelope()
        await self.rejected_on_wire([Image(data=TINY_PNG, format='jpeg'), envelope[1]])

    async def test_standalone_image_metadata_dict_rejected_without_envelope(self):
        envelope = await self.real_envelope()
        await self.rejected_on_wire(envelope[1])
        with self.assertRaises(NativeImageEnvelopeError):
            server.native_image_result([envelope[0], 'metadata'])


class PublicReadBoundaryTests(unittest.IsolatedAsyncioTestCase):
    """Public read refuses PDF/DOCX by validated suffix before any body access."""

    setUp = ReadContractTests.setUp
    wire = ReadContractTests.wire

    async def test_pdf_docx_refused_by_suffix_before_body_access(self):
        fixtures = [('report.pdf', _PDF_SENTINEL), ('report.PDF', _PDF_SENTINEL),
                    ('notes.docx', _DOCX_SENTINEL), ('notes.DOCX', _DOCX_SENTINEL),
                    ('broken.pdf', b'not pdf at all'), ('broken.docx', b'not zip')]
        for name, raw in fixtures:
            (self.root / name).write_bytes(raw)

        def no_bytes(workspace, parts, path, limit):
            raise AssertionError('read must refuse PDF/DOCX before reading bytes')

        with patch.object(server, '_read_bounded_workspace_bytes', no_bytes):
            for name, _raw in fixtures:
                with self.subTest(name=name):
                    _, result = await self.wire(path=name)
                    self.assertFalse(result['ok'])
                    self.assertEqual(result['error_type'], 'UnsupportedReadFormat')
                    self.assertEqual(
                        result['error'],
                        'PDF/DOCX are not supported by read; use prepare_file_attachment '
                        'to prepare the original for later fetch.')
                    self.assertNotIn('content', result)
                    self.assertNotIn('file_sha256', result)
        # No implicit attachment or Work action followed from the refusals.
        self.assertEqual(server._WORK_REGISTRY, {})

    async def test_boundary_follows_argument_target_and_path_precedence(self):
        (self.root / 'report.pdf').write_bytes(_PDF_SENTINEL)
        # Registered-path admission precedes the format boundary.
        _, bad_path = await self.wire(path='../escape.pdf')
        self.assertEqual(bad_path['error_type'], 'InvalidPath')
        # Existing argument/hash-syntax validation also precedes the boundary.
        for args, expected in [({'path': 'report.pdf', 'offset': -1}, 'InvalidOffset'),
                               ({'path': 'report.pdf', 'limit': 0}, 'InvalidLimit'),
                               ({'path': 'report.pdf', 'start_line': 0}, 'InvalidStartLine'),
                               ({'path': 'report.pdf', 'end_line': 0}, 'InvalidEndLine'),
                               ({'path': 'report.pdf', 'expected_sha256': 'bad'}, 'InvalidExpectedSHA256')]:
            with self.subTest(args=args):
                _, result = await self.wire(**args)
                self.assertEqual(result['error_type'], expected)
        # A missing *.pdf is format-refused before existence/body/hash checks;
        # this claims suffix admission only, never that bytes were inspected.
        _, missing = await self.wire(path='absent.pdf')
        self.assertEqual(missing['error_type'], 'UnsupportedReadFormat')
        self.assertNotIn('file_sha256', missing)

    async def test_other_binary_errors_remain_with_attachment_preparation_guidance(self):
        (self.root / 'binary.dat').write_bytes(b'\x00\x01binary')
        (self.root / 'latin.txt').write_bytes(b'caf\xe9 not utf-8')
        for name in ('binary.dat', 'latin.txt'):
            with self.subTest(name=name):
                _, result = await self.wire(path=name)
                self.assertEqual(result['error_type'], 'BinaryFileUnsupported')
                self.assertTrue(result['binary'])
                self.assertIn('use prepare_file_attachment to prepare the original', result['error'])
                self.assertNotIn('content', result)
