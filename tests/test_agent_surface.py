import json
import os
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

os.environ.setdefault("BRIDGE_PATH_TOKEN", "test-token-abcdefghijklmnopqrstuvwxyz-012345")

from gpt_agent_bridge import server


class AgentSurfaceTests(unittest.IsolatedAsyncioTestCase):
    async def test_agent_observe_validates_project_and_agent_ref_and_dispatches(self):
        handle = "b" * 32
        record = {"workspace_root": "/repo", "workspace_ref": "research"}
        workspace = SimpleNamespace(root=Path("/repo"), workspace_ref="research")
        candidate_result = {
            "ok": True,
            "candidate": {"herdr_status": "idle"},
            "read": {"text": "output", "chars": 6, "truncated": False, "source": "pane_terminal_output", "limit": 77},
            "attribution": "unattributed_current_terminal_output",
        }

        with patch.dict(server._MANUAL_AGENT_CANDIDATES, {handle: record}, clear=True), \
             patch.object(server, "_required_project_context", return_value=workspace), \
             patch.object(server, "_read_agent_candidate", AsyncMock(return_value=candidate_result)) as read:
            res = await server.agent_terminal_read(project_ref="research", agent_ref=handle, limit=77)
            self.assertTrue(res["ok"])
            self.assertEqual(res["agent_ref"], handle)
            self.assertEqual(res["project_ref"], "research")
            self.assertEqual(res["status"], "idle")
            self.assertEqual(res["read"]["text"], "output")
            self.assertEqual(res["attribution"], "unattributed_current_terminal_output")
            read.assert_awaited_once_with(candidate_id=handle, limit=77)

        # Missing project_ref
        res = await server.agent_terminal_read(project_ref="", agent_ref=handle)
        self.assertFalse(res["ok"])
        self.assertEqual(res["error_type"], "ProjectRefRequired")

        # Unknown agent_ref
        with patch.dict(server._MANUAL_AGENT_CANDIDATES, {}, clear=True), \
             patch.object(server, "_required_project_context", return_value=workspace):
            res = await server.agent_terminal_read(project_ref="research", agent_ref="unknown-handle")
            self.assertFalse(res["ok"])
            self.assertEqual(res["error_type"], "UnknownAgentRef")

        # Project mismatch
        mismatched_record = {"workspace_root": "/other-repo", "workspace_ref": "other"}
        with patch.dict(server._MANUAL_AGENT_CANDIDATES, {handle: mismatched_record}, clear=True), \
             patch.object(server, "_required_project_context", return_value=workspace):
            res = await server.agent_terminal_read(project_ref="research", agent_ref=handle)
            self.assertFalse(res["ok"])
            self.assertEqual(res["error_type"], "AgentRefProjectMismatch")

        # Invalid limit
        with patch.dict(server._MANUAL_AGENT_CANDIDATES, {handle: record}, clear=True), \
             patch.object(server, "_required_project_context", return_value=workspace):
            with self.assertRaises(ValueError):
                await server.agent_terminal_read(project_ref="research", agent_ref=handle, limit=999)

    async def test_agent_observe_public_docstring_omits_hidden_tool_names(self):
        doc = server.agent_terminal_read.__doc__ or ""
        self.assertNotIn("manual_agent_probe", doc)
        self.assertNotIn("agent_probe", doc)
        self.assertNotIn("manual_agent_", doc)
        self.assertNotIn("maintenance-hidden", doc)

    async def test_agent_observe_docstring_boundaries_no_progress_polling(self):
        doc = " ".join((server.agent_terminal_read.__doc__ or "").split())
        self.assertIn("not a progress, status or liveness polling channel", doc)
        self.assertIn("unattributed", doc)
        self.assertIn("without sending input", doc)
        self.assertIn("does not establish task success", doc)
        self.assertNotIn("watch_decision", doc)
        self.assertNotIn("work_report", doc)

    async def test_agent_observe_public_success_shape_pins_exact_keys_and_excludes_legacy_ontology(self):
        handle = "c" * 32
        record = {"workspace_root": "/repo", "workspace_ref": "research"}
        workspace = SimpleNamespace(root=Path("/repo"), workspace_ref="research")
        internal_read_result = {
            "ok": True,
            "candidate_id": handle,
            "candidate": {
                "candidate_id": handle,
                "agent_kind": "agy",
                "herdr_status": "working",
                "workspace_id": "w1",
                "tab_id": "t1",
                "pane_id": "p1",
                "terminal_id": "term1",
                "agent_session": {"kind": "id", "value": "s1"},
                "foreground_process": {"pid": 1234},
                "ownership": "observed_non_owned",
                "lifecycle": {"authority": "none"},
                "lifecycle_authority": {"authority": "none"},
            },
            "read": {
                "text": "agent output text\n",
                "chars": 18,
                "truncated": False,
                "source": "terminal_output",
                "limit": 120,
            },
            "attribution": "unattributed_current_terminal_output",
        }
        with patch.dict(server._MANUAL_AGENT_CANDIDATES, {handle: record}, clear=True), \
             patch.object(server, "_required_project_context", return_value=workspace), \
             patch.object(server, "_read_agent_candidate", AsyncMock(return_value=internal_read_result)):
            res = await server.agent_terminal_read(project_ref="research", agent_ref=handle)
            self.assertTrue(res["ok"])
            self.assertEqual(
                set(res.keys()),
                {"ok", "project_ref", "agent_ref", "status", "read", "attribution"},
            )
            self.assertEqual(res["project_ref"], "research")
            self.assertEqual(res["agent_ref"], handle)
            self.assertEqual(res["status"], "working")
            self.assertEqual(
                set(res["read"].keys()),
                {"text", "chars", "truncated", "source", "limit"},
            )
            self.assertEqual(res["read"]["text"], "agent output text\n")
            self.assertEqual(res["attribution"], "unattributed_current_terminal_output")

            forbidden_fields = [
                "candidate_id",
                "candidate",
                "workspace_id",
                "tab_id",
                "pane_id",
                "terminal_id",
                "managed",
                "managed_resource_id",
                "lifecycle",
                "lifecycle_authority",
                "session",
                "agent_session",
                "process",
                "foreground_process",
                "ownership",
                "interaction",
                "interaction_authority",
            ]
            for field in forbidden_fields:
                self.assertNotIn(field, res)

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

    async def test_agent_observe_public_error_shape_pins_keys_and_excludes_legacy_ontology(self):
        handle = "c" * 32
        record = {"workspace_root": "/repo", "workspace_ref": "research"}
        workspace = SimpleNamespace(root=Path("/repo"), workspace_ref="research")
        internal_err_result = {
            "ok": False,
            "candidate_id": handle,
            "error_type": "ManualCandidateObservationUnavailable",
            "reason": "observation_unavailable",
            "error": "simulated observation unavailable",
        }
        with patch.dict(server._MANUAL_AGENT_CANDIDATES, {handle: record}, clear=True), \
             patch.object(server, "_required_project_context", return_value=workspace), \
             patch.object(server, "_read_agent_candidate", AsyncMock(return_value=internal_err_result)):
            res = await server.agent_terminal_read(project_ref="research", agent_ref=handle)
            self.assertFalse(res["ok"])
            self.assertEqual(
                set(res.keys()),
                {"ok", "project_ref", "agent_ref", "error_type", "reason", "error"},
            )
            self.assertEqual(res["project_ref"], "research")
            self.assertEqual(res["agent_ref"], handle)
            self.assertEqual(res["error_type"], "AgentObservationUnavailable")
            self.assertFalse(res["error_type"].startswith("ManualCandidate"))
            self.assertEqual(res["reason"], "observation_unavailable")
            self.assertEqual(res["error"], "agent output is temporarily unavailable from the execution environment")
            self.assertNotIn("candidate_id", res)
            self.assertNotIn("candidate", res)
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

    async def test_agent_observe_public_error_type_mapping_pins_principal_names(self):
        handle = "c" * 32
        record = {"workspace_root": "/repo", "workspace_ref": "research"}
        workspace = SimpleNamespace(root=Path("/repo"), workspace_ref="research")
        mappings = [
            ("UnknownManualAgentCandidate", "UnknownAgentRef", "agent_not_found", "agent_ref is unknown to this Bridge runtime or was lost after restart"),
            ("ManualCandidateNotFound", "UnknownAgentRef", "agent_not_found", "agent_ref is unknown to this Bridge runtime or was lost after restart"),
            ("ManualCandidateContinuityLost", "AgentContinuityLost", "continuity_lost", "agent execution continuity was lost due to an execution contradiction"),
            ("ManualCandidateObservationUnavailable", "AgentObservationUnavailable", "observation_unavailable", "agent output is temporarily unavailable from the execution environment"),
            ("ManualCandidateRevalidationUncertain", "AgentObservationUncertain", "observation_uncertain", "agent execution state could not be verified with certainty"),
            ("ManualCandidateWorkspaceUnauthorized", "ProjectRefUnauthorized", "workspace_unauthorized", "project workspace authorization is invalid or expired"),
        ]
        for internal_type, expected_public_type, expected_reason, expected_error in mappings:
            with self.subTest(internal=internal_type):
                internal_err = {
                    "ok": False,
                    "candidate_id": handle,
                    "error_type": internal_type,
                    "reason": "some_internal_reason",
                    "error": "some internal error with candidate, pane w:1",
                }
                with patch.dict(server._MANUAL_AGENT_CANDIDATES, {handle: record}, clear=True), \
                     patch.object(server, "_required_project_context", return_value=workspace), \
                     patch.object(server, "_read_agent_candidate", AsyncMock(return_value=internal_err)):
                    res = await server.agent_terminal_read(project_ref="research", agent_ref=handle)
                    self.assertFalse(res["ok"])
                    self.assertEqual(res["error_type"], expected_public_type)
                    self.assertFalse(res["error_type"].startswith("ManualCandidate"))
                    self.assertEqual(res["agent_ref"], handle)
                    self.assertEqual(res["project_ref"], "research")
                    self.assertEqual(res["reason"], expected_reason)
                    self.assertEqual(res["error"], expected_error)
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

    async def test_agent_observe_realistic_continuity_lost_excludes_legacy_ontology(self):
        handle = "c" * 32
        record = {"workspace_root": "/repo", "workspace_ref": "research"}
        workspace = SimpleNamespace(root=Path("/repo"), workspace_ref="research")
        realistic_internal_err = {
            "ok": False,
            "candidate_id": handle,
            "error_type": "ManualCandidateContinuityLost",
            "reason": "candidate_continuity_lost",
            "error": "foreground process replacement detected on pane w-manual:p1: pid changed from 1234 to 5678 in session s-123",
        }
        with patch.dict(server._MANUAL_AGENT_CANDIDATES, {handle: record}, clear=True), \
             patch.object(server, "_required_project_context", return_value=workspace), \
             patch.object(server, "_read_agent_candidate", AsyncMock(return_value=realistic_internal_err)):
            res = await server.agent_terminal_read(project_ref="research", agent_ref=handle)
            self.assertFalse(res["ok"])
            self.assertEqual(
                set(res.keys()),
                {"ok", "project_ref", "agent_ref", "error_type", "reason", "error"},
            )
            self.assertEqual(res["error_type"], "AgentContinuityLost")
            self.assertEqual(res["reason"], "continuity_lost")
            self.assertEqual(res["error"], "agent execution continuity was lost due to an execution contradiction")
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

    async def test_agent_observe_realistic_observation_unavailable_excludes_legacy_ontology(self):
        handle = "c" * 32
        record = {"workspace_root": "/repo", "workspace_ref": "research"}
        workspace = SimpleNamespace(root=Path("/repo"), workspace_ref="research")
        realistic_internal_err = {
            "ok": False,
            "candidate_id": handle,
            "error_type": "ManualCandidateObservationUnavailable",
            "reason": "observation_unavailable",
            "error": "manual candidate process evidence unavailable for pane w-manual:p1 under managed resource m-1",
        }
        with patch.dict(server._MANUAL_AGENT_CANDIDATES, {handle: record}, clear=True), \
             patch.object(server, "_required_project_context", return_value=workspace), \
             patch.object(server, "_read_agent_candidate", AsyncMock(return_value=realistic_internal_err)):
            res = await server.agent_terminal_read(project_ref="research", agent_ref=handle)
            self.assertFalse(res["ok"])
            self.assertEqual(
                set(res.keys()),
                {"ok", "project_ref", "agent_ref", "error_type", "reason", "error"},
            )
            self.assertEqual(res["error_type"], "AgentObservationUnavailable")
            self.assertEqual(res["reason"], "observation_unavailable")
            self.assertEqual(res["error"], "agent execution evidence is temporarily unavailable")
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

    async def test_agent_observe_realistic_observation_uncertain_excludes_legacy_ontology(self):
        handle = "c" * 32
        record = {"workspace_root": "/repo", "workspace_ref": "research"}
        workspace = SimpleNamespace(root=Path("/repo"), workspace_ref="research")
        realistic_internal_err = {
            "ok": False,
            "candidate_id": handle,
            "error_type": "ManualCandidateRevalidationUncertain",
            "reason": "revalidation_uncertain",
            "error": "multiple manual agent candidates match pane w-manual:p1 in tab t-1 across multiple sessions",
        }
        with patch.dict(server._MANUAL_AGENT_CANDIDATES, {handle: record}, clear=True), \
             patch.object(server, "_required_project_context", return_value=workspace), \
             patch.object(server, "_read_agent_candidate", AsyncMock(return_value=realistic_internal_err)):
            res = await server.agent_terminal_read(project_ref="research", agent_ref=handle)
            self.assertFalse(res["ok"])
            self.assertEqual(
                set(res.keys()),
                {"ok", "project_ref", "agent_ref", "error_type", "reason", "error"},
            )
            self.assertEqual(res["error_type"], "AgentObservationUncertain")
            self.assertEqual(res["reason"], "observation_uncertain")
            self.assertEqual(res["error"], "multiple agents match the target execution locus")
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

    async def test_agent_observe_public_read_source_neutral_fallback(self):
        handle = "c" * 32
        record = {"workspace_root": "/repo", "workspace_ref": "research"}
        workspace = SimpleNamespace(root=Path("/repo"), workspace_ref="research")
        # Internal read result where read dictionary has no "source" key
        internal_read_result = {
            "ok": True,
            "candidate": {"herdr_status": "idle"},
            "read": {
                "text": "sample output",
                "chars": 13,
                "truncated": False,
                "limit": 120,
            },
            "attribution": "unattributed_current_terminal_output",
        }
        with patch.dict(server._MANUAL_AGENT_CANDIDATES, {handle: record}, clear=True), \
             patch.object(server, "_required_project_context", return_value=workspace), \
             patch.object(server, "_read_agent_candidate", AsyncMock(return_value=internal_read_result)):
            res = await server.agent_terminal_read(project_ref="research", agent_ref=handle)
            self.assertTrue(res["ok"])
            self.assertEqual(res["read"]["source"], "terminal_output")
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


    @staticmethod
    def _binding_block(workspace_ref: str) -> str:
        return " ".join(server._project_instructions_snippet(workspace_ref).split())
