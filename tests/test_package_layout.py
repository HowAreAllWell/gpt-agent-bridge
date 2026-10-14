"""Installed package and operator-template migration; no sockets or host actions."""
import ast
import importlib.metadata
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from gpt_agent_bridge import server

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "src/gpt_agent_bridge"
MODULES = {"agent_placement", "commit_candidate", "commit_preparation", "evidence_target",
           "file_attachment", "file_observation", "fixed_git", "herdr_backend",
           "project_continuity", "project_text_edit", "read_schema", "search_observation",
           "server", "tool_presentation", "browser_notifications", "work_reports", "workspace_context"}


class PackageLayoutTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="package-bootstrap-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        subprocess.run(["git", "init", "-q", "-b", "main", str(self.root)],
                       env={"PATH": os.defpath, "GIT_CONFIG_NOSYSTEM": "1",
                            "GIT_CONFIG_GLOBAL": os.devnull}, check=True)
        self.env = {"PATH": os.defpath, "LANG": "C.UTF-8", "HOME": str(self.root),
                    "PYTHONDONTWRITEBYTECODE": "1", "BRIDGE_WORKSPACE": str(self.root),
                    "BRIDGE_PATH_TOKEN": "synthetic-package-only-0123456789abcdef",
                    "BRIDGE_WORKSPACE_STORE_PATH": str(self.root / "registry.json")}

    def child(self, code, env=None):
        return subprocess.run([sys.executable, "-B", "-c", code], cwd=self.root,
                              env=self.env if env is None else env, capture_output=True,
                              text=True, timeout=30)

    def test_installed_lightweight_import_from_other_cwd_needs_no_bootstrap(self):
        env = {k: v for k, v in self.env.items() if not k.startswith("BRIDGE_")}
        result = self.child("import sys, gpt_agent_bridge; "
                            "assert 'gpt_agent_bridge.server' not in sys.modules; "
                            "print(gpt_agent_bridge.__file__)", env)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(Path(result.stdout.strip()), PACKAGE / "__init__.py")

    def test_all_modules_packaged_without_bare_imports_or_root_proxies(self):
        self.assertEqual({p.stem for p in PACKAGE.glob("*.py")} - {"__init__", "__main__"}, MODULES)
        for name in MODULES:
            self.assertFalse((ROOT / (name + ".py")).exists())
            for node in ast.walk(ast.parse((PACKAGE / (name + ".py")).read_bytes())):
                if isinstance(node, ast.Import):
                    self.assertFalse(any(alias.name.split(".")[0] in MODULES for alias in node.names))
                elif isinstance(node, ast.ImportFrom) and node.level == 0:
                    self.assertNotIn((node.module or "").split(".")[0], MODULES)
        for first, second in (("commit_candidate", "commit_preparation"),
                              ("commit_preparation", "commit_candidate")):
            result = self.child(f"from gpt_agent_bridge import {first}, {second}")
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_explicit_workspace_preserved_from_unrelated_cwd(self):
        result = self.child("import json; from gpt_agent_bridge import server; "
                            "print(json.dumps(str(server.ROOT)))")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), str(self.root))
        self.assertFalse((self.root / "registry.json").exists())

    def test_missing_relative_and_nonexistent_workspace_fail_before_run(self):
        (self.root / "src").mkdir()
        non_git = self.root / "not-a-worktree"
        non_git.mkdir()
        for workspace in (None, ".", str(self.root / "absent"), str(self.root / "src"), str(non_git)):
            env = dict(self.env)
            if workspace is None:
                del env["BRIDGE_WORKSPACE"]
            else:
                env["BRIDGE_WORKSPACE"] = workspace
            result = subprocess.run([sys.executable, "-B", "-m", "gpt_agent_bridge"],
                                    cwd=self.root, env=env, capture_output=True, text=True, timeout=30)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("BRIDGE_WORKSPACE", result.stderr)
            self.assertFalse((self.root / "registry.json").exists())

    def test_module_and_console_token_guard_fail_before_listener(self):
        env = dict(self.env)
        del env["BRIDGE_PATH_TOKEN"]
        for command in ([sys.executable, "-B", "-m", "gpt_agent_bridge"],
                        [str(Path(sys.executable).parent / "gpt-agent-bridge")]):
            result = subprocess.run(command, cwd=self.root, env=env,
                                    capture_output=True, text=True, timeout=30)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("BRIDGE_PATH_TOKEN is not set", result.stderr)

    def test_main_keeps_loopback_sse_and_runtime_transport_security(self):
        with patch.object(server, "_transport_security_settings", return_value="synthetic-security") as security, \
             patch.object(server.mcp, "run") as run:
            server.main()
        security.assert_called_once_with()
        run.assert_called_once_with(transport="streamable-http", host="127.0.0.1", port=server.PORT,
                                    streamable_http_path=server.MCP_PATH, json_response=False,
                                    transport_security="synthetic-security")

    def test_metadata_direct_pins_match_existing_requirements(self):
        expected = {line.strip() for line in (ROOT / "requirements.txt").read_text().splitlines()
                    if line.strip() and not line.startswith("#")}
        actual = {item.replace(" ", "").lower()
                  for item in importlib.metadata.requires("gpt-agent-bridge")}
        self.assertEqual(actual, expected)

    def test_adopter_accepts_own_install_rejects_other_checkout_or_missing_package(self):
        installer = ROOT / "scripts/install-bridge-system-service.sh"
        command = ["bash", "-c", 'source "$1"; bridge_require_package "$2"', "test", str(installer)]
        success = subprocess.run(command + [str(ROOT)], env=self.env, capture_output=True, text=True)
        self.assertEqual(success.returncode, 0, success.stderr)
        other = self.root / "other"
        (other / "src/gpt_agent_bridge").mkdir(parents=True)
        (other / "src/gpt_agent_bridge/__main__.py").write_text("")
        (other / "pyproject.toml").write_text("")
        (other / ".venv/bin").mkdir(parents=True)
        (other / ".venv/bin/python").symlink_to(sys.executable)
        result = subprocess.run(command + [str(other)], env=self.env, capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("not installed from this checkout", result.stderr)
        (other / "src/gpt_agent_bridge/__main__.py").unlink()
        result = subprocess.run(command + [str(other)], env=self.env, capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("missing Bridge checkout contents", result.stderr)
