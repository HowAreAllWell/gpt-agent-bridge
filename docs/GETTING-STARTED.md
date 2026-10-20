# Install Bridge and begin in an ordinary ChatGPT Project Chat

[English](GETTING-STARTED.md) | [简体中文](GETTING-STARTED.zh-CN.md)

Follow this guide in order for **one Bridge, one Secure MCP Tunnel companion and
one Chrome extension serving your local projects**. You provide the accounts,
choose the repositories and authorize work. Bridge discovers compatible Agents
you start yourself; installation does not launch them.

This public candidate's **first-use draft** is not fresh-install acceptance.
Windows-local extension preparation is implemented in the source candidate; the
full Windows/account sequence, Chrome loading and behavior after restart still
need field checks. Real, redacted screenshots illustrate controls, not success
on your machine. No Work Chat, Codex installation or API Principal is required.

## 1. Obtain the complete release and check prerequisites

Choose a reviewed **PRE-RELEASE** on the
[Releases list](https://github.com/HowAreAllWell/gpt-agent-bridge/releases) and
download its **single attached complete installation ZIP**. Check that release's
source commit, changes and limitations, and [LICENSE (original license text)](../LICENSE).
Pre-release status does not establish stability or field acceptance.
Extract the whole directory. It must contain `Start-Bridge.ps1`, `prepare`,
`release-manifest.json`, `src/`, `scripts/`, `systemd/`, `browser-extension/`,
`templates/` and all four `skills/*/SKILL.md` files. Keep the directory for recovery.
The manifest checks file bytes; it is not an independent publisher signature.

GitHub's automatically generated **Source code (zip/tar.gz)** archives and
**Code → Download ZIP** are source archives, not complete installation bundles;
they lack the manifest and Git metadata needed for preparation. If no authorized
full installation ZIP is attached, stop and request it; no developer build is
required by this walkthrough. GitHub main may contain changes not included in the
selected ZIP; these documentation changes do not rewrite older release artifacts.
The public package contains no working account binding or private connection token.
A source checkout containing extra private files, such as a screenshot archive,
is not a clean setup candidate and preparation refuses it. Do not package or
upload those private files to make a release.

Before running preparation, have these available:

- Windows with an existing **WSL2 Linux distro** and systemd, or Linux with systemd.
  In Windows PowerShell, `wsl --list --verbose` is an optional read-only inventory
  check; note the distro you intend to use. WSL1 and native Windows/macOS service
  installation are unsupported here. If WSL is absent, follow
  [Microsoft's WSL instructions](https://learn.microsoft.com/en-us/windows/wsl/install)
  before continuing. The launcher does not enable systemd or convert WSL versions.
- An existing Linux **Herdr 0.9.0 executable in that distro**, selected by you.
  Reuse it; if missing, follow [Herdr prerequisites](QUICKSTART.md#herdr-compatibility-and-version-selection) first.
  Its session may be closed, and no Agent needs to be running. Bridge does not
  install, upgrade or open Herdr, or install/log into a provider's Agent CLI.
- **Chrome 120 or newer**, and a ChatGPT workspace where Project Instructions,
  custom MCP plugins and Plugin Creator are available to you. Workspace permissions
  and Platform Tunnel permissions are separate. A subscription alone is not proof
  of access. Use ordinary Web Chat throughout this guide.

**Checkpoint:** you have the complete trusted directory, a chosen Linux environment
and Herdr executable, and access to the needed account controls. Do not run a demo
Agent or delegate work yet.

## 2. Prepare your Tunnel and restricted runtime key privately

In [Platform tunnel settings](https://platform.openai.com/settings/organization/tunnels),
select the correct owning **Platform organization**. Reuse a suitable Tunnel or
create your own. Associate it with the intended **ChatGPT workspace** as well as
the owning organization. These are distinct contexts; matching names are not proof
of association. Creating/editing needs **Tunnels Read + Manage**; running the client
and selecting the Tunnel in ChatGPT need **Read + Use**.
See [OpenAI's Tunnel permissions and associations](https://developers.openai.com/api/docs/guides/secure-mcp-tunnels).

When creating a Tunnel, enter its **Name** and **Description**, then choose the
intended **Organizations** and **ChatGPT workspaces** from the offered controls.

![Create tunnel form with organization and workspace identifiers masked](assets/getting-started/platform-tunnel-workspace.png)

*Organization and workspace are separate fields; this form does not show a completed Tunnel.*

In that owning organization's [Runtime API keys](https://platform.openai.com/settings/organization/api-keys),
create a dedicated runtime key. If the form offers **Project**, choose the intended
Platform API project; this is separate from your ChatGPT Project.
If your account exposes expiration and your controlled, dedicated service
credential policy permits it, choose **Never**; otherwise follow that policy and
plan replacement before expiry. Bridge does not configure this setting.

![Runtime key expiration menu with Never available and project value masked](assets/getting-started/runtime-key-expiration.png)

*Never is an available option here; the screenshot does not show it saved or a key issued.*

Under **Permissions**, select **Restricted** and leave unrelated scopes at **None**.
Do not choose the top-level **All** option or an Admin key.

![Restricted permissions table before Tunnel permissions are selected](assets/getting-started/runtime-key-restricted.png)

*Starting state: zero permissions selected. Tunnel access still needs the next action.*

Open the **Tunnels** permissions menu and tick **Read** and **Use** separately.
Check that both are selected and all other scopes remain **None** before creating
the key. Never include the generated key in a screenshot.

![Tunnels permission menu with Read and Use both checked](assets/getting-started/runtime-key-tunnels.png)

*All selected refers only to these two Tunnels sub-permissions, not the top-level All permission mode.*

The key's principal must also have the required Tunnel role; selecting a scope
cannot grant a missing role. Ask the organization owner/RBAC administrator if needed.

Keep the Tunnel ID and key private for step 4's local prompts, out of Chat,
Instructions/Core, screenshots, CLI arguments, reports and release files. The key
authenticates the Tunnel runtime. Reuse suitable working credentials without
creating another Tunnel or rotating a key just for this guide.

**Checkpoint:** you know which Tunnel belongs to the chosen organization/workspace,
and have a runtime key with the required role and narrow scopes. No Bridge service
or Chat connection has been established by these account actions.

## 3. Start preparation and confirm the exact WSL2 distro

Open **Windows PowerShell in the extracted release directory** and run:

```powershell
.\Start-Bridge.ps1
```

The entry lists verified WSL2 distributions. With one installed distro, check its
name in `Use WSL2 distro '…'? [Y/n]` and press Enter to confirm, or `n` to decline.
With several installed distros, type the **exact name** of one listed WSL2 distro.
An unknown name, WSL1, ambiguous inventory or unavailable selected distro stops
preparation. Check the subsequent `Using WSL2 distro: …` line before continuing.
Every later WSL runtime call uses this selection and its default Linux user;
it does not change the WSL default/version, systemd settings or restart WSL.

If WSL exists but no distro is installed, the entry instead offers official Ubuntu
installation only after you type `yes`, with possible Windows elevation/reboot.
Finish Linux user creation and any requested reboot, then run the same entry again.
Do not disable machine execution policy globally if Windows blocks the script;
review Properties / Unblock or use your administrator's normal trust procedure.

If Python 3/venv or Git is missing, the entry names the chosen distro and asks
permission before `sudo apt-get`. Approve only that intended installation; enter
your Linux password locally if sudo asks. Non-apt distros need their own trusted
package manager. The product requires Python 3.10+ and venv support.

For a **fresh Windows setup**, the same entry then asks for a
`Private Windows extension folder (existing parent, local NTFS)`.
Press Enter to use `%LOCALAPPDATA%\GPT-Agent-Bridge-extension`, or enter an absolute
path for a **new folder under an existing parent** on a fixed local NTFS drive,
without surrounding quotes. Confirm the displayed location by typing `yes`.
The entry checks ownership, permissions and path safety; an occupied or unsafe
destination stops preparation. Keep this location for Chrome. Bridge and Tunnel
stay in the selected WSL distro; existing installations are not moved or rekeyed.

For **Linux/WSL-only preparation**, run `./prepare` from the complete release
instead. That path keeps the extension in Linux and prints a verified WSL UNC
when applicable; it does not choose a Windows-local extension folder. Do not run
both entries for the same installation.

**Checkpoint:** the selected distro/user are correct, dependencies are available,
and the entry reaches `Trust this release and continue local preparation? [yes/no]`.
Review the displayed scope and type `yes` only if you approve it.

## 4. Follow the one local preparation through its handoffs

The entry copies checked release files into its own product directory, prepares a
private Python environment and installs its dependencies. It locates your existing
Herdr or asks for its absolute Linux executable path and checks version 0.9.0.
It downloads the pinned Secure MCP Tunnel runtime **0.0.16**, checking the configured
SHA256 before use; see [the pinned upstream release](https://github.com/openai/tunnel-client/releases/tag/v0.0.16).
Matching completed files are reused. Your work repositories are not moved.

Next it asks whether this installed extension may read registered project refs,
canonical roots and completion metadata, including future authorized registrations.
Approve only if you want that local discovery capability. It grants neither report
text access nor task authority; each Chat still needs explicit binding below.

### Keep the early private extension path

For a fresh Windows run, preparation generates the pairing once in protected WSL
files and privately publishes the same extension bytes into your chosen Windows
folder. You do not copy a token or `connection.js` yourself. The intermediate
`Windows publication is pending` message is not completion.

After the Windows files have been verified and publication confirmed, **before
service installation and credential prompts**, the terminal prints:

- `Expected extension ID:` — compare this with Chrome later.
- `Private extension Windows path (copy into Chrome Load unpacked):`, followed by
  the complete **Windows-local folder** on its own line.

Keep this final path for step 9. Re-entry uses the recorded destination and pairing;
it does not choose a new location or generate another identity to bypass a failure.
Preserve a stopped run's files and observe its error before retrying.

Linux/WSL-only or an existing recorded Linux preparation instead prints
`Private extension Linux path:`. On WSL it also prints `WSL distro:` and the same
Windows-path heading followed by a verified `\\wsl.localhost\…` line. Its receipt
path takes precedence over a guessed home directory. If it says
`Windows extension path: unavailable/unverified`, stop; do not invent a path.
Prepared files alone do not prove Chrome, services, Tunnel or Chat are connected.

<details>
<summary>Where preparation keeps files (do not copy or edit private configuration)</summary>

| Location | Purpose |
| --- | --- |
| Selected WSL user's `~/.local/share/bridge-release/` | Windows wrapper's checked release staging, not the Chrome loading folder |
| `<Linux account home>/.local/share/gpt-agent-bridge/product/` and `product/.venv/` | Private product and Python environment; account home comes from the Linux user record |
| Selected Windows-local folder (default `%LOCALAPPDATA%\GPT-Agent-Bridge-extension`) | Fresh Windows Chrome loading folder; keep its path and identity intact |
| `<Linux account home>/.local/share/gpt-agent-bridge/extension/` | Protected source for Windows publication; Linux/WSL-only preparation loads its printed receipt folder |
| Prepared extension folders' `connection.js` and `<Linux account home>/.config/gpt-agent-bridge/browser-notifications.json` | Generated private notification pairing; never share or copy its contents manually |
| `<Linux account home>/.local/share/gpt-agent-bridge/` | Extension receipt, pending recovery records, preparation lock and `Creator-attachments/` |
| `/var/lib/gpt-agent-bridge-tunnel-autostart/credentials.json` | Owner-only persistent Tunnel credentials, reused on later runs |

The strict installers also create protected service files under `/usr/local/lib/`
and `/etc/systemd/system/`, and private Bridge settings under
`/var/lib/gpt-agent-bridge-autostart/`. Do not edit generated files concurrently.
The preparation lock coordinates cooperating tools, not arbitrary external editors.

</details>

### Approve services, then enter credentials locally

The entry requests sudo for the strict Bridge/Tunnel installers. It installs and
activates Bridge, then installs the Tunnel service before asking for its credentials.
Port **8765** must be available for a new install. Other listeners are not killed.
Unsupported systemd/account layouts, `/mnt` service paths, symlinks or spaces in
installer-controlled paths can stop here; a successfully displayed extension path
does not bypass these separate service checks.

If no saved Tunnel credentials exist, the console asks exactly:

```text
Own Tunnel ID (hidden):
Own runtime API key (hidden):
```

Enter the complete corresponding values locally, without quotes or added labels.
Characters are not echoed. A private interactive terminal is required; do not
redirect input or paste either value into Chat. Existing validated credentials
are reused without asking again; local format/ownership checks do not validate
remote roles or expiry. The runtime receives the key privately; you never need to
copy Bridge's secret MCP endpoint into a command or Chat.

The entry then enables/starts the owned Tunnel service and prints `Local checks:`.
Look for `"bridge_mcp": "initialized_healthy"`. This is initialized **local Bridge
MCP health**; Herdr may be unavailable with its session closed. Service `active`
is a process observation, not proof of Tunnel control-plane access or Web access.
This preparation path does not run the separate Tunnel readiness status probe.

Keep going through the software handoff. Note the printed directory of **four
named Skill attachments and LICENSE**. At the optional native own-App ID prompt,
press **Enter** and use the Web App selection in step 6. Do not guess an ID from a
browser URL. The entry prints the public Core file path and finally:
`Software preparation is complete; no repository or running Herdr session/Agent is required. You may close this terminal.`

**Checkpoint:** preparation ended normally, local MCP health was observed, and you
have the printed extension and Skill handoff paths. This has not installed the
Web plugin/Skills, connected a project or authorized notification delivery.

## 5. Connect the Tunnel to your private ChatGPT plugin

In the intended ChatGPT workspace open [Plugins](https://chatgpt.com/plugins),
use the plus control and **Add custom MCP server**. Give it a recognizable name
and description, set **Connection: Tunnel**, and select your own Tunnel. If the
form offers ID input, enter that same ID only in this official field, never a Chat
message. Do not paste the runtime key into the form.

![Redacted Add custom MCP server form with Tunnel selected](assets/getting-started/mcp-tunnel-form.png)

*Real form example; authentication is still at its OAuth default.*

Change the MCP authentication option to **No authentication** for this private
Bridge connection. Bridge has no OAuth server; Tunnel roles and Bridge's protected
local endpoint still apply. This choice does not make a public unauthenticated
endpoint. Review the risk warning, then choose **I understand and want to continue**
and **Create as a plugin** only if you accept the displayed scope.

![Redacted form with No authentication and the Tunnel ID masked](assets/getting-started/mcp-no-auth.png)

*Real form configuration, not a completed plugin.*

Review the discovered tools and use **Install** when offered. Create or open the
ChatGPT Project you intend to use, then open an ordinary Chat inside it and select
your installed plugin through `@`.
Ask: “Call only read-only bridge_health and show its actual result. Do not register
projects, initialize state or send Agent input.” Inspect the tool result, not just
a sentence saying the connection works. See [the official Tunnel connection flow](https://developers.openai.com/api/docs/guides/secure-mcp-tunnels).

**Checkpoint:** that ordinary Project Chat successfully called `bridge_health`.
Local preparation, a plugin card or tool names alone do not establish this result.
If the Tunnel is absent or the call fails, use the troubleshooting table below;
do not reinstall Bridge to repair an account permission problem.

## 6. Install and discover all four native Skills

**Create as a plugin connects MCP tools; it does not install these four Skills.**
In ordinary Web Chat select **Plugin Creator** via `@` when available. If editing
your working plugin is offered and authorized, keep its existing App mapping;
otherwise ask Creator to use your already-connected Bridge App in a private
combined plugin. Use the host's App picker if offered, not a guessed identifier.
[OpenAI's creation guide](https://learn.chatgpt.com/docs/build-plugins) describes
this permission-dependent workflow; it does not guarantee account eligibility.

Attach the four separately named Markdown files and LICENSE from the printed
`Creator-attachments/` folder. On Windows, browse that folder in the same selected
WSL distro's Linux filesystem; the extension folder is not the attachment folder.
The copies preserve these canonical sources:

- [project-onboarding (canonical, untranslated)](../skills/project-onboarding/SKILL.md)
- [project-resume (canonical, untranslated)](../skills/project-resume/SKILL.md)
- [handoff-preparation (canonical, untranslated)](../skills/handoff-preparation/SKILL.md)
- [team-deliberation (canonical, untranslated)](../skills/team-deliberation/SKILL.md)

Send this credential-free brief:

> Add four separate native Skills named project-onboarding, project-resume,
> handoff-preparation and team-deliberation from my four attached files, preserving
> their full texts, metadata and LICENSE. Use my existing connected Bridge App.
> Show the App mapping and all four Skill bodies for review before I install.
> Do not recreate the MCP connection, collect credentials, publish/share, execute
> the procedures or leave them as reference attachments only. Stop if exact native
> packaging is unavailable.

Review each full Skill body and the existing App mapping. Finish creation/editing
and installation using the controls your account actually offers. Do not grant
blanket tool permission just to reproduce an example.

![Cropped developer plugin Skills section showing four enabled Skills](assets/getting-started/plugin-installed-skills.png)

*Redacted developer example: four Skills are on; this does not prove automatic import or your installation.*

In a new ordinary Project Chat select the resulting plugin and ask it to discover
and read all four installed native Skill bodies **without executing them**. Compare
the names and complete procedures with the sources above. Uploads, a four-name
summary or MCP tool discovery alone are insufficient. Keep this Chat for the later
project connection and notification binding.

**Checkpoint:** all four native Skills are discovered in the target Web Chat.
If creation/discovery is unavailable, record “tools working; Skills unverified”
and stop this full-product setup at that account gate. The
[Skills packaging and diagnostics](TECHNICAL-REFERENCE.md#attachment-and-discovery-diagnostics) diagnose this layer without a second
Tunnel installation; a Work-only result does not pass the ordinary Web check.

## 7. Put the public Core in Project Instructions

Open [templates/WEB-PRINCIPAL-CORE.md (canonical, untranslated)](../templates/WEB-PRINCIPAL-CORE.md), read it,
and copy its **complete public text**. In your ChatGPT **Project settings →
Instructions**, merge that text with relevant existing instructions. It is the
Principal's instruction text, not an installer, executable command, Skill attachment
or one-off Chat message. It supplies no connection credentials or project authority.

![Project settings with project name and Instructions contents masked](assets/getting-started/project-instructions.png)

*Real Instructions control with private text removed; no explicit save button is shown.*

Finish using the controls actually present, then reopen Instructions to check the
full text persisted without truncation and your prior rules remain. Do not infer
saving from this screenshot. Never insert secrets or another project's Binding.

**Checkpoint:** the Project's persisted Instructions contain the complete public
Core and your retained rules. Return to an ordinary Chat inside this same Project
with the Bridge plugin selected; Core text alone does not connect a local repository.

## 8. Connect your existing Git repository and merge its Binding

Tell the Principal to use **project-onboarding**, providing the exact existing
Linux Git root you authorize and your chosen project ref. For example, describe
those two values in your own words, then say:

> Connect only this existing repository with project-onboarding. Inspect registration
> and context; register only if needed. Return the Project Binding for me to review
> and merge into this Project's Instructions. Do not initialize continuity, create
> a repository, launch Agents, send tasks or edit project files.

Review the actual registered canonical root/ref returned through Bridge. Manually
merge the returned **Project Binding (Host Binding)** into the same Project
Instructions alongside Core, preserving unrelated instructions. Reopen and verify
it persisted. ChatGPT Project names and local repository names do not establish
this mapping. No local registration/sync command is needed.

**Checkpoint:** the returned ref/root match your authorized repository and its
Binding is in the intended Project. Connection-only ends here; `project_initialize`
and continuity seeding require a separate explicit request. Registration grants
neither an Agent task nor a notification destination.

## 9. Load the private extension and bind this exact Chat

Open Chrome's `chrome://extensions`, enable **Developer mode**, choose **Load
unpacked**, and select the **private prepared extension folder printed in step 4**.
For a fresh setup through **Start-Bridge.ps1**, select the **final printed
Windows-local folder** in the folder picker. For Linux/WSL-only preparation, use
the printed Linux path or verified WSL UNC as appropriate to the browser host.
Do not select the ZIP, public/source folder, WSL publication source in place of
the final Windows folder, release staging directory or
`product/browser-extension/extension` template.
Compare Chrome's extension ID with the printed expected ID.

Keep this private folder, its `connection.js`, loading location and manifest
identity intact. Existing installed extensions retain their original loading
directory and identity; this fresh-install flow does not authorize relocating them.
If the ID mismatches or Chrome cannot load the printed folder, stop;
do not relocate, uninstall/reinstall or clear storage as a workaround.
**Fresh Windows-local installation, Chrome loading from WSL UNC and behavior
after restart are not yet field accepted.** A printed path or successful file
publication does not establish Chrome acceptance.

Open one exact, existing, ordinary non-private Chat tab inside your Project. Keep
only one ordinary tab for that full destination route. In the extension popup:

1. Choose the registered repository under **本地项目**; verify its identity/root.
2. Tick **允许向当前 Chat 自动发送完成提醒**.
3. Click **设为接收 Chat 并启用**.
4. Check **接收 Chat：当前 Chat** and **自动通知已启用**, and inspect any error shown.

Bind **before delegation**: first enable does not replay older completions. Each
local project has one explicit recipient; adding a project or opening another Chat
does not select it. To change it, explicitly select the new current Chat and authorize
enable again. Only provably never-attempted queued/waiting reminders with a valid
saved route may follow for their **first send**. Old attempted, ambiguous or frozen
identities never move or replay, even after returning to the original Chat, worker
restart or producer epoch change. Their retained raw-ID suppression evidence does
not block a different new Work or create a standing warning; do not clear storage
to bypass it. The 128 limit is for live unattempted reminders, not settled history.

A truly empty, safe composer can send the fixed notice automatically once. A real
text, rich-content or uploaded-file draft instead gets a nonmutating inline
**追加到输入框末尾（另起一行） / 忽略** choice, including while you type or use IME.
Ignore leaves the current draft and attachments intact. Append, after active IME
composition ends, adds only a fixed notice paragraph to the current bound editor;
it does not click Send, replace your draft or transmit file contents to the worker.
Normal edits and attachment changes need no quiet wait. If you submit before an
asynchronous Append executes, it refuses that old choice; choose again for the
current message. An undecided reminder stays pending after refresh/close; the next
normal poll rechecks the exact Chat and may offer again or use the safe empty path.

A local Send click or successful explicit choice is handled once, not proof that
ChatGPT received a message or that a backend acknowledged it. Unknown effects are
not retried. No transcript/receipt scan, notification history UI or old-unknown
warning is used to confirm delivery. Current errors and pending diagnostics remain.

**Checkpoint:** the intended project and exact Chat are visibly enabled. This is
binding state, not proof a reminder was delivered. The adapter is currently verified
only against English ChatGPT Web/Project Chat DOM; changed UI or other languages
may wait or refuse. See [extension behavior and recovery](LIFECYCLE-RESTART-CONTRACT.md#chrome-notification-authority-and-recovery).

## 10. Begin daily use with a bounded read-only check

There is no daily `prepare` step. While the host/WSL and network stay online,
installed Bridge/Tunnel services can run in the background without an open
preparation terminal or Herdr session. Windows logout, WSL shutdown/suspension and
restart are separate availability boundaries; no restart acceptance is claimed.
The [optional WSL logon adapter](AUTOSTART.md) is a separate operator decision.

Open Herdr yourself in the chosen Linux environment, enter the authorized Git
repository, and start/sign into your chosen compatible Agent there. Reuse existing
eligible sessions. Provider setup, model choice and quotas remain yours. You can
open ordinary Web Chat before or after starting the Agent; Bridge never starts one
for you. Ask the Principal for fresh `context(project_ref)` and inspect actual Agent
availability. An error/incomplete observation is unknown, not proof of no Agents.

For a small **read-only** first check, explicitly authorize the Principal to inspect
only the registered project's overview/context and one nonsecret file you name,
then summarize it with source evidence. Specify no edits, commands/tests, Git actions,
initialization or Agent input. Check the returned root/ref and cited file content.
This proves only the exercised read path; it creates no smoke Work or notification.

For real delegation, state the task, allowed changes and acceptance criteria, and
explicitly authorize input to an observed eligible Agent. Principal uses fresh
context handles, delegates and reads the complete `work_report`, following all pages
with its full SHA pin. A reminder gives project/Work refs, not the report or proof
of success. The [invoice example](QUICKSTART.md#optional-invoice-demo) is optional;
it grants no permission to start a demo Agent.

**Checkpoint:** distinguish the successful read-only check from later delegated
work, actual reminder delivery and complete report review. Passing one does not
certify the others. If no real task is authorized, stop after the read-only check.

## If a step stops

Keep completed files and the exact nonsecret error. An unknown outcome requires
observation before another mutation; do not reset, replay or reinstall to guess.

| Observation | Next safe action |
| --- | --- |
| Project Instructions are unavailable, rejected or truncated | Check the actual account controls and text limit. Preserve existing rules; do not claim that a partial Core was installed. |
| Copy, dependency or extension preparation stopped | Inspect the named failure. Re-enter the same release/path/distro/user only when safe: matching files/receipts are reused, an owned partial venv can be completed, and unknown changed files stop. A different release is not an automatic upgrade. Do not delete receipts, generated keys or existing folders. |
| Windows-local publication stopped | Keep the recorded target and staging files. Do not pick another folder, move the original extension or copy secrets manually. Inspect the fixed diagnostic before another attempt; an earlier run may already have reached service setup. |
| Extension Linux path printed, Windows path unverified | Check the selected distro and its path converter; retain the files. Do not guess a UNC or continue to Chrome as if loading succeeded. |
| Service install/start failed or state unknown | Preserve the installation. Use the owner/status guidance in [Bridge autostart](AUTOSTART.md#bridge-component-contract) or [Tunnel autostart](AUTOSTART.md#tunnel-component-contract) for that failed layer. Do not kill another service or repeat an uncertain start. |
| Tunnel absent in the plugin picker, or 403 | Check owning organization, target ChatGPT workspace association, operator/key principal's Tunnel role and Restricted Read + Use scope. Fix that account gate; do not create another local installation. |
| Saved key is wrong/expired | Use the same release's explicit credentials action described below; do not send the replacement to Chat. |
| Tools work but four native Skills are missing | Keep the working MCP connection; resolve Creator/installation permissions and verify native discovery in ordinary Web Chat. |
| Project registration is uncertain or conflicts with an existing route | Inspect the read-only registration observations and ask the owner to reconcile. Do not redirect the route or blindly register it again. |
| Reminder waits, or result is unknown | Check the exact bound Chat for Append/Ignore and current popup diagnostics. Stop, active IME in an empty editor, upload or unsafe composer state can defer automatic Send. Old unknown IDs are silent suppression evidence, not a reason to replay. Do not clear storage or use a synthetic diagnostic as a first-use test. |

For recovery only, Windows `.\Start-Bridge.ps1 status` (Linux `./prepare status`)
reports preparation file existence, **not service health**. The separate Tunnel
status can report `tunnel_startup: ready`, but still labels control-plane verification
and Web readiness unestablished. The actual Project Chat `bridge_health` result is
the remote checkpoint; do not run duplicate status commands as a daily ritual.

If a saved key must be replaced, run `.\Start-Bridge.ps1 credentials` (Linux
`./prepare credentials`) from the same release. Confirm replacement and enter values
at the hidden local prompts. It initially leaves services unchanged, then separately
asks permission to stop/start **only the owned Tunnel service** with sudo. Declining
defers activation. Observe an uncertain outcome before any further mutation;
Bridge itself need not restart. This is recovery, not a second first-use step.

Legacy extension adoption needs separate authorization; preserve its original
path, ID/key, token and histories. The [extension reference](LIFECYCLE-RESTART-CONTRACT.md#chrome-notification-authority-and-recovery)
and service references explain individual contracts, not another required installation.
