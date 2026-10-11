"""Process-env migration; restricted encoder checks are NOT a systemd oracle."""
import json
import os
from pathlib import Path
import re
import subprocess
import socket
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
HELPER = ROOT / "scripts" / "bridge-env-allowlist.sh"
MIGRATED_KEYS = (
    "BRIDGE_PATH_TOKEN", "BRIDGE_WORKSPACE", "PATH", "BRIDGE_PORT",
    "BRIDGE_AWAIT_LEASE_SECONDS", "BRIDGE_WORKSPACE_REGISTRY", "BRIDGE_HERDR_BIN",
    "BRIDGE_HERDR_ENABLED", "BRIDGE_MCP_AUTH_SECRET", "BRIDGE_MCP_AUTH_PREVIOUS_SECRET",
    "BRIDGE_WORKSPACE_STORE_PATH", "XDG_STATE_HOME", "HTTP_PROXY", "HTTPS_PROXY",
    "http_proxy", "https_proxy", "NO_PROXY", "no_proxy",
)
SINGLE_LINE_VALUES = (
    "", "plain", " leading and trailing ", "'single' and \"double\"",
    "\\path\\trailing\\", "$HOME ${NAME} $(must-not-execute)",
    "`must-not-execute`", '{"review":"/srv/审查 = space"}',
    "中文 café 😀", "#literal;=value", "line\\nnot-a-newline",
)


def staged_values(path: Path) -> dict[str, str]:
    """Reference decoder for OUR double-quoted subset, not systemd or Bash.

    In particular, dollar/backtick text is literal and must never be executed.
    The optional native-parser tests below independently check this subset.
    """
    values = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        match = re.fullmatch(r'([A-Za-z_][A-Za-z_0-9]*)="(.*)"', line)
        if match is None:
            raise AssertionError(f"not a restricted encoded assignment: {line!r}")
        key, encoded = match.groups()
        if key in values:
            raise AssertionError(f"duplicate encoded key: {key}")
        decoded, index = [], 0
        while index < len(encoded):
            char = encoded[index]
            if char == "\\":
                index += 1
                if index == len(encoded) or encoded[index] not in '\\"':
                    raise AssertionError("escape outside the supported encoder subset")
                char = encoded[index]
            elif char == '"':
                raise AssertionError("unescaped quote")
            decoded.append(char)
            index += 1
        values[key] = "".join(decoded)
    return values


# Private systemd ABI: deliberately version-bounded, optional, and isolated in
# a child process. v249 src/basic/env-file.h declares load_env_file(FILE*,
# const char*, char***); strv_free owns the returned allocation. No service or
# manager is contacted. Do not guess this ABI for other systemd versions.
SYSTEMD_249_LIBRARY = next((path for path in (
    Path("/usr/lib/systemd/libsystemd-shared-249.so"),
    Path("/lib/systemd/libsystemd-shared-249.so"),
) if path.is_file()), None)
SYSTEMD_249_SKIP = "optional systemd 249 native EnvironmentFile parser unavailable"


def systemd249_values(path: Path) -> dict[str, str]:
    if SYSTEMD_249_LIBRARY is None:
        raise unittest.SkipTest(SYSTEMD_249_SKIP)
    program = '''
import ctypes, json, os, sys
library = ctypes.CDLL(sys.argv[1])
strings = ctypes.POINTER(ctypes.c_char_p)
library.load_env_file.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.POINTER(strings)]
library.load_env_file.restype = ctypes.c_int
library.strv_free.argtypes = [strings]
library.strv_free.restype = ctypes.c_void_p
result = strings()
status = library.load_env_file(None, os.fsencode(sys.argv[2]), ctypes.byref(result))
if status < 0:
    raise RuntimeError("systemd environment parser error: " + str(status))
try:
    values, index = {}, 0
    while result and result[index] is not None:
        key, value = result[index].decode("utf-8").split("=", 1)
        values[key] = value
        index += 1
    print(json.dumps(values, ensure_ascii=False))
finally:
    library.strv_free(result)
'''
    completed = subprocess.run(
        [sys.executable, "-B", "-c", program, str(SYSTEMD_249_LIBRARY), str(path)],
        capture_output=True, text=True, check=True, timeout=10,
    )
    return json.loads(completed.stdout)


class InstallEnvAllowlistTests(unittest.TestCase):
    def _run_helper(self, process_env: bytes, call="bridge_env_append_allowlist",
                    decoder=staged_values, setup=""):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            process_path = directory / "process.environ"
            output_path = directory / "out.env"
            process_path.write_bytes(process_env)
            output_path.write_text('BASE="1"\n', encoding="utf-8")
            completed = subprocess.run(
                ["bash", "-c", f'source "$1"; {setup}{call} "$2" "$3"',
                 "test-helper", str(HELPER), str(process_path), str(output_path)],
                capture_output=True, text=True,
            )
            self.assertEqual(completed.stdout, "")
            output = output_path.read_text(encoding="utf-8")
            values = decoder(output_path) if completed.returncode == 0 else {}
            return completed, output, values

    def test_current_values_preserved_without_printing_secrets(self):
        expected = {
            "BRIDGE_PORT": "9876",
            "BRIDGE_AWAIT_LEASE_SECONDS": "120",
            "BRIDGE_WORKSPACE_REGISTRY": '{"review":"/srv/review"}',
            "BRIDGE_MCP_AUTH_SECRET": "Bearer secret = 'quoted' \\",
            "BRIDGE_MCP_AUTH_PREVIOUS_SECRET": 'previous "secret" $literal',
            "BRIDGE_HERDR_BIN": "/srv/custom herdr/bin/herdr",
            "BRIDGE_HERDR_ENABLED": " FaLsE ",
        }
        process_env = b"".join(f"{k}={v}\0".encode() for k, v in expected.items())
        completed, output, values = self._run_helper(process_env + b"UNAPPROVED=discarded\0")
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(completed.stderr, "")
        for key, value in expected.items():
            self.assertEqual(values[key], value)
            self.assertEqual(output.count(key + "="), 1)
        self.assertNotIn("UNAPPROVED", values)

    def test_explicit_encoder_preserves_supported_single_line_values(self):
        for value in SINGLE_LINE_VALUES:
            with self.subTest(value=value):
                completed, output, values = self._run_helper(
                    f"BRIDGE_MCP_AUTH_SECRET={value}\0".encode())
                self.assertEqual(completed.returncode, 0, completed.stderr)
                self.assertEqual(values["BRIDGE_MCP_AUTH_SECRET"], value)
                self.assertEqual(len(output.splitlines()), 2)

    @unittest.skipUnless(SYSTEMD_249_LIBRARY, SYSTEMD_249_SKIP)
    def test_systemd_249_native_parser_preserves_encoded_values(self):
        for value in SINGLE_LINE_VALUES:
            with self.subTest(value=value):
                completed, _, values = self._run_helper(
                    f"BRIDGE_MCP_AUTH_SECRET={value}\0".encode(), decoder=systemd249_values)
                self.assertEqual(completed.returncode, 0, completed.stderr)
                self.assertEqual(values, {"BASE": "1", "BRIDGE_MCP_AUTH_SECRET": value})

    def test_retired_values_are_not_migrated(self):
        retired = ("BRIDGE_DEFAULT_MODEL", "AGENT_TIMEOUT_SECONDS",
                   "AGENT_WAIT_TIMEOUT_SECONDS", "AGENT_WAIT_MAX_TIMEOUT_SECONDS",
                   "BRIDGE_ENABLE_RESULT_FIXTURE")
        completed, output, _ = self._run_helper(
            b"".join(f"{key}=old\0".encode() for key in retired))
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(output, 'BASE="1"\n')

    def test_absent_and_explicit_empty_values_remain_distinct(self):
        completed, output, _ = self._run_helper(b"")
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(output, 'BASE="1"\n')
        completed, _, values = self._run_helper(
            b"BRIDGE_HERDR_ENABLED=\0BRIDGE_HERDR_BIN=\0BRIDGE_MCP_AUTH_SECRET=\0")
        self.assertEqual(completed.returncode, 0, completed.stderr)
        for key in ("BRIDGE_HERDR_ENABLED", "BRIDGE_HERDR_BIN", "BRIDGE_MCP_AUTH_SECRET"):
            self.assertEqual(values[key], "")

    def test_every_compared_key_rejects_duplicates_before_emission(self):
        for key in MIGRATED_KEYS:
            for first in ("", "same"):
                with self.subTest(key=key, first=first):
                    completed, output, _ = self._run_helper(
                        f"{key}={first}\0{key}=same\0".encode())
                    self.assertNotEqual(completed.returncode, 0)
                    self.assertIn("ambiguous runtime configuration", completed.stderr)
                    self.assertEqual(output, 'BASE="1"\n')

    def test_every_compared_key_rejects_controls_without_disclosing_value(self):
        controls = ("\n", "\r", "\t", "\x01", "\x1b", "\x7f", "\x85", "\u2028", "\u2029")
        for key in MIGRATED_KEYS:
            for control in controls:
                with self.subTest(key=key, control=repr(control)):
                    completed, output, _ = self._run_helper(
                        f"{key}=private{control}value\0".encode())
                    self.assertNotEqual(completed.returncode, 0)
                    self.assertIn(key, completed.stderr)
                    self.assertNotIn("private", completed.stderr)
                    self.assertEqual(output, 'BASE="1"\n')

    def test_invalid_utf8_and_malformed_approved_entry_fail_closed(self):
        for raw in (b"BRIDGE_HERDR_BIN=bad\xff\0", b"PATH\0"):
            with self.subTest(raw=raw):
                completed, output, _ = self._run_helper(raw)
                self.assertNotEqual(completed.returncode, 0)
                self.assertEqual(output, 'BASE="1"\n')
                self.assertNotIn("bad", completed.stderr)

    def test_unicode_noncharacters_and_bom_are_refused_before_emission(self):
        # iconv alone accepts these; systemd's UTF-8 validator rejects the
        # noncharacters. Also exclude BOM for an explicit portable subset.
        codepoints = [*range(0xFDD0, 0xFDF0), 0xFEFF,
                      *(plane * 0x10000 + suffix for plane in range(17)
                        for suffix in (0xFFFE, 0xFFFF))]
        for point in codepoints:
            with self.subTest(point=hex(point)):
                completed, output, _ = self._run_helper(
                    f"BRIDGE_HERDR_BIN=private{chr(point)}value\0".encode())
                self.assertNotEqual(completed.returncode, 0)
                self.assertNotIn("private", completed.stderr)
                self.assertEqual(output, 'BASE="1"\n')

    def test_unavailable_utf8_validator_fails_closed(self):
        completed, output, _ = self._run_helper(
            b"BRIDGE_HERDR_BIN=herdr\0", setup="PATH=/nonexistent-validator-bin; ")
        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("unsupported runtime environment value", completed.stderr)
        self.assertEqual(output, 'BASE="1"\n')

    def test_unterminated_environment_fails_closed(self):
        for raw in (b"BRIDGE_HERDR_ENABLED=false", b"PATH=/bin\0IGNORED=tail"):
            with self.subTest(raw=raw):
                completed, output, _ = self._run_helper(raw)
                self.assertNotEqual(completed.returncode, 0)
                self.assertIn("not NUL-terminated", completed.stderr)
                self.assertEqual(output, 'BASE="1"\n')

    def test_store_overrides_have_one_separate_source(self):
        raw = (b"BRIDGE_MANAGED_STORE_PATH=/live/managed.json\0"
               b"BRIDGE_WORKSPACE_STORE_PATH=/live/workspaces.json\0"
               b"XDG_STATE_HOME=/live/state\0")
        completed, output, _ = self._run_helper(raw)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(output, 'BASE="1"\n')
        completed, output, values = self._run_helper(raw, "bridge_append_live_store_overrides")
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertNotIn("BRIDGE_MANAGED_STORE_PATH", values)
        self.assertEqual(values["BRIDGE_WORKSPACE_STORE_PATH"], "/live/workspaces.json")
        self.assertEqual(values["XDG_STATE_HOME"], "/live/state")
        self.assertEqual(output.count("BRIDGE_WORKSPACE_STORE_PATH="), 1)
        self.assertEqual(output.count("XDG_STATE_HOME="), 1)

    def test_store_emitter_preserves_spaces_specials_and_empty(self):
        for value in SINGLE_LINE_VALUES:
            with self.subTest(value=value):
                completed, _, values = self._run_helper(
                    f"XDG_STATE_HOME={value}\0".encode(), "bridge_append_live_store_overrides")
                self.assertEqual(completed.returncode, 0, completed.stderr)
                self.assertEqual(values["XDG_STATE_HOME"], value)

    @unittest.skipUnless(hasattr(socket, "AF_UNIX"), "Unix-domain socket fixture unavailable")
    def test_readable_socket_open_failure_cannot_report_success(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "env.sock"
            output = Path(temp) / "staged.env"
            output.write_text('BASE="1"\n', encoding="utf-8")
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
                sock.bind(str(path))
                self.assertTrue(os.access(path, os.R_OK))
                for options in ("set +e +u", "set -euo pipefail"):
                    for call in (
                        'bridge_env_load "$2" data',
                        'bridge_env_append_allowlist "$2" "$3"',
                        'bridge_append_live_store_overrides "$2" "$3"',
                    ):
                        with self.subTest(options=options, call=call):
                            command = (
                                'source "$1"; ' + options + '; declare -A data=(); '
                                'if ' + call + '; then printf "function_rc=0\\n"; '
                                'else printf "function_rc=%s\\n" "$?"; fi'
                            )
                            completed = subprocess.run(
                                ["bash", "-c", command, "socket-input", str(HELPER),
                                 str(path), str(output)],
                                capture_output=True, text=True,
                            )
                            self.assertEqual(completed.returncode, 0, completed.stderr)
                            self.assertEqual(completed.stdout, "function_rc=1\n")
                            self.assertIn("cannot open the current Bridge environment",
                                          completed.stderr)
                            self.assertEqual(output.read_text(encoding="utf-8"),
                                             'BASE="1"\n')

    def test_missing_process_environment_fails_closed(self):
        completed = subprocess.run(
            ["bash", "-c", 'source "$1"; bridge_env_append_allowlist "$2" /dev/null',
             "test-helper", str(HELPER), str(ROOT / "nonexistent-process-environ")],
            capture_output=True, text=True,
        )
        self.assertNotEqual(completed.returncode, 0)
        self.assertEqual(completed.stdout, "")
        self.assertIn("cannot read", completed.stderr)
