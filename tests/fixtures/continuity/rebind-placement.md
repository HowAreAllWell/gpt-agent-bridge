# Scenario HANDOFF — synthetic acceptance data, not live evidence

## Current state
Normal delegation uses placement before launch and does not rebind agents.
Same-common-Git linked checkouts remain supported.

## Decision trajectory
D-placement supersedes D-rebind in this scenario.
Goal/context: allow concurrent writers without mixing their working trees.
Prior alternative: D-rebind isolated agents during delegate via rebind/readiness;
scenario acceptance S1 recorded that it worked, not that it failed.
Chosen approach: Herdr supplies stable isolation before first prompt; delegate
only refreshes the exact resource under the writer gate and prompts it.
Why superseded: moving placement earlier removes delegate-time relocation and
readiness dependencies while retaining linked-checkout support. It is a changed
responsibility boundary, not evidence that rebind never worked.
Evidence: scenario://S1/rebind-acceptance (historical scenario version 1);
scenario://S2/placement-contract (current scenario version 2).
Unknown: post-launch relocation demand is not established by this fixture.
Revisit only if supported work demonstrates a need for post-launch relocation
and the Principal/user explicitly changes scope; old success alone is insufficient.
