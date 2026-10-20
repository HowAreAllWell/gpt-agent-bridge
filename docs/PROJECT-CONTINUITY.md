**English** | [简体中文](PROJECT-CONTINUITY.zh-CN.md)

# Project continuity: manifests and conditional state publication

Use this page when you want a new ChatGPT chat to understand **where the project
stands, why you chose an approach, and what it may safely do next**. It explains
saving and resuming project notes; it is not another installation step.

First complete [Getting started](GETTING-STARTED.md), including the correct
project connection and the four installed workflows. The steps here happen in
**ordinary ChatGPT Web Project Chat**, on native Ubuntu Desktop or Windows+WSL2.
Ubuntu uses its own local repository; Windows uses the repository inside the
selected WSL Linux installation. You do not need WSL on native Ubuntu, and you
do not run terminal commands from this page. Account/Skill availability still
needs the actual Web check; this target does not enforce Web-only visibility.

### What should be saved?

Here, the **Principal** is ChatGPT helping you reason and coordinate work.
`project_ref` is the short identifier for the local project you authorized in
Getting Started. Being listed in Bridge does not give permission to work on it.

| Project note | What belongs there | Small example |
| --- | --- | --- |
| **Current state** | The latest judgment, unresolved dependency and next authorized step. Replace it as the decision changes. | “The cache change is still under review. Compare the measured failure cases before recommending deployment; no deployment is authorized.” |
| **Memory** | Reasons that should remain useful after the immediate step: a decision, its evidence, a standing boundary and when to reconsider it. | “We kept the existing cache because the measured alternative lost required behavior; revisit if the workload changes.” |
| **Rules** | The project's existing instructions and permission boundaries. Saving a note does not override them. | “Read-only review until implementation is explicitly authorized.” |

These are project-local files, not a saved copy of the entire conversation.
A **manifest** is a small file telling Bridge which files hold these notes.
**Routing** means following those file paths. The advanced section below defines
the exact format; you do not need to assemble it manually to use the workflows.

### Before changing chats

In the **current ordinary Project Chat**, name your authorized project and ask:

> Use handoff-preparation for project MY_PROJECT. Read its current routed notes.
> Preserve what changes the next decision: our current judgment, why, unresolved
> questions, evidence locations and next permitted action. Save only changes
> covered by our existing permission, then read back what was saved. Do not
> change code, send Agent tasks, commit, push or restart anything. If the notes
> are not configured or saving is not authorized, explain the gap and stop.

Replace `MY_PROJECT` with your actual authorized `project_ref`; it is not a new
project to register. The workflow name is `handoff-preparation`, installed in
Getting Started. A normal turn ending does not itself require a note update.

**Expected result:** ChatGPT distinguishes current state from durable memory,
identifies the files actually used, and verifies the saved bytes and revision.
A revision is a hash identifying the exact file version read, not a statement
that its contents are true. With no decision-relevant change, “no update needed”
is a valid result. Keep private notes, reports and secrets out of public docs.

**If blocked:** a missing Skill means return to the Web discovery check in
Getting Started. Missing/invalid project notes require an authorized setup or
repair decision, not guessed file paths or automatic reinitialization. If an
update conflicts with another writer, reread and reconcile both changes. If the
response is lost, read the destination first; do not blindly repeat the write.

### In the new chat

Open a **new ordinary Chat in the same intended ChatGPT Project**, select the
verified Bridge plugin, and ask:

> Use project-resume for project MY_PROJECT within our existing scope. Read its
> routed current state and the memory/rules needed for the next decision. Tell
> me the unresolved question and next permitted action. Recheck live Git and
> Agent facts where they matter. Do not resend old tasks or make changes merely
> because the previous chat mentioned them. If the project or permission is
> unclear, ask me to identify it before acting.

**Expected result:** the new chat can explain the next decision and its reasons,
separating saved claims from current evidence. Git branch/commit, local changes,
running services and available Herdr Agents may have changed; check them before
relying on old observations. A pasted transcript or old report is a lead, not
proof of the present repository or runtime. Do not repeat closed work just
because its evidence was recorded in an earlier chat.

**If blocked:** do not infer a project from its registry entry or silently switch
to another repository. If a saved Work reference is unavailable, that does not
mean its Agent stopped or that the task may be sent again. See
[results, reminders and restart uncertainty](LIFECYCLE-RESTART-CONTRACT.md#restart-and-uncertainty).

Saving notes helps a successor recover the **decision**, not a running process.
It does not resume Work, restore Agent terminals, replay tasks, create global
memory or guarantee that a future chat will choose correctly. Native Ubuntu
installation and real fresh-chat acceptance still require separate live testing.

### Advanced: exact routing and publication rules

The rest of this page is for reviewing the file format and safe update behavior.
Use it when a workflow reports a routing, revision or size error; it grants no
extra file access or mutation permission. UTF-8 is the text encoding used for
these files. A “pointer” below is a file path, and “publication” means making
approved text the current file version, not publishing it to GitHub.

This shared contract owns manifest file routing, state-versus-memory authoring and
conditional publication. It implements project-local continuity only; it does not
establish global memory, shared runtime identity, or durable Agent/Work identity.

The canonical manifest routes rules, one current-state file and one memory file.
Current state is plain UTF-8 and may be slotless. The canonical manifest is
versionless; the loader refuses any version field. This public repository ships no
actual `.principal/`; each project creates its own under explicit authorization. This shared contract describes source routing and publication.
Rules retain their authority; manifest routing does
not assign a role or grant task authority.

State is the sole replaceable current decision position: where the project is,
the unresolved dependency and next action/boundary, with premises needed to resume.
Memory holds durable causal choices, still-useful standing boundaries, evidence
locators and revisit conditions. Neither is a transcript or parser-owned ledger.
No fixed Markdown region/field schema, automatic archive or shared memory follows.

`context(project_ref)` returns bounded pointers and a SHA-256 revision, not the
state body. A missing/invalid manifest is reported without preventing
ordinary context use. `project_register` returns a connected-ref Project Binding
amendment, which the user applies on the ChatGPT Project side, and a persistence
classification. It does not create continuity files. `project_initialize` publishes
a fresh canonical `.principal/` directory for an already registered project, or
leaves a canonical manifest untouched. A `.principal` that is not already canonical
is refused and not overwritten. Its seed must name existing rule files;
`.principal/rules.md` is written only from meaningful supplied
`project_rules_content`. The publication is one no-replace directory rename.
After that rename the directory is not deleted. A lost response is not proof of
absence. Pointers are relative, bounded, and reject traversal, `.git`, and symlinks.

`current_state_update(project_ref, expected_revision, content=None, edits=None)` conditionally replaces or creates only
the declared state file (UTF-8, at most 65,536 bytes). Use the revision of the text
you actually read; `missing` permits no-clobber creation. The existing per-worktree
single-process writer gate serializes cooperating calls. A stale revision fails
without overwriting state: reread, reconcile both contributions, and submit the
reconciled text against its revision. Existing-file publication rechecks the hash
immediately before atomic replacement; this is not global CAS against external
writers or other processes. A transport loss leaves publication uncertain: read
before deciding what to do next. No automatic retry is implied.

## Canonical manifest

**When you need this section:** setup reports an invalid manifest. “Canonical”
here means the one accepted format, not a higher source of authority. Ask the
Principal to explain the reported mismatch against the rules below. Do not add a
version or extra field to make it look complete, and do not replace existing
project notes without explicit scope. A valid path list alone does not read or
verify the truth of the notes.

The loader accepts one shape. Required keys are `rules`, `current_state` and
`memory`; no other keys are accepted. There is no version field and no takeover field.

- `rules` is a nonempty file-path list.
- `current_state` and `memory` are file paths.
- A version key, a takeover key, a slot key, the retired `methods` key (even empty
  or null), or any other key fails closed.
- State, memory and rules have distinct paths; none points to the manifest.
- The total pointer bound is 16 including state and memory. These are file pointers,
  not directories or procedure discovery.

Duplicate JSON keys, duplicate list entries, unknown fields, and invalid
path/type/counts fail closed. Paths must contain Unicode scalars; escaped lone
surrogates are rejected. The manifest bound is 8192 bytes and the path bound is
512 characters. Checks are repository-local, no-follow, and require a regular file
for every canonical pointer. Rules and memory must be readable before
publication can proceed; missing state alone permits the existing no-clobber
creation path. Pointer checks project no document bodies; memory/rule truth or
UTF-8 content is not certified.

Context projects rules and memory under canonical_pointers and
does not add a manifest version. The state SHA/revision projection is unchanged.
current_state_update uses the same conditional publication, UTF-8/whole-file bounds
and optional in-file slot checks. It writes only current_state and never memory,
rules or the manifest. No slot or file is automatically introduced. No
multi-file migration or transaction follows.

## Opt-in publication slot

**Advanced and optional:** a slot is a marked part of the state file with its
own byte limit. Normal slotless notes do not need one. If an adopted slot rejects
an update, inspect the exact reason and reconcile the content within its existing
limit. Do not remove markers, change the limit or use another editor to bypass
the guard. The exact signature and rules below remain the update contract.

A current-state file may opt into one mechanical slot. The markers are whole lines,
with no escaping, nesting, or second slot:

```
<!-- bridge-state-slot start limit=N -->
```

```
<!-- bridge-state-slot end -->
```

`N` is a canonical decimal integer from 1024 through 65536, with no sign and no
leading zero. The body is the exact UTF-8 byte slice
after the start line's LF or CRLF terminator and before the first byte of the end
line. Those terminators inside the body count; the marker lines and bytes outside
the pair do not. Length is bytes, not Unicode scalars. A bare CR is not a line
terminator. A line is marker-like only when the whole line, excluding its LF or
CRLF terminator, is an HTML comment that begins with `bridge-state-slot`. A mention
inside a longer line, including a code-fence line that prefixes the comment, is not
a marker. A code fence does not hide a marker that occupies its own line; a second
pair is a duplicate and is refused.

The check runs for full content, exact edits, and missing-file creation, after the
revision matches and before any write. It does not summarize, truncate, archive, or
commit. Refusal returns `CheckpointSlotRejected` with a bounded `slot_reason` and
writes nothing.

- Current missing, or present with no marker-like line: a candidate with no slot
  stays a legacy replace. A candidate with exactly one valid slot whose body is at
  most `N` adopts that slot. A malformed marker-like candidate is refused.
- Current one valid slot `N`: the candidate must still be exactly that valid slot
  `N`, with body at most `N`. Removal, widening, narrowing, duplicate or extra or
  malformed markers, and an over-limit body are refused. The same `N` may move
  within the file; the body and the outside bytes may change.
- Current malformed marker-like bytes: publication may repair them to a clean
  no-slot file or to one valid slot whose body is at most its `N`. A malformed
  candidate is refused.
- The 65,536-byte whole-file cap is unchanged and is not this slot.

This guardrail applies to `current_state_update` and to cooperating callers of that
publication. `project_text_edit`, git, and external editors do not enforce it.
Changing an adopted `N` or removing its slot is outside this publication primitive;
other editors do not gain task authority from bypassing it. This generic mechanism
remains for projects that opt in; the synthetic default fixtures are slotless. The tool does
not judge prose or automatically preserve displaced history.

Supply exactly one of full `content` or nonempty `edits=[{old_text,new_text}]`.
Each old_text must be nonempty, unique in the same original state, and nonoverlapping
with every other edit. All replacements use that original version once, preserving
other UTF-8 bytes including CRLF. Missing/ambiguous matches and mixed modes fail.
Edits cannot create missing state. Read's `file_sha256`, prefixed with `sha256:`,
provides the revision for the bytes actually read; inspect_file alone does not read the state.
No Git version action is implied by current_state_update. project_text_edit separately permits exact
edits to existing project UTF-8 files under task scope, including owner documents; it does not
change manifest routing, authoring responsibility or current-state creation/revision semantics.
When a version freeze is authorized, commit_prepare selects literal files and freezes the
review candidate, then commit publishes exactly that candidate. Neither tool authenticates
claims or automatically archives an uncommitted causal spine.

Content is `principal_supplied_unverified`; a filesystem hash proves bytes, not
truth. current_state_update does not execute commands, stage/commit Git, summarize, truncate,
grant new authority, or promote supplied claims into facts. Existing task authorization
applies; there is no extra role, approval, or permission system. The slot check is
byte and limit identity only.

## Authoring and preservation boundaries

**Practical check before replacing state:** would the next chat lose the reason
for a decision? If so, preserve that reason in the authorized memory owner or a
recoverable evidence version before dropping the last useful copy. Updating
state does not also save memory, and a readback is not an automatic Git commit.
Do not request a new memory entry when nothing durable changed.

State replacement does not archive earlier uncommitted bytes. Durable causes can
be edited in the memory file under existing task authority, separately from
current_state_update, which writes only the declared state. There is no multi-file transaction: needed
inline causes remain useful until their destination and recoverable version are
confirmed. A readback proves bytes/pointers, not truth or successful later resumption.

Git history is the default archive of committed causes; unique external/runtime
evidence may need its own preserved artifact. A locator should identify the
intended version. Dynamic runtime facts and process-local Work refs do
not become durable identity through prose. Historical acceptance does not certify
current deployment or a cached client schema.

A commit may supply a recoverable byte locator when separately authorized; this
shared contract grants no standing commit authority. Authoring is a judgment about
what changes the next decision, not an every-turn ritual or required finding ledger.
If no durable delta exists, no memory entry is needed.

Fresh-chat usefulness requires an actual uncoached successor choosing sensible
next work from the published position, evidence and authority limits. Source and
transport tests exercise preservation; they do not establish host discovery,
Skill activation, inference quality or live fresh-chat acceptance.

## Synthetic continuity preservation regression

**For maintainers:** these are tests using made-up project files. They check
that supplied bytes survive the update path. They do not show that a new ChatGPT
chat read the right files, understood them or selected the right next action.
No test command or live project modification is required to read this section.

`tests/fixtures/continuity/rebind-placement.md` is synthetic data used by
[ProjectContinuityTests.test_existing_handoff_retains_causal_bytes_and_rejects_stale_chat](../tests/test_project_continuity.py).
The unittest checks manifest-routed retrieval, exact supplied causal bytes after
current_state_update publication, stale-revision rejection without overwrite, and unchanged
Git HEAD. Its state-only negative control lacks the fixture's causal markers;
the full preserved text retains them. These are transport/preservation assertions,
not a model exercise, a successor-judgment test or live fresh-chat acceptance.

## Reusable procedures and local cognition

**Which workflow should I use?** `handoff-preparation` preserves the next
judgment before leaving; `project-resume` recovers it after returning. Skills
supply those instructions. They do not contain your project's private decisions,
install themselves through the manifest, or authorize new work. If either Skill
is missing, fix discovery through Getting Started; editing project routing is
not a substitute.

[Bridge Plugin Skills](TECHNICAL-REFERENCE.md#native-skills-and-app-binding) own the repository's reusable Principal
procedures. Project instructions retain scope and authority; routed state, memory,
rules remain local. Principal Methods and their manifest routes are retired;
initialization seeds also reject any `methods` field. Existing manifests containing
that field must be explicitly edited under task authority; initialization refuses
an existing noncanonical directory rather than repairing it. No compatibility
alias or replacement procedure-routing field is provided. Source tests exercise
manifest routing and byte preservation, not host skill discovery, automatic trigger
reliability or broader successor usefulness.
Routing grants no role or new authority. Skills remain independent of continuity
manifest routing; no runtime skill loader is introduced.
