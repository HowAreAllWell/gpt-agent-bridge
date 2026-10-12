"""Descriptor-bound exact text replacement; adapter supplies scope and writer gate."""
import hashlib
import os
import re
import secrets
import stat

from pydantic import ConfigDict, with_config
from typing_extensions import TypedDict
from .file_observation import _Walk, _FILE_FLAGS, _signature, ObservationError, error, path_parts

MAX_TEXT_BYTES = 1024 * 1024
MAX_EDITS = 256


@with_config(ConfigDict(extra='forbid', strict=True))
class TextEdit(TypedDict):
    old_text: str
    new_text: str


def exact_edits(original, edits):
    if not isinstance(edits, list) or not 1 <= len(edits) <= MAX_EDITS:
        raise ObservationError('InvalidEdits', 'Supply 1..256 exact edits.')
    spans, budget = [], 0
    for edit in edits:
        if (not isinstance(edit, dict) or set(edit) != {'old_text', 'new_text'}
                or not isinstance(edit['old_text'], str) or not edit['old_text']
                or not isinstance(edit['new_text'], str)):
            raise ObservationError('InvalidEdits', 'Each edit requires nonempty old_text and string new_text only.')
        try:
            old, new = edit['old_text'].encode('utf-8'), edit['new_text'].encode('utf-8')
        except UnicodeError:
            raise ObservationError('InvalidUTF8', 'Edits must be valid UTF-8.') from None
        budget += len(old) + len(new)
        if budget > 2 * MAX_TEXT_BYTES or b'\0' in new:
            raise ObservationError('InvalidEdits', 'Edit bytes exceed the text budget or contain NUL.')
        start = original.find(old)
        if start < 0 or original.find(old, start + 1) >= 0:
            raise ObservationError('EditMismatch', 'Each old_text must match exactly once in the original.')
        spans.append((start, start + len(old), new))
    spans.sort()
    if any(a[1] > b[0] for a, b in zip(spans, spans[1:])):
        raise ObservationError('EditOverlap', 'Edits overlap in the original.')
    result, end = [], 0
    for start, stop, new in spans:
        result.extend((original[end:start], new))
        end = stop
    result.append(original[end:])
    if sum(map(len, result)) > MAX_TEXT_BYTES:
        raise ObservationError('TextTooLarge', 'Result exceeds the 1 MiB text limit.')
    return b''.join(result)


def read_bound(walk, name):
    fd = os.open(name, _FILE_FLAGS, dir_fd=walk.fd)
    try:
        before = os.fstat(fd)
        if not stat.S_ISREG(before.st_mode):
            raise ObservationError('RegularFileRequired', 'Only existing regular files are supported.')
        if before.st_size > MAX_TEXT_BYTES:
            raise ObservationError('TextTooLarge', 'File exceeds the 1 MiB text limit.')
        chunks, size = [], 0
        while True:
            chunk = os.read(fd, min(65536, MAX_TEXT_BYTES + 1 - size))
            if not chunk:
                break
            chunks.append(chunk); size += len(chunk)
            if size > MAX_TEXT_BYTES:
                raise ObservationError('TextTooLarge', 'File exceeds the 1 MiB text limit.')
        if (_signature(before) != _signature(os.fstat(fd))
                or _signature(before) != _signature(os.stat(name, dir_fd=walk.fd, follow_symlinks=False))):
            raise ObservationError('PathChanged', 'File changed during its bounded read.')
        walk.verify()
        return b''.join(chunks), before
    finally:
        os.close(fd)


def text_edit(target, path, expected_sha256, edits):
    replaced, attempted, temporary = False, False, None
    old_hash = new_hash = None
    try:
        if not isinstance(expected_sha256, str) or not re.fullmatch('[0-9a-f]{64}', expected_sha256):
            raise ObservationError('InvalidHash', 'Supply the full lowercase SHA256 of the original bytes.')
        parts = path_parts(path)
        if any(p in ('', '.', '..', '.git') for p in path.split('/')) or '\\' in path:
            raise ObservationError('InvalidPath', 'Use a literal repository-relative file path.')
        with _Walk(target, parts[:-1]) as walk:
            try:
                original, source = read_bound(walk, parts[-1])
                old_hash = hashlib.sha256(original).hexdigest()
                if old_hash != expected_sha256:
                    raise ObservationError('StaleHash', 'File hash differs; nothing written.')
                try:
                    original.decode('utf-8')
                except UnicodeError:
                    raise ObservationError('InvalidUTF8', 'File is not UTF-8 text.') from None
                if b'\0' in original:
                    raise ObservationError('BinaryRejected', 'NUL-containing files are excluded.')
                result = exact_edits(original, edits)
                new_hash = hashlib.sha256(result).hexdigest()
                temporary = '.bridge-text-edit-' + secrets.token_hex(16) + '.tmp'
                fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                             0o600, dir_fd=walk.fd)
                try:
                    pending = memoryview(result)
                    while pending:
                        written = os.write(fd, pending)
                        if written <= 0:
                            raise OSError('short-write')
                        pending = pending[written:]
                    os.fchmod(fd, stat.S_IMODE(source.st_mode))
                    os.fsync(fd)
                finally:
                    os.close(fd)
                # Cooperating writers are gated by the adapter. External writers
                # cannot be locked by Bridge: compare complete bytes and binding
                # immediately before replace, never claim filesystem-wide CAS.
                current, current_stat = read_bound(walk, parts[-1])
                if (hashlib.sha256(current).hexdigest() != old_hash
                        or _signature(source) != _signature(current_stat)):
                    raise ObservationError('StaleHash', 'File changed before replacement; nothing written.')
                walk.verify()
                attempted = True
                os.replace(temporary, parts[-1], src_dir_fd=walk.fd, dst_dir_fd=walk.fd)
                replaced = True
                os.fsync(walk.fd)
                walk.verify()
                observed, observed_stat = read_bound(walk, parts[-1])
                if observed != result or stat.S_IMODE(observed_stat.st_mode) != stat.S_IMODE(source.st_mode):
                    raise ObservationError('WriteUnconfirmed', 'Post-write bytes or mode differ; do not retry.')
            finally:
                if temporary:
                    try:
                        os.unlink(temporary, dir_fd=walk.fd)
                    except FileNotFoundError:
                        pass
        return {'ok': True, 'status': 'edited', 'path': path, **target.provenance(),
                'old_sha256': old_hash, 'new_sha256': new_hash,
                'old_bytes': len(original), 'new_bytes': len(result), 'edit_count': len(edits),
                'file_replaced': True}
    except Exception as exc:
        kind = exc.kind if isinstance(exc, ObservationError) else 'TextEditFailed'
        message = exc.message if isinstance(exc, ObservationError) else 'Safe file replacement could not be completed.'
        return {**error(kind, message), 'status': 'unknown' if attempted else 'rejected',
                'file_replaced': True if replaced else None if attempted else False,
                'old_sha256': old_hash, 'new_sha256': new_hash, **target.provenance()}
