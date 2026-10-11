"""Real temporary root/linked repositories; no Bridge runtime or real commits."""
from copy import deepcopy
import hashlib
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import zlib
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

import commit_candidate as capability
from evidence_target import EvidenceCheckout, EvidenceTarget
from workspace_context import WorkspaceContext, canonical_git_worktree, validate_git_worktree_identity


class CommitCandidateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="bridge-commit-test-")
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.root, self.linked = self.base / "main", self.base / "linked"
        self.root.mkdir()
        clean = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
        clean.update(GIT_CONFIG_GLOBAL="/dev/null", GIT_CONFIG_SYSTEM="/dev/null", GIT_CONFIG_NOSYSTEM="1")
        env = patch.dict(os.environ, clean, clear=True)
        env.start(); self.addCleanup(env.stop)
        self.git("init", "-b", "main")
        self.git("config", "user.name", "Configured Fixture")
        self.git("config", "user.email", "fixture@example.invalid")
        (self.root / "file").write_text("base\n")
        self.git("add", "file")
        self.git("commit", "-m", "base")
        self.git("worktree", "add", "-b", "linked", str(self.linked))
        _, identity = canonical_git_worktree(self.root)
        self.project = WorkspaceContext("p", self.root, identity, str(self.root))
        self.frozen = EvidenceCheckout.capture(self.project, str(self.linked))
        self.store = capability.CandidateStore(self.resolve)

    def git(self, *args, root=None, input=None):
        return subprocess.run([capability.GIT, "--no-optional-locks", "-c", "core.hooksPath=/dev/null",
                               "-c", "commit.gpgsign=false", *args], cwd=root or self.root,
                              input=input, check=True, capture_output=True).stdout

    def resolve(self, project_ref, work_ref):
        if project_ref != "p" or work_ref not in (None, "work"):
            return {"error_type": "unauthorized"}
        validate_git_worktree_identity(self.project.root, self.project.git)
        workspace = self.frozen.revalidate(self.project) if work_ref else self.project
        return EvidenceTarget(self.project, workspace, work_ref)

    def staged(self, root=None, text="accepted\n"):
        root = root or self.root
        (root / "file").write_text(text)
        self.git("add", "file", root=root)
        (root / "file").write_text(text + "UNSTAGED\n")
        (root / "untracked").write_text("untouched\n")

    def preview(self, work_ref=None, **kwargs):
        result = self.store.preview("p", work_ref, **kwargs)
        self.assertEqual(result["status"], "previewed", result)
        return result

    def index(self, root):
        path = Path(self.git("rev-parse", "--git-path", "index", root=root).decode().strip())
        return (path if path.is_absolute() else root / path).read_bytes()

    def storage(self):
        return {str(p.relative_to(self.root)): p.read_bytes()
                for p in (self.root / ".git").rglob("*") if p.is_file()}

    def test_root_and_linked_preview_is_read_only_and_commit_preserves_unstaged_and_index(self):
        for root, work_ref, other in ((self.root, None, self.linked), (self.linked, "work", self.root)):
            with self.subTest(work_ref=work_ref):
                self.staged(root)
                before_index, other_index = self.index(root), self.index(other)
                before_files = {p.name: p.read_bytes() for p in root.iterdir() if p.is_file()}
                before_storage = self.storage()
                parent = self.git("rev-parse", "HEAD", root=root).decode().strip()
                page = self.preview(work_ref, view="patch", limit=7)
                self.assertEqual(self.storage(), before_storage)
                self.assertFalse(page["repository_writes"])
                content = page["text"]
                offset = page["next_offset"]
                while offset is not None:
                    page = self.preview(work_ref, candidate_id=page["candidate_id"], view="patch", offset=offset, limit=7)
                    content += page["text"]
                    offset = page["next_offset"]
                self.assertIn("+accepted", content)
                self.assertNotIn("UNSTAGED", content)
                result = self.store.commit("p", page["candidate_id"], "accepted content")
                self.assertEqual(result["status"], "committed", result)
                self.assertEqual(self.git("rev-parse", "HEAD^", root=root).decode().strip(), parent)
                self.assertEqual(self.git("rev-parse", "HEAD^{tree}", root=root).decode().strip(), page["tree"])
                self.assertEqual(self.git("show", "HEAD:file", root=root), b"accepted\n")
                self.assertEqual(self.git("show", "-s", "--format=%an <%ae>", "HEAD", root=root).strip(),
                                 b"Configured Fixture <fixture@example.invalid>")
                self.assertEqual(self.index(root), before_index)
                self.assertEqual(self.index(other), other_index)
                self.assertEqual({p.name: p.read_bytes() for p in root.iterdir() if p.is_file()}, before_files)
                self.assertTrue(result["index_unchanged"])

    def test_tree_hash_nested_special_paths_modes_delete_and_binary(self):
        self.staged()
        for name, data in [('nested/space \n\t"', b"text\n"), ('dir.z', b"x"), ('dir/a', b"\0binary")]:
            path = self.root / name
            path.parent.mkdir(exist_ok=True, parents=True)
            path.write_bytes(data)
        (self.root / "link").symlink_to("file")
        (self.root / "executable").write_text("exit 0\n")
        (self.root / "executable").chmod(0o755)
        self.git("add", "--", "nested", "dir.z", "dir", "link", "executable")
        result = self.preview(limit=1)
        files = list(result["files"])
        offset = result["next_offset"]
        while offset is not None:
            page = self.preview(candidate_id=result["candidate_id"], offset=offset, limit=1)
            files += page["files"]; offset = page["next_offset"]
        self.assertIn('nested/space \n\t"', {f["path"] for f in files})
        self.assertEqual(self.store.commit("p", result["candidate_id"], "modes")["status"], "committed")
        self.git("rm", "--", "executable")
        deletion = self.preview()
        self.assertEqual(deletion["files"][0]["status"], "D")
        self.assertEqual(self.store.commit("p", deletion["candidate_id"], "delete")["status"], "committed")

    def test_index_head_branch_and_config_changes_refuse(self):
        self.staged()
        for kind in ("index", "head", "branch", "config"):
            with self.subTest(kind=kind):
                page = self.preview()
                if kind == "index":
                    self.staged(text="different\n")
                elif kind == "head":
                    self.git("commit", "--allow-empty", "-m", "other")
                elif kind == "branch":
                    self.git("branch", "other")
                    self.git("symbolic-ref", "HEAD", "refs/heads/other")
                else:
                    self.git("config", "arbitrary.changed", "yes")
                current = self.git("rev-parse", "HEAD")
                result = self.store.commit("p", page["candidate_id"], "stale")
                self.assertEqual(result["status"], "rejected", result)
                self.assertFalse(result["ref_updated"])
                self.assertEqual(self.git("rev-parse", "HEAD"), current)
                self.staged(text=kind + " staged\n")

    def test_hooks_signing_fsmonitor_promisor_and_identity_are_explicit_refusals(self):
        self.staged()
        for key, value, reason in (("commit.gpgsign", "true", "signing-unsupported"),
                                   ("core.fsmonitor", "/never-execute", "fsmonitor-unsupported"),
                                   ("i18n.commitEncoding", "ISO-8859-1", "commit-encoding-unsupported"),
                                   ("remote.origin.promisor", "true", "promisor-store-unsupported")):
            self.git("config", key, value)
            result = self.store.preview("p")
            self.assertEqual(result["reason"], reason, result)
            self.git("config", "--unset", key)
        hooks = self.root / "hooks"
        hooks.mkdir()
        marker = self.root / "HOOK_RAN"
        (hooks / "reference-transaction").write_text(f"#!/bin/sh\ntouch '{marker}'\n")
        (hooks / "reference-transaction").chmod(0o755)
        self.git("config", "core.hooksPath", "hooks")
        self.assertEqual(self.store.preview("p")["reason"], "active-hooks-unsupported")
        self.assertFalse(marker.exists())
        self.git("config", "--unset", "core.hooksPath")
        self.git("config", "--unset", "user.name")
        self.assertEqual(self.store.preview("p")["reason"], "configured-identity-required")

    def test_hook_added_after_preview_is_refused_without_execution(self):
        self.staged(self.linked)
        page = self.preview("work")
        hook = self.root / ".git/hooks/pre-commit"
        hook.write_text("#!/bin/sh\nexit 99\n"); hook.chmod(0o755)
        result = self.store.commit("p", page["candidate_id"], "no hooks")
        self.assertEqual(result["status"], "rejected", result)
        self.assertEqual(result["reason"], "active-hooks-unsupported")

    def test_success_failure_replay_is_cache_only_and_message_bound(self):
        self.staged()
        page = self.preview()
        result = self.store.commit("p", page["candidate_id"], "once")
        self.assertEqual(result["status"], "committed", result)
        with patch.object(capability, "_run_git", side_effect=AssertionError("replay executed Git")):
            self.assertEqual(self.store.commit("p", page["candidate_id"], "once"), result)
            receipt = self.store.preview(
                "p", candidate_id=page["candidate_id"], view="receipt")
            self.assertEqual(receipt["result"], result)
            self.assertEqual(self.store.commit("p", page["candidate_id"], "different")["status"], "rejected")
        receipt["result"]["status"] = "corrupted"
        self.assertEqual(self.store.commit("p", page["candidate_id"], "once")["status"], "committed")

    def test_unknown_ref_result_is_sealed_and_quarantines_checkout(self):
        self.staged()
        page = self.preview()
        another = self.preview()
        real = capability._run_git
        def lost(root, args, env, deadline, input_bytes=None):
            result = real(root, args, env, deadline, input_bytes)
            if args[0] == "update-ref":
                raise capability.GitFailure("timeout")
            return result
        with patch.object(capability, "_run_git", side_effect=lost):
            result = self.store.commit("p", page["candidate_id"], "lost reply")
        self.assertEqual(result["status"], "unknown", result)
        self.assertEqual(self.git("rev-parse", "HEAD").decode().strip(), result["commit"])
        with patch.object(capability, "_run_git", side_effect=AssertionError("unsafe retry")):
            self.assertEqual(self.store.commit("p", page["candidate_id"], "lost reply"), result)
            refused = self.store.commit("p", another["candidate_id"], "different token")
            self.assertEqual(refused["reason"], "checkout-quarantined-unknown-attempt")
        self.assertEqual(self.store.preview("p")["reason"], "checkout-quarantined-unknown-attempt")

    def test_git_failure_receipt_and_actual_tree_mismatch_do_not_update_ref(self):
        self.staged()
        page = self.preview()
        head = self.git("rev-parse", "HEAD")
        real = capability._run_git
        def failed(root, args, env, deadline, input_bytes=None):
            if args[0] == "commit-tree":
                return 1, b"", b"fixture failure"
            return real(root, args, env, deadline, input_bytes)
        with patch.object(capability, "_run_git", side_effect=failed):
            result = self.store.commit("p", page["candidate_id"], "failed")
        self.assertEqual(result["status"], "rejected", result)
        self.assertFalse(result["ref_updated"])
        self.assertTrue(result["objects_may_remain"])
        self.assertEqual(self.git("rev-parse", "HEAD"), head)
        receipt = self.store.preview("p", candidate_id=page["candidate_id"], view="receipt")
        self.assertIn("fixture failure", str(receipt["events"]))
        with patch.object(capability, "_run_git", side_effect=AssertionError("retry")):
            self.assertEqual(self.store.commit("p", page["candidate_id"], "failed"), result)

    def test_linked_gitfile_commondir_and_object_directory_replacement(self):
        self.staged(self.linked)
        for kind in ("gitfile", "commondir", "objects"):
            with self.subTest(kind=kind):
                page = self.preview("work")
                gitdir = Path(self.frozen.git.git_dir)
                path = {"gitfile": self.linked / ".git", "commondir": gitdir / "commondir",
                        "objects": self.root / ".git/objects"}[kind]
                moved = path.with_name(path.name + "-saved")
                path.rename(moved)
                if kind == "objects":
                    path.mkdir()
                else:
                    path.write_bytes(moved.read_bytes())
                try:
                    result = self.store.commit("p", page["candidate_id"], "replacement")
                    self.assertEqual(result["status"], "rejected", result)
                    self.assertFalse(result["ref_updated"])
                finally:
                    if path.is_dir(): path.rmdir()
                    else: path.unlink()
                    moved.rename(path)

    def test_symlinked_storage_to_sibling_is_never_written(self):
        self.staged()
        page = self.preview()
        refs = self.root / ".git/refs"
        saved = refs.with_name("refs-original")
        sibling = self.base / "sibling"
        sibling.mkdir(); (sibling / "sentinel").write_text("same")
        refs.rename(saved); refs.symlink_to(sibling, target_is_directory=True)
        result = self.store.commit("p", page["candidate_id"], "do not redirect")
        self.assertEqual(result["status"], "rejected", result)
        self.assertEqual(list(sibling.iterdir()), [sibling / "sentinel"])
        self.assertEqual((sibling / "sentinel").read_text(), "same")

    def test_finite_cache_and_capture_limits_and_unsupported_environment(self):
        self.staged()
        with patch.object(capability, "MAX_CANDIDATES", 2):
            pages = [self.preview() for _ in range(3)]
        self.assertEqual(len(self.store._items), 2)
        self.assertEqual(self.store.commit("p", pages[0]["candidate_id"], "lost")["reason"], "candidate-unavailable-no-recapture")
        self.assertEqual(self.store.preview("other", candidate_id=pages[-1]["candidate_id"])["status"], "rejected")
        with patch.object(capability, "MAX_BYTES", 8):
            result = self.store.preview("p")
        self.assertEqual(result["status"], "rejected", result)
        with patch.dict(os.environ, {"GIT_TRACE": str(self.base / "trace")}):
            result = self.store.preview("p")
        self.assertEqual(result["reason"], "unsupported-git-environment")
        self.assertFalse((self.base / "trace").exists())

    def test_descriptor_numbers_do_not_change_effective_config_identity(self):
        self.staged()
        page = self.preview()
        with tempfile.TemporaryFile(), tempfile.TemporaryFile(), tempfile.TemporaryFile():
            result = self.store.commit("p", page["candidate_id"], "same configuration")
        self.assertEqual(result["status"], "committed", result)

    def test_direct_registered_linked_project(self):
        _, identity = canonical_git_worktree(self.linked)
        self.project = WorkspaceContext("p", self.linked, identity, str(self.linked))
        self.staged(self.linked)
        page = self.preview()
        self.assertEqual(page["execution_target"], str(self.linked))
        result = self.store.commit("p", page["candidate_id"], "linked project")
        self.assertEqual(result["status"], "committed", result)

    def test_actual_tree_mismatch_refuses_before_commit_object(self):
        self.staged()
        page = self.preview()
        real = capability._run_git
        def wrong_tree(root, args, env, deadline, input_bytes=None):
            if args[0] == "mktree":
                return 0, b"0" * 40 + b"\n", b""
            self.assertNotEqual(args[0], "commit-tree")
            return real(root, args, env, deadline, input_bytes)
        with patch.object(capability, "_run_git", side_effect=wrong_tree):
            result = self.store.commit("p", page["candidate_id"], "tree mismatch")
        self.assertEqual(result["status"], "rejected", result)
        self.assertEqual(result["reason"], "actual-tree-mismatch")
        self.assertFalse(result["ref_updated"])

    def test_index_policy_and_gitfile_changes_after_object_creation_refuse(self):
        self.staged(self.linked)
        real = capability._run_git
        for change in ("config", "index", "gitfile"):
            with self.subTest(change=change):
                page = self.preview("work")
                paths = {"config": self.root / ".git/config", "index": Path(self.frozen.git.git_dir) / "index",
                         "gitfile": self.linked / ".git"}
                path = paths[change]
                original = path.read_bytes()
                def changed(root, args, env, deadline, input_bytes=None):
                    result = real(root, args, env, deadline, input_bytes)
                    if args[0] == "commit-tree":
                        if change == "gitfile":
                            replacement = path.with_name("replacement")
                            replacement.write_bytes(original)
                            os.replace(replacement, path)
                        else:
                            path.write_bytes(original + (b"\n#changed\n" if change == "config" else b"extra"))
                    return result
                try:
                    with patch.object(capability, "_run_git", side_effect=changed):
                        result = self.store.commit("p", page["candidate_id"], "no changed state")
                    self.assertEqual(result["status"], "rejected", result)
                    self.assertFalse(result["ref_updated"])
                    self.assertTrue(result["objects_may_remain"])
                finally:
                    path.write_bytes(original)

    def test_branch_switch_during_ref_update_is_unknown_and_not_redirected(self):
        self.staged()
        page = self.preview()
        self.git("branch", "other")
        real = capability._run_git
        def switch(root, args, env, deadline, input_bytes=None):
            if args[0] == "update-ref":
                self.git("symbolic-ref", "HEAD", "refs/heads/other")
            return real(root, args, env, deadline, input_bytes)
        with patch.object(capability, "_run_git", side_effect=switch):
            result = self.store.commit("p", page["candidate_id"], "race")
        self.assertEqual(result["status"], "unknown", result)
        self.assertTrue(result["ref_updated"])
        self.assertEqual(self.git("rev-parse", "refs/heads/main").decode().strip(), result["commit"])
        self.assertEqual(self.git("rev-parse", "refs/heads/other").decode().strip(), page["parent"])

    def test_intent_to_add_and_unmerged_index_are_refused(self):
        self.staged()
        (self.root / "intent").write_text("not staged\n")
        self.git("add", "-N", "intent")
        self.assertEqual(self.store.preview("p")["reason"], "intent-to-add-unsupported")
        self.git("reset", "--", "intent")
        ids = [self.git("hash-object", "-w", "--stdin", input=data).strip()
               for data in (b"base\n", b"ours\n", b"theirs\n")]
        self.git("update-index", "--index-info", input=b"".join(
            b"100644 " + oid + b" " + str(stage).encode() + b"\tconflict\n" for stage, oid in enumerate(ids, 1)))
        self.assertEqual(self.store.preview("p")["reason"], "unmerged-index-unsupported")

    def test_sha256_repository_tree_fingerprint(self):
        root = self.base / "sha256"
        root.mkdir()
        self.git("init", "-b", "main", "--object-format=sha256", root=root)
        self.git("config", "user.name", "Configured", root=root)
        self.git("config", "user.email", "configured@example.invalid", root=root)
        (root / "file").write_text("base\n")
        self.git("add", "file", root=root); self.git("commit", "-m", "base", root=root)
        _, identity = canonical_git_worktree(root)
        self.project = WorkspaceContext("p", root, identity, str(root))
        self.staged(root)
        page = self.preview()
        self.assertEqual(len(page["tree"]), 64)
        result = self.store.commit("p", page["candidate_id"], "sha256")
        self.assertEqual(result["status"], "committed", result)
        self.assertEqual(self.git("rev-parse", "HEAD^{tree}", root=root).decode().strip(), page["tree"])

    def test_worktree_specific_configured_identity_is_used(self):
        self.git("config", "extensions.worktreeConfig", "true")
        self.git("config", "--worktree", "user.name", "Linked Identity", root=self.linked)
        self.staged(self.linked)
        page = self.preview("work")
        result = self.store.commit("p", page["candidate_id"], "linked identity")
        self.assertEqual(result["status"], "committed", result)
        self.assertEqual(self.git("show", "-s", "--format=%an", "HEAD", root=self.linked).strip(), b"Linked Identity")

    def test_external_diff_textconv_and_filter_are_not_executed(self):
        (self.root / ".gitattributes").write_text("file diff=fixture filter=fixture\n")
        self.git("add", ".gitattributes")
        self.staged()
        marker = self.base / "EXTERNAL_RAN"
        helper = self.base / "external-helper"
        helper.write_text(f"#!{sys.executable}\nfrom pathlib import Path\nPath({str(marker)!r}).write_text('ran')\nraise SystemExit(97)\n")
        helper.chmod(0o755)
        for key in ("diff.external", "diff.fixture.command", "diff.fixture.textconv",
                    "filter.fixture.clean", "filter.fixture.smudge", "filter.fixture.process"):
            self.git("config", key, str(helper))
        self.git("config", "filter.fixture.required", "true")
        config_before = (self.root / ".git/config").read_bytes()
        index_before = self.index(self.root)
        page = self.preview(view="patch", limit=16384)
        self.assertIn("+accepted", page["text"])
        result = self.store.commit("p", page["candidate_id"], "fixed plumbing")
        self.assertEqual(result["status"], "committed", result)
        self.assertFalse(marker.exists())
        self.assertEqual(self.git("show", "HEAD:file"), b"accepted\n")
        self.assertEqual(self.index(self.root), index_before)
        self.assertEqual((self.root / ".git/config").read_bytes(), config_before)

    def test_metadata_directory_swap_after_object_creation_cannot_redirect_write(self):
        self.staged(self.linked)
        page = self.preview("work")
        real = capability._run_git
        gitdir = Path(self.frozen.git.git_dir)
        saved = gitdir.with_name(gitdir.name + "-saved")
        def replaced(root, args, env, deadline, input_bytes=None):
            result = real(root, args, env, deadline, input_bytes)
            if args[0] == "commit-tree":
                gitdir.rename(saved)
                gitdir.mkdir()
                (gitdir / "sentinel").write_text("replacement untouched")
            return result
        with patch.object(capability, "_run_git", side_effect=replaced):
            result = self.store.commit("p", page["candidate_id"], "do not redirect")
        self.assertEqual(result["status"], "rejected", result)
        self.assertFalse(result["ref_updated"])
        self.assertEqual([p.name for p in gitdir.iterdir()], ["sentinel"])
        self.assertEqual((gitdir / "sentinel").read_text(), "replacement untouched")
        self.assertFalse((saved / "index.lock").exists())

    def test_receipt_events_paginate_and_cache_loss_does_not_recapture(self):
        self.staged()
        page = self.preview()
        result = self.store.commit("p", page["candidate_id"], "receipt pages")
        self.assertEqual(result["status"], "committed", result)
        events, offset = [], 0
        with patch.object(capability, "_run_git", side_effect=AssertionError("receipt re-executed")):
            while True:
                receipt = self.store.preview("p", candidate_id=page["candidate_id"], view="receipt", offset=offset, limit=2)
                self.assertEqual(receipt["result"], result)
                events += receipt["events"]
                offset = receipt["next_offset"]
                if offset is None:
                    break
            fresh = capability.CandidateStore(self.resolve)
            self.assertEqual(fresh.commit("p", page["candidate_id"], "receipt pages")["reason"], "candidate-unavailable-no-recapture")
        self.assertEqual(sum(e["operation"] == "update-ref" for e in events), 1)
        self.assertNotIn("directories", receipt["before"])
        self.assertIn("storage_directories_sha256", receipt["before"])

    def test_lock_and_byte_budget_refusal_leaves_existing_files(self):
        self.staged()
        page = self.preview()
        lock = self.root / ".git/index.lock"
        lock.write_bytes(b"other owner")
        result = self.store.commit("p", page["candidate_id"], "busy")
        self.assertEqual(result["status"], "rejected", result)
        self.assertEqual(lock.read_bytes(), b"other owner")
        lock.unlink()
        with patch.object(capability, "MAX_CACHE_BYTES", 16):
            result = self.store.preview("p")
        self.assertEqual(result["reason"], "candidate-cache-size-limit")
        for value in ("", "nul\0", "x" * 65537):
            self.assertEqual(self.store.commit("p", page["candidate_id"], value)["status"], "rejected")
        self.assertEqual(self.store.preview("p", candidate_id={})["reason"], "invalid-candidate-id")
        self.assertEqual(self.store.commit("p", {}, "invalid")["reason"], "invalid-candidate-id")

    def test_unknown_candidate_is_not_evicted_to_enable_new_attempt(self):
        self.staged()
        page = self.preview()
        real = capability._run_git
        def timeout(root, args, env, deadline, input_bytes=None):
            if args[0] == "commit-tree":
                raise capability.GitFailure("timeout")
            return real(root, args, env, deadline, input_bytes)
        with patch.object(capability, "_run_git", side_effect=timeout):
            result = self.store.commit("p", page["candidate_id"], "unknown object creation")
        self.assertEqual(result["status"], "unknown", result)
        self.staged(self.linked)
        with patch.object(capability, "MAX_CANDIDATES", 1):
            refused = self.store.preview("p", "work")
        self.assertEqual(refused["reason"], "candidate-cache-full-of-unknown-attempts")
        self.assertEqual(self.store.commit("p", page["candidate_id"], "unknown object creation"), result)

    def test_concurrent_same_request_commits_once(self):
        self.staged()
        page = self.preview()
        real = capability._run_git
        entered, release = threading.Event(), threading.Event()
        updates = []
        def pause(root, args, env, deadline, input_bytes=None):
            if args[0] == "commit-tree":
                entered.set()
                self.assertTrue(release.wait(5))
            if args[0] == "update-ref":
                updates.append(args)
            return real(root, args, env, deadline, input_bytes)
        with patch.object(capability, "_run_git", side_effect=pause), ThreadPoolExecutor(2) as pool:
            one = pool.submit(self.store.commit, "p", page["candidate_id"], "once")
            try:
                self.assertTrue(entered.wait(5))
                two = pool.submit(self.store.commit, "p", page["candidate_id"], "once")
            finally:
                release.set()
            self.assertEqual(one.result(timeout=5), two.result(timeout=5))
            self.assertEqual(one.result()["status"], "committed", one.result())
        self.assertEqual(len(updates), 1)

    def test_config_sources_are_read_once_per_policy_snapshot_not_per_key(self):
        self.staged()
        for number in range(20):
            self.git("config", f"fixture.key{number}", "value")
        real = capability._file
        reads = []
        def read(path, *args, **kwargs):
            if Path(path) == self.root / ".git/config":
                reads.append(path)
            return real(path, *args, **kwargs)
        with patch.object(capability, "_file", side_effect=read):
            self.preview()
        self.assertEqual(len(reads), 2)  # Capture and final consistency snapshot.

    def test_small_unrelated_history_is_not_walked_and_unrelated_hooks_are_not_read(self):
        self._assert_unrelated_history_and_hooks_are_not_read(8, 3)

    @unittest.skipUnless(os.environ.get('BRIDGE_MAINTAINER_SUITE') == '1',
                         'maintainer lane: full 20,010-object/300-ref history stress '
                         '(BRIDGE_MAINTAINER_SUITE=1)')
    def test_unrelated_history_is_not_walked_and_unrelated_hooks_are_not_read(self):
        self._assert_unrelated_history_and_hooks_are_not_read(20010, 300)

    def _assert_unrelated_history_and_hooks_are_not_read(self, object_count, ref_count):
        self.staged()
        gitdir = self.root / ".git"
        # Both lanes use real unreachable blobs; the maintainer lane exceeds
        # the former total repository node cap without enlarging the candidate.
        for n in range(object_count):
            body = f"unrelated-{n}".encode()
            obj = b"blob " + str(len(body)).encode() + b"\0" + body
            oid = hashlib.sha1(obj).hexdigest()
            bulk = gitdir / "objects" / oid[:2]
            bulk.mkdir(exist_ok=True)
            (bulk / oid[2:]).write_bytes(zlib.compress(obj))
        parent = self.git("rev-parse", "HEAD").strip() + b"\n"
        refs = gitdir / "refs/heads/history"
        refs.mkdir()
        for n in range(ref_count):
            (refs / str(n)).write_bytes(parent)
        hook = gitdir / "hooks/post-checkout"
        marker = self.base / "UNRELATED_HOOK_RAN"
        hook.write_text(f"#!/bin/sh\ntouch '{marker}'\n")
        hook.chmod(0o755)
        before_index = self.index(self.root)
        real = capability._file
        def read(path, *args, **kwargs):
            self.assertNotEqual(Path(path), hook, "unrelated hook body read")
            return real(path, *args, **kwargs)
        real_scandir = os.scandir
        def scandir(path):
            if isinstance(path, (str, bytes, os.PathLike)):
                self.assertFalse(Path(path).is_relative_to(gitdir), "repository enumeration")
            return real_scandir(path)
        with patch.object(capability.os, "scandir", side_effect=scandir), \
                patch.object(capability, "_file", side_effect=read):
            page = self.preview()
            result = self.store.commit("p", page["candidate_id"], "bounded metadata")
        self.assertEqual(result["status"], "committed", result)
        self.assertEqual(self.git("rev-parse", "HEAD^").strip() + b"\n", parent)
        self.assertEqual(self.git("rev-parse", "HEAD^{tree}").decode().strip(), page["tree"])
        self.assertEqual(self.git("show", "HEAD:file"), b"accepted\n")
        self.assertEqual(self.index(self.root), before_index)
        self.assertFalse(marker.exists())

    def test_each_relevant_hook_refuses_without_execution(self):
        self.staged(self.linked)
        marker = self.base / "HOOK_RAN"
        for name in ("pre-commit", "prepare-commit-msg", "commit-msg", "post-commit", "reference-transaction"):
            with self.subTest(name=name):
                hook = self.root / ".git/hooks" / name
                hook.write_text(f"#!/bin/sh\ntouch '{marker}'\n")
                hook.chmod(0o755)
                result = self.store.preview("p", "work")
                self.assertEqual(result["reason"], "active-hooks-unsupported", result)
                self.assertFalse(marker.exists())
                hook.unlink()

    def test_project_is_checked_before_attempt_and_cached_replay(self):
        self.staged()
        page = self.preview()
        token = page["candidate_id"]
        with patch.object(capability, "_run_git", side_effect=AssertionError("wrong project ran Git")):
            self.assertEqual(self.store.commit("other", token, "once")["reason"], "candidate-project-mismatch")
            self.assertEqual(self.store.cached_result("other", token, "once")["reason"], "candidate-project-mismatch")
            with self.assertRaises(capability.Refused):
                self.store.target_for("other", token)
        result = self.store.commit("p", token, "once")
        self.assertEqual(result["status"], "committed", result)
        with patch.object(capability, "_run_git", side_effect=AssertionError("replay ran Git")):
            self.assertEqual(self.store.commit("other", token, "once")["reason"], "candidate-project-mismatch")
            self.assertEqual(self.store.commit("p", token, "once"), result)

    def test_post_index_change_is_unrelated_to_materialized_tree(self):
        for root, work in ((self.root, None), (self.linked, "work")):
            with self.subTest(work=work):
                self.staged(root)
                page = self.preview(work)
                index = self.index(root)
                parent = self.git("rev-parse", "HEAD", root=root)
                hook = self.root / ".git/hooks/post-index-change"
                marker = self.base / "INDEX_HOOK_RAN"
                hook.write_text(f"#!/bin/sh\ntouch '{marker}'\n")
                hook.chmod(0o755)
                real = capability._run_git
                calls = []
                def observe(root, args, env, deadline, input_bytes=None):
                    calls.append(args[0])
                    return real(root, args, env, deadline, input_bytes)
                try:
                    with patch.object(capability, "_run_git", side_effect=observe):
                        result = self.store.commit("p", page["candidate_id"], "reject index hook")
                    self.assertFalse(marker.exists(), result)
                    self.assertEqual(result["status"], "committed", result)
                    self.assertIn("mktree", calls)
                    self.assertNotIn("write-tree", calls)
                    self.assertEqual(self.index(root), index)
                    self.assertEqual(self.git("rev-parse", "HEAD^", root=root), parent)
                finally:
                    hook.unlink()
                    marker.unlink(missing_ok=True)

    def test_private_index_read_commands_do_not_invoke_index_hook_but_write_tree_does(self):
        # Direct temporary-fixture plumbing probes the Git behavior, not a
        # capability policy bypass: no candidate commit is requested here.
        for root, work in ((self.root, None), (self.linked, "work")):
            with self.subTest(work=work):
                self.staged(root)
                original = self.index(root)
                marker = self.base / "PRIVATE_INDEX_HOOK"
                hook = self.root / ".git/hooks/post-index-change"
                hook.write_text(f'#!/bin/sh\nprintf "%s" "$GIT_INDEX_FILE" > "{marker}"\n')
                hook.chmod(0o755)
                binding = capability._Binding(self.resolve("p", work), time.monotonic() + 30)
                try:
                    with tempfile.TemporaryDirectory(prefix="index-hook-fixture-") as temp:
                        private = Path(temp) / "index"
                        private.write_bytes(original)
                        parent = self.git("rev-parse", "HEAD", root=root).decode().strip()
                        flags = ["diff", "--cached", "--no-ext-diff", "--no-textconv", "--no-renames",
                                 "--no-color", "--no-relative", "--ignore-submodules=none", "--submodule=short"]
                        commands = [["ls-files", "--stage", "--full-name", "-z"],
                                    *[[*flags, "--raw", "--no-abbrev", "-z", ita, parent, "--"]
                                      for ita in ("--ita-invisible-in-index", "--ita-visible-in-index")],
                                    [*flags, "--src-prefix=a/", "--dst-prefix=b/",
                                     "-p", parent, "--"]]
                        for command in commands:
                            binding.git(command, index=private)
                            self.assertFalse(marker.exists(), command)
                            self.assertEqual(private.read_bytes(), original)
                        binding.git(["write-tree"], index=private)
                        self.assertEqual(marker.read_text(), str(private))
                        self.assertEqual(self.index(root), original)
                finally:
                    binding.close()
                    hook.unlink()
                    marker.unlink(missing_ok=True)

    def test_matching_required_filters_old_primitive_control_and_exact_store_tree(self):
        for root, work in ((self.root, None), (self.linked, "work")):
            for process in (True, False):
                with self.subTest(work=work, process=process):
                    approved = b"approved process\n" if process else b"approved clean\n"
                    self.staged(root, approved.decode())
                    (root / "binary").write_bytes(b"\0approved\xff\n")
                    (root / ".gitattributes").write_text("file filter=review\nbinary filter=review\n")
                    self.git("add", "binary", ".gitattributes", root=root)
                    marker = self.base / "FILTER_RAN"
                    helper = self.base / "required-filter"
                    helper.write_text(f'#!/bin/sh\nprintf "%s" "$0" > "{marker}"\nexit 97\n')
                    helper.chmod(0o755)
                    keys = ["filter.review.clean", "filter.review.required"]
                    self.git("config", keys[0], str(helper))
                    self.git("config", keys[1], "true")
                    if process:
                        keys.append("filter.review.process")
                        self.git("config", keys[-1], str(helper))
                    original, config = self.index(root), (self.root / ".git/config").read_bytes()
                    # Positive control: same captured index and matched attributes
                    # really execute the forbidden helper under the old primitive.
                    try:
                        binding = capability._Binding(self.resolve("p", work), time.monotonic() + 30)
                        try:
                            with tempfile.TemporaryDirectory(prefix="old-tree-control-") as temp:
                                private = Path(temp) / "index"
                                private.write_bytes(original)
                                # Make the old primitive's racy-index refresh deterministic;
                                # a fresh copy crossing a second boundary can skip the helper.
                                os.utime(private, (1, 1))
                                with self.assertRaises(capability.GitFailure):
                                    binding.git(["write-tree"], index=private)
                                self.assertEqual(marker.read_text(), str(helper))
                                marker.unlink()
                        finally:
                            binding.close()
                        page = self.preview(work)
                        real = capability._run_git
                        calls = []
                        def observe(root, args, env, deadline, input_bytes=None):
                            calls.append(args)
                            return real(root, args, env, deadline, input_bytes)
                        with patch.object(capability, "_run_git", side_effect=observe):
                            result = self.store.commit("p", page["candidate_id"], "exact stage objects")
                        self.assertEqual(result["status"], "committed", result)
                        self.assertFalse(marker.exists())
                        self.assertEqual([a for a in calls if a[0] == "mktree"], [["mktree", "-z", "--batch"]])
                        self.assertFalse(any(a[0] == "write-tree" for a in calls))
                        self.assertEqual(self.git("show", "HEAD:file", root=root), approved)
                        self.assertEqual(self.git("show", "HEAD:binary", root=root), b"\0approved\xff\n")
                        self.assertEqual(self.git("rev-parse", "HEAD^{tree}", root=root).decode().strip(), page["tree"])
                        self.assertEqual(self.index(root), original)
                        self.assertEqual((self.root / ".git/config").read_bytes(), config)
                        self.assertIn("UNSTAGED", (root / "file").read_text())
                    finally:
                        for key in keys:
                            self.git("config", "--unset", key)

    def test_many_directories_use_one_bounded_tree_batch(self):
        for n in range(100):
            path = self.root / f'dir{n}' / 'child' / '空 格\n\t"file'
            path.parent.mkdir(parents=True)
            path.write_bytes(b"staged\0binary")
        self.git("add", ".")
        page = self.preview()
        real = capability._run_git
        calls = []
        def observe(root, args, env, deadline, input_bytes=None):
            calls.append(args[0])
            return real(root, args, env, deadline, input_bytes)
        with patch.object(capability, "_run_git", side_effect=observe):
            result = self.store.commit("p", page["candidate_id"], "201 directories")
        self.assertEqual(result["status"], "committed", result)
        self.assertEqual(calls.count("mktree"), 1)
        self.assertLess(len(calls), 64)
        self.assertEqual(self.git("rev-parse", "HEAD^{tree}").decode().strip(), page["tree"])
        item = self.store._items[page["candidate_id"]]
        self.assertEqual(len(item["tree_oids"].splitlines()), 201)
        self.assertLessEqual(len(item["tree_batch"]), capability.MAX_BYTES)
        with patch.object(capability, "MAX_BYTES", 20):
            with self.assertRaisesRegex(capability.Refused, "tree-batch-size-limit"):
                capability._index_tree(b"100644 " + b"1"*40 + b" 0\tfile\0", "sha1")

    def test_mktree_allows_missing_gitlink(self):
        missing = "1" * 40
        self.git("update-index", "--add", "--cacheinfo", "160000," + missing + ",submodule")
        page = self.preview()
        result = self.store.commit("p", page["candidate_id"], "missing gitlink is valid")
        self.assertEqual(result["status"], "committed", result)
        self.assertIn(b"160000 commit " + missing.encode(), self.git("ls-tree", "HEAD", "submodule"))

    def test_mktree_rejects_missing_staged_blob_before_commit_object(self):
        self.staged()
        page = self.preview()
        oid = self.git("rev-parse", ":file").decode().strip()
        (self.root / ".git/objects" / oid[:2] / oid[2:]).unlink()
        real = capability._run_git
        calls = []
        def observe(root, args, env, deadline, input_bytes=None):
            calls.append(args[0])
            return real(root, args, env, deadline, input_bytes)
        with patch.object(capability, "_run_git", side_effect=observe):
            result = self.store.commit("p", page["candidate_id"], "missing object")
        self.assertEqual(result["status"], "rejected", result)
        self.assertFalse(result["ref_updated"])
        self.assertIn("mktree", calls)
        self.assertNotIn("commit-tree", calls)

    def test_small_binary_set_summary_patch_and_exact_commit(self):
        payloads = {f"npz_{n}.npz": bytes((0, 255, 128, n)) * 1024 for n in range(2)}
        self._assert_binary_set_summary_patch_and_exact_commit(payloads)

    @unittest.skipUnless(os.environ.get('BRIDGE_MAINTAINER_SUITE') == '1',
                         'maintainer lane: full 14 x 850,000-byte binary stress '
                         '(BRIDGE_MAINTAINER_SUITE=1)')
    def test_large_binary_set_summary_patch_and_exact_commit(self):
        # User-shaped repro: many staged binary files totaling >10 MiB.
        payloads = {f"npz_{n}.npz": os.urandom(850_000) for n in range(14)}
        self._assert_binary_set_summary_patch_and_exact_commit(payloads)

    def _assert_binary_set_summary_patch_and_exact_commit(self, payloads):
        for name, data in payloads.items():
            (self.root / name).write_bytes(data)
        self.git("add", "--", *payloads)
        page = self.preview(limit=100)
        self.assertEqual(page["total"], len(payloads))
        self.assertEqual({entry["path"] for entry in page["files"]}, set(payloads))
        for entry in page["files"]:
            self.assertTrue(entry["binary"], entry)
            self.assertEqual(entry["object_size"], len(payloads[entry["path"]]), entry)
            self.assertEqual(entry["object_kind"], "blob", entry)
            self.assertEqual(entry["mode"], "100644", entry)
            self.assertNotEqual(set(entry["object"]), {"0"})
        patch_page = self.preview(candidate_id=page["candidate_id"], view="patch", limit=16384)
        self.assertTrue(patch_page["patch_complete"], patch_page)
        self.assertFalse(patch_page["patch_truncated"])
        self.assertFalse(patch_page["patch_decode_lossy"])
        self.assertGreater(patch_page["patch_bytes"], 0)
        self.assertLessEqual(patch_page["patch_bytes"], capability.PATCH_DISPLAY_BYTES)
        self.assertIn("Binary files", patch_page["text"])
        self.assertIn("b/npz_0.npz differ", patch_page["text"])
        self.assertNotIn("GIT binary patch", patch_page["text"])
        result = self.store.commit("p", page["candidate_id"], "exact binary set")
        self.assertEqual(result["status"], "committed", result)
        self.assertEqual(self.git("rev-parse", "HEAD^{tree}").decode().strip(), page["tree"])
        for name, data in payloads.items():
            self.assertEqual(self.git("show", f"HEAD:{name}"), data)
        # Stale staged index still refuses a previewed but unattempted candidate.
        (self.root / "npz_0.npz").write_bytes(b"changed again")
        self.git("add", "npz_0.npz")
        second = self.preview(limit=100)
        (self.root / "npz_1.npz").write_bytes(b"changed")
        self.git("add", "npz_1.npz")
        before_head, before_index = self.git("rev-parse", "HEAD"), self.index(self.root)
        stale = self.store.commit("p", second["candidate_id"], "stale")
        self.assertEqual(stale["status"], "rejected", stale)
        self.assertIn("index-semantic-drift", stale["reason"])
        self.assertFalse(stale["ref_updated"])
        self.assertEqual(self.git("rev-parse", "HEAD"), before_head)
        self.assertEqual(self.index(self.root), before_index)

    def test_single_small_binary_file_is_previewed_and_committed(self):
        self._assert_single_binary_file_is_previewed_and_committed(bytes(range(256)) * 32)

    @unittest.skipUnless(os.environ.get('BRIDGE_MAINTAINER_SUITE') == '1',
                         'maintainer lane: full 12-MiB binary stress '
                         '(BRIDGE_MAINTAINER_SUITE=1)')
    def test_single_large_binary_file_is_previewed_and_committed(self):
        self._assert_single_binary_file_is_previewed_and_committed(os.urandom(12 * 1024 * 1024))

    def _assert_single_binary_file_is_previewed_and_committed(self, payload):
        (self.root / "big.npz").write_bytes(payload)
        self.git("add", "big.npz")
        page = self.preview()
        entry = page["files"][0]
        self.assertTrue(entry["binary"])
        self.assertEqual(entry["object_size"], len(payload))
        patch_page = self.preview(candidate_id=page["candidate_id"], view="patch", limit=16384)
        self.assertTrue(patch_page["patch_complete"], patch_page)
        self.assertFalse(patch_page["patch_truncated"])
        self.assertFalse(patch_page["patch_decode_lossy"])
        self.assertIn("Binary files", patch_page["text"])
        self.assertIn("b/big.npz differ", patch_page["text"])
        self.assertGreater(patch_page["patch_bytes"], 0)
        self.assertLessEqual(patch_page["patch_bytes"], capability.PATCH_DISPLAY_BYTES)
        result = self.store.commit("p", page["candidate_id"], "one big binary")
        self.assertEqual(result["status"], "committed", result)
        self.assertEqual(self.git("rev-parse", "HEAD^{tree}").decode().strip(), page["tree"])
        self.assertEqual(self.git("show", "HEAD:big.npz"), payload)

    def test_small_text_patch_is_truncated_not_refused(self):
        staged_text = "".join(f"line {n}: " + "x" * 80 + "\n" for n in range(128))
        with patch.object(capability, "PATCH_DISPLAY_BYTES", 2048):
            self._assert_text_patch_is_truncated_not_refused(staged_text)

    @unittest.skipUnless(os.environ.get('BRIDGE_MAINTAINER_SUITE') == '1',
                         'maintainer lane: full 150,000-line text patch stress '
                         '(BRIDGE_MAINTAINER_SUITE=1)')
    def test_huge_text_patch_is_truncated_not_refused(self):
        staged_text = "".join(f"line {n} of a very long staged document\n" for n in range(150_000))
        self._assert_text_patch_is_truncated_not_refused(staged_text)

    def _assert_text_patch_is_truncated_not_refused(self, staged_text):
        payload = staged_text.encode()
        (self.root / "huge.txt").write_bytes(payload)
        self.git("add", "huge.txt")
        page = self.preview()
        self.assertFalse(page["files"][0]["binary"])
        patch_page = self.preview(candidate_id=page["candidate_id"], view="patch", limit=16384)
        self.assertTrue(patch_page["patch_truncated"], patch_page)
        self.assertFalse(patch_page["patch_complete"])
        self.assertFalse(patch_page["patch_decode_lossy"])
        self.assertIn("patch display truncated", self.store._items[page["candidate_id"]]["patch"])
        self.assertGreaterEqual(patch_page["patch_bytes"], capability.PATCH_DISPLAY_BYTES)
        # Summary stays complete and exact commit still commits the frozen tree.
        self.assertEqual(page["total"], 1)
        result = self.store.commit("p", page["candidate_id"], "huge text")
        self.assertEqual(result["status"], "committed", result)
        self.assertEqual(self.git("rev-parse", "HEAD^{tree}").decode().strip(), page["tree"])
        self.assertEqual(self.git("show", "HEAD:huge.txt"), payload)

    def test_invalid_utf8_text_diff_decodes_with_loss_flag(self):
        data = b"\xff\xfe latin-1-ish bytes without NUL\n" * 2000
        (self.root / "legacy.txt").write_bytes(data)
        self.git("add", "legacy.txt")
        page = self.preview()
        self.assertFalse(page["files"][0]["binary"])  # no NUL: git treats it as text
        patch_page = self.preview(candidate_id=page["candidate_id"], view="patch", limit=16384)
        self.assertTrue(patch_page["patch_decode_lossy"], patch_page)
        self.assertFalse(patch_page["patch_complete"])
        self.assertIn("\ufffd", patch_page["text"])
        result = self.store.commit("p", page["candidate_id"], "lossy preview only")
        self.assertEqual(result["status"], "committed", result)
        self.assertEqual(self.git("show", "HEAD:legacy.txt"), data)

    def test_small_file_set_aggregate_patch_truncation_and_bounded_creation(self):
        with patch.object(capability, "PATCH_DISPLAY_BYTES", 2048):
            self._assert_files_aggregate_patch_truncation_and_bounded_creation(5, 80, 2)

    @unittest.skipUnless(os.environ.get('BRIDGE_MAINTAINER_SUITE') == '1',
                         'maintainer lane: full 300-file aggregate patch stress '
                         '(BRIDGE_MAINTAINER_SUITE=1)')
    def test_many_files_aggregate_patch_truncation_and_bounded_creation(self):
        self._assert_files_aggregate_patch_truncation_and_bounded_creation(300, 200, 100)

    def _assert_files_aggregate_patch_truncation_and_bounded_creation(self, file_count,
                                                                   line_width, summary_limit):
        payloads = {f"doc_{n}.txt": (f"document {n}\n" + ("y" * line_width + "\n") * 60).encode()
                    for n in range(file_count)}
        for name, data in payloads.items():
            (self.root / name).write_bytes(data)
        self.git("add", ".")
        page = self.preview(limit=summary_limit)
        self.assertEqual(page["total"], file_count)
        self.assertIsNotNone(page["next_offset"])
        files, offset = list(page["files"]), page["next_offset"]
        with patch.object(capability, "_run_git", side_effect=AssertionError("cached paging ran Git")), \
                patch.object(capability, "_run_git_display",
                             side_effect=AssertionError("cached paging ran Git display")):
            while offset is not None:
                page = self.preview(candidate_id=page["candidate_id"], limit=summary_limit, offset=offset)
                files += page["files"]
                offset = page["next_offset"]
            patch_page = self.preview(candidate_id=page["candidate_id"], view="patch", limit=16384)
        self.assertEqual(len(files), file_count)
        self.assertEqual({entry["path"] for entry in files}, set(payloads))
        for entry in files:
            self.assertFalse(entry["binary"], entry)
            self.assertEqual(entry["object_size"], len(payloads[entry["path"]]), entry)
        self.assertTrue(patch_page["patch_truncated"], patch_page)
        self.assertFalse(patch_page["patch_complete"])
        self.assertFalse(patch_page["patch_decode_lossy"])
        self.assertGreaterEqual(patch_page["patch_bytes"], capability.PATCH_DISPLAY_BYTES)
        item = self.store._items[page["candidate_id"]]
        self.assertIn("patch display truncated", item["patch"])
        # Bounded creation: one aggregate display observation, well under limits.
        display_events = [e for e in item["preview_events"] if e.get("display")]
        self.assertEqual(len(display_events), 1)
        self.assertEqual(display_events[0]["operation"], "diff")
        self.assertLess(len(item["preview_events"]), 64)
        self.assertLessEqual(item["size"], capability.MAX_CACHE_BYTES)
        self.assertLessEqual(len(item["patch"].encode()), capability.PATCH_DISPLAY_BYTES +
                             len(capability.PATCH_TRUNCATION_MARKER.format(
                                 cap=capability.PATCH_DISPLAY_BYTES).encode()))
        result = self.store.commit("p", page["candidate_id"], "exact aggregate text")
        self.assertEqual(result["status"], "committed", result)
        self.assertEqual(self.git("rev-parse", "HEAD^{tree}").decode().strip(), page["tree"])
        for name, data in payloads.items():
            self.assertEqual(self.git("show", f"HEAD:{name}"), data)

    def test_patch_display_timeout_leaves_candidate_valid(self):
        self.staged()
        real = capability._run_git_display
        def lost(root, args, env, deadline, cap=None):
            if args[0] == "diff":
                raise capability.GitFailure("timeout")
            return real(root, args, env, deadline, cap)
        with patch.object(capability, "_run_git_display", side_effect=lost):
            page = self.preview()
        self.assertEqual(page["patch_unavailable"], "patch-timeout", page)
        self.assertFalse(page["patch_complete"])
        patch_page = self.preview(candidate_id=page["candidate_id"], view="patch", limit=16384)
        self.assertEqual(patch_page["patch_unavailable"], "patch-timeout")
        self.assertEqual(patch_page["text"], "")
        result = self.store.commit("p", page["candidate_id"], "display lost, candidate exact")
        self.assertEqual(result["status"], "committed", result)
        item = self.store._items[page["candidate_id"]]
        display_events = [e for e in item["preview_events"] if e.get("display")]
        self.assertEqual(len(display_events), 1)
        self.assertEqual(display_events[0]["outcome"], "git-timeout")
        safety_outcomes = [e["outcome"] for e in item["preview_events"] if not e.get("display")]
        self.assertNotIn("git-timeout", safety_outcomes)

    def test_patch_display_nonzero_exit_leaves_candidate_valid(self):
        self.staged()
        real = capability._run_git_display
        def failed(root, args, env, deadline, cap=None):
            if args[0] == "diff":
                return 128, b"", b"fatal: fixture display failure", False
            return real(root, args, env, deadline, cap)
        with patch.object(capability, "_run_git_display", side_effect=failed):
            page = self.preview()
        self.assertEqual(page["patch_unavailable"], "patch-nonzero", page)
        self.assertFalse(page["patch_complete"])
        self.assertFalse(page["patch_truncated"])
        patch_page = self.preview(candidate_id=page["candidate_id"], view="patch", limit=16384)
        self.assertEqual(patch_page["patch_unavailable"], "patch-nonzero")
        self.assertEqual(patch_page["text"], "")
        result = self.store.commit("p", page["candidate_id"], "display failed, candidate exact")
        self.assertEqual(result["status"], "committed", result)
        item = self.store._items[page["candidate_id"]]
        display_events = [e for e in item["preview_events"] if e.get("display")]
        self.assertEqual(len(display_events), 1)
        # Same nonzero-event convention as safety git(): outcome stays "exited"
        # with the failing exit_code and stderr retained for the receipt.
        self.assertEqual(display_events[0]["outcome"], "exited")
        self.assertEqual(display_events[0]["exit_code"], 128)
        self.assertIn("fixture display failure", display_events[0]["stderr"])
        safety_outcomes = [e["outcome"] for e in item["preview_events"] if not e.get("display")]
        self.assertNotIn("git-nonzero", safety_outcomes)

    def test_special_modes_metadata_and_exact_commit(self):
        self.staged()
        (self.root / "link").symlink_to("file")
        self.git("add", "link")
        payload = (b"version https://git-lfs.github.com/spec/v1\noid sha256:" +
                   b"a" * 64 + b"\nsize 12345\n")
        (self.root / "pointer.bin").write_bytes(payload)
        self.git("add", "pointer.bin")
        commit_oid = self.git("rev-parse", "HEAD").decode().strip()
        self.git("update-index", "--add", "--cacheinfo", f"160000,{commit_oid},submodule")
        page = self.preview()
        by_path = {f["path"]: f for f in page["files"]}
        link = by_path["link"]
        self.assertEqual(link["mode"], "120000")
        self.assertEqual(link["object_kind"], "blob")
        self.assertEqual(link["object_size"], len("file"))
        sub = by_path["submodule"]
        self.assertEqual(sub["mode"], "160000")
        self.assertEqual(sub["object_kind"], "commit")
        self.assertIsNone(sub["object_size"])
        pointer = by_path["pointer.bin"]
        self.assertEqual(pointer["object_size"], len(payload))
        self.assertFalse(pointer["binary"])
        result = self.store.commit("p", page["candidate_id"], "modes and links")
        self.assertEqual(result["status"], "committed", result)
        self.assertEqual(self.git("rev-parse", "HEAD^{tree}").decode().strip(), page["tree"])

    def test_cache_accounting_bounded_with_truncated_patch(self):
        (self.root / "big.txt").write_text("abcdefgh\n" * 128)
        self.git("add", "big.txt")
        with patch.object(capability, "PATCH_DISPLAY_BYTES", 256):
            pages = [self.preview(limit=1) for _ in range(8)]
        for page in pages:
            self.assertTrue(page["patch_truncated"], page)
            self.assertFalse(page["patch_complete"])
        self.assertEqual(len(self.store._items), 8)
        self.assertLessEqual(sum(i["size"] for i in self.store._items.values()),
                             capability.MAX_CACHE_BYTES)
        item = self.store._items[pages[0]["candidate_id"]]
        marker = capability.PATCH_TRUNCATION_MARKER.format(cap=256).encode()
        self.assertEqual(item["patch_state"]["patch_bytes"], 256 + len(marker))
        self.assertLessEqual(len(item["patch"].encode()), 256 + len(marker))


if __name__ == "__main__":
    unittest.main()
