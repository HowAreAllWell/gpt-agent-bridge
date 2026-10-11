"""Server-authorized workspace references and stable worktree identity."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import secrets
import stat
import subprocess
import fixed_git
import time
from typing import Any, Callable


WORKSPACE_REF_ENV = "BRIDGE_WORKSPACE_REGISTRY"
WORKSPACE_STORE_ENV = "BRIDGE_WORKSPACE_STORE_PATH"
WORKSPACE_REF_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
MAX_WORKSPACE_REFS = 32
WORKSPACE_STORE_VERSION = 1
WORKSPACE_STORE_FILE_NAME = "workspace-registry-v1.json"


class WorkspaceAuthorizationError(ValueError):
    """A configured workspace reference is absent or no longer authorized."""


class WorkspaceStoreError(WorkspaceAuthorizationError):
    """Base error for workspace registry store operations.

    A raised store error is a pre-publication no-effect: the previous store
    bytes remain the persisted record and the caller must not treat the
    attempted record as durable. Post-publication uncertainty is returned, not
    raised, so a published file is not reported as an absent write.
    """

    publication = "no_effect"
    durability = "not_applicable"
    persistence_reason = "pre_publication"

    def __init__(
        self,
        message: str,
        *,
        publication: str = "no_effect",
        durability: str = "not_applicable",
        persistence_reason: str = "pre_publication",
    ) -> None:
        super().__init__(message)
        self.publication = publication
        self.durability = durability
        self.persistence_reason = persistence_reason


class InsecureWorkspaceStoreError(WorkspaceStoreError):
    """Store directory or file has insecure permissions, wrong owner, or is a symlink."""


class CorruptedWorkspaceStoreError(WorkspaceStoreError):
    """Store content is malformed or invalid."""


@dataclass(frozen=True)
class GitWorktreeIdentity:
    """Stable filesystem/Git provenance used to revalidate a registered root."""

    root_device: int
    root_inode: int
    git_dir: str
    git_common_dir: str
    git_dir_device: int
    git_dir_inode: int
    git_common_device: int
    git_common_inode: int
    bare: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "root_device": self.root_device,
            "root_inode": self.root_inode,
            "git_dir": self.git_dir,
            "git_common_dir": self.git_common_dir,
            "git_dir_device": self.git_dir_device,
            "git_dir_inode": self.git_dir_inode,
            "git_common_device": self.git_common_device,
            "git_common_inode": self.git_common_inode,
            "bare": self.bare,
        }

    @classmethod
    def from_dict(cls, data: Any) -> GitWorktreeIdentity:
        if not isinstance(data, dict):
            raise CorruptedWorkspaceStoreError("Git worktree identity must be an object")
        int_fields = [
            "root_device",
            "root_inode",
            "git_dir_device",
            "git_dir_inode",
            "git_common_device",
            "git_common_inode",
        ]
        for field in int_fields:
            val = data.get(field)
            if type(val) is not int:
                raise CorruptedWorkspaceStoreError(f"Git identity field {field} must be an integer")
        for str_field in ["git_dir", "git_common_dir"]:
            val = data.get(str_field)
            if (
                not isinstance(val, str)
                or not val
                or val != val.strip()
                or "\x00" in val
                or not Path(val).is_absolute()
            ):
                raise CorruptedWorkspaceStoreError(
                    f"Git identity field {str_field} must be a non-empty absolute path string"
                )
        bare = data.get("bare")
        if bare is not False:
            raise CorruptedWorkspaceStoreError("Git identity bare field must be False")

        return cls(
            root_device=data["root_device"],
            root_inode=data["root_inode"],
            git_dir=data["git_dir"],
            git_common_dir=data["git_common_dir"],
            git_dir_device=data["git_dir_device"],
            git_dir_inode=data["git_dir_inode"],
            git_common_device=data["git_common_device"],
            git_common_inode=data["git_common_inode"],
            bare=False,
        )


@dataclass(frozen=True)
class WorkspaceContext:
    """One authorized observation scope; no execution capability is implied."""

    workspace_ref: str | None
    root: Path
    git: GitWorktreeIdentity | None
    gate_key: str
    backend: Any = None

    @property
    def is_default(self) -> bool:
        return self.workspace_ref is None

    def public(self) -> dict[str, Any]:
        return {
            "workspace_ref": self.workspace_ref,
            "root": str(self.root),
            "scope": "default" if self.is_default else "authorized_registered",
        }


def _reject_duplicate_json_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"invalid JSON constant: {value}")


def _git_value(root: Path, *args: str) -> str:
    rc, raw, _ = fixed_git.observe(root, args, timeout=3, stdout_limit=65536)
    if rc != 0:
        raise WorkspaceAuthorizationError("registered workspace is not a valid Git worktree")
    value = raw.decode("utf-8", errors="strict").strip()
    if not value:
        raise WorkspaceAuthorizationError("registered workspace Git identity is unavailable")
    return value


def _resolved_git_path(root: Path, value: str) -> Path:
    path = Path(value)
    return (path if path.is_absolute() else root / path).resolve()


def canonical_git_worktree(path_value: str | os.PathLike[str]) -> tuple[Path, GitWorktreeIdentity]:
    """Canonicalize and validate one configured path as a non-bare Git root."""
    try:
        root = Path(path_value).expanduser().resolve(strict=True)
    except (OSError, RuntimeError, ValueError) as exc:
        raise WorkspaceAuthorizationError("registered workspace path is unavailable") from exc
    if not root.is_dir():
        raise WorkspaceAuthorizationError("registered workspace path is not a directory")
    try:
        root_stat = root.stat()
        top_level = Path(_git_value(root, "rev-parse", "--show-toplevel")).resolve(strict=True)
        bare_value = _git_value(root, "rev-parse", "--is-bare-repository")
        git_dir = _resolved_git_path(root, _git_value(root, "rev-parse", "--git-dir"))
        common_dir = _resolved_git_path(root, _git_value(root, "rev-parse", "--git-common-dir"))
        git_dir_stat = git_dir.stat()
        common_dir_stat = common_dir.stat()
    except (OSError, RuntimeError, ValueError) as exc:
        if isinstance(exc, WorkspaceAuthorizationError):
            raise
        raise WorkspaceAuthorizationError("registered workspace Git identity is unavailable") from exc
    if top_level != root:
        raise WorkspaceAuthorizationError("registered workspace Git top-level does not exactly match its path")
    if bare_value != "false":
        raise WorkspaceAuthorizationError("registered workspace must be a non-bare worktree")
    if not git_dir.is_dir() or not common_dir.is_dir():
        raise WorkspaceAuthorizationError("registered workspace Git directories are unavailable")
    identity = GitWorktreeIdentity(
        root_device=root_stat.st_dev,
        root_inode=root_stat.st_ino,
        git_dir=str(git_dir),
        git_common_dir=str(common_dir),
        git_dir_device=git_dir_stat.st_dev,
        git_dir_inode=git_dir_stat.st_ino,
        git_common_device=common_dir_stat.st_dev,
        git_common_inode=common_dir_stat.st_ino,
        bare=False,
    )
    return root, identity


def validate_git_worktree_identity(root: Path, expected: GitWorktreeIdentity) -> None:
    """Fail closed when a registered path no longer represents its original worktree."""
    current_root, current = canonical_git_worktree(root)
    if current_root != root or current != expected:
        raise WorkspaceAuthorizationError("registered workspace Git/worktree identity changed")


def _fsync_fd(fd: int) -> None:
    os.fsync(fd)


def default_workspace_store_path() -> Path:
    override = os.environ.get(WORKSPACE_STORE_ENV)
    if override:
        return Path(override).expanduser()
    xdg = os.environ.get("XDG_STATE_HOME")
    if xdg:
        return Path(xdg).expanduser() / "gpt-agent-bridge" / WORKSPACE_STORE_FILE_NAME
    return Path.home() / ".local" / "state" / "gpt-agent-bridge" / WORKSPACE_STORE_FILE_NAME


class WorkspaceRegistryStore:
    """Atomic, permission-checked local JSON store for dynamically registered workspaces."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or default_workspace_store_path()
        self._lock = asyncio.Lock()

    @property
    def lock(self) -> asyncio.Lock:
        return self._lock

    def _verify_path_security(self, p: Path, is_dir: bool = False) -> None:
        try:
            st = p.lstat()
        except FileNotFoundError:
            return
        except OSError as exc:
            raise InsecureWorkspaceStoreError(f"cannot inspect store path {p}: {exc}") from exc

        if stat.S_ISLNK(st.st_mode):
            raise InsecureWorkspaceStoreError(f"store path {p} must not be a symlink")

        current_uid = os.getuid()
        if st.st_uid != current_uid:
            raise InsecureWorkspaceStoreError(
                f"store path {p} owner ({st.st_uid}) does not match current user ({current_uid})"
            )

        if is_dir:
            if not stat.S_ISDIR(st.st_mode):
                raise InsecureWorkspaceStoreError(f"store directory {p} is not a directory")
            if (st.st_mode & 0o777) != 0o700:
                raise InsecureWorkspaceStoreError(
                    f"store directory {p} has insecure permissions {oct(st.st_mode)} (must be exactly mode 0700)"
                )
        else:
            if not stat.S_ISREG(st.st_mode):
                raise InsecureWorkspaceStoreError(f"store file {p} is not a regular file")
            if (st.st_mode & 0o777) != 0o600:
                raise InsecureWorkspaceStoreError(
                    f"store file {p} has insecure permissions {oct(st.st_mode)} (must be exactly mode 0600)"
                )

    def ensure_store_writable(self) -> Path:
        target_dir = self.path.parent
        if not target_dir.exists():
            try:
                target_dir.mkdir(parents=True, mode=0o700, exist_ok=True)
            except OSError as exc:
                raise InsecureWorkspaceStoreError(f"failed to create store directory {target_dir}: {exc}") from exc

        self._verify_path_security(target_dir, is_dir=True)
        if self.path.exists():
            self._verify_path_security(self.path, is_dir=False)
        return self.path

    def _validate_store_schema(self, data: dict[str, Any]) -> None:
        if not isinstance(data, dict) or data.get("version") != WORKSPACE_STORE_VERSION:
            raise CorruptedWorkspaceStoreError(
                f"store file {self.path} has unexpected schema version: {data.get('version') if isinstance(data, dict) else data}"
            )
        workspaces = data.get("workspaces")
        if not isinstance(workspaces, dict):
            raise CorruptedWorkspaceStoreError(f"store file {self.path} missing workspaces mapping")
        if len(workspaces) > MAX_WORKSPACE_REFS:
            raise CorruptedWorkspaceStoreError(f"store file {self.path} exceeds max workspace refs limit")

        for ref, entry in workspaces.items():
            if (
                not isinstance(ref, str)
                or not WORKSPACE_REF_RE.fullmatch(ref)
                or ref == "default"
            ):
                raise CorruptedWorkspaceStoreError(f"store file {self.path} has invalid workspace ref {ref!r}")
            if not isinstance(entry, dict):
                raise CorruptedWorkspaceStoreError(f"workspace record {ref} must be an object")
            if entry.get("workspace_ref") != ref:
                raise CorruptedWorkspaceStoreError(f"workspace record {ref} has mismatched workspace_ref")
            root = entry.get("canonical_root")
            if (
                not isinstance(root, str)
                or not root
                or root != root.strip()
                or "\x00" in root
                or not Path(root).is_absolute()
            ):
                raise CorruptedWorkspaceStoreError(f"workspace record {ref} has invalid canonical_root {root!r}")
            created_at = entry.get("created_at")
            if not isinstance(created_at, (int, float)):
                raise CorruptedWorkspaceStoreError(f"workspace record {ref} has invalid created_at timestamp")
            identity_data = entry.get("identity")
            if identity_data is None:
                raise CorruptedWorkspaceStoreError(f"workspace record {ref} missing identity")
            GitWorktreeIdentity.from_dict(identity_data)

    def load(self) -> dict[str, Any]:
        self.ensure_store_writable()
        if not self.path.exists():
            return {"version": WORKSPACE_STORE_VERSION, "workspaces": {}}

        self._verify_path_security(self.path, is_dir=False)
        try:
            raw_text = self.path.read_text(encoding="utf-8")
        except OSError as exc:
            raise WorkspaceStoreError(f"failed to read store file {self.path}: {exc}") from exc

        if not raw_text.strip():
            return {"version": WORKSPACE_STORE_VERSION, "workspaces": {}}

        try:
            data = json.loads(
                raw_text,
                object_pairs_hook=_reject_duplicate_json_keys,
                parse_constant=_reject_json_constant,
            )
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise CorruptedWorkspaceStoreError(f"store file {self.path} contains malformed JSON: {exc}") from exc

        self._validate_store_schema(data)
        return data

    def _read_nofollow(self) -> bytes:
        fd = os.open(self.path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
        try:
            chunks: list[bytes] = []
            while True:
                block = os.read(fd, 65536)
                if not block:
                    break
                chunks.append(block)
                if sum(len(part) for part in chunks) > 1_048_576:
                    raise OSError("store file exceeds the observation bound")
            return b"".join(chunks)
        finally:
            os.close(fd)

    def _unlink_unpublished_temp(self, temp_path: Path) -> None:
        """Remove one temp file this call created. Never unlinks the store path."""
        if temp_path == self.path or temp_path.name.startswith(".tmp.") is False:
            return
        try:
            info = temp_path.lstat()
        except FileNotFoundError:
            return
        except OSError:
            return
        if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
            return
        try:
            temp_path.unlink()
        except OSError:
            pass

    def save(self, data: dict[str, Any]) -> dict[str, Any]:
        """Publish store bytes. Failures before replace leave the previous file.

        After replace returns, the result is ``published``. A later mode, parent
        fsync, or readback failure is durability ``uncertain`` and does not
        delete or replace the published file.
        """
        self.ensure_store_writable()
        self._validate_store_schema(data)
        payload = json.dumps(data, indent=2, sort_keys=True).encode("utf-8")
        target_dir = self.path.parent
        temp_name = f".tmp.{WORKSPACE_STORE_FILE_NAME}.{secrets.token_hex(6)}"
        temp_path = target_dir / temp_name
        published = False
        fd: int | None = None
        try:
            fd = os.open(
                temp_path,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
                0o600,
            )
            view = memoryview(payload)
            while view:
                written = os.write(fd, view)
                if written <= 0:
                    raise OSError("short store write")
                view = view[written:]
            _fsync_fd(fd)
            os.close(fd)
            fd = None
            os.replace(temp_path, self.path)
            published = True
            reasons: list[str] = []
            try:
                os.chmod(self.path, 0o600)
            except OSError:
                reasons.append("mode_unconfirmed")
            dir_fd: int | None = None
            try:
                dir_fd = os.open(target_dir, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
                _fsync_fd(dir_fd)
            except OSError:
                reasons.append("directory_fsync_unconfirmed")
            finally:
                if dir_fd is not None:
                    os.close(dir_fd)
            readback_matches = False
            try:
                observed = self._read_nofollow()
            except OSError:
                reasons.append("readback_unconfirmed")
            else:
                readback_matches = observed == payload
                if not readback_matches:
                    reasons.append("readback_mismatch")
            return {
                "publication": "published",
                "durability": "uncertain" if reasons else "directory_fsynced",
                "reason": "+".join(reasons) or None,
                "readback_matches": readback_matches,
            }
        except OSError as exc:
            if fd is not None:
                try:
                    os.close(fd)
                except OSError:
                    pass
            if not published:
                self._unlink_unpublished_temp(temp_path)
                raise WorkspaceStoreError(
                    f"failed to write store atomically to {self.path}: {exc}"
                ) from exc
            return {
                "publication": "published",
                "durability": "uncertain",
                "reason": "post_publication_oserror",
                "readback_matches": False,
            }

    def read_persisted_records(self) -> dict[str, Any]:
        """Compare-oriented store read. Does not create, chmod, replace, or stat roots."""
        parent = self.path.parent
        try:
            parent_stat = parent.lstat()
        except FileNotFoundError:
            return {"store": "absent", "reason": "parent_missing", "records": {}, "notes": []}
        except OSError:
            return {"store": "unreadable", "reason": "parent_unreadable", "records": None, "notes": []}
        if stat.S_ISLNK(parent_stat.st_mode) or not stat.S_ISDIR(parent_stat.st_mode):
            return {"store": "unreadable", "reason": "parent_not_directory", "records": None, "notes": []}
        if parent_stat.st_uid != os.getuid():
            return {"store": "unreadable", "reason": "parent_owner", "records": None, "notes": []}
        notes: list[str] = []
        if (parent_stat.st_mode & 0o777) != 0o700:
            notes.append("parent_mode")
        try:
            file_stat = self.path.lstat()
        except FileNotFoundError:
            return {"store": "absent", "reason": "file_missing", "records": {}, "notes": notes}
        except OSError:
            return {"store": "unreadable", "reason": "file_unreadable", "records": None, "notes": notes}
        if stat.S_ISLNK(file_stat.st_mode):
            return {"store": "unreadable", "reason": "symlink", "records": None, "notes": notes}
        if not stat.S_ISREG(file_stat.st_mode):
            return {"store": "unreadable", "reason": "not_regular", "records": None, "notes": notes}
        if file_stat.st_uid != os.getuid():
            return {"store": "unreadable", "reason": "file_owner", "records": None, "notes": notes}
        if (file_stat.st_mode & 0o777) != 0o600:
            notes.append("file_mode")
        try:
            raw = self._read_nofollow()
        except OSError:
            return {"store": "unreadable", "reason": "read_failed", "records": None, "notes": notes}
        if len(raw) > 1_048_576:
            return {"store": "unreadable", "reason": "too_large", "records": None, "notes": notes}
        if not raw.strip():
            return {"store": "readable", "reason": None, "records": {}, "notes": notes}
        try:
            data = json.loads(
                raw.decode("utf-8"),
                object_pairs_hook=_reject_duplicate_json_keys,
                parse_constant=_reject_json_constant,
            )
            self._validate_store_schema(data)
        except (UnicodeError, TypeError, ValueError, json.JSONDecodeError, WorkspaceStoreError):
            return {"store": "unreadable", "reason": "malformed", "records": None, "notes": notes}
        records: dict[str, dict[str, Any]] = {}
        for ref, entry in data["workspaces"].items():
            records[ref] = {
                "canonical_root": entry["canonical_root"],
                "identity": GitWorktreeIdentity.from_dict(entry["identity"]).to_dict(),
            }
        return {"store": "readable", "reason": None, "records": records, "notes": notes}

    def record_workspace(
        self,
        *,
        workspace_ref: str,
        canonical_root: str,
        identity: GitWorktreeIdentity,
    ) -> dict[str, Any]:
        data = self.load()
        workspaces = data.setdefault("workspaces", {})
        existing = workspaces.get(workspace_ref)
        if existing is not None:
            existing_root = existing.get("canonical_root")
            existing_identity_data = existing.get("identity")
            if existing_root != canonical_root:
                raise WorkspaceStoreError(
                    f"store workspace_ref '{workspace_ref}' already registered with different root '{existing_root}'"
                )
            if existing_identity_data is not None:
                try:
                    existing_identity = GitWorktreeIdentity.from_dict(existing_identity_data)
                except CorruptedWorkspaceStoreError as exc:
                    raise WorkspaceStoreError(
                        f"store workspace_ref '{workspace_ref}' has corrupted Git identity"
                    ) from exc
                if existing_identity != identity:
                    raise WorkspaceStoreError(
                        f"store workspace_ref '{workspace_ref}' already registered with different Git identity"
                    )
            # Confirm / repair record
            workspaces[workspace_ref]["canonical_root"] = canonical_root
            workspaces[workspace_ref]["identity"] = identity.to_dict()
        else:
            for other_ref, other_entry in workspaces.items():
                if other_entry.get("canonical_root") == canonical_root:
                    raise WorkspaceStoreError(
                        f"store canonical_root '{canonical_root}' already registered under '{other_ref}'"
                    )
            workspaces[workspace_ref] = {
                "workspace_ref": workspace_ref,
                "canonical_root": canonical_root,
                "identity": identity.to_dict(),
                "created_at": time.time(),
            }
        return self.save(data)


class WorkspaceRegistry:
    """Server configuration for default, static, and dynamic workspace scopes."""

    def __init__(
        self,
        default_root: Path,
        raw: str | None = None,
        *,
        store: WorkspaceRegistryStore | None = None,
        backend_factory: Callable[[Path], Any] | None = None,
    ) -> None:
        self.default_root = Path(default_root).resolve()
        self._backend_factory = backend_factory
        self._store = store if store is not None else WorkspaceRegistryStore()
        self._static_entries: dict[str, tuple[Path, GitWorktreeIdentity]] = {}
        self._dynamic_entries: dict[str, tuple[Path, GitWorktreeIdentity]] = {}
        self._entries: dict[str, tuple[Path, GitWorktreeIdentity]] = {}

        if raw is None:
            raw = os.environ.get(WORKSPACE_REF_ENV)
        if raw is not None and raw.strip():
            self._load_static(raw)

        self._load_dynamic_from_store()

    @property
    def store(self) -> WorkspaceRegistryStore:
        return self._store

    @property
    def refs(self) -> tuple[str, ...]:
        return tuple(sorted(self._entries))

    def is_static(self, workspace_ref: str) -> bool:
        return workspace_ref in self._static_entries

    def get_entry(self, workspace_ref: str) -> tuple[Path, GitWorktreeIdentity] | None:
        return self._entries.get(workspace_ref)

    def all_entries(self) -> dict[str, tuple[Path, GitWorktreeIdentity]]:
        return dict(self._entries)

    def _load_static(self, raw: str) -> None:
        try:
            parsed = json.loads(
                raw,
                object_pairs_hook=_reject_duplicate_json_keys,
                parse_constant=_reject_json_constant,
            )
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"{WORKSPACE_REF_ENV} must be a JSON object of ref/path strings") from exc
        if not isinstance(parsed, dict) or len(parsed) > MAX_WORKSPACE_REFS:
            raise RuntimeError(f"{WORKSPACE_REF_ENV} must contain at most {MAX_WORKSPACE_REFS} entries")
        for ref, value in parsed.items():
            if (
                not isinstance(ref, str)
                or not WORKSPACE_REF_RE.fullmatch(ref)
                or ref == "default"
                or not isinstance(value, str)
                or not value
                or value != value.strip()
                or "\x00" in value
                or not Path(value).is_absolute()
            ):
                raise RuntimeError(f"{WORKSPACE_REF_ENV} contains an invalid workspace reference")
            try:
                root, identity = canonical_git_worktree(value)
            except WorkspaceAuthorizationError as exc:
                raise RuntimeError(f"{WORKSPACE_REF_ENV} contains an invalid registered workspace") from exc
            if any(existing_root == root for existing_root, _ in self._static_entries.values()):
                raise RuntimeError(f"{WORKSPACE_REF_ENV} must not alias one path with multiple refs")
            self._static_entries[ref] = (root, identity)
            self._entries[ref] = (root, identity)

    def _load_dynamic_from_store(self) -> None:
        if self._store is None:
            return
        data = self._store.load()
        workspaces = data.get("workspaces", {})
        for ref, record in workspaces.items():
            if not isinstance(record, dict):
                raise CorruptedWorkspaceStoreError(f"invalid dynamic workspace entry {ref!r}")
            path_str = record.get("canonical_root")
            if (
                not isinstance(ref, str)
                or not WORKSPACE_REF_RE.fullmatch(ref)
                or ref == "default"
                or not isinstance(path_str, str)
                or not Path(path_str).is_absolute()
            ):
                raise CorruptedWorkspaceStoreError(f"invalid dynamic workspace entry {ref!r}")

            identity_data = record.get("identity")
            if identity_data is None:
                raise CorruptedWorkspaceStoreError(f"dynamic workspace entry {ref!r} missing identity")
            expected_identity = GitWorktreeIdentity.from_dict(identity_data)

            # Persisted dynamic entries are authorization/provenance metadata:
            # startup trusts the schema-validated stored canonical path and the
            # stored expected identity WITHOUT consulting the current filesystem
            # or Git state for this route. A vanished or replaced historical root
            # is a use-time authorization failure (resolve() revalidates strictly
            # and fails closed), never a global-boot failure.
            root = Path(path_str)

            if ref in self._static_entries:
                static_root, static_identity = self._static_entries[ref]
                if static_root != root or static_identity != expected_identity:
                    raise RuntimeError(
                        f"dynamic workspace {ref} attempts to redirect static workspace"
                    )
                continue

            for existing_ref, (existing_root, _) in self._entries.items():
                if existing_ref != ref and existing_root == root:
                    raise RuntimeError(
                        f"dynamic workspace {ref} aliases existing path registered as {existing_ref}"
                    )

            if len(self._entries) >= MAX_WORKSPACE_REFS:
                raise RuntimeError(f"registered workspaces exceed max limit of {MAX_WORKSPACE_REFS}")

            self._dynamic_entries[ref] = (root, expected_identity)
            self._entries[ref] = (root, expected_identity)

    def observe_registration(self) -> dict[str, Any]:
        """Point-in-time live-versus-persisted comparison.

        Uses process memory and one no-follow store read. It does not mkdir,
        chmod, save, repair, or stat registered workspace roots. A stale route
        that startup loaded without consulting Git still matches its persisted
        record; use-time ``resolve()`` remains the identity check.
        """
        snap = self._store.read_persisted_records()
        live_dynamic = {
            ref: {"canonical_root": str(root), "identity": identity.to_dict()}
            for ref, (root, identity) in self._dynamic_entries.items()
        }
        live_static = {
            ref: {"canonical_root": str(root), "identity": identity.to_dict()}
            for ref, (root, identity) in self._static_entries.items()
        }
        if snap["store"] == "unreadable" or snap["records"] is None:
            return {
                "status": "unreadable",
                "store": "unreadable",
                "reason": snap.get("reason"),
                "notes": snap.get("notes") or [],
                "live_dynamic_count": len(live_dynamic),
                "persisted_count": None,
                "live_only": [],
                "persisted_only": [],
                "root_or_identity_mismatch": [],
            }
        persisted = snap["records"]
        live_only = sorted(ref for ref in live_dynamic if ref not in persisted)
        mismatched: list[str] = []
        persisted_only: list[str] = []
        for ref, record in persisted.items():
            if ref in live_dynamic:
                current = live_dynamic[ref]
            elif ref in live_static:
                current = live_static[ref]
            else:
                persisted_only.append(ref)
                continue
            if (
                current["canonical_root"] != record["canonical_root"]
                or current["identity"] != record["identity"]
            ):
                mismatched.append(ref)
        persisted_only.sort()
        mismatched.sort()
        status = "mismatch" if live_only or persisted_only or mismatched else "matched"
        return {
            "status": status,
            "store": snap["store"],
            "reason": snap.get("reason"),
            "notes": snap.get("notes") or [],
            "live_dynamic_count": len(live_dynamic),
            "persisted_count": len(persisted),
            "live_only": live_only,
            "persisted_only": persisted_only,
            "root_or_identity_mismatch": mismatched,
        }

    def registration_view(self, project_ref: str | None) -> dict[str, Any]:
        """Full comparison, or one ref without naming any other ref."""
        full = self.observe_registration()
        if project_ref is None:
            return full
        if project_ref in self._static_entries:
            route = "static"
        elif project_ref in self._dynamic_entries:
            route = "dynamic"
        else:
            route = "absent"
        if full["status"] == "unreadable":
            relation = "unreadable"
        elif project_ref in full["live_only"]:
            relation = "live_only"
        elif project_ref in full["persisted_only"]:
            relation = "persisted_only"
        elif project_ref in full["root_or_identity_mismatch"]:
            relation = "root_or_identity_mismatch"
        elif route == "static":
            relation = "static_configuration"
        elif route == "dynamic":
            relation = "matched"
        else:
            relation = "absent"
        return {
            "project_ref": project_ref,
            "route": route,
            "store": full["store"],
            "reason": full["reason"],
            "relation": relation,
            "notes": full["notes"],
        }

    def register_dynamic(self, workspace_ref: str, root: Path, identity: GitWorktreeIdentity) -> dict[str, Any]:
        if workspace_ref in self._static_entries:
            static_root, static_identity = self._static_entries[workspace_ref]
            if static_root != root or static_identity != identity:
                raise RuntimeError(
                    f"dynamic workspace {workspace_ref} attempts to redirect static workspace"
                )
        for existing_ref, (existing_root, _) in self._entries.items():
            if existing_ref != workspace_ref and existing_root == root:
                raise RuntimeError(
                    f"dynamic workspace {workspace_ref} aliases existing path registered as {existing_ref}"
                )
        if workspace_ref not in self._entries and len(self._entries) >= MAX_WORKSPACE_REFS:
            raise RuntimeError(f"registered workspaces exceed max limit of {MAX_WORKSPACE_REFS}")
        outcome = self._store.record_workspace(
            workspace_ref=workspace_ref,
            canonical_root=str(root),
            identity=identity,
        )
        if outcome.get("readback_matches"):
            self._dynamic_entries[workspace_ref] = (root, identity)
            self._entries[workspace_ref] = (root, identity)
            outcome["memory_updated"] = True
        else:
            outcome["memory_updated"] = False
        outcome["registration"] = self.observe_registration()
        return outcome

    def resolve(self, workspace_ref: str | None, *, default_root: Path | None = None) -> WorkspaceContext:
        if workspace_ref is None:
            root = (default_root or self.default_root).resolve()
            backend = self._backend_factory(root) if self._backend_factory else None
            return WorkspaceContext(None, root, None, str(root), backend)
        if not isinstance(workspace_ref, str) or not WORKSPACE_REF_RE.fullmatch(workspace_ref):
            raise WorkspaceAuthorizationError("workspace_ref is not authorized")
        entry = self._entries.get(workspace_ref)
        if entry is None:
            raise WorkspaceAuthorizationError("workspace_ref is not authorized")
        root, identity = entry
        try:
            validate_git_worktree_identity(root, identity)
        except WorkspaceAuthorizationError:
            raise
        backend = self._backend_factory(root) if self._backend_factory else None
        return WorkspaceContext(workspace_ref, root, identity, str(root), backend)
