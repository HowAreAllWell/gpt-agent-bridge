"""Stage-one removal, shared generic bootstrap, and honest health regression tests."""

import ast
import asyncio
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

os.environ.setdefault("BRIDGE_PATH_TOKEN", "test-token-abcdefghijklmnopqrstuvwxyz-012345")

from gpt_agent_bridge import server
from tests.test_manual_agents import agy_agent, manual_backend
from tests.test_work_surface import git_repo_with_two_linked_worktrees
from gpt_agent_bridge.workspace_context import WorkspaceRegistry, WorkspaceRegistryStore


RETAINED = {
    "context", "delegate",
    "read", "search", "diff", "agent_terminal_read",
    "project_register", "project_initialize", "bridge_health", "bridge_overview", "current_state_update",
    "list_entries", "inspect_file", "commit_prepare", "project_text_edit", "commit", "work_report", "prepare_file_attachment",
}
RETIRED = {
    "wait_work_watch", "claim_work_watch", "record_work_watch_send_outcome",
    "view_image", "agent_probe", "manual_agent_allocate", "manual_agent_probe", "manual_agent_start",
    "manual_agent_create", "manual_agent_list", "manual_agent_cleanup",
    "manual_agent_group_cleanup", "manual_agent_read", "manual_agent_prompt",
    "agent_discover", "agent_instruct", "agent_handoff_join", "agent_create",
    "agent_allocate", "agent_activate", "agent_release", "project_document",
    "workspace_diff", "workspace_read", "workspace_search", "workspace_apply_patch",
    "workspace_exec", "agent_start", "agent_continue", "pi_run", "pi_resume",
    "pi_start", "pi_recover_abort", "pi_cleanup", "agent_status", "agent_wait",
    "agent_events", "agent_inspect", "agent_reconcile", "agent_cleanup", "agent_cancel",
    "mrtr_probe", "sse_hold_probe", "codex_run",
}


class StageOneSurfaceTests(unittest.IsolatedAsyncioTestCase):
    async def test_retired_endpoints_are_absent_from_registry_and_module(self):
        self.assertEqual(len(RETIRED), 41 + 3)
        self.assertEqual({t.name for t in await server.mcp.list_tools()}, RETAINED)
        self.assertEqual({t.name for t in server.mcp._tool_manager.list_tools()}, RETAINED)
        for name in RETIRED:
            with self.subTest(name=name):
                self.assertIsNone(server.mcp._tool_manager.get_tool(name))
                self.assertFalse(hasattr(server, name))
        self.assertNotIn("list_tools", server._BridgeMCPServer.__dict__)
        self.assertFalse(hasattr(server, "BRIDGE_TOOL_VISIBILITY_META_KEY"))

    async def test_exact_name_call_cannot_reach_retired_endpoint(self):
        for name in RETIRED:
            with self.subTest(name=name):
                with self.assertRaises(Exception) as error:
                    await server.mcp._tool_manager.call_tool(name, {}, context=None)
                self.assertIn(name, str(error.exception))

    async def test_health_reports_actual_surface_and_observed_connectivity(self):
        call = AsyncMock(return_value={"snapshot": {"agents": []}})
        with patch.object(server.HERDR, "_call", call):
            result = await server.bridge_health()
        call.assert_awaited_once_with("api", "snapshot", timeout=10)
        self.assertEqual(result["herdr"]["status"], "reachable")
        self.assertEqual(result["tool_surface"], {"registered_count": len(RETAINED), "names": sorted(RETAINED)})
        self.assertEqual(set(result), {"ok", "bridge", "runtime", "herdr", "tool_surface"})
        self.assertEqual(result["runtime"]["pid"], os.getpid())
        self.assertEqual(result["runtime"]["started_at"], server.BRIDGE_STARTED_AT)

    async def test_health_does_not_claim_connectivity_on_failure_or_malformed_response(self):
        for call in (AsyncMock(side_effect=TimeoutError("unavailable")),
                     AsyncMock(return_value={"snapshot": {}})):
            with patch.object(server.HERDR, "_call", call):
                result = await server.bridge_health()
            self.assertTrue(result["ok"])  # Bridge responded, independently of Herdr.
            self.assertEqual(result["herdr"]["status"], "unavailable")
            self.assertIn("error", result["herdr"])


class BootstrapObservationTests(unittest.IsolatedAsyncioTestCase):
    async def test_four_preplaced_agents_match_context_and_parameterless_bootstrap(self):
        with tempfile.TemporaryDirectory() as temp:
            root, first, second = git_repo_with_two_linked_worktrees(Path(temp))
            third = Path(temp) / "execution-space" / "agent-three"
            subprocess.run(["git", "worktree", "add", "--quiet", "-b", "agent-three",
                            str(third), "HEAD"], cwd=root, check=True)
            registry = WorkspaceRegistry(root, json.dumps({"bridge": str(root)}))
            backend, state = manual_backend(root)
            for index, cwd in enumerate((first, second, third), start=2):
                agent = agy_agent(root, pid=2000 + index)
                agent.update(tab_id=f"w-manual:t{index}", pane_id=f"w-manual:p{index}",
                             terminal_id=f"term-{index}", foreground_cwd=str(cwd))
                # A lagging reported root remains valid in the same common Git.
                state["created_agents"].append(agent)
                state["panes"].append({k: agent[k] for k in ("workspace_id", "tab_id", "pane_id", "terminal_id", "cwd")})
            with patch.object(server, "ROOT", root), patch.object(server, "HERDR", backend), \
                 patch.object(server, "_WORKSPACE_REGISTRY", registry), \
                 patch.object(server, "_WORKSPACE_BACKENDS", {str(root): backend}), \
                 patch.object(server, "_MANUAL_AGENT_CANDIDATES", {}), \
                 patch.object(server, "_deployment_snapshot", return_value={"main_pid": os.getpid()}):
                context = await server.context("bridge")
                named = await server.bridge_overview("bridge")
                default = await server.bridge_overview()
            self.assertEqual(context["agent_count"], 4)
            self.assertEqual(named["agents"], context["agents"])
            self.assertEqual(default["observation"]["candidate_count"], 4)
            self.assertEqual(default["observation"]["health"], "healthy")
            self.assertEqual(named["observation"]["health"], "healthy")
            for agent in default["agents"]:
                self.assertEqual(set(agent), {"handle", "kind", "name", "status", "hint", "workspace_id", "checkout"})
            self.assertEqual({a["hint"] for a in default["agents"]},
                             {a["hint"] for a in context["agents"]})
            self.assertIn("head", default["repository"])
            self.assertEqual(default["repository"]["status_short"], "")
            self.assertFalse(default["repository"]["dirty"])
            self.assertTrue(default["runtime"]["same_process_as_deployed_main"])
            self.assertIn("documents", default["project_state"])
            self.assertNotIn("documents", named["project_state"])
            self.assertTrue(all(call[:2] in {("api", "snapshot"), ("pane", "process-info")}
                                for call in state["calls"]))

    async def test_discovery_failure_and_partial_coverage_are_honest_in_both_views(self):
        tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(tempdir.cleanup)
        temp = tempdir.name
        registry = WorkspaceRegistry(server.ROOT, json.dumps({"bridge": str(server.ROOT)}), store=WorkspaceRegistryStore(Path(temp) / "registry.json"))
        for discovery, expected in (
            ({"ok": False, "error": "transport unavailable"}, "unavailable"),
            ({"ok": True, "candidates": [], "skipped_count": 1, "candidates_truncated": False,
              "coverage_counts": {"out_of_project": 0, "invalid_or_unavailable": 1, "truncated": 0}}, "partial"),
            ({"ok": True, "candidates": [], "skipped_count": 0, "candidates_truncated": True,
              "coverage_counts": {"out_of_project": 0, "invalid_or_unavailable": 0, "truncated": 1}}, "partial"),
        ):
            with self.subTest(expected=expected), \
                 patch.object(server, "_WORKSPACE_REGISTRY", registry), \
                 patch.object(server, "_discover_project_candidates", AsyncMock(return_value=discovery)), \
                 patch.object(server, "_deployment_snapshot", return_value={}):
                context = await server.context("bridge")
                snapshot = await server.bridge_overview("bridge")
            self.assertFalse(context["agents_complete"])
            self.assertFalse(snapshot["observation"]["complete"])
            self.assertEqual(snapshot["observation"]["health"], expected)
            if expected == "unavailable":
                self.assertIn("agents_error", context)
                self.assertIn("error", snapshot["observation"])

    async def test_unknown_project_fails_without_discovery_or_default_fallback(self):
        with patch.object(server, "_discover_project_candidates", AsyncMock()) as discovery:
            result = await server.bridge_overview("stage1-unregistered")
        self.assertFalse(result["ok"])
        self.assertEqual(result["error_type"], "WorkspaceRefUnauthorized")
        discovery.assert_not_awaited()

    async def test_malformed_discovery_cannot_report_healthy_empty_roster(self):
        for result, health in (
            (None, "unavailable"),
            ({"candidates": None}, "unavailable"),
            ({"candidates": [], "skipped_count": -1}, "unavailable"),
            ({"candidates": [None], "skipped_count": 0, "candidates_truncated": False,
              "coverage_counts": {"out_of_project": 0, "invalid_or_unavailable": 0, "truncated": 0}}, "partial"),
        ):
            with self.subTest(result=result), \
                 patch.object(server.HERDR, "manual_agent_candidates", AsyncMock(return_value=result)), \
                 patch.object(server, "_deployment_snapshot", return_value={}):
                snapshot = await server.bridge_overview()
            self.assertEqual(snapshot["observation"]["health"], health)
            self.assertFalse(snapshot["observation"]["complete"])
