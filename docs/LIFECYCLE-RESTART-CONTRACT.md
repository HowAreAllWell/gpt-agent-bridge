**English** | [简体中文](LIFECYCLE-RESTART-CONTRACT.zh-CN.md)

# GPT-Agent Bridge lifecycle and restart contract

Use this page to understand **what happens after you send a task to a local
Herdr Agent, how to read its result, and what a reminder or restart does not
prove**. For installation, use [Getting started](GETTING-STARTED.md) instead.
You do not need to read the internal contract before your first small task;
start with the practical steps here and use the detailed sections when blocked.

These instructions target **ordinary ChatGPT Web Project Chat**, on native Ubuntu
Desktop or Windows+WSL2. Success in ChatGPT Work mode or local Codex does not
replace the Web check, and the support target does not enforce Web-only plugin
visibility. Compatible Herdr 0.9.0 must already be installed, and your authorized
Agent must already be running;
Bridge does not install providers or start Agents for you.

### A small task from dispatch to review

For example, authorize two available Agents to investigate a design question
independently, with read-only scope and a report. In your ordinary Project Chat:

1. **Check the destination first.** Identify the authorized `project_ref` (the
   short project name from setup) and request fresh project context from Bridge:
   its current repository information and eligible Agent list. Identify the
   intended existing Agents from that observation. If you want browser reminders, bind this exact Chat and
   enable them **before** delegation using [Getting started step 9](GETTING-STARTED.md#9-load-the-private-extension-and-bind-this-exact-chat).
   No extension is required to use Bridge tools and read reports manually.
2. **State the question, scope and expected evidence.** The Principal (ChatGPT
   reasoning with you) sends only the authorized assignments. Bridge returns a
   receipt for each. Bridge calls each tracked assignment a **Work**; its
   `work_ref` identifies that particular dispatch. A receipt is not a completed
   task or proof the Agent consumed input.
3. **Continue useful independent work.** Do not repeatedly send the assignment,
   poll context/terminals just to wait, or treat silence as failure. If there is
   nothing independent to do, end the turn; without an enabled reminder extension,
   you will need to return and ask for the result yourself.
4. **Read before accepting.** When a completion/attention notice arrives, ask the
   Principal to read the full available reports for those exact Work references
   and compare their claims with relevant original files, code changes (diffs) and test evidence.
   A finished Agent turn, readable report or agreement between Agents does not
   establish correctness. The notice itself contains no report body.

One delegation call can group several assignments into one notification batch.
Its reminder becomes eligible after all retained members have final classifications
(or authoritative expiry), so one Agent finishing need not produce an immediate
notice. The extension may combine already-ready batches for the same project/Chat;
it does not wait for an unfinished batch to merge with them.

### What a notice means, and what to ask next

In the **ordinary Project Chat for that project** (the bound recipient if you
use reminders), you can send:

> Review the reported Work references for project MY_PROJECT. Read the complete
> available reports and relevant original evidence within our scope. Separate
> verified results, Agent claims, missing evidence and attention conditions.
> If delivery or a result is unknown, inspect only the permitted diagnostics;
> do not resend tasks, restart services or change files to force a result.

Replace `MY_PROJECT` and use only Work references actually returned for it.
**Expected result:** a reasoned review of evidence, or a specific pending/missing/
uncertain condition. If Bridge has not recorded an end condition for the Work,
its report is not yet readable through `work_report`; do not start a wait loop. A missing report does not prove
that the Agent did nothing or failed. The detailed error rules below determine
what can be observed next, without granting another task dispatch.

| What you observe | What it establishes | Safe next step |
| --- | --- | --- |
| A dispatch receipt | The recorded submission evidence for that assignment | Keep its exact Work reference; inspect the per-item outcome. |
| A completion/attention reminder | A batch became eligible for a notice | Read reports/diagnostics; do not accept the work from the notice alone. |
| A local Send click | The extension invoked the page control, not that ChatGPT received or processed it | Treat an uncertain effect as non-replayable; do not send again to test delivery. |
| A readable report | Those report bytes are available | Read all pages, then check claims against original evidence. |
| No reminder | No observed reminder, with several possible causes | Ask for a scoped result check when you return; do not infer task failure or resend. |

### If ChatGPT is busy or you have a draft

The optional extension acts only on the exact Chat you consented to bind; it does
not give ChatGPT continuous autonomous awareness. In **that Chat's message box**:

- **Visible Stop:** the page is busy. The extension refuses to send under that
  condition. Do not stop a useful response merely to force a reminder.
- **An empty, safe message box:** it may send the fixed notice once after its
  checks. A local click is not server acknowledgement or report review.
- **A text or attachment draft:** the extension offers
  **追加到输入框末尾（另起一行）** (append the notice on a new line) or **忽略**
  (ignore). Append adds the notice after active text composition ends; **it does
  not press Send**. Review the draft and send it yourself only when you choose.
  Ignore leaves your draft and files untouched.

If the choice is stale or an append/acknowledgement has an unknown effect, the
extension does not retry that mutation. Do not clear storage, reinstall the
extension or move its folder to make an old notice reappear. Its stored identity
evidence prevents duplicate attempts, including after browser restart.

### Ubuntu, WSL and restart symptoms

The reminder feed uses **loopback**: a local-only address such as `127.0.0.1`,
which refers to the computer/environment making the request. The private MCP
Tunnel used by ChatGPT tools is a separate connection.

| Your setup or symptom | What to check without guessing a recovery |
| --- | --- |
| **Native Ubuntu Desktop** | Chrome and Bridge are on the same Ubuntu computer. No WSL or PowerShell is needed. After sleep/reboot, check Bridge/Tunnel health and the exact Chat binding before new delegation. |
| **Windows+WSL2** | Windows Chrome needs the selected WSL Linux environment and its loopback feed to be reachable. Shutting down that distribution or Windows sleep can interrupt it; services alone do not keep WSL alive. |
| **Ubuntu Server, browser on another computer** | Do not assume reminders work. A laptop browser's loopback is not the server's. Tunnel tool access does not prove reminder access; this headless arrangement lacks validated browser-reminder acceptance. |
| **Bridge restarted; an old Work reference is unavailable** | Its process-local record may be lost. The external Agent may still be running; notes do not restore that Work. Preserve the uncertainty and seek authorized observations, not a replacement dispatch. |
| **Tools work but no reminder arrives** | Check optional extension enablement, recipient, page/draft conditions and local feed separately. Do not rebuild the MCP connection or resend the task to test notices. |

For read-only service checks and the difference between Ubuntu boot and WSL
login/lifetime, see [Autostart](AUTOSTART.md). If normal `./prepare` already
completed, it installed, enabled and started two services; do not reinstall them
as a troubleshooting step. On Windows use the separate launcher in Getting
Started, not a native Ubuntu command pasted into PowerShell.

Chrome normally uses a minute alarm to wake the extension worker; **this is not
a one-minute delivery guarantee**. Browser scheduling, page safety, report
availability and network conditions can delay or prevent a notice. Fresh native
Ubuntu, Windows restart and real browser delivery still need live acceptance.
Before switching chats, preserve useful decisions through
[project continuity](PROJECT-CONTINUITY.md#before-changing-chats); that does not
resume Work or automatically send a reminder to the new Chat.

### Advanced: exact lifecycle and recovery rules

The rest of this page defines the source-level contract for operators and
maintainers. A resource is an exact current Herdr terminal location; CWD is its
working directory. A terminal Work is a record whose observation has ended, not
necessarily a successful task. A latch keeps the first terminal observation
fixed. A cursor marks feed progress; an epoch identifies a producer lifetime;
consumed IDs prevent an already-attempted notice being offered again. Browser
ACKs below mean local acknowledgements, not proof of ChatGPT server delivery.

Status: source contract for the retained generic Work path. Specialized and
compatibility MCP endpoints are absent, including hidden callability.
This document describes current source behavior and its evidence limits. Source
inspection and tests do not certify a deployed service, backend version or client acceptance.

## Resource and Work identity

**What this means for you:** an Agent's display name is not a permanent address,
and a Work reference is not a saved session. Use the exact current Agent handle
from the authorized project and retain the returned Work reference. If identity
checks fail, stop; do not substitute a similar pane or another repository.
The following rules explain the binding and private report path, not permission
to inspect other projects or private configuration.

An Agent handle addresses one exact current resource in an explicit registered project:
Herdr workspace/tab/pane/terminal plus raw kind/name. It is process-local, not durable
Agent identity. A linked execution checkout is accepted only inside the registered
project's exact Git common-dir boundary. Missing/malformed/ambiguous identity fails
closed; do not infer another project, resource or backend.

Placement is complete before launch/prompt. `delegate(project_ref, assignments=[{agent_ref, task}, ...])`
revalidates the registry and exact resource, reserves Work before prompt mutation, then
refreshes the selected resource under the writer gate immediately before binding
execution identity and dispatch. Resource identity is stable while native session,
foreground process and CWD are execution evidence. No delegate-time rebind, placement
recovery, readiness migration or fallback exists. Frozen evidence_checkout metadata is
captured at this existing writer-gated binding point. Capture failure does not change
dispatch semantics. read/search/diff revalidate the saved target independently of
mutable Agent/handoff state; unavailable or changed identity never falls back.

The Work registry owns opaque work- refs. Delegate always accepts assignments and
returns per-item dispatch receipts immediately. Each retained
item identifies its Work with `work_ref`. Dispatch uncertainty returns the accessible
work_ref where available; prompt transport and caller cancellation cannot silently
orphan already-reserved Work. The internal handoff watcher and resource gating remain
because delegate and the internal watcher consume them; no public handoff/join or legacy call-through exists.
The model-visible await tool is removed.

Every admitted Work requests cooperative publication into a unique private report destination allocated after Work reservation
and before prompt mutation. A single task suffix authorizes only the final report and
its named atomic-publication staging file, requesting the complete UTF-8 report before
the Agent's terminal response. The publication suffix counts toward the existing 16384-character limit, so a
near-limit task may fail preparation. Preparation failure discards the unsubmitted
reservation without truncating task text. The exact augmented bytes enter ordinary dispatch and
same-Work recovery seam once, never a second suffix. They are not persisted in receipts
or task logs. Only prompt-transport errors that may echo augmented bytes/private paths
are redacted; known no-input errors, pre-prompt revalidation and blocking diagnostics
retain their useful messages. Submission uncertainty and retry authority are unchanged.

Report storage is exact: a lazily created per-process 0700 `/tmp/bridge-reports-*`
directory holds random final basenames plus `.pending` staging files, and no report
path appears in public receipts. Graceful whole-server shutdown (systemd SIGTERM;
Uvicorn runs the application lifespan shutdown before restoring/re-raising) closes the
current process store once during the ASGI/MCP lifespan teardown, after normal
MCP/session-manager teardown. Crash/SIGKILL, power loss, late writers or permission
errors can still leave orphaned files — an accepted residual. There is no startup scan,
and restart does not scan, recover or purge old orphans; no startup GC or total disk
bound is implied.

`work_report` requires exact project/Work binding and a terminal Work; it retrieves only
the published private artifact, not a pane tail or provider transcript. It neither waits
for publication nor changes the terminal latch. Missing/noncompliant publication is an
explicit evidence error, not a new Work outcome. Single-assignment delegate receipts keep
their dispatch fields and prior-evidence advisory. Internal Work records keep settlement state, reason and
submission evidence; there is no public per-Work await tool or report-request flag. Settlement
does not wait for a report, and readable report bytes prove presence only, never task
success or truth.
Report retention/cleanup follows
[Work capacity](#work-capacity-and-report-lifetime). No generic Agent startup or output interception is added.
An immediate post-settlement `work_report` can transiently be WorkReportMissing if the external
publication rename lands just after settlement. `work_report` itself remains one
observation per call, without publication waiting or an automatic retry loop; missing
does not prove permanent absence. Classification probes the dedicated report after
the latch, without sleeping under the Work registry lock.
`WorkReportMissing` is the only transient candidate: an initial read plus at most two
extra rechecks about one second apart. Added retry waiting stays within five seconds.
The cap bounds those injected waits, not OS I/O wall-clock time. Other report-read
errors classify immediately as `invalid` or `unknown`. A readable report with
`agent_turn_settled` is `result_ready`. `needs_attention`, `continuity_lost`, and a
missing or invalid report are `attention_required`. The class is set once.

## Submission evidence

**Read the per-item receipt before deciding what happened.** `not_attempted`
means a local refusal before input. `native_acknowledged` means the host accepted
or queued the request, not that the Agent ran it. `delivery_unknown` means input
may have happened. In the latter case follow the returned read-only diagnostic
instruction and **do not resend**. A known no-input refusal can be corrected
within existing authority; it is different from uncertain delivery. The narrow
backend-specific recovery rules below are not a general manual retry recipe.

Work and its handoff retain one compact `submission_evidence` object across the
terminal latch. `not_attempted` records a local refusal before input;
`native_acknowledged` requires an `agent_prompted` receipt identifying the complete
matching stable resource (kind/name, workspace/tab/pane/terminal). Missing, malformed,
unrecognized or contradictory receipt identity remains `delivery_unknown`, as do
native errors, timeout and cancellation. Matching session churn is not required.
Mutation is marked possible before the non-idempotent call. Known native error codes
are bounded tokens, not raw task text, paths or output; no code proves no effect.
Acknowledgement proves only host acceptance/queueing of that request, never Agent
consumption, Enter delivery, task execution or completion. Any transport response without a matching acknowledgement is surfaced synchronously
as WorkDispatchTransportUncertain with agent_ref, work_ref and submission_evidence.
When mutation_possible=true, its structured error carries the safety instruction:
read agent_terminal_read before further delegation and do not resend the task. The
compact text describes delivery unknown and points to that structured instruction.
When mutation_possible=false, the error preserves the concrete backend reason and
the compact text states no prompt/input was sent; neither forbids resend nor claims
unknown delivery. Work and its watcher remain accessible. Cancellation propagates after retaining
uncertainty. Existing local refusals still discard never-dispatched reservations.
Terminal signals and report classification remain independent of submission provenance:
a later agent_turn_settled latch with a readable dedicated report can yield result_ready
even when original delivery remains unknown. That does not rewrite submission evidence.
Native-version compatibility and end-to-end attribution are not established.

Native AgentInfo may omit optional name: omission matches only an expected unnamed
resource (None). Named omission/mismatch and missing required locus/kind fields remain
unknown acknowledgement, with the Work accessible and no prompt retry.

For authoritative agent_kind exactly `agy` — and only it — one exhausted unadvanced
activation-observation budget passes through a bounded cold-path composer recovery
instead of immediate attention. Normal AGY dispatch is unchanged: one native prompt
after the existing validations, with no screen dependency, no local Herdr manifest-override
prerequisite, and no added hot-path Herdr call. A native acknowledgement proves
transport acceptance, not that an AGY turn activated. Because AGY status depends on
screen detection, an unadvanced idle/done observation cannot by itself distinguish
lost input from a turn that is not visible to detection. Recovery therefore
re-delivers only after native_acknowledged submission and under a conjunction: the same execution/session/resource still idle/done
and unblocked with the exact pre-dispatch `state_change_seq` unchanged; Bridge-local
exclusivity (no other nonterminal handoff or Work bound to the same resource_key or
execution identity, regardless of delivery consumption — and an active recovery window
symmetrically blocks same-resource dispatch through the existing in-flight guard); and
TWO fresh bounded read-only `agent read --source detection` observations ~300ms apart
that each independently match the recognized settled EMPTY-composer shape (bare `>`
composer line, box-drawing separator, footer anchor; queued-hint, esc-to-cancel and
permission needles veto), with status/seq/identity revalidated between and after the
reads and exclusivity rechecked immediately before the write. A caller-cancelled
delegate never auto-reprompts: its watcher keeps the existing attention outcome. Only
then is the EXACT
original task — held solely in an in-memory watcher seam, never persisted to receipts,
handoff entries, or logs — re-prompted through the same native prompt primitive ONCE for
the same Work/handoff: no Enter, no lower-level paste, no task mutation or nonce,
followed by ONE fresh bounded activation window (normal AGY settlement debounce applies
after activation). Any uncertainty — screen-read error/timeout/empty/malformed result,
shape mismatch, seq/status movement, exclusivity ambiguity, or a missing recovery seam —
keeps the existing `activation_observation_budget_exhausted` attention; a reprompt
transport failure — or a reprompt receipt that fails the same full stable-resource ack
matching as the first prompt — is terminal `agy_composer_recovery_reprompt_uncertain`
(the mutation may have occurred; never a safe retry); a still unadvanced expiry after the
reprompt is terminal `agy_composer_recovery_exhausted`.
Never a third prompt and never a recovery loop. A successful reprompt is audit-marked
with the boolean `agy_recovery_reprompt` in handoff and Work records,
without task or screen text. If AGY's screen shape changes, recovery fails closed to the
existing attention and normal AGY availability is unaffected. Every other kind keeps the
existing behavior exactly; the qodercli composer-nudge recovery is unchanged.

## Agent settlement and terminal evidence

**“Settled” is an observation, not an acceptance verdict.** The first terminal
record stays fixed even if later evidence arrives. `needs_attention` means you
need to inspect the condition, not that the Agent failed or stopped. Read the
report and original project evidence before accepting a result, or diagnosing
whether any further action is safe. Internal bounded read-only rechecks do not
authorize user-driven prompt retries or forced interruption.

Each first terminal latch emits one
bridge.work_terminal_latch: work_ref, bounded handoff_id, terminal state, reason,
herdr_status, bounded watcher_error_code and dispatch-to-latch elapsed_ms. These logs
contain no task text, terminal content or raw exception body and are process logs,
not a durable journal. Repeated latches emit nothing.

Startup observation uses one five-second monotonic budget, including exact revalidation
and all wakes. A native status wait excludes the currently observed stale idle/done
status: idle waits for working/done/blocked; done waits for working/idle/blocked.
Each wake or native expiry revalidates identity and sequence; an advanced qualifying
terminal sequence can settle without sampling working. Native code=timeout is normal
expiry, while subprocess/transport errors yield startup_wait_uncertain after revalidation.
Exhaustion without activation evidence yields activation_observation_budget_exhausted.
For authoritative agent_kind exactly `qodercli` only, one exhausted window that remains
idle/done with unadvanced exact sequence instead passes through the user-authorized
bounded stuck-composer recovery: one final exact revalidation gates ONE Enter-only
send-keys nudge (no task text, never a second native prompt, at most one nudge per
turn). Continuity loss, checkout change, observation uncertainty, blocked or uncertain
status, working evidence and sequence advancement each veto the nudge with their
existing classification or ordinary flow. A delivered nudge re-arms ONE fresh bounded
window for the SAME physical turn, Work and handoff; still-unadvanced expiry yields
qoder_activation_nudge_exhausted and a failed nudge transport
qoder_activation_nudge_uncertain, each terminal, honest and never retried. No screen
text, Qoder private logs or task-text heuristics are consulted.
This observation budget is not an Agent-start SLA, submission-failure proof, safe-retry
permission or unconditional end-to-end OS/cleanup bound. The subsequent working barrier,
waiter isolation and historical terminal latch remain unchanged.

The first terminal latch wins. Its state and submission evidence remain available
while the bounded process-local Work record is retained:

- `agent_turn_settled`: proves `agent_turn_settlement_only`.
- `needs_attention`: proves `attention_or_observation_condition_only`.
- `continuity_lost`: proves `exact_continuity_contradiction_only`.

Generic settlement is a qualifying observed transition, not task success, detached-child
completion or result attribution. The Principal verifies substance through direct
repository evidence, dedicated work_report artifacts and bounded agent_terminal_read output. needs_attention does not prove
an Agent failed or that a new dispatch/failover is safe. The exact transient codes
`manual_candidate_read_unavailable`, `manual_candidate_observation_unavailable` and
`manual_candidate_process_unavailable` are revalidated from scratch at most twice,
about one second apart, with total extra delay capped at five seconds. Each retry is
read-only: no prompt, send-keys or other write, and no unlatch of a terminal Work.
A definitive code on the next attempt uses that code's existing classification
immediately. Exhausted transient attempts still latch `needs_attention` /
`observation_unavailable`, proving `attention_or_observation_condition_only`.
Ambiguous candidates and every other non-transient revalidation failure still yield
attention immediately. Unequal available foreground process fingerprints prove
continuity loss. Ordinary
same-group child churn and session churn alone are not execution replacement.
The foreground-job anchor is the PGID plus exactly one leader PID/argv, not a claim
that the leader is the Agent. Herdr may detect an Agent child of a wrapper. Valid optional
aggregate/member CWD observations are separate: absent, matching execution, or different;
non-target raw paths are redacted and CWD changes alone are not process replacement.
No matching child is promoted into the anchor. Shape/PID/argv/count and unique-leader
checks remain required; this grants no authority to a wrapper's external directory.
A dispatched Work retains its selected Git checkout: changed selection or captured Git
identity yields execution_checkout_changed attention, not silent retargeting or process
replacement. Work file evidence remains frozen and independently revalidates that checkout.
Agent-resource report reads remain current and unattributed, not the original Work's result.
These source semantics do not identify any live Pi wrapper, executable or conflicting path.

2026-10-06 live evidence `work-b26dd477fd704192`: one transient observation failure
latched a Work terminal while the Agent was still working. A later
`agent_terminal_read` and a file mtime showed observation had recovered and the
Agent had continued executing. The record is the false-terminal mechanism and the
bounded read-only retry above. It is not acceptance of the unreleased source fix,
and it states no Agent scheduling preference.

Terminal Work releases internal handoff gating. Each exact
project_ref/registered-root pair admits 16 active Work and retains 512 terminal receipts.
At latch, terminal count pressure expires the oldest settled_at receipts and report
bytes, including unread or partly read reports. Reads do not renew retention.
Unknown/nonterminal Work never expires. Internal handoff admission remains bounded at
128 per project; a done-only callback releases latched terminal handoffs and watcher Task
references without cancelling running watchers. See [Work capacity](#work-capacity-and-report-lifetime)
for expiry, tombstones, counts and candidate dependencies. Shared CPU/memory/failure
domains are not isolated; settlement/expiry does not prove external writer cessation.

## Unified delegation and evidence-serving reuse checks

**Several assignments are not one all-or-nothing transaction.** If a later item
is refused, an earlier Agent may already have received its task. Inspect each
receipt rather than resending the whole list. When `PriorWorkDiagnosticsRequired`
blocks reuse of an Agent, read the requested current diagnostics first; merely
reading a report does not prove review or resolve an abnormal condition.

`delegate(project_ref, assignments=[{agent_ref, task}, ...])` is the sole advertised
1..N surface. Fresh catalog parameters require project_ref and nonempty assignments,
with minItems=1 and maxItems equal to existing retained Work bounds. Signature,
advertised parameters and runtime validation all require only project_ref and assignments.
Scalar calls and mixed forms are protocol errors; no hidden compatibility exists.
Unknown fields/non-string values are refused; an empty
list or duplicate cached resource identity refuses before input. Existing retained
Work bounds limit the request. Admission and writer-gated revalidation stay per item;
a later refusal/uncertain transport cannot roll back an earlier external prompt.
Each item reports its actual receipt and submitted/delivery_unknown/not_submitted
outcome. An older Work mentioned by a refusal is existing_work_ref, never implicitly
a newly submitted Work. The list envelope's ok is request processing, not all-item success.

One request-local reservation list captures only this invocation's Works before
prompt mutation. Discarded no-input reservations are excluded; uncertain retained
reservations remain. Cancellation/unexpected exception propagates; surviving Works
remain observable while retained. An abort never reprompts or proves response arrival.

Continue useful independent work, or end the turn if none remains. An explicitly enabled
local browser extension can deliver report-readiness notices; otherwise a user reminder
is still needed.

The optional browser completion feed groups each delegate invocation's newly reserved
Works in the configured project/root. It seals membership when dispatch exits, including
exceptions/cancellation, and assigns one sequence only after all retained members have
final classifications (or authoritative expiry). Unsent reservations are removed; existing
Work refs are never adopted. Feed metadata carries member Work refs, final classes,
current report availability and readable SHA256s, never report bodies or dispatch authority.
The browser sends a short reminder with full batch/Work refs, not the feed's diagnostic fields.
Transient report reads hold that project’s feed sequence and its later sequences; other projects have independent cursors. Once queued, candidates
can be rechecked independently; temporarily unreadable candidates do not delay other ready ones.
Batch metadata is attached to retained Works;
expired members are unavailable, and loss of all members or restart loses batch eligibility.
It adds no retention protection or widget. The extension persists its full Chat route,
cursor, queue and pre-send intent. At send time it may combine ready, unattempted batches
for the same project and Chat without changing delegate membership or waiting for unfinished batches.
Group membership, recipient and notice version are fixed before the first mutation;
an existing intent gains no members. Legacy v1/v2/v3 intent identities remain
nonreplayable; new v4 notices name their source project explicitly. Ready groups
are checked before intent; attempted or uncertain identities are suppressed, never replayed.
A busy-after-prefill rollback requires the same live editor and owned text before and after
withdrawal, unchanged binding/edit state, and no observed submission interference. External
Send/submit interference remains unknown and cannot authorize another send. These are bounded
local DOM observations, not an authoritative host-turn or server-transaction guarantee.
A local Send click is not backend delivery proof; no transcript/receipt scan follows it.
An explicit draft choice is locally handled without claiming a submitted message.
See [extension behavior and local setup](#chrome-notification-authority-and-recovery).

At the final writer-gated resource refresh, scan all retained terminal Works in the
exact project/root with the same stable resource key. Abnormal terminal, uncertain
submission or final report-attention conditions take priority. Without a qualifying
post-condition diagnostic-serving fact, PriorWorkDiagnosticsRequired
refuses before handoff reservation/prompt input; its receipt says no input and directs
agent_terminal_read. Existing nonterminal/resource guards are unchanged. Otherwise
normal result_ready evidence gaps attach a nonblocking prior_work_advisory. Return
one primary gap and an additional_count, not unbounded history or an assertion of unreadness.

Successful nonempty public work_report pages mark report_evidence_served at Work
scope, regardless of chat/session. Internal report probes, errors and empty pages never do.
This is evidence serving, not full report coverage, review or acknowledgement;
reads do not renew retention. Diagnostic reads snapshot relevant
same-resource post-conditions before I/O and verify retained object/condition/resource
identity afterward. The condition signature records its kind, terminal signal and
reason, with no per-chat ledger or last-reader overwrite. Another chat cannot erase
the observation; a changed condition or new Work cannot reuse it. New conditions
arriving during a read do not qualify. This is weak current-terminal serving, not
historical Work attribution, resolution or safe retry. Serving markers retain no raw
session IDs or evidence bodies; session-scoped continuation_inbox visibility stays separate.
Late reports never revise result_class/classification_report_status. A late report
read does not discharge an abnormal diagnostic gate. Ordinary expiry/restart loses
markers together with Work, with no durable history or recovery fiction.

## Request-scoped result inbox observation

**This is a limited view of retained classifications, not an email inbox or a
resume button.** Context may show results correlated with this request's session.
An absent entry or unknown session binding does not prove no work happened.
`classification_report_status` is an earlier classification snapshot, not a live
report check. Read the exact retained report when relevant; do not use repeated
context calls as a wait loop or expect reading to clear or preserve an entry.

Each reserved Work automatically registers one lightweight process-local inbox event
before prompt mutation, keyed by exact project_ref/registered-root and originating
opaque host-session correlation, or an unbound bucket when correlation is unknown.
Final Work classification projects result_class and its report-status snapshot into that event without
another watcher, report probe, retry or change to Work truth. Never-submitted discard
and ordinary Work expiry remove the event and empty bucket. Inbox entries do not pin evidence.

The installed MCP 2.0.0 call_tool Context carries request_context.meta. Bridge reads
only `_meta["openai/session"]` from that per-request mapping; nonempty valid UTF-8
strings up to 4096 bytes are supported. Missing, malformed, oversized or other
value shapes are unknown, with no fallback to transport identity. A process-keyed
HMAC-SHA256 produces the stored opaque correlation; raw metadata/Context is not
retained by this bookkeeping. ContextVar set/reset around the supported SDK tool
invocation isolates concurrent requests and exceptional/cancelled exits. Correlation
propagates through asyncio.to_thread, which copies context; arbitrary threads or
executor submissions do not automatically inherit it. No model-visible session/Context
parameter is added. Equal values correlate only within this process;
metadata is caller-supplied correlation, not authenticated conversation identity,
project authority or proof of host delivery. Live host presence/stability is unaccepted.

`context(project_ref).continuation_inbox` is read-only. A matching known request
session gets binding="session", classified_count, up to 50 retained_classified entries
in reservation order ({work_ref, result_class, classification_report_status}),
has_more and proves="final_classification_only". Every retained final-classified event
is eligible. `classification_report_status` is
only the report evidence observed when final classification became immutable; it is not
current report availability. Abnormal settlement may skip report probing, and a missing
or unknown report can become readable later. `work_report` can observe such late evidence
without revising result_class or classification_report_status.
Report retrieval does not discharge it. A different known session sees only its own
bucket. Unknown requests get only binding="unknown" and unbound_classified_count,
never session-bound or unbound Work refs. Counts cover all retained final-classified
events, not active reservations or probes still pending. No new retention pin is added:
ordinary Work expiry/discard removes the event, and restart loses it.
This slice has no inbox paging argument or discharge endpoint. context neither
processes results, renews retention nor schedules classification. Existing pressure
can expire even unread evidence before review.
The inbox is not durable recovery or a continuation delivery path.

## Checkout admission

**Multiple Agents may share a repository, but their writes are not isolated.**
A checkout is the working folder of a Git repository. Admission only means the
Bridge resource checks allow dispatch; you still need explicit task scope and
coordination for overlapping edits. Another Work becoming terminal does not
prove that all external writers have stopped or make a conflicting edit safe.

A known nonterminal Work in the same checkout, including aliases, no longer rejects
dispatch: distinct Agent resources may hold concurrent in-flight Work in one checkout.
Same-resource protection is unchanged — a nonterminal Work or unconsumed handoff for
the same Agent handle/resource still rejects a duplicate prompt. The project writer
gate around dispatch admission and frozen-target revalidation remain after public run
retirement.
No new ownership registry or indefinite uncertainty lock follows. Generic settlement,
needs_attention and continuity_lost do not prove cessation of manual/detached writers.
[Observation contracts](OBSERVATION-TOOLS.md) describe fixed-query evidence limits;
[tool reference](TECHNICAL-REFERENCE.md#tool-reference) lists the retained effect boundaries.
Source tests are not live client acceptance and do not add Work recovery.

Existing candidate pages and same-message attempted receipt replay have a separate
process-local lifetime: project authorization and the candidate's frozen route/request
checks permit cached history after Work expiry, without candidate Git mutation/inspection,
Work resolution, recapture or rebinding. Entry still first performs current project
authorization/WorkspaceRegistry identity validation, which executes bounded read-only
Git identity checks; the whole call is not Git-free.
Unattempted commits still reject expired Work. Candidate eviction makes its history
unavailable; Work GC never releases unknown-attempt quarantine. Reading a receipt does
not establish external cessation or safe retry. See [Work capacity](#work-capacity-and-report-lifetime).

## Restart and uncertainty

**If an old reference stops working, preserve the question “what happened?”**
`WorkRefUnavailable` is not a failed-task receipt. Do not send the assignment
again, cancel an Agent or restart another service just to obtain a cleaner
answer. Read authorized current evidence and separate it from the dated receipt.
Project notes may preserve a decision and next boundary, but cannot reconstruct
the lost Work. The extension's separately stored consumed notice IDs also remain
non-replayable; restarting the browser is not a reset of send permission.

Work, opaque Agent refs, gates, batch subscriptions and delivery consumption are
process-local. An unknown work_ref
returns WorkRefUnavailable: never issued here, lost after restart, or expired beyond
bounded tombstone retention. A known expired receipt returns WorkRefExpired. Both leave
external work fate unknown. Do not rediscover/rebind/resubmit/cancel the external Agent to guess
what happened. A lost delegate response also remains ambiguity by contract; there is
no auto-redelegation. Bridge does not add durable Work recovery, a scheduler
or platform wakeup. Process-log events (batch waits/claims, Work
terminal latches) are not a durable journal and do not survive restart. Project-local checkpoint persists Principal-supplied state, not Work
identity or recovery. Replacement does not automatically archive overwritten uncommitted
history; see docs/PROJECT-CONTINUITY.md. Current acceptance requires separate live evidence.

Observation uncertainty and transport failure never authorize external interruption,
cleanup, resubmission or silent backend switch. No managed lifecycle or specialized
Codex/Pi start/resume/cancel/recovery API remains. User sessions, stored data/config and
installed extensions remain untouched by source retirement. Herdr is the host boundary;
this slice leaves host/YOLO operation unchanged and adds no execution permission system.

## Bootstrap and deployment evidence

**Check the layer you need.** A successful initialized `bridge_health` tool
result establishes Bridge responsiveness separately from Herdr connectivity. Agent discovery may
be partial or unavailable, and code on disk need not be the running version.
For Web use, still verify the actual ordinary Project Chat's tools and four
Skills through Getting Started. None of these read-only observations grants
permission to deploy, restart or refresh an existing connection automatically.

bridge_overview defaults to the configured root and supports an explicit registered
project_ref. It shares compact generic candidate discovery with context, including linked checkouts, and distinguishes unavailable discovery from
partial coverage and complete observations. It retains direct repository, running Bridge
PID/start time, system-service PID/start time and default-root control-document pointers.
Both views require current backend coverage counts: `out_of_project`,
`invalid_or_unavailable`, and `truncated`. Validated foreign-project exclusions do not
reduce coverage; malformed/unreadable/ambiguous candidates and truncation do. Projection
failures also count as unavailable candidates. Missing/malformed counts fail closed,
without a legacy zero-count fallback or a claim of complete discovery.
Proven foreign exclusions reuse existing candidate identity rules, including supported
same-common-Git linked checkouts across reported and foreground CWDs; path inequality
alone is not a contradiction. All raw kinds, including Pi, independently validate both
CWDs in the same Git boundary, selecting foreground when present, otherwise reported.
Actual cross-project target conflicts, malformed session/name/locus and malformed process
evidence still fail closed; process CWD relations do not redefine the selected Git target. Foreign exclusions do not query foreign processes.

Context's agents_rejection_diagnostics and snapshot's observation.rejection_diagnostics
share fixed stage/reason counts, at most eight local kind/hint details, explicit
unlocalized/omitted-local counts and candidate truncation. Only independently proven
selected-project membership plus valid locus permits a local detail; ambiguous duplicates
and foreign/unknown scope receive counts only. Rejected candidates receive no handles.
Raw exceptions, paths, names, argv, sessions and task text are not diagnostic fields.
Missing/malformed diagnostics are unavailable, not invented zero reasons. Public
projection failures count as unlocalized rejections. Whole snapshot failure remains
unavailable; malformed individual entries have a snapshot reason count. Existing
pane-only candidates with unavailable process evidence remain visible with their original
continuity limits; rejection diagnostics do not redefine roster or execution health.
No extra host queries, candidate registry, endpoint or live probe follows from diagnostics.
No legacy task/session ownership or Pi permission projection drives this roster.

Agent rows expose validated native workspace id (no inferred workspace name) alongside
the tab/pane hint and a display-only checkout observation. Existing discovery Git facts
are reused without added Git identity calls; bounded filesystem object/pointer checks
bracket one porcelain-v2 branch/HEAD/status command, fixed to the already-validated
Git directory and checkout root. A successful complete read yields
`observed`; failed/incomplete reads yield `unknown`, detected path/object changes yield
`changed`, and shared budget exhaustion yields `deferred`. Non-observed values are null,
including dirty; observed null branch denotes detached HEAD.

One discovery shares a 1-second enrichment deadline, at most 16 unique checkout attempts,
and four workers. Each command receives at most 0.25 seconds and the remaining budget.
Unique checkouts are considered in snapshot order; concurrent workers keep one slow tree
from blocking other slots, without claiming cross-call scheduling fairness. Deferred
metadata never removes Agent rows or changes coverage. Deadline/cancellation joins native
process cleanup (up to its existing 0.65-second grace, subject to OS scheduling); OS calls
and existing discovery validation are not covered by a hard wall-clock SLA. No background
enrichment is retained. This display optimization does not change authorization, binding,
dispatch revalidation or capacity. It is neither an atomic
filesystem baseline nor a writable guarantee; HEAD is only the current commit and
worktrees are not OS isolation.

bridge_health separates Bridge responsiveness from observed Herdr connectivity and
reports actual registered tools, without hidden-callability counts.

Code on disk, the running service, and the current client-bound tool schema are separate
evidence. Source tests do not prove deployment or client refresh. Before any separately
authorized deployment, obtain exact live runtime and Git evidence and use the current
operational instructions; never restart as an automatic recovery from ambiguity.

## Evidence limits and retired APIs

**When a guide or old receipt mentions a removed API, stop at that mismatch.**
Do not invent a replacement call or assume a removed recovery feature still
exists. Use the current installed tool schema, retain the uncertainty and keep
any new action within explicit authority. Source behavior and synthetic test
coverage are not proof of your live service or browser behavior.

This public source tree does not include private acceptance artifacts or legacy
managed-lifecycle implementations. Retained discovery, checkout admission,
in-flight guards and observation boundaries are described above; source tests
exercise their cases without certifying any deployed host or client behavior.

The generic transport still lacks an atomic expected-instance guard and PID birth
identity. No-retry is intentional; generic settlement proves neither task success nor
detached-child completion. Removing APIs does not add stronger guarantees.
No widget wait segment or durable continuation grant remains. Extension injection and reminder delivery
require separate live evidence for the actual client binding.
Revisit stronger identity/continuity behavior only with actual task need, evidence and
separate authorization; removed APIs are not recovery options.

## Work capacity and report lifetime

**Read useful results while they are available.** Bridge keeps a bounded set of
Work records, not a permanent task archive. Count pressure can remove even an
unread report, and reading does not extend its lifetime. Preserve accepted,
decision-relevant conclusions and evidence locations in authorized project
records; do not treat a Work reference as durable memory or create more Work to
reconstruct missing evidence. The exact limits and errors below still apply.

Each exact explicit project_ref + registered workspace_root pair has separate limits:

| Layer | Default | Lifetime |
| --- | ---: | --- |
| Active Work | 16 (`MAX_ACTIVE_WORK_RECORDS`) | All states outside WORK_TERMINAL_STATES, including reservations and unknown dispatch; never expired |
| Terminal receipts | 512 (`MAX_TERMINAL_WORK_RECORDS`) | Terminal receipts expire earliest settled_at first under count pressure, including unread reports; ties preserve insertion order |
| Expired tombstones | 512 (`MAX_EXPIRED_WORK_RECORDS`) | Oldest expiry entries removed under count pressure; only ref and project/root binding retained |
| Internal handoffs | 128 (`MAX_HANDOFF_RECORDS`) | Completed watcher + terminal latch permits immediate reference release |

The 512 defaults are bounded operational choices, not permanent promises or byte quotas.
There is no TTL or guaranteed minimum age. Report reads and browser notifications
never renew retention. Fixed delegate notification batches preserve membership,
not report lifetime. Completing sequential Work does not exhaust active admission.
Unknown/nonterminal Work retains active-admission counting. `_reserve_work` counts
and inserts synchronously before any native prompt, without an intervening await.
WorkRegistryFull reports scope=project, dimension=work_active and active count/limit
before prompt. Every admitted Work receives a dedicated report allocation.
Full handoff storage reports WorkDispatchBlocked with
handoff_retained count/limit; the never-dispatched Work reservation is discarded.
Other projects do not consume this pair's quota. No second global record pool is added.

Internal terminal receipts retain settlement fields, submission uncertainty, project
binding, execution identity and EvidenceCheckout. There is no public await endpoint
or report-request flag. Internal repeated receipts are field-identical while retained.
A dict already held by an internal waiter remains valid even after its registry index
expires; cancellation detaches only that waiter.
Frozen checkout identity is not a snapshot of file contents; evidence calls revalidate it.

The watcher completion callback releases a handoff only when its Task is done and its
terminal is latched into Work. It never cancels a running Task, even when an injected
terminal or pressure arrives first. Callback registration handles fast completion and
uses an empty callback context; registry references to completed Task ContextVars and
candidate snapshots are released without making await a cleanup operation. A still-running
watcher retains its handoff and the 128 bound remains enforced.

Known expired refs return WorkRefExpired. If no receipt or tombstone remains, including
never-issued refs or restart loss, WorkRefUnavailable preserves the possible causes.
Wrong-project retained receipts/tombstones reject with WorkRefProjectMismatch. Expiry
proves only loss of a Bridge-local receipt, never task success/failure, external cessation,
acceptance, cancellation or safe retry. No rediscovery, retargeting or resubmission follows.
read/search/diff, new previews and unattempted commits share this lookup; expired refs never fall back to
an Agent or the registered root. In-flight evidence holds its already-resolved frozen
target; a later lookup/page may reject expiry, never silently select another target.

Candidate storage and unknown-attempt quarantine are independent of Work retention.
GC neither removes a candidate nor releases its quarantine. Existing summary/patch/receipt
pages use the candidate's frozen target and exact project/work route after current project
authorization. Same-message attempted receipt replay returns the identical cached result.
Both historical pages and replay perform no candidate Git mutation/inspection, Work
resolution, recapture or rebinding.
Entry still first performs current project authorization/WorkspaceRegistry identity
validation, which executes bounded read-only Git identity checks; the whole call is not
Git-free. Different messages reject. This history
remains readable after WorkRefExpired or WorkRefUnavailable. Unattempted commits still
require retained Work. Candidate eviction under its own 8-entry/32-MiB policy returns
candidate-unavailable-no-recapture; unknown attempts remain protected. No cache is durable,
no pin extends Work lifetime, and historical receipts do not establish external cessation
or safe retry. Expiry during a new attempt retains existing rejection/unknown semantics.

context and bridge_overview project_state expose compact work_capacity counts
and policy, without listing refs in that capacity field. Separately, context's
continuation_inbox provides a bounded session-matched retained-classification view
as defined by the [lifecycle contract](#request-scoped-result-inbox-observation).
The index stores one lightweight event per retained Work and removes it on existing
Work discard/expiry, with no separate admission quota, delivery owner, retention pin,
read renewal or discharge mechanism. All retained classified results remain visible
regardless of whether a notification was attempted or received. Visibility does not
prove report retrieval or result processing. Unknown requests expose only an unbound
retained-classified count, never another session's refs. Ordinary Work expiry/discard
still removes the event; visibility adds no protection. These observations are process-local,
not reservations or an atomic snapshot of Git/Agents. Capacity counts do not certify memory-byte, CPU or
cross-process isolation; record-count bounds do not certify real second-project operation.
There is no work_forget/prune tool, durable Work storage, scheduler or restart recovery.
Long-lived decisions/evidence belong in project records, not an assumed permanent ref.

### Private report lifetime

**A complete report may require several pages.** Read the returned pages using
the original full-report hash and the returned continuation offset; a first page
or a terminal tail is not the complete result. Missing/invalid report errors need
inspection, not a substituted provider transcript. A saved report's presence and
hash prove bytes, not author identity, task success or truthful claims.

Every admitted Work requests publication into a random basename in a lazily created
per-process 0700 `/tmp/bridge-reports-*` directory outside project checkouts. Only that Work's private
basename is retained internally; public receipts and errors expose no filesystem locator.
The Agent gets final/staging paths in the augmented dispatch task. Agent access to the private host path is a
prerequisite; Bridge does not configure sandboxes or bypass a publication refusal.

`work_report` validates project identity and Work binding, requires a terminal Work, and
reads at most 1 MiB plus an overflow-detection byte from a nofollow, nonblocking regular
file descriptor. Symlinks, special files, multiply linked files, invalid UTF-8, empty
reports, overflow and observed file replacement/change fail explicitly. Unicode pages
default to 4096, maximum 16384 characters; expected_sha256 checks the full original report
bytes. Pre/post stat and path-binding checks plus hashes do not isolate same-user Agents
or authenticate authorship. A published report need not match the provider's final message.
`work_report` observes once per call; it does not wait for publication or run a retry
loop. After the latch, classification probes `WorkReportMissing` before final classification:
one initial read plus at most two rechecks about one second apart. Added retry waiting
stays within five seconds; that cap is not an OS I/O wall-clock guarantee. The probe
does not renew retention. A missing or invalid report classifies `attention_required`.
Terminal Work and reports, including unread ones, expire oldest settled_at first
under terminal-count pressure. Browser queues do not pin the underlying report.

Discard of a never-submitted Work and terminal receipt expiry unlink its final/staging
files where possible. Read/cleanup are serialized; expiry racing a read may leave that
in-flight call with a missing report, never another Work's report. Reads do not renew
retention. Graceful whole-server shutdown closes the current process store exactly once
during the ASGI/MCP application lifespan teardown, after normal MCP/session-manager
teardown and before Uvicorn re-raises SIGTERM; the idempotent close unlinks only known
final/staging basenames and then attempts directory cleanup, with atexit as a secondary
best-effort net. Crashes, SIGKILL, power loss, unlink/rmdir failures, permission changes
or late Agent writes can still leave orphaned files — that residual is explicitly
accepted; unknown names are never removed and no secure erasure is claimed. There is
no startup scan, and restart never scans, recovers or purges old orphans.
There is no durable store, new TTL, report reservation pin, auto-resubmission or pane fallback.
The 1 MiB cap is a read/publication contract, not an OS disk quota on an external writer.
The internal settlement latch remains immutable and independent of report classification.
Reading a report neither consumes delivery eligibility nor changes its assigned class.

Regression coverage: tests/test_work_retention.py, tests/test_work_capacity.py and the
Work/evidence/candidate suites exercise synthetic backend and disposable Git behavior.
Source tests do not certify deployed behavior, actual provider capacity or
external writer cessation.

### Fixed notification batches

**Example:** two tasks sent in one delegate call keep that membership even if
one settles first. A notice can cover the ready batch; it does not extend either
report's lifetime. An unavailable member remains unavailable instead of being
rerun to fill the gap. Different projects are never combined into one reminder.

One delegate invocation fixes its notification members. A ready batch can be queued
and same-project/same-target ready unattempted reminders can merge. This does not
add a retention owner, widget claim, delivery-consumed flag or acknowledgement API.
An expired member remains unavailable under the existing report contract; no old
Work is recreated or dispatched again to fill missing evidence.

## Chrome notification authority and recovery

**For first use, follow [Getting started step 9](GETTING-STARTED.md#9-load-the-private-extension-and-bind-this-exact-chat).**
In the browser popup select the registered project, check the current exact Chat,
then explicitly enable it. Expect the recipient/current-tab/enabled indicators,
not a retroactive replay of completed tasks. Bind before new delegation; first
enable skips earlier events. If the recipient or permission is wrong, stop before
sending another task. The rules below cover switching, drafts, queues and
uncertain outcomes; none authorizes clearing storage to repair a missing notice.

The optional MV3 extension observes completion metadata, not report bodies or
Agent execution authority. One installation supports up to 32 currently
registered local projects. After approval, `./prepare` creates the local application/venv and extension files
and installs, enables and starts the two systemd services on supported Linux.
Registration through project-onboarding and an explicitly authorized Project Binding
are separate; preparation does not start Herdr or Agents.
The trusted live registry supplies canonical ref/root identities without another
manual project list or restart. Legacy v1/v2 configurations retain their original
scope until explicit metadata-scope migration; v3 authorizes future registrations.
The private 0600 browser-notifications configuration and installed `connection.js`
share a separate read-only loopback feed capability, not the MCP token or runtime
key. The public source connection is null. Never publish those private bytes.

The user selects a registered project and one exact ordinary, non-private Chat
(including any Project prefix), consents, then clicks **设为接收 Chat 并启用**.
Only one ordinary tab may match that full route. No latest-tab/title/slug guess,
automatic prompt-based binding or broadcast exists. First enable skips earlier
completed events: bind before delegation. Binding verifies route/document identity
without typing or sending and does not prove the page is ready to send.
The popup shows recipient/current-tab/enabled state without the full URL, plus
current actionable errors and unfinished-notification diagnostics. Settled real
notification rows, history/receipt controls and standing old-unknown warnings are
retired. Disable preserves pending work and suppression evidence and waits for that
project's current operation; it cannot retract an uncertain in-flight mutation.

Explicitly selecting a new current Chat and authorizing enable changes the future
recipient without sending during the switch or resetting cursor/epoch. Only
provably never-attempted queued/waiting reminders with a valid saved route and no
intent/frozen evidence may follow for their first send. Attempted, ambiguous or
frozen identities are never migrated or replayed, even on returning to the old
Chat. Existing stored real history is safely normalized to raw-ID suppression
evidence rather than reoffered. A passive old unknown, including an unattributed
old attempt, does not pause unrelated new real Work. Malformed scope, cursor,
suppression IDs or genuinely ambiguous live pending state still fail closed.

Each ref/root retains an epoch-scoped feed cursor, only the active unattempted or
undecided queue, and durable consumed raw Work/batch IDs. The 128 bound applies
to that live pending queue, not historical deliveries. Feed progress is saved
before mutation; a cursor alone cannot suppress a retained ID reappearing after
an epoch reset. Consumed identities therefore survive worker/browser restart,
producer epoch changes and explicit recipient switches, with no arbitrary ID GC.
Storage/quota failure still stops safely; do not clear evidence to bypass it.

A verified synchronous Send.click() invocation is locally handled once, never
"ChatGPT received" or server acknowledgement. There is no post-click transcript
or user-message receipt verification. An ambiguous invocation is suppressed too,
without claiming a successful click. This accepts possible loss if ChatGPT does
not deliver after the click; neither case authorizes automatic retry. Old unknown
identity evidence is silent and does not occupy historical-row slots.

A truly empty, safe composer may automatically send once. Visible Stop is busy;
other unsafe composer/route/document/control conditions refuse under their actual
reasons. Active IME prevents empty-editor auto Send, but real text/rich/attached
file drafts show the non-focus-stealing **追加到输入框末尾（另起一行） / 忽略** choice
even during typing or IME. Ignore leaves the current draft/files untouched. Append
after active composition ends adds only the fixed notice paragraph to the current
bound editor without Send, flattening or draft/File snapshots; normal edits and
attachment changes do not need a quiet timer. No draft or file content goes to
the worker. A user submit after the choice but before asynchronous Append refuses
that stale choice before mutation. Unknown append/ACK effects never retry.
Undecided work survives document refresh/close; normal polling revalidates the
exact recipient and reoffers, or uses the current safe empty-editor path.

Different projects never merge, even with the same Chat. Ready unattempted
batches for one project/Chat may share a fixed notice while retaining every Work
and batch identity. Transient report failure holds that project's feed order;
already queued candidates can be checked independently. Before any DOM effect,
durable intent consumes the selected identities. Old notice versions remain
parseable without replay; new v4 names project and full Work refs. Report reads
are not acknowledgements of Principal processing.

Automatic Send still rejects attachments, unowned selected files, wrong/duplicate
editors or primary controls, changed bindings and concurrent edits. Safe prefill
withdrawal requires the same page, binding, editor and exact owned text with no
external submission interference; changed nodes/edits or uncertain effects remain
suppressed. These are local DOM observations, not server transactions or proof of
future hydration. A draft restored before commit or during prefill prevents Send;
no pre-click DOM check can guarantee a draft will not restore after the click.
Offline inspection is not send authority; cached registry data cannot authorize
new sends. Invalid roots or reusing a ref with another root refuse rather than
inheriting Chat consent. Storage failure remains explicit.

Native IndexedDB transactions compare prior state/revision before publication.
A one-way chrome.storage migration witness refuses fallback when the database
is lost; original legacy storage remains a migration source. Native Web Locks
serialize route→project operations and same-recipient sends across workers.
Worker termination releases locks; database transactions complete or abort under
native semantics. No lock API means refusal, not timed lock stealing. A paused
or old unknown send never becomes safe through a restart or migration.
Legacy rows lacking trusted old-root proof stay disabled pending reauthorization;
adding proof does not enable them automatically. Diagnostic synthetic sends are
restricted to the legacy bootstrap project and retain their original scope/alarm;
normal projects do not acquire diagnostic send authority.

Fresh preparations use the fixed keyed manifest identity. Legacy adoption must
be separately authorized with the original loaded directory: preserve its key
or keyless path identity, private pairing and history, and back up reviewed code.
The preparer never changes browser storage; unsafe permissions or unknown code
changes stop update. Chrome reload is an explicit user action, not a source-test
result. Never uninstall, relocate or clear storage to bypass unknown intent.

Alarms normally wake the worker each minute; Chrome MCP or a resident Codex is
not required. Complete reports still require Bridge MCP. Synthetic DOM/transaction
tests do not establish real delivery, overlapping Chrome workers, changed host UI,
non-English DOM, background gates, node replacement or tool-wait timing. Field
acceptance remains separate; no Work Chat/API substitute is implied.
See [first-use binding](GETTING-STARTED.md#9-load-the-private-extension-and-bind-this-exact-chat).
