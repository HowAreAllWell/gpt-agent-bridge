# Work-target direct evidence

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
active public contract. See [observation tools](OBSERVATION-TOOLS.md) for bounds and rereads.

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
Report files and Work are process-local; [Work capacity](WORK-CAPACITY.md) owns cleanup
and expiry. This tool adds no durable report archive or file publication endpoint.
A classified batch names `work_report` for `result_ready` Works and
`agent_terminal_read` for `attention_required` Works. Neither batch readiness nor its notice certifies task
success. Publication and settlement are separate observations. `work_report` itself
does not wait or run an automatic retry loop. Classification probes the dedicated
report after the latch and before final classification: `WorkReportMissing` only, initial read
plus at most two rechecks about one second apart, added waiting within five seconds.
That cap bounds the injected waits, not OS I/O wall-clock time. Other errors classify
immediately. `readable` plus `agent_turn_settled` is `result_ready` and proves presence
only. A missing or invalid report is `attention_required`. The probe is not an
automatic Principal loop.


Search parses Git's filename-NUL/line-number-NUL/content-LF records before
decoding, so colons and newlines in filenames do not lose matches. Each match
includes a `read_locator` (`path`, `start_line`); reuse the same project/work ref.
It covers tracked current files, including tracked files matching ignore rules,
and by default excludes untracked/binary files. Explicit `include_untracked=true`
adds nonignored untracked text via two bounded passes, preserving tracked ignored files.
See [observation tools](OBSERVATION-TOOLS.md) for opt-in limits and directory/hash tools. Line snippets are the raw first 300 Unicode
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

## Evidence and current status

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

Receipt expiry follows [Work capacity](WORK-CAPACITY.md). Known expired work_ref returns
WorkRefExpired; absent receipt/tombstone returns WorkRefUnavailable. No evidence path
falls back to a current Agent or project root. Already-resolved in-flight targets stay
frozen; subsequent lookups may reject expiry without changing the prior target.
