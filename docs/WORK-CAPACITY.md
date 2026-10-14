# Project-local Work lifecycle and capacity

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
as defined by the [lifecycle contract](LIFECYCLE-RESTART-CONTRACT.md#request-scoped-result-inbox-observation).
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

## Private report lifetime

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

## Fixed notification batches

One delegate invocation fixes its notification members. A ready batch can be queued
and same-project/same-target ready unattempted reminders can merge. This does not
add a retention owner, widget claim, delivery-consumed flag or acknowledgement API.
An expired member remains unavailable under the existing report contract; no old
Work is recreated or dispatched again to fill missing evidence.
