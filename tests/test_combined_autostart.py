"""Actual writers/templates with synthetic owner, filesystem and manager facts.

No host service or product listener is invoked. Unit inventory, serialization,
protected reads, adapter and shell gates stay real; host command results and
root identity are explicitly simulated inside an owned TemporaryDirectory.
"""
import asyncio
import contextlib
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import types
import unittest
import venv
from unittest import mock

from tests import test_bridge_tunnel_autostart as fixtures

ROOT = Path(__file__).resolve().parents[1]
BRIDGE = ROOT / "scripts/install-bridge-autostart.py"
BRIDGE_SHA = "17ef82d1f6ac15fd91cc5061f187857391117bb06946cf92f30cc61e4668eb12"
TUNNEL_SHA = "bdf18880db43bd701f3ba18903ad127f8aa804a8f1074bc5613a1cd67afb49c0"


def bridge_module():
    assert hashlib.sha256(BRIDGE.read_bytes()).hexdigest() == BRIDGE_SHA
    spec = importlib.util.spec_from_file_location("combined_bridge", BRIDGE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class WriterAndPolicyTests(unittest.TestCase):
    def setUp(self):
        self.f = fixtures.CompanionTests("runTest")
        self.f.setUp()
        self.addCleanup(self.f.doCleanups)
        self.m = fixtures.m
        self.b = bridge_module()
        self.assertEqual(hashlib.sha256(fixtures.SOURCE.read_bytes()).hexdigest(), TUNNEL_SHA)
        snapshot = self.f.base / "tunnel-root-snapshot"
        snapshot.mkdir(mode=0o700)
        self.f.write(snapshot / "installer.py", fixtures.SOURCE.read_bytes())
        self.f.write(snapshot / "service.template", fixtures.TEMPLATE.read_bytes())
        self.f.patch("__file__", str(snapshot / "installer.py"))

        def reviewed_snapshot():
            # Root identity only is simulated; production private-dir/file reads run.
            with mock.patch.object(self.m.os, "geteuid", return_value=0):
                return fixtures.ORIGINAL_TRUSTED_SNAPSHOT()
        self.f.patch("trusted_snapshot", reviewed_snapshot)

    def install_pair(self, tunnel_first=True):
        manifest, settings = self.f.frozen_bridge_installation(
            production_template=True, tunnel_first=tunnel_first)
        if not tunnel_first:
            self.f.provisioned()
        return manifest, settings

    @contextlib.contextmanager
    def bridge_policy(self):
        b, m = self.b, self.m
        # Only unit locations, root ownership and manager UnitPath observation
        # are routed. Neither production activation inventory is replaced.
        with mock.patch.object(b, "ROOT_UID", self.f.uid), \
                mock.patch.object(b, "UNIT", m.BRIDGE_UNIT_FILE), \
                mock.patch.object(b, "UNIT_SEARCH_DIRS", m.SYSTEMD_ROOTS), \
                mock.patch.object(b, "command", return_value=" ".join(map(str, m.SYSTEMD_ROOTS))):
            yield b

    def test_both_production_templates_actual_writers_both_orders(self):
        # A separate fixture lifecycle for each order, not two install retries.
        for order in (True, False):
            with self.subTest(tunnel_first=order):
                other = type(self)("runTest")
                other.setUp()
                try:
                    manifest, settings = other.install_pair(order)
                    m, f = other.m, other.f
                    contract = m.bridge_contract(f.plan)
                    self.assertEqual(manifest["format"], "gpt-agent-bridge-autostart-v1")
                    self.assertNotEqual(manifest["plan"]["repo"], manifest["plan"]["workspace"])
                    for key in ("user", "uid", "gid", "home"):
                        self.assertEqual(manifest["plan"][key], f.plan[key])
                    self.assertEqual(contract["url"].rsplit("/", 1)[1], settings["token"])
                    self.assertEqual(m.BRIDGE_RUNNER.read_bytes(), BRIDGE.read_bytes())
                    self.assertEqual(m.RUNNER.read_bytes(), fixtures.SOURCE.read_bytes())
                    self.assertEqual(m.record()["unit_sha256"], hashlib.sha256(m.UNIT_FILE.read_bytes()).hexdigest())
                    self.assertIn(b"After=gpt-agent-bridge-autostart.service network-online.target", m.UNIT_FILE.read_bytes())
                    for unit in (m.UNIT_FILE, m.BRIDGE_UNIT_FILE):
                        self.assertNotIn(b"Environment=", unit.read_bytes())
                    self.assertEqual(m.managed_properties()["ActiveState"], "inactive")
                    self.assertEqual(m.managed_properties()["UnitFileState"], "disabled")
                    for folder in (m.LIB, m.STATE, m.BRIDGE_MANIFEST.parent, m.BRIDGE_SETTINGS.parent):
                        for p in folder.iterdir():
                            if p.is_file():
                                self.assertNotIn(contract["url"].encode(), p.read_bytes())
                    self.assertFalse(any(c[1] in ("enable", "start", "restart", "stop") for c in f.calls))
                finally:
                    other.doCleanups()

    def test_generated_schema_identity_and_hash_refusals(self):
        manifest, settings = self.install_pair()
        m, f = self.m, self.f
        original = m.BRIDGE_MANIFEST.read_bytes()
        for key, value in (("uid", f.uid + 1), ("gid", f.gid + 1),
                           ("home", str(f.base / "other-home")), ("format", "foreign")):
            m.BRIDGE_MANIFEST.write_bytes(json.dumps({**manifest, "plan": {**manifest["plan"], key: value}}).encode())
            f.refused("bridge_contract_mismatch", m.bridge_contract, f.plan)
        m.BRIDGE_MANIFEST.write_bytes(json.dumps({**manifest, "runner_sha256": "0" * 64}).encode())
        f.refused("bridge_installation_changed", m.bridge_contract, f.plan)
        m.BRIDGE_MANIFEST.write_bytes(original)
        saved = m.BRIDGE_SETTINGS.read_bytes()
        m.BRIDGE_SETTINGS.write_bytes(json.dumps({**settings, "url": "synthetic-extra-capability"}).encode())
        f.refused("bridge_contract_mismatch", m.bridge_contract, f.plan)
        m.BRIDGE_SETTINGS.write_bytes(saved)
        self.assertEqual(m.bridge_contract(f.plan)["repo"], manifest["plan"]["repo"])

    def test_own_enabled_links_and_other_unit_coexist(self):
        self.install_pair()
        m = self.m
        wants = m.UNIT_FILE.parent / "multi-user.target.wants"
        wants.mkdir(mode=0o700)
        (wants / m.UNIT).symlink_to(m.UNIT_FILE)
        (wants / self.b.UNIT_NAME).symlink_to(m.BRIDGE_UNIT_FILE)
        with self.bridge_policy() as b:
            b.activation_policy(published=True, enabled=True)
            m.managed_properties()
            with self.assertRaises(b.Refusal):
                b.activation_policy(published=True, enabled=False)

    def test_own_stale_dangling_alias_and_dropin_refused(self):
        self.install_pair()
        m = self.m
        for name in (m.UNIT, self.b.UNIT_NAME):
            with self.subTest(unit=name):
                wants = m.UNIT_FILE.parent / "other.target.requires"
                wants.mkdir(mode=0o700)
                link = wants / name
                link.symlink_to(m.UNIT_FILE.parent / "missing" / name)
                with self.bridge_policy() as b:
                    if name == m.UNIT:
                        self.f.refused("foreign_activation", m.managed_properties)
                    else:
                        with self.assertRaises((b.Refusal, OSError)):
                            b.activation_policy(published=True, enabled=True)
                link.unlink(); wants.rmdir()
        alias = m.UNIT_FILE.parent / "foreign-alias.service"
        alias.symlink_to(m.UNIT_FILE)
        self.f.refused("foreign_activation", m.managed_properties)
        alias.unlink()
        alias.symlink_to(m.BRIDGE_UNIT_FILE)
        with self.bridge_policy() as b, self.assertRaises(b.Refusal):
            b.activation_policy(published=True, enabled=True)
        alias.unlink()
        dropin = m.UNIT_FILE.parent / "service.d"
        dropin.mkdir(mode=0o700)
        self.f.refused("foreign_activation", m.managed_properties)
        with self.bridge_policy() as b, self.assertRaises(b.Refusal):
            b.activation_policy(published=True, enabled=True)

    def test_foreign_adopter_and_wrong_unitpath_refused(self):
        self.install_pair()
        m = self.m
        adopter = m.UNIT_FILE.parent / "gpt-agent-bridge.service"
        self.f.write(adopter, b"# synthetic foreign adopter", 0o644)
        with self.bridge_policy() as b, self.assertRaises(b.Refusal):
            b.activation_policy(published=True, enabled=True)
        adopter.unlink()
        with self.bridge_policy() as b, \
                mock.patch.object(b, "command", return_value=str(self.f.base / "unmanaged")), \
                self.assertRaises(b.Refusal):
            b.activation_policy(published=True, enabled=True)
        with mock.patch.object(m, "unit_paths", return_value=(self.f.base / "unsafe-missing" / "nested",)), \
                self.assertRaises((m.Refusal, OSError)):
            m.managed_properties()

    def test_existing_signal_and_parser_controls_remain_default(self):
        text = (ROOT / "tests/test_bridge_tunnel_autostart.py").read_text()
        self.assertNotIn('self.skipTest("explicit frozen', text)
        for method in ("test_parser_depth_tunnel_manifest", "test_file_read_recursion_outside_parser",
                       "test_runtime_recursion_outside_parser"):
            self.assertIn(method, text)
        self.assertEqual(hashlib.sha256(BRIDGE.read_bytes()).hexdigest(), BRIDGE_SHA)

    def test_actual_package_origin_accepts_own_and_refuses_foreign_source(self):
        manifest, _ = self.install_pair()
        repo = Path(manifest["plan"]["repo"])
        (repo / "pyproject.toml").write_text("[project]\nname='synthetic'\n")
        (repo / "src/gpt_agent_bridge/__main__.py").write_text("raise AssertionError('no launch')")
        (repo / "src/gpt_agent_bridge/__init__.py").write_text("raise AssertionError('no import')")
        (repo / ".venv/bin/python").unlink()  # our known inert fixture, not host code
        venv.EnvBuilder(with_pip=False, symlinks=True).create(repo / ".venv")
        site = next((repo / ".venv/lib").glob("python*/site-packages"))
        pointer = site / "fixture.pth"
        pointer.write_text(str(repo / "src") + "\n")
        owner = types.SimpleNamespace(pw_uid=self.f.uid, pw_gid=self.f.gid, pw_dir=self.f.account.pw_dir)
        self.b.package_origin(repo, owner)  # actual isolated find_spec child, no import
        foreign = self.f.base / "foreign-source"
        (foreign / "gpt_agent_bridge").mkdir(parents=True)
        (foreign / "gpt_agent_bridge/__init__.py").write_text("raise AssertionError('no import')")
        pointer.write_text(str(foreign) + "\n")
        with self.assertRaises(self.b.Refusal):
            self.b.package_origin(repo, owner)


class GuideGateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="combined-guide-gate-")
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        doc = (ROOT / "docs/AUTOSTART.md").read_text()
        named = [(re.search(r"^# gate: ([a-z-]+)$", s, re.M).group(1), s)
                 for s in re.findall(r"^```bash\n(.*?)^```", doc, re.M | re.S)
                 if re.search(r"^# gate: ([a-z-]+)$", s, re.M)]
        self.assertEqual(len(named), len({name for name, _ in named}))
        self.blocks = dict(named)
        self.trace = self.base / "trace"
        self.stub = self.base / "inert"
        self.stub.write_text('''#!/usr/bin/python3
import json,os,sys
from pathlib import Path
a=sys.argv[1:]; p=Path(os.environ['TRACE'])
with p.open('a') as f:f.write(' '.join(a)+'\\n')
if a[0]=='show':
 prop=a[a.index('-p')+1]
 print({'LoadState':'loaded','FragmentPath':'/etc/systemd/system/'+a[1],'DropInPaths':''}[prop])
 if os.environ.get('UNIT_FAIL')==prop:sys.exit(1)
elif a[0]=='probe':print(os.environ['HEALTH'])
elif a[0] in ('bridge','tunnel'):
 statefile=Path(os.environ['STATEFILE'])
 states=json.loads(statefile.read_text()) if statefile.exists() else {'bridge':json.loads(os.environ['BRIDGE_STATE']),'tunnel':json.loads(os.environ['TUNNEL_STATE'])}
 if a[-1]=='status':print(json.dumps(states[a[0]]))
 elif os.environ.get('TRANSITION')=='1':
  fields={'bridge':('service','enabled'),'tunnel':('process','boot_activation')}
  if a[-1]=='enable':states[a[0]][fields[a[0]][1]]='enabled'
  elif a[-1]=='start':
   states[a[0]][fields[a[0]][0]]='active'
   if a[0]=='tunnel':states[a[0]]['tunnel_startup']='ready'
  statefile.write_text(json.dumps(states))
''')
        self.stub.chmod(0o700)

    def run_blocks(self, names, bridge=None, tunnel=None, health=None, transition=False, unit_fail="", optimize=""):
        bridge = {"service": "active", "enabled": "enabled"} if bridge is None else bridge
        tunnel = {"process": "inactive", "boot_activation": "disabled"} if tunnel is None else tunnel
        health = {"bridge_mcp": "initialized_healthy", "herdr": "unavailable", "work_resume": "not_established"} if health is None else health
        script = "\n".join(self.blocks[n] for n in ("observations", *names))
        # Replace command endpoints only; execute the guide's guard/check order.
        script = script.replace('/usr/bin/systemctl', '"'+str(self.stub)+'"')
        script = script.replace('sudo /usr/bin/python3 -I -B "$bridge_installer"', '"'+str(self.stub)+'" bridge')
        script = script.replace('sudo /usr/bin/python3 -I -B "$tunnel_installer"', '"'+str(self.stub)+'" tunnel')
        script = script.replace('"$bridge_repo/.venv/bin/python" -I -B /usr/local/lib/gpt-agent-bridge-autostart/runner.py probe', '"'+str(self.stub)+'" probe')
        script = script.replace('/usr/bin/python3 -I -B /usr/local/lib/gpt-agent-bridge-tunnel-autostart/runner.py status', '"'+str(self.stub)+'" tunnel status')
        env = {"PATH": "/usr/bin:/bin", "HOME": str(self.base), "LANG": "C.UTF-8", "TRACE": str(self.trace),
               "BRIDGE_STATE": json.dumps(bridge), "TUNNEL_STATE": json.dumps(tunnel), "HEALTH": json.dumps(health),
               "STATEFILE": str(self.base / "states"), "TRANSITION": "1" if transition else "0", "UNIT_FAIL": unit_fail, "PYTHONOPTIMIZE": optimize}
        result = subprocess.run(["/usr/bin/bash", "--noprofile", "--norc", "-c", script], env=env, capture_output=True)
        trace = self.trace.read_text().splitlines() if self.trace.exists() else []
        self.trace.unlink(missing_ok=True)
        (self.base / "states").unlink(missing_ok=True)
        return result, trace

    def test_inherited_python_optimization_cannot_disable_state_gate(self):
        result, trace = self.run_blocks(["tunnel-enable"], bridge={}, optimize="2")
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn("tunnel enable", trace)

    def test_genuine_state_transitions_allow_each_separate_stage(self):
        result, trace = self.run_blocks(["bridge-enable", "bridge-start", "tunnel-enable", "tunnel-start"],
                                        bridge={"service": "inactive", "enabled": "disabled"}, transition=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual([x for x in trace if x in ("bridge enable", "bridge start", "tunnel enable", "tunnel start")],
                         ["bridge enable", "bridge start", "tunnel enable", "tunnel start"])

    def test_observation_failed_exit_with_valid_stdout_stops(self):
        for prop in ("LoadState", "FragmentPath", "DropInPaths"):
            result, trace = self.run_blocks(["tunnel-enable"], unit_fail=prop)
            self.assertNotEqual(result.returncode, 0)
            self.assertNotIn("tunnel enable", trace)

    def test_wrong_unknown_or_transitioning_bridge_stops_before_tunnel_enable(self):
        for value in ({}, {"service": "activating", "enabled": "enabled"},
                      {"service": "active", "enabled": "unknown"}, {"service": "inactive", "enabled": "enabled"}):
            with self.subTest(state=value):
                result, trace = self.run_blocks(["tunnel-enable"], bridge=value)
                self.assertNotEqual(result.returncode, 0)
                self.assertNotIn("tunnel enable", trace)

    def test_false_successful_enable_cannot_advance_to_start(self):
        result, trace = self.run_blocks(["bridge-enable", "bridge-start"],
                                        bridge={"service": "inactive", "enabled": "disabled"})
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("bridge enable", trace)
        self.assertNotIn("bridge start", trace)

    def test_tunnel_false_enable_success_cannot_advance_to_start(self):
        result, trace = self.run_blocks(["tunnel-enable", "tunnel-start"])
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("tunnel enable", trace)
        self.assertNotIn("tunnel start", trace)

    def test_malformed_health_stops_before_enable(self):
        for value in ({}, {"ok": 1}, {"bridge_mcp": "initialized_healthy", "herdr": "unavailable"},
                      {"bridge_mcp": "unavailable_or_invalid", "herdr": "unknown", "work_resume": "not_established"}):
            result, trace = self.run_blocks(["tunnel-enable"], health=value)
            self.assertNotEqual(result.returncode, 0)
            self.assertNotIn("tunnel enable", trace)

    def test_herdr_unavailable_allows_enable_but_false_readback_stops(self):
        result, trace = self.run_blocks(["tunnel-enable"])
        self.assertIn("tunnel enable", trace)
        self.assertNotEqual(result.returncode, 0)  # unchanged inactive/disabled readback

    def test_tunnel_unknown_readiness_does_not_certify_completion(self):
        result, trace = self.run_blocks(["tunnel-start"],
                                        tunnel={"process": "inactive", "boot_activation": "enabled"})
        self.assertIn("tunnel start", trace)
        self.assertNotEqual(result.returncode, 0)
        for value in ({}, {"process": "activating", "boot_activation": "enabled"},
                      {"process": "active", "boot_activation": "unknown"}):
            result, trace = self.run_blocks(["tunnel-start"], tunnel=value)
            self.assertNotEqual(result.returncode, 0)
            self.assertNotIn("tunnel start", trace)

    def test_actual_initialized_probe_bool_and_unavailable_herdr(self):
        b = bridge_module()
        # Actual async classifier, inert SDK response; no socket/listener.
        config = {"port": 8765, "token": "synthetic-probe-token"}
        for ok, expected in ((True, "initialized_healthy"), (1, "unavailable_or_invalid"),
                             (False, "unavailable_or_invalid")):
            health = {"bridge": "gpt-agent-bridge", "ok": ok, "herdr": {"status": "unavailable"}}
            class Client:
                def __init__(self, *args, **kwargs): pass
                async def __aenter__(self): return self
                async def __aexit__(self, *args): pass
                async def call_tool(self, *args, **kwargs):
                    return types.SimpleNamespace(is_error=False, structured_content=health)
            with mock.patch.dict(sys.modules, {"mcp": types.SimpleNamespace(Client=Client)}):
                self.assertEqual(asyncio.run(b.probe(config))["bridge_mcp"], expected)

    def test_one_anchor_two_units_no_replay_static_contract(self):
        text = fixtures.TEMPLATE.read_text()
        self.assertNotRegex(text, r"(?m)^(Wants|Requires|BindsTo)=")
        self.assertNotIn("herdr", text.lower())


if __name__ == "__main__":
    unittest.main()
