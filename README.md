# GPT-Agent Bridge

[English](README.md) | [简体中文](README.zh-CN.md)

**Make ChatGPT Web your thinking partner for local repository work.**
Web Principal helps frame problems, challenge assumptions, compare tradeoffs and
choose evidence that could change the answer. It coordinates compatible existing
Herdr-managed coding Agents, then checks their complete reports against actual
files and diffs.

Bridge supplies tools and transport, not a second reasoning model. ChatGPT reasons,
your Agents execute locally, and you retain authority over goals, scope and actions.

**[Get started →](docs/GETTING-STARTED.md)** — one guide for preparation, connection,
instructions, project binding and first use.

## Why Web Principal

- **Examine the question before dispatch.** Reframe unclear requests, expose
  missing premises and compare alternatives before choosing a plan.
- **Use independent research and review when they matter.** Coordinate compatible
  Agents across providers/models when separate views could change the judgment.
  Agreement alone does not prove correctness.
- **Check evidence, not just status.** Read complete Work reports and inspect
  source/diffs; distinguish observed results from claims, gaps and unknown outcomes.
- **Carry decisions across chats deliberately.** Explicit project continuity
  preserves the decision, reasons and next boundary. It does not restore running
  Work, replay tasks or automatically create global memory.

## How it works

Use an ordinary **ChatGPT Web Project** with the exact supplied **Core** and **four
separate native Skills**. A private **Secure MCP Tunnel** connects Bridge tools to
local Bridge and **Herdr-managed Agents you started** in authorized repositories.
On Windows, Bridge/Tunnel run in WSL. The optional unpacked Chrome extension lives
in a private Windows-local folder and reminds only the exact Chat you bind.

MCP connection, manual Core installation, Skill discovery and repository binding
are separate checks. None starts Agents or authorizes arbitrary work. No API
Principal or particular Agent provider is required; account access, provider
sign-in and quotas remain yours.

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

[Releases](https://github.com/HowAreAllWell/gpt-agent-bridge/releases) currently offers
**v0.1.0-rc.1 PRE-RELEASE**, with one attached complete installation ZIP. Download
that asset, not GitHub's automatic **Source code ZIP**. Later reviewed releases
may supersede it. The immutable rc.1 guide still contains an older “not published
yet” sentence; current availability is on the release page.

Fresh Windows/account installation, Chrome loading and restart behavior are **not
field accepted**; the full Python suite is not green. Source/synthetic checks prove
only exercised cases. Existing installations are not automatically moved, reset
or rekeyed.

Advanced contracts and documentation navigation: [technical reference](docs/TECHNICAL-REFERENCE.md).
Project memory: [continuity](docs/PROJECT-CONTINUITY.md). Work, notifications and
restart limits: [lifecycle](docs/LIFECYCLE-RESTART-CONTRACT.md).

[MIT License](LICENSE).
