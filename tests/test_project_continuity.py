"""Project continuity and onboarding contract tests."""

from __future__ import annotations

from contextlib import ExitStack
import errno
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

from tests.continuity_fixture import write_canonical_cognition

os.environ.setdefault(
    "BRIDGE_PATH_TOKEN",
    "test-token-abcdefghijklmnopqrstuvwxyz-012345",
)

_import_store = tempfile.TemporaryDirectory(prefix="bridge-test-registry-")
os.environ["BRIDGE_WORKSPACE_STORE_PATH"] = str(Path(_import_store.name) / "registry.json")

from gpt_agent_bridge import server
from gpt_agent_bridge import project_continuity as continuity
from gpt_agent_bridge.workspace_context import WorkspaceRegistry, WorkspaceRegistryStore, canonical_git_worktree


def _init_git_repo(path: Path) -> None:
    path.mkdir()
    subprocess.run(["git", "init", "-b", "main"], cwd=path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=path, check=True)
    (path / "README.md").write_text("# Test Repo\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=path, check=True)
    subprocess.run(["git", "commit", "-m", "initial"], cwd=path, check=True, capture_output=True)


class ProjectContinuityTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self._stack = ExitStack()
        self.addCleanup(self._stack.close)
        self._temp = tempfile.TemporaryDirectory()
        self.addCleanup(self._temp.cleanup)
        self.root = Path(self._temp.name) / "repo"
        _init_git_repo(self.root)
        _, identity = canonical_git_worktree(self.root)
        store_dir = Path(self._temp.name) / "registry"
        store_dir.mkdir(mode=0o700)
        self.registry = WorkspaceRegistry(
            default_root=self.root, raw="{}",
            store=WorkspaceRegistryStore(store_dir / "workspaces.json"),
        )
        self.registry._entries["project"] = (self.root, identity)
        self._stack.enter_context(patch.object(server, "ROOT", self.root))
        self._stack.enter_context(patch.object(server, "_WORKSPACE_REGISTRY", self.registry))
        self._stack.enter_context(patch.object(
            server,
            "_discover_project_candidates",
            AsyncMock(return_value={
                "ok": True,
                "candidates": [],
                "candidates_truncated": False,
                "skipped_count": 0,
                "coverage_counts": {"out_of_project": 0, "invalid_or_unavailable": 0, "truncated": 0},
            }),
        ))

    def _write_manifest(
        self,
        *,
        current_state: str = "STATE.md",
        rules: list[str] | None = None,
        memory: str = "MEMORY.md",
    ) -> None:
        principal = self.root / ".principal"
        principal.mkdir(exist_ok=True)
        memory_path = self.root / memory
        if not memory_path.exists():
            memory_path.parent.mkdir(parents=True, exist_ok=True)
            memory_path.write_text("memory\n", encoding="utf-8")
        data = {
            "rules": rules if rules is not None else ["README.md"],
            "current_state": current_state,
            "memory": memory,
        }
        (principal / "project.json").write_text(json.dumps(data), encoding="utf-8")

    async def test_context_projects_compact_continuity_without_state_content(self) -> None:
        self._write_manifest()
        (self.root / "STATE.md").write_text("private state body\n", encoding="utf-8")

        result = await server.context(project_ref="project")

        continuity = result["continuity"]
        self.assertTrue(continuity["ready"])
        self.assertEqual(continuity["status"], "ready")
        self.assertEqual(continuity["manifest_path"], ".principal/project.json")
        self.assertEqual(continuity["canonical_pointers"], {
            "rules": ["README.md"],
            "memory": "MEMORY.md",
        })
        self.assertNotIn("manifest_version", continuity)
        self.assertEqual(continuity["current_state"]["path"], "STATE.md")
        self.assertTrue(continuity["current_state"]["revision"].startswith("sha256:"))
        self.assertEqual(continuity["current_state"]["revision_provenance"], {
            "source": "direct_filesystem_revision_only",
            "observation": "bytes",
        })
        self.assertNotIn("private state body", json.dumps(result))

    async def test_missing_manifest_is_nonfatal_and_honest(self) -> None:
        result = await server.context(project_ref="project")
        self.assertTrue(result["ok"])
        self.assertEqual(result["continuity"], {
            "ready": False,
            "status": "manifest_missing",
            "manifest_path": ".principal/project.json",
        })

    async def test_manifest_rejects_traversal_and_symlink_ambiguity(self) -> None:
        self._write_manifest(current_state="../outside.md")
        traversal = await server.context(project_ref="project")
        self.assertEqual(traversal["continuity"]["status"], "manifest_invalid")

        (self.root / ".principal" / "project.json").unlink()
        outside = Path(self._temp.name) / "outside-manifest.json"
        outside.write_text("{}", encoding="utf-8")
        (self.root / ".principal" / "project.json").symlink_to(outside)
        symlink_manifest = await server.context(project_ref="project")
        self.assertEqual(symlink_manifest["continuity"]["status"], "manifest_invalid")

        (self.root / ".principal" / "project.json").unlink()
        self._write_manifest()
        (self.root / "README.md").unlink()
        outside_rules = Path(self._temp.name) / "outside-rules.md"
        outside_rules.write_text("outside rules\n", encoding="utf-8")
        (self.root / "README.md").symlink_to(outside_rules)
        symlink_pointer = await server.context(project_ref="project")
        self.assertEqual(
            symlink_pointer["continuity"]["status"],
            "canonical_pointer_unavailable",
        )
        pointer_refused = await server.checkpoint(
            "project", "replacement\n", continuity.CHECKPOINT_MISSING_REVISION
        )
        self.assertFalse(pointer_refused["ok"])
        self.assertEqual(pointer_refused["error_type"], "ProjectManifestUnavailable")
        (self.root / "README.md").unlink()
        (self.root / "README.md").write_text("# Test Repo\n", encoding="utf-8")

        self._write_manifest(current_state="state-link.md")
        outside_state = Path(self._temp.name) / "outside-state.md"
        outside_state.write_text("outside\n", encoding="utf-8")
        (self.root / "state-link.md").symlink_to(outside_state)
        symlink_state = await server.context(project_ref="project")
        self.assertEqual(symlink_state["continuity"]["status"], "current_state_unavailable")
        refused = await server.checkpoint("project", "replacement\n", continuity.CHECKPOINT_MISSING_REVISION)
        self.assertFalse(refused["ok"])
        self.assertEqual(refused["error_type"], "SymlinkRejected")
        self.assertEqual(outside_state.read_text(encoding="utf-8"), "outside\n")

    async def test_manifest_rejects_non_utf8_and_oversized_json(self) -> None:
        principal = self.root / ".principal"
        principal.mkdir()
        manifest = principal / "project.json"
        manifest.write_bytes(b"\xff\xfe")
        non_utf8 = await server.context(project_ref="project")
        self.assertEqual(non_utf8["continuity"]["status"], "manifest_invalid")

        manifest.write_bytes(b"{" + b" " * continuity.MAX_PROJECT_MANIFEST_BYTES + b"}")
        oversized = await server.context(project_ref="project")
        self.assertEqual(oversized["continuity"]["status"], "manifest_invalid")
        self.assertEqual(oversized["continuity"]["reason"], "ManifestTooLarge")

    async def test_manifest_rejects_version_and_takeover_keys(self) -> None:
        self._write_manifest()
        manifest = self.root / ".principal" / "project.json"
        for extra in ({"version": 1}, {"version": 2}, {"takeover": ["README.md"]}):
            with self.subTest(extra=extra):
                data = json.loads(manifest.read_text(encoding="utf-8"))
                data.update(extra)
                manifest.write_text(json.dumps(data), encoding="utf-8")
                result = await server.context(project_ref="project")
                self.assertEqual(result["continuity"]["status"], "manifest_invalid")
                self.assertEqual(result["continuity"]["reason"], "ManifestSchemaInvalid")

    async def test_manifest_rejects_current_state_manifest_or_rules_overlap(self) -> None:
        for current_state in (".principal/project.json", "README.md"):
            with self.subTest(current_state=current_state):
                self._write_manifest(current_state=current_state)
                result = await server.context(project_ref="project")
                self.assertEqual(result["continuity"]["status"], "manifest_invalid")
                self.assertEqual(
                    result["continuity"]["reason"],
                    "ManifestCurrentStateOverlap",
                )

        (self.root / "RULES.md").write_text("rules\n", encoding="utf-8")
        self._write_manifest(
            current_state="README.md",
            rules=["RULES.md"],
            memory="README.md",
        )
        overlapped = await server.context(project_ref="project")
        self.assertEqual(overlapped["continuity"]["status"], "manifest_invalid")
        self.assertEqual(overlapped["continuity"]["reason"], "ManifestPointerOverlap")

    async def test_checkpoint_cas_conflict_leaves_file_unchanged(self) -> None:
        self._write_manifest()
        state = self.root / "STATE.md"
        state.write_text("before\n", encoding="utf-8")

        result = await server.checkpoint("project", "after\n", "sha256:" + "0" * 64)

        self.assertFalse(result["ok"])
        self.assertEqual(result["error_type"], "CheckpointConflict")
        self.assertEqual(state.read_text(encoding="utf-8"), "before\n")
        self.assertTrue(result["actual_revision"].startswith("sha256:"))

    async def test_checkpoint_atomic_success_and_missing_sentinel_creation(self) -> None:
        self._write_manifest()
        created = await server.checkpoint(
            "project", "first\n", continuity.CHECKPOINT_MISSING_REVISION
        )
        self.assertTrue(created["ok"])
        self.assertEqual(created["path"], "STATE.md")
        self.assertEqual(created["previous_revision"], continuity.CHECKPOINT_MISSING_REVISION)
        self.assertTrue(created["revision"].startswith("sha256:"))
        self.assertEqual(created["provenance"], "principal_supplied_unverified")
        self.assertEqual((self.root / "STATE.md").read_text(encoding="utf-8"), "first\n")
        (self.root / "STATE.md").chmod(0o640)

        replaced = await server.checkpoint("project", "second\n", created["revision"])
        self.assertTrue(replaced["ok"])
        self.assertEqual(replaced["previous_revision"], created["revision"])
        self.assertNotEqual(replaced["revision"], created["revision"])
        self.assertEqual((self.root / "STATE.md").read_text(encoding="utf-8"), "second\n")
        self.assertEqual((self.root / "STATE.md").stat().st_mode & 0o777, 0o640)
        self.assertFalse((self.root / ".git" / "index.lock").exists())
        self.assertEqual(list(self.root.glob(".principal-checkpoint-*.tmp")), [])

    async def test_checkpoint_rechecks_existing_file_before_final_replace(self) -> None:
        self._write_manifest()
        state = self.root / "STATE.md"
        state.write_text("initial\n", encoding="utf-8")
        expected = "sha256:" + hashlib.sha256(b"initial\n").hexdigest()
        original_final_check = server._project_continuity._checkpoint_revision_at_parent

        def interpose(parent_fd, file_name, rel_path):
            state.write_text("external modification\n", encoding="utf-8")
            return original_final_check(parent_fd, file_name, rel_path)

        with patch.object(
            server._project_continuity,
            "_checkpoint_revision_at_parent",
            side_effect=interpose,
        ):
            result = await server.checkpoint("project", "checkpoint\n", expected)

        self.assertFalse(result["ok"])
        self.assertEqual(result["error_type"], "CheckpointConflict")
        self.assertEqual(state.read_text(encoding="utf-8"), "external modification\n")
        self.assertEqual(list(self.root.glob(".principal-checkpoint-*.tmp")), [])

    async def test_checkpoint_missing_creation_is_atomic_no_clobber(self) -> None:
        self._write_manifest()
        state = self.root / "STATE.md"
        original_link = os.link

        def interpose(source, destination, **kwargs):
            state.write_text("external creation\n", encoding="utf-8")
            return original_link(source, destination, **kwargs)

        with patch.object(server.os, "link", side_effect=interpose):
            result = await server.checkpoint(
                "project",
                "checkpoint\n",
                continuity.CHECKPOINT_MISSING_REVISION,
            )

        self.assertFalse(result["ok"])
        self.assertEqual(result["error_type"], "CheckpointConflict")
        self.assertEqual(state.read_text(encoding="utf-8"), "external creation\n")
        self.assertEqual(list(self.root.glob(".principal-checkpoint-*.tmp")), [])

    async def test_checkpoint_missing_fails_closed_without_no_clobber_primitive(self) -> None:
        self._write_manifest()
        with patch.object(
            server.os,
            "link",
            side_effect=OSError(errno.EOPNOTSUPP, "unsupported"),
        ):
            result = await server.checkpoint(
                "project",
                "checkpoint\n",
                continuity.CHECKPOINT_MISSING_REVISION,
            )

        self.assertFalse(result["ok"])
        self.assertEqual(result["error_type"], "CheckpointNoClobberUnavailable")
        self.assertFalse((self.root / "STATE.md").exists())
        self.assertEqual(list(self.root.glob(".principal-checkpoint-*.tmp")), [])

    async def test_registration_reports_onboarding_without_mutating_target(self) -> None:
        target = Path(self._temp.name) / "target"
        _init_git_repo(target)
        store_dir = Path(self._temp.name) / "store"
        store_dir.mkdir(mode=0o700)
        registry = WorkspaceRegistry(
            self.root,
            raw="{}",
            store=WorkspaceRegistryStore(store_dir / "registry.json"),
        )
        before = sorted(str(path.relative_to(target)) for path in target.rglob("*"))
        with patch.object(server, "_WORKSPACE_REGISTRY", registry):
            result = await server.project_register("target", str(target))
        after = sorted(str(path.relative_to(target)) for path in target.rglob("*"))

        self.assertTrue(result["ok"])
        self.assertEqual(result["onboarding"]["status"], "manifest_missing")
        self.assertEqual(result["onboarding"]["manifest_path"], ".principal/project.json")
        self.assertEqual(before, after)
        self.assertFalse((target / ".principal").exists())

    async def test_checkpoint_is_visible_and_narrow(self) -> None:
        visible = {tool.name for tool in await server.mcp.list_tools()}
        self.assertIn("current_state_update", visible)
        tool = server.mcp._tool_manager.get_tool("current_state_update")
        self.assertEqual(
            set(tool.parameters["properties"]),
            {"project_ref", "content", "expected_revision", "edits"},
        )
        self.assertEqual(
            set(tool.parameters["required"]),
            {"project_ref", "expected_revision"},
        )

    async def test_existing_handoff_retains_causal_bytes_and_rejects_stale_chat(self) -> None:
        fixture = Path(__file__).parent / "fixtures/continuity/rebind-placement.md"
        causal = fixture.read_text(encoding="utf-8")
        handoff = self.root / "GPT-Agent-Bridge-HANDOFF.md"
        handoff.write_text(causal, encoding="utf-8")
        self._write_manifest(current_state=handoff.name)
        first = await server.context("project")
        revision = first["continuity"]["current_state"]["revision"]
        before_head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=self.root)
        updated = causal + "\nNext task: inspect the selected resource.\n"
        accepted = await server.checkpoint("project", updated, revision)
        stale = await server.checkpoint("project", "state-only stale chat\n", revision)
        self.assertTrue(accepted["ok"])
        self.assertEqual(stale["error_type"], "CheckpointConflict")
        # Fresh orientation reconstructs the target from pointers, not chat state.
        fresh = await server.context("project")
        target = fresh["continuity"]["current_state"]["path"]
        self.assertEqual(target, handoff.name)
        restored = (self.root / target).read_text(encoding="utf-8")
        self.assertEqual(restored, updated)
        self.assertNotIn(causal, json.dumps(fresh))
        for duplicate in ("CURRENT.md", "PROJECT-STATE.md", "STATE.md"):
            self.assertFalse((self.root / duplicate).exists())
        self.assertEqual(before_head, subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=self.root))

        # Fixture coverage only; actual fresh-chat judgment is a separate acceptance.
        required_evidence = ("D-rebind", "Why superseded:", "scenario://S1/",
                             "Unknown:", "Revisit only if")
        def missing_causal_evidence(text):
            return [item for item in required_evidence if item not in text]
        self.assertEqual(missing_causal_evidence(restored), [])
        state_only = restored.split("## Current state\n", 1)[1].split("## Decision trajectory", 1)[0]
        self.assertEqual(missing_causal_evidence(state_only), list(required_evidence))

    async def test_checkpoint_revalidates_project_and_bounds_content(self) -> None:
        self._write_manifest()
        for ref in ("", "foreign"):
            result = await server.checkpoint(ref, "text", "missing")
            self.assertFalse(result["ok"])
        oversized = await server.checkpoint("project", "x" * 65537, "missing")
        self.assertEqual(oversized["error_type"], "InvalidCheckpointContent")
        self.assertFalse((self.root / "STATE.md").exists())

    async def test_two_cooperating_chats_cannot_overwrite_same_revision(self) -> None:
        import asyncio
        self._write_manifest()
        created = await server.checkpoint("project", "start", "missing")
        results = await asyncio.gather(*[
            server.checkpoint("project", text, created["revision"])
            for text in ("chat one", "chat two")
        ])
        self.assertEqual(sum(result["ok"] for result in results), 1)
        conflict = next(result for result in results if not result["ok"])
        self.assertEqual(conflict["error_type"], "CheckpointConflict")

    async def test_cancelled_waiter_keeps_gate_until_publication_finishes(self) -> None:
        import asyncio
        import threading
        self._write_manifest()
        entered, finish = threading.Event(), threading.Event()
        original = server._project_continuity.checkpoint
        def delayed(*args):
            entered.set()
            if not finish.wait(5):
                raise AssertionError("test did not release publisher")
            return original(*args)
        with patch.object(server._project_continuity, "checkpoint", side_effect=delayed):
            pending = asyncio.create_task(server.checkpoint("project", "first", "missing"))
            try:
                self.assertTrue(await asyncio.to_thread(entered.wait, 5))
                pending.cancel()
                await asyncio.sleep(0)
                self.assertFalse(pending.done())
                second = asyncio.create_task(server.checkpoint("project", "second", "missing"))
                await asyncio.sleep(0)
                self.assertFalse(second.done())
            finally:
                finish.set()
            with self.assertRaises(asyncio.CancelledError):
                await pending
            self.assertEqual((await second)["error_type"], "CheckpointConflict")
        self.assertEqual((self.root / "STATE.md").read_text(), "first")

    async def test_checkpoint_replaces_without_automatic_history_archive(self) -> None:
        self._write_manifest()
        first = await server.checkpoint("project", "uncommitted earlier decision", "missing")
        before = {str(path.relative_to(self.root)) for path in self.root.rglob("*")}
        second = await server.checkpoint("project", "replacement supplied by author", first["revision"])
        self.assertTrue(second["ok"])
        self.assertEqual((self.root / "STATE.md").read_text(), "replacement supplied by author")
        self.assertEqual(before, {str(path.relative_to(self.root)) for path in self.root.rglob("*")})
        committed = subprocess.check_output(["git", "ls-tree", "--name-only", "HEAD"], cwd=self.root)
        self.assertNotIn(b"STATE.md", committed)

    async def test_registration_preserves_existing_manifest_and_handoff_bytes(self) -> None:
        handoff = self.root / "GPT-Agent-Bridge-HANDOFF.md"
        handoff.write_text("existing current state and decisions\n", encoding="utf-8")
        self._write_manifest(current_state=handoff.name)
        manifest = self.root / ".principal/project.json"
        before = (manifest.read_bytes(), handoff.read_bytes())
        result = await server.project_register("project", str(self.root))
        self.assertTrue(result["ok"])
        self.assertTrue(result["onboarding"]["ready"])
        self.assertEqual(result["onboarding"]["current_state"]["path"], handoff.name)
        self.assertEqual(before, (manifest.read_bytes(), handoff.read_bytes()))

    def test_synthetic_manifest_is_canonical(self) -> None:
        root = self.root
        write_canonical_cognition(root)
        manifest = json.loads((root / ".principal/project.json").read_text())
        self.assertEqual(set(manifest), {'rules', 'current_state', 'memory'})
        self.assertNotIn('version', manifest)
        self.assertEqual(manifest['current_state'], '.principal/state.md')
        self.assertEqual(manifest['memory'], '.principal/memory.md')
        self.assertEqual(manifest['rules'], ['AGENTS.md'])
        paths = manifest['rules'] + [manifest['current_state'], manifest['memory']]
        self.assertEqual(len(paths), len(set(paths)))
        for pointer in paths:
            self.assertTrue((root / pointer).is_file())
