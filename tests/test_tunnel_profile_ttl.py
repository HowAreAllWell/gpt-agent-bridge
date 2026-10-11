import os
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "stage-tunnel-mcp-ttl.sh"

PROFILE_TEMPLATE = """config_version: 1
control_plane:
  base_url: "https://api.openai.com"
  organization_id: "org-TEST"
  tunnel_id: "tunnel_TEST"
  api_key: "env:CONTROL_PLANE_API_KEY"
health:
  listen_addr: "127.0.0.1:8080"
admin_ui:
  open_browser: false
log:
  level: info
  format: json
mcp:
  server_urls:
    - channel: main
      url: "http://127.0.0.1:8765/mcp/testtoken"
"""


class TunnelProfileTtlTests(unittest.TestCase):
    """EVO-028: the deployed Secure MCP Tunnel profile must carry an explicit
    mcp.connection_max_ttl so long semantic joins are not killed by the
    tunnel-client 10m default TTL ("MCP connection TTL reached; stopping
    response forwarding")."""
    def _write_profile(self, directory: Path, body: str = PROFILE_TEMPLATE) -> Path:
        profile = directory / "secure-bridge.yaml"
        profile.write_text(body, encoding="utf-8")
        os.chmod(profile, 0o600)
        return profile

    def _run_script(self, *args: str, env_extra: dict | None = None) -> subprocess.CompletedProcess:
        env = dict(os.environ)
        env.pop("BRIDGE_TUNNEL_MCP_CONNECTION_MAX_TTL", None)
        env.pop("BRIDGE_TUNNEL_PROFILE", None)
        if env_extra:
            env.update(env_extra)
        return subprocess.run(
            [str(SCRIPT), *args],
            capture_output=True,
            text=True,
            env=env,
            check=False,
        )

    def test_executable_entry_point_defaults_to_project_60m(self):
        with tempfile.TemporaryDirectory() as temp:
            profile = self._write_profile(Path(temp))
            result = self._run_script("--profile", str(profile))
            after = profile.read_text(encoding="utf-8")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("staged", result.stdout)
        self.assertIn("connection_max_ttl: 60m", after)

    def test_upsert_preserves_rest_of_profile_and_file_mode(self):
        with tempfile.TemporaryDirectory() as temp:
            profile = self._write_profile(Path(temp))
            before = profile.read_text(encoding="utf-8")
            result = self._run_script("--profile", str(profile), "--ttl", "90m")
            after = profile.read_text(encoding="utf-8")
            mode_ok = stat.S_IMODE(profile.stat().st_mode) & 0o077 == 0
            backups = list(Path(temp).glob("secure-bridge.yaml.bak.*"))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            after,
            before.replace("mcp:\n", "mcp:\n  connection_max_ttl: 90m\n", 1),
        )
        self.assertTrue(mode_ok)
        self.assertEqual(len(backups), 1)

    def test_restaging_same_value_is_idempotent_no_backup(self):
        with tempfile.TemporaryDirectory() as temp:
            profile = self._write_profile(Path(temp))
            first = self._run_script("--profile", str(profile), "--ttl", "60m")
            staged = profile.read_text(encoding="utf-8")
            second = self._run_script("--profile", str(profile), "--ttl", "60m")
            again = profile.read_text(encoding="utf-8")
            backups = list(Path(temp).glob("*.bak.*"))
        self.assertEqual(first.returncode, 0)
        self.assertEqual(second.returncode, 0)
        self.assertIn("already-staged", second.stdout)
        self.assertEqual(staged, again)
        self.assertEqual(len(backups), 1)

    def test_existing_different_value_is_replaced_with_indent_preserved(self):
        body = PROFILE_TEMPLATE.replace(
            "mcp:\n", "mcp:\n  connection_max_ttl: 10m\n", 1
        )
        with tempfile.TemporaryDirectory() as temp:
            profile = self._write_profile(Path(temp), body)
            result = self._run_script("--profile", str(profile), "--ttl", "60m")
            after = profile.read_text(encoding="utf-8")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("  connection_max_ttl: 60m\n", after)
        self.assertNotIn("connection_max_ttl: 10m", after)
        # Exactly one TTL key survives inside the mcp block.
        self.assertEqual(after.count("connection_max_ttl:"), 1)

    def test_invalid_durations_fail_closed_and_leave_file_untouched(self):
        for bad in ("0m", "-5m", "abc", "60", "1h30m", ""):
            with tempfile.TemporaryDirectory() as temp:
                profile = self._write_profile(Path(temp))
                before = profile.read_text(encoding="utf-8")
                result = self._run_script("--profile", str(profile), "--ttl", bad)
                after = profile.read_text(encoding="utf-8")
                self.assertEqual(result.returncode, 1, f"ttl={bad!r}: {result.stderr}")
                self.assertIn("invalid TTL", result.stderr)
                self.assertEqual(before, after)
                self.assertEqual(list(Path(temp).glob("*.bak.*")), [])

    def test_missing_mcp_section_fails_closed(self):
        body = PROFILE_TEMPLATE.replace("mcp:\n  server_urls:", "notmcp:\n  server_urls:")
        with tempfile.TemporaryDirectory() as temp:
            profile = self._write_profile(Path(temp), body)
            result = self._run_script("--profile", str(profile))
            after = profile.read_text(encoding="utf-8")
        self.assertEqual(result.returncode, 1)
        self.assertIn("exactly one top-level 'mcp:'", result.stderr)
        self.assertNotIn("connection_max_ttl", after)

    def test_ambiguous_duplicate_ttl_keys_fail_closed(self):
        body = PROFILE_TEMPLATE.replace(
            "mcp:\n",
            "mcp:\n  connection_max_ttl: 10m\n  connection_max_ttl: 15m\n",
            1,
        )
        with tempfile.TemporaryDirectory() as temp:
            profile = self._write_profile(Path(temp), body)
            result = self._run_script("--profile", str(profile))
            after = profile.read_text(encoding="utf-8")
        self.assertEqual(result.returncode, 1)
        self.assertIn("multiple connection_max_ttl", result.stderr)
        self.assertIn("connection_max_ttl: 10m", after)

    def test_missing_profile_fails_closed(self):
        with tempfile.TemporaryDirectory() as temp:
            missing = Path(temp) / "absent.yaml"
            result = self._run_script("--profile", str(missing))
        self.assertEqual(result.returncode, 1)
        self.assertIn("missing or not a regular file", result.stderr)

    def test_ttl_environment_variable_overrides_project_default(self):
        with tempfile.TemporaryDirectory() as temp:
            profile = self._write_profile(Path(temp))
            result = self._run_script(
                "--profile", str(profile),
                env_extra={"BRIDGE_TUNNEL_MCP_CONNECTION_MAX_TTL": "45m"},
            )
            after = profile.read_text(encoding="utf-8")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("connection_max_ttl: 45m", after)

    def test_upsert_derives_child_indent_from_sibling_keys(self):
        body = PROFILE_TEMPLATE.replace(
            "mcp:\n", "mcp:\n    server_urls:\n        - channel: main\n", 1
        )
        with tempfile.TemporaryDirectory() as temp:
            profile = self._write_profile(Path(temp), body)
            result = self._run_script("--profile", str(profile), "--ttl", "60m")
            after = profile.read_text(encoding="utf-8")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("    connection_max_ttl: 60m\n", after)
        # Rest of the profile is untouched except the inserted line.
        self.assertIn("mcp:\n    connection_max_ttl: 60m\n    server_urls:\n        - channel: main\n", after)

    def test_upsert_falls_back_to_two_spaces_for_empty_mcp_block(self):
        head = PROFILE_TEMPLATE.split("mcp:\n", 1)[0] + "mcp:\n"
        with tempfile.TemporaryDirectory() as temp:
            profile = self._write_profile(Path(temp), head)
            result = self._run_script("--profile", str(profile), "--ttl", "60m")
            after = profile.read_text(encoding="utf-8")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("  connection_max_ttl: 60m\n", after)

    def test_replace_preserves_existing_key_indent(self):
        body = PROFILE_TEMPLATE.replace(
            "mcp:\n", "mcp:\n    connection_max_ttl: 10m\n", 1
        )
        with tempfile.TemporaryDirectory() as temp:
            profile = self._write_profile(Path(temp), body)
            result = self._run_script("--profile", str(profile), "--ttl", "60m")
            after = profile.read_text(encoding="utf-8")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("    connection_max_ttl: 60m\n", after)
        self.assertNotIn("connection_max_ttl: 10m", after)
        self.assertEqual(after.count("connection_max_ttl:"), 1)

    def test_upsert_child_indent_skips_deep_comment_before_sibling_key(self):
        body = PROFILE_TEMPLATE.replace(
            "mcp:\n", "mcp:\n    # deep comment\n  server_urls:\n", 1
        )
        with tempfile.TemporaryDirectory() as temp:
            profile = self._write_profile(Path(temp), body)
            result = self._run_script("--profile", str(profile), "--ttl", "60m")
            after = profile.read_text(encoding="utf-8")
        self.assertEqual(result.returncode, 0, result.stderr)
        # The comment's deeper indent must not be chosen; the real sibling
        # key's indent (2 spaces) wins.
        self.assertIn("  connection_max_ttl: 60m\n", after)
        self.assertNotIn("    connection_max_ttl: 60m\n", after)


if __name__ == "__main__":
    unittest.main()
