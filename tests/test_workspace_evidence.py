"""Tests for direct workspace evidence: workspace_diff, workspace_read, workspace_search."""

from __future__ import annotations

import asyncio
import hashlib
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault(
    "BRIDGE_PATH_TOKEN",
    "test-token-abcdefghijklmnopqrstuvwxyz-012345",
)

import server
import fixed_git
from workspace_context import (
    GitWorktreeIdentity,
    WorkspaceContext,
    WorkspaceRegistry,
    canonical_git_worktree,
)


def _init_git_repo(path: Path) -> None:
    subprocess.run(["git", "init", "-b", "main"], cwd=str(path), check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=str(path), check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=str(path), check=True, capture_output=True)
    # create initial commit
    init_file = path / "README.md"
    init_file.write_text("# Test Repo\nInitial content\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=str(path), check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "Initial commit"], cwd=str(path), check=True, capture_output=True)


class WorkspaceEvidenceTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self._temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self._temp_dir.name).resolve()
        _init_git_repo(self.root)
        _, self.git_identity = canonical_git_worktree(self.root)

        self._named_dir = tempfile.TemporaryDirectory()
        self.named_root = Path(self._named_dir.name).resolve()
        _init_git_repo(self.named_root)
        _, self.named_git_identity = canonical_git_worktree(self.named_root)

        registry_data = {
            "named": str(self.named_root),
        }
        self.registry = WorkspaceRegistry(
            default_root=self.root,
            raw=os.environ.get("NONEXISTENT_ENV_KEY"),
        )
        self.registry._entries["test-root"] = (self.root, self.git_identity)
        self.registry._entries["named"] = (self.named_root, self.named_git_identity)

    def tearDown(self) -> None:
        self._temp_dir.cleanup()
        self._named_dir.cleanup()

    # -----------------------------------------------------------------------
    # Path validation & traversal security
    # -----------------------------------------------------------------------

    def test_validate_path_traversal_and_git_rejection(self) -> None:
        # Traversal
        with self.assertRaises(ValueError):
            server._validate_workspace_relative_path(self.root, "../secret.txt")
        with self.assertRaises(ValueError):
            server._validate_workspace_relative_path(self.root, "foo/../../secret.txt")
        # Absolute
        with self.assertRaises(ValueError):
            server._validate_workspace_relative_path(self.root, "/etc/passwd")
        # .git internals
        with self.assertRaises(ValueError):
            server._validate_workspace_relative_path(self.root, ".git")
        with self.assertRaises(ValueError):
            server._validate_workspace_relative_path(self.root, ".git/config")
        with self.assertRaises(ValueError):
            server._validate_workspace_relative_path(self.root, "sub/.git/HEAD")
        # Empty
        with self.assertRaises(ValueError):
            server._validate_workspace_relative_path(self.root, "")

    def test_validate_path_symlink_out_of_root_rejected(self) -> None:
        external_file = Path(tempfile.gettempdir()) / "outside_root.txt"
        external_file.write_text("outside", encoding="utf-8")
        symlink_file = self.root / "symlink_outside.txt"
        try:
            os.symlink(external_file, symlink_file)
            with self.assertRaises(ValueError):
                server._validate_workspace_relative_path(self.root, "symlink_outside.txt")
        finally:
            if symlink_file.exists():
                symlink_file.unlink()
            if external_file.exists():
                external_file.unlink()

    # -----------------------------------------------------------------------
    # workspace_diff tests
    # -----------------------------------------------------------------------

    async def test_workspace_diff_clean_summary(self) -> None:
        with patch.object(server, "ROOT", self.root), patch.object(server, "_WORKSPACE_REGISTRY", self.registry):
            result = await server.diff(project_ref="test-root")
            self.assertTrue(result["ok"])
            self.assertEqual(result["view"], "summary")
            self.assertTrue(result["is_clean"])
            self.assertEqual(result["counts"]["total"], 0)
            self.assertEqual(result["counts"]["staged"], 0)
            self.assertEqual(result["counts"]["unstaged"], 0)
            self.assertEqual(result["counts"]["untracked"], 0)
            self.assertEqual(result["provenance"]["source"], "git_worktree")
            self.assertEqual(result["coverage"]["ignored_files"], "excluded")

    async def test_workspace_diff_dirty_summary_with_untracked(self) -> None:
        # Create an untracked file, an unstaged modification, and a staged addition
        (self.root / "untracked.txt").write_text("new untracked file\n", encoding="utf-8")
        (self.root / "README.md").write_text("# Test Repo\nModified line\n", encoding="utf-8")
        (self.root / "staged.txt").write_text("staged file\n", encoding="utf-8")
        subprocess.run(["git", "add", "staged.txt"], cwd=str(self.root), check=True, capture_output=True)

        with patch.object(server, "ROOT", self.root), patch.object(server, "_WORKSPACE_REGISTRY", self.registry):
            result = await server.diff(project_ref="test-root")
            self.assertTrue(result["ok"])
            self.assertFalse(result["is_clean"])
            self.assertEqual(result["counts"]["staged"], 1)
            self.assertEqual(result["counts"]["unstaged"], 1)
            self.assertEqual(result["counts"]["untracked"], 1)
            self.assertEqual(result["counts"]["total"], 3)

            paths = [f["path"] for f in result["files"]]
            self.assertIn("untracked.txt", paths)
            self.assertIn("README.md", paths)
            self.assertIn("staged.txt", paths)

    async def test_workspace_diff_patch_view_and_pagination(self) -> None:
        (self.root / "README.md").write_text("# Test Repo\nModified content line 1\nModified line 2\n", encoding="utf-8")
        with patch.object(server, "ROOT", self.root), patch.object(server, "_WORKSPACE_REGISTRY", self.registry):
            # Read first small page
            page1 = await server.diff(view="patch", limit=20, project_ref="test-root")
            self.assertTrue(page1["ok"])
            self.assertEqual(page1["view"], "patch")
            self.assertTrue(page1["has_changes"])
            self.assertEqual(page1["patch_limit"], 20)
            self.assertEqual(page1["patch_offset"], 0)
            self.assertEqual(page1["patch_page_chars"], 20)
            self.assertTrue(page1["patch_has_more"])
            self.assertIsNotNone(page1["patch_next_offset"])

            # Read next page
            next_off = page1["patch_next_offset"]
            page2 = await server.diff(view="patch", offset=next_off, limit=200, project_ref="test-root")
            self.assertTrue(page2["ok"])
            self.assertEqual(page2["patch_offset"], next_off)
            self.assertFalse(page2["patch_has_more"])

    async def test_workspace_diff_untracked_file_synthetic_patch(self) -> None:
        (self.root / "new_doc.md").write_text("Line 1\nLine 2\n", encoding="utf-8")
        with patch.object(server, "ROOT", self.root), patch.object(server, "_WORKSPACE_REGISTRY", self.registry):
            result = await server.diff(path="new_doc.md", view="patch", project_ref="test-root")
            self.assertTrue(result["ok"])
            self.assertTrue(result["untracked"])
            self.assertTrue(result["has_changes"])
            self.assertIn("--- /dev/null", result["patch"])
            self.assertIn("+++ b/new_doc.md", result["patch"])
            self.assertIn("+Line 1", result["patch"])
            self.assertIn("+Line 2", result["patch"])

    async def test_workspace_diff_fresh_summary_observes_untracked_addition(self) -> None:
        with patch.object(server, "ROOT", self.root), patch.object(server, "_WORKSPACE_REGISTRY", self.registry):
            initial = await server.diff(project_ref="test-root")
            self.assertTrue(initial["is_clean"])
            self.assertFalse(initial["dirty"])
            self.assertEqual(initial["files"], [])

            # Mutate repo
            (self.root / "another.txt").write_text("hello\n", encoding="utf-8")
            after_mod = await server.diff(project_ref="test-root")
            self.assertFalse(after_mod["is_clean"])
            self.assertTrue(after_mod["dirty"])
            self.assertEqual(after_mod["counts"]["untracked"], 1)
            self.assertEqual(after_mod["files"][0]["path"], "another.txt")
            self.assertTrue(after_mod["files"][0]["is_untracked"])
            self.assertNotIn("state_id", after_mod)
            self.assertNotIn("state_id", after_mod["version"])

    async def test_workspace_diff_patch_changes_with_dirty_content_at_same_status(self) -> None:
        readme = self.root / "README.md"
        with patch.object(server, "ROOT", self.root), patch.object(server, "_WORKSPACE_REGISTRY", self.registry):
            readme.write_text("# Test Repo\nDirty content A\n", encoding="utf-8")
            first = await server.diff(project_ref="test-root")
            first_patch = await server.diff(project_ref="test-root", view="patch")
            readme.write_text("# Test Repo\nDirty content B\n", encoding="utf-8")
            second = await server.diff(project_ref="test-root")
            second_patch = await server.diff(project_ref="test-root", view="patch")

        self.assertFalse(first["is_clean"])
        self.assertFalse(second["is_clean"])
        self.assertEqual(first["files"][0]["unstaged_status"], "M")
        self.assertEqual(second["files"][0]["unstaged_status"], "M")
        self.assertIn("+Dirty content A\n", first_patch["patch"])
        self.assertIn("+Dirty content B\n", second_patch["patch"])
        self.assertNotIn("Dirty content A", second_patch["patch"])
        self.assertNotEqual(first_patch["patch"], second_patch["patch"])
        self.assertNotIn("state_id", second_patch)

    async def test_workspace_diff_staged_patch_changes_with_blob_at_same_status(self) -> None:
        readme = self.root / "README.md"
        with patch.object(server, "ROOT", self.root), patch.object(server, "_WORKSPACE_REGISTRY", self.registry):
            readme.write_text("# Test Repo\nStaged content A\n", encoding="utf-8")
            subprocess.run(["git", "add", "README.md"], cwd=str(self.root), check=True, capture_output=True)
            first = await server.diff(project_ref="test-root")
            first_patch = await server.diff(project_ref="test-root", view="patch", staged=True)
            readme.write_text("# Test Repo\nStaged content B\n", encoding="utf-8")
            subprocess.run(["git", "add", "README.md"], cwd=str(self.root), check=True, capture_output=True)
            second = await server.diff(project_ref="test-root")
            second_patch = await server.diff(project_ref="test-root", view="patch", staged=True)
            unstaged_patch = await server.diff(project_ref="test-root", view="patch")

        self.assertEqual(first["files"][0]["staged_status"], "M")
        self.assertEqual(second["files"][0]["staged_status"], "M")
        self.assertIsNone(first["files"][0]["unstaged_status"])
        self.assertIsNone(second["files"][0]["unstaged_status"])
        self.assertIn("+Staged content A\n", first_patch["patch"])
        self.assertIn("+Staged content B\n", second_patch["patch"])
        self.assertNotIn("Staged content A", second_patch["patch"])
        self.assertNotEqual(first_patch["patch"], second_patch["patch"])
        self.assertEqual(unstaged_patch["patch"], "")
        self.assertFalse(unstaged_patch["has_changes"])
        self.assertTrue(unstaged_patch["dirty"])  # Checkout status still includes index changes.

    async def test_workspace_diff_named_workspace(self) -> None:
        (self.named_root / "named_change.txt").write_text("named workspace\n", encoding="utf-8")
        with patch.object(server, "ROOT", self.root), patch.object(server, "_WORKSPACE_REGISTRY", self.registry):
            result = await server.diff(project_ref="named")
            self.assertTrue(result["ok"])
            self.assertEqual(result["workspace_ref"], "named")
            self.assertEqual(result["canonical_root"], str(self.named_root))
            self.assertEqual(result["counts"]["untracked"], 1)

            # Unauthorized workspace
            unauth = await server.diff(project_ref="unknown_ref")
            self.assertFalse(unauth["ok"])
            self.assertEqual(unauth["error_type"], "ProjectRefUnauthorized")

    # -----------------------------------------------------------------------
    # workspace_read tests
    # -----------------------------------------------------------------------

    async def test_workspace_read_basic_and_pagination(self) -> None:
        content = "Line 1\nLine 2\nLine 3\nLine 4\n"
        (self.root / "sample.txt").write_text(content, encoding="utf-8")

        with patch.object(server, "ROOT", self.root), patch.object(server, "_WORKSPACE_REGISTRY", self.registry):
            # Page 1
            page1 = await server.read(path="sample.txt", offset=0, limit=10, project_ref="test-root")
            self.assertTrue(page1["ok"])
            self.assertEqual(page1["path"], "sample.txt")
            self.assertEqual(page1["content"], content[:10])
            self.assertEqual(page1["content_page_chars"], 10)
            self.assertEqual(page1["content_total_chars"], len(content))
            self.assertTrue(page1["content_has_more"])
            self.assertEqual(page1["content_next_offset"], 10)
            self.assertEqual(page1["file_sha256"], hashlib.sha256(content.encode("utf-8")).hexdigest())

            # Page 2
            page2 = await server.read(path="sample.txt", offset=10, limit=50, project_ref="test-root",
                                      expected_sha256=page1["file_sha256"])
            self.assertTrue(page2["ok"])
            self.assertEqual(page2["content"], content[10:])
            self.assertFalse(page2["content_has_more"])
            self.assertIsNone(page2["content_next_offset"])
            self.assertEqual(page1["file_sha256"], page2["file_sha256"])

    async def test_workspace_read_rejects_binary(self) -> None:
        (self.root / "binary.dat").write_bytes(b"hello\x00world\xff\xfe")
        with patch.object(server, "ROOT", self.root), patch.object(server, "_WORKSPACE_REGISTRY", self.registry):
            result = await server.read(path="binary.dat", project_ref="test-root")
            self.assertFalse(result["ok"])
            self.assertEqual(result["error_type"], "BinaryFileUnsupported")
            self.assertTrue(result["binary"])

    async def test_workspace_read_rejects_missing_and_directories(self) -> None:
        (self.root / "subdir").mkdir()
        with patch.object(server, "ROOT", self.root), patch.object(server, "_WORKSPACE_REGISTRY", self.registry):
            missing = await server.read(path="nonexistent.txt", project_ref="test-root")
            self.assertFalse(missing["ok"])
            self.assertEqual(missing["error_type"], "FileNotFound")

            dir_read = await server.read(path="subdir", project_ref="test-root")
            self.assertFalse(dir_read["ok"])
            self.assertEqual(dir_read["error_type"], "NotARegularFile")

    async def test_workspace_read_named_workspace(self) -> None:
        (self.named_root / "named_file.txt").write_text("Hello Named\n", encoding="utf-8")
        with patch.object(server, "ROOT", self.root), patch.object(server, "_WORKSPACE_REGISTRY", self.registry):
            result = await server.read(path="named_file.txt", project_ref="named")
            self.assertTrue(result["ok"])
            self.assertEqual(result["content"], "Hello Named\n")
            self.assertEqual(result["workspace_ref"], "named")

    # -----------------------------------------------------------------------
    # workspace_search tests
    # -----------------------------------------------------------------------

    async def test_workspace_search_fixed_string(self) -> None:
        (self.root / "src").mkdir()
        (self.root / "src" / "code.py").write_text("def find_me_symbol():\n    return 42\n", encoding="utf-8")
        (self.root / "src" / "other.py").write_text("# find_me_symbol is defined elsewhere\n", encoding="utf-8")
        subprocess.run(["git", "add", "src"], cwd=str(self.root), check=True, capture_output=True)
        subprocess.run(["git", "commit", "-m", "Add src"], cwd=str(self.root), check=True, capture_output=True)

        with patch.object(server, "ROOT", self.root), patch.object(server, "_WORKSPACE_REGISTRY", self.registry):
            # Normal search
            result = await server.search(query="find_me_symbol", project_ref="test-root")
            self.assertTrue(result["ok"])
            self.assertEqual(result["match_count"], 2)
            self.assertFalse(result["matches_truncated"])
            paths = [m["path"] for m in result["matches"]]
            self.assertIn("src/code.py", paths)
            self.assertIn("src/other.py", paths)

            # Search with path_prefix
            prefix_res = await server.search(query="find_me_symbol", path_prefix="src/code.py", project_ref="test-root")
            self.assertTrue(prefix_res["ok"])
            self.assertEqual(prefix_res["match_count"], 1)
            self.assertEqual(prefix_res["matches"][0]["path"], "src/code.py")

            # Search with no match
            no_match = await server.search(query="nonexistent_string_12345", project_ref="test-root")
            self.assertTrue(no_match["ok"])
            self.assertEqual(no_match["match_count"], 0)
            self.assertEqual(len(no_match["matches"]), 0)

    async def test_workspace_search_excludes_untracked_and_ignored(self) -> None:
        (self.root / "untracked.py").write_text("TARGET_SYMBOL = 1\n", encoding="utf-8")
        (self.root / ".gitignore").write_text("ignored.py\n", encoding="utf-8")
        (self.root / "ignored.py").write_text("TARGET_SYMBOL = 2\n", encoding="utf-8")
        subprocess.run(["git", "add", ".gitignore"], cwd=str(self.root), check=True, capture_output=True)
        subprocess.run(["git", "commit", "-m", "Add gitignore"], cwd=str(self.root), check=True, capture_output=True)

        with patch.object(server, "ROOT", self.root), patch.object(server, "_WORKSPACE_REGISTRY", self.registry):
            result = await server.search(query="TARGET_SYMBOL", project_ref="test-root")
            self.assertTrue(result["ok"])
            self.assertEqual(result["match_count"], 0)
            self.assertEqual(result["coverage"]["untracked_files"], "excluded")
            self.assertEqual(result["coverage"]["ignored_files"], "excluded_unless_tracked")

    async def test_workspace_search_max_matches_truncation(self) -> None:
        (self.root / "many.txt").write_text("match\nmatch\nmatch\nmatch\nmatch\n", encoding="utf-8")
        subprocess.run(["git", "add", "many.txt"], cwd=str(self.root), check=True, capture_output=True)
        subprocess.run(["git", "commit", "-m", "Add many.txt"], cwd=str(self.root), check=True, capture_output=True)

        with patch.object(server, "ROOT", self.root), patch.object(server, "_WORKSPACE_REGISTRY", self.registry):
            result = await server.search(query="match", max_matches=3, project_ref="test-root")
            self.assertTrue(result["ok"])
            self.assertEqual(result["match_count"], 3)
            self.assertTrue(result["matches_truncated"])
            self.assertEqual(result["total_matches"], 5)

    # -----------------------------------------------------------------------
    # Direct evidence from fresh diff, read and search observations
    # -----------------------------------------------------------------------

    async def test_workspace_read_and_search_observe_changed_body_hash_and_matches(self) -> None:
        with patch.object(server, "ROOT", self.root), patch.object(server, "_WORKSPACE_REGISTRY", self.registry):
            # Clean baseline
            diff_clean = await server.diff(project_ref="test-root")
            search_clean = await server.search(query="Initial", project_ref="test-root")
            read_clean = await server.read(path="README.md", project_ref="test-root")

            self.assertTrue(diff_clean["is_clean"])
            self.assertEqual(search_clean["matches"][0]["line_text"], "Initial content")
            self.assertEqual(read_clean["content"], "# Test Repo\nInitial content\n")
            self.assertEqual(read_clean["file_sha256"], hashlib.sha256(read_clean["content"].encode()).hexdigest())

            # Mutate worktree: add untracked file + unstaged edit
            (self.root / "new_untracked.txt").write_text("untracked\n", encoding="utf-8")
            (self.root / "README.md").write_text("# Test Repo\nModified content\n", encoding="utf-8")

            diff_dirty = await server.diff(project_ref="test-root")
            search_dirty = await server.search(query="Initial", project_ref="test-root")
            read_dirty = await server.read(path="README.md", project_ref="test-root")
            changed_matches = await server.search(query="Modified", project_ref="test-root")
            pinned_read = await server.read(path="README.md", project_ref="test-root",
                                            expected_sha256=read_clean["file_sha256"])

            self.assertFalse(diff_dirty["is_clean"])
            self.assertEqual({f["path"] for f in diff_dirty["files"]}, {"README.md", "new_untracked.txt"})
            self.assertEqual(search_dirty["matches"], [])
            self.assertEqual(changed_matches["matches"][0]["line_text"], "Modified content")
            self.assertEqual(changed_matches["matches"][0]["read_locator"],
                             {"path": "README.md", "start_line": 2})
            self.assertEqual(read_dirty["content"], "# Test Repo\nModified content\n")
            self.assertEqual(read_dirty["file_sha256"], hashlib.sha256(read_dirty["content"].encode()).hexdigest())
            self.assertNotEqual(read_clean["file_sha256"], read_dirty["file_sha256"])
            self.assertEqual(pinned_read["error_type"], "ReadVersionChanged")
            self.assertEqual(pinned_read["actual_sha256"], read_dirty["file_sha256"])
            self.assertNotIn("content", pinned_read)

    async def test_workspace_read_selected_file_body_and_sha256_are_specific(self) -> None:
        (self.root / "file_a.txt").write_text("Content A\n", encoding="utf-8")
        (self.root / "file_b.txt").write_text("Content B\n", encoding="utf-8")
        subprocess.run(["git", "add", "file_a.txt", "file_b.txt"], cwd=str(self.root), check=True, capture_output=True)
        subprocess.run(["git", "commit", "-m", "Add files"], cwd=str(self.root), check=True, capture_output=True)

        with patch.object(server, "ROOT", self.root), patch.object(server, "_WORKSPACE_REGISTRY", self.registry):
            read_a = await server.read(path="file_a.txt", project_ref="test-root")
            read_b = await server.read(path="file_b.txt", project_ref="test-root")

            self.assertTrue(read_a["ok"])
            self.assertTrue(read_b["ok"])
            self.assertEqual(read_a["content"], "Content A\n")
            self.assertEqual(read_b["content"], "Content B\n")
            self.assertEqual(read_a["file_sha256"], hashlib.sha256(b"Content A\n").hexdigest())
            self.assertEqual(read_b["file_sha256"], hashlib.sha256(b"Content B\n").hexdigest())
            self.assertNotEqual(read_a["file_sha256"], read_b["file_sha256"])
            (self.root / "unrelated.txt").write_text("unrelated mutation\n")
            pinned_a = await server.read(path="file_a.txt", project_ref="test-root",
                                         expected_sha256=read_a["file_sha256"])
            self.assertEqual(pinned_a["content"], read_a["content"])
            wrong_file = await server.read(path="file_b.txt", project_ref="test-root",
                                           expected_sha256=read_a["file_sha256"])
            self.assertEqual(wrong_file["error_type"], "ReadVersionChanged")
            self.assertNotIn("content", wrong_file)

    async def test_search_and_current_diff_continuations_are_fresh_unpinned_observations(self) -> None:
        selected = self.root / "README.md"
        selected.write_text("match old first\nmatch old second\n")
        with patch.object(server, "_WORKSPACE_REGISTRY", self.registry):
            first = await server.search("test-root", "match", max_matches=1)
            patch_first = await server.diff("test-root", path="README.md", view="patch", limit=10)
            self.assertEqual(first["matches"][0]["line_text"], "match old first")
            selected.write_text("match new first\nmatch new second\n")
            second = await server.search("test-root", "match", max_matches=1,
                                         match_offset=first["match_next_offset"])
            patch_second = await server.diff("test-root", path="README.md", view="patch",
                                              offset=patch_first["patch_next_offset"])
            current = await server.diff("test-root", path="README.md", view="patch")
            self.assertEqual(second["matches"][0]["line_text"], "match new second")
            self.assertEqual(patch_second["patch"], current["patch"][patch_first["patch_next_offset"]:])
            self.assertIn("+match new second\n", patch_second["patch"])
            self.assertNotIn("match old", patch_second["patch"])
            for result in (first, second, patch_first, patch_second):
                self.assertEqual(result["observation_mode"], "current_worktree")
                self.assertFalse(result["provenance"]["atomic_snapshot"])
                self.assertNotIn("state_id", result)
                self.assertNotIn("state_id", result["version"])

    # -----------------------------------------------------------------------
    # MCP schema check
    # -----------------------------------------------------------------------

    async def test_narrow_observations_do_not_open_or_hash_unrelated_bodies(self) -> None:
        from tests.test_vnext_surface import TINY_PNG

        selected = b"selected evidence\n"
        (self.root / "selected.txt").write_bytes(selected)
        (self.root / "unrelated-dirty.txt").write_text("committed baseline\n")
        subprocess.run(["git", "add", "."], cwd=self.root, check=True, capture_output=True)
        subprocess.run(["git", "commit", "-m", "fixture"], cwd=self.root, check=True, capture_output=True)
        (self.root / "unrelated-dirty.txt").write_text("unrelated dirty body\n")
        (self.root / "unrelated-untracked.txt").write_text("unrelated untracked body\n")
        (self.root / "selected.png").write_bytes(TINY_PNG)
        unrelated = {"unrelated-dirty.txt", "unrelated-untracked.txt"}
        path_open, fd_open, sha256 = Path.open, os.open, hashlib.sha256

        def guarded_path_open(path, *args, **kwargs):
            self.assertNotIn(path.name, unrelated, "metadata opened an unrelated body")
            return path_open(path, *args, **kwargs)

        def guarded_fd_open(path, *args, **kwargs):
            self.assertNotIn(Path(os.fsdecode(path)).name, unrelated,
                             "metadata opened an unrelated body")
            return fd_open(path, *args, **kwargs)

        with patch.object(server, "_WORKSPACE_REGISTRY", self.registry):
            for call, kwargs, body in (
                (server.read, {"path": "selected.txt"}, selected),
                (server.read, {"path": "selected.png"}, TINY_PNG),
                (server.search, {"query": "selected", "path_prefix": "selected.txt"}, None),
            ):
                with self.subTest(call=call.__name__, kwargs=kwargs), \
                        patch.object(Path, "open", guarded_path_open), \
                        patch.object(os, "open", side_effect=guarded_fd_open), \
                        patch.object(fixed_git, "observe", wraps=fixed_git.observe) as queries, \
                        patch.object(hashlib, "sha256", wraps=sha256) as hashes:
                    result = await call(project_ref="test-root", **kwargs)
                    metadata = result[-1] if isinstance(result, list) else result
                    self.assertTrue(metadata["ok"], metadata)
                    self.assertNotIn("state_id", metadata)
                    self.assertNotIn("state_id", metadata["version"])
                    self.assertNotIn("dirty", metadata)
                    for query in queries.call_args_list:
                        self.assertFalse({"status", "ls-files", "diff"}.intersection(query.args[1]), query)
                    if body is not None:
                        self.assertEqual(metadata["file_sha256"], sha256(body).hexdigest())
                        self.assertEqual([c.args for c in hashes.call_args_list], [(body,)])
                    else:
                        hashes.assert_not_called()
                        self.assertEqual(metadata["matches"][0]["line_text"], "selected evidence")


if __name__ == "__main__":
    unittest.main()
