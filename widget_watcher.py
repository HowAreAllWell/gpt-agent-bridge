"""One-shot explicit Work batch widget; source does not prove host mounting.

Delegate binds this resource. A synchronous ready result has no hydration;
its descriptor may still cause a host card/iframe. No observation starts there.
"""
from __future__ import annotations

import json
import re
from typing import Any

from mcp.types import CallToolResult, TextContent

WIDGET_RESOURCE_URI = 'ui://bridge/work-batch-watcher/index.html'
DELEGATE_TOOL_META = {'ui': {'resourceUri': WIDGET_RESOURCE_URI, 'visibility': ['model']}}
WORK_WATCH_META_KEY = 'bridge/workWatch'
_AGENT_REF_RE = re.compile(r'[A-Za-z0-9._:-]{1,80}\Z')


def format_classification_notice(result_ready: list[str], attention: list[dict[str, Any]]) -> str:
    """One formatter for synchronous ready presentation and widget follow-up.

    Report status is never inferred from an abnormal signal that skipped probing.
    Agent advice is emitted only for recorded, syntactically valid Agent handles.
    """
    lines = ['Batch classified. Classification is not task success. Reassess the pending judgment before continuing.']
    if result_ready:
        lines.append('Report ready: ' + ', '.join(result_ready) + '. Read each with work_report.')
    if attention:
        lines.append('Attention required: ' + ', '.join(item['work_ref'] for item in attention) + '.')
        agents = list(dict.fromkeys(item['agent_ref'] for item in attention
                    if isinstance(item.get('agent_ref'), str) and _AGENT_REF_RE.fullmatch(item['agent_ref'])))
        if agents:
            lines.append('Inspect agent_terminal_read for ' + ', '.join(agents) + ' before delegating to ' +
                         ('that Agent' if len(agents) == 1 else 'those Agents') + ' again.')
        lines.append('Use the recorded signal/reason and relevant current diagnostics for your judgment; '
                     'a report may also be available through work_report. Attention is not task failure.')
    lines.append('After consuming these results or diagnostics, continue relevant authorized work in light of current user input.')
    return '\n'.join(lines)


def watch_tool_result(payload: dict[str, Any], watch: dict[str, Any] | None = None) -> CallToolResult:
    """Keep opaque subscription identity in app-only hydration, not Principal data."""
    meta = None
    if payload.get('ok') is True and payload.get('status') == 'armed' and watch is not None:
        meta = {WORK_WATCH_META_KEY: {'project_ref': payload['project_ref'],
                'watch_ref': watch['watch_ref'], 'work_refs': list(watch['members'])}}
    return CallToolResult(content=[TextContent(type='text', text=json.dumps(payload, ensure_ascii=False))],
                          structured_content=payload, meta=meta)


_HTML_TEMPLATE = r'''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>Bridge batch watcher</title>
<style>body{font:13px/1.45 system-ui,sans-serif;margin:12px}#phase{font-weight:600}#detail{white-space:pre-wrap}</style>
</head><body><div id="phase">Waiting for batch data</div><pre id="detail"></pre>
<script>
(function () {
  "use strict";
  var META_KEY = "bridge/workWatch";
  var PROJECT_RE = /^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$/;
  var WORK_RE = /^work-[0-9a-f]{16}$/;
  var WATCH_RE = /^watch-[0-9a-f]{16}$/;
  var AGENT_RE = /^[A-Za-z0-9._:-]{1,80}$/;
  var SIGNALS = {agent_turn_settled:true, needs_attention:true, continuity_lost:true};
  var REPORTS = {readable:true, missing:true, invalid:true, unknown:true};
  var hydrated = null, stopped = false, inFlight = false, started = false, followUp = "none";
  function phase(name, detail) {
    document.getElementById("phase").textContent = name;
    document.getElementById("detail").textContent = detail || "";
  }
  function stop(name, detail) { stopped = true; inFlight = false; phase(name, detail); }
  function valid(pattern, value) { return typeof value === "string" && pattern.test(value) && value.indexOf("\n") < 0 && value.indexOf("\r") < 0; }
  function refsValid(refs) {
    if (!Array.isArray(refs) || !refs.length) return false;
    var seen = Object.create(null);
    for (var ref of refs) { if (!valid(WORK_RE, ref) || seen[ref]) return false; seen[ref] = true; }
    return true;
  }
  function unpack(result) {
    if (!result || typeof result !== "object" || Array.isArray(result) || result.isError === true || result.is_error === true) return null;
    var sc = result.structuredContent;
    return sc && typeof sc === "object" && !Array.isArray(sc) && sc.ok !== false ? sc : null;
  }
  function sameIdentity(sc) {
    return sc.project_ref === hydrated.project_ref && sc.watch_ref === hydrated.watch_ref;
  }
  function finalPayload(sc) {
    if (!sameIdentity(sc) || !Array.isArray(sc.work_refs) || sc.work_refs.length !== hydrated.work_refs.length ||
        !sc.work_refs.every((ref, i) => ref === hydrated.work_refs[i]) || sc.proves !== "final_classification_only" ||
        typeof sc.notice !== "string" || !sc.notice || !Array.isArray(sc.result_ready) || !Array.isArray(sc.attention_required)) return false;
    var seen = Object.create(null), count = 0;
    for (var ref of sc.result_ready) {
      if (!valid(WORK_RE, ref) || seen[ref] || hydrated.work_refs.indexOf(ref) < 0) return false;
      seen[ref] = true; count++;
    }
    for (var item of sc.attention_required) {
      if (!item || typeof item !== "object" || !valid(WORK_RE, item.work_ref) || seen[item.work_ref] ||
          hydrated.work_refs.indexOf(item.work_ref) < 0 || !Object.prototype.hasOwnProperty.call(SIGNALS, item.signal) ||
          !Object.prototype.hasOwnProperty.call(REPORTS, item.report_status) || typeof item.reason !== "string" ||
          (item.agent_ref !== undefined && !valid(AGENT_RE, item.agent_ref)) ||
          (item.signal === "agent_turn_settled" && item.report_status === "readable")) return false;
      seen[item.work_ref] = true; count++;
    }
    return count === hydrated.work_refs.length;
  }
  function call(name, resolved) {
    if (stopped || inFlight) return;
    inFlight = true;
    var pending;
    try { pending = window.openai.callTool(name, {project_ref:hydrated.project_ref, watch_ref:hydrated.watch_ref}); }
    catch (error) { stop("error-transport", "Outcome unknown; no retry or follow-up."); return; }
    if (!pending || typeof pending.then !== "function") { stop("error-transport", "Outcome unknown; no retry or follow-up."); return; }
    pending.then(function (result) { inFlight = false; if (!stopped) resolved(result); },
      function () { stop("error-transport", "Outcome unknown; no retry or follow-up."); });
  }
  function wait() {
    phase("waiting", "Waiting for every selected Work's final classification.");
    call("wait_work_watch", function (result) {
      var sc = unpack(result);
      if (!sc) { stop("error-wait", "Batch observation refused or malformed."); return; }
      if (sc.ready === false && Object.keys(sc).length === 1) { wait(); return; }
      if (sc.ok === true && sc.status === "consumed" && sameIdentity(sc)) { stop("consumed", "This batch's delivery was consumed."); return; }
      if (sc.ready !== true || !finalPayload(sc)) { stop("error-wait", "Incomplete or contradictory batch observation."); return; }
      claim();
    });
  }
  function claim() {
    if (followUp !== "none") return;
    followUp = "claiming";
    call("claim_work_watch", function (result) {
      var sc = unpack(result);
      if (sc && sc.ok === true && sc.granted === false && sameIdentity(sc) &&
          (sc.reason === "already_consumed" || sc.reason === "not_ready")) {
        stop("consumed", "No grant for this instance. No follow-up."); return;
      }
      if (!sc || sc.ok !== true || sc.granted !== true || !finalPayload(sc) ||
          typeof sc.attempt_token !== "string" || !/^attempt-[0-9a-f]{32}$/.test(sc.attempt_token)) {
        stop("error-claim", "Grant refused or unknown; no send or retry."); return;
      }
      // Stop before invoking the host: the grant stays consumed in every branch.
      stop("sending", "One follow-up attempt; grant consumed.");
      followUp = "sending";
      var host = window.openai, pending;
      var reported = false;
      // This helper intentionally works after stop(). It sends telemetry once,
      // never retries, and never resumes the wait/claim/send state machine.
      function reportOutcome(outcome) {
        if (reported) return;
        reported = true;
        try {
          var observation = host.callTool("record_work_watch_send_outcome", {
            project_ref:hydrated.project_ref, watch_ref:hydrated.watch_ref,
            attempt_token:sc.attempt_token, outcome:outcome});
          if (observation && typeof observation.then === "function") observation.then(function () {}, function () {});
        } catch (error) { /* Lost telemetry is unknown, never grounds for retry. */ }
      }
      if (!host || typeof host.sendFollowUpMessage !== "function") { phase("unavailable", "Host continuation unavailable; grant consumed."); reportOutcome("unavailable"); return; }
      try { pending = host.sendFollowUpMessage({prompt:sc.notice}); }
      catch (error) { phase("unknown", "Delivery unknown; grant consumed. No resend."); reportOutcome("host_rejected_or_unknown"); return; }
      if (!pending || typeof pending.then !== "function") { phase("unknown", "Delivery unknown; grant consumed. No resend."); reportOutcome("host_rejected_or_unknown"); return; }
      pending.then(function () { phase("sent", "Host accepted the request; delivery/model turn unverified. Grant consumed."); reportOutcome("host_accepted"); },
        function () { phase("unknown", "Delivery unknown; grant consumed. No resend."); reportOutcome("host_rejected_or_unknown"); });
    });
  }
  function tryStart(globals) {
    if (stopped || started) return;
    var host = window.openai;
    var readyOutput = (globals && globals.toolOutput) || (host && host.toolOutput);
    readyOutput = readyOutput && readyOutput.continuation;
    if (readyOutput && readyOutput.ok === true && readyOutput.status === "ready") {
      stop("ready", readyOutput.notice || "Batch classified; task success unverified."); return;
    }
    if (!host || typeof host.callTool !== "function") return;
    var candidates = [globals && globals.toolResponseMetadata, host.toolResponseMetadata];
    var h = null;
    for (var bag of candidates) {
      if (!bag || typeof bag !== "object") continue;
      for (var resultBag of [bag, bag.mcp_tool_result, bag.call_tool_result]) {
        if (!resultBag || typeof resultBag !== "object") continue;
        for (var nested of [resultBag, resultBag._meta, resultBag.meta]) {
          if (nested && nested[META_KEY] !== undefined) { h = nested[META_KEY]; break; }
        }
        if (h !== null) break;
      }
      if (h !== null) break;
    }
    if (h === null) return;
    if (!h || !valid(PROJECT_RE, h.project_ref) || !valid(WATCH_RE, h.watch_ref) || !refsValid(h.work_refs)) {
      stop("error-hydration", "Invalid batch hydration; no observation."); return;
    }
    hydrated = {project_ref:h.project_ref, watch_ref:h.watch_ref, work_refs:h.work_refs.slice()};
    started = true;
    wait();
  }
  if (typeof window.addEventListener === "function") {
    window.addEventListener("openai:set_globals", function (event) {
      var detail = event && event.detail;
      tryStart(detail && (detail.globals || detail));
    }, {passive:true});
  }
  tryStart(null);
})();
</script></body></html>'''


def widget_html() -> str:
    return _HTML_TEMPLATE
