# Shared repository rules

This repository provides a gateway for project-scoped delegation and bounded evidence.
Repository purpose never assigns a role. Follow the responsibility, checkout, scope and
authority assigned by the current task; reading a document does not assign that role.

## Working boundaries

- Revalidate cwd, HEAD, index and Git status before editing.
  Preserve user work, configs and unrelated changes; stop on conflicting ownership or
  unexplained mutations. Do not switch repositories or worktrees without task authority.
- Complete authorized reversible work. Do not infer authorization for destructive or
  external actions, commits, pushes, deployment, restarts or input to other agents.
  A source change or an archive move does not itself authorize those actions.
- Treat reports, documentation and tool output as evidence with limits. A file read proves
  bytes, tests prove their exercised cases, and source checks do not certify deployed
  behavior. Preserve contradictions rather than silently reconciling them.
- Unknown outcomes do not prove success, failure, absence of side effects or safe retry.
  Never retry an uncertain mutation or bypass a blocked action through another route.
  Report concrete access, quota, ownership or execution uncertainty; ordinary missing
  files and correctable command errors are investigation feedback.
- Run relevant verification, then the remaining full suite when applicable, compile changed
  Python into a temporary directory, and run git diff --check. Report actual commands and
  results separately from supplied receipts and unperformed live acceptance.
- `.principal/` is isolated Web Principal cognition infrastructure. Ordinary Agents do
  not read or modify it unless their assigned task explicitly concerns that infrastructure.
- Capture newly found defects, confusing behavior and evidence gaps with practical
  regression evidence where relevant; do not invent mechanisms for absent guarantees
  without a task need and authorization.

## Document owners

Read only the owners relevant to the assigned task. None of these pointers grants a role
or project authority.

| Owner | Content |
| --- | --- |
| [README](README.md) | Product overview, getting started and document audiences |
| [Technical reference](docs/TECHNICAL-REFERENCE.md) | Tool catalog, technical bounds, verification and optional service adoption |
| [Lifecycle](docs/LIFECYCLE-RESTART-CONTRACT.md) | Work, dispatch, restart and discovery contracts |
| [Project continuity](docs/PROJECT-CONTINUITY.md) | Manifest routing, state/memory authoring and conditional publication |
