"""Exact staged candidates. No server registration, shell, or recovery daemon.

Linux/files-ref/local-object-store slice. The adapter supplies authorized frozen
EvidenceTargets and the existing writer gate; tokens/receipts are process-local.
"""
from collections import OrderedDict
from contextlib import contextmanager
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import selectors
import secrets
import shutil
import signal
import stat
import subprocess
import tempfile
import threading
import time

from evidence_target import EvidenceTarget

MAX_BYTES = 4 * 1024 * 1024
PATCH_DISPLAY_BYTES = 2 * 1024 * 1024
MAX_CANDIDATE_ENTRIES = 20000
MAX_CANDIDATES = 8
MAX_CACHE_BYTES = 32 * 1024 * 1024
RECEIPT_RESERVE = 256 * 1024
MAX_PAGE = 16384
OP_SECONDS = 30
GIT = shutil.which("git")
PATCH_TRUNCATION_MARKER = (
    "\n# bridge: patch display truncated at {cap} bytes; remaining staged files omitted\n"
    "# bridge: view=summary lists every staged file with mode and object ids\n")


class Refused(Exception):
    pass


class GitFailure(Exception):
    def __init__(self, outcome):
        self.outcome = outcome
        super().__init__("git-" + outcome)


def _need(condition, reason):
    if not condition:
        raise Refused(reason)


def _hash(data):
    return hashlib.sha256(data).hexdigest()


def _json_hash(value):
    return _hash(json.dumps(value, sort_keys=True, ensure_ascii=True).encode())


def _environment():
    allowed = {"GIT_OPTIONAL_LOCKS", "GIT_CONFIG_GLOBAL", "GIT_CONFIG_SYSTEM", "GIT_CONFIG_NOSYSTEM"}
    _need(not any(k.startswith("GIT_") and v and k not in allowed for k, v in os.environ.items()),
          "unsupported-git-environment")
    # In particular, no author/committer override, injected config, trace file,
    # alternate index/object store, or command helper is inherited accidentally.
    return {**os.environ, "GIT_OPTIONAL_LOCKS": "0", "GIT_NO_REPLACE_OBJECTS": "1",
            "GIT_NO_LAZY_FETCH": "1", "GIT_ALLOW_PROTOCOL": "", "GIT_TERMINAL_PROMPT": "0"}


def _file(path, limit=MAX_BYTES):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        before = os.fstat(fd)
        _need(stat.S_ISREG(before.st_mode) and before.st_nlink == 1, "indirect-metadata-file")
        _need(before.st_size <= limit, "metadata-size-limit")
        chunks, size = [], 0
        while True:
            chunk = os.read(fd, min(65536, limit + 1 - size))
            if not chunk:
                break
            chunks.append(chunk)
            size += len(chunk)
            _need(size <= limit, "metadata-size-limit")
        after = os.fstat(fd)
        _need((before.st_size, before.st_mtime_ns, before.st_ctime_ns) ==
              (after.st_size, after.st_mtime_ns, after.st_ctime_ns), "metadata-changed-during-read")
        return b"".join(chunks)
    finally:
        os.close(fd)


def _directory(path):
    path = Path(path)
    for part in (path, *path.parents):
        st = part.lstat()
        _need(stat.S_ISDIR(st.st_mode), "indirect-metadata-directory")
    st = path.lstat()
    return (st.st_dev, st.st_ino)


def _pointer(path):
    data = _file(path, 4096)
    st = path.lstat()
    return (st.st_dev, st.st_ino, _hash(data)), data


def _capture(root, args, env, deadline, input_bytes, cap, soft):
    """Shared bounded capture with deadline and process-group reap.

    Hard mode (soft=False) refuses git-output-limit past cap; safety callers
    rely on that refusal. Soft mode (display-only evidence) keeps the retained
    prefix, terminates the writer, drains its pipes and reports truncation.
    """
    with tempfile.TemporaryFile() as inp:
        if input_bytes is not None:
            inp.write(input_bytes)
        inp.seek(0)
        try:
            proc = subprocess.Popen([GIT, "--no-pager", *args], cwd=root, env=env,
                                    stdin=inp, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                    start_new_session=True)
        except OSError:
            raise GitFailure("spawn-failed") from None
        chunks = {"stdout": bytearray(), "stderr": bytearray()}
        until = min(deadline, time.monotonic() + 10)
        truncated = False
        with selectors.DefaultSelector() as selector:
            for name, pipe in (("stdout", proc.stdout), ("stderr", proc.stderr)):
                os.set_blocking(pipe.fileno(), False)
                selector.register(pipe, selectors.EVENT_READ, name)
            try:
                while selector.get_map() or proc.poll() is None:
                    if time.monotonic() >= until:
                        raise GitFailure("timeout")
                    for key, _ in selector.select(min(.05, max(0, until - time.monotonic()))):
                        block = os.read(key.fileobj.fileno(), 65536)
                        if not block:
                            selector.unregister(key.fileobj)
                        else:
                            budget = cap - len(chunks[key.data])
                            if budget > 0:
                                chunks[key.data].extend(block[:budget])
                            if len(block) > budget:
                                if not soft:
                                    raise Refused("git-output-limit")
                                if not truncated:
                                    truncated = True
                                    try:
                                        os.killpg(proc.pid, signal.SIGKILL)
                                    except ProcessLookupError:
                                        pass
                return proc.wait(), bytes(chunks["stdout"]), bytes(chunks["stderr"]), truncated
            finally:
                # Fixed Git may use child pack processes. On exceptional return,
                # terminate the owned group even if the leader already exited.
                if selector.get_map() or proc.poll() is None:
                    try:
                        os.killpg(proc.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                    proc.wait(timeout=2)
                proc.stdout.close()
                proc.stderr.close()


def _run_git(root, args, env, deadline, input_bytes=None):
    """Private fixed-command seam; bounded binary output, deadline and group reap.

    No caller of the public store supplies argv/env. Nonzero exit is distinct
    from timeout/output overflow; mutation callers conservatively seal either.
    """
    _need(time.monotonic() < deadline, "operation-deadline")
    rc, stdout, stderr, _ = _capture(root, args, env, deadline, input_bytes, MAX_BYTES, False)
    return rc, stdout, stderr


def _run_git_display(root, args, env, deadline, cap=PATCH_DISPLAY_BYTES):
    """Display-only bounded capture: overflow terminates the writer and is
    reported as truncation, never refused. Timeout/spawn stay GitFailure."""
    _need(time.monotonic() < deadline, "operation-deadline")
    return _capture(root, args, env, deadline, None, cap, True)


class _Binding:
    def __init__(self, target, deadline):
        self.target, self.deadline = target, deadline
        self.observation_limit = 64
        self.root = target.workspace.root
        identity = target.workspace.git
        _need(identity is not None and not identity.bare, "registered-worktree-required")
        self.gitdir, self.common = Path(identity.git_dir), Path(identity.git_common_dir)
        self.objects = self.common / "objects"
        self.expected_dirs = {self.root: (identity.root_device, identity.root_inode),
                              self.gitdir: (identity.git_dir_device, identity.git_dir_inode),
                              self.common: (identity.git_common_device, identity.git_common_inode)}
        self.pointers, self.fds, self.events, self.owned_locks = {}, [], [], {}
        self.storage_dirs = {}
        self.env = _environment()
        marker = self.root / ".git"
        if marker.is_dir() and not marker.is_symlink():
            _need(marker == self.gitdir == self.common, "unexpected-git-directory-layout")
        else:
            sig, raw = _pointer(marker)
            _need(raw.startswith(b"gitdir: "), "invalid-gitfile")
            pointed = (self.root / raw[8:].decode().strip()).resolve()
            _need(pointed == self.gitdir and self.gitdir != self.common, "gitfile-target-changed")
            self.pointers[marker] = sig
            sig, raw = _pointer(self.gitdir / "commondir")
            _need((self.gitdir / raw.decode().strip()).resolve() == self.common, "commondir-changed")
            self.pointers[self.gitdir / "commondir"] = sig
            sig, raw = _pointer(self.gitdir / "gitdir")
            _need((self.gitdir / raw.decode().strip()).resolve() == marker, "worktree-backpointer-changed")
            self.pointers[self.gitdir / "gitdir"] = sig
        self.expected_dirs[self.objects] = _directory(self.objects)
        self.basic()
        try:
            for path in (self.root, self.gitdir, self.common, self.objects):
                fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
                self.fds.append(fd)
                st = os.fstat(fd)
                _need((st.st_dev, st.st_ino) == self.expected_dirs[path], "directory-object-changed")
            prefix = f"/proc/{os.getpid()}/fd/"
            self.env.update(GIT_WORK_TREE=str(self.root), GIT_DIR=prefix + str(self.fds[1]),
                            GIT_COMMON_DIR=prefix + str(self.fds[2]),
                            GIT_OBJECT_DIRECTORY=prefix + str(self.fds[3]))
        except BaseException:
            self.close()
            raise

    def close(self):
        for fd in self.fds:
            os.close(fd)
        self.fds.clear()

    def basic(self):
        _need(time.monotonic() < self.deadline, "operation-deadline")
        for path, expected in self.expected_dirs.items():
            _need(_directory(path) == expected, "directory-object-changed")
        for path, expected in self.pointers.items():
            _need(_pointer(path)[0] == expected, "git-pointer-changed")

    def storage(self):
        """Bounded local storage checks, not a claim of an OS-atomic sandbox."""
        self.basic()
        for path in (self.common / "shallow", self.objects / "info/alternates",
                     self.objects / "info/http-alternates", self.common / "info/grafts"):
            _need(not os.path.lexists(path), "indirect-or-shallow-object-store")
        observed = {}
        def inspect(path):
            # Inspect only named endpoints and their ancestors, never children.
            _need(time.monotonic() < self.deadline, "operation-deadline")
            if not os.path.lexists(path):
                return
            st = path.lstat()
            _need(stat.S_ISREG(st.st_mode) or stat.S_ISDIR(st.st_mode), "indirect-git-storage")
            if stat.S_ISDIR(st.st_mode):
                observed[str(path)] = _directory(path)
            else:
                _directory(path.parent)
                _need(st.st_nlink == 1, "hardlinked-git-storage")
        def endpoint(path, base):
            for parent in reversed(path.relative_to(base).parents):
                inspect(base / parent)
            inspect(path)
        for base in {self.common, self.gitdir}:
            for name in ("HEAD", "index", "config", "config.worktree", "packed-refs",
                         "HEAD.lock", "index.lock", "packed-refs.lock"):
                inspect(base / name)
        # commit-tree's timestamp-dependent oid is not known before creation.
        # These 256 possible loose-object destinations are a constant bound;
        # no object bodies, pack contents, historical refs or logs are scanned.
        for name in ["info", "pack"] + [f"{n:02x}" for n in range(256)]:
            inspect(self.objects / name)
        branch = getattr(self, "branch", None)
        if branch:
            for path in (self.common / branch, Path(str(self.common / branch) + ".lock"),
                         self.common / "logs" / branch, self.gitdir / "logs/HEAD"):
                endpoint(path, self.common if path.is_relative_to(self.common) else self.gitdir)
        for path, old in self.storage_dirs.items():
            _need(observed.get(path) == old, "storage-directory-changed")
        self.storage_dirs.update(observed)
        for name in ("MERGE_HEAD", "CHERRY_PICK_HEAD", "REVERT_HEAD", "rebase-merge", "rebase-apply", "sequencer"):
            _need(not os.path.lexists(self.gitdir / name), "in-progress-operation")
        for name in ("HEAD.lock", "index.lock"):
            path = self.gitdir / name
            if os.path.lexists(path):
                st = path.lstat()
                _need(self.owned_locks.get(name) == (st.st_dev, st.st_ino), "checkout-busy")
        return dict(self.storage_dirs)

    def git(self, args, *, index=None, input_bytes=None, codes=(0,)):
        self.basic()
        operation = args[2] if args[:2] == ["-c", "core.hooksPath=/dev/null"] else args[0]
        if operation in ("mktree", "commit-tree", "update-ref", "hash-object", "update-index"):
            self.storage()
        _need(len(self.events) < self.observation_limit, "git-observation-count-limit")
        env = dict(self.env)
        if index is not None:
            env["GIT_INDEX_FILE"] = str(index)
        started = time.monotonic()
        event = {"operation": operation}
        self.events.append(event)
        try:
            rc, stdout, stderr = _run_git(self.root, args, env, self.deadline, input_bytes)
            event.update(outcome="exited", exit_code=rc, stdout_sha256=_hash(stdout),
                         stdout_bytes=len(stdout), stderr=stderr[:1024].decode("utf-8", "replace"))
            self.basic()
            if rc not in codes:
                raise GitFailure("nonzero")
            return stdout
        except (GitFailure, Refused) as error:
            event.setdefault("outcome", str(error))
            raise
        finally:
            event["duration_seconds"] = round(time.monotonic() - started, 6)

    def display(self, args, *, index=None):
        """Display-only bounded capture; truncation is reported, never refused.

        Safety facts (snapshot/policy/storage) never depend on this result; a
        GitFailure here means display evidence is unavailable, not that the
        staged candidate is unsafe. Events are marked display=True so receipts
        distinguish display truncation from safety observations.
        """
        self.basic()
        _need(len(self.events) < self.observation_limit, "git-observation-count-limit")
        env = dict(self.env)
        if index is not None:
            env["GIT_INDEX_FILE"] = str(index)
        started = time.monotonic()
        event = {"operation": args[0], "display": True}
        self.events.append(event)
        try:
            rc, stdout, stderr, truncated = _run_git_display(
                self.root, args, env, self.deadline, PATCH_DISPLAY_BYTES)
            event.update(outcome="exited", exit_code=rc, stdout_sha256=_hash(stdout),
                         stdout_bytes=len(stdout), stderr=stderr[:1024].decode("utf-8", "replace"))
            if truncated:
                event["outcome"] = "truncated"
                event["truncated"] = True
            self.basic()
            # A clean-truncated display (writer intentionally killed at the soft
            # cap) is successful incomplete evidence; any other nonzero exit is
            # display loss, never a silent empty/partial patch.
            if not truncated and rc != 0:
                raise GitFailure("nonzero")
            return stdout, truncated
        except (GitFailure, Refused) as error:
            event.setdefault("outcome", str(error))
            raise
        finally:
            event["duration_seconds"] = round(time.monotonic() - started, 6)

    def policy(self):
        raw = self.git(["config", "--null", "--show-origin", "--list", "--includes"])
        records = raw.split(b"\0")
        _need(records[-1] == b"" and len(records) % 2 == 1, "config-output-malformed")
        config, origins, normalized, source_by_origin = {}, {}, [], {}
        source_bytes = 0
        for pos in range(0, len(records)-1, 2):
            _need(time.monotonic() < self.deadline, "operation-deadline")
            origin, record = records[pos:pos+2]
            key, _, value = record.partition(b"\n")
            config[key.decode().lower()] = value.decode()
            if origin.startswith(b"file:"):
                if origin not in source_by_origin:
                    path = Path(os.fsdecode(origin[5:]))
                    path = path if path.is_absolute() else self.root / path
                    if str(path) == "/dev/null":
                        source = str(path)
                        origins[source] = "empty-device"
                    else:
                        resolved = path.resolve(strict=True)
                        source = str(resolved)
                        if source not in origins:
                            content = _file(resolved, MAX_BYTES - source_bytes)
                            source_bytes += len(content)
                            origins[source] = _hash(content)
                    source_by_origin[origin] = source
                source = source_by_origin[origin]
                # Git reports our pinned /proc fd path as the config origin.
                # Descriptor numbers are not repository/config versions.
                normalized.append((source, key.decode(), value.decode()))
            else:
                raise Refused("unsupported-config-origin")
        _need(config.get("commit.gpgsign", "false").lower() in ("false", "no", "off", "0"), "signing-unsupported")
        _need(config.get("core.fsmonitor", "false").lower() in ("false", "no", "off", "0"), "fsmonitor-unsupported")
        _need(config.get("core.splitindex", "false").lower() in ("false", "no", "off", "0"), "split-index-unsupported")
        _need(config.get("i18n.commitencoding", "utf-8").lower().replace("-", "") == "utf8",
              "commit-encoding-unsupported")
        _need(config.get("extensions.refstorage", "files") == "files", "ref-storage-unsupported")
        _need(not config.get("extensions.compatobjectformat"), "compat-object-format-unsupported")
        _need(not config.get("extensions.partialclone") and not any(
            k.startswith("remote.") and k.endswith(".promisor") and v.lower() not in ("false", "no", "off", "0")
            for k, v in config.items()), "promisor-store-unsupported")
        for role in ("author", "committer"):
            for field in ("name", "email"):
                _need(bool(config.get(role + "." + field, config.get("user." + field, "")).strip()),
                      "configured-identity-required")
        hooks = Path(config.get("core.hookspath", str(self.common / "hooks")))
        if not hooks.is_absolute():
            hooks = self.root / hooks
        hook_state = []
        if str(hooks) != "/dev/null" and os.path.lexists(hooks):
            hook_state.append(_directory(hooks))
            for name in ("pre-commit", "prepare-commit-msg", "commit-msg",
                         "post-commit", "reference-transaction"):
                path = hooks / name
                if not os.path.lexists(path):
                    continue
                st = path.lstat()
                _need(stat.S_ISREG(st.st_mode) and st.st_nlink == 1, "indirect-hook-location")
                _need(not os.access(path, os.X_OK), "active-hooks-unsupported")
                hook_state.append((name, st.st_mode, _hash(_file(path))))
        # `git var` validates the effective configured identities, without
        # inventing a name/email or invoking editor/signing/credential helpers.
        author = self.git(["var", "GIT_AUTHOR_IDENT"])
        committer = self.git(["var", "GIT_COMMITTER_IDENT"])
        # Timestamps vary between observations; identity bytes precede `> `.
        identities = (author.rsplit(b"> ", 1)[0], committer.rsplit(b"> ", 1)[0])
        config_environment = [self.env.get(key) for key in
                              ("GIT_CONFIG_GLOBAL", "GIT_CONFIG_SYSTEM", "GIT_CONFIG_NOSYSTEM")]
        return _json_hash([normalized, origins, config_environment, str(hooks), hook_state,
                           [_hash(value) for value in identities]])

    def snapshot(self):
        dirs = self.storage()
        policy = self.policy()
        branch = self.git(["symbolic-ref", "-q", "HEAD"]).decode().strip()
        _need(branch.startswith("refs/heads/"), "attached-local-branch-required")
        self.git(["check-ref-format", branch])
        self.branch = branch
        dirs = self.storage()
        loose = self.common / branch
        if os.path.lexists(loose):
            _need(not _file(loose, 1024).startswith(b"ref:"), "symbolic-branch-unsupported")
        _need(not os.path.lexists(Path(str(loose) + ".lock")), "branch-busy")
        parent = self.git(["rev-parse", "--verify", "HEAD"]).decode().strip()
        _need(len(parent) in (40, 64) and all(c in "0123456789abcdef" for c in parent), "parent-unavailable")
        index_bytes = _file(self.gitdir / "index")
        return {"branch": branch, "parent": parent, "index_sha256": _hash(index_bytes),
                "policy_sha256": policy, "directories": dirs,
                "binding": _json_hash([[(str(p), v) for p, v in self.expected_dirs.items()],
                                       [(str(p), v) for p, v in self.pointers.items()]])}, index_bytes

    @contextmanager
    def locks(self):
        acquired = []
        try:
            # update-ref takes HEAD.lock itself when updating the current
            # branch. Holding it here would reject every normal commit.
            for name in ("index.lock",):
                fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                             0o600, dir_fd=self.fds[1])
                st = os.fstat(fd)
                self.owned_locks[name] = (st.st_dev, st.st_ino)
                acquired.append((name, fd))
            yield
        finally:
            clean = True
            for name, fd in reversed(acquired):
                try:
                    st = os.stat(name, dir_fd=self.fds[1], follow_symlinks=False)
                    if (st.st_dev, st.st_ino) == self.owned_locks[name]:
                        os.unlink(name, dir_fd=self.fds[1])
                    else:
                        clean = False
                except OSError:
                    clean = False
                finally:
                    os.close(fd)
                    self.owned_locks.pop(name, None)
            _need(clean, "owned-lock-cleanup-unconfirmed")


def _index_tree(raw, algorithm):
    """Git tree serialization/hashing from stage-0 entries; writes no objects."""
    _need(algorithm in ("sha1", "sha256"), "object-format-unsupported")
    _need(not raw or raw.endswith(b"\0"), "index-record-truncated")
    root = {}
    directories = 1
    records = raw[:-1].split(b"\0") if raw else []
    _need(len(records) <= MAX_CANDIDATE_ENTRIES, "index-entry-limit")
    oid_length = 40 if algorithm == "sha1" else 64
    for record in records:
        meta, name = record.split(b"\t", 1)
        mode, oid, stage = meta.split(b" ")
        _need(stage == b"0", "unmerged-index-unsupported")
        _need(mode in (b"100644", b"100755", b"120000", b"160000"), "index-mode-unsupported")
        _need(len(oid) == oid_length and all(c in b"0123456789abcdef" for c in oid) and set(oid) != {48},
              "index-object-unavailable")
        name.decode("utf-8")
        parts = name.split(b"/")
        _need(all(p not in (b"", b".", b"..", b".git") for p in parts), "index-path-unsupported")
        node = root
        for part in parts[:-1]:
            if part not in node:
                directories += 1
                _need(directories <= MAX_CANDIDATE_ENTRIES, "index-directory-limit")
            node = node.setdefault(part, {})
            _need(isinstance(node, dict), "index-path-conflict")
        _need(parts[-1] not in node, "index-path-conflict")
        node[parts[-1]] = (mode, bytes.fromhex(oid.decode()))
    # Iterative postorder avoids Python recursion limits for nested paths.
    nodes, pending = [], [root]
    while pending:
        node = pending.pop()
        nodes.append(node)
        pending.extend(value for value in node.values() if isinstance(value, dict))
    hashes, batch, expected = {}, bytearray(), bytearray()
    for node in reversed(nodes):
        body = bytearray()
        for name in sorted(node, key=lambda n: n + (b"/" if isinstance(node[n], dict) else b"")):
            value = node[name]
            mode, oid = (b"40000", hashes[id(value)]) if isinstance(value, dict) else value
            body.extend(mode + b" " + name + b"\0" + oid)
            kind = b"tree" if mode == b"40000" else b"commit" if mode == b"160000" else b"blob"
            batch.extend(mode + b" " + kind + b" " + oid.hex().encode() + b"\t" + name + b"\0")
        digest = hashlib.new(algorithm, b"tree " + str(len(body)).encode() + b"\0" + body).digest()
        hashes[id(node)] = digest
        batch.extend(b"\0")  # mktree --batch -z: empty record ends one tree.
        expected.extend(digest.hex().encode() + b"\n")
        _need(len(batch) <= MAX_BYTES and len(expected) <= MAX_BYTES, "tree-batch-size-limit")
    return hashes[id(root)].hex(), bytes(batch), bytes(expected)


def _summary(raw):
    _need(not raw or raw.endswith(b"\0"), "diff-record-truncated")
    records = raw[:-1].split(b"\0") if raw else []
    _need(len(records) % 2 == 0 and len(records) <= 2 * MAX_CANDIDATE_ENTRIES, "diff-record-invalid")
    files = []
    for pos in range(0, len(records), 2):
        oldmode, mode, old, new, status_code = records[pos].split(b" ")
        _need(oldmode.startswith(b":") and status_code in (b"A", b"M", b"D", b"T"), "diff-record-invalid")
        files.append({"path": records[pos+1].decode("utf-8"), "status": status_code.decode(),
                      "old_mode": oldmode[1:].decode(), "mode": mode.decode(),
                      "old_object": old.decode(), "object": new.decode()})
    return files


def _binary_flags(raw):
    """Aggregate binary classification from one numstat -z call; no blob reads."""
    _need(not raw or raw.endswith(b"\0"), "numstat-record-truncated")
    records = raw[:-1].split(b"\0") if raw else []
    _need(len(records) <= MAX_CANDIDATE_ENTRIES, "numstat-record-limit")
    flags = {}
    for record in records:
        added, deleted, path = record.split(b"\t", 2)
        flags[path.decode("utf-8")] = added == b"-" and deleted == b"-"
    return flags


def _annotate_files(binding, files, parent, index):
    """Bounded per-file audit metadata from aggregate Git operations only.

    Binary flags come from one numstat -z pass; object sizes/kinds come from
    one cat-file --batch-check over the already frozen staged OIDs. No blob
    bodies are read for classification and there is no per-file command loop.
    """
    flags = _binary_flags(binding.git(
        ["diff", "--cached", "--no-ext-diff", "--no-textconv", "--no-renames", "--no-color",
         "--no-relative", "--ignore-submodules=none", "--submodule=short",
         "--numstat", "-z", "--ita-invisible-in-index", parent, "--"], index=index))
    oids, seen = [], set()
    for entry in files:
        for key in ("object", "old_object"):
            oid = entry[key]
            if set(oid) != {"0"} and oid not in seen:
                seen.add(oid)
                oids.append(oid)
    _need(len(oids) <= 2 * MAX_CANDIDATE_ENTRIES, "object-metadata-limit")
    sizes, kinds = {}, {}
    if oids:
        raw = binding.git(["cat-file", "--batch-check=%(objectname) %(objecttype) %(objectsize)"],
                          input_bytes="".join(oid + "\n" for oid in oids).encode())
        _need(raw.endswith(b"\n"), "object-metadata-truncated")
        _need(len(raw.splitlines()) == len(oids), "object-metadata-mismatch")
        for line in raw.splitlines():
            parts = line.split(b" ")
            oid = parts[0].decode()
            if len(parts) == 3:
                kinds[oid], sizes[oid] = parts[1].decode(), int(parts[2])
            else:
                kinds[oid], sizes[oid] = None, None
    for entry in files:
        entry["binary"] = flags.get(entry["path"])
        for oid_key, size_key, kind_key in (("object", "object_size", "object_kind"),
                                            ("old_object", "old_object_size", "old_object_kind")):
            oid = entry[oid_key]
            if set(oid) == {"0"}:
                entry[size_key], entry[kind_key] = None, None
            else:
                entry[kind_key] = kinds.get(oid)
                entry[size_key] = sizes.get(oid) if entry[kind_key] == "blob" else None
    return files


def _decode_display(data):
    """Patch text is display evidence; lossy bytes must not reject a candidate."""
    try:
        return data.decode("utf-8"), False
    except UnicodeDecodeError:
        return data.decode("utf-8", "replace"), True


def _same_snapshot(before, after, *, index=True):
    for key in ("binding", "branch", "parent", "index_sha256", "policy_sha256"):
        if not index and key == "index_sha256":
            continue
        _need(before[key] == after[key], key + "-changed")
    for path, identity in before["directories"].items():
        _need(after["directories"].get(path) == identity, "storage-directory-changed")


_INDEX_ENTRY_MODES = (0o100644, 0o100755, 0o120000, 0o160000)
# skip-worktree | intent-to-add: the only extended-flag bits Git defines.
_INDEX_EXTENDED_FLAG_BITS = 0x6000


def _index_varint(raw, pos, limit, maximum):
    """Decode Git's OFS_DELTA-style varint: the v4 name prefix strip length.

    The decoded value only grows while continuation bits continue, so decoding
    rejects as soon as the partial value cannot stay <= maximum (the previous
    name length); long continuation runs therefore fail in a handful of bytes,
    far below any operation deadline, and never decode a value that could not
    be a valid strip count.
    """
    _need(pos < limit, "index-format-invalid")
    byte = raw[pos]
    pos += 1
    value = byte & 0x7F
    while byte & 0x80:
        _need(value <= maximum, "index-path-strip-invalid")
        _need(pos < limit, "index-format-invalid")
        byte = raw[pos]
        pos += 1
        value = ((value + 1) << 7) | (byte & 0x7F)
    _need(value <= maximum, "index-path-strip-invalid")
    return value, pos


def _index_admission_identity(raw, algorithm):
    """Bounded semantic admission identity of an index file (versions 2-4).

    Format, the trailing checksum and the entry layout are validated:
    entry modes (040000 sparse directory entries refuse outright), name
    constraints (nonempty, no empty/./../.git components), declared name
    length equal to the full reconstructed name length (saturating at 0xFFF)
    in every version, strict (path, stage) entry order, NUL entry padding in
    v2/v3, reserved extended-flag bits, and extension signatures (the
    split-index "link" and sparse-index "sdir" extensions refuse; per native
    Git an unknown extension is optional only when its signature starts with
    an uppercase letter — such payloads are retained byte-exact — and any
    other first byte makes it mandatory, which refuses). Each entry's
    volatile stat-cache fields (ctime/mtime/dev/ino/uid/gid/size) are
    normalized to zero; everything else — v4 names reconstructed with Git's
    strip-from-the-previous-end semantics, modes, OIDs, stage, flags, padding
    and raw extension payload bytes — is retained, so any semantic, layout or
    extension change changes the identity. Malformed layouts refuse rather
    than admit.
    """
    _need(algorithm in ("sha1", "sha256"), "object-format-unsupported")
    oid = 20 if algorithm == "sha1" else 32
    _need(len(raw) >= 12 + oid, "index-format-invalid")
    _need(raw[:4] == b"DIRC", "index-format-invalid")
    version = int.from_bytes(raw[4:8], "big")
    count = int.from_bytes(raw[8:12], "big")
    _need(version in (2, 3, 4), "index-version-admission-unsupported")
    _need(count <= MAX_CANDIDATE_ENTRIES, "index-entry-limit")
    checksum_at = len(raw) - oid
    _need(hashlib.new(algorithm, raw[:checksum_at]).digest() == raw[checksum_at:],
          "index-checksum-invalid")
    normalized = bytearray(raw)
    normalized[checksum_at:] = b"\0" * oid  # derived trailing checksum, not semantic
    pos, previous_name, previous_stage = 12, b"", None
    for _ in range(count):
        fixed = 40 + oid + 2
        _need(pos + fixed <= checksum_at, "index-format-invalid")
        # Volatile stat cache: ctime/mtime/dev/ino precede mode, uid/gid/size
        # follow it. Mode itself is semantic and constrained.
        mode = int.from_bytes(raw[pos + 24:pos + 28], "big")
        _need(mode != 0o040000, "sparse-index-unsupported")
        _need(mode in _INDEX_ENTRY_MODES, "index-mode-invalid")
        flags = int.from_bytes(raw[pos + 40 + oid:pos + fixed], "big")
        name_at = pos + fixed
        if flags & 0x4000:
            _need(version >= 3, "index-format-invalid")
            _need(name_at + 2 <= checksum_at, "index-format-invalid")
            extended = int.from_bytes(raw[name_at:name_at + 2], "big")
            _need(extended & ~_INDEX_EXTENDED_FLAG_BITS == 0, "index-extended-flags-invalid")
            name_at += 2
        normalized[pos:pos + 24] = b"\0" * 24
        normalized[pos + 28:pos + 40] = b"\0" * 12
        if version == 4:
            strip, name_at = _index_varint(raw, name_at, checksum_at, len(previous_name))
            end = raw.find(b"\0", name_at, checksum_at)
            _need(end != -1, "index-format-invalid")
            # The strip count is the number of bytes removed from the END of
            # the previous pathname; zero keeps it whole, len(previous) drops
            # it entirely.
            name = previous_name[:len(previous_name) - strip] + raw[name_at:end]
            pos = end + 1
        else:
            end = raw.find(b"\0", name_at, checksum_at)
            _need(end != -1, "index-format-invalid")
            name = raw[name_at:end]
            entry_end = pos + (((name_at - pos) + (end - name_at) + 8) & ~7)
            _need(entry_end <= checksum_at, "index-format-invalid")
            _need(not any(raw[end + 1:entry_end]), "index-padding-invalid")
            pos = entry_end
        # The declared 12-bit name length carries the full name length in
        # every version (saturating at 0xFFF), including reconstructed v4
        # names; non-ASCII names count UTF-8 bytes.
        _need((flags & 0x0FFF) == min(len(name), 0x0FFF), "index-format-invalid")
        _need(bool(name), "index-name-invalid")
        _need(all(part not in (b"", b".", b"..", b".git") for part in name.split(b"/")),
              "index-name-invalid")
        stage = (flags >> 12) & 0x3
        if previous_stage is not None:
            _need((previous_name, previous_stage) < (name, stage), "index-entry-order-invalid")
        previous_name, previous_stage = name, stage
    while pos < checksum_at:
        _need(pos + 8 <= checksum_at, "index-format-invalid")
        signature = bytes(raw[pos:pos + 4])
        _need(signature not in (b"link", b"sdir"), "split-or-sparse-index-unsupported")
        # Native Git classification (verified on 2.34): an unknown extension
        # whose signature starts with an uppercase letter is optional and is
        # ignored with a warning; any other first byte (lowercase or
        # non-alphabetic) makes it mandatory and the index unreadable.
        # Retaining optional payloads byte-exact keeps the identity sensitive
        # to them.
        _need(signature[:1].isupper(), "index-extension-unsupported")
        pos += 8 + int.from_bytes(raw[pos + 4:pos + 8], "big")
        _need(pos <= checksum_at, "index-format-invalid")
    _need(pos == checksum_at, "index-format-invalid")
    return _hash(bytes(normalized))


class _CommitIndexAdmission:
    """Eligibility tracking before the index lock; sealed raw baseline under it.

    The candidate's validated index identity anchors final commit admission.
    Before the lock, a live index that is byte-equal to the baseline or that
    normalizes to the candidate identity (an ordinary stat-cache refresh) is
    eligible: the baseline follows the latest eligible live bytes, so several
    successive refreshes are tolerated. The final locked admission validates
    the current live index (even when its bytes never diverged, so the
    equal-byte fast path cannot bypass layout validation), seals the latest
    eligible live bytes as the raw baseline, and closes admission: from
    sealing through mktree, commit-tree, update-ref and post-CAS revalidation
    every check requires byte-exact equality. A first divergence after
    sealing rejects before ref mutation; the identical refusal after
    update-ref stays honest unknown. The captured index is never reinstalled
    (commit writes no index at all).
    """

    def __init__(self, candidate_index, candidate_identity, algorithm):
        self.candidate = candidate_index
        self.candidate_identity = candidate_identity
        self.algorithm = algorithm
        self.baseline = candidate_index
        self.sealed = False
        self.admitted_sha256 = None

    def _eligible(self, live):
        return _index_admission_identity(live, self.algorithm) == self.candidate_identity

    def observe(self, live, seal=False):
        if live == self.baseline:
            if seal:
                # Layout validation even on the equal-byte path: the anchor
                # bytes were validated at capture, and this re-walks the live
                # bytes at the final locked admission.
                _need(self._eligible(live), "index-semantic-drift")
                self.sealed = True
            return
        _need(not self.sealed, "index-changed-after-baseline")
        _need(self._eligible(live), "index-semantic-drift")
        self.baseline = live
        self.admitted_sha256 = _hash(live)
        if seal:
            self.sealed = True


def _target_key(target):
    return (target.provenance(), target.project.git, target.workspace.git)


def _message(message):
    _need(isinstance(message, str) and message.strip() and "\0" not in message, "invalid-message")
    try:
        encoded = message.encode("utf-8")
    except UnicodeError:
        raise Refused("invalid-message") from None
    _need(len(encoded) <= 65536, "message-size-limit")
    return encoded


def _public_snapshot(snapshot):
    return {**{key: value for key, value in snapshot.items() if key != "directories"},
            "storage_directory_count": len(snapshot["directories"]),
            "storage_directories_sha256": _json_hash(snapshot["directories"])}


class CandidateStore:
    """Synchronous seam for the existing gate + cancellation-shielded thread.

    Candidate IDs are random process-local capabilities, not authorization. The
    supplied resolver must enforce registered project and immutable Work scope.
    Unknown attempts are quarantined; evicted/lost IDs never recapture or execute.
    """
    def __init__(self, resolve_target):
        self.resolve_target = resolve_target
        self._items = OrderedDict()
        self._mutex = threading.RLock()
        self._preparation_unknown = []

    def _resolve(self, project_ref, work_ref):
        _environment()
        target = self.resolve_target(project_ref, work_ref)
        _need(isinstance(target, EvidenceTarget), "evidence-target-unavailable")
        return target

    def target_for(self, project_ref, candidate_id):
        """Adapter-only gate locator; commit revalidates it before mutation."""
        with self._mutex:
            item = self._items[candidate_id]
            _need(project_ref == item["route"][0], "candidate-project-mismatch")
            return item["target"]

    def cached_result(self, project_ref, candidate_id, message):
        """Adapter-only cache check before writer-gate admission; never Git.

        None means a valid, unattempted candidate, not approval to commit it.
        Call through to_thread as the store mutex may be held by an attempt.
        """
        with self._mutex:
            try:
                _need(isinstance(candidate_id, str), "invalid-candidate-id")
                item = self._items.get(candidate_id)
                _need(item is not None, "candidate-unavailable-no-recapture")
                _need(project_ref == item["route"][0], "candidate-project-mismatch")
                request = _json_hash([candidate_id, _hash(_message(message))])
                receipt = item.get("receipt")
                if receipt is None:
                    return None
                _need(receipt["request_sha256"] == request, "candidate-already-attempted-with-different-message")
                return deepcopy(receipt["result"])
            except Refused as error:
                return {"status": "rejected", "reason": str(error)}

    def _quarantined(self, target, branch=None):
        return any(root == target.workspace.root or
                   branch is not None and common == target.workspace.git.git_common_dir and blocked_branch == branch
                   for root, common, blocked_branch in self._preparation_unknown) or any(item.get("receipt", {}).get("status") == "unknown" and
                   (item["target"].workspace.root == target.workspace.root or
                    branch is not None and item["before"]["branch"] == branch and
                    item["target"].workspace.git.git_common_dir == target.workspace.git.git_common_dir)
                   for item in self._items.values())

    def _page(self, item, view, offset, limit):
        _need(view in ("summary", "patch", "receipt"), "invalid-view")
        _need(type(offset) is int and offset >= 0 and type(limit) is int and 1 <= limit <= MAX_PAGE,
              "invalid-page")
        if view == "receipt":
            receipt = item.get("receipt")
            if receipt is None:
                return {"status": "not-attempted", "candidate_id": item["id"]}
            events = [{"phase": "preview", **event} for event in receipt["preview_events"]]
            events += [{"phase": "commit", **event} for event in receipt["events"]]
            _need(offset <= len(events), "offset-out-of-range")
            end = min(len(events), offset + min(limit, 100))
            return deepcopy({**{k: v for k, v in receipt.items() if k not in ("events", "preview_events")},
                             "events": events[offset:end], "offset": offset,
                             "next_offset": end if end < len(events) else None,
                             "total": len(events), "unit": "events"})
        content = item["files"] if view == "summary" else item["patch"]
        _need(offset <= len(content), "offset-out-of-range")
        end = min(len(content), offset + min(limit, 100) if view == "summary" else offset + limit)
        result = {"status": "previewed", "candidate_id": item["id"],
                  **item["target"].provenance(), "parent": item["before"]["parent"],
                  "branch": item["before"]["branch"], "tree": item["tree"],
                  "index_sha256": item["before"]["index_sha256"], "view": view,
                  "offset": offset, "next_offset": end if end < len(content) else None,
                  "total": len(content), "unit": "files" if view == "summary" else "unicode_characters",
                  "captured_at": item["at"], "basis": "fixed-staged-index-not-authorization",
                  "repository_writes": False, **item["patch_state"]}
        if "preparation" in item:
            result["preparation"] = deepcopy(item["preparation"])
        result["files" if view == "summary" else "text"] = deepcopy(content[offset:end])
        return result

    def _capture(self, binding, target, route, before, index):
        algorithm = binding.git(["rev-parse", "--show-object-format"]).decode().strip()
        _need(binding.git(["cat-file", "-t", before["parent"]]).strip() == b"commit", "parent-not-commit")
        # The commit-admission anchor is validated once at capture, so an
        # unsupported split/sparse or malformed layout refuses even if the raw
        # index bytes never diverge before the final commit.
        admission_identity = _index_admission_identity(index, algorithm)
        with tempfile.TemporaryDirectory(prefix="bridge-candidate-preview-") as temp:
            copy = Path(temp) / "index"
            copy.write_bytes(index)
            entries = binding.git(["ls-files", "--stage", "--full-name", "-z"], index=copy)
            tree, tree_batch, tree_oids = _index_tree(entries, algorithm)
            _need(tree != binding.git(["rev-parse", before["parent"] + "^{tree}"]).decode().strip(), "empty-candidate")
            flags = ["diff", "--cached", "--no-ext-diff", "--no-textconv", "--no-renames", "--no-color",
                     "--no-relative", "--ignore-submodules=none", "--submodule=short"]
            raw_args = ["--raw", "--no-abbrev", "-z"]
            raw = binding.git([*flags, *raw_args, "--ita-invisible-in-index", before["parent"], "--"], index=copy)
            visible = binding.git([*flags, *raw_args, "--ita-visible-in-index", before["parent"], "--"], index=copy)
            _need(raw == visible, "intent-to-add-unsupported")
            files = _annotate_files(binding, _summary(raw), before["parent"], copy)
            # Patch is display evidence only: rendered without --binary
            # (binary files appear as Git's bounded "Binary files ...
            # differ"), soft-capped, and never able to invalidate the
            # frozen candidate. Candidate identity above is complete.
            patch_state = {"patch_complete": False, "patch_truncated": False,
                           "patch_decode_lossy": False, "patch_unavailable": None,
                           "patch_bytes": 0}
            patch = ""
            try:
                captured, truncated = binding.display(
                    [*flags, "--src-prefix=a/", "--dst-prefix=b/", "-p", before["parent"], "--"],
                    index=copy)
                patch, lossy = _decode_display(captured)
                if truncated:
                    patch += PATCH_TRUNCATION_MARKER.format(cap=PATCH_DISPLAY_BYTES)
                patch_state.update(patch_complete=not truncated and not lossy,
                                   patch_truncated=truncated, patch_decode_lossy=lossy,
                                   patch_bytes=len(patch.encode("utf-8")))
            except GitFailure as error:
                # Display-only loss (timeout/spawn): candidate stays
                # valid; the frozen summary remains full audit evidence.
                patch_state["patch_unavailable"] = "patch-" + error.outcome
        size = len(index) + len(admission_identity) + len(tree_batch) + len(tree_oids) + len(patch.encode()) + \
               len(json.dumps([files, before]).encode()) + \
               len(json.dumps(patch_state).encode()) + RECEIPT_RESERVE
        _need(size <= MAX_CACHE_BYTES, "candidate-cache-size-limit")
        token = "candidate-" + secrets.token_hex(24)
        item = {"id": token, "target": target, "route": route, "before": before,
                "index": index, "admission_identity": admission_identity, "tree": tree,
                "tree_batch": tree_batch, "tree_oids": tree_oids,
                "files": files, "patch": patch, "patch_state": patch_state, "size": size,
                "at": time.time(), "preview_events": binding.events}
        return item

    def _reserve(self, size):
        while len(self._items) >= MAX_CANDIDATES or sum(i["size"] for i in self._items.values()) + size > MAX_CACHE_BYTES:
            removable = next((key for key, item in self._items.items()
                              if item.get("receipt", {}).get("status") != "unknown"), None)
            _need(removable is not None, "candidate-cache-full-of-unknown-attempts")
            del self._items[removable]

    def preview(self, project_ref, work_ref=None, *, candidate_id=None, view="summary", offset=0, limit=50):
        with self._mutex:
            binding = None
            try:
                if candidate_id is not None:
                    _need(isinstance(candidate_id, str), "invalid-candidate-id")
                    item = self._items.get(candidate_id)
                    _need(item is not None, "candidate-unavailable-no-recapture")
                    _need((project_ref, work_ref) == item["route"], "candidate-project-work-mismatch")
                    return self._page(item, view, offset, limit)
                _need(offset == 0 and view in ("summary", "patch"), "new-preview-page-invalid")
                _need(type(limit) is int and 1 <= limit <= MAX_PAGE, "invalid-page")
                target = self._resolve(project_ref, work_ref)
                _need(not self._quarantined(target),
                      "checkout-quarantined-unknown-attempt")
                binding = _Binding(target, time.monotonic() + OP_SECONDS)
                before, index = binding.snapshot()
                _need(not self._quarantined(target, before["branch"]), "branch-quarantined-unknown-attempt")
                item = self._capture(binding, target, (project_ref, work_ref), before, index)
                _need(_target_key(self._resolve(project_ref, work_ref)) == _target_key(target), "evidence-target-changed")
                after, _ = binding.snapshot()
                _same_snapshot(before, after)
                self._reserve(item["size"])
                self._items[item["id"]] = item
                return self._page(item, view, offset, limit)
            except Exception as error:
                return {"status": "rejected", "reason": str(error)[:300], "repository_writes": False}
            finally:
                if binding:
                    binding.close()

    def prepare(self, project_ref, work_ref=None, *, paths=None, candidate_id=None,
                view="summary", offset=0, limit=50):
        # Paths omitted explicitly means capture the already-staged index. Cache
        # paging remains pure and never re-resolves Work or recaptures Git.
        if paths is None:
            return self.preview(project_ref, work_ref, candidate_id=candidate_id,
                                view=view, offset=offset, limit=limit)
        from commit_preparation import selection_paths, stage_private, verify_selection, install_index
        with self._mutex:
            binding, attempted, installed = None, False, False
            effects = {"objects_may_remain": False}
            target, before = None, None
            try:
                _need(candidate_id is None, "paths-forbidden-with-candidate-id")
                _need(offset == 0 and view in ("summary", "patch"), "new-preparation-page-invalid")
                _need(type(limit) is int and 1 <= limit <= MAX_PAGE, "invalid-page")
                paths = selection_paths(paths)
                target = self._resolve(project_ref, work_ref)
                _need(not self._quarantined(target), "checkout-quarantined-unknown-attempt")
                _need(len(self._preparation_unknown) < MAX_CANDIDATES, "preparation-unknown-capacity")
                binding = _Binding(target, time.monotonic() + OP_SECONDS)
                binding.observation_limit = 96
                before, original_index = binding.snapshot()
                # The captured anchor derives from this live index: its layout
                # is validated here too, so unsupported split/sparse or
                # malformed representations refuse at capture, before any
                # staging, even though staged copies are rewritten by Git.
                _index_admission_identity(
                    original_index, "sha1" if len(before["parent"]) == 40 else "sha256")
                _need(not self._quarantined(target, before["branch"]), "branch-quarantined-unknown-attempt")
                with tempfile.TemporaryDirectory(prefix="bridge-candidate-prepare-") as temp:
                    private = Path(temp) / "index"
                    private.write_bytes(original_index)
                    captured, policy = stage_private(binding, target, paths, before, private, effects)
                    prepared_index = _file(private)
                    captured_storage, _ = binding.snapshot()
                    _same_snapshot(before, captured_storage)
                    expected = {**captured_storage, "index_sha256": _hash(prepared_index)}
                    item = self._capture(binding, target, (project_ref, work_ref), expected, prepared_index)
                    _need(set(f["path"] for f in item["files"]) <= set(paths), "candidate-outside-selection")
                    item["preparation"] = {"mode": "selected_paths", "paths": paths,
                                           "old_index_sha256": before["index_sha256"],
                                           "new_index_sha256": expected["index_sha256"]}
                    item["size"] += len(json.dumps(item["preparation"]).encode())
                    _need(item["size"] <= MAX_CACHE_BYTES, "candidate-cache-size-limit")
                    self._reserve(item["size"])
                    page = self._page(item, view, offset, limit)
                    # Git's conventional index.lock serializes cooperating Git;
                    # the adapter's writer lease serializes cooperating Bridge.
                    with binding.locks():
                        verify_selection(binding, target, paths, captured, policy)
                        _need(_target_key(self._resolve(project_ref, work_ref)) == _target_key(target), "evidence-target-changed")
                        current, _ = binding.snapshot()
                        _same_snapshot(before, current)
                        attempted = True
                        install_index(binding, prepared_index)
                        installed = True
                        current, _ = binding.snapshot()
                        _same_snapshot(expected, current)
                        _need(_target_key(self._resolve(project_ref, work_ref)) == _target_key(target), "evidence-target-changed")
                # Publish only after index installation, validation, lock cleanup
                # AND outer preparation-directory cleanup all succeed. A cleanup
                # exception follows the same unknown/quarantine path as any other
                # post-install failure, without retaining an inaccessible candidate.
                self._items[item["id"]] = item
                page.update(repository_writes=True, index_updated=True, objects_may_remain=effects["objects_may_remain"],
                            ref_updated=False)
                return page
            except Exception as error:
                uncertain = attempted or str(error) == "owned-lock-cleanup-unconfirmed"
                if uncertain and target is not None and before is not None:
                    self._preparation_unknown.append((target.workspace.root, target.workspace.git.git_common_dir, before["branch"]))
                return {"status": "unknown" if uncertain else "rejected", "reason": str(error)[:300],
                        "repository_writes": effects["objects_may_remain"] or attempted,
                        "objects_may_remain": effects["objects_may_remain"],
                        "index_updated": True if installed else None if uncertain else False,
                        "ref_updated": False, "retry_safe": False if uncertain else None}
            finally:
                if binding:
                    binding.close()

    def commit(self, project_ref, candidate_id, message):
        with self._mutex:
            cached = self.cached_result(project_ref, candidate_id, message)
            if cached is not None:
                return cached
            item = self._items[candidate_id]
            encoded = _message(message)
            request = _json_hash([candidate_id, _hash(encoded)])
            before = item["before"]
            result = {"status": "rejected", "candidate_id": candidate_id, "receipt_ref": candidate_id,
                      "request_sha256": request, "parent": before["parent"], "tree": item["tree"],
                      "branch": before["branch"], "ref_updated": False, "objects_may_remain": False}
            receipt = {"candidate_id": candidate_id, "request_sha256": request, "started_at": time.time(),
                       "target": item["target"].provenance(), "before": _public_snapshot(before),
                       "preview_events": item["preview_events"]}
            # Seal before any attempt. The mutex prevents concurrent same-token
            # execution; final receipts remain cache-only, including failures.
            item["receipt"] = receipt
            binding, ref_attempted = None, False
            try:
                target = self._resolve(*item["route"])
                _need(_target_key(target) == _target_key(item["target"]), "evidence-target-changed")
                _need(not self._quarantined(target, before["branch"]), "checkout-quarantined-unknown-attempt")
                binding = _Binding(target, time.monotonic() + OP_SECONDS)
                algorithm = "sha1" if len(before["parent"]) == 40 else "sha256"
                admission = _CommitIndexAdmission(item["index"], item["admission_identity"], algorithm)
                current, live_index = binding.snapshot()
                admission.observe(live_index)
                _same_snapshot(before, current, index=False)
                with binding.locks():
                    current, live_index = binding.snapshot()
                    # Final locked admission: validate the live index, seal
                    # the latest eligible bytes as the raw baseline, and close
                    # admission for the remainder of the attempt.
                    admission.observe(live_index, seal=True)
                    _same_snapshot(before, current, index=False)
                    result["objects_may_remain"] = True
                    # Materialize captured stage objects only: no index refresh,
                    # worktree paths, filters, or post-index-change invocation.
                    actual = binding.git(["mktree", "-z", "--batch"], input_bytes=item["tree_batch"])
                    _need(actual == item["tree_oids"], "actual-tree-mismatch")
                    tree = actual.splitlines()[-1].decode()
                    _need(tree == item["tree"], "actual-tree-mismatch")
                    current, live_index = binding.snapshot()
                    admission.observe(live_index)
                    _same_snapshot(before, current, index=False)
                    commit = binding.git(["commit-tree", tree, "-p", before["parent"]], input_bytes=encoded).decode().strip()
                    _need(len(commit) == len(before["parent"]) and all(c in "0123456789abcdef" for c in commit),
                          "created-commit-unconfirmed")
                    result["commit"] = commit
                    _need(_target_key(self._resolve(*item["route"])) == _target_key(target), "evidence-target-changed")
                    current, live_index = binding.snapshot()
                    admission.observe(live_index)
                    _same_snapshot(before, current, index=False)
                    ref_attempted = True
                    result["ref_updated"] = None
                    binding.git(["update-ref", "--no-deref", "-m", "Bridge: accepted staged candidate",
                                 before["branch"], commit, before["parent"]])
                    result["ref_updated"] = True
                    after, after_index = binding.snapshot()
                    admission.observe(after_index)
                    receipt["after"] = _public_snapshot(after)
                    _same_snapshot({**before, "parent": commit}, after, index=False)
                    _need(_target_key(self._resolve(*item["route"])) == _target_key(target), "evidence-target-changed")
                    result.update(status="committed", reason="exact-staged-tree-committed",
                                  index_unchanged=admission.admitted_sha256 is None)
                    if admission.admitted_sha256 is not None:
                        result["admitted_index_sha256"] = admission.admitted_sha256
            except BaseException as error:
                # Known pre-CAS refusals may leave tree/commit objects, but
                # cannot have updated the branch. Output/time/cleanup loss is
                # unknown even before CAS and never authorizes another attempt.
                uncertain = (ref_attempted or
                             isinstance(error, GitFailure) and error.outcome == "timeout" or
                             str(error) in ("git-output-limit", "owned-lock-cleanup-unconfirmed") or
                             not isinstance(error, (Refused, GitFailure, OSError, ValueError, KeyError)))
                result.update(status="unknown" if uncertain else "rejected", reason=str(error)[:300])
            finally:
                receipt.update(status=result["status"], ended_at=time.time(), result=deepcopy(result),
                               events=deepcopy(binding.events) if binding else [])
                if binding:
                    binding.close()
            return deepcopy(result)
