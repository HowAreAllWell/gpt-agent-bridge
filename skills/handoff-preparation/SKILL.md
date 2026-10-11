---
name: handoff-preparation
description: Preserve decision-relevant project continuity when a chat switch or interruption risks losing a successor's next choice, or the user requests a handoff. An ordinary turn ending alone does not trigger this skill.
---

Ask: if this chat disappeared now, what information would change the successor's
next choice? Reconcile that delta against the routed current state, memory and
existing evidence. No decision-relevant delta means no write.

Put the replaceable current judgment, unresolved dependency and next action in
state. Put durable causes, standing boundaries and useful evidence locators in
memory. Keep project-specific decisions, causes and rules in their local owners.
Reference existing evidence instead of copying reports, transcripts or secrets
into another ledger.

Read the actual routed state bytes and revision. Publish state with
`current_state_update` against that revision; memory changes are separate scoped
edits. On conflict, reread and reconcile. An uncertain publication requires
observation before another mutation. Verify the published bytes and intended
routing before relying on the handoff. Process-local refs remain dated evidence.

Publication grants no role, automatic commit, push, restart or additional action
authority. Follow the selected project's rules and existing task scope.
