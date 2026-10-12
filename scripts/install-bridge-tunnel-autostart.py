#!/usr/bin/env python3
"""Opt-in private Tunnel companion. No import-time I/O; stdlib-only controller.

Bridge settings adapter is an explicit integration contract, not live acceptance.
Privileged actions require a reviewed, root-owned snapshot; secrets are owner-only.
"""
import argparse
import ast
import contextlib
import errno
import fcntl
import getpass
import hashlib
import http.client
import json
import os
from pathlib import Path
import pwd
import re
import signal
import socket
import stat
import subprocess
import sys
import tempfile
import time
import warnings

UNIT = "gpt-agent-bridge-tunnel.service"
BRIDGE_UNIT = "gpt-agent-bridge-autostart.service"
LIB = Path("/usr/local/lib/gpt-agent-bridge-tunnel-autostart")
STATE = Path("/var/lib/gpt-agent-bridge-tunnel-autostart")
RUNTIME = Path("/run/gpt-agent-bridge-tunnel-autostart")
UNIT_FILE = Path("/etc/systemd/system") / UNIT
RUNNER = LIB / "runner.py"
MANIFEST = LIB / "installation.json"
CREDENTIALS = STATE / "credentials.json"
LOCK = STATE / "runtime.lock"
BRIDGE_MANIFEST = Path("/usr/local/lib/gpt-agent-bridge-autostart/installation.json")
BRIDGE_SETTINGS = Path("/var/lib/gpt-agent-bridge-autostart/settings.json")
BRIDGE_RUNNER = BRIDGE_MANIFEST.parent / "runner.py"
BRIDGE_UNIT_FILE = Path("/etc/systemd/system") / BRIDGE_UNIT
# Verified against frozen Bridge installer SHA256
# 17ef82d1f6ac15fd91cc5061f187857391117bb06946cf92f30cc61e4668eb12.
# Never infer a replacement format from private or untrusted settings.
BRIDGE_MARKER = "gpt-agent-bridge-autostart-v1"
SYSTEMCTL = "/usr/bin/systemctl"
ANALYZE = "/usr/bin/systemd-analyze"
SYSTEMD_ROOTS = (Path("/etc/systemd/system"), Path("/run/systemd/system"),
                 Path("/usr/lib/systemd/system"), Path("/lib/systemd/system"))
MARKER = "bridge-private-tunnel-v1"
LIMIT = 65536
TUNNEL_ID = re.compile(r"tunnel_[a-z0-9]{32}\Z", re.ASCII)
VERSION = re.compile(r"v?0\.0\.16(?:\+(?P<build>[a-fA-F0-9]{7,40}))?"
                     r"(?: \(git sha: (?P<sha>[a-fA-F0-9]{7,40})\))?\n?\Z", re.ASCII)
API_KEY = re.compile(r"[0-9A-Za-z_-]{16,4096}\Z", re.ASCII)
MAX_TREE_ENTRIES = 30000


class Refusal(Exception):
    """Only fixed, nonsecret reason codes may be reported."""
    def __init__(self, code, stage=None):
        self.code = code
        self.stage = stage
        super().__init__(code)


def require(condition, code):
    if not condition:
        raise Refusal(code)


def absolute(value):
    require(isinstance(value, str)
            and not any(ord(c) < 32 or ord(c) > 126 for c in value), "invalid_path")
    p = Path(value)
    require(p.is_absolute() and str(p) == value and ".." not in p.parts, "invalid_path")
    return p


def identity(st):
    return (st.st_dev, st.st_ino, st.st_uid, st.st_gid, st.st_mode,
            st.st_nlink, st.st_size, st.st_mtime_ns, st.st_ctime_ns)


def directory(p, owners, mode=None):
    """Reject symlink ancestors and writable foreign ancestry, including /tmp."""
    p = absolute(str(p))
    for item in list(reversed(p.parents)) + [p]:
        st = item.lstat()
        require(stat.S_ISDIR(st.st_mode) and st.st_uid in owners | {0}
                and not st.st_mode & 0o022, "unsafe_directory")
    if mode is not None:
        require(stat.S_IMODE(p.lstat().st_mode) == mode, "directory_mode")


def read_file(p, owners, mode=None, private_parent=False, limit=LIMIT):
    p = absolute(str(p))
    directory(p.parent, owners, 0o700 if private_parent else None)
    before = p.lstat()
    require(stat.S_ISREG(before.st_mode) and before.st_uid in owners
            and before.st_nlink == 1 and not before.st_mode & 0o7022, "unsafe_file")
    if mode is not None:
        require(stat.S_IMODE(before.st_mode) == mode, "file_mode")
    require(before.st_size <= limit, "file_too_large")
    fd = os.open(p, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        require(identity(os.fstat(fd)) == identity(before), "file_race")
        chunks = []
        remaining = limit + 1
        while remaining:
            part = os.read(fd, min(remaining, 65536))
            if not part:
                break
            chunks.append(part)
            remaining -= len(part)
        data = b"".join(chunks)
        require(len(data) <= limit and identity(os.fstat(fd)) == identity(before)
                and identity(p.lstat()) == identity(before), "file_race")
        return data
    finally:
        os.close(fd)


def read_json(p, owners, mode, private_parent=False):
    def unique(pairs):
        result = {}
        for k, v in pairs:
            require(k not in result, "duplicate_json_key")
            result[k] = v
        return result
    raw = read_file(p, owners, mode, private_parent)
    try:
        data = json.loads(raw, object_pairs_hook=unique)
    except (ValueError, UnicodeError, RecursionError):
        raise Refusal("invalid_json") from None
    require(isinstance(data, dict), "invalid_json")
    return data


def digest(p, owners, mode=None):
    return hashlib.sha256(read_file(p, owners, mode, limit=256 * 1024 * 1024)).hexdigest()


def environment(plan):
    return {"HOME": plan["home"], "PATH": "/usr/bin:/bin", "LANG": "C.UTF-8"}


def check_client(plan):
    client = Path(plan["client"])
    require(digest(client, {0}) == plan["client_sha256"], "client_digest")
    require(client.lstat().st_mode & 0o111, "client_not_executable")
    try:
        os.getxattr(client, "security.capability", follow_symlinks=False)
    except OSError as error:
        require(error.errno in (errno.ENODATA, errno.ENOTSUP), "client_capability_check")
    else:
        raise Refusal("privileged_client")


def validate_plan(plan):
    keys = {"format", "user", "uid", "gid", "home", "client", "client_sha256",
            "client_version", "health_socket", "ttl", "bridge_wait_seconds"}
    require(isinstance(plan, dict) and set(plan) == keys
            and plan["format"] == MARKER, "invalid_plan")
    require(type(plan["uid"]) is int and plan["uid"] > 0
            and type(plan["gid"]) is int and plan["gid"] >= 0, "invalid_owner")
    require(isinstance(plan["user"], str) and re.fullmatch(r"[a-z_][a-z0-9_-]{0,31}", plan["user"]), "invalid_owner")
    for key in ("home", "client", "health_socket"):
        absolute(plan[key])
    try:
        account = pwd.getpwnam(plan["user"])
    except KeyError:
        raise Refusal("invalid_owner") from None
    require((account.pw_uid, account.pw_gid, account.pw_dir) ==
            (plan["uid"], plan["gid"], plan["home"]), "owner_changed")
    require(plan["client_version"] == "v0.0.16" and isinstance(plan["client_sha256"], str)
            and re.fullmatch(r"[a-f0-9]{64}", plan["client_sha256"]), "invalid_client_pin")
    require(Path(plan["health_socket"]).parent == RUNTIME
            and re.fullmatch(r"[a-z][a-z0-9_-]{0,30}\.sock", Path(plan["health_socket"]).name)
            and len(plan["health_socket"].encode()) < 104, "invalid_health_socket")
    require(type(plan["bridge_wait_seconds"]) is int
            and 1 <= plan["bridge_wait_seconds"] <= 300, "invalid_wait")
    require(plan["ttl"] in ("10m", "60m"), "invalid_ttl")
    return plan


def make_plan(args):
    account = pwd.getpwnam(args.user)
    plan = {"format": MARKER, "user": args.user, "uid": account.pw_uid,
            "gid": account.pw_gid, "home": account.pw_dir,
            "client": str(absolute(args.client)), "client_sha256": args.client_sha256,
            "client_version": "v0.0.16", "health_socket": str(RUNTIME / args.health_socket),
            "ttl": args.ttl, "bridge_wait_seconds": args.bridge_wait_seconds}
    validate_plan(plan)
    # Hash only. No execution/version observation as root; no credentials/services.
    check_client(plan)
    return plan


def trusted_snapshot():
    require(os.geteuid() == 0, "root_required")
    source = absolute(str(Path(__file__)))
    directory(source.parent, {0}, 0o700)
    code = read_file(source, {0}, 0o600, True)
    template = read_file(source.parent / "service.template", {0}, 0o600, True)
    return code, template.decode("ascii")


def render_unit(plan, template):
    substitutions = {"@USER@": plan["user"], "@GID@": str(plan["gid"]), "@RUNNER@": str(RUNNER)}
    for key, value in substitutions.items():
        template = template.replace(key, value)
    require("@" not in template and "Environment=" not in template, "invalid_template")
    return template.encode("ascii")


def call(args, allowed=(0,)):
    # Never forward raw subprocess output/errors, even from systemctl.
    result = subprocess.run(args, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                            stderr=subprocess.DEVNULL, env={"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8"},
                            timeout=20, check=False)
    require(result.returncode in allowed, "control_failed")
    require(len(result.stdout) <= LIMIT, "control_output_limit")
    return result


def unit_properties():
    result = call([SYSTEMCTL, "show", UNIT, "--no-pager", "--property=LoadState,FragmentPath,DropInPaths,ActiveState,UnitFileState"])
    try:
        return dict(line.split("=", 1) for line in result.stdout.decode("ascii").splitlines() if "=" in line)
    except UnicodeError:
        raise Refusal("invalid_control_output") from None


def unit_paths():
    result = call([SYSTEMCTL, "show", "--property=UnitPath", "--value", "--no-pager"])
    try:
        values = result.stdout.decode("ascii").strip().split()
        require(values and len(values) <= 64 and len(set(values)) == len(values), "unknown_unit_path")
        roots = tuple(absolute(value) for value in values)
        # The system manager must include the actual intended fragment directory.
        require(UNIT_FILE.parent in roots, "unknown_unit_path")
        return roots
    except (UnicodeError, ValueError):
        raise Refusal("unknown_unit_path") from None


def systemd_roots():
    # Enumerate manager-selected paths and the known persistent/runtime/vendor
    # paths; refuse unsupported ancestry rather than guessing manager precedence.
    roots = tuple(dict.fromkeys(unit_paths() + SYSTEMD_ROOTS))
    result = []
    for root in roots:
        if not os.path.lexists(root):
            directory(root.parent, {0})
            continue
        # Common /lib -> /usr/lib vendor aliases are allowed only when they
        # resolve to another manager-enumerated path with trusted real ancestry.
        resolved = root.resolve(strict=True)
        require(root == resolved or resolved in roots, "unsupported_unit_path_alias")
        directory(resolved, {0})
        if resolved not in result:
            result.append(resolved)
    return result


def activation_links():
    paths = []
    dropins = {"service.d", UNIT + ".d", "gpt-.service.d",
               "gpt-agent-.service.d", "gpt-agent-bridge-.service.d"}
    visited = 0
    for root in systemd_roots():
        if root != UNIT_FILE.parent and os.path.lexists(root / UNIT):
            paths.append(root / UNIT)
        for sub in root.iterdir():
            visited += 1
            require(visited <= MAX_TREE_ENTRIES, "unit_inventory_limit")
            if sub.name in dropins or sub.name in (UNIT + ".wants", UNIT + ".requires"):
                paths.append(sub)
            if sub.is_symlink():
                # Refuse aliases aimed at the companion, including dangling ones.
                target = os.readlink(sub)
                if Path(target).name == UNIT or target == str(UNIT_FILE):
                    paths.append(sub)
            if sub.name.endswith((".wants", ".requires")):
                directory(sub, {0})
                for entry in sub.iterdir():
                    visited += 1
                    require(visited <= MAX_TREE_ENTRIES, "unit_inventory_limit")
                    if entry.name == UNIT or (entry.is_symlink() and Path(os.readlink(entry)).name == UNIT):
                        paths.append(entry)
    return paths


def absent_installation():
    require(not any(os.path.lexists(p) for p in (LIB, STATE, UNIT_FILE, RUNTIME)), "existing_installation")
    require(not activation_links(), "foreign_activation")
    activation_parent()
    props = unit_properties()
    require(props.get("LoadState") == "not-found" and not props.get("FragmentPath")
            and not props.get("DropInPaths") and props.get("ActiveState") == "inactive", "foreign_unit")


def activation_parent():
    target = UNIT_FILE.parent / "multi-user.target.wants"
    if os.path.lexists(target):
        directory(target, {0})


@contextlib.contextmanager
def interrupts():
    previous = {}
    pending = []
    def interrupted(signum, frame):
        # Record, never raise inside an acquisition/cleanup operation. Check at
        # explicit safe boundaries; external commands have bounded timeouts.
        pending.append(signum)
    def checkpoint():
        require(not pending, "interrupted_install")
    for sig in (signal.SIGHUP, signal.SIGTERM, signal.SIGINT):
        previous[sig] = signal.signal(sig, interrupted)
    try:
        yield checkpoint
    finally:
        blocked = signal.pthread_sigmask(signal.SIG_BLOCK, set(previous))
        try:
            caught = bool(pending or signal.sigpending() & set(previous))
            for sig, handler in previous.items():
                signal.signal(sig, handler)
            # Drain only known pending standard signals under the mask; each
            # consumed signal forces interruption, rather than being swallowed.
            for _ in previous:
                event = signal.sigtimedwait(set(previous), 0)
                if event is None:
                    break
                caught = True
            caught = caught or bool(signal.sigpending() & set(previous))
        finally:
            signal.pthread_sigmask(signal.SIG_SETMASK, blocked)
        require(not caught, "interrupted_install")


def publish_file(target, data, mode):
    """O_EXCL, no-clobber atomic hardlink publication; cleanup only same inode."""
    fd, temporary = tempfile.mkstemp(prefix=".tunnel-stage-", dir=target.parent)
    temp = Path(temporary)
    owned = os.fstat(fd)
    published = False
    try:
        os.fchmod(fd, mode)
        # Keep the original fd open until cleanup: a removed staging inode must
        # not be recycled into an unknown replacement with the same inode number.
        with os.fdopen(os.dup(fd), "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.link(temp, target, follow_symlinks=False)
        published = True
        target_stat = target.lstat()
        require((target_stat.st_dev, target_stat.st_ino) == (owned.st_dev, owned.st_ino)
                and stat.S_ISREG(target_stat.st_mode), "publication_race")
    finally:
        # Block cleanup-triggering signals: no recursive signal-handler rollback.
        old = signal.pthread_sigmask(signal.SIG_BLOCK, {signal.SIGHUP, signal.SIGTERM, signal.SIGINT})
        try:
            if os.path.lexists(temp):
                current = temp.lstat()
                if (current.st_dev, current.st_ino) == (owned.st_dev, owned.st_ino):
                    temp.unlink()
            if published:
                dfd = os.open(target.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
                try:
                    os.fsync(dfd)
                finally:
                    os.close(dfd)
        finally:
            os.close(fd)
            signal.pthread_sigmask(signal.SIG_SETMASK, old)


def install(plan):
    progress = ["preflight"]
    try:
        return install_steps(plan, progress)
    except Refusal as error:
        error.stage = progress[0]
        raise
    except BaseException:
        raise Refusal("installation_not_completed", progress[0]) from None


def install_steps(plan, progress):
    code, template = trusted_snapshot()
    validate_plan(plan)
    check_client(plan)
    for parent in (LIB.parent, STATE.parent, UNIT_FILE.parent):
        directory(parent, {0})
    absent_installation()
    unit = render_unit(plan, template)
    # Analyze before publication, using a private root-owned staging directory.
    with interrupts() as checkpoint:
        progress[0] = "unit_review"
        checkpoint()
        stage = Path(tempfile.mkdtemp(prefix=".tunnel-review-", dir=LIB.parent))
        stage_id = stage.lstat()
        check = stage / UNIT
        check_id = None
        try:
            publish_file(check, unit, 0o600)
            check_id = identity(check.lstat())
            checkpoint()
            call([ANALYZE, "verify", str(check)])
            checkpoint()
        finally:
            blocked = signal.pthread_sigmask(signal.SIG_BLOCK, {signal.SIGHUP, signal.SIGTERM, signal.SIGINT})
            try:
                if check_id is not None and os.path.lexists(check) and identity(check.lstat()) == check_id:
                    check.unlink()
                if (stage.lstat().st_dev, stage.lstat().st_ino) == (stage_id.st_dev, stage_id.st_ino):
                    stage.rmdir()
            finally:
                signal.pthread_sigmask(signal.SIG_SETMASK, blocked)
        absent_installation()
        checkpoint()
        progress[0] = "create_installation_directories"
        LIB.mkdir(mode=0o755)
        os.chmod(LIB, 0o755)  # Runtime readability must not depend on root umask.
        STATE.mkdir(mode=0o700)
        os.chown(STATE, plan["uid"], plan["gid"])
        checkpoint()
        # Published objects are preserved on failure for explicit operator review.
        progress[0] = "publish_runner"
        publish_file(RUNNER, code, 0o644)
        checkpoint()
        progress[0] = "publish_unit"
        publish_file(UNIT_FILE, unit, 0o644)
        checkpoint()
        record = {"format": MARKER, "plan": plan, "runner_sha256": hashlib.sha256(code).hexdigest(),
                  "unit_sha256": hashlib.sha256(unit).hexdigest()}
        progress[0] = "publish_manifest"
        publish_file(MANIFEST, (json.dumps(record, sort_keys=True) + "\n").encode(), 0o644)
        checkpoint()
        progress[0] = "reload_and_verify_disabled"
        call([SYSTEMCTL, "daemon-reload"])
        checkpoint()
        props = managed_properties()
        require(props.get("ActiveState") == "inactive" and props.get("UnitFileState") == "disabled", "unsafe_installed_state")
        checkpoint()
    return {"installation": "installed_disabled", "credentials": "not_provisioned", "web_ready": "not_established"}


def record():
    data = read_json(MANIFEST, {0}, 0o644)
    require(set(data) == {"format", "plan", "runner_sha256", "unit_sha256"}
            and data["format"] == MARKER, "invalid_manifest")
    validate_plan(data["plan"])
    require(all(isinstance(data[key], str) and re.fullmatch(r"[a-f0-9]{64}", data[key])
                for key in ("runner_sha256", "unit_sha256")), "invalid_manifest")
    require(digest(RUNNER, {0}, 0o644) == data["runner_sha256"]
            and digest(UNIT_FILE, {0}, 0o644) == data["unit_sha256"], "installation_changed")
    return data


def configured_owner(plan):
    require(os.geteuid() == plan["uid"] and os.getegid() == plan["gid"], "owner_required")
    directory(STATE, {0, plan["uid"]}, 0o700)
    require(STATE.lstat().st_uid == plan["uid"], "state_owner")


def validate_credentials(value):
    require(isinstance(value, dict) and set(value) == {"tunnel_id", "runtime_api_key"}, "invalid_credentials")
    require(isinstance(value["tunnel_id"], str) and TUNNEL_ID.fullmatch(value["tunnel_id"]), "invalid_tunnel_id")
    key = value["runtime_api_key"]
    require(isinstance(key, str) and API_KEY.fullmatch(key), "invalid_runtime_key")
    return value


def verify_client(plan):
    require(os.geteuid() != 0, "nonroot_version_observation_required")
    check_client(plan)
    result = subprocess.run([plan["client"], "--version"], stdin=subprocess.DEVNULL,
                            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=5,
                            env=environment(plan), cwd="/", check=False)
    require(result.returncode == 0 and len(result.stdout) <= 256, "client_version")
    try:
        match = VERSION.fullmatch(result.stdout.decode("ascii"))
        require(match is not None, "client_version")
        if match.group("build") is not None and match.group("sha") is not None:
            require(match.group("build").lower() == match.group("sha").lower(), "client_version")
    except UnicodeError:
        raise Refusal("client_version") from None


def configure(credentials_file=None):
    plan = record()["plan"]
    configured_owner(plan)
    require(not os.path.lexists(CREDENTIALS), "credentials_exist")
    verify_client(plan)
    if credentials_file:
        value = read_json(absolute(credentials_file), {plan["uid"]}, 0o600, True)
    else:
        require(sys.stdin.isatty() and sys.stderr.isatty(), "private_tty_required")
        with warnings.catch_warnings():
            warnings.simplefilter("error", getpass.GetPassWarning)
            value = {"tunnel_id": getpass.getpass("Own Tunnel ID (hidden): "),
                     "runtime_api_key": getpass.getpass("Own runtime API key (hidden): ")}
    validate_credentials(value)
    publish_file(CREDENTIALS, (json.dumps(value) + "\n").encode(), 0o600)
    return {"credentials": "provisioned", "services": "unchanged"}


def bridge_contract(plan):
    """Read selected Bridge contract only as owner; never invent/copy its token."""
    configured_owner(plan)
    manifest = read_json(BRIDGE_MANIFEST, {0}, 0o644)
    expected = manifest.get("plan")
    require(BRIDGE_MARKER is not None, "bridge_format_unverified")
    require(set(manifest) == {"format", "plan", "unit_sha256", "runner_sha256"}
            and manifest["format"] == BRIDGE_MARKER
            and isinstance(expected, dict)
            and set(expected) == {"format", "user", "uid", "gid", "home", "repo", "workspace", "herdr_bin", "port", "entrypoint"}
            and expected["format"] == BRIDGE_MARKER and expected.get("uid") == plan["uid"]
            and expected.get("gid") == plan["gid"] and expected.get("user") == plan["user"]
            and expected.get("home") == plan["home"] and expected.get("entrypoint") == "module",
            "bridge_contract_mismatch")
    require(type(expected["uid"]) is int and type(expected["gid"]) is int
            and type(expected["port"]) is int and 1 <= expected["port"] <= 65535,
            "bridge_contract_mismatch")
    for name in ("repo", "workspace", "herdr_bin", "home"):
        absolute(expected[name])
    for file, key in ((BRIDGE_RUNNER, "runner_sha256"), (BRIDGE_UNIT_FILE, "unit_sha256")):
        require(isinstance(manifest[key], str) and re.fullmatch(r"[a-f0-9]{64}", manifest[key])
                and digest(file, {0}, 0o644) == manifest[key], "bridge_installation_changed")
    # No token is read before exact schema and known root-installed file proofs.
    settings = read_json(BRIDGE_SETTINGS, {plan["uid"]}, 0o600, True)
    require(set(settings) == set(expected) | {"token"}
            and {k: settings[k] for k in expected} == expected
            and all(type(settings[k]) is type(expected[k]) for k in expected),
            "bridge_contract_mismatch")
    require(type(settings.get("port")) is int and 1 <= settings["port"] <= 65535
            and isinstance(settings.get("token"), str)
            and re.fullmatch(r"[A-Za-z0-9._~-]{32,256}", settings["token"], re.ASCII), "bridge_contract_mismatch")
    repo = absolute(settings["repo"])
    bridge = {"url": f"http://127.0.0.1:{settings['port']}/mcp/{settings['token']}",
              "python": str(repo / ".venv/bin/python"), "repo": str(repo)}
    validate_bridge_tree(bridge, plan)
    return bridge


def validate_bridge_tree(bridge, plan):
    try:
        return inspect_bridge_tree(bridge, plan)
    except Refusal:
        raise
    except (OSError, RuntimeError, ValueError, SyntaxError):
        raise Refusal("unsafe_bridge_tree") from None


def inspect_bridge_tree(bridge, plan):
    """Metadata-only trust walk, excluding non-code Git/cognition/App state.

    Never open excluded state; executable package/venv files are not excluded.
    Repeat immediately before every interpreter invocation, not just enrollment.
    """
    repo = absolute(bridge["repo"])
    owners = {0, plan["uid"]}
    directory(repo, owners)
    python = repo / ".venv/bin/python"
    directory(python.parent, owners)
    resolved = python.resolve(strict=True)
    directory(resolved.parent, owners)
    read_file(resolved, owners, limit=256 * 1024 * 1024)
    require(resolved.lstat().st_mode & 0o111, "bridge_interpreter")
    excluded = {".git", ".principal", ".app.json"}
    pending = [repo]
    count = 0
    started = time.monotonic()
    while pending:
        folder = pending.pop()
        before = identity(folder.lstat())
        with os.scandir(folder) as entries:
            for entry in entries:
                count += 1
                require(count <= MAX_TREE_ENTRIES and time.monotonic() - started <= 10, "bridge_tree_limit")
                if folder == repo and entry.name in excluded:
                    continue
                p = Path(entry.path)
                st = entry.stat(follow_symlinks=False)
                require(st.st_uid in owners and (stat.S_ISLNK(st.st_mode) or not st.st_mode & 0o7022), "unsafe_bridge_tree")
                if stat.S_ISLNK(st.st_mode):
                    target = p.resolve(strict=True)
                    safe_python = p.parent == python.parent and re.fullmatch(r"python(?:3(?:\.[0-9]+)?)?", p.name)
                    require((safe_python and target == resolved) or
                            (target.is_relative_to(repo) and target.relative_to(repo).parts[0] not in excluded),
                            "external_bridge_symlink")
                    target_stat = target.lstat()
                    require(target_stat.st_uid in owners and not target_stat.st_mode & 0o7022
                            and (stat.S_ISREG(target_stat.st_mode) or stat.S_ISDIR(target_stat.st_mode)), "unsafe_bridge_tree")
                elif stat.S_ISDIR(st.st_mode):
                    pending.append(p)
                else:
                    require(stat.S_ISREG(st.st_mode) and st.st_nlink == 1, "unsafe_bridge_tree")
        require(identity(folder.lstat()) == before, "bridge_tree_race")
    initializer = repo / "src/gpt_agent_bridge/__init__.py"
    try:
        tree = ast.parse(read_file(initializer, owners), filename="<bridge-initializer>")
    except (SyntaxError, UnicodeError):
        raise Refusal("bridge_initializer_not_inert") from None
    require(all(isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant)
                and isinstance(node.value.value, str) for node in tree.body), "bridge_initializer_not_inert")


ORIGIN_CODE = '''import importlib.util,json,sys
expected=json.loads(sys.stdin.read())["expected"]
spec=importlib.util.find_spec("gpt_agent_bridge")
sys.stdout.write("origin_valid" if spec is not None and spec.origin==expected else "origin_invalid")
'''


def package_origin(bridge, plan, timeout):
    require(os.geteuid() != 0, "owner_required")
    validate_bridge_tree(bridge, plan)
    expected = str(Path(bridge["repo"]) / "src/gpt_agent_bridge/__init__.py")
    result = subprocess.run([bridge["python"], "-I", "-B", "-c", ORIGIN_CODE],
                            input=json.dumps({"expected": expected}).encode(), stdout=subprocess.PIPE,
                            stderr=subprocess.DEVNULL, env=environment(plan), cwd="/", timeout=timeout, check=False)
    require(result.returncode == 0 and result.stdout == b"origin_valid", "bridge_package_origin")


PROBE_CODE = '''import asyncio,contextlib,json,logging,os,sys
logging.disable(logging.CRITICAL)
endpoint=json.loads(sys.stdin.read())["url"]
async def probe():
    with open(os.devnull,"w") as sink, contextlib.redirect_stdout(sink), contextlib.redirect_stderr(sink):
        from mcp import Client
        async with Client(endpoint,mode="legacy") as client:
            result=await client.call_tool("bridge_health",{})
            value=result.structured_content
            if result.is_error or not isinstance(value,dict) or value.get("bridge")!="gpt-agent-bridge" or value.get("ok") is not True:
                return "invalid"
            return "ready"
try:
    ready=asyncio.run(asyncio.wait_for(probe(),timeout=3))
except (ImportError,AttributeError,TypeError,ValueError):
    ready="invalid"
except BaseException:
    ready="pending"
sys.stdout.write(ready)
'''


def probe_bridge(bridge, plan, timeout):
    started = time.monotonic()
    package_origin(bridge, plan, timeout)
    validate_bridge_tree(bridge, plan)
    remaining = max(0.01, timeout - (time.monotonic() - started))
    result = subprocess.run([bridge["python"], "-I", "-B", "-c", PROBE_CODE],
                            input=json.dumps({"url": bridge["url"]}).encode(),
                            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                            env=environment(plan), cwd="/", timeout=remaining, check=False)
    require(result.returncode == 0 and result.stdout in (b"ready", b"pending"), "bridge_health_invalid")
    return result.stdout == b"ready"


def wait_bridge(bridge, plan, probe=probe_bridge, clock=time.monotonic, sleep=time.sleep):
    end = clock() + plan["bridge_wait_seconds"]
    while clock() < end:
        try:
            if probe(bridge, plan, min(4, max(0.01, end - clock()))) and clock() <= end:
                return
        except (OSError, subprocess.TimeoutExpired):
            pass
        remaining = end - clock()
        if remaining > 0:
            sleep(min(1, remaining))
    raise Refusal("bridge_not_ready")


def client_environment(plan, bridge, credentials):
    return {**environment(plan), "CONTROL_PLANE_TUNNEL_ID": credentials["tunnel_id"],
            "CONTROL_PLANE_API_KEY": credentials["runtime_api_key"], "MCP_SERVER_URL": bridge["url"],
            "HEALTH_UNIX_SOCKET": plan["health_socket"], "MCP_CONNECTION_MAX_TTL": plan["ttl"]}


@contextlib.contextmanager
def runtime_lock(plan):
    configured_owner(plan)
    try:
        fd = os.open(LOCK, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        os.write(fd, (MARKER + "\n").encode())
        os.fsync(fd)
        os.close(fd)
    except FileExistsError:
        pass
    require(read_file(LOCK, {plan["uid"]}, 0o600, True) == (MARKER + "\n").encode(), "foreign_lock")
    before = LOCK.lstat()
    fd = os.open(LOCK, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        require(identity(os.fstat(fd)) == identity(before), "lock_race")
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise Refusal("duplicate_tunnel") from None
        yield
    finally:
        os.close(fd)


def launch_client(plan, env):
    # Parent holds the exclusive runtime lock for the entire child's lifetime.
    with subprocess.Popen([plan["client"], "run"], stdin=subprocess.DEVNULL,
                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                          env=env, cwd="/", close_fds=True) as child:
        previous = {}
        def forward(sig, frame):
            if child.poll() is None:
                child.send_signal(sig)
        for sig in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
            previous[sig] = signal.signal(sig, forward)
        try:
            code = child.wait()
        finally:
            for sig, handler in previous.items():
                signal.signal(sig, handler)
        # An unexpected clean client exit should also be restarted by the unit.
        return 1 if code <= 0 else min(code, 125)


def runtime():
    plan = record()["plan"]
    configured_owner(plan)
    bridge = bridge_contract(plan)
    credentials = validate_credentials(read_json(CREDENTIALS, {plan["uid"]}, 0o600, True))
    verify_client(plan)
    with runtime_lock(plan):
        directory(RUNTIME, {0, plan["uid"]}, 0o700)
        require(RUNTIME.lstat().st_uid == plan["uid"] and not os.path.lexists(plan["health_socket"]), "health_socket_conflict")
        wait_bridge(bridge, plan)
        return launch_client(plan, client_environment(plan, bridge, credentials))


def managed_properties():
    activation_parent()
    props = unit_properties()
    require(props.get("FragmentPath") == str(UNIT_FILE) and not props.get("DropInPaths"), "foreign_unit")
    permitted = UNIT_FILE.parent / "multi-user.target.wants" / UNIT
    for p in activation_links():
        require(p == permitted and p.is_symlink() and os.readlink(p) == str(UNIT_FILE), "foreign_activation")
    return props


@contextlib.contextmanager
def owned_snapshot(path, expected_sha=None, expected_json=None):
    """Hold the original inode until its removal or a preserved failure."""
    before = path.lstat()
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        require(identity(os.fstat(fd)) == identity(before), "uninstall_identity_changed")
        data = read_file(path, {0}, 0o644)
        require(identity(path.lstat()) == identity(before)
                and identity(os.fstat(fd)) == identity(before), "uninstall_identity_changed")
        if expected_sha is not None:
            require(hashlib.sha256(data).hexdigest() == expected_sha, "uninstall_identity_changed")
        if expected_json is not None:
            require(json.loads(data) == expected_json, "uninstall_identity_changed")
        yield (before, data, fd)
    finally:
        os.close(fd)


def remove_owned(path, snapshot):
    before, data, fd = snapshot
    require(identity(path.lstat()) == identity(before)
            and identity(os.fstat(fd)) == identity(before)
            and read_file(path, {0}, 0o644) == data, "uninstall_identity_changed")
    # Move into a new private quarantine before unlink. If a replacement raced
    # the rename, preserve it there; never unlink an unproven public pathname.
    quarantine = Path(tempfile.mkdtemp(prefix=".tunnel-remove-", dir=path.parent))
    qid = identity(quarantine.lstat())
    qfd = os.open(quarantine, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    staged = quarantine / path.name
    try:
        os.rename(path, staged)
        current = staged.lstat()
        def core(st):
            return identity(st)[:-1]  # rename may change ctime, never inode/data/mode
        require(core(current) == core(before) and core(os.fstat(fd)) == core(before)
                and read_file(staged, {0}, 0o644, True) == data, "uninstall_identity_changed")
        require(core(staged.lstat()) == core(before), "uninstall_identity_changed")
        staged.unlink()
    finally:
        # Unknown/replaced quarantine contents stay available to the operator.
        try:
            if identity(quarantine.lstat())[:2] == qid[:2] and not list(quarantine.iterdir()):
                quarantine.rmdir()
        finally:
            os.close(qfd)


def lifecycle(action):
    trusted_snapshot()
    data = record()
    props = managed_properties()
    if action in ("enable", "start"):
        st = CREDENTIALS.lstat()  # permission/existence only: root never reads key
        require(stat.S_ISREG(st.st_mode) and st.st_uid == data["plan"]["uid"]
                and stat.S_IMODE(st.st_mode) == 0o600 and st.st_nlink == 1, "credentials_not_provisioned")
        directory(STATE, {0, data["plan"]["uid"]}, 0o700)
        require(STATE.lstat().st_uid == data["plan"]["uid"], "state_owner")
    if action == "enable":
        require(props.get("UnitFileState") == "disabled", "unexpected_enable_state")
    elif action == "start":
        require(props.get("ActiveState") == "inactive", "unexpected_start_state")
        require(not os.path.lexists(data["plan"]["health_socket"]), "health_socket_conflict")
    elif action == "uninstall":
        require(props.get("ActiveState") == "inactive" and props.get("UnitFileState") == "disabled", "uninstall_active")
        require(set(p.name for p in LIB.iterdir()) == {"runner.py", "installation.json"}, "unknown_installation_files")
        # Capture all known objects before any unlink. Replacements after the
        # last root manifest read do not become authorized uninstall objects.
        data = record()
        with contextlib.ExitStack() as stack:
            snapshots = [stack.enter_context(owned_snapshot(UNIT_FILE, data["unit_sha256"])),
                         stack.enter_context(owned_snapshot(RUNNER, data["runner_sha256"])),
                         stack.enter_context(owned_snapshot(MANIFEST, expected_json=data))]
            for p, captured in zip((UNIT_FILE, RUNNER, MANIFEST), snapshots):
                remove_owned(p, captured)
        LIB.rmdir()
        call([SYSTEMCTL, "daemon-reload"])
        return {"installation": "removed", "credentials": "preserved", "services": "not_started"}
    call([SYSTEMCTL, action, UNIT])
    return {"action": action, "result": "command_completed", "web_ready": "not_established"}


class UnixHTTP(http.client.HTTPConnection):
    def connect(self):
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.settimeout(self.timeout)
        self.sock.connect(self.host)


def health_status(plan):
    configured_owner(plan)
    directory(RUNTIME, {0, plan["uid"]}, 0o700)
    s = Path(plan["health_socket"]).lstat()
    require(stat.S_ISSOCK(s.st_mode) and s.st_uid == plan["uid"], "unsafe_health_socket")
    conn = UnixHTTP(plan["health_socket"], timeout=2)
    try:
        conn.request("GET", "/readyz")
        response = conn.getresponse()
        ready = response.status == 200
        response.read(LIMIT + 1)  # discard raw readiness reason
        return {"tunnel_startup": "ready" if ready else "not_ready", "control_plane": "not_verified", "web_ready": "not_established"}
    finally:
        conn.close()


def status():
    data = record()
    props = managed_properties()
    active = props.get("ActiveState")
    enabled = props.get("UnitFileState")
    result = {"process": active if active in ("active", "inactive", "failed", "activating", "deactivating") else "unknown",
              "boot_activation": enabled if enabled in ("enabled", "disabled") else "unknown",
              "herdr": "manual_not_probed", "work_resume": "not_established", "web_ready": "not_established"}
    if os.geteuid() == data["plan"]["uid"]:
        try:
            result.update(health_status(data["plan"]))
        except (Refusal, OSError, http.client.HTTPException):
            result["tunnel_startup"] = "unknown"
    else:
        result["tunnel_startup"] = "owner_probe_required"
    return result


class SafeParser(argparse.ArgumentParser):
    def error(self, message):
        raise Refusal("invalid_arguments")


def main(argv=None):
    parser = SafeParser(description=__doc__)
    parser.add_argument("action", choices=("plan", "install", "configure", "enable", "start", "status", "disable", "stop", "uninstall", "run"))
    parser.add_argument("--user")
    parser.add_argument("--client")
    parser.add_argument("--client-sha256")
    parser.add_argument("--health-socket", default="health.sock")
    parser.add_argument("--ttl", choices=("10m", "60m"), default="10m")
    parser.add_argument("--bridge-wait-seconds", type=int, default=60)
    parser.add_argument("--credentials-file")
    try:
        args = parser.parse_args(argv)
        if args.action == "plan":
            result = {"plan": make_plan(args), "effects": "none", "client_version": "unobserved_until_nonroot", "bridge_contract": "pending_runtime_verification"}
        elif args.action == "install":
            trusted_snapshot()  # before any user-selected executable is inspected
            result = install(make_plan(args))
        elif args.action == "configure":
            result = configure(args.credentials_file)
        elif args.action == "run":
            return runtime()
        elif args.action == "status":
            result = status()
        else:
            result = lifecycle(args.action)
        print(json.dumps(result, sort_keys=True))
        return 0
    except SystemExit as error:
        return error.code
    except Refusal as error:
        print(json.dumps({"result": "refused", "reason": error.code,
                          "stage": error.stage, "retry": "operator_review_required"}))
        return 1 if error.code == "bridge_not_ready" else 78
    except BaseException:
        # Never print raw exception, child stdout, secret input or traceback.
        print(json.dumps({"result": "not_completed", "reason": "operation_failed", "retry": "operator_review_required"}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
