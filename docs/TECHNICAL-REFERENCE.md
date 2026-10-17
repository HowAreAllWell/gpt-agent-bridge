# Technical reference

[English](TECHNICAL-REFERENCE.md) | [简体中文](TECHNICAL-REFERENCE.zh-CN.md)

This reference preserves the catalog, contracts, setup context and verification
material moved from the product homepage. For the current product introduction,
see [README](../README.md); new users follow only [Getting started](GETTING-STARTED.md).
Specialist documents remain the owners of their detailed contracts. This is
source documentation, not deployed-runtime or host-acceptance evidence.

## Document owners and audiences

| Owner | Audience and responsibility |
| --- | --- |
| [README](../README.md) | Product overview and entry navigation |
| [Getting started](GETTING-STARTED.md) | Single chronological newcomer installation and first use |
| [Quickstart](QUICKSTART.md) | Advanced/developer foreground setup, WSL, pinned Herdr and optional demo |
| [Technical reference](TECHNICAL-REFERENCE.md) | Tool catalog, Web Principal layers, native packaging and advanced navigation |
| [Project continuity](PROJECT-CONTINUITY.md) | Manifest routing, state/memory authoring and conditional publication |
| [Lifecycle](LIFECYCLE-RESTART-CONTRACT.md) | Dispatch, capacity, private reports, notifications, restart and uncertainty |
| [Autostart](AUTOSTART.md) | Owned Bridge/Tunnel units, explicit operator gates and optional WSL anchor |
| [Observation tools](OBSERVATION-TOOLS.md) | Work-target evidence, pagination, originals, bounded edits and Git candidates |

[AGENTS (unchanged machine rules)](../AGENTS.md) supplies contributor boundaries, not a product manual or
role assignment. The [Core (canonical, untranslated)](../templates/WEB-PRINCIPAL-CORE.md), four canonical
Skills and continuity fixture remain machine/procedure inputs with separate owners.
The public tree ships no actual project cognition. App installation does not
register a repository, seed continuity, start Agents or grant task authority.

Within this reference: [Web Principal layers](#web-principal-layers),
[native Skills and App binding](#native-skills-and-app-binding),
[private native packaging](#private-native-plugin-packaging), and
[optional running-service adoption](#optional-system-service-adoption).

## Original overview and setup context

Use **ChatGPT Web as the Principal for coding agents already running on your machine**.
GPT-Agent Bridge connects ChatGPT to Herdr-managed local agents without replacing their
native CLIs or forcing you into another agent dashboard.

## Getting Started

The chronological [Getting started guide](GETTING-STARTED.md) is the novice entry.
The [developer quickstart](QUICKSTART.md) retains clone-to-foreground MCP checks;
the [advanced Windows + WSL2 reference](QUICKSTART.md#windows-and-wsl2) covers manual environment
details. They are not additional required installation steps. Developer checks
need Git, Python 3.10+ with venv and Herdr; delegation additionally needs eligible
Agents you have launched. ChatGPT Web also needs your own connection and App.
Bridge is already used in WSL; a fresh WSL2 installation has not been validated.
The root [`.app.json`](../.app.json) and [`.app.example.json`](../.app.example.json)
contain an explicitly nonfunctional App ID placeholder. Replace it with your own
registered App ID in your independent configuration. The copyright name is not a
GitHub account login; use the actual owner of the repository you clone.

The Principal can delegate work to existing heterogeneous agents, continue reasoning while
they run, receive explicit reports, and inspect the same local project evidence itself:
source files, search results, diffs, images and original-file attachments. Project-local
state and memory let a later chat recover the current decision position instead of starting
over. When authorized, Bridge also provides bounded local edits and exact Git candidate /
commit operations.

The design goal is not autonomous agent orchestration for its own sake. Agents execute;
ChatGPT stays responsible for framing the problem, deciding what to delegate, checking the
evidence and making the final judgment. Herdr provides the local agent substrate; Bridge
provides the ChatGPT-facing project, Work, evidence, continuation and continuity layer.

### What Bridge adds

- **ChatGPT Web + your existing local agents.** Coordinate the sessions and agent CLIs you
  already use under Herdr instead of copying prompts and outputs between terminals.
- **Evidence-native review.** Agent reports are claims, not truth: ChatGPT can independently
  inspect repository text, diffs, images and files before accepting the result.
- **Completion reminders.** Delegate a fixed batch, keep doing independent work,
  and let the explicitly enabled extension notify the selected ordinary Chat.
- **Project continuity.** Repository-local rules, state, memory and reusable Plugin Skills
  preserve decision-relevant context across chat switches without turning transcripts into
  a second database.
- **Bounded local action.** Exact edits and captured Git candidates let an authorized
  Principal make narrow, reviewable changes while preserving unrelated work.

Bridge is a developer-oriented self-hosted integration. This public source contains
product code, portable documentation and synthetic tests. It ships no project cognition
state, private acceptance artifacts, working App binding or configured service.

## Tool reference

The SOURCE catalog contains 18 model-facing MCP tools with explicit behavioral annotations.
The retired widget and its three app-only watch/claim/feedback tools are absent,
including hidden callability. Browser completion notifications use a separate
loopback capability, not a model polling tool or report-body endpoint.
The catalog describes SOURCE behavior; deployment and host acceptance require
separate evidence. All registered tools
reject unknown arguments before executing; annotations describe behavior, not authority
or a guarantee against client refusal. Generic discovery supports Pi, Codex and other
raw providers. No retired tool remains hidden or callable by old name; specialized
managed start/resume/cancel/cleanup/recovery APIs are removed.
See the [observation contract](OBSERVATION-TOOLS.md) for bounds and rereads.

Tool-name migration: the public surface was renamed for name/description/effect
alignment — collaboration_snapshot→bridge_overview (selector project_ref; default view
exposes registered_project_refs), workspace_register→project_register(project_ref, path),
checkpoint→current_state_update, agent_observe→agent_terminal_read,
attach_file→prepare_file_attachment.
The current redesign also removes delegate's optional report selector; every admitted
Work requests a report.
context, commit_prepare and the other retained names are unchanged; the model-visible
await tool is removed. commit_prepare
keeps its three modes (stage paths + freeze / capture already-staged / page a saved
candidate). There are no callable aliases; use the current tool names and schemas.

| Tool | Purpose / owner |
| --- | --- |
| `context(project_ref)` | Selected-project orientation: Git facts, capacity, Agent handles, continuity pointers and a bounded session-matched continuation_inbox observation; does not restore/read the state-file body, consume results or bind a Chat |
| `delegate(project_ref, assignments=[{agent_ref, task}, ...])` | Dispatch 1..N tasks with mandatory reports and per-item receipts; automatically prepares one immutable all-of cohort/card for retained Works. Partial dispatch is not a transaction; unknown delivery is not safe to resend |
| `agent_terminal_read(project_ref, agent_ref, limit=120)` | Bounded current unattributed Agent terminal output; not a progress/status/liveness polling channel |
| `read(project_ref, path, offset=0, limit=4096, work_ref=None, start_line=None, expected_sha256=None, end_line=None)` | UTF-8 text and native image evidence with metadata; PDF/DOCX originals come via prepare_file_attachment |
| `work_report(project_ref, work_ref, offset=0, limit=4096, expected_sha256=None)` | Page the Agent-published report for a terminal work_ref; missing and invalid reports are errors; the text is not task success |
| `search(project_ref, query, ..., work_ref=None, match_offset=0, include_untracked=False)` | Tracked search; explicit opt-in additionally searches nonignored untracked text files |
| `list_entries(project_ref, path=".", work_ref=None, offset=0, limit=50)` | One directory's exact child names and types |
| `inspect_file(project_ref, path, work_ref=None)` | Regular-file mode/size/full SHA-256 without body |
| `prepare_file_attachment(project_ref, path, work_ref=None, expected_sha256=None)` | Hash the current source and prepare expiring ResourceLinks for later resources/read; nothing uploaded, host-imported, assembled or attached yet; multipart adds one receipt |
| `diff(project_ref, ..., work_ref=None, base=None, target=None)` | Current or pinned commit differences |
| `bridge_overview(project_ref=None)` | Bridge bootstrap/runtime diagnostics; default root additionally lists registered project refs, a read-only persisted-versus-live registration observation, and control documents |
| `bridge_health()` | Responding server registration and observed Herdr connectivity |
| `project_register(project_ref, path)` | Register an existing local Git project (absolute existing repository/checkout root); creates no repo/worktree/ChatGPT Project or continuity files and grants no task authority. Results distinguish pre-publication no-effect, published-but-uncertain durability, and the read-only live-versus-persisted observation |
| `project_initialize(project_ref, seed)` | Fresh canonical `.principal/` publication for an already registered project, or no-op when that manifest is already canonical. A non-canonical `.principal` is refused. Does not register, stage, commit, or grant task authority |
| `current_state_update(project_ref, expected_revision, content=None, edits=None)` | Replace/create only the manifest-routed current-state file; preserves no history or recovery point. An opted-in bridge-state-slot is a byte and limit-identity check; no summary or truncation |
| `project_text_edit(project_ref, path, expected_sha256, edits, work_ref=None)` | Exact edits to an existing UTF-8 file; full original hash required |
| `commit_prepare(project_ref, paths=None, work_ref=None, candidate_id=None, view="summary", offset=0, limit=50)` | With paths, stage selected literal files and freeze a candidate; without paths, freeze already-staged content; with candidate_id, page the saved candidate without staging/recapture |
| `commit(project_ref, candidate_id, message)` | Commit that exact staged candidate; preserve working files and index bytes |

### Project selection and authority

Use actual client schemas for complete arguments. Every project-scoped call requires its
explicit authorized ref and revalidates the registered Git root. Project instructions define
a finite allowed project_ref set; registry membership alone is not task authority.
ChatGPT Project identity remains not_exposed_or_unproven. No mutable global current project,
silent root fallback, placement, migration or automatic lost-Work resubmission exists.

### Delegation and completion reminders

`delegate` accepts explicit `project_ref` and a nonempty `assignments` list.
It returns one dispatch receipt per item immediately. A list envelope's `ok:true`
is not proof of admission, delivery or task success; response loss never justifies replay.
Continue useful independent work, or end the turn if none remains. There is no widget,
app-only watch tool or second watch-registration step.

The opt-in extension observes each delegate's fixed retained membership. Once
classified and readable, ready unattempted batches for the same project and Chat
can share one short reminder. Different projects/Chats keep separate queues,
recipients and cursors. A failed report blocks later feed entries in that project;
already queued ready candidates can skip another temporarily unreadable candidate.
Unknown sends never replay. Read the complete `work_report` separately; a reminder
or a report read does not acknowledge that the Principal has processed it.
See [notification rules](LIFECYCLE-RESTART-CONTRACT.md#chrome-notification-authority-and-recovery) and the
[lifecycle contract](LIFECYCLE-RESTART-CONTRACT.md).

### Agent reuse, Work lifetime and inbox

Before reusing a validated Agent/resource, Bridge scans all retained terminal history.
An abnormal/attention/uncertain gap refuses input until a qualifying same-resource
terminal diagnostic observation is recorded for the unchanged condition. An older gap is not
hidden by a newer observed Work. A normal result_ready report gap is nonblocking and
adds one advisory plus an additional-gap count. A successful nonempty public report
page records only a weak Work-level evidence-serving fact; classifier
probes do not count. Terminal text stays current and unattributed to any historical
Work. Neither marker proves review, resolution, task success or safe retry, and neither
consumes delivery or renews evidence. These project/resource hygiene facts are shared
across chats; later readers cannot erase them. Session-scoped inbox visibility remains
separate, and correlation is not authenticated identity. Expiry/restart loses this
history and adds no recovery.

Agents may share a checkout. Work captures exact execution identity at the
writer-gated refresh before prompt; optional work_ref reads target that frozen checkout,
not the original task's execution truth. Per-project capacity is 16 active Work plus
512 recent terminal receipts and 512 expiry tombstones. Terminal receipts expire
oldest settled_at first under count pressure, including unread reports. Notifications
and report reads do not pin or renew evidence. Known expiry returns WorkRefExpired;
other missing refs return WorkRefUnavailable. Capacity fields expose counts without refs.
Separately, context's `continuation_inbox` observes up to 50 retained classified Work
refs, result classes and classification-time report-status snapshots only for matching
request `_meta["openai/session"]`. They stay visible until ordinary expiry/discard.
Unknown sessions see only an unbound retained-classified count, never other sessions' refs.
This process-local index adds no widget claim, follow-up, retry, discharge or retention
protection. A notification receipt is not result processing; report reads are non-consuming.
`classification_report_status`
records evidence at final classification, not current report availability; attention Works may
publish a readable report later, which `work_report` can observe without reclassifying the Work.
This is not durable recovery
or proof of conversation identity. See the [request-scoped inbox contract](LIFECYCLE-RESTART-CONTRACT.md#request-scoped-result-inbox-observation).
[Work capacity](LIFECYCLE-RESTART-CONTRACT.md#work-capacity-and-report-lifetime) owns the lifecycle and handoff bounds. Terminal
signals do not establish writer cessation.

### Checkout observations

context and bridge_overview Agent rows also show native `workspace_id` (no proven workspace
name) and a display-only `checkout` summary: status, root, branch, HEAD and dirty.
Use workspace id with the tab/pane hint to distinguish workspaces; `handle` remains
the operation ref. Unknown/changed/deferred observations have null checkout values;
an observed null branch means detached HEAD. Each discovery shares a one-second display
budget, at most 16 checkout observations and four workers, reusing one result per checkout.
Each guarded status observation includes a configuration probe; default bootstrap may
need one display-identity prerequisite within the same budget.
Budget expiry defers metadata, not Agent rows; native process cleanup adds bounded grace
and OS calls are not preemptible. This is not an atomic snapshot or writable guarantee. HEAD identifies a commit,
not the complete baseline of dirty files. Worktrees are not OS security isolation.

### Local writes and exact Git candidates

Public `run` is removed from SOURCE with no alias or generic command replacement.
delegate dispatches to existing Agents and does not wait. The model-visible await
tool is removed.
Direct observations, current_state_update and bounded project_text_edit remain.
Version actions use commit_prepare then commit. Selected-path preparation mutates the index and may
write objects; final commit publishes the exact captured tree without rereading paths or
refreshing the index. Omit paths explicitly to capture already-staged content. No public
commit_preview/stage_paths alias, command arguments or approval field is exposed.
project_text_edit requires the full lowercase SHA256 of an existing regular UTF-8 file
and 1..256 exact, unique, nonoverlapping edits against the same original (file/result <=1 MiB).
It preserves untouched bytes/newlines/mode; no creation, links, binary/NUL, .git/traversal,
staging or commands. It uses the same frozen Work target and writer gate as other project
operations. commit_prepare selects 1..2048 literal regular-file paths (<=16 KiB total UTF-8
path bytes, <=4 MiB total contents), including
explicit new files/deletions; it refuses mixed staged/unstaged selections, staging outside
the selection, clean/process filters, active index hooks and content-conversion settings.
Captured bytes are written in one raw-object Git batch, with no per-file Git calls or
worktree reread for object creation. The path ceiling bounds temporary files and validation
work; the 30-second operation deadline and candidate/cache bounds still apply.
Both gates cover cooperating Bridge calls, not external writers. Unknown writes never
authorize blind retry. See [candidate version actions](OBSERVATION-TOOLS.md#candidate-version-actions)
for exact mechanical boundaries.
Source tests do not certify the running service or client refresh.

### Text and native image reads

read no longer extracts documents: it observes UTF-8 text and whole native images
(PNG/JPEG/GIF/WebP with matching suffix and magic, 5 MiB cap). PDF/DOCX are refused
by validated suffix (`UnsupportedReadFormat`) before any body access; `prepare_file_attachment`
requests such originals, which read never approves, parses or assembles. Other
binary/invalid-UTF-8 files remain `BinaryFileUnsupported` errors with the same
prepare_file_attachment guidance. read is now the only native-image route: the former
`view_image` compatibility tool is retired from SOURCE. Unified read retains native
image serialization; source and wire tests do not certify host visual recognition.

### Mandatory Work reports

Every admitted Work requests a report. Bridge appends publication instructions for a
private temporary report (up to 1 MiB UTF-8) and its atomic-publication staging file;
it does not write into the project checkout. After batch classification names `work_report`, page
that tool using its continuation and full-report SHA-256.
Agents must be able to write that private location; a missing or invalid report after
settlement is `attention_required`, not a silent success. `work_report` does not wait
or retry. Bridge probes the dedicated report once after the latch, before final classification:
`WorkReportMissing` may be rechecked at most twice, about one second apart, within
five seconds of added waiting. A readable report plus `agent_turn_settled` classifies
`result_ready`. That class is presence of the artifact, not task success.
The artifact is Agent-authored evidence, not task acceptance or a provider transcript.
The publication suffix counts toward the existing 16384-character task cap: a near-limit
task may fit the original task bound but fail mandatory report preparation with `WorkReportPreparationFailed`
before any prompt. Bridge does not silently truncate the task or expand its cap.
Delegation sends the caller task with the report publication instructions appended.
Work/report retention remains
process-local; no restart recovery or automatic retry is added.

## Original file attachments

`prepare_file_attachment` returns exactly one original-basename/original-MIME ResourceLink for
files at most **7 MiB (7,340,032 bytes)**, with no TextContent metadata. Larger files
return ordered ResourceLinks followed by exactly one compact JSON TextContent receipt:
`{"multipart":{"target":"original.bin","size":14680064,"sha256":"<full SHA-256>","parts":["<part 1 name>","<part 2 name>"]}}`.
The receipt contains only the original basename, full byte size, full SHA-256 and
ordered materialized part names. TTL, retention, status and provenance are internal
and do not appear in successful tool results. No outputSchema, structuredContent,
widget, blob/base64 or hidden body is added.

Every part is at most 7 MiB, uses application/octet-stream and has its exact raw size.
Names follow `<shortened-basename>.bridge-<fullsha12>-part-0001-of-000N`, bounded to
255 UTF-8 bytes without splitting a character. Small-file URIs remain
`bridge://attach/{capability}`; multipart uses `bridge://attach/{capability}/part/0001`.
Ordinals start at 0001 with at least four ASCII digits (10000 follows 9999); excess
leading zeros are rejected. A multipart group without an ordinal, or a single file
with a part ordinal, fails closed. `export_file` and `bridge://export/` remain retired.

The source part cap is **7 MiB**. For a hypothetical serialized response budget
of **10,485,760 bytes (10 MiB)**, base64 for a full part is about **9.33 MiB**
(9,786,712 bytes), leaving about **0.67 MiB** for JSON/protocol overhead. This
calculation is not an official raw-file limit or an accepted relay configuration.
Verify the actual client/relay budget and overhead: a smaller budget or larger
protocol envelope can still reject a part. The arbitrary **128 MiB** original-file
limit and **128-entry** attachment count limit/eviction have been removed. Every binary resources/read is still a
single base64 response; MCP does not supply standard streaming/range/reassembly
for this path. Bridge uses a bounded internal range reader. Actual observation
deadlines and transport capacity still apply; removing the logical size cap does
not promise that every arbitrarily large preparation/result will fit those limits.

The recipient uses the receipt's part names to locate host-materialized files,
concatenates them in order to the original basename, and verifies the full SHA-256
and size before treating the original as received. Bridge adds no automatic Web
assembler or post-materialization hook. Preparation and successful individual
fetches do not certify host import or File Library presence. `readOnlyHint=true`
describes filesystem observation; `idempotentHint=false` reflects a fresh opaque
token. Bridge performs no upload.

### Resource fetch validation and wire tests

The internal PendingAttachments lookup stores one frozen metadata entry per original,
independent of part count, with finite expiry/GC (currently 15 minutes), no read
renewal and no restart durability. No file bytes are retained. The entry binds
project/Work/path/target key, full SHA/size, original name/MIME, file stat and
parent-directory identities, and immutable part index/offset/length/SHA. Preparation
streams once in bounded reads, computing full and per-part hashes. Optional
expected_sha256 remains a full-file pin. Fetch re-resolves the same registered
project/frozen Work, uses reader admission and no-follow regular-file descriptor
walking, then reads ONLY the requested part. It checks saved device/inode/mode/link
count/size/mtime/ctime and parent identities, pre/post descriptor/stat/path binding,
exact part length/hash, and lookup identity/expiry again after observation.
Traversal, symlinks, special files, changed paths and unknown/expired/wrong/noncanonical
tokens return no bytes (-32602). Ordinary mutation anywhere invalidates subsequent
fetches, even when mtime is restored because ctime is also checked. These observations
are not an atomic snapshot: if identity, size and observed timestamps are spoofed,
an edit outside the requested part can escape that fetch's checks. Final full-file
SHA verification is the end-to-end check. No format parsing is added.

MCP 2.0.0's template has a fixed MIME hint; the narrow MCPServer.read_resource override
routes bridge://attach/ to per-response ReadResourceContents. Single-file fetches
retain the original MIME; multipart fetches are application/octet-stream. Both
discovery templates advertise a generic binary hint; other routes use the SDK.
Default MCP memory transport tests retain real 7 MiB and 7 MiB+1 physical
boundaries, small real two-part and frozen-Work three-part roundtrips (using a
test-local part cap), ordered raw bytes/full SHA, exact wire shapes, bounded reads
and no body retention. A metadata-seeded 128/129/130-entry default test crosses
the real store count boundary while still preparing and fetching through the
MCP wire; the original 129-preparation wire sequence is retained as opt-in stress.
Full 14 MiB/two-part and 21 MiB/three-part wire roundtrips remain in that
maintainer lane. Lightweight regressions also cover >128 MiB preparation using
fake hashing plus a real lower-layer open/early-EOF check, canonical ordinals
beyond 9999 and the 5 MiB and 417,431-byte Work/non-ASCII cases.

The 7 MiB raw part cap leaves room for base64 and protocol overhead. It is not a
guarantee for any relay or host: validate response limits and file import behavior
in the environment you operate. ResourceLinks prepare original bytes; they do not
prove host materialization, approval behavior or automatic attachment. Recipients
assemble ordered parts and verify the full original size and SHA-256.

## Passive catalog diagnostics

Passive `bridge.catalog_listing` INFO events describe handler catalog construction only,
not client receipt. `read_only_count` counts explicit True hints, not the total tools.
The implementation remains available; no dedicated observation task follows.

## Linked checkouts and user-preplaced Agents

Same-common-Git linked checkouts are supported as optional write domains, not
permanent roles or OS isolation. Placement is complete before launch; Bridge has
no public Agent-create/launch or worktree-create tool and does not rebind an existing
Agent during delegate. USER selects and launches the actual coding Agent with
knowledge of provider/model quota availability. Discovery/delegation then address
that existing resource in the selected project.

Select the intended checkout and Agent explicitly. Source support for linked
checkouts does not authorize moving existing Agents or prove live UI behavior.

## Verification and deployment boundaries

Install the package into this checkout's `.venv` with `pip install -e .` as in
[Quickstart](QUICKSTART.md#2-clone-and-install-direct-dependencies). Run relevant
tests, then the remaining full suite and diff checks:

```sh
PYTHONDONTWRITEBYTECODE=1 ./.venv/bin/python -m unittest discover -s tests -q
# Full-scale retention stress (opt-in maintainer lane):
BRIDGE_MAINTAINER_SUITE=1 ./.venv/bin/python -m unittest tests.test_work_retention.WorkRetentionTests.test_600_real_delegations_receipt_window_and_no_read_renewal -q
# Full-scale candidate and preparation stress (opt-in maintainer lane):
BRIDGE_MAINTAINER_SUITE=1 ./.venv/bin/python -m unittest tests.test_commit_candidate.CommitCandidateTests.test_unrelated_history_is_not_walked_and_unrelated_hooks_are_not_read tests.test_commit_prepare.CommitPrepareTests.test_query_count_stays_constant_through_2048_path_complexity_ceiling -q
# Full-size binary/patch and multipart/wire stress (opt-in maintainer lane):
BRIDGE_MAINTAINER_SUITE=1 ./.venv/bin/python -m unittest \
  tests.test_commit_candidate.CommitCandidateTests.test_large_binary_set_summary_patch_and_exact_commit \
  tests.test_commit_candidate.CommitCandidateTests.test_single_large_binary_file_is_previewed_and_committed \
  tests.test_commit_candidate.CommitCandidateTests.test_huge_text_patch_is_truncated_not_refused \
  tests.test_commit_candidate.CommitCandidateTests.test_many_files_aggregate_patch_truncation_and_bounded_creation \
  tests.test_file_attachment.FileAttachmentTests.test_fourteen_mib_two_part_memory_roundtrip \
  tests.test_file_attachment.FileAttachmentTests.test_twenty_one_mib_three_part_work_memory_roundtrip \
  tests.test_file_attachment.FileAttachmentTests.test_over_128_attachments_remain_readable_until_expiry_and_restart -q
git diff --check
```

The default suite keeps a small real retention sequence across the 512/513 boundary; the full 600-delegation loop runs only in the maintainer lane above.

Candidate tests use real temporary Git repositories in both lanes. The default
history case creates 8 unrelated loose objects and 3 refs, forbids repository
directory enumeration and reading the unrelated hook body, and verifies preview
plus an exact commit without running the hook. Its original-name maintainer case
retains 20,010 objects and 300 refs to guard against total-repository traversal
limits. Preparation checks 1 and 36 real paths by default; its original-name
maintainer case retains 1, 36, 256 and `MAX_SELECTED_PATHS` (2,048) to guard the
complexity ceiling. Both preparation lanes verify each result's status, total and
exact path set, exactly one `hash-object`, and a constant event count below 96.
The default suite also retains the cheap 2,049-path refusal, the 36-file exact
bytes/mode/index checks, and hook, filter and frozen Git safety coverage. These
fixture tests do not establish live service or deployed behavior.

Compile changed Python to a temporary directory when applicable. Preserve existing user
work. No commit, push, restart, deployment or other-agent input follows automatically from
a successful test. Source registration, running process and client-bound schemas are
separate evidence; transient tool visibility is not a complete binding inventory.

## Optional system service adoption

For a fresh installation with two independently managed services, use
[Bridge + Secure MCP Tunnel autostart](AUTOSTART.md). Its optional single owner
WSL anchor holds the distro while systemd starts enabled units. Herdr and Agents
remain manual; no Work or session replay is provided. Do not combine its units
with the adopter described here.

`scripts/` contains the portable service installer, environment allowlist library and tunnel TTL staging tool; `systemd/gpt-agent-bridge.service.template` is rendered for the selected user and checkout at install time. Machine paths, users and proxies are supplied as installer inputs.

After a Bridge process is already running for this checkout, optional system service
installation uses `sudo scripts/install-bridge-system-service.sh --user USER --repo /path/to/gpt-agent-bridge [--proxy URL]`.
The adopter requires an editable package installed into this checkout's `.venv`
and an exact `/absolute/checkout/.venv/bin/python -m gpt_agent_bridge` launch
from that checkout. Root `server.py` launches, console entrypoints, flags and
extra arguments are refused; identity checks cannot attest already loaded code.
The installer adopts the running Bridge fail-closed, stages a private environment file,
installs and verifies the unit, and never starts or enables it; starting the service remains
an explicit operator action. It cannot bootstrap a clean clone with no running process.

## Migration risks

Changing a checkout on disk does not migrate its installed package, running
process, service definition or ChatGPT connection. The src layout removes root
module entrypoints: a future restart using `server.py` will fail. Prepare and
verify the intended checkout's editable install and module origin before any
separately authorized cutover. Preserve the existing capability token, App
binding and required transport configuration; neither autostart installer
imports a live environment or supports automatic takeover.

The first-install services refuse occupied ports, foreign units/drop-ins and
unknown partial installation. Their minimal environment may not fit an existing
proxy/CA/mTLS deployment. Stop and review those differences before migration.
Stopping Bridge loses process-local Work, references and continuation state;
restarting does not resume Agents or authorize replay. Rollback must account for
code, package and service configuration together. Local initialized Bridge health
and Tunnel readiness do not establish remote ChatGPT acceptance. Linux reboot,
Windows login/no-window/lifetime behavior and fresh-user endpoints still need
separate target-host acceptance; this does not negate reported existing WSL use.

## Web Principal layers

Web Principal is the integrated self-hosted workflow of **ChatGPT Web + Project
Core + Bridge tools/Skills + Herdr**. ChatGPT supplies the reasoning; the Core
guides its judgment and conduct; Bridge connects explicitly selected local
projects and Herdr-managed Agents. This is not a separate reasoning engine or a
one-click hosted app.

The [copy/paste Core text (canonical, untranslated)](../templates/WEB-PRINCIPAL-CORE.md) is the exact body
supplied by the Principal from the current ChatGPT Project instructions at this
checkpoint. This records the supplied text; it is not independent authentication
of live Project settings and is not automatically synchronized with them. Manual
installation and a separately reviewed Project Binding remain distinct steps.
Publishing this file does not change an installed Project or establish fresh-host
acceptance.

### What the Principal owns

The Principal is the user's high-level cognitive partner: frame and, when needed,
reshape a problem; challenge assumptions; investigate gaps; compare alternatives
and tradeoffs; and take responsibility for the final synthesis. Delegation supports
that judgment. Reporting Agent status is not the whole job.

The user keeps goals, scope, key tradeoffs and authorization. Within an authorized
task, the Principal should keep making useful progress rather than repeatedly
asking for the same permission. A new consequential choice or authority boundary
returns to the user with concrete evidence and a recommendation.

### Four different layers

| Layer | Responsibility | What it does not establish |
| --- | --- | --- |
| Project Instructions: Core and separate Binding | Always-on judgment, conduct, explicit project selection and applicable boundaries | Tool access, identity authentication or execution isolation |
| Four Plugin Skills | Reusable procedures triggered by a relevant situation | A role, new task authority or async protocol behavior |
| Bridge tool schemas and descriptors | Available operations, their limits and continuation/evidence contracts | Permission to take every technically available action |
| Local routed rules, current state and memory | Project-specific decisions, durable causes and resumption context | Global memory, automatic authority or fresh runtime truth |

The four [canonical procedures](#native-skills-and-app-binding) remain separate
from the versionless continuity manifest. Core does not install software, expose
a connection or discover native Skills. Follow only [Getting Started](GETTING-STARTED.md)
for manual Core installation, four-Skill checks and a separately reviewed Binding.
Keep credentials and private cognition out of Core/Binding; selection must be
explicit rather than inferred from a Chat or directory name. Registration can
return a Binding amendment but does not apply Instructions or initialize files.

### Delegation, reports and verification

Give Agents independent, bounded questions when their investigations can improve
the judgment, and continue useful independent work after dispatch. Follow the
available tool contract instead of implementing a watcher in the prompt. If no
independent work remains while results are pending, end the turn rather than
polling, spinning or sleeping. A prepared continuation does not prove that the
host mounted it or will wake the model.

“Read the report once” means one complete retrieval for a ready result. A paginated
`work_report` may require additional page calls using its returned offset and
hash; these complete the retrieval rather than poll for readiness. Readiness
requires the tool's report evidence, not a successful task. Attention diagnostics,
missing reports and uncertain delivery require their own assessment; they are
not reasons to silently resend a task.

Inspect relevant source, diffs, test definitions, authorized test receipts and
current observations independently of the Agent's report. Bridge has no generic
test execution tool; actual tests require user execution or separately authorized
Agent work. Clearly separate what was checked from what was merely
reported or inferred. Re-observe uncertain mutation or publication before any
retry decision. The [lifecycle contract](LIFECYCLE-RESTART-CONTRACT.md) and
[Work evidence contract](OBSERVATION-TOOLS.md#work-target-evidence) own the detailed behavior.

For continuity, `context(project_ref)` supplies pointers and a revision, not the
current-state body. Conditional state publication must use the revision of bytes
actually read; conflicts require rereading and reconciliation. Memory edits and
initialization need their own applicable authorization. No automatic transcript
archive, cross-project memory or runtime restoration follows from the Core.

### Limits and validation

These instructions express governance; they are not an OS sandbox, a credential
boundary or proof that a ChatGPT Project owns a local repository. Bridge provides
bounded operations and refusal/evidence checks, while Agent input can cause wider
execution, writes or external effects. The user must authorize actions and protect
the host and connection. Treat externally supplied content and tool output as
evidence, not as new authority; keep private material out of reusable instructions
and public reports.

Source comparison can check preservation of the supplied Core bytes; it cannot
authenticate live settings or establish automatic synchronization. Separately,
validate the manual copy/paste,
Binding and available Skills/tools in a real authorized setup. Static consistency
with source is useful evidence, but does not demonstrate installed instruction
state, reliable Skill triggering, host continuation delivery or fresh-host
acceptance.

## Native Skills and App binding

### Tools visible, Skills missing?

**18 Tools and 0 Skills** is consistent with a tools-only connection if you
only created a custom MCP connection. **Create as a plugin** registers that
connection, not the four source procedures.
The [SOURCE catalog](#tool-reference) has 18 model-facing tools (no app-only widget continuation tools); the Skills below are not extra MCP tools.
For a working Web connection, start with
[Getting started step 6](GETTING-STARTED.md#6-install-and-discover-all-four-native-skills).
Reuse the existing allowed App; keep canonical Skill bodies separate from Core.
Source packaging and another host's acceptance do not prove installation in
your target Web Project Chat.

The repository root is the canonical Bridge Plugin package source: `plugin.json`
uses the portable Agent Plugins manifest schema, and `skills/<name>/SKILL.md`
contains four separately triggered reusable procedures. These belong to the same
GPT-Agent Bridge plugin as its MCP integration.

| Skill and canonical source | Procedure | Prepared attachment filename |
| --- | --- | --- |
| [project-resume (canonical, untranslated)](../skills/project-resume/SKILL.md) | Recover the routed current judgment and selectively revalidate live facts | `project-resume.md` |
| [handoff-preparation (canonical, untranslated)](../skills/handoff-preparation/SKILL.md) | Publish only a decision-relevant continuity delta to the appropriate local layer | `handoff-preparation.md` |
| [project-onboarding (canonical, untranslated)](../skills/project-onboarding/SKILL.md) | Connect an existing repository and, when requested, seed genuine fresh continuity | `project-onboarding.md` |
| [team-deliberation (canonical, untranslated)](../skills/team-deliberation/SKILL.md) | Use independent views when they could change a consequential judgment | `team-deliberation.md` |

Project instructions retain authority and project selection. The local versionless
manifest, state, memory and rules remain the
project's durable cognition. Plugin skills own reusable workflow prose; tool
descriptors own capability/continuation contracts. Skills contain no async
watch/delegate sequencing rules. A skill's activation does not assign a role.

Principal Methods are retired. Local route wrappers are deleted, and continuity
manifests and initialization seeds reject the `methods` field even when empty or
null. Canonical reusable procedures live only in `skills/`; no forwarding stubs
or replacement manifest routes are provided. Project-specific decisions, causes
and rules stay with their local owners. This source retirement does not update
installed Skill texts or certify automatic trigger reliability.

### Attachment and discovery diagnostics

The preparation handoff supplies these four uniquely named copies in
`Creator-attachments/`. Preserve each canonical file's complete bytes, `name`
and `description` frontmatter. Rename only private attachment copies, never the
canonical Skill folders or files. A source URL does not prove that its body was
imported. If attachment names still collide, supply four complete, individually
labeled texts and confirm that each arrived without truncation. These are inputs,
not evidence of native installation; do not include private cognition or secrets.

Check **four complete installed native Skill bodies** and an actual
**`bridge_health()` result** separately in the intended ordinary Web Project Chat.
Health alone proves no Skill discovery; installed procedures alone prove no MCP
connectivity. A shortened per-turn listing or four-name summary is insufficient:
explicitly discover the bodies and compare them with the canonical inputs.
If tools work but Skills are missing, retain the working App/Tunnel and diagnose
native packaging or workspace permissions. Do not recreate credentials or prompt
tasks to force discovery. Record **tools working; Skills unverified**, adding
Core only if its instructions were separately checked. Work/Codex acceptance
does not establish ordinary Web availability or automatic Skill triggering.

### Public package configuration

[plugin.json](../plugin.json) points `extensions.com.openai.apps` to
[root .app.json](../.app.json). The sole alias `bridge` has `required: true` and
`asdk_app_REPLACE_WITH_OWN_APP_ID`, an explicitly nonfunctional placeholder.
[.app.example.json](../.app.example.json) provides the same reference shape.

For optional local packaging, the
[personal package guide](#private-native-plugin-packaging)
uses [prepare-personal-plugin.py](../scripts/prepare-personal-plugin.py) to
copy this public manifest, its existing LICENSE and all four Skill texts into
a separate eight-file marketplace. The generator never reads the source App
binding or installs a host plugin. Only a verified native App reference is
accepted (`asdk_app_`, `connector_` or `templated_apps_`); browser
`plugin_asdk_app...` identifiers are not converted. Root placeholders stay here.
Use your own registered App ID in an independent configuration. This package
adds no endpoint, credential, runtime skill handler or marketplace configuration.

The source bundle and tests establish file layout and mapping shape. They do not
establish acceptance by a plugin distribution service, a working App connection,
installed skill discovery, automatic trigger reliability or fresh-chat usefulness.
Consult the host's current packaging requirements separately before installation
or distribution. No installation or publishing action follows from source tests.

Skills remain separate from project-local cognition. This public package includes
no actual project `.principal/` directory. Installation does not onboard projects,
start services, launch Agents or grant task authority. See
[Getting started](GETTING-STARTED.md) for the single first-use path.

## Private native plugin packaging

This optional route is for a verified eligible native App and a supported local
marketplace surface. It does not install Skills into every Web account. Use
[Getting started step 6](GETTING-STARTED.md#6-install-and-discover-all-four-native-skills)
for the single Creator path. A browser `plugin_asdk_app_` representation is not a
native `.app.json` ID: never trim prefixes or infer eligibility from a string.
The Chrome extension ID is a different identity altogether.

The [shared native ID check](https://developers.openai.com/plugins/deploy/submission-errors#mcp-server-reference-errors)
allows `asdk_app_`, `connector_` or `templated_apps_`, followed by one ASCII
letter/digit and then ASCII letters/digits/underscores/hyphens. Uppercase and
different suffix lengths are allowed. The generator adds a **local 256-character
total limit** and rejects the known public placeholder, browser IDs, URLs,
whitespace, non-ASCII and controls. It preserves your input exactly; there is no
browser-to-native conversion. If you only have a browser URL, return to the Creator route in
[Getting started step 6](GETTING-STARTED.md#6-install-and-discover-all-four-native-skills)
and have the host select the existing App.

### Use a reviewed licensed public source

Run with Python 3.10+ on Linux/WSL and review
[the generator](../scripts/prepare-personal-plugin.py) first. Inputs must come
from a trusted **public source checkout with its existing root LICENSE**,
plugin.json and four canonical Skills. The reviewed public distribution includes
its MIT notice and attribution. The generator copies that exact notice; it does
not decide licensing or generate copyright text.

The internal development checkout has no root LICENSE, so its default source
fails closed. Do not create a license there to bypass this check. Use a reviewed
public clone that includes this generator, or explicitly point an already
reviewed script at that public source. If the public clone lacks the script,
this local candidate has not reached it yet; do not assume a command is available.

From a public clone containing the script:

```bash
python3 scripts/prepare-personal-plugin.py \
  --marketplace-root "$HOME/bridge-personal-marketplace"
```

When running a reviewed script elsewhere, explicitly choose your reviewed
licensed public source (adjust the source path to your actual clone):

```bash
python3 scripts/prepare-personal-plugin.py \
  --source "$HOME/gpt-agent-bridge-public" \
  --marketplace-root "$HOME/bridge-personal-marketplace"
```

Choose a new absolute output directory outside the source. Its parent must
already exist, belong to you and not be writable by group/others. Paths must not
contain symlinks or traversal. Existing destinations, including empty directories
and broken links, are refused; no existing marketplace is merged or overwritten.

Enter only the verified native App ID at the hidden prompt, never an API key,
password, tunnel ID or token URL. Do not use arguments, shell history, public
reports, screenshots or Project Instructions for the ID. Input echo fallback
is refused. The ID appears only in the generated private `.app.json`.

For noninteractive use, `--id-file /absolute/private/id-file` accepts one exact
UTF-8 ID line, optionally ending in LF. The file must belong to you, have mode
0600 or 0400, and have no symlink/hard link. The same 256-character total ID limit
applies. Prepare that input yourself in a private editor; the generator neither
writes nor deletes it. Never pass a real source `.app.json` as the input file.

### Exact eight-file result

```text
bridge-personal-marketplace/
├── .agents/plugins/marketplace.json
└── plugins/gpt-agent-bridge/
    ├── plugin.json
    ├── LICENSE
    ├── .app.json
    └── skills/
        ├── project-resume/SKILL.md
        ├── handoff-preparation/SKILL.md
        ├── project-onboarding/SKILL.md
        └── team-deliberation/SKILL.md
```

The manifest, LICENSE and four Skills are exact source-byte copies. Missing,
empty, invalid UTF-8, unsafe or changing LICENSE inputs stop publication.
The notice is checked again with the source snapshot before publishing.
The generator validates safe notice text, not its legal applicability: review
the public source's actual licensing before copying or distributing it.

The generated mapping is alias `bridge`, your exact native ID and
`required: true`. The catalog uses
`source.path="./plugins/gpt-agent-bridge"`, relative to the marketplace root,
and marks the entry AVAILABLE with ON_INSTALL authentication. Source version is
retained. No hooks, compatibility overlay, runtime source, private docs, real
source App binding or cognition are copied.

Directories are created with mode 0700, files 0600 under the normal tested umask.
A private temporary sibling and Linux `renameat2(RENAME_NOREPLACE)` publish
without clobbering a concurrent destination. Unsupported environments fail
closed, without an overwrite fallback. Cleanup removes only identified objects
created by this invocation. Unknown/replaced content and crashes can leave a
private `.bridge-plugin-pending-*` sibling; inspect it manually rather than
using blanket recursive cleanup. A post-publication durability warning requires
inspection before retry. These checks do not isolate malicious same-user
processes.

### Explicit host installation

Review the private generated package and compare its notice/Skills with the
source. Generation has not changed the host. Where your client supports the
[official local marketplace flow](https://developers.openai.com/plugins/build/plugins#add-a-marketplace-from-the-cli),
the user may explicitly add this marketplace root:

```bash
codex plugin marketplace add "$HOME/bridge-personal-marketplace"
```

This command changes host configuration; the generator never runs it. In an
eligible local Work/Codex desktop surface, refresh/restart the desktop app as
the current instructions require, open Plugins Directory, select Personal
GPT-Agent Bridge and install GPT-Agent Bridge. Review App authentication and
permissions. This is not a Bridge/tunnel restart or a universal Web Project Chat
installation path. Account/workspace policy can block local sources or App access.
Do not edit host caches, global config, admin settings or another marketplace
to bypass those limits. Sharing/publication needs separate review and authority.

## Target Chat Skill verification

After either supported installation route, open a fresh chat in the intended
Project and select/enable the plugin where the UI offers it. Ask:

```text
Read-only check: explicitly discover this chat's installed Skill catalog.
Find project-onboarding, project-resume, handoff-preparation and
team-deliberation under my Bridge plugin and compare their available texts
with the canonical attachments I reviewed. Do not invoke these procedures,
register/initialize a project, delegate Agent input or change any files.
Separately call bridge_health and inspect the returned Herdr.status.
```

Use actual results, not a prose assertion or a shortened per-turn listing.
Testing in Work/Codex does not certify ordinary Web Project Chat availability.
Discovery does not certify automatic selection, trigger reliability or continuity.
After all four are verified on the actual target surface, return to
[Getting started step 8](GETTING-STARTED.md#8-connect-your-existing-git-repository-and-merge-its-binding)
and its [bounded first-use check](GETTING-STARTED.md#10-begin-daily-use-with-a-bounded-read-only-check). Registration, initialization,
Agent input and continuity keep their separate permissions.

## Native execution retirement

Public `run` is removed from SOURCE, with no hidden alias or arbitrary-command replacement.
Its exclusive native_execution module and tests are removed after consumer inspection.
Source inspection and tests establish local contracts only; runtime deployment and
host acceptance require separate evidence.
The [tool reference](#tool-reference) lists retained capabilities;
[observation contracts](OBSERVATION-TOOLS.md) own exact evidence/version mechanics.

Distinct Agent resources may hold concurrent in-flight Work in one shared checkout;
a nonterminal Work or unconsumed handoff for the same Agent handle/resource still
rejects a duplicate prompt. Terminal
settlement does not prove manual/detached writers stopped. Shared gates and dispatch
identity checks remain; see [Lifecycle](LIFECYCLE-RESTART-CONTRACT.md).

Fixed Git observations retain bounded byte capture, timeout and joined cancellation cleanup.
They expose no caller argv. Spawn/nonzero failures and incomplete captures are not clean
observations. Inherited pipes, TERM-resistant descendants, repeated cancellation and escaped
pipe holders are covered by tests/test_fixed_git_lifecycle.py. Escaped processes and
nonpreemptible OS operations prevent an unconditional end-to-end bound.
See [observations](OBSERVATION-TOOLS.md) for query limits and unsupported configurations.

Shared admission regressions live in tests/test_checkout_admission.py; actual MCP retirement
and retained evidence calls are covered by tests/test_run_retirement.py.
Source tests do not certify runtime acceptance; validate the configured service and
client separately. This public source does not include private execution receipts.

## License

Released under the [MIT License (original text)](../LICENSE). Copyright (c) 2026 tomoyo.
