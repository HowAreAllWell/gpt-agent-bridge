# GPT-Agent Bridge

[English](README.md) | [简体中文](README.zh-CN.md)

**Think with ChatGPT Web. Coordinate your local Agent team.**
Use a Web Principal in ordinary **ChatGPT Web Project Chat** to frame the real
problem, challenge assumptions and compare alternatives. Delegate investigations,
implementation and independent review to **any authorized local Agent already supported,
runnable and managed by Herdr**, including CLI Agents across providers and models.

Bridge supplies MCP tools and Skills; Herdr supplies the existing local Agents.
The Web Principal checks reports against real code, files, diffs and test evidence,
while you keep control of goals, scope and permissions.

**[Get started →](docs/GETTING-STARTED.md)** — one guide for preparation, connection,
instructions, project binding and first use.

## Why Web Principal

- **Examine the question before dispatch.** Reframe unclear requests, expose
  missing premises and compare alternatives before choosing a plan.
- **Coordinate independent Agents across providers and models.** Split research,
  implementation and review into bounded assignments for your existing Herdr
  Agents. Ask them to challenge findings when another view could change the decision.
- **Check evidence before accepting results.** Read complete Work reports and
  inspect actual code, files, diffs and test evidence. Distinguish observations
  from claims, gaps and unknown outcomes; agreement alone does not prove correctness.
- **Carry decisions across chats deliberately.** Explicit project continuity
  preserves the decision, reasons and next boundary. It does not restore running
  Work, replay tasks or automatically create global memory.

For example, with three eligible Herdr Agents already available, the Web Principal
explores a storage-design decision, sends two independent questions in parallel,
asks the third Agent to review and challenge the findings, then checks the reports
against relevant code, diffs and test evidence before recommending an approach.

For demanding reasoning and decisions, optionally pair the Web Principal with
[GPT-6 Pro](https://help.openai.com/en/articles/20001354-gpt-6-and-other-models-in-chatgpt)
when available, while Herdr-managed Agents implement and independently review.
You select the model through your own eligible ChatGPT plan and workspace;
model access is separate from Bridge.

## How it works

Use ordinary **ChatGPT Web Project Chat** with the exact supplied **Core** and **four
separate native Skills**. A private **Secure MCP Tunnel** connects Bridge tools to
local Bridge and **Herdr-managed Agents you started** in authorized repositories.
On Windows, Bridge/Tunnel run in WSL. The optional unpacked Chrome extension lives
in a private Windows-local folder and reminds only the exact Chat you bind.

MCP connection, manual Core installation, Skill discovery and repository binding
are separate checks. None starts Agents or authorizes arbitrary work. No API
Principal or particular Agent provider is required; account access, provider
sign-in and quotas remain yours.

Install the Skills through **Plugin Creator in ordinary Web Chat**, reusing your
connected Bridge App, as described in [Get started step 6](docs/GETTING-STARTED.md#6-install-and-discover-all-four-native-skills).
Verify both Bridge tools and all four native Skills in the target Project Chat.
Work/Codex setup is not required, and success there does not pass this check.
This supported target does not imply host-enforced Web-only plugin visibility.

## After setup: three useful steps

1. **Orient:** select the authorized project, request current context and a
   read-only source check. Verify the repository and available Agents.
2. **Delegate deliberately:** state the question, allowed changes and acceptance
   criteria; authorize input to an observed eligible Agent. Continue useful
   independent reasoning while it works.
3. **Judge and preserve:** read the full report, compare original evidence, resolve
   contradictions and preserve decision-relevant continuity when authorized.
   A reminder proves neither success nor completed review.

## Download and status

Choose a reviewed **PRE-RELEASE** on the
[Releases list](https://github.com/HowAreAllWell/gpt-agent-bridge/releases) and
download its attached **complete installation ZIP**, not GitHub's automatic
**Source code ZIP**. Check that release's source commit, changes and limitations;
GitHub main may contain fixes not yet included in an attached ZIP.

Fresh Windows/account installation, Chrome loading and restart behavior are **not
field accepted**; the full Python suite is not green. Source/synthetic checks prove
only exercised cases. Existing installations are not automatically moved, reset
or rekeyed.

Advanced contracts and documentation navigation: [technical reference](docs/TECHNICAL-REFERENCE.md).
Project memory: [continuity](docs/PROJECT-CONTINUITY.md). Work, notifications and
restart limits: [lifecycle](docs/LIFECYCLE-RESTART-CONTRACT.md).

[MIT License](LICENSE).
