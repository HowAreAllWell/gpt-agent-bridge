# GPT-Agent Bridge

[English](README.md) | [简体中文](README.zh-CN.md)

**Think with ChatGPT Web. Coordinate your local Agent team.**

A **Web Principal** is your thinking partner in ordinary **ChatGPT Web Project
Chat**. Use the supplied instructions to frame the real problem, question
assumptions and compare alternatives, then coordinate independent investigations,
implementation and review by your local Agents.

Bridge connects that conversation to your project and to **any authorized local
Agent already supported, runnable and managed by Herdr**, including terminal
Agents across providers and models. You keep control of goals, scope and
permissions; Bridge does not install providers or supply Agents.

**v0.1.0-rc.5 PRE-RELEASE is available.** [Download the full installation ZIP](https://github.com/HowAreAllWell/gpt-agent-bridge/releases/download/v0.1.0-rc.5/gpt-agent-bridge-clean-first-install-candidate-2026-10-20.zip) · [Release notes](https://github.com/HowAreAllWell/gpt-agent-bridge/releases/tag/v0.1.0-rc.5).
SHA256: `fbd764ade9b63372…` (full checksum below). Chrome reminders are optional.

**[Start here: the complete setup guide →](docs/GETTING-STARTED.md)**

| Your computer | Core preparation | Web and optional reminders |
| --- | --- | --- |
| **Native Ubuntu Desktop** | [Ubuntu Terminal: `./prepare`](docs/GETTING-STARTED.md#native-ubuntu-desktop) | ChatGPT Web; optional Chrome reminders on the same Ubuntu computer |
| **Windows + WSL2** | [Windows PowerShell: `.\Start-Bridge.ps1 prepare`](docs/GETTING-STARTED.md#windows-and-wsl2) | Same Web setup; optional Windows Chrome reminders; core runs in WSL2 |

Follow the guide from step 1 before using either command. You need existing
**Herdr 0.9.0** in the chosen Linux environment and the required ChatGPT workspace
controls. Check custom MCP, Plugin Creator/Skills and Project Instructions access
**before local installation**. You do not need a running Agent just to set up Bridge. Both routes
continue with the same ChatGPT Web setup; reminders are optional.

## Why Web Principal

- **Examine the question before dispatch.** Reframe unclear requests, expose
  missing premises and compare alternatives before choosing a plan.
- **Coordinate multiple independent Agents.** Give your existing Herdr Agents
  bounded questions in parallel, across providers and models. Separate
  implementation from review, and ask one Agent to challenge another's findings.
- **Check evidence before accepting results.** Read complete task reports and
  inspect actual code, files, diffs and test evidence. Distinguish observations
  from claims, gaps and unknown outcomes; agreement alone does not prove correctness.
- **Carry decisions across chats deliberately.** When authorized, preserve the
  decision, reasons and next boundary in project notes. This does not restore
  running tasks, replay them or automatically create global memory.

For example, when three eligible Herdr Agents are already available, explore a
storage-design decision with ChatGPT. Have two investigate independent questions
in parallel, then ask the third to review and challenge them. Check the reports
against the relevant code, diffs and test evidence before choosing an approach.
Each assignment still needs your authorization.

For demanding reasoning and decisions, optionally use
[GPT-6 Pro](https://help.openai.com/en/articles/20001354-gpt-6-and-other-models-in-chatgpt)
as the Web Principal while Herdr-managed Agents implement and review. You select
the model through your own eligible ChatGPT plan and workspace. Bridge does not
include model access, select it automatically or promise comparative speed or quality.

## How it works

1. **Prepare your computer.** The guide explains what you approve: a private
   Python environment and two Linux background services
   (Bridge and its Tunnel connection), installed, enabled and started.
   Chrome extension preparation and loading happen only if you later choose reminders.
2. **Connect ChatGPT.** A private **Secure MCP Tunnel** carries tool requests from
   ChatGPT to your Bridge. Install the connection as a plugin, then use
   **Plugin Creator** in ordinary Web Chat to add the four supplied **Skills** —
   reusable instructions for connecting, resuming, handing off and coordinating work.
3. **Choose the project and permissions.** Save the supplied base instructions
   (**Core**) in your ChatGPT Project. Connect an existing local Git repository,
   review the returned project-identifying text (**Binding**), and save it beside
   Core. Start with a small read-only check.

The guide gives separate checks for local preparation, the Web connection, all
four installed Skills, and the correct repository. A local health result or four
blue switches in a screenshot does not establish the remaining checks. Creating
the connection does not start Agents or authorize project work.

Plugin Creator and installation depend on plan/workspace permissions. If the
required controls are unavailable, stop at that account issue.
[Step 6](docs/GETTING-STARTED.md#6-install-and-discover-all-four-native-skills)
shows the five files to upload and how to verify the four installed workflows in
a **new ordinary Project Chat**. Work/local Codex is not the supported installation
path; success there cannot replace that check. No separate model API Principal is required.

The optional Chrome extension sends completion reminders only to the exact Chat
you explicitly select. On Ubuntu, it runs on the same computer as Bridge; on
Windows, load the final private Windows-local folder printed by the optional
`reminders` action (`./prepare reminders` or `.\Start-Bridge.ps1 reminders`).
It preserves drafts and does not send an appended reminder for you.

## After setup: three useful steps

1. **Orient:** select the authorized project and ask for current context and a
   read-only check of a named file. Verify the repository. When you need delegation,
   start your supported Agent in Herdr and check that it is actually available.
2. **Delegate deliberately:** state the question, allowed changes and acceptance
   criteria; authorize input to an observed eligible Agent. Continue useful
   independent reasoning while it works.
3. **Judge and preserve:** read the full report, compare original evidence, resolve
   contradictions and save decision-relevant project notes when authorized.
   A reminder proves neither success nor completed review.

Accounts, provider sign-in, model selection, fees and quotas remain yours.

## Download and status

Download [**gpt-agent-bridge-clean-first-install-candidate-2026-10-20.zip**](https://github.com/HowAreAllWell/gpt-agent-bridge/releases/download/v0.1.0-rc.5/gpt-agent-bridge-clean-first-install-candidate-2026-10-20.zip) from [v0.1.0-rc.5 PRE-RELEASE](https://github.com/HowAreAllWell/gpt-agent-bridge/releases/tag/v0.1.0-rc.5) (1,259,628 bytes).
SHA256: `fbd764ade9b63372872bc8e2e6bc71c2ebce771bd6aa3eb9c87ab8dfc38f4279`.
Extract the whole bundle; GitHub's **Source code ZIP** and **Code → Download ZIP** are not the installation package.
The old rc.4 ZIP lacks these fixes. The rc.5 ZIP and its bundled Markdown remain frozen; follow the [current online Getting Started](docs/GETTING-STARTED.md) for the latest instructions.

This pre-release has static ZIP/integrity validation only. Fresh native Ubuntu Desktop,
Windows WSL2, ordinary ChatGPT Web custom MCP, Plugin Creator/four Skills, Chrome
and restart behavior are **not field accepted**.

**Next:** [follow the beginner guide](docs/GETTING-STARTED.md).
Herdr prerequisite: [the short installation section](docs/GETTING-STARTED.md#herdr-090-prerequisite).
Advanced manual setup and optional example: [Quickstart](docs/QUICKSTART.md).
For service inspection and advanced manual stop/removal: [autostart](docs/AUTOSTART.md).
Advanced contracts and documentation navigation:
[technical reference](docs/TECHNICAL-REFERENCE.md).
Project notes: [continuity](docs/PROJECT-CONTINUITY.md).
Task, reminder and restart limits: [lifecycle](docs/LIFECYCLE-RESTART-CONTRACT.md).

[MIT License](LICENSE).
