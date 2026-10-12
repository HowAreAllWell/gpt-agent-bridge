#!/usr/bin/env python3
"""Explicit first-install Bridge bootstrap. No process adoption or dependency install.

Plan is the default. Mutations require root and an explicit action. Runtime config
is JSON, never shell code. Errors deliberately omit subprocess/transport output.
"""
import argparse
import asyncio
import contextlib
import hashlib
import json
import logging
import os
import pwd
import re
import secrets
import signal
import socket
import stat
import subprocess
import sys
import tempfile
from pathlib import Path

UNIT_NAME = "gpt-agent-bridge-autostart.service"
UNIT = Path("/etc/systemd/system") / UNIT_NAME
LIB = Path("/usr/local/lib/gpt-agent-bridge-autostart")
STATE = Path("/var/lib/gpt-agent-bridge-autostart")
CONFIG = STATE / "settings.json"
MANIFEST = LIB / "installation.json"
RUNNER = LIB / "runner.py"
SYSTEMCTL = "/usr/bin/systemctl"
ANALYZE = "/usr/bin/systemd-analyze"
SAFE_PATH = re.compile(r"/[A-Za-z0-9_./-]+\Z")
SAFE_USER = re.compile(r"[a-z_][a-z0-9_-]{0,31}\Z")
MARKER = "gpt-agent-bridge-autostart-v1"
ROOT_UID = 0
TEMPLATE_SHA256 = "4c5789f450c620ff6222bf0dbf4ca81fe6c49a7b82299e68067edbe27dac0da3"
# systemd.unit(5): system manager lookup paths, including generators/control.
# Unknown manager paths are a refusal, not an invitation to scan arbitrary roots.
UNIT_SEARCH_DIRS = tuple(Path(p) for p in (
    "/etc/systemd/system.control", "/run/systemd/system.control", "/run/systemd/transient",
    "/run/systemd/generator.early", "/etc/systemd/system", "/etc/systemd/system.attached",
    "/run/systemd/system", "/run/systemd/system.attached", "/run/systemd/generator",
    "/usr/local/lib/systemd/system", "/usr/lib/systemd/system", "/lib/systemd/system",
    "/run/systemd/generator.late"))


class Refusal(Exception):
    pass


def require(condition, message):
    if not condition:
        raise Refusal(message)


def path(value):
    p = Path(value)
    require(bool(SAFE_PATH.fullmatch(str(p))) and ".." not in p.parts,
            "Paths must be absolute ASCII Linux paths without spaces or metacharacters")
    require(not str(p).startswith("/mnt/"), "Use a checkout on the Linux filesystem")
    return p


def no_symlinks(p):
    for part in [*reversed(p.parents), p]:
        require(not part.is_symlink(), "Symlinked configuration/checkout paths are unsupported")


def trusted_path(p, uid, allow_link=False):
    """Check controlling directories and resolved objects, without executing them.

    Root-owned sticky /tmp may contain an owner-private checkout. Other writable
    ancestors are refused. This is not a sandbox against the selected account.
    """
    for item in [*reversed(p.parents), p]:
        st = item.lstat()
        if stat.S_ISLNK(st.st_mode):
            require(allow_link and item == p and st.st_uid in (0, uid), "Unexpected source symlink")
            trusted_path(item.resolve(strict=True), uid)
            continue
        require(st.st_uid in (0, uid), "Untrusted source owner")
        sticky_root = item != p and st.st_uid == 0 and stat.S_ISDIR(st.st_mode) and st.st_mode & stat.S_ISVTX
        require(not st.st_mode & 0o022 or sticky_root, "Writable source or controlling directory")
        require(stat.S_ISDIR(st.st_mode) if item != p else
                stat.S_ISDIR(st.st_mode) or stat.S_ISREG(st.st_mode), "Unexpected source object")


def trusted_tree(root, uid, python=None):
    """Bounded metadata walk of executable source/dependencies, never .git/private data."""
    trusted_path(root, uid)
    pending = [root]
    seen = 0
    while pending:
        directory = pending.pop()
        for item in directory.iterdir():
            seen += 1
            require(seen <= 30000, "Source trust inventory exceeds its bound")
            if item.is_symlink():
                target = item.resolve(strict=True)
                require(target.is_relative_to(root) or
                        (python is not None and item.parent == root / "bin"
                         and item.name in ("python", "python3", python.name)
                         and target == python), "Unexpected dependency symlink")
                trusted_path(item, uid, allow_link=True)
                # Canonical internal directories are already visited through their real path.
            else:
                trusted_path(item, uid)
                if item.is_dir(): pending.append(item)


def protected_read(p, uid, mode):
    no_symlinks(p)
    parent = p.parent.stat()
    require(parent.st_uid == uid and stat.S_IMODE(parent.st_mode) == 0o700,
            "Private directory must belong to its owner and have mode 0700")
    fd = os.open(p, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, "rb") as f:
        st = os.fstat(f.fileno())
        require(stat.S_ISREG(st.st_mode) and st.st_uid == uid
                and stat.S_IMODE(st.st_mode) == mode and st.st_nlink == 1,
                "Private file ownership, type or permissions are unsafe")
        data = f.read(65537)
    require(len(data) <= 65536, "Private file is too large")
    return data


def command(args, allowed=(0,)):
    result = subprocess.run(args, env={"PATH": "/usr/bin:/bin", "LANG": "C"},
                            capture_output=True, text=True, timeout=30)
    require(result.returncode in allowed,
            "Command failed or outcome is uncertain; inspect locally, do not blindly retry")
    return result.stdout.strip()


def user_command(args, owner):
    """Never execute a user-controlled venv or Git checkout as root."""
    options = {}
    if os.geteuid() == 0:
        options = {"user": owner.pw_uid, "group": owner.pw_gid, "extra_groups": []}
    else:
        require(os.geteuid() == owner.pw_uid, "Run plan as the selected user or approved root operator")
    result = subprocess.run(args, cwd="/", env={
        "HOME": owner.pw_dir, "PATH": "/usr/bin:/bin", "LANG": "C",
        "PYTHONDONTWRITEBYTECODE": "1", "GIT_OPTIONAL_LOCKS": "0",
        "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": "/dev/null",
        "GIT_CONFIG_SYSTEM": "/dev/null"}, capture_output=True, text=True,
        timeout=30, **options)
    require(result.returncode == 0, "User checkout/package verification failed; no source was imported")
    return result.stdout.strip()


def checkout_root(p, owner):
    trusted_path(p, owner.pw_uid)
    require(p.is_dir() and p.stat().st_uid == owner.pw_uid,
            "Checkout must belong to the explicit service user")
    result = user_command(["/usr/bin/git", "-c", "core.fsmonitor=false", "-C", str(p),
                           "rev-parse", "--show-toplevel", "--is-bare-repository"], owner)
    require(result.splitlines() == [str(p), "false"], "Specify the exact non-bare Git checkout root")


def package_origin(repo, owner):
    require((repo / "pyproject.toml").is_file()
            and (repo / "src/gpt_agent_bridge/__main__.py").is_file(),
            "A complete src package checkout is required; root server.py is unsupported")
    for p in (repo / "src/gpt_agent_bridge", repo / "src/gpt_agent_bridge/__init__.py",
              repo / "src/gpt_agent_bridge/__main__.py", repo / ".venv"):
        no_symlinks(p)
    python = repo / ".venv/bin/python"
    require(python.is_file() and os.access(python, os.X_OK), "Install the checkout's .venv first")
    trusted_path(repo / "pyproject.toml", owner.pw_uid)
    trusted_tree(repo / "src/gpt_agent_bridge", owner.pw_uid)
    trusted_tree(repo / ".venv", owner.pw_uid, python.resolve(strict=True))
    # find_spec on this top-level package does not import its __init__ or server.
    code = """import importlib.util, pathlib, sys
r = pathlib.Path(sys.argv[1])
s = importlib.util.find_spec('gpt_agent_bridge')
ok = (pathlib.Path(sys.prefix).resolve() == r / '.venv'
      and pathlib.Path(sys.executable).absolute() == r / '.venv/bin/python'
      and s is not None and s.origin is not None
      and pathlib.Path(s.origin).resolve() == r / 'src/gpt_agent_bridge/__init__.py'
      and list(s.submodule_search_locations or []) == [str(r / 'src/gpt_agent_bridge')])
raise SystemExit(0 if ok else 1)
"""
    user_command([str(python), "-I", "-B", "-c", code, str(repo)], owner)


def host(root=False):
    require(sys.platform == "linux", "Only Linux with systemd is supported")
    require(Path("/run/systemd/system").is_dir()
            and Path("/proc/1/comm").read_text().strip() == "systemd",
            "systemd must already be PID 1; this tool does not configure WSL")
    require(Path(SYSTEMCTL).is_file(), "systemctl is unavailable")
    if root:
        require(os.geteuid() == 0, "This action requires explicit operator-approved sudo")


def account(user):
    require(bool(SAFE_USER.fullmatch(user)) and user != "root", "Specify a nonroot Linux user")
    try:
        entry = pwd.getpwnam(user)
    except KeyError:
        raise Refusal("Unknown Linux user") from None
    require(entry.pw_uid != 0, "Root service users are unsupported")
    path(entry.pw_dir)
    return entry


def make_plan(args):
    owner = account(args.user)
    repo, workspace, herdr = path(args.repo), path(args.workspace), path(args.herdr_bin)
    for p in (repo, workspace, herdr):
        no_symlinks(p)
        trusted_path(p, owner.pw_uid)
    trusted_path(path(owner.pw_dir), owner.pw_uid)
    checkout_root(repo, owner)
    checkout_root(workspace, owner)
    package_origin(repo, owner)
    require(herdr.is_file() and os.access(herdr, os.X_OK), "Select an existing absolute Herdr executable")
    require(1 <= args.port <= 65535, "Port must be in 1..65535")
    return {"format": MARKER, "user": owner.pw_name, "uid": owner.pw_uid,
            "gid": owner.pw_gid, "home": owner.pw_dir, "repo": str(repo),
            "workspace": str(workspace), "herdr_bin": str(herdr), "port": args.port,
            "entrypoint": "module"}


def verify_plan(plan):
    current = make_plan(argparse.Namespace(user=plan["user"], repo=plan["repo"],
        workspace=plan["workspace"], herdr_bin=plan["herdr_bin"], port=plan["port"]))
    require(current == plan, "Selected account or checkout changed; refusing stale plan")


def render_unit(plan):
    template = path(plan["repo"]) / "systemd/gpt-agent-bridge-autostart.service.template"
    no_symlinks(template)
    data = template.read_bytes()
    require(hashlib.sha256(data).hexdigest() == TEMPLATE_SHA256,
            "Service template differs from this reviewed installer")
    text = data.decode()
    for key, value in {"USER": plan["user"], "REPO": plan["repo"],
                       "PYTHON": plan["repo"] + "/.venv/bin/python",
                       "RUNNER": str(RUNNER), "CONFIG": str(CONFIG)}.items():
        text = text.replace("@" + key + "@", value)
    require("@" not in text, "Unresolved service template")
    return text.encode()


def free_port(port):
    try:
        with socket.socket() as s:
            s.bind(("127.0.0.1", port))
    except OSError:
        raise Refusal("Bridge port is occupied; no process will be adopted or stopped") from None


def identity(st):
    return st.st_dev, st.st_ino, st.st_uid, st.st_gid, st.st_mode, st.st_nlink


class CreatedFiles:
    """Remove only recorded objects; preserve changed/foreign content for review."""
    def __init__(self):
        self.objects = {}

    def directory(self, p):
        p.mkdir(mode=0o700)
        self.objects[p] = (identity(p.lstat()), None)

    def file(self, p, data, mode, uid, gid):
        fd = os.open(p, os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, mode)
        try:
            os.fchmod(fd, mode)
            os.fchown(fd, uid, gid)
            with os.fdopen(fd, "r+b", closefd=False) as f:
                f.write(data)
                f.flush()
                os.fsync(fd)
        finally:
            # Includes a partially written file on failure, while its fd is bound.
            st = os.fstat(fd)
            os.lseek(fd, 0, os.SEEK_SET)
            digest = hashlib.sha256()
            while chunk := os.read(fd, 65536):
                digest.update(chunk)
            self.objects[p] = (identity(st), digest.hexdigest())
            os.close(fd)

    def matches(self, p):
        saved, digest = self.objects[p]
        try:
            if identity(p.lstat()) != saved:
                return False
            if digest is None:
                return True
            fd = os.open(p, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
            with os.fdopen(fd, "rb") as f:
                return identity(os.fstat(f.fileno())) == saved and hashlib.sha256(f.read()).hexdigest() == digest
        except OSError:
            return False

    def capture(self, p):
        st = p.lstat()
        if stat.S_ISDIR(st.st_mode):
            self.objects[p] = (identity(st), None)
        else:
            fd = os.open(p, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
            with os.fdopen(fd, "rb") as f:
                require(stat.S_ISREG(st.st_mode) and identity(os.fstat(f.fileno())) == identity(st),
                        "Installation object changed while recording removal")
                self.objects[p] = (identity(st), hashlib.sha256(f.read()).hexdigest())

    def validate(self):
        require(all(self.matches(p) for p in self.objects), "Staged objects changed; refusing publication")
        for p, (_, digest) in self.objects.items():
            if digest is None:
                require(set(p.iterdir()) == {q for q in self.objects if q.parent == p},
                        "Unknown staged content; preserve for operator review")

    def cleanup(self):
        safe = True
        for p in reversed(self.objects):
            if not self.matches(p):
                safe = False
                continue
            try:
                if self.objects[p][1] is None:
                    p.rmdir()  # Never recursive, refuses foreign children.
                else:
                    p.unlink()
            except OSError:
                safe = False
        require(safe, "Cleanup preserved changed/unknown objects; operator review required")


def trusted_installer():
    # The operator first copies the reviewed installer into a root-owned 0700 dir.
    return protected_read(Path(__file__).absolute(), ROOT_UID, 0o700)


def system_parent(p):
    no_symlinks(p)
    trusted_path(p, ROOT_UID)
    st = p.stat()
    require(st.st_uid == ROOT_UID and stat.S_ISDIR(st.st_mode) and not st.st_mode & 0o022,
            "System parent directory is unsafe")


def activation_policy(published=False, enabled=False):
    """Finite disk inventory plus manager lookup-path agreement; no removals.

    Inspect only immediate entries of known unit lookup roots and their named
    dependency directories. Alias chains are classified by basename; uncertain
    links to a Bridge name are refused even if dangling or currently unloaded.
    """
    reported = command([SYSTEMCTL, "show", "-p", "UnitPath", "--value"]).split()
    known = {p.resolve() for p in UNIT_SEARCH_DIRS}
    require(reported and all(path(p).resolve() in known for p in reported)
            and UNIT.parent.resolve() in {path(p).resolve() for p in reported},
            "Unknown system manager unit lookup paths")
    names = {UNIT_NAME, "gpt-agent-bridge.service"}
    prefixes = {"service.d"}
    for name in names:
        prefixes.add(name + ".d")
        stem = name.removesuffix(".service")
        prefixes.update(stem[:i + 1] + ".service.d" for i, ch in enumerate(stem) if ch == "-")
    aliases, dependencies = [], []
    count = 0
    for directory in dict.fromkeys(p.resolve() for p in UNIT_SEARCH_DIRS):
        if not directory.exists():
            # Refuse writable/foreign ancestors even for a currently absent lookup directory.
            ancestor = directory.parent
            while not ancestor.exists(): ancestor = ancestor.parent
            system_parent(ancestor)
            continue
        system_parent(directory)
        entries = list(directory.iterdir())
        count += len(entries)
        require(count <= 65536, "Unit lookup inventory exceeds its bound")
        for item in entries:
            if item.name in names:
                require(published and item == UNIT and not item.is_symlink(),
                        "Existing or competing Bridge unit")
            if item.name in prefixes or item.name in {n + s for n in names for s in (".wants", ".requires")}:
                raise Refusal("Foreign or inherited Bridge drop-in/dependency directory")
            if item.is_symlink(): aliases.append((item.name, Path(os.readlink(item)).name))
            if item.name.endswith((".wants", ".requires")):
                system_parent(item)  # Symlinked or writable dependency directories are uncertain.
                children = list(item.iterdir())
                count += len(children)
                require(count <= 65536, "Unit dependency inventory exceeds its bound")
                dependencies.extend((item, child) for child in children)
    changed = True
    while changed:
        changed = False
        for alias, target in aliases:
            if target in names and alias not in names:
                names.add(alias); changed = True
    require(not any(target in names for alias, target in aliases), "Bridge unit alias is unsupported")
    for directory, child in dependencies:
        targets_bridge = child.name in names or (child.is_symlink() and Path(os.readlink(child)).name in names)
        if targets_bridge:
            require(published and enabled and directory == UNIT.parent / "multi-user.target.wants"
                    and child.name == UNIT_NAME and child.is_symlink()
                    and child.resolve(strict=True) == UNIT, "Unexpected Bridge activation dependency")


def installed_inactive_disabled():
    owned_installation()  # Checks exact bytes, FragmentPath, and absence of manager drop-ins.
    require(command([SYSTEMCTL, "show", UNIT_NAME, "-p", "LoadState", "--value"]) == "loaded",
            "Published service is not positively loaded; preserve evidence")
    require(command([SYSTEMCTL, "show", UNIT_NAME, "-p", "ActiveState", "--value"]) == "inactive",
            "Published service activated or manager state uncertain; preserve evidence")
    require(command([SYSTEMCTL, "is-enabled", UNIT_NAME], allowed=(0, 1)) == "disabled",
            "Published service is not positively disabled; preserve evidence")


def install(plan, token_file=None):
    host(root=True)
    runner = trusted_installer()
    verify_plan(plan)
    for p in (UNIT.parent, LIB.parent, STATE.parent):
        system_parent(p)
    require(not any(p.exists() or p.is_symlink() for p in (UNIT, LIB, STATE)),
            "Existing installation/files are unknown; refusing overwrite")
    activation_policy()
    for name in (UNIT_NAME, "gpt-agent-bridge.service"):
        require(command([SYSTEMCTL, "show", name, "-p", "LoadState", "--value"]) == "not-found",
                "An existing Bridge service must be handled separately; refusing fresh install")
    free_port(plan["port"])
    token = (protected_read(path(token_file), plan["uid"], 0o600).decode().strip()
             if token_file else secrets.token_urlsafe(32))
    require(bool(re.fullmatch(r"[A-Za-z0-9._~-]{32,256}", token)), "Invalid path token")
    unit = render_unit(plan)
    config = json.dumps({**plan, "token": token}).encode()
    # Private, root-owned staging; verify before publishing the unit.
    created = CreatedFiles()
    published = False
    pending = None
    finalizing = False
    deferred_interrupt = False
    def interrupted(signum, frame):
        nonlocal deferred_interrupt
        if finalizing:
            # A failure is already unwinding: do not interrupt secret cleanup.
            # A single bit bounds repeated callbacks; never retry publication.
            deferred_interrupt = True
            return
        raise Refusal("Installation interrupted; inspect any published evidence before retry")
    previous_handlers = {}
    try:
        # Register only after the host/provenance gates. Record before changing
        # each handler so partial setup and staging/cleanup failures restore it.
        for signum in (signal.SIGTERM, signal.SIGHUP):
            previous_handlers[signum] = signal.getsignal(signum)
            signal.signal(signum, interrupted)
        created.directory(LIB)
        created.directory(STATE)
        created.file(RUNNER, runner, 0o644, ROOT_UID, 0)
        created.file(CONFIG, config, 0o600, plan["uid"], plan["gid"])
        staged_unit = LIB / UNIT_NAME
        # Nonsecret provenance must be readable by the service user after publish.
        created.file(staged_unit, unit, 0o644, ROOT_UID, 0)
        command([ANALYZE, "verify", str(staged_unit)])
        manifest = {"format": MARKER, "plan": plan,
                    "unit_sha256": hashlib.sha256(unit).hexdigest(),
                    "runner_sha256": hashlib.sha256(runner).hexdigest()}
        created.file(MANIFEST, json.dumps(manifest).encode(), 0o644, ROOT_UID, 0)
        # Publish complete bytes atomically without clobbering an existing unit.
        pending = UNIT.parent / ("." + UNIT_NAME + "." + secrets.token_hex(8))
        created.file(pending, unit, 0o644, ROOT_UID, 0)
        created.validate()
        verify_plan(plan)
        activation_policy()
        os.link(pending, UNIT, follow_symlinks=False)
        published = True  # Any later failure retains published installation evidence.
        pending.unlink()
    finally:
        finalizing = True
        failed = sys.exc_info()[0] is not None
        try:
            if failed:
                # Only pre-publication files in our newly created directories.
                # Recognize a successful link before published was assigned;
                # retain evidence for any published/unknown manager outcome.
                if not published and pending in created.objects:
                    try:
                        st = UNIT.lstat()
                        published = (st.st_dev, st.st_ino) == created.objects[pending][0][:2]
                    except OSError:
                        pass
                if not published:
                    created.cleanup()
        finally:
            # Pending OS signals may be delivered to the original disposition
            # only after cleanup and both handlers are restored. Preserve the
            # caller's mask; do not discard its previously blocked signals.
            previous_mask = signal.pthread_sigmask(signal.SIG_BLOCK, {signal.SIGTERM, signal.SIGHUP})
            try:
                for signum, previous in previous_handlers.items():
                    signal.signal(signum, previous)
            finally:
                signal.pthread_sigmask(signal.SIG_SETMASK, previous_mask)
        if deferred_interrupt and not failed:
            # Publication may already have happened; keep its evidence and do
            # not proceed to daemon-reload or claim successful installation.
            raise Refusal("Installation interrupted; inspect any published evidence before retry")
    os.chown(STATE, plan["uid"], plan["gid"])
    os.chmod(LIB, 0o755)
    command([SYSTEMCTL, "daemon-reload"])
    activation_policy(published=True)
    installed_inactive_disabled()
    print("Installed only; service is not enabled or started. Token is never printed.")


def installation_record():
    no_symlinks(LIB)
    require(LIB.stat().st_uid == ROOT_UID and stat.S_IMODE(LIB.stat().st_mode) == 0o755,
            "Unknown installation directory")
    # Manifest is protected by its root-owned, non-writable parent (not 0700).
    st = MANIFEST.lstat()
    require(stat.S_ISREG(st.st_mode) and st.st_uid == ROOT_UID and st.st_nlink == 1
            and stat.S_IMODE(st.st_mode) == 0o644,
            "Unknown installation manifest")
    record = json.loads(MANIFEST.read_text())
    require(record.get("format") == MARKER, "Unknown installation format")
    for p, key in ((UNIT, "unit_sha256"), (LIB / UNIT_NAME, "unit_sha256"), (RUNNER, "runner_sha256")):
        no_symlinks(p)
        st = p.stat()
        require(st.st_uid == ROOT_UID and st.st_nlink == 1 and stat.S_ISREG(st.st_mode) and not st.st_mode & 0o022
                and hashlib.sha256(p.read_bytes()).hexdigest() == record[key],
                "Installed files changed; refusing service control or deletion")
    return record


def owned_installation():
    record = installation_record()
    require(command([SYSTEMCTL, "show", UNIT_NAME, "-p", "FragmentPath", "--value"]) == str(UNIT),
            "Unknown loaded service fragment")
    require(not command([SYSTEMCTL, "show", UNIT_NAME, "-p", "DropInPaths", "--value"]),
            "Service drop-ins are unsupported")
    return record["plan"]


def control(action):
    host(root=True)
    trusted_installer()
    plan = owned_installation()
    if action in ("enable", "start"):
        verify_plan(plan)
        require(command([SYSTEMCTL, "show", "gpt-agent-bridge.service", "-p", "LoadState", "--value"]) == "not-found",
                "An adopter service now exists; refusing coexistence")
        config = json.loads(protected_read(CONFIG, plan["uid"], 0o600))
        require({k: config.get(k) for k in plan} == plan,
                "Installed public configuration changed; reinstall requires separate review")
        require(set(config) == set(plan) | {"token"}, "Unknown configuration fields")
        require(isinstance(config.get("token"), str) and bool(re.fullmatch(
            r"[A-Za-z0-9._~-]{32,256}", config["token"])), "Invalid path token")
        activation_policy(published=True, enabled=action == "start")
    if action == "start":
        require(command([SYSTEMCTL, "show", UNIT_NAME, "-p", "ActiveState", "--value"]) == "inactive",
                "Start requires an inactive service; inspect failed/transitioning state first")
        free_port(plan["port"])
    if action == "uninstall":
        require(command([SYSTEMCTL, "show", UNIT_NAME, "-p", "ActiveState", "--value"]) == "inactive",
                "Disable and stop the service explicitly before uninstalling")
        require(command([SYSTEMCTL, "is-enabled", UNIT_NAME], allowed=(0, 1)) == "disabled",
                "Disable the service before uninstalling")
        protected_read(CONFIG, plan["uid"], 0o600)
        require(set(p.name for p in STATE.iterdir()) == {CONFIG.name}
                and set(p.name for p in LIB.iterdir()) == {RUNNER.name, MANIFEST.name, UNIT_NAME},
                "Unknown files in installation directories; refusing deletion")
        removal = CreatedFiles()
        for p in (LIB, STATE, UNIT, RUNNER, MANIFEST, LIB / UNIT_NAME, CONFIG):
            removal.capture(p)
        removal.validate()
        removal.cleanup()
        command([SYSTEMCTL, "daemon-reload"])
        print("Removed this installation; private token is invalid for any future new installation.")
    else:
        command([SYSTEMCTL, action, UNIT_NAME])
        print(action + " requested successfully; check status separately.")


def load_config():
    owner = os.geteuid()
    require(owner != 0, "Runtime/probe must run as the configured nonroot owner")
    config = json.loads(protected_read(CONFIG, owner, 0o600))
    plan = installation_record()["plan"]
    require(plan["uid"] == owner and {k: config.get(k) for k in plan} == plan
            and set(config) == set(plan) | {"token"}, "Runtime config differs from root-owned installation plan")
    require(config.get("format") == MARKER and config.get("uid") == owner,
            "Runtime owner/config mismatch")
    require(isinstance(config.get("token"), str) and bool(re.fullmatch(
        r"[A-Za-z0-9._~-]{32,256}", config["token"])), "Invalid path token")
    require(type(config.get("port")) is int and 1 <= config["port"] <= 65535, "Invalid port")
    for name in ("repo", "workspace", "home", "herdr_bin"):
        path(config[name])
    require(config["entrypoint"] == "module", "Only the installed src module entrypoint is supported")
    verify_plan(plan)
    return config


def runtime(config):
    repo = config["repo"]
    executable = repo + "/.venv/bin/python"
    require(config["entrypoint"] == "module", "Only the src module entrypoint is supported")
    verify_plan({k: config[k] for k in (
        "format", "user", "uid", "gid", "home", "repo", "workspace", "herdr_bin", "port", "entrypoint")})
    # Match the isolated origin check, excluding cwd/user-site/env path injection.
    args = [executable, "-I", "-B", "-m", "gpt_agent_bridge"]
    env = {"HOME": config["home"], "USER": config["user"], "LOGNAME": config["user"],
           "PATH": str(Path(config["herdr_bin"]).parent) + ":/usr/bin:/bin",
           "LANG": "C.UTF-8", "PYTHONUNBUFFERED": "1",
           "BRIDGE_PATH_TOKEN": config["token"], "BRIDGE_PORT": str(config["port"]),
           "BRIDGE_WORKSPACE": config["workspace"], "BRIDGE_HERDR_BIN": config["herdr_bin"],
           "BRIDGE_SERVICE_NAME": UNIT_NAME,
           "BRIDGE_MCP_ENABLE_DNS_REBINDING_PROTECTION": "true",
           "BRIDGE_MCP_ALLOWED_HOSTS": json.dumps([f"127.0.0.1:{config['port']}"]),
           "BRIDGE_MCP_ALLOWED_ORIGINS": "[]"}
    os.chdir(repo)
    os.execve(executable, args, env)


async def probe(config):
    # SDK context performs initialize. Neither raw HTTP nor outer ok proves Herdr.
    previous_logging = logging.root.manager.disable
    logging.disable(logging.CRITICAL)
    try:
        with open(os.devnull, "w") as quiet, contextlib.redirect_stdout(quiet), contextlib.redirect_stderr(quiet):
            from mcp import Client
            endpoint = f"http://127.0.0.1:{config['port']}/mcp/{config['token']}"
            async with Client(endpoint, mode="legacy") as client:
                result = await client.call_tool("bridge_health", {})
                health = result.structured_content
                require(not result.is_error and isinstance(health, dict)
                        and health.get("ok") is True
                        and health.get("bridge") == "gpt-agent-bridge", "Malformed health response")
                herdr = health.get("herdr", {})
                status = herdr.get("status") if isinstance(herdr, dict) else None
                return {"bridge_mcp": "initialized_healthy", "herdr": status if status in (
                    "reachable", "unavailable") else "unknown", "work_resume": "not_established"}
    except Exception:
        return {"bridge_mcp": "unavailable_or_invalid", "herdr": "unknown",
                "work_resume": "not_established"}
    finally:
        logging.disable(previous_logging)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", nargs="?", default="plan", choices=(
        "plan", "install", "enable", "start", "stop", "disable", "uninstall", "status", "run", "probe", "handoff"))
    for name in ("user", "repo", "workspace", "herdr-bin", "token-file"):
        parser.add_argument("--" + name)
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args(argv)
    try:
        if args.action in ("plan", "install"):
            require(all((args.user, args.repo, args.workspace, args.herdr_bin)),
                    "Specify --user, --repo, --workspace and --herdr-bin")
            plan = make_plan(args)
            if args.action == "plan":
                print(json.dumps({**plan, "token": "not_read_or_generated",
                                  "service_enabled": False, "service_started": False}, indent=2))
            else:
                install(plan, args.token_file)
        elif args.action in ("run", "probe", "handoff"):
            config = load_config()
            if args.action == "run":
                runtime(config)
            elif args.action == "handoff":
                fd, filename = tempfile.mkstemp(prefix="bridge-client-env.", dir=STATE)
                with os.fdopen(fd, "w") as f:
                    os.fchmod(f.fileno(), 0o600)
                    f.write(f"export BRIDGE_PORT={config['port']}\n"
                            f"export BRIDGE_PATH_TOKEN={config['token']}\n")
                print("Private client environment file: " + filename)
            else:
                try:
                    result = asyncio.run(asyncio.wait_for(probe(config), timeout=20))
                except asyncio.TimeoutError:
                    result = {"bridge_mcp": "unavailable_or_invalid", "herdr": "unknown",
                              "work_resume": "not_established"}
                print(json.dumps(result))
                return 0 if result["bridge_mcp"] == "initialized_healthy" else 1
        elif args.action == "status":
            host()
            # Status never reads secrets, starts a unit or tries to repair it.
            print(json.dumps({"service": command([SYSTEMCTL, "show", UNIT_NAME, "-p", "ActiveState", "--value"]),
                              "enabled": command([SYSTEMCTL, "is-enabled", UNIT_NAME], allowed=(0, 1, 3, 4)),
                              "mcp_health": "not_probed; run probe as owner with .venv Python"}))
        else:
            control(args.action)
        return 0
    except Refusal as exc:
        # Refusal messages are authored constants, never values/subprocess output.
        print(str(exc), file=sys.stderr)
        return 1
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError, TimeoutError):
        # Never print raw exception strings: they may contain token-bearing URLs.
        print("Refused or outcome uncertain. Check prerequisites/ownership privately; do not blindly retry.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
