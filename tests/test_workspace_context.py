import asyncio
import inspect
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

os.environ.setdefault(
    "BRIDGE_PATH_TOKEN",
    "test-token-abcdefghijklmnopqrstuvwxyz-012345",
)

_import_store = tempfile.TemporaryDirectory(prefix="bridge-test-registry-")
os.environ["BRIDGE_WORKSPACE_STORE_PATH"] = str(Path(_import_store.name) / "registry.json")

import server
from herdr_backend import HerdrBackend, HerdrError
import workspace_context
from workspace_context import (
    CorruptedWorkspaceStoreError,
    InsecureWorkspaceStoreError,
    MAX_WORKSPACE_REFS,
    WorkspaceAuthorizationError,
    WorkspaceRegistry,
    WorkspaceRegistryStore,
    WorkspaceStoreError,
    canonical_git_worktree,
)


def git_worktree(path: Path) -> Path:
    path.mkdir()
    subprocess.run(["git", "init", "--quiet", str(path)], check=True)
    return path.resolve()


class WorkspaceRegistryTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix="bridge-registry-case-")
        self.addCleanup(temp.cleanup)
        env = patch.dict(os.environ, {"BRIDGE_WORKSPACE_STORE_PATH": str(Path(temp.name) / "registry.json")})
        env.start()
        self.addCleanup(env.stop)

    def test_registry_authorizes_only_named_canonical_git_worktrees(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            default = git_worktree(base / "default")
            target = git_worktree(base / "target")
            registry = WorkspaceRegistry(
                default,
                json.dumps({"review": str(target)}),
            )

            selected = registry.resolve("review")
            fallback = registry.resolve(None)

        self.assertEqual(selected.workspace_ref, "review")
        self.assertEqual(selected.root, target)
        self.assertIsNotNone(selected.git)
        self.assertEqual(selected.gate_key, str(target))
        self.assertTrue(fallback.is_default)
        self.assertEqual(fallback.root, default)
        with self.assertRaises(WorkspaceAuthorizationError):
            registry.resolve("/arbitrary/path")
        with self.assertRaises(WorkspaceAuthorizationError):
            registry.resolve("missing")

    def test_registry_rejects_non_root_bare_and_duplicate_targets(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            default = git_worktree(base / "default")
            target = git_worktree(base / "target")
            child = target / "child"
            child.mkdir()
            bare = base / "bare.git"
            subprocess.run(["git", "init", "--bare", "--quiet", str(bare)], check=True)

            with self.assertRaises(RuntimeError):
                WorkspaceRegistry(default, json.dumps({"child": str(child)}))
            with self.assertRaises(RuntimeError):
                WorkspaceRegistry(default, json.dumps({"bare": str(bare)}))
            with self.assertRaises(RuntimeError):
                WorkspaceRegistry(
                    default,
                    json.dumps({"one": str(target), "two": str(target)}),
                )
            with self.assertRaises(RuntimeError):
                WorkspaceRegistry(
                    default,
                    '{"one":"' + str(target) + '","one":"' + str(target) + '"}',
                )

    def test_default_root_may_hold_exactly_one_static_named_ref(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            default = git_worktree(base / "default")

            registry = WorkspaceRegistry(default, json.dumps({"bridgeself": str(default)}))
            resolved = registry.resolve("bridgeself")
            self.assertEqual(resolved.workspace_ref, "bridgeself")
            self.assertEqual(resolved.root, default)
            self.assertFalse(resolved.is_default)

            with self.assertRaises(RuntimeError):
                WorkspaceRegistry(
                    default,
                    json.dumps({"bridgeself": str(default), "alias": str(default)}),
                )

            # Legacy workspace_ref=None default fallback is unchanged.
            legacy = registry.resolve(None)
            self.assertTrue(legacy.is_default)
            self.assertEqual(legacy.root, default)
            self.assertIsNone(legacy.workspace_ref)

    def test_dynamic_default_root_ref_survives_restart_and_rejects_second_alias(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            default = git_worktree(base / "default")
            store_dir = base / "store_dir"
            store_dir.mkdir(mode=0o700)
            store = WorkspaceRegistryStore(store_dir / "workspace-registry-v1.json")

            _, identity = canonical_git_worktree(default)
            first = WorkspaceRegistry(default, raw="{}", store=store)
            first.register_dynamic("bridgeself", default, identity)

            second = WorkspaceRegistry(default, raw="{}", store=store)
            resolved = second.resolve("bridgeself")
            self.assertEqual(resolved.root, default)
            self.assertFalse(resolved.is_default)

            with self.assertRaises(RuntimeError):
                second.register_dynamic("alias", default, identity)

            store_path = store_dir / "workspace-registry-v1.json"
            data = json.loads(store_path.read_text(encoding="utf-8"))
            data["workspaces"]["alias"] = dict(data["workspaces"]["bridgeself"])
            data["workspaces"]["alias"]["workspace_ref"] = "alias"
            store_path.write_text(json.dumps(data), encoding="utf-8")
            with self.assertRaises(RuntimeError):
                WorkspaceRegistry(default, raw="{}", store=store)

    def test_registered_identity_is_revalidated_before_each_use(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            default = git_worktree(base / "default")
            target = git_worktree(base / "target")
            registry = WorkspaceRegistry(default, json.dumps({"target": str(target)}))
            git_dir = target / ".git"
            replacement = target / ".git.replacement"
            git_dir.rename(replacement)
            git_dir.mkdir()

            with self.assertRaises(WorkspaceAuthorizationError):
                registry.resolve("target")


class WorkspaceRegisterTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix="bridge-registry-case-")
        self.addCleanup(temp.cleanup)
        env = patch.dict(os.environ, {"BRIDGE_WORKSPACE_STORE_PATH": str(Path(temp.name) / "registry.json")})
        env.start()
        self.addCleanup(env.stop)

    async def test_workspace_register_is_canonical_tool_name_without_project_setup_alias(self):
        self.assertTrue(hasattr(server, "project_register"))
        self.assertFalse(hasattr(server, "project_setup"))
        tools = {t.name: t for t in await server.mcp.list_tools()}
        self.assertEqual(list(tools["project_register"].input_schema["properties"]), ["project_ref", "path"])
        self.assertNotIn("project_setup", tools)

    async def test_workspace_register_registers_and_persists_workspace_ref(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            default = git_worktree(base / "default")
            target = git_worktree(base / "feature_a")
            store_dir = base / "store_dir"
            store_dir.mkdir(mode=0o700)
            store = WorkspaceRegistryStore(store_dir / "workspace-registry-v1.json")
            registry = WorkspaceRegistry(default, raw="{}", store=store)

            with patch.object(server, "ROOT", default), patch.object(
                server, "_WORKSPACE_REGISTRY", registry
            ):
                result = await server.project_register(
                    project_ref="feature_a",
                    path=str(target),
                )

                self.assertTrue(result["ok"])
                self.assertEqual(result["project_ref"], "feature_a")
                self.assertEqual(result["canonical_root"], str(target))
                self.assertEqual(result["status"], "created")
                self.assertEqual(result["project_identity"], "not_exposed_or_unproven")
                self.assertEqual(result["binding_provenance"], "not_exposed_or_unproven")
                self.assertEqual(result["instructions_action"], "manual_user_copy_required")
                self.assertIn('project_ref="feature_a"', result["project_instructions_snippet"])
                self.assertIn(
                    'Connected Bridge project refs:', result["project_instructions_snippet"]
                )
                self.assertEqual(result["project_ref"], "feature_a")
                self.assertEqual(result["project_ref"], "feature_a")

                # Re-verify resolved in registry
                context = registry.resolve("feature_a")
                self.assertEqual(context.root, target)
                self.assertEqual(context.workspace_ref, "feature_a")

                # Re-verify persisted in store file
                loaded = store.load()
                self.assertIn("feature_a", loaded["workspaces"])
                self.assertEqual(loaded["workspaces"]["feature_a"]["canonical_root"], str(target))
                self.assertIn("identity", loaded["workspaces"]["feature_a"])
                self.assertEqual(loaded["workspaces"]["feature_a"]["identity"]["bare"], False)

    async def test_workspace_register_idempotent_on_same_ref_and_path(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            default = git_worktree(base / "default")
            target = git_worktree(base / "feature_a")
            store_dir = base / "store_dir"
            store_dir.mkdir(mode=0o700)
            store = WorkspaceRegistryStore(store_dir / "workspace-registry-v1.json")
            registry = WorkspaceRegistry(default, raw="{}", store=store)

            with patch.object(server, "ROOT", default), patch.object(
                server, "_WORKSPACE_REGISTRY", registry
            ):
                first = await server.project_register(
                    project_ref="feature_a",
                    path=str(target),
                )
                self.assertTrue(first["ok"])
                self.assertEqual(first["status"], "created")

                # Simulate durable-store loss while the in-memory registry still
                # knows this dynamic ref. The idempotent path must repair the
                # persistent record rather than merely trusting memory.
                store.path.unlink()
                self.assertFalse(store.path.exists())

                second = await server.project_register(
                    project_ref="feature_a",
                    path=str(target),
                )
                self.assertTrue(second["ok"])
                self.assertEqual(second["status"], "already_registered")
                self.assertEqual(second["canonical_root"], str(target))
                self.assertEqual(second["project_identity"], "not_exposed_or_unproven")

                # Verify store has the record and is confirmed
                loaded = store.load()
                self.assertEqual(loaded["workspaces"]["feature_a"]["canonical_root"], str(target))

    async def test_workspace_register_verifies_static_ref_without_dynamic_store_write(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            default = git_worktree(base / "default")
            target = git_worktree(base / "static_target")
            store_dir = base / "store_dir"
            store_dir.mkdir(mode=0o700)
            store = WorkspaceRegistryStore(store_dir / "workspace-registry-v1.json")
            registry = WorkspaceRegistry(
                default,
                raw=json.dumps({"static_ref": str(target)}),
                store=store,
            )

            with patch.object(server, "ROOT", default), patch.object(
                server, "_WORKSPACE_REGISTRY", registry
            ):
                result = await server.project_register(
                    project_ref="static_ref",
                    path=str(target),
                )

            self.assertTrue(result["ok"])
            self.assertEqual(result["status"], "already_registered")
            self.assertTrue(registry.is_static("static_ref"))
            self.assertEqual(store.load()["workspaces"], {})

    async def test_workspace_register_refuses_when_max_workspace_refs_reached(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            default = git_worktree(base / "default")
            static_refs = {}
            for index in range(MAX_WORKSPACE_REFS):
                target = git_worktree(base / f"static_{index}")
                static_refs[f"ref_{index}"] = str(target)
            extra = git_worktree(base / "extra")
            store_dir = base / "store_dir"
            store_dir.mkdir(mode=0o700)
            store = WorkspaceRegistryStore(store_dir / "workspace-registry-v1.json")
            registry = WorkspaceRegistry(
                default,
                raw=json.dumps(static_refs),
                store=store,
            )

            with patch.object(server, "ROOT", default), patch.object(
                server, "_WORKSPACE_REGISTRY", registry
            ):
                result = await server.project_register(
                    project_ref="overflow",
                    path=str(extra),
                )

            self.assertFalse(result["ok"])
            self.assertEqual(result["error_type"], "MaxWorkspaceRefsExceeded")
            self.assertEqual(store.load()["workspaces"], {})

    async def test_workspace_register_refuses_ref_redirection(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            default = git_worktree(base / "default")
            target1 = git_worktree(base / "target1")
            target2 = git_worktree(base / "target2")
            store_dir = base / "store_dir"
            store_dir.mkdir(mode=0o700)
            store = WorkspaceRegistryStore(store_dir / "workspace-registry-v1.json")
            registry = WorkspaceRegistry(default, raw="{}", store=store)

            with patch.object(server, "ROOT", default), patch.object(
                server, "_WORKSPACE_REGISTRY", registry
            ):
                first = await server.project_register(
                    project_ref="shared_ref",
                    path=str(target1),
                )
                self.assertTrue(first["ok"])
                self.assertEqual(first["status"], "created")

                second = await server.project_register(
                    project_ref="shared_ref",
                    path=str(target2),
                )
                self.assertFalse(second["ok"])
                self.assertEqual(second["error_type"], "WorkspaceRefRedirectionForbidden")

    async def test_workspace_register_refuses_path_aliasing(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            default = git_worktree(base / "default")
            target = git_worktree(base / "target")
            store_dir = base / "store_dir"
            store_dir.mkdir(mode=0o700)
            store = WorkspaceRegistryStore(store_dir / "workspace-registry-v1.json")
            registry = WorkspaceRegistry(default, raw="{}", store=store)

            with patch.object(server, "ROOT", default), patch.object(
                server, "_WORKSPACE_REGISTRY", registry
            ):
                first = await server.project_register(
                    project_ref="ref_one",
                    path=str(target),
                )
                self.assertTrue(first["ok"])

                second = await server.project_register(
                    project_ref="ref_two",
                    path=str(target),
                )
                self.assertFalse(second["ok"])
                self.assertEqual(second["error_type"], "DuplicateWorkspacePath")

    async def test_workspace_register_refuses_invalid_or_non_git_path(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            default = git_worktree(base / "default")
            non_git = base / "non_git_dir"
            non_git.mkdir()
            target = git_worktree(base / "target")
            subdir = target / "subfolder"
            subdir.mkdir()
            bare = base / "bare.git"
            subprocess.run(["git", "init", "--bare", "--quiet", str(bare)], check=True)

            store_dir = base / "store_dir"
            store_dir.mkdir(mode=0o700)
            store = WorkspaceRegistryStore(store_dir / "workspace-registry-v1.json")
            registry = WorkspaceRegistry(default, raw="{}", store=store)

            with patch.object(server, "ROOT", default), patch.object(
                server, "_WORKSPACE_REGISTRY", registry
            ):
                # Non-existent path
                res = await server.project_register("valid_ref", str(base / "nonexistent"))
                self.assertFalse(res["ok"])
                self.assertEqual(res["error_type"], "InvalidGitWorktree")

                # Non-git directory
                res = await server.project_register("valid_ref", str(non_git))
                self.assertFalse(res["ok"])
                self.assertEqual(res["error_type"], "InvalidGitWorktree")

                # Subdirectory of a git repo
                res = await server.project_register("valid_ref", str(subdir))
                self.assertFalse(res["ok"])
                self.assertEqual(res["error_type"], "InvalidGitWorktree")

                # Bare git repo
                res = await server.project_register("valid_ref", str(bare))
                self.assertFalse(res["ok"])
                self.assertEqual(res["error_type"], "InvalidGitWorktree")

                # Relative path
                res = await server.project_register("valid_ref", "relative/path")
                self.assertFalse(res["ok"])
                self.assertEqual(res["error_type"], "InvalidWorkspacePath")

                # Empty path or null byte
                res = await server.project_register("valid_ref", "")
                self.assertFalse(res["ok"])
                self.assertEqual(res["error_type"], "InvalidWorkspacePath")
                res = await server.project_register("valid_ref", "/path\x00with/null")
                self.assertFalse(res["ok"])
                self.assertEqual(res["error_type"], "InvalidWorkspacePath")

    async def test_workspace_register_allows_one_default_root_ref_and_rejects_second(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            default = git_worktree(base / "default")
            target = git_worktree(base / "target")

            store_dir = base / "store_dir"
            store_dir.mkdir(mode=0o700)
            store = WorkspaceRegistryStore(store_dir / "workspace-registry-v1.json")
            registry = WorkspaceRegistry(default, raw="{}", store=store)

            with patch.object(server, "ROOT", default), patch.object(
                server, "_WORKSPACE_REGISTRY", registry
            ):
                # Reserved ref name 'default'
                res = await server.project_register("default", str(target))
                self.assertFalse(res["ok"])
                self.assertEqual(res["error_type"], "ReservedWorkspaceRef")

                # The default root may hold exactly one explicit named ref.
                res = await server.project_register("bridgeself", str(default))
                self.assertTrue(res["ok"])
                self.assertEqual(res["status"], "created")
                self.assertEqual(res["canonical_root"], str(default))

                # A second ref aliasing the same canonical path fails closed.
                res = await server.project_register("other_ref", str(default))
                self.assertFalse(res["ok"])
                self.assertEqual(res["error_type"], "DuplicateWorkspacePath")

                # Invalid ref format
                for bad_ref in ["-invalid", "bad@ref", "ref with spaces", "", "a" * 70]:
                    res = await server.project_register(bad_ref, str(target))
                    self.assertFalse(res["ok"])
                    self.assertEqual(res["error_type"], "InvalidWorkspaceRef")

    async def test_workspace_register_returns_provenance_and_instructions_snippet(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            default = git_worktree(base / "default")
            target = git_worktree(base / "my_project")

            store_dir = base / "store_dir"
            store_dir.mkdir(mode=0o700)
            store = WorkspaceRegistryStore(store_dir / "workspace-registry-v1.json")
            registry = WorkspaceRegistry(default, raw="{}", store=store)

            with patch.object(server, "ROOT", default), patch.object(
                server, "_WORKSPACE_REGISTRY", registry
            ):
                res = await server.project_register("my_project", str(target))
                self.assertTrue(res["ok"])
                self.assertEqual(res["project_identity"], "not_exposed_or_unproven")
                self.assertEqual(res["binding_provenance"], "not_exposed_or_unproven")
                self.assertEqual(res["instructions_action"], "manual_user_copy_required")
                snippet = res["project_instructions_snippet"]
                self.assertIn("# Project Binding", snippet)
                self.assertIn('project_ref="my_project"', snippet)
                self.assertNotIn("bound to exactly one", snippet)
                self.assertEqual(res["project_ref"], "my_project")
                # Registration emits only a connected-ref amendment, without a second Core.
                self.assertEqual(snippet, '# Project Binding\n\nConnected Bridge project refs:\n'
                                 '- `project_ref="my_project"`\n')
                self.assertNotIn('Startup', snippet)
                self.assertNotIn('context(', snippet)

    async def test_workspace_registry_store_security_and_restart_reload(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            default = git_worktree(base / "default")
            target1 = git_worktree(base / "dyn1")
            target2 = git_worktree(base / "dyn2")
            static_target = git_worktree(base / "static_target")

            _, id1 = canonical_git_worktree(target1)
            _, id2 = canonical_git_worktree(target2)

            store_dir = base / "store_dir"
            store_dir.mkdir(mode=0o700)
            store_path = store_dir / "workspace-registry-v1.json"
            store = WorkspaceRegistryStore(store_path)

            # Record dynamic entries into store
            store.record_workspace(workspace_ref="dyn1", canonical_root=str(target1), identity=id1)
            store.record_workspace(workspace_ref="dyn2", canonical_root=str(target2), identity=id2)

            # Re-load registry (restart-style reload) with static + store
            raw_static = json.dumps({"static_ref": str(static_target)})
            reloaded_registry = WorkspaceRegistry(default, raw=raw_static, store=store)

            self.assertEqual(reloaded_registry.refs, ("dyn1", "dyn2", "static_ref"))
            self.assertTrue(reloaded_registry.is_static("static_ref"))
            self.assertFalse(reloaded_registry.is_static("dyn1"))
            self.assertEqual(reloaded_registry.resolve("dyn1").root, target1)
            self.assertEqual(reloaded_registry.resolve("dyn2").root, target2)
            self.assertEqual(reloaded_registry.resolve("static_ref").root, static_target)

            # Test store record redirection rejection in record_workspace
            with self.assertRaises(WorkspaceStoreError):
                store.record_workspace(workspace_ref="dyn1", canonical_root=str(target2), identity=id2)

            # Test permission enforcement
            st_dir = store_dir.stat()
            self.assertEqual(st_dir.st_mode & 0o777, 0o700)
            st_file = store_path.stat()
            self.assertEqual(st_file.st_mode & 0o777, 0o600)

            # Test symlink rejection
            symlink_path = base / "symlink_store.json"
            symlink_path.symlink_to(store_path)
            insecure_store = WorkspaceRegistryStore(symlink_path)
            with self.assertRaises(InsecureWorkspaceStoreError):
                insecure_store.load()

            # Test corrupted JSON rejection
            corrupt_file = store_dir / "corrupt.json"
            corrupt_file.write_text("not json", encoding="utf-8")
            os.chmod(corrupt_file, 0o600)
            corrupt_store = WorkspaceRegistryStore(corrupt_file)
            with self.assertRaises(CorruptedWorkspaceStoreError):
                corrupt_store.load()

            # Test static override rejection: dynamic store entry cannot redirect static
            conflicting_store_path = store_dir / "conflict.json"
            conflicting_store = WorkspaceRegistryStore(conflicting_store_path)
            conflicting_store.record_workspace(workspace_ref="static_ref", canonical_root=str(target1), identity=id1)
            with self.assertRaises(RuntimeError):
                WorkspaceRegistry(default, raw=raw_static, store=conflicting_store)

    async def test_restart_reload_tolerates_replaced_or_missing_route_until_resolve(self):
        """Persisted dynamic routes are provenance metadata: startup loads them
        without live filesystem/Git consultation, and only resolve() fails closed."""
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            default = git_worktree(base / "default")
            target = git_worktree(base / "target_repo")
            _, orig_identity = canonical_git_worktree(target)
            healthy = git_worktree(base / "healthy_repo")
            _, healthy_identity = canonical_git_worktree(healthy)

            store_dir = base / "store_dir"
            store_dir.mkdir(mode=0o700)
            store_path = store_dir / "workspace-registry-v1.json"
            store = WorkspaceRegistryStore(store_path)
            store.record_workspace(workspace_ref="target", canonical_root=str(target), identity=orig_identity)
            store.record_workspace(workspace_ref="healthy", canonical_root=str(healthy), identity=healthy_identity)
            store_bytes_before = store_path.read_bytes()

            # Replace the target repository with a separate-git-dir repository.
            shutil.rmtree(target / ".git")
            separate_git_dir = base / "separate_git_dir"
            subprocess.run(
                ["git", "init", f"--separate-git-dir={separate_git_dir}", str(target)],
                check=True,
                capture_output=True,
            )

            # A second store holds a route whose path no longer exists at all.
            missing_store_path = store_dir / "missing.json"
            missing_store = WorkspaceRegistryStore(missing_store_path)
            missing_store.record_workspace(
                workspace_ref="ghost",
                canonical_root=str(base / "vanished_repo"),
                identity=orig_identity,
            )
            missing_bytes_before = missing_store_path.read_bytes()

            # Construction must not consult live filesystem/Git state for any
            # persisted dynamic route.
            with patch.object(workspace_context, "canonical_git_worktree",
                              side_effect=AssertionError("startup must not probe live Git")), \
                 patch.object(workspace_context, "validate_git_worktree_identity",
                              side_effect=AssertionError("startup must not revalidate routes")):
                registry = WorkspaceRegistry(default, raw="{}", store=store)
                ghost_registry = WorkspaceRegistry(default, raw="{}", store=missing_store)

            # Stale/missing routes stay registered and reserved; construction
            # never rewrites the store.
            self.assertIn("target", registry.refs)
            self.assertIn("healthy", registry.refs)
            self.assertEqual(registry.get_entry("target"), (Path(str(target)), orig_identity))
            self.assertIn("ghost", ghost_registry.refs)
            self.assertEqual(store_path.read_bytes(), store_bytes_before)
            self.assertEqual(missing_store_path.read_bytes(), missing_bytes_before)

            # Use-time revalidation still fails closed for the replaced and the
            # vanished route while healthy/default routes keep working.
            with self.assertRaises(WorkspaceAuthorizationError):
                registry.resolve("target")
            healthy_context = registry.resolve("healthy")
            self.assertEqual(healthy_context.workspace_ref, "healthy")
            default_context = registry.resolve(None)
            self.assertTrue(default_context.is_default)
            with self.assertRaises(WorkspaceAuthorizationError):
                ghost_registry.resolve("ghost")

    async def test_stale_dynamic_route_reserves_ref_path_and_capacity(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            default = git_worktree(base / "default")
            target = git_worktree(base / "target_repo")
            _, identity = canonical_git_worktree(target)

            store_dir = base / "store_dir"
            store_dir.mkdir(mode=0o700)
            store_path = store_dir / "workspace-registry-v1.json"
            store = WorkspaceRegistryStore(store_path)
            vanished_root = base / "vanished_repo"
            store.record_workspace(workspace_ref="stale", canonical_root=str(vanished_root), identity=identity)
            bytes_before = store_path.read_bytes()

            registry = WorkspaceRegistry(default, raw="{}", store=store)
            self.assertIn("stale", registry.refs)
            stale_root, stale_identity = registry.get_entry("stale")
            self.assertEqual(stale_root, vanished_root)
            self.assertEqual(stale_identity, identity)

            # The stale path stays reserved against new dynamic registrations.
            with self.assertRaises(RuntimeError) as ctx:
                registry.register_dynamic("other", vanished_root, identity)
            self.assertIn("aliases existing path", str(ctx.exception))

            # The stale ref keeps consuming registry capacity.
            with patch.object(workspace_context, "MAX_WORKSPACE_REFS", 1):
                with self.assertRaises(RuntimeError) as ctx:
                    registry.register_dynamic("extra", target, identity)
            self.assertIn("max limit", str(ctx.exception))

            # Construction and refused registrations never rewrite the store.
            self.assertEqual(store_path.read_bytes(), bytes_before)

    async def test_server_startup_succeeds_with_unavailable_persisted_route(self):
        """Isolated startup regression: one unavailable historical dynamic route
        must not prevent server import, diagnostics or default-root startup."""
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            _, identity = canonical_git_worktree(git_worktree(base / "source_repo"))
            store_dir = base / "store_dir"
            store_dir.mkdir(mode=0o700)
            store_path = store_dir / "workspace-registry-v1.json"
            store = WorkspaceRegistryStore(store_path)
            store.record_workspace(
                workspace_ref="ghost",
                canonical_root=str(base / "vanished_repo"),
                identity=identity,
            )

            code = (
                "import json, server\n"
                "r = server._WORKSPACE_REGISTRY\n"
                "try:\n"
                "    r.resolve('ghost'); rejected = False\n"
                "except server.WorkspaceAuthorizationError:\n"
                "    rejected = True\n"
                "print(json.dumps({'refs': sorted(r.refs), 'ghost_rejected': rejected,"
                " 'default_ok': bool(r.resolve(None))}))\n"
            )
            env = {
                'PATH': os.defpath,
                'LANG': 'C.UTF-8',
                'PYTHONDONTWRITEBYTECODE': '1',
                'PYTHONPATH': str(Path(server.__file__).parent),
                'BRIDGE_PATH_TOKEN': 'synthetic-startup-only-0123456789abcdef',
                'BRIDGE_WORKSPACE_STORE_PATH': str(store_path),
            }
            result = await asyncio.to_thread(
                subprocess.run, [sys.executable, '-B', '-c', code],
                env=env, capture_output=True, text=True, timeout=60)
            self.assertEqual(result.returncode, 0, result.stderr)
            data = json.loads(result.stdout.strip().splitlines()[-1])
            self.assertEqual(data['refs'], ['ghost'])
            self.assertTrue(data['ghost_rejected'])
            self.assertTrue(data['default_ok'])

    async def test_snapshot_exposes_bounded_refs_and_named_target_is_target_safe(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            default = git_worktree(base / "default")
            target = git_worktree(base / "research_test")
            store_dir = base / "store_dir"
            store_dir.mkdir(mode=0o700)
            store = WorkspaceRegistryStore(store_dir / "workspace-registry-v1.json")
            registry = WorkspaceRegistry(default, raw="{}", store=store)

            backend = type("Backend", (), {"manual_agent_candidates": AsyncMock(return_value={"candidates": [], "skipped_count": 0, "candidates_truncated": False,
                    "coverage_counts": {"out_of_project": 0, "invalid_or_unavailable": 0, "truncated": 0}})})()

            with patch.object(server, "ROOT", default), patch.object(
                server, "_WORKSPACE_REGISTRY", registry
            ), patch.object(
                server, "_WORKSPACE_BACKENDS", {str(target): backend}
            ), patch.object(
                server.HERDR, "manual_agent_candidates", AsyncMock(return_value={"candidates": [], "skipped_count": 0, "candidates_truncated": False,
                    "coverage_counts": {"out_of_project": 0, "invalid_or_unavailable": 0, "truncated": 0}})
            ), patch.object(
                server, "_deployment_snapshot", return_value={"main_pid": None}
            ):
                # Register target
                await server.project_register("research_test", str(target))

                # Check default snapshot
                default_snapshot = await server.bridge_overview()
                self.assertTrue(default_snapshot["ok"])
                self.assertIn("registered_project_refs", default_snapshot["project_state"])
                self.assertIn("research_test", default_snapshot["project_state"]["registered_project_refs"])
                self.assertIn("binding_guidance", default_snapshot["project_state"])
                self.assertIn("documents", default_snapshot["project_state"])
                self.assertNotIn("evolution_findings", default_snapshot["project_state"])

                # Check named snapshot
                named_snapshot = await server.bridge_overview("research_test")
                self.assertTrue(named_snapshot["ok"])
                self.assertEqual(named_snapshot["project_state"], {
                    "workspace": str(target),
                    "project_ref": "research_test",
                    "work_capacity": server._work_capacity("research_test", str(target)),
                    "continuity": server._project_continuity.describe(registry.resolve("research_test")),
                    "registration": registry.registration_view("research_test"),
                })
                self.assertNotIn("documents", named_snapshot["project_state"])
                self.assertNotIn("evolution_findings", named_snapshot["project_state"])
                self.assertNotIn("registered_project_refs", named_snapshot["project_state"])


if __name__ == "__main__":
    unittest.main()
