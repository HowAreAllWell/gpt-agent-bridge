# Direct observation tools

[English](OBSERVATION-TOOLS.md) | [简体中文](OBSERVATION-TOOLS.zh-CN.md)

Use this page when you want ChatGPT to **check a particular file, compare changes,
read an Agent's full report, or retrieve an original file**. You can ask in ordinary
language; the technical names below help you recognize the tool results.

**First time using Bridge?** Complete [Getting started](GETTING-STARTED.md) first.
It covers **native Ubuntu Desktop** and **Windows+WSL2** separately. Ubuntu needs
no WSL or PowerShell. On either route, use the connected plugin in an ordinary
**ChatGPT Web Project Chat**. This page adds no installation or terminal commands.

For example, name a non-secret file in your authorized project and ask:

> Read only the file I named and explain the relevant lines. Show the actual file
> location and any missing or partial result. Do not edit, run commands/tests,
> search other files or send Agent tasks.

**A useful result:** the requested file content comes from the correct local
project, with enough lines to support the explanation. A sentence saying “checked”
is not evidence. If the path is wrong, access is refused or only part arrived,
stop that conclusion and report the limitation.

## Choose the evidence you need

| What you want | A request you can adapt in the connected Project Chat | What to look for |
| --- | --- | --- |
| Read a particular file | “Read only the named file and explain these lines.” | `read` returns the content, path and file fingerprint. |
| Find text in an allowed area | “Find this exact phrase only in the folder I named; read the relevant match.” | `search` returns locations; a snippet alone is not the whole file. |
| Compare changes | “Show changes to this named file and explain the actual patch. Do not stage or commit.” | `diff` shows the selected scope and any remaining pages or errors. |
| Review an Agent's result | “Read the complete report for this Work, then compare its claims with the evidence I authorize.” | `work_report` returns the published report, possibly in pages. |
| Retrieve an original | “Prepare this named PDF as an original file; tell me whether it was actually received.” | `prepare_file_attachment` returns temporary links, not extracted text or proof of upload. |

These examples do not authorize a whole-tree scan, private/untracked-file search,
writes or Agent input. Name the intended project and permitted files. Ask for
`list_entries` only when you want that directory's immediate names; it can reveal
ignored and untracked names even without reading bodies. `inspect_file` checks
one file's size and fingerprint without returning its content.

## Before asking: choose the project and understand partial evidence

- **Project identifier (`project_ref`):** the short name registered for the local
  repository you authorized. A ChatGPT Project title alone does not select it.
- **Work identifier (`work_ref`):** the record of a delegated task. If supplied, it
  selects that Work's recorded **checkout** — the local Git folder it used.
  It does not restore old file bytes or prove what the Agent executed.
- **SHA-256:** a fingerprint of the complete original bytes. Reusing it while
  continuing a read detects ordinary content changes; it does not prove authorship,
  correctness or an atomic snapshot of the whole project.
- **Pagination:** a long result arrives in pieces. The returned “next offset”
  tells the tool where to continue. A first page is not a complete file/report.

A direct file read proves which bytes were observed. An Agent report tells you
what the Agent published. Neither alone proves that a test ran successfully.
Ask for the relevant code, test definitions and authorized test receipts before
accepting such a claim. Do not widen access to secrets to fill an evidence gap.

## Read a file or compare changes

**In the connected Project Chat**, identify the exact file and question. Check
the returned project/folder before using its contents.

1. For text, continue with `content_next_offset` and the same `file_sha256` as
   `expected_sha256` until the requested range is complete. Let ChatGPT handle
   these fields; you need not calculate offsets manually.
2. For a search match, follow its `read_locator` to read the relevant lines in
   the same project/Work. Search defaults to tracked files; do not opt into
   untracked text unless you explicitly permit that scope.
3. For changes, distinguish **current files** from **two fixed commits**.
   Current search/diff pages are fresh observations and can change between calls;
   they are not saved snapshots. A filtered clean result applies only to that scope.
4. If a read's hash changes, keep old and new results separate and re-evaluate.
   An error, overflow or incomplete page does not mean “no changes.”

Images use `read` as a whole image, not text pages. PDF/DOCX requests to `read`
return `UnsupportedReadFormat`; use the original-file path below. Other binary
or invalid UTF-8 files can return `BinaryFileUnsupported`. No automatic document
extraction or parsing occurs.

**Stop when blocked:** explain the exact missing file, refused format, changed
content or incomplete comparison. Do not silently fall back to another checkout,
call a retired command tool or run a broad search.

## Read a complete Agent report

**Once a specific Work is terminal and its report is published and readable**, ask
for that exact Work's report with `work_report`. Other Works in the batch may
still be running, and browser notifications may be disabled. `result_ready` means
the artifact was readable and the Agent turn settled; you still need to judge its claims.

Use `work_report` through every page, with the returned continuation offset and
full-report SHA-256. Completing pages is reading the same report, not polling for
task readiness. A terminal tail from `agent_terminal_read` is current diagnostic
output, not a substitute for the full report or complete task history.

**Success:** you have the complete published report and can name what independent
evidence supports or contradicts it. **Blocked:** a missing/invalid report or
`attention_required` needs diagnosis; `WorkRefExpired` or `WorkRefUnavailable`
does not select a different project. Do not resend the task to obtain a report.
Reading it neither acknowledges result processing nor extends its retention.

## Retrieve a PDF or another original file

**In the connected Project Chat**, name the authorized file and ask to retrieve
its original bytes. A **ResourceLink** is a temporary retrieval link prepared by
`prepare_file_attachment`; creating it uploads nothing.

- At most **7 MiB** produces one original-name link. A larger original produces
  ordered part links and a **receipt** listing the original name, full size,
  SHA-256 and part names.
- Receiving parts separately is not receiving the original. The receiving side
  must locate the materialized files, join them in receipt order, and verify the
  full original size and SHA-256. Bridge adds no automatic Web assembler.
- A successful prepare/fetch does not prove approval, ChatGPT import, attachment
  or File Library presence. The host must actually support and complete those steps.

**Success:** the original, or the assembled original, is present and verified on
the receiving side. **Blocked:** if links expire, the file changes, a part fails or
the host cannot import/assemble it, say “original not verified as received.”
Inspect the current situation before any new preparation; never present an
unverified partial file as complete or promise every large file will fit.

## Exact read and attachment contracts (advanced)

The following is for developers and anyone checking an exact limit or error.
“Source contract” means documented implementation behavior, not a completed
test of your running service or ChatGPT account.

<details>
<summary>Advanced: exact catalog, read/search bounds and original-file transport</summary>

These are SOURCE contracts; current runtime/host acceptance requires separate evidence.
The SOURCE catalog registers 18 model-facing tools; the three retired app-only widget tools are absent.
All registered tools reject extra arguments in the actual SDK validator before entering
the tool function. Annotations describe effects, not authorization or guaranteed client approval.

Use explicit project_ref. Optional work_ref pins the existing recorded checkout, not
a file snapshot or the original task's truth. Unknown/replaced Work does not fall back
to the main tree. Existing reader gates and target revalidation apply.

| Intent | Tool and reread |
| --- | --- |
| Discover a directory | list_entries(path=".", offset=0, limit=50). Direct children only; follow returned entry paths and next_offset. Pages are fresh observations, sorted Unicode names. |
| Read text | read defaults to 4096 Unicode characters; maximum 16384. Continue with content_next_offset and expected_sha256=file_sha256 to reject changed original bytes. Optional absolute 1-based inclusive end_line ceilings the page at that full-representation line (beyond EOF clamps); it works alone, with start_line, or with a nonzero offset continuation. Images are whole native blocks, up to 5 MiB, plus one compact metadata text block and no structuredContent. |
| Refuse PDF/DOCX | read refuses PDF/DOCX by validated suffix (case-insensitive) before reading any bytes (UnsupportedReadFormat) and points to prepare_file_attachment for the original; it does not approve, parse or assemble attachments. Other binary/invalid-UTF-8 bodies stay BinaryFileUnsupported with the same guidance. |
| Retrieve a full Agent report | Every admitted Work requests a report. Once a specific Work is terminal and its report is published and readable, use work_report for that exact Work with Unicode offset/limit and expected_sha256. Other Works may still run, and browser notifications may be disabled. A missing or invalid report needs attention; only the published private artifact is read. |
| Find a line | search defaults to tracked files. include_untracked=true additionally searches nonignored untracked text. Both branches share one literal-pattern query validation (1..500 characters, no NUL/LF, valid UTF-8; the pattern is passed as an explicit `-e` operand with literal pathspecs) and return each match's raw first ≤300 Unicode characters (record-ending LF excluded; CR/whitespace preserved, no invented marker or ellipsis) plus `line_text_truncated` and a `read_locator` {path,start_line} for the same project/work_ref. Malformed or nonpositive grep line records and a no-match status carrying output are rejected. Snippets do not prove full-file content. |
| Inspect binary or large text | inspect_file gives regular-file mode, byte_size and full original-byte SHA-256, without body. This does not make binary files readable as text. |
| Prepare original bytes | prepare_file_attachment hashes the current source and prepares expiring ResourceLinks for later resources/read; nothing is uploaded, host-imported, assembled or attached yet. It returns one original-name/MIME link with no TextContent for <=7 MiB; otherwise ordered octet-stream links plus only multipart {target, size, sha256, parts}. Internal metadata lookup and bounded part fetch preserve source stat/path and part hash checks; see [attachment contract](TECHNICAL-REFERENCE.md#original-file-attachments) for source mechanics; live host acceptance requires separate checks. |
| Publish continuity | Read manifest state, then current_state_update with required expected_revision and exactly one of content or edits. This is state publication, not a Git commit or verification of supplied claims. An opted-in bridge-state-slot adds a mechanical body-byte and limit-identity refusal; it does not summarize or truncate. |
| Inspect changes | diff uses the existing current or pinned-commit contract in [Work evidence](#work-target-evidence). Unknown is not clean. |

Directory listing scans at most 4096 direct entries / 1 MiB name bytes, returns at most
100 entries per page, and excludes .git. It includes ignored/untracked names without
opening their bodies. It reports links/special files; it does not follow them.
Inspect hashes at most 64 MiB in bounded chunks and checks pre/post stat and path
binding; changed/oversized/special/link targets fail without a purported full hash.
Both tools bound the serialized structured envelope to 32 KiB; names are not truncated.
Their cooperative filesystem deadline is 10 seconds, not a kernel-stall SLA.

Opt-in search uses two fixed Git passes sharing 5 seconds and 1 MiB combined stdout
plus 4096-byte stderr caps; one pass retains tracked ignored files. Results deduplicate
matching path/line pairs and reject contradictory repeated lines. Maximum 50 matches
per page, 300 Unicode snippet characters, 100000 match offset; query is one literal
pattern of 1..500 characters without NUL/LF, passed as an explicit `-e` operand with
literal pathspecs; grep color and column output are explicitly disabled (`--no-color`,
`--no-column`) on both branches so ambient `color.ui`/`color.grep`/`grep.column`
configuration cannot inject bytes into paths or snippets. Numbered NUL-path records are
validated (incomplete, nonpositive
or overlong line numbers, or a no-match exit with output, fail without a coverage claim).
Snippets are the raw decoded prefix with no invented truncation marker. The structured
envelope is at most 32 KiB.
It excludes nontracked ignored files, binary bodies and recursive submodule worktrees.
Directory/path locators preserve literal names, including ./ for root whitespace names.
Search and current-diff pages are fresh, unpinned observations with no consistency
token or retained snapshot. Read/image and tracked-search metadata do not request
checkout dirtiness or open/hash unrelated dirty/untracked bodies. Read integrity
uses the selected file's SHA-256; historical diff pages can use the exact resolved
base/target commit IDs.

Fixed Git observations deny transport protocols (including implicit partial-clone
fetch), disable fsmonitor/hooks/pager/textconv, and return unsupported for clean/process
filter configuration. No permanent config or index writes are requested: diff
observations additionally suppress Git's index auto-refresh write
(`diff.autoRefreshIndex=false` command-locally), because that refresh rewrites the real
index even under --no-optional-locks and would mutate the exact staged index a selected
prepare froze. Diff output is unchanged; stat-dirty entries are still content-compared
without the write. Status/diff do not inspect nested submodule worktree dirtiness. Query errors/overflow are incomplete
observations; read can still return a file body without requesting Git status. Probe/query
and filesystem checks are not atomic against outside writers; no OS security isolation
or whole-tool latency/memory guarantee is implied.

MCP structuredContent carries necessary structure/body once. Only text proven to
serialize that same payload is removed; distinct text and native image blocks remain.
`prepare_file_attachment` returns one ResourceLink with no TextContent for <=7 MiB, or ordered
part links plus exactly one compact receipt containing only multipart {target, size,
sha256, parts}: original basename, full bytes/SHA and ordered materialized part names.
There is no body/base64, outputSchema or structuredContent in the tool result.
The raw part cap remains 7 MiB (7340032 bytes): ~9.33 MiB base64 leaves ~0.67 MiB
under an example 10,485,760-byte relay response budget for overhead. That safety
margin is not an official original-file limit. The arbitrary 128 MiB original bound
and 128-entry attachment count/eviction are removed; actual deadlines/transport
capacity still apply. resources/read remains one base64 result per part. There is
no standard streaming/reassembly or public range API, only a bounded internal reader.
One internal PendingAttachments metadata entry per original has finite expiry/GC,
no renewal/restart durability and no file bytes; TTL/retention/status/provenance are
absent from successful results. Preparation hashes the whole file and each part;
expected_sha256 pins the full original. Fetch checks saved stat/parent identities,
part hash/length and pre/post descriptor/stat/path/lookup expiry/identity. Ordinary
mutation anywhere fails closed; spoofing all observed identities/timestamps can hide
edits outside a fetched part. Final full-SHA verification remains necessary.
Single files use bridge://attach/{capability}; multipart uses canonical /part/0001
ordinals extending beyond 9999 and deterministic names. Recipients concatenate
materialized parts in receipt order and verify full SHA/size. Bridge adds no automatic
Web assembler/post-materialization hook; assembly still requires Web-side orchestration.
`view_image` is retired from SOURCE; read is the native-image route (whole native
image plus one compact JSON text metadata block, no structured result). Source and
wire tests do not establish host file import, approval behavior or visual recognition.
Delivery, attention, settlement and exit codes describe observations, not task acceptance.
Public run is retired from SOURCE; narrow commit_prepare/commit now implement version actions. Exact continuity
CAS rules are in [Project continuity](PROJECT-CONTINUITY.md).

Reader leases for read, default search, current/pinned diff remain held until their worker
ends, even after repeated cancellation; current_state_update and commit reuse the same join boundary.
The original cancellation is preserved if that worker later fails. This is not an OS deadline.
Candidate summary/patch/receipt pages contain captured facts, not today's dirty projection;
see [candidate version actions](#candidate-version-actions).

Public read has NO document extraction route: it refuses PDF/DOCX by validated suffix
(`UnsupportedReadFormat`) before reading any bytes and points to prepare_file_attachment for the
original. prepare_file_attachment only returns original-file links/receipts; it does not parse
documents or produce readable text, and nothing calls it automatically. No document-extraction
utility exists in this repository; historical extraction behavior is not an active public
contract.

`agent_terminal_read` accepts 1..400 lines (default 120) with a 16 KiB character cap.
`truncated=false` only describes that cap on the returned tail; it proves neither
complete history nor complete report content. Every admitted Work requests a dedicated
report; once that specific Work is terminal and its report is published and readable,
use `work_report` for that exact Work. Other Works may still run, and browser
notifications may be disabled.
A missing or invalid report is attention, not successful task completion.

</details>

## Direct project text edits

Use this section only when you have authorized changing a particular existing
text file. Merely asking to inspect a file grants no edit permission.

A safe first request is: “Read this file and propose the exact replacement;
do not apply it yet.” Review the proposal and its source fingerprint before
authorizing `project_text_edit`. The tool can apply exact replacements to an
existing UTF-8 file; it is not a file-creation or command interface.

**Success:** a receipt identifies the target, before/after hashes, byte counts and
edit count. That is evidence of the bounded edit, not proof the resulting code is
correct. **Blocked:** stale hashes or ambiguous replacements require rereading
and reconciling the proposal. An unknown post-write outcome requires inspection,
not blindly applying the edit again.

<details>
<summary>Advanced: exact edit signature, validation, race and state-slot boundaries</summary>

project_text_edit(project_ref, path, expected_sha256, edits, work_ref=None) changes only an
existing regular UTF-8 project file. The full lowercase 64-hex SHA256 is required, without
the current-state sha256: revision prefix. Use the hash of bytes actually read. Supply 1..256 exact
{old_text,new_text} objects: old_text is nonempty, unique in the same original, and
nonoverlapping; replacements apply once against that original. File/result <=1 MiB;
aggregate old/new edit bytes <=2 MiB. NUL/binary, invalid UTF-8, links/special files,
.git/traversal, creation, directories and mode changes are refused. Untouched bytes,
CRLF and original mode remain; no normalization, commands, hooks, staging or commit.

Explicit project_ref and optional work_ref resolve the same frozen evidence checkout as
read/search/diff. The existing writer lease covers the cancellation-shielded worker through
cleanup. No-follow descriptor traversal pins parent bindings; the full source hash and file
identity/mode/timestamps are rechecked immediately before atomic replacement. Success returns
only target provenance, hashes, byte counts and edit count. Post-replace observation/fsync or
acknowledgement loss is unknown and never blindly retried. These checks serialize cooperating
Bridge writers, not external processes: there remains a check/replace race window. A receipt
proves bounded bytes, not authenticated authorship, truth or acceptance. current_state_update retains
its separate manifest-only 65536-byte, full-content/exact-edit and missing-creation contract.
When the state file opts into one bridge-state-slot, that same publication also refuses
a malformed, removed, widened, narrowed, or over-limit slot and writes nothing. Manifest routing is unchanged by this editor. project_text_edit remains an exact-edit bypass.

</details>

## Candidate version actions

Read this when you explicitly want to prepare or make a Git commit. A **candidate**
is captured staged content to review. The **index** is Git's staging area.
A **receipt** records the outcome of one attempted operation.

**Preparation can change staging.** Do not request it during a read-only review.
First ask: “Show the current changes in these named files; do not stage or commit.”
Only after reviewing them should you authorize a particular preparation mode.

| Mode | What it does |
| --- | --- |
| `commit_prepare` with `paths` | Stages the selected literal paths and freezes a candidate; may write Git objects. |
| `commit_prepare` without `paths` | Captures content already staged, without changing the repository. An empty list is not this mode. |
| `commit_prepare` with `candidate_id` | Reads saved candidate pages; does not recapture or stage. |
| `commit` | Publishes that exact candidate using your configured Git identity and explicit message. |

Review the saved summary and all needed patch pages before separately authorizing
the exact commit. A truncated patch does not show every changed byte; binary
content may have only metadata. Neither a candidate ID nor “ready for review”
grants permission.

**Success:** distinguish a prepared candidate from a committed receipt.
**Blocked/unknown:** inspect the existing candidate receipt and current authorized
evidence. A lost response, consumed ID, expired Work or cache miss is not permission
to make a replacement candidate or retry a mutation. The detailed replay rules
below return old receipts for the same already-attempted request; they do not
execute it again or provide durable recovery.

<details>
<summary>Advanced: exact preparation/commit modes, limits, index validation and receipt replay</summary>

commit_prepare(project_ref, paths=None, work_ref=None, candidate_id=None, view="summary",
offset=0, limit=50) has three explicit modes. With paths, prepare 1..2048 exact literal
repository-relative regular-file paths (at most 16 KiB total UTF-8 path bytes and
4 MiB total captured contents). The 2048-path complexity ceiling bounds temporary inodes,
captured records and repeated filesystem validation; excess count returns
selection-path-count-limit, independently of Git query count. Ordinary tracked
modifications, new files and explicit tracked deletions are supported; no globs, pathspec
magic, directory recursion, .git/traversal, symlinks/special files or arbitrary argv. Literal
metacharacters in actual filenames remain literal. It refuses staged paths outside selection,
mixed staged/unstaged selected content, intent-to-add and selected assume-unchanged/skip-worktree
flags; deliberate partial-hunk staging stays intact. Unrelated working files are preserved.

Preparation copies the real index privately and captures every selected file before object
writes. A private temporary directory holds only captured bytes in at most 2048 generated
regular files. One hash-object -w --no-filters --stdin-paths call writes raw blobs; generated
ASCII names travel on stdin, not argv, avoiding count-dependent ARG_MAX pressure and user
pathname quoting/option hazards. Every returned SHA-1 or SHA-256 OID must match the captured
hash in order. Git never rereads selected worktree files for object creation. Deletions
need no blob and a deletion-only selection makes no hash-object call. The temporary copies
are removed on normal/exceptional unwind. Only then is the private index updated.
Candidate/policy/selection/cache validation
precedes real-index installation. Under the Bridge writer gate and Git index.lock it rechecks
selected bytes/bindings, policy, target, HEAD/branch and full real-index hash, then atomically
installs the prepared index and confirms its snapshot. Cache insertion and candidate-ID
publication happen only after lock and outer preparation-directory cleanup succeed.
A refusal before installation leaves the real index intact, although objects may remain.
Preparation reports index_updated/objects_may_remain/ref_updated separately; it never moves
refs. An uncertain installation/cleanup returns unknown, issues no publishable candidate and
quarantines that checkout/branch within the process; it neither rolls back nor retries.
No restart durability or automatic reconciliation is supplied.

Selected-path preparation stages raw bytes: it explicitly refuses all configured nonempty clean/process
filters, even unrelated drivers, active post-index-change hooks (in addition to existing commit
hooks), core.autocrlf conversion, and selected filter/text/eol/working-tree-encoding/ident
attributes. Unsupported helpers are refused rather than silently run or omitted. After hook
admission, private update-index uses a fixed no-hook override to prevent a newly introduced
hook running in the check/use gap; raw hash-object never invokes content filters. Conversion
support is a future scope decision, not a generic Git add escape hatch. Existing configured
identity and R3 repository/storage restrictions still apply. Each operation retains its
30-second deadline and bounded subprocess output. Selected preparation retains a fixed
96-call Git-observation ceiling (already-staged capture retains 64); blob writes consume
one call regardless of file count. Total captured-content overflow returns
selection-total-byte-limit and total path-byte overflow returns selection-path-byte-limit.

Omit paths (or use null) to capture the already-staged index without repository writes;
this explicit mode preserves existing partial-hunk workflows. An empty list is rejected.
With candidate_id, paths must be omitted: page the immutable captured summary/patch/receipt
without Work lookup, gate acquisition, Git observation, recapture or repository writes.
A freshly prepared candidate reports "Commit candidate ready for review" with
index_updated/ref/objects effect facts; cached candidate paging reports a saved candidate
page with no staging or recapture in that response; rejected/unknown stay honest with
reasons. Initial status previewed
means a frozen candidate is available for review, not permission or task acceptance.
There is no public commit_preview or stage_paths compatibility alias.

summary counts files and lists every staged path with status,
modes, object ids, staged blob sizes (null for gitlinks/missing objects) and a binary
flag derived from one aggregate numstat pass. patch counts Unicode characters and is
bounded display evidence only: binary files render as Git's "Binary files ... differ"
line, aggregate text past the display cap stops with an explicit truncation marker
(`patch_truncated`/`patch_complete`), invalid UTF-8 decodes with replacement
(`patch_decode_lossy`), and display loss marks `patch_unavailable` with a reason — none
of which invalidates the frozen candidate, blocks summary, or blocks the exact commit.
Candidate identity is the staged index/tree/parent/branch/policy snapshot, never patch
bytes. limit is 1..16384, with files/events capped at 100 per page. Continue with
candidate_id and the same project/work route; pages are the captured candidate, not a fresh
dirty snapshot. read/diff remain available when today's evidence is wanted.

commit(project_ref, candidate_id, message) uses that staged tree, configured identity and
an explicit nonblank UTF-8 message (at most 65536 bytes, no NUL). It creates objects and
materializes captured mode/OID/name entries with one mktree -z --batch (children before
parents), checks every returned tree OID, then uses commit-tree and parent ref CAS. It never
uses write-tree or refreshes the working tree/index for commit; working files and the real index retain their
bytes, including unstaged changes. Existing project checks apply to every call including
receipt replay. IDs confer no authority; missing IDs or changed targets do not recapture.
Already-staged capture uses a reader gate; selected preparation and commit use the writer gate plus exact candidate target,
snapshot and index/ref CAS revalidation. Worker execution and cleanup finish before
leases release, including cancellation.

A repeated same request returns only its old receipt. rejected, unknown and committed are
different outcomes; objects may remain even after rejection, and unknown does not establish
whether a ref changed or permit another attempt. Cancellation/lost responses require inspecting
existing candidate receipts, not automatically starting another candidate. Cache is process-local
(8 entries/32 MiB; unknown attempts not evicted), not durable recovery or global idempotency.

This implementation supports bounded local Linux/files-ref repositories with configured
identity. It rejects unsupported signing, fsmonitor, split-index, promisor/alternate storage,
indirect metadata and active pre-commit/prepare-commit-msg/commit-msg/post-commit and
reference-transaction hooks rather than suppressing them. For already-staged capture/final
commit, neither post-index-change nor post-checkout is rejected: this staged-object primitive
does not invoke them. Selected preparation refuses active post-index-change hooks as above. Matching
required process/clean filters are not executed by already-staged capture/commit; no filter config
is disabled to obtain this behavior. R2's private-index write-tree could execute a matched
process helper and is superseded. Fixed working-file observations retain their own
unsupported-filter boundary. No implementation limit here defines another repository's
local capability ceiling.

Each Git stream is capped at 4 MiB; operation work has a 30-second budget and 64-query cap,
the captured mktree batch and expected OID output are each bounded at 4 MiB and count
toward the cache. Cleanup/OS-call limits are not a hard total latency SLA. External writers and shared
refs/config can race between checks; worktrees are not OS security isolation. No public
path/argv/env/approval-token parameter or generic host-command replacement is added.

Final commit admission tolerates exactly one class of live-index change: an ordinary
status-style stat-cache refresh. A bounded v2/v3/v4 index parser validates format, the
trailing checksum and layout (entry modes — 040000 sparse directory entries refuse —,
declared name lengths equal to the full reconstructed name in every version (saturating
at 0xFFF, UTF-8 bytes), name constraints and strict (path, stage) order, NUL v2/v3
padding, reserved extended-flag bits, unknown mandatory extensions (any signature whose
first byte is not uppercase — native Git ignores unknown uppercase-first extensions),
and the split-index "link" / sparse-index "sdir" extensions) and compares a normalized
identity that zeroes only each entry's time/mtime/dev/ino/uid/gid/size; paths, modes,
OIDs, stage, assume-valid/skip-worktree/intent-to-add flags, padding and raw extension
bytes are compared exactly, with v4 names reconstructed using Git's strip-from-the-previous-end
semantics. Capture validates the anchor — and the prepare-time live original — once, so
unsupported layouts refuse even when raw index bytes never diverge. Pre-lock
observations may follow several stat-only refreshes; at the final locked admission the
latest eligible live index bytes are validated and sealed as the raw baseline and
admission closes: from sealing through mktree, commit-tree, update-ref and post-CAS
revalidation every check is byte-exact, a first post-seal divergence rejects before ref
mutation, and a post-update-ref divergence stays honest unknown. The captured index is
never reinstalled and commit itself writes no index. Selected-path prepare installation
and preview keep strict raw-byte CAS.

Work routes use bounded process-local receipts: 512 recent terminals per project/root,
with no read renewal. Expired refs reject without target fallback; missing refs whose
cause is no longer known return WorkRefUnavailable. Candidate caches and unknown-attempt
quarantine survive Work expiry. Existing summary/patch/receipt pages remain pure cache
reads under project authorization and exact candidate project/work matching, using the
frozen target. Historical pages and field-stable same-message attempted receipt replay
perform no candidate Git mutation/inspection, Work resolution, recapture or rebinding.
Entry still first performs current project authorization/WorkspaceRegistry identity
validation, which executes bounded read-only Git identity checks; the whole call is not
Git-free. Different messages reject. New preparations and unattempted commits
still require Work. Candidate eviction returns candidate-unavailable-no-recapture;
these historical caches do not imply safe retry. context/bootstrap expose compact capacity counts; no Work
cleanup tool or destructive await mode is added. See [Work capacity](LIFECYCLE-RESTART-CONTRACT.md#work-capacity-and-report-lifetime).

</details>

## Work-target evidence

Use the following lookup when a file result came from the wrong place, a long
result is incomplete, or you need to understand exactly what was checked.
The project/Work selection must remain explicit throughout a read.

### Choose the project or recorded Work folder

A Work chooses its recorded folder, not a saved copy of every file. If that folder is missing, replaced or unavailable, the read must fail instead of selecting the main project.

<details>
<summary>Advanced: target identity and exact read/search/diff signatures</summary>

`read`, `search`, `diff`, `list_entries`, and `inspect_file` accept optional `work_ref`. Omission selects the
explicit registered `project_ref` root. A supplied Work must belong to that
exact project/root and carry immutable evidence metadata captured at the existing
writer-gated binding immediately before handoff/prompt. `EvidenceCheckout`
stores only the checkout path and existing `GitWorktreeIdentity` fields.
Capture failure leaves metadata unavailable and does not change dispatch.
Generic Pi and other providers share reported/foreground same-common-Git checkout
validation. Foreground selects execution when present; session metadata does not override
that checkout or permit fallback. Work freezes this exact linked checkout independently
of later Agent discovery; movement/replacement still fails closed.

`_resolve_evidence_target(project_ref: str, work_ref: str | None = None)` returns
`EvidenceTarget | dict[str, Any]` (a structured error). It revalidates registered
project identity, saved checkout identity, and exact Git common-dir path/device/
inode. It never consults a current Agent or handoff, registers a path, creates a
checkout, or recovers Work. While its bounded receipt is retained, a terminal Work remains usable after handoff
pruning. Earlier/unbound Work without metadata is unavailable. Unknown Work has
honest never-issued-or-lost-after-restart semantics. A missing/replaced checkout
fails even if its path or repository name matches. The target's existing reader
gate is used, with identity rechecked after gate acquisition.

```python
read(project_ref, path, offset=0, limit=4096, work_ref=None, start_line=None,
     expected_sha256=None, end_line=None)
search(project_ref, query, path_prefix=None, max_matches=20,
       work_ref=None, match_offset=0, include_untracked=False)
diff(project_ref, path=None, view="summary", staged=False, offset=0, limit=32768,
     work_ref=None, base=None, target=None)
```

</details>

### Continue text reads and handle format errors

Use returned continuation fields and the same original-byte fingerprint. A clipped result is only the requested range. Client hints such as readOnlyHint describe behavior; they do not authorize access or guarantee an approval dialog.

<details>
<summary>Advanced: line/character ranges, image formats and result serialization</summary>

Text read accepts 1-based LF-delimited `start_line` or a Unicode character offset.
Nonzero `offset` plus `start_line` is ambiguous and rejected. Optional `end_line`
is an absolute 1-based inclusive final line of the full representation; it may be
used alone, with `start_line` (it must not be below it), or with a nonzero offset
continuation, and beyond EOF it clamps to EOF rather than failing. Pages never
cross the selected ceiling, continuation repeats the same `end_line` with the
returned offset and no `start_line`, and `content_next_offset` is terminal once
the ceiling is reached. Output includes
`content_offset`, `content_end_offset`, `content_start_line`, and 1-based
`content_start_column`; continue using `content_next_offset` without
`start_line`; send `expected_sha256=file_sha256` to reject changed bytes between reads. Full-file SHA-256 covers original bytes, including CRLF. A final LF
has an empty EOF line location; requesting beyond the final location fails.
Images remain native whole-image responses; line/character paging is rejected.
PDF/DOCX are refused by validated suffix (`UnsupportedReadFormat`) before any
body read; other binary/invalid-UTF-8 files remain `BinaryFileUnsupported` with
brief prepare_file_attachment guidance.

`read` advertises `readOnlyHint=true`, `destructiveHint=false`, and
`openWorldHint=false` for its bounded registered-filesystem operation. These are
client hints, not authority, permission policy or a guarantee of UI behavior.
It publishes no outputSchema; SDK argument validation and extra-argument
rejection are unchanged, and text pages plus application errors keep their
structuredContent metadata while a private metadata model validates every
result before serialization. Proven duplicate
JSON text is removed; unique explanations remain alongside a neutral short summary.
Image success returns native image content plus one compact text block holding the
full metadata dict, with no structuredContent, no base64 in metadata and no result
wrapper. Absent fields stay absent;
nullable continuation/provenance values stay null.
Application errors do not become protocol `isError` results; SDK argument/protocol
failures remain distinct. All registered argument models reject extra fields. Offset
is nonnegative, text limit is 1..16384 Unicode characters, and whole images have
the existing 5 MiB bound. Validation is structural, not evidence of task
success or cognition. Source changes require separately authorized runtime/client
refresh before any claim about what the current client displays.

The descriptor/result distinction follows the
[OpenAI tool reference](https://developers.openai.com/plugins/reference);
[developer mode](https://developers.openai.com/api/docs/guides/developer-mode)
documents the client's use of readOnlyHint.

`view_image` was the former Web compatibility path: the same reader gate, target
revalidation, nofollow descriptor read, suffix/magic check and 5 MiB image cap,
advertising no outputSchema and returning one native image plus one compact JSON
text metadata block on success, text error metadata only on failure. It was retired
from SOURCE; read keeps that image serializer and its text/error structuredContent.
Read is the only native-image route. SDK/wire evidence does not establish the Web
client's visual recognition.

Public read no longer extracts PDF/DOCX: those requests fail as
`UnsupportedReadFormat` by validated suffix (case-insensitive) before any byte is
read, and `prepare_file_attachment` is the way to prepare the original for later fetch; read does not
approve, parse or assemble it. The historical extraction implementation was retired; no
extraction utility exists in this repository. Historical extraction behavior is not an
active public contract. See [observation tools](#direct-observation-tools) for bounds and rereads.

</details>

### Understand report availability

A published report is Agent-authored evidence. Missing or invalid publication is an explicit problem, and a ready classification does not certify its contents.

<details>
<summary>Advanced: report signature, publication, classification and lifetime</summary>

`work_report(project_ref, work_ref, offset=0, limit=4096, expected_sha256=None)`
reads only the private report allocated for that admitted Work, after
the Work becomes terminal. It validates the current registered project and exact
Work binding, not the current Agent or checkout contents. No raw-path selector is
exposed. The publication instruction additionally asks the Agent
to front-load its conclusion, decisive evidence and material limitations within
the task's requested format; Bridge does not parse, grade, certify or reject
report structure, and the artifact remains complete free-form observed content.
The 1 MiB original-byte SHA-256 pins Unicode continuation (maximum 16384
characters per page). Missing, unrequested, nonterminal, oversized, empty, invalid
UTF-8, symlink/nonregular, changed and unavailable reports are explicit errors;
no terminal-tail fallback exists. Provenance says Agent-published observed content,
not task success, authenticated authorship, or a byte-for-byte provider transcript.
Report files and Work are process-local; [Work capacity](LIFECYCLE-RESTART-CONTRACT.md#work-capacity-and-report-lifetime) owns cleanup
and expiry. This tool adds no durable report archive or file publication endpoint.
An optional notification batch names `work_report` for `result_ready` Works and
`agent_terminal_read` for `attention_required` Works. This is notification guidance,
not a report-read gate: once a specific Work is terminal and its report is published
and readable, `work_report` can read it while other Works still run or notifications
are disabled. Neither batch readiness nor its notice certifies task success. Publication and settlement are separate observations. `work_report` itself
does not wait or run an automatic retry loop. Classification probes the dedicated
report after the latch and before final classification: `WorkReportMissing` only, initial read
plus at most two rechecks about one second apart, added waiting within five seconds.
That cap bounds the injected waits, not OS I/O wall-clock time. Other errors classify
immediately. `readable` plus `agent_turn_settled` is `result_ready` and proves presence
only. A missing or invalid report is `attention_required`. The probe is not an
automatic Principal loop.

</details>

### Follow search locations

A match points to a line to inspect. Its short snippet may omit decisive context, and another page can observe later filesystem state.

<details>
<summary>Advanced: literal search, snippets and fresh-page limits</summary>

Search parses Git's filename-NUL/line-number-NUL/content-LF records before
decoding, so colons and newlines in filenames do not lose matches. Each match
includes a `read_locator` (`path`, `start_line`); reuse the same project/work ref.
It covers tracked current files, including tracked files matching ignore rules,
and by default excludes untracked/binary files. Explicit `include_untracked=true`
adds nonignored untracked text via two bounded passes, preserving tracked ignored files.
See [observation tools](#direct-observation-tools) for opt-in limits and directory/hash tools. Line snippets are the raw first 300 Unicode
characters of the decoded line: the record-ending LF is excluded, CR and other
whitespace are preserved, and no invented marker or ellipsis is added;
`line_text_truncated` is true exactly when the decoded line is longer than 300
characters. Default and opt-in search share one literal-pattern query contract
(1..500 characters, no NUL/LF, valid UTF-8), pass the pattern as an explicit `-e`
operand with literal pathspecs, explicitly disable grep color and column output so
ambient `color.ui`/`color.grep`/`grep.column` configuration cannot inject bytes,
prefix whitespace-only root filenames with `./` so returned locators stay followable,
and reject incomplete/nonpositive/overlong numbered
records or a no-match status carrying output. `match_next_offset` continues bounded result pages (at
most 50 matches); each page is a fresh, unpinned observation with no retained
search snapshot or cross-page consistency token. Invalid UTF-8 snippets use replacement decoding;
strict UTF-8 read may consequently reject a file search can locate.

</details>

### Compare current changes or fixed commits

For today's files, keep scope and any partial status visible. For a historical comparison, keep both returned commit IDs for subsequent pages; branch names can move.

<details>
<summary>Advanced: diff modes, paths, Git queries and incomplete results</summary>

Diff defaults to current uncommitted observations. Commit comparison requires
both `base` and `target`, rejects `staged=True`, resolves each revision once to a
full commit ID, and runs Git against those IDs without switching branches.
Continue with returned `base_commit`/`target_commit` to pin later pages even if
branch names move. Comparison excludes current index, worktree, and untracked
changes. Paths are literal Git tree paths, independent of current symlinks.
Renames are represented as delete/add; binary differences are metadata only.
`offset`/`limit` address characters for patch or files for summary (100-file cap).
Current summary also provides file continuation; ordinary current patch still
excludes untracked files unless an explicit untracked path requests a synthetic
patch. Missing paths in a commit comparison naturally produce no difference.

Current summary parses porcelain-v1 `-z -uall` and numstat `-z` records before
decoding UTF-8 paths. It includes tracked changes and individual nonignored
untracked files, including nested files. Spaces, tabs, LF, quotes and literal
` -> ` in names are preserved, not Git-quoted or split into separate entries.
For Git-detected rename/copy entries, `path` is the destination and
`original_path` is the source; a current summary path filter matches either.
Reuse `path` with `read` and the same project/work ref; existing path/permission,
file-type and missing-file restrictions still apply (a deleted source need not
be readable; the existing read validator still rejects all-whitespace-only paths). Current summary continues to combine index and worktree status
and counts even with `staged=True`; that flag selects the index for current
tracked patch. Numstat rename records use the destination, combine both sides'
counts, and preserve binary/unknown counts as null. Untracked counts are null.
Current tracked patch paths are literal; Git diff calls explicitly disable
external diff, textconv and color. Current tracked patches (unstaged and staged)
and base/target commit patches are generated with fixed `--unified=3` and
`--inter-hunk-context=0`; summaries, numstat and the synthetic untracked-file patch
are not, so ambient `diff.context`/`diff.interHunkContext` configuration or an
inherited `GIT_DIFF_OPTS` variable cannot expand or fuse hunks. Fixed Git
subprocesses receive a child environment with inherited `GIT_DIFF_OPTS` removed;
the parent process environment and persistent Git config are never modified.
The new machine observations disable Git's
optional locks; they do not stage, commit or execute hooks.

Git failures, malformed/unterminated records, non-UTF-8 paths, or a current-diff
Git stdout above 8 MiB return an application error, without `is_clean`, counts
or a complete-coverage claim. Summary pages retain the 100-entry cap; page
continuations are fresh observations. Fixed Git capture enforces the stdout limit
while reading and separately caps stderr at 64 KiB. Configuration probe and query
share an individual deadline. Current diff uses the NUL status and both index/worktree
numstat observations for scope and counts, plus the requested tracked patch or
selected untracked body. It does not fingerprint unrelated dirty/untracked bodies
or sample an additional text status to build metadata.
Fixed queries disable fsmonitor/hooks/pager/textconv and deny transport protocols;
clean/process-filter configuration yields unsupported/unknown rather than substituted
Git semantics. Read/image observations do not request checkout status; selected
file bodies remain readable when filter-dependent Git observations are unsupported.
Nested submodule worktree dirtiness is not observed. No end-to-end time/IO bound
or atomic configuration/filesystem snapshot is claimed.
Explicit untracked synthetic patch reads reuse the bounded file reader with
the existing 10 MiB file limit; oversized files fail instead of giving a partial
patch with a false completion marker.

</details>

### Read the evidence labels

Check project_root/execution_target and coverage/pagination rather than assuming a result covers the whole repository. A commit ID is not a version of every uncommitted file.

<details>
<summary>Advanced: provenance, version and coverage fields</summary>

Successful envelopes distinguish `project_root`, `execution_target`, `work_ref`,
`target_kind`, `version`, `observation_mode`, `coverage`, and `pagination`.
Read/image and tracked search omit global `dirty` and `state_id` metadata. Their
`version.git_head` is an observed commit reference, not a file version or a pin on
current checkout contents; direct read integrity uses `file_sha256` and optional
`expected_sha256`. They do not open/hash unrelated dirty or untracked bodies to
build metadata. Current diff retains checkout `dirty` from its required full
status observation; a filtered summary's `is_clean` applies to the selected scope.
Search and current-diff continuations remain fresh, unpinned observations; there
is no replacement token, snapshot or cache. Commit comparisons report exact resolved
base/target commit IDs and exclude the unrelated current dirty flag. Native image
metadata carries the same target provenance. `canonical_root` remains the
actual evidence checkout. Hashes identify observed content, not an atomic
filesystem snapshot. Reading Agent-written logs proves observed bytes, not
execution, test success, attribution, or truth of the log's claims.

</details>

### Evidence and current status

Developers can use the regression references below to locate source tests. Those
tests exercise their stated cases; they do not verify the service or host you are
using now. Runtime changes and live acceptance require separate authorization.

<details>
<summary>Advanced: regression coverage and evidence expiry</summary>

The canonical evidence regressions are in `tests/test_work_evidence.py` and
`tests/test_read_contract.py`. They exercise exact Work targets, search/read continuation,
pinned revision differences and native image/structured metadata preservation. They do
not certify live client behavior or the truth of an Agent-written report.

`tests/test_current_diff_paths.py` covers main/linked current summary-to-read
paths, rename source/destination, numstat, paging and incomplete observations.
`tests/test_workspace_evidence.py` checks direct changed bodies/hashes, matches,
current/staged patch contents, fresh continuations and the narrow-observation
regression that rejects unrelated body opens and metadata-only status/diff scans.
NUL-safe parsing covers current summary, search and commit-diff summary; other
Git consumers are unchanged. Earlier unbound Work remains unavailable. The
capture and snapshot limits above are scope limits, not a separate state owner.

Project continuity is manifest-routed. Source contracts and synthetic tests do not
certify current runtime or client behavior.

Receipt expiry follows [Work capacity](LIFECYCLE-RESTART-CONTRACT.md#work-capacity-and-report-lifetime). Known expired work_ref returns
WorkRefExpired; absent receipt/tombstone returns WorkRefUnavailable. No evidence path
falls back to a current Agent or project root. Already-resolved in-flight targets stay
frozen; subsequent lookups may reject expiry without changing the prior target.

</details>
