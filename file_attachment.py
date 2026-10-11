"""Experimental original-byte attachment through opaque, process-local MCP resources."""
from __future__ import annotations

from dataclasses import dataclass
import json
import mimetypes
import re
import secrets
import time

from mcp.server.lowlevel.helper_types import ReadResourceContents
from mcp.server.mcpserver.exceptions import ResourceNotFoundError
from mcp.types import CallToolResult, ResourceLink, TextContent, ToolAnnotations

from file_observation import (
    FileObservation, FilePart, ObservationError, _hash_regular_file_parts,
    _read_regular_file_part, _target_key, error, path_parts,
)

# Raw resource size leaves room for base64 and protocol overhead in the tunnel.
MAX_ATTACH_PART_BYTES = 7 * 1024 * 1024
ATTACH_TTL_SECONDS = 15 * 60
ATTACH_RESOURCE_PREFIX = 'bridge://attach/'
ATTACH_RESOURCE_TEMPLATE = ATTACH_RESOURCE_PREFIX + '{capability}'
ATTACH_PART_RESOURCE_TEMPLATE = ATTACH_RESOURCE_TEMPLATE + '/part/{part_index}'


@dataclass(frozen=True)
class PendingAttachment:
    project_ref: str
    work_ref: str | None
    path: str
    target_key: tuple
    sha256: str
    byte_size: int
    mime_type: str
    name: str
    file_binding: tuple
    parts: tuple[FilePart, ...]
    expires_at: float


class PendingAttachments:
    """Event-loop-owned metadata lookup; reads never renew internal expiry."""
    def __init__(self, *, clock=time.monotonic):
        self.clock = clock
        self.entries: dict[str, PendingAttachment] = {}

    def _prune(self) -> None:
        now = self.clock()
        for token, entry in list(self.entries.items()):
            if now >= entry.expires_at:
                del self.entries[token]

    def issue(self, **binding) -> tuple[str, PendingAttachment]:
        self._prune()
        token = secrets.token_urlsafe(32)
        while token in self.entries:
            token = secrets.token_urlsafe(32)
        entry = PendingAttachment(**binding, expires_at=self.clock() + ATTACH_TTL_SECONDS)
        self.entries[token] = entry
        return token, entry

    def get(self, token: str) -> PendingAttachment:
        self._prune()
        entry = self.entries.get(token)
        if entry is None:
            raise ResourceNotFoundError('Attachment capability unavailable; no file bytes returned.')
        return entry


def _public_error(result: dict) -> dict:
    # Resolver messages can include checkout roots. Attachment never forwards them.
    kind = result.get('error_type', 'AttachmentUnavailable')
    if not isinstance(kind, str) or re.fullmatch(r'[A-Za-z][A-Za-z0-9]{0,79}', kind) is None:
        kind = 'AttachmentUnavailable'
    return error(kind, 'Attachment unavailable; no file bytes returned.')


def _text(metadata: dict) -> TextContent:
    return TextContent(type='text', text=json.dumps(metadata, ensure_ascii=False, separators=(',', ':')))


def _part_name(name: str, sha256: str, index: int, count: int) -> str:
    suffix = f'.bridge-{sha256[:12]}-part-{index:04d}-of-{count:04d}'
    prefix = name.encode('utf-8')[:255 - len(suffix)].decode('utf-8', errors='ignore')
    return prefix + suffix


class FileAttachment(FileObservation):
    def __init__(self, resolve_target, access_gate, *, store=None):
        super().__init__(resolve_target, access_gate)
        self.store = store if store is not None else PendingAttachments()

    async def prepare_file_attachment(self, project_ref: str, path: str, work_ref: str | None = None,
                          expected_sha256: str | None = None) -> CallToolResult:
        """Hash the current bytes of an existing project file and prepare expiring
        ResourceLinks for a later resources/read fetch; nothing is uploaded,
        host-imported, assembled, or attached yet.

        Up to 7 MiB: one original-name/MIME link. Larger files: ordered 7 MiB parts
        and one receipt: multipart {target, size, sha256, parts} with ordered part names.
        The recipient concatenates parts and verifies full SHA-256 and size.
        Registered project/frozen Work only; no links, special files or parsing.
        Optional lowercase SHA-256 pins original bytes.
        """
        binding = {}
        try:
            parts = path_parts(path)
            if expected_sha256 is not None and (not isinstance(expected_sha256, str)
                    or re.fullmatch(r'[0-9a-f]{64}', expected_sha256) is None):
                raise ObservationError('InvalidExpectedSHA256', 'Use a lowercase full-file SHA-256 hex digest.')

            def prepare(target):
                metadata, file_binding, descriptors = _hash_regular_file_parts(
                    target, path, part_bytes=MAX_ATTACH_PART_BYTES)
                if expected_sha256 is not None and metadata['sha256'] != expected_sha256:
                    raise ObservationError('ReadVersionChanged', 'File differs from expected_sha256.')
                binding.update(target_key=_target_key(target), sha256=metadata['sha256'],
                               byte_size=metadata['byte_size'], file_binding=file_binding,
                               parts=descriptors)
                return metadata

            metadata = await self._observe(project_ref, work_ref, prepare)
        except ObservationError as exc:
            metadata = error(exc.kind, exc.message)
        except Exception:
            # SDK tool errors otherwise stringify exceptions, possibly exposing roots.
            metadata = error('AttachmentPreparationFailed', 'Attachment preparation unavailable.')
        if not metadata.get('ok'):
            return CallToolResult(content=[_text(_public_error(metadata))], isError=True)

        # Mint only after the observer's final binding check succeeds. Retain no bytes.
        name = parts[-1]
        mime = mimetypes.guess_type(name)[0] or 'application/octet-stream'
        token, entry = self.store.issue(project_ref=project_ref, work_ref=work_ref,
                                       path=path, name=name, mime_type=mime, **binding)
        count = len(entry.parts)
        links = []
        for part in entry.parts:
            single = count == 1
            uri = ATTACH_RESOURCE_TEMPLATE.format(capability=token) if single else (
                ATTACH_PART_RESOURCE_TEMPLATE.format(capability=token, part_index=f'{part.index:04d}'))
            links.append(ResourceLink(type='resource_link', uri=uri,
                name=name if single else _part_name(name, entry.sha256, part.index, count),
                mimeType=mime if single else 'application/octet-stream', size=part.length,
                description='Original bytes.' if single else 'Original file part.'))
        if count == 1:
            return CallToolResult(content=links)
        return CallToolResult(content=[*links, _text({'multipart': {
            'target': name, 'size': entry.byte_size, 'sha256': entry.sha256,
            'parts': [link.name for link in links]}})])

    async def read_attachment(self, capability: str) -> bytes:
        """Stable single-resource route; multipart groups require a part ordinal."""
        entry = self.store.get(capability)
        if len(entry.parts) != 1:
            raise ResourceNotFoundError('Attachment requires a part URI; no file bytes returned.')
        return await self._read_part(capability, 1)

    async def read_part(self, capability: str, part_index: str) -> bytes:
        if re.fullmatch(r'(?:[0-9]{4}|[1-9][0-9]{4,})', part_index) is None:
            raise ResourceNotFoundError('Attachment part unavailable; no file bytes returned.')
        entry = self.store.get(capability)
        if len(entry.parts) == 1:
            raise ResourceNotFoundError('Attachment requires its single URI; no file bytes returned.')
        return await self._read_part(capability, int(part_index))

    async def _read_part(self, capability: str, index: int) -> bytes:
        entry = self.store.get(capability)
        if not 1 <= index <= len(entry.parts):
            raise ResourceNotFoundError('Attachment part unavailable; no file bytes returned.')
        part = entry.parts[index - 1]
        payload = None

        def fetch(target):
            nonlocal payload
            if _target_key(target) != entry.target_key:
                raise ObservationError('TargetChanged', 'Attachment checkout binding changed.')
            payload = _read_regular_file_part(target, entry.path, file_binding=entry.file_binding,
                byte_size=entry.byte_size, part=part, max_part_bytes=MAX_ATTACH_PART_BYTES)
            return {'ok': True}

        try:
            metadata = await self._observe(entry.project_ref, entry.work_ref, fetch)
        except Exception:
            raise ResourceNotFoundError('Attachment target unavailable; no file bytes returned.') from None
        # A wait for reader admission or observation may cross internal expiry.
        if self.store.get(capability) is not entry:
            raise ResourceNotFoundError('Attachment capability unavailable; no file bytes returned.')
        if not metadata.get('ok') or payload is None:
            raise ResourceNotFoundError('Attachment target unavailable or changed; no file bytes returned.')
        return payload

    async def read_resource(self, uri: str) -> list[ReadResourceContents]:
        """SDK read_resource adapter preserving the capability's exact MIME hint."""
        match = re.fullmatch(re.escape(ATTACH_RESOURCE_PREFIX) +
                            r'([A-Za-z0-9_-]{43})(?:/part/([0-9]{4}|[1-9][0-9]{4,}))?', uri)
        if match is None:
            raise ResourceNotFoundError('Attachment capability unavailable; no file bytes returned.')
        capability = match[1]
        entry = self.store.get(capability)
        raw = await self.read_attachment(capability) if match[2] is None else (
            await self.read_part(capability, match[2]))
        return [ReadResourceContents(content=raw,
            mime_type=entry.mime_type if len(entry.parts) == 1 else 'application/octet-stream')]


def register_file_attachment(mcp, resolve_target, access_gate) -> FileAttachment:
    service = FileAttachment(resolve_target, access_gate)
    mcp._file_attachment_service = service
    # Discovery template has a generic binary hint. Bridge's read_resource override
    # routes this namespace to read_resource above for per-response MIME support.
    mcp.resource(ATTACH_RESOURCE_TEMPLATE, name='bridge-attachment-artifact',
                 description='Prepared original file bytes.',
                 mime_type='application/octet-stream')(service.read_attachment)
    mcp.resource(ATTACH_PART_RESOURCE_TEMPLATE, name='bridge-attachment-part',
                 description='Ordered original file part.',
                 mime_type='application/octet-stream')(service.read_part)
    mcp.tool(name='prepare_file_attachment', structured_output=False,
             annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False,
                                         openWorldHint=False, idempotentHint=False))(service.prepare_file_attachment)
    return service
