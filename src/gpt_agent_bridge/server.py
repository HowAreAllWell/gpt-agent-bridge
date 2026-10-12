from __future__ import annotations

import asyncio
import contextlib
import contextvars
from functools import partial
import threading
import errno
from datetime import datetime, timezone
import hashlib
import hmac
import json
import logging
import os
import re
import secrets
import stat
import subprocess
import time
import uuid
from pathlib import Path
from typing import Annotated, Any, AsyncIterator, Literal
from urllib.parse import urlsplit

from mcp.server import MCPServer
from mcp.server.apps import Apps
from mcp.server.transport_security import TransportSecuritySettings
from mcp.server.mcpserver import Image
from mcp.types import CallToolResult, TextContent, ToolAnnotations
from pydantic import BaseModel, ConfigDict, Field, StrictInt, StrictStr
from . import widget_watcher
from .tool_presentation import compact_result
from .read_schema import (NativeImageEnvelopeError, ReadResultModel, is_image_success_metadata,
                         native_image_result, read_tool_result)
from .work_reports import ReportStore, error as report_error

from .herdr_backend import DISCOVERY_REJECTION_CODES, HERDR_AGY_LABEL, MAX_REJECTION_DETAILS, HerdrBackend, ManualAgentPromptNotReady, HerdrError as HerdrBackendError, MAX_MANUAL_AGENT_READ_LINES
from . import agent_placement
from . import fixed_git
from .evidence_target import EvidenceCheckout, EvidenceTarget
from .project_continuity import ProjectContinuity
from .project_text_edit import TextEdit, text_edit
from .workspace_context import (
    MAX_WORKSPACE_REFS,
    WORKSPACE_REF_RE,
    WorkspaceAuthorizationError,
    WorkspaceContext,
    WorkspaceRegistry,
    WorkspaceRegistryStore,
    WorkspaceStoreError,
    canonical_git_worktree,
    validate_git_worktree_identity,
)


# ---------------------------------------------------------------------------
# Bootstrap configuration
# ---------------------------------------------------------------------------

_workspace = os.environ.get("BRIDGE_WORKSPACE", "")
if not _workspace or not Path(_workspace).is_absolute():
    raise RuntimeError("BRIDGE_WORKSPACE must be set to an absolute repository root")
ROOT = Path(_workspace).resolve()
if not ROOT.is_dir():
    raise RuntimeError("BRIDGE_WORKSPACE must be an existing repository root")
try:
    ROOT, _bootstrap_identity = canonical_git_worktree(ROOT)
except WorkspaceAuthorizationError as exc:
    raise RuntimeError("BRIDGE_WORKSPACE must name an exact non-bare Git repository root") from exc

BRIDGE_STARTED_AT = time.time()

PORT = int(os.environ.get("BRIDGE_PORT", "8765"))

TOKEN = os.environ.get("BRIDGE_PATH_TOKEN", "").strip()
if not TOKEN:
    raise RuntimeError("BRIDGE_PATH_TOKEN is not set")
if len(TOKEN) < 32:
    raise RuntimeError(
        "BRIDGE_PATH_TOKEN must be at least 32 characters long"
    )
if any(char not in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-._~" for char in TOKEN):
    raise RuntimeError(
        "BRIDGE_PATH_TOKEN must contain only RFC3986 unreserved ASCII "
        "characters (A-Z, a-z, 0-9, -, ., _, ~)"
    )

MCP_PATH = f"/mcp/{TOKEN}"

MCP_SECURITY_ENABLED_ENV = "BRIDGE_MCP_ENABLE_DNS_REBINDING_PROTECTION"
MCP_ALLOWED_HOSTS_ENV = "BRIDGE_MCP_ALLOWED_HOSTS"
MCP_ALLOWED_ORIGINS_ENV = "BRIDGE_MCP_ALLOWED_ORIGINS"
MCP_AUTH_SECRET_ENV = "BRIDGE_MCP_AUTH_SECRET"
MCP_AUTH_PREVIOUS_SECRET_ENV = "BRIDGE_MCP_AUTH_PREVIOUS_SECRET"
MCP_AUTH_MIN_LENGTH = 32


def _parse_security_boolean(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default

    value = raw.lower()
    if value not in {"true", "false"}:
        raise RuntimeError(f"{name} must be exactly 'true' or 'false'")
    return value == "true"


def _parse_exact_security_list(name: str) -> list[str]:
    raw = os.environ.get(name)
    if raw is None:
        return []

    try:
        values = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"{name} must be a JSON array of exact strings") from exc

    if not isinstance(values, list):
        raise RuntimeError(f"{name} must be a JSON array of exact strings")

    parsed: list[str] = []
    for index, value in enumerate(values):
        wildcard_port = value.endswith(":*") if isinstance(value, str) else False
        if (
            not isinstance(value, str)
            or not value
            or value != value.strip()
            or any(
                character.isspace() or ord(character) < 0x20
                for character in value
            )
            or ("*" in value and not wildcard_port)
        ):
            raise RuntimeError(
                f"{name}[{index}] must be a non-empty exact value without "
                "whitespace or unsupported wildcards"
            )
        if value in parsed:
            raise RuntimeError(f"{name} must not contain duplicate values")
        try:
            value_to_validate = value[:-2] if wildcard_port else value
            if value_to_validate.endswith(":"):
                valid = False
            elif name == MCP_ALLOWED_HOSTS_ENV:
                parsed_url = urlsplit(f"//{value_to_validate}")
                valid = (
                    parsed_url.hostname is not None
                    and not parsed_url.path
                    and not parsed_url.query
                    and not parsed_url.fragment
                    and parsed_url.username is None
                    and parsed_url.password is None
                )
                parsed_url.port
            elif value == "null":
                valid = True
            else:
                parsed_url = urlsplit(value_to_validate)
                valid = (
                    bool(parsed_url.scheme)
                    and parsed_url.hostname is not None
                    and not parsed_url.path
                    and not parsed_url.query
                    and not parsed_url.fragment
                    and parsed_url.username is None
                    and parsed_url.password is None
                )
                parsed_url.port
        except ValueError as exc:
            raise RuntimeError(f"{name}[{index}] is not a valid exact value") from exc
        if not valid:
            raise RuntimeError(f"{name}[{index}] is not a valid exact value")
        parsed.append(value)
    return parsed


def _transport_security_settings() -> TransportSecuritySettings:
    enabled = _parse_security_boolean(MCP_SECURITY_ENABLED_ENV)
    allowed_hosts = _parse_exact_security_list(MCP_ALLOWED_HOSTS_ENV)
    allowed_origins = _parse_exact_security_list(MCP_ALLOWED_ORIGINS_ENV)

    if not enabled:
        if allowed_hosts or allowed_origins:
            raise RuntimeError(
                f"{MCP_SECURITY_ENABLED_ENV}=true is required when "
                f"{MCP_ALLOWED_HOSTS_ENV} or {MCP_ALLOWED_ORIGINS_ENV} is set"
            )
        return TransportSecuritySettings(enable_dns_rebinding_protection=False)

    if not allowed_hosts:
        raise RuntimeError(
            f"{MCP_SECURITY_ENABLED_ENV}=true requires a non-empty "
            f"{MCP_ALLOWED_HOSTS_ENV} JSON array"
        )

    return TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=allowed_hosts,
        allowed_origins=allowed_origins,
    )


def _mcp_auth_secrets() -> tuple[str, ...]:
    """Return configured current and optional previous MCP secrets."""
    current = os.environ.get(MCP_AUTH_SECRET_ENV)
    previous = os.environ.get(MCP_AUTH_PREVIOUS_SECRET_ENV)

    if current is None and previous is None:
        return ()
    if current is None:
        raise RuntimeError(
            f"{MCP_AUTH_SECRET_ENV} is required when "
            f"{MCP_AUTH_PREVIOUS_SECRET_ENV} is set"
        )

    secrets: list[str] = []
    for name, value in (
        (MCP_AUTH_SECRET_ENV, current),
        (MCP_AUTH_PREVIOUS_SECRET_ENV, previous),
    ):
        if value is None:
            continue
        if (
            len(value) < MCP_AUTH_MIN_LENGTH
            or value != value.strip()
            or any(ord(character) < 0x21 or ord(character) > 0x7E for character in value)
        ):
            raise RuntimeError(
                f"{name} must be at least {MCP_AUTH_MIN_LENGTH} printable "
                "non-whitespace characters"
            )
        if value in secrets:
            raise RuntimeError(
                f"{MCP_AUTH_SECRET_ENV} and "
                f"{MCP_AUTH_PREVIOUS_SECRET_ENV} must differ"
            )
        secrets.append(value)
    return tuple(secrets)


class _MCPSharedSecretMiddleware:
    """Protect the exact MCP route with an optional rotating bearer secret."""

    def __init__(self, app: Any, path: str, secrets: tuple[str, ...]):
        self.app = app
        self.path = path
        self.secrets = secrets

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        if scope.get("type") != "http" or scope.get("path") != self.path:
            await self.app(scope, receive, send)
            return

        authorization_headers = [
            value
            for key, value in scope.get("headers", [])
            if key.lower() == b"authorization"
        ]
        authorization = (
            authorization_headers[0].decode("latin-1")
            if len(authorization_headers) == 1
            else ""
        )
        scheme, separator, presented = authorization.partition(" ")
        if not separator or scheme.lower() != "bearer":
            presented = ""
        authorized = bool(presented) and any(
            hmac.compare_digest(presented, secret) for secret in self.secrets
        )
        if authorized:
            await self.app(scope, receive, send)
            return

        body = b"MCP authentication required\n"
        await send(
            {
                "type": "http.response.start",
                "status": 401,
                "headers": [
                    (b"content-type", b"text/plain; charset=utf-8"),
                    (b"content-length", str(len(body)).encode("ascii")),
                    (b"www-authenticate", b"Bearer"),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})


_CATALOG_LOGGER = logging.getLogger("mcp.bridge.catalog")
_CATALOG_LOGGER.setLevel(logging.INFO)
_CATALOG_LOGGER.propagate = False
if not _CATALOG_LOGGER.handlers:
    # SDK rich formatting can wrap JSON across lines. Keep this event one plain line.
    _catalog_handler = logging.StreamHandler()
    _catalog_handler.setFormatter(logging.Formatter("%(message)s"))
    _CATALOG_LOGGER.addHandler(_catalog_handler)

_AWAIT_LEASE_LOGGER = logging.getLogger("mcp.bridge.await_segment")
_AWAIT_LEASE_LOGGER.setLevel(logging.INFO)
_AWAIT_LEASE_LOGGER.propagate = False
if not _AWAIT_LEASE_LOGGER.handlers:
    # Same one-plain-JSON-line discipline as the catalog event.
    _await_lease_handler = logging.StreamHandler()
    _await_lease_handler.setFormatter(logging.Formatter("%(message)s"))
    _AWAIT_LEASE_LOGGER.addHandler(_await_lease_handler)


_FOLLOWUP_CLAIM_LOGGER = logging.getLogger("mcp.bridge.followup_claim")
_FOLLOWUP_CLAIM_LOGGER.setLevel(logging.INFO)
_FOLLOWUP_CLAIM_LOGGER.propagate = False
if not _FOLLOWUP_CLAIM_LOGGER.handlers:
    # Same one-plain-JSON-line discipline as the lease configuration event.
    _followup_claim_handler = logging.StreamHandler()
    _followup_claim_handler.setFormatter(logging.Formatter("%(message)s"))
    _FOLLOWUP_CLAIM_LOGGER.addHandler(_followup_claim_handler)

_WORK_TERMINAL_LOGGER = logging.getLogger("mcp.bridge.work_terminal")
_WORK_TERMINAL_LOGGER.setLevel(logging.INFO)
_WORK_TERMINAL_LOGGER.propagate = False
if not _WORK_TERMINAL_LOGGER.handlers:
    # Same one-plain-JSON-line discipline. Never task text or terminal body.
    _work_terminal_handler = logging.StreamHandler()
    _work_terminal_handler.setFormatter(logging.Formatter("%(message)s"))
    _WORK_TERMINAL_LOGGER.addHandler(_work_terminal_handler)

_JOURNAL_TOKEN_RE = re.compile(r"^[A-Za-z0-9_.:-]{1,80}$")
_WORK_TERMINAL_ELAPSED_MS_CAP = 86_400_000


# Only an opaque digest crosses the request boundary into Work bookkeeping.
# The process key prevents raw/guessable host IDs from becoming stored identifiers.
_HOST_SESSION_HASH_KEY = secrets.token_bytes(32)
_HOST_SESSION_MAX_BYTES = 4096
_REQUEST_SESSION_CORRELATION: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    'bridge_request_session_correlation', default=None)
_DELEGATE_RESERVATIONS: contextvars.ContextVar[list[str] | None] = contextvars.ContextVar(
    'bridge_delegate_reservations', default=None)


def _host_session_correlation(context: Any) -> str | None:
    """MCP 2 Context supplies request metadata; no injected tool argument needed.

    Never retain Context, transport/session identity, or the raw metadata value.
    Absent, malformed, oversized and unsupported session shapes remain unknown.
    """
    try:
        meta = context.request_context.meta
        value = meta.get('openai/session') if isinstance(meta, dict) else None
        if not isinstance(value, str) or not value or len(value) > _HOST_SESSION_MAX_BYTES:
            return None
        encoded = value.encode('utf-8')
        if len(encoded) > _HOST_SESSION_MAX_BYTES:
            return None
        return hmac.new(_HOST_SESSION_HASH_KEY, encoded, hashlib.sha256).hexdigest()
    except (AttributeError, ValueError, TypeError, UnicodeError):
        return None


class _BridgeMCPServer(MCPServer):
    async def call_tool(self, name, arguments, context=None):
        token = _REQUEST_SESSION_CORRELATION.set(_host_session_correlation(context))
        try:
            result = await super().call_tool(name, arguments, context)
            return compact_result(result, name)
        finally:
            _REQUEST_SESSION_CORRELATION.reset(token)

    async def read_resource(self, uri, context=None):
        service = getattr(self, '_file_attachment_service', None)
        if service is not None and str(uri).startswith(ATTACH_RESOURCE_PREFIX):
            return await service.read_resource(str(uri))
        return await super().read_resource(uri, context)

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self._catalog_sequence = 0
        self._catalog_listing: dict[str, Any] | None = None
        super().__init__(*args, **kwargs)

    async def _handle_list_tools(self, ctx: Any, params: Any) -> Any:
        result = await super()._handle_list_tools(ctx, params)
        # Only the actual request handler records construction. Helper calls (including
        # bridge_health) do not. This is not a transport-send or client-receipt hook.
        try:
            self._catalog_sequence += 1
            descriptors = [tool.model_dump(mode="json", by_alias=True) for tool in result.tools]
            canonical = json.dumps(
                sorted(descriptors, key=lambda item: item["name"]),
                sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False,
            ).encode("utf-8")
            names = sorted(tool.name for tool in result.tools)
            observation = {
                "event": "bridge.catalog_listing",
                "status": "constructed",
                "utc": datetime.now(timezone.utc).isoformat(),
                "pid": os.getpid(),
                "sequence": self._catalog_sequence,
                "tool_count": len(result.tools),
                "names": [name[:128] for name in names[:64]],
                "names_truncated": len(names) > 64 or any(len(name) > 128 for name in names),
                "read_only_count": sum(
                    tool.annotations is not None and tool.annotations.read_only_hint is True
                    for tool in result.tools
                ),
                "descriptor_sha256": hashlib.sha256(canonical).hexdigest(),
                "cursor_present": result.next_cursor is not None,
            }
            # Store only bounded public metadata, never request context or descriptor bodies.
            self._catalog_listing = observation
            _CATALOG_LOGGER.info(json.dumps(observation, sort_keys=True, separators=(",", ":")))
        except Exception:
            # Diagnostics must not change the original list result, even if logging fails.
            # No exception text: it could carry data from a logging handler.
            pass
        return result

    def streamable_http_app(self, **kwargs: Any) -> Any:
        app = super().streamable_http_app(**kwargs)
        # Whole-server graceful shutdown owns report-store teardown exactly once:
        # the ASGI application lifespan runs the SDK/session-manager teardown first,
        # then closes the lazily created process-local store, before Uvicorn
        # re-raises SIGTERM. This is never a per-request or per-client-session
        # hook, startup/shutdown alone allocates no report directory, and forced
        # SIGKILL/crash residue remains accepted and outside this guarantee.
        inner_lifespan = app.router.lifespan_context

        @contextlib.asynccontextmanager
        async def _lifespan_close_report_store(asgi_app: Any) -> AsyncIterator[None]:
            try:
                async with inner_lifespan(asgi_app):
                    yield
            finally:
                _REPORT_STORE.close()

        app.router.lifespan_context = _lifespan_close_report_store
        secrets = _mcp_auth_secrets()
        if secrets:
            app.add_middleware(
                _MCPSharedSecretMiddleware,
                path=MCP_PATH,
                secrets=secrets,
            )
        return app


MAX_TEXT = 4000
MAX_ACTIVE_READERS = 4


HERDR_STREAM_LIMIT = 8 * 1024 * 1024

HERDR = HerdrBackend(ROOT, HERDR_STREAM_LIMIT)

_WORKSPACE_BACKENDS: dict[str, HerdrBackend] = {}
_WORKSPACE_STORE = WorkspaceRegistryStore()
_WORKSPACE_REGISTRY = WorkspaceRegistry(ROOT, store=_WORKSPACE_STORE)


def _workspace_backend(context: WorkspaceContext) -> HerdrBackend:
    """Return the exact root-scoped backend for an authorized context."""
    if context.workspace_ref is None:
        return HERDR
    key = str(context.root)
    backend = _WORKSPACE_BACKENDS.get(key)
    if backend is None:
        backend = HerdrBackend(
            context.root,
            HERDR_STREAM_LIMIT,
        )
        _WORKSPACE_BACKENDS[key] = backend
    return backend


def _workspace_context(workspace_ref: str | None = None) -> WorkspaceContext:
    context = _WORKSPACE_REGISTRY.resolve(workspace_ref, default_root=ROOT)
    return WorkspaceContext(
        context.workspace_ref,
        context.root,
        context.git,
        context.gate_key,
        _workspace_backend(context),
    )


_ACCESS_GATES: dict[str, "_AccessGate"] = {}
# Manual candidates are deliberately process-local. They are discovery handles,
# never lifecycle resources, and disappear rather than being reconstructed after
# a Bridge restart.
_MANUAL_AGENT_CANDIDATES: dict[str, dict[str, Any]] = {}


PROJECT_DOCUMENTS = {
    "AGENTS.md": "AGENTS.md",
    "docs/LIFECYCLE-RESTART-CONTRACT.md": "docs/LIFECYCLE-RESTART-CONTRACT.md",
    "docs/PROJECT-CONTINUITY.md": "docs/PROJECT-CONTINUITY.md",
}
MAX_MANUAL_AGENT_CANDIDATES = 128
MAX_MANUAL_AGENT_TASK_CHARS = 16 * 1024


class _AccessLease:
    def __init__(self, gate: "_AccessGate", mode: str):
        self.gate = gate
        self.mode = mode
        self.released = False

    async def release(self) -> None:
        if not self.released:
            self.released = True
            await self.gate.release(self.mode)


class _AccessGate:
    """Process-local worktree gate; it makes no cross-Bridge claim."""

    def __init__(self, worktree: str):
        self.worktree = worktree
        self.loop = asyncio.get_running_loop()
        self.condition = asyncio.Condition()
        self.active_readers = 0
        self.writer_active = False
        self.waiting_writers = 0
        self.waiting_readers = 0

    async def acquire(self, mode: str) -> _AccessLease:
        is_writer = mode == "writer"
        async with self.condition:
            if is_writer:
                self.waiting_writers += 1
            else:
                self.waiting_readers += 1
            try:
                while True:
                    if is_writer:
                        available = not self.writer_active and self.active_readers == 0
                    else:
                        available = (
                            not self.writer_active
                            and self.waiting_writers == 0
                            and self.active_readers < MAX_ACTIVE_READERS
                        )
                    if available:
                        break
                    await self.condition.wait()
            except asyncio.CancelledError:
                if is_writer:
                    self.waiting_writers -= 1
                else:
                    self.waiting_readers -= 1
                self.condition.notify_all()
                raise
            if is_writer:
                self.waiting_writers -= 1
                self.writer_active = True
            else:
                self.waiting_readers -= 1
                self.active_readers += 1
            return _AccessLease(self, mode)

    async def release(self, mode: str) -> None:
        async with self.condition:
            if mode == "writer":
                self.writer_active = False
            elif self.active_readers > 0:
                self.active_readers -= 1
            self.condition.notify_all()

    def snapshot(self) -> dict[str, Any]:
        return {
            "worktree": self.worktree,
            "writer_active": self.writer_active,
            "active_readers": self.active_readers,
            "waiting_writers": self.waiting_writers,
            "waiting_readers": self.waiting_readers,
            "max_active_readers": MAX_ACTIVE_READERS,
            "scope": "process_local",
        }


def _access_gate(worktree: Path | str | None = None) -> _AccessGate:
    key = str(Path(worktree or ROOT).resolve())
    gate = _ACCESS_GATES.get(key)
    if (
        gate is not None
        and gate.loop.is_closed()
    ):
        gate = None
    if gate is None:
        gate = _AccessGate(key)
        _ACCESS_GATES[key] = gate
    return gate


def _git_inspect_small(*args: str, root: Path | None = None) -> str | None:
    rc, raw, _ = fixed_git.observe(root or ROOT, args, timeout=3, stdout_limit=65536)
    return raw.decode("utf-8", errors="replace").strip() if rc == 0 else None


def _workspace_boundary_snapshot(root: Path | None = None) -> dict[str, Any]:
    target_root = (root or ROOT).resolve()
    snapshot: dict[str, Any] = {
        "head": _git_inspect_small("rev-parse", "--verify", "HEAD", root=target_root),
        "branch": _git_inspect_small("rev-parse", "--abbrev-ref", "HEAD", root=target_root),
        "status_short": _git_inspect_small("status", "--short", root=target_root),
        "tracked_worktree_shortstat": _git_inspect_small(
            "diff", "--shortstat", "HEAD", "--", root=target_root
        ),
    }
    errors = [name for name, value in snapshot.items() if value is None]
    snapshot["submodule_worktrees"] = "not_observed"
    snapshot["dirty"] = bool(snapshot["status_short"]) if snapshot["status_short"] is not None else None
    if errors:
        snapshot["capture_error"] = "git snapshot command failed: " + ", ".join(errors)
    return snapshot


async def _capture_workspace_boundary(root: Path | None = None) -> dict[str, Any]:
    return await asyncio.to_thread(_workspace_boundary_snapshot, root)


# One ui:// cohort widget, bound only by delegate.
# Live acceptance is recorded separately from source behavior.
# Non-Apps hosts must
# ignore the additive extension advertisement and unknown `_meta` keys
# (text-only behavior kept).
_APPS_EXTENSION = Apps()
_APPS_EXTENSION.add_html_resource(
    widget_watcher.WIDGET_RESOURCE_URI,
    widget_watcher.widget_html(),
    name="bridge-work-watcher",
    title="Bridge continuation watcher",
    description=(
        "One explicit Work batch watcher. It waits for final classification and can "
        "request one follow-up per batch. Classification is not task success."
    ),
)

mcp = _BridgeMCPServer(
    "GPT-Agent Bridge Bootstrap",
    instructions=(
        "Project-scoped tools require an explicit project_ref. context returns Agent handles "
        "and continuity pointers. Work refs are process-local. Tool descriptions "
        "define each call's effects and evidence limits."
    ),
    extensions=(_APPS_EXTENSION,),
)


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------

def _truncate(text: str, limit: int = MAX_TEXT) -> str:
    text = text or ""
    if len(text) <= limit:
        return text

    return text[:limit] + f"\n...[truncated {len(text) - limit} chars]"


def _bounded_nullable_text(value: Any, limit: int = MAX_TEXT) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        value = str(value)
    return _truncate(value, limit)


def _manual_candidate_response(candidate_id: str, candidate: dict[str, Any]) -> dict[str, Any]:
    public = candidate.get("public")
    if not isinstance(public, dict):
        raise HerdrBackendError("agent candidate has no public projection")
    return {"candidate_id": candidate_id, **public}


def _manual_candidate_workspace(record: dict[str, Any]) -> WorkspaceContext:
    workspace = _workspace_context(record.get("workspace_ref"))
    if (
        workspace.root != Path(record.get("workspace_root", "")).resolve()
        or workspace.git != record.get("_workspace_git_identity")
        or workspace.backend is not record.get("_workspace_backend")
    ):
        raise WorkspaceAuthorizationError(
            "manual candidate workspace authorization or identity changed"
        )
    return workspace


def _remember_manual_candidate(
    workspace: WorkspaceContext,
    candidate: dict[str, Any],
) -> str:
    candidate_key = candidate.get("candidate_key")
    if not isinstance(candidate_key, str) or not candidate_key:
        raise HerdrBackendError("manual agent candidate continuity key is unavailable")
    resource_key = candidate.get("resource_key")
    for candidate_id, record in _MANUAL_AGENT_CANDIDATES.items():
        if (
            record.get("workspace_ref") == workspace.workspace_ref
            and record.get("workspace_root") == str(workspace.root)
            and record.get("_workspace_git_identity") == workspace.git
            and record.get("_workspace_backend") is workspace.backend
            and isinstance(record.get("candidate"), dict)
        ):
            rec_cand = record["candidate"]
            rec_resource_key = rec_cand.get("resource_key")
            if (
                isinstance(resource_key, str)
                and resource_key
                and rec_resource_key == resource_key
            ) or (
                resource_key is None
                and rec_resource_key is None
                and rec_cand.get("candidate_key") == candidate_key
            ):
                record["last_seen_at"] = time.monotonic()
                record["candidate"] = candidate
                return candidate_id
    if len(_MANUAL_AGENT_CANDIDATES) >= MAX_MANUAL_AGENT_CANDIDATES:
        oldest_id = min(
            _MANUAL_AGENT_CANDIDATES,
            key=lambda key: _MANUAL_AGENT_CANDIDATES[key].get("last_seen_at", 0.0),
        )
        _MANUAL_AGENT_CANDIDATES.pop(oldest_id, None)
    candidate_id = uuid.uuid4().hex
    _MANUAL_AGENT_CANDIDATES[candidate_id] = {
        "workspace_ref": workspace.workspace_ref,
        "workspace_root": str(workspace.root),
        "_workspace_git_identity": workspace.git,
        "_workspace_backend": workspace.backend,
        "candidate": candidate,
        "created_at": time.monotonic(),
        "last_seen_at": time.monotonic(),
    }
    return candidate_id


def _manual_candidate_record(candidate_id: str) -> dict[str, Any] | None:
    if not isinstance(candidate_id, str) or not re.fullmatch(r"[0-9a-f]{32}", candidate_id):
        return None
    record = _MANUAL_AGENT_CANDIDATES.get(candidate_id)
    return record if isinstance(record, dict) else None


def _rejection_diagnostics(value: Any, rejected: int, truncated: int,
                           projection_rejected: int = 0) -> dict[str, Any]:
    """Validate the current bounded contract; never forward arbitrary diagnostics."""
    unavailable = {"status": "unavailable"}
    if not isinstance(value, dict) or set(value) != {
        "status", "reason_counts", "details", "unlocalized_count",
        "omitted_local_count", "truncated_candidates"
    } or value["status"] != "available":
        return unavailable
    counts, details = value["reason_counts"], value["details"]
    if (not isinstance(counts, dict) or set(counts) != set(DISCOVERY_REJECTION_CODES)
            or any(type(n) is not int or n < 0 for n in counts.values())
            or sum(counts.values()) != rejected
            or any(type(value[k]) is not int or value[k] < 0 for k in
                   ("unlocalized_count", "omitted_local_count", "truncated_candidates"))
            or value["truncated_candidates"] != truncated
            or not isinstance(details, list) or len(details) > MAX_REJECTION_DETAILS
            or len(details) + value["unlocalized_count"] + value["omitted_local_count"] != rejected):
        return unavailable
    detail_counts = {}
    for detail in details:
        if (not isinstance(detail, dict) or set(detail) != {"stage", "reason", "kind", "hint"}
                or not isinstance(detail["reason"], str) or detail["reason"] not in counts
                or detail["stage"] != detail["reason"].split("_", 1)[0]
                or not isinstance(detail["kind"], str)
                or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}", detail["kind"])
                or not isinstance(detail["hint"], str)
                or not re.fullmatch(r"tab [0-9]{1,6} / pane [0-9]{1,6}", detail["hint"])):
            return unavailable
        detail_counts[detail["reason"]] = detail_counts.get(detail["reason"], 0) + 1
    if any(n > counts[reason] for reason, n in detail_counts.items()):
        return unavailable
    counts = dict(counts)
    counts["projection_invalid"] += projection_rejected
    return {**value, "reason_counts": counts, "details": [dict(d) for d in details],
            "unlocalized_count": value["unlocalized_count"] + projection_rejected}


async def _discover_project_candidates(
    workspace_ref: str | None = None,
) -> dict[str, Any]:
    """Discover current generic project candidates for internal projection."""
    if workspace_ref is not None and (
        not isinstance(workspace_ref, str) or not workspace_ref.strip()
    ):
        raise ValueError("workspace_ref must be a non-empty authorized reference when supplied")
    try:
        workspace = _workspace_context(workspace_ref)
    except WorkspaceAuthorizationError:
        return {
            "ok": False,
            "error_type": "WorkspaceRefUnauthorized",
            "error": "workspace_ref is not authorized or its registered Git worktree is no longer valid",
        }
    try:
        discovery = await workspace.backend.manual_agent_candidates()
        if not isinstance(discovery, dict) or not isinstance(discovery.get("candidates"), list):
            raise HerdrBackendError("generic candidate discovery was malformed")
        skipped = discovery.get("skipped_count", 0)
        if not isinstance(skipped, int) or isinstance(skipped, bool) or skipped < 0:
            raise HerdrBackendError("generic discovery coverage was malformed")
        counts = discovery.get("coverage_counts")
        if (not isinstance(counts, dict)
                or set(counts) != {"out_of_project", "invalid_or_unavailable", "truncated"}
                or any(not isinstance(n, int) or isinstance(n, bool) or n < 0 for n in counts.values())
                or counts["invalid_or_unavailable"] != skipped
                or bool(counts["truncated"]) != bool(discovery.get("candidates_truncated", False))):
            raise HerdrBackendError("generic discovery coverage was malformed")
        counts = dict(counts)
        diagnostics = _rejection_diagnostics(discovery.get("rejection_diagnostics"),
                                             skipped, counts["truncated"])
        original_skipped = skipped
        candidates: list[dict[str, Any]] = []
        placement_sources = []
        for candidate in discovery["candidates"]:
            if not isinstance(candidate, dict):
                skipped += 1
                counts["invalid_or_unavailable"] += 1
                continue
            try:
                _manual_candidate_response("", candidate)  # Validate before issuing a handle.
                candidate_id = _remember_manual_candidate(workspace, candidate)
                public = _manual_candidate_response(candidate_id, candidate)
                candidates.append(public)
                placement_sources.append(candidate)
            except (KeyError, TypeError, ValueError, AttributeError):
                skipped += 1
                counts["invalid_or_unavailable"] += 1
    except Exception as exc:
        return {
            "ok": False,
            "workspace_ref": workspace.workspace_ref,
            "error_type": "ManualAgentDiscoveryUnavailable",
            "error": _bounded_nullable_text(str(exc), 1000),
        }

    # Optional display enrichment cannot turn a usable roster into failed discovery.
    try:
        placements = await agent_placement.observe_all(workspace, placement_sources)
    except Exception:
        placements = [agent_placement.unavailable() for _ in candidates]
    for candidate, placement in zip(candidates, placements):
        candidate["checkout"] = placement
    return {
        "ok": True,
        "workspace_ref": workspace.workspace_ref,
        "candidates": candidates,
        "candidate_count": len(candidates),
        "candidates_truncated": bool(discovery.get("candidates_truncated", False)),
        "skipped_count": skipped,
        "coverage_counts": counts,
        "rejection_diagnostics": _rejection_diagnostics(
            diagnostics, original_skipped, counts["truncated"], skipped - original_skipped),
    }


def _classify_manual_agent_read_error(exc: Exception) -> tuple[str, str]:
    code = getattr(exc, "code", None)
    if code in {
        "manual_candidate_identity_lost",
        "manual_candidate_continuity_lost",
    }:
        return "ManualCandidateContinuityLost", "candidate_continuity_lost"
    if code in {
        "manual_candidate_observation_unavailable",
        "manual_candidate_process_unavailable",
        "manual_candidate_read_unavailable",
    }:
        return "ManualCandidateObservationUnavailable", "observation_unavailable"
    return "ManualCandidateRevalidationUncertain", "revalidation_uncertain"


async def _read_agent_candidate(
    candidate_id: str,
    limit: int = 120,
) -> dict[str, Any]:
    """Read bounded current terminal output after exact candidate revalidation."""
    record = _manual_candidate_record(candidate_id)
    if record is None:
        return {
            "ok": False,
            "candidate_id": candidate_id if isinstance(candidate_id, str) else None,
            "error_type": "UnknownManualAgentCandidate",
            "error": "candidate_id is unknown to this Bridge process or was lost after restart",
        }
    if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= MAX_MANUAL_AGENT_READ_LINES:
        raise ValueError(f"limit must be between 1 and {MAX_MANUAL_AGENT_READ_LINES}")
    try:
        workspace = _manual_candidate_workspace(record)
    except WorkspaceAuthorizationError:
        return {
            "ok": False,
            "candidate_id": candidate_id,
            "error_type": "ManualCandidateWorkspaceUnauthorized",
            "error": "candidate workspace authorization is no longer valid",
        }
    candidate = record.get("candidate")
    if not isinstance(candidate, dict):
        return {
            "ok": False,
            "candidate_id": candidate_id,
            "error_type": "ManualCandidateRevalidationUncertain",
            "reason": "revalidation_uncertain",
            "error": "candidate identity is unavailable",
        }
    try:
        read = await workspace.backend.read_manual_agent(
            candidate, limit=limit, allow_session_promotion=True
        )
    except HerdrBackendError as exc:
        error_type, reason = _classify_manual_agent_read_error(exc)
        return {
            "ok": False,
            "candidate_id": candidate_id,
            "error_type": error_type,
            "reason": reason,
            "error": _bounded_nullable_text(str(exc), 1000),
        }
    current = read["candidate"]
    record["candidate"] = current
    record["last_seen_at"] = time.monotonic()
    return {
        "ok": True,
        "candidate": _manual_candidate_response(candidate_id, current),
        "read": {
            "text": read["text"],
            "chars": read["chars"],
            "truncated": read["truncated"],
            "source": read["source"],
            "limit": limit,
        },
        "attribution": "unattributed_current_terminal_output",
    }


def _validate_manual_agent_task(task: Any) -> None:
    if not isinstance(task, str) or not task.strip():
        raise ValueError("task must be a non-empty string")
    if len(task) > MAX_MANUAL_AGENT_TASK_CHARS:
        raise ValueError(f"task exceeds the {MAX_MANUAL_AGENT_TASK_CHARS}-character limit")


def _execution_identity(
    workspace_root: str | None,
    candidate: dict[str, Any] | None,
) -> str | None:
    """Compute an immutable session-independent execution identity for in-flight turn exclusion.

    Binds:
    - exact project/workspace scope (workspace_root)
    - agent_kind and agent_name
    - workspace_id, tab_id, pane_id, terminal_id
    - validated chosen execution checkout (cwd)
    - AVAILABLE foreground-process fingerprint

    Excludes agent_session and optional raw foreground_cwd observations. A missing
    foreground observation falls back to reported cwd during candidate validation;
    absent/present observations choosing the same checkout must have the same key.
    Neither observation changes nor session strengthening may bypass in-flight exclusion.
    Missing,
    unsupported, or unavailable process evidence yields None (no equivalence).
    Process replacement or static scope/identity changes produce a different identity.
    """
    if not isinstance(workspace_root, str) or not workspace_root:
        return None
    if not isinstance(candidate, dict):
        return None

    identity = candidate.get("identity")
    if not isinstance(identity, dict):
        return None

    agent_kind = identity.get("agent_kind")
    if not isinstance(agent_kind, str) or not agent_kind:
        return None

    agent_name = identity.get("agent_name")
    if agent_name is not None and not isinstance(agent_name, str):
        return None

    workspace_id = identity.get("workspace_id")
    tab_id = identity.get("tab_id")
    pane_id = identity.get("pane_id")
    terminal_id = identity.get("terminal_id")
    cwd = identity.get("cwd")

    for val in (workspace_id, tab_id, pane_id, terminal_id, cwd):
        if not isinstance(val, str) or not val:
            return None

    process = candidate.get("process")
    if not isinstance(process, dict):
        return None
    if process.get("available") is not True:
        return None
    fingerprint = process.get("fingerprint")
    if not fingerprint or not isinstance(fingerprint, (dict, str)):
        return None

    payload = {
        "agent_kind": agent_kind,
        "agent_name": agent_name,
        "cwd": cwd,
        "pane_id": pane_id,
        "process_fingerprint": fingerprint,
        "tab_id": tab_id,
        "terminal_id": terminal_id,
        "workspace_id": workspace_id,
        "workspace_scope": workspace_root,
    }
    return hashlib.sha256(
        json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    ).hexdigest()


async def _dispatch_manual_turn(
    candidate_id: str,
    record: dict[str, Any],
    task: str,
    work_entry: dict[str, Any],
) -> dict[str, Any]:
    """Dispatch the exact resource for one already-reserved Work.

    Reserved Work has no execution authority until this writer-gated resource
    refresh binds it immediately before handoff reservation and native prompt
    mutation, so ordinary success and transport uncertainty cannot create
    inaccessible work.
    """
    try:
        workspace = _manual_candidate_workspace(record)
    except WorkspaceAuthorizationError:
        return {
            "ok": False,
            "candidate_id": candidate_id,
            "error_type": "ManualCandidateWorkspaceUnauthorized",
            "error": "candidate workspace authorization is no longer valid",
        }
    candidate = record.get("candidate")
    if not isinstance(candidate, dict):
        return {
            "ok": False,
            "candidate_id": candidate_id,
            "error_type": "ManualCandidateRevalidationUncertain",
            "error": "candidate identity is unavailable",
        }
    lease = await _access_gate(workspace.root).acquire("writer")
    try:
        try:
            current = await workspace.backend.revalidate_manual_agent_resource(candidate)
        except HerdrBackendError as exc:
            error_type, _reason = _classify_manual_agent_read_error(exc)
            return {
                "ok": False,
                "candidate_id": candidate_id,
                "error_type": error_type,
                "error": _bounded_nullable_text(str(exc), 1000),
            }
        record["candidate"] = current
        record["last_seen_at"] = time.monotonic()
        capability = workspace.backend.manual_prompt_capability(current)
        pre_seq = current.get("_raw_state_change_seq")
        pre_rev = current.get("_raw_revision")
        current_resource_key = current.get("resource_key")
        current_exec_id = _execution_identity(
            record.get("workspace_root") or str(workspace.root), current
        )
        if (
            not isinstance(current_resource_key, str)
            or not current_resource_key
            or current_exec_id is None
        ):
            return {
                "ok": False,
                "candidate_id": candidate_id,
                "error_type": "ManualCandidateRevalidationUncertain",
                "error": "candidate resource or execution identity is unavailable after writer-gated refresh",
            }
        # Prevent concurrent prompts to the same stable Agent resource, handle,
        # or execution while an unconsumed handoff exists — or while a consumed
        # handoff's watcher is inside the AGY composer-recovery window.
        existing_hid = next(
            (
                hid
                for hid, h in _HANDOFF_REGISTRY.items()
                if (
                    h.get("candidate_id") == candidate_id
                    or h.get("resource_key") == current_resource_key
                    or (
                        current_exec_id is not None
                        and h.get("execution_identity") is not None
                        and h.get("execution_identity") == current_exec_id
                    )
                )
                and (not h.get("joined_once", False) or h.get("agy_recovery_active"))
            ),
            None,
        )
        if existing_hid is not None:
            return {
                "ok": False,
                "candidate": _manual_candidate_response(candidate_id, current),
                "error_type": "AgentHandoffInFlight",
                "error": f"an active handoff is already in flight for this candidate: {existing_hid}",
                "in_flight_handoff_id": existing_hid,
            }

        if (
            work_entry.get("resource_key") != current_resource_key
            or work_entry.get("agent_key") is not None
            or work_entry.get("execution_identity") is not None
        ):
            return {
                "ok": False,
                "candidate_id": candidate_id,
                "error_type": "ManualCandidateRevalidationUncertain",
                "error": "reserved Work cannot be rebound to a different or already-bound execution",
            }
        with _WORK_REGISTRY_LOCK:
            gap = _prior_evidence_gap(work_entry, current_resource_key)
        if gap and gap['kind'] == 'terminal_diagnostics':
            return {'ok': False, 'error_type': 'PriorWorkDiagnosticsRequired',
                    'error': 'No prompt/input sent. Use agent_terminal_read for this Agent before delegating again; '
                             'Bridge has no qualifying post-condition terminal diagnostics serving recorded.',
                    'prior_work': gap,
                    'submission_evidence': {'state': 'not_attempted', 'mutation_possible': False,
                                            'proves': 'no_input_attempted'}}
        if gap:
            work_entry['prior_work_advisory'] = gap
        try:
            current_checkout = EvidenceCheckout.capture(workspace, current["identity"]["cwd"])
        except (WorkspaceAuthorizationError, KeyError, TypeError, ValueError):
            current_checkout = None
        if current_checkout is not None and current_checkout.root != workspace.root:
            # Exact identity revalidation only. A shared checkout is not an
            # admission restriction: no checkout-wide gate and no collision
            # rejection serialize independent Agent resources here.
            try:
                current_checkout.revalidate(workspace)
            except WorkspaceAuthorizationError:
                return {"ok": False, "error_type": "ManualCandidateRevalidationUncertain",
                        "error": "execution checkout identity changed before dispatch"}
        work_entry["agent_key"] = current.get("candidate_key")
        work_entry["execution_identity"] = current_exec_id
        # Freeze exactly the checkout checked under admission, without recapture.
        work_entry["evidence_checkout"] = current_checkout
        if current_checkout is not None:
            current = dict(current, _work_checkout=current_checkout)

        try:
            handoff_entry = _reserve_handoff(
                candidate_id=candidate_id,
                candidate=current,
                workspace_ref=record.get("workspace_ref"),
                pre_seq=pre_seq,
                pre_rev=pre_rev,
                workspace_root=record.get("workspace_root") or str(workspace.root),
            )
        except HandoffRegistryFullError as exc:
            return {
                "ok": False,
                "candidate": _manual_candidate_response(candidate_id, current),
                "error_type": "HandoffRegistryFull",
                "error": _bounded_nullable_text(str(exc), 1000),
                "capacity": exc.capacity,
            }
        handoff_id = handoff_entry["handoff_id"]
        work_entry["handoff_id"] = handoff_id
        handoff_entry["work_ref"] = work_entry["work_ref"]
        handoff_entry["submission_evidence"] = work_entry["submission_evidence"]
        # Conservative until the backend establishes a local no-input refusal or
        # crosses the native call boundary and records its receipt.
        work_entry["submission_evidence"].update(
            state="delivery_unknown", mutation_possible=True, proves="delivery_unknown")

        # In-memory-only recovery seam for the AGY cold-path composer recovery:
        # the exact task text travels with the watcher coroutine and is never
        # persisted to the handoff entry, receipts, or logs.
        dispatch_identity = current.get("identity") if isinstance(current, dict) else None
        recovery_task = (
            task
            if isinstance(dispatch_identity, dict)
            and dispatch_identity.get("agent_kind") == HERDR_AGY_LABEL
            else None
        )
        try:
            transport = await workspace.backend.prompt_manual_agent(
                current, task, submission_evidence=work_entry["submission_evidence"])
            _mark_handoff_dispatched(handoff_id)
            _start_handoff_watcher(workspace.backend, handoff_entry,
                                   recovery_task=(recovery_task if work_entry["submission_evidence"].get(
                                       "state") == "native_acknowledged" else None))
        except asyncio.CancelledError:
            _mark_handoff_dispatched(handoff_id)
            # Caller cancellation is an explicit ambiguity: the watcher still
            # owns the reserved Work, but it never auto-reprompts a cancelled
            # dispatch — exhaustion keeps the existing attention outcome.
            _start_handoff_watcher(workspace.backend, handoff_entry)
            raise
        except ManualAgentPromptNotReady as exc:
            _discard_handoff(handoff_id)
            work_entry["handoff_id"] = None
            _discard_work(work_entry["work_ref"])
            return {
                "ok": False,
                "candidate": _manual_candidate_response(candidate_id, current),
                "error_type": "ManualAgentPromptNotReady",
                "error": _bounded_nullable_text(str(exc), 1000),
                "prompt_transport": {
                    **capability,
                    "status": "not_attempted",
                    "reason": "bridge_status_not_ordinary_turn_target",
                },
            }
        except Exception as exc:
            _mark_handoff_dispatched(handoff_id)
            # An uncertain mutation never authorizes automatic redelivery.
            _start_handoff_watcher(workspace.backend, handoff_entry)
            native_code = exc.code if isinstance(exc, HerdrBackendError) else None
            reason = (
                "native_herdr_request_timeout"
                if isinstance(exc, TimeoutError)
                else "native_herdr_request_uncertain"
            )
            error = _bounded_nullable_text(str(exc), 1000)
            # Only prompt transport may echo the augmented task/private path.
            # Keep local refusal and pre-prompt diagnostics, including a known
            # no-input error from the backend's submission-evidence boundary.
            if ('report_key' in work_entry
                    and work_entry['submission_evidence'].get('mutation_possible') is not False):
                error = 'Report-enabled dispatch unavailable; inspect Work submission evidence'
            resp = {
                "ok": False,
                "candidate": _manual_candidate_response(candidate_id, current),
                "error_type": "ManualAgentPromptTransportError",
                "error": error,
                "prompt_transport": {
                    **capability,
                    "status": "transport_uncertain",
                    "reason": reason,
                },
                "handoff_id": handoff_id,
                "handoff": {
                    "handoff_id": handoff_id,
                    "state": "running",
                    "herdr_status": current.get("herdr_status") or "unknown",
                    "pre_state_change_seq": pre_seq,
                    "post_state_change_seq": None,
                    "pre_revision": pre_rev,
                    "post_revision": None,
                },
                "completion": "unattributed",
                "result": "unattributed",
                "attribution": "none",
            }
            if native_code is not None:
                resp["native_error_code"] = native_code
            return resp
    finally:
        await lease.release()
    return {
        "ok": True,
        "candidate": _manual_candidate_response(candidate_id, current),
        "state": "native_herdr_response_received",
        "prompt_transport": transport,
        "handoff_id": handoff_id,
        "handoff": {
            "handoff_id": handoff_id,
            "state": "running",
            "herdr_status": current.get("herdr_status") or "unknown",
            "pre_state_change_seq": pre_seq,
            "post_state_change_seq": None,
            "pre_revision": pre_rev,
            "post_revision": None,
        },
        "completion": "unattributed",
        "result": "unattributed",
        "attribution": "none",
    }


MAX_HANDOFF_RECORDS = 128

_HANDOFF_REGISTRY: dict[str, dict[str, Any]] = {}


class ProjectCapacityError(Exception):
    """Only the requesting project's observed capacity is disclosed."""

    def __init__(self, dimension: str, count: int, limit: int, **counts: int):
        super().__init__(f"project {dimension} capacity exhausted ({count}/{limit}); no prompt was sent")
        self.capacity = {"scope": "project", "dimension": dimension,
                         "count": count, "limit": limit, **counts}


class HandoffRegistryFullError(ProjectCapacityError):
    """Raised when this project's internal handoff pool is exhausted."""


def _generate_handoff_id() -> str:
    return f"handoff-{uuid.uuid4().hex[:16]}"


def _reserve_handoff(
    candidate_id: str,
    candidate: dict[str, Any],
    workspace_ref: str | None,
    pre_seq: Any,
    pre_rev: Any,
    workspace_root: str | None = None,
) -> dict[str, Any]:
    root = workspace_root or candidate.get("identity", {}).get("cwd")
    scoped = {
        hid: h for hid, h in _HANDOFF_REGISTRY.items()
        if h.get("workspace_ref") == workspace_ref and h.get("workspace_root") == root
    }
    if len(scoped) >= MAX_HANDOFF_RECORDS:
        prunable = [
            hid for hid, h in scoped.items()
            if h.get("state") in {"done", "needs_attention", "failed"}
            and h.get("joined_once", False) is True
            and (h.get("watcher_task") is None or h["watcher_task"].done())
        ]
        for hid in prunable[:max(0, len(scoped) - MAX_HANDOFF_RECORDS + 1)]:
            _HANDOFF_REGISTRY.pop(hid, None)
            scoped.pop(hid)
        if len(scoped) >= MAX_HANDOFF_RECORDS:
            raise HandoffRegistryFullError("handoff_retained", len(scoped), MAX_HANDOFF_RECORDS)

    handoff_id = _generate_handoff_id()
    exec_id = _execution_identity(root, candidate)
    entry = {
        "handoff_id": handoff_id,
        "candidate_id": candidate_id,
        "candidate": dict(candidate),
        "workspace_ref": workspace_ref,
        "workspace_root": root,
        "resource_key": candidate.get("resource_key"),
        "execution_identity": exec_id,
        "dispatched_at": None,
        "state": "running",
        "reason": "running",
        "herdr_status": candidate.get("herdr_status") or "unknown",
        "pre_state_change_seq": pre_seq,
        "post_state_change_seq": None,
        "pre_revision": pre_rev,
        "post_revision": None,
        "latched_at": None,
        "watcher_task": None,
        "joined_once": False,
    }
    _HANDOFF_REGISTRY[handoff_id] = entry
    return entry


def _discard_handoff(handoff_id: str) -> None:
    _HANDOFF_REGISTRY.pop(handoff_id, None)


def _mark_handoff_dispatched(handoff_id: str) -> None:
    entry = _HANDOFF_REGISTRY.get(handoff_id)
    if entry is not None:
        entry["dispatched_at"] = time.time()


def _update_handoff_entry(
    handoff_id: str,
    state: str,
    reason: str,
    herdr_status: str | None = None,
    post_seq: Any = None,
    post_rev: Any = None,
    candidate: dict[str, Any] | None = None,
    agy_recovery_reprompt: bool = False,
    watcher_error_code: str | None = None,
) -> None:
    entry = _HANDOFF_REGISTRY.get(handoff_id)
    if entry is None:
        return
    if entry.get("state") in {"done", "needs_attention", "failed"}:
        return
    entry["state"] = state
    entry["reason"] = reason
    # The watcher is terminal: the AGY recovery window no longer blocks
    # same-resource dispatch.
    entry.pop("agy_recovery_active", None)
    if herdr_status is not None:
        entry["herdr_status"] = herdr_status
    if post_seq is not None:
        entry["post_state_change_seq"] = post_seq
    if post_rev is not None:
        entry["post_revision"] = post_rev
    if candidate is not None:
        entry["candidate"] = candidate
        cand_id = entry.get("candidate_id")
        if cand_id and cand_id in _MANUAL_AGENT_CANDIDATES:
            _MANUAL_AGENT_CANDIDATES[cand_id]["candidate"] = candidate
            _MANUAL_AGENT_CANDIDATES[cand_id]["last_seen_at"] = time.monotonic()
    if agy_recovery_reprompt is True:
        # Audit marker only: a bounded AGY recovery reprompt re-delivered the
        # exact task once. Never task or screen text.
        entry["agy_recovery_reprompt"] = True
    bounded_code = _journal_token(watcher_error_code)
    if bounded_code is not None:
        entry["watcher_error_code"] = bounded_code
    entry["latched_at"] = time.time()
    work_ref = entry.get("work_ref")
    if work_ref is not None:
        _latch_work_from_handoff(work_ref, entry)


def _release_completed_handoff(handoff_id: str, task: asyncio.Task) -> None:
    """Drop only completed watcher ownership after its terminal was latched.

    The callback captures an ID, not a request Context or the handoff dict. It
    also works when a task finishes before callback registration (eager tasks).
    No live task is cancelled and no external resource is changed.
    """
    entry = _HANDOFF_REGISTRY.get(handoff_id)
    if (entry is not None and entry.get("watcher_task") is task and task.done()
            and entry.get("joined_once")
            and entry.get("state") in {"done", "needs_attention", "failed"}):
        entry["watcher_task"] = None
        _HANDOFF_REGISTRY.pop(handoff_id, None)


def _agy_recovery_exclusivity_clear(handoff_id: str) -> bool:
    """True only when NO other active same-resource dispatch can be in flight.

    Conservative Bridge-local check for the AGY cold-path reprompt: any other
    nonterminal handoff or Work bound to the same resource_key or execution
    identity vetoes — regardless of handoff consumption (joined_once). Missing
    identity, a terminal own entry, or any ambiguity is NOT clear. The first
    clear call marks this handoff as recovery-active so concurrent dispatches
    to the same resource are rejected while the recovery window is open.
    """
    entry = _HANDOFF_REGISTRY.get(handoff_id)
    if entry is None or entry.get("state") in {"done", "needs_attention", "failed"}:
        return False
    resource_key = entry.get("resource_key")
    if not isinstance(resource_key, str) or not resource_key:
        return False
    exec_id = entry.get("execution_identity")
    work_ref = entry.get("work_ref")

    def same_resource(other: dict[str, Any]) -> bool:
        return other.get("resource_key") == resource_key or (
            exec_id is not None
            and other.get("execution_identity") is not None
            and other.get("execution_identity") == exec_id
        )

    for hid, other in _HANDOFF_REGISTRY.items():
        if hid == handoff_id:
            continue
        if other.get("state") in {"done", "needs_attention", "failed"}:
            continue
        if same_resource(other):
            return False
    for wref, work in _WORK_REGISTRY.items():
        if wref == work_ref:
            continue
        if work.get("state") in WORK_TERMINAL_STATES:
            continue
        if same_resource(work):
            return False
    entry["agy_recovery_active"] = True
    return True


def _start_handoff_watcher(
    backend: Any,
    entry: dict[str, Any],
    recovery_task: str | None = None,
) -> asyncio.Task:
    task = asyncio.create_task(
        _watch_handoff_task(backend, entry["handoff_id"], recovery_task))
    entry["watcher_task"] = task
    task.add_done_callback(partial(_release_completed_handoff, entry["handoff_id"]),
                           context=contextvars.Context())
    return task


async def _watch_handoff_task(
    backend: Any,
    handoff_id: str,
    recovery_task: str | None = None,
) -> None:
    entry = _HANDOFF_REGISTRY.get(handoff_id)
    if entry is None:
        return
    expected = entry["candidate"]
    pre_seq = entry["pre_state_change_seq"]
    pre_rev = entry["pre_revision"]
    recovery = None
    if isinstance(recovery_task, str) and recovery_task.strip():
        # Smallest internal seam: the exact task lives only in this coroutine
        # and the backend watcher; it is never written to the entry, receipts,
        # or logs.
        recovery = {
            "task": recovery_task,
            "exclusivity_clear": lambda: _agy_recovery_exclusivity_clear(handoff_id),
        }
    try:
        res = await backend.watch_manual_agent_turn(
            expected, pre_seq, pre_rev, recovery=recovery)
        raw_code = res.get("watcher_error_code")
        _update_handoff_entry(
            handoff_id,
            state=res.get("state", "needs_attention"),
            reason=res.get("reason", "unknown"),
            herdr_status=res.get("herdr_status"),
            post_seq=res.get("post_state_change_seq"),
            post_rev=res.get("post_revision"),
            candidate=res.get("post_candidate"),
            agy_recovery_reprompt=res.get("agy_recovery_reprompt") is True,
            watcher_error_code=raw_code if isinstance(raw_code, str) else None,
        )
    except asyncio.CancelledError:
        raise
    except Exception:
        _update_handoff_entry(
            handoff_id,
            state="needs_attention",
            reason="watcher_internal_error",
            herdr_status="unknown",
        )


# ---------------------------------------------------------------------------
# Project-scoped Work and notification substrate (process-local)
# ---------------------------------------------------------------------------

# Per explicit project/root: active admission and bounded terminal receipts are
# independent. Reads do not renew retention; no disk recovery or global pool.
MAX_TERMINAL_WORK_RECORDS = 512
MAX_EXPIRED_WORK_RECORDS = 512
MAX_ACTIVE_WORK_RECORDS = 16

# Bounded batch-observation event-wait lease. Keep the existing configuration
# environment name and startup event; no per-Work continuation API remains.
WORK_AWAIT_LEASE_DEFAULT_SECONDS = 90.0
WORK_AWAIT_LEASE_MIN_SECONDS = 1.0
WORK_AWAIT_LEASE_MAX_SECONDS = 600.0
AWAIT_LEASE_ENV = "BRIDGE_AWAIT_LEASE_SECONDS"


def _parse_await_lease_seconds(raw: str | None) -> tuple[float, str | None]:
    """Strictly parse the benchmark lease override; never fail startup.

    Unset/blank keeps the accepted production default. Any malformed,
    non-finite or out-of-bounds value falls back to the default and returns a
    bounded warning string for the startup event, because this nonsecurity
    benchmark knob must not create another startup crash-loop class.
    """
    if raw is None or not raw.strip():
        return WORK_AWAIT_LEASE_DEFAULT_SECONDS, None
    try:
        value = float(raw.strip())
    except (TypeError, ValueError):
        return WORK_AWAIT_LEASE_DEFAULT_SECONDS, f"invalid float {raw!r}; using default"
    if value != value or value in (float("inf"), float("-inf")):
        return WORK_AWAIT_LEASE_DEFAULT_SECONDS, f"non-finite value {raw!r}; using default"
    if not WORK_AWAIT_LEASE_MIN_SECONDS <= value <= WORK_AWAIT_LEASE_MAX_SECONDS:
        return WORK_AWAIT_LEASE_DEFAULT_SECONDS, (
            f"value {value!r} outside inclusive bounds "
            f"[{WORK_AWAIT_LEASE_MIN_SECONDS}, {WORK_AWAIT_LEASE_MAX_SECONDS}]; using default")
    return value, None


def _log_await_lease_event(payload: dict[str, Any]) -> None:
    try:
        _AWAIT_LEASE_LOGGER.info(
            json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True))
    except Exception:  # Observability must never break batch observation.
        pass


# One bridge.await_lease CONFIGURATION event per process import/startup — never
# per batch-observation wait. source is
# "default" for unset/blank (no warning), "env" for a valid override (no
# warning), and "fallback" for an invalid/nonfinite/out-of-bounds value
# (bounded warning) with the effective lease always stated.
_raw_await_lease = os.environ.get(AWAIT_LEASE_ENV)
WORK_AWAIT_LEASE_SECONDS, _AWAIT_LEASE_WARNING = _parse_await_lease_seconds(_raw_await_lease)
if _raw_await_lease is None or not _raw_await_lease.strip():
    _AWAIT_LEASE_SOURCE = "default"
elif _AWAIT_LEASE_WARNING is None:
    _AWAIT_LEASE_SOURCE = "env"
else:
    _AWAIT_LEASE_SOURCE = "fallback"
_await_lease_startup_event: dict[str, Any] = {
    "event": "bridge.await_lease",
    "lease_s": WORK_AWAIT_LEASE_SECONDS,
    "source": _AWAIT_LEASE_SOURCE,
}
if _AWAIT_LEASE_WARNING:
    _await_lease_startup_event["warning"] = _AWAIT_LEASE_WARNING[:300]
_log_await_lease_event(_await_lease_startup_event)
del _raw_await_lease, _await_lease_startup_event

def _log_followup_claim_event(payload: str) -> None:
    """Emit an already frozen diagnostic outside the registry critical section."""
    try:
        _FOLLOWUP_CLAIM_LOGGER.info(payload)
    except Exception:  # Observability must never break the claim contract.
        pass


# Terminal states are honest about what the generic watcher proves: agent turn
# settlement only, never delegated task success, detached-child completion, or
# accepted result. Substance acceptance stays Principal-owned.
WORK_STATE_RUNNING = "running"
WORK_TERMINAL_STATES = {"agent_turn_settled", "needs_attention", "continuity_lost"}
_WORK_TERMINAL_BY_HANDOFF_STATE = {
    "done": "agent_turn_settled",
    "needs_attention": "needs_attention",
    "failed": "continuity_lost",
}

_WORK_REGISTRY: dict[str, dict[str, Any]] = {}
_REPORT_STORE = ReportStore()
# Tombstones contain only binding, not receipt payloads, execution or Agent state.
_EXPIRED_WORK_REFS: dict[str, tuple[str, str]] = {}
# Evidence/candidate resolvers also run in workers. Pair lookup with expiration
# atomically without taking the candidate mutex or holding a lock across I/O.
_WORK_REGISTRY_LOCK = threading.RLock()

# Explicit immutable Work batches. Classification and execution remain Work-owned.
RESULT_READY = "result_ready"
ATTENTION_REQUIRED = "attention_required"
_WORK_WATCHES: dict[str, dict[str, Any]] = {}
_WORK_WATCH_WAITERS: dict[str, list[tuple[asyncio.AbstractEventLoop, asyncio.Event]]] = {}
_CLASSIFICATION_TASKS: set[asyncio.Task] = set()
_CLASSIFICATION_INFLIGHT: set[str] = set()

# One lightweight event per retained Work, partitioned by exact project/root and
# originating opaque session (None is the unbound bucket). No delivery owner/pin.
_RESULT_INBOX: dict[tuple[str, str, str | None], dict[str, dict[str, Any]]] = {}
_CONTEXT_INBOX_LIMIT = 50
_WATCH_LOG_MEMBER_LIMIT = 528  # Default retained terminal + active Work bounds.


def _register_inbox_work(work: dict[str, Any]) -> None:
    """Registry lock held; registration is part of pre-prompt Work reservation."""
    key = (work['project_ref'], work['workspace_root'], _REQUEST_SESSION_CORRELATION.get())
    event = {'work_ref': work['work_ref'], 'result_class': None, 'report_status': None}
    work['inbox_key'] = key
    work['inbox_event'] = event
    _RESULT_INBOX.setdefault(key, {})[work['work_ref']] = event


def _diagnostic_condition(work: dict[str, Any]) -> tuple[str, str, str | None] | None:
    """Bounded condition signature, not an acknowledgement or Work resolution."""
    if work.get('state') not in WORK_TERMINAL_STATES:
        return None
    if work['state'] != 'agent_turn_settled':
        kind = 'abnormal_terminal'
    elif work.get('submission_evidence', {}).get('state') == 'delivery_unknown':
        kind = 'uncertain_submission'
    elif work.get('result_class') == ATTENTION_REQUIRED:
        kind = 'report_attention'
    else:
        return None
    return (kind, work['state'], work.get('reason'))


def _prior_evidence_gap(current: dict[str, Any], resource_key: str) -> dict[str, Any] | None:
    """Registry lock held; scan retained same-resource history, abnormal first."""
    abnormal, normal = [], []
    for work in _scope_works(current['project_ref'], current['workspace_root']):
        if work is current or work.get('resource_key') != resource_key or work.get('state') not in WORK_TERMINAL_STATES:
            continue
        condition = _diagnostic_condition(work)
        if condition:
            if work.get('terminal_diagnostics_served_condition') != condition:
                abnormal.append(work)
        elif work.get('result_class') == RESULT_READY and not work.get('report_evidence_served'):
            normal.append(work)
    gaps = abnormal or normal
    if not gaps:
        return None
    work = gaps[0]
    return {'work_ref': work['work_ref'], 'kind': 'terminal_diagnostics' if abnormal else 'report_evidence',
            'signal': work['state'], 'additional_count': len(abnormal) + len(normal) - 1,
            'notice': ('No qualifying post-condition terminal diagnostics served; use agent_terminal_read.'
                       if abnormal else 'Bridge has no recorded report evidence serving; '
                       'read work_report if relevant to the current judgment.')}


def _unregister_inbox_work(work: dict[str, Any]) -> None:
    """Registry lock held; inbox lifetime follows Work discard/expiry exactly."""
    key = work.get('inbox_key')
    bucket = _RESULT_INBOX.get(key)
    if bucket is not None and bucket.get(work['work_ref']) is work.get('inbox_event'):
        del bucket[work['work_ref']]
        if not bucket:
            del _RESULT_INBOX[key]


def _retained_classified_inbox_events(key: tuple[str, str, str | None]) -> list[dict[str, Any]]:
    """Registry lock held. Notification consumption is not result processing.

    Identity checks fail closed if a registry is replaced or an event is stale.
    No report I/O, classifier scheduling, retention renewal or delivery mutation.
    """
    classified = []
    for ref, event in _RESULT_INBOX.get(key, {}).items():
        work = _WORK_REGISTRY.get(ref)
        if (work is not None and work.get('inbox_key') == key
                and work.get('inbox_event') is event
                and event['result_class'] in (RESULT_READY, ATTENTION_REQUIRED)):
            classified.append({
                'work_ref': event['work_ref'],
                'result_class': event['result_class'],
                'classification_report_status': event['report_status'],
                'delivery_consumed': work.get('delivery_consumed') is True,
            })
    return classified


def _continuation_inbox_observation(project_ref: str, root: str) -> dict[str, Any]:
    """Retained classified results; unknown requests get unbound counts only."""
    correlation = _REQUEST_SESSION_CORRELATION.get()
    with _WORK_REGISTRY_LOCK:
        classified = _retained_classified_inbox_events((project_ref, root, correlation))
        if correlation is None:
            return {'binding': 'unknown', 'unbound_classified_count': len(classified)}
        return {'binding': 'session', 'classified_count': len(classified),
                'retained_classified': classified[:_CONTEXT_INBOX_LIMIT],
                'has_more': len(classified) > _CONTEXT_INBOX_LIMIT,
                'proves': 'final_classification_only'}


def _delivery_protected(work: dict[str, Any]) -> bool:
    """Unconsumed delivery or active batch ownership protects terminal evidence."""
    return (work.get("state") in WORK_TERMINAL_STATES
            and "report_key" in work
            and (work.get("delivery_consumed") is not True or bool(work.get("watch_refs"))))


def _scope_works(project_ref: str, root: str) -> list[dict[str, Any]]:
    scope = (project_ref, root)
    return [w for w in _WORK_REGISTRY.values()
            if (w.get("project_ref"), w.get("workspace_root")) == scope]


def _classify_result(state: str, report_status: str) -> str:
    """Mechanical final class. delivery_unknown is not a class.

    A later agent_turn_settled latch plus a readable dedicated report is
    result_ready, including when dispatch itself was transport-uncertain.
    needs_attention, continuity_lost, and a missing or invalid report are
    attention_required. Any other non-readable status is attention too.
    """
    if state == "agent_turn_settled" and report_status == "readable":
        return RESULT_READY
    return ATTENTION_REQUIRED


def _wake_work_watches(work_ref: str) -> None:
    for watch_ref, waiters in list(_WORK_WATCH_WAITERS.items()):
        watch = _WORK_WATCHES.get(watch_ref)
        if watch is not None and work_ref in watch["members"]:
            for loop, event in list(waiters):
                if not loop.is_closed():
                    loop.call_soon_threadsafe(event.set)


def _schedule_work_classification(work_ref: str) -> None:
    """Queue one report probe after the latch. The probe itself takes no registry lock."""
    with _WORK_REGISTRY_LOCK:
        if work_ref in _CLASSIFICATION_INFLIGHT:
            return
        work = _WORK_REGISTRY.get(work_ref)
        if (work is None or work.get("result_class") is not None
                or "report_key" not in work
                or work.get("state") not in WORK_TERMINAL_STATES):
            return
        _CLASSIFICATION_INFLIGHT.add(work_ref)
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None
    if loop is None or not loop.is_running():
        _CLASSIFICATION_INFLIGHT.discard(work_ref)
        return
    task = loop.create_task(_classify_latched_work(work_ref))
    _CLASSIFICATION_TASKS.add(task)

    def _finished(done: asyncio.Task) -> None:
        _CLASSIFICATION_TASKS.discard(done)
        _CLASSIFICATION_INFLIGHT.discard(work_ref)

    task.add_done_callback(_finished)


async def _classify_latched_work(work_ref: str) -> None:
    with _WORK_REGISTRY_LOCK:
        work = _WORK_REGISTRY.get(work_ref)
        if (work is None or work.get("state") not in WORK_TERMINAL_STATES
                or "report_key" not in work or work.get("result_class") is not None):
            return
        original = work
        state = work["state"]
        report_key = work.get("report_key")
        project_ref = work["project_ref"]
        root = work["workspace_root"]
    # Abnormal settlement already requires attention; publication cannot make
    # it normal and must not delay the notice.
    status = "unknown"
    if state == "agent_turn_settled":
        probed = await _probe_requested_reports([(work_ref, report_key)])
        status = probed[0]["status"] if probed else "unknown"
    result_class = _classify_result(state, status)
    with _WORK_REGISTRY_LOCK:
        work = _WORK_REGISTRY.get(work_ref)
        if (work is not original or work.get("state") != state
                or work.get("result_class") is not None):
            return
        work["report_status"] = status
        work["result_class"] = result_class
        if 'inbox_event' in work:
            work['inbox_event'].update(result_class=result_class, report_status=status)
        _wake_work_watches(work_ref)


def _expire_terminal_work(project_ref: str, root: str) -> None:
    """Called at terminal latch; delivery releases protection for later pressure; active entries are ineligible.

    Registry removal does not mutate dicts held by existing observers or frozen
    EvidenceTargets. Candidate storage/quarantine has an independent lifetime.
    """
    diagnostics = []
    try:
        with _WORK_REGISTRY_LOCK:
            scope = (project_ref, root)
            terminal = sorted(
                (w for w in _WORK_REGISTRY.values()
                 if (w.get("project_ref"), w.get("workspace_root")) == scope
                 and w.get("state") in WORK_TERMINAL_STATES),
                key=lambda w: w["settled_at"])
            overflow = max(0, len(terminal) - MAX_TERMINAL_WORK_RECORDS)
            expirable = [w for w in terminal if not _delivery_protected(w)]
            for work in expirable[:overflow]:
                ref = work["work_ref"]
                _EXPIRED_WORK_REFS[ref] = scope
                del _WORK_REGISTRY[ref]
                _unregister_inbox_work(work)
                diagnostics.extend(_retire_work_watches_locked(ref, 'member_expired'))
                _REPORT_STORE.discard(work.get('report_key'))
            expired = [ref for ref, binding in _EXPIRED_WORK_REFS.items() if binding == scope]
            for ref in expired[:max(0, len(expired) - MAX_EXPIRED_WORK_RECORDS)]:
                del _EXPIRED_WORK_REFS[ref]
    finally:
        _emit_work_watch_events(diagnostics)


def _lookup_work(project_ref: str, root: str, work_ref: str) -> dict[str, Any]:
    with _WORK_REGISTRY_LOCK:
        work = _WORK_REGISTRY.get(work_ref) if isinstance(work_ref, str) else None
        expired = _EXPIRED_WORK_REFS.get(work_ref) if isinstance(work_ref, str) else None
        binding = ((work.get("project_ref"), work.get("workspace_root"))
                   if work is not None else expired)
        if binding is not None and binding != (project_ref, root):
            return {"ok": False, "error_type": "WorkRefProjectMismatch",
                    "error": "Work belongs to a different project; no retargeting is permitted"}
        if work is not None:
            return work
        return {
            "ok": False,
            "error_type": "WorkRefExpired" if expired is not None else "WorkRefUnavailable",
            "reason": "terminal_receipt_expired" if expired is not None else "work_ref_unavailable",
            "error": ("Bridge local terminal receipt expired under retention pressure. "
                      if expired is not None else
                      "Work is unavailable: never issued here, lost after restart, or expired beyond tombstone retention. ")
                     + "This proves no task outcome or external cessation and permits no retry; "
                       "Bridge will not rediscover, rebind, resubmit, or cancel the external Agent.",
        }


def _work_capacity(project_ref: str, root: str) -> dict[str, Any]:
    scope = (project_ref, root)
    with _WORK_REGISTRY_LOCK:
        scoped = [w for w in _WORK_REGISTRY.values()
                  if (w.get("project_ref"), w.get("workspace_root")) == scope]
        terminal = sum(w.get("state") in WORK_TERMINAL_STATES for w in scoped)
        protected = sum(_delivery_protected(w) for w in scoped)
        expired = sum(binding == scope for binding in _EXPIRED_WORK_REFS.values())
    handoffs = sum((h.get("workspace_ref"), h.get("workspace_root")) == scope
                   for h in _HANDOFF_REGISTRY.values())
    return {"scope": "project", "active": {"count": len(scoped) - terminal, "limit": MAX_ACTIVE_WORK_RECORDS},
            "terminal_receipts": {"count": terminal, "limit": MAX_TERMINAL_WORK_RECORDS},
            "undelivered_terminal_reports": {"count": protected, "limit": MAX_TERMINAL_WORK_RECORDS},
            "expired_tombstones": {"count": expired, "limit": MAX_EXPIRED_WORK_RECORDS},
            "handoffs": {"count": handoffs, "limit": MAX_HANDOFF_RECORDS},
            "policy": "process-local; delivered terminal receipts without active batch ownership expire oldest settled_at first; "
                      "undelivered or batch-owned terminal Work/report evidence is kept and admission backpressures; "
                      "reads do not renew; nonterminal Work never expires; expiration is not safe retry"}


class WorkRegistryFullError(ProjectCapacityError):
    """Raised when process-local Work capacity is exhausted before dispatch."""


def _generate_work_ref() -> str:
    return f"work-{uuid.uuid4().hex[:16]}"


def _reserve_work(
    project_ref: str,
    workspace: WorkspaceContext,
    agent_ref: str,
    candidate: dict[str, Any],
) -> dict[str, Any]:
    """Reserve active capacity synchronously before native prompt mutation.

    Terminal receipts have a separate bounded lifecycle; unknown/nonterminal
    entries conservatively occupy active capacity regardless of their age.
    """
    root = str(workspace.root)
    with _WORK_REGISTRY_LOCK:
        scoped = _scope_works(project_ref, root)
        active = sum(w.get("state") not in WORK_TERMINAL_STATES for w in scoped)
        if active >= MAX_ACTIVE_WORK_RECORDS:
            raise WorkRegistryFullError("work_active", active, MAX_ACTIVE_WORK_RECORDS,
                                        active_count=active, active_limit=MAX_ACTIVE_WORK_RECORDS)
        protected = sum(_delivery_protected(w) for w in scoped)
        if protected + active + 1 > MAX_TERMINAL_WORK_RECORDS:
            raise WorkRegistryFullError(
                "delivery_retention", protected + active, MAX_TERMINAL_WORK_RECORDS,
                active_count=active, active_limit=MAX_ACTIVE_WORK_RECORDS,
                protected_terminal_count=protected,
                protected_terminal_limit=MAX_TERMINAL_WORK_RECORDS)
        work_ref = _generate_work_ref()
        entry = {
            "work_ref": work_ref,
            "project_ref": project_ref,
            "workspace_root": root,
            "agent_ref": agent_ref,
            "resource_key": candidate.get("resource_key"),
            "agent_key": None,
            "execution_identity": None,
            "state": WORK_STATE_RUNNING,
            "reason": "delegated",
            "submission_evidence": {"state": "not_attempted", "mutation_possible": False,
                                    "proves": "no_input_attempted", "native_error_code": None},
            "handoff_id": None,
            "created_at": time.time(),
            "settled_at": None,
            "post_state_change_seq": None,
            "result_class": None,
            "report_status": None,
            "delivery_consumed": False,
            "watch_refs": set(),
        }
        _WORK_REGISTRY[work_ref] = entry
        _register_inbox_work(entry)
        reservations = _DELEGATE_RESERVATIONS.get()
        if reservations is not None:
            reservations.append(work_ref)
        return entry


def _discard_work(work_ref: str) -> None:
    """Discard a reserved-but-never-dispatched Work; terminal Work is never discarded."""
    diagnostics = []
    try:
        with _WORK_REGISTRY_LOCK:
            entry = _WORK_REGISTRY.get(work_ref)
            if (
                entry is not None
                and entry.get("state") == WORK_STATE_RUNNING
                and entry.get("handoff_id") is None
            ):
                _WORK_REGISTRY.pop(work_ref, None)
                _unregister_inbox_work(entry)
                diagnostics.extend(_retire_work_watches_locked(work_ref, 'member_discarded'))
                _REPORT_STORE.discard(entry.get('report_key'))
                _wake_work_watches(work_ref)
    finally:
        _emit_work_watch_events(diagnostics)


def _journal_token(value: object) -> str | None:
    if not isinstance(value, str) or not _JOURNAL_TOKEN_RE.fullmatch(value):
        return None
    return value


def _dispatch_to_latch_elapsed_ms(handoff_entry: dict[str, Any]) -> int | None:
    dispatched_at = handoff_entry.get("dispatched_at")
    latched_at = handoff_entry.get("latched_at")
    if isinstance(dispatched_at, bool) or not isinstance(dispatched_at, (int, float)):
        return None
    if isinstance(latched_at, bool) or not isinstance(latched_at, (int, float)):
        return None
    if dispatched_at != dispatched_at or latched_at != latched_at:
        return None
    if dispatched_at in (float("inf"), float("-inf")) or latched_at in (float("inf"), float("-inf")):
        return None
    delta_ms = int((latched_at - dispatched_at) * 1000)
    if delta_ms < 0:
        return None
    return min(delta_ms, _WORK_TERMINAL_ELAPSED_MS_CAP)


def _log_work_terminal_latch(
    work_ref: str, state: str, handoff_entry: dict[str, Any]
) -> None:
    """One bounded process-log line for a successful Work terminal latch.

    Fields are tokens and a capped elapsed duration. Task text, terminal
    content, exception messages and candidate bodies are never copied.
    """
    payload = {
        "event": "bridge.work_terminal_latch",
        "work_ref": _journal_token(work_ref),
        "handoff_id": _journal_token(handoff_entry.get("handoff_id")),
        "state": _journal_token(state),
        "reason": _journal_token(handoff_entry.get("reason")),
        "herdr_status": _journal_token(handoff_entry.get("herdr_status")),
        "watcher_error_code": _journal_token(handoff_entry.get("watcher_error_code")),
        "elapsed_ms": _dispatch_to_latch_elapsed_ms(handoff_entry),
    }
    try:
        _WORK_TERMINAL_LOGGER.info(
            json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True))
    except Exception:  # Observability must never break the latch.
        pass


def _latch_work_from_handoff(work_ref: str, handoff_entry: dict[str, Any]) -> None:
    """Latch one Work terminal from its linked handoff's terminal latch.

    The latch is first-wins and immutable. Releasing the legacy handoff gate
    here lets terminal Work stop blocking later prompts to the same agent
    while its evidence remains retained independently of delivery consumption.
    """
    work = _WORK_REGISTRY.get(work_ref)
    if work is None or work.get("state") in WORK_TERMINAL_STATES:
        return
    state = _WORK_TERMINAL_BY_HANDOFF_STATE.get(handoff_entry.get("state"))
    if state is None:
        return
    work["state"] = state
    work["reason"] = handoff_entry.get("reason") or "unknown"
    work["settled_at"] = time.time()
    work["post_state_change_seq"] = handoff_entry.get("post_state_change_seq")
    if handoff_entry.get("agy_recovery_reprompt") is True:
        work["agy_recovery_reprompt"] = True
    handoff_entry["joined_once"] = True
    _log_work_terminal_latch(work_ref, state, handoff_entry)
    _expire_terminal_work(work["project_ref"], work["workspace_root"])
    _wake_work_watches(work_ref)
    if "report_key" in work:
        _schedule_work_classification(work_ref)


_PUBLIC_OBSERVE_ERROR_TYPE_MAP: dict[str, str] = {
    "UnknownManualAgentCandidate": "UnknownAgentRef",
    "ManualCandidateNotFound": "UnknownAgentRef",
    "ManualCandidateContinuityLost": "AgentContinuityLost",
    "ManualCandidateObservationUnavailable": "AgentObservationUnavailable",
    "ManualCandidateRevalidationUncertain": "AgentObservationUncertain",
    "ManualCandidateWorkspaceUnauthorized": "ProjectRefUnauthorized",
}

_PUBLIC_OBSERVE_REASON_MAP: dict[str, str] = {
    "candidate_continuity_lost": "continuity_lost",
    "continuity_lost": "continuity_lost",
    "observation_unavailable": "observation_unavailable",
    "revalidation_uncertain": "observation_uncertain",
    "observation_uncertain": "observation_uncertain",
    "agent_not_found": "agent_not_found",
    "workspace_unauthorized": "workspace_unauthorized",
    "project_mismatch": "project_mismatch",
}

_FORBIDDEN_LEGACY_TERMS: tuple[str, ...] = (
    "manualcandidate",
    "manual_agent",
    "manual agent",
    "candidate",
    "process",
    "pane",
    "session",
    "managed",
    "lifecycle",
)


def _public_observe_error_type(internal_error_type: Any) -> str:
    if not isinstance(internal_error_type, str):
        return "AgentObserveFailed"
    if internal_error_type in _PUBLIC_OBSERVE_ERROR_TYPE_MAP:
        return _PUBLIC_OBSERVE_ERROR_TYPE_MAP[internal_error_type]
    if internal_error_type.startswith("ManualCandidate"):
        return "AgentObserveFailed"
    return internal_error_type


def _public_observe_reason(internal_reason: Any, public_error_type: str) -> str:
    if isinstance(internal_reason, str) and internal_reason in _PUBLIC_OBSERVE_REASON_MAP:
        return _PUBLIC_OBSERVE_REASON_MAP[internal_reason]
    if public_error_type == "AgentContinuityLost":
        return "continuity_lost"
    if public_error_type == "AgentObservationUnavailable":
        return "observation_unavailable"
    if public_error_type == "AgentObservationUncertain":
        return "observation_uncertain"
    if public_error_type == "UnknownAgentRef":
        return "agent_not_found"
    if public_error_type == "ProjectRefUnauthorized":
        return "workspace_unauthorized"
    if public_error_type == "AgentRefProjectMismatch":
        return "project_mismatch"
    return "observation_unavailable"


def _public_observe_error_message(
    public_error_type: str,
    public_reason: str,
    raw_error: Any = None,
) -> str:
    raw_str = str(raw_error).lower() if raw_error is not None else ""
    if public_error_type == "AgentContinuityLost":
        msg = "agent execution continuity was lost due to an execution contradiction"
    elif public_error_type == "AgentObservationUnavailable":
        if "read" in raw_str:
            msg = "agent terminal output is currently unreadable"
        elif "process" in raw_str:
            msg = "agent execution evidence is temporarily unavailable"
        else:
            msg = "agent output is temporarily unavailable from the execution environment"
    elif public_error_type == "AgentObservationUncertain":
        if "ambiguous" in raw_str or "multiple" in raw_str:
            msg = "multiple agents match the target execution locus"
        elif "snapshot" in raw_str or "malformed" in raw_str:
            msg = "agent environment data is malformed or uncertain"
        else:
            msg = "agent execution state could not be verified with certainty"
    elif public_error_type == "UnknownAgentRef":
        msg = "agent_ref is unknown to this Bridge runtime or was lost after restart"
    elif public_error_type == "ProjectRefUnauthorized":
        msg = "project workspace authorization is invalid or expired"
    elif public_error_type == "AgentRefProjectMismatch":
        msg = "agent handle belongs to a different project; project_ref cannot retarget an agent"
    elif public_error_type == "ProjectRefRequired":
        msg = "project_ref is required on this tool; there is no default-root fallback"
    else:
        msg = "agent observation failed"

    msg_lower = msg.lower()
    for term in _FORBIDDEN_LEGACY_TERMS:
        if term in msg_lower:
            return "agent observation failed"
    return msg


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=False, idempotentHint=True))
async def agent_terminal_read(
    project_ref: str,
    agent_ref: str,
    limit: int = 120,
) -> dict[str, Any]:
    """Reads one Agent's current terminal text without sending input.

    Use this for diagnostics when the terminal text itself is relevant. It is not
    a delegated-Work completion or progress monitor, nor a polling substitute
    for delegated cohort continuation.

    The text is unattributed to a work_ref, is not a progress, status or liveness
    polling channel, and does not establish task success. limit is 1..400 lines
    (default 120); truncated describes Bridge's character cap, not complete
    terminal history."""
    if not isinstance(project_ref, str) or not project_ref.strip():
        return {
            "ok": False,
            "error_type": "ProjectRefRequired",
            "error": "project_ref is required on this tool; there is no default-root fallback",
        }
    resolved = _required_project_context(project_ref)
    if isinstance(resolved, dict):
        return resolved
    workspace = resolved
    if not isinstance(agent_ref, str) or not agent_ref:
        return {
            "ok": False,
            "error_type": "UnknownAgentRef",
            "error": "agent_ref must be the opaque agent handle returned by context",
        }
    record = _manual_candidate_record(agent_ref)
    if record is None:
        return {
            "ok": False,
            "project_ref": workspace.workspace_ref,
            "agent_ref": agent_ref,
            "error_type": "UnknownAgentRef",
            "error": "agent_ref is unknown to this Bridge runtime or was lost after restart",
        }
    if (
        record.get("workspace_root") != str(workspace.root)
        or record.get("workspace_ref") != workspace.workspace_ref
    ):
        return {
            "ok": False,
            "project_ref": workspace.workspace_ref,
            "agent_ref": agent_ref,
            "error_type": "AgentRefProjectMismatch",
            "error": "agent handle belongs to a different project; project_ref cannot retarget an agent",
        }
    if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= MAX_MANUAL_AGENT_READ_LINES:
        raise ValueError(f"limit must be between 1 and {MAX_MANUAL_AGENT_READ_LINES}")
    resource_key = (record.get('candidate') or {}).get('resource_key')
    with _WORK_REGISTRY_LOCK:
        diagnostic_targets = [(w, _diagnostic_condition(w)) for w in _scope_works(project_ref, str(workspace.root))
                              if resource_key and w.get('resource_key') == resource_key and _diagnostic_condition(w)]
    res = await _read_agent_candidate(candidate_id=agent_ref, limit=limit)
    if not isinstance(res, dict):
        return {
            "ok": False,
            "project_ref": workspace.workspace_ref,
            "agent_ref": agent_ref,
            "error_type": "AgentObserveFailed",
            "reason": "observation_failed",
            "error": "unexpected response from internal read",
        }
    if not res.get("ok"):
        pub_error_type = _public_observe_error_type(res.get("error_type"))
        pub_reason = _public_observe_reason(res.get("reason"), pub_error_type)
        pub_error = _public_observe_error_message(pub_error_type, pub_reason, res.get("error"))
        return {
            "ok": False,
            "project_ref": workspace.workspace_ref,
            "agent_ref": agent_ref,
            "error_type": pub_error_type,
            "reason": pub_reason,
            "error": pub_error,
        }

    candidate_data = res.get("candidate") if isinstance(res.get("candidate"), dict) else {}
    status = candidate_data.get("herdr_status") or candidate_data.get("status") or "unknown"
    read_data = res.get("read") if isinstance(res.get("read"), dict) else {}
    if (isinstance(read_data.get('text'), str) and read_data['text'].strip()
            and _manual_candidate_record(agent_ref) is record
            and (record.get('candidate') or {}).get('resource_key') == resource_key):
        with _WORK_REGISTRY_LOCK:
            for work, condition in diagnostic_targets:
                if (_WORK_REGISTRY.get(work['work_ref']) is work
                        and _diagnostic_condition(work) == condition):
                    work['terminal_diagnostics_served_condition'] = condition
    return {
        "ok": True,
        "project_ref": workspace.workspace_ref,
        "agent_ref": agent_ref,
        "status": status,
        "read": {
            "text": read_data.get("text", ""),
            "chars": read_data.get("chars", 0),
            "truncated": read_data.get("truncated", False),
            "source": read_data.get("source", "terminal_output"),
            "limit": limit,
        },
        "attribution": "unattributed_current_terminal_output",
    }


class DelegateAssignment(BaseModel):
    model_config = ConfigDict(extra='forbid')
    agent_ref: StrictStr
    task: StrictStr


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=True, openWorldHint=True, idempotentHint=False),
          meta=widget_watcher.DELEGATE_TOOL_META)
async def delegate(project_ref: str, assignments: Annotated[list[DelegateAssignment],
                   Field(min_length=1, max_length=MAX_TERMINAL_WORK_RECORDS + MAX_ACTIVE_WORK_RECORDS)]) -> CallToolResult:
    """Delegate 1..N explicit assignments and always request each Agent's report.

    Use assignments=[{agent_ref, task}, ...]. Returns without waiting for results,
    with per-item dispatch evidence and one immutable all-of continuation for retained
    Works from this call. Partial admission and delivery_unknown are not transactions
    or task success; unknown delivery is not safe to send again.

    Continue useful work that does not depend on these results, including further
    delegation. Ready: read result_ready reports with work_report, inspect relevant
    attention diagnostics and reassess the pending judgment. Armed: do not poll, sleep,
    repeatedly delegate, or inspect terminals/context merely to wait; continue independent
    work or end this turn if none remains. Later Works never join this cohort.
    Ready iff every retained member is finally classified. Attention never completes
    early; report-probe-pending is not ready. Normal/result_ready requires
    agent_turn_settled plus a readable required report; other final classifications
    require attention. Unrelated Works never delay this cohort. Readiness is not task success.

    An abnormal/uncertain condition lacking qualifying diagnostics refuses that item's prompt
    before input and directs agent_terminal_read. A normal report-evidence gap gives
    a nonblocking advisory. Serving evidence proves neither review nor resolution.
    May cause arbitrary Agent writes, execution or external actions. One nonterminal
    Work per Agent. Prepared continuation does not prove host mounting or model wake.
    """
    def error(payload):
        return widget_watcher.watch_tool_result(payload)
    if not isinstance(project_ref, str) or not project_ref.strip():
        return error({
            "ok": False,
            "error_type": "ProjectRefRequired",
            "error": "project_ref is required on this tool; there is no default-root fallback",
        })
    resolved = _required_project_context(project_ref)
    if isinstance(resolved, dict):
        return error(resolved)
    entries = [a if isinstance(a, DelegateAssignment) else DelegateAssignment.model_validate(a)
               for a in assignments]
    if not entries or len(entries) > MAX_TERMINAL_WORK_RECORDS + MAX_ACTIVE_WORK_RECORDS:
        return error({'ok': False, 'error_type': 'DelegateInvalidAssignments',
                      'error': 'Use a nonempty assignment list within retained Work request bounds; no prompt sent.'})
    resources = set()
    for entry in entries:
        _validate_manual_agent_task(entry.task)
        record = _manual_candidate_record(entry.agent_ref)
        cached = (record or {}).get('candidate')
        key = cached.get('resource_key') if isinstance(cached, dict) else None
        key = key if isinstance(key, str) and key else entry.agent_ref
        if key in resources:
            return error({'ok': False, 'error_type': 'DelegateDuplicateResource',
                          'error': 'Assignments must name distinct Agent resources; no prompt sent.'})
        resources.add(key)
    reservations: list[str] = []
    token = _DELEGATE_RESERVATIONS.set(reservations)
    items = []
    continuation = None
    try:
        for index, entry in enumerate(entries):
            before = len(reservations)
            receipt = await _delegate_work(project_ref, resolved, entry.agent_ref, entry.task)
            own = reservations[before:]
            outcome = ('submitted' if receipt.get('ok') else 'delivery_unknown'
                       if receipt.get('submission_evidence', {}).get('mutation_possible') else 'not_submitted')
            item = {'index': index, 'agent_ref': entry.agent_ref, 'outcome': outcome, **receipt}
            if item.get('work_ref') and item['work_ref'] not in own:
                item['existing_work_ref'] = item.pop('work_ref')
            for ref in own:
                work = _WORK_REGISTRY.get(ref)
                if work and work.get('prior_work_advisory'):
                    item['prior_work_advisory'] = work['prior_work_advisory']
            items.append(item)
    finally:
        _DELEGATE_RESERVATIONS.reset(token)
    # Only a normally completed call can deliver/consume a synchronous ready batch.
    # Aborts propagate with surviving Works still protected and recoverable through
    # later context/report observation; no subscription, delivery or duplicate input is invented.
    with _WORK_REGISTRY_LOCK:
        refs = [ref for ref in reservations if ref in _WORK_REGISTRY]
    if refs:
        continuation = _register_work_watch(project_ref, resolved, refs)
    payload = {'ok': True, 'items': items}
    if continuation:
        observed = continuation.structured_content
        payload['continuation'] = observed if observed.get('ok') else None
        if not observed.get('ok'):
            payload['continuation_error'] = observed
    else:
        payload['continuation'] = None
    return CallToolResult(content=[TextContent(type='text', text=json.dumps(payload, ensure_ascii=False))],
                          structured_content=payload, meta=continuation.meta if continuation else None)


async def _delegate_work(project_ref: str, workspace: WorkspaceContext,
                         agent_ref: str, task: str) -> dict[str, Any]:
    """Dispatch one Work. A report slot is allocated for every admitted Work."""
    _validate_manual_agent_task(task)
    if not isinstance(agent_ref, str) or not agent_ref:
        return {
            "ok": False,
            "error_type": "UnknownAgentRef",
            "error": "agent_ref must be the opaque agent handle returned by context",
        }
    record = _manual_candidate_record(agent_ref)
    if record is None:
        return {
            "ok": False,
            "error_type": "UnknownAgentRef",
            "error": "agent_ref is unknown to this Bridge process or was lost after restart",
        }
    if (
        record.get("workspace_root") != str(workspace.root)
        or record.get("workspace_ref") != workspace.workspace_ref
    ):
        return {
            "ok": False,
            "error_type": "AgentRefProjectMismatch",
            "error": "agent handle belongs to a different project; project_ref cannot retarget an agent",
        }
    try:
        agent_workspace = _manual_candidate_workspace(record)
    except WorkspaceAuthorizationError:
        return {
            "ok": False,
            "error_type": "AgentRefRevalidationUncertain",
            "error": "agent resource workspace authorization or identity changed",
        }
    candidate = record.get("candidate")
    if not isinstance(candidate, dict):
        return {
            "ok": False,
            "error_type": "AgentRefRevalidationUncertain",
            "error": "agent resource identity is unavailable",
        }
    try:
        candidate = await agent_workspace.backend.revalidate_manual_agent_resource(candidate)
    except HerdrBackendError as exc:
        code = getattr(exc, "code", None)
        if code in {
            "manual_candidate_observation_unavailable",
            "manual_candidate_process_unavailable",
            "manual_candidate_read_unavailable",
        }:
            error_type = "AgentRefObservationUnavailable"
        else:
            error_type = "AgentRefRevalidationUncertain"
        return {
            "ok": False,
            "error_type": error_type,
            "error": _bounded_nullable_text(str(exc), 1000),
        }
    record["candidate"] = candidate
    record["last_seen_at"] = time.monotonic()
    candidate_resource_key = candidate.get("resource_key")
    if not isinstance(candidate_resource_key, str) or not candidate_resource_key:
        return {
            "ok": False,
            "error_type": "AgentRefRevalidationUncertain",
            "error": "agent resource identity is unavailable",
        }
    existing = next(
        (
            w
            for w in _WORK_REGISTRY.values()
            if w["state"] not in WORK_TERMINAL_STATES
            and (
                w["agent_ref"] == agent_ref
                or w.get("resource_key") == candidate_resource_key
            )
        ),
        None,
    )
    if existing is not None:
        return {
            "ok": False,
            "error_type": "WorkAlreadyInFlight",
            "error": f"No prompt sent. Agent has nonterminal {existing['work_ref']}.",
            "work_ref": existing["work_ref"],
        }
    try:
        work = _reserve_work(
            project_ref, workspace, agent_ref,
            candidate if isinstance(candidate, dict) else {},
        )
    except WorkRegistryFullError as exc:
        return {
            "ok": False,
            "error_type": "WorkRegistryFull",
            "error": _bounded_nullable_text(str(exc), 1000),
            "capacity": exc.capacity,
            "submission_evidence": {"state": "not_attempted", "mutation_possible": False,
                                    "proves": "no_input_attempted"},
        }
    try:
        try:
            work["report_key"] = _REPORT_STORE.allocate()
            task = _REPORT_STORE.augment(task, work["report_key"])
            _validate_manual_agent_task(task)
        except (OSError, ValueError):
            _discard_work(work["work_ref"])
            return {"ok": False, "error_type": "WorkReportPreparationFailed",
                    "error": "Private report allocation failed or augmented task exceeds the task limit; no prompt sent",
                    "submission_evidence": {"state": "not_attempted", "mutation_possible": False,
                                            "proves": "no_input_attempted"}}
        try:
            response = await _dispatch_manual_turn(agent_ref, record, task, work_entry=work)
        except BaseException:
            _discard_work(work["work_ref"])
            raise
        if response.get("ok") and work["submission_evidence"].get("state") == "native_acknowledged":
            return {"ok": True, "work_ref": work["work_ref"]}
        error_type = response.get("error_type")
        if error_type == 'PriorWorkDiagnosticsRequired':
            _discard_work(work['work_ref'])
            return response
        if error_type == "ManualAgentPromptTransportError" or response.get("ok"):
            # Synchronous uncertainty. A later settled readable report can still
            # classify result_ready; this response does not.
            return {
                "ok": False,
                "error_type": "WorkDispatchTransportUncertain",
                "error": ("Delivery unknown. Read agent_terminal_read for this Agent before delegating to it again. Do not resend this task."
                          if work["submission_evidence"].get("mutation_possible") is True
                          else response.get("error")),
                "work_ref": work["work_ref"],
                "agent_ref": agent_ref,
                "submission_evidence": dict(work["submission_evidence"]),
            }
        if error_type == "AgentHandoffInFlight":
            _discard_work(work["work_ref"])
            return {
                "ok": False,
                "error_type": "AgentTurnOutstanding",
                "error": "an earlier ordinary turn for this agent has not been consumed; no new prompt was sent",
            }
        if error_type == "HandoffRegistryFull":
            _discard_work(work["work_ref"])
            return {
                "ok": False,
                "error_type": "WorkDispatchBlocked",
                "error": "internal dispatch capacity was exhausted before any prompt; no prompt was sent",
                "capacity": response.get("capacity"),
                "submission_evidence": {"state": "not_attempted", "mutation_possible": False,
                                        "proves": "no_input_attempted"},
            }
        if error_type == "ManualCandidateObservationUnavailable":
            _discard_work(work["work_ref"])
            return {
                "ok": False,
                "error_type": "AgentRefObservationUnavailable",
                "error": response.get("error"),
            }
        if error_type == "ManualCandidateRevalidationUncertain":
            _discard_work(work["work_ref"])
            return {
                "ok": False,
                "error_type": "AgentRefRevalidationUncertain",
                "error": response.get("error"),
            }
        _discard_work(work["work_ref"])
        return {
            "ok": False,
            "error_type": error_type or "WorkDispatchFailed",
            "error": response.get("error"),
        }
    except BaseException:
        _discard_work(work["work_ref"])
        raise


def _app_only_helper_meta() -> dict[str, Any]:
    """Fresh nested Apps visibility for one helper registration.

    visibility ["app"] carries no resourceUri, so the tool does not mount UI.
    A compliant MCP Apps host is expected to omit it from model discovery.
    tools/list still returns it. This metadata is not live-host acceptance.
    Each call builds a new outer dict, ui dict, and visibility list so the
    helper registrations cannot alias one another's nested metadata.
    """
    return {"ui": {"visibility": ["app"]}}


# Bounded report-evidence probe used by follow-up claims. WorkReportMissing is
# the only transient candidate: one initial read plus at most two shared
# rechecks, about one second apart. Added retry waiting is for the claim as a
# whole (all reports in a probe share those windows) and stays
# within five seconds. That cap bounds the injected waits, not OS I/O
# wall-clock time. Other report-read errors classify immediately. readable
# proves presence only, never task success, truth, or authenticated authorship.
# The probe runs before the claim is consumed and never sleeps under the
# registry lock.
_REPORT_EVIDENCE_EXTRA_ATTEMPTS = 2
_REPORT_EVIDENCE_RETRY_INTERVAL_SECONDS = 1.0
_REPORT_EVIDENCE_RETRY_DELAY_CAP_SECONDS = 5.0
_REPORT_EVIDENCE_INVALID = frozenset({
    "WorkReportNotRegular",
    "WorkReportTooLarge",
    "WorkReportChanged",
    "WorkReportSymlinkRejected",
    "WorkReportInvalidUTF8",
    "WorkReportEmpty",
    "WorkReportVersionChanged",
})


def _report_evidence_retry_budget() -> tuple[int, float]:
    """Shared extra rechecks and the sleep between them for one claim.

    attempts * interval stays <= 5s. That is added retry waiting for the
    claim as a whole, not a per-member sum and not an OS I/O wall-clock
    guarantee.
    """
    raw_attempts = _REPORT_EVIDENCE_EXTRA_ATTEMPTS
    if isinstance(raw_attempts, bool) or not isinstance(raw_attempts, int):
        attempts = 2
    else:
        attempts = raw_attempts
    attempts = max(0, min(attempts, 2))
    raw_interval = _REPORT_EVIDENCE_RETRY_INTERVAL_SECONDS
    if isinstance(raw_interval, bool) or not isinstance(raw_interval, (int, float)):
        interval = 1.0
    else:
        interval = float(raw_interval)
    if interval != interval or interval < 0 or interval == float("inf"):
        interval = 1.0
    raw_cap = _REPORT_EVIDENCE_RETRY_DELAY_CAP_SECONDS
    if isinstance(raw_cap, bool) or not isinstance(raw_cap, (int, float)):
        cap = 5.0
    else:
        cap = float(raw_cap)
    if cap != cap or cap < 0 or cap == float("inf"):
        cap = 5.0
    cap = min(cap, 5.0)
    if attempts and attempts * interval > cap:
        interval = cap / attempts
    return attempts, interval


def _classify_report_read(result: Any) -> str:
    """Map one report read to readable, missing, invalid, or unknown."""
    if isinstance(result, dict) and result.get("ok") is True:
        return "readable"
    if not isinstance(result, dict):
        return "unknown"
    code = result.get("error_type")
    if code == "WorkReportMissing":
        return "missing"
    if isinstance(code, str) and code in _REPORT_EVIDENCE_INVALID:
        return "invalid"
    return "unknown"


async def _report_evidence_sleep(delay: float) -> None:
    """Injectable pause between WorkReportMissing rechecks.

    Tests replace this. It must not run while _WORK_REGISTRY_LOCK is held.
    """
    await asyncio.sleep(delay)


async def _read_requested_report(report_key: Any) -> str:
    """One report read. Empty keys and unexpected failures are unknown."""
    if not isinstance(report_key, str) or not report_key:
        return "unknown"
    try:
        result = await join_worker(_REPORT_STORE.read, report_key, 0, 1, None)
    except Exception:
        return "unknown"
    return _classify_report_read(result)


async def _probe_requested_reports(
        targets: list[tuple[str, Any]]) -> list[dict[str, str]]:
    """Classify requested reports without holding the registry lock.

    Each round reads the still-missing members together. At most two shared
    sleeps separate those rounds, so a batch does not add the five-second
    cap once per member. Output follows `targets` order. Members that are not
    missing drop out and are not rechecked.
    """
    statuses: list[str | None] = [None] * len(targets)
    pending = list(range(len(targets)))
    attempts, interval = _report_evidence_retry_budget()
    extras = 0
    while pending:
        round_status = await asyncio.gather(*[
            _read_requested_report(targets[index][1]) for index in pending
        ])
        still: list[int] = []
        for index, status in zip(pending, round_status):
            if status == "missing":
                still.append(index)
            else:
                statuses[index] = status
        if not still or extras >= attempts:
            for index in still:
                statuses[index] = "missing"
            break
        extras += 1
        await _report_evidence_sleep(interval)
        pending = still
    return [
        {"work_ref": work_ref, "status": statuses[index] or "unknown"}
        for index, (work_ref, _report_key) in enumerate(targets)
    ]


def _batch_members(watch: dict[str, Any]) -> list[dict[str, Any]] | dict[str, Any]:
    """Lock held. Absence is unavailable evidence, never a completed member."""
    members = []
    for ref in watch['members']:
        work = _WORK_REGISTRY.get(ref)
        if work is None or (work['project_ref'], work['workspace_root']) != watch['scope']:
            return {'ok': False, 'error_type': 'WorkWatchMemberUnavailable',
                    'error': 'A watched Work is unavailable; no outcome or retry authority is established.'}
        members.append(work)
    return members


def _batch_ready(members: list[dict[str, Any]]) -> bool:
    return all(work.get('result_class') in (RESULT_READY, ATTENTION_REQUIRED) for work in members)


def _batch_payload(project_ref: str, members: list[dict[str, Any]]) -> dict[str, Any]:
    ready = [work['work_ref'] for work in members if work['result_class'] == RESULT_READY]
    attention = []
    for work in members:
        if work['result_class'] == ATTENTION_REQUIRED:
            item = {'work_ref': work['work_ref'], 'signal': work['state'],
                    'report_status': work['report_status'], 'reason': str(work['reason'])[:128]}
            if isinstance(work.get('agent_ref'), str):
                item['agent_ref'] = work['agent_ref']
            attention.append(item)
    return {'project_ref': project_ref, 'result_ready': ready, 'attention_required': attention,
            'proves': 'final_classification_only',
            'notice': widget_watcher.format_classification_notice(ready, attention)}


def _consume_work_watch(watch: dict[str, Any], members: list[dict[str, Any]]) -> None:
    """Lock held; shared by synchronous delivery and app claim."""
    watch['consumed'] = True
    for work in members:
        work['delivery_consumed'] = True
        work.setdefault('watch_refs', set()).discard(watch['watch_ref'])
    _wake_work_watches(members[0]['work_ref'])


def _retire_work_watches_locked(work_ref: str, outcome: str) -> tuple[str | None, ...]:
    """Lock held: retire membership and return frozen diagnostics, never emit.

    Expiry/discard callers must carry these out of their outer critical section.
    """
    diagnostics = []
    for ref, watch in list(_WORK_WATCHES.items()):
        if work_ref not in watch['members']:
            continue
        _wake_work_watches(work_ref)
        diagnostics.append(_capture_work_watch_event('bridge.work_watch_retire', watch['scope'][0], ref, outcome))
        del _WORK_WATCHES[ref]
        for member in watch['members']:
            work = _WORK_REGISTRY.get(member)
            if work is not None:
                work.setdefault('watch_refs', set()).discard(ref)
    return tuple(diagnostics)


def _retire_work_watches(work_ref: str, outcome: str) -> None:
    """Standalone retirement; nested cleanup uses the capture-only locked helper."""
    with _WORK_REGISTRY_LOCK:
        diagnostics = _retire_work_watches_locked(work_ref, outcome)
    _emit_work_watch_events(diagnostics)


def _lookup_work_watch(project_ref: str, root: str, watch_ref: str) -> dict[str, Any]:
    watch = _WORK_WATCHES.get(watch_ref)
    if watch is None:
        return {'ok': False, 'error_type': 'WorkWatchUnavailable',
                'error': 'Batch subscription unavailable: never issued, expired with Work, or lost after restart. No retry authority.'}
    if watch['scope'] != (project_ref, root):
        return {'ok': False, 'error_type': 'WorkWatchProjectMismatch',
                'error': 'Batch subscription belongs to another project/root.'}
    return watch


def _register_work_watch(project_ref: str, workspace: WorkspaceContext,
                         work_refs: list[str]) -> CallToolResult:
    """Atomic immutable all-of cohort registration for delegate."""
    def result(payload, watch=None):
        return widget_watcher.watch_tool_result(payload, watch)
    if (not isinstance(work_refs, list) or not work_refs
            or any(not isinstance(ref, str) or re.fullmatch(r'work-[0-9a-f]{16}', ref) is None for ref in work_refs)
            or len(set(work_refs)) != len(work_refs)
            or len(work_refs) > MAX_TERMINAL_WORK_RECORDS + MAX_ACTIVE_WORK_RECORDS):
        return result({'ok': False, 'error_type': 'WorkWatchInvalidRefs',
                       'error': 'Use a nonempty distinct list of existing Work refs within retained Work resource bounds.'})
    root = str(workspace.root)
    diagnostics = []
    try:
        with _WORK_REGISTRY_LOCK:
            members = []
            for ref in work_refs:
                work = _lookup_work(project_ref, root, ref)
                if work.get('ok') is False:
                    return result(work)
                members.append(work)
            membership = frozenset(work_refs)
            existing = None
            for watch in _WORK_WATCHES.values():
                if watch['consumed'] or watch['scope'] != (project_ref, root):
                    continue
                if frozenset(watch['members']) == membership:
                    existing = watch
                    members = [_WORK_REGISTRY[ref] for ref in watch['members']]
                    diagnostics.append(_capture_work_watch_event(
                        'bridge.work_watch_reuse', project_ref, watch['watch_ref'], 'reused'))
                    break
            # Only unresolved owned members conflict; already-classified dependencies
            # can legitimately support another batch and stay protected by both owners.
            for work in members:
                if work.get('result_class') is None:
                    owners = work.get('watch_refs', set()) - ({existing['watch_ref']} if existing else set())
                    if owners:
                        diagnostics.append(_capture_work_watch_event(
                            'bridge.work_watch_overlap', project_ref, sorted(owners)[0],
                            'refused', requested_work_refs=work_refs))
                        return result({'ok': False, 'error_type': 'WorkWatchOverlap',
                                       'error': 'An unresolved Work already belongs to another active batch.'})
            if _batch_ready(members):
                payload = {'ok': True, 'status': 'ready', **_batch_payload(project_ref, members)}
                if existing:
                    _consume_work_watch(existing, members)
                else:
                    for work in members:
                        work['delivery_consumed'] = True
                diagnostics.append(_capture_work_watch_event(
                    'bridge.work_watch_ready', project_ref,
                    existing['watch_ref'] if existing else None, 'consumed',
                    work_refs=[work['work_ref'] for work in members]))
                return result(payload)
            if existing is None:
                scoped = _scope_works(project_ref, root)
                active = sum(work['state'] not in WORK_TERMINAL_STATES for work in scoped)
                protected = sum(_delivery_protected(work) for work in scoped)
                added = sum(work['state'] in WORK_TERMINAL_STATES and not _delivery_protected(work) for work in members)
                if protected + active + added > MAX_TERMINAL_WORK_RECORDS:
                    return result({'ok': False, 'error_type': 'WorkWatchRetentionFull',
                                   'error': 'Batch ownership would exceed the existing terminal evidence budget.'})
                ref = f'watch-{uuid.uuid4().hex[:16]}'
                existing = {'watch_ref': ref, 'scope': (project_ref, root),
                            'members': tuple(work['work_ref'] for work in members), 'consumed': False,
                            'session_correlation': _REQUEST_SESSION_CORRELATION.get()}
                _WORK_WATCHES[ref] = existing
                for work in members:
                    work.setdefault('watch_refs', set()).add(ref)
                diagnostics.append(_capture_work_watch_event('bridge.work_watch_arm', project_ref, ref, 'armed'))
            payload = {'ok': True, 'status': 'armed', 'project_ref': project_ref,
                       'work_refs': list(existing['members'])}
            output = result(payload, existing)
    finally:
        # The with statement releases the outer lock even on ready/refusal returns.
        _emit_work_watch_events(diagnostics)
    # Queue missing classifiers without blocking this observation. No report I/O
    # or sleep is held inside the Work registry lock.
    for work in members:
        _schedule_work_classification(work['work_ref'])
    return output


def _capture_work_watch_event(event: str, project_ref: str, watch_ref: str | None, outcome: str,
                              *, work_refs: list[str] | None = None,
                              requested_work_refs: list[str] | None = None) -> str | None:
    """Lock held: freeze bounded JSON at the state transition, with no logger I/O.

    The immutable string carries membership/fingerprints out of nested cleanup
    critical sections. Capture failure cannot change registry behavior.
    """
    try:
        watch = _WORK_WATCHES.get(watch_ref)
        refs = work_refs if work_refs is not None else (watch['members'] if watch else ())
        origin = watch.get('session_correlation') if watch else None
        def fingerprint(value):
            return value[:16] if isinstance(value, str) and re.fullmatch(r'[0-9a-f]{64}', value) else None
        def bounded_refs(values):
            return [ref for ref in values[:_WATCH_LOG_MEMBER_LIMIT]
                    if isinstance(ref, str) and re.fullmatch(r'work-[0-9a-f]{16}', ref)]
        payload = {'event': _journal_token(event), 'project_ref': _journal_token(project_ref),
                   'watch_ref': _journal_token(watch_ref), 'outcome': _journal_token(outcome),
                   'work_refs': bounded_refs(refs), 'member_count': len(refs),
                   'members_truncated': len(refs) > _WATCH_LOG_MEMBER_LIMIT,
                   'request_session_fingerprint': fingerprint(_REQUEST_SESSION_CORRELATION.get()),
                   'origin_session_fingerprint': fingerprint(origin)}
        if requested_work_refs is not None:
            payload['requested_work_refs'] = bounded_refs(requested_work_refs)
            payload['requested_member_count'] = len(requested_work_refs)
            payload['requested_members_truncated'] = len(requested_work_refs) > _WATCH_LOG_MEMBER_LIMIT
        return json.dumps(payload, sort_keys=True, separators=(',', ':'), ensure_ascii=True)
    except Exception:
        return None


def _emit_work_watch_events(diagnostics) -> None:
    """Caller has left its outer registry critical section; never reread state."""
    for payload in diagnostics:
        if payload is not None:
            _log_followup_claim_event(payload)


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False,
    openWorldHint=False, idempotentHint=True), meta=_app_only_helper_meta())
async def wait_work_watch(project_ref: str, watch_ref: str) -> dict[str, Any]:
    """App-only bounded, non-consuming all-of classification observation for one batch.

    A neutral {ready:false} segment changes no Work or subscription. Cancellation
    detaches only this waiter. No model-visible wait, UI binding or Agent input.
    """
    workspace = _required_project_context(project_ref)
    if isinstance(workspace, dict):
        return workspace
    root = str(workspace.root)

    def preview():
        with _WORK_REGISTRY_LOCK:
            watch = _lookup_work_watch(project_ref, root, watch_ref)
            if watch.get('ok') is False:
                return watch
            if watch['consumed']:
                return {'ok': True, 'status': 'consumed', 'project_ref': project_ref, 'watch_ref': watch_ref}
            members = _batch_members(watch)
            if isinstance(members, dict):
                return members
            if _batch_ready(members):
                return {'ready': True, 'watch_ref': watch_ref, 'work_refs': list(watch['members']),
                        **_batch_payload(project_ref, members)}
            for work in members:
                _schedule_work_classification(work['work_ref'])
            return None

    event = asyncio.Event()
    waiter = (asyncio.get_running_loop(), event)
    deadline = time.monotonic() + WORK_AWAIT_LEASE_SECONDS
    with _WORK_REGISTRY_LOCK:
        _WORK_WATCH_WAITERS.setdefault(watch_ref, []).append(waiter)
    outcome = 'lease_expired'
    try:
        while True:
            observed = preview()
            if observed is not None:
                outcome = 'observed'
                return observed
            event.clear()
            observed = preview()
            if observed is not None:
                outcome = 'observed'
                return observed
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return {'ready': False}
            try:
                await asyncio.wait_for(event.wait(), remaining)
            except asyncio.TimeoutError:
                return preview() or {'ready': False}
    except asyncio.CancelledError:
        outcome = 'cancelled'
        raise
    finally:
        with _WORK_REGISTRY_LOCK:
            waiters = _WORK_WATCH_WAITERS.get(watch_ref, [])
            if waiter in waiters:
                waiters.remove(waiter)
            if not waiters:
                _WORK_WATCH_WAITERS.pop(watch_ref, None)
            diagnostic = _capture_work_watch_event('bridge.work_watch_wait', project_ref, watch_ref, outcome)
        _emit_work_watch_events((diagnostic,))


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False,
    openWorldHint=False, idempotentHint=False), meta=_app_only_helper_meta())
async def claim_work_watch(project_ref: str, watch_ref: str) -> dict[str, Any]:
    """App-only atomic consume-before-send grant for one fully classified batch.

    One grant per process-local subscription. Duplicate mounts share it; an
    ambiguous/failed send remains consumed. No retry, confirm or restart recovery.
    """
    workspace = _required_project_context(project_ref)
    if isinstance(workspace, dict):
        return workspace
    with _WORK_REGISTRY_LOCK:
        watch = _lookup_work_watch(project_ref, str(workspace.root), watch_ref)
        if watch.get('ok') is False:
            return watch
        denied = {'ok': True, 'granted': False, 'project_ref': project_ref, 'watch_ref': watch_ref}
        if watch['consumed']:
            return {**denied, 'reason': 'already_consumed'}
        members = _batch_members(watch)
        if isinstance(members, dict):
            return members
        if not _batch_ready(members):
            return {**denied, 'reason': 'not_ready'}
        payload = {'ok': True, 'granted': True, 'watch_ref': watch_ref,
                   'work_refs': list(watch['members']), **_batch_payload(project_ref, members)}
        _consume_work_watch(watch, members)
        watch['attempt_token'] = 'attempt-' + secrets.token_hex(16)
        payload['attempt_token'] = watch['attempt_token']
        diagnostic = _capture_work_watch_event('bridge.work_watch_claim', project_ref, watch_ref, 'granted')
    _emit_work_watch_events((diagnostic,))
    return payload


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False,
    openWorldHint=False, idempotentHint=True), meta=_app_only_helper_meta())
async def record_work_watch_send_outcome(project_ref: str, watch_ref: str, attempt_token: str,
        outcome: Literal['host_accepted', 'host_rejected_or_unknown', 'unavailable']) -> dict[str, Any]:
    """App-only client-reported send telemetry for one granted attempt, not proof
    of delivery or model wake. No retry, grant, classification or retention effect."""
    workspace = _required_project_context(project_ref)
    if isinstance(workspace, dict):
        return workspace
    with _WORK_REGISTRY_LOCK:
        watch = _lookup_work_watch(project_ref, str(workspace.root), watch_ref)
        if watch.get('ok') is False:
            return watch
        if (outcome not in ('host_accepted', 'host_rejected_or_unknown', 'unavailable')
                or not isinstance(attempt_token, str) or not re.fullmatch(r'attempt-[0-9a-f]{32}', attempt_token)
                or not watch.get('attempt_token')
                or not secrets.compare_digest(watch['attempt_token'], attempt_token)):
            return {'ok': False, 'error_type': 'WorkWatchAttemptMismatch'}
        previous = watch.get('client_send_outcome')
        if previous is not None and previous != outcome:
            return {'ok': False, 'error_type': 'WorkWatchOutcomeConflict'}
        watch['client_send_outcome'] = outcome
        return {'ok': True, 'outcome': outcome, 'proves': 'client_reported_send_only'}


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=False, idempotentHint=True))
async def work_report(project_ref: str, work_ref: str, offset: int = 0,
                      limit: int = 4096, expected_sha256: str | None = None) -> dict[str, Any]:
    """Reads the published report for one terminal work_ref, in Unicode pages.

    Default 4096, max 16384 characters; continue with content_next_offset and
    expected_sha256. Missing and invalid reports are errors. The text is the
    Agent's result, not task success, truth, or a transcript. A call does not
    wait or retry. Retention is process-local; reads do not renew it."""
    workspace = _required_project_context(project_ref)
    if isinstance(workspace, dict):
        return workspace
    work = _lookup_work(project_ref, str(workspace.root), work_ref)
    if work.get('ok') is False:
        return work
    if type(offset) is not int or offset < 0:
        return report_error('InvalidOffset')
    if type(limit) is not int or not 1 <= limit <= MAX_WORKSPACE_READ_PAGE:
        return report_error('InvalidLimit')
    if expected_sha256 is not None and (not isinstance(expected_sha256, str)
            or re.fullmatch(r'[0-9a-f]{64}', expected_sha256) is None):
        return report_error('InvalidExpectedSHA256')
    if work['state'] not in WORK_TERMINAL_STATES:
        return report_error('WorkReportNotTerminal')
    if 'report_key' not in work:
        return report_error('WorkReportUnavailable')
    result = await join_worker(_REPORT_STORE.read, work['report_key'], offset, limit, expected_sha256)
    if result.get('ok') and isinstance(result.get('content'), str) and bool(result['content']):
        with _WORK_REGISTRY_LOCK:
            if _WORK_REGISTRY.get(work_ref) is work:
                work['report_evidence_served'] = True
    result.update(project_ref=project_ref, work_ref=work_ref)
    return result


def _project_instructions_snippet(workspace_ref: str) -> str:
    """Return a minimal connected-ref amendment for the user's Project Binding."""
    return (
        "# Project Binding\n\n"
        "Connected Bridge project refs:\n"
        f'- `project_ref="{workspace_ref}"`\n'
    )


def _registration_persistence(
    publication: str,
    durability: str,
    reason: str | None = None,
    *,
    memory_updated: bool | None = None,
) -> dict[str, Any]:
    result: dict[str, Any] = {"publication": publication, "durability": durability}
    if reason is not None:
        result["reason"] = reason
    if memory_updated is not None:
        result["memory_updated"] = memory_updated
    return result


def _store_error_result(exc: WorkspaceStoreError) -> dict[str, Any]:
    try:
        registration: dict[str, Any] | None = _WORKSPACE_REGISTRY.observe_registration()
    except Exception:
        registration = {"status": "unreadable", "store": "unreadable", "reason": "observation_failed"}
    return {
        "ok": False,
        "error_type": "WorkspaceStoreError",
        "error": f"failed to persist workspace registration: {exc}",
        "task_authority": "not_granted",
        "persistence": _registration_persistence(
            exc.publication, exc.durability, exc.persistence_reason
        ),
        "registration": registration,
    }


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, openWorldHint=False, idempotentHint=True))
async def project_register(
    project_ref: str,
    path: str,
) -> dict[str, Any]:
    """Register an existing local Git project with Bridge: path is an absolute
    existing repository or checkout root.

    Writes only the registry route; verifies an existing matching entry without
    redirecting it. This creates no repository, worktree, ChatGPT Project, or
    .principal continuity files, and grants no task authority. Persistence
    distinguishes a pre-publication no-effect from a published record whose
    directory durability is uncertain. Use bridge_overview for the read-only
    live-versus-persisted registration observation."""
    if not isinstance(project_ref, str) or not WORKSPACE_REF_RE.fullmatch(project_ref):
        return {
            "ok": False,
            "error_type": "InvalidWorkspaceRef",
            "error": "project_ref must be 1-64 alphanumeric characters, dots, underscores, or hyphens, starting with an alphanumeric character",
            "task_authority": "not_granted",
            "persistence": _registration_persistence("not_attempted", "not_applicable"),
        }
    if project_ref == "default":
        return {
            "ok": False,
            "error_type": "ReservedWorkspaceRef",
            "error": "'default' is a reserved project reference",
            "task_authority": "not_granted",
            "persistence": _registration_persistence("not_attempted", "not_applicable"),
        }
    if (
        not isinstance(path, str)
        or not path
        or path != path.strip()
        or "\x00" in path
        or not Path(path).is_absolute()
    ):
        return {
            "ok": False,
            "error_type": "InvalidWorkspacePath",
            "error": "path must be a non-empty absolute path string without leading/trailing whitespace or null bytes",
            "task_authority": "not_granted",
            "persistence": _registration_persistence("not_attempted", "not_applicable"),
        }

    try:
        canonical_root, identity = canonical_git_worktree(path)
    except WorkspaceAuthorizationError as exc:
        return {
            "ok": False,
            "error_type": "InvalidGitWorktree",
            "error": str(exc),
            "task_authority": "not_granted",
            "persistence": _registration_persistence("not_attempted", "not_applicable"),
        }

    persistence = _registration_persistence("not_attempted", "not_applicable")
    async with _WORKSPACE_REGISTRY.store.lock:
        existing_entry = _WORKSPACE_REGISTRY.get_entry(project_ref)
        if existing_entry is not None:
            existing_root, existing_identity = existing_entry
            if existing_root != canonical_root:
                return {
                    "ok": False,
                    "error_type": "WorkspaceRefRedirectionForbidden",
                    "error": f"project_ref '{project_ref}' is already registered to a different path",
                    "task_authority": "not_granted",
                    "persistence": persistence,
                }
            try:
                validate_git_worktree_identity(canonical_root, existing_identity)
            except WorkspaceAuthorizationError as exc:
                return {
                    "ok": False,
                    "error_type": "GitWorktreeIdentityChanged",
                    "error": f"registered workspace Git/worktree identity changed: {exc}",
                    "task_authority": "not_granted",
                    "persistence": persistence,
                }
            if not _WORKSPACE_REGISTRY.is_static(project_ref):
                try:
                    outcome = _WORKSPACE_REGISTRY.store.record_workspace(
                        workspace_ref=project_ref,
                        canonical_root=str(canonical_root),
                        identity=identity,
                    )
                except WorkspaceStoreError as exc:
                    return _store_error_result(exc)
                except Exception as exc:
                    return _store_error_result(WorkspaceStoreError(str(exc)))
                persistence = _registration_persistence(
                    outcome["publication"],
                    outcome["durability"],
                    outcome.get("reason"),
                    memory_updated=True,
                )
            status = "already_registered"
        else:
            for other_ref, (other_root, _) in _WORKSPACE_REGISTRY.all_entries().items():
                if other_root == canonical_root:
                    return {
                        "ok": False,
                        "error_type": "DuplicateWorkspacePath",
                        "error": f"workspace path is already registered under reference '{other_ref}'",
                        "task_authority": "not_granted",
                        "persistence": persistence,
                    }
            if len(_WORKSPACE_REGISTRY.refs) >= MAX_WORKSPACE_REFS:
                return {
                    "ok": False,
                    "error_type": "MaxWorkspaceRefsExceeded",
                    "error": f"maximum number of registered workspace references ({MAX_WORKSPACE_REFS}) reached",
                    "task_authority": "not_granted",
                    "persistence": persistence,
                }

            try:
                outcome = _WORKSPACE_REGISTRY.register_dynamic(project_ref, canonical_root, identity)
            except WorkspaceStoreError as exc:
                return _store_error_result(exc)
            except Exception as exc:
                return _store_error_result(WorkspaceStoreError(str(exc)))
            persistence = _registration_persistence(
                outcome["publication"],
                outcome["durability"],
                outcome.get("reason"),
                memory_updated=outcome.get("memory_updated"),
            )
            if not outcome.get("memory_updated"):
                return {
                    "ok": False,
                    "error_type": "RegistrationPersistenceUnconfirmed",
                    "error": "registry replace was not confirmed by readback; live memory was not updated and the published file was not deleted",
                    "task_authority": "not_granted",
                    "persistence": persistence,
                    "registration": outcome.get("registration"),
                }
            status = "created"
        registration = _WORKSPACE_REGISTRY.observe_registration()

    snippet = _project_instructions_snippet(project_ref)
    return {
        "ok": True,
        "project_ref": project_ref,
        "canonical_root": str(canonical_root),
        "status": status,
        "task_authority": "not_granted",
        "project_identity": "not_exposed_or_unproven",
        "binding_provenance": "not_exposed_or_unproven",
        "persistence": persistence,
        "registration": registration,
        "onboarding": await asyncio.to_thread(
            _project_continuity.describe, _WORKSPACE_REGISTRY.resolve(project_ref)
        ),
        "project_instructions_snippet": snippet,
        "instructions_action": "manual_user_copy_required",
    }


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, openWorldHint=False, idempotentHint=True))
async def project_initialize(project_ref: str, seed: dict) -> dict[str, Any]:
    """Initialize a fresh .principal directory for an already registered project.

    seed.rules names genuine existing rule files. state_content and memory_content
    are the new state and memory bytes. project_rules_content, when meaningful,
    is written only to .principal/rules.md. No other seed fields are accepted.
    A canonical manifest is left untouched. This does not register a route,
    create AGENTS.md, copy another project's cognition, stage, or commit, and it
    grants no task authority. Publication is one no-replace directory rename;
    after that rename, the directory is not deleted. A missing response is not
    proof the directory is absent: read continuity before retrying.
    """
    workspace = _required_project_context(project_ref)
    if isinstance(workspace, dict):
        workspace["task_authority"] = "not_granted"
        workspace["publication"] = "not_attempted"
        workspace["durability"] = "not_applicable"
        workspace["git_mutation"] = "none"
        return workspace
    lease = await _access_gate(workspace.root).acquire("writer")
    try:
        return await join_worker(_project_continuity.initialize_fresh, workspace, seed)
    finally:
        await lease.release()


# ---------------------------------------------------------------------------
# Direct Workspace Evidence & Mutation constants & helpers
# ---------------------------------------------------------------------------

DEFAULT_WORKSPACE_READ_PAGE = 4096
MAX_WORKSPACE_READ_PAGE = 16384
MAX_WORKSPACE_DIFF_PAGE = 32768
MAX_WORKSPACE_SUMMARY_FILES = 100
MAX_WORKSPACE_SEARCH_QUERY_CHARS = 500
MAX_WORKSPACE_SEARCH_MATCHES = 50
DEFAULT_WORKSPACE_SEARCH_MATCHES = 20
MAX_WORKSPACE_SEARCH_LINE_CHARS = 300
MAX_WORKSPACE_FILE_SIZE = 10 * 1024 * 1024  # 10 MB


def _validate_workspace_relative_path(root: Path, path_str: str) -> tuple[Path, str]:
    if not isinstance(path_str, str) or not path_str.strip():
        raise ValueError("path must be a non-empty string")
    raw = Path(path_str)
    if raw.is_absolute():
        raise ValueError("path must be relative to the workspace root")
    parts = raw.parts
    if any(part == ".." or part == ".git" or part.startswith(".git/") for part in parts):
        raise ValueError("path traversal and .git internal paths are not permitted")
    try:
        target = (root / raw).resolve(strict=False)
    except (OSError, RuntimeError) as exc:
        raise ValueError(f"invalid path: {exc}") from exc
    try:
        rel = target.relative_to(root)
    except ValueError:
        raise ValueError("path escapes the workspace root")
    rel_str = str(rel)
    if rel_str == "." or rel_str == ".git" or rel_str.startswith(".git/") or rel_str.startswith(".git\\"):
        raise ValueError(".git internal paths are not permitted")
    return target, rel_str


def _git_run_bounded(
    *args: str,
    root: Path,
    input: str | None = None,
    timeout: float = 5.0,
) -> tuple[int, str, str]:
    if input is not None:
        return fixed_git.UNSUPPORTED, "", "fixed observation does not accept stdin"
    rc, out, err = fixed_git.observe(root, args, timeout)
    return rc, out.decode("utf-8", errors="replace"), err.decode("utf-8", errors="replace")


def _git_run_bytes_bounded(
    *args: str, root: Path, timeout: float = 5.0,
) -> tuple[int, bytes, bytes]:
    return fixed_git.observe(root, args, timeout)


_NOFOLLOW_DIR_OPEN_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
# O_NONBLOCK prevents blocking opens on non-regular specials; the regular-file
# fstat check below rejects them before any read.
_NOFOLLOW_FILE_OPEN_FLAGS = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC


def _component_is_symlink(dir_fd: int, part: str) -> bool:
    try:
        return stat.S_ISLNK(os.lstat(part, dir_fd=dir_fd).st_mode)
    except OSError:
        return False


def _vnext_open_error(rel_path: str, exc: OSError) -> dict[str, Any]:
    if exc.errno == errno.ENOENT:
        return {"ok": False, "error_type": "FileNotFound", "error": f"file '{rel_path}' does not exist"}
    if exc.errno == errno.ELOOP:
        return {"ok": False, "error_type": "SymlinkRejected", "error": f"path '{rel_path}' contains a symbolic link component; refusing to follow"}
    if exc.errno == errno.ENOTDIR:
        return {"ok": False, "error_type": "NotADirectory", "error": f"path '{rel_path}' has a component that is not a directory"}
    return {"ok": False, "error_type": "ReadError", "error": str(exc)}


def _read_bounded_workspace_bytes(
    workspace: WorkspaceContext,
    rel_parts: list[str],
    rel_path: str,
    limit: int,
) -> tuple[bytes | None, dict[str, Any] | None]:
    """Read at most limit+1 bytes via a no-follow descriptor walk bound to the
    registered root; return (bytes, None) or (None, structured error). Every
    component is opened relative to the previous descriptor, so neither final
    nor parent components can redirect the read outside the root. Callers pass
    validation-resolved relative paths, so stable in-root symlinks stay
    readable through their canonical in-root target; only symlinks introduced
    after validation fail closed."""
    try:
        root_fd = os.open(workspace.root, _NOFOLLOW_DIR_OPEN_FLAGS)
    except OSError as exc:
        return None, _vnext_open_error(rel_path, exc)
    walked_fds: list[int] = []
    file_fd: int | None = None
    try:
        if workspace.git is not None:
            opened = os.fstat(root_fd)
            if (opened.st_dev, opened.st_ino) != (workspace.git.root_device, workspace.git.root_inode):
                return None, {
                    "ok": False,
                    "error_type": "WorkspaceRootIdentityChanged",
                    "error": "opened workspace root does not match its registered Git worktree identity",
                }
        parent_fd = root_fd
        for part in rel_parts[:-1]:
            try:
                parent_fd = os.open(part, _NOFOLLOW_DIR_OPEN_FLAGS, dir_fd=parent_fd)
            except OSError as exc:
                # On Linux an O_DIRECTORY|O_NOFOLLOW open of a symlinked
                # component surfaces as ENOTDIR; classify it as the symlink
                # rejection it is when the component really is a symlink.
                if exc.errno == errno.ENOTDIR and _component_is_symlink(parent_fd, part):
                    return None, {
                        "ok": False,
                        "error_type": "SymlinkRejected",
                        "error": f"path '{rel_path}' contains a symbolic link component; refusing to follow",
                    }
                raise
            walked_fds.append(parent_fd)
        file_fd = os.open(rel_parts[-1], _NOFOLLOW_FILE_OPEN_FLAGS, dir_fd=parent_fd)
        opened = os.fstat(file_fd)
        if not stat.S_ISREG(opened.st_mode):
            return None, {
                "ok": False,
                "error_type": "NotARegularFile",
                "error": f"path '{rel_path}' is not a regular file",
            }
        chunks: list[bytes] = []
        remaining = limit + 1
        while remaining > 0:
            chunk = os.read(file_fd, remaining)
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        return b"".join(chunks), None
    except OSError as exc:
        return None, _vnext_open_error(rel_path, exc)
    finally:
        if file_fd is not None:
            try:
                os.close(file_fd)
            except OSError:
                pass
        for fd in walked_fds:
            try:
                os.close(fd)
            except OSError:
                pass
        os.close(root_fd)


# Streaming per-command stdout cap; config probe shares the command deadline.
# Multiple observations and filesystem work do not have an end-to-end SLA.
MAX_CURRENT_DIFF_CAPTURE_BYTES = 8 * 1024 * 1024


def _current_diff_git(root: Path, *args: str) -> tuple[bytes | None, dict[str, Any] | None]:
    rc, raw, err = _git_run_bytes_bounded("--no-optional-locks", *args, root=root)
    if rc != 0:
        return None, {"ok": False, "error_type": ("GitObservationUnsupported" if rc == fixed_git.UNSUPPORTED else
                                     "DiffObservationTooLarge" if rc == fixed_git.TOO_LARGE else "GitDiffError"),
                      "coverage": {"complete": False},
                      "error": err[:1000].decode("utf-8", errors="replace") or "current diff observation failed"}
    if len(raw) > MAX_CURRENT_DIFF_CAPTURE_BYTES:
        return None, {"ok": False, "error_type": "DiffObservationTooLarge",
                      "error": "current diff Git output exceeds the observation limit; coverage is unknown"}
    return raw, None


def _current_diff_records(raw: bytes) -> list[bytes]:
    if raw and not raw.endswith(b"\0"):
        raise ValueError("unterminated Git record")
    return raw[:-1].split(b"\0") if raw else []


def _current_diff_path(raw: bytes) -> str:
    if not raw:
        raise ValueError("empty Git path")
    # Do not send surrogate/replacement paths that cannot be reused by read.
    return raw.decode("utf-8")


def _current_diff_status(raw: bytes) -> list[dict[str, Any]]:
    records = iter(_current_diff_records(raw))
    entries = []
    for record in records:
        if (len(record) < 4 or record[2:3] != b" "
                or any(c not in b" MADRCUT?" for c in record[:2])):
            raise ValueError("invalid porcelain status record")
        staged, unstaged = record[:2].decode("ascii")
        untracked = record[:2] == b"??"
        if ("?" in (staged, unstaged) and not untracked) or record[:2] == b"  ":
            raise ValueError("invalid porcelain status pair")
        entry = {"path": _current_diff_path(record[3:]),
                 "staged_status": staged if staged not in (" ", "?") else None,
                 "unstaged_status": unstaged if unstaged not in (" ", "?") else None,
                 "is_untracked": untracked}
        if staged in "RC" or unstaged in "RC":
            # Porcelain -z is destination NUL source NUL (opposite numstat).
            entry["original_path"] = _current_diff_path(next(records, b""))
        entries.append(entry)
    return entries


def _current_diff_numstat(raw: bytes) -> dict[str, tuple[int | None, int | None]]:
    records = iter(_current_diff_records(raw))
    counts = {}
    for record in records:
        fields = record.split(b"\t", 2)
        if len(fields) != 3:
            raise ValueError("invalid numstat record")
        added, deleted, path = fields
        if not ((added.isdigit() and deleted.isdigit()) or (added == deleted == b"-")):
            raise ValueError("invalid numstat counts")
        if not path:
            # Rename/copy: counts TAB NUL source NUL destination NUL.
            _current_diff_path(next(records, b""))
            path = next(records, b"")
        name = _current_diff_path(path)
        current = (int(added), int(deleted)) if added.isdigit() else (None, None)
        # Unmerged paths can have a 0/0 conflict record followed by worktree
        # counts for the same name. Both are valid Git records, not truncation.
        previous = counts.get(name, (0, 0))
        counts[name] = tuple(a + b if a is not None and b is not None else None
                             for a, b in zip(previous, current))
    return counts


def _compute_workspace_diff(
    workspace: WorkspaceContext,
    path: str | None,
    view: str,
    staged: bool,
    offset: int,
    limit: int,
) -> dict[str, Any]:
    head = _git_inspect_small("rev-parse", "--verify", "HEAD", root=workspace.root)
    branch = _git_inspect_small("rev-parse", "--abbrev-ref", "HEAD", root=workspace.root)
    status_raw, error = _current_diff_git(workspace.root, "status", "--porcelain=v1", "-z", "-uall")
    if error:
        return error
    try:
        all_file_entries = _current_diff_status(status_raw)
        numstats = []
        for stage_args in (("--cached",), ()):
            raw, error = _current_diff_git(
                workspace.root, "diff", "--no-ext-diff", "--no-textconv", "--numstat", "-z", *stage_args
            )
            if error:
                return error
            numstats.append(_current_diff_numstat(raw))
    except (ValueError, UnicodeError) as exc:
        return {"ok": False, "error_type": "DiffOutputMalformed",
                "error": f"current diff coverage is unknown: {str(exc)[:300]}"}
    for entry in all_file_entries:
        observed = [counts[entry["path"]] for counts in numstats if entry["path"] in counts]
        for position, key in enumerate(("insertions", "deletions")):
            entry[key] = (sum(count[position] for count in observed)
                          if observed and all(count[position] is not None for count in observed) else None)
    target_rel_path: str | None = None
    target_path: Path | None = None
    if path:
        try:
            target_path, target_rel_path = _validate_workspace_relative_path(workspace.root, path)
        except ValueError as exc:
            return {
                "ok": False,
                "error_type": "InvalidPath",
                "error": str(exc),
            }

    if view == "summary":
        if target_rel_path:
            filtered_entries = [
                f for f in all_file_entries
                if any(p == target_rel_path or p.startswith(target_rel_path + "/")
                       for p in (f["path"], f.get("original_path", "")))
            ]
        else:
            filtered_entries = all_file_entries

        staged_count = sum(1 for f in filtered_entries if f["staged_status"])
        unstaged_count = sum(1 for f in filtered_entries if f["unstaged_status"])
        untracked_count = sum(1 for f in filtered_entries if f["is_untracked"])
        total_files = len(filtered_entries)

        return {
            "ok": True,
            "workspace_ref": workspace.workspace_ref,
            "canonical_root": str(workspace.root),
            "git_head": head,
            "dirty": bool(all_file_entries),
            "branch": branch,
            "view": "summary",
            "is_clean": (staged_count == 0 and unstaged_count == 0 and untracked_count == 0),
            "counts": {
                "staged": staged_count,
                "unstaged": unstaged_count,
                "untracked": untracked_count,
                "total": total_files,
            },
            "files": filtered_entries[offset:offset + min(limit, MAX_WORKSPACE_SUMMARY_FILES)],
            "files_offset": offset,
            "files_next_offset": offset + min(limit, MAX_WORKSPACE_SUMMARY_FILES) if offset + min(limit, MAX_WORKSPACE_SUMMARY_FILES) < len(filtered_entries) else None,
            "files_truncated": offset + min(limit, MAX_WORKSPACE_SUMMARY_FILES) < len(filtered_entries),
            "provenance": {
                "source": "git_worktree",
                "workspace_ref": workspace.workspace_ref,
                "canonical_root": str(workspace.root),
                "git_head": head,
                "observed_at": time.time(),
            },
            "coverage": {
                "tracked_files": "included",
                "untracked_files": "included",
                "ignored_files": "excluded",
            },
        }

    elif view == "patch":
        # Check if path is specified and corresponds to an untracked file
        if target_rel_path and target_path:
            is_untracked = any(f["path"] == target_rel_path and f["is_untracked"] for f in all_file_entries)
            if is_untracked:
                if not target_path.exists():
                    return {
                        "ok": False,
                        "error_type": "FileNotFound",
                        "error": f"untracked file '{target_rel_path}' does not exist on disk",
                    }
                if not target_path.is_file():
                    return {
                        "ok": False,
                        "error_type": "NotARegularFile",
                        "error": f"untracked path '{target_rel_path}' is not a regular file",
                    }
                raw_bytes, error = _read_bounded_workspace_bytes(
                    workspace, list(Path(target_rel_path).parts), target_rel_path, MAX_WORKSPACE_FILE_SIZE
                )
                if error:
                    return error
                if len(raw_bytes) > MAX_WORKSPACE_FILE_SIZE:
                    return {"ok": False, "error_type": "FileTooLarge",
                            "error": "untracked synthetic diff exceeds the file observation limit"}
                if b"\x00" in raw_bytes[:4096]:
                    return {
                        "ok": False,
                        "error_type": "BinaryFileUnsupported",
                        "error": f"untracked file '{target_rel_path}' is binary",
                        "binary": True,
                    }
                try:
                    text_content = raw_bytes.decode("utf-8")
                except UnicodeDecodeError:
                    return {
                        "ok": False,
                        "error_type": "BinaryFileUnsupported",
                        "error": f"untracked file '{target_rel_path}' is not valid UTF-8 text",
                        "binary": True,
                    }
                # Generate synthetic unified diff from /dev/null
                lines = text_content.splitlines(keepends=True)
                line_count = len(lines)
                header = f"--- /dev/null\n+++ b/{target_rel_path}\n@@ -0,0 +1,{line_count} @@\n"
                body = "".join(f"+{l}" if l.endswith("\n") else f"+{l}\n\\ No newline at end of file\n" for l in lines)
                full_patch = header + body
                page = full_patch[offset:offset + limit]
                next_offset = offset + len(page) if offset + len(page) < len(full_patch) else None
                return {
                    "ok": True,
                    "workspace_ref": workspace.workspace_ref,
                    "canonical_root": str(workspace.root),
                    "git_head": head,
                    "dirty": bool(all_file_entries),
                    "view": "patch",
                    "staged": staged,
                    "path": target_rel_path,
                    "untracked": True,
                    "patch": page,
                    "patch_offset": offset,
                    "patch_limit": limit,
                    "patch_page_chars": len(page),
                    "patch_total_chars": len(full_patch),
                    "patch_next_offset": next_offset,
                    "patch_has_more": next_offset is not None,
                    "has_changes": True,
                    "provenance": {
                        "source": "git_worktree_untracked_synthetic",
                        "workspace_ref": workspace.workspace_ref,
                        "canonical_root": str(workspace.root),
                        "git_head": head,
                        "observed_at": time.time(),
                    },
                    "coverage": {
                        "tracked_files": "included",
                        "untracked_files": "synthetic_patch_from_dev_null",
                        "ignored_files": "excluded",
                    },
                }

        # Tracked files patch (either whole workspace or specific tracked path)
        diff_cmd = ["diff", "--no-ext-diff", "--no-textconv", "--no-color",
                    "--unified=3", "--inter-hunk-context=0"]
        if staged:
            diff_cmd.append("--cached")
        if target_rel_path:
            diff_cmd.extend(["--", ":(literal)" + target_rel_path])
        patch_raw, error = _current_diff_git(workspace.root, *diff_cmd)
        if error:
            return error
        patch_out = patch_raw.decode("utf-8", errors="replace")
        page = patch_out[offset:offset + limit]
        next_offset = offset + len(page) if offset + len(page) < len(patch_out) else None
        return {
            "ok": True,
            "workspace_ref": workspace.workspace_ref,
            "canonical_root": str(workspace.root),
            "git_head": head,
            "dirty": bool(all_file_entries),
            "view": "patch",
            "staged": staged,
            "path": target_rel_path,
            "untracked": False,
            "patch": page,
            "patch_offset": offset,
            "patch_limit": limit,
            "patch_page_chars": len(page),
            "patch_total_chars": len(patch_out),
            "patch_next_offset": next_offset,
            "patch_has_more": next_offset is not None,
            "has_changes": bool(patch_out.strip()),
            "provenance": {
                "source": "git_worktree",
                "workspace_ref": workspace.workspace_ref,
                "canonical_root": str(workspace.root),
                "git_head": head,
                "observed_at": time.time(),
            },
            "coverage": {
                "tracked_files": "included",
                "untracked_files": "excluded_in_tracked_patch",
                "ignored_files": "excluded",
            },
        }

    return {
        "ok": False,
        "error_type": "InvalidView",
        "error": "view must be 'summary' or 'patch'",
    }


def _compute_workspace_read(
    workspace: WorkspaceContext,
    rel_path: str,
    offset: int,
    limit: int,
    start_line: int | None = None,
    end_line: int | None = None,
) -> dict[str, Any]:
    # Public read carries UTF-8 text and native images only. Refuse PDF/DOCX by
    # the validation-resolved suffix before any body read, extraction or hash.
    if Path(rel_path).suffix.lower() in UNSUPPORTED_READ_FORMATS:
        return {
            "ok": False,
            "error_type": "UnsupportedReadFormat",
            "error": "PDF/DOCX are not supported by read; use prepare_file_attachment to prepare the original for later fetch.",
        }
    raw_bytes, read_error = _read_bounded_workspace_bytes(
        workspace, list(Path(rel_path).parts), rel_path, MAX_WORKSPACE_FILE_SIZE
    )
    if read_error is not None:
        return read_error
    if len(raw_bytes) > MAX_WORKSPACE_FILE_SIZE:
        return {
            "ok": False,
            "error_type": "FileTooLarge",
            "error": f"file '{rel_path}' size ({len(raw_bytes)} bytes) exceeds maximum {MAX_WORKSPACE_FILE_SIZE} bytes",
            "file_size_bytes": len(raw_bytes),
        }
    if b"\x00" in raw_bytes[:4096]:
        return {
            "ok": False,
            "error_type": "BinaryFileUnsupported",
            "error": f"file '{rel_path}' contains binary data; use prepare_file_attachment to prepare the original for later fetch.",
            "file_size_bytes": len(raw_bytes),
            "binary": True,
        }
    try:
        content = raw_bytes.decode("utf-8")
    except UnicodeDecodeError:
        return {
            "ok": False,
            "error_type": "BinaryFileUnsupported",
            "error": f"file '{rel_path}' is not valid UTF-8 text; use prepare_file_attachment to prepare the original for later fetch.",
            "file_size_bytes": len(raw_bytes),
            "binary": True,
        }

    file_sha256 = hashlib.sha256(raw_bytes).hexdigest()
    head = _git_inspect_small("rev-parse", "--verify", "HEAD", root=workspace.root)

    if start_line is not None:
        offset = 0
        for _ in range(start_line - 1):
            newline = content.find("\n", offset)
            if newline < 0:
                return {"ok": False, "error_type": "LineOutOfRange", "error": "start_line exceeds the file's line locations"}
            offset = newline + 1
    # Optional read ceiling: one past the end_line-th LF, or EOF when that LF
    # does not exist (end_line beyond EOF clamps; LF alone delimits lines).
    ceiling = len(content)
    if end_line is not None:
        ceiling = 0
        for _ in range(end_line):
            newline = content.find("\n", ceiling)
            if newline < 0:
                ceiling = len(content)
                break
            ceiling = newline + 1
    page = content[offset:min(offset + limit, ceiling)]
    page_end = offset + len(page)
    next_offset = page_end if page_end < ceiling else None

    result = {
        "ok": True,
        "path": rel_path,
        "content": page,
        "content_offset": offset,
        "content_start_line": content.count("\n", 0, min(offset, len(content))) + 1,
        "content_start_column": min(offset, len(content)) - content.rfind("\n", 0, min(offset, len(content))),
        "content_end_offset": offset + len(page),
        "offset_unit": "unicode_characters",
        "line_unit": "LF_delimited_1_based",
        "content_limit": limit,
        "content_page_chars": len(page),
        "content_total_chars": len(content),
        "content_next_offset": next_offset,
        "content_has_more": next_offset is not None,
        "file_size_bytes": len(raw_bytes),
        "file_sha256": file_sha256,
        "workspace_ref": workspace.workspace_ref,
        "canonical_root": str(workspace.root),
        "provenance": {
            "source": "direct_filesystem",
            "workspace_ref": workspace.workspace_ref,
            "canonical_root": str(workspace.root),
            "git_head": head,
            "observed_at": time.time(),
        },
        "coverage": {
            "file_type": "regular_utf8_text",
            "binary": False,
        },
    }
    return result


def _compute_workspace_search(
    workspace: WorkspaceContext,
    query: str,
    path_prefix: str | None,
    max_matches: int,
    match_offset: int = 0,
) -> dict[str, Any]:
    head = _git_inspect_small("rev-parse", "--verify", "HEAD", root=workspace.root)
    cmd = ["grep", "--no-color", "--no-column", "-z", "-F", "-n", "-I", "-e", query, "--"]
    if path_prefix:
        try:
            _, rel_prefix = _validate_workspace_relative_path(workspace.root, path_prefix)
            cmd.append(":(literal)" + rel_prefix)
        except ValueError as exc:
            return {"ok": False, "error_type": "InvalidPath", "error": str(exc)}
    rc, stdout, stderr = _git_run_bytes_bounded(*cmd, root=workspace.root, timeout=5.0)
    if rc not in (0, 1):
        return {"ok": False, "error_type": ("GitObservationUnsupported" if rc == fixed_git.UNSUPPORTED else
                    "SearchObservationTooLarge" if rc == fixed_git.TOO_LARGE else "SearchFailed"),
                "coverage": {"complete": False},
                "error": stderr.decode("utf-8", errors="replace").strip() or "git grep failed"}
    if rc == 1 and stdout:
        return {"ok": False, "error_type": "SearchOutputMalformed",
                "error": "no-match status contradicts grep output"}

    # With -z, Git emits filename NUL line-number NUL line-content LF.
    # Parse boundaries before decoding: filenames may contain colons or LF.
    matches: list[dict[str, Any]] = []
    cursor = 0
    total_matches = 0
    while cursor < len(stdout):
        path_end = stdout.find(b"\0", cursor)
        number_end = stdout.find(b"\0", path_end + 1) if path_end >= 0 else -1
        if path_end < 0 or number_end < 0:
            return {"ok": False, "error_type": "SearchOutputMalformed", "error": "missing grep record delimiter"}
        line_end = stdout.find(b"\n", number_end + 1)
        if line_end < 0:
            return {"ok": False, "error_type": "SearchOutputMalformed", "error": "missing grep record delimiter"}
        number = stdout[path_end + 1:number_end]
        if not number.isdigit() or len(number) > 12 or int(number) < 1:
            return {"ok": False, "error_type": "SearchOutputMalformed", "error": "invalid grep line number"}
        if match_offset <= total_matches < match_offset + max_matches:
            path = os.fsdecode(stdout[cursor:path_end])
            # Existing read refuses strings containing only whitespace. './' keeps
            # the exact file address without stripping or altering the filename.
            if not path.strip():
                path = './' + path
            line = stdout[number_end + 1:line_end].decode("utf-8", errors="replace")
            matches.append({"path": path, "line_number": int(number),
                            "line_text": line[:MAX_WORKSPACE_SEARCH_LINE_CHARS],
                            "line_text_truncated": len(line) > MAX_WORKSPACE_SEARCH_LINE_CHARS,
                            "read_locator": {"path": path, "start_line": int(number)}})
        total_matches += 1
        cursor = line_end + 1
    next_offset = match_offset + len(matches) if match_offset + len(matches) < total_matches else None
    return {
        "ok": True, "query": query, "workspace_ref": workspace.workspace_ref,
        "canonical_root": str(workspace.root), "git_head": head,
        "path_prefix": path_prefix, "match_count": len(matches), "total_matches": total_matches,
        "matches": matches, "matches_truncated": next_offset is not None,
        "match_offset": match_offset, "match_next_offset": next_offset,
        "provenance": {"source": "git_grep_tracked", "workspace_ref": workspace.workspace_ref,
                       "canonical_root": str(workspace.root), "git_head": head, "observed_at": time.time()},
        "coverage": {"tracked_files": "included", "untracked_files": "excluded",
                     "ignored_files": "excluded_unless_tracked", "binary_files": "excluded",
                     "search_mode": "fixed_string_literal", "text_decoding": "utf8_replacement",
                     "pagination": "match_offset_current_observation"},
    }


# ---------------------------------------------------------------------------
# Bridge VNext Phase 1: Principal-facing project-scoped read-only evidence
# ---------------------------------------------------------------------------

# VNext evidence tools take a mandatory project_ref resolved against the
# WorkspaceRegistry on every call. There is no default-root fallback and no
# process-global current-project state; unknown, unregistered, or
# identity-changed refs fail closed (cheap revalidation over synchronization).
VNEXT_IMAGE_MIME_BY_SUFFIX = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
}
MAX_VNEXT_IMAGE_FILE_SIZE = 5 * 1024 * 1024
# Public read refuses these container formats by validated suffix (case-insensitive)
# before any byte read; prepare_file_attachment prepares the original for later fetch.
UNSUPPORTED_READ_FORMATS = {".pdf", ".docx"}


def _vnext_image_bytes_match_mime(mime: str, head: bytes) -> bool:
    if mime == "image/png":
        return head.startswith(b"\x89PNG\r\n\x1a\n")
    if mime == "image/jpeg":
        return head.startswith(b"\xff\xd8\xff")
    if mime == "image/gif":
        return head[:6] in (b"GIF87a", b"GIF89a")
    if mime == "image/webp":
        return len(head) >= 12 and head[:4] == b"RIFF" and head[8:12] == b"WEBP"
    return False


def _required_project_context(project_ref: Any) -> WorkspaceContext | dict[str, Any]:
    if not isinstance(project_ref, str) or not project_ref.strip():
        return {
            "ok": False,
            "error_type": "ProjectRefRequired",
            "error": "project_ref is required on this tool; there is no default-root fallback",
        }
    try:
        return _WORKSPACE_REGISTRY.resolve(project_ref)
    except WorkspaceAuthorizationError:
        return {
            "ok": False,
            "error_type": "ProjectRefUnauthorized",
            "error": "project_ref is not a registered project or its registered Git worktree is no longer valid",
        }


def _agent_location_hint(candidate: dict[str, Any]) -> str | None:
    """Render one agent's existing Herdr ids as a short human disambiguator.

    Derived purely from the ``tab``/``pane`` suffix already present on the
    candidate (``w1R:t2`` + ``w1R:p5`` -> ``tab 2 / pane 5``), so it costs no
    extra backend call. It is a non-stable human reference for telling
    otherwise identical agents apart, not identity, not a handle, and not
    lifecycle authority; ``handle`` stays the only operation ref. Malformed,
    missing, or nonconforming ids yield ``None`` rather than a guess.
    """
    parts: list[str] = []
    for field, letter, label in (("tab_id", "t", "tab"), ("pane_id", "p", "pane")):
        value = candidate.get(field)
        if not isinstance(value, str):
            return None
        match = re.fullmatch(rf"{letter}([0-9]+)", value.rsplit(":", 1)[-1])
        if match is None:
            return None
        parts.append(f"{label} {match.group(1)}")
    return " / ".join(parts)


def _compact_vnext_agent(candidate: Any) -> dict[str, Any] | None:
    if not isinstance(candidate, dict):
        return None
    return {
        "handle": candidate.get("candidate_id"),
        "kind": candidate.get("agent_kind"),
        "status": candidate.get("herdr_status"),
        "name": candidate.get("agent_name"),
        "hint": _agent_location_hint(candidate),
        "workspace_id": candidate.get("workspace_id"),
        "checkout": candidate.get("checkout", agent_placement.unavailable()),
    }


def _compute_bridge_read_image(
    workspace: WorkspaceContext,
    rel_path: str,
    mime: str,
) -> dict[str, Any] | list[Any]:
    raw_bytes, read_error = _read_bounded_workspace_bytes(
        workspace, list(Path(rel_path).parts), rel_path, MAX_VNEXT_IMAGE_FILE_SIZE
    )
    if read_error is not None:
        return read_error
    if len(raw_bytes) > MAX_VNEXT_IMAGE_FILE_SIZE:
        return {
            "ok": False,
            "error_type": "FileTooLarge",
            "error": f"image '{rel_path}' size ({len(raw_bytes)} bytes observed) exceeds maximum {MAX_VNEXT_IMAGE_FILE_SIZE} bytes",
            "file_size_bytes": len(raw_bytes),
        }
    if not _vnext_image_bytes_match_mime(mime, raw_bytes[:64]):
        return {
            "ok": False,
            "error_type": "UnsupportedImageFormat",
            "error": f"file '{rel_path}' extension suggests {mime} but its bytes do not match",
            "mime_type": mime,
            "file_size_bytes": len(raw_bytes),
        }
    file_sha256 = hashlib.sha256(raw_bytes).hexdigest()
    head = _git_inspect_small("rev-parse", "--verify", "HEAD", root=workspace.root)
    image = Image(data=raw_bytes, format=mime.removeprefix("image/"))
    return [
        image,
        {
            "ok": True,
            "path": rel_path,
            "kind": "image",
            "mime_type": mime,
            "file_size_bytes": len(raw_bytes),
            "file_sha256": file_sha256,
            "workspace_ref": workspace.workspace_ref,
            "canonical_root": str(workspace.root),
            "provenance": {
                "source": "direct_filesystem",
                "workspace_ref": workspace.workspace_ref,
                "canonical_root": str(workspace.root),
                "git_head": head,
                "observed_at": time.time(),
            },
            "coverage": {
                "file_type": "image_allowlisted",
                "native_image_content": True,
            },
        },
    ]


def _compute_bridge_read(
    workspace: WorkspaceContext,
    rel_path: str,
    offset: int,
    limit: int,
    start_line: int | None = None,
    expected_sha256: str | None = None,
    end_line: int | None = None,
) -> dict[str, Any] | list[Any]:
    mime = VNEXT_IMAGE_MIME_BY_SUFFIX.get(Path(rel_path).suffix.lower())
    if mime is not None:
        if (offset != 0 or limit not in (DEFAULT_WORKSPACE_READ_PAGE, MAX_WORKSPACE_READ_PAGE)
                or start_line is not None or end_line is not None):
            return {
                "ok": False,
                "error_type": "ImagePagingUnsupported",
                "error": "image reads return the whole file; offset/limit pagination applies to text reads only",
            }
        result = _compute_bridge_read_image(workspace, rel_path, mime)
    else:
        result = _compute_workspace_read(workspace, rel_path, offset, limit, start_line, end_line=end_line)
    metadata = result[-1] if isinstance(result, list) else result
    if (expected_sha256 is not None and metadata.get("ok") is True
            and metadata["file_sha256"] != expected_sha256):
        return {"ok": False, "error_type": "ReadVersionChanged",
                "error": "file bytes differ from expected_sha256; no page returned",
                "expected_sha256": expected_sha256, "actual_sha256": metadata["file_sha256"]}
    return result


async def _project_agent_observation(workspace: WorkspaceContext) -> dict[str, Any]:
    """One generic discovery and compact projection shared by context and bridge_overview."""
    discovery = await _discover_project_candidates(workspace_ref=workspace.workspace_ref)
    agents: list[dict[str, Any]] = []
    agents_complete = False
    agents_skipped_count = 0
    agents_error: dict[str, str] | None = None
    counts = discovery.get("coverage_counts")
    raw_skipped = discovery.get("skipped_count")
    truncated = discovery.get("candidates_truncated")
    coverage_valid = (
        isinstance(counts, dict)
        and set(counts) == {"out_of_project", "invalid_or_unavailable", "truncated"}
        and all(isinstance(n, int) and not isinstance(n, bool) and n >= 0 for n in counts.values())
        and isinstance(raw_skipped, int) and not isinstance(raw_skipped, bool)
        and counts["invalid_or_unavailable"] == raw_skipped
        and isinstance(truncated, bool) and bool(counts["truncated"]) == truncated
    )
    if discovery.get("ok") and coverage_valid:
        agents = [
            compact
            for compact in (
                _compact_vnext_agent(candidate)
                for candidate in discovery.get("candidates", [])
            )
            if compact is not None
        ]
        projection_skipped = len(discovery.get("candidates", [])) - len(agents)
        counts = dict(counts)
        counts["invalid_or_unavailable"] += projection_skipped
        agents_skipped_count = counts["invalid_or_unavailable"]
        agents_complete = not truncated and agents_skipped_count == 0
    else:
        agents_error = {
            "error_type": "AgentDiscoveryUnavailable",
            "error": "live agent discovery failed; the visible-agent set is unknown for this project",
        }
    result = {
        "agents": agents,
        "agent_count": len(agents),
        "agents_complete": agents_complete,
        "agents_skipped_count": agents_skipped_count,
    }
    if agents_error is not None:
        result["agents_error"] = agents_error
    else:
        result["agents_coverage_counts"] = counts
    result["agents_rejection_diagnostics"] = (
        _rejection_diagnostics(discovery.get("rejection_diagnostics"), raw_skipped,
                               counts["truncated"], projection_skipped)
        if agents_error is None else {"status": "unavailable"})
    return result


_project_continuity = ProjectContinuity(
    _read_bounded_workspace_bytes, _vnext_open_error, _component_is_symlink
)


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=False, idempotentHint=True))
async def context(project_ref: str) -> dict[str, Any]:
    """Orient in the selected registered project: bounded Git facts, capacity,
    Agent handles and continuity pointers. This call does not read the current-state
    file body. continuation_inbox observes up to 50 retained classified Works for
    matching host session metadata, including notification-consumed results with
    separate delivery_consumed state. Unknown sessions get only an unbound count.
    This observation does not process results, renew evidence or bind a widget.

    Checkout metadata is bounded observation, not a dirty task baseline or permission.
    Dirty excludes nested submodule worktree changes; filter-dependent facts are unknown.
    Use handle for operations; workspace/tab/pane hints only aid recognition."""
    resolved = _required_project_context(project_ref)
    if isinstance(resolved, dict):
        return resolved
    workspace = resolved
    agent_observation = await _project_agent_observation(workspace)
    head = _git_inspect_small("rev-parse", "--short", "HEAD", root=workspace.root)
    branch = _git_inspect_small("rev-parse", "--abbrev-ref", "HEAD", root=workspace.root)
    status_rc, status_out, _status_err = _git_run_bounded(
        "status", "--porcelain=v1", "-uall", root=workspace.root
    )
    status_ok = status_rc == 0 and bool(head) and bool(branch)
    status_lines = [
        line for line in status_out.splitlines() if line.strip()
    ] if status_ok else []
    if status_ok:
        git_facts = {
            "observation": "ok",
            "branch": branch,
            "head": head,
            "dirty": bool(status_lines),
            "changes": len(status_lines),
        }
    else:
        # Never fabricate dirty/head/branch facts from a failed observation.
        git_facts = {
            "observation": "unavailable",
            "error_type": "GitObservationUnsupported" if status_rc == fixed_git.UNSUPPORTED else "GitObservationUnavailable",
            "branch": branch,
            "head": head,
            "dirty": None,
            "changes": None,
        }
    git_facts["submodule_worktrees"] = "not_observed"
    result = {
        "ok": True,
        "project_ref": workspace.workspace_ref,
        "root": str(workspace.root),
        "git": git_facts,
        "work_capacity": _work_capacity(project_ref, str(workspace.root)),
        "continuation_inbox": _continuation_inbox_observation(project_ref, str(workspace.root)),
        "continuity": await asyncio.to_thread(_project_continuity.describe, workspace),
        **agent_observation,
        "provenance": {
            "source": "direct_git_and_live_agent_snapshot",
            "project_ref": workspace.workspace_ref,
            "canonical_root": str(workspace.root),
            "git_head": head,
            "observed_at": time.time(),
        },
    }
    return result


async def join_worker(operation, *args):
    """Keep the caller's lease until its worker exits, even after cancellation.

    Joining may wait for the worker's own I/O bounds; this adds no OS deadline.
    """
    pending = asyncio.create_task(asyncio.to_thread(operation, *args))
    try:
        return await asyncio.shield(pending)
    except asyncio.CancelledError as cancellation:
        while not pending.done():
            try:
                await asyncio.shield(pending)
            except asyncio.CancelledError:
                continue
            except Exception:
                break
        if not pending.cancelled():
            pending.exception()
        raise cancellation


async def checkpoint(project_ref: str, content: str | None, expected_revision: str,
                     edits: list[dict[str, str]] | None = None) -> dict[str, Any]:
    """Conditionally replace the manifest's state file with Principal-supplied text.

    Preserve relevant causal decisions: replacement does not archive history.
    No Git commit, execution, new authorization, or global external-writer CAS.
    An opted-in bridge-state-slot is enforced here as bytes and limit identity only.
    """
    workspace = _required_project_context(project_ref)
    if isinstance(workspace, dict):
        return workspace
    lease = await _access_gate(workspace.root).acquire("writer")
    try:
        return await join_worker(
            _project_continuity.checkpoint, workspace, content, expected_revision, edits
        )
    finally:
        await lease.release()


@mcp.tool(name="current_state_update", annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=True, openWorldHint=False, idempotentHint=False))
async def _current_state_update_tool(project_ref: str, expected_revision: str,
                                     content: str | None = None,
                                     edits: list[dict[str, str]] | None = None) -> dict[str, Any]:
    """Replace or create only the manifest-routed current-state UTF-8 file from
    supplied content or exact edits; preserves no history or recovery point; no
    archive, commit, summary, or truncation.

    Whole-line bridge-state-slot markers opt into a mechanical check: one exact
    pair, body bytes within the declared limit (1024..65536), and an existing
    valid limit left unchanged. No marker keeps the legacy replace. The 65536-byte
    file cap still applies. project_text_edit does not enforce the slot.

    edits is [{old_text, new_text}]; expected_revision is required. Each nonempty
    old_text must occur exactly once in the same original text; ranges cannot overlap. Stale
    retries conflict; this is not global idempotency against external writers.
    """
    return await checkpoint(project_ref, content, expected_revision, edits)


async def _read_target(
    project_ref: str,
    path: str,
    offset: int = 0,
    limit: int = DEFAULT_WORKSPACE_READ_PAGE,
    work_ref: str | None = None,
    start_line: int | None = None,
    expected_sha256: str | None = None,
    end_line: int | None = None,
) -> dict[str, Any] | list[Any]:
    """Shared target/gate read for UTF-8 text and native images.

    Text defaults to 4096 Unicode characters, maximum 16384. Continue with returned
    content_next_offset and expected_sha256=file_sha256 to reject changed bytes.
    start_line is 1-based LF, exclusive with nonzero offset. Optional end_line is an
    absolute 1-based inclusive line ceiling (beyond EOF clamps to EOF). Images are
    whole (up to 5 MiB), no line/offset paging; default or 16384 limit accepted.
    Public read refuses PDF/DOCX by validated suffix before any body read
     (UnsupportedReadFormat; prepare_file_attachment prepares originals for later fetch); other binary fails."""
    if expected_sha256 is not None and (not isinstance(expected_sha256, str)
            or re.fullmatch(r"[0-9a-f]{64}", expected_sha256) is None):
        return {"ok": False, "error_type": "InvalidExpectedSHA256",
                "error": "expected_sha256 must be a lowercase full-file SHA-256 hex digest"}
    resolved = _resolve_evidence_target(project_ref, work_ref)
    if isinstance(resolved, dict):
        return resolved
    workspace = resolved.workspace
    if not isinstance(path, str) or not path.strip():
        return {
            "ok": False,
            "error_type": "InvalidPath",
            "error": "path must be a non-empty string",
        }
    try:
        _, rel_path = _validate_workspace_relative_path(workspace.root, path)
    except ValueError as exc:
        return {
            "ok": False,
            "error_type": "InvalidPath",
            "error": str(exc),
        }
    if not isinstance(offset, int) or isinstance(offset, bool) or offset < 0:
        return {
            "ok": False,
            "error_type": "InvalidOffset",
            "error": "offset must be a non-negative integer",
        }
    if not isinstance(limit, int) or isinstance(limit, bool) or limit <= 0 or limit > MAX_WORKSPACE_READ_PAGE:
        return {
            "ok": False,
            "error_type": "InvalidLimit",
            "error": f"limit must be between 1 and {MAX_WORKSPACE_READ_PAGE}",
        }
    if start_line is not None:
        if type(start_line) is not int or start_line < 1:
            return {"ok": False, "error_type": "InvalidStartLine", "error": "start_line must be a positive integer"}
        if offset != 0:
            return {"ok": False, "error_type": "AmbiguousReadPosition", "error": "use start_line or nonzero offset, not both"}
    if end_line is not None:
        if type(end_line) is not int or end_line < 1:
            return {"ok": False, "error_type": "InvalidEndLine", "error": "end_line must be a positive integer"}
        if start_line is not None and end_line < start_line:
            return {"ok": False, "error_type": "InvalidEndLine",
                    "error": "end_line must not be below start_line"}
    lease = await _access_gate(workspace.root).acquire("reader")
    try:
        checked = _resolve_evidence_target(project_ref, work_ref)
        if isinstance(checked, dict):
            return checked
        return _evidence_result(await join_worker(
            partial(_compute_bridge_read, workspace, rel_path, offset, limit, start_line,
                    expected_sha256, end_line)
        ), resolved)
    finally:
        await lease.release()


async def read(project_ref: str, path: str, offset: int = 0,
               limit: int = DEFAULT_WORKSPACE_READ_PAGE, work_ref: str | None = None,
               start_line: int | None = None, expected_sha256: str | None = None,
               end_line: int | None = None) -> dict[str, Any] | list[Any]:
    return await _read_target(project_ref, path, offset, limit, work_ref, start_line,
                              expected_sha256, end_line=end_line)


async def _read_tool(
    project_ref: str,
    path: str,
    offset: int = 0,
    limit: int = DEFAULT_WORKSPACE_READ_PAGE,
    work_ref: str | None = None,
    start_line: int | None = None,
    expected_sha256: str | None = None,
    end_line: StrictInt | None = None,
) -> CallToolResult:
    """Read UTF-8 text or one whole native image at a project/frozen Work
    checkout. Text: default 4096, max 16384 Unicode characters; continue
    content_next_offset with expected_sha256=file_sha256; changed bytes return
    no page. start_line is 1-based LF and excludes nonzero offset. end_line is
    an absolute 1-based inclusive ceiling, clamps at EOF, and bounds
    continuation. Images: max 5 MiB, matching suffix/magic, default or 16384
    limit; no offset/start_line/end_line paging. PDF/DOCX and other binary are
    refused; use prepare_file_attachment for originals. read does not approve, parse or
    assemble attachments."""
    result = await read(project_ref, path, offset, limit, work_ref,
                        start_line, expected_sha256, end_line=end_line)
    # No SDK output schema exists any more: validate metadata privately and return
    # the ORIGINAL dict/list so absent/null/extra diagnostics are not rewritten.
    if isinstance(result, list):
        try:
            return native_image_result(result)
        except NativeImageEnvelopeError as exc:
            # Fail closed: internal/protocol dispatch error, never an ordinary
            # ok=false application response and never image content or metadata
            # text without the correlated image.
            return exc.wire_result()
    ReadResultModel.model_validate(result)
    if is_image_success_metadata(result):
        # A successful image-kind dict without its native envelope is an internal
        # producer failure, not serializable structured image metadata.
        return NativeImageEnvelopeError(
            'image metadata requires the native image envelope').wire_result()
    return read_tool_result(result)


# Preserve the SDK's existing read argument-schema title as well as its fields.
_read_tool.__name__ = "read"
mcp.tool(name="read", structured_output=False, annotations=ToolAnnotations(
    readOnlyHint=True, destructiveHint=False, openWorldHint=False, idempotentHint=True))(_read_tool)


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=False, idempotentHint=True))
async def search(
    project_ref: str,
    query: str,
    path_prefix: str | None = None,
    max_matches: int = DEFAULT_WORKSPACE_SEARCH_MATCHES,
    work_ref: str | None = None,
    match_offset: int = 0,
    include_untracked: bool = False,
) -> dict[str, Any]:
    """Find literal text in tracked files; include_untracked additionally searches nonignored untracked text files.

    Untracked files are excluded by default. Use returned read(path,start_line) locators and
    match_next_offset; pages are fresh observations, not a retained snapshot.
    Opt-in search uses two bounded passes (1 MiB combined), with exact read locators."""
    if type(include_untracked) is not bool:
        return {"ok": False, "error_type": "InvalidIncludeUntracked",
                "error": "include_untracked must be a boolean"}
    if include_untracked:
        return await _untracked_search.search(
            project_ref, query, path_prefix, max_matches, work_ref, match_offset)
    resolved = _resolve_evidence_target(project_ref, work_ref)
    if isinstance(resolved, dict):
        return resolved
    workspace = resolved.workspace
    if (not isinstance(query, str) or not query or len(query) > MAX_WORKSPACE_SEARCH_QUERY_CHARS
            or "\0" in query or "\n" in query):
        return {
            "ok": False,
            "error_type": "InvalidQuery",
            "error": f"query must be a non-empty string under {MAX_WORKSPACE_SEARCH_QUERY_CHARS} characters without NUL or LF",
        }
    try:
        query.encode("utf-8")
    except UnicodeError:
        return {"ok": False, "error_type": "InvalidQuery", "error": "query must be encodable as UTF-8"}
    if not isinstance(max_matches, int) or isinstance(max_matches, bool) or max_matches <= 0 or max_matches > MAX_WORKSPACE_SEARCH_MATCHES:
        return {
            "ok": False,
            "error_type": "InvalidLimit",
            "error": f"max_matches must be between 1 and {MAX_WORKSPACE_SEARCH_MATCHES}",
        }
    if path_prefix is not None and (not isinstance(path_prefix, str) or not path_prefix or "\0" in path_prefix):
        return {"ok": False, "error_type": "InvalidPath", "error": "path_prefix must be a non-empty relative path"}
    if type(match_offset) is not int or match_offset < 0:
        return {"ok": False, "error_type": "InvalidMatchOffset", "error": "match_offset must be a non-negative integer"}
    lease = await _access_gate(workspace.root).acquire("reader")
    try:
        checked = _resolve_evidence_target(project_ref, work_ref)
        if isinstance(checked, dict):
            return checked
        return _evidence_result(await join_worker(
            _compute_workspace_search, workspace, query, path_prefix, max_matches, match_offset
        ), resolved)
    finally:
        await lease.release()


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=False, idempotentHint=True))
async def diff(
    project_ref: str,
    path: str | None = None,
    view: str = "summary",
    staged: bool = False,
    offset: int = 0,
    limit: int = MAX_WORKSPACE_DIFF_PAGE,
    work_ref: str | None = None,
    base: str | None = None,
    target: str | None = None,
) -> dict[str, Any]:
    """Inspect current changes or compare two commits at the project or frozen Work checkout.

    Omit both revisions for current state; otherwise supply base and target and no staged.
    summary pages count files; patch pages count Unicode characters. Current summary
    combines index/worktree; staged selects tracked patch. Unknown is not clean."""
    resolved = _resolve_evidence_target(project_ref, work_ref)
    if isinstance(resolved, dict):
        return resolved
    workspace = resolved.workspace
    if view not in ("summary", "patch"):
        return {
            "ok": False,
            "error_type": "InvalidView",
            "error": "view must be 'summary' or 'patch'",
        }
    if not isinstance(staged, bool):
        return {
            "ok": False,
            "error_type": "InvalidParameter",
            "error": "staged must be a boolean",
        }
    if not isinstance(offset, int) or isinstance(offset, bool) or offset < 0:
        return {
            "ok": False,
            "error_type": "InvalidOffset",
            "error": "offset must be a non-negative integer",
        }
    if not isinstance(limit, int) or isinstance(limit, bool) or limit <= 0 or limit > MAX_WORKSPACE_DIFF_PAGE:
        return {
            "ok": False,
            "error_type": "InvalidLimit",
            "error": f"limit must be between 1 and {MAX_WORKSPACE_DIFF_PAGE}",
        }
    if (base is not None or target is not None) and staged:
        return {"ok": False, "error_type": "AmbiguousDiffMode", "error": "staged cannot be combined with commit comparison"}
    lease = await _access_gate(workspace.root).acquire("reader")
    try:
        checked = _resolve_evidence_target(project_ref, work_ref)
        if isinstance(checked, dict):
            return checked
        if base is not None or target is not None:
            result = await join_worker(
                _compute_revision_diff, workspace, path, view, offset, limit, base, target
            )
        else:
            result = await join_worker(
                _compute_workspace_diff, workspace, path, view, staged, offset, limit
            )
        return _evidence_result(result, resolved)
    finally:
        await lease.release()


def _deployment_snapshot() -> dict[str, Any]:
    service = os.environ.get(
        "BRIDGE_SERVICE_NAME", "gpt-agent-bridge.service"
    ).strip() or "gpt-agent-bridge.service"
    result: dict[str, Any] = {
        "service": service,
        "observed": False,
        "active_state": None,
        "sub_state": None,
        "main_pid": None,
        "exec_start_timestamp": None,
    }
    try:
        completed = subprocess.run(
            [
                "systemctl", "show", service,
                "--no-pager",
                "--property=ActiveState,SubState,MainPID,ExecMainStartTimestamp",
            ],
            capture_output=True,
            text=True,
            timeout=3,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        result["error"] = _bounded_nullable_text(str(exc), 400)
        return result
    if completed.returncode != 0:
        result["error"] = _bounded_nullable_text(
            completed.stderr.strip() or "systemd service state unavailable", 400
        )
        return result
    values: dict[str, str] = {}
    for line in completed.stdout.splitlines():
        key, separator, value = line.partition("=")
        if separator:
            values[key] = value
    result.update({
        "observed": bool(values),
        "active_state": values.get("ActiveState"),
        "sub_state": values.get("SubState"),
        "exec_start_timestamp": values.get("ExecMainStartTimestamp"),
    })
    try:
        result["main_pid"] = int(values["MainPID"])
    except (KeyError, ValueError):
        pass
    return result


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=False, idempotentHint=True))
async def bridge_overview(project_ref: str | None = None) -> dict[str, Any]:
    """Observe Bridge bootstrap and runtime diagnostics: server, repository,
    deployment and Agent-discovery observations for one root.

    Without project_ref this uses the configured default root and additionally
    lists registered project refs, a read-only persisted-versus-live registration
    observation, and control documents. With project_ref it scopes observations
    to that registered project and reports only that ref's registration relation,
    without listing other refs. The registration observation does not create,
    repair, or save the store and does not probe other workspace roots. For
    routine project orientation use context; for connectivity alone use
    bridge_health. Continuity pointers are manifest-routed; no document body is
    returned."""
    try:
        workspace = _workspace_context(project_ref)
    except WorkspaceAuthorizationError:
        return {
            "ok": False,
            "error_type": "WorkspaceRefUnauthorized",
            "error": "project_ref is not authorized or its registered Git worktree is no longer valid",
        }
    repository = await _capture_workspace_boundary(workspace.root)
    deployment = _deployment_snapshot()
    observation = await _project_agent_observation(workspace)
    health = (
        "unavailable" if "agents_error" in observation
        else "healthy" if observation["agents_complete"] else "partial"
    )
    project_state = {
        "workspace": str(workspace.root),
        "project_ref": workspace.workspace_ref,
        "work_capacity": _work_capacity(workspace.workspace_ref, str(workspace.root)),
        "continuity": _project_continuity.describe(workspace),
    }
    if workspace.is_default:
        continuity = project_state["continuity"]
        document_paths = set(PROJECT_DOCUMENTS.values()) | {".principal/project.json"}
        canonical = continuity.get("canonical_pointers", {})
        document_paths.update(canonical.get("rules", []))
        for path in (canonical.get("memory"), continuity.get("current_state", {}).get("path")):
            if path is not None:
                document_paths.add(path)
        project_state["documents"] = []
        for path in sorted(document_paths):
            _, error = _read_bounded_workspace_bytes(workspace, path.split("/"), path, 0)
            project_state["documents"].append({
                "name": path, "path": str(workspace.root / path), "available": error is None,
            })
        project_state["registered_project_refs"] = list(_WORKSPACE_REGISTRY.refs)
        project_state["binding_guidance"] = (
            "Calls route by explicit registered project_ref; ChatGPT Project identity is not exposed."
        )
        project_state["registration"] = _WORKSPACE_REGISTRY.registration_view(None)
    else:
        project_state["registration"] = _WORKSPACE_REGISTRY.registration_view(workspace.workspace_ref)
    return {
        "ok": True,
        "repository": repository,
        "deployment": deployment,
        "runtime": {
            "pid": os.getpid(),
            "started_at": BRIDGE_STARTED_AT,
            "workspace": str(workspace.root),
            "project_ref": workspace.workspace_ref,
            "same_process_as_deployed_main": (
                deployment.get("main_pid") == os.getpid()
                if isinstance(deployment.get("main_pid"), int) else None
            ),
        },
        "observation": {
            "health": health,
            "candidate_count": observation["agent_count"],
            "complete": observation["agents_complete"],
            "skipped_count": observation["agents_skipped_count"],
            "source": "generic_project_candidate_discovery",
            "rejection_diagnostics": observation["agents_rejection_diagnostics"],
            **({"coverage_counts": observation["agents_coverage_counts"]}
               if "agents_coverage_counts" in observation else {}),
            **({"error": observation["agents_error"]} if "agents_error" in observation else {}),
        },
        "agents": observation["agents"],
        "project_state": project_state,
    }


# ---------------------------------------------------------------------------
# MCP tools
# ---------------------------------------------------------------------------


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=False, idempotentHint=True))
async def bridge_health() -> dict[str, Any]:
    """Observe Bridge responsiveness, Herdr connectivity and raw registered tool names.

    No Agent input or service control. Registered names do not establish a client's
    model-visible schema."""
    try:
        response = await HERDR._call("api", "snapshot", timeout=10)
        snapshot = response.get("snapshot")
        if not isinstance(snapshot, dict) or not isinstance(snapshot.get("agents"), list):
            raise HerdrBackendError("Herdr snapshot is malformed")
        connectivity = {"status": "reachable", "source": "herdr_api_snapshot"}
    except Exception as exc:
        connectivity = {
            "status": "unavailable",
            "source": "herdr_api_snapshot",
            "error": _bounded_nullable_text(str(exc), 400),
        }
    tools = await mcp.list_tools()
    return {
        "ok": True,
        "bridge": "gpt-agent-bridge",
        "runtime": {"pid": os.getpid(), "started_at": BRIDGE_STARTED_AT, "workspace": str(ROOT)},
        "herdr": connectivity,
        "tool_surface": {
            "registered_count": len(tools),
            "names": sorted(tool.name for tool in tools),
        },
    }


# ---------------------------------------------------------------------------
# Server
# ---------------------------------------------------------------------------


def _compute_revision_diff(
    workspace: WorkspaceContext, path: str | None, view: str,
    offset: int, limit: int, base: str | None, target: str | None,
) -> dict[str, Any]:
    """Resolve revisions once, then compare immutable commit IDs without checkout."""
    commits = []
    for label, revision in (("base", base), ("target", target)):
        if not isinstance(revision, str) or not revision or len(revision) > 1024 or "\0" in revision:
            return {"ok": False, "error_type": "InvalidRevision", "error": f"{label} must name a commit; both base and target are required"}
        rc, output, _ = _git_run_bounded(
            "rev-parse", "--verify", "--end-of-options", revision + "^{commit}", root=workspace.root
        )
        commit = output.strip()
        if rc != 0 or not re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", commit):
            return {"ok": False, "error_type": "RevisionUnavailable", "error": f"{label} does not resolve to a commit"}
        commits.append(commit)
    path_args = ["--"]
    if path is not None:
        # Revision paths belong to Git trees, not today's symlink targets.
        if (not isinstance(path, str) or not path or "\0" in path or Path(path).is_absolute()
                or any(part in ("..", ".git") for part in Path(path).parts)):
            return {"ok": False, "error_type": "InvalidPath", "error": "path must be a relative non-traversing Git tree path"}
        path_args.append(":(literal)" + path)
    args = ["diff", "--no-ext-diff", "--no-textconv", "--no-renames"]
    args += (["--numstat", "-z"] if view == "summary"
             else ["--no-color", "--unified=3", "--inter-hunk-context=0"])
    rc, raw, err = _git_run_bytes_bounded(*args, *commits, *path_args, root=workspace.root)
    if rc != 0:
        return {"ok": False, "error_type": "GitDiffError", "error": err.decode("utf-8", errors="replace")[:1000]}
    result = {
        "ok": True, "view": view, "path": path, "observation_mode": "commit_comparison",
        "base_commit": commits[0], "target_commit": commits[1],
        "version": {"base_commit": commits[0], "target_commit": commits[1]},
        "canonical_root": str(workspace.root), "workspace_ref": workspace.workspace_ref,
        "provenance": {"source": "git_commit_comparison", "observed_at": time.time()},
        "coverage": {"tracked_files": "committed_trees", "untracked_files": "excluded",
                     "worktree_changes": "excluded", "index_changes": "excluded",
                     "renames": "delete_and_add", "binary_files": "metadata_only"},
    }
    if view == "summary":
        entries = []
        for record in raw.split(b"\0"):
            if not record:
                continue
            added, deleted, filename = record.split(b"\t", 2)
            entries.append({"path": os.fsdecode(filename),
                            "insertions": int(added) if added.isdigit() else None,
                            "deletions": int(deleted) if deleted.isdigit() else None})
        page = entries[offset:offset + min(limit, MAX_WORKSPACE_SUMMARY_FILES)]
        next_offset = offset + len(page) if offset + len(page) < len(entries) else None
        result.update(files=page, counts={"total": len(entries)}, files_offset=offset,
                      files_next_offset=next_offset, files_truncated=next_offset is not None,
                      has_changes=bool(entries))
    else:
        text = raw.decode("utf-8", errors="replace")
        page = text[offset:offset + limit]
        next_offset = offset + len(page) if offset + len(page) < len(text) else None
        result.update(patch=page, patch_offset=offset, patch_limit=limit,
                      patch_page_chars=len(page), patch_total_chars=len(text),
                      patch_next_offset=next_offset, patch_has_more=next_offset is not None,
                      has_changes=bool(text))
        result["coverage"]["text_decoding"] = "utf8_replacement"
    return result


def _resolve_evidence_target(
    project_ref: str, work_ref: str | None = None,
) -> EvidenceTarget | dict[str, Any]:
    """Resolve only registered project or immutable Work-bound checkout evidence."""
    project = _required_project_context(project_ref)
    if isinstance(project, dict):
        return project
    if work_ref is None:
        return EvidenceTarget(project, project, None)
    if not isinstance(work_ref, str) or not work_ref:
        return {"ok": False, "error_type": "InvalidWorkRef", "error": "work_ref must be a non-empty string"}
    work = _lookup_work(project_ref, str(project.root), work_ref)
    if work.get("ok") is False:
        return work
    checkout = work.get("evidence_checkout")
    if not work.get("execution_identity") or not isinstance(checkout, EvidenceCheckout):
        return {"ok": False, "error_type": "WorkEvidenceTargetUnavailable",
                "error": "Work has no recorded bound checkout identity; no Agent or handoff fallback is permitted"}
    try:
        workspace = checkout.revalidate(project)
    except WorkspaceAuthorizationError:
        return {"ok": False, "error_type": "WorkEvidenceTargetChanged",
                "error": "recorded execution checkout is missing or its worktree/common-dir identity changed"}
    return EvidenceTarget(project, workspace, work_ref)


def _evidence_result(result: Any, target: EvidenceTarget) -> Any:
    """Qualify evidence without adding Git queries or a global content token."""
    if isinstance(result, list):
        return [_evidence_result(item, target) if isinstance(item, dict) else item for item in result]
    result = dict(result)
    result.update(target.provenance())
    if result.get("ok"):
        if "content_offset" in result:
            result["pagination"] = {"unit": "unicode_characters", "offset": result["content_offset"], "next_offset": result["content_next_offset"]}
        elif "patch_offset" in result:
            result["pagination"] = {"unit": "unicode_characters", "offset": result["patch_offset"], "next_offset": result["patch_next_offset"]}
        elif "match_offset" in result:
            result["pagination"] = {"unit": "matches", "offset": result["match_offset"], "next_offset": result["match_next_offset"]}
        elif "files_offset" in result:
            result["pagination"] = {"unit": "files", "offset": result["files_offset"], "next_offset": result["files_next_offset"]}
        else:
            result["pagination"] = {"unit": "whole_image", "next_offset": None}
        frozen = result.get("observation_mode") == "commit_comparison"
        result.setdefault("observation_mode", "current_worktree")
        result["provenance"] = {**result.get("provenance", {}), **target.provenance(),
            "atomic_snapshot": False,
            "proves": "commit_difference" if frozen else "observed_content_only"}
        if not frozen:
            result.setdefault("coverage", {})["submodule_worktrees"] = "not_observed"
            result["version"] = {"git_head": result.get("git_head") or result["provenance"].get("git_head")}
    return result


# These observers retain their bounded filesystem envelopes and reader-gated binding.
from .file_observation import register_file_observation
from .file_attachment import ATTACH_RESOURCE_PREFIX, register_file_attachment
from .search_observation import UntrackedSearch
from .tool_presentation import forbid_extra_arguments

_file_observation = register_file_observation(mcp, _resolve_evidence_target, _access_gate)
_file_attachment = register_file_attachment(mcp, _resolve_evidence_target, _access_gate)
_untracked_search = UntrackedSearch(_resolve_evidence_target, _access_gate)


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=True, openWorldHint=False, idempotentHint=False))
async def project_text_edit(project_ref: str, path: str, expected_sha256: str,
                            edits: list[TextEdit], work_ref: str | None = None) -> dict[str, Any]:
    """Edit an existing regular UTF-8 project file using its full lowercase SHA256.

    1..256 exact old_text/new_text edits match uniquely and without overlap in the
    same original; untouched bytes/newlines/mode remain. File/result <=1 MiB.
    No links, .git/traversal, NUL/binary, creation, staging, hooks or commands.
    Frozen Work targeting matches read/search/diff. Unknown writes must not be
    retried blindly; the writer gate covers cooperating Bridge calls only.
    """
    target = _resolve_evidence_target(project_ref, work_ref)
    if isinstance(target, dict):
        return target
    lease = await _access_gate(target.workspace.root).acquire("writer")
    try:
        current = _resolve_evidence_target(project_ref, work_ref)
        if isinstance(current, dict):
            return current
        if current != target:
            return {"ok": False, "error_type": "TargetChanged", "error": "Evidence target changed before editing."}
        return await join_worker(text_edit, target, path, expected_sha256, edits)
    finally:
        await lease.release()


# Candidate store owns captured staged facts and immutable attempt receipts.
from .commit_candidate import CandidateStore, Refused

_commit_candidates = CandidateStore(lambda project_ref, work_ref: _resolve_evidence_target(project_ref, work_ref))


def _candidate_rejected(reason):
    return {"status": "rejected", "reason": str(reason)[:300],
            "side_effects": {"ref_updated": False, "objects_may_remain": False}}


def _candidate_target(project_ref, candidate_id):
    try:
        target = _commit_candidates.target_for(project_ref, candidate_id)
    except (KeyError, Refused, TypeError) as error:
        return _candidate_rejected(str(error) if not isinstance(error, KeyError)
                                   else "candidate-unavailable-no-recapture")
    current = _resolve_evidence_target(project_ref, target.work_ref)
    if isinstance(current, dict):
        return current
    if current != target:
        return _candidate_rejected("evidence-target-changed")
    return target


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=True, openWorldHint=False, idempotentHint=False))
async def commit_prepare(project_ref: str, paths: list[StrictStr] | None = None, work_ref: str | None = None,
                         candidate_id: str | None = None, view: str = "summary",
                         offset: int = 0, limit: int = 50) -> dict[str, Any]:
    """With paths, stage exactly those selected project paths into the real Git
    index and freeze the commit candidate; with paths omitted, freeze the
    already-staged content without repository writes; with candidate_id, page the
    saved candidate without staging or recapture.

    paths: 1..2048 exact repo-relative files, <=16 KiB total UTF-8 path bytes,
    <=4 MiB total contents. One raw-object batch stages captured bytes. Stages
    modifications/new files/deletions via a private index, then atomically installs it;
    refuses mixed staged/unstaged selections, staging outside selection, helpers
    and conversion attributes. May write objects/index, never refs/working files.
    Omit paths to capture already-staged content without repository writes.
    A 30-second deadline and bounded candidate/cache resources still apply.
    candidate_id pages immutable summary/patch/receipt; paths then forbidden.
    Process-local IDs are not authorization; unknown preparation is not safe to
    retry. limit 1..16384; files/events capped at 100. Patch completeness flags
    qualify display only. commit publishes exactly this candidate, never paths.
    """
    project = _required_project_context(project_ref)
    if isinstance(project, dict):
        return project
    if (candidate_id is not None and (not isinstance(candidate_id, str) or not candidate_id)
            or view not in ("summary", "patch", "receipt")
            or type(offset) is not int or offset < 0
            or type(limit) is not int or not 1 <= limit <= 16384):
        return _candidate_rejected("invalid-candidate-or-page")
    if candidate_id is not None and paths is not None:
        return _candidate_rejected("paths-forbidden-with-candidate-id")
    if candidate_id is not None:
        # Historical pages are immutable cache reads, authorized by the current
        # project and the store's exact project/work route. Never resolve Work,
        # acquire its checkout gate or recapture Git for an existing candidate.
        return await join_worker(lambda: _commit_candidates.prepare(
            project_ref, work_ref, paths=paths, candidate_id=candidate_id, view=view, offset=offset, limit=limit))
    target = _resolve_evidence_target(project_ref, work_ref)
    if isinstance(target, dict):
        return target
    lease = await _access_gate(target.workspace.root).acquire("writer" if paths is not None else "reader")
    try:
        current = _resolve_evidence_target(project_ref, work_ref)
        if isinstance(current, dict):
            return current
        if current != target:
            return _candidate_rejected("evidence-target-changed")
        return await join_worker(lambda: _commit_candidates.prepare(
            project_ref, work_ref, paths=paths, candidate_id=candidate_id, view=view, offset=offset, limit=limit))
    finally:
        await lease.release()


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=True, openWorldHint=False, idempotentHint=False))
async def commit(project_ref: str, candidate_id: str, message: str) -> dict[str, Any]:
    """Commit an exact prepared staged candidate with the supplied message.

    Writes objects and the branch/ref log, preserving working files and index bytes.
    Repeated same requests return only the old receipt, not a new attempt; unknown
    is not safe to retry. IDs are not authorization; no staging, hooks or remote action."""
    project = _required_project_context(project_ref)
    if isinstance(project, dict):
        return project
    if not isinstance(candidate_id, str) or not candidate_id or not isinstance(message, str):
        return _candidate_rejected("invalid-candidate-or-message")
    # Validate the message before target lookup or any attempted repository write.
    cached = await join_worker(_commit_candidates.cached_result, project_ref, candidate_id, message)
    if cached is not None:
        # Same-request replay is historical evidence, not another attempt. Its
        # original result survives Work expiry without changing any fields.
        return _candidate_effects(cached) if "candidate_id" in cached else cached
    target = await join_worker(_candidate_target, project_ref, candidate_id)
    if isinstance(target, dict):
        # A concurrent attempt may have finished while target lookup ran.
        cached = await join_worker(_commit_candidates.cached_result, project_ref, candidate_id, message)
        if cached is not None:
            return _candidate_effects(cached) if "candidate_id" in cached else cached
        return target
    lease = await _access_gate(target.workspace.root).acquire("writer")
    try:
        # A competing waiter may have attempted this candidate while we waited.
        # Replay before resolving Work; an unattempted candidate still needs it.
        cached = await join_worker(_commit_candidates.cached_result, project_ref, candidate_id, message)
        if cached is not None:
            return _candidate_effects(cached) if "candidate_id" in cached else cached
        current = _resolve_evidence_target(project_ref, target.work_ref)
        if isinstance(current, dict):
            return current
        if current != target:
            return _candidate_rejected("evidence-target-changed")
        result = await join_worker(_commit_candidates.commit, project_ref, candidate_id, message)
        return _candidate_effects(result)
    finally:
        await lease.release()


def _candidate_effects(result):
    return {**result, "side_effects": {
        "ref_updated": result.get("ref_updated", False),
        "objects_may_remain": result.get("objects_may_remain", False),
    }}


forbid_extra_arguments(mcp)


def main() -> None:
    """Run the loopback MCP server; runtime configuration is validated on import."""
    # Bootstrap sits behind an HTTPS reverse tunnel. The local service itself
    # remains bound to loopback; security checks are opt-in so dynamic Quick
    # Tunnel startup remains backwards compatible.
    security = _transport_security_settings()

    mcp.run(
        transport="streamable-http",
        host="127.0.0.1",
        port=PORT,
        streamable_http_path=MCP_PATH,
        # SSE-capable (SDK default); JSON-only drops notifications/back-channel.
        json_response=False,
        transport_security=security,
    )


if __name__ == "__main__":
    main()
