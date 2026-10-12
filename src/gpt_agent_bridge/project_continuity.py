"""Repository-local continuity: bounded pointers and conditional state replacement.

No history engine or truth promotion. The caller resolves the project and holds
its existing writer gate throughout checkpoint publication.
"""
from __future__ import annotations

import ctypes
import errno
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import stat
from typing import Any, Callable

from .workspace_context import WorkspaceContext

_NOFOLLOW_DIR_OPEN_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
_NOFOLLOW_FILE_OPEN_FLAGS = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC
PROJECT_MANIFEST_PATH = ".principal/project.json"
_MANIFEST_REQUIRED_KEYS = frozenset({"rules", "current_state", "memory"})
_MANIFEST_ALLOWED_KEYS = _MANIFEST_REQUIRED_KEYS
MAX_PROJECT_MANIFEST_BYTES = 8192
MAX_PROJECT_POINTERS = 16
MAX_PROJECT_PATH_CHARS = 512
MAX_CHECKPOINT_CONTENT_BYTES = 65536
CHECKPOINT_MISSING_REVISION = "missing"
PRINCIPAL_DIR = ".principal"
PRINCIPAL_STATE_PATH = ".principal/state.md"
PRINCIPAL_MEMORY_PATH = ".principal/memory.md"
PRINCIPAL_RULES_PATH = ".principal/rules.md"
_INIT_SEED_KEYS = frozenset({
    "rules", "state_content", "memory_content", "project_rules_content",
})
_VALID_EXISTING_MANIFEST_STATUSES = frozenset({
    "ready",
    "current_state_missing",
    "current_state_unavailable",
    "canonical_pointer_unavailable",
})
_RENAME_NOREPLACE = 1
_AT_REMOVEDIR = 0x200
_CHECKPOINT_REVISION_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
# Generic opt-in whole-line slot; Bridge state does not opt in.
SLOT_LIMIT_MIN = 1024
SLOT_LIMIT_MAX = MAX_CHECKPOINT_CONTENT_BYTES
_SLOT_MARKER_LIKE_RE = re.compile(br"^<!--\s*bridge-state-slot\b.*-->\s*$")
_SLOT_START_RE = re.compile(br"^<!-- bridge-state-slot start limit=([1-9][0-9]*) -->$")
_SLOT_END_LINE = b"<!-- bridge-state-slot end -->"
_SLOT_REASONS = frozenset({
    "slot_malformed",
    "slot_removed",
    "slot_widened",
    "slot_narrowed",
    "slot_body_exceeds_limit",
})


def _manifest_relative_path(value: Any) -> tuple[str, list[str]]:
    """Validate one manifest-owned lexical repository path without resolving links."""
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or len(value) > MAX_PROJECT_PATH_CHARS
        or "\x00" in value
        or Path(value).is_absolute()
    ):
        raise ValueError("paths must be bounded non-empty relative strings")
    # JSON can decode escaped lone surrogates, but they are not UTF-8 paths.
    # Reject them here rather than leaking an encoding error from the file walk.
    value.encode("utf-8")
    parts = value.split("/")
    if (
        any(part in ("", ".", "..") for part in parts)
        or any(part == ".git" for part in parts)
        or "\\" in value
    ):
        raise ValueError("paths must not traverse, enter .git, or use ambiguous separators")
    return "/".join(parts), parts


def _terminated_lines(data: bytes) -> list[tuple[int, int, bytes]]:
    """Split on ``\\n`` / ``\\r\\n`` only. A bare CR stays inside the line.

    Each item is ``(start, end_including_terminator, content_without_terminator)``.
    """
    lines: list[tuple[int, int, bytes]] = []
    index = 0
    size = len(data)
    while index < size:
        newline = data.find(b"\n", index)
        if newline < 0:
            lines.append((index, size, data[index:]))
            break
        if newline > index and data[newline - 1:newline] == b"\r":
            content = data[index:newline - 1]
        else:
            content = data[index:newline]
        lines.append((index, newline + 1, content))
        index = newline + 1
    return lines


def _canonical_slot_limit(text: bytes) -> int | None:
    match = _SLOT_START_RE.fullmatch(text)
    if match is None:
        return None
    digits = match.group(1)
    # The grammar forbids leading zeros, so more digits than the maximum's
    # decimal form is always out of range. This keeps int() on a bounded
    # string regardless of the interpreter's integer digit limit.
    if len(digits) > len(str(SLOT_LIMIT_MAX).encode("ascii")):
        return None
    limit = int(digits)
    if SLOT_LIMIT_MIN <= limit <= SLOT_LIMIT_MAX:
        return limit
    return None


def classify_state_slot(data: bytes) -> dict[str, Any]:
    """Classify opt-in slot markers. Body length is not a malformation.

    A marker-like line is a whole line, excluding its LF or CRLF terminator,
    matching an HTML comment that begins with ``bridge-state-slot``. Valid
    markers are the exact ASCII start and end lines. The body is the exact
    byte slice after the start line's terminator and before the end line.
    Marker lines and bytes outside the pair are not body bytes. No nesting,
    escaping, or second slot is recognized.
    """
    lines = _terminated_lines(data)
    marker_indexes = [
        index for index, (_, _, content) in enumerate(lines)
        if _SLOT_MARKER_LIKE_RE.fullmatch(content)
    ]
    if not marker_indexes:
        return {"kind": "absent", "limit": None, "body_bytes": None}
    starts = [index for index in marker_indexes if _canonical_slot_limit(lines[index][2]) is not None]
    ends = [index for index in marker_indexes if lines[index][2] == _SLOT_END_LINE]
    extras = [index for index in marker_indexes if index not in starts and index not in ends]
    if extras or len(starts) != 1 or len(ends) != 1 or starts[0] > ends[0]:
        return {"kind": "malformed", "limit": None, "body_bytes": None}
    start = lines[starts[0]]
    end = lines[ends[0]]
    body = data[start[1]:end[0]]
    return {
        "kind": "valid",
        "limit": _canonical_slot_limit(start[2]),
        "body_bytes": len(body),
    }


def _slot_rejection(
    reason: str,
    message: str,
    *,
    slot_limit: int | None = None,
    slot_body_bytes: int | None = None,
    candidate_slot_limit: int | None = None,
) -> dict[str, Any]:
    if reason not in _SLOT_REASONS:
        raise ValueError(reason)
    result: dict[str, Any] = {
        "ok": False,
        "error_type": "CheckpointSlotRejected",
        "slot_reason": reason,
        "error": message,
    }
    if slot_limit is not None:
        result["slot_limit"] = slot_limit
    if slot_body_bytes is not None:
        result["slot_body_bytes"] = slot_body_bytes
    if candidate_slot_limit is not None:
        result["candidate_slot_limit"] = candidate_slot_limit
    return result


def slot_publication_error(current: bytes | None, candidate: bytes) -> dict[str, Any] | None:
    """Mechanical slot policy for one publication. ``None`` means allow.

    Missing current and a present file with no marker-like line are both
    ``absent``. This does not summarize, truncate, archive, or commit.
    """
    current_slot = classify_state_slot(b"" if current is None else current)
    candidate_slot = classify_state_slot(candidate)
    malformed = _slot_rejection(
        "slot_malformed",
        "current-state slot markers are malformed, duplicated, or extra; nothing written",
    )
    if candidate_slot["kind"] == "malformed":
        return malformed
    if current_slot["kind"] == "malformed":
        if candidate_slot["kind"] == "absent":
            return None
        if candidate_slot["body_bytes"] > candidate_slot["limit"]:
            return _slot_rejection(
                "slot_body_exceeds_limit",
                "current-state slot body exceeds its limit; nothing written",
                slot_limit=candidate_slot["limit"],
                slot_body_bytes=candidate_slot["body_bytes"],
            )
        return None
    if current_slot["kind"] == "absent":
        if candidate_slot["kind"] == "absent":
            return None
        if candidate_slot["body_bytes"] > candidate_slot["limit"]:
            return _slot_rejection(
                "slot_body_exceeds_limit",
                "current-state slot body exceeds its limit; nothing written",
                slot_limit=candidate_slot["limit"],
                slot_body_bytes=candidate_slot["body_bytes"],
            )
        return None
    if candidate_slot["kind"] == "absent":
        return _slot_rejection(
            "slot_removed",
            "current-state slot cannot be removed by publication; nothing written",
            slot_limit=current_slot["limit"],
        )
    if candidate_slot["limit"] > current_slot["limit"]:
        return _slot_rejection(
            "slot_widened",
            "current-state slot limit cannot be widened by publication; nothing written",
            slot_limit=current_slot["limit"],
            candidate_slot_limit=candidate_slot["limit"],
        )
    if candidate_slot["limit"] < current_slot["limit"]:
        return _slot_rejection(
            "slot_narrowed",
            "current-state slot limit cannot be narrowed by publication; nothing written",
            slot_limit=current_slot["limit"],
            candidate_slot_limit=candidate_slot["limit"],
        )
    if candidate_slot["body_bytes"] > candidate_slot["limit"]:
        return _slot_rejection(
            "slot_body_exceeds_limit",
            "current-state slot body exceeds its limit; nothing written",
            slot_limit=candidate_slot["limit"],
            slot_body_bytes=candidate_slot["body_bytes"],
        )
    return None


def _reject_manifest_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate manifest key: {key}")
        result[key] = value
    return result


def _libc():
    library = ctypes.CDLL(None, use_errno=True)
    return library


def _syscall_error() -> OSError:
    err = ctypes.get_errno()
    return OSError(err, os.strerror(err))


def rename_noreplace(old_dirfd: int, old_name: bytes, new_dirfd: int, new_name: bytes) -> None:
    """Atomically publish a directory only when the destination name is absent."""
    library = _libc()
    if not hasattr(library, "renameat2"):
        raise OSError(errno.ENOSYS, "renameat2 is unavailable")
    function = library.renameat2
    function.argtypes = [
        ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint,
    ]
    function.restype = ctypes.c_int
    ctypes.set_errno(0)
    if function(old_dirfd, old_name, new_dirfd, new_name, _RENAME_NOREPLACE) != 0:
        raise _syscall_error()


def _mkdirat(dirfd: int, name: bytes, mode: int) -> None:
    function = _libc().mkdirat
    function.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
    function.restype = ctypes.c_int
    ctypes.set_errno(0)
    if function(dirfd, name, mode) != 0:
        raise _syscall_error()


def _unlinkat(dirfd: int, name: bytes, flags: int = 0) -> None:
    function = _libc().unlinkat
    function.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int]
    function.restype = ctypes.c_int
    ctypes.set_errno(0)
    if function(dirfd, name, flags) != 0:
        raise _syscall_error()


def _encode_text(value: Any, limit: int) -> bytes | None:
    if not isinstance(value, str):
        return None
    try:
        raw = value.encode("utf-8")
    except UnicodeError:
        return None
    if b"\0" in raw or len(raw) > limit:
        return None
    return raw


class ProjectContinuity:
    """Use the server's existing bounded file routing and error classification."""

    def __init__(
        self, read_bytes: Callable, open_error: Callable, is_symlink: Callable
    ) -> None:
        self._read_bytes = read_bytes
        self._open_error = open_error
        self._is_symlink = is_symlink

    def _load_project_manifest(
        self,
        workspace: WorkspaceContext,
    ) -> tuple[dict[str, Any] | None, dict[str, Any]]:
        """Load and validate the fixed repository onboarding manifest.

        This is the single internal seam for both context projection and checkpoint
        target selection. It returns no state-file content.
        """
        raw, error = self._read_bytes(
            workspace,
            PROJECT_MANIFEST_PATH.split("/"),
            PROJECT_MANIFEST_PATH,
            MAX_PROJECT_MANIFEST_BYTES,
        )
        if error is not None:
            if error.get("error_type") == "FileNotFound":
                return None, {
                    "ready": False,
                    "status": "manifest_missing",
                    "manifest_path": PROJECT_MANIFEST_PATH,
                }
            return None, {
                "ready": False,
                "status": "manifest_invalid",
                "manifest_path": PROJECT_MANIFEST_PATH,
                "reason": error.get("error_type", "ManifestReadError"),
            }
        if raw is None or len(raw) > MAX_PROJECT_MANIFEST_BYTES:
            return None, {
                "ready": False,
                "status": "manifest_invalid",
                "manifest_path": PROJECT_MANIFEST_PATH,
                "reason": "ManifestTooLarge",
            }
        try:
            text = raw.decode("utf-8")
            parsed = json.loads(text, object_pairs_hook=_reject_manifest_duplicate_keys)
        except (UnicodeError, ValueError, json.JSONDecodeError):
            return None, {
                "ready": False,
                "status": "manifest_invalid",
                "manifest_path": PROJECT_MANIFEST_PATH,
                "reason": "ManifestJsonInvalid",
            }
        if (not isinstance(parsed, dict)
                or not _MANIFEST_REQUIRED_KEYS <= set(parsed) <= _MANIFEST_ALLOWED_KEYS):
            return None, {
                "ready": False,
                "status": "manifest_invalid",
                "manifest_path": PROJECT_MANIFEST_PATH,
                "reason": "ManifestSchemaInvalid",
            }
        rules = parsed.get("rules")
        if not isinstance(rules, list):
            return None, {
                "ready": False,
                "status": "manifest_invalid",
                "manifest_path": PROJECT_MANIFEST_PATH,
                "reason": "ManifestSchemaInvalid",
            }
        pointer_count = len(rules) + 2
        if not rules or pointer_count > MAX_PROJECT_POINTERS:
            return None, {
                "ready": False,
                "status": "manifest_invalid",
                "manifest_path": PROJECT_MANIFEST_PATH,
                "reason": "ManifestPointerCountInvalid",
            }
        try:
            clean_rules = [_manifest_relative_path(path)[0] for path in rules]
            current_state, current_parts = _manifest_relative_path(parsed.get("current_state"))
            memory = _manifest_relative_path(parsed.get("memory"))[0]
        except ValueError:
            return None, {
                "ready": False,
                "status": "manifest_invalid",
                "manifest_path": PROJECT_MANIFEST_PATH,
                "reason": "ManifestPathInvalid",
            }
        if len(set(clean_rules)) != len(clean_rules):
            return None, {
                "ready": False,
                "status": "manifest_invalid",
                "manifest_path": PROJECT_MANIFEST_PATH,
                "reason": "ManifestPointerDuplicate",
            }
        if current_state == PROJECT_MANIFEST_PATH or current_state in clean_rules:
            return None, {
                "ready": False,
                "status": "manifest_invalid",
                "manifest_path": PROJECT_MANIFEST_PATH,
                "reason": "ManifestCurrentStateOverlap",
            }
        all_paths = clean_rules + [current_state, memory]
        if PROJECT_MANIFEST_PATH in all_paths or len(set(all_paths)) != len(all_paths):
            return None, {
                "ready": False,
                "status": "manifest_invalid",
                "manifest_path": PROJECT_MANIFEST_PATH,
                "reason": "ManifestPointerOverlap",
            }
        pointers = {"rules": clean_rules, "memory": memory}
        manifest = {
            **pointers,
            "current_state": current_state,
            "_current_parts": current_parts,
        }
        projection: dict[str, Any] = {
            "ready": False,
            "status": "current_state_unavailable",
            "manifest_path": PROJECT_MANIFEST_PATH,
            "canonical_pointers": pointers,
            "current_state": {
                "path": current_state,
                "status": "unavailable",
                "revision": None,
            },
        }

        for pointer in clean_rules + [memory]:
            _, pointer_parts = _manifest_relative_path(pointer)
            _, pointer_error = self._read_bytes(
                workspace, pointer_parts, pointer, 0
            )
            if pointer_error is not None:
                projection["status"] = "canonical_pointer_unavailable"
                projection["current_state"]["status"] = "unknown"
                return None, projection

        state_bytes, state_error = self._read_bytes(
            workspace, current_parts, current_state, MAX_CHECKPOINT_CONTENT_BYTES
        )
        if state_error is not None:
            if state_error.get("error_type") == "FileNotFound":
                projection["status"] = "current_state_missing"
                projection["current_state"] = {
                    "path": current_state,
                    "status": "missing",
                    "revision": CHECKPOINT_MISSING_REVISION,
                }
            return manifest, projection
        if state_bytes is None or len(state_bytes) > MAX_CHECKPOINT_CONTENT_BYTES:
            return manifest, projection
        try:
            state_bytes.decode("utf-8")
        except UnicodeError:
            return manifest, projection
        projection["ready"] = True
        projection["status"] = "ready"
        projection["current_state"] = {
            "path": current_state,
            "status": "readable",
            "revision": "sha256:" + hashlib.sha256(state_bytes).hexdigest(),
            "revision_provenance": {
                "source": "direct_filesystem_revision_only",
                "observation": "bytes",
            },
        }
        return manifest, projection

    def describe(self, workspace: WorkspaceContext) -> dict[str, Any]:
        return self._load_project_manifest(workspace)[1]

    def _checkpoint_revision_at_parent(
        self,
        parent_fd: int,
        file_name: str,
        rel_path: str,
    ) -> tuple[str | None, dict[str, Any] | None]:
        """Re-open and hash current state through one already-pinned parent."""
        file_fd: int | None = None
        try:
            file_fd = os.open(file_name, _NOFOLLOW_FILE_OPEN_FLAGS, dir_fd=parent_fd)
            opened = os.fstat(file_fd)
            if not stat.S_ISREG(opened.st_mode):
                return None, {
                    "ok": False,
                    "error_type": "NotARegularFile",
                    "error": f"path '{rel_path}' is not a regular file",
                }
            chunks: list[bytes] = []
            remaining = MAX_CHECKPOINT_CONTENT_BYTES + 1
            while remaining > 0:
                chunk = os.read(file_fd, remaining)
                if not chunk:
                    break
                chunks.append(chunk)
                remaining -= len(chunk)
            current = b"".join(chunks)
            if len(current) > MAX_CHECKPOINT_CONTENT_BYTES:
                return None, {
                    "ok": False,
                    "error_type": "CheckpointStateUnavailable",
                    "error": "current-state file is not bounded readable text",
                }
            try:
                current.decode("utf-8")
            except UnicodeError:
                return None, {
                    "ok": False,
                    "error_type": "CheckpointStateUnavailable",
                    "error": "current-state file is not UTF-8 text",
                }
            return "sha256:" + hashlib.sha256(current).hexdigest(), None
        except OSError as exc:
            return None, self._open_error(rel_path, exc)
        finally:
            if file_fd is not None:
                os.close(file_fd)

    def _checkpoint_conflict(
        self,
        expected_revision: str,
        actual_revision: str,
    ) -> dict[str, Any]:
        return {
            "ok": False,
            "error_type": "CheckpointConflict",
            "error": "current-state revision does not match expected_revision; no current-state content was written",
            "expected_revision": expected_revision,
            "actual_revision": actual_revision,
        }

    def _atomic_checkpoint_replace(
        self,
        workspace: WorkspaceContext,
        rel_path: str,
        rel_parts: list[str],
        content_bytes: bytes | None,
        expected_revision: str,
        edits: list[dict[str, str]] | None = None,
    ) -> dict[str, Any]:
        current, read_error = self._read_bytes(
            workspace, rel_parts, rel_path, MAX_CHECKPOINT_CONTENT_BYTES
        )
        if read_error is not None:
            if read_error.get("error_type") != "FileNotFound":
                return read_error
            actual_revision = CHECKPOINT_MISSING_REVISION
            current_mode = 0o644
        else:
            if current is None or len(current) > MAX_CHECKPOINT_CONTENT_BYTES:
                return {
                    "ok": False,
                    "error_type": "CheckpointStateUnavailable",
                    "error": "current-state file is not bounded readable text",
                }
            try:
                current.decode("utf-8")
            except UnicodeError:
                return {
                    "ok": False,
                    "error_type": "CheckpointStateUnavailable",
                    "error": "current-state file is not UTF-8 text",
                }
            actual_revision = "sha256:" + hashlib.sha256(current).hexdigest()
            current_mode = 0o644
        if actual_revision != expected_revision:
            return self._checkpoint_conflict(expected_revision, actual_revision)

        if edits is not None:
            if current is None or read_error is not None:
                return {"ok": False, "error_type": "CheckpointEditMismatch",
                        "error": "edits require an existing readable current-state file; nothing written"}
            spans = []
            for edit in edits:
                old = edit["old_text"].encode("utf-8")
                start = current.find(old)
                if start < 0 or current.find(old, start + 1) >= 0:
                    return {"ok": False, "error_type": "CheckpointEditMismatch",
                            "error": "each old_text must match exactly once in the original state; nothing written"}
                spans.append((start, start + len(old), edit["new_text"].encode("utf-8")))
            spans.sort()
            if any(left[1] > right[0] for left, right in zip(spans, spans[1:])):
                return {"ok": False, "error_type": "CheckpointEditOverlap",
                        "error": "edit ranges overlap in the original state; nothing written"}
            parts, previous = [], 0
            for start, end, replacement in spans:
                parts.extend((current[previous:start], replacement))
                previous = end
            parts.append(current[previous:])
            content_bytes = b"".join(parts)
            if len(content_bytes) > MAX_CHECKPOINT_CONTENT_BYTES:
                return {"ok": False, "error_type": "InvalidCheckpointContent",
                        "error": "edited current state exceeds the byte limit; nothing written"}

        pinned_current = None if actual_revision == CHECKPOINT_MISSING_REVISION else current
        slot_error = slot_publication_error(pinned_current, content_bytes)
        if slot_error is not None:
            return slot_error

        root_fd: int | None = None
        parent_fd: int | None = None
        walked_fds: list[int] = []
        temp_name: str | None = None
        try:
            root_fd = os.open(workspace.root, _NOFOLLOW_DIR_OPEN_FLAGS)
            if workspace.git is not None:
                opened_root = os.fstat(root_fd)
                if (opened_root.st_dev, opened_root.st_ino) != (
                    workspace.git.root_device, workspace.git.root_inode
                ):
                    return {
                        "ok": False,
                        "error_type": "WorkspaceRootIdentityChanged",
                        "error": "opened workspace root does not match its registered Git worktree identity",
                    }
            parent_fd = root_fd
            for part in rel_parts[:-1]:
                previous_fd = parent_fd
                try:
                    parent_fd = os.open(part, _NOFOLLOW_DIR_OPEN_FLAGS, dir_fd=previous_fd)
                except OSError as exc:
                    if exc.errno == errno.ENOTDIR and self._is_symlink(previous_fd, part):
                        return {
                            "ok": False,
                            "error_type": "SymlinkRejected",
                            "error": f"path '{rel_path}' contains a symbolic link component; refusing to follow",
                        }
                    raise
                walked_fds.append(parent_fd)

            try:
                target_stat = os.stat(rel_parts[-1], dir_fd=parent_fd, follow_symlinks=False)
            except FileNotFoundError:
                target_stat = None
            if target_stat is not None:
                if stat.S_ISLNK(target_stat.st_mode):
                    return {
                        "ok": False,
                        "error_type": "SymlinkRejected",
                        "error": f"path '{rel_path}' is a symbolic link; refusing to replace",
                    }
                if not stat.S_ISREG(target_stat.st_mode):
                    return {
                        "ok": False,
                        "error_type": "NotARegularFile",
                        "error": f"path '{rel_path}' is not a regular file",
                    }
                current_mode = stat.S_IMODE(target_stat.st_mode)

            temp_name = f".principal-checkpoint-{secrets.token_hex(16)}.tmp"
            temp_fd = os.open(
                temp_name,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
                current_mode,
                dir_fd=parent_fd,
            )
            try:
                os.fchmod(temp_fd, current_mode)
                view = memoryview(content_bytes)
                while view:
                    written = os.write(temp_fd, view)
                    view = view[written:]
                os.fsync(temp_fd)
            finally:
                os.close(temp_fd)
            if expected_revision == CHECKPOINT_MISSING_REVISION:
                try:
                    os.link(
                        temp_name,
                        rel_parts[-1],
                        src_dir_fd=parent_fd,
                        dst_dir_fd=parent_fd,
                        follow_symlinks=False,
                    )
                except OSError as exc:
                    if exc.errno == errno.EEXIST:
                        final_revision, final_error = self._checkpoint_revision_at_parent(
                            parent_fd, rel_parts[-1], rel_path
                        )
                        return self._checkpoint_conflict(
                            expected_revision,
                            final_revision if final_error is None else "unavailable",
                        )
                    return {
                        "ok": False,
                        "error_type": "CheckpointNoClobberUnavailable",
                        "error": "atomic no-clobber creation could not be proven; no current-state content was published",
                    }
                os.unlink(temp_name, dir_fd=parent_fd)
                temp_name = None
            else:
                final_revision, final_error = self._checkpoint_revision_at_parent(
                    parent_fd, rel_parts[-1], rel_path
                )
                if final_error is not None:
                    return self._checkpoint_conflict(
                        expected_revision,
                        CHECKPOINT_MISSING_REVISION
                        if final_error.get("error_type") == "FileNotFound"
                        else "unavailable",
                    )
                if final_revision != expected_revision:
                    return self._checkpoint_conflict(expected_revision, final_revision)
                os.replace(
                    temp_name,
                    rel_parts[-1],
                    src_dir_fd=parent_fd,
                    dst_dir_fd=parent_fd,
                )
                temp_name = None
            os.fsync(parent_fd)
        except OSError as exc:
            return self._open_error(rel_path, exc)
        finally:
            if temp_name is not None and parent_fd is not None:
                try:
                    os.unlink(temp_name, dir_fd=parent_fd)
                except OSError:
                    pass
            for fd in reversed(walked_fds):
                try:
                    os.close(fd)
                except OSError:
                    pass
            if root_fd is not None:
                try:
                    os.close(root_fd)
                except OSError:
                    pass

        revision = "sha256:" + hashlib.sha256(content_bytes).hexdigest()
        return {
            "ok": True,
            "project_ref": workspace.workspace_ref,
            "path": rel_path,
            "previous_revision": actual_revision,
            "revision": revision,
            "bytes_written": len(content_bytes),
            "provenance": "principal_supplied_unverified",
        }

    def checkpoint(
        self, workspace: WorkspaceContext, content: str | None, expected_revision: str,
        edits: list[dict[str, str]] | None = None
    ) -> dict[str, Any]:
        """Replace state only; the author retains causal history or archives it first.

        An opted-in whole-line slot is a byte and limit-identity check at this
        publication. It does not summarize, truncate, archive, or commit.
        """
        if (content is None) == (edits is None):
            return {"ok": False, "error_type": "InvalidCheckpointMode",
                    "error": "supply exactly one of content or edits; nothing written"}
        content_bytes = None
        if edits is not None:
            if not isinstance(edits, list) or not edits:
                return {"ok": False, "error_type": "InvalidCheckpointEdits",
                        "error": "edits must be a nonempty list; nothing written"}
            try:
                # Every nonoverlapping old span consumes at least one source byte.
                if len(edits) > MAX_CHECKPOINT_CONTENT_BYTES:
                    raise ValueError
                size = 0
                for edit in edits:
                    if (not isinstance(edit, dict) or set(edit) != {"old_text", "new_text"}
                            or not all(isinstance(v, str) for v in edit.values()) or not edit["old_text"]):
                        raise ValueError
                    size += len(edit["old_text"].encode("utf-8")) + len(edit["new_text"].encode("utf-8"))
                if size > 2 * MAX_CHECKPOINT_CONTENT_BYTES:
                    raise ValueError
            except (ValueError, UnicodeError):
                return {"ok": False, "error_type": "InvalidCheckpointEdits",
                        "error": "edits need nonempty old_text and UTF-8 new_text within state byte bounds; nothing written"}
        else:
            try:
                if not isinstance(content, str):
                    raise ValueError
                content_bytes = content.encode("utf-8")
                if len(content_bytes) > MAX_CHECKPOINT_CONTENT_BYTES:
                    raise ValueError
            except (ValueError, UnicodeError):
                return {"ok": False, "error_type": "InvalidCheckpointContent",
                        "error": "content must be bounded UTF-8 text; nothing written"}
        if not isinstance(expected_revision, str) or not (
            expected_revision == CHECKPOINT_MISSING_REVISION
            or _CHECKPOINT_REVISION_RE.fullmatch(expected_revision)
        ):
            return {
                "ok": False,
                "error_type": "InvalidExpectedRevision",
                "error": "expected_revision must be 'missing' or a sha256:<64 lowercase hex> revision",
            }

        manifest, projection = self._load_project_manifest(workspace)
        if manifest is None:
            return {"ok": False, "error_type": "ProjectManifestUnavailable",
                    "error": "a valid .principal/project.json manifest is required",
                    "continuity": projection}
        return self._atomic_checkpoint_replace(
            workspace, manifest["current_state"], manifest["_current_parts"],
            content_bytes, expected_revision, edits=edits,
        )

    def initialize_fresh(self, workspace: WorkspaceContext, seed: Any) -> dict[str, Any]:
        """Publish one fresh canonical `.principal` directory, or leave one untouched.

        The caller holds the root writer gate. This does not register a route,
        stage, or commit. After `renameat2(RENAME_NOREPLACE)` returns, the
        published directory is never removed.
        """
        from .workspace_context import WorkspaceAuthorizationError, validate_git_worktree_identity

        if workspace.git is None or not workspace.workspace_ref:
            return self._init_result(
                False, "ProjectRefUnauthorized",
                "project_initialize requires an already registered project",
                publication="not_attempted",
            )
        try:
            validate_git_worktree_identity(workspace.root, workspace.git)
        except WorkspaceAuthorizationError as exc:
            return self._init_result(
                False, "GitWorktreeIdentityChanged", str(exc), publication="not_attempted",
            )
        prepared = self._prepare_initialization(seed)
        if prepared.get("ok") is False:
            return prepared

        root_fd: int | None = None
        published = False
        staging_name: bytes | None = None
        staging_id: tuple[int, int] | None = None
        outcome: dict[str, Any] | None = None
        try:
            root_fd = os.open(workspace.root, _NOFOLLOW_DIR_OPEN_FLAGS)
            opened = os.fstat(root_fd)
            if (opened.st_dev, opened.st_ino) != (
                workspace.git.root_device, workspace.git.root_inode
            ):
                return self._init_result(
                    False, "GitWorktreeIdentityChanged",
                    "opened workspace root does not match its registered Git worktree identity",
                    publication="not_attempted",
                )
            disposition, detail = self._principal_disposition(root_fd, workspace)
            if disposition == "valid":
                return self._already_ready(workspace, detail)
            if disposition == "blocked":
                return detail
            for path in prepared["rules"]:
                problem = self._require_existing_file(root_fd, path)
                if problem is not None:
                    return self._init_result(
                        False, "SeedPathUnavailable",
                        f"rules path '{path}' is {problem}; nothing published",
                        publication="not_attempted",
                    )
            try:
                validate_git_worktree_identity(workspace.root, workspace.git)
            except WorkspaceAuthorizationError as exc:
                return self._init_result(
                    False, "GitWorktreeIdentityChanged", str(exc), publication="not_attempted",
                )
            staging_name = f".principal-init-{secrets.token_hex(16)}".encode("ascii")
            _mkdirat(root_fd, staging_name, 0o755)
            staging_fd = os.open(staging_name, _NOFOLLOW_DIR_OPEN_FLAGS, dir_fd=root_fd)
            try:
                info = os.fstat(staging_fd)
                staging_id = (info.st_dev, info.st_ino)
                os.fchmod(staging_fd, 0o755)
                for name, payload in prepared["files"].items():
                    self._write_exclusive(staging_fd, name.encode("ascii"), payload)
                os.fsync(staging_fd)
            finally:
                os.close(staging_fd)
            current = os.fstat(root_fd)
            if (current.st_dev, current.st_ino) != (
                workspace.git.root_device, workspace.git.root_inode
            ):
                outcome = self._init_result(
                    False, "GitWorktreeIdentityChanged",
                    "workspace root changed before publication; staging was not published",
                    publication="no_effect",
                )
                return outcome
            try:
                rename_noreplace(root_fd, staging_name, root_fd, PRINCIPAL_DIR.encode("ascii"))
            except OSError as exc:
                if exc.errno == errno.EEXIST:
                    raced, raced_detail = self._principal_disposition(root_fd, workspace)
                    if raced == "valid":
                        outcome = self._already_ready(workspace, raced_detail)
                    elif raced == "blocked":
                        outcome = raced_detail
                    else:
                        outcome = self._init_result(
                            False, "InitializationNotFresh",
                            ".principal appeared before publication; nothing of this call was published",
                            publication="no_effect",
                        )
                    return outcome
                if exc.errno == errno.ENOSYS:
                    outcome = self._init_result(
                        False, "DirectoryPublicationUnavailable",
                        "atomic no-replace directory publication is unavailable; nothing published",
                        publication="no_effect",
                    )
                    return outcome
                outcome = self._init_result(
                    False, "DirectoryPublicationFailed",
                    "directory publication failed before replace; nothing published",
                    publication="no_effect",
                )
                return outcome
            published = True
            staging_name = None
            reasons: list[str] = []
            try:
                os.fsync(root_fd)
            except OSError:
                reasons.append("directory_fsync_unconfirmed")
            readback, readback_reason = self._readback_published(root_fd, prepared["files"])
            if readback_reason is not None:
                reasons.append(readback_reason)
            continuity = self.describe(workspace)
            confirmed = (
                not reasons
                and continuity.get("status") == "ready"
                and "manifest_version" not in continuity
                and "memory" in continuity.get("canonical_pointers", {})
            )
            outcome = {
                "ok": True,
                "status": "initialized" if confirmed else "published_unconfirmed",
                "project_ref": workspace.workspace_ref,
                "task_authority": "not_granted",
                "publication": "published",
                "durability": "uncertain" if reasons else "directory_fsynced",
                "reason": "+".join(reasons) or None,
                "files": readback,
                "continuity": continuity,
                "git_mutation": "none",
            }
            return outcome
        except OSError:
            outcome = self._init_result(
                False, "InitializationFailed",
                "fresh initialization failed before publication" if not published
                else "fresh initialization published, then an unexpected filesystem error occurred; the directory was not removed",
                publication="no_effect" if not published else "published",
                durability="not_applicable" if not published else "uncertain",
            )
            return outcome
        finally:
            cleanup = None
            if root_fd is not None and staging_name is not None and not published:
                if staging_id is not None:
                    cleanup = self._discard_staging(root_fd, staging_name, staging_id)
                else:
                    try:
                        _unlinkat(root_fd, staging_name, _AT_REMOVEDIR)
                        cleanup = "removed"
                    except OSError as exc:
                        cleanup = "absent" if exc.errno == errno.ENOENT else "unconfirmed"
            if root_fd is not None:
                os.close(root_fd)
            if outcome is not None and cleanup not in (None, "removed", "absent"):
                outcome["staging_cleanup"] = "unconfirmed"

    def _init_result(
        self,
        ok: bool,
        error_type: str,
        error: str,
        *,
        publication: str,
        durability: str = "not_applicable",
    ) -> dict[str, Any]:
        return {
            "ok": ok,
            "error_type": error_type,
            "error": error,
            "task_authority": "not_granted",
            "publication": publication,
            "durability": durability,
            "git_mutation": "none",
        }

    def _already_ready(self, workspace: WorkspaceContext, continuity: dict[str, Any]) -> dict[str, Any]:
        return {
            "ok": True,
            "status": "already_ready",
            "project_ref": workspace.workspace_ref,
            "task_authority": "not_granted",
            "publication": "not_attempted",
            "durability": "not_applicable",
            "continuity": continuity,
            "git_mutation": "none",
        }

    def _prepare_initialization(self, seed: Any) -> dict[str, Any]:
        required = {"rules", "state_content", "memory_content"}
        if (
            not isinstance(seed, dict)
            or set(seed) - _INIT_SEED_KEYS
            or not required <= set(seed)
        ):
            return self._init_result(
                False, "InvalidSeed",
                "seed requires rules, state_content, and memory_content; only project_rules_content is optional",
                publication="not_attempted",
            )
        rules = seed.get("rules")
        if not isinstance(rules, list) or not rules:
            return self._init_result(
                False, "InvalidSeed",
                "rules must be a nonempty list of existing file paths",
                publication="not_attempted",
            )
        try:
            clean_rules = [_manifest_relative_path(path)[0] for path in rules]
        except ValueError:
            return self._init_result(
                False, "InvalidSeed",
                "seed paths must be bounded relative paths without traversal or .git",
                publication="not_attempted",
            )
        rules_bytes = None
        if "project_rules_content" in seed:
            rules_bytes = _encode_text(seed.get("project_rules_content"), MAX_CHECKPOINT_CONTENT_BYTES)
            if rules_bytes is None or not rules_bytes.strip():
                return self._init_result(
                    False, "InvalidSeed",
                    "project_rules_content must be meaningful bounded UTF-8 text when supplied",
                    publication="not_attempted",
                )
        state_bytes = _encode_text(seed.get("state_content"), MAX_CHECKPOINT_CONTENT_BYTES)
        memory_bytes = _encode_text(seed.get("memory_content"), MAX_CHECKPOINT_CONTENT_BYTES)
        if state_bytes is None or memory_bytes is None:
            return self._init_result(
                False, "InvalidSeed",
                "state_content and memory_content must be bounded UTF-8 text without NUL",
                publication="not_attempted",
            )
        slot_error = slot_publication_error(None, state_bytes)
        if slot_error is not None:
            slot_error = dict(slot_error)
            slot_error["task_authority"] = "not_granted"
            slot_error["publication"] = "not_attempted"
            slot_error["durability"] = "not_applicable"
            slot_error["git_mutation"] = "none"
            return slot_error
        rule_paths = list(clean_rules)
        if rules_bytes is not None:
            if PRINCIPAL_RULES_PATH in rule_paths:
                return self._init_result(
                    False, "InvalidSeed",
                    ".principal/rules.md is created only from project_rules_content",
                    publication="not_attempted",
                )
            rule_paths.append(PRINCIPAL_RULES_PATH)
        routed = rule_paths + [PRINCIPAL_STATE_PATH, PRINCIPAL_MEMORY_PATH]
        if (
            len(rule_paths) + 2 > MAX_PROJECT_POINTERS
            or len(set(routed)) != len(routed)
            or PROJECT_MANIFEST_PATH in routed
            or any(path == PRINCIPAL_DIR or path.startswith(PRINCIPAL_DIR + "/") for path in clean_rules)
        ):
            return self._init_result(
                False, "InvalidSeed",
                "seed pointers exceed the manifest budget, overlap, or point inside .principal",
                publication="not_attempted",
            )
        manifest: dict[str, Any] = {
            "rules": rule_paths,
            "current_state": PRINCIPAL_STATE_PATH,
            "memory": PRINCIPAL_MEMORY_PATH,
        }
        manifest_bytes = (json.dumps(manifest, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
        if len(manifest_bytes) > MAX_PROJECT_MANIFEST_BYTES:
            return self._init_result(
                False, "InvalidSeed",
                "the manifest exceeds its byte bound; nothing published",
                publication="not_attempted",
            )
        files = {
            "project.json": manifest_bytes,
            "state.md": state_bytes,
            "memory.md": memory_bytes,
        }
        if rules_bytes is not None:
            files["rules.md"] = rules_bytes
        return {"rules": clean_rules, "files": files}

    def _principal_disposition(
        self, root_fd: int, workspace: WorkspaceContext
    ) -> tuple[str, dict[str, Any]]:
        try:
            info = os.lstat(PRINCIPAL_DIR, dir_fd=root_fd)
        except FileNotFoundError:
            return "absent", {}
        except OSError as exc:
            return "blocked", self._init_result(
                False, "InitializationNotFresh",
                f".principal could not be inspected ({exc.errno}); nothing published",
                publication="not_attempted",
            )
        if stat.S_ISLNK(info.st_mode):
            return "blocked", self._init_result(
                False, "SymlinkRejected",
                ".principal is a symbolic link; refusing to follow or replace it",
                publication="not_attempted",
            )
        if not stat.S_ISDIR(info.st_mode):
            return "blocked", self._init_result(
                False, "InitializationNotFresh",
                ".principal exists and is not a directory; nothing published",
                publication="not_attempted",
            )
        continuity = self.describe(workspace)
        if continuity.get("status") in _VALID_EXISTING_MANIFEST_STATUSES:
            return "valid", continuity
        return "blocked", self._init_result(
            False, "InitializationNotFresh",
            ".principal exists without a canonical manifest; nothing published",
            publication="not_attempted",
        )

    def _require_existing_file(self, root_fd: int, rel: str) -> str | None:
        parts = rel.split("/")
        parent = root_fd
        opened: list[int] = []
        try:
            for part in parts[:-1]:
                try:
                    info = os.lstat(part, dir_fd=parent)
                except FileNotFoundError:
                    return "missing"
                except OSError:
                    return "unavailable"
                if stat.S_ISLNK(info.st_mode):
                    return "a symbolic link"
                if not stat.S_ISDIR(info.st_mode):
                    return "not a directory path"
                try:
                    parent = os.open(part, _NOFOLLOW_DIR_OPEN_FLAGS, dir_fd=parent)
                except OSError:
                    return "unavailable"
                opened.append(parent)
            name = parts[-1]
            try:
                info = os.lstat(name, dir_fd=parent)
            except FileNotFoundError:
                return "missing"
            except OSError:
                return "unavailable"
            if stat.S_ISLNK(info.st_mode):
                return "a symbolic link"
            if not stat.S_ISREG(info.st_mode):
                return "not a regular file"
            return None
        finally:
            for fd in opened:
                os.close(fd)

    def _write_exclusive(self, dir_fd: int, name: bytes, payload: bytes) -> None:
        fd = os.open(
            name,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
            0o644,
            dir_fd=dir_fd,
        )
        try:
            os.fchmod(fd, 0o644)
            view = memoryview(payload)
            while view:
                written = os.write(fd, view)
                if written <= 0:
                    raise OSError("short initialization write")
                view = view[written:]
            os.fsync(fd)
        finally:
            os.close(fd)

    def _discard_staging(self, root_fd: int, name: bytes, identity: tuple[int, int]) -> str:
        """Remove one staging directory only when its inode is the one this call created."""
        try:
            fd = os.open(name, _NOFOLLOW_DIR_OPEN_FLAGS, dir_fd=root_fd)
        except FileNotFoundError:
            return "absent"
        except OSError:
            return "unconfirmed"
        try:
            info = os.fstat(fd)
            if (info.st_dev, info.st_ino) != identity:
                return "unconfirmed"
            for child in (b"project.json", b"state.md", b"memory.md", b"rules.md"):
                try:
                    _unlinkat(fd, child)
                except OSError as exc:
                    if exc.errno != errno.ENOENT:
                        return "unconfirmed"
            os.fsync(fd)
        finally:
            os.close(fd)
        try:
            _unlinkat(root_fd, name, _AT_REMOVEDIR)
        except OSError as exc:
            return "absent" if exc.errno == errno.ENOENT else "unconfirmed"
        return "removed"

    def _readback_published(
        self, root_fd: int, expected: dict[str, bytes]
    ) -> tuple[list[dict[str, Any]], str | None]:
        try:
            dir_fd = os.open(PRINCIPAL_DIR, _NOFOLLOW_DIR_OPEN_FLAGS, dir_fd=root_fd)
        except OSError:
            return [], "readback_unconfirmed"
        rows: list[dict[str, Any]] = []
        try:
            for name, payload in expected.items():
                try:
                    fd = os.open(
                        name, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=dir_fd
                    )
                except OSError:
                    return rows, "readback_unconfirmed"
                try:
                    chunks: list[bytes] = []
                    remaining = len(payload) + 1
                    while remaining > 0:
                        block = os.read(fd, remaining)
                        if not block:
                            break
                        chunks.append(block)
                        remaining -= len(block)
                    observed = b"".join(chunks)
                finally:
                    os.close(fd)
                if observed != payload:
                    return rows, "readback_mismatch"
                rows.append({
                    "path": f"{PRINCIPAL_DIR}/{name}",
                    "sha256": hashlib.sha256(observed).hexdigest(),
                    "bytes": len(observed),
                })
        finally:
            os.close(dir_fd)
        return rows, None
