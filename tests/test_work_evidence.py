"""Evidence is bound to Work checkout identity, not current Agent narratives."""

import asyncio
import dataclasses
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault("BRIDGE_PATH_TOKEN", "test-token-abcdefghijklmnopqrstuvwxyz-012345")

_import_store = tempfile.TemporaryDirectory(prefix="bridge-test-registry-")
os.environ["BRIDGE_WORKSPACE_STORE_PATH"] = str(Path(_import_store.name) / "registry.json")

import server
from tests.work_observation import delegate_item
import herdr_backend
from evidence_target import EvidenceCheckout
from tests.test_manual_agents import manual_backend
from tests.test_work_surface import git_repo_with_linked_worktree
from workspace_context import WorkspaceRegistry, WorkspaceRegistryStore


class WorkEvidenceTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root, self.linked = git_repo_with_linked_worktree(Path(self.temp.name))
        self.registry = WorkspaceRegistry(self.root, json.dumps({"p": str(self.root), "alias": str(self.linked)}),
            store=WorkspaceRegistryStore(Path(self.temp.name) / "registry.json"))
        self.addCleanup(patch.stopall)
        patch.object(server, "_WORKSPACE_REGISTRY", self.registry).start()
        patch.object(server, "_WORK_REGISTRY", {}).start()
        patch.object(server, "_WORK_WATCHES", {}).start()
        patch.object(server, "_WORK_WATCH_WAITERS", {}).start()
        patch.object(server, "_RESULT_INBOX", {}).start()
        patch.object(server, "_HANDOFF_REGISTRY", {}).start()
        patch.object(server, "_MANUAL_AGENT_CANDIDATES", {}).start()
        # Fixture agents are kind agy; keep the authorized AGY 60s settlement
        # debounce (watch-layer contract, mocked-time tested elsewhere) off the
        # real-time path of these evidence/admission substrate tests.
        patch.object(herdr_backend, "AGY_SETTLEMENT_CONFIRM_SECONDS", 0.0).start()
        patch.object(herdr_backend, "AGY_SETTLEMENT_CONFIRM_ATTEMPTS", 1).start()
        self.project = self.registry.resolve("p")

    def git(self, *args, root=None):
        return subprocess.run(["git", *args], cwd=root or self.root, check=True,
                              capture_output=True).stdout.decode().strip()

    def work(self):
        work = {"project_ref": "p", "workspace_root": str(self.root),
                "execution_identity": "bound", "evidence_checkout": EvidenceCheckout.capture(self.project, str(self.linked))}
        server._WORK_REGISTRY["work-test"] = work
        return work

    async def test_all_tools_follow_saved_checkout_after_handoff_loss(self):
        work = self.work()
        (self.root / "README.md").write_text("root-only\n")
        (self.linked / "README.md").write_text("execution-only\n")
        # No Agent or handoff is required, even for settled Work.
        work["state"] = "agent_turn_settled"
        for call, kwargs in ((server.read, {"path": "README.md"}),
                             (server.search, {"query": "execution-only"}),
                             (server.diff, {"view": "patch"})):
            result = await call(project_ref="p", work_ref="work-test", **kwargs)
            self.assertTrue(result["ok"], result)
            self.assertEqual(result["project_root"], str(self.root))
            self.assertEqual(result["execution_target"], str(self.linked))
            self.assertEqual(result["observation_mode"], "current_worktree")
            if call is server.diff:
                self.assertTrue(result["dirty"])
            else:
                self.assertNotIn("dirty", result)
            self.assertNotIn("state_id", result)
            self.assertNotIn("state_id", result["version"])
            self.assertFalse(result["provenance"]["atomic_snapshot"])
            self.assertIn("execution-only", str(result))
            self.assertNotIn("root-only", str(result))
        default = await server.read("p", "README.md")
        self.assertEqual(default["content"], "root-only\n")
        self.assertEqual(default["target_kind"], "project_root")

    async def test_missing_mismatched_unbound_and_replaced_work_never_fall_back(self):
        work = self.work()
        for call, kwargs in ((server.read, {"path": "README.md"}),
                             (server.search, {"query": "bridge"}), (server.diff, {})):
            self.assertEqual((await call("p", work_ref="missing", **kwargs))["error_type"], "WorkRefUnavailable")
            self.assertEqual((await call("alias", work_ref="work-test", **kwargs))["error_type"], "WorkRefProjectMismatch")
            saved = work.pop("evidence_checkout")
            self.assertEqual((await call("p", work_ref="work-test", **kwargs))["error_type"], "WorkEvidenceTargetUnavailable")
            work["evidence_checkout"] = saved
        moved = self.linked.with_name("original")
        self.linked.rename(moved)
        self.linked.mkdir()
        # Same Git metadata/common-dir at the old path is insufficient: root inode changed.
        (self.linked / ".git").write_bytes((moved / ".git").read_bytes())
        (self.linked / "README.md").write_text("replacement")
        for call, kwargs in ((server.read, {"path": "README.md"}),
                             (server.search, {"query": "replacement"}), (server.diff, {})):
            self.assertEqual((await call("p", work_ref="work-test", **kwargs))["error_type"], "WorkEvidenceTargetChanged")

    async def test_capture_is_frozen_and_rejects_foreign_common_dir(self):
        saved = self.work()["evidence_checkout"]
        with self.assertRaises(dataclasses.FrozenInstanceError):
            saved.root = self.root
        other = Path(self.temp.name) / "other"
        other.mkdir()
        self.git("init", str(other))
        with self.assertRaises(ValueError):
            EvidenceCheckout.capture(self.project, str(other))

    async def test_target_is_revalidated_after_waiting_on_execution_reader_gate(self):
        self.work()
        gate = server._access_gate(self.linked)
        lease = await gate.acquire("writer")
        waiting = asyncio.Event()
        acquire = gate.acquire

        async def observed_acquire(mode):
            self.assertEqual(mode, "reader")
            waiting.set()
            return await acquire(mode)

        with patch.object(gate, "acquire", side_effect=observed_acquire):
            task = asyncio.create_task(server.read("p", "README.md", work_ref="work-test"))
            try:
                await asyncio.wait_for(waiting.wait(), 3)
                self.linked.rename(self.linked.with_name("removed"))
            finally:
                await lease.release()
            result = await task
        self.assertEqual(result["error_type"], "WorkEvidenceTargetChanged")

    async def test_search_colon_newline_filename_continuation_and_exact_read_lines(self):
        self.work()
        filename = "a:b\nodd.py"
        text = "π🙂\r\nneedle first\r\nneedle second\n"
        (self.linked / filename).write_bytes(text.encode())
        self.git("add", "--", filename, root=self.linked)
        (self.linked / "untracked").write_text("needle\n")
        first = await server.search("p", "needle", work_ref="work-test", max_matches=1)
        second = await server.search("p", "needle", work_ref="work-test", max_matches=1,
                                     match_offset=first["match_next_offset"])
        self.assertEqual(first["total_matches"], 2)
        self.assertIsNone(second["match_next_offset"])
        self.assertEqual(first["matches"][0]["path"], filename)
        self.assertEqual(second["matches"][0]["line_number"], 3)
        result = await server.read("p", work_ref="work-test", limit=7, **first["matches"][0]["read_locator"])
        self.assertEqual(result["content_offset"], 4)
        self.assertEqual(result["content_start_line"], 2)
        self.assertEqual(result["content_start_column"], 1)
        self.assertEqual(result["content"], "needle ")
        self.assertEqual(result["file_sha256"], hashlib.sha256(text.encode()).hexdigest())
        rest = await server.read("p", filename, work_ref="work-test", offset=result["content_next_offset"])
        self.assertEqual(result["content"] + rest["content"], text[4:])
        self.assertEqual(rest["content_start_column"], 8)

    async def test_line_validation_eof_and_image_paging(self):
        (self.root / "lines").write_text("one\n")
        for value in (0, -1, True, "2"):
            self.assertEqual((await server.read("p", "lines", start_line=value))["error_type"], "InvalidStartLine")
        self.assertEqual((await server.read("p", "lines", offset=1, start_line=1))["error_type"], "AmbiguousReadPosition")
        self.assertEqual((await server.read("p", "lines", start_line=3))["error_type"], "LineOutOfRange")
        self.assertEqual((await server.read("p", "lines", start_line=2))["content"], "")
        self.assertEqual((await server.read("p", "x.png", start_line=1))["error_type"], "ImagePagingUnsupported")
        self.assertEqual((await server.search("p", "x", match_offset=-1))["error_type"], "InvalidMatchOffset")
        self.assertEqual((await server.search("p", "\0"))["error_type"], "InvalidQuery")

    async def test_end_line_scopes_work_reads_with_preserved_hash_and_failure_semantics(self):
        self.work()
        text = "alpha\nbeta\ngamma\n"
        (self.linked / "scoped.txt").write_text(text)
        digest = hashlib.sha256(text.encode()).hexdigest()
        first = await server.read("p", "scoped.txt", work_ref="work-test",
                                  start_line=1, end_line=2, limit=4)
        self.assertTrue(first["ok"], first)
        self.assertEqual(first["content"], "alph")
        self.assertEqual(first["content_next_offset"], 4)
        self.assertEqual(first["file_sha256"], digest)
        self.assertEqual(first["execution_target"], str(self.linked))
        self.assertEqual(first["target_kind"], "work_checkout")
        # Nonzero-offset continuation repeats the same ceiling with no start_line.
        second = await server.read("p", "scoped.txt", work_ref="work-test",
                                   offset=first["content_next_offset"], end_line=2)
        self.assertEqual(second["content"], "a\nbeta\n")
        self.assertIsNone(second["content_next_offset"])
        self.assertEqual(second["file_sha256"], digest)
        # end_line beyond EOF clamps to the full representation.
        whole = await server.read("p", "scoped.txt", work_ref="work-test", end_line=99)
        self.assertEqual(whole["content"], text)
        self.assertIsNone(whole["content_next_offset"])
        # Failure, gate and version semantics are unchanged under the ceiling.
        for value in (0, True):
            self.assertEqual((await server.read("p", "scoped.txt", work_ref="work-test",
                                                end_line=value))["error_type"], "InvalidEndLine")
        below = await server.read("p", "scoped.txt", work_ref="work-test", start_line=2, end_line=1)
        self.assertEqual(below["error_type"], "InvalidEndLine")
        self.assertEqual((await server.read("p", "scoped.txt", work_ref="work-test",
                                            offset=1, start_line=1))["error_type"], "AmbiguousReadPosition")
        mismatch = await server.read("p", "scoped.txt", work_ref="work-test",
                                     end_line=2, expected_sha256="0" * 64)
        self.assertEqual(mismatch["error_type"], "ReadVersionChanged")
        self.assertNotIn("content", mismatch)
        pinned = await server.read("p", "scoped.txt", work_ref="work-test",
                                   end_line=2, expected_sha256=digest)
        self.assertEqual(pinned["content"], "alpha\nbeta\n")
        self.assertIsNone(pinned["content_next_offset"])
        self.assertEqual((await server.read("p", "missing", work_ref="work-test",
                                            end_line=1))["error_type"], "FileNotFound")

    async def test_revision_diff_is_pinned_and_excludes_dirty_index_worktree(self):
        self.work()
        base = self.git("rev-parse", "HEAD")
        (self.root / "a:b.py").write_text("committed\n")
        self.git("add", "a:b.py")
        self.git("commit", "-m", "second")
        target = self.git("rev-parse", "HEAD")
        (self.linked / "README.md").write_text("DIRTY\n")
        self.git("add", "README.md", root=self.linked)
        summary = await server.diff("p", work_ref="work-test", base=base, target=target)
        self.assertEqual(summary["files"][0]["path"], "a:b.py")
        self.assertEqual(summary["execution_target"], str(self.linked))
        self.assertEqual(summary["observation_mode"], "commit_comparison")
        self.assertEqual(summary["base_commit"], base)
        self.assertEqual(summary["target_commit"], target)
        self.assertEqual(summary["version"], {"base_commit": base, "target_commit": target})
        self.assertNotIn("dirty", summary)
        first = await server.diff("p", base=base, target="HEAD", view="patch", limit=20)
        # Move HEAD; continuation with returned IDs remains the same comparison.
        self.git("commit", "--allow-empty", "-m", "third")
        second = await server.diff("p", base=first["base_commit"], target=first["target_commit"],
                                   view="patch", offset=first["patch_next_offset"])
        full = await server.diff("p", base=base, target=target, view="patch")
        self.assertEqual(first["patch"] + second["patch"], full["patch"])
        self.assertIn("committed", full["patch"])
        self.assertNotIn("DIRTY", full["patch"])
        self.assertEqual((await server.diff("p", base=base))["error_type"], "InvalidRevision")
        self.assertEqual((await server.diff("p", base=base, target=target, staged=True))["error_type"], "AmbiguousDiffMode")
        self.assertEqual((await server.diff("p", base="--help", target=target))["error_type"], "RevisionUnavailable")

    async def test_revision_paths_do_not_follow_current_symlinks_and_summary_pages(self):
        base = self.git("rev-parse", "HEAD")
        (self.root / "one").write_text("one\n")
        (self.root / "two").write_text("two\n")
        self.git("add", "one", "two")
        self.git("commit", "-m", "files")
        target = self.git("rev-parse", "HEAD")
        (self.root / "one").unlink()
        (self.root / "one").symlink_to("two")
        result = await server.diff("p", path="one", base=base, target=target, view="patch")
        self.assertIn("+one", result["patch"])
        self.assertNotIn("+two", result["patch"])
        first = await server.diff("p", base=base, target=target, limit=1)
        second = await server.diff("p", base=base, target=target, limit=1, offset=first["files_next_offset"])
        self.assertEqual([first["files"][0]["path"], second["files"][0]["path"]], ["one", "two"])
        self.assertIsNone(second["files_next_offset"])
        self.assertEqual((await server.diff("p", path="../outside", base=base, target=target))["error_type"], "InvalidPath")

    async def test_native_image_has_work_provenance(self):
        self.work()
        # Existing image contract verifies magic, not image-library decoding.
        (self.linked / "example.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"\0" * 16)
        result = await server.read("p", "example.png", work_ref="work-test")
        self.assertIsInstance(result, list)
        metadata = result[1]
        self.assertEqual(metadata["execution_target"], str(self.linked))
        self.assertEqual(metadata["project_root"], str(self.root))
        self.assertEqual(metadata["pagination"]["unit"], "whole_image")
        self.assertEqual(metadata["provenance"]["proves"], "observed_content_only")

    async def test_real_delegate_captures_only_writer_gated_refreshed_checkout(self):
        backend, state = manual_backend(self.root)
        with patch.object(server, "_WORKSPACE_BACKENDS", {str(self.root): backend}):
            context = await server.context("p")
            agent = context["agents"][0]["handle"]
            original = server._reserve_work
            reserved = asyncio.Event()

            def reserve(*args, **kwargs):
                result = original(*args, **kwargs)
                reserved.set()
                return result

            lease = await server._access_gate(self.root).acquire("writer")
            with patch.object(server, "_reserve_work", side_effect=reserve):
                task = asyncio.create_task(delegate_item("p", assignments=[{'agent_ref': agent, 'task': "capture evidence"}]))
                try:
                    await asyncio.wait_for(reserved.wait(), 3)
                    work = next(iter(server._WORK_REGISTRY.values()))
                    self.assertNotIn("evidence_checkout", work)
                    state["agent"]["cwd"] = str(self.linked)
                    state["agent"]["foreground_cwd"] = str(self.linked)
                finally:
                    await lease.release()
                response = await task
            self.assertTrue(response["ok"], response)
            work = server._WORK_REGISTRY[response["work_ref"]]
            self.assertEqual(work["evidence_checkout"].root, self.linked)
            watcher = server._HANDOFF_REGISTRY[work["handoff_id"]]["watcher_task"]
            await watcher
            server._HANDOFF_REGISTRY.clear()
            state["agent"]["cwd"] = str(self.root)
            state["agent"]["foreground_cwd"] = str(self.root)
            result = await server.read("p", "README.md", work_ref=response["work_ref"])
            self.assertEqual(result["execution_target"], str(self.linked))
