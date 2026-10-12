"""Internal fixed Git observations, byte-preserving bounded capture. Not a public executor."""
import asyncio
import os
import selectors
import signal
import subprocess
import threading
import time

MAX_STDOUT = 8 * 1024 * 1024
MAX_STDERR = 64 * 1024
TOO_LARGE = -2
UNSUPPORTED = -3
_ALLOWED = {"rev-parse", "status", "diff", "grep", "ls-files"}
_SENSITIVE = {"status", "diff", "grep", "ls-files"}


def _capture(root, argv, deadline, stdout_limit, stderr_limit, cancel, pass_fds=()):
    """Retain at most each cap plus one read chunk; terminate on overflow/timeout."""
    if time.monotonic() >= deadline or cancel.is_set():
        return -1, b"", b"GitObservationTimeout: coverage incomplete"
    env = dict(os.environ, GIT_OPTIONAL_LOCKS="0", GIT_PAGER="cat",
               GIT_TERMINAL_PROMPT="0", GIT_NO_LAZY_FETCH="1",
               GIT_ALLOW_PROTOCOL="", GIT_PROTOCOL_FROM_USER="0")
    # Inherited GIT_DIFF_OPTS must not reach Bridge Git subprocesses; patch
    # context is pinned per query and external drivers never run. The child
    # copy is dropped without mutating the parent environment or any config.
    env.pop("GIT_DIFF_OPTS", None)
    try:
        proc = subprocess.Popen(argv, cwd=root, stdin=subprocess.DEVNULL,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                start_new_session=True, env=env, pass_fds=pass_fds)
    except OSError as exc:
        return -1, b"", ("GitObservationSpawnError: " + str(exc)[:400]).encode()
    buffers = [bytearray(), bytearray()]
    limits = [stdout_limit, stderr_limit]
    failure = None
    selector = selectors.DefaultSelector()
    try:
        for index, pipe in enumerate((proc.stdout, proc.stderr)):
            os.set_blocking(pipe.fileno(), False)
            selector.register(pipe, selectors.EVENT_READ, index)
        while selector.get_map() or proc.poll() is None:
            if cancel.is_set() or time.monotonic() >= deadline:
                failure = (-1, b"GitObservationTimeout: coverage incomplete")
                break
            for key, _ in selector.select(min(.01, max(0, deadline-time.monotonic()))):
                chunk = os.read(key.fd, 65536)
                if not chunk:
                    selector.unregister(key.fileobj)
                    continue
                index = key.data
                remaining = limits[index] - len(buffers[index])
                buffers[index].extend(chunk[:remaining])
                if len(chunk) > remaining:
                    failure = (TOO_LARGE, b"GitObservationTooLarge: coverage incomplete")
                    break
            if failure:
                break
        if failure:
            # No descendants should be needed by fixed queries. Kill the whole
            # owned group, including a leader-exited writer holding the pipes.
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            try:
                proc.wait(timeout=.5)
            except subprocess.TimeoutExpired:
                return -1, bytes(buffers[0]), b"GitObservationCleanupUnknown: coverage incomplete"
            return failure[0], bytes(buffers[0]), failure[1]
        return proc.returncode, bytes(buffers[0]), bytes(buffers[1])
    finally:
        selector.close()
        proc.stdout.close()
        proc.stderr.close()
        # Exception paths must not abandon an owned process.
        if proc.poll() is None:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            try:
                proc.wait(timeout=.5)
            except subprocess.TimeoutExpired:
                pass


def observe(root, args, timeout=5.0, stdout_limit=MAX_STDOUT,
            stderr_limit=MAX_STDERR, *, cancel=None, git_dir=None, pass_fds=()):
    """One deadline includes config probe and query; no persistent config writes.

    Probe/query are not an atomic snapshot against concurrent external config
    replacement. OS spawn/cleanup may exceed the local deadline; no total API SLA.
    """
    cancel = cancel or threading.Event()
    deadline = time.monotonic() + timeout
    args = list(args)
    if args and args[0] == "--no-optional-locks":
        args.pop(0)
    if not args or args[0] not in _ALLOWED:
        return UNSUPPORTED, b"", b"GitObservationUnsupported: not a fixed observation"
    base = ["git", "--no-pager", "--no-optional-locks",
            "-c", "core.fsmonitor=false", "-c", "core.hooksPath=/dev/null",
            "-c", "protocol.allow=never", "-c", "grep.threads=1"]
    if args[0] == "diff":
        # Git's worktree diff auto-refresh can write the real index even under
        # --no-optional-locks (observed on git 2.34 after a selected prepare
        # installs zeroed stat-cache entries). A public observation must never
        # mutate the exact staged index a candidate froze. Command-local only;
        # diff output is unchanged because stat-dirty entries are still
        # content-compared without the refresh write.
        base += ["-c", "diff.autoRefreshIndex=false"]
    if git_dir is not None:
        base += ["--git-dir", str(git_dir), "--work-tree", str(root)]
    if args[0] in _SENSITIVE:
        rc, _, err = _capture(root, base + [
            "config", "--includes", "--null", "--name-only", "--get-regexp",
            r"^filter\..*\.(clean|process)$"], deadline, 65536, stderr_limit, cancel, pass_fds)
        if rc == 0:
            return UNSUPPORTED, b"", b"GitObservationUnsupported: clean/process filter configuration; Git facts unknown"
        if rc != 1:
            return rc, b"", err or b"GitObservationConfigUnknown: coverage incomplete"
    if args[0] == "diff":
        args[1:1] = ["--no-ext-diff", "--no-textconv", "--ignore-submodules=dirty", "--submodule=short"]
    if args[0] == "status":
        args[1:1] = ["--ignore-submodules=dirty"]
    if args[0] == "grep":
        args[1:1] = ["--no-textconv", "--no-recurse-submodules"]
    return _capture(root, base + args, deadline, stdout_limit, stderr_limit, cancel, pass_fds)


async def observe_async(root, args, timeout=5.0, stdout_limit=MAX_STDOUT,
                        stderr_limit=MAX_STDERR, *, git_dir=None):
    """Join thread/process cleanup on cancellation, within the query's local budget."""
    cancel = threading.Event()
    task = asyncio.create_task(asyncio.to_thread(observe, root, args, timeout,
        stdout_limit, stderr_limit, cancel=cancel, git_dir=git_dir))
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        cancel.set()
        while not task.done():
            try:
                await asyncio.shield(task)
            except asyncio.CancelledError:
                continue
        task.result()
        raise


async def execute(root, argv, timeout, limit):
    """Display adapter retaining the existing capture shape, fixed Git verbs only."""
    args = list(argv)
    if not args or args.pop(0) != "git":
        return {"outcome": "unsupported", "exit_code": None}
    git_dir = None
    if args and args[0] == "--no-optional-locks":
        args.pop(0)
    if args and args[0] == "--git-dir":
        git_dir = args[1]
        args = args[2:]
    if args[:2] == ["--work-tree", str(root)]:
        args = args[2:]
    rc, out, err = await observe_async(root, args, timeout, limit, limit, git_dir=git_dir)
    return {"outcome": "exited" if rc >= 0 else "unavailable", "exit_code": rc,
            "stdout": {"text": out.decode("utf-8", errors="replace"), "capture_complete": rc >= 0},
            "stderr": {"text": err.decode("utf-8", errors="replace"), "capture_complete": rc >= 0}}
