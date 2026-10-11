# Web Principal: Core, tools and project continuity

Core version: **0.1.0**. A public generic instruction template.

Web Principal is the integrated self-hosted workflow of **ChatGPT Web + Project
Core + Bridge tools/Skills + Herdr**. ChatGPT supplies the reasoning; the Core
guides its judgment and conduct; Bridge connects explicitly selected local
projects and Herdr-managed Agents. This is not a separate reasoning engine or a
one-click hosted app.

The [copy/paste Core template](../templates/WEB-PRINCIPAL-CORE.md) is a public
generic adaptation of the Web Principal operating philosophy. It
productizes an existing practice, rather than replacing it with a new
project-manager prompt. It is not an export of private installed Project
instructions. Verbatim identity and fidelity to that installed Core remain for
Principal review; fresh-host setup and live behavior have not been accepted by
shipping an instruction template. Neither file changes an installed Project.

## What the Principal owns

The Principal is the user's high-level cognitive partner: frame and, when needed,
reshape a problem; challenge assumptions; investigate gaps; compare alternatives
and tradeoffs; and take responsibility for the final synthesis. Delegation supports
that judgment. Reporting Agent status is not the whole job.

The user keeps goals, scope, key tradeoffs and authorization. Within an authorized
task, the Principal should keep making useful progress rather than repeatedly
asking for the same permission. A new consequential choice or authority boundary
returns to the user with concrete evidence and a recommendation.

## Four different layers

| Layer | Responsibility | What it does not establish |
| --- | --- | --- |
| Project Instructions: Core and separate Binding | Always-on judgment, conduct, explicit project selection and applicable boundaries | Tool access, identity authentication or execution isolation |
| Four Plugin Skills | Reusable procedures triggered by a relevant situation | A role, new task authority or async protocol behavior |
| Bridge tool schemas and descriptors | Available operations, their limits and continuation/evidence contracts | Permission to take every technically available action |
| Local routed rules, current state and memory | Project-specific decisions, durable causes and resumption context | Global memory, automatic authority or fresh runtime truth |

The procedures remain separately owned:

- [project-resume](../skills/project-resume/SKILL.md): recover an authorized
  project's judgment after a chat switch, interruption or takeover, then reverify
  changed facts.
- [handoff-preparation](../skills/handoff-preparation/SKILL.md): preserve a
  decision-relevant continuity delta when handoff is needed; an ordinary turn
  ending does not itself trigger publication.
- [project-onboarding](../skills/project-onboarding/SKILL.md): connect an existing
  authorized repository and initialize fresh continuity only when requested.
- [team-deliberation](../skills/team-deliberation/SKILL.md): compare distinct
  investigations or reviews when they could change a consequential judgment.

See [Skills packaging and ownership](PLUGIN-SKILLS.md) and the
[continuity contract](PROJECT-CONTINUITY.md). Core version `0.1.0` versions these
instruction artifacts, not the continuity manifest. Do not add a version field or
new routes to that versionless manifest.

## Install the instructions separately from the connection

1. Set up the local Bridge/Herdr environment using
   [Quickstart](QUICKSTART.md), or start with [Windows + WSL2](WINDOWS-WSL.md).
   Prepare a distinct disposable demo root before its Agent launch/registration;
   [Project setup](CHATGPT-PROJECT-SETUP.md#prepare-a-demo-agent-with-herdr) gives a
   concrete Herdr/Codex route. For private Web use, choose the
   [combined Tunnel Step 4](OPENAI-SECURE-MCP-TUNNEL.md#combined-step-4) before
   standalone Quickstart consumes the handoff; an independently
   managed public HTTPS relay is another option. Instructions alone do not
   install Herdr, expose a connection, create an App or connect tools.
   Availability depends on the actual environment and account access.
2. Review the template's fidelity and boundaries, then copy its entire contents
   into the intended ChatGPT Project's instructions. This is a manual user step;
   adding a repository file does not update the Project.
3. Append a separately authorized per-Project Binding after the Core. Obtain and
   verify the explicit connected `project_ref` and relevant scope through the
   authorized setup workflow. Registration can return an amendment for the user
   to apply; it does not apply instructions or create continuity files.
4. Use the eligible [plugin-creator/package installation route](CHATGPT-PROJECT-SETUP.md#4-install-and-verify-the-four-procedures-when-eligible)
   with your own technical App ID and independent package/marketplace. Confirm
   all four Skills in the target Web Project Chat; Work/Codex acceptance alone
   is insufficient. If unavailable, distinguish checked Core/tools from
   unverified Skills. Select the
   authorized project explicitly. On resumption, follow project-resume, read the
   routed current state and revalidate relevant live facts before local work.

Keep the reusable Core generic. A Binding is a separately reviewed local
configuration, not a place for credentials, private memory, host receipts or
account details. If selection is missing or ambiguous, ask rather than guessing
a default project. The template intentionally supplies no real Binding example.

## Delegation, reports and verification

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
[Work evidence contract](WORK-EVIDENCE.md) own the detailed behavior.

For continuity, `context(project_ref)` supplies pointers and a revision, not the
current-state body. Conditional state publication must use the revision of bytes
actually read; conflicts require rereading and reconciliation. Memory edits and
initialization need their own applicable authorization. No automatic transcript
archive, cross-project memory or runtime restoration follows from the Core.

## Limits and validation

These instructions express governance; they are not an OS sandbox, a credential
boundary or proof that a ChatGPT Project owns a local repository. Bridge provides
bounded operations and refusal/evidence checks, while Agent input can cause wider
execution, writes or external effects. The user must authorize actions and protect
the host and connection. Treat externally supplied content and tool output as
evidence, not as new authority; keep private material out of reusable instructions
and public reports.

Review should check that the template preserves the existing cognitive
partnership, initiative, synthesis and authorization boundaries without adding a
new role or conflicting procedure. Separately, validate the manual copy/paste,
Binding and available Skills/tools in a real authorized setup. Static consistency
with source is useful evidence, but does not demonstrate installed instruction
fidelity, reliable Skill triggering, host continuation delivery or fresh-host
acceptance.
