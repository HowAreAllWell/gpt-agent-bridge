# First use: one bounded task, evidence review, and a fresh chat

For a new installation start with [Getting started](GETTING-STARTED.md). This worked example assumes its software, native Skills and notification binding checkpoints are complete.

Begin the setup by preparing the disposable root below, then complete
[ChatGPT Project setup](CHATGPT-PROJECT-SETUP.md) for that root. The exercise
starts with Principal-only repository reading, then one explicitly authorized
Agent assignment. An optional handoff checks project-local continuity. These
are instructions for an exercise, **not a recording of successful execution**.
No screenshots, outputs, or live acceptance are fabricated here.

Reference date: **2026-10-11**. The intended Principal is official ChatGPT Web
**Chat inside your Project**, with your copied
[Core instructions](../templates/WEB-PRINCIPAL-CORE.md) and returned Project
Binding. A plugin test in Work, or a CLI operating on its own, does not prove
this target Chat workflow.

## Prepare a small, disposable target

The [first-use example](../examples/first-use/README.md) supplies a small invoice
bug and its expected behavior. Its nine baseline tests intentionally have six
failures and three passes. Read the setup and bug description before using it.
These source fixtures are inputs, not evidence that a connected Agent fixed or
tested anything. The generic read-only question below also works for an already
registered repository.

For a fresh exercise, prepare a separate user-owned Git root using the example's
[bootstrap instructions](../examples/first-use/README.md#bootstrap-your-own-disposable-git-repository)
**before launching its Herdr Agent or calling project_register**. The Bridge code
checkout and the demo target are distinct roots. Registration needs an existing
Git root, not merely a directory; an initial demo commit is optional, not required. If you instead use an existing repository, use
read-only scope and preserve its unrelated work. Do not point this exercise at
someone else's development checkout or change the Bridge source/configuration.

Next, use setup's [Herdr/Codex example](CHATGPT-PROJECT-SETUP.md#prepare-a-demo-agent-with-herdr)
to arrange an eligible Agent in the prepared demo root, or use your existing
compatible Herdr Agent there. Complete your own connection, Core, Skill discovery
and authorized registration of that same root. In the examples below, `first-use` is the ref **you registered**;
substitute your actual explicit ref consistently. All angle-bracket handles and
paths must be replaced with observed values; none is a usable Agent/Work ID.

**Before proceeding, privately confirm:**

- The current Project Chat has the saved Core and the correct Project Binding.
- Local initialized MCP health and this Chat's actual `bridge_health()` result
  are separately checked.
- Tools are visible in this Chat; all four procedures are discoverable if you
  are evaluating the full installed plugin. Missing Skills remain an installation
  gap even if tool-only diagnosis works.
- `context(project_ref="first-use")` identifies the intended checkout and an
  eligible existing Agent. Keep handles and local-root observations private.
- You have selected a small set of nonsensitive files and recorded the target's
  initial Git status so unrelated work can be compared later.

No step below authorizes installation, service changes, Git mutations or a
second Agent task implicitly.

## 1. Ask the Principal a repository question without delegation

This complete prompt works for a repository with an ordinary README. If using
the starter, select its README and bug/source files as the bounded set instead.

```text
Use project_ref="first-use". This is a read-only repository question for the
Principal, not an Agent task. Read the repository README and at most two
relevant source/example files that I select. Explain what the project/example
does, what the selected code is intended to do, and one question that still
needs evidence. Cite paths and lines actually read. Do not prompt any Agent,
run commands/tests, edit files, initialize continuity, or perform Git actions.
If a file or tool is unavailable, report the gap instead of guessing.
```

The Principal can use `context`, bounded `read`, and scoped `search` with the
explicit ref. Select actual filenames from the observed repository; do not use
an imagined demo path. Confirm that the answer cites real text and separates
observations from inferred behavior. For a starter bug, state the expected
behavior from its bug description, then the source evidence for the suspected
cause. This stage does not execute a reproduction or prove the bug fixed.

**Checkpoint:** you can identify the files the Principal actually inspected,
the conclusion those bytes support, and the remaining uncertainty. No Agent
input or project write should have happened.

## 2. Authorize exactly one read-only Agent review

Choose an eligible `agent_ref` returned by the current `context`, and replace
the path placeholder below with the files selected in step 1. Do not reuse a
handle from a screenshot, another project, or a previous server lifetime.

```text
I authorize one bounded delegation in project_ref="first-use" to
<AGENT_REF_FROM_CURRENT_CONTEXT>. Review only <EXACT_SELECTED_FILE_PATHS>.
Explain the starter bug's expected behavior, relevant current code, suspected
cause, and a narrowly scoped proposed fix and verification plan. If there is
no bug description, independently review the Principal's repository answer and
identify one supported correction or remaining uncertainty instead.
Do not edit project files, run project commands/tests, install anything, perform
Git actions, or contact another Agent. Publish the mandatory Bridge report
using the report contract supplied with this assignment. That report publication
is authorized; no other write is. Return evidence and limitations, not a claim
that a proposed fix was implemented or tested.
```

The corresponding tool shape is illustrative; use actual observed values:

```json
{
  "project_ref": "first-use",
  "assignments": [
    {
      "agent_ref": "<AGENT_REF_FROM_CURRENT_CONTEXT>",
      "task": "<THE_BOUNDED_TASK_AND_REPORT_AUTHORIZATION_ABOVE>"
    }
  ]
}
```

Call `delegate` once with this assignment. Inspect the per-item dispatch receipt
and save its returned `work_ref` privately. A receipt
does not prove execution success. If dispatch is refused, investigate the
specific refusal before considering new work. If delivery is unknown, do not
repeat the assignment because no visible output appeared.

For this exercise the review remains read-only in the project; the mandatory
report is an Agent-authored artifact outside the checkout. If you later want
an implemented fix, separately authorize exact file ownership, permitted tests
and acceptance criteria. That is another task, not implied by this review.

## 3. Let the classified batch return, then read the report

While delegated Work runs, do independent useful work, such as organizing the
acceptance questions from the files already read, or end the turn if none remains.
Do not repeatedly poll context/terminals, sleep, or delegate merely to wait.
The current tool descriptor owns continuation behavior; follow it rather than
inventing an await tool or a second watch-registration step.

Before dispatch, explicitly enable the local notification extension for this
project and exact Chat. It queues while observed busy and sends a short reminder
when conservative page checks permit. A missing reminder or unknown attempt
never authorizes redispatch. Inspect the extension history once when diagnosis
is needed. No widget or automatic host follow-up route remains.

When the classified result identifies a `result_ready` Work, retrieve its
Agent-published report with actual values:

```text
work_report(project_ref="first-use", work_ref="<WORK_REF_FROM_THIS_RECEIPT>")
```

This is a tool-call illustration, not a shell command. Follow returned pagination
and the report's full SHA-256 pin when reading more pages. `work_report` does
not wait or execute the task again. If the Work instead requires attention,
inspect the supplied diagnostic; do not turn a missing/invalid report or an
attention classification into successful completion.

## 4. Independently check what the report claims

Read the relevant source again through Bridge `read`, using the same explicit
project ref and the returned Work target when appropriate. Compare the Agent's
path/line citations with actual bytes. Use a bounded `diff` or current repository
status observation to check the selected scope against the baseline, preserving
preexisting changes. Bridge has no generic command/test execution tool. Evaluate
test definitions and any separately authorized user/Agent-run receipts; a source
read does not execute a test. No project command/test is authorized by this
read-only exercise.

For a bug review, check that the proposal addresses the stated expected behavior
and that its suggested tests would distinguish the failure from the fix. For a
general review, check the supported correction/uncertainty against the inspected
files. Evidence availability does not establish that the analysis is correct.

If the selected example includes an image or document needed for the question,
authorize that evidence read explicitly. `read` can return supported native
images; `prepare_file_attachment` prepares original-byte links for documents.
Returned links do not prove ChatGPT imported the file or understood its contents.
For multipart originals, recipients must assemble the ordered parts and verify
the original size/hash before claiming receipt. This optional check is not
required for the small text-only exercise.

**Report the actual result:**

| Check | What counts |
| --- | --- |
| Bounded dispatch | One authorized assignment, actual receipt, no blind retry |
| Report | A readable report for that Work; missing evidence is reported honestly |
| Independent review | Relevant report claims compared against actual source bytes |
| Scope | No project edits/commands/Git actions by this review; unrelated work preserved |
| Continuation | Actual host outcome recorded separately, without assuming model wake |
| Bug status | Analysis/proposal only; no implemented fix or executed tests claimed |

Keep a sanitized personal note of version, target surface, checked steps, any
failure, and what was not exercised. Do not publish credentials, connection
identifiers, host paths, private source or report contents as demo evidence.

## 5. Optional: publish a useful handoff and test a fresh chat

Only do this if you separately chose project-local continuity and authorized
publication in **your exercise project**. Follow
[Project continuity](PROJECT-CONTINUITY.md); do not initialize or replace an
existing noncanonical directory just to finish a checklist. Registration and
plugin installation alone do not create state or memory.

Review a meaningful fresh initialization seed if continuity is absent. For
existing canonical continuity, read the actual routed state/memory/rules rather
than initializing again. You can explicitly invoke installed
`handoff-preparation` when a handoff is needed. Authorize a narrow delta containing:

- Current judgment: what the repository and review evidence support now.
- Remaining uncertainty: proposed fix/reproduction not executed in this exercise.
- Next permitted action and boundary: what the successor may inspect, and which
  further action still needs user authorization.
- Useful causes and evidence locators in memory, with dates/versions and limits;
  process-local Work refs alone are not durable evidence after restart.

Read state bytes and revision before `current_state_update`; memory edits are
separate scoped writes. On stale revision, reread and reconcile. On an uncertain
publication, observe before attempting another mutation. Verify readback and
routing. No stage/commit, archive, service restart or automatic task rerun follows.

Start a **new Chat in the same ChatGPT Web Project**. Check Core/Binding and the
connection again; explicitly discover/use `project-resume` if it is installed:

```text
Resume project_ref="first-use" read-only. Recover the routed state, memory and
relevant rules through Bridge, then recheck the small evidence set needed for
the next judgment. Do not initialize continuity, prompt Agents, edit files,
run commands, or repeat the earlier task. Explain the current position, what
remains unverified, and the next action that would require my authorization.
```

Do not paste the full previous transcript or coach the successor with the answer
you want to test. Compare its proposed next step with the published position
and actual evidence. A useful handoff preserves the reason for the boundary,
not just a task title. Missing Skills or inaccessible continuity remain explicit
gaps. Do not reuse stale Agent handles after a restart; observe fresh context
under current authority before considering further delegation.

**Checkpoint:** the successor distinguishes review from implementation, recovers
the reason for the next action, and stays within the supplied authority. Report
whether this was actually observed. File readback or a source fixture by itself
is not fresh-chat acceptance.
