"""Tests for Bridge VNext Phase 1: project-scoped context/read/search/diff facades."""

from __future__ import annotations

import asyncio
import base64
from contextlib import ExitStack
import dataclasses
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

os.environ.setdefault(
    "BRIDGE_PATH_TOKEN",
    "test-token-abcdefghijklmnopqrstuvwxyz-012345",
)

_import_store = tempfile.TemporaryDirectory(prefix="bridge-test-registry-")
os.environ["BRIDGE_WORKSPACE_STORE_PATH"] = str(Path(_import_store.name) / "registry.json")

from gpt_agent_bridge import server
from gpt_agent_bridge.workspace_context import WorkspaceRegistryStore, WorkspaceRegistry, canonical_git_worktree

# Canonical 1x1 PNG.
TINY_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)
# Minimal JPEG-magic and WebP-magic byte heads (not decodable; magic check only).
JPEG_HEAD = b"\xff\xd8\xff\xe0" + b"\x00" * 20
WEBP_HEAD = b"RIFF\x24\x00\x00\x00WEBP" + b"\x00" * 12
VNEXT_TOOLS = ("context", "read", "search", "diff")


def _init_git_repo(path: Path) -> None:
    subprocess.run(["git", "init", "-b", "main"], cwd=str(path), check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=str(path), check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=str(path), check=True, capture_output=True)
    init_file = path / "README.md"
    init_file.write_text("# Test Repo\nInitial content\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=str(path), check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "Initial commit"], cwd=str(path), check=True, capture_output=True)


def _without_observed_at(result: dict) -> dict:
    provenance = dict(result.get("provenance") or {})
    provenance.pop("observed_at", None)
    for field in ("project_ref", "project_root", "execution_target", "target_kind", "work_ref", "atomic_snapshot", "proves"):
        provenance.pop(field, None)
    normalized = dict(result)
    for field in ("project_ref", "project_root", "execution_target", "target_kind", "work_ref", "observation_mode", "dirty", "version", "pagination"):
        normalized.pop(field, None)
    normalized["coverage"] = dict(normalized.get("coverage", {}))
    normalized["coverage"].pop("submodule_worktrees", None)
    normalized["provenance"] = provenance
    return normalized


def _identical_agy_backend(root: Path):
    """Three unnamed, idle `agy` candidates differing only by tab/pane id.

    Pane ids stay non-sequential so the hint visibly echoes each id's own suffix
    rather than any computed position.
    """
    from tests.test_manual_agents import agy_agent, manual_backend

    backend, state = manual_backend(root)
    placements = [
        ("w-manual:t1", "w-manual:p1"),
        ("w-manual:t1", "w-manual:p4"),
        ("w-manual:t2", "w-manual:p2"),
    ]
    state["tabs"] = [
        {"workspace_id": "w-manual", "tab_id": tab_id, "label": tab_id, "pane_count": 1}
        for tab_id in dict.fromkeys(tab_id for tab_id, _pane_id in placements)
    ]
    state["panes"] = [
        {
            "workspace_id": "w-manual",
            "cwd": str(root),
            "tab_id": tab_id,
            "pane_id": pane_id,
            "terminal_id": f"term-{pane_id}",
        }
        for tab_id, pane_id in placements
    ]
    extra = []
    for index, (tab_id, pane_id) in enumerate(placements[1:]):
        agent = agy_agent(root, pid=2000 + index)
        agent["tab_id"] = tab_id
        agent["pane_id"] = pane_id
        agent["terminal_id"] = f"term-{pane_id}"
        extra.append(agent)
    state["created_agents"] = extra
    return backend, state


async def computed_read(path, workspace_ref):
    workspace = server._workspace_context(workspace_ref)
    _, rel_path = server._validate_workspace_relative_path(workspace.root, path)
    return await asyncio.to_thread(server._compute_workspace_read,
        workspace, rel_path, 0, server.MAX_WORKSPACE_READ_PAGE)


async def computed_search(query, workspace_ref):
    return await asyncio.to_thread(server._compute_workspace_search,
        server._workspace_context(workspace_ref), query, None, server.DEFAULT_WORKSPACE_SEARCH_MATCHES)


async def computed_diff(workspace_ref, view="summary"):
    return await asyncio.to_thread(server._compute_workspace_diff,
        server._workspace_context(workspace_ref), None, view, False, 0, server.MAX_WORKSPACE_DIFF_PAGE)


class VNextSurfaceTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self._stack = ExitStack()
        self.addCleanup(self._stack.close)

        self._temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self._temp_dir.cleanup)
        self.root = Path(self._temp_dir.name).resolve()
        _init_git_repo(self.root)
        _, self.git_identity = canonical_git_worktree(self.root)

        self._beta_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self._beta_dir.cleanup)
        self.beta_root = Path(self._beta_dir.name).resolve()
        _init_git_repo(self.beta_root)
        _, self.beta_git_identity = canonical_git_worktree(self.beta_root)

        registry_temp = tempfile.TemporaryDirectory(prefix="bridge-registry-case-")
        self.addCleanup(registry_temp.cleanup)
        self.registry = WorkspaceRegistry(default_root=self.root, raw=os.environ.get("NONEXISTENT_ENV_KEY"), store=WorkspaceRegistryStore(Path(registry_temp.name) / "registry.json"))
        self.registry._entries["alpha"] = (self.root, self.git_identity)
        self.registry._entries["beta"] = (self.beta_root, self.beta_git_identity)
        stale_identity = dataclasses.replace(self.git_identity, root_inode=self.git_identity.root_inode + 1)
        self.registry._entries["stale"] = (self.root, stale_identity)

        self._stack.enter_context(patch.object(server, "ROOT", self.root))
        self._stack.enter_context(patch.object(server, "_WORKSPACE_REGISTRY", self.registry))
        from tests.test_manual_agents import manual_backend
        beta_backend, beta_state = manual_backend(self.beta_root)
        beta_state["agent"] = None
        self._stack.enter_context(patch.object(server, "_WORKSPACE_BACKENDS", {
            str(self.root): manual_backend(self.root)[0], str(self.beta_root): beta_backend,
        }))

    # -------------------------------------------------------------------
    # Mandatory project_ref, fail-closed authorization
    # -------------------------------------------------------------------

    async def test_project_ref_is_schema_required_for_every_vnext_tool(self) -> None:
        for name in VNEXT_TOOLS:
            tool = server.mcp._tool_manager.get_tool(name)
            self.assertIsNotNone(tool)
            self.assertIn("project_ref", tool.parameters.get("required", []))

    async def test_missing_or_blank_project_ref_fails_closed_without_default_fallback(self) -> None:
        for value in (None, "", "   "):
            with self.subTest(project_ref=value):
                self.assertEqual((await server.context(project_ref=value))["error_type"], "ProjectRefRequired")
                self.assertEqual((await server.read(project_ref=value, path="README.md"))["error_type"], "ProjectRefRequired")
                self.assertEqual((await server.search(project_ref=value, query="x"))["error_type"], "ProjectRefRequired")
                self.assertEqual((await server.diff(project_ref=value))["error_type"], "ProjectRefRequired")

    async def test_unknown_and_identity_changed_refs_fail_closed(self) -> None:
        for ref in ("missing_ref", "stale", "Default"):
            with self.subTest(project_ref=ref):
                self.assertEqual((await server.context(project_ref=ref))["error_type"], "ProjectRefUnauthorized")
                self.assertEqual((await server.read(project_ref=ref, path="README.md"))["error_type"], "ProjectRefUnauthorized")
                self.assertEqual((await server.search(project_ref=ref, query="x"))["error_type"], "ProjectRefUnauthorized")
                self.assertEqual((await server.diff(project_ref=ref))["error_type"], "ProjectRefUnauthorized")

    async def test_authorized_refs_resolve_to_their_exact_registered_root(self) -> None:
        context = await server.context(project_ref="beta")
        self.assertTrue(context["ok"])
        self.assertEqual(context["project_ref"], "beta")
        self.assertEqual(context["root"], str(self.beta_root))

    # -------------------------------------------------------------------
    # context: compact Principal orientation
    # -------------------------------------------------------------------

    async def test_context_reports_compact_git_facts_and_dirty_state(self) -> None:
        result = await server.context(project_ref="alpha")
        self.assertTrue(result["ok"])
        self.assertEqual(
            set(result.keys()),
            {"ok", "project_ref", "root", "git", "work_capacity", "continuation_inbox", "continuity", "agents", "agent_count",
             "agents_complete", "agents_skipped_count", "agents_coverage_counts",
             "agents_rejection_diagnostics", "provenance"},
        )
        self.assertEqual(result["git"]["observation"], "ok")
        self.assertEqual(result["git"]["branch"], "main")
        self.assertTrue(result["git"]["head"])
        self.assertFalse(result["git"]["dirty"])
        self.assertEqual(result["git"]["changes"], 0)

        (self.root / "untracked.txt").write_text("dirty\n", encoding="utf-8")
        dirty = await server.context(project_ref="alpha")
        self.assertTrue(dirty["git"]["dirty"])
        self.assertGreaterEqual(dirty["git"]["changes"], 1)

    async def test_context_agents_are_decision_relevant_without_low_level_telemetry(self) -> None:
        from tests.test_manual_agents import manual_backend

        server._MANUAL_AGENT_CANDIDATES.clear()
        self.addCleanup(server._MANUAL_AGENT_CANDIDATES.clear)
        backend, _state = manual_backend(self.root)
        self._stack.enter_context(
            patch.dict(server._WORKSPACE_BACKENDS, {str(self.root): backend})
        )

        result = await server.context(project_ref="alpha")
        self.assertTrue(result["ok"])
        self.assertEqual(result["agent_count"], 1)
        agent = result["agents"][0]
        self.assertEqual(set(agent.keys()), {"handle", "kind", "status", "name", "hint", "workspace_id", "checkout"})
        self.assertEqual(agent["kind"], "agy")
        self.assertEqual(agent["hint"], "tab 1 / pane 1")
        self.assertTrue(agent["handle"])
        self.assertIn(agent["handle"], server._MANUAL_AGENT_CANDIDATES)

        again = await server.context(project_ref="alpha")
        self.assertEqual(again["agents"][0]["handle"], agent["handle"])

    async def test_context_hint_separates_identical_agents_without_becoming_identity(self) -> None:
        server._MANUAL_AGENT_CANDIDATES.clear()
        self.addCleanup(server._MANUAL_AGENT_CANDIDATES.clear)
        backend, _state = _identical_agy_backend(self.root)
        self._stack.enter_context(
            patch.dict(server._WORKSPACE_BACKENDS, {str(self.root): backend})
        )

        result = await server.context(project_ref="alpha")
        self.assertTrue(result["ok"])
        self.assertEqual(result["agent_count"], 3)
        # Kind, name, and status are indistinguishable; only hint separates them.
        self.assertEqual({agent["kind"] for agent in result["agents"]}, {"agy"})
        self.assertEqual({agent["name"] for agent in result["agents"]}, {None})
        self.assertEqual({agent["status"] for agent in result["agents"]}, {"idle"})
        self.assertEqual(
            sorted(agent["hint"] for agent in result["agents"]),
            ["tab 1 / pane 1", "tab 1 / pane 4", "tab 2 / pane 2"],
        )
        self.assertEqual(
            len({agent["hint"] for agent in result["agents"]}), 3, "hint must disambiguate"
        )

        handles = {agent["handle"] for agent in result["agents"]}
        self.assertEqual(len(handles), 3)
        for agent in result["agents"]:
            self.assertNotIn(agent["hint"], handles)
            self.assertNotIn(agent["hint"], server._MANUAL_AGENT_CANDIDATES)
            self.assertIsNone(re.fullmatch(r"[0-9a-f]{32}", agent["hint"]))
            refused = await server.agent_terminal_read(project_ref="alpha", agent_ref=agent["hint"])
            self.assertFalse(refused["ok"])
            self.assertEqual(refused["error_type"], "UnknownAgentRef")

        # A hint is a rendering of the id suffix, not a leak of raw location ids.
        blob = json.dumps(result)
        for leak in (
            "w-manual:t1", "w-manual:t2", "w-manual:p1", "w-manual:p2",
            "w-manual:p4", "term-w-manual", "tab_id", "pane_id",
            "terminal_id", "foreground_process", "agent_session",
        ):
            self.assertNotIn(leak, blob)

    def test_hint_derives_from_existing_ids_and_stays_none_when_unproven(self) -> None:
        self.assertEqual(
            server._agent_location_hint({"tab_id": "w1R:t2", "pane_id": "w1R:p5"}),
            "tab 2 / pane 5",
        )
        for candidate in (
            {},
            {"tab_id": "w1R:t2"},
            {"tab_id": "w1R:t2", "pane_id": None},
            {"tab_id": "w1R:2", "pane_id": "w1R:p5"},
            {"tab_id": "w1R:tX", "pane_id": "w1R:p5"},
            {"tab_id": "w1R:t2", "pane_id": "w1R:q5"},
            {"tab_id": "w1R:t2", "pane_id": 5},
        ):
            with self.subTest(candidate=candidate):
                self.assertIsNone(server._agent_location_hint(candidate))

    async def test_context_agents_stay_scoped_to_the_selected_project(self) -> None:
        from tests.test_manual_agents import manual_backend

        server._MANUAL_AGENT_CANDIDATES.clear()
        self.addCleanup(server._MANUAL_AGENT_CANDIDATES.clear)
        backend, _state = manual_backend(self.root)
        self._stack.enter_context(
            patch.dict(server._WORKSPACE_BACKENDS, {str(self.root): backend})
        )

        beta_context = await server.context(project_ref="beta")
        self.assertTrue(beta_context["ok"])
        self.assertEqual(beta_context["agent_count"], 0)
        self.assertEqual(beta_context["agents"], [])

        alpha_context = await server.context(project_ref="alpha")
        self.assertEqual(alpha_context["agent_count"], 1)

    async def test_context_reports_discovery_completeness_and_failures_honestly(self) -> None:
        (self.root / "untracked.txt").write_text("dirty\n", encoding="utf-8")

        truncated = {"ok": True, "candidates": [], "candidates_truncated": True, "skipped_count": 2,
                     "coverage_counts": {"out_of_project": 0, "invalid_or_unavailable": 2, "truncated": 1}}
        with patch.object(server, "_discover_project_candidates", AsyncMock(return_value=truncated)):
            result = await server.context(project_ref="alpha")
        self.assertTrue(result["ok"])
        self.assertFalse(result["agents_complete"])
        self.assertEqual(result["agents_skipped_count"], 2)
        self.assertNotIn("agents_error", result)

        complete = {"ok": True, "candidates": [], "candidates_truncated": False, "skipped_count": 0,
                    "coverage_counts": {"out_of_project": 0, "invalid_or_unavailable": 0, "truncated": 0}}
        with patch.object(server, "_discover_project_candidates", AsyncMock(return_value=complete)):
            result = await server.context(project_ref="alpha")
        self.assertTrue(result["agents_complete"])
        self.assertEqual(result["agents_skipped_count"], 0)

        failed = {
            "ok": False,
            "error_type": "ManualAgentDiscoveryUnavailable",
            "error": "raw herdr payload noise 12345",
        }
        with patch.object(server, "_discover_project_candidates", AsyncMock(return_value=failed)):
            result = await server.context(project_ref="alpha")
        self.assertTrue(result["ok"])
        self.assertEqual(result["git"]["branch"], "main")
        self.assertTrue(result["git"]["dirty"])
        self.assertEqual(result["agents"], [])
        self.assertFalse(result["agents_complete"])
        self.assertEqual(result["agents_error"]["error_type"], "AgentDiscoveryUnavailable")
        self.assertNotIn("raw herdr payload noise", json.dumps(result))

    async def test_context_git_observation_failure_is_honest(self) -> None:
        (self.root / "untracked.txt").write_text("dirty\n", encoding="utf-8")

        with patch.object(
            server, "_git_run_bounded", return_value=(1, "", "fatal: not a git repository")
        ):
            result = await server.context(project_ref="alpha")
        self.assertTrue(result["ok"])
        self.assertEqual(result["git"]["observation"], "unavailable")
        self.assertIsNone(result["git"]["dirty"])
        self.assertIsNone(result["git"]["changes"])
        self.assertEqual(result["git"]["branch"], "main")
        self.assertNotIn("status_error", json.dumps(result))
        self.assertNotIn("fatal", json.dumps(result))

        with patch.object(server, "_git_inspect_small", return_value=None):
            result = await server.context(project_ref="alpha")
        self.assertEqual(result["git"]["observation"], "unavailable")
        self.assertIsNone(result["git"]["branch"])
        self.assertIsNone(result["git"]["head"])
        self.assertIsNone(result["git"]["dirty"])
        self.assertIsNone(result["git"]["changes"])

    # -------------------------------------------------------------------
    # read: text compatibility and native image support
    # -------------------------------------------------------------------

    async def test_read_text_matches_workspace_read_semantics(self) -> None:
        (self.root / "notes.txt").write_text("alpha line\nsecond line\n", encoding="utf-8")
        facade = await server.read(project_ref="alpha", path="notes.txt", limit=16384)
        legacy = await computed_read(path="notes.txt", workspace_ref="alpha")
        self.assertTrue(facade["ok"])
        self.assertEqual(_without_observed_at(facade), _without_observed_at(legacy))

        page = await server.read(project_ref="alpha", path="notes.txt", offset=6, limit=4)
        self.assertEqual(page["content"], "line")

        (self.root / "blob.bin").write_bytes(b"\x00\x01\x02binary")
        binary = await server.read(project_ref="alpha", path="blob.bin")
        self.assertEqual(binary["error_type"], "BinaryFileUnsupported")

        traversal = await server.read(project_ref="alpha", path="../secret.txt")
        self.assertEqual(traversal["error_type"], "InvalidPath")

    async def test_read_returns_native_image_content_for_allowlisted_formats(self) -> None:
        (self.root / "tiny.png").write_bytes(TINY_PNG)
        result = await server.read(project_ref="alpha", path="tiny.png")
        self.assertIsInstance(result, list)
        self.assertEqual(len(result), 2)
        image, provenance = result
        self.assertIsInstance(image, server.Image)
        self.assertEqual(image.data, TINY_PNG)
        self.assertEqual(provenance["ok"], True)
        self.assertEqual(provenance["kind"], "image")
        self.assertEqual(provenance["mime_type"], "image/png")
        self.assertEqual(provenance["file_sha256"], hashlib.sha256(TINY_PNG).hexdigest())
        self.assertEqual(provenance["execution_target"], str(self.root))
        self.assertEqual(provenance["provenance"]["proves"], "observed_content_only")
        self.assertNotIn("state_id", provenance)
        self.assertNotIn("dirty", provenance)

        tool = server.mcp._tool_manager.get_tool("read")
        self.assertIsNone(tool.fn_metadata.output_schema)
        converted = server.native_image_result(result)
        self.assertEqual(converted.structured_content, None)
        self.assertEqual(converted.content[0].type, "image")
        self.assertEqual(converted.content[0].mime_type, "image/png")
        self.assertEqual(base64.b64decode(converted.content[0].data), TINY_PNG)
        self.assertEqual(converted.content[1].type, "text")
        self.assertEqual(json.loads(converted.content[1].text)["kind"], "image")

    async def test_read_image_accepts_jpeg_gif_webp_suffixes(self) -> None:
        (self.root / "pic.jpg").write_bytes(JPEG_HEAD)
        result = await server.read(project_ref="alpha", path="pic.jpg")
        self.assertEqual(result[1]["mime_type"], "image/jpeg")

        (self.root / "pic.webp").write_bytes(WEBP_HEAD)
        result = await server.read(project_ref="alpha", path="pic.webp")
        self.assertEqual(result[1]["mime_type"], "image/webp")

    async def test_read_image_rejects_unallowlisted_mismatched_and_oversized(self) -> None:
        (self.root / "pic.bmp").write_bytes(b"BM\x00\x00" + b"\x00" * 20)
        result = await server.read(project_ref="alpha", path="pic.bmp")
        self.assertFalse(result["ok"])
        self.assertEqual(result["error_type"], "BinaryFileUnsupported")

        (self.root / "fake.png").write_bytes(JPEG_HEAD)
        result = await server.read(project_ref="alpha", path="fake.png")
        self.assertFalse(result["ok"])
        self.assertEqual(result["error_type"], "UnsupportedImageFormat")

        (self.root / "big.png").write_bytes(TINY_PNG + b"\x00" * 4)
        with patch.object(server, "MAX_VNEXT_IMAGE_FILE_SIZE", 8):
            result = await server.read(project_ref="alpha", path="big.png")
        self.assertFalse(result["ok"])
        self.assertEqual(result["error_type"], "FileTooLarge")

        result = await server.read(project_ref="alpha", path="missing.png")
        self.assertFalse(result["ok"])
        self.assertEqual(result["error_type"], "FileNotFound")

    async def test_image_read_rejects_pagination(self) -> None:
        (self.root / "tiny.png").write_bytes(TINY_PNG)
        paged_offset = await server.read(project_ref="alpha", path="tiny.png", offset=1)
        self.assertFalse(paged_offset["ok"])
        self.assertEqual(paged_offset["error_type"], "ImagePagingUnsupported")
        paged_limit = await server.read(project_ref="alpha", path="tiny.png", limit=1024)
        self.assertFalse(paged_limit["ok"])
        self.assertEqual(paged_limit["error_type"], "ImagePagingUnsupported")
        whole = await server.read(project_ref="alpha", path="tiny.png")
        self.assertIsInstance(whole, list)

    async def test_image_read_enforces_bound_on_bytes_actually_read(self) -> None:
        (self.root / "big.png").write_bytes(TINY_PNG)
        with patch.object(server, "MAX_VNEXT_IMAGE_FILE_SIZE", 16):
            result = await server.read(project_ref="alpha", path="big.png")
        self.assertNotIsInstance(result, list)
        self.assertFalse(result["ok"])
        self.assertEqual(result["error_type"], "FileTooLarge")
        self.assertEqual(result["file_size_bytes"], 17)

        (self.root / "fits.png").write_bytes(TINY_PNG)
        fits = await server.read(project_ref="alpha", path="fits.png")
        self.assertIsInstance(fits, list)
        self.assertEqual(fits[0].data, TINY_PNG)
        self.assertEqual(fits[1]["file_size_bytes"], len(TINY_PNG))

    async def test_image_read_rejects_final_symlink_without_following(self) -> None:
        outside = Path(tempfile.gettempdir()) / "vnext_outside_symlink.png"
        outside.write_bytes(TINY_PNG)
        link = self.root / "link.png"
        os.symlink(outside, link)
        try:
            via_tool = await server.read(project_ref="alpha", path="link.png")
            self.assertFalse(via_tool["ok"])

            workspace = server._WORKSPACE_REGISTRY.resolve("alpha")
            direct = server._compute_bridge_read_image(workspace, "link.png", "image/png")
            self.assertNotIsInstance(direct, list)
            self.assertFalse(direct["ok"])
            self.assertEqual(direct["error_type"], "SymlinkRejected")
            self.assertNotIn(base64.b64encode(TINY_PNG).decode(), json.dumps(direct))
        finally:
            link.unlink()
            outside.unlink()

    async def test_read_rejects_parent_symlink_replacement_for_text_and_image(self) -> None:
        outside_dir = Path(tempfile.mkdtemp(prefix="vnext_outside_parent_"))
        self.addCleanup(shutil.rmtree, outside_dir, ignore_errors=True)
        (outside_dir / "note.txt").write_text("OUTSIDE-TEXT-BYTES\n", encoding="utf-8")
        (outside_dir / "pic.png").write_bytes(TINY_PNG)
        (self.root / "sub").symlink_to(outside_dir, target_is_directory=True)
        try:
            via_tool = await server.read(project_ref="alpha", path="sub/note.txt")
            self.assertFalse(via_tool["ok"])
            self.assertEqual(via_tool["error_type"], "InvalidPath")

            workspace = server._WORKSPACE_REGISTRY.resolve("alpha")
            direct_text = server._compute_workspace_read(workspace, "sub/note.txt", 0, 100)
            self.assertFalse(direct_text["ok"])
            self.assertEqual(direct_text["error_type"], "SymlinkRejected")
            self.assertNotIn("OUTSIDE-TEXT-BYTES", json.dumps(direct_text))

            direct_image = server._compute_bridge_read_image(workspace, "sub/pic.png", "image/png")
            self.assertFalse(direct_image["ok"])
            self.assertEqual(direct_image["error_type"], "SymlinkRejected")
            self.assertNotIn(base64.b64encode(TINY_PNG).decode(), json.dumps(direct_image))

            (self.root / "plain.txt").write_text("plain\n", encoding="utf-8")
            not_dir = server._compute_workspace_read(workspace, "plain.txt/note.txt", 0, 100)
            self.assertFalse(not_dir["ok"])
            self.assertEqual(not_dir["error_type"], "NotADirectory")
        finally:
            (self.root / "sub").unlink()

    async def test_nested_regular_text_and_image_reads_work(self) -> None:
        sub = self.root / "sub"
        sub.mkdir()
        (sub / "note.txt").write_text("nested alpha line\n", encoding="utf-8")
        (sub / "pic.png").write_bytes(TINY_PNG)

        nested_text = await server.read(project_ref="alpha", path="sub/note.txt")
        self.assertTrue(nested_text["ok"])
        self.assertIn("nested alpha line", nested_text["content"])

        nested_image = await server.read(project_ref="alpha", path="sub/pic.png")
        self.assertIsInstance(nested_image, list)
        self.assertEqual(nested_image[0].data, TINY_PNG)
        self.assertEqual(nested_image[1]["file_sha256"], hashlib.sha256(TINY_PNG).hexdigest())

    async def test_root_identity_mismatch_fails_closed_for_descriptor_reads(self) -> None:
        (self.root / "ident.png").write_bytes(TINY_PNG)
        workspace = server._WORKSPACE_REGISTRY.resolve("alpha")
        bad_identity = dataclasses.replace(workspace.git, root_inode=workspace.git.root_inode + 1)
        bad_workspace = dataclasses.replace(workspace, git=bad_identity)

        text = server._compute_workspace_read(bad_workspace, "README.md", 0, 100)
        self.assertFalse(text["ok"])
        self.assertEqual(text["error_type"], "WorkspaceRootIdentityChanged")

        image = server._compute_bridge_read_image(bad_workspace, "ident.png", "image/png")
        self.assertFalse(image["ok"])
        self.assertEqual(image["error_type"], "WorkspaceRootIdentityChanged")

    async def test_stable_in_root_symlinks_stay_readable_through_both_seams(self) -> None:
        (self.root / "real_note.txt").write_text("alpha target bytes\n", encoding="utf-8")
        (self.root / "link_note.txt").symlink_to("real_note.txt")
        (self.root / "real.png").write_bytes(TINY_PNG)
        (self.root / "link.png").symlink_to("real.png")

        legacy = await computed_read(path="link_note.txt", workspace_ref="alpha")
        self.assertTrue(legacy["ok"])
        self.assertEqual(legacy["content"], "alpha target bytes\n")
        self.assertEqual(legacy["path"], "real_note.txt")

        vnext_text = await server.read(project_ref="alpha", path="link_note.txt")
        self.assertTrue(vnext_text["ok"])
        self.assertEqual(vnext_text["content"], "alpha target bytes\n")
        self.assertEqual(vnext_text["path"], "real_note.txt")

        vnext_image = await server.read(project_ref="alpha", path="link.png")
        self.assertIsInstance(vnext_image, list)
        self.assertEqual(vnext_image[0].data, TINY_PNG)
        self.assertEqual(vnext_image[1]["path"], "real.png")
        self.assertEqual(vnext_image[1]["file_sha256"], hashlib.sha256(TINY_PNG).hexdigest())

    async def test_fifo_final_component_fails_closed_promptly_without_blocking(self) -> None:
        os.mkfifo(self.root / "pipe.png")
        os.mkfifo(self.root / "pipe.txt")

        image_fifo = await asyncio.wait_for(
            server.read(project_ref="alpha", path="pipe.png"), timeout=5
        )
        self.assertFalse(image_fifo["ok"])
        self.assertEqual(image_fifo["error_type"], "NotARegularFile")

        text_fifo = await asyncio.wait_for(
            server.read(project_ref="alpha", path="pipe.txt"), timeout=5
        )
        self.assertFalse(text_fifo["ok"])
        self.assertEqual(text_fifo["error_type"], "NotARegularFile")

        legacy_fifo = await asyncio.wait_for(
            computed_read(path="pipe.txt", workspace_ref="alpha"), timeout=5
        )
        self.assertFalse(legacy_fifo["ok"])
        self.assertEqual(legacy_fifo["error_type"], "NotARegularFile")

    async def test_default_root_named_ref_works_for_vnext_tools(self) -> None:
        self.registry._entries["bridgeself"] = (self.root, self.git_identity)
        self.addCleanup(self.registry._entries.pop, "bridgeself", None)

        context = await server.context(project_ref="bridgeself")
        self.assertTrue(context["ok"])
        self.assertEqual(context["root"], str(self.root))

        read_result = await server.read(project_ref="bridgeself", path="README.md")
        self.assertTrue(read_result["ok"])
        self.assertEqual(read_result["canonical_root"], str(self.root))

        search_result = await server.search(project_ref="bridgeself", query="Initial")
        self.assertTrue(search_result["ok"])
        diff_result = await server.diff(project_ref="bridgeself")
        self.assertTrue(diff_result["ok"])

    # -------------------------------------------------------------------
    # search/diff: facade equivalence and project scope
    # -------------------------------------------------------------------

    async def test_search_and_diff_facades_match_workspace_tools_exactly(self) -> None:
        (self.root / "README.md").write_text("# Test Repo\nModified alpha marker\n", encoding="utf-8")
        (self.root / "untracked.txt").write_text("alpha only\n", encoding="utf-8")

        facade_search = await server.search(project_ref="alpha", query="alpha marker")
        legacy_search = await computed_search(query="alpha marker", workspace_ref="alpha")
        self.assertEqual(_without_observed_at(facade_search), _without_observed_at(legacy_search))
        self.assertEqual(facade_search["match_count"], 1)

        facade_diff = await server.diff(project_ref="alpha")
        legacy_diff = await computed_diff(workspace_ref="alpha")
        self.assertEqual(_without_observed_at(facade_diff), _without_observed_at(legacy_diff))
        self.assertFalse(facade_diff["is_clean"])
        self.assertEqual(facade_diff["counts"]["untracked"], 1)

        facade_patch = await server.diff(project_ref="alpha", view="patch")
        legacy_patch = await computed_diff(workspace_ref="alpha", view="patch")
        self.assertEqual(_without_observed_at(facade_patch), _without_observed_at(legacy_patch))

    async def test_search_and_diff_reject_invalid_parameters_like_legacy_tools(self) -> None:
        self.assertEqual((await server.diff(project_ref="alpha", view="bogus"))["error_type"], "InvalidView")
        self.assertEqual(
            (await server.search(project_ref="alpha", query="x" * 501))["error_type"],
            "InvalidQuery",
        )
        self.assertEqual(
            (await server.search(project_ref="alpha", query="x", max_matches=0))["error_type"],
            "InvalidLimit",
        )

    async def test_search_and_diff_stay_scoped_to_one_project(self) -> None:
        # search covers tracked files only, so markers go into tracked READMEs.
        (self.root / "README.md").write_text("# Test Repo\nalpha marker here\n", encoding="utf-8")
        (self.beta_root / "README.md").write_text("# Test Repo\nbeta marker here\n", encoding="utf-8")
        (self.root / "alpha_only.txt").write_text("alpha untracked\n", encoding="utf-8")
        (self.beta_root / "beta_only.txt").write_text("beta untracked\n", encoding="utf-8")

        alpha_read = await server.read(project_ref="alpha", path="README.md")
        beta_read = await server.read(project_ref="beta", path="README.md")
        self.assertNotEqual(alpha_read["canonical_root"], beta_read["canonical_root"])
        self.assertEqual(alpha_read["canonical_root"], str(self.root))
        self.assertEqual(beta_read["canonical_root"], str(self.beta_root))

        alpha_search = await server.search(project_ref="alpha", query="alpha marker here")
        self.assertEqual(alpha_search["match_count"], 1)
        self.assertEqual(alpha_search["matches"][0]["path"], "README.md")
        beta_search = await server.search(project_ref="beta", query="beta marker here")
        self.assertEqual(beta_search["match_count"], 1)
        self.assertEqual(beta_search["matches"][0]["path"], "README.md")
        cross_search = await server.search(project_ref="alpha", query="beta marker here")
        self.assertEqual(cross_search["match_count"], 0)

        alpha_diff = await server.diff(project_ref="alpha")
        alpha_paths = {f["path"] for f in alpha_diff["files"]}
        self.assertIn("alpha_only.txt", alpha_paths)
        self.assertNotIn("beta_only.txt", alpha_paths)
        beta_diff = await server.diff(project_ref="beta")
        beta_paths = {f["path"] for f in beta_diff["files"]}
        self.assertIn("beta_only.txt", beta_paths)
        self.assertNotIn("alpha_only.txt", beta_paths)


if __name__ == "__main__":
    unittest.main()
