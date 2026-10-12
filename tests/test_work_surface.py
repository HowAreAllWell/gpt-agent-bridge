import asyncio
import contextlib
import json
import logging
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault(
    "BRIDGE_PATH_TOKEN",
    "test-token-abcdefghijklmnopqrstuvwxyz-012345",
)

from gpt_agent_bridge import herdr_backend
from gpt_agent_bridge import server
from tests.work_observation import delegate_item
from tests.work_observation import finished_work
from tests.test_manual_agents import manual_backend
from gpt_agent_bridge.workspace_context import WorkspaceRegistry


def git_worktree(path: Path) -> Path:
    path.mkdir()
    subprocess.run(["git", "init", "--quiet", str(path)], check=True)
    return path.resolve()


def git_repo_with_linked_worktree(container: Path) -> tuple[Path, Path]:
    root = git_worktree(container / "registered-project")
    subprocess.run(["git", "config", "user.name", "Bridge Test"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.email", "bridge@example.test"], cwd=root, check=True)
    (root / "README.md").write_text("bridge\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=root, check=True)
    subprocess.run(["git", "commit", "--quiet", "-m", "init"], cwd=root, check=True)
    linked = (container / "execution-space" / "agent-one").resolve()
    linked.parent.mkdir()
    subprocess.run(
        ["git", "worktree", "add", "--quiet", "-b", "agent-one", str(linked), "HEAD"],
        cwd=root,
        check=True,
    )
    return root, linked


def git_repo_with_two_linked_worktrees(container: Path) -> tuple[Path, Path, Path]:
    root, first = git_repo_with_linked_worktree(container)
    second = (container / "execution-space" / "agent-two").resolve()
    subprocess.run(
        ["git", "worktree", "add", "--quiet", "-b", "agent-two", str(second), "HEAD"],
        cwd=root,
        check=True,
    )
    return root, first, second


async def _slow_watch(*_args, **_kwargs):
    await asyncio.sleep(30)


class WorkSurfaceTests(unittest.IsolatedAsyncioTestCase):
    """Delegate/await substrate contract tests (process-local)."""

    def setUp(self):
        server._HANDOFF_REGISTRY.clear()
        for name in ('_WORK_REGISTRY', '_RESULT_INBOX', '_WORK_WATCHES', '_WORK_WATCH_WAITERS'):
            patcher = patch.object(server, name, {})
            patcher.start()
            self.addCleanup(patcher.stop)

    def _project(self, target: Path, ref: str = "research"):
        registry = WorkspaceRegistry(server.ROOT, json.dumps({ref: str(target)}))
        backend, state = manual_backend(target)
        return registry, backend, state

    @contextlib.contextmanager
    def _patches(self, registry, backend, target):
        # Fixture agents are kind agy; the authorized AGY settlement debounce
        # (one full 60s interval) is watch-layer contract tested with mocked
        # time elsewhere, so these substrate tests keep zero-second logical
        # confirmation instead of real minute-long waits.
        with patch.object(server, "_WORKSPACE_REGISTRY", registry), patch.object(
            server, "_WORKSPACE_BACKENDS", {str(target): backend}
        ), patch.object(herdr_backend, "AGY_SETTLEMENT_CONFIRM_SECONDS", 0.0), patch.object(
            herdr_backend, "AGY_SETTLEMENT_CONFIRM_ATTEMPTS", 1
        ):
            yield

    async def _discover(self, ref="research"):
        listed = await server._discover_project_candidates(workspace_ref=ref)
        self.assertTrue(listed["ok"], listed)
        return listed["candidates"][0]["candidate_id"]

    async def _cancel_watchers(self):
        for entry in list(server._HANDOFF_REGISTRY.values()):
            watcher = entry.get("watcher_task")
            if watcher is not None and not watcher.done():
                watcher.cancel()
                with contextlib.suppress(asyncio.CancelledError, asyncio.TimeoutError):
                    await asyncio.wait_for(watcher, timeout=2)

    async def test_delegate_requires_explicit_registered_project_ref(self):
        with tempfile.TemporaryDirectory() as temp:
            target = git_worktree(Path(temp) / "target")
            registry, backend, _state = self._project(target)
            with self._patches(registry, backend, target):
                for bad_ref in ("", "   ", None, 7):
                    with self.subTest(bad_ref=bad_ref):
                        res = await delegate_item(bad_ref, assignments=[{'agent_ref': "a", 'task': "t"}])
                        self.assertFalse(res["ok"])
                        self.assertEqual(res["error_type"], "ProjectRefRequired")
                res = await delegate_item("missing", assignments=[{'agent_ref': "a", 'task': "t"}])
                self.assertEqual(res["error_type"], "ProjectRefUnauthorized")
                res = await finished_work(project_ref="missing", work_ref="work-x")
                self.assertEqual(res["error_type"], "ProjectRefUnauthorized")

    async def test_delegate_fails_closed_on_mismatch_and_unknown_agent_ref(self):
        with tempfile.TemporaryDirectory() as temp:
            target = git_worktree(Path(temp) / "target")
            other = git_worktree(Path(temp) / "other")
            registry = WorkspaceRegistry(
                server.ROOT, json.dumps({"research": str(target), "other": str(other)})
            )
            backend, state = manual_backend(target)
            with patch.object(server, "_WORKSPACE_REGISTRY", registry), patch.object(
                server, "_WORKSPACE_BACKENDS", {str(target): backend}
            ):
                candidate_id = await self._discover("research")
                res = await delegate_item("other", assignments=[{'agent_ref': candidate_id, 'task': "wrong project"}])
                self.assertFalse(res["ok"])
                self.assertEqual(res["error_type"], "AgentRefProjectMismatch")
                self.assertEqual(
                    [c for c in state["calls"] if c[:2] == ("agent", "prompt")], []
                )
                self.assertEqual(len(server._WORK_REGISTRY), 0)
                for bad_ref in ("work-unknown", ""):
                    with self.subTest(bad_ref=bad_ref):
                        res = await delegate_item("research", assignments=[{'agent_ref': bad_ref, 'task': "t"}])
                        self.assertFalse(res["ok"])
                        self.assertEqual(res["error_type"], "UnknownAgentRef")
                self.assertEqual(len(server._WORK_REGISTRY), 0)

    async def test_work_capacity_fails_before_native_prompt(self):
        with tempfile.TemporaryDirectory() as temp:
            target = git_worktree(Path(temp) / "target")
            registry, backend, state = self._project(target)
            with self._patches(registry, backend, target):
                candidate_id = await self._discover("research")
                for max_records, fill in ((0, 0), (1, 1), (2, 2)):
                    with self.subTest(max_records=max_records, fill=fill):
                        server._WORK_REGISTRY.clear()
                        server._RESULT_INBOX.clear()
                        for i in range(fill):
                            server._WORK_REGISTRY[f"work-dummy-{max_records}-{i}"] = {
                                "work_ref": f"work-dummy-{max_records}-{i}",
                                "project_ref": "research",
                                "workspace_root": str(target),
                                "agent_ref": f"other-{i}",
                                "agent_key": None,
                                "state": "running",
                                "reason": "delegated",
                                "handoff_id": None,
                                "created_at": 0.0,
                                "settled_at": None,
                                "post_state_change_seq": None,
                                                            }
                        prompts_before = len(
                            [c for c in state["calls"] if c[:2] == ("agent", "prompt")]
                        )
                        with patch.object(server, "MAX_ACTIVE_WORK_RECORDS", max_records):
                            res = await delegate_item("research", assignments=[{'agent_ref': candidate_id, 'task': f"must never prompt {max_records}"}])
                        self.assertFalse(res["ok"])
                        self.assertEqual(res["error_type"], "WorkRegistryFull")
                        self.assertNotIn("work_ref", res)
                        self.assertEqual(
                            len([c for c in state["calls"] if c[:2] == ("agent", "prompt")]),
                            prompts_before,
                        )
                        self.assertEqual(len(server._WORK_REGISTRY), fill)

    async def test_delegate_reuses_resource_handle_and_refreshes_execution_before_dispatch(self):
        with tempfile.TemporaryDirectory() as temp:
            target = git_worktree(Path(temp) / "target")
            registry, backend, state = self._project(target)
            with self._patches(registry, backend, target):
                candidate_id = await self._discover("research")
                stale = server._MANUAL_AGENT_CANDIDATES[candidate_id]["candidate"]
                stale_fingerprint = stale["process"]["fingerprint"]

                state["agent"] = {
                    **state["agent"],
                    "_pid": 98765,
                }

                refreshed_context = await server.context(project_ref="research")
                self.assertEqual(refreshed_context["agents"][0]["handle"], candidate_id)
                refreshed = server._MANUAL_AGENT_CANDIDATES[candidate_id]["candidate"]
                self.assertNotEqual(refreshed["process"]["fingerprint"], stale_fingerprint)

                res = await delegate_item("research", assignments=[{'agent_ref': candidate_id, 'task': "resource handle refresh before dispatch"}])
                self.assertTrue(res["ok"], res)
                work = server._WORK_REGISTRY[res["work_ref"]]
                self.assertEqual(
                    work["execution_identity"],
                    server._execution_identity(str(target), refreshed),
                )
                self.assertEqual(
                    [c[:2] for c in state["calls"]].count(("agent", "prompt")), 1
                )
                await server._HANDOFF_REGISTRY[work["handoff_id"]]["watcher_task"]

    async def test_discovery_keeps_agent_ref_across_same_common_git_linked_cwd(self):
        with tempfile.TemporaryDirectory() as temp:
            root, linked = git_repo_with_linked_worktree(Path(temp))
            registry, backend, state = self._project(root)
            with self._patches(registry, backend, root):
                original = await server.context(project_ref="research")
                original_ref = original["agents"][0]["handle"]
                original_candidate = server._MANUAL_AGENT_CANDIDATES[original_ref]["candidate"]

                state["agent"] = {
                    **state["agent"],
                    "cwd": str(linked),
                    "foreground_cwd": str(linked),
                }
                moved = await server.context(project_ref="research")

                self.assertEqual(moved["agents"][0]["handle"], original_ref)
                moved_candidate = server._MANUAL_AGENT_CANDIDATES[original_ref]["candidate"]
                self.assertEqual(moved_candidate["identity"]["cwd"], str(linked))
                self.assertEqual(
                    moved_candidate["resource_key"], original_candidate["resource_key"]
                )
                self.assertNotEqual(
                    moved_candidate["candidate_key"], original_candidate["candidate_key"]
                )
                self.assertFalse(str(linked).startswith(str(root) + os.sep))

    async def test_discovery_rejects_foreign_repository_cwd(self):
        with tempfile.TemporaryDirectory() as temp:
            container = Path(temp)
            root = git_worktree(container / "registered")
            foreign = git_worktree(container / "registered-looking-foreign")
            registry, backend, state = self._project(root)
            registered_refs = registry.refs
            with self._patches(registry, backend, root):
                for reported_cwd, foreground_cwd in (
                    (foreign, foreign),
                    (foreign, root),
                    (root, foreign),
                ):
                    with self.subTest(
                        reported_cwd=reported_cwd,
                        foreground_cwd=foreground_cwd,
                    ):
                        state["agent"] = {
                            **state["agent"],
                            "cwd": str(reported_cwd),
                            "foreground_cwd": str(foreground_cwd),
                        }
                        observed = await server.context(project_ref="research")
                        self.assertEqual(observed["agents"], [])
                        excluded = reported_cwd == foreground_cwd == foreign
                        self.assertEqual(observed["agents_skipped_count"], 0 if excluded else 1)
                        self.assertEqual(observed["agents_complete"], excluded)
                        self.assertEqual(observed["agents_coverage_counts"], {
                            "out_of_project": int(excluded),
                            "invalid_or_unavailable": int(not excluded), "truncated": 0,
                        })
            self.assertEqual(registry.refs, registered_refs)
            self.assertNotIn(
                str(foreign),
                {str(entry[0]) for entry in registry.all_entries().values()},
            )

    async def test_distinct_agents_sharing_one_checkout_are_both_admitted(self):
        with tempfile.TemporaryDirectory() as temp:
            root = git_worktree(Path(temp) / "target")
            registry, backend, state = self._project(root)
            state["created_agents"].append({
                **state["agent"],
                "pane_id": "w-manual:p2",
                "terminal_id": "term-manual-2",
                "name": "agent-two",
                "_pid": 4321,
            })
            state["panes"].append({
                "workspace_id": "w-manual",
                "cwd": str(root),
                "tab_id": "w-manual:t1",
                "pane_id": "w-manual:p2",
                "terminal_id": "term-manual-2",
            })
            with self._patches(registry, backend, root):
                await server.context(project_ref="research")
                refs = {
                    record["candidate"]["identity"]["pane_id"]: candidate_id
                    for candidate_id, record in server._MANUAL_AGENT_CANDIDATES.items()
                }
                with patch.object(backend, "watch_manual_agent_turn", _slow_watch):
                    first, second = await asyncio.gather(
                        delegate_item("research", assignments=[{'agent_ref': refs["w-manual:p1"], 'task': "first"}]),
                        delegate_item("research", assignments=[{'agent_ref': refs["w-manual:p2"], 'task': "second"}]),
                    )
                    # A shared checkout admits both distinct Agent resources; the
                    # same-resource duplicate prompt protection still rejects.
                    duplicate = await delegate_item("research", assignments=[{'agent_ref': refs["w-manual:p1"], 'task': "must be blocked"}])

                self.assertTrue(first["ok"], first)
                self.assertTrue(second["ok"], second)
                self.assertNotEqual(first["work_ref"], second["work_ref"])
                self.assertFalse(duplicate["ok"])
                self.assertEqual(duplicate["error_type"], "WorkAlreadyInFlight")
                self.assertEqual(duplicate["existing_work_ref"], first["work_ref"])
                self.assertEqual(
                    [
                        c
                        for c in state["calls"]
                        if c[:2] in {("agent", "rebind"), ("agent", "wait")}
                    ],
                    [],
                )
                self.assertEqual(
                    [c[:2] for c in state["calls"]].count(("agent", "prompt")), 2
                )
                await self._cancel_watchers()

    async def test_concurrent_preplaced_linked_agents_preserve_same_common_git_acceptance(self):
        with tempfile.TemporaryDirectory() as temp:
            root, linked = git_repo_with_linked_worktree(Path(temp))
            registry, backend, state = self._project(root)
            state["created_agents"].append({
                **state["agent"],
                "pane_id": "w-manual:p2",
                "terminal_id": "term-manual-2",
                "name": "agent-two",
                "cwd": str(linked),
                "foreground_cwd": str(linked),
                "_pid": 4321,
            })
            state["panes"].append({
                "workspace_id": "w-manual",
                "cwd": str(linked),
                "tab_id": "w-manual:t1",
                "pane_id": "w-manual:p2",
                "terminal_id": "term-manual-2",
            })
            with self._patches(registry, backend, root):
                await server.context(project_ref="research")
                refs = {
                    record["candidate"]["identity"]["pane_id"]: candidate_id
                    for candidate_id, record in server._MANUAL_AGENT_CANDIDATES.items()
                }
                with patch.object(backend, "watch_manual_agent_turn", _slow_watch):
                    first, second = await asyncio.gather(
                        delegate_item("research", assignments=[{'agent_ref': refs["w-manual:p1"], 'task': "first"}]),
                        delegate_item("research", assignments=[{'agent_ref': refs["w-manual:p2"], 'task': "second"}]),
                    )

                self.assertTrue(first["ok"], first)
                self.assertTrue(second["ok"], second)
                self.assertEqual(
                    [c for c in state["calls"] if c[:2] == ("agent", "rebind")], []
                )
                self.assertEqual(
                    [c for c in state["calls"] if c[:2] == ("agent", "wait")], []
                )
                self.assertEqual(
                    [c[:2] for c in state["calls"]].count(("agent", "prompt")), 2
                )
                await self._cancel_watchers()

    async def test_first_context_discovers_root_and_two_preplaced_linked_agents(self):
        with tempfile.TemporaryDirectory() as temp:
            root, first_linked, second_linked = git_repo_with_two_linked_worktrees(
                Path(temp)
            )
            registry, backend, state = self._project(root)
            state["agent"] = {
                **state["agent"],
                "agent": "codex",
                "agent_session": {
                    "kind": "id",
                    "value": "01999999-1111-7111-8111-111111111111",
                },
            }
            state["created_agents"].extend([
                {
                    **state["agent"],
                    "agent": "agy",
                    "agent_session": None,
                    "pane_id": "w-manual:p2",
                    "terminal_id": "term-manual-2",
                    "cwd": str(root),
                    "foreground_cwd": str(first_linked),
                    "_pid": 4321,
                },
                {
                    **state["agent"],
                    "agent": "qoder",
                    "agent_session": None,
                    "pane_id": "w-manual:p3",
                    "terminal_id": "term-manual-3",
                    "cwd": str(first_linked),
                    "foreground_cwd": str(second_linked),
                    "_pid": 5432,
                },
            ])
            state["panes"].extend([
                {
                    "workspace_id": "w-manual",
                    "cwd": str(root),
                    "tab_id": "w-manual:t1",
                    "pane_id": "w-manual:p2",
                    "terminal_id": "term-manual-2",
                },
                {
                    "workspace_id": "w-manual",
                    "cwd": str(first_linked),
                    "tab_id": "w-manual:t1",
                    "pane_id": "w-manual:p3",
                    "terminal_id": "term-manual-3",
                },
            ])

            with self._patches(registry, backend, root):
                first = await server.context(project_ref="research")
                second = await server.context(project_ref="research")

            first_by_kind = {agent["kind"]: agent for agent in first["agents"]}
            second_by_kind = {agent["kind"]: agent for agent in second["agents"]}
            self.assertEqual(set(first_by_kind), {"codex", "agy", "qoder"})
            self.assertEqual(first["agents_skipped_count"], 0)
            self.assertEqual(
                {kind: agent["handle"] for kind, agent in first_by_kind.items()},
                {kind: agent["handle"] for kind, agent in second_by_kind.items()},
            )
            self.assertEqual(first_by_kind["codex"]["hint"], "tab 1 / pane 1")
            self.assertEqual(first_by_kind["agy"]["hint"], "tab 1 / pane 2")
            self.assertEqual(first_by_kind["qoder"]["hint"], "tab 1 / pane 3")
            self.assertEqual(
                [call for call in state["calls"] if call[:2] == ("agent", "rebind")],
                [],
            )

    async def test_delegate_old_handle_refreshes_current_execution_without_context_round_trip(self):
        with tempfile.TemporaryDirectory() as temp:
            target = git_worktree(Path(temp) / "target")
            registry, backend, state = self._project(target)
            with self._patches(registry, backend, target):
                candidate_id = await self._discover("research")
                old_fingerprint = server._MANUAL_AGENT_CANDIDATES[candidate_id]["candidate"]["process"]["fingerprint"]
                state["agent"] = {**state["agent"], "_pid": 98765}

                res = await delegate_item("research", assignments=[{'agent_ref': candidate_id, 'task': "direct resource refresh before dispatch"}])
                self.assertTrue(res["ok"], res)
                refreshed = server._MANUAL_AGENT_CANDIDATES[candidate_id]["candidate"]
                self.assertNotEqual(refreshed["process"]["fingerprint"], old_fingerprint)
                work = server._WORK_REGISTRY[res["work_ref"]]
                self.assertEqual(
                    work["execution_identity"],
                    server._execution_identity(str(target), refreshed),
                )
                await server._HANDOFF_REGISTRY[work["handoff_id"]]["watcher_task"]

    async def test_work_execution_identity_is_unset_until_writer_gated_refresh(self):
        with tempfile.TemporaryDirectory() as temp:
            target = git_worktree(Path(temp) / "target")
            registry, backend, state = self._project(target)
            with self._patches(registry, backend, target):
                candidate_id = await self._discover("research")
                reserved = asyncio.Event()
                original_reserve = server._reserve_work
                original_execution_identity = server._execution_identity
                pre_gate_identity_calls = []
                writer_gate_released = False

                def reserve_and_signal(*args, **kwargs):
                    work = original_reserve(*args, **kwargs)
                    reserved.set()
                    return work

                def track_execution_identity(*args, **kwargs):
                    if not writer_gate_released:
                        pre_gate_identity_calls.append((args, kwargs))
                    return original_execution_identity(*args, **kwargs)

                writer_lease = await server._access_gate(target).acquire("writer")
                with patch.object(
                    server, "_reserve_work", side_effect=reserve_and_signal
                ), patch.object(
                    server, "_execution_identity", side_effect=track_execution_identity
                ):
                    try:
                        delegation = asyncio.create_task(delegate_item("research", assignments=[{'agent_ref': candidate_id, 'task': "bind only after gated refresh"}]))
                        await asyncio.wait_for(reserved.wait(), timeout=2)
                        work = next(iter(server._WORK_REGISTRY.values()))
                        pre_gate_execution_identity = work["execution_identity"]
                        state["agent"] = {**state["agent"], "_pid": 98765}
                    finally:
                        writer_gate_released = True
                        await writer_lease.release()

                    result = await delegation
                    self.assertTrue(result["ok"], result)
                    work = server._WORK_REGISTRY[result["work_ref"]]
                    refreshed = server._MANUAL_AGENT_CANDIDATES[candidate_id]["candidate"]
                    self.assertIsNone(pre_gate_execution_identity)
                    self.assertEqual(pre_gate_identity_calls, [])
                    self.assertEqual(
                        work["execution_identity"],
                        server._execution_identity(str(target), refreshed),
                    )
                    await server._HANDOFF_REGISTRY[work["handoff_id"]]["watcher_task"]

    async def test_duplicate_stale_handle_for_same_resource_cannot_bypass_in_flight_work(self):
        with tempfile.TemporaryDirectory() as temp:
            target = git_worktree(Path(temp) / "target")
            registry, backend, state = self._project(target)
            with self._patches(registry, backend, target):
                candidate_id = await self._discover("research")
                duplicate_id = "f" * 32
                original_record = server._MANUAL_AGENT_CANDIDATES[candidate_id]
                server._MANUAL_AGENT_CANDIDATES[duplicate_id] = {
                    **original_record,
                    "candidate": {
                        **original_record["candidate"],
                        "identity": dict(original_record["candidate"]["identity"]),
                        "process": dict(original_record["candidate"]["process"]),
                    },
                }

                with patch.object(backend, "watch_manual_agent_turn", _slow_watch):
                    first = await delegate_item("research", assignments=[{'agent_ref': candidate_id, 'task': "first task"}])
                    self.assertTrue(first["ok"], first)
                    first_work = server._WORK_REGISTRY[first["work_ref"]]
                    first_handoff = server._HANDOFF_REGISTRY[first_work["handoff_id"]]
                    self.assertEqual(
                        first_work["resource_key"],
                        original_record["candidate"]["resource_key"],
                    )
                    self.assertEqual(
                        first_handoff["resource_key"], first_work["resource_key"]
                    )
                    state["agent"] = {**state["agent"], "_pid": 98765}

                    second = await delegate_item("research", assignments=[{'agent_ref': duplicate_id, 'task': "must be blocked"}])

                self.assertFalse(second["ok"])
                self.assertIn(
                    second["error_type"],
                    {"WorkAlreadyInFlight", "AgentTurnOutstanding"},
                )
                self.assertEqual(
                    [c[:2] for c in state["calls"]].count(("agent", "prompt")), 1
                )
                await self._cancel_watchers()

    async def test_delegate_resource_revalidation_fails_closed_without_rebinding_or_prompt(self):
        with tempfile.TemporaryDirectory() as temp:
            target = git_worktree(Path(temp) / "target")
            for case in (
                "missing", "ambiguous", "malformed_sibling", "different_kind_sibling",
                "process_unavailable", "kind_drift",
            ):
                with self.subTest(case=case):
                    server._MANUAL_AGENT_CANDIDATES.clear()
                    server._HANDOFF_REGISTRY.clear()
                    server._WORK_REGISTRY.clear()
                    server._RESULT_INBOX.clear()
                    registry, backend, state = self._project(target)
                    with self._patches(registry, backend, target):
                        candidate_id = await self._discover("research")
                        if case == "missing":
                            state["agent"] = None
                        elif case == "ambiguous":
                            state["created_agents"].append(dict(state["agent"]))
                        elif case == "malformed_sibling":
                            state["created_agents"].append(
                                {**state["agent"], "name": "bad name"}
                            )
                        elif case == "different_kind_sibling":
                            state["created_agents"].append(
                                {**state["agent"], "agent": "pi"}
                            )
                        elif case == "process_unavailable":
                            state["process_info"] = {
                                "pane_id": state["agent"]["pane_id"],
                                "foreground_process_group_id": None,
                                "foreground_processes": [],
                            }
                        else:
                            state["agent"] = {**state["agent"], "agent": "pi"}

                        res = await delegate_item("research", assignments=[{'agent_ref': candidate_id, 'task': "must not dispatch"}])
                        self.assertFalse(res["ok"])
                        self.assertIn(
                            res["error_type"],
                            {"AgentRefObservationUnavailable", "AgentRefRevalidationUncertain"},
                        )
                        self.assertEqual(server._WORK_REGISTRY, {})
                        self.assertEqual(
                            [c for c in state["calls"] if c[:2] == ("agent", "prompt")],
                            [],
                        )


    def test_project_notice_lease_env_parser_default_bounds_and_fallback(self):
        parse = server._parse_await_lease_seconds
        self.assertEqual(parse(None), (90.0, None))
        self.assertEqual(parse(""), (90.0, None))
        self.assertEqual(parse("   "), (90.0, None))
        self.assertEqual(parse("90"), (90.0, None))
        for raw, expected in (("105", 105.0), ("120", 120.0), ("150", 150.0),
                              ("1", 1.0), ("600", 600.0)):
            value, warning = parse(raw)
            self.assertEqual((value, warning), (expected, None), raw)
        for raw in ("abc", "12.5.1", "nan", "inf", "-inf", "1e400",
                    "0.99", "600.1", "-5", "true"):
            value, warning = parse(raw)
            self.assertEqual(value, 90.0, raw)
            self.assertTrue(warning, raw)
            self.assertLessEqual(len(warning), 300)

    async def test_project_notice_lease_env_import_wiring_via_subprocess(self):
        # The child import must never read or create the real per-user registry:
        # the store path is pinned to a TemporaryDirectory-backed file and
        # HOME/XDG_STATE_HOME are isolated too.
        with tempfile.TemporaryDirectory() as temp:
            temp_path = Path(temp)
            repo = Path(__file__).resolve().parents[1]
            default = git_worktree(temp_path / "default")
            code = (
                "import json; from gpt_agent_bridge import server\n"
                "print(json.dumps({'lease': server.WORK_AWAIT_LEASE_SECONDS}))\n"
            )
            base_env = {
                "PATH": os.defpath,
                "LANG": "C.UTF-8",
                "PYTHONDONTWRITEBYTECODE": "1",
                "BRIDGE_WORKSPACE": str(default),
                "BRIDGE_PATH_TOKEN": "synthetic-lease-only-0123456789abcdef",
                "HOME": temp_path,
                "XDG_STATE_HOME": str(temp_path / "state"),
                "BRIDGE_WORKSPACE_STORE_PATH": str(temp_path / "workspace-registry-v1.json"),
            }
            for raw, expected in (("105", 105.0), ("abc", 90.0), ("", 90.0), ("601", 90.0)):
                env = dict(base_env)
                env["BRIDGE_AWAIT_LEASE_SECONDS"] = raw
                result = await asyncio.to_thread(
                    subprocess.run, [sys.executable, "-B", "-c", code],
                    env=env, capture_output=True, text=True, timeout=60)
                self.assertEqual(result.returncode, 0, (raw, result.stderr))
                lease = json.loads(result.stdout.strip().splitlines()[-1])["lease"]
                self.assertEqual(lease, expected, raw)
            # Isolation held: no state dir was created under the fake HOME and
            # the pinned store file was read (never created/written) by import.
            self.assertFalse((temp_path / "state" / "gpt-agent-bridge").exists())
            self.assertFalse((temp_path / "workspace-registry-v1.json").exists())



    async def test_delegate_success_retains_terminal_record_for_repeated_reads(self):
        with tempfile.TemporaryDirectory() as temp:
            target = git_worktree(Path(temp) / "target")
            registry, backend, state = self._project(target)
            with self._patches(registry, backend, target):
                candidate_id = await self._discover("research")
                res = await delegate_item("research", assignments=[{'agent_ref': candidate_id, 'task': "delegate-ok"}])
                work_ref = res["work_ref"]
                self.assertEqual({k: res[k] for k in ("ok", "work_ref")}, {"ok": True, "work_ref": work_ref})
                self.assertTrue(server._WORK_REGISTRY[work_ref]["watch_refs"])
                self.assertTrue(work_ref.startswith("work-"))
                for banned in (
                    "state", "project_ref", "dispatch", "attribution",
                    "result", "completion", "handoff_id", "candidate_id",
                ):
                    self.assertNotIn(banned, res)
                self.assertEqual(
                    [c[:2] for c in state["calls"]].count(("agent", "prompt")), 1
                )
                work = server._WORK_REGISTRY[work_ref]
                hid = work["handoff_id"]
                self.assertIn(hid, server._HANDOFF_REGISTRY)
                self.assertIsNotNone(server._HANDOFF_REGISTRY[hid]["watcher_task"])
                await server._HANDOFF_REGISTRY[hid]["watcher_task"]
                self.assertEqual(work["state"], "agent_turn_settled")
                self.assertNotIn(hid, server._HANDOFF_REGISTRY)

                first = await finished_work(project_ref="research", work_ref=work_ref)
                self.assertTrue(first["state"] in server.WORK_TERMINAL_STATES)
                self.assertEqual(first["state"], "agent_turn_settled")
                self.assertEqual(first["reason"], "state_transition_proven")
                self.assertIsNotNone(first["settled_at"])
                self.assertNotIn("report_requested", first)
                second = await finished_work(project_ref="research", work_ref=work_ref)
                self.assertEqual(second, first)
                # Terminal Work is retained, not evicted.
                self.assertIn(work_ref, server._WORK_REGISTRY)

    async def test_terminal_work_survives_handoff_pruning_and_pressure(self):
        with tempfile.TemporaryDirectory() as temp:
            target = git_worktree(Path(temp) / "target")
            registry, backend, state = self._project(target)
            with self._patches(registry, backend, target):
                candidate_id = await self._discover("research")
                with patch.object(backend, "watch_manual_agent_turn", _slow_watch):
                    res = await delegate_item("research", assignments=[{'agent_ref': candidate_id, 'task': "prune me not"}])
                work_ref = res["work_ref"]
                work = server._WORK_REGISTRY[work_ref]
                hid = work["handoff_id"]
                server._update_handoff_entry(
                    hid,
                    state="done",
                    reason="state_transition_proven",
                    herdr_status="idle",
                    post_seq=2,
                    post_rev=2,
                )
                self.assertEqual(work["state"], "agent_turn_settled")
                self.assertTrue(server._HANDOFF_REGISTRY[hid]["joined_once"])
                # Legacy gating released: later prompts to the same agent are not blocked.
                with patch.object(backend, "watch_manual_agent_turn", _slow_watch):
                    res2 = await delegate_item("research", assignments=[{'agent_ref': candidate_id, 'task': "next turn"}])
                self.assertTrue(res2["ok"], res2)
                self.assertNotEqual(res2["work_ref"], work_ref)
                work2 = server._WORK_REGISTRY[res2["work_ref"]]
                server._update_handoff_entry(
                    work2["handoff_id"],
                    state="done",
                    reason="state_transition_proven",
                    herdr_status="idle",
                    post_seq=3,
                    post_rev=3,
                )
                # Protected terminal reports backpressure admission without
                # expiring either retained receipt or sending another prompt.
                with patch.object(server, "MAX_TERMINAL_WORK_RECORDS", 2):
                    admitted = await delegate_item("research", assignments=[{'agent_ref': candidate_id, 'task': "admitted"}])
                self.assertEqual(admitted["error_type"], "WorkRegistryFull")
                self.assertEqual(admitted["capacity"]["dimension"], "delivery_retention")
                # Terminal Work retains its evidence record after handoff release.
                await self._cancel_watchers()
                server._HANDOFF_REGISTRY.clear()
                for _ in range(3):
                    awaited = await finished_work(project_ref="research", work_ref=work_ref)
                    self.assertTrue(awaited["state"] in server.WORK_TERMINAL_STATES)
                    self.assertEqual(awaited["state"], "agent_turn_settled")




    async def test_work_ref_unknown_is_honest_restart_loss(self):
        with tempfile.TemporaryDirectory() as temp:
            target = git_worktree(Path(temp) / "target")
            registry, backend, state = self._project(target)
            with self._patches(registry, backend, target):
                candidate_id = await self._discover("research")
                lost = await finished_work(
                    project_ref="research", work_ref="work-neverissued"
                )
                self.assertFalse(lost["ok"])
                self.assertEqual(lost["error_type"], "WorkRefUnavailable")
                self.assertIn("restart", lost["error"])
                with patch.object(backend, "watch_manual_agent_turn", _slow_watch):
                    res = await delegate_item("research", assignments=[{'agent_ref': candidate_id, 'task': "lost"}])
                work_ref = res["work_ref"]
                prompts_before = [c for c in state["calls"] if c[:2] == ("agent", "prompt")]
                # Simulated restart: both process-local registries are empty.
                server._WORK_REGISTRY.clear()
                server._RESULT_INBOX.clear()
                after = await finished_work(project_ref="research", work_ref=work_ref)
                self.assertFalse(after["ok"])
                self.assertEqual(after["error_type"], "WorkRefUnavailable")
                self.assertEqual(
                    [c for c in state["calls"] if c[:2] == ("agent", "prompt")],
                    prompts_before,
                    "restart loss must never resubmit or rebind external work",
                )
                await self._cancel_watchers()

    async def test_observed_non_owned_authority_unchanged(self):
        with tempfile.TemporaryDirectory() as temp:
            target = git_worktree(Path(temp) / "target")
            registry, backend, _state = self._project(target)
            with self._patches(registry, backend, target):
                candidate_id = await self._discover("research")
                with patch.object(backend, "watch_manual_agent_turn", _slow_watch):
                    res = await delegate_item("research", assignments=[{'agent_ref': candidate_id, 'task': "authority"}])
                self.assertTrue(res["ok"], res)
                self.assertNotIn("ownership", res)
                self.assertNotIn("lifecycle_authority", res)
                for tool_name in (
                    "work_cancel", "cancel_work", "work_cleanup", "work_release",
                    "work_kill", "work_recover",
                ):
                    self.assertIsNone(server.mcp._tool_manager.get_tool(tool_name))
                read = await server._read_agent_candidate(candidate_id=candidate_id)
                self.assertNotIn("ownership", read["candidate"])
                self.assertNotIn("lifecycle_authority", read["candidate"])
                await self._cancel_watchers()

    async def test_terminal_state_mapping_and_submission_evidence_retention(self):
        with tempfile.TemporaryDirectory() as temp:
            target = git_worktree(Path(temp) / "target")
            registry, backend, _state = self._project(target)
            with self._patches(registry, backend, target):
                candidate_id = await self._discover("research")
                cases = [
                    ("done", "state_transition_proven", "agent_turn_settled"),
                    ("needs_attention", "observation_unavailable", "needs_attention"),
                    ("failed", "candidate_continuity_lost", "continuity_lost"),
                ]
                for handoff_state, reason, expected_state in cases:
                    if any(server._diagnostic_condition(w) for w in server._WORK_REGISTRY.values()):
                        self.assertTrue((await server.agent_terminal_read("research", candidate_id))["ok"])
                    with self.subTest(handoff_state=handoff_state):
                        with patch.object(backend, "watch_manual_agent_turn", _slow_watch):
                            res = await delegate_item("research", assignments=[{'agent_ref': candidate_id, 'task': f"map {handoff_state}"}])
                        work_ref = res["work_ref"]
                        work = server._WORK_REGISTRY[work_ref]
                        submission = dict(work["submission_evidence"])
                        server._update_handoff_entry(work["handoff_id"], state=handoff_state,
                            reason=reason, herdr_status="idle", post_seq=3, post_rev=3)
                        self.assertEqual(work["state"], expected_state)
                        self.assertEqual(work["reason"], reason)
                        self.assertEqual(work["post_state_change_seq"], 3)
                        self.assertIsNotNone(work["settled_at"])
                        self.assertEqual(work["submission_evidence"], submission)
                await self._cancel_watchers()

    async def test_later_delegate_after_terminal_latch_is_not_blocked(self):
            with tempfile.TemporaryDirectory() as temp:
                target = git_worktree(Path(temp) / "target")
                registry, backend, state = self._project(target)
                with self._patches(registry, backend, target):
                    candidate_id = await self._discover("research")
                    with patch.object(backend, "watch_manual_agent_turn", _slow_watch):
                        first = await delegate_item("research", assignments=[{'agent_ref': candidate_id, 'task': "first"}])
                    work = server._WORK_REGISTRY[first["work_ref"]]
                    hid = work["handoff_id"]
                    # Completed but never awaited via any join: the legacy gate
                    # must still be released by the Work terminal latch alone.
                    server._update_handoff_entry(
                        hid,
                        state="done",
                        reason="state_transition_proven",
                        herdr_status="idle",
                        post_seq=2,
                        post_rev=2,
                    )
                    with patch.object(backend, "watch_manual_agent_turn", _slow_watch):
                        second = await delegate_item("research", assignments=[{'agent_ref': candidate_id, 'task': "second"}])
                    self.assertTrue(second["ok"], second)
                    self.assertNotEqual(second["work_ref"], first["work_ref"])
                    self.assertEqual(
                        [c[:2] for c in state["calls"]].count(("agent", "prompt")), 2
                    )
                    await self._cancel_watchers()

    async def test_delegate_transport_uncertain_keeps_observable_work(self):
        with tempfile.TemporaryDirectory() as temp:
            target = git_worktree(Path(temp) / "target")
            registry, backend, state = self._project(target)
            with self._patches(registry, backend, target), \
                    patch.object(herdr_backend, 'ACTIVATION_OBSERVATION_SECONDS', 0.01):
                candidate_id = await self._discover("research")
                state["prompt_error"] = herdr_backend.HerdrError("connection dropped", code="x1")
                res = await delegate_item("research", assignments=[{'agent_ref': candidate_id, 'task': "uncertain"}])
                self.assertFalse(res["ok"])
                self.assertEqual(res["error_type"], "WorkDispatchTransportUncertain")
                work_ref = res["work_ref"]
                self.assertTrue(work_ref.startswith("work-"))
                self.assertEqual(
                    set(res.keys()),
                    {"ok", "error_type", "error", "work_ref", "agent_ref", "submission_evidence", "index", "outcome"},
                )
                for banned in (
                    "state", "attribution", "result", "completion", "dispatch",
                    "project_ref", "handoff_id", "native_error_code",
                ):
                    self.assertNotIn(banned, res)
                work = server._WORK_REGISTRY[work_ref]
                self.assertEqual(work["state"], "running")
                self.assertIsNotNone(server._HANDOFF_REGISTRY[work["handoff_id"]]["watcher_task"])
                await server._HANDOFF_REGISTRY[work["handoff_id"]]["watcher_task"]
                settled = await finished_work(project_ref="research", work_ref=work_ref)
                self.assertTrue(settled["state"] in server.WORK_TERMINAL_STATES)
                self.assertEqual(settled["state"], "needs_attention")

    async def test_cancelled_delegate_dispatch_keeps_work_accessible(self):
        with tempfile.TemporaryDirectory() as temp:
            target = git_worktree(Path(temp) / "target")
            registry, backend, _state = self._project(target)
            with self._patches(registry, backend, target), \
                    patch.object(herdr_backend, 'ACTIVATION_OBSERVATION_SECONDS', 0.01):
                candidate_id = await self._discover("research")

                async def cancel_prompt(*_args, **_kwargs):
                    raise asyncio.CancelledError()

                with patch.object(backend, "prompt_manual_agent", side_effect=cancel_prompt):
                    with self.assertRaises(asyncio.CancelledError):
                        await delegate_item("research", assignments=[{'agent_ref': candidate_id, 'task': "cancelled mid-dispatch"}])
                self.assertEqual(len(server._WORK_REGISTRY), 1)
                work = next(iter(server._WORK_REGISTRY.values()))
                self.assertEqual(work["state"], "running")
                self.assertIsNotNone(work["handoff_id"])
                entry = server._HANDOFF_REGISTRY[work["handoff_id"]]
                self.assertIsNotNone(entry["watcher_task"])
                await entry["watcher_task"]
                self.assertEqual(work["state"], "needs_attention")
                settled = await finished_work(
                    project_ref="research", work_ref=work["work_ref"]
                )
                self.assertTrue(settled["state"] in server.WORK_TERMINAL_STATES)
                self.assertEqual(settled["state"], "needs_attention")
                # A caller-cancelled dispatch never auto-reprompts: no native
                # prompt and no AGY recovery screen read ever move.
                kinds = [c[:2] for c in _state["calls"]]
                self.assertEqual(kinds.count(("agent", "prompt")), 0)
                self.assertEqual(kinds.count(("agent", "read")), 0)

    async def test_work_project_mismatch_fails_closed(self):
        with tempfile.TemporaryDirectory() as temp:
            target = git_worktree(Path(temp) / "target")
            other = git_worktree(Path(temp) / "other")
            registry = WorkspaceRegistry(
                server.ROOT, json.dumps({"research": str(target), "other": str(other)})
            )
            backend, _state = manual_backend(target)
            with patch.object(server, "_WORKSPACE_REGISTRY", registry), patch.object(
                server, "_WORKSPACE_BACKENDS", {str(target): backend}
            ):
                candidate_id = await self._discover("research")
                with patch.object(backend, "watch_manual_agent_turn", _slow_watch):
                    res = await delegate_item("research", assignments=[{'agent_ref': candidate_id, 'task': "scoped"}])
                work_ref = res["work_ref"]
                mismatched = await finished_work(
                    project_ref="other", work_ref=work_ref
                )
                self.assertFalse(mismatched["ok"])
                self.assertEqual(mismatched["error_type"], "WorkRefProjectMismatch")
                self.assertEqual(
                    server._WORK_REGISTRY[work_ref]["state"], "running"
                )
                await self._cancel_watchers()

    async def test_work_first_delegate_promotion_settles_with_agent_turn_settled(self):
        with tempfile.TemporaryDirectory() as temp:
            target = git_worktree(Path(temp) / "target")
            registry, backend, state = self._project(target)
            # Candidate initially begins with agent_session=None (observed_non_owned pane_process continuity)
            state["agent"]["agent_session"] = None
            with self._patches(registry, backend, target):
                candidate_id = await self._discover("research")

                # Set up prompt handler so agent gains native session upon prompt execution
                def on_prompt(*_args):
                    state["agent"]["agent_session"] = {"kind": "id", "value": "promoted-work-session-99"}
                    state["agent"]["state_change_seq"] = (state["agent"].get("state_change_seq") or 1) + 1
                    state["agent"]["revision"] = (state["agent"].get("revision") or 1) + 1
                    return {"type": "agent_prompted", "agent": dict(state["agent"])}

                state["prompt_handler"] = on_prompt
                res = await delegate_item("research", assignments=[{'agent_ref': candidate_id, 'task': "first work turn"}])
                self.assertTrue(res["ok"], res)
                work_ref = res["work_ref"]

                work = server._WORK_REGISTRY[work_ref]
                hid = work["handoff_id"]
                self.assertIsNotNone(server._HANDOFF_REGISTRY[hid]["watcher_task"])
                await server._HANDOFF_REGISTRY[hid]["watcher_task"]

                settled = await finished_work(project_ref="research", work_ref=work_ref)
                self.assertTrue(settled["state"] in server.WORK_TERMINAL_STATES)
                self.assertEqual(settled["state"], "agent_turn_settled")
                self.assertEqual(settled["reason"], "state_transition_proven")
                self.assertEqual(
                    server._MANUAL_AGENT_CANDIDATES[candidate_id]["candidate"]["identity"]["agent_session"],
                    {"kind": "id", "value": "promoted-work-session-99"},
                )

    async def test_rediscovered_promoted_handle_returns_work_already_in_flight_and_prompt_count_stays_one(self):
        with tempfile.TemporaryDirectory() as temp:
            target = git_worktree(Path(temp) / "target")
            registry, backend, state = self._project(target)
            state["agent"]["agent_session"] = None
            with self._patches(registry, backend, target):
                candidate_id_1 = await self._discover("research")

                async def _never_settle(*_args, **_kwargs):
                    await asyncio.sleep(3600)

                with patch.object(backend, "watch_manual_agent_turn", _never_settle):
                    res1 = await delegate_item("research", assignments=[{'agent_ref': candidate_id_1, 'task': "first task"}])
                    self.assertTrue(res1["ok"], res1)
                    work_ref_1 = res1["work_ref"]
                    self.assertEqual(server._WORK_REGISTRY[work_ref_1]["state"], "running")

                    # Agent gains native session in Herdr during execution
                    state["agent"]["agent_session"] = {"kind": "id", "value": "promoted-native-session-1"}

                    # Mid-turn rediscovery preserves the stable handle (zero handle churn)
                    candidate_id_2 = await self._discover("research")
                    self.assertEqual(candidate_id_1, candidate_id_2)

                    # Second delegate to candidate_id_2 must return WorkAlreadyInFlight with original work_ref
                    res2 = await delegate_item("research", assignments=[{'agent_ref': candidate_id_2, 'task': "second task"}])
                    self.assertFalse(res2["ok"])
                    self.assertEqual(res2["error_type"], "WorkAlreadyInFlight")
                    self.assertEqual(res2["existing_work_ref"], work_ref_1)

                    # Prompt count stays 1 (no second prompt attempted)
                    prompts = [c for c in state["calls"] if c[:2] == ("agent", "prompt")]
                    self.assertEqual(len(prompts), 1)

                    await self._cancel_watchers()

    async def test_session_identity_change_blocks_second_work_dispatch_without_second_prompt(self):
        with tempfile.TemporaryDirectory() as temp:
            target = git_worktree(Path(temp) / "target")
            registry, backend, state = self._project(target)
            state["agent"]["agent_session"] = {"kind": "id", "value": "session-A"}
            with self._patches(registry, backend, target):
                candidate_id_1 = await self._discover("research")

                async def _never_settle(*_args, **_kwargs):
                    await asyncio.sleep(3600)

                with patch.object(backend, "watch_manual_agent_turn", _never_settle):
                    res1 = await delegate_item("research", assignments=[{'agent_ref': candidate_id_1, 'task': "first task"}])
                    self.assertTrue(res1["ok"], res1)
                    work_ref_1 = res1["work_ref"]

                    # Session in Herdr changes to session-B during execution
                    state["agent"]["agent_session"] = {"kind": "id", "value": "session-B"}

                    # Mid-turn rediscovery preserves the stable handle (zero handle churn)
                    candidate_id_2 = await self._discover("research")
                    self.assertEqual(candidate_id_1, candidate_id_2)

                    # Attempt second delegate with new handle
                    res2 = await delegate_item("research", assignments=[{'agent_ref': candidate_id_2, 'task': "second task"}])
                    self.assertFalse(res2["ok"])
                    self.assertEqual(res2["error_type"], "WorkAlreadyInFlight")
                    self.assertEqual(res2["existing_work_ref"], work_ref_1)

                    # Prompt count stays 1
                    prompts = [c for c in state["calls"] if c[:2] == ("agent", "prompt")]
                    self.assertEqual(len(prompts), 1)

                    await self._cancel_watchers()

    async def test_work_transient_observation_maps_to_needs_attention(self):
        with tempfile.TemporaryDirectory() as temp:
            target = git_worktree(Path(temp) / "target")
            registry, backend, state = self._project(target)
            snapshot_calls = 0
            orig_agent = dict(state["agent"])

            def snapshot_handler(*args):
                nonlocal snapshot_calls
                snapshot_calls += 1
                if snapshot_calls <= 3:
                    return {
                        "snapshot": {
                            "agents": [orig_agent],
                            "panes": state.get("panes", [{"workspace_id": state["workspace_id"], "pane_id": "w-manual:p1", "cwd": str(target), "terminal_id": "term-w-manual:p1"}]),
                            "tabs": state.get("tabs", []),
                            "workspaces": [{"workspace_id": state["workspace_id"], "label": "GPT Web Bridge"}],
                        }
                    }
                # Watcher encounters transient empty snapshot
                return {
                    "snapshot": {
                        "agents": [],
                        "panes": state.get("panes", [{"workspace_id": state["workspace_id"], "pane_id": "w-manual:p1", "cwd": str(target), "terminal_id": "term-w-manual:p1"}]),
                        "tabs": state.get("tabs", []),
                        "workspaces": [{"workspace_id": state["workspace_id"], "label": "GPT Web Bridge"}],
                    }
                }

            state["snapshot_handler"] = snapshot_handler
            state["text"] = "TERMINAL_BODY_do_not_log"
            with patch.object(
                herdr_backend, "TRANSIENT_OBSERVATION_RETRY_INTERVAL_SECONDS", 0.0
            ), self._patches(registry, backend, target), self.assertLogs(
                "mcp.bridge.work_terminal", level="INFO"
            ) as captured:
                candidate_id = await self._discover("research")
                orig_stored_cand = dict(server._MANUAL_AGENT_CANDIDATES[candidate_id]["candidate"])

                delegate_res = await delegate_item("research", assignments=[{'agent_ref': candidate_id, 'task': "transient observation Work test SECRET_TASK_BODY"}])
                self.assertTrue(delegate_res["ok"])
                work_ref = delegate_res["work_ref"]
                hid = server._WORK_REGISTRY[work_ref]["handoff_id"]
                watcher = server._HANDOFF_REGISTRY[hid]["watcher_task"]
                await watcher

                settled = await finished_work(
                    project_ref="research",
                    work_ref=work_ref,
                )
                self.assertTrue(settled["state"] in server.WORK_TERMINAL_STATES)
                self.assertEqual(settled["state"], "needs_attention")
                self.assertEqual(settled["reason"], "observation_unavailable")
                # Candidate record was NOT rebound
                stored = server._MANUAL_AGENT_CANDIDATES[candidate_id]["candidate"]
                self.assertEqual(stored["candidate_key"], orig_stored_cand["candidate_key"])
                # Prompt count to Herdr stays 1
                prompts = [c for c in state["calls"] if c[:2] == ("agent", "prompt")]
                self.assertEqual(len(prompts), 1)
                self.assertEqual(
                    [c for c in state["calls"] if c[:2] == ("agent", "send-keys")], [])
                self.assertEqual(snapshot_calls, 6)
                self.assertNotIn("watcher_error_code", settled)
                self.assertEqual(len(captured.records), 1)
                payload = json.loads(captured.records[0].getMessage())
                self.assertEqual(payload["event"], "bridge.work_terminal_latch")
                self.assertEqual(payload["state"], "needs_attention")
                self.assertEqual(payload["reason"], "observation_unavailable")
                self.assertEqual(
                    payload["watcher_error_code"],
                    "manual_candidate_observation_unavailable",
                )
                self.assertNotIn("SECRET_TASK_BODY", captured.records[0].getMessage())
                self.assertNotIn("TERMINAL_BODY_do_not_log", captured.records[0].getMessage())

    async def test_work_terminal_latch_journal_for_ordinary_settlement_is_bounded(self):
        with tempfile.TemporaryDirectory() as temp:
            target = git_worktree(Path(temp) / "target")
            registry, backend, state = self._project(target)
            state["text"] = "TERMINAL_BODY_do_not_log"
            with self._patches(registry, backend, target):
                candidate_id = await self._discover("research")
                with patch.object(backend, "watch_manual_agent_turn", _slow_watch):
                    delegated = await delegate_item("research", assignments=[{'agent_ref': candidate_id, 'task': "ordinary settlement SECRET_TASK_BODY"}])
                self.assertTrue(delegated["ok"], delegated)
                work_ref = delegated["work_ref"]
                hid = server._WORK_REGISTRY[work_ref]["handoff_id"]
                with self.assertLogs("mcp.bridge.work_terminal", level="INFO") as captured:
                    server._update_handoff_entry(
                        hid,
                        state="done",
                        reason="state_transition_proven",
                        herdr_status="idle",
                        post_seq=2,
                        post_rev=2,
                    )
                with self.assertNoLogs("mcp.bridge.work_terminal", level="INFO"):
                    server._update_handoff_entry(
                        hid,
                        state="needs_attention",
                        reason="agent_blocked",
                        herdr_status="blocked",
                        watcher_error_code="manual_candidate_read_unavailable",
                    )
                self.assertEqual(len(captured.records), 1)
                payload = json.loads(captured.records[0].getMessage())
                self.assertEqual(set(payload), {
                    "elapsed_ms", "event", "handoff_id", "herdr_status", "reason",
                    "state", "watcher_error_code", "work_ref",
                })
                self.assertEqual(payload["event"], "bridge.work_terminal_latch")
                self.assertEqual(payload["work_ref"], work_ref)
                self.assertEqual(payload["handoff_id"], hid)
                self.assertEqual(payload["state"], "agent_turn_settled")
                self.assertEqual(payload["reason"], "state_transition_proven")
                self.assertEqual(payload["herdr_status"], "idle")
                self.assertIsNone(payload["watcher_error_code"])
                self.assertIsInstance(payload["elapsed_ms"], int)
                self.assertGreaterEqual(payload["elapsed_ms"], 0)
                blob = captured.records[0].getMessage()
                self.assertNotIn("SECRET_TASK_BODY", blob)
                self.assertNotIn("TERMINAL_BODY_do_not_log", blob)
                self.assertEqual(server._WORK_REGISTRY[work_ref]["state"], "agent_turn_settled")
                settled = await finished_work(project_ref="research", work_ref=work_ref)
                self.assertEqual(settled["state"], "agent_turn_settled")
                self.assertNotIn("watcher_error_code", settled)
                await self._cancel_watchers()

    async def test_work_execution_replacement_still_latches_continuity_lost(self):
        with tempfile.TemporaryDirectory() as temp:
            target = git_worktree(Path(temp) / "target")
            registry, backend, state = self._project(target)
            snapshot_calls = 0
            original = dict(state["agent"])
            replacement = {**original, "_pid": 98765, "state_change_seq": 2}

            def snapshot_handler(*_args):
                nonlocal snapshot_calls
                snapshot_calls += 1
                live = original if snapshot_calls <= 3 else replacement
                state["agent"] = live
                return {
                    "snapshot": {
                        "agents": [live],
                        "panes": state["panes"],
                        "tabs": state["tabs"],
                        "workspaces": [{"workspace_id": state["workspace_id"], "label": "GPT Web Bridge"}],
                    }
                }

            state["snapshot_handler"] = snapshot_handler
            with self._patches(registry, backend, target):
                candidate_id = await self._discover("research")
                delegated = await delegate_item("research", assignments=[{'agent_ref': candidate_id, 'task': "replacement after dispatch"}])
                self.assertTrue(delegated["ok"], delegated)
                work = server._WORK_REGISTRY[delegated["work_ref"]]
                await server._HANDOFF_REGISTRY[work["handoff_id"]]["watcher_task"]

                settled = await finished_work(
                    project_ref="research", work_ref=delegated["work_ref"]
                )

                self.assertTrue(settled["state"] in server.WORK_TERMINAL_STATES)
                self.assertEqual(settled["state"], "continuity_lost")

    async def test_process_replacement_does_not_alias_execution_identity(self):
        with tempfile.TemporaryDirectory() as temp:
            target = git_worktree(Path(temp) / "target")
            registry, backend, state = self._project(target)
            with self._patches(registry, backend, target):
                candidate_id_1 = await self._discover("research")

                async def _never_settle(*_args, **_kwargs):
                    await asyncio.sleep(3600)

                with patch.object(backend, "watch_manual_agent_turn", _never_settle):
                    res1 = await delegate_item("research", assignments=[{'agent_ref': candidate_id_1, 'task': "first task"}])
                    self.assertTrue(res1["ok"], res1)

                    # Process replacement: PID changes so foreground process fingerprint changes
                    state["agent"]["_pid"] = 98765
                    state["process_info"] = {
                        "pane_id": state["agent"]["pane_id"],
                        "foreground_process_group_id": 98765,
                        "foreground_cwd": state["agent"]["cwd"],
                        "foreground_processes": [{
                            "pid": 98765,
                            "argv": ["agy", "--replacement"],
                            "cwd": state["agent"]["cwd"],
                        }],
                    }

                    candidate_id_2 = await self._discover("research")
                    self.assertEqual(candidate_id_1, candidate_id_2)

                    cand2 = server._MANUAL_AGENT_CANDIDATES[candidate_id_2]["candidate"]
                    exec1 = server._WORK_REGISTRY[res1["work_ref"]]["execution_identity"]
                    exec2 = server._execution_identity(str(target), cand2)
                    self.assertIsNotNone(exec1)
                    self.assertIsNotNone(exec2)
                    self.assertNotEqual(exec1, exec2)

                    await self._cancel_watchers()

    async def test_unavailable_process_evidence_does_not_claim_equivalence(self):
        with tempfile.TemporaryDirectory() as temp:
            target = git_worktree(Path(temp) / "target")
            registry, backend, state = self._project(target)
            state["process_info"] = {
                "pane_id": state["agent"]["pane_id"],
                "foreground_process_group_id": None,
                "foreground_processes": [],
            }
            with self._patches(registry, backend, target):
                cand_id = await self._discover("research")
                cand = server._MANUAL_AGENT_CANDIDATES[cand_id]["candidate"]
                self.assertFalse(cand["process"]["available"])

                exec_id = server._execution_identity(str(target), cand)
                self.assertIsNone(exec_id)

    def test_execution_identity_table_every_static_process_field_affects_identity_session_does_not(self):
        workspace_root = "/path/to/workspace"
        base_candidate = {
            "identity": {
                "agent_kind": "agy",
                "agent_name": "worker-1",
                "workspace_id": "w1",
                "tab_id": "w1:t1",
                "pane_id": "w1:p1",
                "terminal_id": "term-1",
                "cwd": "/path/to/workspace",
                "foreground_cwd": "/path/to/workspace",
                "agent_session": None,
            },
            "process": {
                "available": True,
                "fingerprint": "fingerprint-alpha",
            },
        }

        base_id = server._execution_identity(workspace_root, base_candidate)
        self.assertIsNotNone(base_id)

        # 1. agent_session does NOT affect execution identity
        for sess in (
            {"kind": "id", "value": "sess-123"},
            {"kind": "id", "value": "sess-456"},
            {"kind": "url", "value": "http://example.com"},
        ):
            cand_sess = json.loads(json.dumps(base_candidate))
            cand_sess["identity"]["agent_session"] = sess
            self.assertEqual(
                server._execution_identity(workspace_root, cand_sess),
                base_id,
                f"agent_session {sess} should not change execution identity",
            )

        # Raw optional CWD observations are not the normalized selected checkout.
        for foreground in (None, workspace_root):
            candidate = json.loads(json.dumps(base_candidate))
            candidate["identity"]["foreground_cwd"] = foreground
            self.assertEqual(server._execution_identity(workspace_root, candidate), base_id)
        candidate["identity"].pop("foreground_cwd")
        self.assertEqual(server._execution_identity(workspace_root, candidate), base_id)

        # 2. Every static identity field DOES affect execution identity
        field_mutations = [
            ("workspace_scope", "/different/workspace", base_candidate),
            ("agent_kind", workspace_root, {"identity": {**base_candidate["identity"], "agent_kind": "pi"}, "process": base_candidate["process"]}),
            ("agent_name", workspace_root, {"identity": {**base_candidate["identity"], "agent_name": "other-worker"}, "process": base_candidate["process"]}),
            ("agent_name_none", workspace_root, {"identity": {**base_candidate["identity"], "agent_name": None}, "process": base_candidate["process"]}),
            ("workspace_id", workspace_root, {"identity": {**base_candidate["identity"], "workspace_id": "w2"}, "process": base_candidate["process"]}),
            ("tab_id", workspace_root, {"identity": {**base_candidate["identity"], "tab_id": "w1:t2"}, "process": base_candidate["process"]}),
            ("pane_id", workspace_root, {"identity": {**base_candidate["identity"], "pane_id": "w1:p2"}, "process": base_candidate["process"]}),
            ("terminal_id", workspace_root, {"identity": {**base_candidate["identity"], "terminal_id": "term-2"}, "process": base_candidate["process"]}),
            ("cwd", workspace_root, {"identity": {**base_candidate["identity"], "cwd": "/sub/dir"}, "process": base_candidate["process"]}),
            ("process_fingerprint", workspace_root, {"identity": base_candidate["identity"], "process": {"available": True, "fingerprint": "fingerprint-beta"}}),
            ("process_fingerprint_dict", workspace_root, {"identity": base_candidate["identity"], "process": {"available": True, "fingerprint": {"leader": 1}}}),
        ]

        for name, root, cand in field_mutations:
            new_id = server._execution_identity(root, cand)
            self.assertIsNotNone(new_id, f"Mutation {name} should produce a valid identity")
            self.assertNotEqual(new_id, base_id, f"Mutation {name} must change execution identity")

        # 3. Missing or unavailable process evidence yields None (no equivalence)
        invalid_cases = [
            ("process_unavailable", workspace_root, {"identity": base_candidate["identity"], "process": {"available": False, "fingerprint": "fp"}}),
            ("process_missing", workspace_root, {"identity": base_candidate["identity"]}),
            ("fingerprint_missing", workspace_root, {"identity": base_candidate["identity"], "process": {"available": True, "fingerprint": None}}),
            ("fingerprint_empty", workspace_root, {"identity": base_candidate["identity"], "process": {"available": True, "fingerprint": ""}}),
            ("fingerprint_empty_dict", workspace_root, {"identity": base_candidate["identity"], "process": {"available": True, "fingerprint": {}}}),
            ("workspace_root_none", None, base_candidate),
            ("workspace_root_empty", "", base_candidate),
            ("candidate_none", workspace_root, None),
            ("identity_missing", workspace_root, {"process": base_candidate["process"]}),
        ]
        for name, root, cand in invalid_cases:
            self.assertIsNone(server._execution_identity(root, cand), f"Invalid case {name} must return None")





if __name__ == "__main__":
    unittest.main()
