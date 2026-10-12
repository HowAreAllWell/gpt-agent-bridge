"""Narrow descriptor-bound observations; authority comes from EvidenceTarget.

No discovery, registry writes, shell, recursive file reads or content responses.
Use FileObservation with the server's existing resolver and reader gate. A caller
using the synchronous helpers directly must supply a freshly validated target.
"""
from __future__ import annotations

import asyncio
from contextlib import contextmanager
from dataclasses import dataclass
import errno
import hashlib
import json
import os
from os import read as _read_chunk
from pathlib import Path
import stat
import time
from typing import Any, Callable

from .evidence_target import EvidenceTarget

MAX_ENTRIES = 4096
MAX_NAMES_BYTES = 1024 * 1024
MAX_PAGE_ENTRIES = 100
MAX_JSON_BYTES = 32768
MAX_PATH_BYTES = 4096
MAX_FILE_BYTES = 64 * 1024 * 1024
CHUNK_BYTES = 65536
OBSERVATION_SECONDS = 10.0
_DIR_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
_FILE_FLAGS = os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW | os.O_CLOEXEC


class ObservationError(Exception):
    def __init__(self, kind: str, message: str):
        self.kind, self.message = kind, message
        super().__init__(message)


def error(kind: str, message: str) -> dict:
    # Messages are fixed/bounded, never raw filenames, subprocess output or content.
    return {'ok': False, 'error_type': kind, 'error': message[:300]}


def json_size(value: dict) -> int:
    # Conservative ASCII JSON budget includes escaped LF/quotes/non-ASCII names.
    return len(json.dumps(value, ensure_ascii=True).encode('ascii'))


def path_parts(path: str, *, directory: bool = False) -> list[str]:
    if not isinstance(path, str) or not path or '\0' in path:
        raise ObservationError('InvalidPath', 'Use a non-empty relative path without NUL.')
    try:
        if len(path.encode('utf-8')) > MAX_PATH_BYTES:
            raise ObservationError('InvalidPath', 'Path exceeds the byte limit; names are never truncated.')
    except UnicodeError:
        raise ObservationError('InvalidPath', 'Path must be valid UTF-8.') from None
    raw = Path(path)
    if raw.is_absolute() or any(p in ('..', '.git') for p in raw.parts):
        raise ObservationError('InvalidPath', 'Absolute, parent traversal and .git paths are excluded.')
    parts = list(raw.parts)
    if not parts and not directory:
        raise ObservationError('InvalidPath', 'A regular file path is required.')
    return parts


def _signature(s: os.stat_result) -> tuple:
    return (s.st_dev, s.st_ino, s.st_mode, s.st_nlink, s.st_size, s.st_mtime_ns, s.st_ctime_ns)


def _identity(s: os.stat_result) -> tuple:
    return s.st_dev, s.st_ino, s.st_mode


def _io_error(exc: OSError) -> dict:
    kind = {errno.ENOENT: 'PathUnavailable', errno.ELOOP: 'SymlinkRejected',
            errno.ENOTDIR: 'DirectoryOrLinkRejected', errno.EACCES: 'PermissionDenied',
            errno.EPERM: 'PermissionDenied'}.get(exc.errno, 'ObservationFailed')
    return error(kind, 'Path could not be observed without following links or crossing its binding.')


def _deadline(end: float) -> None:
    if time.monotonic() > end:
        raise ObservationError('ObservationTimedOut', 'Observation deadline reached; coverage is unknown.')


class _Walk:
    def __init__(self, target: EvidenceTarget, parts: list[str]):
        self.root = target.workspace.root
        expected = target.workspace.git
        if expected is None:
            raise ObservationError('TargetIdentityUnavailable', 'A registered Git checkout identity is required.')
        self.fds: list[int] = []
        self.bindings: list[tuple[int, str, tuple]] = []
        try:
            root_fd = os.open(self.root, _DIR_FLAGS)
            self.fds.append(root_fd)
            root_stat = os.fstat(root_fd)
            if (root_stat.st_dev, root_stat.st_ino) != (expected.root_device, expected.root_inode):
                raise ObservationError('TargetChanged', 'Opened root differs from the authorized checkout.')
            self.root_identity = _identity(root_stat)
            for part in parts:
                parent = self.fds[-1]
                before = os.stat(part, dir_fd=parent, follow_symlinks=False)
                if stat.S_ISLNK(before.st_mode):
                    raise ObservationError('SymlinkRejected', 'Directory links are not followed by this observer.')
                fd = os.open(part, _DIR_FLAGS, dir_fd=parent)
                self.fds.append(fd)
                if _identity(before) != _identity(os.fstat(fd)):
                    raise ObservationError('PathChanged', 'Directory binding changed during open.')
                self.bindings.append((parent, part, _identity(before)))
        except BaseException:
            self.close()
            raise

    @property
    def fd(self) -> int:
        return self.fds[-1]

    def verify(self) -> None:
        if _identity(os.stat(self.root, follow_symlinks=False)) != self.root_identity:
            raise ObservationError('TargetChanged', 'Root path binding changed during observation.')
        for parent, name, identity in self.bindings:
            if _identity(os.stat(name, dir_fd=parent, follow_symlinks=False)) != identity:
                raise ObservationError('PathChanged', 'Directory path binding changed during observation.')

    def close(self) -> None:
        for fd in reversed(self.fds):
            os.close(fd)
        self.fds.clear()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


def _type(mode: int) -> str:
    if stat.S_ISLNK(mode): return 'link'
    if stat.S_ISREG(mode): return 'file'
    if stat.S_ISDIR(mode): return 'directory'
    return 'special'


def _list_entries(target: EvidenceTarget, path: str, offset: int, limit: int) -> dict:
    parts = path_parts(path, directory=True)
    end = time.monotonic() + OBSERVATION_SECONDS
    with _Walk(target, parts) as walk:
        before = os.fstat(walk.fd)
        names = []
        total_bytes = 0
        # Only names retained. Stop on the first entry beyond a fixed scan cap;
        # do not sort/materialize an arbitrarily large directory for one page.
        with os.scandir(walk.fd) as iterator:
            scanned = 0
            for entry in iterator:
                _deadline(end)
                scanned += 1
                if scanned > MAX_ENTRIES:
                    raise ObservationError('DirectoryTooLarge', 'Direct-entry scan cap exceeded; use a narrower directory.')
                if entry.name == '.git':
                    continue
                try:
                    raw = entry.name.encode('utf-8')
                except UnicodeError:
                    raise ObservationError('PathEncodingUnsupported', 'A directory name is not valid UTF-8; no complete page is claimed.') from None
                total_bytes += len(raw)
                if total_bytes > MAX_NAMES_BYTES:
                    raise ObservationError('DirectoryTooLarge', 'Directory name-byte cap exceeded; no complete page is claimed.')
                names.append(entry.name)
        names.sort()
        result = {'ok': True, 'path': path, 'entries': [],
                  'pagination': {'offset': offset, 'next_offset': None, 'unit': 'entries', 'order': 'unicode_name'},
                  'coverage': {'scope': 'direct_children', 'recursive': False, 'git_internal': 'excluded',
                               'tracking_filter': 'none', 'total_entries': len(names), 'scan_complete': True}}
        # Reserve bounded envelope room. Final facade verifies the actual total.
        entry_budget = MAX_JSON_BYTES - 8192
        for name in names[offset:offset + limit]:
            _deadline(end)
            s = os.stat(name, dir_fd=walk.fd, follow_symlinks=False)
            # './' makes even all-whitespace root filenames reusable by read.
            rel = '/'.join(parts + [name]) if parts else './' + name
            path_parts(rel)
            item = {'path': rel, 'name': name, 'type': _type(s.st_mode)}
            result['entries'].append(item)
            if json_size(result) > entry_budget:
                result['entries'].pop()
                if not result['entries']:
                    raise ObservationError('ResponseTooLarge', 'One complete path does not fit the response budget.')
                break
        if offset + len(result['entries']) < len(names):
            result['pagination']['next_offset'] = offset + len(result['entries'])
        if _signature(before) != _signature(os.fstat(walk.fd)):
            raise ObservationError('DirectoryChanged', 'Directory changed while enumerating; retry a fresh observation.')
        walk.verify()
        return result


@contextmanager
def _open_regular_file(target: EvidenceTarget, path: str, *, max_bytes: int | None):
    """Own a no-follow descriptor and verify its stat/path binding on successful exit."""
    parts = path_parts(path)
    with _Walk(target, parts[:-1]) as walk:
        initial = os.stat(parts[-1], dir_fd=walk.fd, follow_symlinks=False)
        if stat.S_ISLNK(initial.st_mode):
            raise ObservationError('SymlinkRejected', 'Only known regular files are hashed; links are not followed.')
        if not stat.S_ISREG(initial.st_mode):
            raise ObservationError('NotARegularFile', 'Only regular files can be hashed; no special file is opened.')
        if max_bytes is not None and initial.st_size > max_bytes:
            raise ObservationError('FileTooLarge', 'File exceeds the byte limit; no bytes or full hash returned.')
        fd = os.open(parts[-1], _FILE_FLAGS, dir_fd=walk.fd)
        try:
            before = os.fstat(fd)
            if not stat.S_ISREG(before.st_mode) or _signature(initial) != _signature(before):
                raise ObservationError('FileChanged', 'File changed during open; no full hash is claimed.')
            yield walk, fd, before
            after = os.fstat(fd)
            bound = os.stat(parts[-1], dir_fd=walk.fd, follow_symlinks=False)
            if _signature(before) != _signature(after) or _signature(after) != _signature(bound):
                raise ObservationError('FileChanged', 'File content/stat or path binding changed; no bytes returned.')
            walk.verify()
        finally:
            os.close(fd)


def _file_binding(walk: _Walk, info: os.stat_result) -> tuple:
    return (_signature(info), walk.root_identity, tuple(identity for _, _, identity in walk.bindings))


def _file_metadata(path: str, info: os.stat_result, count: int, sha256: str) -> dict:
    return {'ok': True, 'path': path, 'mode': format(stat.S_IMODE(info.st_mode), '04o'),
            'byte_size': count, 'sha256': sha256,
            'coverage': {'hash': 'full_original_bytes', 'file_type': 'regular',
                         'checks': 'pre_post_stat_and_path_binding'}}


def _read_regular_file(target: EvidenceTarget, path: str, *, max_bytes: int,
                       retain_bytes: bool = False) -> tuple[dict, bytes | None]:
    """Shared stat/binding-checked hash, optionally retaining bounded original bytes."""
    end = time.monotonic() + OBSERVATION_SECONDS
    with _open_regular_file(target, path, max_bytes=max_bytes) as (_, fd, before):
        digest = hashlib.sha256()
        count = 0
        chunks = []
        while True:
            _deadline(end)
            chunk = _read_chunk(fd, min(CHUNK_BYTES, max_bytes + 1 - count))
            if not chunk:
                break
            count += len(chunk)
            if count > max_bytes:
                raise ObservationError('FileTooLarge', 'File grew past the hash limit; no full hash is claimed.')
            digest.update(chunk)
            if retain_bytes:
                chunks.append(chunk)
        if count != before.st_size:
            raise ObservationError('FileChanged', 'File content/stat or path binding changed; no full hash is claimed.')
        metadata = _file_metadata(path, before, count, digest.hexdigest())
    return metadata, b''.join(chunks) if retain_bytes else None


@dataclass(frozen=True)
class FilePart:
    index: int
    offset: int
    length: int
    sha256: str


def _hash_regular_file_parts(target: EvidenceTarget, path: str, *,
                             part_bytes: int) -> tuple[dict, tuple, tuple[FilePart, ...]]:
    """Hash once in bounded reads, retaining only an immutable part manifest."""
    end = time.monotonic() + OBSERVATION_SECONDS
    with _open_regular_file(target, path, max_bytes=None) as (walk, fd, before):
        binding = _file_binding(walk, before)
        digest, part_digest = hashlib.sha256(), hashlib.sha256()
        count = length = 0
        parts = []
        while True:
            _deadline(end)
            block = _read_chunk(fd, min(CHUNK_BYTES, part_bytes - length))
            if not block:
                break
            count += len(block)
            digest.update(block)
            part_digest.update(block)
            length += len(block)
            if length == part_bytes:
                parts.append(FilePart(len(parts) + 1, count - length, length, part_digest.hexdigest()))
                length = 0
                part_digest = hashlib.sha256()
        if length or not parts:
            parts.append(FilePart(len(parts) + 1, count - length, length, part_digest.hexdigest()))
        if count != before.st_size:
            raise ObservationError('FileChanged', 'File size changed during preparation.')
        metadata = _file_metadata(path, before, count, digest.hexdigest())
    return metadata, binding, tuple(parts)


def _read_regular_file_part(target: EvidenceTarget, path: str, *, file_binding: tuple,
                            byte_size: int, part: FilePart, max_part_bytes: int) -> bytes:
    """Read only a pinned part; saved file and directory identities precede any bytes."""
    if not 0 <= part.length <= max_part_bytes or not 0 <= part.offset <= byte_size - part.length:
        raise ObservationError('InvalidPart', 'Attachment part is unavailable.')
    end = time.monotonic() + OBSERVATION_SECONDS
    with _open_regular_file(target, path, max_bytes=byte_size) as (walk, fd, before):
        if before.st_size != byte_size or _file_binding(walk, before) != file_binding:
            raise ObservationError('ReadVersionChanged', 'Attachment source binding changed.')
        os.lseek(fd, part.offset, os.SEEK_SET)
        digest = hashlib.sha256()
        blocks = []
        count = 0
        while count < part.length:
            _deadline(end)
            block = _read_chunk(fd, min(CHUNK_BYTES, part.length - count))
            if not block:
                raise ObservationError('FileChanged', 'Attachment part length changed.')
            count += len(block)
            digest.update(block)
            blocks.append(block)
        if digest.hexdigest() != part.sha256:
            raise ObservationError('ReadVersionChanged', 'Attachment part bytes changed.')
    return b''.join(blocks)


def _inspect_file(target: EvidenceTarget, path: str) -> dict:
    return _read_regular_file(target, path, max_bytes=MAX_FILE_BYTES)[0]


def _target_key(target: EvidenceTarget) -> tuple:
    return (target.project.workspace_ref, target.project.root, target.project.git,
            target.workspace.root, target.workspace.git, target.work_ref)


def _envelope(result: dict, target: EvidenceTarget) -> dict:
    if not result.get('ok'):
        return result
    result['provenance'] = {**target.provenance(), 'observed_at': time.time(),
                            'observation_mode': 'fresh_filesystem', 'atomic_snapshot': False}
    if json_size(result) > MAX_JSON_BYTES:
        return error('ResponseTooLarge', 'Complete result exceeds the serialized JSON budget; names are never truncated.')
    return result


class FileObservation:
    """Two direct tools sharing existing target authority and admission gates."""
    def __init__(self, resolve_target: Callable, access_gate: Callable):
        self.resolve_target, self.access_gate = resolve_target, access_gate

    async def _observe(self, project_ref, work_ref, operation, *args):
        if not isinstance(project_ref, str) or not project_ref or len(project_ref) > 64:
            return error('InvalidProjectRef', 'Use a registered project reference.')
        if work_ref is not None and (not isinstance(work_ref, str) or not work_ref or len(work_ref) > 256):
            return error('InvalidWorkRef', 'Use a recorded Work reference.')
        resolved = self.resolve_target(project_ref, work_ref)
        if isinstance(resolved, dict):
            return error(str(resolved.get('error_type', 'TargetUnavailable'))[:80], str(resolved.get('error', 'Target unavailable.')))
        lease = await self.access_gate(resolved.workspace.root).acquire('reader')
        try:
            checked = self.resolve_target(project_ref, work_ref)
            if isinstance(checked, dict) or _target_key(checked) != _target_key(resolved):
                return error('TargetChanged', 'Target changed during reader admission.')
            # Cancellation must not release the gate while a worker still reads.
            task = asyncio.create_task(asyncio.to_thread(operation, resolved, *args))
            try:
                result = await asyncio.shield(task)
            except asyncio.CancelledError as cancellation:
                while not task.done():
                    try:
                        await asyncio.shield(task)
                    except asyncio.CancelledError:
                        continue
                    except Exception:
                        # The worker is finished with an error. Retrieve it below;
                        # it must not replace the caller's original cancellation.
                        break
                if not task.cancelled():
                    task.exception()  # Retrieve a worker error; caller cancellation wins.
                raise cancellation
            checked = self.resolve_target(project_ref, work_ref)
            if isinstance(checked, dict) or _target_key(checked) != _target_key(resolved):
                return error('TargetChanged', 'Target changed during observation.')
            return _envelope(result, resolved)
        except ObservationError as exc:
            return error(exc.kind, exc.message)
        except OSError as exc:
            return _io_error(exc)
        finally:
            await lease.release()

    async def list_entries(self, project_ref: str, path: str = '.', work_ref: str | None = None,
                           offset: int = 0, limit: int = 50) -> dict[str, Any]:
        """List one directory's direct children with complete literal names and types.

        limit is 1..100; scan caps are 4096 entries/1 MiB names. .git is excluded.
        Links are listed, not followed. Continue next_offset; pages are fresh observations.
        """
        try:
            path_parts(path, directory=True)
            if type(offset) is not int or not 0 <= offset <= MAX_ENTRIES:
                raise ObservationError('InvalidOffset', 'Offset must be an integer from 0 through 4096.')
            if type(limit) is not int or not 1 <= limit <= MAX_PAGE_ENTRIES:
                raise ObservationError('InvalidLimit', 'Limit must be an integer from 1 through 100.')
        except ObservationError as exc:
            return error(exc.kind, exc.message)
        return await self._observe(project_ref, work_ref, _list_entries, path, offset, limit)

    async def inspect_file(self, project_ref: str, path: str, work_ref: str | None = None) -> dict[str, Any]:
        """Hash up to 64 MiB of a known regular file; return mode/size/SHA, no body."""
        try:
            path_parts(path)
        except ObservationError as exc:
            return error(exc.kind, exc.message)
        return await self._observe(project_ref, work_ref, _inspect_file, path)


def register_file_observation(mcp, resolve_target: Callable, access_gate: Callable) -> FileObservation:
    """Call once after the server's resolver/gate definitions and before mcp.run."""
    from mcp.types import ToolAnnotations
    service = FileObservation(resolve_target, access_gate)
    annotations = ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=False, idempotentHint=True)
    mcp.tool(name='list_entries', annotations=annotations)(service.list_entries)
    mcp.tool(name='inspect_file', annotations=annotations)(service.inspect_file)
    # Installed MCP SDK exposes no argument-config option on @tool. Rebuild each
    # new tool's own runtime model AND its published schema before serving calls;
    # schema-only additionalProperties would still silently ignore selectors.
    from .tool_presentation import forbid_extra_arguments
    forbid_extra_arguments(mcp, ('list_entries', 'inspect_file'))
    return service
