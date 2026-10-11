import asyncio
import contextlib
import json
import os
import re
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault(
    "BRIDGE_PATH_TOKEN",
    "test-token-abcdefghijklmnopqrstuvwxyz-012345",
)

import herdr_backend
import server
from tests.work_observation import work_record
from workspace_context import WorkspaceRegistry


def setUpModule():
    # Globally guard against live Herdr subprocess execution during unit tests
    orig_exec_raw = herdr_backend.HerdrBackend._exec_raw

    async def _guarded_exec_raw(self, *args, **kwargs):
        raise AssertionError(
            f"TEST ISOLATION VIOLATION: Unmocked live Herdr subprocess execution was attempted in unit tests! "
            f"Args: {args}, root: {self.root}"
        )

    herdr_backend.HerdrBackend._exec_raw = _guarded_exec_raw
    herdr_backend.HerdrBackend._orig_exec_raw_for_test = orig_exec_raw
    # This module's fixtures are kind agy and await real watchers; keep the
    # authorized AGY 60s settlement debounce (watch-layer contract, mocked-time
    # tested in test_startup_observation) off the real-time path here.
    global _orig_agy_schedule_for_test
    _orig_agy_schedule_for_test = (
        herdr_backend.AGY_SETTLEMENT_CONFIRM_SECONDS,
        herdr_backend.AGY_SETTLEMENT_CONFIRM_ATTEMPTS,
    )
    herdr_backend.AGY_SETTLEMENT_CONFIRM_SECONDS = 0.0
    herdr_backend.AGY_SETTLEMENT_CONFIRM_ATTEMPTS = 1
    # Persistent observation failures still exhaust the real extra-attempt
    # count; only the sleep is zeroed so the suite does not add real seconds.
    global _orig_transient_retry_for_test
    _orig_transient_retry_for_test = (
        herdr_backend.TRANSIENT_OBSERVATION_EXTRA_ATTEMPTS,
        herdr_backend.TRANSIENT_OBSERVATION_RETRY_INTERVAL_SECONDS,
    )
    herdr_backend.TRANSIENT_OBSERVATION_RETRY_INTERVAL_SECONDS = 0.0


_orig_agy_schedule_for_test = None
_orig_transient_retry_for_test = None


def tearDownModule():
    if hasattr(herdr_backend.HerdrBackend, "_orig_exec_raw_for_test"):
        herdr_backend.HerdrBackend._exec_raw = herdr_backend.HerdrBackend._orig_exec_raw_for_test
    if _orig_agy_schedule_for_test is not None:
        (herdr_backend.AGY_SETTLEMENT_CONFIRM_SECONDS,
         herdr_backend.AGY_SETTLEMENT_CONFIRM_ATTEMPTS) = _orig_agy_schedule_for_test
    if _orig_transient_retry_for_test is not None:
        (herdr_backend.TRANSIENT_OBSERVATION_EXTRA_ATTEMPTS,
         herdr_backend.TRANSIENT_OBSERVATION_RETRY_INTERVAL_SECONDS) = (
            _orig_transient_retry_for_test)


def git_worktree(path: Path) -> Path:
    path.mkdir()
    subprocess.run(["git", "init", "--quiet", str(path)], check=True)
    return path.resolve()


def agy_agent(root: Path, *, pid: int = 1234) -> dict:
    return {
        "agent": "agy",
        "agent_status": "idle",
        "state_change_seq": 1,
        "revision": 1,
        "cwd": str(root),
        "workspace_id": "w-manual",
        "tab_id": "w-manual:t1",
        "pane_id": "w-manual:p1",
        "terminal_id": "term-manual",
        "foreground_cwd": str(root),
        "name": None,
        "_pid": pid,
    }


def running_handoff_entry(hid, watcher=None):
    return {
        "handoff_id": hid, "candidate_id": "c1", "candidate": {}, "workspace_ref": None,
        "dispatched_at": 100.0, "state": "running", "reason": "running",
        "herdr_status": "working", "pre_state_change_seq": 1, "post_state_change_seq": None,
        "pre_revision": 1, "post_revision": None, "latched_at": None, "watcher_task": watcher,
        "join_waiters": 0, "joined_once": False,
    }


def process_info(agent: dict) -> dict:
    pid = agent["_pid"]
    foreground_cwd = agent.get("foreground_cwd") or agent["cwd"]
    return {
        "pane_id": agent["pane_id"],
        "foreground_process_group_id": pid,
        "foreground_cwd": foreground_cwd,
        "foreground_processes": [{
            "pid": pid,
            "argv": ["agy", "--dangerously-skip-permissions"],
            "cwd": foreground_cwd,
        }],
    }


# Live-validated settled AGY screen shape (2026-09-21 probes): transcript with
# a quoted user block and reply, box-drawing separator, bare `>` composer, and
# a footer anchor. Recovery-only fixture; the parser is deliberately small.
AGY_SETTLED_COMPOSER_SCREEN = "\n".join([
    "> earlier task",
    "",
    "Earlier reply line.",
    "────────────────────────────────────────────────",
    ">",
    "🤖 Gemini 3.8 Flash (High) | 🧠 Context: 19% | /help",
])

AGY_SCREEN_NEGATIVE_VARIANTS = {
    "composer-holds-text": AGY_SETTLED_COMPOSER_SCREEN.replace(
        "\n>\n", "\n> drafted task text\n"),
    "queued-hint": AGY_SETTLED_COMPOSER_SCREEN
    + "\nPress up to edit queued messages",
    "esc-to-cancel-bar": AGY_SETTLED_COMPOSER_SCREEN.replace(
        "🤖 Gemini 3.8 Flash (High) | 🧠 Context: 19% | /help",
        "esc to cancel · Gemini"),
    "permission-prompt": AGY_SETTLED_COMPOSER_SCREEN
    + "\nrequesting permission for: shell command",
    "missing-separator": "\n".join(
        line for line in AGY_SETTLED_COMPOSER_SCREEN.splitlines()
        if not line.startswith("─")),
    "missing-footer": "\n".join(
        AGY_SETTLED_COMPOSER_SCREEN.splitlines()[:-1]),
    "missing-bare-composer": AGY_SETTLED_COMPOSER_SCREEN.replace("\n>\n", "\n\n"),
    "empty": "",
}


def manual_backend(root: Path):
    backend = herdr_backend.HerdrBackend(root)
    created_agent = {
        "agent": "agy",
        "agent_status": "idle",
        "state_change_seq": 1,
        "revision": 1,
        "cwd": str(root),
        "workspace_id": "w-manual",
        "tab_id": "w-manual:t2",
        "pane_id": "w-manual:p2",
        "terminal_id": "term-created",
        "foreground_cwd": str(root),
        "name": None,
        "_pid": 4321,
    }
    state = {
        "agent": agy_agent(root),
        "created_agent": created_agent,
        "created_agents": [],
        "text": "manual output",
        "calls": [],
        "process_info": None,
        "prompt_error": None,
        "start_error": None,
        "start_errors": [],
        "workspace_id": "w-manual",
        "panes": [
            {"workspace_id": "w-manual", "cwd": str(root), "tab_id": "w-manual:t1", "pane_id": "w-manual:p1", "terminal_id": "term-w-manual:p1"}
        ],
        "tabs": [
            {"workspace_id": "w-manual", "tab_id": "w-manual:t1", "label": "Main Tab", "pane_count": 1}
        ],
    }

    async def fake_call(*args, **_kwargs):
        state["calls"].append(args)
        if args[:2] == ("api", "snapshot"):
            if state.get("snapshot_error") is not None:
                raise state["snapshot_error"]
            if state.get("snapshot_handler") is not None:
                return state["snapshot_handler"](*args)
            panes = state.get("panes")
            if panes is None:
                panes = [{"workspace_id": state["workspace_id"], "pane_id": "w-manual:p1", "cwd": str(root), "terminal_id": "term-w-manual:p1"}]
            tabs = state.get("tabs", [])
            live_pane_ids = {p.get("pane_id") for p in panes if isinstance(p, dict)}
            raw_agents = [state["agent"]] + list(state.get("created_agents", []))
            live_agents = []
            for a in raw_agents:
                if isinstance(a, dict) and (not a.get("pane_id") or a.get("pane_id") in live_pane_ids):
                    agent_dict = dict(a)
                    pane = next((p for p in panes if isinstance(p, dict) and p.get("pane_id") == a.get("pane_id")), None)
                    if "workspace_id" not in agent_dict:
                        agent_dict["workspace_id"] = pane.get("workspace_id") if pane else state["workspace_id"]
                    if "tab_id" not in agent_dict and pane:
                        agent_dict["tab_id"] = pane.get("tab_id")
                    live_agents.append(agent_dict)
            return {
                "snapshot": {
                    "agents": live_agents,
                    "panes": panes,
                    "tabs": tabs,
                    "layouts": state.get("layouts", []),
                    "workspaces": state.get(
                        "workspaces",
                        [{"workspace_id": state["workspace_id"], "label": "GPT Web Bridge"}],
                    ),
                }
            }
        if args[:2] == ("pane", "process-info"):
            req_pane = args[3] if len(args) > 3 and args[2] == "--pane" else None
            agents_list = [state.get("agent")] + list(state.get("created_agents", []))
            target_agent = next((a for a in agents_list if isinstance(a, dict) and a.get("pane_id") == req_pane), state["agent"])
            return {"process_info": state["process_info"] or process_info(target_agent)}
        if args[:2] == ("agent", "prompt"):
            if state["prompt_error"] is not None:
                raise state["prompt_error"]
            if state.get("prompt_handler") is not None:
                return state["prompt_handler"](*args)
            agents = [state.get("agent")] + list(state.get("created_agents", []))
            target = next((agent for agent in agents if isinstance(agent, dict)
                           and agent.get("pane_id") == args[2]), state["agent"])
            if state.get("auto_advance_turn", True):
                if isinstance(target, dict):
                    if target.get("state_change_seq") is not None:
                        target["state_change_seq"] += 1
                    if target.get("revision") is not None:
                        target["revision"] += 1
            return {"type": "agent_prompted", "agent": dict(target)}
        if args[:2] == ("agent", "wait"):
            if state.get("wait_error") is not None:
                raise state["wait_error"]
            if state.get("wait_handler") is not None:
                return state["wait_handler"](*args, **_kwargs)
            return {"agent": state.get("created_agent") or state["agent"]}
        if args[:2] == ("agent", "send-keys"):
            return {"agent": state["agent"]}
        if args[:2] == ("agent", "read"):
            # Recovery-only bounded detection read; never serves task text.
            if state.get("read_error") is not None:
                raise state["read_error"]
            if state.get("read_handler") is not None:
                return state["read_handler"](*args)
            return state.get("detection_text", AGY_SETTLED_COMPOSER_SCREEN)
        if args[:2] == ("pane", "read"):
            return state["text"]
        raise AssertionError(args)

    backend._call = fake_call
    backend._call_text = fake_call
    return backend, state


async def dispatch_candidate(candidate_id, task):
    """Exercise dispatch with a reserved Work, as the retained delegate path does."""
    record = server._manual_candidate_record(candidate_id)
    workspace = server._manual_candidate_workspace(record)
    work = server._reserve_work(workspace.workspace_ref, workspace, candidate_id, record["candidate"])
    return await server._dispatch_manual_turn(candidate_id, record, task, work_entry=work)


class ManualAgentBackendTests(unittest.TestCase):
    def test_resource_key_includes_registered_project_scope_not_execution_cwd(self):
        with tempfile.TemporaryDirectory() as temp:
            container = Path(temp)
            first_root = container / "first"
            second_root = container / "second"
            first_root.mkdir()
            second_root.mkdir()
            first_backend, _ = manual_backend(first_root)
            second_backend, _ = manual_backend(second_root)

            first = asyncio.run(
                first_backend.manual_agent_candidates()
            )["candidates"][0]
            second = asyncio.run(
                second_backend.manual_agent_candidates()
            )["candidates"][0]

        self.assertNotEqual(first["resource_key"], second["resource_key"])

    def test_agy_discovery_preserves_raw_kind_and_process_identity(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            backend, state = manual_backend(root)
            result = asyncio.run(backend.manual_agent_candidates())

        self.assertEqual(result["candidate_count"], 1)
        candidate = result["candidates"][0]
        public = candidate["public"]
        self.assertEqual(public["agent_kind"], "agy")
        self.assertEqual(public["agent_name"], None)
        self.assertEqual(public["continuity"]["level"], "pane_process")
        self.assertEqual(public["continuity"]["read_status"], "available")
        self.assertEqual(
            public["foreground_process"]["foreground_process_group_id"], 1234
        )
        self.assertEqual(public["foreground_process"]["processes"][0]["pid"], 1234)
        self.assertEqual(public["prompt_transport"]["mode"], "native_herdr")
        self.assertEqual(public["prompt_transport"]["identity_guard"], "herdr_native_preflight")
        self.assertEqual(state["calls"][0], ("api", "snapshot"))

    def test_absent_raw_kind_never_aliases_literal_unknown_kind(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            backend, state = manual_backend(root)
            state["agent"].pop("agent")
            absent = asyncio.run(backend.manual_agent_candidates())

            self.assertEqual(absent["candidate_count"], 0)
            self.assertEqual(absent["skipped_count"], 1)

            state["agent"]["agent"] = "unknown"
            literal = asyncio.run(backend.manual_agent_candidates())
            self.assertEqual(literal["candidate_count"], 1)
            candidate = literal["candidates"][0]
            self.assertEqual(candidate["public"]["agent_kind"], "unknown")

            state["agent"].pop("agent")
            with self.assertRaises(herdr_backend.HerdrError) as changed_to_absent:
                asyncio.run(backend.revalidate_manual_agent_resource(candidate))

            self.assertEqual(
                changed_to_absent.exception.code,
                "manual_candidate_identity_ambiguous",
            )

    def test_discovery_rejects_explicit_cwd_conflicts(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            mismatch = str(root / "other-workspace")
            for source in ("agent", "foreground", "process"):
                with self.subTest(source=source):
                    backend, state = manual_backend(root)
                    if source == "agent":
                        state["agent"]["foreground_cwd"] = mismatch
                    else:
                        state["process_info"] = process_info(state["agent"])
                        if source == "foreground":
                            state["process_info"]["foreground_cwd"] = mismatch
                        else:
                            state["process_info"]["foreground_processes"][0]["cwd"] = mismatch

                    result = asyncio.run(backend.manual_agent_candidates())

                    self.assertEqual(result["candidate_count"], 0 if source == "agent" else 1)
                    self.assertEqual(result["skipped_count"], 1 if source == "agent" else 0)
                    if source != "agent":
                        self.assertNotIn(mismatch, json.dumps(result))

    def test_missing_optional_cwds_are_not_inferred_as_matching(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            backend, state = manual_backend(root)
            state["agent"].pop("foreground_cwd")
            state["process_info"] = process_info(state["agent"])
            state["process_info"].pop("foreground_cwd")
            state["process_info"]["foreground_processes"][0].pop("cwd")
            candidate = asyncio.run(backend.manual_agent_candidates())["candidates"][0]
            result = asyncio.run(backend.read_manual_agent(candidate, limit=1))

        public = candidate["public"]
        self.assertIsNone(public["foreground_cwd"])
        self.assertIsNone(public["foreground_process"]["foreground_cwd"])
        self.assertIsNone(public["foreground_process"]["processes"][0]["cwd"])
        self.assertEqual(result["text"], "manual output")

    def test_missing_argv_evidence_is_not_read_eligible(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            backend, state = manual_backend(root)
            state["process_info"] = {
                "pane_id": "w-manual:p1",
                "foreground_process_group_id": 1234,
                "foreground_processes": [{"pid": 1234, "argv0": "agy"}],
            }
            candidate = asyncio.run(backend.manual_agent_candidates())["candidates"][0]
            with self.assertRaisesRegex(herdr_backend.HerdrError, "continuity is unavailable"):
                asyncio.run(backend.revalidate_manual_agent(candidate))

        self.assertEqual(candidate["public"]["continuity"]["level"], "pane_only")
        self.assertEqual(candidate["public"]["continuity"]["read_status"], "unavailable")

    def test_revalidation_rejects_same_pane_replacement_process(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            backend, state = manual_backend(root)
            candidate = asyncio.run(backend.manual_agent_candidates())["candidates"][0]
            state["agent"] = agy_agent(root, pid=5678)
            with self.assertRaisesRegex(herdr_backend.HerdrError, "continuity changed"):
                asyncio.run(backend.revalidate_manual_agent(candidate))

    def test_resource_revalidation_accepts_process_replacement_at_exact_locus(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            backend, state = manual_backend(root)
            candidate = asyncio.run(backend.manual_agent_candidates())["candidates"][0]
            old_fingerprint = candidate["process"]["fingerprint"]
            state["agent"] = agy_agent(root, pid=5678)

            current = asyncio.run(backend.revalidate_manual_agent_resource(candidate))

        self.assertEqual(current["resource_key"], candidate["resource_key"])
        self.assertNotEqual(current["process"]["fingerprint"], old_fingerprint)

    def test_resource_revalidation_never_rebinds_locus_kind_or_name_drift(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for field, value in (
                ("pane_id", "w-manual:p9"),
                ("terminal_id", "term-other"),
                ("agent", "pi"),
                ("name", "other-agent"),
            ):
                with self.subTest(field=field):
                    backend, state = manual_backend(root)
                    candidate = asyncio.run(backend.manual_agent_candidates())["candidates"][0]
                    state["agent"] = {**state["agent"], field: value}
                    if field == "pane_id":
                        state["panes"] = [{
                            **state["panes"][0],
                            "pane_id": value,
                            "terminal_id": state["agent"]["terminal_id"],
                        }]
                    with self.assertRaises(herdr_backend.HerdrError) as raised:
                        asyncio.run(backend.revalidate_manual_agent_resource(candidate))
                    self.assertEqual(
                        raised.exception.code,
                        "manual_candidate_observation_unavailable",
                    )

    def test_resource_revalidation_fails_closed_on_ambiguous_or_missing_process_evidence(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            backend, state = manual_backend(root)
            candidate = asyncio.run(backend.manual_agent_candidates())["candidates"][0]

            state["created_agents"].append(dict(state["agent"]))
            with self.assertRaises(herdr_backend.HerdrError) as ambiguous:
                asyncio.run(backend.revalidate_manual_agent_resource(candidate))
            self.assertEqual(ambiguous.exception.code, "manual_candidate_identity_ambiguous")

            state["created_agents"].clear()
            state["process_info"] = {
                "pane_id": state["agent"]["pane_id"],
                "foreground_process_group_id": None,
                "foreground_processes": [],
            }
            with self.assertRaises(herdr_backend.HerdrError) as unavailable:
                asyncio.run(backend.revalidate_manual_agent_resource(candidate))
            self.assertEqual(unavailable.exception.code, "manual_candidate_process_unavailable")

    def test_process_evidence_requires_exactly_one_declared_group_leader(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for leader_processes in (
                [{"pid": 5678, "argv": ["git", "status"], "cwd": str(root)}],
                [
                    {"pid": 1234, "argv": ["agy"], "cwd": str(root)},
                    {"pid": 1234, "argv": ["agy", "--duplicate"], "cwd": str(root)},
                ],
            ):
                with self.subTest(leader_processes=leader_processes):
                    backend, state = manual_backend(root)
                    state["process_info"] = {
                        "pane_id": "w-manual:p1",
                        "foreground_process_group_id": 1234,
                        "foreground_cwd": str(root),
                        "foreground_processes": leader_processes,
                    }

                    candidate = asyncio.run(backend.manual_agent_candidates())["candidates"][0]

                    self.assertFalse(candidate["process"]["available"])
                    with self.assertRaises(herdr_backend.HerdrError) as unavailable:
                        asyncio.run(backend.revalidate_manual_agent_resource(candidate))
                    self.assertEqual(
                        unavailable.exception.code,
                        "manual_candidate_process_unavailable",
                    )

    def test_malformed_present_kind_or_name_never_aliases_resource_identity(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for field, value in (("agent", "bad kind"), ("name", "bad name"), ("name", 7)):
                with self.subTest(field=field, value=value):
                    backend, state = manual_backend(root)
                    candidate = asyncio.run(backend.manual_agent_candidates())["candidates"][0]
                    state["agent"] = {**state["agent"], field: value}

                    with self.assertRaises(herdr_backend.HerdrError) as unavailable:
                        asyncio.run(backend.revalidate_manual_agent_resource(candidate))

                    self.assertEqual(
                        unavailable.exception.code,
                        "manual_candidate_identity_ambiguous",
                    )

    def test_malformed_same_locus_sibling_makes_resource_revalidation_ambiguous(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            backend, state = manual_backend(root)
            candidate = asyncio.run(backend.manual_agent_candidates())["candidates"][0]
            state["created_agents"].append({**state["agent"], "name": "bad name"})

            with self.assertRaises(herdr_backend.HerdrError) as ambiguous:
                asyncio.run(backend.revalidate_manual_agent_resource(candidate))

            self.assertEqual(ambiguous.exception.code, "manual_candidate_identity_ambiguous")

    def test_different_kind_or_name_same_locus_sibling_is_ambiguous(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for field, value in (("agent", "pi"), ("name", "other-agent")):
                with self.subTest(field=field):
                    backend, state = manual_backend(root)
                    candidate = asyncio.run(backend.manual_agent_candidates())["candidates"][0]
                    state["created_agents"].append({**state["agent"], field: value})

                    with self.assertRaises(herdr_backend.HerdrError) as ambiguous:
                        asyncio.run(backend.revalidate_manual_agent_resource(candidate))

                    self.assertEqual(
                        ambiguous.exception.code,
                        "manual_candidate_identity_ambiguous",
                    )

    def test_child_cwd_churn_preserves_read_and_fingerprint_without_path_leak(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            backend, state = manual_backend(root)
            candidate = asyncio.run(backend.manual_agent_candidates())["candidates"][0]
            fingerprint = candidate["process"]["fingerprint"]
            for child_cwd in (str(root / "PRIVATE-child"), None, str(root)):
                with self.subTest(child_cwd=child_cwd):
                    state["process_info"] = process_info(state["agent"])
                    state["process_info"]["foreground_processes"].append(
                        {"pid": 5678, "argv": ["git", "status"], "cwd": child_cwd})
                    current = asyncio.run(backend.revalidate_manual_agent_resource(candidate))
                    self.assertEqual(current["process"]["fingerprint"], fingerprint)
                    self.assertNotIn("PRIVATE-child", json.dumps(current["process"]["public"]))
                    self.assertEqual(asyncio.run(backend.read_manual_agent(candidate, limit=10))["text"],
                                     "manual output")
            state["process_info"]["foreground_processes"].pop()
            current = asyncio.run(backend.revalidate_manual_agent_resource(candidate))
            self.assertEqual(current["process"]["fingerprint"], fingerprint)

    def test_process_cwd_observations_preserve_shape_and_redaction(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for source in ("aggregate", "leader"):
                with self.subTest(source=source):
                    info = process_info(agy_agent(root))
                    info["foreground_processes"].append({"pid": 5678, "argv": ["git"], "cwd": str(root)})
                    if source == "aggregate":
                        info["foreground_cwd"] = str(root / "other")
                    else:
                        info["foreground_processes"][0]["cwd"] = str(root / "other")
                    evidence = herdr_backend.HerdrBackend._manual_process_evidence(info, "w-manual:p1", root)
                    self.assertTrue(evidence["available"])
                    self.assertNotIn(str(root / "other"), json.dumps(evidence["public"]))
                    self.assertEqual(evidence["fingerprint"], {
                        "process_group_id": 1234,
                        "leader": {"pid": 1234, "argv": ["agy", "--dangerously-skip-permissions"]}})
            for invalid in ("", 3, {}, "x" * (herdr_backend.MAX_OUTPUT + 1)):
                info = process_info(agy_agent(root))
                info["foreground_processes"].append({"pid": 5678, "argv": ["git"], "cwd": invalid})
                with self.subTest(invalid_type=type(invalid).__name__), self.assertRaises(herdr_backend.HerdrError):
                    herdr_backend.HerdrBackend._manual_process_evidence(info, "w-manual:p1", root)

    def test_work_watcher_tolerates_same_execution_group_child_churn(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            backend, state = manual_backend(root)
            candidate = asyncio.run(backend.manual_agent_candidates())["candidates"][0]
            state["agent"]["state_change_seq"] = 2
            state["process_info"] = {
                "pane_id": "w-manual:p1",
                "foreground_process_group_id": 1234,
                "foreground_cwd": str(root),
                "foreground_processes": [
                    {
                        "pid": 1234,
                        "argv": ["agy", "--dangerously-skip-permissions"],
                        "cwd": str(root),
                    },
                    {
                        "pid": 5678,
                        "argv": ["git", "status"],
                        "cwd": str(root),
                    },
                ],
            }

            with patch.object(herdr_backend, 'SETTLEMENT_CONFIRM_SECONDS', 0.0), \
                    patch.object(herdr_backend, 'SETTLEMENT_CONFIRM_ATTEMPTS', 1):
                result = asyncio.run(backend.watch_manual_agent_turn(candidate, 1, 1))

        self.assertEqual(result["state"], "done")
        self.assertEqual(result["reason"], "state_transition_proven")

    def test_manual_read_tolerates_ephemeral_subshells_under_agent(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            backend, state = manual_backend(root)
            candidate = asyncio.run(backend.manual_agent_candidates())["candidates"][0]
            state["process_info"] = {
                "pane_id": "w-manual:p1",
                "foreground_process_group_id": 1234,
                "foreground_cwd": str(root),
                "foreground_processes": [
                    {
                        "pid": 1234,
                        "argv": ["agy", "--dangerously-skip-permissions"],
                        "cwd": str(root),
                    },
                    {
                        "pid": 5678,
                        "argv": ["git", "status"],
                        "cwd": str(root),
                    },
                ],
            }
            result = asyncio.run(backend.read_manual_agent(candidate, limit=10))
            self.assertEqual(result["text"], "manual output")

    def test_manual_read_raw_text_cli_handling(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            backend, state = manual_backend(root)
            candidate = asyncio.run(backend.manual_agent_candidates())["candidates"][0]
            state["text"] = "plain terminal text output\nsecond line"
            result = asyncio.run(backend.read_manual_agent(candidate, limit=5))
            self.assertEqual(result["text"], "plain terminal text output\nsecond line")

    def test_manual_read_is_bounded_and_revalidates_before_pane_read(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            backend, state = manual_backend(root)
            candidate = asyncio.run(backend.manual_agent_candidates())["candidates"][0]
            state["text"] = "x" * (herdr_backend.MAX_MANUAL_AGENT_READ_TEXT + 1)
            result = asyncio.run(backend.read_manual_agent(candidate, limit=7))

        self.assertTrue(result["truncated"])
        self.assertEqual(result["chars"], herdr_backend.MAX_MANUAL_AGENT_READ_TEXT + 1)
        self.assertTrue(result["text"].startswith("x" * herdr_backend.MAX_MANUAL_AGENT_READ_TEXT))
        self.assertIn("truncated 1 chars", result["text"])
        pane_read = [call for call in state["calls"] if call[:2] == ("pane", "read")]
        self.assertEqual(len(pane_read), 1)
        self.assertEqual(pane_read[0][2], "w-manual:p1")
        self.assertIn("7", pane_read[0])

    def test_manual_prompt_uses_one_exact_pane_native_transport(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            backend, state = manual_backend(root)
            candidate = asyncio.run(backend.manual_agent_candidates())["candidates"][0]
            transport = asyncio.run(backend.prompt_manual_agent(candidate, "send this turn"))

        self.assertEqual(transport["mode"], "native_herdr")
        self.assertEqual(transport["target"], "exact_pane")
        self.assertEqual(transport["completion"], "unattributed")
        self.assertEqual(
            [call for call in state["calls"] if call[:2] == ("agent", "prompt")],
            [("agent", "prompt", "w-manual:p1", "send this turn")],
        )
        self.assertEqual(
            [call for call in state["calls"] if call[:2] in {
                ("agent", "send-keys"),
                ("pane", "send-text"),
                ("pane", "send-keys"),
            }],
            [],
        )

    def test_manual_prompt_rejects_non_ready_status_without_transport(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            backend, state = manual_backend(root)
            candidate = asyncio.run(backend.manual_agent_candidates())["candidates"][0]
            state["agent"]["agent_status"] = "working"
            current = asyncio.run(backend.revalidate_manual_agent(candidate))
            with self.assertRaises(herdr_backend.ManualAgentPromptNotReady):
                asyncio.run(backend.prompt_manual_agent(current, "do not send"))

        self.assertEqual(
            [call for call in state["calls"] if call[:2] == ("agent", "prompt")],
            [],
        )


class ManualAgentServerTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self._work_patch = patch.object(server, "_WORK_REGISTRY", {})
        self._work_patch.start()
        self._inbox_patch = patch.object(server, "_RESULT_INBOX", {})
        self._inbox_patch.start()
        self._candidate_patch = patch.object(server, "_MANUAL_AGENT_CANDIDATES", {})
        self._handoff_patch = patch.object(server, "_HANDOFF_REGISTRY", {})
        self._candidate_patch.start()
        self._handoff_patch.start()

    async def asyncTearDown(self):
        self._handoff_patch.stop()
        self._candidate_patch.stop()
        self._inbox_patch.stop()
        self._work_patch.stop()
        server._ACCESS_GATES.clear()


    async def test_read_refreshes_replaced_process_on_same_resource(self):
        backend, state = manual_backend(server.ROOT)
        with patch.object(server, "HERDR", backend):
            listed = await server._discover_project_candidates()
            candidate_id = listed["candidates"][0]["candidate_id"]
            state["agent"] = agy_agent(server.ROOT, pid=7777)
            result = await server._read_agent_candidate(candidate_id, limit=8)

        self.assertTrue(result["ok"], result)
        self.assertEqual(result["candidate"]["candidate_id"], candidate_id)
        self.assertEqual(
            len([call for call in state["calls"] if call[:2] == ("pane", "read")]), 1
        )

    async def test_read_rejects_target_conflicts_but_not_wrapper_cwd_observations(self):
        mismatch = str(server.ROOT / "other-workspace")
        for source in ("agent", "foreground", "process"):
            with self.subTest(source=source):
                server._MANUAL_AGENT_CANDIDATES.clear()
                backend, state = manual_backend(server.ROOT)
                with patch.object(server, "HERDR", backend):
                    listed = await server._discover_project_candidates()
                    candidate_id = listed["candidates"][0]["candidate_id"]
                    if source == "agent":
                        state["agent"]["foreground_cwd"] = mismatch
                    else:
                        state["process_info"] = process_info(state["agent"])
                        if source == "foreground":
                            state["process_info"]["foreground_cwd"] = mismatch
                        else:
                            state["process_info"]["foreground_processes"][0]["cwd"] = mismatch
                    result = await server._read_agent_candidate(candidate_id, limit=8)

                reads = [call for call in state["calls"] if call[:2] == ("pane", "read")]
                if source == "agent":
                    self.assertFalse(result["ok"])
                    self.assertEqual(result["error_type"], "ManualCandidateObservationUnavailable")
                    self.assertEqual(result["reason"], "observation_unavailable")
                    self.assertEqual(reads, [])
                else:
                    self.assertTrue(result["ok"])
                    self.assertEqual(len(reads), 1)
                    self.assertNotIn(mismatch, json.dumps(result))

    async def test_read_rejects_33rd_foreground_process_change_before_terminal_read(self):
        backend, state = manual_backend(server.ROOT)
        state["process_info"] = process_info(state["agent"])
        state["process_info"]["foreground_processes"] = [
            {
                "pid": 10_000 + index,
                "argv": ["agy", "--worker", str(index)],
                "cwd": str(server.ROOT),
            }
            for index in range(herdr_backend.MAX_PROBE_AGENTS + 1)
        ]
        with patch.object(server, "HERDR", backend):
            listed = await server._discover_project_candidates()
            candidate = listed["candidates"][0]
            candidate_id = candidate["candidate_id"]
            state["process_info"]["foreground_processes"][-1]["argv"][-1] = "replaced"
            result = await server._read_agent_candidate(candidate_id, limit=8)

        self.assertEqual(
            candidate["foreground_process"]["reason"],
            "foreground_process_count_exceeds_safe_limit",
        )
        self.assertEqual(candidate["continuity"]["read_status"], "unavailable")
        self.assertFalse(result["ok"])
        self.assertEqual(result["error_type"], "ManualCandidateObservationUnavailable")
        self.assertEqual(result["reason"], "observation_unavailable")
        self.assertEqual(
            [call for call in state["calls"] if call[:2] == ("pane", "read")], []
        )

    async def test_read_accepts_session_churn_before_terminal_read(self):
        for kind, initial, replacement in (
            ("id", "native-session-a", "native-session-b"),
            ("path", "/tmp/native-session-a.jsonl", "/tmp/native-session-b.jsonl"),
        ):
            with self.subTest(kind=kind):
                server._MANUAL_AGENT_CANDIDATES.clear()
                backend, state = manual_backend(server.ROOT)
                state["agent"]["agent_session"] = {"kind": kind, "value": initial}
                with patch.object(server, "HERDR", backend):
                    listed = await server._discover_project_candidates()
                    candidate_id = listed["candidates"][0]["candidate_id"]
                    state["agent"]["agent_session"] = {
                        "kind": kind,
                        "value": replacement,
                    }
                    result = await server._read_agent_candidate(candidate_id, limit=8)

                self.assertTrue(result["ok"])
                self.assertIn("read", result)
                self.assertIn("text", result["read"])


    async def test_watcher_latches_done_on_seq_advance(self):
        """Herdr-native proof: settled status + state_change_seq advance = done."""
        server._HANDOFF_REGISTRY.clear()
        backend, state = manual_backend(server.ROOT)
        with patch.object(server, "HERDR", backend):
            listed = await server._discover_project_candidates()
            candidate_id = listed["candidates"][0]["candidate_id"]
            result = await dispatch_candidate(candidate_id, "turn to complete")
            hid = result["handoff_id"]
            observed_handoff = server._HANDOFF_REGISTRY[hid]
            watcher = observed_handoff["watcher_task"]
            self.assertIsNotNone(watcher)
            await watcher

        self.assertNotIn(hid, server._HANDOFF_REGISTRY)
        entry = observed_handoff
        self.assertEqual(entry["state"], "done")
        self.assertEqual(entry["reason"], "state_transition_proven")
        self.assertEqual(entry["herdr_status"], "idle")
        self.assertEqual(entry["post_state_change_seq"], 2)
        self.assertEqual(entry["post_revision"], 2)

    async def test_agy_turn_with_constant_revision_latches_done(self):
        """EVO-027 case 1: AGY advances state_change_seq but never revision.

        Herdr bumps the pane ``revision`` only on stripped terminal title and
        metadata-token changes; AGY's session-only integration hook never
        rewrites either, so a completed AGY turn keeps ``revision`` constant.
        The transition proof must therefore rely on Herdr's own
        ``state_change_seq`` turn signal and still latch done.
        """
        server._HANDOFF_REGISTRY.clear()
        backend, state = manual_backend(server.ROOT)

        def prompt_handler(*args):
            # AGY turn ran and settled: seq advanced 1 -> 4, revision stayed 1.
            state["agent"]["state_change_seq"] = 4
            state["agent"]["revision"] = 1
            return {"agent": state["agent"]}
        state["prompt_handler"] = prompt_handler

        with patch.object(server, "HERDR", backend):
            listed = await server._discover_project_candidates()
            candidate_id = listed["candidates"][0]["candidate_id"]
            result = await dispatch_candidate(candidate_id, "agy real turn")
            hid = result["handoff_id"]
            observed_handoff = server._HANDOFF_REGISTRY[hid]
            watcher = observed_handoff["watcher_task"]
            await watcher

        self.assertNotIn(hid, server._HANDOFF_REGISTRY)
        entry = observed_handoff
        self.assertEqual(entry["state"], "done")
        self.assertEqual(entry["reason"], "state_transition_proven")
        self.assertEqual(entry["post_state_change_seq"], 4)
        self.assertEqual(entry["post_revision"], 1)
        self.assertEqual(entry["pre_revision"], 1)


    async def test_revision_only_advance_never_latches_done(self):
        """Negative: title/metadata churn (revision advance) with no Herdr
        state_change_seq advancement must not become completion attribution;
        a settled pane without a proven transition stays needs_attention."""
        server._HANDOFF_REGISTRY.clear()
        backend, state = manual_backend(server.ROOT)

        def prompt_handler(*args):
            # Pane title churn advanced revision, but no agent state change
            # was ever sampled: seq stays at the pre-turn value.
            state["agent"]["agent_status"] = "working"
            state["agent"]["revision"] = 5
            return {"agent": state["agent"]}
        state["prompt_handler"] = prompt_handler

        def wait_handler(*args, **kwargs):
            state["agent"]["agent_status"] = "idle"
            state["agent"]["state_change_seq"] = 1
            state["agent"]["revision"] = 6
            return {"agent": state["agent"]}
        state["wait_handler"] = wait_handler

        with patch.object(server, "HERDR", backend):
            listed = await server._discover_project_candidates()
            candidate_id = listed["candidates"][0]["candidate_id"]
            result = await dispatch_candidate(candidate_id, "title churn only")
            hid = result["handoff_id"]
            observed_handoff = server._HANDOFF_REGISTRY[hid]
            watcher = observed_handoff["watcher_task"]
            await watcher

        self.assertNotIn(hid, server._HANDOFF_REGISTRY)
        entry = observed_handoff
        self.assertEqual(entry["state"], "needs_attention")
        self.assertEqual(entry["reason"], "transition_unproven")
        self.assertEqual(entry["post_state_change_seq"], 1)
        self.assertEqual(entry["post_revision"], 6)

    async def test_slow_working_turn_invokes_settled_barrier_with_timeout_none(self):
        server._HANDOFF_REGISTRY.clear()
        backend, state = manual_backend(server.ROOT)
        # After prompt, agent status is working with advanced sequence
        def prompt_handler(*args):
            state["agent"]["agent_status"] = "working"
            state["agent"]["state_change_seq"] = 2
            state["agent"]["revision"] = 2
            return {"agent": state["agent"]}
        state["prompt_handler"] = prompt_handler

        wait_calls = []
        def wait_handler(*args, **kwargs):
            wait_calls.append((args, kwargs))
            # Settle to done
            state["agent"]["agent_status"] = "done"
            return {"agent": state["agent"]}
        state["wait_handler"] = wait_handler

        with patch.object(server, "HERDR", backend):
            listed = await server._discover_project_candidates()
            candidate_id = listed["candidates"][0]["candidate_id"]
            result = await dispatch_candidate(candidate_id, "slow turn")
            hid = result["handoff_id"]
            observed_handoff = server._HANDOFF_REGISTRY[hid]
            watcher = observed_handoff["watcher_task"]
            await watcher

        self.assertNotIn(hid, server._HANDOFF_REGISTRY)
        entry = observed_handoff
        self.assertEqual(entry["state"], "done")
        self.assertEqual(entry["reason"], "state_transition_proven")
        self.assertEqual(entry["herdr_status"], "done")
        # Settled wait call must be invoked with timeout=None
        settle_waits = [c for c in wait_calls if c[0][:2] == ("agent", "wait") and "--until" in c[0] and "idle" in c[0]]
        self.assertTrue(len(settle_waits) >= 1)
        self.assertIsNone(settle_waits[0][1].get("timeout"))

    async def test_initial_idle_startup_wait_observes_budget_without_claiming_failure(self):
        from types import SimpleNamespace
        server._HANDOFF_REGISTRY.clear()
        backend, state = manual_backend(server.ROOT)
        state["auto_advance_turn"] = False
        # This test pins the generic budget semantics; keep the AGY cold-path
        # recovery out of it by presenting a non-settled screen shape.
        state["detection_text"] = "unrecognized screen shape"
        clock = [0.0]
        wait_calls = []

        def wait_handler(*args, **kwargs):
            wait_calls.append((args, kwargs))
            # Native status expiry, not a subprocess/transport TimeoutError.
            clock[0] += int(args[args.index("--timeout") + 1]) / 1000
            raise herdr_backend.HerdrError("timed out waiting for agent status", code="timeout")
        state["wait_handler"] = wait_handler

        with patch.object(server, "HERDR", backend), patch.object(
            herdr_backend, "time", SimpleNamespace(monotonic=lambda: clock[0], time=lambda: 0)
        ):
            listed = await server._discover_project_candidates()
            candidate_id = listed["candidates"][0]["candidate_id"]
            result = await dispatch_candidate(candidate_id, "unobserved turn")
            entry = server._HANDOFF_REGISTRY[result["handoff_id"]]
            await entry["watcher_task"]

        self.assertEqual(entry["state"], "needs_attention")
        self.assertEqual(entry["reason"], "activation_observation_budget_exhausted")
        self.assertGreaterEqual(clock[0], 5.0)
        self.assertTrue(wait_calls)
        for args, kwargs in wait_calls:
            self.assertIn("working", args)
            self.assertIn("done", args)
            self.assertIn("blocked", args)
            self.assertNotIn("idle", args)
            self.assertGreater(int(args[args.index("--timeout") + 1]), 0)

    async def test_manual_handoff_watcher_latches_needs_attention_on_blocked(self):
        server._HANDOFF_REGISTRY.clear()
        backend, state = manual_backend(server.ROOT)
        def prompt_handler(*args):
            state["agent"]["agent_status"] = "working"
            state["agent"]["state_change_seq"] = 2
            state["agent"]["revision"] = 2
            return {"agent": state["agent"]}
        state["prompt_handler"] = prompt_handler

        def wait_handler(*args, **kwargs):
            state["agent"]["agent_status"] = "blocked"
            return {"agent": state["agent"]}
        state["wait_handler"] = wait_handler

        with patch.object(server, "HERDR", backend):
            listed = await server._discover_project_candidates()
            candidate_id = listed["candidates"][0]["candidate_id"]
            result = await dispatch_candidate(candidate_id, "turn to block")
            hid = result["handoff_id"]
            observed_handoff = server._HANDOFF_REGISTRY[hid]
            watcher = observed_handoff["watcher_task"]
            await watcher

        self.assertNotIn(hid, server._HANDOFF_REGISTRY)
        entry = observed_handoff
        self.assertEqual(entry["state"], "needs_attention")
        self.assertEqual(entry["reason"], "agent_blocked")
        self.assertEqual(entry["herdr_status"], "blocked")

    async def test_manual_handoff_watcher_latches_failed_on_replacement_agent_without_rebinding(self):
        server._HANDOFF_REGISTRY.clear()
        backend, state = manual_backend(server.ROOT)
        snapshot_calls = 0
        original_agent = dict(state["agent"])
        def snapshot_handler(*args):
            nonlocal snapshot_calls
            snapshot_calls += 1
            if snapshot_calls <= 2:
                # Listing (1) and pre-submit revalidation (2): original agent with PID 1234
                return {
                    "snapshot": {
                        "agents": [original_agent],
                        "panes": state.get("panes", [{"workspace_id": state["workspace_id"], "pane_id": "w-manual:p1", "cwd": str(server.ROOT), "terminal_id": "term-w-manual:p1"}]),
                        "tabs": state.get("tabs", []),
                        "workspaces": [{"workspace_id": state["workspace_id"], "label": "GPT Web Bridge"}],
                    }
                }
            else:
                # Post-submit revalidation in watcher: replacement agent with PID 99999
                replacement = agy_agent(server.ROOT, pid=99999)
                state["agent"] = replacement
                return {
                    "snapshot": {
                        "agents": [replacement],
                        "panes": state.get("panes", [{"workspace_id": state["workspace_id"], "pane_id": "w-manual:p1", "cwd": str(server.ROOT), "terminal_id": "term-w-manual:p1"}]),
                        "tabs": state.get("tabs", []),
                        "workspaces": [{"workspace_id": state["workspace_id"], "label": "GPT Web Bridge"}],
                    }
                }
        state["snapshot_handler"] = snapshot_handler
        with patch.object(server, "HERDR", backend):
            listed = await server._discover_project_candidates()
            candidate_id = listed["candidates"][0]["candidate_id"]
            result = await dispatch_candidate(candidate_id, "turn with replacement")
            hid = result["handoff_id"]
            observed_handoff = server._HANDOFF_REGISTRY[hid]
            watcher = observed_handoff["watcher_task"]
            await watcher

        self.assertNotIn(hid, server._HANDOFF_REGISTRY)
        entry = observed_handoff
        self.assertEqual(entry["state"], "failed")
        self.assertEqual(entry["reason"], "candidate_continuity_lost")
        # Candidate record in server._MANUAL_AGENT_CANDIDATES was NOT rebound to replacement!
        stored = server._MANUAL_AGENT_CANDIDATES[candidate_id]["candidate"]


    async def test_manual_handoff_watcher_read_unavailable_latches_needs_attention_not_failed(self):
        server._HANDOFF_REGISTRY.clear()
        backend, state = manual_backend(server.ROOT)
        snapshot_calls = 0
        def snapshot_handler(*args):
            nonlocal snapshot_calls
            snapshot_calls += 1
            if snapshot_calls <= 2:
                return {
                    "snapshot": {
                        "agents": [state["agent"]],
                        "panes": state.get("panes", [{"workspace_id": state["workspace_id"], "pane_id": "w-manual:p1", "cwd": str(server.ROOT), "terminal_id": "term-w-manual:p1"}]),
                        "tabs": state.get("tabs", []),
                        "workspaces": [{"workspace_id": state["workspace_id"], "label": "GPT Web Bridge"}],
                    }
                }
            raise herdr_backend.HerdrError("terminal read unavailable", code="manual_candidate_read_unavailable")

        state["snapshot_handler"] = snapshot_handler
        with patch.object(server, "HERDR", backend):
            listed = await server._discover_project_candidates()
            candidate_id = listed["candidates"][0]["candidate_id"]
            result = await dispatch_candidate(candidate_id, "turn with read failure")
            hid = result["handoff_id"]
            observed_handoff = server._HANDOFF_REGISTRY[hid]
            watcher = observed_handoff["watcher_task"]
            await watcher

        self.assertNotIn(hid, server._HANDOFF_REGISTRY)
        entry = observed_handoff
        self.assertEqual(entry["state"], "needs_attention")
        self.assertEqual(entry["reason"], "observation_unavailable")


    async def test_terminal_handoff_is_immutable_once_latched(self):
        server._HANDOFF_REGISTRY.clear()
        hid = server._generate_handoff_id()
        server._HANDOFF_REGISTRY[hid] = {
            "handoff_id": hid, "candidate_id": "c1", "candidate": {}, "workspace_ref": None,
            "workspace_root": str(server.ROOT), "dispatched_at": 100.0, "state": "done", "reason": "state_transition_proven",
            "herdr_status": "idle", "pre_state_change_seq": 1, "post_state_change_seq": 2,
            "pre_revision": 1, "post_revision": 2, "latched_at": 105.0, "watcher_task": None,
            "join_waiters": 0, "joined_once": False,
        }
        # Attempting to update an already terminal state is a no-op
        server._update_handoff_entry(hid, state="needs_attention", reason="agent_blocked", herdr_status="blocked")
        self.assertEqual(server._HANDOFF_REGISTRY[hid]["state"], "done")
        self.assertEqual(server._HANDOFF_REGISTRY[hid]["reason"], "state_transition_proven")


    async def test_workspace_ref_scopes_discovery_and_rejects_unknown_scope(self):
        with tempfile.TemporaryDirectory() as temp:
            target = git_worktree(Path(temp) / "target")
            registry = WorkspaceRegistry(
                server.ROOT, json.dumps({"review": str(target)})
            )
            backend, _state = manual_backend(target)
            with patch.object(server, "_WORKSPACE_REGISTRY", registry), patch.object(
                server, "_WORKSPACE_BACKENDS", {str(target): backend}
            ):
                scoped = await server._discover_project_candidates(workspace_ref="review")
                unknown = await server._discover_project_candidates(workspace_ref="not-authorized")

        self.assertTrue(scoped["ok"])
        self.assertEqual(scoped["workspace_ref"], "review")
        self.assertEqual(scoped["candidates"][0]["cwd"], str(target))
        self.assertFalse(unknown["ok"])
        self.assertEqual(unknown["error_type"], "WorkspaceRefUnauthorized")


    async def test_candidate_id_unknown_after_process_registry_loss(self):
        backend, _state = manual_backend(server.ROOT)
        with patch.object(server, "HERDR", backend):
            listed = await server._discover_project_candidates()
            candidate_id = listed["candidates"][0]["candidate_id"]
            server._MANUAL_AGENT_CANDIDATES.clear()
            result = await server._read_agent_candidate(candidate_id)

        self.assertFalse(result["ok"])
        self.assertEqual(result["error_type"], "UnknownManualAgentCandidate")

    async def test_read_succeeds_with_subshell_and_plain_text(self):
        backend, state = manual_backend(server.ROOT)
        state["text"] = "Line 1: AGY running\nLine 2: output"
        with patch.object(server, "HERDR", backend):
            listed = await server._discover_project_candidates()
            candidate_id = listed["candidates"][0]["candidate_id"]
            # Subprocess runs under agent leader process group
            state["process_info"] = {
                "pane_id": "w-manual:p1",
                "foreground_process_group_id": 1234,
                "foreground_cwd": str(server.ROOT),
                "foreground_processes": [
                    {
                        "pid": 1234,
                        "argv": ["agy", "--dangerously-skip-permissions"],
                        "cwd": str(server.ROOT),
                    },
                    {
                        "pid": 9999,
                        "argv": ["bash", "-c", "pytest"],
                        "cwd": str(server.ROOT),
                    },
                ],
            }
            result = await server._read_agent_candidate(candidate_id, limit=20)

        self.assertTrue(result["ok"])
        self.assertEqual(result["read"]["text"], "Line 1: AGY running\nLine 2: output")
        self.assertEqual(result["read"]["chars"], len("Line 1: AGY running\nLine 2: output"))
        self.assertFalse(result["read"]["truncated"])


    async def test_prompt_revalidates_then_uses_only_exact_pane_native_prompt(self):
        backend, state = manual_backend(server.ROOT)
        with patch.object(server, "HERDR", backend):
            listed = await server._discover_project_candidates()
            candidate_id = listed["candidates"][0]["candidate_id"]
            result = await dispatch_candidate(candidate_id, "send this turn")

        self.assertTrue(result["ok"])
        self.assertEqual(result["state"], "native_herdr_response_received")
        self.assertEqual(result["prompt_transport"]["mode"], "native_herdr")
        self.assertEqual(result["prompt_transport"]["status"], "native_response_received")
        self.assertEqual(result["prompt_transport"]["identity_guard"], "herdr_native_preflight")
        self.assertEqual(result["completion"], "unattributed")
        self.assertEqual(result["result"], "unattributed")
        self.assertEqual(result["attribution"], "none")
        self.assertEqual(
            [call for call in state["calls"] if call[:2] == ("agent", "prompt")],
            [("agent", "prompt", "w-manual:p1", "send this turn")],
        )
        self.assertEqual(
            [call for call in state["calls"] if call[:2] in {
                ("agent", "send-keys"), ("pane", "send-text"),
                ("pane", "send-keys"),
            }],
            [],
        )


    async def test_prompt_refreshes_replaced_process_on_same_resource(self):
        backend, state = manual_backend(server.ROOT)
        with patch.object(server, "HERDR", backend):
            listed = await server._discover_project_candidates()
            candidate_id = listed["candidates"][0]["candidate_id"]
            state["agent"] = agy_agent(server.ROOT, pid=9876)
            result = await dispatch_candidate(candidate_id, "send to refreshed resource")

        self.assertTrue(result["ok"], result)
        self.assertEqual(
            [call for call in state["calls"] if call[:2] == ("agent", "prompt")],
            [("agent", "prompt", "w-manual:p1", "send to refreshed resource")],
        )


    async def test_prompt_non_ready_status_rejects_before_zero_input(self):
        for status in ("working", "blocked", "unknown"):
            with self.subTest(status=status):
                server._MANUAL_AGENT_CANDIDATES.clear()
                backend, state = manual_backend(server.ROOT)
                state["agent"]["agent_status"] = status
                with patch.object(server, "HERDR", backend):
                    listed = await server._discover_project_candidates()
                    candidate_id = listed["candidates"][0]["candidate_id"]
                    result = await dispatch_candidate(candidate_id, "never transport this")

                self.assertFalse(result["ok"])
                self.assertEqual(result["error_type"], "ManualAgentPromptNotReady")
                self.assertEqual(result["prompt_transport"]["status"], "not_attempted")
                self.assertEqual(
                    [call for call in state["calls"] if call[:2] == ("agent", "prompt")],
                    [],
                )


    async def test_native_prompt_error_is_not_retried_or_fallback_transported(self):
        backend, state = manual_backend(server.ROOT)
        state["prompt_error"] = herdr_backend.HerdrError(
            "native prompt rejected", code="agent_not_ready"
        )
        with patch.object(server, "HERDR", backend):
            listed = await server._discover_project_candidates()
            candidate_id = listed["candidates"][0]["candidate_id"]
            result = await dispatch_candidate(candidate_id, "send once")

        self.assertFalse(result["ok"])
        self.assertEqual(result["error_type"], "ManualAgentPromptTransportError")
        self.assertEqual(result["native_error_code"], "agent_not_ready")
        self.assertEqual(result["prompt_transport"]["status"], "transport_uncertain")
        self.assertTrue(result["handoff_id"].startswith("handoff-"))
        self.assertEqual(result["handoff"]["state"], "running")
        self.assertEqual(
            [call for call in state["calls"] if call[:2] == ("agent", "prompt")],
            [("agent", "prompt", "w-manual:p1", "send once")],
        )
        self.assertEqual(
            [call for call in state["calls"] if call[:2] in {
                ("agent", "send-keys"), ("pane", "send-text"),
                ("pane", "send-keys"),
            }],
            [],
        )


    async def test_native_prompt_timeout_is_ambiguous_without_retry(self):
        backend, state = manual_backend(server.ROOT)
        state["prompt_error"] = TimeoutError("native prompt timed out")
        with patch.object(server, "HERDR", backend):
            listed = await server._discover_project_candidates()
            candidate_id = listed["candidates"][0]["candidate_id"]
            result = await dispatch_candidate(candidate_id, "send once")

        self.assertFalse(result["ok"])
        self.assertEqual(result["error_type"], "ManualAgentPromptTransportError")
        self.assertEqual(result["prompt_transport"]["status"], "transport_uncertain")
        self.assertEqual(
            [call for call in state["calls"] if call[:2] == ("agent", "prompt")],
            [("agent", "prompt", "w-manual:p1", "send once")],
        )


    async def test_manual_agent_prompt_returns_fast_and_releases_writer_lease(self):
        server._HANDOFF_REGISTRY.clear()
        backend, state = manual_backend(server.ROOT)
        gate = server._access_gate(server.ROOT)
        with patch.object(server, "HERDR", backend):
            listed = await server._discover_project_candidates()
            candidate_id = listed["candidates"][0]["candidate_id"]
            result = await dispatch_candidate(candidate_id, "fast dispatch turn")

        self.assertTrue(result["ok"])
        self.assertTrue(result["handoff_id"].startswith("handoff-"))
        self.assertEqual(result["handoff"]["state"], "running")
        self.assertEqual(result["handoff"]["herdr_status"], "idle")
        self.assertEqual(result["handoff"]["handoff_id"], result["handoff_id"])
        self.assertEqual(result["completion"], "unattributed")
        self.assertEqual(result["result"], "unattributed")
        self.assertEqual(result["attribution"], "none")
        # Writer lease is released immediately upon return from prompt
        self.assertFalse(gate.writer_active)
        self.assertEqual(gate.waiting_writers, 0)
        # Handoff is registered in process-local registry without raw task text
        self.assertIn(result["handoff_id"], server._HANDOFF_REGISTRY)
        self.assertNotIn("task", server._HANDOFF_REGISTRY[result["handoff_id"]])


    async def test_prompt_transport_timeout_returns_uncertain_with_handoff_id_and_retained_watcher(self):
        server._HANDOFF_REGISTRY.clear()
        backend, state = manual_backend(server.ROOT)
        state["prompt_error"] = TimeoutError("native prompt timed out")
        with patch.object(server, "HERDR", backend):
            listed = await server._discover_project_candidates()
            candidate_id = listed["candidates"][0]["candidate_id"]
            result = await dispatch_candidate(candidate_id, "send ambiguous")

        self.assertFalse(result["ok"])
        self.assertEqual(result["error_type"], "ManualAgentPromptTransportError")
        self.assertEqual(result["prompt_transport"]["status"], "transport_uncertain")
        self.assertTrue(result["handoff_id"].startswith("handoff-"))
        self.assertEqual(result["handoff"]["state"], "running")
        # Handoff entry is retained in registry and watcher is running
        self.assertIn(result["handoff_id"], server._HANDOFF_REGISTRY)
        self.assertIsNotNone(server._HANDOFF_REGISTRY[result["handoff_id"]]["watcher_task"])
        self.assertEqual(
            [call for call in state["calls"] if call[:2] == ("agent", "prompt")],
            [("agent", "prompt", "w-manual:p1", "send ambiguous")],
        )


    async def test_prompt_transport_herdr_error_retains_running_handoff_and_starts_watcher(self):
        server._HANDOFF_REGISTRY.clear()
        backend, state = manual_backend(server.ROOT)
        state["prompt_error"] = herdr_backend.HerdrError("agent not ready", code="manual_agent_prompt_not_ready")
        with patch.object(server, "HERDR", backend):
            listed = await server._discover_project_candidates()
            candidate_id = listed["candidates"][0]["candidate_id"]
            result = await dispatch_candidate(candidate_id, "send rejected")

        self.assertFalse(result["ok"])
        self.assertEqual(result["error_type"], "ManualAgentPromptTransportError")
        self.assertEqual(result["prompt_transport"]["status"], "transport_uncertain")
        self.assertTrue(result["handoff_id"].startswith("handoff-"))
        self.assertEqual(result["handoff"]["state"], "running")
        # Reservation is retained in registry with watcher task running
        self.assertIn(result["handoff_id"], server._HANDOFF_REGISTRY)
        self.assertIsNotNone(server._HANDOFF_REGISTRY[result["handoff_id"]]["watcher_task"])


    async def test_prompt_transport_codeless_or_malformed_herdr_error_retains_running_handoff_and_starts_watcher(self):
        server._HANDOFF_REGISTRY.clear()
        backend, state = manual_backend(server.ROOT)
        state["prompt_error"] = herdr_backend.HerdrError("Herdr returned malformed JSON") # code is None
        with patch.object(server, "HERDR", backend):
            listed = await server._discover_project_candidates()
            candidate_id = listed["candidates"][0]["candidate_id"]
            result = await dispatch_candidate(candidate_id, "send ambiguous error")

        self.assertFalse(result["ok"])
        self.assertEqual(result["error_type"], "ManualAgentPromptTransportError")
        self.assertEqual(result["prompt_transport"]["status"], "transport_uncertain")
        self.assertTrue(result["handoff_id"].startswith("handoff-"))
        self.assertEqual(result["handoff"]["state"], "running")
        # Reservation is retained in registry with watcher task running, no retry
        self.assertIn(result["handoff_id"], server._HANDOFF_REGISTRY)
        self.assertIsNotNone(server._HANDOFF_REGISTRY[result["handoff_id"]]["watcher_task"])
        self.assertEqual(
            [call for call in state["calls"] if call[:2] == ("agent", "prompt")],
            [("agent", "prompt", "w-manual:p1", "send ambiguous error")],
        )



class ManualCandidateSessionPromotionTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self._work_patch = patch.object(server, "_WORK_REGISTRY", {})
        self._work_patch.start()
        self._inbox_patch = patch.object(server, "_RESULT_INBOX", {})
        self._inbox_patch.start()
        self._orig_candidates = dict(server._MANUAL_AGENT_CANDIDATES)
        self._orig_handoffs = dict(server._HANDOFF_REGISTRY)
        server._MANUAL_AGENT_CANDIDATES.clear()
        server._HANDOFF_REGISTRY.clear()

    def tearDown(self):
        self._inbox_patch.stop()
        self._work_patch.stop()
        server._MANUAL_AGENT_CANDIDATES.clear()
        server._MANUAL_AGENT_CANDIDATES.update(self._orig_candidates)
        server._HANDOFF_REGISTRY.clear()
        server._HANDOFF_REGISTRY.update(self._orig_handoffs)
        server._ACCESS_GATES.clear()


    async def test_promotion_accepts_session_churn_under_stable_locus_and_process(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            registry = server.WorkspaceRegistry(root, "{}")
            backend, state = manual_backend(root)

            with patch.object(server, "ROOT", root), patch.object(server, "_WORKSPACE_REGISTRY", registry), patch.object(server, "_WORKSPACE_BACKENDS", {str(root): backend}), patch.object(server, "HERDR", backend):
                listed = await server._discover_project_candidates()
                candidate_id = listed["candidates"][0]["candidate_id"]

                # Set initial session and read to bind it
                for a in [state["agent"]]:
                    if a is state["agent"]:
                        a["agent_session"] = {"kind": "id", "value": "session-A"}
                read_res1 = await server._read_agent_candidate(candidate_id=candidate_id, limit=10)
                self.assertTrue(read_res1["ok"])

                # Session changed from A to B (session churn under stable locus/process is accepted)
                for a in [state["agent"]]:
                    if a is state["agent"]:
                        a["agent_session"] = {"kind": "id", "value": "changed-session-B"}

                read_res2 = await server._read_agent_candidate(candidate_id=candidate_id, limit=10)
                self.assertTrue(read_res2["ok"])
                self.assertIn("read", read_res2)
                self.assertIn("text", read_res2["read"])

    async def test_promotion_fails_closed_if_pane_or_terminal_drifted(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            registry = server.WorkspaceRegistry(root, "{}")
            backend, state = manual_backend(root)

            with patch.object(server, "ROOT", root), patch.object(server, "_WORKSPACE_REGISTRY", registry), patch.object(server, "_WORKSPACE_BACKENDS", {str(root): backend}), patch.object(server, "HERDR", backend):
                listed = await server._discover_project_candidates()
                candidate_id = listed["candidates"][0]["candidate_id"]

                # Session appears BUT terminal ID changed -> MUST FAIL CLOSED
                for a in [state["agent"]]:
                    if a is state["agent"]:
                        a["agent_session"] = {"kind": "id", "value": "01a01912-2b88-7d92-accc-63105dcfe5fc"}
                        a["terminal_id"] = "term-drifted-999"

                read_res = await server._read_agent_candidate(candidate_id=candidate_id, limit=10)
                self.assertFalse(read_res["ok"])
                self.assertEqual(read_res["error_type"], "ManualCandidateObservationUnavailable")
                self.assertEqual(read_res["reason"], "observation_unavailable")


    async def test_observed_non_owned_watcher_promotion(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            registry = server.WorkspaceRegistry(root, "{}")
            backend, state = manual_backend(root)
            state["agent"]["agent_session"] = None

            with patch.object(server, "ROOT", root), patch.object(server, "_WORKSPACE_REGISTRY", registry), patch.object(server, "_WORKSPACE_BACKENDS", {str(root): backend}), patch.object(server, "HERDR", backend):
                list1 = await server._discover_project_candidates()
                cid1 = list1["candidates"][0]["candidate_id"]

                # Prompt starts when agent has NO session
                prompt_res = await dispatch_candidate(candidate_id=cid1, task="run background")
                self.assertTrue(prompt_res["ok"])
                hid = prompt_res["handoff_id"]

                # During watcher observation, agent gains native session and settles
                state["agent"]["agent_session"] = {"kind": "id", "value": "watcher-promoted-s42"}
                state["agent"]["agent_status"] = "idle"

                observed_handoff = server._HANDOFF_REGISTRY[hid]
                watcher = observed_handoff["watcher_task"]
                await watcher

                self.assertNotIn(hid, server._HANDOFF_REGISTRY)
                handoff = observed_handoff
                self.assertEqual(handoff["state"], "done")
                self.assertEqual(handoff["reason"], "state_transition_proven")
                self.assertEqual(
                    handoff["candidate"]["identity"]["agent_session"],
                    {"kind": "id", "value": "watcher-promoted-s42"},
                )


    async def test_unmanaged_agent_ref_refreshes_if_foreground_process_changed(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            registry = server.WorkspaceRegistry(root, "{}")
            backend, state = manual_backend(root)
            state["agent"]["agent_session"] = None

            with patch.object(server, "ROOT", root), patch.object(server, "_WORKSPACE_REGISTRY", registry), patch.object(server, "_WORKSPACE_BACKENDS", {str(root): backend}), patch.object(server, "HERDR", backend):
                cands = (await server._discover_project_candidates())["candidates"]
                cid = cands[0]["candidate_id"]

                # Gains session BUT foreground process PID changed (process replacement)
                state["agent"]["agent_session"] = {"kind": "id", "value": "new-session"}
                state["agent"]["_pid"] = 99999

                read_res = await server._read_agent_candidate(candidate_id=cid, limit=10)
                self.assertTrue(read_res["ok"], read_res)
                self.assertEqual(read_res["candidate"]["candidate_id"], cid)

    async def test_unmanaged_promotion_fails_closed_if_process_evidence_missing(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            registry = server.WorkspaceRegistry(root, "{}")
            backend, state = manual_backend(root)
            state["agent"]["agent_session"] = None

            with patch.object(server, "ROOT", root), patch.object(server, "_WORKSPACE_REGISTRY", registry), patch.object(server, "_WORKSPACE_BACKENDS", {str(root): backend}), patch.object(server, "HERDR", backend):
                cands = (await server._discover_project_candidates())["candidates"]
                cid = cands[0]["candidate_id"]

                # Gains session BUT process info becomes unavailable
                state["agent"]["agent_session"] = {"kind": "id", "value": "new-session"}
                state["process_info"] = {
                    "pane_id": "w-manual:p1",
                    "foreground_process_group_id": None,
                    "foreground_processes": [],
                }

                read_res = await server._read_agent_candidate(candidate_id=cid, limit=10)
                self.assertFalse(read_res["ok"])
                self.assertEqual(read_res["error_type"], "ManualCandidateObservationUnavailable")
                self.assertEqual(read_res["reason"], "observation_unavailable")

    async def test_unmanaged_accepts_session_churn_under_stable_locus_and_process(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            registry = server.WorkspaceRegistry(root, "{}")
            backend, state = manual_backend(root)
            state["agent"]["agent_session"] = {"kind": "id", "value": "session-A"}

            with patch.object(server, "ROOT", root), patch.object(server, "_WORKSPACE_REGISTRY", registry), patch.object(server, "_WORKSPACE_BACKENDS", {str(root): backend}), patch.object(server, "HERDR", backend):
                cands = (await server._discover_project_candidates())["candidates"]
                cid = cands[0]["candidate_id"]

                # Session changed from session-A to session-B under stable execution locus/process
                state["agent"]["agent_session"] = {"kind": "id", "value": "session-B"}

                read_res = await server._read_agent_candidate(candidate_id=cid, limit=10)
                self.assertTrue(read_res["ok"])
                self.assertIn("read", read_res)
                self.assertIn("text", read_res["read"])

    async def test_unmanaged_accepts_session_disappearing_under_stable_locus_and_process(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            registry = server.WorkspaceRegistry(root, "{}")
            backend, state = manual_backend(root)
            state["agent"]["agent_session"] = {"kind": "id", "value": "session-A"}

            with patch.object(server, "ROOT", root), patch.object(server, "_WORKSPACE_REGISTRY", registry), patch.object(server, "_WORKSPACE_BACKENDS", {str(root): backend}), patch.object(server, "HERDR", backend):
                cands = (await server._discover_project_candidates())["candidates"]
                cid = cands[0]["candidate_id"]

                # Session disappears (session->None under stable execution locus/process is accepted)
                state["agent"]["agent_session"] = None

                read_res = await server._read_agent_candidate(candidate_id=cid, limit=10)
                self.assertTrue(read_res["ok"])
                self.assertIn("read", read_res)
                self.assertIn("text", read_res["read"])

    async def test_backend_read_accepts_session_churn_without_promotion_opt_in(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            registry = server.WorkspaceRegistry(root, "{}")
            backend, state = manual_backend(root)
            state["agent"]["agent_session"] = None

            with patch.object(server, "ROOT", root), patch.object(server, "_WORKSPACE_REGISTRY", registry), patch.object(server, "_WORKSPACE_BACKENDS", {str(root): backend}), patch.object(server, "HERDR", backend):
                cands_resp = await server._discover_project_candidates()
                cid = cands_resp["candidates"][0]["candidate_id"]
                raw_candidate = server._MANUAL_AGENT_CANDIDATES[cid]["candidate"]

                # Unmanaged agent gains native session
                state["agent"]["agent_session"] = {"kind": "id", "value": "promoted-session-strict-test"}

                # Direct backend read accepts session change under stable execution locus/process
                backend_read = await backend.read_manual_agent(raw_candidate, limit=10)
                self.assertIn("text", backend_read)

                # Server _read_agent_candidate production path succeeds
                server_read = await server._read_agent_candidate(candidate_id=cid, limit=10)
                self.assertTrue(server_read["ok"])
                self.assertEqual(
                    server_read["candidate"]["agent_session"],
                    {"kind": "id", "value": "promoted-session-strict-test"},
                )

    async def test_unmanaged_promotion_fails_closed_if_pane_or_cwd_mismatches(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            registry = server.WorkspaceRegistry(root, "{}")
            backend, state = manual_backend(root)
            state["agent"]["agent_session"] = None

            with patch.object(server, "ROOT", root), patch.object(server, "_WORKSPACE_REGISTRY", registry), patch.object(server, "_WORKSPACE_BACKENDS", {str(root): backend}), patch.object(server, "HERDR", backend):
                cands = (await server._discover_project_candidates())["candidates"]
                cid = cands[0]["candidate_id"]

                # Case 1: Pane drifted -> fails closed
                state["agent"]["agent_session"] = {"kind": "id", "value": "new-session"}
                orig_pane = state["agent"]["pane_id"]
                state["agent"]["pane_id"] = "w-manual:p99"
                read_res1 = await server._read_agent_candidate(candidate_id=cid, limit=10)
                self.assertFalse(read_res1["ok"])
                self.assertEqual(read_res1["error_type"], "ManualCandidateObservationUnavailable")
                self.assertEqual(read_res1["reason"], "observation_unavailable")
                state["agent"]["pane_id"] = orig_pane

                # Case 2: CWD drifted -> fails closed
                orig_cwd = state["agent"]["cwd"]
                state["agent"]["cwd"] = str(root / "drifted_cwd")
                read_res2 = await server._read_agent_candidate(candidate_id=cid, limit=10)
                self.assertFalse(read_res2["ok"])
                self.assertEqual(read_res2["error_type"], "ManualCandidateObservationUnavailable")
                self.assertEqual(read_res2["reason"], "observation_unavailable")
                state["agent"]["cwd"] = orig_cwd

                # Case 3: Foreground CWD drifted -> fails closed
                orig_fg_cwd = state["agent"]["foreground_cwd"]
                state["agent"]["foreground_cwd"] = str(root / "drifted_fg_cwd")
                read_res3 = await server._read_agent_candidate(candidate_id=cid, limit=10)
                self.assertFalse(read_res3["ok"])
                self.assertEqual(read_res3["error_type"], "ManualCandidateObservationUnavailable")
                self.assertEqual(read_res3["reason"], "observation_unavailable")
                state["agent"]["foreground_cwd"] = orig_fg_cwd

    async def test_unmanaged_promotion_fails_closed_if_ambiguous(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            registry = server.WorkspaceRegistry(root, "{}")
            backend, state = manual_backend(root)
            state["agent"]["agent_session"] = None

            with patch.object(server, "ROOT", root), patch.object(server, "_WORKSPACE_REGISTRY", registry), patch.object(server, "_WORKSPACE_BACKENDS", {str(root): backend}), patch.object(server, "HERDR", backend):
                cands = (await server._discover_project_candidates())["candidates"]
                cid = cands[0]["candidate_id"]

                # Ambiguous: two live agents match the same exact criteria
                clone = dict(state["agent"])
                clone["agent_session"] = {"kind": "id", "value": "new-session"}
                state["created_agents"].append(clone)

                read_res = await server._read_agent_candidate(candidate_id=cid, limit=10)
                self.assertFalse(read_res["ok"])
                self.assertEqual(read_res["error_type"], "ManualCandidateRevalidationUncertain")
                self.assertEqual(read_res["reason"], "revalidation_uncertain")


    async def test_transient_empty_agent_snapshot_recovers_and_continues_observation(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            registry = server.WorkspaceRegistry(root, "{}")
            backend, state = manual_backend(root)
            snapshot_calls = 0
            orig_agent = dict(state["agent"])
            hold = asyncio.Event()

            def snapshot_handler(*args):
                nonlocal snapshot_calls
                snapshot_calls += 1
                agents = [orig_agent]
                if snapshot_calls == 3:
                    agents = []
                elif snapshot_calls >= 4:
                    orig_agent["agent_status"] = "working"
                return {
                    "snapshot": {
                        "agents": agents,
                        "panes": state.get("panes", [{"workspace_id": state["workspace_id"], "pane_id": "w-manual:p1", "cwd": str(root), "terminal_id": "term-w-manual:p1"}]),
                        "tabs": state.get("tabs", []),
                        "workspaces": [{"workspace_id": state["workspace_id"], "label": "GPT Web Bridge"}],
                    }
                }

            state["snapshot_handler"] = snapshot_handler
            orig_call = backend._call

            async def mock_call(*args, **kwargs):
                if args[:2] == ("agent", "wait"):
                    state["calls"].append(args)
                    await hold.wait()
                    return {"agent": state["agent"]}
                return await orig_call(*args, **kwargs)

            backend._call = mock_call
            with patch.object(server, "ROOT", root), patch.object(server, "_WORKSPACE_REGISTRY", registry), patch.object(server, "_WORKSPACE_BACKENDS", {str(root): backend}), patch.object(server, "HERDR", backend), self.assertNoLogs("mcp.bridge.work_terminal", level="INFO"):
                cands = (await server._discover_project_candidates())["candidates"]
                cid = cands[0]["candidate_id"]

                prompt_res = await dispatch_candidate(candidate_id=cid, task="empty snapshot test SECRET_TASK_BODY")
                self.assertTrue(prompt_res["ok"])
                hid = prompt_res["handoff_id"]
                observed_handoff = server._HANDOFF_REGISTRY[hid]
                watcher = observed_handoff["watcher_task"]
                for _ in range(30):
                    await asyncio.sleep(0)
                    if any(call[:2] == ("agent", "wait") for call in state["calls"]):
                        break
                else:
                    self.fail("watcher did not resume observation after one empty snapshot")

                self.assertFalse(watcher.done())
                self.assertEqual(observed_handoff["state"], "running")
                work = server._WORK_REGISTRY[observed_handoff["work_ref"]]
                self.assertEqual(work["state"], "running")
                self.assertEqual(snapshot_calls, 4)
                prompts = [c for c in state["calls"] if c[:2] == ("agent", "prompt")]
                send_keys = [c for c in state["calls"] if c[:2] == ("agent", "send-keys")]
                self.assertEqual(len(prompts), 1)
                self.assertEqual(send_keys, [])
                watcher.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await watcher

    async def test_transient_process_info_timeout_recovers_and_continues_observation(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            registry = server.WorkspaceRegistry(root, "{}")
            backend, state = manual_backend(root)
            state["agent"]["agent_session"] = {"kind": "id", "value": "native-sess-1"}
            process_calls = 0
            hold = asyncio.Event()

            orig_call = backend._call
            async def mock_call(subsystem, action, *args, **kwargs):
                nonlocal process_calls
                if subsystem == "agent" and action == "wait":
                    state["calls"].append(("agent", "wait", *args))
                    await hold.wait()
                    return {"agent": state["agent"]}
                if subsystem == "pane" and action == "process-info":
                    process_calls += 1
                    if process_calls == 3:
                        state["agent"]["agent_status"] = "working"
                        raise TimeoutError("process-info timed out during revalidation")
                return await orig_call(subsystem, action, *args, **kwargs)

            backend._call = mock_call
            with patch.object(server, "ROOT", root), patch.object(server, "_WORKSPACE_REGISTRY", registry), patch.object(server, "_WORKSPACE_BACKENDS", {str(root): backend}), patch.object(server, "HERDR", backend), self.assertNoLogs("mcp.bridge.work_terminal", level="INFO"):
                cands = (await server._discover_project_candidates())["candidates"]
                cid = cands[0]["candidate_id"]

                prompt_res = await dispatch_candidate(candidate_id=cid, task="process timeout test SECRET_TASK_BODY")
                self.assertTrue(prompt_res["ok"])
                hid = prompt_res["handoff_id"]
                observed_handoff = server._HANDOFF_REGISTRY[hid]
                watcher = observed_handoff["watcher_task"]
                for _ in range(30):
                    await asyncio.sleep(0)
                    if any(call[:2] == ("agent", "wait") for call in state["calls"]):
                        break
                else:
                    self.fail("watcher did not resume observation after one process-info timeout")

                self.assertFalse(watcher.done())
                self.assertEqual(observed_handoff["state"], "running")
                work = server._WORK_REGISTRY[observed_handoff["work_ref"]]
                self.assertEqual(work["state"], "running")
                self.assertEqual(process_calls, 4)
                prompts = [c for c in state["calls"] if c[:2] == ("agent", "prompt")]
                send_keys = [c for c in state["calls"] if c[:2] == ("agent", "send-keys")]
                self.assertEqual(len(prompts), 1)
                self.assertEqual(send_keys, [])
                watcher.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await watcher

    async def test_persistent_transient_observation_exhausts_retry_then_needs_attention(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            registry = server.WorkspaceRegistry(root, "{}")
            backend, state = manual_backend(root)
            snapshot_calls = 0
            orig_agent = dict(state["agent"])
            sleeps: list[float] = []

            def snapshot_handler(*_args):
                nonlocal snapshot_calls
                snapshot_calls += 1
                agents = [orig_agent] if snapshot_calls <= 2 else []
                return {
                    "snapshot": {
                        "agents": agents,
                        "panes": state.get("panes", [{"workspace_id": state["workspace_id"], "pane_id": "w-manual:p1", "cwd": str(root), "terminal_id": "term-w-manual:p1"}]),
                        "tabs": state.get("tabs", []),
                        "workspaces": [{"workspace_id": state["workspace_id"], "label": "GPT Web Bridge"}],
                    }
                }

            original_sleep = asyncio.sleep

            async def tracking_sleep(amount):
                sleeps.append(float(amount))
                await original_sleep(0)

            state["snapshot_handler"] = snapshot_handler
            state["text"] = "TERMINAL_BODY_do_not_log"
            with patch.object(server, "ROOT", root), patch.object(server, "_WORKSPACE_REGISTRY", registry), patch.object(server, "_WORKSPACE_BACKENDS", {str(root): backend}), patch.object(server, "HERDR", backend), patch.object(herdr_backend, "TRANSIENT_OBSERVATION_RETRY_INTERVAL_SECONDS", 100.0), patch.object(herdr_backend.asyncio, "sleep", tracking_sleep), self.assertLogs("mcp.bridge.work_terminal", level="INFO") as captured:
                cands = (await server._discover_project_candidates())["candidates"]
                cid = cands[0]["candidate_id"]
                prompt_res = await dispatch_candidate(
                    candidate_id=cid, task="exhaustion SECRET_TASK_BODY")
                self.assertTrue(prompt_res["ok"])
                hid = prompt_res["handoff_id"]
                observed = server._HANDOFF_REGISTRY[hid]
                await observed["watcher_task"]

            self.assertEqual(observed["state"], "needs_attention")
            self.assertEqual(observed["reason"], "observation_unavailable")
            self.assertEqual(snapshot_calls, 5)
            self.assertEqual(sleeps, [2.5, 2.5])
            prompts = [c for c in state["calls"] if c[:2] == ("agent", "prompt")]
            send_keys = [c for c in state["calls"] if c[:2] == ("agent", "send-keys")]
            self.assertEqual(len(prompts), 1)
            self.assertEqual(send_keys, [])
            self.assertEqual(len(captured.records), 1)
            payload = json.loads(captured.records[0].getMessage())
            self.assertEqual(set(payload), {
                "elapsed_ms", "event", "handoff_id", "herdr_status", "reason",
                "state", "watcher_error_code", "work_ref",
            })
            self.assertEqual(payload["event"], "bridge.work_terminal_latch")
            self.assertEqual(payload["work_ref"], observed["work_ref"])
            self.assertEqual(payload["handoff_id"], hid)
            self.assertEqual(payload["state"], "needs_attention")
            self.assertEqual(payload["reason"], "observation_unavailable")
            self.assertEqual(payload["herdr_status"], "unknown")
            self.assertEqual(payload["watcher_error_code"], "manual_candidate_observation_unavailable")
            self.assertIsInstance(payload["elapsed_ms"], int)
            self.assertGreaterEqual(payload["elapsed_ms"], 0)
            self.assertLessEqual(payload["elapsed_ms"], 86_400_000)
            blob = captured.records[0].getMessage()
            self.assertNotIn("SECRET_TASK_BODY", blob)
            self.assertNotIn("TERMINAL_BODY_do_not_log", blob)
            self.assertNotIn("no agent at expected locus", blob)
            work = server._WORK_REGISTRY[observed["work_ref"]]
            self.assertEqual(work["state"], "needs_attention")
            self.assertEqual(work["reason"], "observation_unavailable")

    async def test_transient_then_continuity_loss_is_not_masked_by_retry(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            registry = server.WorkspaceRegistry(root, "{}")
            backend, state = manual_backend(root)
            snapshot_calls = 0
            original = dict(state["agent"])

            def snapshot_handler(*_args):
                nonlocal snapshot_calls
                snapshot_calls += 1
                if snapshot_calls <= 2:
                    live = original
                elif snapshot_calls == 3:
                    live = None
                else:
                    live = agy_agent(root, pid=99999)
                    state["agent"] = live
                agents = [] if live is None else [live]
                return {
                    "snapshot": {
                        "agents": agents,
                        "panes": state.get("panes", [{"workspace_id": state["workspace_id"], "pane_id": "w-manual:p1", "cwd": str(root), "terminal_id": "term-w-manual:p1"}]),
                        "tabs": state.get("tabs", []),
                        "workspaces": [{"workspace_id": state["workspace_id"], "label": "GPT Web Bridge"}],
                    }
                }

            state["snapshot_handler"] = snapshot_handler
            with patch.object(server, "ROOT", root), patch.object(server, "_WORKSPACE_REGISTRY", registry), patch.object(server, "_WORKSPACE_BACKENDS", {str(root): backend}), patch.object(server, "HERDR", backend), self.assertLogs("mcp.bridge.work_terminal", level="INFO") as captured:
                cands = (await server._discover_project_candidates())["candidates"]
                cid = cands[0]["candidate_id"]
                prompt_res = await dispatch_candidate(
                    candidate_id=cid, task="definitive after transient SECRET_TASK_BODY")
                self.assertTrue(prompt_res["ok"])
                hid = prompt_res["handoff_id"]
                observed = server._HANDOFF_REGISTRY[hid]
                await observed["watcher_task"]

            self.assertEqual(snapshot_calls, 4)
            self.assertEqual(observed["state"], "failed")
            self.assertEqual(observed["reason"], "candidate_continuity_lost")
            prompts = [c for c in state["calls"] if c[:2] == ("agent", "prompt")]
            send_keys = [c for c in state["calls"] if c[:2] == ("agent", "send-keys")]
            self.assertEqual(len(prompts), 1)
            self.assertEqual(send_keys, [])
            self.assertEqual(len(captured.records), 1)
            payload = json.loads(captured.records[0].getMessage())
            self.assertEqual(payload["state"], "continuity_lost")
            self.assertEqual(payload["reason"], "candidate_continuity_lost")
            self.assertEqual(payload["herdr_status"], "continuity_lost")
            self.assertEqual(payload["watcher_error_code"], "manual_candidate_continuity_lost")
            self.assertNotEqual(payload["reason"], "observation_unavailable")
            self.assertNotIn("SECRET_TASK_BODY", captured.records[0].getMessage())
            work = server._WORK_REGISTRY[observed["work_ref"]]
            self.assertEqual(work["state"], "continuity_lost")

    async def test_ambiguous_matches_latches_needs_attention_revalidation_uncertain(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            registry = server.WorkspaceRegistry(root, "{}")
            backend, state = manual_backend(root)
            snapshot_calls = 0
            orig_agent = dict(state["agent"])

            def snapshot_handler(*args):
                nonlocal snapshot_calls
                snapshot_calls += 1
                if snapshot_calls <= 2:
                    return {
                        "snapshot": {
                            "agents": [orig_agent],
                            "panes": state.get("panes", [{"workspace_id": state["workspace_id"], "pane_id": "w-manual:p1", "cwd": str(root), "terminal_id": "term-w-manual:p1"}]),
                            "tabs": state.get("tabs", []),
                            "workspaces": [{"workspace_id": state["workspace_id"], "label": "GPT Web Bridge"}],
                        }
                    }
                # Watcher revalidation: ambiguous multiple matches at exact locus
                clone = dict(orig_agent)
                return {
                    "snapshot": {
                        "agents": [orig_agent, clone],
                        "panes": state.get("panes", [{"workspace_id": state["workspace_id"], "pane_id": "w-manual:p1", "cwd": str(root), "terminal_id": "term-w-manual:p1"}]),
                        "tabs": state.get("tabs", []),
                        "workspaces": [{"workspace_id": state["workspace_id"], "label": "GPT Web Bridge"}],
                    }
                }

            state["snapshot_handler"] = snapshot_handler
            with patch.object(server, "ROOT", root), patch.object(server, "_WORKSPACE_REGISTRY", registry), patch.object(server, "_WORKSPACE_BACKENDS", {str(root): backend}), patch.object(server, "HERDR", backend):
                cands = (await server._discover_project_candidates())["candidates"]
                cid = cands[0]["candidate_id"]

                prompt_res = await dispatch_candidate(candidate_id=cid, task="ambiguous test")
                self.assertTrue(prompt_res["ok"])
                hid = prompt_res["handoff_id"]
                observed_handoff = server._HANDOFF_REGISTRY[hid]
                watcher = observed_handoff["watcher_task"]
                await watcher

                self.assertNotIn(hid, server._HANDOFF_REGISTRY)
                entry = observed_handoff
                self.assertEqual(entry["state"], "needs_attention")
                self.assertEqual(entry["reason"], "revalidation_uncertain")
                stored = server._MANUAL_AGENT_CANDIDATES[cid]["candidate"]
                prompts = [c for c in state["calls"] if c[:2] == ("agent", "prompt")]
                self.assertEqual(len(prompts), 1)

    async def test_session_churn_alone_is_accepted_under_stable_execution_locus_and_process(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            registry = server.WorkspaceRegistry(root, "{}")
            backend, state = manual_backend(root)
            state["agent"]["agent_session"] = {"kind": "id", "value": "native-sess-1"}
            snapshot_calls = 0

            def snapshot_handler(*args):
                nonlocal snapshot_calls
                snapshot_calls += 1
                if snapshot_calls <= 2:
                    return {
                        "snapshot": {
                            "agents": [state["agent"]],
                            "panes": state.get("panes", [{"workspace_id": state["workspace_id"], "pane_id": "w-manual:p1", "cwd": str(root), "terminal_id": "term-w-manual:p1"}]),
                            "tabs": state.get("tabs", []),
                            "workspaces": [{"workspace_id": state["workspace_id"], "label": "GPT Web Bridge"}],
                        }
                    }
                # Watcher revalidation: session changed to native-sess-2 under stable locus/process
                conflicting = dict(state["agent"])
                conflicting["agent_session"] = {"kind": "id", "value": "native-sess-2"}
                return {
                    "snapshot": {
                        "agents": [conflicting],
                        "panes": state.get("panes", [{"workspace_id": state["workspace_id"], "pane_id": "w-manual:p1", "cwd": str(root), "terminal_id": "term-w-manual:p1"}]),
                        "tabs": state.get("tabs", []),
                        "workspaces": [{"workspace_id": state["workspace_id"], "label": "GPT Web Bridge"}],
                    }
                }

            state["snapshot_handler"] = snapshot_handler
            with patch.object(server, "ROOT", root), patch.object(server, "_WORKSPACE_REGISTRY", registry), patch.object(server, "_WORKSPACE_BACKENDS", {str(root): backend}), patch.object(server, "HERDR", backend):
                cands = (await server._discover_project_candidates())["candidates"]
                cid = cands[0]["candidate_id"]

                prompt_res = await dispatch_candidate(candidate_id=cid, task="conflicting session test")
                self.assertTrue(prompt_res["ok"])
                hid = prompt_res["handoff_id"]
                observed_handoff = server._HANDOFF_REGISTRY[hid]
                watcher = observed_handoff["watcher_task"]
                await watcher

                self.assertNotIn(hid, server._HANDOFF_REGISTRY)
                entry = observed_handoff
                self.assertEqual(entry["state"], "done")
                self.assertEqual(entry["reason"], "state_transition_proven")
                self.assertEqual(entry["herdr_status"], "idle")

    async def test_available_changed_process_fingerprint_remains_continuity_lost(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            registry = server.WorkspaceRegistry(root, "{}")
            backend, state = manual_backend(root)
            snapshot_calls = 0
            orig_agent = dict(state["agent"])

            def snapshot_handler(*args):
                nonlocal snapshot_calls
                snapshot_calls += 1
                if snapshot_calls <= 2:
                    return {
                        "snapshot": {
                            "agents": [orig_agent],
                            "panes": state.get("panes", [{"workspace_id": state["workspace_id"], "pane_id": "w-manual:p1", "cwd": str(root), "terminal_id": "term-w-manual:p1"}]),
                            "tabs": state.get("tabs", []),
                            "workspaces": [{"workspace_id": state["workspace_id"], "label": "GPT Web Bridge"}],
                        }
                    }
                # Watcher revalidation: replacement agent with PID 99999
                replacement = agy_agent(root, pid=99999)
                state["agent"] = replacement
                return {
                    "snapshot": {
                        "agents": [replacement],
                        "panes": state.get("panes", [{"workspace_id": state["workspace_id"], "pane_id": "w-manual:p1", "cwd": str(root), "terminal_id": "term-w-manual:p1"}]),
                        "tabs": state.get("tabs", []),
                        "workspaces": [{"workspace_id": state["workspace_id"], "label": "GPT Web Bridge"}],
                    }
                }

            state["snapshot_handler"] = snapshot_handler
            with patch.object(server, "ROOT", root), patch.object(server, "_WORKSPACE_REGISTRY", registry), patch.object(server, "_WORKSPACE_BACKENDS", {str(root): backend}), patch.object(server, "HERDR", backend):
                cands = (await server._discover_project_candidates())["candidates"]
                cid = cands[0]["candidate_id"]

                prompt_res = await dispatch_candidate(candidate_id=cid, task="changed fingerprint test")
                self.assertTrue(prompt_res["ok"])
                hid = prompt_res["handoff_id"]
                observed_handoff = server._HANDOFF_REGISTRY[hid]
                watcher = observed_handoff["watcher_task"]
                await watcher

                self.assertNotIn(hid, server._HANDOFF_REGISTRY)
                entry = observed_handoff
                self.assertEqual(entry["state"], "failed")
                self.assertEqual(entry["reason"], "candidate_continuity_lost")
                self.assertEqual(entry["herdr_status"], "continuity_lost")


class TestIsolationSentinelRegressionTests(unittest.IsolatedAsyncioTestCase):
    async def test_sentinel_blocks_unmocked_live_herdr_execution(self):
        """Prove that unmocked HerdrBackend instances cannot execute live Herdr commands."""
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            raw_backend = herdr_backend.HerdrBackend(root)
            with self.assertRaises(AssertionError) as cm:
                await raw_backend._call("api", "snapshot")
            self.assertIn("TEST ISOLATION VIOLATION", str(cm.exception))


class VisibleAgentObserveReadErrorClassificationTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        server._MANUAL_AGENT_CANDIDATES.clear()
        server._HANDOFF_REGISTRY.clear()
        for name in ('_WORK_REGISTRY', '_RESULT_INBOX'):
            patcher = patch.object(server, name, {})
            patcher.start()
            self.addCleanup(patcher.stop)

    def _project(self, root: Path, pref: str = "test-proj"):
        subprocess.run(["git", "init", "--quiet", str(root)], check=True)
        registry = server.WorkspaceRegistry(root, json.dumps({pref: str(root)}))
        backend, state = manual_backend(root)
        return registry, backend, state

    async def test_visible_observe_zero_match_returns_observation_unavailable(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            pref = "test-proj"
            registry, backend, state = self._project(root, pref)

            with patch.object(server, "ROOT", root), patch.object(server, "_WORKSPACE_REGISTRY", registry), patch.object(server, "_WORKSPACE_BACKENDS", {str(root): backend}), patch.object(server, "HERDR", backend):
                cands = (await server._discover_project_candidates(workspace_ref=pref))["candidates"]
                cid = cands[0]["candidate_id"]
                orig_cand = dict(server._MANUAL_AGENT_CANDIDATES[cid]["candidate"])

                # Snapshot reports no agents matching expected locus (empty snapshot)
                state["agent"] = None
                state["created_agents"] = []

                # Test through visible agent_observe
                res = await server.agent_terminal_read(project_ref=pref, agent_ref=cid)
                self.assertFalse(res["ok"])
                self.assertNotIn("candidate_id", res)
                self.assertEqual(res["agent_ref"], cid)
                self.assertEqual(res["project_ref"], pref)
                self.assertEqual(res["error_type"], "AgentObservationUnavailable")
                self.assertEqual(res["reason"], "observation_unavailable")
                self.assertIn("error", res)

                # Test through compatibility _read_agent_candidate
                read_res = await server._read_agent_candidate(candidate_id=cid)
                self.assertFalse(read_res["ok"])
                self.assertEqual(read_res["candidate_id"], cid)
                self.assertEqual(read_res["error_type"], "ManualCandidateObservationUnavailable")
                self.assertEqual(read_res["reason"], "observation_unavailable")

                # Assert refused observation causes no retry, no native prompt, no fuzzy rebind, and no terminal pane read after refusal
                self.assertEqual(server._MANUAL_AGENT_CANDIDATES[cid]["candidate"]["candidate_key"], orig_cand["candidate_key"])
                self.assertEqual([call for call in state["calls"] if call[:2] == ("agent", "prompt")], [])
                self.assertEqual([call for call in state["calls"] if call[:2] == ("pane", "read")], [])

    async def test_visible_observe_process_unavailable_returns_observation_unavailable(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            pref = "test-proj"
            registry, backend, state = self._project(root, pref)

            with patch.object(server, "ROOT", root), patch.object(server, "_WORKSPACE_REGISTRY", registry), patch.object(server, "_WORKSPACE_BACKENDS", {str(root): backend}), patch.object(server, "HERDR", backend):
                cands = (await server._discover_project_candidates(workspace_ref=pref))["candidates"]
                cid = cands[0]["candidate_id"]
                orig_cand = dict(server._MANUAL_AGENT_CANDIDATES[cid]["candidate"])

                # Foreground process evidence becomes unavailable (e.g. process-info empty / unavailable)
                state["process_info"] = {
                    "pane_id": "w-manual:p1",
                    "foreground_process_group_id": None,
                    "foreground_processes": [],
                }
                # Also ensure candidate key differs so process revalidation is checked
                state["agent"]["agent_session"] = {"kind": "id", "value": "new-native-session"}

                res = await server.agent_terminal_read(project_ref=pref, agent_ref=cid)
                self.assertFalse(res["ok"])
                self.assertNotIn("candidate_id", res)
                self.assertEqual(res["agent_ref"], cid)
                self.assertEqual(res["project_ref"], pref)
                self.assertEqual(res["error_type"], "AgentObservationUnavailable")
                self.assertEqual(res["reason"], "observation_unavailable")

                # Assert refused observation causes no retry, no native prompt, no fuzzy rebind, and no terminal pane read
                self.assertEqual(server._MANUAL_AGENT_CANDIDATES[cid]["candidate"]["candidate_key"], orig_cand["candidate_key"])
                self.assertEqual([call for call in state["calls"] if call[:2] == ("agent", "prompt")], [])
                self.assertEqual([call for call in state["calls"] if call[:2] == ("pane", "read")], [])

    async def test_visible_observe_ambiguity_returns_revalidation_uncertain(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            pref = "test-proj"
            registry, backend, state = self._project(root, pref)

            with patch.object(server, "ROOT", root), patch.object(server, "_WORKSPACE_REGISTRY", registry), patch.object(server, "_WORKSPACE_BACKENDS", {str(root): backend}), patch.object(server, "HERDR", backend):
                cands = (await server._discover_project_candidates(workspace_ref=pref))["candidates"]
                cid = cands[0]["candidate_id"]
                orig_cand = dict(server._MANUAL_AGENT_CANDIDATES[cid]["candidate"])

                # Ambiguous: two live agents match the same locus
                clone = dict(state["agent"])
                state["created_agents"].append(clone)

                res = await server.agent_terminal_read(project_ref=pref, agent_ref=cid)
                self.assertFalse(res["ok"])
                self.assertNotIn("candidate_id", res)
                self.assertEqual(res["agent_ref"], cid)
                self.assertEqual(res["project_ref"], pref)
                self.assertEqual(res["error_type"], "AgentObservationUncertain")
                self.assertEqual(res["reason"], "observation_uncertain")

                # Assert refused observation causes no retry, no native prompt, no fuzzy rebind, and no terminal pane read
                self.assertEqual(server._MANUAL_AGENT_CANDIDATES[cid]["candidate"]["candidate_key"], orig_cand["candidate_key"])
                self.assertEqual([call for call in state["calls"] if call[:2] == ("agent", "prompt")], [])
                self.assertEqual([call for call in state["calls"] if call[:2] == ("pane", "read")], [])

    async def test_visible_observe_accepts_session_churn_under_stable_execution_locus_and_process(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            pref = "test-proj"
            registry, backend, state = self._project(root, pref)
            state["agent"]["agent_session"] = {"kind": "id", "value": "session-A"}

            with patch.object(server, "ROOT", root), patch.object(server, "_WORKSPACE_REGISTRY", registry), patch.object(server, "_WORKSPACE_BACKENDS", {str(root): backend}), patch.object(server, "HERDR", backend):
                cands = (await server._discover_project_candidates(workspace_ref=pref))["candidates"]
                cid = cands[0]["candidate_id"]

                # Session churn: changed from session-A to session-B under stable locus/process
                state["agent"]["agent_session"] = {"kind": "id", "value": "session-B"}

                res = await server.agent_terminal_read(project_ref=pref, agent_ref=cid)
                self.assertTrue(res["ok"])
                self.assertNotIn("candidate_id", res)
                self.assertNotIn("candidate", res)
                self.assertEqual(res["agent_ref"], cid)
                self.assertEqual(res["project_ref"], pref)
                self.assertEqual(res["status"], "idle")
                self.assertIn("read", res)

                # Underlying compatibility _read_agent_candidate retains full candidate structure
                read_res = await server._read_agent_candidate(candidate_id=cid)
                self.assertTrue(read_res["ok"])
                self.assertEqual(read_res["candidate"]["candidate_id"], cid)
                self.assertEqual(
                    read_res["candidate"]["agent_session"],
                    {"kind": "id", "value": "session-B"},
                )

    async def test_visible_observe_process_replacement_refreshes_same_agent_ref(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            pref = "test-proj"
            registry, backend, state = self._project(root, pref)

            with patch.object(server, "ROOT", root), patch.object(server, "_WORKSPACE_REGISTRY", registry), patch.object(server, "_WORKSPACE_BACKENDS", {str(root): backend}), patch.object(server, "HERDR", backend):
                cands = (await server._discover_project_candidates(workspace_ref=pref))["candidates"]
                cid = cands[0]["candidate_id"]
                orig_cand = dict(server._MANUAL_AGENT_CANDIDATES[cid]["candidate"])

                # Real execution contradiction: foreground process replacement (PID changed)
                state["agent"] = agy_agent(root, pid=99999)

                res = await server.agent_terminal_read(project_ref=pref, agent_ref=cid)
                self.assertTrue(res["ok"], res)
                self.assertNotIn("candidate_id", res)
                self.assertEqual(res["agent_ref"], cid)
                self.assertEqual(res["project_ref"], pref)
                self.assertEqual(res["status"], "idle")
                self.assertIn("read", res)

                # Observation refreshes only this exact resource and never prompts.
                self.assertNotEqual(server._MANUAL_AGENT_CANDIDATES[cid]["candidate"]["candidate_key"], orig_cand["candidate_key"])
                self.assertEqual([call for call in state["calls"] if call[:2] == ("agent", "prompt")], [])
                self.assertEqual(len([call for call in state["calls"] if call[:2] == ("pane", "read")]), 1)

    async def test_visible_observe_table_coverage_for_backend_codes_and_unknown_fallback(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            pref = "test-proj"
            registry, backend, state = self._project(root, pref)

            with patch.object(server, "ROOT", root), patch.object(server, "_WORKSPACE_REGISTRY", registry), patch.object(server, "_WORKSPACE_BACKENDS", {str(root): backend}), patch.object(server, "HERDR", backend):
                cands = (await server._discover_project_candidates(workspace_ref=pref))["candidates"]
                cid = cands[0]["candidate_id"]
                orig_cand = dict(server._MANUAL_AGENT_CANDIDATES[cid]["candidate"])

                test_cases = [
                    ("manual_candidate_observation_unavailable", "AgentObservationUnavailable", "observation_unavailable"),
                    ("manual_candidate_process_unavailable", "AgentObservationUnavailable", "observation_unavailable"),
                    ("manual_candidate_read_unavailable", "AgentObservationUnavailable", "observation_unavailable"),
                    ("manual_candidate_identity_ambiguous", "AgentObservationUncertain", "observation_uncertain"),
                    ("manual_candidate_snapshot_malformed", "AgentObservationUncertain", "observation_uncertain"),
                    ("manual_candidate_identity_unavailable", "AgentObservationUncertain", "observation_uncertain"),
                    ("manual_candidate_identity_lost", "AgentContinuityLost", "continuity_lost"),
                    ("manual_candidate_continuity_lost", "AgentContinuityLost", "continuity_lost"),
                    ("unknown_backend_code", "AgentObservationUncertain", "observation_uncertain"),
                    (None, "AgentObservationUncertain", "observation_uncertain"),
                ]

                for backend_code, expected_type, expected_reason in test_cases:
                    with self.subTest(backend_code=backend_code):
                        calls_before = len(state["calls"])
                        err = herdr_backend.HerdrError(f"simulated failure for {backend_code}", code=backend_code)
                        with patch.object(backend, "read_manual_agent", side_effect=err):
                            res = await server.agent_terminal_read(project_ref=pref, agent_ref=cid)
                            self.assertFalse(res["ok"])
                            self.assertNotIn("candidate_id", res)
                            self.assertEqual(res["agent_ref"], cid)
                            self.assertEqual(res["project_ref"], pref)
                            self.assertEqual(res["error_type"], expected_type)
                            self.assertFalse(res["error_type"].startswith("ManualCandidate"))
                            self.assertEqual(res["reason"], expected_reason)
                            self.assertIsInstance(res["error"], str)
                            self.assertTrue(len(res["error"]) > 0)
                            serialized = json.dumps(res).lower()
                            for forbidden in (
                                "manualcandidate",
                                "manual_agent",
                                "manual agent",
                                "candidate",
                                "process",
                                "pane",
                                "session",
                                "managed",
                                "lifecycle",
                            ):
                                self.assertNotIn(forbidden, serialized)

                            # Assert no extra calls / retry, no prompt, no fuzzy rebind, no terminal pane read
                            self.assertEqual(len(state["calls"]), calls_before)
                            self.assertEqual(server._MANUAL_AGENT_CANDIDATES[cid]["candidate"]["candidate_key"], orig_cand["candidate_key"])
                            self.assertEqual([call for call in state["calls"] if call[:2] == ("agent", "prompt")], [])
                            self.assertEqual([call for call in state["calls"] if call[:2] == ("pane", "read")], [])


class AgyComposerRecoveryTests(unittest.IsolatedAsyncioTestCase):
    """AGY cold-path empty-composer recovery (proven silent-loss class).

    The proven incident: a native prompt acked while AGY created no turn and
    the composer stayed empty. Recovery must fire ONLY after the existing
    activation budget exhausts in exactly that absorbing shape, and only when
    TWO fresh bounded detection reads independently prove the validated
    settled empty-composer shape while status stays idle/done and the exact
    pre-dispatch seq never moves. Then the exact task is re-prompted through
    the same native primitive ONCE; any uncertainty keeps the existing
    needs_attention path. Never Enter, never a third prompt.
    """

    TASK = "recovery task text"

    def recovery_seam(self, **overrides):
        seam = {"task": self.TASK, "exclusivity_clear": lambda: True}
        seam.update(overrides)
        return seam

    def absorbing(self, root):
        """Fixture frozen in the absorbing shape: idle, exact seq never moves."""
        backend, state = manual_backend(root)
        state["auto_advance_turn"] = False

        def prompt_handler(*args):
            # Valid typed ack against the complete stable resource identity;
            # the absorbing fixture does not advance seq by default.
            return {"type": "agent_prompted", "agent": dict(state["agent"])}
        state["prompt_handler"] = prompt_handler
        clock = [0.0]

        def wait_handler(*args, **kwargs):
            if "--timeout" not in args:
                # Settled barrier: reached only after a self-activation veto.
                state["agent"]["agent_status"] = "done"
                state["agent"]["state_change_seq"] += 1
                return {"agent": dict(state["agent"])}
            clock[0] += int(args[args.index("--timeout") + 1]) / 1000
            raise herdr_backend.HerdrError(
                "timed out waiting for agent status", code="timeout")
        state["wait_handler"] = wait_handler
        return backend, state, clock

    async def candidate(self, backend):
        return (await backend.manual_agent_candidates())["candidates"][0]

    async def watch(self, backend, clock, recovery, pre_seq=1):
        candidate = await self.candidate(backend)
        with patch.object(herdr_backend, "time", SimpleNamespace(
                monotonic=lambda: clock[0], time=lambda: 0)), \
                patch.object(herdr_backend,
                             "AGY_COMPOSER_RECOVERY_READ_INTERVAL_SECONDS", 0.0):
            return await backend.watch_manual_agent_turn(
                candidate, pre_seq, 1, recovery=recovery)

    def kinds(self, state):
        return [c[:2] for c in state["calls"]]

    def reads(self, state):
        return [c for c in state["calls"] if c[:2] == ("agent", "read")]

    def prompts(self, state):
        return [c for c in state["calls"] if c[:2] == ("agent", "prompt")]

    async def test_healthy_activation_never_touches_recovery(self):
        with tempfile.TemporaryDirectory() as temp:
            backend, state = manual_backend(Path(temp))
            state["agent"]["state_change_seq"] = 2  # turn activated normally
            result = await self.watch(backend, [0.0], self.recovery_seam())
        self.assertEqual(result["state"], "done")
        self.assertNotIn("agy_recovery_reprompt", result)
        self.assertEqual(self.reads(state), [])
        self.assertEqual(self.prompts(state), [])

    async def test_absorbing_shape_reprompts_once_with_exact_task_then_settles(self):
        with tempfile.TemporaryDirectory() as temp:
            backend, state, clock = self.absorbing(Path(temp))

            def prompt_handler(*args):
                # The reprompt lands: seq advances and the turn completes.
                state["agent"]["state_change_seq"] += 1
                state["agent"]["revision"] += 1
                return {"type": "agent_prompted", "agent": dict(state["agent"])}
            state["prompt_handler"] = prompt_handler
            result = await self.watch(backend, clock, self.recovery_seam())
        self.assertEqual(result["state"], "done")
        self.assertIs(result["agy_recovery_reprompt"], True)
        prompts = self.prompts(state)
        self.assertEqual(len(prompts), 1)  # watcher issues ONLY the reprompt
        self.assertEqual(prompts[0][2], "w-manual:p1")
        self.assertEqual(prompts[0][3], self.TASK)  # exact original task bytes
        reads = self.reads(state)
        self.assertEqual(len(reads), 2)
        for call in reads:
            self.assertEqual(call, (
                "agent", "read", "w-manual:p1", "--source", "detection",
                "--lines", str(herdr_backend.AGY_COMPOSER_RECOVERY_READ_LINES),
                "--format", "text"))
        self.assertNotIn(("agent", "send-keys"), self.kinds(state))

    async def test_second_window_exhaustion_is_terminal_after_one_reprompt(self):
        with tempfile.TemporaryDirectory() as temp:
            backend, state, clock = self.absorbing(Path(temp))
            result = await self.watch(backend, clock, self.recovery_seam())
        self.assertEqual(result["state"], "needs_attention")
        self.assertEqual(result["reason"], "agy_composer_recovery_exhausted")
        self.assertIs(result["agy_recovery_reprompt"], True)
        self.assertEqual(len(self.prompts(state)), 1)    # never a third prompt
        self.assertEqual(len(self.reads(state)), 2)      # never a recovery loop
        self.assertNotIn(("agent", "send-keys"), self.kinds(state))

    async def test_reprompt_transport_failure_is_honest_attention_without_retry(self):
        with tempfile.TemporaryDirectory() as temp:
            backend, state, clock = self.absorbing(Path(temp))
            state["prompt_error"] = herdr_backend.HerdrError("transport lost")
            result = await self.watch(backend, clock, self.recovery_seam())
        self.assertEqual(result["state"], "needs_attention")
        self.assertEqual(result["reason"],
                         "agy_composer_recovery_reprompt_uncertain")
        self.assertNotIn("agy_recovery_reprompt", result)
        self.assertEqual(len(self.prompts(state)), 1)  # one attempt, no retry
        self.assertEqual(len(self.reads(state)), 2)

    async def test_unacknowledged_reprompt_receipt_is_terminal_uncertainty(self):
        # The recovery reprompt demands the SAME full stable-resource ack
        # matching as the first prompt: malformed receipts and wrong identity
        # are delivery uncertainty (mutation may have occurred), never a
        # acknowledged re-arm, never an audit marker, never a retry.
        variants = {
            "untyped-receipt": lambda agent: {"agent": dict(agent)},
            "missing-identity": lambda agent: {"type": "agent_prompted"},
            "wrong-pane": lambda agent: {
                "type": "agent_prompted",
                "agent": dict(agent, pane_id="w-manual:pX")},
            "wrong-terminal": lambda agent: {
                "type": "agent_prompted",
                "agent": dict(agent, terminal_id="term-other")},
            "wrong-workspace": lambda agent: {
                "type": "agent_prompted",
                "agent": dict(agent, workspace_id="w-other")},
            "wrong-kind": lambda agent: {
                "type": "agent_prompted",
                "agent": dict(agent, agent="pi")},
        }
        for label, receipt_for in variants.items():
            with self.subTest(variant=label), tempfile.TemporaryDirectory() as temp:
                backend, state, clock = self.absorbing(Path(temp))
                agent = state["agent"]
                state["prompt_handler"] = lambda *args: receipt_for(agent)
                result = await self.watch(backend, clock, self.recovery_seam())
                self.assertEqual(result["state"], "needs_attention")
                self.assertEqual(
                    result["reason"], "agy_composer_recovery_reprompt_uncertain")
                self.assertNotIn("agy_recovery_reprompt", result)
                # Never a third prompt and no fresh acknowledged window: the
                # watcher made exactly the one recovery attempt, and the
                # terminal latched without further level waits.
                self.assertEqual(len(self.prompts(state)), 1)
                self.assertEqual(len(self.reads(state)), 2)

    async def test_screen_shape_negatives_decline_to_existing_attention(self):
        for label, screen in AGY_SCREEN_NEGATIVE_VARIANTS.items():
            with self.subTest(variant=label), tempfile.TemporaryDirectory() as temp:
                backend, state, clock = self.absorbing(Path(temp))
                state["detection_text"] = screen
                result = await self.watch(backend, clock, self.recovery_seam())
                self.assertEqual(result["state"], "needs_attention")
                self.assertEqual(
                    result["reason"], "activation_observation_budget_exhausted")
                self.assertNotIn("agy_recovery_reprompt", result)
                self.assertEqual(self.prompts(state), [])
        for label, injected in (
                ("read-error",
                 {"read_error": herdr_backend.HerdrError("read transport lost")}),
                ("non-text-payload", {"detection_text": {"unexpected": "envelope"}}),
        ):
            with self.subTest(variant=label), tempfile.TemporaryDirectory() as temp:
                backend, state, clock = self.absorbing(Path(temp))
                state.update(injected)
                result = await self.watch(backend, clock, self.recovery_seam())
                self.assertEqual(
                    result["reason"], "activation_observation_budget_exhausted")
                self.assertEqual(self.prompts(state), [])

    async def test_mixed_reads_second_negative_declines(self):
        with tempfile.TemporaryDirectory() as temp:
            backend, state, clock = self.absorbing(Path(temp))
            seen = []

            def read_handler(*args):
                seen.append(args)
                return (AGY_SETTLED_COMPOSER_SCREEN if len(seen) == 1
                        else AGY_SCREEN_NEGATIVE_VARIANTS["queued-hint"])
            state["read_handler"] = read_handler
            result = await self.watch(backend, clock, self.recovery_seam())
        self.assertEqual(result["reason"], "activation_observation_budget_exhausted")
        self.assertEqual(self.prompts(state), [])
        self.assertEqual(len(self.reads(state)), 2)

    async def test_seq_advance_between_reads_activates_without_reprompt(self):
        with tempfile.TemporaryDirectory() as temp:
            backend, state, clock = self.absorbing(Path(temp))

            def read_handler(*args):
                # The first prompt actually landed invisibly fast: seq moved.
                state["agent"]["state_change_seq"] = 2
                return AGY_SETTLED_COMPOSER_SCREEN
            state["read_handler"] = read_handler
            result = await self.watch(backend, clock, self.recovery_seam())
        self.assertEqual(result["state"], "done")  # existing settlement flow
        self.assertNotIn("agy_recovery_reprompt", result)
        self.assertEqual(self.prompts(state), [])
        self.assertEqual(len(self.reads(state)), 1)

    async def test_working_between_reads_activates_without_reprompt(self):
        with tempfile.TemporaryDirectory() as temp:
            backend, state, clock = self.absorbing(Path(temp))

            def read_handler(*args):
                state["agent"]["agent_status"] = "working"
                return AGY_SETTLED_COMPOSER_SCREEN
            state["read_handler"] = read_handler
            result = await self.watch(backend, clock, self.recovery_seam())
        self.assertEqual(result["state"], "done")
        self.assertNotIn("agy_recovery_reprompt", result)
        self.assertEqual(self.prompts(state), [])
        self.assertEqual(len(self.reads(state)), 1)

    async def test_exclusivity_vetoes_at_either_check(self):
        with tempfile.TemporaryDirectory() as temp:
            backend, state, clock = self.absorbing(Path(temp))
            result = await self.watch(
                backend, clock, self.recovery_seam(exclusivity_clear=lambda: False))
            self.assertEqual(result["reason"],
                             "activation_observation_budget_exhausted")
            self.assertEqual(self.prompts(state), [])
            self.assertEqual(self.reads(state), [])  # veto before any screen read
        with tempfile.TemporaryDirectory() as temp:
            backend, state, clock = self.absorbing(Path(temp))
            votes = iter([True, False])
            result = await self.watch(
                backend, clock,
                self.recovery_seam(exclusivity_clear=lambda: next(votes)))
            self.assertEqual(result["reason"],
                             "activation_observation_budget_exhausted")
            self.assertEqual(self.prompts(state), [])
            self.assertEqual(len(self.reads(state)), 2)

    async def test_missing_or_malformed_recovery_seam_declines(self):
        seams = [
            None,
            {},
            {"task": self.TASK},
            {"exclusivity_clear": lambda: True},
            {"task": "   ", "exclusivity_clear": lambda: True},
            {"task": None, "exclusivity_clear": lambda: True},
            {"task": self.TASK, "exclusivity_clear": None},
        ]
        for index, seam in enumerate(seams):
            with self.subTest(seam=index), tempfile.TemporaryDirectory() as temp:
                backend, state, clock = self.absorbing(Path(temp))
                result = await self.watch(backend, clock, seam)
                self.assertEqual(result["reason"],
                                 "activation_observation_budget_exhausted")
                self.assertEqual(self.prompts(state), [])
                self.assertEqual(self.reads(state), [])

    async def test_non_agy_kinds_never_read_screens_or_reprompt(self):
        for kind in ("qodercli", "pi", "AGY", "Agy", "agy-wrapper"):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as temp:
                backend, state, clock = self.absorbing(Path(temp))
                state["agent"]["agent"] = kind
                result = await self.watch(backend, clock, self.recovery_seam())
                self.assertEqual(self.reads(state), [])
                self.assertEqual(self.prompts(state), [])
                self.assertNotIn("agy_recovery_reprompt", result)
                if kind == "qodercli":
                    # The existing one Enter-only nudge remains qoder recovery.
                    self.assertEqual(
                        result["reason"], "qoder_activation_nudge_exhausted")
                    self.assertEqual(
                        len([c for c in state["calls"]
                             if c[:2] == ("agent", "send-keys")]), 1)
                else:
                    self.assertEqual(
                        result["reason"], "activation_observation_budget_exhausted")


class AgyComposerShapeParserTests(unittest.TestCase):
    def test_validated_settled_shape_is_proven(self):
        self.assertTrue(herdr_backend._agy_empty_composer_shape(
            AGY_SETTLED_COMPOSER_SCREEN))
        # Trailing whitespace/newlines never defeat the proof.
        self.assertTrue(herdr_backend._agy_empty_composer_shape(
            AGY_SETTLED_COMPOSER_SCREEN + "\n\n   \n"))
        # Minimal shape: separator + bare composer + one footer anchor.
        self.assertTrue(herdr_backend._agy_empty_composer_shape(
            "────────────────\n  >  \n? for shortcuts"))

    def test_negatives_are_never_proven(self):
        for label, screen in AGY_SCREEN_NEGATIVE_VARIANTS.items():
            with self.subTest(variant=label):
                self.assertFalse(herdr_backend._agy_empty_composer_shape(screen))
        for invalid in (None, 42, b"...", ["text"],
                        {"text": AGY_SETTLED_COMPOSER_SCREEN}):
            with self.subTest(invalid=type(invalid).__name__):
                self.assertFalse(herdr_backend._agy_empty_composer_shape(invalid))
        # Any veto needle dominates otherwise-present positive anchors.
        for needle in herdr_backend.AGY_COMPOSER_VETO_NEEDLES:
            with self.subTest(needle=needle):
                self.assertFalse(herdr_backend._agy_empty_composer_shape(
                    AGY_SETTLED_COMPOSER_SCREEN + "\n" + needle))


class AgyRecoveryServerPlumbingTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        for name in ('_WORK_REGISTRY', '_RESULT_INBOX'):
            patcher = patch.object(server, name, {})
            patcher.start()
            self.addCleanup(patcher.stop)

    """Server-level recovery seam: audit marker, exclusivity, dispatch guard."""

    TASK = "silent loss task text"

    def absorbing(self, root):
        backend, state = manual_backend(root)
        state["auto_advance_turn"] = False

        def prompt_handler(*args):
            # Valid typed ack against the complete stable resource identity;
            # the absorbing fixture does not advance seq by default.
            return {"type": "agent_prompted", "agent": dict(state["agent"])}
        state["prompt_handler"] = prompt_handler
        clock = [0.0]

        def wait_handler(*args, **kwargs):
            if "--timeout" not in args:
                state["agent"]["agent_status"] = "done"
                state["agent"]["state_change_seq"] += 1
                return {"agent": dict(state["agent"])}
            clock[0] += int(args[args.index("--timeout") + 1]) / 1000
            raise herdr_backend.HerdrError("timed out", code="timeout")
        state["wait_handler"] = wait_handler
        return backend, state, clock

    def watcher_patches(self, clock):
        return (
            patch.object(herdr_backend, "time", SimpleNamespace(
                monotonic=lambda: clock[0], time=lambda: 0)),
            patch.object(herdr_backend,
                         "AGY_COMPOSER_RECOVERY_READ_INTERVAL_SECONDS", 0.0),
        )

    async def dispatch_absorbing(self, state_seed=None):
        """Dispatch into the absorbing shape; return (result, entry, state)."""
        backend, state, clock = self.absorbing(server.ROOT)
        if state_seed is not None:
            state_seed(state)
        time_patch, interval_patch = self.watcher_patches(clock)
        with patch.object(server, "HERDR", backend), time_patch, interval_patch:
            listed = await server._discover_project_candidates()
            ref = listed["candidates"][0]["candidate_id"]
            result = await dispatch_candidate(ref, self.TASK)
            entry = server._HANDOFF_REGISTRY.get(result.get("handoff_id")) \
                if result.get("ok") else None
            if entry is not None:
                await entry["watcher_task"]
        return result, entry, state

    async def test_reprompt_marker_latches_without_task_or_screen_text(self):
        server._HANDOFF_REGISTRY.clear()
        server._WORK_REGISTRY.clear()
        server._RESULT_INBOX.clear()
        result, entry, state = await self.dispatch_absorbing()
        self.assertTrue(result["ok"], result)
        self.assertEqual(entry["state"], "needs_attention")
        self.assertEqual(entry["reason"], "agy_composer_recovery_exhausted")
        self.assertIs(entry["agy_recovery_reprompt"], True)
        self.assertNotIn("agy_recovery_active", entry)  # cleared at terminal latch
        prompts = [c for c in state["calls"] if c[:2] == ("agent", "prompt")]
        self.assertEqual(len(prompts), 2)  # dispatch + exactly ONE reprompt
        self.assertEqual(prompts[1][3], self.TASK)
        reads = [c for c in state["calls"] if c[:2] == ("agent", "read")]
        self.assertEqual(len(reads), 2)
        _work_ref, work = next(iter(server._WORK_REGISTRY.items()))
        self.assertIs(work["agy_recovery_reprompt"], True)
        receipt = work_record(work)
        self.assertIs(receipt["agy_recovery_reprompt"], True)
        # Neither task text nor screen text is ever persisted.
        for serialized in (json.dumps(receipt, default=str),
                           json.dumps(entry, default=str),
                           json.dumps(work, default=str)):
            self.assertNotIn(self.TASK, serialized)
            self.assertNotIn("Gemini", serialized)
            self.assertNotIn("Context:", serialized)

    async def test_unacknowledged_reprompt_keeps_two_total_prompts_no_marker(self):
        for label, receipt_for in (
            ("untyped-receipt",
             lambda agent: {"agent": dict(agent)}),
            ("wrong-terminal",
             lambda agent: {"type": "agent_prompted",
                            "agent": dict(agent, terminal_id="term-other")}),
        ):
            with self.subTest(variant=label):
                server._HANDOFF_REGISTRY.clear()
                server._WORK_REGISTRY.clear()
                server._RESULT_INBOX.clear()

                def seed(state, receipt_for=receipt_for):
                    agent = state["agent"]
                    # Only acknowledged initial dispatch permits recovery.
                    attempts = [0]
                    def prompt(*args):
                        attempts[0] += 1
                        return ({"type": "agent_prompted", "agent": dict(agent)}
                                if attempts[0] == 1 else receipt_for(agent))
                    state["prompt_handler"] = prompt

                result, entry, state = await self.dispatch_absorbing(
                    state_seed=seed)
                self.assertTrue(result["ok"], result)
                self.assertEqual(entry["state"], "needs_attention")
                self.assertEqual(
                    entry["reason"], "agy_composer_recovery_reprompt_uncertain")
                self.assertNotIn("agy_recovery_reprompt", entry)
                kinds = [c[:2] for c in state["calls"]]
                # Exactly two task-carrying prompt attempts total: initial
                # dispatch + the one recovery reprompt; never a third.
                self.assertEqual(kinds.count(("agent", "prompt")), 2)
                self.assertEqual(kinds.count(("agent", "read")), 2)
                _work_ref, work = next(iter(server._WORK_REGISTRY.items()))
                self.assertNotIn("agy_recovery_reprompt", work)
                receipt = work_record(work)
                self.assertNotIn("agy_recovery_reprompt", receipt)

    async def test_unknown_initial_delivery_never_enables_recovery_redelivery(self):
        server._HANDOFF_REGISTRY.clear()
        server._WORK_REGISTRY.clear()
        server._RESULT_INBOX.clear()
        def seed(state):
            state['prompt_handler'] = lambda *args: {}
        result, entry, state = await self.dispatch_absorbing(state_seed=seed)
        self.assertEqual(result['prompt_transport']['submission_evidence']['state'], 'delivery_unknown')
        self.assertEqual(entry['reason'], 'activation_observation_budget_exhausted')
        self.assertNotIn('agy_recovery_reprompt', entry)
        kinds = [call[:2] for call in state['calls']]
        self.assertEqual(kinds.count(('agent', 'prompt')), 1)
        self.assertEqual(kinds.count(('agent', 'read')), 0)
        self.assertEqual(kinds.count(('agent', 'send-keys')), 0)

    async def test_dispatch_rejected_while_recovery_window_active(self):
        server._HANDOFF_REGISTRY.clear()
        server._WORK_REGISTRY.clear()
        server._RESULT_INBOX.clear()
        backend, state = manual_backend(server.ROOT)
        with patch.object(server, "HERDR", backend):
            listed = await server._discover_project_candidates()
            ref = listed["candidates"][0]["candidate_id"]
            record = server._manual_candidate_record(ref)
            server._HANDOFF_REGISTRY["h-recovering"] = {
                "handoff_id": "h-recovering", "candidate_id": None,
                "resource_key": record["candidate"]["resource_key"],
                "execution_identity": None, "state": "running",
                "joined_once": True, "agy_recovery_active": True,
            }
            result = await dispatch_candidate(ref, "must not double-dispatch")
        self.assertFalse(result["ok"])
        self.assertEqual(result["error_type"], "AgentHandoffInFlight")
        self.assertEqual(
            [c[:2] for c in state["calls"]].count(("agent", "prompt")), 0)

    async def test_recovery_declines_when_other_consumed_handoff_same_resource(self):
        server._HANDOFF_REGISTRY.clear()
        server._WORK_REGISTRY.clear()
        server._RESULT_INBOX.clear()
        backend_probe, _ = manual_backend(server.ROOT)
        with patch.object(server, "HERDR", backend_probe):
            listed = await server._discover_project_candidates()
            record = server._manual_candidate_record(
                listed["candidates"][0]["candidate_id"])
        # Incident shape: an earlier same-pane Work was already awaited
        # (joined_once) yet its handoff is still nonterminal.
        server._HANDOFF_REGISTRY["h-consumed"] = {
            "handoff_id": "h-consumed", "candidate_id": None,
            "resource_key": record["candidate"]["resource_key"],
            "execution_identity": None, "state": "running", "joined_once": True,
        }
        result, entry, state = await self.dispatch_absorbing()
        self.assertTrue(result["ok"], result)
        self.assertEqual(entry["reason"], "activation_observation_budget_exhausted")
        self.assertNotIn("agy_recovery_reprompt", entry)
        kinds = [c[:2] for c in state["calls"]]
        self.assertEqual(kinds.count(("agent", "prompt")), 1)  # dispatch only
        self.assertEqual(kinds.count(("agent", "read")), 0)

    async def test_recovery_declines_when_other_active_work_same_resource(self):
        server._HANDOFF_REGISTRY.clear()
        server._WORK_REGISTRY.clear()
        server._RESULT_INBOX.clear()
        backend_probe, _ = manual_backend(server.ROOT)
        with patch.object(server, "HERDR", backend_probe):
            listed = await server._discover_project_candidates()
            record = server._manual_candidate_record(
                listed["candidates"][0]["candidate_id"])
        server._WORK_REGISTRY["w-other"] = {
            "work_ref": "w-other", "state": "running",
            "resource_key": record["candidate"]["resource_key"],
            "execution_identity": None,
        }
        result, entry, state = await self.dispatch_absorbing()
        self.assertTrue(result["ok"], result)
        self.assertEqual(entry["reason"], "activation_observation_budget_exhausted")
        self.assertNotIn("agy_recovery_reprompt", entry)
        kinds = [c[:2] for c in state["calls"]]
        self.assertEqual(kinds.count(("agent", "prompt")), 1)
        self.assertEqual(kinds.count(("agent", "read")), 0)
