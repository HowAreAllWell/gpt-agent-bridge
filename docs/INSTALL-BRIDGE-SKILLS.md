# Install Bridge's four Skills in ChatGPT Web

Already have **18 Tools but 0 Skills**? Your custom MCP **Create as a plugin**
connection supplies Bridge tools; it does not import this repository's Skill
files. Keep that working connection. Bridge's SOURCE catalog has **18 model-facing tools**; the retired app-only
widget continuation tools are absent. The four native
Skills are reusable procedures, not four extra MCP tools.

This guide adds the procedures to a combined plugin through **Web Chat**, when
Plugin Creator and editing are enabled in your target workspace. It does not
configure your tunnel, replace credentials, or change your Project Instructions.
Follow [Project setup](CHATGPT-PROJECT-SETUP.md) for the other product layers.

Reviewed on **2026-10-11** against OpenAI's
[Web plugin creation guide](https://learn.chatgpt.com/docs/build-plugins) and
[developer packaging guide](https://developers.openai.com/plugins/build/plugins).
Availability depends on workspace permissions; these instructions are not a
recording of a successful installation in your account.

## 1. Open the Web creator with your existing connection

In ChatGPT **Plugins**, open your working Bridge plugin and choose **Edit Plugin**
only if you have edit permission and that control is offered. Otherwise start
a Web Chat, type `@`, and select **Plugin Creator** to create a private personal
combined plugin, if available. Tell Creator which already-connected, allowed
Bridge App to use; use an App selection control if offered. If editing your
working plugin, preserve its existing App. Inspect the final Apps mapping and
connection status; do not recreate the MCP connection, tunnel, or token.

If Creator cannot use that App or policy disables it, stop at that boundary.
A plugin cannot grant App access you do not already have.

## 2. Attach four separate canonical files

Use these **actual public file contents**, including each file's `name` and
`description` frontmatter and complete procedure body:

| Native Skill name | Canonical source file | Private attachment copy filename |
| --- | --- | --- |
| `project-resume` | [skills/project-resume/SKILL.md](../skills/project-resume/SKILL.md) | `project-resume.md` |
| `handoff-preparation` | [skills/handoff-preparation/SKILL.md](../skills/handoff-preparation/SKILL.md) | `handoff-preparation.md` |
| `project-onboarding` | [skills/project-onboarding/SKILL.md](../skills/project-onboarding/SKILL.md) | `project-onboarding.md` |
| `team-deliberation` | [skills/team-deliberation/SKILL.md](../skills/team-deliberation/SKILL.md) | `team-deliberation.md` |

Privately make four **copies** with the unique attachment filenames above and
attach them separately. Rename only the copies: preserve the full canonical
bytes, frontmatter metadata and procedure text; leave the original Skill folders
and files unchanged. If browsing GitHub, download the raw contents first; a URL
is navigation, not a guarantee of file import. Confirm all four inputs arrived
and review each distinct frontmatter `name`.

If attachment names still collide, send four complete texts, each individually
labeled with its Skill name, and confirm each was received without truncation.
Attachments or labeled text supply **input context**, not proof of installed
native Skills. Do not include private cognition, App configuration, reports, or
secrets.

Send this brief after identifying your existing App and supplying all four inputs:

```text
Create a private personal GPT-Agent Bridge plugin, or update the plugin opened
for editing. Use the already-connected, allowed Bridge App I identify in this
conversation. If editing my working plugin, preserve its existing App mapping.
Use an App selection control if offered; show the final Apps mapping for review
and let the host validate it. Keep the working tools connection.

Add exactly four distinct native Skills from the four separately supplied
canonical inputs (uniquely named file copies, or complete labeled texts):
project-resume, handoff-preparation, project-onboarding, team-deliberation.
Preserve each name, description, and full canonical procedure text. Do not
summarize, combine them into one Skill, leave them as reference files only,
or merge them into Project Instructions. Tell me if exact preservation is
unsupported rather than silently rewriting them.

Show me the Apps mapping and all four Skill bodies for review before I install.
Do not rebuild a tunnel, request tokens, create Agent tasks, initialize project
state, edit a repository, or execute any of these procedures.
```

## 3. Review and install the combined plugin

Before finishing, review the plugin's **Apps** tab/section and **Skills**
tab/section (labels can vary). Confirm the selected existing Bridge App and
exactly the four names above. Compare each full body with its canonical source
and supplied input, including authority limits; a four-name summary is insufficient.
Reference attachments alone do not establish native Skill installation.

Follow the supported UI prompts to finish and **install** the combined plugin
for your own use. Do not publish or share it as part of this check.

Keep identifiers separate: a browser `plugin_asdk_app...` identifier is not
a native App reference to paste into raw App mapping. Native references use
`asdk_app_`, `connector_` or `templated_apps_`; a matching format alone does
not prove eligibility. Do not strip/add prefixes or guess a conversion. Let
the eligible host resolve and validate your own App. The public root
[.app.json](../.app.json) is the nonfunctional
`asdk_app_REPLACE_WITH_OWN_APP_ID` placeholder, not your working connection.
[Package ownership](PLUGIN-SKILLS.md) explains the portable source layout.

## 4. Check a new target Web Project Chat

Start a **new Chat inside your intended Web Project** and select the installed
combined plugin from the `@` menu. Keep your existing Core and Project Binding.
Use this read-only check:

```text
Check the selected GPT-Agent Bridge plugin in this Web Project Chat.
Explicitly discover and read the installed native Skill bodies for
project-resume, handoff-preparation, project-onboarding, and team-deliberation.
Compare them with the canonical source files I provide; do not infer bodies
from names or manually pasted instructions. Report any missing/truncated Skill.

Separately call bridge_health() through the connected Bridge App and report
its actual result. Do not execute the Skill procedures, register/initialize a
project, send Agent input, edit files, run commands/tests, or perform Git actions.
```

Record two separate outcomes: **four native Skill bodies discovered** and
**Bridge health tool result observed**. Tool visibility alone is not connectivity;
health alone is not Skill discovery. Explicit discovery does not guarantee
automatic triggering, future usefulness, or model follow-up.

## If Web creation or discovery is unavailable

Check workspace permission with its owner/admin. Continue as **Tools-only**
if tools actually work; report Skills as unavailable/unverified. If Core was
also checked, say **Core + tools working; Skills unverified**. Do not call a
connection with zero native Skills a complete installation.

If you already have a verified native App ID and an eligible local client,
[the optional personal package route](PERSONAL-PLUGIN-INSTALL.md#b-advanced-generate-and-install-a-local-marketplace)
can prepare a separate eight-file marketplace using the public LICENSE and
unchanged Skills. It does not install anything. Work/Codex local marketplaces
are an **advanced, different surface**; acceptance there does not automatically
establish Web Project Chat availability.
Reading Skill text manually may help, but is not native Skill installation.
