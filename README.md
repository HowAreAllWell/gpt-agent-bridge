# GPT-Agent Bridge

**Give your coding agents a Principal.**

Coding agents can execute tasks. Who keeps the bigger picture in view?

Building software takes more than writing code. Someone must frame and reframe
the problem, challenge assumptions, weigh alternatives, coordinate investigations,
and evaluate what the evidence actually supports. Decisions also need their
reasons preserved across chats. Without that continuity and judgment, you become
the manual dispatcher and reviewer, piecing together each Agent's work yourself.

Web Principal changes this relationship. Use **ChatGPT Web in a Project**, with
the Principal Core in its instructions, as your always-on high-level cognitive
partner. It helps keep the larger engineering question in view, develops
acceptance cases, and takes responsibility for the final synthesis. Project-local
state and memory preserve decisions and their causes for the next chat.

The Principal and Agents form **one collaborative AI team**. Bridge connects
your existing compatible **Herdr-managed Agent CLIs** across models and providers,
without a model/provider whitelist. Within Herdr's session and project-placement
requirements, Agents investigate and implement locally; the Principal seeks
divergent perspectives, independent challenge and cross-validation, then checks
reports against source evidence. **You retain goals, scope, material decisions
and authorization.**

## What Bridge adds

- **A partner for the bigger picture.** The Principal compares alternatives,
  questions assumptions and synthesizes a judgment, rather than just tracking
  task completion.
- **A team with different model perspectives.** Reuse any compatible
  Herdr-managed Agent CLI that meets session and project-placement requirements;
  Bridge has no model/provider whitelist. Cross-check findings and compare
  competing proposed fixes.
- **Delegate, then keep thinking and researching.** Dispatch bounded Agent
  investigations while the Principal does useful independent work. Where
  available, ChatGPT Web Search and Deep Research add host research alongside
  local Agents; they are separate from Bridge delegation. An explicitly enabled local extension can
  send short completion reminders to the selected ordinary Chat, with no guarantee of delivery or model wake.
- **Verify beyond reports.** Agents publish complete reports; ChatGPT can read,
  search and diff the selected project to check conclusions against source and
  acceptance cases. A readable report is evidence, not proof of success.
- **Review images and original files.** Observe native images and prepare
  original PDF/DOCX/ZIP ResourceLinks. Preparation is not upload, automatic
  parsing or host import; multipart recipients assemble and verify the original.
- **Carry decisions forward and act precisely.** Project-local state/memory and
  four reusable Skills support resumption. Separately authorized exact edits and
  Git candidate/commit actions keep local changes reviewable.
- **Use the ChatGPT Web plan you already have.** No separate API-billed Principal
  reasoning controller. Your subscription's reasoning and usage quotas still
  apply; Agent-provider usage and relay costs remain separate.

**One Principal. Many models. One collaborative team.**

## Install and begin

Use the complete release directory and its **`prepare`** entry (Windows: **`Start-Bridge.ps1`**).
Follow [Getting started](docs/GETTING-STARTED.md) for trust, account/permission steps
and recovery. The entry checks/downloads dependencies, prepares the existing strict
Bridge/Tunnel services and one browser extension, then separately asks for a local
work project. Codex is not an installation prerequisite. Herdr and Agent CLIs are
user-managed: open Herdr, cd to your repository and start your Agent yourself.
Bridge/Tunnel stay in the background; daily use needs no preparation entry.
Ordinary Web Chat may be opened before or after the Agent.

One installation can authorize multiple local projects and explicitly bind each to
one ordinary ChatGPT Chat. Adding a project does not reinstall the extension or
restart Bridge. New reminders include the source project and full Work identifiers.
This is a source-tested candidate, not a claim of fresh-account or Windows acceptance.

## How it fits together

Descriptive architecture — these roles are not executable commands:

```text
You: goals, scope, key tradeoffs and authorization
  |
ChatGPT Web Chat/Project: Principal reasoning and instructions
  |
Your Secure MCP Tunnel or HTTPS/App connection
  |
Bridge: explicit project selection, delegation, evidence and continuity tools
  |
Herdr: existing compatible local coding Agents in their native CLIs
  |
Your selected Git checkout(s)
```

Bridge is the tool infrastructure in this system, not another reasoning engine.
Project Instructions provide the always-on Core; Plugin Skills provide triggered
procedures; tool schemas define operations; local rules/state/memory preserve
project-specific judgment. No instruction template is an OS sandbox.

The [portable Principal Core](templates/WEB-PRINCIPAL-CORE.md) is ready to copy
into your own Project Instructions. [Web Principal](docs/WEB-PRINCIPAL.md)
explains its responsibilities and version. This public generic adaptation needs
your review and manual installation; Bridge does not configure your Project.

<a name="an-illustrated-review-workflow"></a>

## Example: Catch a two-cent invoice bug

An invoice adds **$0.29 + $1.15**. The correct total is **$1.44**, but our
[shipped fixture](examples/first-use/README.md) converts each amount with `float`
and truncates cents, yielding **$1.42**. It also silently treats missing values
as zero. A plausible-looking total can hide lost cents and incomplete data.

Ask ChatGPT Web, acting as Principal, to read the actual source and form
acceptance cases: preserve both cents, reject missing values, and handle large
amounts exactly. Then authorize one bounded, read-only review by an
already-running Herdr Agent. ChatGPT compares the report with the source and
test expectations; you separately authorize any repair.

```mermaid
flowchart LR
    A["You<br/>Authorize review"] --> B["ChatGPT Web<br/>Read source; frame cases"]
    B --> C["Local Agent<br/>Read-only investigation"]
    C --> D["ChatGPT Web<br/>Verify report against source"]
    D --> E["You<br/>Authorize next step"]
```

This narrated workflow is **illustrative, not an executed fix**. You may run
the tests yourself; Bridge has no generic test execution tool. Follow the
[first-use guide](docs/FIRST-USE-WALKTHROUGH.md) to try the review.

## Getting Started

**18 Tools, 0 Skills?** [Install the four Skills](docs/INSTALL-BRIDGE-SKILLS.md)
using your existing Bridge connection.

Start with [ChatGPT Project setup](docs/CHATGPT-PROJECT-SETUP.md) to assemble the
Core, connection, Skills and explicit project binding. For the local stack, use
the [developer Quickstart](docs/QUICKSTART.md); on Windows, start with
[Windows + WSL2](docs/WINDOWS-WSL.md).

Quickstart installs the `src/gpt_agent_bridge` package with `pip install -e .`
and launches `python -m gpt_agent_bridge` from that checkout's virtualenv, with
an explicit Git workspace. For boot / owner WSL login startup, choose the
[Bridge + Secure MCP Tunnel autostart guide](docs/AUTOSTART.md) after package
setup: two services, one optional WSL anchor, and manual Herdr/Agent startup.
The [Bridge component guide](docs/BRIDGE-AUTOSTART.md) covers Bridge-only setup
and the optional owner WSL anchor.

You will need:

- Git and Python **3.10+** with venv on the Linux codepath, including **WSL2**.
- Herdr plus compatible, already running Herdr-managed coding Agents in the
  intended checkout. Choose your own providers/models and confirm their quota.
- A configured local Bridge and an initialized MCP health check.
- Your own **Secure MCP Tunnel** (including account access and a runtime key), or
  verified HTTPS/SSE relay, plus a registered ChatGPT App and explicit Project
  Binding/authorization. Public App files contain a nonfunctional placeholder.

For foreground private first use, follow [OpenAI Secure MCP Tunnel](docs/OPENAI-SECURE-MCP-TUNNEL.md):
choose its combined Step 4 **before** the standalone Quickstart check consumes the
token handoff. It checks local health and starts your verified client. This tunnel
key is for transport, not an additional API-billed Principal reasoning controller.

Then try the [first-use walkthrough](docs/FIRST-USE-WALKTHROUGH.md): understand a
[small invoice bug](examples/first-use/README.md), authorize one read-only Agent
review, inspect its report and independently check the source. The nine starter
tests have **six intentional failures**; this is an illustrated exercise, not a
recording of a live fix. Optional fresh-chat continuity is a separate checkpoint.

The preparation entry automates supported local setup and preserves recoverable checkpoints.
Account trust/permissions, provider login and exact Chat consent remain human actions.
An unrelated running-process deployment is not automatically adopted.
Account permissions, the target Project Chat and actual connectivity need checks.

The maintainer reports field use with **Plus/Pro** and Windows WSL. These are
reported use cases, not automatic eligibility for every account or a fresh-host
acceptance guarantee. New clean WSL2 onboarding has not been field-validated;
the Linux codepath is not a claim of separately accepted bare-metal Linux.
Windows-native and macOS-native operation are unsupported/unverified.

## Tool reference

The [technical reference](docs/TECHNICAL-REFERENCE.md#tool-reference) contains the
**18-tool SOURCE catalog**; the retired app-only continuation
tools are absent. It also preserves migration notes, exact bounds and historical caveats.
Use actual client schemas; catalog annotations describe behavior, not authority.
See [original-file attachments](docs/TECHNICAL-REFERENCE.md#original-file-attachments)
for ResourceLinks, multipart assembly, fetch validation and transport limits.

## Linked checkouts and user-preplaced Agents

[Linked checkouts](docs/TECHNICAL-REFERENCE.md#linked-checkouts-and-user-preplaced-agents)
are optional write domains, not isolation. You select and launch Agents before
Bridge delegation; Bridge does not create worktrees, launch Agents or move them.

## Document owners and audiences

| Read next | Purpose |
| --- | --- |
| [Project setup](docs/CHATGPT-PROJECT-SETUP.md) / [Web Principal](docs/WEB-PRINCIPAL.md) | Install Core separately, connect tools/Skills and bind your project |
| [Quickstart](docs/QUICKSTART.md) / [Windows + WSL2](docs/WINDOWS-WSL.md) / [Secure MCP Tunnel](docs/OPENAI-SECURE-MCP-TUNNEL.md) | Foreground setup, private transport and own-App boundaries |
| [Bridge + Tunnel autostart](docs/AUTOSTART.md) | Optional boot/login setup, explicit activation and migration limits |
| [First use](docs/FIRST-USE-WALKTHROUGH.md) / [Invoice example](examples/first-use/README.md) | One bounded review, evidence checks and optional fresh-chat handoff |
| [Technical reference](docs/TECHNICAL-REFERENCE.md) | Full catalog, migrations, bounds, verification commands and optional service adoption |
| [Plugin Skills](docs/PLUGIN-SKILLS.md) / [Project continuity](docs/PROJECT-CONTINUITY.md) | Four procedures, routed state/memory and conditional publication |
| [Lifecycle](docs/LIFECYCLE-RESTART-CONTRACT.md) / [Work capacity](docs/WORK-CAPACITY.md) | Dispatch, continuation, restart, retention and pressure |
| [Observation tools](docs/OBSERVATION-TOOLS.md) / [Work evidence](docs/WORK-EVIDENCE.md) | Read/search/diff, exact edits, Git candidates and provenance |
| [Native execution retirement](docs/NATIVE-EXECUTION.md) / [AGENTS](AGENTS.md) | Removed execution surface and contributor boundaries |

Specialist documents remain the owners of their detailed contracts. This public
source ships no actual project cognition, private acceptance artifacts, working
App binding or configured service. Shared cognitive memory across hosts is not
implemented.

## Verification and deployment boundaries

Find exact default/stress commands and fixture limits in the
[verification reference](docs/TECHNICAL-REFERENCE.md#verification-and-deployment-boundaries).
Source/tests do not certify a running service, client-bound schemas or live host
behavior. Report reads do not prove review; notification consumption is not result
processing. Unknown delivery or mutation does not justify blind retry.

[Optional system service adoption](docs/TECHNICAL-REFERENCE.md#optional-system-service-adoption)
requires an already running Bridge. The installer does not start or enable it.
Successful tests never authorize a commit, push, restart, deployment or Agent input.

## License

Released under the [MIT License](LICENSE). Copyright (c) 2026 tomoyo.
