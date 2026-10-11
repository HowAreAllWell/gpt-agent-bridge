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


class AdoptPidTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.repo = Path(self.dir.name) / "repo"
        (self.repo / ".venv" / "bin").mkdir(parents=True)
        (self.repo / "server.py").write_text("", encoding="utf-8")
        self.procs: list[subprocess.Popen] = []

    def tearDown(self):
        for proc in self.procs:
            proc.kill()
            proc.wait()

    def spawn_decoy(self) -> subprocess.Popen:
        proc = subprocess.Popen(
            ["bash", "-c",
             f'cd "{self.repo}" && exec -a "gpt-agent-bridge server.py" sleep 30'])
        self.procs.append(proc)
        return proc

    @staticmethod
    def fake_systemctl_bin(mode: str) -> str:
        bin_dir = Path(tempfile.mkdtemp()) / "bin"
        bin_dir.mkdir(parents=True)
        fake = bin_dir / "systemctl"
        if mode == "active":
            fake.write_text(
                '#!/usr/bin/env bash\n'
                'if [[ "$1" == "is-active" ]]; then [[ "${2:-}" == "--quiet" ]] || echo active; exit 0; fi\n'
                'if [[ "$1" == "show" ]]; then echo 999999; exit 0; fi\n'
                "exit 0\n")
        else:
            fake.write_text(
                '#!/usr/bin/env bash\n'
                'if [[ "$1" == "is-active" ]]; then [[ "${2:-}" == "--quiet" ]] || echo inactive; exit 3; fi\n'
                "exit 3\n")
        fake.chmod(0o755)
        return str(bin_dir) + ":"

    def test_zero_candidates_fails(self):
        completed = source_call(
            'bridge_adopt_pid "$3" >/dev/null', str(self.repo),
            PATH_prefix=self.fake_systemctl_bin("inactive"))
        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("no running Bridge process", completed.stderr)

    def test_exactly_one_candidate_is_returned(self):
        self.spawn_decoy()
        completed = source_call(
            'bridge_adopt_pid "$3"', str(self.repo),
            PATH_prefix=self.fake_systemctl_bin("inactive"))
        self.assertEqual(completed.returncode, 0, completed.stderr)
        pid = completed.stdout.strip()
        self.assertTrue(pid.isdigit())
        self.assertTrue(Path(f"/proc/{pid}/cwd").resolve()
                        .is_relative_to(self.repo.resolve()))

    def test_two_candidates_fail_exactly_one_required(self):
        self.spawn_decoy()
        self.spawn_decoy()
        completed = source_call(
            'bridge_adopt_pid "$3" >/dev/null', str(self.repo),
            PATH_prefix=self.fake_systemctl_bin("inactive"))
        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("exactly one", completed.stderr)

    def test_active_service_mainpid_must_revalidate_repo(self):
        completed = source_call(
            'bridge_adopt_pid "$3" >/dev/null', str(self.repo),
            PATH_prefix=self.fake_systemctl_bin("active"))
        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("refusing service adoption", completed.stderr)


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
                [sys.executable, "-c", "import json, herdr_backend as h; "
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
        self.assertIn(f"ExecStart={interpreter} ", text)
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
