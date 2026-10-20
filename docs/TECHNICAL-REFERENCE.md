# Technical reference

[English](TECHNICAL-REFERENCE.md) | [简体中文](TECHNICAL-REFERENCE.zh-CN.md)

Use this page to **understand the parts of Bridge, find the right tool, or check
a precise technical limit**. You do not need to read it front to back.

**Installing for the first time?** Start with [Getting started](GETTING-STARTED.md).
That guide has equal native Ubuntu Desktop and Windows+WSL2 routes, then one
ordinary ChatGPT Web Project Chat setup. This page is a lookup after that journey,
not a second installation checklist.

For a small first check in the connected Project Chat, name one authorized file:

> Read only this file and explain the relevant lines. Show the actual result and
> any missing evidence. Do not edit, run commands/tests or send Agent tasks.

**Success:** real content from the correct project supports the explanation.
**Blocked:** a wrong target, missing tool, incomplete page or access error must
remain visible; do not silently change projects or repeat an uncertain action.
Source contracts below describe implementation behavior. They do not certify
your running service, account controls or a fresh installation.


<a id="document-owners-and-audiences"></a>
## Find the right guide

| What you need | Read this page | Who needs it |
| --- | --- | --- |
| Understand the product | [README](../README.md) | Everyone deciding whether Bridge fits |
| Install and make a first connection | [Getting started](GETTING-STARTED.md) | New users on Ubuntu Desktop or Windows+WSL2 |
| Run processes manually or check Herdr 0.9.0 | [Quickstart](QUICKSTART.md) | Developers and people diagnosing a manual setup |
| Find a capability or exact limit | [Technical reference](TECHNICAL-REFERENCE.md) | Users looking something up; developers checking contracts |
| Save decisions for a later chat | [Project continuity](PROJECT-CONTINUITY.md) | Users authorizing project notes and resumption |
| Understand task completion, reminders or expired results | [Lifecycle](LIFECYCLE-RESTART-CONTRACT.md) | Users interpreting a task outcome |
| Check background services or recover them | [Autostart](AUTOSTART.md) | Operators managing their own installation |
| Read files, changes, reports or originals | [Observation tools](OBSERVATION-TOOLS.md) | Users checking evidence |

[AGENTS](../AGENTS.md) contains contributor rules; reading it does not assign a
role or grant project authority. The supplied [Core](../templates/WEB-PRINCIPAL-CORE.md)
and four Skills are instruction inputs. Private project decisions are not
included in the public package. Installing a plugin does not register a repository,
initialize notes, start Agents or authorize tasks.

Jump to [tools](#tool-reference), [instructions and responsibilities](#web-principal-layers),
[missing Skills](#native-skills-and-app-binding), [Web plugin setup](#private-native-plugin-packaging),
or [advanced service adoption](#optional-system-service-adoption).


<a id="original-overview-and-setup-context"></a>
## How the pieces fit

**Web Principal** means ChatGPT acting as your thinking partner: frame a problem,
compare alternatives, coordinate authorized work and judge the evidence.
These are the pieces it uses:

| Name | Plain meaning | What you check |
| --- | --- | --- |
| **Core and Project Binding** | Saved ChatGPT Project instructions: how to work, and which local project you authorize | Complete text saved in the intended Project |
| **MCP App / plugin** | The connection selected in ChatGPT; MCP is the protocol carrying tool requests | A successful actual `bridge_health` call |
| **18 tools** | Operations such as reading a file or dispatching a task | The real available tool catalog |
| **Four native Skills** | Installed reusable instruction workflows | Four complete installed bodies, not just attachments |
| **Herdr / local Agent** | Herdr manages terminal sessions; you start a supported Agent in one | Fresh project context shows an eligible authorized Agent |
| **Work** | Bridge's record of a dispatched task | Per-item dispatch outcome, final classification and report |
| **Git commit candidate** | Captured staged changes to review before a commit | Exact selected content and a separate commit authorization |
| **Checkout** | The local Git working folder used as an evidence/action target | Correct folder and identity, not just a matching name |

ChatGPT supplies reasoning; Bridge supplies bounded access; Herdr manages the
existing local Agents. A Skill is not an Agent or another tool. None of these
pieces grants permission to use every technically available capability.


<a id="getting-started"></a>
## Start with the setup guide

Follow [Getting started](GETTING-STARTED.md) from step 1. Choose the route for
your computer before running a launcher:

| Computer | Preparation entry | Browser/reminder location |
| --- | --- | --- |
| **Native Ubuntu Desktop** | Ubuntu Terminal, `./prepare` | Chrome on the same Ubuntu computer; no WSL or PowerShell |
| **Windows+WSL2** | Windows PowerShell, `.\Start-Bridge.ps1` | Windows Chrome; use the final printed Windows-local extension folder |

The guide explains the required existing **Herdr 0.9.0**, account permissions,
private credentials and consent prompts. Preparation creates its own Python
environment and extension files, then **installs, enables and starts both Bridge
and Tunnel services** on supported Linux. **systemd** is Linux's background-service
manager. Herdr/Agents are not installed
or launched by Bridge. No Agent must be running merely for preparation.
Browser reminders are optional.

Native Ubuntu beginner installation, fresh Windows/account setup, Chrome loading
and restart behavior remain unaccepted on a fresh user machine. An Ubuntu
Server/headless setup with a browser elsewhere has no validated local Chrome
loopback-reminder path; do not infer support from the Tunnel connection.

The [developer quickstart](QUICKSTART.md) and its
[Windows+WSL2 subsection](QUICKSTART.md#windows-and-wsl2) are alternative manual
routes, not extra steps after preparation. Do not start duplicate processes
alongside the installed services. Packaging examples belong to the
[developer configuration section](#public-package-configuration); beginners do
not need to edit an App ID file.


<a id="what-bridge-adds"></a>
### What you can do after setup

- **Think before dispatching.** Ask ChatGPT to challenge assumptions and compare
  approaches before assigning work.
- **Coordinate eligible local Agents.** Give independent, bounded questions to
  authorized Agents already supported and runnable under Herdr.
- **Review real evidence.** Compare complete reports with relevant code, diffs and
  authorized test receipts.
- **Keep useful project decisions.** Explicitly save reasons and next boundaries
  for another chat; this does not restore running tasks.
- **Make narrow changes when authorized.** Exact text edits and reviewed Git
  candidates preserve a clear scope. Tool availability is not permission.

The optional extension can remind the exact Chat you enable. A reminder is not a
report, proof of successful work or a guarantee of model wake-up. This self-hosted
package supplies source, documentation and synthetic tests, not configured
accounts, providers or private project notes.


## Tool reference

**You can ask in ordinary language.** The table below points to the operation
ChatGPT should use; the expandable catalog preserves the exact signatures.

| Your goal | Tools to recognize | Important boundary |
| --- | --- | --- |
| Check the connection or select a project | `bridge_health`, `bridge_overview`, `context` | Current observations do not grant authority or restore Work. |
| Connect an existing repository | `project_register` | No repository creation, task permission or Chat binding. |
| Read evidence | `read`, `search`, `list_entries`, `inspect_file`, `diff` | Keep scope explicit; complete relevant pages. |
| Read a task report or diagnostic | `work_report`, `agent_terminal_read` | A terminal tail is not the full report. |
| Retrieve original files | `prepare_file_attachment` | Preparing links does not upload or assemble files. |
| Assign work | `delegate` | Sends input to existing Agents; per-item unknown outcomes are not safe to resend. |
| Initialize or save project notes | `project_initialize`, `current_state_update` | Separate write authorization and conflict checks apply. |
| Edit or commit | `project_text_edit`, `commit_prepare`, `commit` | Preparation with selected paths stages files; commits need explicit authorization. |

The source catalog defines **18 tools for ChatGPT**; check the actual catalog
in your own Chat. Old names have no callable compatibility aliases. The “Codex” mentioned in provider discovery below means a local Agent CLI,
not the normal ChatGPT plugin installation surface.
[Observation tools](OBSERVATION-TOOLS.md) explains everyday requests and partial results.
<details>
<summary>Advanced: exact 18-tool catalog and retired names</summary>

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
| `delegate(project_ref, assignments=[{agent_ref, task}, ...])` | Dispatch 1..N tasks with mandatory reports and per-item receipts. If browser notifications are configured, eligible new Works may share a fixed notification group; no cohort UI card is created. Partial dispatch is not a transaction; unknown delivery is not safe to resend |
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

</details>


### Project selection and authority

Tell ChatGPT the registered `project_ref` you authorize and verify the returned
local folder. A matching ChatGPT Project name is not proof of that choice.
If the returned target is wrong or identity is unproven, stop; do not let it
select another repository as a fallback.
<details>
<summary>Advanced: exact contract and implementation limits</summary>

Use actual client schemas for complete arguments. Every project-scoped call requires its
explicit authorized ref and revalidates the registered Git root. Project instructions define
a finite allowed project_ref set; registry membership alone is not task authority.
ChatGPT Project identity remains not_exposed_or_unproven. No mutable global current project,
silent root fallback, placement, migration or automatic lost-Work resubmission exists.

</details>


### Delegation and completion reminders

After you authorize a task, check each `delegate` receipt separately. For
example: “Give these two eligible Agents independent questions within this scope.”
One item may be accepted while another is refused or uncertain.
Read the eventual complete report; an enabled reminder is only a notification.
Do not resend an assignment because a response or reminder was lost.
<details>
<summary>Advanced: exact contract and implementation limits</summary>

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

</details>


### Agent reuse, Work lifetime and inbox

A **Work** is one dispatched task record. The **inbox** is a limited view of
retained classified results for the current request session, not durable memory.

Before another assignment, refresh context and inspect any attention/gap warning.
Read the relevant report or diagnostic; doing so records limited evidence-serving
facts, not proof that the problem was resolved. Expired/missing references require
an honest “unavailable,” not a new task or a fallback target.
<details>
<summary>Advanced: exact contract and implementation limits</summary>

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

</details>


<a id="checkout-observations"></a>
### Identify the local working folder

If two Agents look similar, use the displayed workspace ID and tab/pane hint,
then the current operation handle. A **checkout** is their local Git folder.
Missing display metadata can mean it was deferred; it does not prove the Agent
vanished. A displayed commit does not describe all uncommitted files.
<details>
<summary>Advanced: exact contract and implementation limits</summary>

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

</details>


<a id="local-writes-and-exact-git-candidates"></a>
### Edit files and review Git commit candidates

Ask for a proposed change before authorizing it. `project_text_edit` changes
an existing text file using its full source fingerprint. For Git, review changes
first: `commit_prepare` with selected paths **stages** them, while `commit`
publishes the reviewed captured candidate. No generic shell/test tool is provided.
A refusal or unknown write outcome requires inspection before another mutation.
See [the exact edit/candidate guide](OBSERVATION-TOOLS.md#candidate-version-actions).
<details>
<summary>Advanced: exact contract and implementation limits</summary>

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

</details>


### Text and native image reads

Ask to read the specific text file or image. Images arrive whole, up to
**5 MiB**; text can require pages. PDF/DOCX are not extracted by `read`:
`UnsupportedReadFormat` directs you to original-file retrieval.
`BinaryFileUnsupported` also does not mean an empty document.
The host's ability to display/recognize an image needs separate evidence.
<details>
<summary>Advanced: exact contract and implementation limits</summary>

read no longer extracts documents: it observes UTF-8 text and whole native images
(PNG/JPEG/GIF/WebP with matching suffix and magic, 5 MiB cap). PDF/DOCX are refused
by validated suffix (`UnsupportedReadFormat`) before any body access; `prepare_file_attachment`
requests such originals, which read never approves, parses or assembles. Other
binary/invalid-UTF-8 files remain `BinaryFileUnsupported` errors with the same
prepare_file_attachment guidance. read is now the only native-image route: the former
`view_image` compatibility tool is retired from SOURCE. Unified read retains native
image serialization; source and wire tests do not certify host visual recognition.

</details>


### Mandatory Work reports

Every admitted task requests a dedicated report. Once a specific Work is terminal
and its report is published and readable, use `work_report` for that exact Work
and read all pages with the full-report SHA-256 fingerprint. Other Works in the
batch may still be running, and browser notifications may be disabled.
Do not substitute the terminal tail or assume `result_ready` means correct.
Missing/invalid reports need attention; no automatic wait/retry or durable report
archive is supplied.
<details>
<summary>Advanced: exact contract and implementation limits</summary>

Every admitted Work requests a report. Bridge appends publication instructions for a
private temporary report (up to 1 MiB UTF-8) and its atomic-publication staging file;
it does not write into the project checkout. Once that specific Work is terminal
and its report is published and readable, page `work_report` for that exact Work
using its continuation and full-report SHA-256. Other Works may still be running;
batch notification readiness is not required, and notifications may be disabled.
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

</details>


## Original file attachments

Use this when you need the **original file**, including a PDF/DOCX that cannot
be read as text. Ask for one named authorized file via `prepare_file_attachment`.

**Expected result:** temporary retrieval links, plus an ordered-parts receipt
when needed. “Prepared” does not mean uploaded, imported into ChatGPT or attached.
At most **7 MiB** uses one link; larger originals need the receiving side to
fetch, assemble in receipt order and verify full size/SHA-256. Bridge adds no
automatic Web assembler. If a part is missing, expired or changed, report the
original as unverified rather than presenting a partial file as complete.
[The practical retrieval guide](OBSERVATION-TOOLS.md) explains the user check.
<details>
<summary>Advanced: exact contract and implementation limits</summary>

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

</details>


<a id="resource-fetch-validation-and-wire-tests"></a>
### Advanced: attachment validation and transport tests

**Developer detail.** These checks explain why a temporary file link can be
refused after preparation. They do not prove the host imported the original.
Verify the final original's full fingerprint and size, even when each part fetch
succeeded. Keep failures visible rather than bypassing an expired/changed target.
<details>
<summary>Advanced: exact contract and implementation limits</summary>

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

</details>


<a id="passive-catalog-diagnostics"></a>
## Advanced: tool catalog diagnostics

**For diagnostics only:** a server log saying it built a tool catalog is not
proof ChatGPT received it. Check the catalog in the actual target Chat instead.
A count of read-only hints is not the total tool count.
<details>
<summary>Advanced: exact contract and implementation limits</summary>

Passive `bridge.catalog_listing` INFO events describe handler catalog construction only,
not client receipt. `read_only_count` counts explicit True hints, not the total tools.
The implementation remains available; no dedicated observation task follows.

</details>


<a id="linked-checkouts-and-user-preplaced-agents"></a>
## Use Agents in linked working folders

A linked checkout is another working folder for the same Git repository.
If you use one, choose and launch the authorized Agent there yourself, then
verify the observed target. Bridge does not create/move the folder or launch/rebind
an Agent. Sharing a folder is not operating-system isolation.
<details>
<summary>Advanced: exact contract and implementation limits</summary>

Same-common-Git linked checkouts are supported as optional write domains, not
permanent roles or OS isolation. Placement is complete before launch; Bridge has
no public Agent-create/launch or worktree-create tool and does not rebind an existing
Agent during delegate. USER selects and launches the actual coding Agent with
knowledge of provider/model quota availability. Discovery/delegation then address
that existing resource in the selected project.

Select the intended checkout and Agent explicitly. Source support for linked
checkouts does not authorize moving existing Agents or prove live UI behavior.

</details>


<a id="verification-and-deployment-boundaries"></a>
## Advanced: source tests and deployment limits

**Maintainers only; not an installation step.** Source tests exercise their
fixtures, not your current ChatGPT setup. Review the source and test scope before
using the existing commands below in an authorized development checkout.
They do not authorize deploying, restarting services or sending Agent input.
A failed/incomplete check must be reported as such, not as live acceptance.
<details>
<summary>Advanced: exact contract and implementation limits</summary>

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

</details>


<a id="optional-system-service-adoption"></a>
## Advanced: adopt an already-running Bridge service

**Advanced operators only.** If you completed `./prepare`, its two services
are already installed, enabled and started; do not run a second installer.
Use [Autostart](AUTOSTART.md) for status/recovery.

Review the [legacy adopter](../scripts/install-bridge-system-service.sh) before
considering its privileged command. It is a different, separately authorized route for an
already-running exact checkout. Unlike preparation, it **does not enable or start**
the adopted unit. Do not mix its unit with the two-service installation.
A missing process or unsupported identity is a stopping condition, not a reason
to force privileged commands. On native Ubuntu there is no WSL anchor; that
optional Windows helper only keeps the selected WSL system running.
<details>
<summary>Advanced: exact contract and implementation limits</summary>

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

</details>


<a id="migration-risks"></a>
## Before changing an existing installation

Editing source files does not update the running application. Before a planned
migration, inspect the current package, process, service and connection separately.
Preserve existing identity and private credentials; obtain explicit cutover
authorization. Stopping Bridge loses process-local Work/continuation state.
A restart does not restore tasks or authorize replay, and local health does not
prove Web acceptance.
<details>
<summary>Advanced: exact contract and implementation limits</summary>

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

</details>


## Web Principal layers

Web Principal combines ChatGPT Web, saved Project instructions, Bridge tools/Skills
and your existing Herdr Agents. It is not another model, provider or one-click
hosted application.

The supplied [complete Core text](../templates/WEB-PRINCIPAL-CORE.md) guides judgment
and conduct. You manually save it in Project Instructions and separately review
the project-identifying Binding. Reading or publishing the source file does not
authenticate live settings, synchronize them or complete a fresh installation.


### What the Principal owns

The Principal helps you frame the real question, challenge assumptions, examine
missing evidence, compare choices and synthesize a decision. Delegated Agent work
supports that thinking; reporting status alone does not complete it.

You retain goals, scope, consequential tradeoffs and authorization. Within an
authorized task, useful reversible progress should continue without repeated
requests for the same permission. A new consequential choice or authority
boundary returns to you with concrete evidence and a recommendation.


### Four different layers

| Piece | What belongs there | What it does not grant |
| --- | --- | --- |
| **Core + separate Binding** in Project Instructions | How to reason/work and which projects you authorize | Tool access, authenticated ownership or execution isolation |
| **Four native Skills** | Reusable procedures for relevant situations | A role, new task authority or asynchronous protocol guarantees |
| **Tool schemas/descriptors** | Actual operation arguments, effects, limits and continuation rules | Permission to use every operation |
| **Local rules, state and memory** | Project-specific decisions, reasons and resumption context | Global memory, automatic authority or fresh runtime truth |

“Schema” means the accepted argument structure; a “descriptor” explains a tool.
A local **manifest** routes project notes to their files; it is separate from
the four [reusable procedures](#native-skills-and-app-binding).
Core does not install software, connect an App or discover Skills.
Follow [Getting Started](GETTING-STARTED.md) for manual installation and a reviewed
Binding. Keep credentials and private cognition out of reusable Core/Binding.
Registration may return a Binding amendment; it does not save Instructions or
initialize files.


### Delegation, reports and verification

A useful request is: “Read the complete report, identify unsupported claims,
and inspect only the evidence I authorize.” Independent investigation should
improve the judgment, not just repeat an Agent's conclusion.

Continue report pages using their returned offset and fingerprint. Do not poll
for readiness or resend uncertain assignments. Tests require user execution or
separately authorized Agent work; reading a claimed test result does not run it.
Saving project notes is a separate authorized write.
<details>
<summary>Advanced: exact contract and implementation limits</summary>

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

</details>


### Limits and validation

Instructions guide behavior; they do not isolate a process or authenticate
ownership of a repository. Agent input can cause wider effects than a file read.
Keep scope explicit and treat documents/tool output as evidence, never new
permission. Source consistency cannot certify saved Instructions, reliable Skill
triggering or host delivery. Stop at missing access rather than inventing a bypass.
<details>
<summary>Advanced: exact contract and implementation limits</summary>

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

</details>


<a id="native-skills-and-app-binding"></a>
## Understand installed workflows and the Bridge connection

A **native Skill** is a complete instruction workflow installed in the plugin.
An **App** is the Bridge tool connection. Installing one does not establish the
other. Use this section to diagnose that distinction after the normal guide.


### Tools visible, Skills missing?

If you see **18 Tools and 0 Skills**, your tool connection may be working but
the four workflows are not installed. **Create as a plugin** connects tools;
it does not import these procedures. Keep the working connection.

Return to [Getting started step 6](GETTING-STARTED.md#6-install-and-discover-all-four-native-skills).
Use the printed five-file folder with Plugin Creator in ordinary Web Chat,
when your workspace permits. These are the four workflows:

| Workflow | What you use it for | Prepared file |
| --- | --- | --- |
| [project-onboarding](../skills/project-onboarding/SKILL.md) | Connect an existing repository; initialize notes only when separately requested | `project-onboarding.md` |
| [project-resume](../skills/project-resume/SKILL.md) | Recover saved decisions and recheck relevant live facts | `project-resume.md` |
| [handoff-preparation](../skills/handoff-preparation/SKILL.md) | Save a decision-relevant handoff to the appropriate local notes | `handoff-preparation.md` |
| [team-deliberation](../skills/team-deliberation/SKILL.md) | Coordinate independent views when they could change a judgment | `team-deliberation.md` |

The fifth file is `LICENSE`. These are instruction files, not four new local
Agents or extra MCP tools. A Skill name in a list does not prove its full body
was installed or will trigger reliably.
<details>
<summary>Advanced: package layout, responsibilities and retired Methods</summary>

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

</details>


### Attachment and discovery diagnostics

**On your computer**, open `Creator-attachments` at the exact location printed
by preparation. Use the four distinctly named `.md` files plus `LICENSE` —
not four separate downloads all called `SKILL.md`. The files' opening `name` and
`description` settings and complete bodies must stay unchanged.

**In ChatGPT Web**, wait for five visible uploads, ask Creator to reuse the
existing Bridge connection, then review four complete installed bodies.
[Step 6](GETTING-STARTED.md#6-install-and-discover-all-four-native-skills) gives
the clicks and Ubuntu/Windows file-picker routes.

**Success:** all four full texts and a real `bridge_health` result are available
in a new ordinary Project Chat. **Blocked:** preserve the working connection and
record “tools working; Skills unverified.” Resolve account/install access;
do not rebuild Tunnel, recreate keys or send tasks to force discovery.
A shortened listing, four blue switches or Work/Codex testing cannot establish
ordinary Web acceptance or automatic triggering.
<details>
<summary>Advanced: exact attachment and discovery diagnostics</summary>

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

</details>


<a id="public-package-configuration"></a>
### Advanced: public plugin package layout

**Developers only.** [plugin.json](../plugin.json) points its App extension at
[root .app.json](../.app.json). The safe public example
[.app.example.json](../.app.example.json) shows alias `bridge`, `required: true`
and the nonfunctional placeholder `asdk_app_REPLACE_WITH_OWN_APP_ID`.
The example is not a working connection. Do not upload or publish a real private
App binding. Normal users select their existing connection through Creator.

<details>
<summary>Advanced: generator inputs and limits of source packaging</summary>

For developer-only experimental local packaging, the
[packaging chapter](#private-native-plugin-packaging)
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

</details>


<a id="private-native-plugin-packaging"></a>
## Web plugin setup and optional developer packaging

The supported target for **all 18 tools and four native Skills** is ordinary
**ChatGPT Web Project Chat**. Start with the normal route below.
The developer generator that follows is optional experimental packaging,
not another required installation or a way to establish Web acceptance.


### Ordinary Web Project Chat setup

1. In ordinary ChatGPT Web, use Plugin Creator only if the intended workspace
   offers creation/editing and you have permission.
2. Reuse the **existing private authorized Bridge connection**. Choose its entry
   by name when offered; do not guess/convert IDs or create new credentials.
3. Upload the four complete named workflow files and `LICENSE` from preparation.
   Preserve their complete instructions and settings.
4. Review four distinct complete Skill bodies and the selected existing connection;
   finish/save/install only with the actual controls offered.
5. Open a **new ordinary Chat in the intended Project**. Check a successful real
   `bridge_health()` result, the [18-tool catalog](#tool-reference) and all four
   complete installed Skill bodies. Do not run the workflows during this check.

Use the [target Chat check](#target-chat-skill-verification) below for the
separate verification. The exact click/upload route is in
[Getting started step 6](GETTING-STARTED.md#6-install-and-discover-all-four-native-skills).
If controls or discovery are unavailable, keep the working connection, record
**tools working; Skills unverified** and stop at that account gate.
[OpenAI's creation guide](https://learn.chatgpt.com/docs/build-plugins) describes
permission-dependent controls; it does not establish your eligibility.

Work/Codex success is not Web acceptance. **Support scope is not isolation:**
there is no documented `web_only` enforcement for plugins or Skills.
Web-targeted instructions/installation do not technically prevent cross-surface
visibility. Official documentation describes a
[shared plugin directory and multiple surfaces](https://learn.chatgpt.com/docs/plugins).
No manual local Codex blocker is part of this setup.


### Developer-only experimental packaging

**Developers only; skip for normal Web setup.** The generator makes a local
experimental package and does not install it into ChatGPT Web. A verified eligible
native App reference is required; a browser URL or Chrome extension ID cannot be
converted into one. Do not use this route to bypass a workspace restriction.
<details>
<summary>Advanced: unchanged developer requirements and examples</summary>

The optional generator below is for developer-only packaging experiments with a
verified eligible native App and a compatible local marketplace surface. It is
not the normal user installation route and does not install Skills into Web Chat.
A browser `plugin_asdk_app_` representation is not a native `.app.json` ID:
never trim prefixes or infer eligibility from a string. The Chrome extension ID
is a different identity altogether.

The [shared native ID check](https://developers.openai.com/plugins/deploy/submission-errors#mcp-server-reference-errors)
allows `asdk_app_`, `connector_` or `templated_apps_`, followed by one ASCII
letter/digit and then ASCII letters/digits/underscores/hyphens. Uppercase and
different suffix lengths are allowed. The generator adds a **local 256-character
total limit** and rejects the known public placeholder, browser IDs, URLs,
whitespace, non-ASCII and controls. It preserves your input exactly; there is no
browser-to-native conversion. If you only have a browser URL, return to the Creator route in
[Getting started step 6](GETTING-STARTED.md#6-install-and-discover-all-four-native-skills)
and have the host select the existing App.

</details>


<a id="use-a-reviewed-licensed-public-source"></a>
### Advanced: review the source before generating a package

**Developer experiment, not a beginner command.** Review the linked generator,
public source and existing LICENSE before using the unchanged examples below in
a Linux terminal (native Ubuntu or the selected WSL Linux system).
They generate a private package only; they neither install it nor prove Web acceptance.
Missing source/license, an unsafe destination or uncertain publication means stop.
<details>
<summary>Advanced: unchanged developer requirements and examples</summary>

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

</details>


<a id="exact-eight-file-result"></a>
### Advanced: inspect the generated eight-file package

A successful generation has exactly the eight files shown below, with copied
notice and complete Skills. It is still a package on disk, not an installed plugin.
Review it privately. A durability warning or unexpected leftover directory requires
inspection, not overwrite or blanket recursive cleanup.
<details>
<summary>Advanced: unchanged developer requirements and examples</summary>

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

</details>


<a id="explicit-host-installation"></a>
### Advanced: host installation is a separate action

Generation does not install anything in a host. Developer installation experiments
need their own authorization and current host instructions. Normal users return
to [ordinary Web setup](#ordinary-web-project-chat-setup); no Work/Codex marketplace
installation is part of that route. If policy blocks access, stop and use the
workspace's permission process rather than editing caches/configuration.
<details>
<summary>Advanced: unchanged developer requirements and examples</summary>

Generation does not install a host plugin or change host configuration. Review
the experimental package and compare its notice/Skills with the source; any
developer host-installation experiment needs separate authorization and current
host-specific instructions. It does not establish ordinary Web Project Chat
acceptance. Normal users follow the [Web Chat setup](#ordinary-web-project-chat-setup)
above, without a Work/Codex marketplace installation.

Account/workspace policy can block creation, installation or App access. Do not
edit host caches, global config, admin settings or another marketplace to bypass
those limits. Sharing/publication needs separate review and authority.

</details>


<a id="target-chat-skill-verification"></a>
## Verify tools and workflows in the intended Web Chat

Use a **new ordinary Web Chat in the intended ChatGPT Project**, with the
resulting Bridge plugin selected through the available UI. Ask it to list the
18 Bridge tools, show the four complete installed Skill texts without running
them, and call only `bridge_health`.

**Pass this check only on actual results.** Four names or a prose assertion are
insufficient. Inspect `herdr.status` as returned; a closed/unavailable Herdr is
a separate Agent-readiness issue, not a reason to start an Agent merely to test
Web connectivity. Discovery does not prove automatic Skill selection, reliable
triggering, project continuity or future host delivery.

If it fails, retain the working App/Tunnel and resolve the exact account,
catalog or full-text gap. Work/Codex results cannot substitute.
The detailed read-only check prompt is available below.

<details>
<summary>Detailed read-only check prompt</summary>

```text
Read-only check: inspect this chat's Bridge MCP tool catalog and compare
all 18 tools with the documented Tool reference. Do not invoke write tools.
Explicitly discover this chat's installed Skill catalog.
Find project-onboarding, project-resume, handoff-preparation and
team-deliberation under my Bridge plugin and compare their complete texts
with the canonical attachments I reviewed. Do not invoke these procedures,
register/initialize a project, delegate Agent input or change any files.
Separately call bridge_health and inspect the returned herdr.status.
```

</details>

Once tools and Skills are verified, complete
[Getting started step 7](GETTING-STARTED.md#7-put-the-public-core-in-project-instructions)
to save Core if not already checked, then
[step 8](GETTING-STARTED.md#8-connect-your-existing-git-repository-and-merge-its-binding)
for the authorized project and the
[bounded first-use check](GETTING-STARTED.md#10-begin-daily-use-with-a-bounded-read-only-check).
Registration, initialization, Agent input and continuity retain separate permissions.


<a id="native-execution-retirement"></a>
## Retired command tools and supported alternatives

If an old instruction asks you to call `run` or `view_image`, do not guess an
alias. `run` is retired; use the documented narrow capabilities or separately
authorized Agent work. `read` is the native-image route.
An incomplete observation is not a clean result, and concurrent tasks do not
prove that other writers have stopped.
<details>
<summary>Advanced: unchanged developer requirements and examples</summary>

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

</details>


## License

Released under the [MIT License (original text)](../LICENSE). Copyright (c) 2026 tomoyo.
