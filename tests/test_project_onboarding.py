"""Fresh canonical onboarding and honest registry persistence. Source tests only."""

from __future__ import annotations

import errno
import json
import os
from pathlib import Path
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

import project_continuity
import server
import workspace_context
from workspace_context import (
    WorkspaceRegistry,
    WorkspaceRegistryStore,
    WorkspaceStoreError,
    canonical_git_worktree,
)


def git_worktree(path: Path) -> Path:
    path.mkdir()
    subprocess.run(["git", "init", "--quiet", str(path)], check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=path, check=True)
    (path / "README.md").write_text("existing rules\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=path, check=True)
    subprocess.run(["git", "commit", "-m", "rules", "--quiet"], cwd=path, check=True)
    return path.resolve()


def seed_for(rules=("README.md",), **extra):
    body = {
        "rules": list(rules),
        "state_content": "current position\n",
        "memory_content": "durable note\n",
    }
    body.update(extra)
    return body


class RegistryTruthTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix="bridge-registry-truth-")
        self.addCleanup(temp.cleanup)
        self.base = Path(temp.name)
        env = patch.dict(os.environ, {"BRIDGE_WORKSPACE_STORE_PATH": str(self.base / "missing-parent" / "registry.json")})
        env.start()
        self.addCleanup(env.stop)

    def _registry(self, store_name="registry.json"):
        default = git_worktree(self.base / "default")
        store_dir = self.base / "store"
        store_dir.mkdir(mode=0o700, exist_ok=True)
        store = WorkspaceRegistryStore(store_dir / store_name)
        return default, WorkspaceRegistry(default, raw="{}", store=store), store

    async def test_register_reports_durable_publication_and_matched_observation(self):
        default, registry, store = self._registry()
        target = git_worktree(self.base / "feature")
        with patch.object(server, "ROOT", default), patch.object(server, "_WORKSPACE_REGISTRY", registry):
            result = await server.project_register("feature", str(target))
        self.assertTrue(result["ok"])
        self.assertEqual(result["status"], "created")
        self.assertEqual(result["task_authority"], "not_granted")
        self.assertEqual(result["persistence"]["publication"], "published")
        self.assertEqual(result["persistence"]["durability"], "directory_fsynced")
        self.assertTrue(result["persistence"]["memory_updated"])
        self.assertEqual(result["registration"]["status"], "matched")
        self.assertEqual(result["registration"]["live_only"], [])
        self.assertEqual(registry.resolve("feature").root, target)

    async def test_pre_publication_failure_has_no_effect_and_leaves_no_temp(self):
        default, registry, store = self._registry()
        target = git_worktree(self.base / "feature")
        before = store.path.exists()

        def fail_replace(*_args, **_kwargs):
            raise OSError("replace refused")

        with patch.object(server, "ROOT", default), patch.object(server, "_WORKSPACE_REGISTRY", registry), \
                patch.object(os, "replace", fail_replace):
            result = await server.project_register("feature", str(target))
        self.assertFalse(result["ok"])
        self.assertEqual(result["error_type"], "WorkspaceStoreError")
        self.assertEqual(result["persistence"]["publication"], "no_effect")
        self.assertEqual(result["persistence"]["durability"], "not_applicable")
        self.assertIsNone(registry.get_entry("feature"))
        self.assertEqual(store.path.exists(), before)
        self.assertEqual(list(store.path.parent.glob(".tmp.*")), [])

    async def test_directory_fsync_failure_stays_published_and_updates_memory(self):
        default, registry, store = self._registry()
        target = git_worktree(self.base / "feature")
        real = workspace_context._fsync_fd
        calls = {"n": 0}

        def flaky(fd):
            calls["n"] += 1
            if calls["n"] >= 2:
                raise OSError("directory fsync failed")
            real(fd)

        with patch.object(server, "ROOT", default), patch.object(server, "_WORKSPACE_REGISTRY", registry), \
                patch.object(workspace_context, "_fsync_fd", flaky):
            result = await server.project_register("feature", str(target))
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["persistence"]["publication"], "published")
        self.assertEqual(result["persistence"]["durability"], "uncertain")
        self.assertIn("directory_fsync_unconfirmed", result["persistence"]["reason"])
        self.assertEqual(registry.resolve("feature").root, target)
        self.assertIn("feature", store.load()["workspaces"])

    async def test_readback_mismatch_after_replace_keeps_bytes_and_skips_memory(self):
        default, registry, store = self._registry()
        target = git_worktree(self.base / "feature")
        real = WorkspaceRegistryStore._read_nofollow
        seen: dict[str, bytes] = {}

        def diverge(store_self):
            data = real(store_self)
            if "published" not in seen:
                seen["published"] = data
                return data + b"\n"
            return data

        with patch.object(server, "ROOT", default), patch.object(server, "_WORKSPACE_REGISTRY", registry), \
                patch.object(WorkspaceRegistryStore, "_read_nofollow", diverge):
            result = await server.project_register("feature", str(target))
        self.assertFalse(result["ok"])
        self.assertEqual(result["error_type"], "RegistrationPersistenceUnconfirmed")
        self.assertEqual(result["task_authority"], "not_granted")
        self.assertEqual(
            result["error"],
            "registry replace was not confirmed by readback; live memory was not updated and the published file was not deleted",
        )
        self.assertEqual(result["persistence"]["publication"], "published")
        self.assertEqual(result["persistence"]["durability"], "uncertain")
        self.assertEqual(result["persistence"]["reason"], "readback_mismatch")
        self.assertFalse(result["persistence"]["memory_updated"])
        self.assertIsNone(registry.get_entry("feature"))
        self.assertEqual(result["registration"]["persisted_only"], ["feature"])
        self.assertEqual(result["registration"]["live_only"], [])
        self.assertEqual(store.path.read_bytes(), seen["published"])
        observed = registry.observe_registration()
        self.assertEqual(observed["status"], "mismatch")
        self.assertEqual(observed["persisted_only"], ["feature"])
        self.assertEqual(observed["live_only"], [])
        self.assertEqual(list(store.path.parent.glob(".tmp.*")), [])

    async def test_observation_is_read_only_and_reports_mismatch_without_root_probe(self):
        default, registry, store = self._registry()
        target = git_worktree(self.base / "feature")
        _, identity = canonical_git_worktree(target)
        store.record_workspace(workspace_ref="feature", canonical_root=str(target), identity=identity)
        registry = WorkspaceRegistry(default, raw="{}", store=store)
        vanished = self.base / "does-not-exist-parent"
        self.assertFalse(vanished.exists())
        absent = WorkspaceRegistryStore(vanished / "registry.json").read_persisted_records()
        self.assertEqual(absent["store"], "absent")
        self.assertFalse(vanished.exists())
        payload = json.loads(store.path.read_text(encoding="utf-8"))
        payload["workspaces"]["feature"]["canonical_root"] = str(self.base / "other-root")
        store.path.write_text(json.dumps(payload), encoding="utf-8")
        os.chmod(store.path, 0o600)
        before = store.path.read_bytes()
        with patch.object(workspace_context, "canonical_git_worktree", side_effect=AssertionError("probe")):
            observed = registry.observe_registration()
        self.assertEqual(observed["status"], "mismatch")
        self.assertEqual(observed["root_or_identity_mismatch"], ["feature"])
        self.assertEqual(store.path.read_bytes(), before)
        self.assertFalse(vanished.exists())

    async def test_stale_loaded_route_matches_persisted_bytes_without_use_time_probe(self):
        default = git_worktree(self.base / "default")
        store_dir = self.base / "store"
        store_dir.mkdir(mode=0o700, exist_ok=True)
        store = WorkspaceRegistryStore(store_dir / "stale.json")
        _, identity = canonical_git_worktree(default)
        store.record_workspace(
            workspace_ref="ghost", canonical_root=str(self.base / "vanished"), identity=identity,
        )
        with patch.object(workspace_context, "canonical_git_worktree", side_effect=AssertionError("startup probe")):
            registry = WorkspaceRegistry(default, raw="{}", store=store)
        with patch.object(workspace_context, "canonical_git_worktree", side_effect=AssertionError("observe probe")):
            observed = registry.observe_registration()
        self.assertEqual(observed["status"], "matched")
        self.assertIn("ghost", registry.refs)

    async def test_named_overview_does_not_list_another_ref(self):
        default, registry, store = self._registry()
        first = git_worktree(self.base / "first")
        second = git_worktree(self.base / "second")
        with patch.object(server, "ROOT", default), patch.object(server, "_WORKSPACE_REGISTRY", registry), \
                patch.object(server, "_deployment_snapshot", return_value={"observed": False}), \
                patch.object(server, "_discover_project_candidates", AsyncMock(return_value={
                    "ok": True, "candidates": [], "candidates_truncated": False, "skipped_count": 0,
                    "coverage_counts": {"out_of_project": 0, "invalid_or_unavailable": 0, "truncated": 0},
                })):
            await server.project_register("first_repo", str(first))
            await server.project_register("second_repo", str(second))
            named = await server.bridge_overview("first_repo")
            default_view = await server.bridge_overview()
        self.assertEqual(named["project_state"]["registration"]["project_ref"], "first_repo")
        self.assertEqual(named["project_state"]["registration"]["relation"], "matched")
        self.assertNotIn("second_repo", json.dumps(named))
        self.assertNotIn("registered_project_refs", named["project_state"])
        self.assertIn("second_repo", default_view["project_state"]["registered_project_refs"])
        self.assertEqual(default_view["project_state"]["registration"]["status"], "matched")


class ProjectInitializeTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix="bridge-init-")
        self.addCleanup(temp.cleanup)
        self.base = Path(temp.name)
        self.default = git_worktree(self.base / "default")
        self.target = git_worktree(self.base / "target")
        store_dir = self.base / "store"
        store_dir.mkdir(mode=0o700)
        self.store = WorkspaceRegistryStore(store_dir / "registry.json")
        self.registry = WorkspaceRegistry(self.default, raw="{}", store=self.store)
        self._patch = patch.object(server, "ROOT", self.default)
        self._patch.start()
        self.addCleanup(self._patch.stop)
        self._registry = patch.object(server, "_WORKSPACE_REGISTRY", self.registry)
        self._registry.start()
        self.addCleanup(self._registry.stop)

    async def _register(self):
        result = await server.project_register("target", str(self.target))
        self.assertTrue(result["ok"], result)
        self.assertEqual(list(result["project_instructions_snippet"].splitlines()), [
            "# Project Binding", "", "Connected Bridge project refs:", '- `project_ref="target"`',
        ])
        return result

    def _index_clean(self):
        completed = subprocess.run(
            ["git", "diff", "--cached", "--quiet"], cwd=self.target, check=False,
        )
        self.assertEqual(completed.returncode, 0)

    async def test_fresh_initialize_publishes_one_directory_and_does_not_stage(self):
        await self._register()
        head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=self.target, capture_output=True, check=False)
        result = await server.project_initialize("target", seed_for())
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["status"], "initialized")
        self.assertEqual(result["publication"], "published")
        self.assertEqual(result["durability"], "directory_fsynced")
        self.assertEqual(result["task_authority"], "not_granted")
        self.assertEqual(result["git_mutation"], "none")
        self.assertNotIn("manifest_schema", result)
        manifest = json.loads((self.target / ".principal" / "project.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest, {
            "rules": ["README.md"],
            "current_state": ".principal/state.md",
            "memory": ".principal/memory.md",
        })
        self.assertEqual((self.target / ".principal" / "state.md").read_text(encoding="utf-8"), "current position\n")
        self.assertEqual((self.target / ".principal" / "memory.md").read_text(encoding="utf-8"), "durable note\n")
        self.assertFalse((self.target / "AGENTS.md").exists())
        self.assertFalse((self.target / ".principal" / "rules.md").exists())
        self.assertEqual(result["continuity"]["status"], "ready")
        self.assertNotIn("manifest_version", result["continuity"])
        self._index_clean()
        again = subprocess.run(["git", "rev-parse", "HEAD"], cwd=self.target, capture_output=True, check=False)
        self.assertEqual(head.stdout, again.stdout)
        staged = subprocess.run(["git", "status", "--porcelain"], cwd=self.target, capture_output=True, text=True, check=True)
        self.assertNotIn("A ", staged.stdout)
        self.assertTrue(any(line.startswith("??") for line in staged.stdout.splitlines()))

    async def test_second_call_is_untouched_and_noncanonical_is_refused(self):
        await self._register()
        first = await server.project_initialize("target", seed_for())
        self.assertEqual(first["status"], "initialized")
        before = {
            path: (self.target / path).read_bytes()
            for path in (".principal/project.json", ".principal/state.md", ".principal/memory.md")
        }
        second = await server.project_initialize("target", seed_for(state_content="replacement\n"))
        self.assertEqual(second["status"], "already_ready")
        self.assertEqual(second["publication"], "not_attempted")
        self.assertEqual({path: (self.target / path).read_bytes() for path in before}, before)

        v1 = self.base / "legacy"
        git_worktree(v1)
        (v1 / "STATE.md").write_text("legacy\n", encoding="utf-8")
        (v1 / ".principal").mkdir()
        manifest = {
            "version": 1, "rules": ["README.md"], "takeover": ["README.md"], "current_state": "STATE.md",
        }
        (v1 / ".principal" / "project.json").write_text(json.dumps(manifest), encoding="utf-8")
        raw = (v1 / ".principal" / "project.json").read_bytes()
        await server.project_register("legacy", str(v1))
        left = await server.project_initialize("legacy", seed_for())
        self.assertFalse(left["ok"])
        self.assertEqual(left["error_type"], "InitializationNotFresh")
        self.assertEqual(left["publication"], "not_attempted")
        self.assertEqual((v1 / ".principal" / "project.json").read_bytes(), raw)
        self.assertFalse((v1 / ".principal" / "state.md").exists())

    async def test_retired_methods_seeds_refuse_fresh_and_existing_publication(self):
        await self._register()
        values = ([], ["METHOD.md"], None, "METHOD.md", {}, False, 0)
        for value in values:
            with self.subTest(value=value, existing=False):
                result = await server.mcp.call_tool("project_initialize", {
                    "project_ref": "target", "seed": seed_for(methods=value),
                })
                self.assertEqual(result.structured_content["error_type"], "InvalidSeed")
                self.assertEqual(result.structured_content["publication"], "not_attempted")
                self.assertFalse((self.target / ".principal").exists())
                self.assertEqual(list(self.target.glob(".principal-init-*")), [])
        self.assertEqual((await server.project_initialize("target", seed_for()))["status"], "initialized")
        principal = self.target / ".principal"
        before = {path.name: path.read_bytes() for path in principal.iterdir()}
        for value in values:
            with self.subTest(value=value, existing=True):
                result = await server.project_initialize("target", seed_for(methods=value))
                self.assertEqual(result["error_type"], "InvalidSeed")
                self.assertEqual(result["publication"], "not_attempted")
                self.assertEqual(before, {path.name: path.read_bytes() for path in principal.iterdir()})
        self._index_clean()

    async def test_existing_retired_methods_manifest_is_not_repaired_or_overwritten(self):
        await self._register()
        await server.project_initialize("target", seed_for())
        principal = self.target / ".principal"
        path = principal / "project.json"
        canonical = json.loads(path.read_text())
        workspace = self.registry.resolve("target")
        for value in ([], ["METHOD.md"], None):
            with self.subTest(value=value):
                path.write_text(json.dumps({**canonical, "methods": value}), encoding="utf-8")
                before = {file.name: file.read_bytes() for file in principal.iterdir()}
                observed = server._project_continuity.describe(workspace)
                self.assertEqual(observed["reason"], "ManifestSchemaInvalid")
                result = await server.project_initialize("target", seed_for())
                self.assertEqual(result["error_type"], "InitializationNotFresh")
                self.assertEqual(result["publication"], "not_attempted")
                self.assertEqual(before, {file.name: file.read_bytes() for file in principal.iterdir()})
                self.assertEqual(list(self.target.glob(".principal-init-*")), [])
        self._index_clean()

    async def test_refuses_missing_rules_blank_rules_content_and_invalid_directory(self):
        await self._register()
        missing = await server.project_initialize("target", seed_for(rules=["missing.md"]))
        self.assertFalse(missing["ok"])
        self.assertEqual(missing["error_type"], "SeedPathUnavailable")
        self.assertEqual(missing["publication"], "not_attempted")
        self.assertFalse((self.target / ".principal").exists())
        blank = await server.project_initialize("target", seed_for(project_rules_content=" \n\t"))
        self.assertEqual(blank["error_type"], "InvalidSeed")
        self.assertFalse((self.target / ".principal").exists())
        (self.target / ".principal").mkdir()
        (self.target / ".principal" / "project.json").write_text("{", encoding="utf-8")
        refused = await server.project_initialize("target", seed_for())
        self.assertEqual(refused["error_type"], "InitializationNotFresh")
        self.assertEqual((self.target / ".principal" / "project.json").read_text(encoding="utf-8"), "{")

    async def test_optional_rules_content_and_symlink_refusal(self):
        await self._register()
        result = await server.project_initialize(
            "target", seed_for(project_rules_content="project-specific rule\n"),
        )
        self.assertEqual(result["status"], "initialized", result)
        manifest = json.loads((self.target / ".principal" / "project.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["rules"], ["README.md", ".principal/rules.md"])
        self.assertEqual(set(manifest), {"rules", "current_state", "memory"})
        self.assertEqual(
            (self.target / ".principal" / "rules.md").read_text(encoding="utf-8"),
            "project-specific rule\n",
        )
        self.assertEqual((self.target / "README.md").read_text(encoding="utf-8"), "existing rules\n")

        linked = git_worktree(self.base / "linked")
        outside = self.base / "outside"
        outside.mkdir()
        (linked / ".principal").symlink_to(outside)
        await server.project_register("linked", str(linked))
        refused = await server.project_initialize("linked", seed_for())
        self.assertEqual(refused["error_type"], "SymlinkRejected")
        self.assertTrue((linked / ".principal").is_symlink())
        self.assertEqual(list(outside.iterdir()), [])

    async def test_unavailable_rename_and_post_publish_fsync_do_not_roll_back(self):
        await self._register()

        def unavailable(*_args, **_kwargs):
            raise OSError(errno.ENOSYS, "renameat2")

        with patch.object(project_continuity, "rename_noreplace", unavailable):
            failed = await server.project_initialize("target", seed_for())
        self.assertEqual(failed["error_type"], "DirectoryPublicationUnavailable")
        self.assertEqual(failed["publication"], "no_effect")
        self.assertFalse((self.target / ".principal").exists())
        self.assertEqual(list(self.target.glob(".principal-init-*")), [])

        real = os.fsync
        root_id = (self.target.stat().st_dev, self.target.stat().st_ino)

        def fail_root(fd):
            info = os.fstat(fd)
            if (info.st_dev, info.st_ino) == root_id:
                raise OSError("root fsync failed")
            real(fd)

        with patch.object(project_continuity.os, "fsync", fail_root):
            published = await server.project_initialize("target", seed_for())
        self.assertTrue(published["ok"], published)
        self.assertEqual(published["publication"], "published")
        self.assertEqual(published["durability"], "uncertain")
        self.assertEqual(published["status"], "published_unconfirmed")
        self.assertTrue((self.target / ".principal" / "project.json").is_file())
        follow = await server.project_initialize("target", seed_for(state_content="nope\n"))
        self.assertEqual(follow["status"], "already_ready")
        self.assertEqual((self.target / ".principal" / "state.md").read_text(encoding="utf-8"), "current position\n")

    async def test_lost_race_keeps_the_other_manifest_and_drops_owned_staging(self):
        await self._register()

        def collide(*_args, **_kwargs):
            principal = self.target / ".principal"
            principal.mkdir()
            (principal / "project.json").write_text(json.dumps({
                "rules": ["README.md"],
                "current_state": "NOTES.md",
                "memory": "MEMORY.md",
            }), encoding="utf-8")
            raise OSError(errno.EEXIST, "exists")

        with patch.object(project_continuity, "rename_noreplace", collide):
            result = await server.project_initialize("target", seed_for())
        self.assertEqual(result["status"], "already_ready")
        self.assertFalse((self.target / ".principal" / "state.md").exists())
        self.assertEqual(list(self.target.glob(".principal-init-*")), [])
        self.assertIn("README.md", (self.target / ".principal" / "project.json").read_text(encoding="utf-8"))

    async def test_unregistered_project_and_register_schema_stay_separate(self):
        missing = await server.project_initialize("missing", seed_for())
        self.assertEqual(missing["error_type"], "ProjectRefUnauthorized")
        self.assertEqual(missing["publication"], "not_attempted")
        tools = {tool.name: tool for tool in await server.mcp.list_tools()}
        self.assertEqual(list(tools["project_register"].input_schema["properties"]), ["project_ref", "path"])
        self.assertEqual(sorted(tools["project_initialize"].input_schema["required"]), ["project_ref", "seed"])
        self.assertIsNone(tools["project_initialize"].meta)
        self.assertNotIn("methods", tools["project_initialize"].description.lower())
        self.assertIn("project_initialize", {tool.name for tool in await server.mcp.list_tools()})


class StoreErrorShapeTests(unittest.TestCase):
    def test_raised_store_error_defaults_to_pre_publication_no_effect(self):
        exc = WorkspaceStoreError("before replace")
        self.assertEqual(exc.publication, "no_effect")
        self.assertEqual(exc.durability, "not_applicable")
