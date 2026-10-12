"""Stdlib-only fixtures: no real systemctl, WSL, MCP server or credentials."""
import argparse
import asyncio
import contextlib
import hashlib
import importlib.util
import io
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import tempfile
import types
import unittest
import venv
from pathlib import Path
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/install-bridge-autostart.py"
spec = importlib.util.spec_from_file_location("autostart", SCRIPT)
app = importlib.util.module_from_spec(spec)
spec.loader.exec_module(app)


class InputTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)

    def test_path_injection_and_windows_mount_refused(self):
        for value in ("relative", "/mnt/c/code", "/tmp/x;id", "/tmp/x\nUser=root",
                      "/tmp/a b", "/tmp/$HOME", "/tmp/%h", "/tmp/../etc"):
            with self.subTest(value=value), self.assertRaises(app.Refusal):
                app.path(value)

    def test_unknown_or_root_user_refused(self):
        for name in ("root", "other\nUser=root", "--bad"):
            with self.assertRaises(app.Refusal):
                app.account(name)
        with patch.object(app.pwd, "getpwnam", side_effect=KeyError), self.assertRaises(app.Refusal):
            app.account("missing")

    def test_plan_is_read_only_and_generates_no_token(self):
        repo = self.base / "repo"
        (repo / ".venv/bin").mkdir(parents=True)
        (repo / ".git").mkdir()
        (repo / "pyproject.toml").write_text("")
        (repo / "src/gpt_agent_bridge").mkdir(parents=True)
        (repo / "src/gpt_agent_bridge/__init__.py").write_text("")
        (repo / "src/gpt_agent_bridge/__main__.py").write_text("")
        (repo / ".venv/bin/python").write_text("")
        (repo / ".venv/bin/python").chmod(0o700)
        herdr = self.base / "herdr"
        herdr.write_text(""); herdr.chmod(0o700)
        owner = types.SimpleNamespace(pw_name="operator", pw_uid=os.getuid(),
                                      pw_gid=os.getgid(), pw_dir=str(self.base))
        before = sorted(str(p) for p in self.base.rglob("*"))
        with patch.object(app, "account", return_value=owner), patch.object(app, "command") as cmd, \
                patch.object(app, "user_command", side_effect=[str(repo) + "\nfalse", str(repo) + "\nfalse", ""]) as verify, \
                patch.object(app.secrets, "token_urlsafe") as token, contextlib.redirect_stdout(io.StringIO()) as out:
            rc = app.main(["plan", "--user", "operator", "--repo", str(repo),
                           "--workspace", str(repo), "--herdr-bin", str(herdr),
                           "--token-file", str(self.base / "not-read")])
        self.assertEqual(rc, 0)
        cmd.assert_not_called(); token.assert_not_called()
        self.assertEqual(verify.call_count, 3)
        self.assertIn("-I", verify.call_args.args[0]); self.assertIn("-B", verify.call_args.args[0])
        self.assertEqual(before, sorted(str(p) for p in self.base.rglob("*")))
        self.assertEqual(json.loads(out.getvalue())["token"], "not_read_or_generated")
        with patch.object(app, "account", return_value=owner), \
                patch.object(app, "user_command", side_effect=[str(repo) + "\nfalse", str(repo) + "\nfalse", ""]):
            plan = app.make_plan(argparse.Namespace(user="operator", repo=str(repo),
                workspace=str(repo), herdr_bin=str(herdr), port=8765))
        self.assertEqual(plan["entrypoint"], "module")

    def test_legacy_only_entrypoint_refused(self):
        repo = self.base / "repo"; repo.mkdir()
        (repo / "server.py").write_text("raise AssertionError('must not execute')")
        owner = types.SimpleNamespace(pw_uid=os.getuid())
        with self.assertRaises(app.Refusal):
            app.package_origin(repo, owner)

    def test_user_verification_drops_root_credentials_and_ignores_environment(self):
        owner = types.SimpleNamespace(pw_uid=12345, pw_gid=23456, pw_dir="/synthetic/home")
        with patch.object(app.os, "geteuid", return_value=0), \
                patch.object(app.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, "", "")) as run:
            app.user_command(["/synthetic/venv/python", "-I", "-B"], owner)
        kwargs = run.call_args.kwargs
        self.assertEqual((kwargs["user"], kwargs["group"], kwargs["extra_groups"]), (12345, 23456, []))
        self.assertEqual(kwargs["cwd"], "/")
        self.assertEqual(kwargs["env"]["GIT_CONFIG_GLOBAL"], "/dev/null")
        self.assertNotIn("BRIDGE_PATH_TOKEN", kwargs["env"])
        self.assertNotIn("PYTHONPATH", kwargs["env"])
        with patch.object(app.os, "geteuid", return_value=54321), \
                patch.object(app.subprocess, "run") as run, self.assertRaises(app.Refusal):
            app.user_command(["/synthetic/python"], owner)
        run.assert_not_called()

    def test_privileged_installer_requires_private_owned_regular_copy(self):
        self.base.chmod(0o700)
        source = self.base / "installer.py"; source.write_text("synthetic reviewed bytes")
        source.chmod(0o700)
        with patch.object(app, "ROOT_UID", os.getuid()), patch.object(app, "__file__", str(source)):
            self.assertEqual(app.trusted_installer(), b"synthetic reviewed bytes")
            source.chmod(0o755)
            with self.assertRaises(app.Refusal): app.trusted_installer()
            source.chmod(0o700); self.base.chmod(0o755)
            with self.assertRaises(app.Refusal): app.trusted_installer()

    def test_private_read_rejects_modes_symlinks_hardlinks_and_fifo(self):
        self.base.chmod(0o700)
        secret = self.base / "secret"
        secret.write_text("synthetic"); secret.chmod(0o600)
        self.assertEqual(app.protected_read(secret, os.getuid(), 0o600), b"synthetic")
        for mode in (0o644, 0o400, 0o666):
            secret.chmod(mode)
            with self.assertRaises(app.Refusal):
                app.protected_read(secret, os.getuid(), 0o600)
        secret.chmod(0o600)
        with self.assertRaises(app.Refusal):
            app.protected_read(secret, os.getuid() + 1, 0o600)
        link = self.base / "link"; link.symlink_to(secret)
        with self.assertRaises(app.Refusal):
            app.protected_read(link, os.getuid(), 0o600)
        hard = self.base / "hard"; os.link(secret, hard)
        with self.assertRaises(app.Refusal):
            app.protected_read(secret, os.getuid(), 0o600)
        hard.unlink()
        fifo = self.base / "fifo"; os.mkfifo(fifo, 0o600)
        with self.assertRaises(app.Refusal):
            app.protected_read(fifo, os.getuid(), 0o600)
        self.base.chmod(0o755)
        with self.assertRaises(app.Refusal):
            app.protected_read(secret, os.getuid(), 0o600)

    def test_host_gates_before_mutation(self):
        with patch.object(app.sys, "platform", "win32"), self.assertRaises(app.Refusal):
            app.host(root=True)
        with patch.object(app.Path, "is_dir", return_value=False), self.assertRaises(app.Refusal):
            app.host()
        with patch.object(app.Path, "is_dir", return_value=True), \
                patch.object(app.Path, "read_text", return_value="systemd\n"), \
                patch.object(app.Path, "is_file", return_value=False), self.assertRaises(app.Refusal):
            app.host()

    def test_system_parent_requires_root_nonwritable_no_symlink(self):
        with patch.object(app, "ROOT_UID", os.getuid() + 1), self.assertRaises(app.Refusal):
            app.system_parent(self.base)
        self.base.chmod(0o777)
        with patch.object(app, "ROOT_UID", os.getuid()), self.assertRaises(app.Refusal):
            app.system_parent(self.base)
        link = self.base / "linked"; link.symlink_to(self.base)
        with self.assertRaises(app.Refusal):
            app.system_parent(link)

    def test_port_conflict_refuses_without_stopping_process(self):
        sock = Mock(); sock.__enter__ = Mock(return_value=sock); sock.__exit__ = Mock(return_value=False)
        sock.bind.side_effect = OSError("occupied")
        with patch.object(app.socket, "socket", return_value=sock), self.assertRaises(app.Refusal):
            app.free_port(8765)

    def test_subprocess_failure_does_not_echo_output(self):
        result = subprocess.CompletedProcess([], 1, "synthetic-secret-url", "synthetic-key")
        with patch.object(app.subprocess, "run", return_value=result) as run, self.assertRaises(app.Refusal) as exc:
            app.command(["/usr/bin/systemctl", "start", app.UNIT_NAME])
        self.assertNotIn("synthetic", str(exc.exception))
        self.assertEqual(run.call_args.kwargs["env"], {"PATH": "/usr/bin:/bin", "LANG": "C"})


class PackageValidationTests(unittest.TestCase):
    """Actual Git/venv metadata; poisoned package bodies must never be imported."""
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.repo = self.base / "repo"; self.repo.mkdir()
        self.env = {"PATH": "/usr/bin:/bin", "HOME": str(self.base), "GIT_CONFIG_NOSYSTEM": "1",
                    "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_OPTIONAL_LOCKS": "0"}
        subprocess.run(["/usr/bin/git", "init", "-q", str(self.repo)], env=self.env, check=True)
        package = self.repo / "src/gpt_agent_bridge"; package.mkdir(parents=True)
        (package / "__init__.py").write_text("raise AssertionError('package must not be imported')")
        (package / "__main__.py").write_text("raise AssertionError('entrypoint must not run')")
        (package / "server.py").write_text("raise AssertionError('server must not be imported')")
        (self.repo / "pyproject.toml").write_text("[project]\nname='synthetic'\n")
        venv.EnvBuilder(with_pip=False, symlinks=True).create(self.repo / ".venv")
        self.site = next((self.repo / ".venv/lib").glob("python*/site-packages"))
        (self.site / "fixture.pth").write_text(str(package.parent) + "\n")
        self.herdr = self.base / "herdr"; self.herdr.write_text("synthetic; never executed")
        self.herdr.chmod(0o700)
        self.owner = types.SimpleNamespace(pw_name="operator", pw_uid=os.getuid(), pw_gid=os.getgid(),
                                         pw_dir=str(self.base))

    def plan(self, workspace=None):
        with patch.object(app, "account", return_value=self.owner):
            return app.make_plan(argparse.Namespace(user="operator", repo=str(self.repo),
                workspace=str(workspace or self.repo), herdr_bin=str(self.herdr), port=8765))

    def test_actual_installed_origin_without_import_or_server_bootstrap(self):
        plan = self.plan()
        self.assertEqual(plan["entrypoint"], "module")
        self.assertEqual(plan["workspace"], str(self.repo))
        self.assertFalse((self.repo / "src/gpt_agent_bridge/__pycache__").exists())

    def test_uninstalled_or_wrong_package_origin_refused(self):
        (self.site / "fixture.pth").unlink()
        with self.assertRaises(app.Refusal): self.plan()
        other = self.base / "other/gpt_agent_bridge"; other.mkdir(parents=True)
        (other / "__init__.py").write_text("")
        (self.site / "fixture.pth").write_text(str(other.parent) + "\n")
        with self.assertRaises(app.Refusal): self.plan()

    def test_subdirectory_non_git_and_bare_workspace_refused(self):
        for name in ("subdirectory", "nongit", "bare"):
            directory = self.repo / name if name == "subdirectory" else self.base / name
            directory.mkdir()
            if name == "bare":
                subprocess.run(["/usr/bin/git", "init", "--bare", "-q", str(directory)], env=self.env, check=True)
            with self.subTest(name=name), self.assertRaises(app.Refusal): self.plan(directory)

    def test_wrong_venv_and_symlinked_package_refused(self):
        real = self.repo / ".venv"; real.rename(self.base / "other-venv")
        real.symlink_to(self.base / "other-venv")
        with self.assertRaises(app.Refusal): self.plan()
        real.unlink(); (self.base / "other-venv").rename(real)
        package = self.repo / "src/gpt_agent_bridge"; package.rename(self.base / "other-package")
        package.symlink_to(self.base / "other-package")
        with self.assertRaises(app.Refusal): self.plan()

    def test_actual_module_launch_uses_checked_src_not_cwd_shadow(self):
        package = self.repo / "src/gpt_agent_bridge"
        (package / "__init__.py").write_text("")
        (package / "__main__.py").write_text("print('isolated-source')")
        shadow = self.repo / "gpt_agent_bridge"; shadow.mkdir()
        (shadow / "__init__.py").write_text("")
        (shadow / "__main__.py").write_text("raise AssertionError('cwd shadow must not run')")
        plan = self.plan()
        with patch.object(app.os, "chdir"), patch.object(app.os, "execve") as execute, \
                patch.object(app, "account", return_value=self.owner):
            app.runtime({**plan, "token": "synthetic-only-" + "x" * 32})
        executable, argv, env = execute.call_args.args
        result = subprocess.run(argv, executable=executable, env=env, cwd=self.repo,
                                capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "isolated-source")

    def test_writable_checkout_source_venv_and_herdr_refused_before_python(self):
        for target in (self.repo, self.repo / "src", self.repo / "src/gpt_agent_bridge/server.py",
                       self.repo / ".venv/bin", self.site, self.site / "fixture.pth", self.herdr,
                       self.base):
            old = target.stat().st_mode & 0o777
            with self.subTest(target=target.relative_to(self.base) if target != self.base else "home"):
                try:
                    target.chmod(0o777 if target.is_dir() else (0o722 if target == self.herdr else 0o666))
                    with patch.object(app, "user_command", wraps=app.user_command) as commands, self.assertRaises(app.Refusal):
                        self.plan()
                    self.assertFalse(any(c.args[0][0].endswith("/python") for c in commands.call_args_list))
                finally: target.chmod(old)

    def test_writable_resolved_interpreter_and_external_venv_link_refused(self):
        python = self.repo / ".venv/bin/python"
        original = os.readlink(python)
        fake = self.base / "python3"; fake.write_text("never execute"); fake.chmod(0o777)
        python.unlink(); python.symlink_to(fake)
        with patch.object(app, "user_command", wraps=app.user_command) as commands, self.assertRaises(app.Refusal): self.plan()
        self.assertFalse(any(c.args[0][0] == str(python) for c in commands.call_args_list))
        python.unlink(); python.symlink_to(original)
        (self.site / "escaped.py").symlink_to(self.herdr)
        with self.assertRaises(app.Refusal): self.plan()

    def test_foreign_source_owner_refused_and_normal_symlink_venv_allowed(self):
        target = self.repo / "src/gpt_agent_bridge/server.py"
        original = Path.lstat
        def lstat(p, *args, **kwargs):
            st = original(p, *args, **kwargs)
            return types.SimpleNamespace(st_uid=self.owner.pw_uid + 9999, st_mode=st.st_mode) if p == target else st
        with patch.object(Path, "lstat", lstat), self.assertRaises(app.Refusal): self.plan()
        self.assertTrue((self.repo / ".venv/bin/python").is_symlink())
        self.assertEqual(self.plan()["repo"], str(self.repo))

    def test_permission_change_after_plan_refused_on_revalidation(self):
        plan = self.plan()
        (self.site / "fixture.pth").chmod(0o666)
        with patch.object(app, "account", return_value=self.owner), self.assertRaises(app.Refusal): app.verify_plan(plan)


class ActivationPolicyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.units = self.base / "units"; self.units.mkdir()
        for key, value in (("UNIT", self.units / app.UNIT_NAME), ("UNIT_SEARCH_DIRS", (self.units,)),
                           ("ROOT_UID", os.getuid())):
            p = patch.object(app, key, value); p.start(); self.addCleanup(p.stop)
        p = patch.object(app, "command", return_value=str(self.units)); p.start(); self.addCleanup(p.stop)

    def test_clean_and_unrelated_vendor_units_are_accepted(self):
        (self.units / "unrelated.service").write_text("synthetic")
        (self.units / "alias.service").symlink_to("unrelated.service")
        app.activation_policy()

    def test_dangling_wants_requires_and_alias_chain_refused(self):
        for suffix in ("wants", "requires"):
            directory = self.units / ("other.target." + suffix); directory.mkdir()
            edge = directory / app.UNIT_NAME; edge.symlink_to("../" + app.UNIT_NAME)
            with self.assertRaises(app.Refusal): app.activation_policy()
            edge.unlink(); directory.rmdir()
        (self.units / "alias.service").symlink_to(app.UNIT_NAME)
        (self.units / "second.service").symlink_to("alias.service")
        with self.assertRaises(app.Refusal): app.activation_policy()

    def test_unit_inherited_and_dash_prefix_dropins_refused(self):
        for name in (app.UNIT_NAME + ".d", "service.d", "gpt-.service.d", "gpt-agent-bridge-.service.d"):
            directory = self.units / name; directory.mkdir()
            (directory / "foreign.conf").write_text("[Install]\nWantedBy=other.target")
            with self.subTest(name=name), self.assertRaises(app.Refusal): app.activation_policy()
            (directory / "foreign.conf").unlink(); directory.rmdir()

    def test_unsafe_lookup_or_dependency_directory_and_unknown_manager_refused(self):
        self.units.chmod(0o777)
        with self.assertRaises(app.Refusal): app.activation_policy()
        self.units.chmod(0o755)
        directory = self.units / "other.target.wants"; directory.mkdir(); directory.chmod(0o777)
        with self.assertRaises(app.Refusal): app.activation_policy()
        directory.chmod(0o755); directory.rmdir()
        for result in ("", str(self.base / "unknown")):
            with patch.object(app, "command", return_value=result), self.assertRaises(app.Refusal): app.activation_policy()
        with patch.object(app, "command", side_effect=app.Refusal("unavailable")), self.assertRaises(app.Refusal): app.activation_policy()

    def test_only_exact_owned_boot_dependency_allowed_for_start(self):
        app.UNIT.write_text("synthetic")
        directory = self.units / "multi-user.target.wants"; directory.mkdir()
        edge = directory / app.UNIT_NAME; edge.symlink_to("../" + app.UNIT_NAME)
        with self.assertRaises(app.Refusal): app.activation_policy(published=True)
        app.activation_policy(published=True, enabled=True)
        edge.unlink(); edge.symlink_to(self.base / app.UNIT_NAME)
        with self.assertRaises((app.Refusal, FileNotFoundError)): app.activation_policy(published=True, enabled=True)


class InstallTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        (self.base / "units").mkdir(); (self.base / "lib").mkdir(); (self.base / "state").mkdir()
        lib = self.base / "lib/autostart"; state = self.base / "state/autostart"
        constants = {"UNIT": self.base / "units" / app.UNIT_NAME, "LIB": lib,
                     "STATE": state, "CONFIG": state / "settings.json", "RUNNER": lib / "runner.py",
                     "MANIFEST": lib / "installation.json"}
        for key, value in constants.items():
            p = patch.object(app, key, value); p.start(); self.addCleanup(p.stop)
        p = patch.object(app, "UNIT_SEARCH_DIRS", (app.UNIT.parent,)); p.start(); self.addCleanup(p.stop)
        for name in ("host", "system_parent", "free_port"):
            p = patch.object(app, name); p.start(); self.addCleanup(p.stop)
        for name, value in (("trusted_installer", SCRIPT.read_bytes()), ("verify_plan", None)):
            p = patch.object(app, name, return_value=value); p.start(); self.addCleanup(p.stop)
        for name in ("chown", "fchown"):
            p = patch.object(app.os, name); p.start(); self.addCleanup(p.stop)
        p = patch.object(app, "ROOT_UID", os.getuid()); p.start(); self.addCleanup(p.stop)
        self.plan = {"format": app.MARKER, "user": "operator", "uid": os.getuid(), "gid": os.getgid(),
                     "home": "/home/operator", "repo": str(ROOT), "workspace": "/home/operator/project",
                     "herdr_bin": "/home/operator/bin/herdr", "port": 8765, "entrypoint": "module"}
        self.commands = []

    def fake_command(self, args, allowed=(0,)):
        self.commands.append(args)
        if "UnitPath" in args: return str(app.UNIT.parent)
        if "LoadState" in args: return "loaded" if app.UNIT.exists() and app.UNIT_NAME in args else "not-found"
        if "FragmentPath" in args: return str(app.UNIT)
        if "ActiveState" in args: return "inactive"
        if "is-enabled" in args: return "disabled"
        return ""

    def install(self, token=None):
        with patch.object(app, "command", side_effect=self.fake_command), \
                contextlib.redirect_stdout(io.StringIO()):
            app.install(self.plan, token)

    def signal_handlers(self):
        return {signum: app.signal.getsignal(signum)
                for signum in (app.signal.SIGTERM, app.signal.SIGHUP)}

    def assert_handlers_restored(self, previous):
        for signum, handler in previous.items():
            self.assertIs(app.signal.getsignal(signum), handler)

    def test_install_persists_one_private_token_never_enables_or_starts(self):
        previous = self.signal_handlers()
        self.install()
        self.assert_handlers_restored(previous)
        config = json.loads(app.CONFIG.read_text())
        self.assertRegex(config["token"], r"^[A-Za-z0-9_-]{32,}$")
        self.assertEqual(app.CONFIG.stat().st_mode & 0o777, 0o600)
        self.assertEqual(app.STATE.stat().st_mode & 0o777, 0o700)
        unit = app.UNIT.read_text()
        self.assertNotIn(config["token"], unit)
        self.assertIn("User=operator\n", unit); self.assertIn("Restart=on-failure", unit)
        self.assertIn("StandardError=null", unit)
        self.assertIn(" -I -B " + str(app.RUNNER) + " run", unit)
        self.assertFalse(any("start" in x or "enable" in x for x in self.commands))
        self.assertIn([app.SYSTEMCTL, "daemon-reload"], self.commands)
        self.assertEqual(self.commands[-1], [app.SYSTEMCTL, "is-enabled", app.UNIT_NAME])
        self.assertEqual(json.loads(app.MANIFEST.read_text())["unit_sha256"], hashlib.sha256(app.UNIT.read_bytes()).hexdigest())

    def test_no_clobber_any_existing_file_or_dangling_symlink(self):
        for target in (app.UNIT, app.LIB, app.STATE):
            with self.subTest(target=target):
                target.symlink_to(self.base / "missing")
                with self.assertRaises(app.Refusal): self.install()
                self.assertTrue(target.is_symlink()); target.unlink()
        app.UNIT.write_text("unknown")
        with self.assertRaises(app.Refusal): self.install()
        self.assertEqual(app.UNIT.read_text(), "unknown")

    def test_existing_adopter_service_refused(self):
        def cmd(args, allowed=(0,)):
            return "loaded" if "gpt-agent-bridge.service" in args else "not-found"
        with patch.object(app, "command", side_effect=cmd), self.assertRaises(app.Refusal):
            app.install(self.plan)
        self.assertFalse(app.STATE.exists())

    def test_bad_token_never_publishes(self):
        directory = self.base / "private"; directory.mkdir(mode=0o700)
        token = directory / "token"; token.write_text("not-valid\nsecret"); token.chmod(0o600)
        with self.assertRaises(app.Refusal): self.install(str(token))
        self.assertFalse(app.UNIT.exists()); self.assertFalse(app.STATE.exists())

    def test_supplied_token_is_preserved_and_not_echoed(self):
        directory = self.base / "private"; directory.mkdir(mode=0o700)
        token = directory / "token"; token.write_text("synthetic-stable-token-" + "x" * 32); token.chmod(0o600)
        self.install(str(token))
        self.assertEqual(json.loads(app.CONFIG.read_text())["token"], token.read_text())

    def test_verify_failure_cleans_only_new_staging(self):
        previous = self.signal_handlers()
        unrelated = self.base / "unrelated"; unrelated.write_text("keep")
        def cmd(args, allowed=(0,)):
            if args[0] == app.ANALYZE: raise app.Refusal("verification failed")
            return self.fake_command(args)
        with patch.object(app, "command", side_effect=cmd), self.assertRaises(app.Refusal):
            app.install(self.plan)
        self.assertFalse(app.UNIT.exists()); self.assertFalse(app.STATE.exists()); self.assertFalse(app.LIB.exists())
        self.assertEqual(unrelated.read_text(), "keep")
        self.assert_handlers_restored(previous)

    def test_interruption_before_publication_cleans_private_staging(self):
        previous = self.signal_handlers()
        def cmd(args, allowed=(0,)):
            if args[0] == app.ANALYZE: raise KeyboardInterrupt
            return self.fake_command(args)
        with patch.object(app, "command", side_effect=cmd), self.assertRaises(KeyboardInterrupt):
            app.install(self.plan)
        self.assertFalse(app.STATE.exists()); self.assertFalse(app.LIB.exists()); self.assertFalse(app.UNIT.exists())
        self.assert_handlers_restored(previous)

    def test_termination_handler_cleans_staging_and_restores_handler(self):
        previous = self.signal_handlers()
        def cmd(args, allowed=(0,)):
            if args[0] == app.ANALYZE:
                handler = app.signal.getsignal(app.signal.SIGTERM)
                self.assertTrue(callable(handler))
                handler(app.signal.SIGTERM, None)  # No OS signal or other process touched.
            return self.fake_command(args)
        with patch.object(app, "command", side_effect=cmd), self.assertRaises(app.Refusal): app.install(self.plan)
        self.assert_handlers_restored(previous)
        self.assertFalse(app.STATE.exists()); self.assertFalse(app.LIB.exists()); self.assertFalse(app.UNIT.exists())

    def test_actual_sighup_in_disposable_session_cleans_secret_and_sanitizes_cli(self):
        # Only the child signals its own PID; no host/group process is targeted.
        child = """
import contextlib, io, json, os
from unittest.mock import patch
from tests.test_bridge_autostart import InstallTests, app
assert os.getpgrp() == os.getpid()
case = InstallTests('test_install_persists_one_private_token_never_enables_or_starts')
case.setUp()
secret = 'synthetic-sighup-secret-' + 'x' * 32
def prior_handler(signum, frame):
    raise AssertionError('Original handler ran during staged installation')
for signum in (app.signal.SIGTERM, app.signal.SIGHUP):
    app.signal.signal(signum, prior_handler)
previous = case.signal_handlers()
def command(args, allowed=(0,)):
    if args[0] == app.ANALYZE:
        assert json.loads(app.CONFIG.read_text())['token'] == secret
        assert app.CONFIG.stat().st_mode & 0o777 == 0o600
        assert not app.UNIT.exists()
        assert callable(app.signal.getsignal(app.signal.SIGHUP))
        os.kill(os.getpid(), app.signal.SIGHUP)
        raise AssertionError('SIGHUP did not interrupt verify')
    return case.fake_command(args)
try:
    out, err = io.StringIO(), io.StringIO()
    with patch.object(app, 'make_plan', return_value=case.plan), \\
            patch.object(app, 'command', side_effect=command), \\
            patch.object(app.secrets, 'token_urlsafe', return_value=secret), \\
            contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        result = app.main(['install', '--user', 'operator', '--repo', str(case.base),
                           '--workspace', str(case.base), '--herdr-bin', '/synthetic/herdr'])
    assert result == 1
    assert out.getvalue() == ''
    assert err.getvalue() == 'Installation interrupted; inspect any published evidence before retry\\n'
    assert secret not in err.getvalue()
    assert not app.CONFIG.exists() and not app.STATE.exists()
    assert not app.LIB.exists() and not app.UNIT.exists()
    case.assert_handlers_restored(previous)
    assert not any('start' in args or 'enable' in args for args in case.commands)
finally:
    case.doCleanups()
"""
        env = {"PATH": os.defpath, "HOME": str(self.base), "TMPDIR": str(self.base),
               "LANG": "C.UTF-8", "PYTHONDONTWRITEBYTECODE": "1",
               "GIT_OPTIONAL_LOCKS": "0", "GIT_CONFIG_NOSYSTEM": "1",
               "GIT_CONFIG_GLOBAL": "/dev/null"}
        result = subprocess.run([sys.executable, "-B", "-c", child], cwd=ROOT, env=env,
                                start_new_session=True, capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, ""); self.assertEqual(result.stderr, "")

    def cleanup_signal_child(self, mode):
        # Real signals stay in a disposable session, including restoration races.
        child = """
import contextlib, io, json, os, sys
from pathlib import Path
from unittest.mock import patch
from tests.test_bridge_autostart import InstallTests, app
assert os.getpgrp() == os.getpid()
mode = sys.argv[1]
foreign = mode.startswith('foreign')
hardlink = mode.startswith('hardlink')
restore = mode.endswith('restore')
case = InstallTests('test_install_persists_one_private_token_never_enables_or_starts')
case.setUp()
secret = 'synthetic-cleanup-signal-secret-' + 'x' * 32
prior_calls = []
def prior_handler(signum, frame):
    assert all(app.signal.getsignal(s) is prior_handler
               for s in (app.signal.SIGHUP, app.signal.SIGTERM))
    prior_calls.append(signum)
for signum in (app.signal.SIGTERM, app.signal.SIGHUP):
    app.signal.signal(signum, prior_handler)
previous = case.signal_handlers()
app.signal.pthread_sigmask(app.signal.SIG_BLOCK, {app.signal.SIGUSR1})
original_mask = app.signal.pthread_sigmask(app.signal.SIG_BLOCK, set())
fired = False
restoration_fired = False
real_unlink = Path.unlink
real_register = app.signal.signal
alias = case.base / 'foreign-hardlink'
def command(args, allowed=(0,)):
    if args[0] == app.ANALYZE:
        assert json.loads(app.CONFIG.read_text())['token'] == secret
        assert app.CONFIG.stat().st_mode & 0o777 == 0o600
        assert not app.UNIT.exists()
        if foreign:
            (app.STATE / 'foreign').write_text('keep foreign evidence')
        if hardlink:
            os.link(app.CONFIG, alias)
        raise app.Refusal('synthetic verification failed')
    return case.fake_command(args)
def unlink(p, *args, **kwargs):
    global fired
    trigger = app.LIB / app.UNIT_NAME if foreign or hardlink else app.CONFIG
    if p == trigger and not fired:
        fired = True
        assert app.CONFIG.exists() and not app.UNIT.exists()
        # The original verify exception is already being unwound by cleanup.
        assert isinstance(sys.exc_info()[1], app.Refusal)
        os.kill(os.getpid(), app.signal.SIGTERM if mode == 'term' else app.signal.SIGHUP)
        if mode.endswith('repeat'):
            os.kill(os.getpid(), app.signal.SIGTERM)
    return real_unlink(p, *args, **kwargs)
def register(signum, handler):
    global restoration_fired
    result = real_register(signum, handler)
    if restore and fired and signum == app.signal.SIGTERM and handler is prior_handler:
        restoration_fired = True
        assert {app.signal.SIGHUP, app.signal.SIGTERM}.issubset(
            app.signal.pthread_sigmask(app.signal.SIG_BLOCK, set()))
        os.kill(os.getpid(), app.signal.SIGHUP)
    return result
try:
    out, err = io.StringIO(), io.StringIO()
    with patch.object(app, 'make_plan', return_value=case.plan), \\
            patch.object(app, 'command', side_effect=command), \\
            patch.object(app.secrets, 'token_urlsafe', return_value=secret), \\
            patch.object(Path, 'unlink', unlink), patch.object(app.signal, 'signal', register), \\
            contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        result = app.main(['install', '--user', 'operator', '--repo', str(case.base),
                           '--workspace', str(case.base), '--herdr-bin', '/synthetic/herdr'])
    assert fired and result == 1 and not app.UNIT.exists()
    if hardlink:
        assert app.CONFIG.exists() and alias.exists()
        assert app.CONFIG.stat().st_ino == alias.stat().st_ino
    else:
        assert not app.CONFIG.exists(), 'Owned staging secret survived cleanup interruption'
        if foreign:
            assert (app.STATE / 'foreign').read_text() == 'keep foreign evidence'
        else:
            assert not app.STATE.exists()
    assert not app.LIB.exists()
    assert not list(app.UNIT.parent.iterdir())
    case.assert_handlers_restored(previous)
    assert app.signal.pthread_sigmask(app.signal.SIG_BLOCK, set()) == original_mask
    assert prior_calls == ([app.signal.SIGHUP] if restore else [])
    assert restoration_fired == restore
    expected = ('Cleanup preserved changed/unknown objects; operator review required\\n'
                if foreign or hardlink else 'synthetic verification failed\\n')
    assert out.getvalue() == '' and err.getvalue() == expected
    assert secret not in err.getvalue()
    assert not any('start' in args or 'enable' in args for args in case.commands)
finally:
    case.doCleanups()
"""
        previous = self.signal_handlers()
        env = {"PATH": os.defpath, "HOME": str(self.base), "TMPDIR": str(self.base),
               "LANG": "C.UTF-8", "PYTHONDONTWRITEBYTECODE": "1",
               "GIT_OPTIONAL_LOCKS": "0", "GIT_CONFIG_NOSYSTEM": "1",
               "GIT_CONFIG_GLOBAL": "/dev/null"}
        result = subprocess.run([sys.executable, "-B", "-c", child, mode], cwd=ROOT, env=env,
                                start_new_session=True, capture_output=True, text=True, timeout=20)
        self.assert_handlers_restored(previous)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, ""); self.assertEqual(result.stderr, "")

    def test_real_sighup_during_failed_install_cleanup_removes_owned_secret(self):
        self.cleanup_signal_child("hup")

    def test_real_sigterm_during_failed_install_cleanup_removes_owned_secret(self):
        self.cleanup_signal_child("term")

    def test_second_signal_during_cleanup_does_not_reenter_or_retry(self):
        self.cleanup_signal_child("repeat")

    def test_second_sighup_during_handler_restore_waits_for_both_handlers(self):
        self.cleanup_signal_child("restore")

    def test_cleanup_signal_preserves_foreign_objects_and_cleans_owned_secret(self):
        self.cleanup_signal_child("foreign")

    def test_cleanup_signal_preserves_hardlinked_secret_and_restores_handlers(self):
        self.cleanup_signal_child("hardlink")

    def test_second_cleanup_signal_preserves_foreign_evidence_without_retry(self):
        self.cleanup_signal_child("foreign_repeat")

    def test_second_restore_signal_preserves_hardlinked_secret_after_cleanup_refusal(self):
        self.cleanup_signal_child("hardlink_restore")

    def test_handlers_not_changed_when_host_gate_refuses(self):
        previous = self.signal_handlers()
        app.host.side_effect = app.Refusal("unsupported host")
        with patch.object(app.signal, "signal", wraps=app.signal.signal) as changed, \
                self.assertRaises(app.Refusal):
            self.install()
        changed.assert_not_called()
        self.assert_handlers_restored(previous)
        self.assertFalse(app.LIB.exists()); self.assertFalse(app.STATE.exists())

    def test_partial_signal_setup_restores_previous_handler_without_staging(self):
        previous = self.signal_handlers()
        real = app.signal.signal
        def register(signum, handler):
            if signum == app.signal.SIGHUP and handler is not previous[signum]:
                raise ValueError("synthetic handler registration failure")
            return real(signum, handler)
        with patch.object(app.signal, "signal", side_effect=register), self.assertRaises(ValueError):
            self.install()
        self.assert_handlers_restored(previous)
        self.assertFalse(app.LIB.exists()); self.assertFalse(app.STATE.exists()); self.assertFalse(app.UNIT.exists())

    def test_sighup_before_publication_link_cleans_pending_and_secret(self):
        previous = self.signal_handlers()
        def link(src, dst, **kwargs):
            app.signal.getsignal(app.signal.SIGHUP)(app.signal.SIGHUP, None)
        with patch.object(app.os, "link", side_effect=link), self.assertRaises(app.Refusal):
            self.install()
        self.assertFalse(app.CONFIG.exists()); self.assertFalse(app.STATE.exists()); self.assertFalse(app.LIB.exists())
        self.assertEqual(list(app.UNIT.parent.iterdir()), [])
        self.assert_handlers_restored(previous)

    def test_sighup_after_publication_link_retains_owned_evidence(self):
        previous = self.signal_handlers()
        real = os.link
        def link(src, dst, **kwargs):
            real(src, dst, **kwargs)
            app.signal.getsignal(app.signal.SIGHUP)(app.signal.SIGHUP, None)
        with patch.object(app.os, "link", side_effect=link), self.assertRaises(app.Refusal):
            self.install()
        self.assertTrue(app.UNIT.exists()); self.assertTrue(app.CONFIG.exists()); self.assertTrue(app.RUNNER.exists())
        pending = next(p for p in app.UNIT.parent.iterdir() if p != app.UNIT)
        self.assertEqual(pending.stat().st_ino, app.UNIT.stat().st_ino)
        self.assertFalse(any("daemon-reload" in args for args in self.commands))
        self.assert_handlers_restored(previous)

    def test_sighup_with_foreign_unit_preserves_it_and_cleans_own_secret(self):
        previous = self.signal_handlers()
        def link(src, dst, **kwargs):
            app.UNIT.write_text("foreign unit")
            app.signal.getsignal(app.signal.SIGHUP)(app.signal.SIGHUP, None)
        with patch.object(app.os, "link", side_effect=link), self.assertRaises(app.Refusal):
            self.install()
        self.assertEqual(app.UNIT.read_text(), "foreign unit")
        self.assertFalse(app.CONFIG.exists()); self.assertFalse(app.STATE.exists()); self.assertFalse(app.LIB.exists())
        self.assertEqual(list(app.UNIT.parent.iterdir()), [app.UNIT])
        self.assert_handlers_restored(previous)

    def test_sighup_cleanup_preserves_hardlinked_secret_and_restores_handlers(self):
        previous = self.signal_handlers()
        alias = self.base / "foreign-hardlink"
        def cmd(args, allowed=(0,)):
            if args[0] == app.ANALYZE:
                os.link(app.CONFIG, alias)
                app.signal.getsignal(app.signal.SIGHUP)(app.signal.SIGHUP, None)
            return self.fake_command(args)
        with patch.object(app, "command", side_effect=cmd), self.assertRaisesRegex(app.Refusal, "operator review"):
            app.install(self.plan)
        self.assertTrue(app.CONFIG.exists()); self.assertTrue(alias.exists())
        self.assertEqual(app.CONFIG.stat().st_ino, alias.stat().st_ino)
        self.assertFalse(app.UNIT.exists())
        self.assert_handlers_restored(previous)

    def test_interruption_after_link_retains_published_evidence(self):
        real = os.link
        def link(src, dst, **kwargs):
            real(src, dst, **kwargs)
            raise KeyboardInterrupt
        with patch.object(app.os, "link", side_effect=link), self.assertRaises(KeyboardInterrupt): self.install()
        self.assertTrue(app.UNIT.exists()); self.assertTrue(app.CONFIG.exists()); self.assertTrue(app.RUNNER.exists())

    def test_uncertain_daemon_reload_retains_published_evidence(self):
        previous = self.signal_handlers()
        def cmd(args, allowed=(0,)):
            if "daemon-reload" in args: raise app.Refusal("unknown effect")
            return self.fake_command(args)
        with patch.object(app, "command", side_effect=cmd), self.assertRaises(app.Refusal):
            app.install(self.plan)
        self.assertTrue(app.UNIT.exists()); self.assertTrue(app.CONFIG.exists()); self.assertTrue(app.MANIFEST.exists())
        self.assert_handlers_restored(previous)

    def test_activation_appearing_during_verify_cleans_staging_without_publish(self):
        foreign = app.UNIT.parent / "other.target.wants"; foreign.mkdir()
        def cmd(args, allowed=(0,)):
            if args[0] == app.ANALYZE: (foreign / app.UNIT_NAME).symlink_to("../" + app.UNIT_NAME)
            return self.fake_command(args)
        with patch.object(app, "command", side_effect=cmd), self.assertRaises(app.Refusal): app.install(self.plan)
        self.assertFalse(app.UNIT.exists()); self.assertFalse(app.CONFIG.exists()); self.assertFalse(app.LIB.exists())
        self.assertTrue((foreign / app.UNIT_NAME).is_symlink())

    def test_postpublication_manager_states_never_claim_success(self):
        # Each subcase gets a fresh fixture; published evidence must be retained.
        for property_name, bad in (("FragmentPath", "/foreign/unit"), ("DropInPaths", "/foreign.conf"),
                                   ("ActiveState", "activating"), ("is-enabled", "enabled-runtime")):
            with self.subTest(property=property_name):
                def cmd(args, allowed=(0,)):
                    if property_name in args: return bad
                    return self.fake_command(args)
                with patch.object(app, "command", side_effect=cmd), contextlib.redirect_stdout(io.StringIO()) as out, self.assertRaises(app.Refusal):
                    app.install(self.plan)
                self.assertNotIn("Installed only", out.getvalue())
                self.assertTrue(app.UNIT.exists()); self.assertTrue(app.CONFIG.exists())
                # Dispose only known test fixture outputs, never production files.
                app.UNIT.unlink(); shutil.rmtree(app.LIB); shutil.rmtree(app.STATE)

    def test_changed_source_after_verify_cleans_staging(self):
        app.verify_plan.side_effect = [None, app.Refusal("permissions changed")]
        with self.assertRaises(app.Refusal): self.install()
        self.assertFalse(app.UNIT.exists()); self.assertFalse(app.STATE.exists()); self.assertFalse(app.LIB.exists())

    def test_explicit_enable_has_no_start_and_start_rejects_transition(self):
        self.install()
        with patch.object(app, "owned_installation", return_value=self.plan), \
                patch.object(app, "activation_policy") as policy, \
                patch.object(app, "command", side_effect=["not-found", ""]) as cmd, contextlib.redirect_stdout(io.StringIO()):
            app.control("enable")
        policy.assert_called_once_with(published=True, enabled=False)
        self.assertEqual(cmd.call_args.args[0], [app.SYSTEMCTL, "enable", app.UNIT_NAME])
        self.assertEqual(cmd.call_count, 2)
        with patch.object(app, "owned_installation", return_value=self.plan), \
                patch.object(app, "activation_policy") as policy, \
                patch.object(app, "command", side_effect=["not-found", "activating"]) as cmd, self.assertRaises(app.Refusal):
            app.control("start")
        policy.assert_called_once_with(published=True, enabled=True)
        self.assertEqual(cmd.call_count, 2)

    def test_unknown_fragment_dropins_and_modified_runner_refused(self):
        self.install()
        for results in (["/unknown/unit"], [str(app.UNIT), "/unknown/dropin.conf"]):
            with patch.object(app, "command", side_effect=results), self.assertRaises(app.Refusal):
                app.owned_installation()
        with patch.object(app, "command", side_effect=[str(app.UNIT), ""]):
            self.assertEqual(app.owned_installation(), self.plan)
        app.RUNNER.write_text("changed")
        with patch.object(app, "command") as cmd, self.assertRaises(app.Refusal):
            app.owned_installation()
        cmd.assert_not_called()

    def test_enable_rejects_unsafe_config(self):
        self.install(); app.CONFIG.chmod(0o644)
        with patch.object(app, "owned_installation", return_value=self.plan), \
                patch.object(app, "command", return_value="not-found") as cmd, self.assertRaises(app.Refusal):
            app.control("enable")
        self.assertFalse(any('enable' in call.args[0] for call in cmd.call_args_list))

    def test_control_refuses_coexisting_adopter(self):
        self.install()
        with patch.object(app, "owned_installation", return_value=self.plan), \
                patch.object(app, "command", return_value="loaded") as cmd, self.assertRaises(app.Refusal):
            app.control("enable")
        self.assertEqual(cmd.call_count, 1)

    def test_state_directory_creation_failure_cleans_lib(self):
        original = Path.mkdir
        def mkdir(p, *args, **kwargs):
            if p == app.STATE: raise OSError("synthetic failure")
            return original(p, *args, **kwargs)
        with patch.object(Path, "mkdir", mkdir), self.assertRaises(OSError):
            self.install()
        self.assertFalse(app.LIB.exists()); self.assertFalse(app.UNIT.exists())

    def test_partial_private_config_write_failure_cleans_secret(self):
        original = os.fsync
        def fsync(fd):
            if app.CONFIG.exists() and os.fstat(fd).st_ino == app.CONFIG.lstat().st_ino:
                raise OSError("synthetic fsync failure")
            return original(fd)
        with patch.object(app.os, "fsync", side_effect=fsync), self.assertRaises(OSError):
            self.install()
        self.assertFalse(app.CONFIG.exists()); self.assertFalse(app.LIB.exists()); self.assertFalse(app.STATE.exists())

    def test_foreign_staged_file_is_preserved_and_own_secret_cleaned(self):
        def cmd(args, allowed=(0,)):
            if args[0] == app.ANALYZE:
                (app.STATE / "foreign").write_text("must keep")
                raise app.Refusal("verification failed")
            return self.fake_command(args)
        with patch.object(app, "command", side_effect=cmd), self.assertRaises(app.Refusal):
            app.install(self.plan)
        self.assertEqual((app.STATE / "foreign").read_text(), "must keep")
        self.assertFalse(app.CONFIG.exists()); self.assertFalse(app.UNIT.exists())

    def test_replaced_private_staging_file_is_preserved_for_review(self):
        def cmd(args, allowed=(0,)):
            if args[0] == app.ANALYZE:
                app.CONFIG.unlink(); app.CONFIG.write_text("foreign private content")
                raise app.Refusal("verification failed")
            return self.fake_command(args)
        with patch.object(app, "command", side_effect=cmd), self.assertRaises(app.Refusal):
            app.install(self.plan)
        self.assertEqual(app.CONFIG.read_text(), "foreign private content")
        self.assertFalse(app.UNIT.exists())

    def test_modified_staging_content_is_preserved_before_publish(self):
        def cmd(args, allowed=(0,)):
            if args[0] == app.ANALYZE: app.CONFIG.write_text("foreign replacement bytes")
            return self.fake_command(args)
        with patch.object(app, "command", side_effect=cmd), self.assertRaises(app.Refusal):
            app.install(self.plan)
        self.assertEqual(app.CONFIG.read_text(), "foreign replacement bytes")
        self.assertFalse(app.UNIT.exists())

    def test_unit_appearing_during_verify_is_not_clobbered(self):
        def cmd(args, allowed=(0,)):
            if args[0] == app.ANALYZE: app.UNIT.write_text("foreign unit")
            return self.fake_command(args)
        with patch.object(app, "command", side_effect=cmd), self.assertRaises(app.Refusal):
            app.install(self.plan)
        self.assertEqual(app.UNIT.read_text(), "foreign unit")
        self.assertFalse(app.CONFIG.exists()); self.assertFalse(app.STATE.exists()); self.assertFalse(app.LIB.exists())
        self.assertEqual(list(app.UNIT.parent.iterdir()), [app.UNIT])

    def test_source_and_template_trust_fail_before_publication(self):
        app.trusted_installer.side_effect = app.Refusal("untrusted source")
        with self.assertRaises(app.Refusal): self.install()
        self.assertFalse(app.LIB.exists())
        app.trusted_installer.side_effect = None
        with patch.object(app, "TEMPLATE_SHA256", "wrong"), self.assertRaises(app.Refusal): self.install()
        self.assertFalse(app.LIB.exists())

    def test_runtime_public_config_cannot_override_root_manifest(self):
        self.install()
        config = json.loads(app.CONFIG.read_text()); config["repo"] = "/tmp/foreign"
        app.CONFIG.write_text(json.dumps(config))
        with self.assertRaises(app.Refusal): app.load_config()

    def test_root_manifest_available_to_runtime_without_manager_calls(self):
        self.install()
        with patch.object(app, "command") as cmd:
            loaded = app.load_config()
        cmd.assert_not_called()
        self.assertEqual(loaded["repo"], self.plan["repo"])
        self.assertEqual(app.MANIFEST.stat().st_mode & 0o777, 0o644)
        self.assertEqual((app.LIB / app.UNIT_NAME).stat().st_mode & 0o777, 0o644)

    def test_uninstall_refuses_active_or_extra_files(self):
        self.install()
        with patch.object(app, "owned_installation", return_value=self.plan), \
                patch.object(app, "command", return_value="active"), self.assertRaises(app.Refusal):
            app.control("uninstall")
        extra = app.STATE / "unknown"; extra.write_text("keep")
        with patch.object(app, "owned_installation", return_value=self.plan), \
                patch.object(app, "command", side_effect=["inactive", "disabled"]), self.assertRaises(app.Refusal):
            app.control("uninstall")
        self.assertEqual(extra.read_text(), "keep"); self.assertTrue(app.UNIT.exists())

    def test_uninstall_only_owned_inactive_disabled_install(self):
        self.install()
        with patch.object(app, "owned_installation", return_value=self.plan), \
                patch.object(app, "command", side_effect=["inactive", "disabled", ""]) as cmd, \
                contextlib.redirect_stdout(io.StringIO()):
            app.control("uninstall")
        self.assertFalse(app.UNIT.exists()); self.assertFalse(app.LIB.exists()); self.assertFalse(app.STATE.exists())
        self.assertEqual(cmd.call_args.args[0], [app.SYSTEMCTL, "daemon-reload"])


class RuntimeHealthTests(unittest.TestCase):
    def setUp(self):
        self.config = {"user": "operator", "repo": "/home/operator/bridge", "home": "/home/operator",
                       "workspace": "/home/operator/project", "herdr_bin": "/home/operator/bin/herdr",
                       "token": "synthetic-token-" + "x" * 32, "port": 8765, "entrypoint": "module"}
        self.config.update(format=app.MARKER, uid=os.getuid(), gid=os.getgid())
        p = patch.object(app, "verify_plan"); p.start(); self.addCleanup(p.stop)

    def test_runtime_secret_only_in_allowlisted_env_not_argv(self):
        for entrypoint in ("module",):
            with self.subTest(entrypoint=entrypoint), patch.object(app.os, "chdir"), patch.object(app.os, "execve") as ex:
                app.runtime({**self.config, "entrypoint": entrypoint, "OTHER_SECRET": "must-not-copy"})
            executable, args, env = ex.call_args.args
            self.assertNotIn(self.config["token"], " ".join(args))
            self.assertEqual(env["BRIDGE_PATH_TOKEN"], self.config["token"])
            self.assertNotIn("OTHER_SECRET", env)
            self.assertEqual(env["BRIDGE_SERVICE_NAME"], app.UNIT_NAME)
            self.assertEqual(args[1:], ["-I", "-B", "-m", "gpt_agent_bridge"])

    def test_legacy_runtime_rejected(self):
        with patch.object(app.os, "execve") as ex, self.assertRaises(app.Refusal):
            app.runtime({**self.config, "entrypoint": "legacy"})
        ex.assert_not_called()

    def test_probe_success_does_not_require_herdr_running(self):
        for status in ("reachable", "unavailable", "unknown"):
            sdk, calls = self.client({"bridge": "gpt-agent-bridge", "ok": True, "herdr": {"status": status}})
            with patch.dict(sys.modules, {"mcp": sdk}), patch.object(app, "load_config", return_value=self.config), \
                    contextlib.redirect_stdout(io.StringIO()) as out:
                self.assertEqual(app.main(["probe"]), 0)
            self.assertEqual(json.loads(out.getvalue())["herdr"], status)
            self.assertEqual(calls, ["bridge_health"])

    def test_valid_bridge_with_missing_or_malformed_herdr_is_nonblocking(self):
        for value in (None, [], {}, {"status": "unknown"}):
            sdk, _ = self.client({"bridge": "gpt-agent-bridge", "ok": True, "herdr": value})
            with patch.dict(sys.modules, {"mcp": sdk}): result = asyncio.run(app.probe(self.config))
            self.assertEqual(result["bridge_mcp"], "initialized_healthy")
            self.assertEqual(result["herdr"], "unknown")

    def test_runtime_permission_revalidation_failure_never_executes(self):
        app.verify_plan.side_effect = app.Refusal("source changed")
        with patch.object(app.os, "execve") as execute, self.assertRaises(app.Refusal): app.runtime(self.config)
        execute.assert_not_called()

    def client(self, health=None, error=False):
        entered = []; calls = []
        class Client:
            def __init__(inner, endpoint, mode):
                self.assertEqual(mode, "legacy")
            async def __aenter__(inner): entered.append(True); return inner
            async def __aexit__(inner, *args): pass
            async def call_tool(inner, name, args):
                self.assertTrue(entered); calls.append(name)
                if error:
                    logging.error("synthetic-secret-url")
                    print("synthetic-secret-url")
                    print("synthetic-secret-url", file=sys.stderr)
                    raise RuntimeError("synthetic-secret-url")
                return types.SimpleNamespace(is_error=False, structured_content=health)
        return types.SimpleNamespace(Client=Client), calls

    def test_initialized_health_distinguishes_herdr_unavailable(self):
        for status in ("reachable", "unavailable", "garbage"):
            sdk, calls = self.client({"bridge": "gpt-agent-bridge", "ok": True, "herdr": {"status": status}})
            with patch.dict(sys.modules, {"mcp": sdk}): result = asyncio.run(app.probe(self.config))
            self.assertEqual(result["bridge_mcp"], "initialized_healthy")
            self.assertEqual(result["herdr"], status if status != "garbage" else "unknown")
            self.assertEqual(result["work_resume"], "not_established")
            self.assertEqual(calls, ["bridge_health"])

    def test_transport_error_and_logs_redacted_logging_restored(self):
        sdk, _ = self.client(error=True)
        previous = logging.root.manager.disable
        with patch.dict(sys.modules, {"mcp": sdk}), contextlib.redirect_stderr(io.StringIO()) as err, \
                contextlib.redirect_stdout(io.StringIO()) as out:
            result = asyncio.run(app.probe(self.config))
        self.assertEqual(result["bridge_mcp"], "unavailable_or_invalid")
        self.assertNotIn("synthetic-secret", json.dumps(result) + err.getvalue() + out.getvalue())
        self.assertEqual(logging.root.manager.disable, previous)

    def test_malformed_health_not_reported_as_success(self):
        for health in (None, {}, {"bridge": "another-service", "ok": True},
                       {"bridge": "gpt-agent-bridge"},
                       *({"bridge": "gpt-agent-bridge", "ok": value} for value in (False, 1, "true", None))):
            sdk, _ = self.client(health)
            with patch.dict(sys.modules, {"mcp": sdk}): result = asyncio.run(app.probe(self.config))
            self.assertEqual(result["bridge_mcp"], "unavailable_or_invalid")

    def test_handoff_is_explicit_private_and_contains_same_token(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(app, "load_config", return_value=self.config), \
                patch.object(app, "STATE", Path(tmp)), contextlib.redirect_stdout(io.StringIO()) as out:
            self.assertEqual(app.main(["handoff"]), 0)
            files = list(Path(tmp).iterdir()); self.assertEqual(len(files), 1)
            self.assertEqual(files[0].stat().st_mode & 0o777, 0o600)
            self.assertRegex(files[0].name, r"^bridge-client-env\..{8}$")
            self.assertIn(self.config["token"], files[0].read_text())
            self.assertNotIn(self.config["token"], out.getvalue())

    def test_status_does_not_read_config_or_start(self):
        with patch.object(app, "host"), patch.object(app, "command", side_effect=["active", "enabled"]) as cmd, \
                patch.object(app, "load_config") as load, contextlib.redirect_stdout(io.StringIO()) as out:
            self.assertEqual(app.main(["status"]), 0)
        load.assert_not_called()
        self.assertFalse(any("start" in call.args[0] for call in cmd.call_args_list))
        self.assertEqual(json.loads(out.getvalue())["service"], "active")

    def test_probe_timeout_is_bounded_json_on_python_310_too(self):
        def timeout(awaitable, timeout):
            awaitable.close()
            raise asyncio.TimeoutError
        with patch.object(app, "load_config", return_value=self.config), \
                patch.object(app.asyncio, "wait_for", side_effect=timeout), \
                contextlib.redirect_stdout(io.StringIO()) as out:
            self.assertEqual(app.main(["probe"]), 1)
        self.assertEqual(json.loads(out.getvalue()), {"bridge_mcp": "unavailable_or_invalid",
            "herdr": "unknown", "work_resume": "not_established"})


class WindowsStaticTests(unittest.TestCase):
    """Portable checks of policy-bearing text, not Windows runtime acceptance."""
    def test_fixed_native_action_and_explicit_enable(self):
        text = (ROOT / "scripts/install-bridge-wsl-logon-task.ps1").read_text()
        self.assertIn("--exec /usr/bin/sleep infinity", text)
        self.assertIn("New-ScheduledTaskSettingsSet -Disable", text)
        self.assertNotIn("$settings.Enabled = $false", text)
        self.assertIn("-ExecutionTimeLimit ([TimeSpan]::Zero) -MultipleInstances IgnoreNew", text)
        self.assertIn("-LogonType Interactive -RunLevel Limited", text)
        self.assertIn("-AtLogOn -User $Sid", text)
        for forbidden in ("-ExecutionPolicy", "-Password", "-Force", "Start-ScheduledTask", "wsl --shutdown", "Invoke-Expression"):
            self.assertNotIn(forbidden, text)

    def test_ownership_and_unknown_host_gates(self):
        text = (ROOT / "scripts/install-bridge-wsl-logon-task.ps1").read_text()
        for gate in ("S-1-5-18", "Version -ne 2", "Get-OwnedTask"):
            self.assertIn(gate, text)
        self.assertIn("$actions.Count -ne 1", text)
        self.assertIn("$execs[0].Arguments -cne $script:Arguments", text)
        self.assertIn("$Value -notmatch", text)
        self.assertIn("'\\A[a-z_][a-z0-9_-]{0,31}\\z'", text)
        self.assertIn("$names -cnotcontains $Distro", text)
        self.assertNotIn("-Confirm:$false -Force", text)

    def test_host_state_readback_follows_each_mutation(self):
        text = (ROOT / "scripts/install-bridge-wsl-logon-task.ps1").read_text()
        for action, command, state in (("Install", "Register-ScheduledTask", "$false"),
                                       ("Enable", "Enable-ScheduledTask", "$true"),
                                       ("Disable", "Disable-ScheduledTask", "$false")):
            block = text.split("'" + action + "' {", 1)[1].split("\n        }", 1)[0]
            self.assertLess(block.index(command), block.index("Assert-OwnedTaskState " + state))
            self.assertLess(block.index("Assert-OwnedTaskState " + state), block.index("Write-Output"))
        for field in ("RegistrationInfo/t:Description", "$task.Description", "t:Enabled",
                      "DisallowStartIfOnBatteries", "StopIfGoingOnBatteries", "ExpectedEnabled",
                      "t:ExecutionTimeLimit", "t:Repetition | t:StartBoundary | t:EndBoundary"):
            self.assertIn(field, text)

    def test_uninstall_and_anchor_stop_require_instance_readback(self):
        text = (ROOT / "scripts/install-bridge-wsl-logon-task.ps1").read_text()
        block = text.split("'Uninstall' {", 1)[1].split("\n        }", 1)[0]
        for token in ("'Running', 'Queued'", "Unknown anchor state", "Disable-ScheduledTask",
                      "Assert-OwnedTaskState $false", "Assert-NoAnchorInstance"):
            self.assertIn(token, block)
        self.assertLess(block.index("Assert-NoAnchorInstance"), block.index("Unregister-ScheduledTask"))
        check = text.split("function Assert-NoAnchorInstance", 1)[1].split("function Assert-ReadyDistro", 1)[0]
        self.assertIn("$registered.GetInstances(0).Count -ne 0", check)
        self.assertEqual(check.count("Assert-OwnedTaskState $false"), 2)
        self.assertIn("State -notin @('Ready', 'Disabled')", check)
        disable = text.split("'Disable' {", 1)[1].split("\n        }", 1)[0]
        self.assertLess(disable.index("Stop-ScheduledTask"), disable.index("Assert-NoAnchorInstance"))
        self.assertNotIn("ExecutionTimeLimit = 'PT0S'", text.replace("TaskSettingsExecutionTimeLimit = 'PT0S'", ""))
        self.assertIn("TriggerLimitVerified = $false", text)

    @unittest.skipUnless(shutil.which("pwsh") or shutil.which("powershell"), "PowerShell parser unavailable on this host")
    def test_powershell_parser_without_running_helper(self):
        executable = shutil.which("pwsh") or shutil.which("powershell")
        source = str(ROOT / "scripts/install-bridge-wsl-logon-task.ps1").replace("'", "''")
        command = "$t=$null; $e=$null; [System.Management.Automation.Language.Parser]::ParseFile('" + source + "',[ref]$t,[ref]$e) | Out-Null; if ($e.Count -ne 0) { exit 1 }"
        result = subprocess.run([executable, "-NoProfile", "-NonInteractive", "-Command", command], capture_output=True)
        self.assertEqual(result.returncode, 0, "PowerShell source parser rejected the helper")


class AutostartDocTests(unittest.TestCase):
    def test_local_guide_links_and_shell_syntax(self):
        text = (ROOT / "docs/BRIDGE-AUTOSTART.md").read_text()
        for block in re.findall(r"```bash\n(.*?)\n```", text, re.S):
            result = subprocess.run(["/bin/bash", "--noprofile", "--norc", "-n"], input=block, text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)
        for target in re.findall(r"\]\(([^)]+)\)", text):
            if "://" in target: continue
            relative, _, anchor = target.partition("#")
            dest = (ROOT / "docs" / relative).resolve()
            self.assertTrue(dest.is_file(), target)
            if anchor:
                contents = re.sub(r"```.*?```", "", dest.read_text(), flags=re.S)
                headings = re.findall(r"^#+ (.+)$", contents, re.M)
                slugs = [re.sub(r"[^\w -]", "", h.lower()).replace(" ", "-") for h in headings]
                slugs += re.findall(r'\bid=[\"\x27]([^\"\x27]+)', contents)
                self.assertIn(anchor, slugs, target)

    def test_references_and_limitations_remain_explicit(self):
        text = (ROOT / "docs/BRIDGE-AUTOSTART.md").read_text()
        for phrase in ("not promise pre-login", "does not promise", "systemd services alone", "disabled", "Herdr"):
            self.assertIn(phrase, text)
        for document in ("README.md", "docs/QUICKSTART.md", "docs/WINDOWS-WSL.md"):
            self.assertIn("BRIDGE-AUTOSTART.md", (ROOT / document).read_text())
        self.assertNotIn("CONTROL_PLANE_API_KEY=", text)


if __name__ == "__main__":
    unittest.main()
