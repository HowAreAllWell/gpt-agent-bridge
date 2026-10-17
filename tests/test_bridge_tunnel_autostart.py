"""Synthetic-only companion tests: no host systemctl, credentials or network.

Tests map root ownership to the fixture UID and stop ancestry at a temporary
0700 sandbox. Production path/regular-file/mode/race checks otherwise run.
All privileged command calls are inert in-memory fakes.
"""
import contextlib
import hashlib
import importlib.util
import io
import json
import logging
import os
from pathlib import Path
import signal
import socket
import stat
import subprocess
import sys
import tempfile
import types
import unittest
from unittest import mock

SOURCE = Path(__file__).resolve().parents[1] / "scripts/install-bridge-tunnel-autostart.py"
TEMPLATE = SOURCE.parent.parent / "systemd/gpt-agent-bridge-tunnel.service.template"
spec = importlib.util.spec_from_file_location("tunnel_companion_test_module", SOURCE)
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
ORIGINAL_TRUSTED_SNAPSHOT = m.trusted_snapshot


class CompanionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="bridge-tunnel-test-")
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.uid = os.getuid()
        self.gid = os.getgid()
        self.account = types.SimpleNamespace(pw_uid=self.uid, pw_gid=self.gid,
                                             pw_dir=str(self.base / "home"))
        (self.base / "home").mkdir(mode=0o700)
        paths = {"LIB": self.base / "lib/tunnel", "STATE": self.base / "state/tunnel",
                 "RUNTIME": self.base / "run/tunnel", "UNIT_FILE": self.base / "systemd/gpt-agent-bridge-tunnel.service",
                 "BRIDGE_MANIFEST": self.base / "bridge-lib/installation.json",
                 "BRIDGE_SETTINGS": self.base / "bridge-state/settings.json"}
        paths.update({"RUNNER": paths["LIB"] / "runner.py", "MANIFEST": paths["LIB"] / "installation.json",
                      "CREDENTIALS": paths["STATE"] / "credentials.json", "LOCK": paths["STATE"] / "runtime.lock",
                      "BRIDGE_RUNNER": paths["BRIDGE_MANIFEST"].parent / "runner.py",
                      "BRIDGE_UNIT_FILE": paths["UNIT_FILE"].parent / "gpt-agent-bridge-autostart.service",
                      "SYSTEMD_ROOTS": (self.base / "systemd", self.base / "vendor", self.base / "run-systemd")})
        for name, value in paths.items():
            self.patch(name, value)
        for p in [m.LIB.parent, m.STATE.parent, m.RUNTIME.parent, m.UNIT_FILE.parent,
                  m.BRIDGE_MANIFEST.parent, m.BRIDGE_SETTINGS.parent]:
            p.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.patch("directory", self.fixture_directory)
        original_read = m.read_file
        def fixture_read(path, owners, *args, **kwargs):
            if Path(path).is_relative_to(self.base):
                owners = (owners - {0}) | ({self.uid} if 0 in owners else set())
            return original_read(path, owners, *args, **kwargs)
        self.patch("read_file", fixture_read)
        self.patch("pwd", types.SimpleNamespace(getpwnam=lambda name: self.account))
        self.calls = []
        self.props = {"LoadState": "not-found", "FragmentPath": "", "DropInPaths": "",
                      "ActiveState": "inactive", "UnitFileState": "disabled"}
        self.patch("call", self.fake_call)
        self.client = self.base / "client"
        self.write(self.client, b"#!/usr/bin/python3\nimport sys\nprint('v0.0.16')\n", 0o700)
        self.plan = {"format": m.MARKER, "user": "demo", "uid": self.uid, "gid": self.gid,
                     "home": self.account.pw_dir, "client": str(self.client),
                     "client_sha256": hashlib.sha256(self.client.read_bytes()).hexdigest(),
                     "client_version": "v0.0.16", "health_socket": str(m.RUNTIME / "health.sock"),
                     "ttl": "10m", "bridge_wait_seconds": 3}
        self.secrets = {"tunnel_id": "tunnel_" + "a1" * 16, "runtime_api_key": "synthetic-runtime-key-ONLY"}
        self.patch("trusted_snapshot", lambda: (b"# reviewed synthetic runner\n", TEMPLATE.read_text()))

    def patch(self, name, value):
        p = mock.patch.object(m, name, value)
        p.start()
        self.addCleanup(p.stop)
        return value

    def fixture_directory(self, p, owners, mode=None):
        p = m.absolute(str(p))
        m.require(p.is_relative_to(self.base), "test_escape")
        owners = (owners - {0}) | ({self.uid} if 0 in owners else set())
        items = []
        cursor = p
        while True:
            items.append(cursor)
            if cursor == self.base:
                break
            cursor = cursor.parent
        for item in items:
            st = item.lstat()
            m.require(stat.S_ISDIR(st.st_mode) and st.st_uid in owners
                      and not st.st_mode & 0o022, "unsafe_directory")
        if mode is not None:
            m.require(stat.S_IMODE(p.lstat().st_mode) == mode, "directory_mode")

    def write(self, path, data, mode=0o600):
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        path.write_bytes(data)
        path.chmod(mode)

    def fake_call(self, argv, allowed=(0,)):
        self.calls.append(argv)
        if argv[1] == "show":
            if "--property=UnitPath" in argv:
                return subprocess.CompletedProcess(argv,0," ".join(str(p) for p in m.SYSTEMD_ROOTS).encode())
            if m.UNIT_FILE.exists():
                self.props.update(LoadState="loaded", FragmentPath=str(m.UNIT_FILE))
            return subprocess.CompletedProcess(argv, 0, "\n".join(f"{k}={v}" for k,v in self.props.items()).encode())
        if argv[1] == "enable":
            self.props["UnitFileState"] = "enabled"
        if argv[1] == "disable":
            self.props["UnitFileState"] = "disabled"
        if argv[1] == "start":
            self.props["ActiveState"] = "active"
        if argv[1] == "stop":
            self.props["ActiveState"] = "inactive"
        return subprocess.CompletedProcess(argv, 0, b"")

    def installed(self):
        with mock.patch.object(m.os, "chown"):
            m.install(self.plan)

    def provisioned(self):
        self.installed()
        self.write(m.CREDENTIALS, json.dumps(self.secrets).encode())

    def bridge(self):
        repo = self.base / "repo"
        python = repo / ".venv/bin/python"
        self.write(python, b"#!/usr/bin/python3\n", 0o700)
        bridge_plan = {"format":m.BRIDGE_MARKER,"uid": self.uid, "gid": self.gid, "user": "demo", "home": self.account.pw_dir,
                       "entrypoint": "module", "port": 8765, "repo": str(repo), "workspace": str(repo),
                       "herdr_bin":str(self.base/"herdr-not-executed")}
        self.write(repo/"src/gpt_agent_bridge/__init__.py",b'"""Inert synthetic package."""\n',0o644)
        self.write(m.BRIDGE_RUNNER,b"# synthetic known Bridge loader\n",0o644)
        self.write(m.BRIDGE_UNIT_FILE,b"# synthetic known Bridge unit\n",0o644)
        manifest={"format":m.BRIDGE_MARKER,"plan":bridge_plan,
                  "unit_sha256":hashlib.sha256(m.BRIDGE_UNIT_FILE.read_bytes()).hexdigest(),
                  "runner_sha256":hashlib.sha256(m.BRIDGE_RUNNER.read_bytes()).hexdigest()}
        self.write(m.BRIDGE_MANIFEST, json.dumps(manifest).encode(), 0o644)
        self.write(m.BRIDGE_SETTINGS, json.dumps({**bridge_plan, "token": "z" * 40}).encode())
        return bridge_plan

    def refused(self, code, fn, *args):
        with self.assertRaises(m.Refusal) as caught:
            fn(*args)
        self.assertEqual(caught.exception.code, code)

    def test_plan_no_services_credentials_version_or_writes(self):
        args = types.SimpleNamespace(user="demo", client=str(self.client), client_sha256=self.plan["client_sha256"],
                                     health_socket="health.sock", ttl="10m", bridge_wait_seconds=3)
        with mock.patch.object(m.subprocess, "run", side_effect=AssertionError("execution forbidden")), \
                mock.patch.object(m, "read_json", side_effect=AssertionError("credentials forbidden")):
            self.assertEqual(m.make_plan(args), self.plan)
        self.assertEqual(self.calls, [])
        self.assertFalse(m.LIB.exists())

    def test_pin_digest_mismatch(self):
        args = types.SimpleNamespace(user="demo", client=str(self.client), client_sha256="0"*64,
                                     health_socket="health.sock", ttl="10m", bridge_wait_seconds=3)
        self.refused("client_digest", m.make_plan, args)

    def test_client_symlink_rejected(self):
        link = self.base / "linked-client"
        link.symlink_to(self.client)
        self.refused("unsafe_file", m.digest, link, {self.uid})

    def test_binary_parent_write_rejected(self):
        folder = self.base / "writable"
        folder.mkdir(mode=0o777)
        folder.chmod(0o777)
        self.write(folder / "client", b"x")
        self.refused("unsafe_directory", m.digest, folder / "client", {self.uid})

    def test_install_disabled_stopped_and_no_bridge_action(self):
        self.installed()
        verbs = [argv[1] for argv in self.calls]
        self.assertNotIn("enable", verbs)
        self.assertNotIn("start", verbs)
        self.assertTrue(m.MANIFEST.exists())
        self.assertFalse(m.CREDENTIALS.exists())
        self.assertEqual(m.record()["plan"], self.plan)

    def test_unit_no_dependency_start_or_herdr(self):
        unit = m.render_unit(self.plan, TEMPLATE.read_text()).decode()
        self.assertIn("After=gpt-agent-bridge-autostart.service network-online.target", unit)
        for forbidden in ["Wants=", "Requires=", "BindsTo=", "herdr", "Environment=", "key", "token"]:
            self.assertNotIn(forbidden, unit)
        for expected in ["User=demo", f"Group={self.gid}", "StandardOutput=null", "StandardError=null", "LimitCORE=0", "StartLimitIntervalSec=0"]:
            self.assertIn(expected, unit)

    def test_foreign_unit_refused(self):
        self.props["FragmentPath"] = "/foreign.service"
        self.refused("foreign_unit", m.install, self.plan)
        self.assertFalse(m.LIB.exists())

    def test_existing_lib_not_overwritten(self):
        self.write(m.LIB / "unknown", b"keep")
        self.refused("existing_installation", m.install, self.plan)
        self.assertEqual((m.LIB / "unknown").read_bytes(), b"keep")

    def test_stale_boot_link_refused(self):
        link = m.UNIT_FILE.parent / "multi-user.target.wants" / m.UNIT
        link.parent.mkdir(mode=0o700)
        link.symlink_to("/missing.service")
        self.refused("foreign_activation", m.install, self.plan)

    def test_inherited_dropin_refused(self):
        self.props["DropInPaths"] = "/etc/systemd/system/service.d/inherited.conf"
        self.refused("foreign_unit", m.install, self.plan)

    def test_local_dropin_refused(self):
        (m.UNIT_FILE.parent / (m.UNIT + ".d")).mkdir(mode=0o700)
        self.refused("foreign_activation", m.install, self.plan)

    def test_enable_start_separate_and_stop(self):
        self.provisioned()
        m.lifecycle("enable")
        self.assertEqual(self.props["ActiveState"], "inactive")
        m.lifecycle("start")
        self.assertEqual(self.props["ActiveState"], "active")
        m.lifecycle("stop")
        self.assertEqual(self.props["ActiveState"], "inactive")
        self.assertEqual(self.calls[-1], [m.SYSTEMCTL, "stop", m.UNIT])

    def test_enable_without_credentials_refused(self):
        self.installed()
        with self.assertRaises(FileNotFoundError):
            m.lifecycle("enable")
        self.assertNotIn("enable", [a[1] for a in self.calls])

    def test_unknown_dropin_after_install_refused(self):
        self.provisioned()
        self.props["DropInPaths"] = "/unknown/dropin"
        self.refused("foreign_unit", m.lifecycle, "enable")

    def test_changed_runner_refused(self):
        self.installed()
        m.RUNNER.write_bytes(b"different")
        self.refused("installation_changed", m.record)

    def test_manifest_duplicate_keys_refused(self):
        self.installed()
        m.MANIFEST.write_text('{"format":"a","format":"b"}')
        self.refused("duplicate_json_key", m.record)

    def test_uninstall_preserves_credentials(self):
        self.provisioned()
        original = m.CREDENTIALS.read_bytes()
        result = m.lifecycle("uninstall")
        self.assertEqual(result["credentials"], "preserved")
        self.assertEqual(m.CREDENTIALS.read_bytes(), original)
        self.assertFalse(m.UNIT_FILE.exists())

    def test_uninstall_unknown_file_refused(self):
        self.provisioned()
        self.write(m.LIB / "unknown", b"keep")
        self.refused("unknown_installation_files", m.lifecycle, "uninstall")
        self.assertTrue(m.UNIT_FILE.exists())

    def test_active_uninstall_refused(self):
        self.provisioned()
        self.props["ActiveState"] = "active"
        self.refused("uninstall_active", m.lifecycle, "uninstall")

    def test_id_exact_charset(self):
        for value in ["tunnel_"+"A"*32, "tunnel_"+"a"*31, "tunnel_"+"a"*33,
                      "tunnel_"+"a"*31+"_", "tunnel_"+"a"*32+"\n", " tunnel_"+"a"*32,
                      "tunnel_"+"é"*32, "https://example.invalid/tunnel_"+"a"*32]:
            with self.subTest(value=value):
                self.refused("invalid_tunnel_id", m.validate_credentials, {**self.secrets,"tunnel_id":value})
        self.assertEqual(m.validate_credentials(self.secrets), self.secrets)

    def test_runtime_key_control_whitespace_refused(self):
        for key in ["", "short", " "*20, "a"*20+"\n", "x"*20+"é", "x"*4097]:
            self.refused("invalid_runtime_key", m.validate_credentials, {**self.secrets, "runtime_api_key":key})

    def test_credentials_file_copy_only_owner_private(self):
        self.installed()
        source = self.base / "private/input.json"
        self.write(source, json.dumps(self.secrets).encode())
        m.configure(str(source))
        self.assertEqual(json.loads(m.CREDENTIALS.read_text()), self.secrets)
        self.assertEqual(stat.S_IMODE(m.CREDENTIALS.stat().st_mode), 0o600)
        self.assertNotIn(self.secrets["runtime_api_key"], m.MANIFEST.read_text())

    def test_configure_no_overwrite(self):
        self.provisioned()
        self.refused("credentials_exist", m.configure)

    def test_non_tty_refused_without_getpass(self):
        self.installed()
        with mock.patch.object(m.sys.stdin, "isatty", return_value=False), \
                mock.patch.object(m.getpass, "getpass", side_effect=AssertionError("prompt forbidden")):
            self.refused("private_tty_required", m.configure)

    def test_getpass_warning_fail_closed(self):
        self.installed()
        def warning(*args):
            import warnings
            warnings.warn("synthetic", m.getpass.GetPassWarning)
        with mock.patch.object(m.sys.stdin,"isatty",return_value=True), \
                mock.patch.object(m.sys.stderr,"isatty",return_value=True), \
                mock.patch.object(m.getpass,"getpass",side_effect=warning):
            with self.assertRaises(m.getpass.GetPassWarning):
                m.configure()
        self.assertFalse(m.CREDENTIALS.exists())

    def test_wrong_version_rejected_nonroot(self):
        self.write(self.client,b"#!/usr/bin/python3\nprint('v0.0.17')\n",0o700)
        self.plan["client_sha256"] = hashlib.sha256(self.client.read_bytes()).hexdigest()
        self.refused("client_version", m.verify_client, self.plan)

    def test_version_never_executed_as_root(self):
        with mock.patch.object(m.os,"geteuid",return_value=0), \
                mock.patch.object(m.subprocess,"run",side_effect=AssertionError("root execution")):
            self.refused("nonroot_version_observation_required",m.verify_client,self.plan)

    def test_credentials_symlink_hardlink_permissions_owner(self):
        p = self.base / "private/settings.json"
        self.write(p,json.dumps(self.secrets).encode())
        link = p.parent / "link"
        link.symlink_to(p)
        self.refused("unsafe_file",m.read_json,link,{self.uid},0o600,True)
        link.unlink()
        os.link(p,link)
        self.refused("unsafe_file",m.read_json,p,{self.uid},0o600,True)
        link.unlink()
        p.chmod(0o644)
        self.refused("file_mode",m.read_json,p,{self.uid},0o600,True)
        p.chmod(0o600)
        self.refused("unsafe_directory",m.read_json,p,{self.uid+100},0o600,True)

    def test_settings_parent_symlink_refused(self):
        p = self.base / "private/settings.json"
        self.write(p,b"{}")
        parent = self.base / "alias"
        parent.symlink_to(p.parent,target_is_directory=True)
        self.refused("unsafe_directory",m.read_json,parent/p.name,{self.uid},0o600,True)

    def test_read_identity_race_refused(self):
        p = self.base / "private/value"
        self.write(p,b"original")
        actual_read = m.os.read
        def raced(fd,limit):
            data = actual_read(fd,limit)
            p.write_bytes(b"changed")
            return data
        with mock.patch.object(m.os,"read",side_effect=raced):
            self.refused("file_race",m.read_file,p,{self.uid},0o600,True)

    def test_existing_bridge_token_exact_no_duplicate_url(self):
        self.provisioned()
        self.bridge()
        value = m.bridge_contract(self.plan)
        self.assertEqual(value["url"],"http://127.0.0.1:8765/mcp/"+"z"*40)
        self.assertNotIn("z"*40,m.CREDENTIALS.read_text())
        self.assertNotIn("MCP_SERVER_URL",m.MANIFEST.read_text())

    def test_bridge_contract_owner_and_token_mismatch(self):
        self.provisioned()
        self.bridge()
        value = json.loads(m.BRIDGE_SETTINGS.read_text())
        value["uid"] += 1
        m.BRIDGE_SETTINGS.write_text(json.dumps(value))
        self.refused("bridge_contract_mismatch",m.bridge_contract,self.plan)

    def test_bridge_no_token_in_manifest_contract(self):
        self.provisioned()
        self.bridge()
        value = json.loads(m.BRIDGE_MANIFEST.read_text())
        value["plan"]["token"] = "z"*40
        m.BRIDGE_MANIFEST.write_text(json.dumps(value))
        self.refused("bridge_contract_mismatch",m.bridge_contract,self.plan)

    def test_minimal_env_excludes_host_fallback_profile_proxy(self):
        with mock.patch.dict(os.environ,{"OPENAI_API_KEY":"host-secret","CONTROL_PLANE_API_KEY":"host-key",
                                       "TUNNEL_CLIENT_PROFILE":"private-profile","HTTP_PROXY":"private-proxy","PYTHONPATH":"bad"}):
            env = m.client_environment(self.plan,{"url":"synthetic-loopback"},self.secrets)
        self.assertEqual(set(env),{"HOME","PATH","LANG","CONTROL_PLANE_TUNNEL_ID","CONTROL_PLANE_API_KEY",
                                   "MCP_SERVER_URL","HEALTH_UNIX_SOCKET","MCP_CONNECTION_MAX_TTL"})
        self.assertEqual(env["CONTROL_PLANE_API_KEY"],self.secrets["runtime_api_key"])

    def test_pending_bridge_then_ready(self):
        now = [0]
        probe = mock.Mock(side_effect=[False,False,True])
        m.wait_bridge({},self.plan,probe,lambda:now[0],lambda n:now.__setitem__(0,now[0]+n))
        self.assertEqual(probe.call_count,3)

    def test_bad_bridge_init_timeout_bounded(self):
        now = [0]
        probe = mock.Mock(return_value=False)
        self.refused("bridge_not_ready",m.wait_bridge,{},self.plan,probe,lambda:now[0],lambda n:now.__setitem__(0,now[0]+n))
        self.assertEqual(now[0],3)
        self.assertEqual(probe.call_count,3)

    def test_probe_timeout_transient(self):
        now = [0]
        probe = mock.Mock(side_effect=[subprocess.TimeoutExpired("synthetic",1),True])
        m.wait_bridge({},self.plan,probe,lambda:now[0],lambda n:now.__setitem__(0,now[0]+n))
        self.assertEqual(probe.call_count,2)

    def run_probe_code(self,health,is_error=False):
        events=[]
        class Client:
            def __init__(self,endpoint,mode): events.append(("client",endpoint,mode))
            async def __aenter__(self): events.append("initialized"); return self
            async def __aexit__(self,*args): return False
            async def call_tool(self,name,args):
                events.append(name)
                return types.SimpleNamespace(is_error=is_error,structured_content=health)
        output=io.StringIO()
        previous = logging.root.manager.disable
        self.addCleanup(logging.disable, previous)
        with mock.patch.dict(sys.modules,{"mcp":types.SimpleNamespace(Client=Client)}), \
                mock.patch.object(sys,"stdin",io.StringIO('{"url":"synthetic"}')),contextlib.redirect_stdout(output):
            exec(compile(m.PROBE_CODE,"synthetic-probe","exec"),{})
        return output.getvalue(),events

    def test_initialized_probe_accepts_herdr_unavailable(self):
        result,events=self.run_probe_code({"bridge":"gpt-agent-bridge","ok":True,"herdr":{"status":"unavailable"}})
        self.assertEqual(result,"ready")
        self.assertIn("initialized",events)
        self.assertIn("bridge_health",events)

    def test_initialized_probe_rejects_wrong_result(self):
        self.assertEqual(self.run_probe_code({"bridge":"wrong","ok":True})[0],"invalid")
        self.assertEqual(self.run_probe_code({"bridge":"gpt-agent-bridge","ok":True},True)[0],"invalid")

    def test_probe_url_stdin_only(self):
        with mock.patch.object(m,"package_origin"),mock.patch.object(m,"validate_bridge_tree"), \
                mock.patch.object(m.subprocess,"run",return_value=subprocess.CompletedProcess([],0,b"ready")) as run:
            self.assertTrue(m.probe_bridge({"url":"secret-path-url","python":"/safe/python"},self.plan,2))
        self.assertNotIn("secret-path-url",str(run.call_args.args))
        self.assertIn(b"secret-path-url",run.call_args.kwargs["input"])
        self.assertEqual(run.call_args.kwargs["stderr"],subprocess.DEVNULL)

    def test_runtime_lock_excludes_second_instance(self):
        self.provisioned()
        with m.runtime_lock(self.plan):
            self.refused("duplicate_tunnel",lambda: self.enter_lock())

    def enter_lock(self):
        with m.runtime_lock(self.plan): pass

    def test_foreign_lock_refused(self):
        self.provisioned()
        self.write(m.LOCK,b"unknown")
        self.refused("foreign_lock",self.enter_lock)

    def test_health_socket_conflict_refused(self):
        self.provisioned()
        self.bridge()
        m.RUNTIME.mkdir(mode=0o700)
        self.write(Path(self.plan["health_socket"]),b"foreign")
        with mock.patch.object(m,"verify_client"),mock.patch.object(m,"wait_bridge") as wait:
            self.refused("health_socket_conflict",m.runtime)
        wait.assert_not_called()

    def test_runtime_wait_then_inert_launch(self):
        self.provisioned()
        self.bridge()
        m.RUNTIME.mkdir(mode=0o700)
        events=[]
        def wait(*args): events.append("wait")
        def launch(plan,env):
            events.append("launch")
            self.assertEqual(env["MCP_SERVER_URL"],"http://127.0.0.1:8765/mcp/"+"z"*40)
            return 1
        with mock.patch.object(m,"wait_bridge",side_effect=wait),mock.patch.object(m,"launch_client",side_effect=launch):
            self.assertEqual(m.runtime(),1)
        self.assertEqual(events,["wait","launch"])

    def test_synthetic_real_subprocess_only_env_and_run_argv(self):
        output=self.base/"observed.json"
        script="#!/usr/bin/python3\nimport json,os,sys\nfrom pathlib import Path\nPath("+repr(str(output))+").write_text(json.dumps({'argv':sys.argv[1:],'env':dict(os.environ)}))\nprint('synthetic secret to stdout')\nprint('synthetic secret to stderr',file=sys.stderr)\n"
        self.write(self.client,script.encode(),0o700)
        env=m.client_environment(self.plan,{"url":"synthetic-url"},self.secrets)
        captured=io.StringIO()
        with contextlib.redirect_stdout(captured):
            self.assertEqual(m.launch_client(self.plan,env),1)
        observed=json.loads(output.read_text())
        self.assertEqual(observed["argv"],["run"])
        # Python's inert stand-in may add LC_CTYPE; the parent passes exact env.
        self.assertEqual({k:v for k,v in observed["env"].items() if k!="LC_CTYPE"},env)
        self.assertEqual(captured.getvalue(),"")

    def test_redaction_main_exception_and_bad_argv(self):
        for args,patch in [(["--unknown-secret=DO-NOT-PRINT"],contextlib.nullcontext()),
                           (["status"],mock.patch.object(m,"status",side_effect=RuntimeError("DO-NOT-PRINT")))]:
            output=io.StringIO()
            with patch,contextlib.redirect_stdout(output),contextlib.redirect_stderr(output):
                self.assertNotEqual(m.main(args),0)
            self.assertNotIn("DO-NOT-PRINT",output.getvalue())

    def test_atomic_publication_no_clobber(self):
        p=self.base/"existing"
        self.write(p,b"keep")
        with self.assertRaises(FileExistsError): m.publish_file(p,b"replace",0o600)
        self.assertEqual(p.read_bytes(),b"keep")
        self.assertEqual(list(self.base.glob('.tunnel-stage-*')),[])

    def test_publish_preserves_replaced_staging_object(self):
        target=self.base/"new"
        actual_link=m.os.link
        replacement=[]
        def raced(source,dest,**kwargs):
            source=Path(source)
            source.unlink()
            self.write(source,b"unknown")
            replacement.append(source)
            raise OSError("synthetic failure")
        with mock.patch.object(m.os,"link",side_effect=raced):
            with self.assertRaises(OSError): m.publish_file(target,b"ours",0o600)
        self.assertEqual(replacement[0].read_bytes(),b"unknown")

    def test_hup_term_recorded_not_reentrant(self):
        with self.assertRaises(m.Refusal):
            with m.interrupts() as checkpoint:
                checkpoint()
                signal.raise_signal(signal.SIGHUP)
                signal.raise_signal(signal.SIGTERM)
                self.refused("interrupted_install",checkpoint)

    def test_hup_during_stage_cleanup_owned_only(self):
        original=m.publish_file
        def hup(target,data,mode):
            original(target,data,mode)
            signal.raise_signal(signal.SIGHUP)
            signal.raise_signal(signal.SIGHUP)
        with mock.patch.object(m,"publish_file",side_effect=hup):
            self.refused("interrupted_install",m.install,self.plan)
        self.assertFalse(m.LIB.exists())
        self.assertEqual(list(m.LIB.parent.glob('.tunnel-review-*')),[])

    def test_partial_publication_preserved_no_blind_retry(self):
        original=m.publish_file
        def fail(target,data,mode):
            if target==m.UNIT_FILE: raise OSError("synthetic failure")
            original(target,data,mode)
        with mock.patch.object(m,"publish_file",side_effect=fail),mock.patch.object(m.os,"chown"):
            with self.assertRaises(m.Refusal) as caught: m.install(self.plan)
        self.assertEqual(caught.exception.code,"installation_not_completed")
        self.assertEqual(caught.exception.stage,"publish_unit")
        self.assertTrue(m.RUNNER.exists())
        self.refused("existing_installation",m.install,self.plan)

    def test_status_never_claims_web_ready(self):
        self.provisioned()
        self.props["ActiveState"]="active"
        output=m.status()
        self.assertEqual(output["web_ready"],"not_established")
        self.assertEqual(output["work_resume"],"not_established")
        self.assertNotIn(self.secrets["tunnel_id"],json.dumps(output))

    def test_invalid_socket_and_owner_plan(self):
        for changes in [{"health_socket":str(self.base/"elsewhere.sock")},{"uid":0},
                        {"ttl":"0s"},{"bridge_wait_seconds":0},{"client_version":"v0.0.17"}]:
            with self.assertRaises(m.Refusal): m.validate_plan({**self.plan,**changes})

    def test_privileged_snapshot_refuses_nonroot(self):
        with mock.patch.object(m.os,"geteuid",return_value=self.uid):
            self.refused("root_required",ORIGINAL_TRUSTED_SNAPSHOT)

    def test_snapshot_mode_refuses_root_execution_of_user_code(self):
        snapshot=self.base/"review/installer.py"
        self.write(snapshot,b"# synthetic",0o644)
        self.write(snapshot.parent/"service.template",TEMPLATE.read_bytes(),0o600)
        with mock.patch.object(m.os,"geteuid",return_value=0),mock.patch.object(m,"__file__",str(snapshot)):
            self.refused("file_mode",ORIGINAL_TRUSTED_SNAPSHOT)

    def test_symlink_wants_directory_refused_before_install(self):
        other=self.base/"other"
        other.mkdir(mode=0o700)
        (m.UNIT_FILE.parent/"multi-user.target.wants").symlink_to(other,target_is_directory=True)
        self.refused("unsafe_directory",m.install,self.plan)

    def test_start_without_credentials_has_no_effect(self):
        self.installed()
        with self.assertRaises(FileNotFoundError): m.lifecycle("start")
        self.assertNotIn("start",[a[1] for a in self.calls])

    def test_client_version_env_contains_no_credentials(self):
        with mock.patch.object(m.subprocess,"run",return_value=subprocess.CompletedProcess([],0,b"v0.0.16\n")) as run:
            m.verify_client(self.plan)
        self.assertEqual(run.call_args.args[0],[str(self.client),"--version"])
        self.assertEqual(set(run.call_args.kwargs["env"]),{"HOME","PATH","LANG"})

    def test_health_discards_raw_endpoint_and_key(self):
        self.provisioned()
        m.RUNTIME.mkdir(mode=0o700)
        health=Path(self.plan["health_socket"])
        sock=socket.socket(socket.AF_UNIX,socket.SOCK_STREAM)
        self.addCleanup(sock.close)
        sock.bind(str(health))
        response=types.SimpleNamespace(status=200,read=lambda n:b"secret raw endpoint runtime key")
        connection=mock.Mock()
        connection.getresponse.return_value=response
        with mock.patch.object(m,"UnixHTTP",return_value=connection):
            value=m.health_status(self.plan)
        self.assertEqual(value["tunnel_startup"],"ready")
        self.assertEqual(value["control_plane"],"not_verified")
        self.assertNotIn("secret",json.dumps(value))

    def test_term_during_staging_is_bounded_and_cleanup_safe(self):
        original=m.publish_file
        def term(target,data,mode):
            original(target,data,mode)
            signal.raise_signal(signal.SIGTERM)
        with mock.patch.object(m,"publish_file",side_effect=term):
            self.refused("interrupted_install",m.install,self.plan)
        self.assertEqual(list(m.LIB.parent.glob('.tunnel-review-*')),[])

    def test_install_library_permissions_ignore_restrictive_umask(self):
        previous=os.umask(0o077)
        try:
            self.installed()
        finally:
            os.umask(previous)
        self.assertEqual(stat.S_IMODE(m.LIB.stat().st_mode),0o755)
        self.assertEqual(stat.S_IMODE(m.RUNNER.stat().st_mode),0o644)

    def test_help_has_success_exit(self):
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(m.main(["--help"]),0)

    def test_setuid_client_refused_without_execution(self):
        self.client.chmod(0o4700)
        self.refused("unsafe_file",m.check_client,self.plan)

    def test_capability_client_refused_without_execution(self):
        with mock.patch.object(m.os,"getxattr",return_value=b"synthetic-capability"):
            self.refused("privileged_client",m.check_client,self.plan)

    # Independent HOLD reproductions: these intentionally fail on the first
    # 64-test implementation before repairs. Fixtures only, no host services.
    def test_review_health_ok_must_be_boolean_true(self):
        for ok in (False, None, 1, "true"):
            health={"bridge":"gpt-agent-bridge","ok":ok,"herdr":{"status":"unavailable"}}
            self.assertNotEqual(self.run_probe_code(health)[0],"ready")
        self.assertNotEqual(self.run_probe_code({"bridge":"gpt-agent-bridge"})[0],"ready")

    def test_review_writable_dependency_pth_refused_before_probe(self):
        self.provisioned()
        self.bridge()
        p=self.base/"repo/.venv/lib/python3.10/site-packages/unsafe.pth"
        self.write(p,b"# synthetic dependency hook\n",0o666)
        with mock.patch.object(m.subprocess,"run",side_effect=AssertionError("must refuse before subprocess")):
            with self.assertRaises(m.Refusal): m.bridge_contract(self.plan)

    def test_review_official_build_metadata_version_accepted(self):
        version=b"0.0.16+123456789abcdef (git sha: 123456789abcdef)\n"
        with mock.patch.object(m.subprocess,"run",return_value=subprocess.CompletedProcess([],0,version)):
            m.verify_client(self.plan)

    def test_review_disk_inherited_service_dropin_before_publication(self):
        self.write(m.UNIT_FILE.parent/"service.d/foreign.conf",b"[Service]\n",0o644)
        with self.assertRaises(m.Refusal): self.installed()
        self.assertFalse(m.RUNNER.exists())

    def test_review_document_fences_explicit_failstop(self):
        import re
        doc=(SOURCE.parent.parent/"docs/AUTOSTART.md").read_text()
        fences = re.findall(r'^```bash\n(.*?)^```',doc,re.M|re.S)
        fences = [f for f in fences if re.search(r"^# gate: component-tunnel-[a-z-]+$", f, re.M)]
        self.assertEqual(len(fences), 7)
        for fence in fences:
            self.assertIn("set -euo pipefail",fence)
            self.assertIn("|| exit 1",fence)

    def test_review_uninstall_preserves_replaced_runner(self):
        self.provisioned()
        original_unlink=Path.unlink
        injected=[]
        def replacing(path,*args,**kwargs):
            if Path(path)==m.UNIT_FILE or (Path(path).name==m.UNIT_FILE.name and Path(path).parent.parent==m.UNIT_FILE.parent):
                old=m.RUNNER.with_name("replaced-old")
                m.RUNNER.rename(old)
                self.write(m.RUNNER,b"unknown replacement",0o644)
                injected.append(True)
            return original_unlink(path,*args,**kwargs)
        with mock.patch.object(Path,"unlink",autospec=True,side_effect=replacing):
            with self.assertRaises(m.Refusal): m.lifecycle("uninstall")
        self.assertTrue(injected)
        self.assertEqual(m.RUNNER.read_bytes(),b"unknown replacement")

    def test_review_final_manager_signal_never_success(self):
        original=m.managed_properties
        def signaled():
            result=original()
            signal.raise_signal(signal.SIGHUP)
            return result
        with mock.patch.object(m,"managed_properties",side_effect=signaled):
            with self.assertRaises(m.Refusal): self.installed()
        self.assertTrue(m.MANIFEST.exists())

    def test_review_runtime_key_punctuation_refused(self):
        for punctuation in ("!", ".", ":", "/", "=", "\\", "'"):
            with self.assertRaises(m.Refusal):
                m.validate_credentials({**self.secrets,"runtime_api_key":"synthetic-key-123"+punctuation})

    def test_source_or_site_packages_write_bits_refuse_before_execution(self):
        self.provisioned()
        self.bridge()
        candidates=[self.base/"repo/src/gpt_agent_bridge/unsafe.py",
                    self.base/"repo/.venv/lib/python3.10/site-packages/unsafe.pth"]
        for path in candidates:
            self.write(path,b"# harmless fixture\n",0o644)
            for mode in (0o664,0o666):
                path.chmod(mode)
                with mock.patch.object(m.subprocess,"run",side_effect=AssertionError("unsafe execution")):
                    self.refused("unsafe_bridge_tree",m.bridge_contract,self.plan)
            path.chmod(0o644)
        parent=candidates[-1].parent
        parent.chmod(0o775)
        self.refused("unsafe_bridge_tree",m.bridge_contract,self.plan)

    def test_foreign_owned_dependency_refused(self):
        self.provisioned()
        self.bridge()
        unsafe=self.base/"repo/.venv/lib/python3.10/site-packages/foreign.pth"
        self.write(unsafe,b"# fixture\n",0o644)
        original=os.scandir
        @contextlib.contextmanager
        def scan(folder):
            with original(folder) as entries:
                result=[]
                for entry in entries:
                    if Path(entry.path)==unsafe:
                        result.append(types.SimpleNamespace(name=entry.name,path=entry.path,
                          stat=lambda follow_symlinks=False:types.SimpleNamespace(st_uid=self.uid+77,
                            st_mode=stat.S_IFREG|0o644,st_nlink=1)))
                    else: result.append(entry)
                yield iter(result)
        with mock.patch.object(m.os,"scandir",side_effect=scan), \
                mock.patch.object(m.subprocess,"run",side_effect=AssertionError("unsafe execution")):
            self.refused("unsafe_bridge_tree",m.bridge_contract,self.plan)

    def test_external_dependency_symlink_refused(self):
        self.provisioned()
        self.bridge()
        target=self.base/"outside.py"
        self.write(target,b"# outside fixture\n",0o644)
        (self.base/"repo/src/gpt_agent_bridge/escape.py").symlink_to(target)
        self.refused("external_bridge_symlink",m.bridge_contract,self.plan)

    def test_internal_venv_symlink_safe_python_and_inert_init(self):
        self.provisioned()
        self.bridge()
        repo=self.base/"repo"
        (repo/".venv/lib").mkdir(mode=0o700)
        (repo/".venv/lib64").symlink_to("lib",target_is_directory=True)
        (repo/".venv/bin/python3").symlink_to("python")
        m.bridge_contract(self.plan)
        self.write(repo/"src/gpt_agent_bridge/__init__.py",b"import server\n",0o644)
        self.refused("bridge_initializer_not_inert",m.bridge_contract,self.plan)

    def test_bridge_tree_count_limit(self):
        self.provisioned()
        self.bridge()
        with mock.patch.object(m,"MAX_TREE_ENTRIES",2):
            self.refused("bridge_tree_limit",m.bridge_contract,self.plan)

    def test_package_origin_exact_and_revalidated_before_each_probe(self):
        self.provisioned()
        self.bridge()
        bridge=m.bridge_contract(self.plan)
        with mock.patch.object(m.subprocess,"run",return_value=subprocess.CompletedProcess([],0,b"origin_invalid")):
            self.refused("bridge_package_origin",m.package_origin,bridge,self.plan,2)
        with mock.patch.object(m.subprocess,"run",side_effect=[subprocess.CompletedProcess([],0,b"origin_valid"),
                                                               subprocess.CompletedProcess([],0,b"ready")]) as run:
            self.assertTrue(m.probe_bridge(bridge,self.plan,4))
        self.assertEqual(run.call_count,2)
        self.assertNotIn(bridge["url"],str(run.call_args_list[0]))
        unsafe=self.base/"repo/.venv/lib/python3.10/site-packages/raced.pth"
        self.write(unsafe,b"# changed after enrollment\n",0o666)
        with mock.patch.object(m.subprocess,"run",side_effect=AssertionError("unsafe execution")):
            self.refused("unsafe_bridge_tree",m.probe_bridge,bridge,self.plan,4)

    def test_malformed_health_is_permanent_no_retry(self):
        probe=mock.Mock(side_effect=m.Refusal("bridge_health_invalid"))
        self.refused("bridge_health_invalid",m.wait_bridge,{},self.plan,probe)
        self.assertEqual(probe.call_count,1)
        with mock.patch.object(m,"runtime",side_effect=m.Refusal("bridge_health_invalid")), \
                contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(m.main(["run"]),78)

    def test_version_parser_exact_consistent_sha_forms(self):
        good=[b"0.0.16\n",b"v0.0.16\n",b"0.0.16+abcdef1234567 (git sha: abcdef1234567)\n",
              b"0.0.16+"+b"a"*40+b" (git sha: "+b"a"*40+b")\n"]
        bad=[b"0.0.17\n",b"0.0.160\n",b"0.0.16+arbitrary\n",b"0.0.16+abcdef1 (git sha: abcdef2)\n",
             b"0.0.16+abcdef\n",b"0.0.16+abcdef1.extra\n",b"0.0.16-dirty\n",b"0.0.16\n\n"]
        for value in good:
            with mock.patch.object(m.subprocess,"run",return_value=subprocess.CompletedProcess([],0,value)):
                m.verify_client(self.plan)
        for value in bad:
            with mock.patch.object(m.subprocess,"run",return_value=subprocess.CompletedProcess([],0,value)):
                self.refused("client_version",m.verify_client,self.plan)

    def test_unknown_unit_path_failclosed_before_publish(self):
        original=self.fake_call
        def call(argv,allowed=(0,)):
            if "--property=UnitPath" in argv: return subprocess.CompletedProcess(argv,0,b"")
            return original(argv,allowed)
        with mock.patch.object(m,"call",side_effect=call):
            self.refused("unknown_unit_path",m.install,self.plan)
        self.assertFalse(m.LIB.exists())

    def test_manager_only_path_dropin_refused(self):
        extra=self.base/"extra-manager-path"
        self.write(extra/"service.d/inherited.conf",b"[Service]\n",0o644)
        original=self.fake_call
        def call(argv,allowed=(0,)):
            if "--property=UnitPath" in argv:
                return subprocess.CompletedProcess(argv,0," ".join(str(p) for p in (*m.SYSTEMD_ROOTS,extra)).encode())
            return original(argv,allowed)
        with mock.patch.object(m,"call",side_effect=call):
            self.refused("foreign_activation",m.install,self.plan)
        self.assertFalse(m.RUNNER.exists())

    def test_dash_prefix_dropin_and_alias_refused(self):
        directory=m.UNIT_FILE.parent/"gpt-agent-.service.d"
        directory.mkdir(mode=0o700)
        self.refused("foreign_activation",m.install,self.plan)
        directory.rmdir()
        alias=m.UNIT_FILE.parent/"other.service"
        alias.symlink_to(m.UNIT_FILE)
        self.refused("foreign_activation",m.install,self.plan)

    def test_uninstall_hardlink_replacement_preserved(self):
        self.provisioned()
        original=Path.unlink
        injected=[]
        def replace(path,*args,**kwargs):
            if Path(path).name==m.UNIT_FILE.name:
                os.link(m.RUNNER,self.base/"extra-link")
                injected.append(True)
            return original(path,*args,**kwargs)
        with mock.patch.object(Path,"unlink",autospec=True,side_effect=replace):
            self.refused("uninstall_identity_changed",m.lifecycle,"uninstall")
        self.assertTrue(injected)
        self.assertTrue(m.RUNNER.exists())

    def test_uninstall_replacement_during_rename_quarantined_not_deleted(self):
        self.provisioned()
        original=m.os.rename
        changed=[]
        def race(source,target):
            if Path(source)==m.RUNNER:
                original(source,self.base/"original-runner")
                self.write(Path(source),b"unknown raced replacement",0o644)
                changed.append(Path(target))
            return original(source,target)
        with mock.patch.object(m.os,"rename",side_effect=race):
            self.refused("uninstall_identity_changed",m.lifecycle,"uninstall")
        self.assertEqual(changed[0].read_bytes(),b"unknown raced replacement")

    def final_signal(self,sig):
        original=m.managed_properties
        def signaled():
            result=original()
            signal.raise_signal(sig)
            return result
        with mock.patch.object(m,"managed_properties",side_effect=signaled):
            self.refused("interrupted_install",self.installed)
        self.assertTrue(m.MANIFEST.exists())

    def test_final_readback_term(self): self.final_signal(signal.SIGTERM)
    def test_final_readback_int(self): self.final_signal(signal.SIGINT)

    def test_signal_during_handler_restore_is_reported(self):
        original=m.signal.signal
        injected=[]
        def restoring(sig,handler):
            result=original(sig,handler)
            if sig==signal.SIGTERM and handler==signal.SIG_DFL:
                signal.raise_signal(signal.SIGTERM)
                injected.append(True)
            return result
        with mock.patch.object(m.signal,"signal",side_effect=restoring):
            with self.assertRaises(m.Refusal):
                with m.interrupts(): pass
        self.assertTrue(injected)

    def test_invalid_key_configure_and_runtime_exit78(self):
        self.installed()
        invalid={**self.secrets,"runtime_api_key":"synthetic-key-with!"}
        source=self.base/"private/input.json"
        self.write(source,json.dumps(invalid).encode())
        self.refused("invalid_runtime_key",m.configure,str(source))
        self.assertFalse(m.CREDENTIALS.exists())
        self.write(m.CREDENTIALS,json.dumps(invalid).encode())
        self.bridge()
        with mock.patch.object(m.subprocess,"run",side_effect=AssertionError("must not launch")), \
                contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(m.main(["run"]),78)
        self.assertEqual(json.loads(output.getvalue())["reason"], "invalid_runtime_key")
        self.assertNotIn(invalid["runtime_api_key"],output.getvalue())
        m.validate_credentials({**self.secrets,"runtime_api_key":"Abc_123-"*4})

    def test_exact_bridge_schema_provenance_before_token_read(self):
        self.provisioned()
        self.bridge()
        m.BRIDGE_RUNNER.write_bytes(b"corrupted known loader")
        original=m.read_json
        def no_token(path,*args,**kwargs):
            if Path(path)==m.BRIDGE_SETTINGS: raise AssertionError("token must remain unread")
            return original(path,*args,**kwargs)
        with mock.patch.object(m,"read_json",side_effect=no_token):
            self.refused("bridge_installation_changed",m.bridge_contract,self.plan)

    def test_unverified_bridge_format_never_inferred(self):
        self.provisioned()
        self.bridge()
        with mock.patch.object(m,"BRIDGE_MARKER",None):
            self.refused("bridge_format_unverified",m.bridge_contract,self.plan)

    def assert_permanent_run(self, reason, allow_settings=False, allow_credentials=False):
        original = m.read_json
        sensitive = set() if allow_credentials else {m.CREDENTIALS}
        if not allow_settings:
            sensitive.add(m.BRIDGE_SETTINGS)
        observed = []
        def read(path, *args, **kwargs):
            observed.append(Path(path))
            self.assertNotIn(Path(path), sensitive, "must refuse before sensitive read")
            return original(path, *args, **kwargs)
        output, errors = io.StringIO(), io.StringIO()
        with contextlib.ExitStack() as stack:
            stack.enter_context(mock.patch.object(m, "read_json", side_effect=read))
            for name in ("verify_client", "probe_bridge", "launch_client", "validate_credentials"):
                stack.enter_context(mock.patch.object(m, name, side_effect=AssertionError("runtime must not proceed")))
            stack.enter_context(mock.patch.object(m.subprocess, "run", side_effect=AssertionError("no subprocess")))
            stack.enter_context(mock.patch.object(m.subprocess, "Popen", side_effect=AssertionError("no child")))
            stack.enter_context(contextlib.redirect_stdout(output))
            stack.enter_context(contextlib.redirect_stderr(errors))
            self.assertEqual(m.main(["run"]), 78)
        self.assertEqual(json.loads(output.getvalue()),
                         {"result": "refused", "reason": reason, "stage": None,
                          "retry": "operator_review_required"})
        self.assertEqual(errors.getvalue(), "")
        for value in (self.secrets["runtime_api_key"], self.secrets["tunnel_id"], "z" * 40):
            self.assertNotIn(value, output.getvalue())
        self.assertTrue(sensitive.isdisjoint(observed))
        return observed

    def replace_json(self, path, value):
        # Keep the already established fixture modes and owner untouched.
        path.write_bytes(json.dumps(value).encode())

    def test_permanent_repro_null_tunnel_plan(self):
        self.provisioned()
        record = json.loads(m.MANIFEST.read_bytes())
        self.replace_json(m.MANIFEST, {**record, "plan": None})
        self.assert_permanent_run("invalid_plan")

    def test_permanent_repro_null_tunnel_client(self):
        self.provisioned()
        record = json.loads(m.MANIFEST.read_bytes())
        self.replace_json(m.MANIFEST, {**record, "plan": {**record["plan"], "client": None}})
        self.assert_permanent_run("invalid_path")

    def test_permanent_repro_null_bridge_repo(self):
        self.provisioned()
        self.bridge()
        record = json.loads(m.BRIDGE_MANIFEST.read_bytes())
        self.replace_json(m.BRIDGE_MANIFEST, {**record, "plan": {**record["plan"], "repo": None}})
        self.assert_permanent_run("invalid_path")

    def test_permanent_tunnel_plan_wrong_containers_and_schema(self):
        self.provisioned()
        record = json.loads(m.MANIFEST.read_bytes())
        variants = [False, 1, "malformed-synthetic-plan", [], [self.plan],
                    {**self.plan, "unknown": True},
                    {k: v for k, v in self.plan.items() if k != "client"}]
        for value in variants:
            with self.subTest(kind=type(value).__name__):
                self.replace_json(m.MANIFEST, {**record, "plan": value})
                self.assert_permanent_run("invalid_plan")

    def test_permanent_tunnel_path_types_and_characters(self):
        self.provisioned()
        record = json.loads(m.MANIFEST.read_bytes())
        variants = [None, False, 42, 1.5, [], {}, "relative", "/bad\0path",
                    "/bad\npath", "/bad\x7fpath", "/bad\u2603path", "/bad\ud800path"]
        for field in ("client", "home", "health_socket"):
            for value in variants:
                with self.subTest(field=field, kind=type(value).__name__):
                    self.replace_json(m.MANIFEST, {**record, "plan": {**self.plan, field: value}})
                    self.assert_permanent_run("invalid_path")

    def test_permanent_tunnel_nested_field_types(self):
        self.provisioned()
        record = json.loads(m.MANIFEST.read_bytes())
        variants = [("uid", True, "invalid_owner"), ("uid", {}, "invalid_owner"),
                    ("gid", False, "invalid_owner"), ("gid", None, "invalid_owner"),
                    ("user", [], "invalid_owner"), ("user", "bad\nuser", "invalid_owner"),
                    ("format", {}, "invalid_plan"), ("client_version", [], "invalid_client_pin"),
                    ("client_sha256", {}, "invalid_client_pin"), ("client_sha256", None, "invalid_client_pin"),
                    ("ttl", {}, "invalid_ttl"), ("ttl", None, "invalid_ttl"),
                    ("bridge_wait_seconds", True, "invalid_wait"), ("bridge_wait_seconds", [], "invalid_wait")]
        for field, value, reason in variants:
            with self.subTest(field=field, reason=reason):
                self.replace_json(m.MANIFEST, {**record, "plan": {**self.plan, field: value}})
                self.assert_permanent_run(reason)

    def test_permanent_missing_account(self):
        self.provisioned()
        with mock.patch.object(m.pwd, "getpwnam", side_effect=KeyError("do not print synthetic username")):
            self.assert_permanent_run("invalid_owner")

    def test_permanent_tunnel_record_hash_types(self):
        self.provisioned()
        record = json.loads(m.MANIFEST.read_bytes())
        for field in ("runner_sha256", "unit_sha256"):
            for value in (None, [], {}, True, "not-a-hash"):
                with self.subTest(field=field, kind=type(value).__name__):
                    self.replace_json(m.MANIFEST, {**record, field: value})
                    self.assert_permanent_run("invalid_manifest")

    def test_permanent_bridge_plan_wrong_containers_and_schema(self):
        self.provisioned()
        self.bridge()
        record = json.loads(m.BRIDGE_MANIFEST.read_bytes())
        variants = [None, False, 1, "malformed-synthetic-plan", [],
                    {**record["plan"], "unknown": True},
                    {k: v for k, v in record["plan"].items() if k != "repo"}]
        for value in variants:
            with self.subTest(kind=type(value).__name__):
                self.replace_json(m.BRIDGE_MANIFEST, {**record, "plan": value})
                self.assert_permanent_run("bridge_contract_mismatch")

    def test_permanent_bridge_path_types_and_characters(self):
        self.provisioned()
        self.bridge()
        record = json.loads(m.BRIDGE_MANIFEST.read_bytes())
        for field in ("repo", "workspace", "herdr_bin"):
            for value in (None, False, 42, [], {}, "relative", "/bad\0path", "/bad\npath",
                          "/bad\x7fpath", "/bad\u2603path", "/bad\ud800path"):
                with self.subTest(field=field, kind=type(value).__name__):
                    self.replace_json(m.BRIDGE_MANIFEST, {**record, "plan": {**record["plan"], field: value}})
                    self.assert_permanent_run("invalid_path")

    def test_permanent_bridge_nested_types_and_hashes(self):
        self.provisioned()
        self.bridge()
        record = json.loads(m.BRIDGE_MANIFEST.read_bytes())
        for field in ("format", "user", "uid", "gid", "home", "port", "entrypoint"):
            for value in (None, [], {}, True):
                with self.subTest(field=field, kind=type(value).__name__):
                    self.replace_json(m.BRIDGE_MANIFEST, {**record, "plan": {**record["plan"], field: value}})
                    self.assert_permanent_run("bridge_contract_mismatch")
        for field in ("runner_sha256", "unit_sha256"):
            for value in (None, [], {}, True, "not-a-hash"):
                with self.subTest(field=field, kind=type(value).__name__):
                    self.replace_json(m.BRIDGE_MANIFEST, {**record, field: value})
                    self.assert_permanent_run("bridge_installation_changed")

    def test_permanent_bridge_settings_types_before_key_read(self):
        self.provisioned()
        self.bridge()
        settings = json.loads(m.BRIDGE_SETTINGS.read_bytes())
        for field in settings:
            for value in (None, [], {}):
                with self.subTest(field=field, kind=type(value).__name__):
                    self.replace_json(m.BRIDGE_SETTINGS, {**settings, field: value})
                    self.assert_permanent_run("bridge_contract_mismatch", allow_settings=True)
        # JSON floats can compare equal to integer account fields. Equality
        # alone must not make an unsupported persisted type acceptable.
        for field in ("uid", "gid", "port"):
            with self.subTest(equal_numeric_field=field):
                self.replace_json(m.BRIDGE_SETTINGS, {**settings, field: float(settings[field])})
                self.assert_permanent_run("bridge_contract_mismatch", allow_settings=True)

    def test_permanent_non_dictionary_json_roots(self):
        self.provisioned()
        self.bridge()
        originals = {p: p.read_bytes() for p in (m.MANIFEST, m.BRIDGE_MANIFEST, m.BRIDGE_SETTINGS)}
        for path in originals:
            for value in (None, False, 1, "malformed-synthetic-record", []):
                with self.subTest(path=path.name, kind=type(value).__name__):
                    self.replace_json(path, value)
                    self.assert_permanent_run("invalid_json", allow_settings=path == m.BRIDGE_SETTINGS)
                    path.write_bytes(originals[path])

    def test_runtime_transient_and_unknown_classification_preserved(self):
        for failure, expected, reason in [(m.Refusal("bridge_not_ready"), 1, "bridge_not_ready"),
                                          (KeyboardInterrupt(), 1, "operation_failed"),
                                          (TypeError("unexpected synthetic bug"), 1, "operation_failed")]:
            with self.subTest(reason=reason), mock.patch.object(m, "runtime", side_effect=failure), \
                    contextlib.redirect_stdout(io.StringIO()) as output:
                self.assertEqual(m.main(["run"]), expected)
                self.assertEqual(json.loads(output.getvalue())["reason"], reason)

    def bounded_depth_json(self, key=None):
        # Fixed historical depth, independent of interpreter recursion limits.
        # Decoders may accept it; a root array is still invalid for every record.
        payload = b'[' * 1100 + b'0' + b']' * 1100
        if key is not None:
            payload = b'{"' + key.encode("ascii") + b'":' + payload + b'}'
        self.assertLess(len(payload), m.LIMIT)
        return payload

    def test_parser_depth_tunnel_manifest_refuses_before_sensitive_reads(self):
        self.provisioned()
        m.MANIFEST.write_bytes(self.bounded_depth_json())
        self.assertEqual(self.assert_permanent_run("invalid_json"), [m.MANIFEST])

    def test_parser_depth_bridge_manifest_refuses_before_sensitive_reads(self):
        self.provisioned()
        self.bridge()
        m.BRIDGE_MANIFEST.write_bytes(self.bounded_depth_json())
        self.assertEqual(self.assert_permanent_run("invalid_json"), [m.MANIFEST, m.BRIDGE_MANIFEST])

    def test_parser_depth_owner_settings_refuses_before_credentials(self):
        self.provisioned()
        self.bridge()
        m.BRIDGE_SETTINGS.write_bytes(self.bounded_depth_json())
        self.assertEqual(self.assert_permanent_run("invalid_json", allow_settings=True),
                         [m.MANIFEST, m.BRIDGE_MANIFEST, m.BRIDGE_SETTINGS])

    def test_parser_depth_credentials_refuses_before_probe_or_child(self):
        self.provisioned()
        self.bridge()
        m.CREDENTIALS.write_bytes(self.bounded_depth_json())
        # This input must be read to classify it; normal synthetic Bridge token
        # read also precedes it. No downstream credential validation/probe/child.
        self.assertEqual(self.assert_permanent_run("invalid_json", allow_settings=True, allow_credentials=True),
                         [m.MANIFEST, m.BRIDGE_MANIFEST, m.BRIDGE_SETTINGS, m.CREDENTIALS])

    def test_historical_deep_plan_real_decoder_and_schema_refusal(self):
        self.provisioned()
        payload = self.bounded_depth_json("plan")
        self.assertEqual(len(payload), 2210)
        try:
            decoded = json.loads(payload, object_pairs_hook=dict)
        except RecursionError:
            reason = "invalid_json"
        else:
            self.assertIsInstance(decoded, dict)
            self.assertIsInstance(decoded["plan"], list)
            reason = "invalid_manifest"
        m.MANIFEST.write_bytes(payload)
        self.assertEqual(self.assert_permanent_run(reason), [m.MANIFEST])

    def test_deep_inputs_both_decoder_outcomes_at_json_loads_only(self):
        self.provisioned()
        self.bridge()
        paths = [m.MANIFEST, m.BRIDGE_MANIFEST, m.BRIDGE_SETTINGS, m.CREDENTIALS]
        originals = {path: path.read_bytes() for path in paths}
        loads = json.loads
        nested = 0
        for _ in range(1100):
            nested = [nested]
        cases = [(path, None, "invalid_json") for path in paths]
        cases.append((m.MANIFEST, "plan", "invalid_manifest"))
        for path, key, accepted_reason in cases:
            payload = self.bounded_depth_json(key)
            for rejected in (False, True):
                with self.subTest(path=path.name, key=key, decoder_rejected=rejected):
                    calls = []
                    def decode(raw, *args, **kwargs):
                        if raw == payload:
                            self.assertTrue(callable(kwargs.get("object_pairs_hook")))
                            calls.append(raw)
                            if rejected:
                                raise RecursionError("synthetic decoder depth fault")
                            return nested if key is None else kwargs["object_pairs_hook"]([("plan", nested)])
                        return loads(raw, *args, **kwargs)
                    path.write_bytes(payload)
                    try:
                        with mock.patch.object(m.json, "loads", side_effect=decode):
                            observed = self.assert_permanent_run(
                                "invalid_json" if rejected else accepted_reason,
                                allow_settings=path in paths[2:], allow_credentials=path == m.CREDENTIALS)
                        self.assertEqual(calls, [payload])
                        self.assertEqual(observed, paths[:paths.index(path) + 1])
                    finally:
                        path.write_bytes(originals[path])

    def assert_unknown_recursion_run(self):
        with contextlib.redirect_stdout(io.StringIO()) as output, \
                contextlib.redirect_stderr(io.StringIO()) as errors:
            self.assertEqual(m.main(["run"]), 1)
        self.assertEqual(json.loads(output.getvalue()),
                         {"result": "not_completed", "reason": "operation_failed",
                          "retry": "operator_review_required"})
        self.assertEqual(errors.getvalue(), "")

    def test_runtime_recursion_outside_parser_remains_unknown(self):
        with mock.patch.object(m, "runtime", side_effect=RecursionError("synthetic fault outside parser")):
            self.assert_unknown_recursion_run()

    def test_file_read_recursion_outside_parser_remains_unknown(self):
        self.provisioned()
        with mock.patch.object(m, "read_file", side_effect=RecursionError("synthetic file reader fault")):
            self.assert_unknown_recursion_run()

    def frozen_bridge_installation(self, production_template=False, tunnel_first=True):
        """Actual hash-pinned writer; host effects stop at a private sandbox.

        Default source is this combined checkout, never a predecessor path.
        An explicit frozen source remains supported, with the same exact digest.
        No installed Bridge settings or source package is loaded.
        """
        selected = os.environ.get("BRIDGE_FROZEN_INSTALLER_SOURCE",
                                  str(SOURCE.parent / "install-bridge-autostart.py"))
        frozen = Path(selected)
        self.assertTrue(frozen.is_absolute())
        self.assertTrue(frozen.is_file() and not frozen.is_symlink())
        source = frozen.read_bytes()
        self.assertEqual(hashlib.sha256(source).hexdigest(),
                         "17ef82d1f6ac15fd91cc5061f187857391117bb06946cf92f30cc61e4668eb12")
        b = types.ModuleType("verified_frozen_bridge_fixture")
        b.__file__ = str(frozen)
        # Frozen top-level code contains only stdlib imports, constants and
        # definitions; its __main__ guard is false here.
        exec(compile(source, "<verified-frozen-bridge-installer>", "exec"), b.__dict__)
        self.assertEqual(b.MARKER, "gpt-agent-bridge-autostart-v1")
        self.assertEqual(m.BRIDGE_MARKER, b.MARKER)

        if tunnel_first:
            self.provisioned()
        repo, target = self.base / "frozen-source", self.base / "demo-target"
        repo.mkdir(mode=0o700)
        target.mkdir(mode=0o700)
        self.write(repo / ".venv/bin/python", b"#!/usr/bin/python3\n", 0o700)
        self.write(repo / "src/gpt_agent_bridge/__init__.py", b'"""Inert synthetic package."""\n', 0o644)
        herdr = self.base / "herdr-inert"
        self.write(herdr, b"#!/bin/false\n", 0o700)
        # Exercise render_unit with a deliberately synthetic, inert template;
        # no other frozen checkout file is opened.
        template = b"[Service]\nUser=@USER@\nWorkingDirectory=@REPO@\nExecStart=@PYTHON@ -I -B @RUNNER@ run\n# settings @CONFIG@\n"
        if production_template:
            template = (SOURCE.parent.parent / "systemd/gpt-agent-bridge-autostart.service.template").read_bytes()
            self.assertEqual(hashlib.sha256(template).hexdigest(), b.TEMPLATE_SHA256)
        self.write(repo / "systemd/gpt-agent-bridge-autostart.service.template", template, 0o644)
        snapshot = self.base / "reviewed-installer.py"
        self.write(snapshot, source, 0o700)
        # setUp created these empty parent directories for independent fixtures.
        # The actual installer insists its own final directories do not exist.
        m.BRIDGE_MANIFEST.parent.rmdir()
        m.BRIDGE_SETTINGS.parent.rmdir()
        owner = types.SimpleNamespace(pw_name="demo", pw_uid=self.uid,
                                      pw_gid=self.gid, pw_dir=self.account.pw_dir)
        calls, checkout_checks, origin_checks = [], [], []

        def host(root=False):
            self.assertTrue(root)

        def check_checkout(path, account):
            self.assertIn(path, (repo, target))
            self.assertIs(account, owner)
            checkout_checks.append(path)

        def check_origin(path, account):
            self.assertEqual(path, repo)
            self.assertIs(account, owner)
            origin_checks.append(path)

        def fake_command(argv, allowed=(0,)):
            calls.append(list(argv))
            if argv[0] == b.ANALYZE:
                self.assertEqual(argv[1:], ["verify", str(b.LIB / b.UNIT_NAME)])
                return ""
            self.assertEqual(argv[0], b.SYSTEMCTL)
            if argv[1:] == ["daemon-reload"]:
                return ""
            if argv[1:] == ["is-enabled", b.UNIT_NAME]:
                return "disabled"
            self.assertEqual(argv[1], "show")
            prop = argv[argv.index("-p") + 1]
            if prop == "UnitPath":
                return str(b.UNIT.parent)
            self.assertIn(argv[2], (b.UNIT_NAME, "gpt-agent-bridge.service"))
            values = {"LoadState": "loaded" if b.UNIT.exists() and argv[2] == b.UNIT_NAME else "not-found",
                      "FragmentPath": str(b.UNIT), "DropInPaths": "", "ActiveState": "inactive"}
            self.assertIn(prop, values)
            return values[prop]

        def fake_chown(path, uid, gid):
            self.assertTrue(Path(path).is_relative_to(self.base))
            self.assertEqual((uid, gid), (self.uid, self.gid))

        def fake_fchown(fd, uid, gid):
            self.assertEqual(os.fstat(fd).st_uid, self.uid)
            self.assertIn(uid, (self.uid, b.ROOT_UID))
            self.assertIn(gid, (0, self.gid))

        synthetic_token = "Synthetic_Frozen_Token_" + "7" * 32
        patched = {"UNIT": m.BRIDGE_UNIT_FILE, "LIB": m.BRIDGE_MANIFEST.parent,
                   "STATE": m.BRIDGE_SETTINGS.parent, "CONFIG": m.BRIDGE_SETTINGS,
                   "MANIFEST": m.BRIDGE_MANIFEST, "RUNNER": m.BRIDGE_RUNNER,
                   "ROOT_UID": self.uid, "UNIT_SEARCH_DIRS": (m.BRIDGE_UNIT_FILE.parent,),
                   "TEMPLATE_SHA256": hashlib.sha256(template).hexdigest(), "__file__": str(snapshot),
                   "host": host, "pwd": types.SimpleNamespace(getpwnam=lambda name: owner),
                   "checkout_root": check_checkout, "package_origin": check_origin,
                   "command": fake_command,
                   "user_command": mock.Mock(side_effect=AssertionError("host user command forbidden")),
                   "free_port": mock.Mock(),}
        output = io.StringIO()
        with contextlib.ExitStack() as stack:
            for name, value in patched.items():
                stack.enter_context(mock.patch.object(b, name, value))
            stack.enter_context(mock.patch.object(b.os, "chown", side_effect=fake_chown))
            stack.enter_context(mock.patch.object(b.os, "fchown", side_effect=fake_fchown))
            stack.enter_context(mock.patch.object(b.secrets, "token_urlsafe", return_value=synthetic_token))
            stack.enter_context(mock.patch.object(b.subprocess, "run", side_effect=AssertionError("host subprocess forbidden")))
            stack.enter_context(contextlib.redirect_stdout(output))
            result = b.main(["install", "--user", "demo", "--repo", str(repo),
                             "--workspace", str(target), "--herdr-bin", str(herdr), "--port", "8765"])
            self.assertEqual(result, 0)
            self.assertEqual(b.installation_record()["format"], b.MARKER)
        self.assertNotIn(synthetic_token, output.getvalue())
        self.assertIn("not enabled or started", output.getvalue())
        self.assertEqual(checkout_checks, [repo, target] * 3)
        self.assertEqual(origin_checks, [repo] * 3)
        self.assertFalse(any(call[1] in {"start", "enable", "stop", "restart"} for call in calls))
        manifest = json.loads(m.BRIDGE_MANIFEST.read_bytes())
        settings = json.loads(m.BRIDGE_SETTINGS.read_bytes())
        self.assertEqual(m.BRIDGE_RUNNER.read_bytes(), source)
        self.assertEqual(set(manifest), {"format", "plan", "unit_sha256", "runner_sha256"})
        expected = {"format": b.MARKER, "user": "demo", "uid": self.uid, "gid": self.gid,
                    "home": self.account.pw_dir, "repo": str(repo), "workspace": str(target),
                    "herdr_bin": str(herdr), "port": 8765, "entrypoint": "module"}
        self.assertEqual(manifest["plan"], expected)
        self.assertEqual(settings, {**expected, "token": synthetic_token})
        self.assertEqual(manifest["runner_sha256"], hashlib.sha256(source).hexdigest())
        self.assertEqual(manifest["unit_sha256"], hashlib.sha256(m.BRIDGE_UNIT_FILE.read_bytes()).hexdigest())
        return manifest, settings

    def test_frozen_installer_generated_records_accepted_without_duplicate_url(self):
        manifest, settings = self.frozen_bridge_installation()
        # Actual adapter function, schema/hash checks and token read are intact;
        # only file locations and synthetic ownership boundary are routed.
        bridge = m.bridge_contract(self.plan)
        expected_url = "http://127.0.0.1:8765/mcp/" + settings["token"]
        self.assertEqual(bridge["url"], expected_url)
        self.assertEqual(bridge["repo"], manifest["plan"]["repo"])
        self.assertEqual(bridge["python"], manifest["plan"]["repo"] + "/.venv/bin/python")
        self.assertEqual(bridge["url"].rsplit("/", 1)[1].encode(), settings["token"].encode())
        for folder in (m.LIB, m.STATE, m.BRIDGE_MANIFEST.parent, m.BRIDGE_SETTINGS.parent):
            for path in folder.iterdir():
                if path.is_file():
                    self.assertNotIn(expected_url.encode(), path.read_bytes())

    def test_frozen_generated_records_reject_unknown_and_corrupt_inputs(self):
        manifest, settings = self.frozen_bridge_installation()
        originals = {p: p.read_bytes() for p in (m.BRIDGE_MANIFEST, m.BRIDGE_SETTINGS, m.BRIDGE_UNIT_FILE)}
        mutations = [
            (m.BRIDGE_MANIFEST, {**manifest, "format": "foreign-format"}, "bridge_contract_mismatch"),
            (m.BRIDGE_MANIFEST, {**manifest, "unknown": True}, "bridge_contract_mismatch"),
            (m.BRIDGE_MANIFEST, {**manifest, "plan": {**manifest["plan"], "format": "foreign-format"}}, "bridge_contract_mismatch"),
            (m.BRIDGE_MANIFEST, {**manifest, "plan": {**manifest["plan"], "unknown": True}}, "bridge_contract_mismatch"),
            (m.BRIDGE_MANIFEST, {**manifest, "unit_sha256": "0" * 64}, "bridge_installation_changed"),
            (m.BRIDGE_MANIFEST, {**manifest, "runner_sha256": "0" * 64}, "bridge_installation_changed"),
            (m.BRIDGE_SETTINGS, {**settings, "token": "invalid!"}, "bridge_contract_mismatch"),
            (m.BRIDGE_SETTINGS, {**settings, "unknown": True}, "bridge_contract_mismatch"),
            (m.BRIDGE_SETTINGS, {**settings, "uid": self.uid + 1}, "bridge_contract_mismatch"),
        ]
        for path, value, code in mutations:
            with self.subTest(path=path.name, code=code, fields=tuple(value)):
                path.write_bytes(json.dumps(value).encode())
                self.refused(code, m.bridge_contract, self.plan)
                path.write_bytes(originals[path])
        m.BRIDGE_UNIT_FILE.write_bytes(b"corrupt synthetic unit")
        self.refused("bridge_installation_changed", m.bridge_contract, self.plan)
        m.BRIDGE_UNIT_FILE.write_bytes(originals[m.BRIDGE_UNIT_FILE])
        self.refused("bridge_contract_mismatch", m.bridge_contract,
                     {**self.plan, "user": "another-demo"})
        self.assertEqual(m.bridge_contract(self.plan)["url"].rsplit("/", 1)[1], settings["token"])

    def test_copy_docs_existing_snapshot_stops_before_install(self):
        import re
        doc=(SOURCE.parent.parent/"docs/AUTOSTART.md").read_text()
        fences=re.findall(r'^```bash\n(.*?)^```',doc,re.M|re.S)
        copies=[block for block in fences if re.search(r"^# gate: component-tunnel-snapshot$", block, re.M)]
        self.assertEqual(len(copies), 1)
        copy=copies[0]
        fakebin=self.base/"fakebin"
        trace=self.base/"command-trace"
        fake="#!/usr/bin/python3\nimport sys\nfrom pathlib import Path\np=Path("+repr(str(trace))+")\np.write_text(p.read_text()+' '.join(sys.argv[1:])+'\\n' if p.exists() else ' '.join(sys.argv[1:])+'\\n')\nsys.exit(1 if sys.argv[1]=='mkdir' else 0)\n"
        self.write(fakebin/"sudo",fake.encode(),0o700)
        result=subprocess.run(['/usr/bin/bash','-c',copy],env={'PATH':str(fakebin)+':/usr/bin:/bin','HOME':self.account.pw_dir,'LANG':'C.UTF-8'},capture_output=True)
        self.assertNotEqual(result.returncode,0)
        self.assertEqual(len(trace.read_text().splitlines()),1)
        self.assertNotIn('/usr/bin/install',trace.read_text())


if __name__ == "__main__":
    unittest.main()
