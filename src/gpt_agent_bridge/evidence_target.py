"""Immutable checkout evidence attached to an existing process-local Work."""

from dataclasses import dataclass
from pathlib import Path

from .workspace_context import (
    GitWorktreeIdentity,
    WorkspaceAuthorizationError,
    WorkspaceContext,
    canonical_git_worktree,
    validate_git_worktree_identity,
)


def _common(identity: GitWorktreeIdentity) -> tuple[str, int, int]:
    return (identity.git_common_dir, identity.git_common_device, identity.git_common_inode)


@dataclass(frozen=True)
class EvidenceCheckout:
    root: Path
    git: GitWorktreeIdentity

    @classmethod
    def capture(cls, project: WorkspaceContext, cwd: str) -> "EvidenceCheckout":
        root, identity = canonical_git_worktree(cwd)
        _, project_identity = canonical_git_worktree(project.root)
        if str(root) != cwd or _common(identity) != _common(project_identity):
            raise WorkspaceAuthorizationError("execution checkout does not match the project Git common-dir")
        if project.git is not None and project_identity != project.git:
            raise WorkspaceAuthorizationError("project worktree identity changed")
        return cls(root, identity)

    def revalidate(self, project: WorkspaceContext) -> WorkspaceContext:
        validate_git_worktree_identity(self.root, self.git)
        if project.git is None or _common(self.git) != _common(project.git):
            raise WorkspaceAuthorizationError("execution checkout Git common-dir changed")
        return WorkspaceContext(project.workspace_ref, self.root, self.git, str(self.root))


@dataclass(frozen=True)
class EvidenceTarget:
    project: WorkspaceContext
    workspace: WorkspaceContext
    work_ref: str | None

    def provenance(self) -> dict:
        return {
            "project_ref": self.project.workspace_ref,
            "project_root": str(self.project.root),
            "execution_target": str(self.workspace.root),
            "target_kind": "work_checkout" if self.work_ref is not None else "project_root",
            "work_ref": self.work_ref,
        }
