"""Budgeted display observations, independent of binding and dispatch revalidation."""

import asyncio
from dataclasses import replace
import os
from pathlib import Path
import re
import stat
import time

from .evidence_target import EvidenceCheckout
from . import fixed_git
from .workspace_context import GitWorktreeIdentity


# Local Git normally needs milliseconds. Limit optional enrichment, not discovery.
TOTAL_SECONDS = 1.0
COMMAND_SECONDS = 0.25
MAX_CHECKOUTS = 16
CONCURRENCY = 4


def unavailable(status="unknown"):
    return dict(status=status, root=None, branch=None, head=None, dirty=None)


def _pointer(path):
    """Read only a bounded regular Git pointer; never follow a replaced FIFO/link."""
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise ValueError("not a regular Git pointer")
        data = os.read(fd, 4097)
        if len(data) > 4096:
            raise ValueError("oversized Git pointer")
        return data.decode().strip()
    finally:
        os.close(fd)


def _same_objects(project, checkout):
    """Cheap pre/post checks of facts already validated by discovery, no Git calls.

    This is display-only replacement detection, not an authorization substitute.
    Dispatch still performs its original full Git revalidation.
    """
    identity = checkout.git
    if project.git is None or identity.bare or (
        identity.git_common_dir, identity.git_common_device, identity.git_common_inode
    ) != (
        project.git.git_common_dir, project.git.git_common_device, project.git.git_common_inode
    ):
        return False
    for path, device, inode in (
        (checkout.root, identity.root_device, identity.root_inode),
        (Path(identity.git_dir), identity.git_dir_device, identity.git_dir_inode),
        (Path(identity.git_common_dir), identity.git_common_device, identity.git_common_inode),
    ):
        current = path.stat()
        if (not stat.S_ISDIR(current.st_mode) or (current.st_dev, current.st_ino) != (device, inode)
                or path.resolve(strict=True) != path):
            return False
    dotgit = checkout.root / ".git"
    if stat.S_ISDIR(dotgit.lstat().st_mode):
        git_dir = dotgit.resolve(strict=True)
    else:
        pointer = _pointer(dotgit)
        if not pointer.startswith("gitdir: "):
            return False
        git_dir = (checkout.root / pointer[8:]).resolve(strict=True)
    if str(git_dir) != identity.git_dir:
        return False
    common_pointer = git_dir / "commondir"
    common = ((git_dir / _pointer(common_pointer)).resolve(strict=True)
              if common_pointer.exists() else git_dir)
    return str(common) == identity.git_common_dir


def _parse(observed, root):
    stream = observed.get("stdout")
    if (observed.get("outcome") != "exited" or observed.get("exit_code") != 0
            or not isinstance(stream, dict) or stream.get("capture_complete") is not True
            or not isinstance(stream.get("text"), str) or not stream["text"].endswith("\0")):
        return unavailable()
    records = stream["text"].split("\0")
    headers = {}
    while records and records[0].startswith("# "):
        key, sep, value = records.pop(0)[2:].partition(" ")
        if not sep or key in headers:
            return unavailable()
        headers[key] = value
    head, branch = headers.get("branch.oid", ""), headers.get("branch.head", "")
    if re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", head) is None or not branch:
        return unavailable()
    # Do not parse filenames, including the second path of a rename, as metadata.
    return dict(status="observed", root=str(root), head=head,
                branch=None if branch == "(detached)" else branch,
                dirty=any(records))


def _objects_match(project, checkout):
    try:
        return _same_objects(project, checkout)
    except (OSError, ValueError, RuntimeError):
        return False


async def _observe(project, checkout, deadline):
    try:
        if not _objects_match(project, checkout):
            return unavailable("changed")
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return unavailable("deferred")
        observed = await fixed_git.execute(
            checkout.root,
            ["git", "--no-optional-locks", "--git-dir", checkout.git.git_dir,
             "--work-tree", str(checkout.root), "status", "--porcelain=v2", "--branch",
             "-z", "--untracked-files=normal"],
            min(COMMAND_SECONDS, remaining), 8192,
        )
        if time.monotonic() >= deadline:
            return unavailable("deferred")
        if not _objects_match(project, checkout):
            return unavailable("changed")
        if time.monotonic() >= deadline:
            return unavailable("deferred")
        # A guarded Git read that never completed (per-command budget timeout or
        # transient spawn/cleanup failure; fixed_git sentinel exit_code -1) is a
        # deferral of an identity-valid checkout, not absent host evidence. Only
        # oversized/unsupported reads (-2/-3) and completed-but-unparseable output
        # stay "unknown"; a cold checkout must not be misprojected as evidence loss.
        if observed.get("outcome") == "unavailable" and observed.get("exit_code") == -1:
            return unavailable("deferred")
        return _parse(observed, checkout.root)
    except Exception:
        return unavailable()


async def _default_display_project(project, deadline):
    """Default scope has no registry Git identity. Capture one for display only.

    One bounded command inside the existing enrichment budget; never register it,
    attach it to a handle, or use it for dispatch authorization.
    """
    try:
        remaining = deadline - time.monotonic()
        if remaining <= 0 or project.root.resolve(strict=True) != project.root:
            return None
        root_stat = project.root.stat()
        observed = await fixed_git.execute(
            project.root, ["git", "--no-optional-locks", "rev-parse", "--show-toplevel",
                           "--absolute-git-dir", "--path-format=absolute", "--git-common-dir",
                           "--is-bare-repository"], min(COMMAND_SECONDS, remaining), 8192)
        stream = observed.get("stdout")
        if (time.monotonic() >= deadline or observed.get("outcome") != "exited"
                or observed.get("exit_code") != 0 or not isinstance(stream, dict)
                or stream.get("capture_complete") is not True):
            return None
        top, git_dir, common_dir, bare = stream["text"].splitlines()
        if top != str(project.root) or bare != "false":
            return None
        admin, common = Path(git_dir), Path(common_dir)
        if (not admin.is_absolute() or not common.is_absolute()
                or admin.resolve(strict=True) != admin or common.resolve(strict=True) != common):
            return None
        admin_stat, common_stat = admin.stat(), common.stat()
        identity = GitWorktreeIdentity(
            root_stat.st_dev, root_stat.st_ino, git_dir, common_dir,
            admin_stat.st_dev, admin_stat.st_ino, common_stat.st_dev, common_stat.st_ino, False)
        display = replace(project, git=identity)
        if _objects_match(display, EvidenceCheckout(project.root, identity)):
            return display
    except Exception:
        pass
    return None


async def observe_all(project, candidates):
    """One shared deadline/work cap; four workers let healthy trees pass a slow one.

    Deadline expiry cancels and joins execution cleanup before returning. Native
    cleanup grace and nonpreemptible OS calls are additional, not a hard wall SLA.
    No tasks or processes are retained for deferred rows.
    """
    deadline = time.monotonic() + TOTAL_SECONDS
    if not candidates:
        return []
    if project.git is None:
        display = (await _default_display_project(project, deadline)
                   if project.workspace_ref is None else None)
        if display is None:
            status = "deferred" if time.monotonic() >= deadline else "unknown"
            return [unavailable(status) for _ in candidates]
        project = display
    sources, results = [], {}
    for candidate in candidates:
        cwd = candidate.get("identity", {}).get("cwd")
        checkout = candidate.get("_placement_checkout")
        if checkout is None and cwd == str(project.root) and project.git is not None:
            checkout = EvidenceCheckout(project.root, project.git)
        if not isinstance(checkout, EvidenceCheckout) or str(checkout.root) != cwd:
            checkout = None
        sources.append(checkout)
        if checkout is not None:
            results.setdefault(checkout, unavailable("deferred"))
    queue = iter(list(results)[:MAX_CHECKOUTS])

    async def worker():
        for checkout in queue:
            if time.monotonic() >= deadline:
                break
            results[checkout] = await _observe(project, checkout, deadline)

    tasks = [asyncio.create_task(worker()) for _ in range(min(CONCURRENCY, len(results), MAX_CHECKOUTS))]
    if tasks:
        try:
            await asyncio.wait(tasks, timeout=max(0, deadline - time.monotonic()))
        finally:
            for task in tasks:
                if not task.done():
                    task.cancel()
            joined = asyncio.gather(*tasks, return_exceptions=True)
            cancelled = False
            while not joined.done():
                try:
                    await asyncio.shield(joined)
                except asyncio.CancelledError:
                    cancelled = True
            if cancelled:
                raise asyncio.CancelledError
    return [dict(results[source]) if source is not None else unavailable() for source in sources]
