"""Synthetic integration tests for the portable service installer.

Exercises the real main-path formats and failure cases without privileges:
NUL-environ parsing, process adoption (exactly-one, working-directory
revalidated, systemd MainPID revalidated), env staging through the shared
allowlist library, unit rendering with a valid .service filename, verification
gating before publication, and the never-start/never-enable guarantee."""
import getpass
import json
import os
import subprocess
import sys
import tempfile
import unittest
import venv
from pathlib import Path
from tests.test_install_env_allowlist import (
    MIGRATED_KEYS, SINGLE_LINE_VALUES, SYSTEMD_249_LIBRARY, SYSTEMD_249_SKIP,
    staged_values, systemd249_values,
)

ROOT = Path(__file__).resolve().parents[1]
INSTALLER = ROOT / "scripts" / "install-bridge-system-service.sh"
TEMPLATE = ROOT / "systemd" / "gpt-agent-bridge.service.template"
ALLOWLIST = ROOT / "scripts" / "bridge-env-allowlist.sh"
TTL = ROOT / "scripts" / "stage-tunnel-mcp-ttl.sh"


def write_nul_environ(path: Path, pairs: dict[str, str]) -> None:
    path.write_bytes(
        b"".join(f"{k}={v}".encode() + b"\x00" for k, v in pairs.items()))


def bash(script: str, *args: str, PATH_prefix: str | None = None,
         cwd: str | None = None) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    if PATH_prefix:
        env["PATH"] = PATH_prefix + ":" + env.get("PATH", "")
    return subprocess.run(
        ["bash", "-c", script, "test-helper", *args],
        capture_output=True, text=True, env=env, cwd=cwd)


def source_call(call: str, *args: str, PATH_prefix: str | None = None):
    # $1 = installer, $2 = allowlist library; call arguments start at $3.
    return bash(
        'source "$1"; source "$2"; ' + call,
        INSTALLER, ALLOWLIST, *args, PATH_prefix=PATH_prefix)


class NulEnvValueTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.environ = Path(self.dir.name) / "environ"

    def test_parses_nul_separated_pairs_with_embedded_equals(self):
        write_nul_environ(self.environ, {
            "BRIDGE_PATH_TOKEN": "tok=en=ded",
            "BRIDGE_WORKSPACE": "/repo",
            "PATH": "/bin:/usr/bin",
        })
        completed = source_call(
            'printf "%s" "$(bridge_env_value "$3" BRIDGE_PATH_TOKEN)"',
            str(self.environ))
        self.assertEqual(completed.returncode, 0)
        self.assertEqual(completed.stdout, "tok=en=ded")

    def test_exact_prefix_match_and_missing_key(self):
        write_nul_environ(self.environ, {
            "NO_PROXY": "127.0.0.1",
            "PATH": "/bin",
        })
        for key, expected in (("NO_PROXY", "127.0.0.1"), ("PATH", "/bin"),
                              ("NO_PROXY_V2", ""), ("BRIDGE_PATH_TOKEN", "")):
            with self.subTest(key=key):
                completed = source_call(
                    f'printf "%s" "$(bridge_env_value "$3" "{key}")"',
                    str(self.environ))
                self.assertEqual(completed.returncode, 0)
                self.assertEqual(completed.stdout, expected)

    def test_newline_file_is_not_accepted_as_a_process_environment(self):
        self.environ.write_bytes(b"BRIDGE_MCP_AUTH_SECRET=sec\n")
        completed = source_call(
            'bridge_env_value "$3" BRIDGE_MCP_AUTH_SECRET', str(self.environ))
        self.assertNotEqual(completed.returncode, 0)
        self.assertEqual(completed.stdout, "")
        self.assertIn("not NUL-terminated", completed.stderr)

    def test_lookup_validates_all_migrated_keys_not_only_requested_key(self):
        for tail in (b"PATH=/bin\0PATH=/other\0", b"XDG_STATE_HOME=/state\nother\0"):
            with self.subTest(tail=tail):
                self.environ.write_bytes(b"BRIDGE_PATH_TOKEN=tok\0" + tail)
                completed = source_call(
                    'bridge_env_value "$3" BRIDGE_PATH_TOKEN', str(self.environ))
                self.assertNotEqual(completed.returncode, 0)
                self.assertEqual(completed.stdout, "")

    def test_lookup_preserves_leading_trailing_spaces_and_equals(self):
        value = " token = 'quoted' "
        write_nul_environ(self.environ, {"BRIDGE_PATH_TOKEN": value})
        completed = source_call('bridge_env_value "$3" BRIDGE_PATH_TOKEN', str(self.environ))
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(completed.stdout, value)


def synthetic_package(repo: Path) -> Path:
    package = repo / "src/gpt_agent_bridge"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text("", encoding="utf-8")
    (package / "__main__.py").write_text("", encoding="utf-8")
    (repo / "pyproject.toml").write_text("", encoding="utf-8")
    # Genuine isolated interpreter + editable-style source path, no pip or
    # product bootstrap. -I still discovers this fixture's installed package.
    venv.EnvBuilder(with_pip=False, symlinks=True).create(repo / ".venv")
    site = next((repo / ".venv/lib").glob("python*/site-packages"))
    (site / "fixture.pth").write_text(str(repo / "src") + "\n")
    return site


class AdoptPidTests(unittest.TestCase):
    """Real validator, synthetic proc bytes; never inspect the host process table."""
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.root = Path(self.dir.name)
        self.repo = self.root / "repo"
        self.site = synthetic_package(self.repo)
        self.python = self.repo / ".venv/bin/python"
        self.proc = self.root / "proc"
        self.proc.mkdir()
        self.candidates = self.root / "candidates"
        self.candidates.write_text("")
        self.active = self.root / "active"
        self.active.write_text("101\n")
        self.enumerated = self.root / "enumerated"
        self.bin = self.root / "bin"
        self.bin.mkdir()
        self.command("pgrep", 'touch "$FAKE_ENUMERATED"; cat "$FAKE_CANDIDATES"')

    def command(self, name, body):
        target = self.bin / name
        target.write_text('#!/usr/bin/env bash\n' + body + '\n')
        target.chmod(0o755)

    def candidate(self, pid=101, *, argv=None, exe=None, cwd=None, state="S", started=100):
        directory = self.proc / str(pid)
        directory.mkdir(exist_ok=True)
        for name, target in (("cwd", cwd or self.repo), ("exe", exe or self.python.resolve())):
            link = directory / name
            link.unlink(missing_ok=True)
            link.symlink_to(target)
        if argv is None:
            argv = [str(self.python), "-m", "gpt_agent_bridge"]
        (directory / "cmdline").write_bytes(
            b"\0".join(os.fsencode(arg) for arg in argv) + b"\0")
        self.stat(pid, state=state, started=started)
        self.candidates.write_text(self.candidates.read_text() + f"{pid}\n")
        return directory

    def stat(self, pid=101, *, state="S", started=100):
        # Fields 3..21, followed by field 22 (starttime). Parentheses in comm
        # exercise the parser rather than a whitespace-only stat stub.
        (self.proc / str(pid) / "stat").write_text(
            f"{pid} (dummy ) python) {state} " + "0 " * 18 + f"{started} 0\n")

    def call(self, mode="inactive", extra="", call='bridge_adopt_pid "$3"'):
        self.command("systemctl", 'if [[ "$1" == is-active ]]; then exit ' +
                     ("0" if mode == "active" else "3") +
                     '; fi\nif [[ "$1" == show ]]; then cat "$FAKE_ACTIVE"; else exit 2; fi')
        return source_call(
            'FAKE_CANDIDATES=$5 FAKE_ACTIVE=$6 FAKE_ENUMERATED=$7; '
            'export FAKE_CANDIDATES FAKE_ACTIVE FAKE_ENUMERATED; '
            'fixture_proc=$4; bridge_proc_root() { printf "%s" "$fixture_proc"; }; ' + extra + call,
            str(self.repo), str(self.proc), str(self.candidates), str(self.active),
            str(self.enumerated), PATH_prefix=str(self.bin))

    def refused_both(self):
        for mode in ("inactive", "active"):
            with self.subTest(mode=mode):
                result = self.call(mode)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(result.stdout, "")

    def test_zero_candidates_fails(self):
        result = self.call()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("no running Bridge process", result.stderr)
        self.assertTrue(self.enumerated.exists())

    def test_exactly_one_candidate_is_returned(self):
        self.candidate()
        result = self.call()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "101\n")
        self.assertTrue(self.enumerated.exists())

    def test_active_service_exact_launch_is_returned_without_pgrep(self):
        self.candidate()
        result = self.call("active")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "101\n")
        self.assertFalse(self.enumerated.exists())

    def test_two_candidates_fail_exactly_one_required(self):
        self.candidate()
        self.candidate(102)
        result = self.call()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("exactly one", result.stderr)

    def test_active_service_mainpid_must_revalidate_repo(self):
        self.candidate(cwd=self.root)
        self.refused_both()

    def test_sleep_exec_a_decoy_is_rejected(self):
        # Exact bytes produced by exec -a "python -m gpt_agent_bridge" sleep 30.
        self.candidate(argv=["python -m gpt_agent_bridge", "30"], exe="/bin/sleep")
        self.refused_both()

    def test_exact_argv_with_wrong_executable_is_rejected(self):
        self.candidate(exe="/bin/sleep")
        self.refused_both()

    def test_other_venv_same_resolved_python_is_rejected(self):
        other = self.root / "other-venv/bin/python"
        other.parent.mkdir(parents=True)
        other.symlink_to(self.python.resolve())
        self.assertEqual(other.resolve(), self.python.resolve())
        self.candidate(argv=[str(other), "-m", "gpt_agent_bridge"])
        self.refused_both()

    def test_flags_extra_args_wrong_module_and_console_are_rejected(self):
        self.candidate()
        variants = ([str(self.python), "-I", "-m", "gpt_agent_bridge"],
                    [str(self.python), "-m", "gpt_agent_bridge", "--extra"],
                    [str(self.python), "-m", "gpt_agent_bridge.server"],
                    [str(self.python), str(self.repo / ".venv/bin/gpt-agent-bridge")],
                    ["python", "-m", "gpt_agent_bridge"])
        for argv in variants:
            with self.subTest(argv=argv):
                (self.proc / "101/cmdline").write_bytes(
                    b"\0".join(os.fsencode(a) for a in argv) + b"\0")
                self.refused_both()

    def test_wrong_package_origin_is_rejected(self):
        self.candidate()
        other = self.root / "other-source/gpt_agent_bridge"
        other.mkdir(parents=True)
        (other / "__init__.py").write_text("")
        (self.site / "fixture.pth").write_text(str(other.parent) + "\n")
        self.refused_both()

    def test_missing_package_is_rejected(self):
        self.candidate()
        (self.site / "fixture.pth").unlink()
        self.refused_both()

    def test_package_init_symlink_escape_is_rejected(self):
        self.candidate()
        target = self.root / "outside.py"
        target.write_text("")
        init = self.repo / "src/gpt_agent_bridge/__init__.py"
        init.unlink()
        init.symlink_to(target)
        self.refused_both()

    def test_invalid_active_pid_never_falls_back_to_valid_candidate(self):
        self.candidate()
        for pid in ("0", "-1", "101\n102", "not-a-pid", "999999"):
            with self.subTest(pid=pid):
                self.active.write_text(pid + "\n")
                result = self.call("active")
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(result.stdout, "")
                self.assertIn("refusing service adoption", result.stderr)
                self.assertFalse(self.enumerated.exists())

    def test_unreadable_proc_is_rejected(self):
        directory = self.candidate()
        (directory / "cmdline").chmod(0)
        self.refused_both()

    def test_missing_or_nonregular_proc_is_rejected(self):
        directory = self.candidate()
        for kind in ("absent", "directory", "fifo", "symlink"):
            with self.subTest(kind=kind):
                path = directory / "cmdline"
                if path.is_dir():
                    path.rmdir()
                else:
                    path.unlink(missing_ok=True)
                if kind == "directory":
                    path.mkdir()
                elif kind == "fifo":
                    os.mkfifo(path)
                elif kind == "symlink":
                    target = self.root / "argv"
                    target.write_bytes(os.fsencode(self.python) + b"\0-m\0gpt_agent_bridge\0")
                    path.symlink_to(target)
                self.refused_both()

    def test_dead_or_invalid_stat_is_rejected(self):
        self.candidate()
        for state, started in (("Z", 100), ("X", 100), ("S", 0)):
            with self.subTest(state=state, started=started):
                self.stat(state=state, started=started)
                self.refused_both()
        (self.proc / "101/stat").write_text("bad stat\n")
        self.refused_both()

    def test_nul_boundary_and_oversized_argv_are_rejected(self):
        self.candidate()
        for raw in (os.fsencode(self.python) + b" -m gpt_agent_bridge\0",
                    os.fsencode(self.python) + b"\0-m\0gpt_agent_bridge",
                    os.fsencode(self.python) + b"\0-m\0gpt_agent_bridge\0\0",
                    b"x" * 16385):
            with self.subTest(length=len(raw)):
                (self.proc / "101/cmdline").write_bytes(raw)
                self.refused_both()

    def test_fallback_filters_decoy_with_real_identity_validator(self):
        self.candidate(argv=["python -m gpt_agent_bridge", "30"], exe="/bin/sleep")
        self.candidate(102)
        result = self.call()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "102\n")

    def test_duplicate_or_invalid_enumeration_fails_closed(self):
        self.candidate()
        for raw in ("101\n101\n", "101\ninvalid\n"):
            with self.subTest(raw=raw):
                self.candidates.write_text(raw)
                result = self.call()
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(result.stdout, "")

    def test_enumeration_error_fails_closed(self):
        self.candidate()
        self.command("pgrep", "exit 2")
        result = self.call()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("enumeration failed", result.stderr)

    def test_failed_service_activity_query_never_enumerates(self):
        self.candidate()
        result = self.call(extra='systemctl() { return 2; }; ')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("activity query failed", result.stderr)
        self.assertFalse(self.enumerated.exists())

    def test_active_mainpid_query_error_never_falls_back(self):
        self.candidate()
        result = self.call("active", extra='systemctl() { '
                           '[[ "$1" == is-active ]] && return 0; return 2; }; ')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("refusing service adoption", result.stderr)
        self.assertFalse(self.enumerated.exists())

    def test_selected_identity_is_retained_and_revalidated(self):
        self.candidate()
        for mode in ("inactive", "active"):
            with self.subTest(mode=mode):
                result = self.call(mode, call='bridge_adopt_pid "$3" >/dev/null && '
                                   '[[ $BRIDGE_ADOPTED_PID == 101 ]] && '
                                   'bridge_validate_pid "$3" "$BRIDGE_ADOPTED_PID" '
                                   '"$BRIDGE_ADOPTED_IDENTITY" >/dev/null')
                self.assertEqual(result.returncode, 0, result.stderr)

    def test_reused_pid_or_changed_identity_rejects_old_fingerprint(self):
        self.candidate()
        result = self.call(call='bridge_validate_pid "$3" 101')
        self.assertEqual(result.returncode, 0, result.stderr)
        fingerprint = result.stdout.strip()
        self.assertRegex(fingerprint, r"^[0-9a-f]{64}$")
        for changed in ("starttime", "cwd", "exe", "argv", "dead", "removed"):
            with self.subTest(changed=changed):
                self.candidate()
                if changed == "starttime":
                    self.stat(started=101)
                elif changed in ("cwd", "exe"):
                    path = self.proc / "101" / changed
                    path.unlink()
                    path.symlink_to(self.root if changed == "cwd" else "/bin/sleep")
                elif changed == "argv":
                    (self.proc / "101/cmdline").write_bytes(b"different\0")
                elif changed == "dead":
                    self.stat(state="Z")
                else:
                    (self.proc / "101/stat").unlink()
                result = self.call(call=f'bridge_validate_pid "$3" 101 "{fingerprint}"')
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(result.stdout, "")

    def test_change_after_validation_is_rejected_in_both_selection_branches(self):
        self.candidate()
        # Wrap the REAL validator only to remove a fixture after its first read.
        extra = ('definition=$(declare -f bridge_validate_pid); '
                 'eval "${definition/bridge_validate_pid/real_bridge_validate_pid}"; '
                 'bridge_validate_pid() { real_bridge_validate_pid "$@" || return; '
                 'rm -f "$4/101/cmdline"; }; ')
        # Function positional arguments differ from the outer source_call args;
        # capture the synthetic proc root before declaring the wrapper.
        extra = extra.replace('definition=', 'fixture_proc=$4; definition=', 1).replace(
            '"$4/101/cmdline"', '"$fixture_proc/101/cmdline"')
        for mode in ("inactive", "active"):
            with self.subTest(mode=mode):
                (self.proc / "101/cmdline").write_bytes(
                    os.fsencode(self.python) + b"\0-m\0gpt_agent_bridge\0")
                result = self.call(mode, extra=extra)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(result.stdout, "")
                self.assertIn("changed during selection", result.stderr)


class StageEnvIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.environ = Path(self.dir.name) / "environ"
        self.out = Path(self.dir.name) / "bridge.env"

    def stage(self, repo: str = "/repo", proxy: str | None = None,
              pairs: dict[str, str] | None = None):
        pairs = {"BRIDGE_PATH_TOKEN": "tok", "BRIDGE_WORKSPACE": "/repo",
                 "PATH": "/bin:/usr/bin",
                 **(pairs or {})}
        raw = b"".join(f"{key}={value}\0".encode() for key, value in pairs.items())
        return self.stage_raw(raw, repo=repo, proxy=proxy or "")

    def stage_raw(self, raw: bytes, repo="/repo", proxy="", guarded=False):
        self.out.unlink(missing_ok=True)
        self.environ.write_bytes(raw)
        call = 'bridge_stage_env "$4" "$3" me /home/me "$5" "$6"'
        if guarded:
            call = f'if {call}; then touch "$7"; else exit 1; fi'
        return source_call(
            'set -euo pipefail; ' + call, str(self.environ), str(self.out), repo, proxy,
            str(Path(self.dir.name) / "published"))

    def test_happy_path_stages_real_main_path_format(self):
        completed = self.stage(pairs={"BRIDGE_MCP_AUTH_SECRET": "sec"})
        self.assertEqual(completed.returncode, 0, completed.stderr)
        values = staged_values(self.out)
        self.assertEqual(values["BRIDGE_PATH_TOKEN"], "tok")
        self.assertEqual(values["BRIDGE_WORKSPACE"], "/repo")
        self.assertEqual(values["PATH"], "/bin:/usr/bin")
        self.assertEqual(values["BRIDGE_MCP_ENABLE_DNS_REBINDING_PROTECTION"], "true")
        self.assertEqual(json.loads(values["BRIDGE_MCP_ALLOWED_HOSTS"]), ["127.0.0.1:8765"])
        self.assertEqual(json.loads(values["BRIDGE_MCP_ALLOWED_ORIGINS"]), [])
        self.assertEqual(values["BRIDGE_MCP_AUTH_SECRET"], "sec")

    def test_nondefault_port_has_exact_matching_host_rule(self):
        for raw_port in ("9876", "09876", "1", "65535"):
            with self.subTest(port=raw_port):
                completed = self.stage(pairs={"BRIDGE_PORT": raw_port})
                self.assertEqual(completed.returncode, 0, completed.stderr)
                values = staged_values(self.out)
                self.assertEqual(values["BRIDGE_PORT"], raw_port)
                self.assertEqual(json.loads(values["BRIDGE_MCP_ALLOWED_HOSTS"]),
                                 [f"127.0.0.1:{int(raw_port)}"])
                self.assertEqual(values["BRIDGE_MCP_ENABLE_DNS_REBINDING_PROTECTION"], "true")
                self.assertEqual(json.loads(values["BRIDGE_MCP_ALLOWED_ORIGINS"]), [])

    def test_ambiguous_or_invalid_port_fails_before_staging(self):
        for port in ("", "0", "65536", "-1", "+9876", " 9876 ", "1e4",
                     "9999999999999999999999", "9876\nother"):
            with self.subTest(port=port):
                completed = self.stage(pairs={"BRIDGE_PORT": port})
                self.assertNotEqual(completed.returncode, 0)
                self.assertIn("BRIDGE_PORT", completed.stderr)
                self.assertFalse(self.out.exists())

    def test_herdr_runtime_configuration_survives_migration(self):
        def runtime_configuration(values):
            completed = subprocess.run(
                [sys.executable, "-c", "import json; from gpt_agent_bridge import herdr_backend as h; "
                 "print(json.dumps([h.HERDR_COMMAND, h.HERDR_ENABLED]))"],
                cwd=ROOT, env={"PATH": os.defpath, "PYTHONDONTWRITEBYTECODE": "1", **values},
                capture_output=True, text=True, check=True,
            )
            return json.loads(completed.stdout)
        for binary, enabled in ((None, None), ("/srv/custom herdr/bin/herdr", None),
                                ("/srv/custom herdr/bin/herdr", "false"),
                                ("custom-herdr", " TRUE "), ("custom-herdr", ""),
                                ("", "false"), ("", "")):
            with self.subTest(binary=binary, enabled=enabled):
                pairs = {key: value for key, value in
                         (("BRIDGE_HERDR_BIN", binary), ("BRIDGE_HERDR_ENABLED", enabled))
                         if value is not None}
                completed = self.stage(pairs=pairs)
                self.assertEqual(completed.returncode, 0, completed.stderr)
                migrated = staged_values(self.out)
                for key in ("BRIDGE_HERDR_BIN", "BRIDGE_HERDR_ENABLED"):
                    if key in pairs:
                        self.assertEqual(migrated[key], pairs[key])
                    else:
                        self.assertNotIn(key, migrated)
                self.assertEqual(runtime_configuration(pairs), runtime_configuration(migrated))

    def test_unrepresentable_herdr_config_prevents_publication(self):
        self.out.unlink(missing_ok=True)
        write_nul_environ(self.environ, {
            "BRIDGE_PATH_TOKEN": "tok", "BRIDGE_WORKSPACE": "/repo", "PATH": "/bin",
            "BRIDGE_HERDR_BIN": "/private\nherdr",
        })
        published = Path(self.dir.name) / "published"
        completed = source_call(
            'set -euo pipefail; bridge_stage_env "$4" "$3" me /home/me /repo ""; '
            'touch "$5"', str(self.environ), str(self.out), str(published))
        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("BRIDGE_HERDR_BIN", completed.stderr)
        self.assertFalse(published.exists())

    def test_store_overrides_lease_and_both_secrets_survive_staging(self):
        pairs = {"BRIDGE_WORKSPACE_STORE_PATH": "/live/workspaces.json",
                 "XDG_STATE_HOME": "/live/state", "BRIDGE_AWAIT_LEASE_SECONDS": "120",
                 "BRIDGE_WORKSPACE_REGISTRY": '{"review":"/srv/review"}',
                 "BRIDGE_MCP_AUTH_SECRET": "current secret", "BRIDGE_MCP_AUTH_PREVIOUS_SECRET": "old secret"}
        completed = self.stage(pairs=pairs)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        values = staged_values(self.out)
        for key, value in pairs.items():
            self.assertEqual(values[key], value)

    def test_workspace_mismatch_fails_closed(self):
        completed = self.stage(repo="/other")
        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("does not match this repository", completed.stderr)
        self.assertFalse(self.out.exists())

    def test_missing_path_token_fails_closed(self):
        completed = self.stage(pairs={"BRIDGE_PATH_TOKEN": ""})
        self.assertNotEqual(completed.returncode, 0)
        self.assertFalse(self.out.exists())

    def test_proxy_lines_are_staged_when_proxy_given(self):
        completed = self.stage(
            pairs={"HTTP_PROXY": "http://p:1", "HTTPS_PROXY": "http://p:1",
                   "http_proxy": "http://p:1", "https_proxy": "http://p:1",
                   "NO_PROXY": "127.0.0.1"},
            proxy="http://p:1")
        self.assertEqual(completed.returncode, 0, completed.stderr)
        values = staged_values(self.out)
        self.assertEqual(values["HTTP_PROXY"], "http://p:1")
        self.assertEqual(values["NO_PROXY"], "127.0.0.1")
        self.assertEqual(values["no_proxy"], "127.0.0.1")

    def test_proxy_mismatch_fails_closed(self):
        completed = self.stage(
            pairs={"HTTP_PROXY": "http://other:9"}, proxy="http://p:1")
        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("HTTP_PROXY does not match --proxy", completed.stderr)
        self.assertNotIn("http://p:1", completed.stderr)
        self.assertFalse(self.out.exists())

    def test_every_compared_key_fails_before_output_on_controls_and_duplicates(self):
        baseline = {"BRIDGE_PATH_TOKEN": "tok", "BRIDGE_WORKSPACE": "/repo", "PATH": "/bin"}
        for key in MIGRATED_KEYS:
            prefix = b"".join(f"{k}={v}\0".encode() for k, v in baseline.items() if k != key)
            for suffix in (f"{key}=private\nvalue\0", f"{key}=private\tvalue\0",
                           f"{key}=private\rvalue\0", f"{key}=\0{key}=again\0"):
                with self.subTest(key=key, suffix=repr(suffix)):
                    completed = self.stage_raw(prefix + suffix.encode(), guarded=True)
                    self.assertNotEqual(completed.returncode, 0)
                    self.assertIn(key, completed.stderr)
                    self.assertNotIn("private", completed.stderr)
                    self.assertFalse(self.out.exists())
                    self.assertFalse((Path(self.dir.name) / "published").exists())

    def test_unterminated_unknown_tail_and_invalid_utf8_prevent_output(self):
        base = b"BRIDGE_PATH_TOKEN=tok\0BRIDGE_WORKSPACE=/repo\0PATH=/bin\0"
        for tail in (b"IGNORED=tail", b"XDG_STATE_HOME=bad\xff\0"):
            with self.subTest(tail=tail):
                completed = self.stage_raw(base + tail, guarded=True)
                self.assertNotEqual(completed.returncode, 0)
                self.assertFalse(self.out.exists())
                self.assertFalse((Path(self.dir.name) / "published").exists())

    def test_supported_special_values_survive_every_emission_group(self):
        for value in SINGLE_LINE_VALUES:
            with self.subTest(value=value):
                # Required base fields remain nonempty; exact repo comparison
                # is deliberately exercised with quotes/dollars/Unicode too.
                repo, token = "/repo/" + value, "token:" + value
                pairs = {"BRIDGE_PATH_TOKEN": token, "BRIDGE_WORKSPACE": repo,
                         "PATH": "/bin:" + value, "BRIDGE_HERDR_BIN": value,
                         "BRIDGE_HERDR_ENABLED": value, "BRIDGE_MCP_AUTH_SECRET": value,
                         "BRIDGE_WORKSPACE_STORE_PATH": value, "XDG_STATE_HOME": value,
                         "NO_PROXY": value, "no_proxy": value}
                completed = self.stage(repo=repo, pairs=pairs)
                self.assertEqual(completed.returncode, 0, completed.stderr)
                values = staged_values(self.out)
                for key, expected in pairs.items():
                    self.assertEqual(values[key], expected)
                for key in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy"):
                    self.assertNotIn(key, values)

    def test_proxy_specials_are_literal_and_lowercase_conflict_refuses(self):
        proxy = 'http://name:$secret`literal`"\\\\@host:1'
        pairs = {key: proxy for key in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy")}
        pairs.update(NO_PROXY=" host,localhost ", no_proxy=" host,localhost ")
        completed = self.stage(proxy=proxy, pairs=pairs)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        values = staged_values(self.out)
        for key, value in pairs.items():
            self.assertEqual(values[key], value)
        completed = self.stage(pairs={"NO_PROXY": "host", "no_proxy": "other"})
        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("no_proxy does not match NO_PROXY", completed.stderr)
        self.assertFalse(self.out.exists())

    def test_proxy_argument_controls_fail_even_without_errexit(self):
        base = b"BRIDGE_PATH_TOKEN=tok\0BRIDGE_WORKSPACE=/repo\0PATH=/bin\0"
        completed = self.stage_raw(base, proxy="private\nproxy", guarded=True)
        self.assertNotEqual(completed.returncode, 0)
        self.assertNotIn("private", completed.stderr)
        self.assertFalse(self.out.exists())
        self.assertFalse((Path(self.dir.name) / "published").exists())

    @unittest.skipUnless(Path("/dev/full").exists(), "Linux write-failure fixture unavailable")
    def test_write_failure_prevents_publication_even_in_guarded_call(self):
        write_nul_environ(self.environ, {
            "BRIDGE_PATH_TOKEN": "tok", "BRIDGE_WORKSPACE": "/repo", "PATH": "/bin"})
        published = Path(self.dir.name) / "published"
        completed = source_call(
            'if bridge_stage_env /dev/full "$3" me /home/me /repo ""; '
            'then touch "$4"; else exit 1; fi', str(self.environ), str(published))
        self.assertNotEqual(completed.returncode, 0)
        self.assertFalse(published.exists())

    @unittest.skipUnless(SYSTEMD_249_LIBRARY, SYSTEMD_249_SKIP)
    def test_systemd_249_native_parser_consumes_whole_staged_environment(self):
        special = ' leading "quoted" \\\\ $dollar `backtick` 中文 trailing '
        repo = "/repo/" + special
        proxy = "http://host/" + special
        pairs = {"BRIDGE_PATH_TOKEN": special, "BRIDGE_WORKSPACE": repo,
                 "PATH": "/bin:" + special, "BRIDGE_PORT": "09876",
                 "BRIDGE_AWAIT_LEASE_SECONDS": "120",
                 "BRIDGE_WORKSPACE_REGISTRY": '{"review":"/srv/审查"}',
                 "BRIDGE_HERDR_BIN": special, "BRIDGE_HERDR_ENABLED": "",
                 "BRIDGE_MCP_AUTH_SECRET": special, "BRIDGE_MCP_AUTH_PREVIOUS_SECRET": "",
                 "BRIDGE_WORKSPACE_STORE_PATH": special, "XDG_STATE_HOME": special,
                 "NO_PROXY": special, "no_proxy": special,
                 **{key: proxy for key in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy")}}
        completed = self.stage(repo=repo, proxy=proxy, pairs=pairs)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        expected = {**pairs, "BRIDGE_MCP_ENABLE_DNS_REBINDING_PROTECTION": "true",
                    "BRIDGE_MCP_ALLOWED_HOSTS": '["127.0.0.1:9876"]',
                    "BRIDGE_MCP_ALLOWED_ORIGINS": "[]"}
        self.assertEqual(systemd249_values(self.out), expected)
        self.assertEqual(staged_values(self.out), expected)


class RenderAndVerifyTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.stage_dir = Path(self.dir.name) / "stage"
        self.stage_dir.mkdir()

    def test_rendered_unit_verifies_under_valid_service_filename(self):
        # A fresh public source tree has no venv. Supply the executable only in
        # this disposable rendered-unit fixture; keep real systemd verification.
        repo = Path(self.dir.name) / "repo"
        interpreter = repo / ".venv/bin/python"
        interpreter.parent.mkdir(parents=True)
        interpreter.symlink_to(Path(sys.executable).resolve())
        unit = self.stage_dir / "gpt-agent-bridge.service"
        completed = source_call(
            'bridge_render_unit "$3" alice "/home/alice" "$5" > "$4"'
            ' && systemd-analyze verify "$4"',
            str(TEMPLATE), str(unit), str(repo))
        self.assertEqual(completed.returncode, 0, completed.stderr)
        text = unit.read_text(encoding="utf-8")
        self.assertIn("User=alice", text)
        self.assertIn(f"WorkingDirectory={repo}", text)
        self.assertIn(f"ExecStart={interpreter} -m gpt_agent_bridge", text)
        self.assertNotIn("server.py", text)
        self.assertIn(
            "EnvironmentFile=/home/alice/.config/gpt-agent-bridge/bridge.env",
            text)
        self.assertNotIn("@", text)

    def test_verify_gate_blocks_publication_when_analyze_fails(self):
        fake_bin = Path(self.dir.name) / "bin"
        fake_bin.mkdir()
        verify_marker = Path(self.dir.name) / "verify-invoked"
        (fake_bin / "systemd-analyze").write_text(
            f"#!/usr/bin/env bash\nprintf invoked > {verify_marker!s}\nexit 1\n",
            encoding="utf-8")
        (fake_bin / "systemd-analyze").chmod(0o755)
        unit = self.stage_dir / "gpt-agent-bridge.service"
        env_dest = Path(self.dir.name) / "publish" / "bridge.env"
        unit_dest = Path(self.dir.name) / "publish" / "gpt-agent-bridge.service"
        completed = source_call(
            'bridge_render_unit "$3" alice "/home/alice" "/srv/gab" > "$4" && '
            'bridge_verify_unit "$4" && { mkdir -p "$(dirname "$5")"; '
            'cp "$4" "$5"; cp "$4" "$6"; }',
            str(TEMPLATE), str(unit), str(env_dest), str(unit_dest),
            PATH_prefix=str(fake_bin))
        self.assertNotEqual(completed.returncode, 0)
        self.assertTrue(verify_marker.exists())
        self.assertFalse(env_dest.exists())
        self.assertFalse(unit_dest.exists())

    def test_publish_installs_env_and_unit_with_ownership(self):
        me = getpass.getuser()
        stage = self.stage_dir
        (stage / "bridge.env").write_text("BRIDGE_PATH_TOKEN=tok\n",
                                          encoding="utf-8")
        (stage / "gpt-agent-bridge.service").write_text("[Unit]\n", encoding="utf-8")
        env_dest = Path(self.dir.name) / "conf" / "bridge.env"
        unit_dest = Path(self.dir.name) / "conf" / "gpt-agent-bridge.service"
        completed = bash(
            'source "$1"; source "$2"; bridge_publish "$3" "$4" "$5" "$6"',
            str(INSTALLER), str(ALLOWLIST), str(stage), str(env_dest),
            str(unit_dest), me)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(env_dest.read_text(encoding="utf-8"),
                         "BRIDGE_PATH_TOKEN=tok\n")
        self.assertEqual(env_dest.stat().st_mode & 0o777, 0o600)
        self.assertTrue(unit_dest.exists())


class MainStagingLifecycleTests(unittest.TestCase):
    # Exact production main/cleanup; fake host tools and disposable destinations.
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="installer-main-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.repo = self.root / "repo"
        synthetic_package(self.repo)
        (self.repo / "scripts").mkdir()
        (self.repo / "systemd").mkdir()
        (self.repo / "scripts/bridge-env-allowlist.sh").write_bytes(ALLOWLIST.read_bytes())
        (self.repo / "systemd/gpt-agent-bridge.service.template").write_bytes(TEMPLATE.read_bytes())
        self.installer = self.repo / "scripts/install-bridge-system-service.sh"
        # Only the privilege gate and installed unit destination change in this
        # disposable source. No replacement of main, PID validation or cleanup.
        source = INSTALLER.read_text()
        self.assertEqual(source.count('if (( EUID != 0 )); then'), 1)
        source = source.replace('if (( EUID != 0 )); then', 'if false; then')
        destination = 'local unit_dest="/etc/systemd/system/gpt-agent-bridge.service"'
        self.assertEqual(source.count(destination), 1)
        source = source.replace(destination, 'local unit_dest="$FAKE_ROOT/published/gpt-agent-bridge.service"')
        self.installer.write_text(source)
        self.home = self.root / "home"
        self.home.mkdir()
        self.stages = self.root / "stages"
        self.stages.mkdir(mode=0o700)
        self.pid = self.root / "proc/101"
        self.pid.mkdir(parents=True)
        python = self.repo / ".venv/bin/python"
        (self.pid / "cwd").symlink_to(self.repo)
        (self.pid / "exe").symlink_to(python.resolve())
        (self.pid / "cmdline").write_bytes(os.fsencode(python) + b"\0-m\0gpt_agent_bridge\0")
        self.initial_stat = "101 (fixture) S " + "0 " * 18 + "100 0\n"
        (self.pid / "stat").write_text(self.initial_stat)
        write_nul_environ(self.pid / "environ", {
            "BRIDGE_PATH_TOKEN": "synthetic-cleanup-secret",
            "BRIDGE_WORKSPACE": str(self.repo), "PATH": "/usr/bin:/bin",
        })
        self.outside = self.root / "outside"
        self.outside.write_text("outside-sentinel")
        self.bin = self.root / "bin"
        self.bin.mkdir()
        self.command("pgrep", 'printf "101\\n"')
        self.command("ps", 'printf "fixture\\n"')
        self.command("getent", r'''if [[ "$FAKE_SCENARIO" == pre_refusal ]]; then
  { printf '101 (fixture) S '; printf '0 %.0s' {1..18}; printf '200 0\n'; } > "$FAKE_ROOT/proc/101/stat"
fi
printf 'fixture:x:1234:1234::%s:/bin/bash\n' "$FAKE_ROOT/home"''')
        self.command("systemctl", r'''case "$1" in
is-active) [[ "$FAKE_MODE" == active ]] && exit 0; exit 3;;
show) printf '101\n';;
daemon-reload) touch "$FAKE_ROOT/reloaded"; [[ "$FAKE_SCENARIO" != reload_failure ]];;
*) exit 97;;
esac''')
        self.command("systemd-analyze", r'''[[ "$1" == verify ]] || exit 97
stage=$(dirname "$2")
[[ $(stat -c %a "$stage") == 700 && $(stat -c %a "$stage/bridge.env") == 600 ]] || exit 98
grep -q 'synthetic-cleanup-secret' "$stage/bridge.env" || exit 99
touch "$FAKE_ROOT/verified-secret"
case "$FAKE_SCENARIO" in
verify_failure) exit 7;;
post_refusal) { printf '101 (fixture) S '; printf '0 %.0s' {1..18}; printf '200 0\n'; } > "$FAKE_ROOT/proc/101/stat";;
foreign_file) printf foreign > "$stage/foreign";;
replaced_env) mv "$stage/bridge.env" "$stage/original-env"; printf foreign > "$stage/bridge.env";;
symlink_env) mv "$stage/bridge.env" "$stage/original-env"; ln -s "$FAKE_ROOT/outside" "$stage/bridge.env";;
replaced_directory) mv "$stage" "$stage.original"; mkdir -m 700 "$stage"; printf foreign > "$stage/foreign";;
hardlinked_env) ln "$stage/bridge.env" "$stage/foreign";;
signal_HUP) kill -HUP "$PPID";;
signal_INT) kill -INT "$PPID";;
signal_TERM) kill -TERM "$PPID";;
esac
exit 0''')
        # Fake account flags; real byte-copy/modes only after bounding TMP paths.
        self.command("install", r'''exec python3 - "$@" <<'INSTALL_FIXTURE'
import json, os, pathlib, subprocess, sys
root = pathlib.Path(os.environ["FAKE_ROOT"])
args = iter(sys.argv[1:]); safe = []
for arg in args:
    if arg in ("-o", "-g"):
        next(args)
    else:
        safe.append(arg)
for arg in safe:
    if arg.startswith("/"):
        assert pathlib.Path(arg).is_relative_to(root)
with (root / "install-calls").open("a") as log:
    log.write(json.dumps(safe) + "\n")
if (os.environ["FAKE_SCENARIO"] == "publish_failure" and
        safe[-1].endswith("gpt-agent-bridge.service") and "-d" not in safe):
    raise SystemExit(9)
raise SystemExit(subprocess.run(["/usr/bin/install", *safe]).returncode)
INSTALL_FIXTURE''')

    def command(self, name, body):
        path = self.bin / name
        path.write_text('#!/usr/bin/env bash\nset -eu\n' + body + '\n')
        path.chmod(0o755)

    def run_main(self, scenario, mode="inactive"):
        script = r'''export FAKE_ROOT=$2 FAKE_SCENARIO=$3 FAKE_MODE=$4 TMPDIR=$2/stages
source "$1"
bridge_proc_root() { printf '%s' "$FAKE_ROOT/proc"; }
# Instrument calls to the REAL guard; no cleanup stub.
definition=$(declare -f bridge_stage_guard)
eval "${definition/bridge_stage_guard/real_bridge_stage_guard}"
bridge_stage_guard() {
  if [[ "$1" == cleanup ]]; then printf 'cleanup\n' >> "$FAKE_ROOT/cleanup-calls"; fi
  real_bridge_stage_guard "$@"
}
main --user fixture --repo "$2/repo"
'''
        result = bash(script, str(self.installer), str(self.root), scenario, mode,
                      PATH_prefix=str(self.bin))
        self.assertNotIn("unbound variable", result.stderr)
        self.assertNotIn("synthetic-cleanup-secret", result.stdout + result.stderr)
        self.assertEqual((self.root / "cleanup-calls").read_text(), "cleanup\n")
        return result

    def assert_not_published(self):
        self.assertFalse((self.root / "install-calls").exists())
        self.assertFalse((self.root / "reloaded").exists())
        self.assertFalse((self.home / ".config/gpt-agent-bridge/bridge.env").exists())
        self.assertFalse((self.root / "published/gpt-agent-bridge.service").exists())

    def assert_no_stage(self):
        self.assertEqual(list(self.stages.iterdir()), [])

    def test_pre_staging_refusal_cleans_directory_before_main_returns(self):
        result = self.run_main("pre_refusal")
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("before environment staging", result.stderr)
        self.assert_not_published()
        self.assert_no_stage()

    def test_post_verify_fingerprint_refusal_deletes_staged_secret(self):
        result = self.run_main("post_refusal")
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("before publication", result.stderr)
        self.assertTrue((self.root / "verified-secret").exists())
        self.assert_not_published()
        self.assert_no_stage()

    def test_active_mainpid_post_verify_refusal_also_cleans_secret(self):
        result = self.run_main("post_refusal", "active")
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertTrue((self.root / "verified-secret").exists())
        self.assert_not_published()
        self.assert_no_stage()

    def test_unit_verification_failure_cleans_secret_and_never_publishes(self):
        result = self.run_main("verify_failure")
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertTrue((self.root / "verified-secret").exists())
        self.assert_not_published()
        self.assert_no_stage()

    def test_invalid_environment_cleans_precreated_stage_objects(self):
        write_nul_environ(self.pid / "environ", {"PATH": "/bin", "BRIDGE_WORKSPACE": str(self.repo)})
        result = self.run_main("env_failure")
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assert_not_published()
        self.assert_no_stage()

    def test_success_cleans_stage_and_preserves_published_bytes_and_modes(self):
        result = self.run_main("success")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assert_no_stage()
        env = self.home / ".config/gpt-agent-bridge/bridge.env"
        self.assertIn("synthetic-cleanup-secret", env.read_text())
        self.assertEqual(env.stat().st_mode & 0o777, 0o600)
        self.assertEqual(env.parent.stat().st_mode & 0o777, 0o700)
        unit = self.root / "published/gpt-agent-bridge.service"
        self.assertIn(f"ExecStart={self.repo}/.venv/bin/python -m gpt_agent_bridge", unit.read_text())
        self.assertEqual(unit.stat().st_mode & 0o777, 0o644)
        self.assertTrue((self.root / "reloaded").exists())

    def test_hup_int_term_exit_codes_and_single_cleanup_after_secret_staging(self):
        for signal, code in (("HUP", 129), ("INT", 130), ("TERM", 143)):
            with self.subTest(signal=signal):
                (self.root / "cleanup-calls").unlink(missing_ok=True)
                result = self.run_main(f"signal_{signal}")
                self.assertEqual(result.returncode, code, result.stderr)
                self.assertTrue((self.root / "verified-secret").exists())
                self.assert_not_published()
                self.assert_no_stage()

    def test_foreign_file_is_preserved_but_owned_secret_is_removed(self):
        result = self.run_main("foreign_file")
        self.assertEqual(result.returncode, 1)
        self.assert_not_published()
        stage, = self.stages.iterdir()
        self.assertEqual((stage / "foreign").read_text(), "foreign")
        self.assertEqual(sorted(p.name for p in stage.iterdir()), ["foreign"])
        self.assertIn("operator review", result.stderr)

    def test_replaced_env_is_preserved_and_renamed_original_secret_removed(self):
        result = self.run_main("replaced_env")
        self.assertEqual(result.returncode, 1)
        self.assert_not_published()
        stage, = self.stages.iterdir()
        self.assertEqual((stage / "bridge.env").read_text(), "foreign")
        self.assertEqual(sorted(p.name for p in stage.iterdir()), ["bridge.env"])

    def test_symlink_env_does_not_touch_its_external_target(self):
        result = self.run_main("symlink_env")
        self.assertEqual(result.returncode, 1)
        self.assert_not_published()
        stage, = self.stages.iterdir()
        self.assertTrue((stage / "bridge.env").is_symlink())
        self.assertEqual(self.outside.read_text(), "outside-sentinel")
        self.assertEqual(sorted(p.name for p in stage.iterdir()), ["bridge.env"])

    def test_replaced_directory_preserves_foreign_root_and_cleans_held_original(self):
        result = self.run_main("replaced_directory")
        self.assertEqual(result.returncode, 1)
        self.assert_not_published()
        old = next(self.stages.glob("*.original"))
        replacement = next(p for p in self.stages.iterdir() if p != old)
        self.assertEqual(list(old.iterdir()), [])
        self.assertEqual((replacement / "foreign").read_text(), "foreign")
        self.assertEqual(sorted(p.name for p in replacement.iterdir()), ["foreign"])

    def test_hardlinked_secret_is_preserved_for_explicit_operator_review(self):
        result = self.run_main("hardlinked_env")
        self.assertEqual(result.returncode, 1)
        self.assert_not_published()
        stage, = self.stages.iterdir()
        self.assertEqual((stage / "foreign").stat().st_ino, (stage / "bridge.env").stat().st_ino)
        self.assertEqual((stage / "foreign").read_text(), (stage / "bridge.env").read_text())
        self.assertIn("operator review", result.stderr)

    def test_reload_failure_cleans_stage_and_retains_already_published_outputs(self):
        result = self.run_main("reload_failure")
        self.assertEqual(result.returncode, 1)
        self.assertIn("failed after publication", result.stderr)
        self.assert_no_stage()
        self.assertTrue((self.home / ".config/gpt-agent-bridge/bridge.env").exists())
        self.assertTrue((self.root / "published/gpt-agent-bridge.service").exists())

    def test_partial_publication_failure_cleans_stage_without_deleting_installed_env(self):
        result = self.run_main("publish_failure")
        self.assertEqual(result.returncode, 1)
        self.assertIn("outputs may be partial", result.stderr)
        self.assert_no_stage()
        self.assertTrue((self.home / ".config/gpt-agent-bridge/bridge.env").exists())
        self.assertFalse((self.root / "published/gpt-agent-bridge.service").exists())
        self.assertFalse((self.root / "reloaded").exists())


class PortabilityTests(unittest.TestCase):
    DEPLOYMENT_FILES = [INSTALLER, TEMPLATE, ALLOWLIST, TTL]

    def test_deployment_files_exist_and_cutover_is_gone(self):
        for path in self.DEPLOYMENT_FILES:
            self.assertTrue(path.is_file(), path)
        self.assertFalse((ROOT / "scripts" / "bridge-cutover.sh").exists())

    def test_no_machine_paths_users_or_hardcoded_proxy(self):
        for path in self.DEPLOYMENT_FILES:
            text = path.read_text(encoding="utf-8")
            self.assertNotIn("/home/bridge-synthetic-user", text, path)
            self.assertNotIn("bridge-synthetic-user", text, path)
            # Reject any literal user home, including names outside this fixture.
            self.assertNotRegex(
                text, r"(?<![A-Za-z0-9_])/home/[A-Za-z0-9_.-]+", str(path))
            self.assertNotIn("7897", text, path)
            self.assertNotIn("nvm/versions", text, path)

    def test_unit_template_uses_explicit_home_placeholder(self):
        text = TEMPLATE.read_text(encoding="utf-8")
        self.assertIn("@BRIDGE_USER@", text)
        self.assertIn("@BRIDGE_HOME@", text)
        self.assertIn("@BRIDGE_REPO@", text)
        self.assertNotIn("%h", text)

    def test_installer_never_starts_or_enables_and_verifies_before_publish(self):
        text = INSTALLER.read_text(encoding="utf-8")
        self.assertNotIn("systemctl start", text)
        self.assertNotIn("systemctl enable", text)
        self.assertIn("bridge_verify_unit", text)
        self.assertIn("bridge_publish", text)
        self.assertIn('systemd-analyze verify "$unit"', text)
        self.assertIn('bridge_verify_unit "$staged_unit"', text)
        self.assertIn('bridge_publish "$stage_dir" "$env_dest" "$unit_dest" '
                      '"$bridge_user_live"', text)
        self.assertLess(text.index('bridge_verify_unit "$staged_unit"'),
                        text.index('bridge_publish "$stage_dir"'))

    def test_shell_scripts_parse(self):
        for path in (INSTALLER, ALLOWLIST, TTL):
            completed = subprocess.run(["bash", "-n", str(path)],
                                       capture_output=True, text=True)
            self.assertEqual(completed.returncode, 0, path)

    def test_installer_requires_root_for_install_mode(self):
        completed = subprocess.run(
            [str(INSTALLER), "--user", "x", "--repo", "/tmp"],
            capture_output=True, text=True, check=False)
        if os.geteuid() == 0:
            self.skipTest("running as root; sudo gate not exercised")
        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("sudo", completed.stderr)


if __name__ == "__main__":
    unittest.main()
