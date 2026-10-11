# GPT-Agent Bridge lifecycle and restart contract

Status: source contract for the retained generic Work path. Specialized and
compatibility MCP endpoints are absent, including hidden callability.
This document describes current source behavior and its evidence limits. Source
inspection and tests do not certify a deployed service, backend version or client acceptance.

## Resource and Work identity

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
returns per-item receipts with one invocation-level `continuation`. Each retained
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
their existing fields and add continuation/advisory metadata. Internal Work records keep settlement state, reason and
submission evidence; there is no public per-Work await tool or report-request flag. Settlement
does not wait for a report, and readable report bytes prove presence only, never task
success or truth.
Report retention/cleanup follows
[Work capacity](WORK-CAPACITY.md). No generic Agent startup or output interception is added.
An immediate post-settlement `work_report` can transiently be WorkReportMissing if the external
publication rename lands just after settlement. `work_report` itself remains one
observation per call, without publication waiting or an automatic retry loop; missing
does not prove permanent absence. Classification probes the dedicated report after
the latch and before a batch is ready, without sleeping under the Work registry lock.
`WorkReportMissing` is the only transient candidate: an initial read plus at most two
extra rechecks about one second apart. Added retry waiting stays within five seconds.
The cap bounds those injected waits, not OS I/O wall-clock time. Other report-read
errors classify immediately as `invalid` or `unknown`. A readable report with
`agent_turn_settled` is `result_ready`. `needs_attention`, `continuity_lost`, and a
missing or invalid report are `attention_required`. The class is set once. Duplicate
widget mounts share one consume-before-send grant.

## Submission evidence

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

## Batch wait segments and terminal evidence

The per-Work await endpoint and its internal receipt/wait helpers remain removed
without aliases. App-only `wait_work_watch` observes an explicit immutable batch in
one event barrier segment, bounded by BRIDGE_AWAIT_LEASE_SECONDS (default 90 seconds;
valid finite range 1..600). Neutral `{ready:false}` consumes nothing. The widget
reattaches after neutral segments; there is no timer, watchdog or progress polling.
Transport errors stop that instance. Cancellation detaches only that waiter.

Watch lifecycle diagnostics journal `bridge.work_watch_arm`,
`bridge.work_watch_reuse`, `bridge.work_watch_overlap`, `bridge.work_watch_ready`,
`bridge.work_watch_claim` and `bridge.work_watch_retire`; resolved waits retain
`bridge.work_watch_wait`. Each event includes project_ref, watch_ref, frozen
work_refs, member_count, truncation flags and outcome. A synchronous-ready result
without a subscription has watch_ref=null; it does not invent a watch. Overlap
logs the existing owner's frozen membership plus the refused requested_work_refs.
Retirement distinguishes member_expired from member_discarded. Membership logs
are capped at 528 refs (the default terminal-plus-active bound); larger synthetic
bounds are explicitly truncated. Request and original-watch session correlation
appear only as 16-hex fingerprints, or null when unknown. Diagnostics are frozen
as bounded immutable JSON under the registry lock at each transition, then emitted
after leaving the outer critical section. Nested expiry/discard retirement returns
capture-only diagnostics to its caller; it never invokes a logger under that lock.
A blocked logger may delay its caller, but must not hold the global Work registry
lock. Capture/logging failures do not change ownership, consumption or cleanup.
Concurrent emitted lines may interleave; each payload preserves its captured state.
These diagnostics prove local state
transitions, not host mounting, follow-up delivery or model wake.
Startup retains one bridge.await_lease configuration event for the reused lease setting. Each first terminal latch emits one
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

A transient observation failure can occur while an Agent continues executing.
The bounded read-only retries limit immediate false-terminal classification;
exhausted uncertainty still latches attention. A later terminal read or changed
file mtime is a new observation: neither revises an already terminal Work nor
attributes task completion. Synthetic regression cases exercise the retry and
latch rules, not a guarantee of observation recovery or external writer cessation.

Terminal Work releases internal handoff gating independently of delivery consumption. Each exact
project_ref/registered-root pair admits 16 active Work and retains 512 terminal receipts.
At latch, pressure expires only consumed terminal receipts, oldest settled_at first;
undelivered or batch-owned report evidence is protected and admission backpressures. Reads do not renew.
Unknown/nonterminal Work never expires. Internal handoff admission remains bounded at
128 per project; a done-only callback releases latched terminal handoffs and watcher Task
references without cancelling running watchers. See [Work capacity](WORK-CAPACITY.md)
for expiry, tombstones, counts and candidate dependencies. Shared CPU/memory/failure
domains are not isolated; settlement/expiry does not prove external writer cessation.

## Unified delegation and evidence-serving reuse checks

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
a cohort member. The list envelope's ok is request processing, not all-item success.

One request-local reservation list captures only this invocation's Works before
prompt mutation. After dispatch attempts, shared watch registration atomically freezes
its retained membership and returns continuation ready or armed, or an explicit
continuation_error with all dispatch receipts retained. No new scheduler exists.
Discarded no-input reservations are excluded; uncertain retained reservations remain.
Cancellation/unexpected exception propagates and skips registration entirely:
surviving Works retain their delivery eligibility and evidence protection, including
already-ready members. No phantom synchronous delivery or follow-up is manufactured.
Later context/report observation can recover retained evidence; an abort never
reprompts or proves response arrival. Later assignments/Works never join. Multiple auto cohorts
cannot be implicitly merged under existing unresolved-overlap rules.

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
reads neither consume delivery nor renew retention. Diagnostic reads snapshot relevant
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

A successful app claim now includes a random opaque attempt_token. The stopped widget
makes one best-effort record_work_watch_send_outcome call after its send attempt,
with host_accepted, host_rejected_or_unknown or unavailable. It is token/project/watch
bound, first-outcome immutable and idempotent for identical repeats; conflicts refuse.
No feedback response authorizes retry/regrant or alters retention/classification.
These are client assertions, not authenticated host/model-wake evidence. Missing
feedback stays unknown; no timer, retry queue, polling or automatic nag is added.
Same-Agent reuse gating/advice depends on evidence serving, not host acceptance.
Source tests exercise delegate render binding, same-chat continuation and bounded
feedback behavior; they do not certify live host delivery or feedback ingestion. Only same-version
server/widget/schema operation is supported. Mixed versions are unsupported. A
missing attempt token is a malformed grant: stop without send, regrant, feedback or
fallback. A consumed grant remains consumed. Source checks alone do not establish
live-host behavior.

## Internal immutable cohort continuation

Delegate automatically registers the retained Works created by that invocation.
There is no public watch_works tool and no follow-on model-visible watch step.
Internal _register_work_watch validates a nonempty distinct list of existing Works
in the exact project/root atomically: unknown/expired/wrong-project/malformed/duplicate
refs refuse without partial arm or consumption. Membership is bounded only by actual
retained Work resource bounds (512 terminal plus 16 active by default).

Classification is Work-owned and starts after the immutable terminal latch.
agent_turn_settled plus a readable mandatory report is result_ready. Other terminal
signals or missing/invalid/unknown report evidence are attention_required. Abnormal
signals skip probing, so unknown report status is not an assertion of absence.
Missing-only bounded publication-race rechecks are unchanged. Class assignment is
once-only: late report reads do not revise it, and original submission uncertainty
remains independent.

Strict all-of readiness requires every selected Work's final class. A terminal
Work whose report probe is pending is not ready. Attention never wakes early.
Unwatched Work and delegates after arming neither join nor delay this batch.
A Work that never classifies leaves the batch pending indefinitely.

A ready continuation returns `status:"ready"`, result_ready refs, attention_required
summaries with recorded signal/report_status/reason and Agent handle where present,
`proves:"final_classification_only"`, and a factual notice. It consumes delivery
eligibility synchronously and creates no subscription/follow-up. An armed continuation
returns `status:"armed"` with frozen member refs; the opaque process-local watch_ref
exists only in app-side hydration. It prepares one batch widget binding regardless
of member count. Delegation is not a yield command. The
Principal may keep doing useful independent work, or end the turn if none remains.

Identical active membership sets reuse one subscription and frozen order. Another
batch overlapping an unresolved owned member is refused. Already-classified members
may support another batch; both owners protect their terminal evidence. Membership
is immutable, with no question, open/planning stage, editing, sealing or Decision
projection. Subscription records are removed when a member expires/is discarded;
active ownership prevents ordinary terminal-pressure expiry. No independent group
quota or durable subscription store is added.

Only delegate binds the single `ui://bridge/work-batch-watcher/index.html`
render binding. context remains UI-free. Armed result metadata carries
`bridge/workWatch` with project_ref/watch_ref/work_refs; initial/passive host updates
freeze one valid batch per iframe. Ready results have no hydration; a host may still
briefly mount a card/iframe because the descriptor is statically bound. Source tests
prove no observer starts from a ready result, not literal zero host mounting.

The raw catalog has 21 tools, 18 declared model-visible. App-only
`wait_work_watch`, `claim_work_watch` and `record_work_watch_send_outcome`
have no resourceUri. Visibility is audience guidance, not authentication. Retired
project notice helpers, public watch_works/scalar watch, Decision tools and
model-visible await have no aliases. Delegate accepts only assignments and returns
per-item receipts with automatic continuation without waiting. Useful independent
work can include further delegation.

A wait returns neutral ready:false, full all-ready membership, consumed status or a
lookup error. Previews consume nothing. The widget serializes waits/claims and
requires every frozen member exactly once in final summaries. The atomic per-watch
claim revalidates all-of and consumes once under the registry lock. Duplicate mounts
share it. Only the grant authorizes one sendFollowUpMessage attempt; missing host
continuation, failed/ambiguous sends remain consumed. The widget stops permanently
after sending or consumed denial, with no post-send resume, resend or confirmation.
Prepared hydration/consumed grant proves neither host mount nor delivery/model wake.

The same formatter produces synchronous ready presentation and widget follow-up.
Normal wording names work_report without claiming task success. Attention identifies
affected Work and, only for recorded valid Agent handles, advises inspecting that
Agent before delegating to it again. Unknown report status never becomes a fabricated
missing-report assertion. Report bytes are read separately; notice text contains no
Agent report/task body or instruction to redispatch or rewatch.

Undelivered terminal evidence and terminal members owned by pending batches remain
protected. Active plus protected terminal evidence accounts against the existing
512 budget; adding ownership to an already-delivered member checks the same budget.
Admission backpressures with delivery_retention before prompting. Synchronous ready
delivery or successful batch claim releases protection only where no other owner
remains. Subsequent pressure may expire delivered receipts/reports before retrieval.
work_report remains non-consuming/non-renewing; no acknowledgement or new retention
protocol is added. Unarmed/abandoned evidence can backpressure admission.

Work/classification/watch/grant state remains process-local. Restart, member loss and
expired subscription lookup fail closed, with no outcome inference, recovery,
retargeting or redelegation. Readiness is classification, not success or external
writer cessation. Source tests do not certify host mounting, caching/remount
behavior or live abnormal/ambiguous-send branches.

## Request-scoped result inbox observation

Each reserved Work automatically registers one lightweight process-local inbox event
before prompt mutation, keyed by exact project_ref/registered-root and originating
opaque host-session correlation, or an unbound bucket when correlation is unknown.
Final Work classification projects result_class and its report-status snapshot into that event without
another watcher, report probe, retry or change to Work truth. Never-submitted discard
and ordinary Work expiry remove the event and empty bucket. Inbox entries neither
own a watch nor pin evidence; existing watch consumption/retention stays unchanged.

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
in reservation order ({work_ref, result_class, classification_report_status, delivery_consumed}),
has_more and proves="final_classification_only". Every retained final-classified event
is eligible regardless of notification consumption. delivery_consumed is a separate
boolean reflecting the existing delivery grant state, not report retrieval, result
processing, task success, or verified host delivery. `classification_report_status` is
only the report evidence observed when final classification became immutable; it is not
current report availability. Abnormal settlement may skip report probing, and a missing
or unknown report can become readable later. `work_report` can observe such late evidence
without revising result_class, classification_report_status, or notification consumption. A successful claim with a lost
response/send and unread report remains visible; so does a synchronous-ready result.
Report retrieval does not discharge it. A different known session sees only its own
bucket. Unknown requests get only binding="unknown" and unbound_classified_count,
never session-bound or unbound Work refs. Counts cover all retained final-classified
events, not active reservations or probes still pending. No new retention pin is added:
ordinary Work expiry/discard removes the event, and restart loses it.
This slice has no inbox paging argument or discharge endpoint. context neither
processes results, consumes delivery, renews, schedules classification nor creates a
widget/follow-up. Existing pressure can still expire delivered evidence before review;
inbox visibility does not justify regranting or resending an ambiguous notification.
The inbox is not durable recovery or a new continuation delivery path.

## Checkout admission

A known nonterminal Work in the same checkout, including aliases, no longer rejects
dispatch: distinct Agent resources may hold concurrent in-flight Work in one checkout.
Same-resource protection is unchanged — a nonterminal Work or unconsumed handoff for
the same Agent handle/resource still rejects a duplicate prompt. The project writer
gate around dispatch admission and frozen-target revalidation remain after public run
retirement.
No new ownership registry or indefinite uncertainty lock follows. Generic settlement,
needs_attention and continuity_lost do not prove cessation of manual/detached writers.
[Observation contracts](OBSERVATION-TOOLS.md) describe fixed-query evidence limits;
[tool reference](../README.md#tool-reference) lists the retained effect boundaries.
Source tests are not live client acceptance and do not add Work recovery.

Existing candidate pages and same-message attempted receipt replay have a separate
process-local lifetime: project authorization and the candidate's frozen route/request
checks permit cached history after Work expiry, without candidate Git mutation/inspection,
Work resolution, recapture or rebinding. Entry still first performs current project
authorization/WorkspaceRegistry identity validation, which executes bounded read-only
Git identity checks; the whole call is not Git-free.
Unattempted commits still reject expired Work. Candidate eviction makes its history
unavailable; Work GC never releases unknown-attempt quarantine. Reading a receipt does
not establish external cessation or safe retry. See [Work capacity](WORK-CAPACITY.md).

## Restart and uncertainty

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

This public source tree does not include private acceptance artifacts or legacy
managed-lifecycle implementations. Retained discovery, checkout admission,
in-flight guards and observation boundaries are described above; source tests
exercise their cases without certifying any deployed host or client behavior.

The generic transport still lacks an atomic expected-instance guard and PID birth
identity. No-retry is intentional; generic settlement proves neither task success nor
detached-child completion. Removing APIs does not add stronger guarantees.
The default 90-second wait segment bounds one batch observation; it does not prove
outer-turn wakeup or durable continuation. Host mounting and follow-up delivery
require separate live evidence for the actual client binding.
Revisit stronger identity/continuity behavior only with actual task need, evidence and
separate authorization; removed APIs are not recovery options.
