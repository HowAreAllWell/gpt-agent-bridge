# Install the four Bridge Skills for your existing tools

Use this guide when your own GPT-Agent Bridge MCP tools already work but native
Skills are missing. **Create as a plugin** for a custom MCP connection does not
by itself package these four procedures. Keep your existing connection and
running Bridge/tunnel. Choose one of the three routes below; none grants new
project, service, account or Agent permissions.

## A. Easiest: Web Plugin Creator, without a CLI

When your workspace offers Plugin Creator, use the
[official Web creation flow](https://learn.chatgpt.com/docs/build-plugins).
It requires Use plugins permission, Plugin Creator availability and access to
the existing App. A browser conversation does not make every plugin or App
eligible for your account.

1. Open Chat or Work on the web, type `@`, and select **Plugin Creator**.
2. Attach the four canonical files from a reviewed public Bridge clone. Identify
   each attachment by procedure name, since all source basenames are SKILL.md.
   If your upload UI needs distinct filenames, upload distinctly named copies
   with unchanged contents; preserve the original source files.

   | Procedure | Canonical attachment |
   | --- | --- |
   | project-onboarding | [skills/project-onboarding/SKILL.md](../skills/project-onboarding/SKILL.md) |
   | project-resume | [skills/project-resume/SKILL.md](../skills/project-resume/SKILL.md) |
   | handoff-preparation | [skills/handoff-preparation/SKILL.md](../skills/handoff-preparation/SKILL.md) |
   | team-deliberation | [skills/team-deliberation/SKILL.md](../skills/team-deliberation/SKILL.md) |

3. Choose your existing, working Bridge App from the Apps available to you.
   Ask Creator to prepare a private plugin containing **four separate native
   Skills**, preserve their text and connect that App. For example:

   ```text
   Prepare a private personal GPT-Agent Bridge plugin using the four attached
   canonical procedures: project-onboarding, project-resume,
   handoff-preparation and team-deliberation. Keep each as a separate native
   Skill with its exact name and reviewed text, not one combined instruction
   or reference-file-only upload. Use my existing working Bridge App selected
   from those available to me; let the host resolve its eligible native App ID.
   Do not recreate the MCP connection, change its permissions, collect
   credentials, restart services, edit the source checkout or publish/share.
   Show the procedures and App binding for review. Stop if that exact packaging
   or existing App selection is unavailable.
   ```

4. Review the result before finishing Creator's prompts. Verify the App is yours
   and all four separate procedures remain present. Preserve the public source's
   license/attribution when copying Skill text; provide its existing LICENSE as
   an additional reference if Creator produces an exportable package. Do not
   invent a license or upload private developer configs/cognition.
5. Finish the private creation/install controls actually offered, then run the
   [target-chat checkpoint](#verify-in-the-target-project-chat) below. If Creator
   cannot retain four native Skills or select your existing App, use route C;
   do not describe a reference-file upload as installed Skills.

### Browser plugin ID versus native App ID

A browser URL beginning `plugin_asdk_app_` identifies a plugin representation,
not a value to paste into raw `.app.json`. The
[official existing-App reference](https://learn.chatgpt.com/docs/enterprise/plugin-management#reference-an-existing-app-with-appjson)
explains that distinction. For your verified own connection, use Creator's
existing-App selection and host-resolved binding. Never infer, trim or remove a
prefix yourself. A matching string alone does not establish an eligible App,
ownership, account access or connection permissions.

## B. Advanced: generate and install a local marketplace

Use this route only if you already have a **verified native App ID** for your
own eligible existing connection and a supported local marketplace installation
surface. The generator prepares files; it does not install or contact a host.

The [shared native ID check](https://developers.openai.com/plugins/deploy/submission-errors#mcp-server-reference-errors)
allows `asdk_app_`, `connector_` or `templated_apps_`, followed by one ASCII
letter/digit and then ASCII letters/digits/underscores/hyphens. Uppercase and
different suffix lengths are allowed. The generator adds a **local 256-character
total limit** and rejects the known public placeholder, browser IDs, URLs,
whitespace, non-ASCII and controls. It preserves your input exactly; there is no
browser-to-native conversion. If you only have a browser URL, return to route A
and have the host select the existing App.

### Use a reviewed licensed public source

Run with Python 3.10+ on Linux/WSL and review
[the generator](../scripts/prepare-personal-plugin.py) first. Inputs must come
from a trusted **public source checkout with its existing root LICENSE**,
plugin.json and four canonical Skills. The reviewed public distribution includes
its MIT notice and attribution. The generator copies that exact notice; it does
not decide licensing or generate copyright text.

The internal development checkout has no root LICENSE, so its default source
fails closed. Do not create a license there to bypass this check. Use a reviewed
public clone that includes this generator, or explicitly point an already
reviewed script at that public source. If the public clone lacks the script,
this local candidate has not reached it yet; do not assume a command is available.

From a public clone containing the script:

```bash
python3 scripts/prepare-personal-plugin.py \
  --marketplace-root "$HOME/bridge-personal-marketplace"
```

When running a reviewed script elsewhere, explicitly choose your reviewed
licensed public source (adjust the source path to your actual clone):

```bash
python3 scripts/prepare-personal-plugin.py \
  --source "$HOME/gpt-agent-bridge-public" \
  --marketplace-root "$HOME/bridge-personal-marketplace"
```

Choose a new absolute output directory outside the source. Its parent must
already exist, belong to you and not be writable by group/others. Paths must not
contain symlinks or traversal. Existing destinations, including empty directories
and broken links, are refused; no existing marketplace is merged or overwritten.

Enter only the verified native App ID at the hidden prompt, never an API key,
password, tunnel ID or token URL. Do not use arguments, shell history, public
reports, screenshots or Project Instructions for the ID. Input echo fallback
is refused. The ID appears only in the generated private `.app.json`.

For noninteractive use, `--id-file /absolute/private/id-file` accepts one exact
UTF-8 ID line, optionally ending in LF. The file must belong to you, have mode
0600 or 0400, and have no symlink/hard link. The same 256-character total ID limit
applies. Prepare that input yourself in a private editor; the generator neither
writes nor deletes it. Never pass a real source `.app.json` as the input file.

### Exact eight-file result

```text
bridge-personal-marketplace/
├── .agents/plugins/marketplace.json
└── plugins/gpt-agent-bridge/
    ├── plugin.json
    ├── LICENSE
    ├── .app.json
    └── skills/
        ├── project-resume/SKILL.md
        ├── handoff-preparation/SKILL.md
        ├── project-onboarding/SKILL.md
        └── team-deliberation/SKILL.md
```

The manifest, LICENSE and four Skills are exact source-byte copies. Missing,
empty, invalid UTF-8, unsafe or changing LICENSE inputs stop publication.
The notice is checked again with the source snapshot before publishing.
The generator validates safe notice text, not its legal applicability: review
the public source's actual licensing before copying or distributing it.

The generated mapping is alias `bridge`, your exact native ID and
`required: true`. The catalog uses
`source.path="./plugins/gpt-agent-bridge"`, relative to the marketplace root,
and marks the entry AVAILABLE with ON_INSTALL authentication. Source version is
retained. No hooks, compatibility overlay, runtime source, private docs, real
source App binding or cognition are copied.

Directories are created with mode 0700, files 0600 under the normal tested umask.
A private temporary sibling and Linux `renameat2(RENAME_NOREPLACE)` publish
without clobbering a concurrent destination. Unsupported environments fail
closed, without an overwrite fallback. Cleanup removes only identified objects
created by this invocation. Unknown/replaced content and crashes can leave a
private `.bridge-plugin-pending-*` sibling; inspect it manually rather than
using blanket recursive cleanup. A post-publication durability warning requires
inspection before retry. These checks do not isolate malicious same-user
processes.

### Explicit host installation

Review the private generated package and compare its notice/Skills with the
source. Generation has not changed the host. Where your client supports the
[official local marketplace flow](https://developers.openai.com/plugins/build/plugins#add-a-marketplace-from-the-cli),
the user may explicitly add this marketplace root:

```bash
codex plugin marketplace add "$HOME/bridge-personal-marketplace"
```

This command changes host configuration; the generator never runs it. In an
eligible local Work/Codex desktop surface, refresh/restart the desktop app as
the current instructions require, open Plugins Directory, select Personal
GPT-Agent Bridge and install GPT-Agent Bridge. Review App authentication and
permissions. This is not a Bridge/tunnel restart or a universal Web Project Chat
installation path. Account/workspace policy can block local sources or App access.
Do not edit host caches, global config, admin settings or another marketplace
to bypass those limits. Sharing/publication needs separate review and authority.

## C. Keep Tools-only when installation is unsupported

If Creator is unavailable, the existing App is ineligible or your target surface
cannot install/discover the four Skills, keep the already working MCP tools.
Record **tools available; Skills unverified**. Only add **Core +** if Core was
separately installed and checked in Project Instructions. Manual reading or
pasting procedure Markdown can assist a task, but is not native installation or
complete-product acceptance.

## Verify in the target Project Chat

After either supported installation route, open a fresh chat in the intended
Project and select/enable the plugin where the UI offers it. Ask:

```text
Read-only check: explicitly discover this chat's installed Skill catalog.
Find project-onboarding, project-resume, handoff-preparation and
team-deliberation under my Bridge plugin and compare their available texts
with the canonical attachments I reviewed. Do not invoke these procedures,
register/initialize a project, delegate Agent input or change any files.
Separately call bridge_health and inspect the returned Herdr.status.
```

Use actual results, not a prose assertion or a shortened per-turn listing.
Testing in Work/Codex does not certify ordinary Web Project Chat availability.
Discovery does not certify automatic selection, trigger reliability or continuity.
After all four are verified on the actual target surface, return to
[Project setup](CHATGPT-PROJECT-SETUP.md) and the
[first-use walkthrough](FIRST-USE-WALKTHROUGH.md). Registration, initialization,
Agent input and continuity keep their separate permissions.
