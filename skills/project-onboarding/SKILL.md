---
name: project-onboarding
description: Connect an existing local Git repository to Bridge, return its Binding, and offer continuity setup when no usable configuration is recognized. Initialize notes only with separate explicit authorization; never create a repository under this workflow.
---

Confirm the authorized `project_ref` and existing repository root. Register with
`project_register` only if needed, then return the tool-provided Project Binding
for the user to save beside Core and existing Project Instructions. A request to
connect/register authorizes this step only, not project-note creation or tasks.
Inspect registration and continuity with `bridge_overview` and `context`; respect
uncertain persistence/publication results rather than repeating a mutation.

Only when continuity explicitly reports `manifest_missing`, explain after the
Binding handoff: "The repository is connected, but Bridge has not recognized a
usable project continuity configuration. Would you like to set up project notes?"
Missing does not prove notes never existed or permit overwriting a noncanonical
directory. Ask once in this onboarding conversation;
a refusal or no answer means no initialization and no writes. Simple authorized
file reading remains available; it does not mean continuity is ready. Do not
interpret a read/permission error, invalid manifest or unknown outcome as missing.

After a separate explicit yes, confirm the project's goal, current progress and
confirmed decisions from actual facts, and identify genuine existing rule files.
If rules are absent, explain the missing prerequisite and stop; do not invent an
`AGENTS.md` or manufacture rules to satisfy initialization. Supply additional
project rule text only for real project-specific guidance separately authorized
for that layer. Never copy another project's cognition or seed speculative history.

Use `project_initialize` only for the already registered project and authorized
seed. A canonical manifest already present needs no initialization. If existing
notes are known to be noncanonical, stop and explain; do not attempt initialization
as a repair. The tool also refuses a noncanonical directory. Do not delete or
replace existing notes to force it. On an uncertain write outcome, inspect before
another mutation. Verify returned routing
and published content before saying continuity is ready. Registration and
initialization grant no project role or further task authority.
