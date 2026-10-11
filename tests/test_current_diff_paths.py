"""Current diff paths are exact read locators, including in a frozen linked Work."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault("BRIDGE_PATH_TOKEN", "test-token-abcdefghijklmnopqrstuvwxyz-012345")
import server
import fixed_git
from evidence_target import EvidenceCheckout
from workspace_context import WorkspaceRegistry, WorkspaceRegistryStore


class CurrentDiffPathsTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "main"
        self.root.mkdir()
        self.linked = Path(self.temp.name) / "linked"
        self.git("init", "-b", "main")
        (self.root / "README.md").write_text("original\n")
        (self.root / ".gitignore").write_text("ignored/\n")
        self.git("add", ".")
        self.git("commit", "-m", "initial")
        self.git("worktree", "add", "-b", "linked", str(self.linked))
        registry = WorkspaceRegistry(self.root, json.dumps({"p": str(self.root)}),
            store=WorkspaceRegistryStore(Path(self.temp.name) / "registry.json"))
        for name, value in (("_WORKSPACE_REGISTRY", registry), ("_WORK_REGISTRY", {}), ("_RESULT_INBOX", {})):
            patcher = patch.object(server, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        server._WORK_REGISTRY["frozen"] = {
            "project_ref": "p", "workspace_root": str(self.root),
            "execution_identity": "bound",
            "evidence_checkout": EvidenceCheckout.capture(registry.resolve("p"), str(self.linked)),
        }

    def git(self, *args, root=None, input=None):
        # Identity and hooks policy are command-local, never written to Git config.
        return subprocess.run(["git", "--no-optional-locks", "-c", "core.hooksPath=/dev/null",
            "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid", *args],
            cwd=root or self.root, input=input, capture_output=True, check=True).stdout

    async def test_main_and_linked_exact_paths_summary_to_read_and_pagination(self):
        names = [' space ', 'quote".txt', 'tab\tfile', 'line\nfile', 'arrow -> file', '中文.txt',
                 'new/nested\nfile', ':(glob)*.txt']
        for root, work_ref in ((self.root, None), (self.linked, "frozen")):
            with self.subTest(root=root):
                for number, name in enumerate(names):
                    path = root / name
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text(f"{root.name} {number}\n")
                self.git("add", "--", *names[:3], root=root)
                (root / "ignored").mkdir()
                (root / "ignored/hidden").write_text("excluded")
                entries, offset = [], 0
                while True:
                    page = await server.diff("p", work_ref=work_ref, offset=offset, limit=2)
                    self.assertTrue(page["ok"], page)
                    self.assertEqual(page["counts"]["total"], len(names))
                    self.assertEqual(page["execution_target"], str(root))
                    self.assertFalse(page["provenance"]["atomic_snapshot"])
                    entries.extend(page["files"])
                    offset = page["files_next_offset"]
                    self.assertEqual(page["files_truncated"], offset is not None)
                    if offset is None:
                        break
                self.assertEqual({e["path"] for e in entries}, set(names))
                self.assertEqual(len(entries), len(names))
                for entry in entries:
                    read = await server.read("p", entry["path"], work_ref=work_ref)
                    self.assertTrue(read["ok"], read)
                    self.assertEqual(read["content"], (root / entry["path"]).read_text())
                synthetic = await server.diff("p", path='new/nested\nfile', view="patch", work_ref=work_ref)
                self.assertTrue(synthetic["ok"], synthetic)
                self.assertTrue(synthetic["untracked"])
                self.assertIn(f"+{root.name} 6", synthetic["patch"])

    async def test_rename_both_paths_numstat_staged_unstaged_deleted_and_binary(self):
        old, new = 'old\n\t" name', 'new\n\t" name'
        for name, content in ((old, b"same\n"), ("delete\nme", b"gone\n"), ("binary\tfile", b"\0before")):
            (self.linked / name).write_bytes(content)
        self.git("add", ".", root=self.linked)
        self.git("commit", "-m", "files", root=self.linked)
        self.git("mv", "--", old, new, root=self.linked)
        (self.linked / new).write_text("same\nextra\n")
        (self.linked / "delete\nme").unlink()
        (self.linked / "binary\tfile").write_bytes(b"\0after")
        (self.linked / "README.md").write_text("staged\n")
        self.git("add", "README.md", root=self.linked)
        (self.linked / "README.md").write_text("unstaged\n")
        result = await server.diff("p", work_ref="frozen")
        self.assertTrue(result["ok"], result)
        entries = {e["path"]: e for e in result["files"]}
        self.assertEqual(set(entries), {new, "delete\nme", "binary\tfile", "README.md"})
        self.assertEqual(entries[new]["original_path"], old)
        self.assertEqual((entries[new]["staged_status"], entries[new]["unstaged_status"]), ("R", "M"))
        self.assertEqual((entries[new]["insertions"], entries[new]["deletions"]), (1, 0))
        self.assertEqual(entries["delete\nme"]["unstaged_status"], "D")
        self.assertEqual(entries["delete\nme"]["deletions"], 1)
        self.assertIsNone(entries["binary\tfile"]["insertions"])
        self.assertIsNone(entries["binary\tfile"]["deletions"])
        self.assertEqual((entries["README.md"]["insertions"], entries["README.md"]["deletions"]), (2, 2))
        for path in (old, new):
            filtered = await server.diff("p", path=path, work_ref="frozen")
            self.assertEqual([e["path"] for e in filtered["files"]], [new])
        self.assertEqual((await server.read("p", new, work_ref="frozen"))["content"], "same\nextra\n")
        staged = await server.diff("p", work_ref="frozen", staged=True)
        self.assertEqual(staged["files"], result["files"])  # Existing summary is combined.
        for staged, present, absent in ((True, "+staged", "+unstaged"), (False, "+unstaged", "+staged")):
            response = await server.diff("p", path="README.md", view="patch", staged=staged, work_ref="frozen")
            self.assertIn(present, response["patch"])
            self.assertNotIn(absent, response["patch"])
        self.git("add", "-A", root=self.linked)
        staged_delete = await server.diff("p", work_ref="frozen")
        deleted = next(e for e in staged_delete["files"] if e["path"] == "delete\nme")
        self.assertEqual(deleted["staged_status"], "D")
        self.assertIsNone(deleted["unstaged_status"])

    async def test_literal_patch_path_and_no_external_diff_or_textconv(self):
        name = ':(glob)*.txt'
        (self.root / name).write_text("one\n")
        (self.root / "other.txt").write_text("other\n")
        self.git("add", ".")
        self.git("commit", "-m", "literal paths")
        (self.root / name).write_text("two\n")
        (self.root / "other.txt").write_text("unrelated\n")
        with patch.dict(os.environ, {"GIT_EXTERNAL_DIFF": "/must-not-execute"}):
            result = await server.diff("p", path=name, view="patch")
        self.assertTrue(result["ok"], result)
        self.assertIn("+two", result["patch"])
        self.assertNotIn("unrelated", result["patch"])

    async def test_observation_limits_and_numstat_failure_do_not_claim_coverage(self):
        (self.root / "new\nfile").write_text("content\n")
        with patch.object(server, "MAX_CURRENT_DIFF_CAPTURE_BYTES", 4):
            result = await server.diff("p")
        self.assertFalse(result["ok"], result)
        self.assertEqual(result["error_type"], "DiffObservationTooLarge")
        self.assertNotIn("is_clean", result)
        with patch.object(server, "MAX_WORKSPACE_FILE_SIZE", 4):
            result = await server.diff("p", path="new\nfile", view="patch")
        self.assertEqual(result["error_type"], "FileTooLarge")
        actual = server._git_run_bytes_bounded
        for answer in ((1, b"", b"numstat failed"), (0, b"1\t0\t\0old\0", b""),
                       (0, b"1\t0\tbroken", b""), (0, b"?\t0\tx\0", b"")):
            def observe(*args, **kwargs):
                return answer if "--numstat" in args else actual(*args, **kwargs)
            with self.subTest(answer=answer), patch.object(server, "_git_run_bytes_bounded", side_effect=observe):
                result = await server.diff("p")
                self.assertFalse(result["ok"], result)
                self.assertNotIn("is_clean", result)

    async def test_numstat_and_patch_disable_textconv_and_external_diff(self):
        (self.root / ".gitattributes").write_text("*.md diff=fixture\n")
        self.git("add", ".gitattributes")
        self.git("commit", "-m", "attributes")
        (self.root / "README.md").write_text("changed\n")
        # An inherited driver would fail if invoked; no executable/hook is created.
        env = {"GIT_CONFIG_COUNT": "2", "GIT_CONFIG_KEY_0": "diff.fixture.textconv",
               "GIT_CONFIG_VALUE_0": "/must-not-execute-textconv",
               "GIT_CONFIG_KEY_1": "diff.fixture.command",
               "GIT_CONFIG_VALUE_1": "/must-not-execute-external-diff"}
        with patch.dict(os.environ, env):
            for view in ("summary", "patch"):
                result = await server.diff("p", view=view)
                self.assertTrue(result["ok"], result)
                if view == "summary":
                    self.assertEqual(result["files"][0]["insertions"], 1)
                else:
                    self.assertIn("+changed", result["patch"])

    async def test_frozen_target_replacement_does_not_fall_back(self):
        (self.root / "root-only").write_text("root")
        self.linked.rename(self.linked.with_name("moved"))
        self.linked.mkdir()
        result = await server.diff("p", work_ref="frozen")
        self.assertFalse(result["ok"], result)
        self.assertEqual(result["error_type"], "WorkEvidenceTargetChanged")

    async def test_summary_hard_page_cap_and_empty_final_page(self):
        for number in range(103):
            (self.root / f"file-{number:03d}\n").write_text("new\n")
        first = await server.diff("p")
        self.assertEqual(len(first["files"]), 100)
        self.assertEqual(first["counts"]["untracked"], 103)
        self.assertEqual(first["files_next_offset"], 100)
        second = await server.diff("p", offset=first["files_next_offset"])
        self.assertEqual(len(second["files"]), 3)
        self.assertIsNone(second["files_next_offset"])
        self.assertFalse(second["files_truncated"])
        empty = await server.diff("p", offset=103)
        self.assertEqual(empty["files"], [])
        self.assertFalse(empty["is_clean"])

    async def test_unmerged_numstat_repeated_path_is_valid_not_malformed(self):
        name = 'conflict\nfile'
        objects = [self.git("hash-object", "-w", "--stdin", input=content).strip()
                   for content in (b"base\n", b"ours\n", b"theirs\n")]
        stages = b"".join(b"100644 " + oid + b" " + str(stage).encode() + b"\t" + name.encode() + b"\0"
                          for stage, oid in enumerate(objects, 1))
        self.git("update-index", "-z", "--index-info", input=stages)
        (self.root / name).write_text("merged\n")
        result = await server.diff("p")
        self.assertTrue(result["ok"], result)
        self.assertFalse(result["is_clean"])
        entry, = result["files"]
        self.assertEqual(entry["path"], name)
        self.assertEqual((entry["staged_status"], entry["unstaged_status"]), ("U", "U"))
        self.assertEqual((entry["insertions"], entry["deletions"]), (1, 1))

    async def test_git_error_or_incomplete_machine_output_is_not_clean(self):
        actual = server._git_run_bytes_bounded
        cases = [(1, b"", b"failed"), (0, b'?? broken', b''),
                 (0, b'R  new\0', b''), (0, b'?? bad\xff\0', b'')]
        for answer in cases:
            def observe(*args, **kwargs):
                return answer if "status" in args else actual(*args, **kwargs)
            with self.subTest(answer=answer), patch.object(server, "_git_run_bytes_bounded", side_effect=observe):
                result = await server.diff("p")
                self.assertFalse(result["ok"], result)
                self.assertNotIn("is_clean", result)

    async def test_current_diff_retains_scope_queries_without_fingerprint_queries(self):
        (self.root / "README.md").write_text("changed\n")
        (self.root / "untracked.txt").write_text("untracked body\n")
        for view in ("summary", "patch"):
            with self.subTest(view=view), patch.object(fixed_git, "observe", wraps=fixed_git.observe) as calls:
                result = await server.diff("p", view=view, path="README.md")
            self.assertTrue(result["ok"], result)
            self.assertTrue(result["dirty"])
            queries = [tuple(call.args[1]) for call in calls.call_args_list]
            self.assertEqual([q for q in queries if "status" in q],
                             [("--no-optional-locks", "status", "--porcelain=v1", "-z", "-uall")])
            diff_queries = [q for q in queries if "diff" in q]
            self.assertEqual(sum("--numstat" in q for q in diff_queries), 2)
            self.assertEqual(sum("--cached" in q for q in diff_queries), 1)
            self.assertEqual(len(diff_queries), 2 if view == "summary" else 3)
            self.assertFalse(any("ls-files" in q or "--raw" in q for q in queries))
            self.assertNotIn("state_id", result)
            if view == "patch":
                self.assertIn("+changed\n", result["patch"])

    async def test_hostile_context_cannot_expand_or_fuse_pinned_patches(self):
        filler = "".join(f"filler {i}\n" for i in range(1, 9))
        hostile = {"GIT_CONFIG_COUNT": "2",
                   "GIT_CONFIG_KEY_0": "diff.context", "GIT_CONFIG_VALUE_0": "8",
                   "GIT_CONFIG_KEY_1": "diff.interHunkContext", "GIT_CONFIG_VALUE_1": "5",
                   "GIT_DIFF_OPTS": "--unified=16"}

        async def pair(label, **kwargs):
            baseline = await server.diff("p", view="patch", **kwargs)
            with patch.dict(os.environ, hostile):
                pinned = await server.diff("p", view="patch", **kwargs)
            for result in (baseline, pinned):
                self.assertTrue(result["ok"], (label, result))
                self.assertEqual(result["patch"].count("@@ -"), 2, (label, result["patch"]))
                self.assertIn("+ALPHA", result["patch"])
                self.assertIn("+OMEGA", result["patch"])
                self.assertNotIn("filler 4", result["patch"])
                self.assertNotIn("\x1b[", result["patch"])
            self.assertEqual(pinned["patch"], baseline["patch"], label)

        (self.root / "hunks.txt").write_text("alpha\n" + filler + "omega\n")
        self.git("add", "hunks.txt")
        self.git("commit", "-m", "hunks")
        base = self.git("rev-parse", "HEAD").decode().strip()
        for root in (self.root, self.linked):
            (root / "hunks.txt").write_text("ALPHA\n" + filler + "OMEGA\n")
        # Current unstaged patch in the registered workspace.
        await pair("unstaged")
        # Staged patch: index against HEAD.
        self.git("add", "hunks.txt")
        await pair("staged", staged=True)
        # Frozen Work checkout keeps its own pinned current patch.
        self.git("add", "hunks.txt", root=self.linked)
        self.git("commit", "-m", "hunks changed", root=self.linked)
        target = self.git("rev-parse", "HEAD", root=self.linked).decode().strip()
        (self.linked / "hunks.txt").write_text("ALPHA2\n" + filler + "OMEGA2\n")
        await pair("frozen", work_ref="frozen")
        # Base/target commit comparison against immutable IDs.
        await pair("revision", base=base, target=target)
        # Summaries keep their numstat shape; the synthetic untracked patch is
        # not a Git query and keeps its own fixed header.
        with patch.dict(os.environ, hostile):
            summary = await server.diff("p", view="summary")
            revision_summary = await server.diff("p", base=base, target=target)
            (self.root / "untracked-new.txt").write_text("l1\nl2\n")
            synthetic = await server.diff("p", path="untracked-new.txt", view="patch")
        self.assertTrue(summary["ok"], summary)
        self.assertEqual(summary["counts"]["total"], 1)
        self.assertEqual((summary["files"][0]["insertions"], summary["files"][0]["deletions"]), (2, 2))
        self.assertEqual(revision_summary["files"][0]["insertions"], 2)
        self.assertIn("@@ -0,0 +1,2 @@", synthetic["patch"])
        # Patch generation carries the pinned flags; summaries/numstat never do.
        actual = server._git_run_bytes_bounded
        seen = {}
        def record(*args, **kwargs):
            if "--unified=3" in args:
                seen["revision"] = args
            return actual(*args, **kwargs)
        with patch.object(server, "_git_run_bytes_bounded", side_effect=record):
            await server.diff("p", base=base, target=target, view="patch")
        self.assertIn("--unified=3", seen["revision"])
        self.assertIn("--inter-hunk-context=0", seen["revision"])
        self.assertIn("--no-color", seen["revision"])
        self.assertIn("--no-renames", seen["revision"])
        with patch.object(fixed_git, "observe", wraps=fixed_git.observe) as calls:
            await server.diff("p", path="hunks.txt", view="patch")
            await server.diff("p", view="summary")
        patch_queries = [tuple(c.args[1]) for c in calls.call_args_list
                         if c.args and c.args[1] and "diff" in c.args[1] and "--numstat" not in c.args[1]]
        numstat_queries = [tuple(c.args[1]) for c in calls.call_args_list
                           if c.args and c.args[1] and "--numstat" in c.args[1]]
        self.assertTrue(patch_queries)
        self.assertTrue(numstat_queries)
        for query in patch_queries:
            self.assertIn("--unified=3", query)
            self.assertIn("--inter-hunk-context=0", query)
        for query in numstat_queries:
            self.assertNotIn("--unified=3", query)
            self.assertNotIn("--inter-hunk-context=0", query)


if __name__ == "__main__":
    unittest.main()
