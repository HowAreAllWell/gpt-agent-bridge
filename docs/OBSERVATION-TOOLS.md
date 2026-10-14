# Direct observation tools

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
| Retrieve a full Agent report | Every admitted Work requests a report. After batch classification names work_report, page that report with Unicode offset/limit and expected_sha256. A missing or invalid report is attention and the batch identifies the affected Agent where recorded. Only the published private artifact is read. |
| Find a line | search defaults to tracked files. include_untracked=true additionally searches nonignored untracked text. Both branches share one literal-pattern query validation (1..500 characters, no NUL/LF, valid UTF-8; the pattern is passed as an explicit `-e` operand with literal pathspecs) and return each match's raw first ≤300 Unicode characters (record-ending LF excluded; CR/whitespace preserved, no invented marker or ellipsis) plus `line_text_truncated` and a `read_locator` {path,start_line} for the same project/work_ref. Malformed or nonpositive grep line records and a no-match status carrying output are rejected. Snippets do not prove full-file content. |
| Inspect binary or large text | inspect_file gives regular-file mode, byte_size and full original-byte SHA-256, without body. This does not make binary files readable as text. |
| Prepare original bytes | prepare_file_attachment hashes the current source and prepares expiring ResourceLinks for later resources/read; nothing is uploaded, host-imported, assembled or attached yet. It returns one original-name/MIME link with no TextContent for <=7 MiB; otherwise ordered octet-stream links plus only multipart {target, size, sha256, parts}. Internal metadata lookup and bounded part fetch preserve source stat/path and part hash checks; see [attachment contract](TECHNICAL-REFERENCE.md#original-file-attachments) for source mechanics; live host acceptance requires separate checks. |
| Publish continuity | Read manifest state, then current_state_update with required expected_revision and exactly one of content or edits. This is state publication, not a Git commit or verification of supplied claims. An opted-in bridge-state-slot adds a mechanical body-byte and limit-identity refusal; it does not summarize or truncate. |
| Inspect changes | diff uses the existing current or pinned-commit contract in [Work evidence](WORK-EVIDENCE.md). Unknown is not clean. |

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
report; use `work_report` for the published artifact after final classification.
A missing or invalid report is attention, not successful task completion.

## Direct project text edits

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

## Candidate version actions

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
cleanup tool or destructive await mode is added. See [Work capacity](WORK-CAPACITY.md).
