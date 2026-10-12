"""Generic Herdr discovery, exact resource validation, prompt, read, and turn observation."""


from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import shutil
import signal
import time
from pathlib import Path
from typing import Any

from .workspace_context import WorkspaceAuthorizationError, canonical_git_worktree, validate_git_worktree_identity
from .evidence_target import EvidenceCheckout


HERDR_COMMAND = os.environ.get("BRIDGE_HERDR_BIN", "herdr").strip() or "herdr"
HERDR_ENABLED = os.environ.get("BRIDGE_HERDR_ENABLED", "true").strip().lower() == "true"
MAX_OUTPUT = 2 * 1024 * 1024
MAX_TEXT = 4000
MAX_PROBE_AGENTS = 32
MAX_MANUAL_AGENT_READ_LINES = 400
MAX_MANUAL_AGENT_READ_TEXT = 16 * 1024
MAX_PUBLIC_PID = 2_147_483_647
AGENT_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
RAW_AGENT_KIND_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")

# Screen-manifest detection can fall back to a weak idle/done status while an
# Agent is still executing, and observed fallback gaps reach several seconds,
# so one idle/done transition never settles a turn alone. A settlement
# candidate must present identical status and an identical exact-integer
# state_change_seq across SETTLEMENT_CONFIRM_ATTEMPTS full re-observation
# intervals spaced SETTLEMENT_CONFIRM_SECONDS apart; working evidence, a status
# change, a seq change or a non-exact seq rejects the candidate and re-arms
# observation, and elapsed attempts never force a settlement. Both are module
# attributes so tests inject short intervals (no real sleeps, no client
# polling).
SETTLEMENT_CONFIRM_SECONDS = 3.0
SETTLEMENT_CONFIRM_ATTEMPTS = 2

# User-authorized AGY-specific debounce: every AGY idle/done settlement
# candidate is provisional. Instead of the generic schedule below, an AGY
# candidate must remain identical (same status AND same exact-integer
# state_change_seq) across one full 60-second interval — a single confirming
# re-observation at the end of the interval — before terminal settlement.
# Rejection re-arms observation for the SAME turn exactly like the generic
# schedule, and a later fresh candidate starts a fresh interval. Only
# idle/done settlement is debounced: blocked/needs_attention, continuity loss,
# checkout change and observation/revalidation uncertainty stay immediate.
# Both are module attributes so tests inject short logical intervals (no real
# sleeps, no client polling).
AGY_SETTLEMENT_CONFIRM_SECONDS = 60.0
AGY_SETTLEMENT_CONFIRM_ATTEMPTS = 1

# Read-only retry for an exact transient observation blip. A single empty
# snapshot or unavailable read/process-info can latch a Work while the Agent
# is still working. Only these three codes are retried, from scratch, at most
# twice, about one second apart. The product of attempts and interval is
# capped so extra delay cannot exceed five seconds. Definitive classes are
# not retried. Exhaustion keeps today's needs_attention / observation_unavailable.
# Module attributes so tests inject a zero interval without real sleeps.
TRANSIENT_OBSERVATION_EXTRA_ATTEMPTS = 2
TRANSIENT_OBSERVATION_RETRY_INTERVAL_SECONDS = 1.0
TRANSIENT_OBSERVATION_RETRY_DELAY_CAP_SECONDS = 5.0
_TRANSIENT_OBSERVATION_CODES = frozenset({
    "manual_candidate_read_unavailable",
    "manual_candidate_observation_unavailable",
    "manual_candidate_process_unavailable",
})
_WATCHER_ERROR_CODE_RE = re.compile(r"^[A-Za-z0-9_.-]{1,80}$")


def _transient_observation_retry_budget() -> tuple[int, float]:
    """Extra attempts and per-attempt sleep, with total extra delay <= 5s."""
    raw_attempts = TRANSIENT_OBSERVATION_EXTRA_ATTEMPTS
    if isinstance(raw_attempts, bool) or not isinstance(raw_attempts, int):
        attempts = 2
    else:
        attempts = raw_attempts
    attempts = max(0, min(attempts, 2))
    raw_interval = TRANSIENT_OBSERVATION_RETRY_INTERVAL_SECONDS
    if isinstance(raw_interval, bool) or not isinstance(raw_interval, (int, float)):
        interval = 1.0
    else:
        interval = float(raw_interval)
    if interval != interval or interval < 0 or interval == float("inf"):
        interval = 1.0
    raw_cap = TRANSIENT_OBSERVATION_RETRY_DELAY_CAP_SECONDS
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


def _bounded_watcher_error_code(code: Any) -> str | None:
    if isinstance(code, str) and _WATCHER_ERROR_CODE_RE.fullmatch(code):
        return code
    return None


def _manual_revalidation_failure(exc: HerdrError) -> dict[str, Any]:
    """Existing definitive taxonomy, plus a bounded code and no exception text."""
    if exc.code in {
        "manual_candidate_identity_lost",
        "manual_candidate_continuity_lost",
        "manual_candidate_identity_unavailable",
    }:
        failure: dict[str, Any] = {
            "state": "failed",
            "reason": "candidate_continuity_lost",
            "herdr_status": "continuity_lost",
            "post_state_change_seq": None,
            "post_revision": None,
            "post_candidate": None,
        }
    elif exc.code == "manual_candidate_checkout_changed":
        failure = {
            "state": "needs_attention",
            "reason": "execution_checkout_changed",
            "herdr_status": "unknown",
            "post_state_change_seq": None,
            "post_revision": None,
            "post_candidate": None,
        }
    else:
        reason = (
            "observation_unavailable"
            if exc.code in _TRANSIENT_OBSERVATION_CODES
            else "revalidation_uncertain"
        )
        failure = {
            "state": "needs_attention",
            "reason": reason,
            "herdr_status": "unknown",
            "post_state_change_seq": None,
            "post_revision": None,
            "post_candidate": None,
        }
    bounded = _bounded_watcher_error_code(exc.code)
    if bounded is not None:
        failure["watcher_error_code"] = bounded
    return failure


def _settlement_confirmation_schedule(agent_kind: Any) -> tuple[int, float]:
    """Select the confirmation schedule from the authoritative candidate kind.

    Exactly ``agy`` gets the authorized debounce; every other (or absent) kind
    keeps the generic schedule unchanged.
    """
    if agent_kind == "agy":
        return AGY_SETTLEMENT_CONFIRM_ATTEMPTS, AGY_SETTLEMENT_CONFIRM_SECONDS
    return SETTLEMENT_CONFIRM_ATTEMPTS, SETTLEMENT_CONFIRM_SECONDS


def _is_exact_integer(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


HERDR_QODER_LABEL = "qodercli"

# Qoder's TUI can accept a native prompt (host-acknowledged) yet leave it
# sitting unsubmitted in the composer: a lost Enter keeps the pane idle/done
# with an unadvanced exact state_change_seq. That is an absorbing state — no
# amount of extra waiting activates the turn — so one user-authorized,
# qodercli-scoped activation recovery exists: after the startup observation
# budget expires unadvanced, ONE final exact revalidation gates ONE Enter-only
# nudge through Herdr's send-keys primitive, then ONE fresh bounded activation
# window re-arms for the SAME physical turn. Key name verified against Herdr
# source (config/keybinds.rs: "enter"/"return" -> KeyCode::Enter; every key is
# validated before any write). The nudge never carries task text, never
# re-invokes agent prompt, happens at most once per turn, and is vetoed by
# structured working/blocked/continuity/checkout/observation evidence. No
# screen text, Qoder private logs, or task-text heuristics are consulted.
QODER_ACTIVATION_NUDGE_KEY = "enter"
QODER_ACTIVATION_NUDGE_TIMEOUT_SECONDS = 10.0
ACTIVATION_OBSERVATION_SECONDS = 5.0

HERDR_AGY_LABEL = "agy"

# Proven incident class (2026-09-21 forensics): `herdr agent prompt` acked
# agent_prompted for an AGY pane, yet AGY created no turn and its composer was
# observed empty — the task bytes were silently lost between PTY acceptance and
# TUI input handling. AGY state is screen-detection-only (its session
# integration is identity-only), so an unadvanced idle fallback cannot by
# itself distinguish "never landed" from an invisible turn. Recovery is
# therefore a COLD path only: never on dispatch (normal AGY delivery has no
# screen dependency and no added hot-path Herdr call), only after the existing
# activation observation budget exhausts in the exact absorbing shape (same
# execution, idle/done, exact pre-dispatch seq, unblocked), and only when TWO
# fresh bounded detection reads independently prove the live-validated settled
# EMPTY-composer screen shape below. Then the exact original task is
# re-prompted through the same native primitive ONCE, with a fresh bounded
# window; never Enter, never a third prompt. Any uncertainty — screen shape,
# seq/status movement, exclusivity, transport — declines to the existing
# needs_attention path. If AGY's screen shape changes, recovery fails closed
# and normal availability is unaffected.
AGY_COMPOSER_RECOVERY_READ_LINES = 40
AGY_COMPOSER_RECOVERY_READ_TIMEOUT_SECONDS = 10.0
AGY_COMPOSER_RECOVERY_READ_INTERVAL_SECONDS = 0.3
AGY_COMPOSER_REPROMPT_TIMEOUT_SECONDS = 30.0
AGY_RECOVERY_EXHAUSTED_REASON = "agy_composer_recovery_exhausted"
AGY_RECOVERY_REPROMPT_UNCERTAIN_REASON = "agy_composer_recovery_reprompt_uncertain"
# The validated settled AGY shape: a bare `>` composer line, a box-drawing
# separator, and at least one footer anchor; queued/working/permission renderings
# veto. Recovery-only parser — deliberately not a screen-detection framework.
AGY_COMPOSER_LINE_RE = re.compile(r"\s*>\s*")
AGY_COMPOSER_SEPARATOR_RE = re.compile(r"[\u2500-\u257F]{8,}\s*")
AGY_COMPOSER_FOOTER_ANCHORS = ("Context:", "Gemini", "? for shortcuts")
AGY_COMPOSER_VETO_NEEDLES = (
    "Press up to edit queued messages",
    "esc to cancel",
    "requesting permission for:",
    "do you want to proceed?",
)


def _agy_empty_composer_shape(text: Any) -> bool:
    """Recovery-only proof of the validated settled empty-composer shape."""
    if not isinstance(text, str):
        return False
    stripped = text.strip()
    if not stripped:
        return False
    if any(needle in stripped for needle in AGY_COMPOSER_VETO_NEEDLES):
        return False
    lines = stripped.splitlines()
    return (
        any(AGY_COMPOSER_LINE_RE.fullmatch(line) for line in lines)
        and any(AGY_COMPOSER_SEPARATOR_RE.fullmatch(line) for line in lines)
        and any(anchor in stripped for anchor in AGY_COMPOSER_FOOTER_ANCHORS)
    )


class HerdrError(RuntimeError):
    """A bounded failure from the optional Herdr backend."""

    def __init__(self, message: str, code: str | None = None):
        super().__init__(message)
        self.code = code


DISCOVERY_REJECTION_CODES = (
    "snapshot_malformed", "snapshot_duplicate", "identity_kind", "identity_cwd_git",
    "identity_name", "identity_locus", "identity_session",
    "candidate_unavailable", "projection_invalid",
)
MAX_REJECTION_DETAILS = 8


class _DiscoveryRejected(HerdrError):
    def __init__(self, reason: str):
        super().__init__("candidate rejected", code=reason)


class _OutsideProject(HerdrError):
    """Valid but different Git identity; discovery must still validate the roster entry."""

    def __init__(self, root: Path):
        super().__init__("Herdr manual agent workspace does not match the selected project")
        self.root = root


class HerdrUnavailable(HerdrError):
    pass


class ManualAgentPromptNotReady(HerdrError):
    """The exact manual agent is not ready for an ordinary native turn."""


def _truncate(value: Any, limit: int = MAX_TEXT) -> str:
    text = "" if value is None else str(value)
    return text if len(text) <= limit else text[:limit] + f"\n...[truncated {len(text) - limit} chars]"


def _public_int(value: Any) -> int | None:
    if (
        isinstance(value, int)
        and not isinstance(value, bool)
        and 0 <= value <= MAX_PUBLIC_PID
    ):
        return value
    return None


_HERDR_STATUS_VALUES = frozenset({"idle", "working", "done", "blocked", "unknown"})


def _public_herdr_status(value: Any) -> str:
    return value if isinstance(value, str) and value in _HERDR_STATUS_VALUES else "unknown"


def available() -> bool:
    return HERDR_ENABLED and shutil.which(HERDR_COMMAND) is not None


def _id(value: Any, label: str) -> str:
    if not isinstance(value, str) or not IDENTIFIER_RE.fullmatch(value):
        raise HerdrError(f"Herdr returned an invalid {label}")
    return value


class HerdrBackend:

    def __init__(
        self,
        root: Path,
        stream_limit: int = 8 * 1024 * 1024,
    ):
        self.root = root.resolve()
        self.stream_limit = stream_limit

    async def _exec_raw(
        self, *args: str, timeout: float | None = 30
    ) -> tuple[str, str]:
        if not available():
            raise HerdrUnavailable(f"Herdr executable {HERDR_COMMAND!r} was not found")
        proc: asyncio.subprocess.Process | None = None
        try:
            proc = await asyncio.create_subprocess_exec(
                HERDR_COMMAND, *args, cwd=str(self.root),
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
                limit=self.stream_limit, start_new_session=True,
            )
            if timeout is not None:
                stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
            else:
                stdout, stderr = await proc.communicate()
        except asyncio.CancelledError:
            if proc is not None:
                await self._terminate(proc)
            raise
        except asyncio.TimeoutError as exc:
            if proc is not None:
                await self._terminate(proc)
            raise TimeoutError(f"Herdr {args[0] if args else 'command'} timed out") from exc
        except OSError as exc:
            raise HerdrError(f"Herdr command could not start: {exc}") from exc
        if len(stdout) > MAX_OUTPUT:
            raise HerdrError("Herdr command output exceeded its safety limit")
        raw_stdout = stdout.decode(errors="replace")
        raw_stderr = stderr.decode(errors="replace")
        if proc.returncode != 0:
            detail = _truncate(raw_stderr.strip(), 2000)
            code = None
            try:
                error_response = json.loads(detail)
                error = error_response.get("error") if isinstance(error_response, dict) else None
                code = error.get("code") if isinstance(error, dict) else None
            except json.JSONDecodeError:
                pass
            raise HerdrError(f"Herdr command failed{': ' + detail if detail else ''}", code=code)
        return raw_stdout, raw_stderr

    async def _call(
        self, *args: str, timeout: float | None = 30, allow_empty: bool = False
    ) -> dict[str, Any]:
        raw_stdout, _ = await self._exec_raw(*args, timeout=timeout)
        if not raw_stdout.strip() and allow_empty:
            return {}
        try:
            response = json.loads(raw_stdout)
        except json.JSONDecodeError as exc:
            raise HerdrError("Herdr returned malformed JSON") from exc
        if not isinstance(response, dict):
            raise HerdrError("Herdr returned a malformed response")
        if response.get("error") is not None:
            error = response["error"]
            code = error.get("code") if isinstance(error, dict) else None
            raise HerdrError("Herdr API error: " + _truncate(json.dumps(error), 2000), code=code)
        if not isinstance(response.get("result"), dict):
            raise HerdrError("Herdr returned a malformed response")
        return response["result"]

    async def _call_text(
        self, *args: str, timeout: float | None = 30
    ) -> str:
        raw_stdout, _ = await self._exec_raw(*args, timeout=timeout)
        return raw_stdout

    async def _terminate(self, proc: asyncio.subprocess.Process) -> None:
        if proc.returncode is not None:
            return
        try:
            os.killpg(proc.pid, signal.SIGTERM)
        except ProcessLookupError:
            return
        try:
            await asyncio.wait_for(proc.wait(), timeout=1)
        except asyncio.TimeoutError:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            await proc.wait()


    @staticmethod
    def _manual_agent_session(agent: dict[str, Any]) -> dict[str, str] | None:
        session = agent.get("agent_session")
        if session is None:
            return None
        if not isinstance(session, dict):
            raise HerdrError("Herdr manual agent session metadata was malformed")
        kind = session.get("kind")
        value = session.get("value")
        if kind not in {"id", "path"} or not isinstance(value, str) or not value:
            raise HerdrError("Herdr manual agent session metadata was malformed")
        if len(value) > MAX_OUTPUT:
            raise HerdrError("Herdr manual agent session metadata exceeded its safety limit")
        return {"kind": kind, "value": value}

    @staticmethod
    def _manual_workspace_cwd(value: Any, execution_root: Path, source: str) -> str | None:
        """Accept absent CWD evidence, but reject disagreement with live execution."""
        if value is None:
            return None
        if not isinstance(value, str) or not value or len(value) > MAX_OUTPUT:
            raise HerdrError(f"Herdr manual agent {source} was malformed")
        if value != str(execution_root):
            raise HerdrError(
                f"Herdr manual agent {source} does not match the live agent cwd",
            )
        return value

    @staticmethod
    def _manual_execution_cwd(value: Any, root: Path, placement_cache=None) -> Path:
        """Accept the registered root or a same-common-Git linked worktree."""
        if not isinstance(value, str) or not value or len(value) > MAX_OUTPUT:
            raise HerdrError("Herdr manual agent cwd was malformed")
        if value == str(root):
            return root
        try:
            registered_root, registered_git = canonical_git_worktree(root)
            execution_root, execution_git = canonical_git_worktree(value)
        except WorkspaceAuthorizationError as exc:
            raise HerdrError(
                "Herdr manual agent workspace does not match the selected project"
            ) from exc
        registered_common = (
            registered_git.git_common_dir,
            registered_git.git_common_device,
            registered_git.git_common_inode,
        )
        execution_common = (
            execution_git.git_common_dir,
            execution_git.git_common_device,
            execution_git.git_common_inode,
        )
        if registered_root != root or str(execution_root) != value or execution_git.bare:
            raise HerdrError("Herdr manual agent workspace does not match the selected project")
        if execution_common != registered_common:
            # Path-only or inode-only disagreement can be replacement/alias evidence,
            # not proof of an unrelated project. Git validation failure never gets here.
            if (execution_common[0] != registered_common[0]
                    and execution_common[1:] != registered_common[1:]):
                raise _OutsideProject(execution_root)
            raise HerdrError("Herdr manual agent Git identity is uncertain")
        if placement_cache is not None:
            # Export already-validated facts; no extra Git reads for display.
            placement_cache.setdefault(value, EvidenceCheckout(execution_root, execution_git))
        return execution_root

    @staticmethod
    def _manual_agent_identity(agent: dict[str, Any], root: Path, placement_cache=None) -> dict[str, Any]:
        stage = "identity_kind"
        try:
            raw_kind = agent.get("agent")
            if isinstance(raw_kind, str) and RAW_AGENT_KIND_RE.fullmatch(raw_kind):
                kind = raw_kind
            else:
                raise HerdrError("Herdr manual agent kind was malformed")
            stage = "identity_cwd_git"
            reported_root = HerdrBackend._manual_execution_cwd(agent.get("cwd"), root, placement_cache)
            foreground_value = agent.get("foreground_cwd")
            execution_root = (
                reported_root
                if foreground_value is None
                else HerdrBackend._manual_execution_cwd(foreground_value, root, placement_cache)
            )
            stage = "identity_name"
            name = agent.get("name")
            if name is not None and (
                not isinstance(name, str) or not AGENT_NAME_RE.fullmatch(name)
            ):
                raise HerdrError("Herdr manual agent name was malformed")
            foreground_cwd = HerdrBackend._manual_workspace_cwd(
                agent.get("foreground_cwd"), execution_root, "foreground cwd"
            )
            stage = "identity_locus"
            locus = {key: _id(agent.get(key), key) for key in
                     ("workspace_id", "tab_id", "pane_id", "terminal_id")}
            stage = "identity_session"
            session = HerdrBackend._manual_agent_session(agent)
            return {
                "agent_kind": kind,
                "agent_name": name,
                "workspace_id": locus["workspace_id"],
                "tab_id": locus["tab_id"],
                "pane_id": locus["pane_id"],
                "terminal_id": locus["terminal_id"],
                "cwd": str(execution_root),
                "foreground_cwd": foreground_cwd,
                "agent_session": session,
            }
        except _OutsideProject:
            raise
        except HerdrError as exc:
            raise _DiscoveryRejected(stage) from exc

    @staticmethod
    def _manual_process_arguments(process: dict[str, Any]) -> tuple[str, ...] | None:
        for field in ("argv", "cmdline"):
            value = process.get(field)
            if isinstance(value, list) and value and all(
                isinstance(item, str) and item for item in value
            ):
                return tuple(value)
        command = process.get("cmdline")
        if isinstance(command, str) and command:
            return (command,)
        return None

    @staticmethod
    def _manual_process_evidence(
        process_info: Any,
        pane_id: str,
        root: Path,
    ) -> dict[str, Any]:
        def unavailable(
            reason: str | None = None,
            *,
            unsafe: bool = False,
        ) -> dict[str, Any]:
            return {
                "available": False,
                "unsafe": unsafe,
                "fingerprint": None,
                "public": {
                    "available": False,
                    "reason": reason,
                    "pane_id": None,
                    "foreground_process_group_id": None,
                    "foreground_cwd": None,
                    "processes": [],
                },
            }

        if not isinstance(process_info, dict) or process_info.get("pane_id") != pane_id:
            return unavailable()
        process_group_id = _public_int(process_info.get("foreground_process_group_id"))
        processes = process_info.get("foreground_processes")
        if process_group_id is None or not isinstance(processes, list) or not processes:
            return unavailable()
        def cwd_observation(value: Any) -> tuple[str | None, str]:
            if value is None:
                return None, "absent"
            if not isinstance(value, str) or not value or len(value) > MAX_OUTPUT:
                raise HerdrError("Herdr foreground process cwd was malformed")
            if value == str(root):
                return value, "matches_execution"
            return None, "differs_execution"

        # Herdr may detect an Agent child of a wrapper. Neither leader nor aggregate
        # CWD identifies that child or grants a different directory project authority.
        foreground_cwd, foreground_relation = cwd_observation(process_info.get("foreground_cwd"))
        if len(processes) > MAX_PROBE_AGENTS:
            return unavailable(
                "foreground_process_count_exceeds_safe_limit",
                unsafe=True,
            )
        exact_processes: list[tuple[int, tuple[str, ...], str | None]] = []
        public_processes: list[dict[str, Any]] = []
        seen_pids: set[int] = set()
        for process in processes:
            if not isinstance(process, dict):
                return unavailable()
            pid = _public_int(process.get("pid"))
            arguments = HerdrBackend._manual_process_arguments(process)
            if pid is None or arguments is None or pid in seen_pids:
                return unavailable()
            seen_pids.add(pid)
            cwd, relation = cwd_observation(process.get("cwd"))
            exact_processes.append((pid, arguments, cwd))
            public_processes.append({
                "pid": pid,
                "argv0": _truncate(Path(arguments[0].split(maxsplit=1)[0]).name, 128),
                "argc": len(arguments),
                "cwd": _truncate(cwd, 400) if isinstance(cwd, str) else None,
                "cwd_relation": relation,
            })
        public_processes.sort(key=lambda item: item["pid"])
        leader_processes = [p for p in exact_processes if p[0] == process_group_id]
        if len(leader_processes) != 1:
            return unavailable("foreground_process_group_leader_unavailable")
        leader_process = leader_processes[0]
        fingerprint_value = {
            "process_group_id": process_group_id,
            "leader": {
                "pid": leader_process[0],
                "argv": list(leader_process[1]),
            },
        }
        fingerprint = hashlib.sha256(
            json.dumps(fingerprint_value, separators=(",", ":"), sort_keys=True).encode()
        ).hexdigest()[:32]
        return {
            "available": True,
            "unsafe": False,
            "fingerprint": fingerprint_value,
            "public": {
                "available": True,
                "reason": None,
                "fingerprint": fingerprint,
                "pane_id": pane_id,
                "foreground_process_group_id": process_group_id,
                "foreground_cwd": _truncate(foreground_cwd, 400)
                if isinstance(foreground_cwd, str) else None,
                "foreground_cwd_relation": foreground_relation,
                "processes": public_processes,
            },
        }

    async def _manual_candidate_from_agent(self, agent: dict[str, Any], *, placement_cache=None) -> dict[str, Any]:
        identity = self._manual_agent_identity(agent, self.root, placement_cache)
        placement_checkout = (placement_cache or {}).get(identity["cwd"])
        process_error: str | None = None
        try:
            response = await self._call(
                "pane", "process-info", "--pane", identity["pane_id"], timeout=10
            )
        except Exception as exc:
            process = self._manual_process_evidence(
                None, identity["pane_id"], Path(identity["cwd"])
            )
            process_error = _truncate(exc, 400)
        else:
            process = self._manual_process_evidence(
                response.get("process_info"), identity["pane_id"], Path(identity["cwd"])
            )
        has_native_session = identity["agent_session"] is not None
        if has_native_session and process["available"]:
            continuity_level = "native_session_and_instance"
        elif has_native_session:
            continuity_level = "native_session_and_pane"
        elif process["available"]:
            continuity_level = "pane_process"
        else:
            continuity_level = "pane_only"
        read_status = "available" if (
            continuity_level != "pane_only" and not process["unsafe"]
        ) else "unavailable"
        continuity_identity = {
            k: v for k, v in identity.items() if k != "agent_session"
        }
        resource_identity = {
            "workspace_scope": str(self.root),
            **{
                k: identity.get(k)
                for k in (
                    "agent_kind", "agent_name", "workspace_id", "tab_id",
                    "pane_id", "terminal_id",
                )
            },
        }
        continuity_key = {
            "identity": continuity_identity,
            "process": process["fingerprint"],
        }
        candidate = {
            "_placement_checkout": placement_checkout,
            "identity": identity,
            "herdr_status": _public_herdr_status(agent.get("agent_status")),
            "_raw_state_change_seq": agent.get("state_change_seq"),
            "_raw_revision": agent.get("revision"),
            "process": process,
            "continuity": {
                "level": continuity_level,
                "status": "established_process_local"
                if read_status == "available" else "unknown",
                "read_status": read_status,
            },
            "candidate_key": hashlib.sha256(
                json.dumps(continuity_key, separators=(",", ":"), sort_keys=True).encode()
            ).hexdigest(),
            "resource_key": hashlib.sha256(
                json.dumps(resource_identity, separators=(",", ":"), sort_keys=True).encode()
            ).hexdigest(),
        }
        if process_error is not None:
            candidate["process_error"] = process_error
        candidate["public"] = self._manual_public_candidate(candidate)
        return candidate

    @staticmethod
    def manual_prompt_capability(_candidate: dict[str, Any] | None = None) -> dict[str, str]:
        """Describe the native Herdr prompt transport without overclaiming guards."""
        return {
            "mode": "native_herdr",
            "status": "available",
            "target": "exact_pane",
            "identity_guard": "herdr_native_preflight",
            "delivery": "request_accepted_or_queued",
            "completion": "unattributed",
            "result": "unattributed",
            "retry": "none",
        }

    @staticmethod
    def _manual_public_candidate(candidate: dict[str, Any]) -> dict[str, Any]:
        identity = candidate["identity"]
        session = identity.get("agent_session")
        return {
            "agent_kind": identity["agent_kind"],
            "agent_name": identity.get("agent_name"),
            "workspace_id": identity["workspace_id"],
            "tab_id": identity["tab_id"],
            "pane_id": identity["pane_id"],
            "terminal_id": identity["terminal_id"],
            "cwd": identity["cwd"],
            "foreground_cwd": identity.get("foreground_cwd"),
            "agent_session": (
                {"kind": session["kind"], "value": _truncate(session["value"], 400)}
                if isinstance(session, dict) else None
            ),
            "herdr_status": candidate["herdr_status"],
            "foreground_process": candidate["process"]["public"],
            "continuity": dict(candidate["continuity"]),
            "prompt_transport": HerdrBackend.manual_prompt_capability(candidate),
        }


    def _rejected_local_detail(self, agent: Any, reason: str) -> dict[str, str] | None:
        if not isinstance(agent, dict):
            return None
        try:
            self._manual_execution_cwd(agent.get("cwd"), self.root)
            if agent.get("foreground_cwd") is not None:
                self._manual_execution_cwd(agent["foreground_cwd"], self.root)
            for key in ("workspace_id", "tab_id", "pane_id", "terminal_id"):
                _id(agent.get(key), key)
        except HerdrError:
            return None
        kind = agent.get("agent")
        if not isinstance(kind, str) or not RAW_AGENT_KIND_RE.fullmatch(kind):
            return None
        tab = re.fullmatch(r"t([0-9]{1,6})", agent["tab_id"].rsplit(":", 1)[-1])
        pane = re.fullmatch(r"p([0-9]{1,6})", agent["pane_id"].rsplit(":", 1)[-1])
        if tab is None or pane is None:
            return None
        return {"stage": reason.split("_", 1)[0], "reason": reason,
                "kind": kind, "hint": f"tab {tab[1]} / pane {pane[1]}"}

    async def manual_agent_candidates(self) -> dict[str, Any]:
        """Discover raw Herdr agents in this exact backend workspace only."""
        snapshot_result = await self._call("api", "snapshot", timeout=10)
        snapshot = snapshot_result.get("snapshot")
        if not isinstance(snapshot, dict):
            raise HerdrError("Herdr manual-agent snapshot was malformed")
        agents = snapshot.get("agents")
        if not isinstance(agents, list):
            raise HerdrError("Herdr manual-agent snapshot has malformed agents")
        eligible_agents = [agent for agent in agents if isinstance(agent, dict)]
        candidates: list[dict[str, Any]] = []
        placement_cache = {}
        reasons = {"out_of_project": 0, "invalid_or_unavailable": len(agents) - len(eligible_agents),
                   "truncated": max(0, len(eligible_agents) - MAX_PROBE_AGENTS)}
        diagnostics = {"status": "available", "reason_counts": {
            code: 0 for code in DISCOVERY_REJECTION_CODES}, "details": [],
            "unlocalized_count": len(agents) - len(eligible_agents),
            "omitted_local_count": 0, "truncated_candidates": reasons["truncated"]}
        diagnostics["reason_counts"]["snapshot_malformed"] = len(agents) - len(eligible_agents)

        def reject(agent, code):
            if code not in DISCOVERY_REJECTION_CODES:
                code = "candidate_unavailable"
            reasons["invalid_or_unavailable"] += 1
            diagnostics["reason_counts"][code] += 1
            detail = None if code == "snapshot_duplicate" else self._rejected_local_detail(agent, code)
            if detail is None:
                diagnostics["unlocalized_count"] += 1
            elif len(diagnostics["details"]) < MAX_REJECTION_DETAILS:
                diagnostics["details"].append(detail)
            else:
                diagnostics["omitted_local_count"] += 1

        # Snapshot locus ambiguity must not be hidden as ordinary project filtering.
        def locus(agent):
            values = tuple(agent.get(k) for k in ("workspace_id", "tab_id", "pane_id", "terminal_id"))
            return values if all(isinstance(v, str) for v in values) else None
        loci = {}
        for agent in eligible_agents:
            key = locus(agent)
            if key is not None:
                loci[key] = loci.get(key, 0) + 1
        for agent in eligible_agents[:MAX_PROBE_AGENTS]:
            if loci.get(locus(agent), 0) > 1:
                reject(agent, "snapshot_duplicate")
                continue
            try:
                candidates.append(await self._manual_candidate_from_agent(agent, placement_cache=placement_cache))
            except _OutsideProject as exc:
                try:
                    # Exclude only consistent, identifiable snapshot entries. A current
                    # project cwd with foreign foreground cwd is a contradiction.
                    if agent.get("cwd") != str(exc.root):
                        raise HerdrError("candidate cwd evidence disagrees")
                    self._manual_agent_identity(agent, exc.root)
                except HerdrError as error:
                    reject(agent, error.code if isinstance(error, _DiscoveryRejected) else "identity_cwd_git")
                else:
                    reasons["out_of_project"] += 1
            except HerdrError as error:
                reject(agent, error.code)
        tabs = [t for t in snapshot.get("tabs", []) if isinstance(t, dict)]
        return {
            "candidates": candidates,
            "candidate_count": len(candidates),
            "candidates_truncated": len(eligible_agents) > MAX_PROBE_AGENTS,
            "skipped_count": reasons["invalid_or_unavailable"],
            "coverage_counts": reasons,
            "rejection_diagnostics": diagnostics,
            "tabs": tabs,
            "observed_at": time.time(),
        }

    async def _revalidate_manual_agent_resource_candidate(
        self,
        expected: dict[str, Any],
    ) -> dict[str, Any]:
        """Resolve the same exact Agent resource without binding old execution evidence."""
        if not isinstance(expected, dict) or not isinstance(expected.get("identity"), dict):
            raise HerdrError("manual agent candidate identity is unavailable", code="manual_candidate_identity_unavailable")
        exp_identity = expected["identity"]

        snapshot_result = await self._call("api", "snapshot", timeout=10)
        snapshot = snapshot_result.get("snapshot")
        agents = snapshot.get("agents") if isinstance(snapshot, dict) else None
        if not isinstance(agents, list):
            raise HerdrError("Herdr manual-agent snapshot was malformed", code="manual_candidate_snapshot_malformed")
        locus_keys = (
            "agent_kind", "agent_name", "workspace_id", "tab_id",
            "pane_id", "terminal_id",
        )
        locus_matches: list[tuple[dict[str, Any], dict[str, Any]]] = []
        malformed_same_locus = False
        physical_locus_matches = 0
        physical_locus_keys = (
            "workspace_id", "tab_id", "pane_id", "terminal_id",
        )
        for agent in agents:
            if not isinstance(agent, dict):
                continue
            same_physical_locus = all(
                agent.get(k) == exp_identity.get(k)
                for k in physical_locus_keys
            )
            if same_physical_locus:
                physical_locus_matches += 1
            raw_kind = agent.get("agent")
            raw_name = agent.get("name")
            malformed_kind_or_name = (
                (
                    not isinstance(raw_kind, str)
                    or not RAW_AGENT_KIND_RE.fullmatch(raw_kind)
                )
            ) or (
                raw_name is not None
                and (
                    not isinstance(raw_name, str)
                    or not AGENT_NAME_RE.fullmatch(raw_name)
                )
            )
            if malformed_kind_or_name:
                if same_physical_locus:
                    malformed_same_locus = True
                continue
            try:
                live_identity = self._manual_agent_identity(agent, self.root)
                if all(
                    live_identity.get(k) == exp_identity.get(k)
                    for k in locus_keys
                ):
                    locus_matches.append((agent, live_identity))
            except HerdrError:
                continue
            except Exception:
                continue

        if malformed_same_locus or physical_locus_matches > 1:
            raise HerdrError(
                "manual agent identity is ambiguous at the expected physical locus",
                code="manual_candidate_identity_ambiguous",
            )
        if not locus_matches:
            raise HerdrError(
                "no agent at expected locus in snapshot",
                code="manual_candidate_observation_unavailable",
            )
        if len(locus_matches) > 1:
            raise HerdrError(
                "manual agent identity is ambiguous across multiple candidates",
                code="manual_candidate_identity_ambiguous",
            )

        agent = locus_matches[0][0]
        return await self._manual_candidate_from_agent(agent)

    async def revalidate_manual_agent_resource(
        self,
        expected: dict[str, Any],
    ) -> dict[str, Any]:
        """Refresh one exact Agent resource before a new Work is reserved.

        Resource identity is the selected workspace plus exact Herdr
        workspace/tab/pane/terminal and raw agent kind/name. Native session and
        foreground-process evidence describe the current execution, not the
        resource, so they may refresh here. Missing or ambiguous resource or
        current process evidence still fails closed.
        """
        current = await self._revalidate_manual_agent_resource_candidate(expected)
        process = current.get("process")
        if (
            not isinstance(process, dict)
            or process.get("available") is not True
            or process.get("fingerprint") is None
        ):
            raise HerdrError(
                "manual agent foreground process evidence is unavailable or malformed",
                code="manual_candidate_process_unavailable",
            )
        return current

    async def revalidate_manual_agent(
        self,
        expected: dict[str, Any],
        *,
        allow_session_promotion: bool | None = None,
    ) -> dict[str, Any]:
        """Require the same Agent resource and dispatched execution evidence."""
        current = await self._revalidate_manual_agent_resource_candidate(expected)
        if current["identity"]["cwd"] != expected["identity"]["cwd"]:
            raise HerdrError("selected execution checkout changed",
                             code="manual_candidate_checkout_changed")
        # The dispatch gate already captured this object; do not recapture new rights.
        checkout = expected.get("_work_checkout")
        if isinstance(checkout, EvidenceCheckout):
            try:
                validate_git_worktree_identity(checkout.root, checkout.git)
            except WorkspaceAuthorizationError as exc:
                raise HerdrError("frozen execution checkout identity changed",
                                 code="manual_candidate_checkout_changed") from exc
            current["_work_checkout"] = checkout

        if current.get("candidate_key") != expected.get("candidate_key"):
            exp_proc = expected.get("process") if isinstance(expected.get("process"), dict) else {}
            curr_proc = current.get("process") if isinstance(current.get("process"), dict) else {}
            exp_avail = exp_proc.get("available") is True and exp_proc.get("fingerprint") is not None
            curr_avail = curr_proc.get("available") is True and curr_proc.get("fingerprint") is not None

            if exp_avail and curr_avail:
                exp_fp = exp_proc.get("fingerprint")
                curr_fp = curr_proc.get("fingerprint")
                if exp_fp != curr_fp:
                    raise HerdrError(
                        "manual agent foreground process continuity changed",
                        code="manual_candidate_continuity_lost",
                    )
            else:
                raise HerdrError(
                    "manual agent foreground process evidence is unavailable or malformed",
                    code="manual_candidate_process_unavailable",
                )
        if current["continuity"]["read_status"] != "available":
            raise HerdrError(
                "manual agent continuity is unavailable",
                code="manual_candidate_read_unavailable",
            )
        return current

    @staticmethod
    def _manual_read_text(response: dict[str, Any]) -> str:
        for value in (
            response.get("text"), response.get("output"), response.get("content"),
            response.get("data"),
        ):
            if isinstance(value, str):
                return value
        for nested_key in ("read", "pane", "agent"):
            nested = response.get(nested_key)
            if isinstance(nested, dict):
                for key in ("text", "output", "content", "data"):
                    if isinstance(nested.get(key), str):
                        return nested[key]
        raise HerdrError("Herdr manual-agent read returned no bounded text output")

    async def read_manual_agent(
        self,
        expected: dict[str, Any],
        *,
        limit: int,
        allow_session_promotion: bool = False,
    ) -> dict[str, Any]:
        if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= MAX_MANUAL_AGENT_READ_LINES:
            raise ValueError(f"limit must be between 1 and {MAX_MANUAL_AGENT_READ_LINES}")
        current = await self.revalidate_manual_agent_resource(expected)
        raw_result = await self._call_text(
            "pane", "read", current["identity"]["pane_id"],
            "--source", "recent-unwrapped", "--lines", str(limit),
            "--format", "text", timeout=10,
        )
        text = raw_result if isinstance(raw_result, str) else self._manual_read_text(raw_result)
        return {
            "candidate": current,
            "text": _truncate(text, MAX_MANUAL_AGENT_READ_TEXT),
            "chars": len(text),
            "truncated": len(text) > MAX_MANUAL_AGENT_READ_TEXT,
            "source": "recent-unwrapped",
        }

    @staticmethod
    def _prompt_ack_matches(receipt: Any, expected: dict[str, Any]) -> bool:
        """Recognize only a typed receipt identifying the entire stable resource.

        Session/status/sequence are not permanent identity. Unknown native versions
        or missing identity remain unknown; this never gates the watcher.
        """
        if not isinstance(receipt, dict) or receipt.get("type") != "agent_prompted":
            return False
        agent = receipt.get("agent")
        if isinstance(agent, str):
            agent = receipt  # A flat receipt must still identify every stable field.
        identity = expected.get("identity")
        if not isinstance(agent, dict) or not isinstance(identity, dict):
            return False
        fields = {"agent": "agent_kind", "name": "agent_name",
                  "workspace_id": "workspace_id", "tab_id": "tab_id",
                  "pane_id": "pane_id", "terminal_id": "terminal_id"}
        for raw, key in fields.items():
            if key not in identity:
                return False
            if raw == "name" and raw not in agent and identity[key] is None:
                value = None  # Native serde omits an unnamed Agent's optional name.
            elif raw in agent:
                value = agent[raw]
            else:
                return False
            if value != identity[key]:
                return False
            if key != "agent_name" and (not isinstance(value, str) or not value):
                return False
            # Conflicting duplicated identity, when supplied, is not acknowledgement.
            if raw != "agent" and raw in receipt and receipt[raw] != identity[key]:
                return False
        for fields_source in (receipt, agent):
            for key in fields.values():
                if key in fields_source and fields_source[key] != identity[key]:
                    return False
            if "kind" in fields_source and fields_source["kind"] != identity["agent_kind"]:
                return False
        return True

    async def _agy_detection_read(self, pane_id: str) -> str | None:
        """One bounded read-only `agent read --source detection` observation.

        Returns the detection text, or None on any transport failure or empty
        output — recovery declines on None and never retries here.
        """
        try:
            raw_result = await self._call_text(
                "agent", "read", pane_id,
                "--source", "detection",
                "--lines", str(AGY_COMPOSER_RECOVERY_READ_LINES),
                "--format", "text",
                timeout=AGY_COMPOSER_RECOVERY_READ_TIMEOUT_SECONDS,
            )
        except Exception:
            return None
        if isinstance(raw_result, str):
            text = raw_result
        elif isinstance(raw_result, dict):
            try:
                text = self._manual_read_text(raw_result)
            except HerdrError:
                return None
        else:
            return None
        return text.strip() or None

    async def prompt_manual_agent(
        self,
        expected: dict[str, Any],
        task: str,
        submission_evidence: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Submit once, preserving receipt evidence without inferring task execution."""
        evidence = submission_evidence if submission_evidence is not None else {}
        evidence.update(state="not_attempted", mutation_possible=False,
                        proves="no_input_attempted", native_error_code=None)
        if not isinstance(task, str) or not task.strip():
            raise ValueError("task must be a non-empty string")
        status = expected.get("herdr_status")
        if status not in {"idle", "done"}:
            raise ManualAgentPromptNotReady(
                "manual agent status is not suitable for an ordinary turn",
                code="manual_agent_prompt_not_ready",
            )
        identity = expected.get("identity")
        pane_id = identity.get("pane_id") if isinstance(identity, dict) else None
        if not isinstance(pane_id, str) or not pane_id:
            raise HerdrError(
                "manual agent exact pane identity is unavailable",
                code="manual_agent_pane_unavailable",
            )
        # Publish uncertainty before entering the non-idempotent host call.
        evidence.update(state="delivery_unknown", mutation_possible=True,
                        proves="delivery_unknown")
        try:
            receipt = await self._call("agent", "prompt", pane_id, task, timeout=30)
        except HerdrError as exc:
            code = exc.code
            if isinstance(code, str) and re.fullmatch(r"[A-Za-z0-9_.-]{1,80}", code):
                evidence["native_error_code"] = code
            raise
        if self._prompt_ack_matches(receipt, expected):
            evidence.update(state="native_acknowledged", proves="host_accepted_or_queued_only")
        return {
            **self.manual_prompt_capability(expected),
            "status": "native_response_received",
            "submission_evidence": evidence,
        }

    async def watch_manual_agent_turn(
        self,
        expected: dict[str, Any],
        pre_seq: Any,
        pre_rev: Any,
        *,
        recovery: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Watch a submitted turn; attach the AGY recovery audit marker if set.

        ``recovery`` is an optional in-memory seam for the AGY cold-path
        composer recovery only: ``{"task": <exact original task text>,
        "exclusivity_clear": <sync callable -> bool>}``. The task text is held
        only for this same-Work recovery and is never persisted to receipts,
        handoff entries, or logs.
        """
        audit: dict[str, Any] = {}
        result = await self._watch_manual_agent_turn(
            expected, pre_seq, pre_rev, recovery=recovery, audit=audit)
        if audit.get("agy_recovery_reprompt") is True and isinstance(result, dict):
            result = dict(result, agy_recovery_reprompt=True)
        return result

    async def _watch_manual_agent_turn(
        self,
        expected: dict[str, Any],
        pre_seq: Any,
        pre_rev: Any,
        *,
        recovery: dict[str, Any] | None,
        audit: dict[str, Any],
    ) -> dict[str, Any]:
        """Watch a submitted turn using Herdr native agent wait until settled or blocked.

        Transition proof is Herdr-native ``state_change_seq`` advancement only
        (``post_seq > pre_seq`` on exact integers).  Herdr increments this
        per-terminal sequence exactly when the pane's effective agent state
        changes, and Herdr's own ``agent prompt --wait`` accepts any status
        with ``state_change_seq`` past the post-submit baseline as the prompt
        effect, timing out as prompt-stalled otherwise.  The pane ``revision``
        field is a terminal title/metadata revision, not a turn signal, so it
        is reported as a diagnostic only and is never required for proof
        (agent kinds such as AGY keep it constant across turns).

        Finite state machine:
        1. Immediate exact-revalidation against original candidate continuity.
        2. If blocked -> needs_attention (agent_blocked). If idle/done with seq advancement ->
           bounded settlement confirmation (below); a rejected candidate proceeds to the
           settled barrier, a fully stable candidate settles.
        3. If working -> ONE indefinite settled barrier at a time (--until idle --until done
           --until blocked, timeout=None). A confirmation candidate that is rejected
           re-arms the same barrier for the same turn; no terminal receipt is frozen.
        4. Unadvanced idle/done uses level waits excluding its current stale status,
           revalidating on every wake/expiry under ONE five-second observation budget.
           Budget exhaustion means outcome unproven, not submission failure or an
           Agent-start SLA. Revalidation, OS work and cleanup are not a hard 5s bound.
           For kind "qodercli" only, one exhausted unadvanced budget first passes
           through the bounded composer-nudge recovery below; for kind "agy" only,
           through the bounded empty-composer reprompt recovery — each instead of
           immediate attention.
        5. Observation/transport errors return distinct attention; only native status
           timeout is ordinary expiry. The exact codes
           manual_candidate_read_unavailable, manual_candidate_observation_unavailable
           and manual_candidate_process_unavailable are revalidated from scratch
           at most TRANSIENT_OBSERVATION_EXTRA_ATTEMPTS extra times, spaced by
           TRANSIENT_OBSERVATION_RETRY_INTERVAL_SECONDS, with total extra delay
           capped at TRANSIENT_OBSERVATION_RETRY_DELAY_CAP_SECONDS. A definitive
           code on the next attempt returns immediately under the existing
           taxonomy. Exhaustion still returns needs_attention /
           observation_unavailable. Continuity loss, identity ambiguity,
           identity unavailable, checkout change, agent_blocked and budget
           exhaustion are not retried. The retry is read-only: no prompt,
           send-keys, restorative write, or historical latch reopening.
           Apart from the two bounded recoveries below, no prompt retry.
        6. failed is reserved strictly for definitive candidate continuity loss.

        Settlement confirmation: screen-manifest agents can fall back to a weak
        idle/done while still executing, and observed fallback gaps reach several
        seconds, so one idle/done transition never settles alone. A candidate
        (exact status plus exact-integer state_change_seq) must survive the
        confirmation schedule selected from the authoritative expected.identity
        agent_kind — generically SETTLEMENT_CONFIRM_ATTEMPTS consecutive
        revalidations spaced by SETTLEMENT_CONFIRM_SECONDS; for kind "agy", under
        explicit user authorization, AGY_SETTLEMENT_CONFIRM_ATTEMPTS
        revalidation(s) spanning one full AGY_SETTLEMENT_CONFIRM_SECONDS interval
        — with identical status AND identical exact state_change_seq: positive
        working evidence rejects it (barrier re-arms), blocked yields attention,
        and any status change, seq change, or a missing/non-exact seq rejects the
        candidate and re-arms observation. A rejected AGY candidate never freezes
        a terminal receipt, releases/recreates the Work, or requires redelivery; a
        later fresh idle/done candidate starts a fresh interval. Elapsed attempts
        never force a settlement; only a fully stable candidate across every
        interval settles. Kind selects only the interval schedule — observation
        itself remains generic Herdr status and state_change_seq, with no TUI
        heuristic and no explain/detection-provenance query; weak or unavailable
        provenance never proves completion.

        Qoder activation recovery (user-authorized, kind "qodercli" only):
        Qoder can accept a native prompt yet leave it sitting unsubmitted in
        the composer, so the pane stays idle/done with unadvanced exact
        state_change_seq — an absorbing state that no additional waiting
        activates. When the startup budget expires in exactly that shape, ONE
        final exact revalidation gates ONE Enter-only nudge through Herdr's
        send-keys primitive: continuity loss, checkout change, observation
        uncertainty, blocked status, uncertain status, working evidence or seq
        advancement each veto the nudge and keep their existing classification
        or ordinary flow. The delivered nudge carries no task text, never
        re-invokes agent prompt (exactly one native prompt per turn is
        preserved), happens at most once per turn, and re-arms ONE fresh
        bounded activation window for the SAME physical turn — no Work
        recreation, no redelivery, no public intermediate state. A
        still-unadvanced expiry after the nudge is terminal needs_attention
        with reason qoder_activation_nudge_exhausted; a failed nudge transport
        is qoder_activation_nudge_uncertain; neither is retried or escalated.
        No screen text, Qoder private logs, or task-text heuristics are
        consulted.

        AGY composer recovery (user-authorized, kind "agy" only): the proven
        2026-09-21 incident silently lost an acked task between PTY acceptance
        and TUI input handling, leaving the absorbing shape — idle/done, exact
        pre-dispatch state_change_seq unadvanced, composer empty. When the
        startup budget expires in exactly that shape, ONE bounded cold-path
        recovery may re-deliver: a fresh exact revalidation, a Bridge-local
        same-resource exclusivity recheck, then TWO fresh bounded read-only
        `agent read --source detection` observations ~300ms apart that must
        EACH independently prove the live-validated settled empty-composer
        shape (bare `>` composer line, box separator, footer anchor; queued /
        esc-to-cancel / permission needles veto), with status idle/done and
        the exact pre-dispatch seq re-verified between and after the reads,
        and the exclusivity recheck repeated immediately before the write.
        Only then is the EXACT original task re-prompted through the same
        native `agent prompt` primitive ONCE — no Enter, no lower-level paste,
        no task mutation or nonce — and ONE fresh bounded window re-arms for
        the SAME Work/handoff. Any screen-read error/timeout/empty/malformed
        result, shape mismatch, seq/status movement, exclusivity ambiguity, or
        missing recovery seam declines silently to the existing
        activation_observation_budget_exhausted attention. A reprompt transport
        failure — or a receipt that fails full stable-resource ack matching —
        is terminal agy_composer_recovery_reprompt_uncertain (the mutation may
        have occurred; never a safe retry); a still unadvanced expiry after the
        reprompt is terminal
        agy_composer_recovery_exhausted. Never a third prompt, never a
        recovery loop; successful reprompts are audit-marked
        (agy_recovery_reprompt=True) without persisting task or screen text.
        The parser is recovery-only: if AGY's screen shape changes, recovery
        fails closed and normal AGY availability is unaffected.
        """
        identity = expected.get("identity") if isinstance(expected, dict) else {}
        pane_id = identity.get("pane_id") if isinstance(identity, dict) else None
        agent_kind = identity.get("agent_kind") if isinstance(identity, dict) else None
        if not isinstance(pane_id, str) or not pane_id:
            return {
                "state": "failed",
                "reason": "candidate_continuity_lost",
                "herdr_status": "continuity_lost",
                "post_state_change_seq": None,
                "post_revision": None,
                "post_candidate": None,
            }

        async def _safe_revalidate() -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
            extra_attempts, interval = _transient_observation_retry_budget()
            extras_used = 0
            while True:
                try:
                    curr = await self.revalidate_manual_agent(
                        expected, allow_session_promotion=True
                    )
                    return curr, None
                except HerdrError as exc:
                    failure = _manual_revalidation_failure(exc)
                    if exc.code in _TRANSIENT_OBSERVATION_CODES and extras_used < extra_attempts:
                        extras_used += 1
                        await asyncio.sleep(interval)
                        continue
                    return None, failure
                except Exception:
                    return None, {
                        "state": "needs_attention",
                        "reason": "revalidation_uncertain",
                        "herdr_status": "unknown",
                        "post_state_change_seq": None,
                        "post_revision": None,
                        "post_candidate": None,
                    }

        async def _confirm_settled_candidate(
            observed: dict[str, Any],
        ) -> dict[str, Any] | None:
            """Stability confirmation for one idle/done candidate.

            Returns a terminal ``done`` result only after the candidate survives
            every confirmation interval of its kind-selected schedule (see
            ``_settlement_confirmation_schedule``) with IDENTICAL status and
            IDENTICAL exact integer state_change_seq; returns None to reject the
            candidate and re-arm the native settled barrier (positive working
            evidence, a status change, a seq change, or a missing/non-exact seq);
            or returns an attention/failure result from revalidation (blocked,
            unknown status, continuity loss). One fallback transition alone
            proves nothing; elapsed attempts never force a settlement. Only
            generic Herdr status and state_change_seq are observed — no TUI
            heuristic and no explain/detection-provenance query, so weak or
            unavailable provenance never proves completion.
            """
            candidate_status = observed.get("herdr_status")
            candidate_seq = observed.get("_raw_state_change_seq")
            # A candidate without an exact-integer seq cannot be confirmed as
            # terminal; reject so outer fail-closed logic classifies it.
            if candidate_status not in {"idle", "done"} or not _is_exact_integer(candidate_seq):
                return None
            confirm_attempts, confirm_seconds = _settlement_confirmation_schedule(agent_kind)
            for _ in range(confirm_attempts):
                await asyncio.sleep(confirm_seconds)
                current, failure = await _safe_revalidate()
                if failure is not None:
                    return failure
                status = current.get("herdr_status")
                if status == "blocked":
                    return {
                        "state": "needs_attention",
                        "reason": "agent_blocked",
                        "herdr_status": status,
                        "post_state_change_seq": current.get("_raw_state_change_seq"),
                        "post_revision": current.get("_raw_revision"),
                        "post_candidate": current,
                    }
                if status == "working":
                    return None
                if status not in {"idle", "done"}:
                    return {
                        "state": "needs_attention",
                        "reason": "settlement_confirmation_uncertain",
                        "herdr_status": status,
                        "post_state_change_seq": current.get("_raw_state_change_seq"),
                        "post_revision": current.get("_raw_revision"),
                        "post_candidate": current,
                    }
                current_seq = current.get("_raw_state_change_seq")
                # Any status change (idle<->done), any seq change, or a
                # missing/non-exact seq rejects the candidate: positive evidence
                # of continued change is never treated as completion. The
                # rejection re-arms observation; a genuinely stable later
                # candidate re-establishes and settles on its own intervals.
                if status != candidate_status or current_seq != candidate_seq \
                        or not _is_exact_integer(current_seq):
                    return None
            # Survived every interval with identical status and identical exact
            # seq: this is the only path that proves the transition.
            return {
                "state": "done",
                "reason": "state_transition_proven",
                "herdr_status": candidate_status,
                "post_state_change_seq": candidate_seq,
                "post_revision": observed.get("_raw_revision"),
                "post_candidate": observed,
            }

        async def _qoder_activation_nudge() -> tuple[dict[str, Any] | None, bool]:
            """One Enter-only activation nudge for a stuck qodercli composer.

            Returns ``(terminal_result, nudged)``. A terminal result preserves
            the existing classification of the final exact revalidation
            (continuity loss, checkout change, observation uncertainty, blocked,
            uncertain status) or honestly reports a failed nudge transport;
            ``nudged`` is True only when the single Enter was actually
            delivered, after which observation re-arms with ONE fresh bounded
            window for the SAME physical turn. Working evidence or exact seq
            advancement at the final revalidation vetoes the nudge without a
            terminal result: the turn activated on its own. The nudge carries
            no task text, never re-invokes the native prompt, and is never
            retried here — the caller enforces the at-most-once bound.
            """
            current, failure = await _safe_revalidate()
            if failure is not None:
                return failure, False
            status = current.get("herdr_status")
            seq_now = current.get("_raw_state_change_seq")
            if status == "blocked":
                return {
                    "state": "needs_attention",
                    "reason": "agent_blocked",
                    "herdr_status": status,
                    "post_state_change_seq": seq_now,
                    "post_revision": current.get("_raw_revision"),
                    "post_candidate": current,
                }, False
            activated = status == "working" or (
                _is_exact_integer(pre_seq) and _is_exact_integer(seq_now)
                and seq_now > pre_seq
            )
            if activated:
                return None, False
            if status not in {"idle", "done"}:
                return {
                    "state": "needs_attention",
                    "reason": "startup_observation_uncertain",
                    "herdr_status": status,
                    "post_state_change_seq": seq_now,
                    "post_revision": current.get("_raw_revision"),
                    "post_candidate": current,
                }, False
            try:
                await self._call(
                    "agent", "send-keys", pane_id, QODER_ACTIVATION_NUDGE_KEY,
                    timeout=QODER_ACTIVATION_NUDGE_TIMEOUT_SECONDS,
                )
            except Exception:
                # Nudge transport failure is activation uncertainty, not a turn
                # outcome; never retried and never escalated into redelivery.
                return {
                    "state": "needs_attention",
                    "reason": "qoder_activation_nudge_uncertain",
                    "herdr_status": status,
                    "post_state_change_seq": seq_now,
                    "post_revision": current.get("_raw_revision"),
                    "post_candidate": current,
                }, False
            return None, True

        async def _agy_composer_recovery() -> tuple[dict[str, Any] | None, str]:
            """One cold-path empty-composer reprompt for a silently lost AGY task.

            Returns ``(terminal_result, outcome)`` where outcome is
            "reprompted" (the exact task was re-accepted by the native prompt
            primitive; the caller re-arms ONE fresh bounded window),
            "activated" (the turn started on its own at a recovery gate; the
            caller keeps the existing observation flow), or "declined" (any
            uncertainty; the caller keeps the existing exhaustion attention).
            A terminal result preserves existing classifications (continuity
            loss, checkout change, observation uncertainty, blocked, uncertain
            status) or honestly reports a failed reprompt transport or a
            reprompt receipt that fails full stable-resource ack matching.
            Never Enter, never a third prompt, never task mutation, never
            screen or task text in any result.
            """
            task = recovery.get("task") if isinstance(recovery, dict) else None
            exclusivity_clear = (recovery.get("exclusivity_clear")
                                 if isinstance(recovery, dict) else None)
            if not isinstance(task, str) or not task.strip() \
                    or not callable(exclusivity_clear):
                return None, "declined"

            def gate(current: dict[str, Any]) -> tuple[dict[str, Any] | None, str]:
                status = current.get("herdr_status")
                seq_now = current.get("_raw_state_change_seq")
                if status == "blocked":
                    return {
                        "state": "needs_attention",
                        "reason": "agent_blocked",
                        "herdr_status": status,
                        "post_state_change_seq": seq_now,
                        "post_revision": current.get("_raw_revision"),
                        "post_candidate": current,
                    }, "declined"
                if status == "working" or (
                        _is_exact_integer(pre_seq) and _is_exact_integer(seq_now)
                        and seq_now > pre_seq):
                    return None, "activated"
                if status not in {"idle", "done"}:
                    return {
                        "state": "needs_attention",
                        "reason": "startup_observation_uncertain",
                        "herdr_status": status,
                        "post_state_change_seq": seq_now,
                        "post_revision": current.get("_raw_revision"),
                        "post_candidate": current,
                    }, "declined"
                if not (_is_exact_integer(pre_seq) and _is_exact_integer(seq_now)
                        and seq_now == pre_seq):
                    return None, "declined"
                return None, "ok"

            current, failure = await _safe_revalidate()
            if failure is not None:
                return failure, "declined"
            terminal, outcome = gate(current)
            if terminal is not None or outcome != "ok":
                return terminal, outcome
            # Bridge-local exclusivity: no OTHER active/nonterminal handoff or
            # Work bound to the same resource/execution identity (regardless of
            # await consumption). Any ambiguity vetoes the reprompt.
            if exclusivity_clear() is not True:
                return None, "declined"
            for read_index in range(2):
                if read_index:
                    await asyncio.sleep(AGY_COMPOSER_RECOVERY_READ_INTERVAL_SECONDS)
                screen = await self._agy_detection_read(pane_id)
                if screen is None or not _agy_empty_composer_shape(screen):
                    return None, "declined"
                # Between and after the reads: the exact absorbing shape must
                # persist — same execution, idle/done, exact pre-dispatch seq.
                current, failure = await _safe_revalidate()
                if failure is not None:
                    return failure, "declined"
                terminal, outcome = gate(current)
                if terminal is not None or outcome != "ok":
                    return terminal, outcome
            # Immediately before the non-idempotent write: repeat exclusivity.
            if exclusivity_clear() is not True:
                return None, "declined"

            def uncertain_reprompt() -> dict[str, Any]:
                return {
                    "state": "needs_attention",
                    "reason": AGY_RECOVERY_REPROMPT_UNCERTAIN_REASON,
                    "herdr_status": current.get("herdr_status"),
                    "post_state_change_seq": current.get("_raw_state_change_seq"),
                    "post_revision": current.get("_raw_revision"),
                    "post_candidate": current,
                }

            try:
                receipt = await self._call(
                    "agent", "prompt", pane_id, task,
                    timeout=AGY_COMPOSER_REPROMPT_TIMEOUT_SECONDS,
                )
            except Exception:
                # Reprompt transport uncertainty is terminal and honest; never
                # retried and never escalated.
                return uncertain_reprompt(), "declined"
            if not self._prompt_ack_matches(receipt, expected):
                # A receipt that does not acknowledge the COMPLETE stable
                # resource identity is delivery uncertainty, not a safe retry:
                # the mutation may have occurred. Terminal and honest; never
                # retried, never audit-marked, never re-armed as acknowledged.
                return uncertain_reprompt(), "declined"
            audit["agy_recovery_reprompt"] = True
            return None, "reprompted"

        # One observation budget, not an Agent-start SLA or submission proof.
        # Revalidation and every native wake consume this same monotonic budget.
        startup_deadline = time.monotonic() + ACTIVATION_OBSERVATION_SECONDS
        qoder_nudge_used = False
        agy_recovery_used = False
        while True:
            current, failure = await _safe_revalidate()
            if failure is not None:
                return failure

            post_status = current.get("herdr_status")
            post_seq = current.get("_raw_state_change_seq")
            post_rev = current.get("_raw_revision")
            seq_adv = _is_exact_integer(pre_seq) and _is_exact_integer(post_seq) and post_seq > pre_seq

            if post_status == "blocked":
                return {
                    "state": "needs_attention",
                    "reason": "agent_blocked",
                    "herdr_status": post_status,
                    "post_state_change_seq": post_seq,
                    "post_revision": post_rev,
                    "post_candidate": current,
                }
            if post_status in {"idle", "done"} and seq_adv:
                confirmed = await _confirm_settled_candidate(current)
                if confirmed is not None:
                    return confirmed
                # Candidate rejected during confirmation (working evidence, a
                # status/seq change, or a non-exact seq): proceed to the settled
                # barrier below; the same turn is still open and re-establishes.
                break
            if post_status == "working":
                break
            if post_status not in {"idle", "done"}:
                return {
                    "state": "needs_attention",
                    "reason": "startup_observation_uncertain",
                    "herdr_status": post_status,
                    "post_state_change_seq": post_seq,
                    "post_revision": post_rev,
                    "post_candidate": current,
                }

            remaining = startup_deadline - time.monotonic()
            if remaining <= 0:
                if agent_kind == HERDR_QODER_LABEL and not qoder_nudge_used:
                    veto, nudged = await _qoder_activation_nudge()
                    if veto is not None:
                        return veto
                    if nudged:
                        qoder_nudge_used = True
                    # Nudge delivered (or the turn self-activated at the final
                    # gate): re-arm ONE fresh bounded window for the SAME
                    # physical turn — never an unbounded or repeated loop.
                    startup_deadline = time.monotonic() + ACTIVATION_OBSERVATION_SECONDS
                    continue
                if agent_kind == HERDR_AGY_LABEL and not agy_recovery_used:
                    veto, outcome = await _agy_composer_recovery()
                    if veto is not None:
                        return veto
                    if outcome in {"reprompted", "activated"}:
                        if outcome == "reprompted":
                            agy_recovery_used = True
                        # Reprompt delivered (or the turn self-activated at a
                        # recovery gate): re-arm ONE fresh bounded window for
                        # the SAME Work/handoff — never a recovery loop.
                        startup_deadline = time.monotonic() + ACTIVATION_OBSERVATION_SECONDS
                        continue
                    # Declined: keep the existing exhaustion attention below.
                # This exact revalidation is also the final observation after
                # native timeout: fast same-terminal turns can still settle.
                return {
                    "state": "needs_attention",
                    "reason": ("qoder_activation_nudge_exhausted" if qoder_nudge_used
                               else AGY_RECOVERY_EXHAUSTED_REASON if agy_recovery_used
                               else "activation_observation_budget_exhausted"),
                    "herdr_status": post_status,
                    "post_state_change_seq": post_seq,
                    "post_revision": post_rev,
                    "post_candidate": current,
                }

            # Herdr wait is level-triggered. Exclude the CURRENT stale status,
            # not always idle; a previous done must not immediately satisfy it.
            other_terminal = "done" if post_status == "idle" else "idle"
            timeout_ms = max(1, int(remaining * 1000))
            wait_started = time.monotonic()
            try:
                await self._call(
                    "agent", "wait", pane_id,
                    "--until", "working", "--until", other_terminal, "--until", "blocked",
                    "--timeout", str(timeout_ms),
                    timeout=remaining + 1.0,
                )
            except Exception as exc:
                # Only native status-wait expiry has code=timeout. Python's
                # TimeoutError is subprocess/transport uncertainty, not expiry.
                if not isinstance(exc, HerdrError) or exc.code != "timeout":
                    current, failure = await _safe_revalidate()
                    if failure is not None:
                        return failure
                    return {
                        "state": "needs_attention",
                        "reason": "startup_wait_uncertain",
                        "herdr_status": current.get("herdr_status"),
                        "post_state_change_seq": current.get("_raw_state_change_seq"),
                        "post_revision": current.get("_raw_revision"),
                        "post_candidate": current,
                    }
            # A transient event may wake a level wait although revalidation
            # finds the original status again. Pace such immediate wakeups;
            # never spin, reset the budget, or send a zero/indefinite timeout.
            pause = min(0.01 - (time.monotonic() - wait_started),
                        startup_deadline - time.monotonic())
            if pause > 0:
                await asyncio.sleep(pause)

        # Step 3: watch the turn with ONE indefinite native settled barrier; a
        # confirmed candidate that reverts to working re-arms the same barrier
        # for the same turn and never freezes a terminal receipt mid-flight.
        while True:
            try:
                await self._call(
                    "agent", "wait", pane_id,
                    "--until", "idle", "--until", "done", "--until", "blocked",
                    timeout=None,
                )
            except Exception:
                return {
                    "state": "needs_attention",
                    "reason": "settle_wait_uncertain",
                    "herdr_status": "unknown",
                    "post_state_change_seq": None,
                    "post_revision": None,
                    "post_candidate": None,
                }

            current, failure = await _safe_revalidate()
            if failure is not None:
                return failure

            post_status = current.get("herdr_status")
            post_seq = current.get("_raw_state_change_seq")
            post_rev = current.get("_raw_revision")
            seq_adv = _is_exact_integer(pre_seq) and _is_exact_integer(post_seq) and post_seq > pre_seq

            if post_status == "blocked":
                return {
                    "state": "needs_attention",
                    "reason": "agent_blocked",
                    "herdr_status": post_status,
                    "post_state_change_seq": post_seq,
                    "post_revision": post_rev,
                    "post_candidate": current,
                }
            if post_status not in {"idle", "done"}:
                return {
                    "state": "needs_attention",
                    "reason": "transition_unproven",
                    "herdr_status": post_status,
                    "post_state_change_seq": post_seq,
                    "post_revision": post_rev,
                    "post_candidate": current,
                }
            if not seq_adv:
                return {
                    "state": "needs_attention",
                    "reason": "transition_unproven",
                    "herdr_status": post_status,
                    "post_state_change_seq": post_seq,
                    "post_revision": post_rev,
                    "post_candidate": current,
                }
            confirmed = await _confirm_settled_candidate(current)
            if confirmed is not None:
                return confirmed
            # Candidate rejected during confirmation (working evidence, a
            # status/seq change, or a non-exact seq): re-arm the native settled
            # barrier and keep watching the same open turn.
