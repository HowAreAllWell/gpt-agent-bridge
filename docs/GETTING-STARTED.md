<a id="install-bridge-and-begin-in-an-ordinary-chatgpt-project-chat"></a>
# Set up Bridge and use it in ChatGPT Web

[English](GETTING-STARTED.md) | [简体中文](GETTING-STARTED.zh-CN.md)

Use this short path; the linked sections explain the clicks and prompts.
A running Agent is not needed for setup. Installation needs Internet access.

| Step | What to do |
| --- | --- |
| 1 | [Check your account and computer](#1-obtain-the-complete-release-and-check-prerequisites), including Linux Herdr **0.9.0**. |
| 2 | [Download the complete installation package](#download-the-complete-package). |
| 3 | [Create your private Tunnel and Restricted runtime key](#2-prepare-your-tunnel-and-restricted-runtime-key-privately). Never paste secrets into Chat. |
| 4 | In the extracted folder: [Ubuntu `./prepare`](#native-ubuntu-desktop) **or** [PowerShell `.\Start-Bridge.ps1 prepare`](#windows-and-wsl2). This sets up two services. |
| 5 | [Add the Web connection and check bridge_health](#5-connect-the-tunnel-to-your-private-chatgpt-plugin). |
| 6 | [Install all four Skills with one `Bridge-Skills.zip` upload](#6-install-and-discover-all-four-native-skills). |
| 7 | [Save Core + your project's Binding](#7-put-the-public-core-in-project-instructions). |
| 8 | [Read one named file and begin daily use](#10-begin-daily-use-with-a-bounded-read-only-check). |

**Optional afterward:** [Chrome reminders](#9-load-the-private-extension-and-bind-this-exact-chat).

<a id="choose-your-computer"></a>
<a id="1-obtain-the-complete-release-and-check-prerequisites"></a>
## 1. Check access and prerequisites before installing

In the **ChatGPT workspace you intend to use**, check that you can:

- Open [Plugins](https://chatgpt.com/plugins) and add a **custom MCP server**.
- Use **Plugin Creator** in ordinary Web Chat to create and install native Skills.
- Open a ChatGPT **Project** and edit its **Instructions**.

These controls depend on your account and workspace. Labels can differ from the
examples below. If a control is missing or blocked, stop and ask the workspace
administrator about access **before installing locally**. Work/local Codex
access does not substitute for this Web setup. No separate model API Principal
is needed; the Tunnel does need its own runtime key.

| Your computer | Supported setup route |
| --- | --- |
| **Native Ubuntu Desktop** | Ubuntu Terminal, systemd running as PID 1, Python 3.10+, Linux `x86_64` or `aarch64`. No WSL or PowerShell. |
| **Windows + WSL2 Ubuntu** | Windows PowerShell launches the selected WSL2 distro using its default nonroot Linux user. Inside it: the same systemd, Python and architecture requirements. |

If WSL2 or systemd is not ready, complete [Microsoft's WSL setup](https://learn.microsoft.com/windows/wsl/install)
and [systemd setup](https://learn.microsoft.com/windows/wsl/systemd) separately.
Native Windows/macOS and WSL1 are not this route. Ubuntu Server/headless use is
[advanced](QUICKSTART.md#native-ubuntu-desktop-and-server), with separate browser
and Agent-session limitations.

<a id="herdr-090-prerequisite"></a>
### Herdr 0.9.0 prerequisite — no running server or Agent needed

Use **Ubuntu Terminal**, or open the **selected Ubuntu distro** on Windows and
use its Bash terminal as the same Linux user that will own Bridge. These are
Linux commands, not PowerShell; Windows `herdr.exe` is not this prerequisite.
First check (keep the printed executable path):

```bash
command -v herdr
herdr --version
```

If it reports **0.9.0**, continue to step 2. Otherwise use the fixed download
below. It needs `curl` and `sha256sum`; if missing on Ubuntu, run
`sudo apt install curl coreutils` first. The generic Herdr installer follows the
latest version, so do not substitute it here. Assets and digests are from the
existing [official v0.9.0 release](https://github.com/herdrdev/herdr/releases/tag/v0.9.0)
and [release metadata](https://api.github.com/repos/herdrdev/herdr/releases/tags/v0.9.0).

This block chooses `x86_64` or `aarch64`/`arm64`, creates a new private version
folder outside your project, checks the SHA256 **before** making the download
executable, then prints its version and full path. It does not overwrite an
existing folder or change your saved PATH.

```bash
(
  set -euo pipefail
  umask 077
  command -v curl >/dev/null
  command -v sha256sum >/dev/null
  case "$(uname -m)" in
    x86_64)
      asset=herdr-linux-x86_64
      digest=4fa1a01158dd8043da92d31b270780b0dcc10603038d9b61cac4d81ab63fb71f
      ;;
    aarch64|arm64)
      asset=herdr-linux-aarch64
      digest=9c8db20fb7e7427b138d5367113f1621ffd319f2f65d6f009e2594029115f0d2
      ;;
    *) printf 'No pinned asset in this guide for this architecture.\n' >&2; exit 1 ;;
  esac
  [[ "$HOME" = /* ]] || { printf 'HOME must be an absolute path.\n' >&2; exit 1; }
  for parent in "$HOME" "$HOME/.local" "$HOME/.local/opt"; do
    if [[ -L "$parent" || ( -e "$parent" && ( ! -d "$parent" || ! -O "$parent" ) ) ]]; then
      printf 'Refusing an unsafe installation parent.\n' >&2
      exit 1
    fi
  done
  version_dir="$HOME/.local/opt/herdr-v0.9.0"
  if [[ -e "$version_dir" || -L "$version_dir" ]]; then
    printf 'Version directory already exists; stop and inspect it.\n' >&2
    exit 1
  fi
  mkdir -p -- "$HOME/.local/opt"
  mkdir -m 700 -- "$version_dir"
  cd -- "$version_dir"
  curl --fail --location --proto '=https' --proto-redir '=https' \
    --output herdr.download \
    "https://github.com/herdrdev/herdr/releases/download/v0.9.0/$asset"
  printf '%s  herdr.download\n' "$digest" | sha256sum -c -
  chmod 700 -- herdr.download
  mv -- herdr.download herdr
  ./herdr --version
  printf 'Herdr executable: %s/herdr\n' "$version_dir"
)
```

Continue only if the whole block succeeds and **0.9.0** appears. Keep the printed
**full executable path**: if Herdr is not in PATH, enter it when prepare asks.
**Stay on this Getting Started page and continue to step 2. No Herdr server,
Agent, snapshot or provider login is needed just to install Bridge.** On Windows,
return to PowerShell only for the Bridge command in step 4.

<a id="download-the-complete-package"></a>
## 2. Download the complete installation package

Download the complete installation ZIP
[**gpt-agent-bridge-v0.1.0-rc.7.zip**](https://github.com/HowAreAllWell/gpt-agent-bridge/releases/download/v0.1.0-rc.7/gpt-agent-bridge-v0.1.0-rc.7.zip)
from the [v0.1.0-rc.7 release page](https://github.com/HowAreAllWell/gpt-agent-bridge/releases/tag/v0.1.0-rc.7).
Use the full release ZIP; GitHub's **Source code (zip)** and **Code → Download ZIP**
are not installation packages.

Extract the **whole ZIP** to a folder you own. Keep its files together; the root
must contain `prepare`, `Start-Bridge.ps1`, `release-manifest.json` and
`Bridge-Skills.zip`. If `Bridge-Skills.zip` is missing, that download is not the
complete package for these steps; get the current complete package from the
release page.

<a id="2-prepare-your-tunnel-and-restricted-runtime-key-privately"></a>
## 3. Prepare your private Tunnel and runtime key

In [Platform Tunnel settings](https://platform.openai.com/settings/organization/tunnels),
select the intended organization, create your Tunnel and associate it with the
**ChatGPT workspace from step 1**. Keep its full Tunnel ID privately.
Creating/editing needs **Tunnels Read + Manage**; running/selecting the Tunnel
needs **Read + Use**. Ask your administrator if those options are unavailable.

In [API key settings](https://platform.openai.com/settings/organization/api-keys),
create a **Restricted runtime key with Tunnels Read + Use**, in that organization.
Do not use an Admin key or All permissions. Set an expiry suitable for your use;
keep track of it. Enter the ID and key only at the installer's **hidden local
terminal prompts**. Do not send them in Chat, attachments, screenshots or reports.
Check your account's applicable charges and quotas separately.

<details>
<summary>Example account screens (your labels and available controls may differ)</summary>

![Example Tunnel workspace association](assets/getting-started/platform-tunnel-workspace.png)
![Example key expiry control](assets/getting-started/runtime-key-expiration.png)
![Example Restricted key option](assets/getting-started/runtime-key-restricted.png)
![Example Tunnels permissions](assets/getting-started/runtime-key-tunnels.png)

</details>

<a id="3-start-preparation-and-confirm-the-exact-wsl2-distro"></a>
## 4. Prepare the local core — choose one route

<a id="native-ubuntu-desktop"></a>
### Native Ubuntu Desktop

In **Files**, open the extracted folder. Right-click its empty background and
choose **Open in Terminal**. If unavailable, open Terminal and enter `cd` followed
by the quoted full folder path copied from Files, for example:

```bash
cd "/full/path/to/the/extracted-folder"
./prepare
```

Replace the example path; run the command from the folder containing `prepare`.
Use your normal Linux user, **not `sudo ./prepare`**.

<a id="windows-and-wsl2"></a>
### Windows + WSL2

In **File Explorer**, open the extracted folder. Click its address bar, type
`powershell`, and press Enter to open PowerShell **in that folder**. Run:

```powershell
.\Start-Bridge.ps1 prepare
```

Choose the exact WSL2 distro that has your Linux Herdr 0.9.0. Its **default Linux
user** owns this installation; confirm the displayed distro/user choice. If WSL
asks for initial user creation or a reboot, finish that first. If Windows blocks
scripts, ask the administrator about the local policy; do not bypass it.
This command does not install a native Windows Bridge.

<a id="4-follow-the-one-local-preparation-through-its-handoffs"></a>
<a id="approve-services-then-enter-credentials-locally"></a>
### What you approve, and when local preparation is finished

Preparation asks you to trust the package, installs missing Python/venv/Git
prerequisites if you agree, creates a private application/Python environment,
and downloads the pinned Tunnel client. With your sudo approval it **installs,
enables for boot, and starts TWO Linux systemd services**:
`gpt-agent-bridge-autostart.service` and `gpt-agent-bridge-tunnel.service`.
The sudo password is your Linux password; the later hidden prompts take your
Tunnel ID and runtime key. Those credentials stay in protected local files.
Tunnel installation can first report `inactive` / `disabled`: that intermediate
stage comes before credential entry and start. Judge the final checks below.

Default preparation does **not** create or configure the Chrome reminder
extension, ask for a Windows extension folder, or ask for an App ID.
At normal completion, keep the two printed locations:

- **Skills upload:** select `Bridge-Skills.zip` directly in the package folder
  you extracted, for step 6. No hidden-folder navigation is needed.
- **Unchanged Web Principal Core:** the public instruction file for step 7.

`Local checks:` with `"bridge_mcp": "initialized_healthy"` means the **local**
Bridge answered. Herdr may be unavailable while closed. Successful local service
checks do not prove that ChatGPT or the four Skills work. After preparation ends
normally, you can close this terminal and continue in the browser.
If it stops, use [the troubleshooting section](#if-a-step-stops).

<a id="5-connect-the-tunnel-to-your-private-chatgpt-plugin"></a>
## 5. Add the connection in ChatGPT Web

1. In the same workspace, open **Plugins → + → Add custom MCP server**. Give your
   Bridge connection a recognizable name.
2. Choose **Connection: Tunnel**, then your own Tunnel. If an official Tunnel ID
   field appears, use it there; the runtime key does **not** belong in this form.
3. Change MCP authentication from the default OAuth option to **No authentication**.
   Bridge has no OAuth server; the private Tunnel permissions and protected local
   endpoint still apply. Review the risk notice, then choose **Create as a plugin**
   and **Install**, if those controls are offered.
4. Open an ordinary Chat in your intended ChatGPT Project, type `@`, select the
   Bridge plugin, and send:

   > Call only read-only bridge_health and show the actual tool result. Do not
   > register projects, change files or send tasks to Agents.

Continue only after a **successful, non-error tool result in this Web Chat**.
A plugin card, local `active` service or sentence saying “connected” is not enough.
Herdr readiness is separate. For a missing Tunnel, check the organization,
workspace association and Read + Use permissions; retain the local installation.

<details>
<summary>Example connection form</summary>

![Tunnel selected; default OAuth still needs changing](assets/getting-started/mcp-tunnel-form.png)
![Example No authentication selection](assets/getting-started/mcp-no-auth.png)

</details>

<a id="6-install-and-discover-all-four-native-skills"></a>
## 6. Install the four Skills

In the package folder you extracted, select **Bridge-Skills.zip**. Upload
only that file in an ordinary Web Chat with **@Plugin Creator**. Windows users
select it in their extracted Windows folder; there is no WSL hidden path to find.
This is a materials ZIP containing four canonical `skills/<name>/SKILL.md` files
and `LICENSE`, not a complete plugin package or a new MCP connection:

| Workflow in the ZIP | Purpose |
| --- | --- |
| `project-onboarding` | Connect an existing Git project and offer notes separately |
| `project-resume` | Recover project context in a new Chat |
| `handoff-preparation` | Save decisions before leaving |
| `team-deliberation` | Organize independent Agent work |

Replace the bracketed placeholder with the display name of your personal Bridge plugin whose health check succeeded in step 5. After the ZIP upload finishes, send:

> Use this ZIP to update my existing personal Bridge plugin
> 【display name of my personal Bridge plugin whose health check succeeded】 and
> install its four native Skills: project-onboarding, project-resume,
> handoff-preparation and team-deliberation. Preserve the attached Skill
> instructions and LICENSE in full, and keep that plugin's existing MCP
> connection and name unchanged. Do not create another plugin or MCP connection,
> do not ask me for keys, and do not perform project operations. If you cannot
> identify that plugin uniquely, ask me; do not guess. When finished, briefly
> list the plugin name and the four Skill names.

When Creator finishes, save/finish/install only using controls actually offered.
Open the plugin list and refresh it if that control exists; if not, close and
reopen the list, or refresh the page if needed. Then open a **new ordinary
Chat in the intended Project**, `@` the **same Bridge plugin**, and send:

> Check the connection: call bridge_health and show the actual result.
> Do not register a project, change files or send Agent tasks.

A successful health result confirms the connection. Then confirm the four
installed Skill entries — project-onboarding, project-resume,
handoff-preparation and team-deliberation — in the plugin's Skill list. With
those names and the health result, continue with step 7. No manual App ID or
config editing is needed here.

<details>
<summary>Example installed-Skills screen</summary>

![Example settings, not a discovery result](assets/getting-started/plugin-installed-skills.png)

</details>

<a id="7-put-the-public-core-in-project-instructions"></a>
## 7. Save the base instructions and connect your project once

Open the printed Core file, or [Web Principal Core](../templates/WEB-PRINCIPAL-CORE.md).
Copy its **complete text** into the ChatGPT Project's **Instructions**, retaining
relevant existing rules. Finish saving and reopen to check it persisted. This is
a Project setting, not a one-off Chat message or another Skill attachment.

![Example Project Instructions control](assets/getting-started/project-instructions.png)

<a id="8-connect-your-existing-git-repository-and-merge-its-binding"></a>
In that Project Chat, replace the path and short project reference below:

> Use project-onboarding to connect my existing repository /absolute/linux/repo
> as MY_PROJECT. Only register it and return its Project Binding; do not initialize
> notes, change project files or send Agent tasks.

Review the returned **Project Binding** and save it beside Core and existing
Project rules. Do this once per project. When continuity explicitly reports
`manifest_missing`, onboarding explains “the repository is connected, but Bridge
has not recognized a usable project continuity configuration” and asks once
**“Set up project notes?”** Missing does not prove that notes never existed or
permit overwriting a noncanonical directory. A “no” or no
answer leaves notes unwritten; simple authorized file reading still works.

If you want notes, reply separately:

> Yes, create project notes for MY_PROJECT. First confirm with me the goal,
> current progress and confirmed decisions, and use the project's real existing
> rule files. Do not invent rules or overwrite existing notes.

Without existing rule files, initialization must stop and explain the prerequisite.
An invalid existing notes directory or unknown write outcome needs inspection,
not forced initialization. Only verified routing and published content establish
continuity readiness; registration and a file read alone do not.

<a id="10-begin-daily-use-with-a-bounded-read-only-check"></a>
## 8. Read one file, then begin normal use

Choose a known non-secret file in that repository and replace the example below:

> In project MY_PROJECT, read only README.md and tell me what it says. Do not edit
> files, run commands, commit or send work to Agents.

Verify the project and actual file result. This file read works before any
project notes exist; the step 7 notes setup stays optional until you want it.
To change Chats after notes are ready, ask
“Use handoff-preparation for MY_PROJECT; save the authorized decision and reasons.”
In the new Project Chat, `@` the same plugin and ask “Use project-resume for
MY_PROJECT; read the notes and explain the next permitted step.” See
[continuity](PROJECT-CONTINUITY.md#before-changing-chats) for the permission and
unknown-outcome boundaries. You can use this Web conversation
without Chrome reminders. For delegation later, open Herdr yourself and start
your authorized Agents in that repository; ask for fresh context before choosing
an available Agent. State the task and allowed changes. Unknown delivery is not
permission to resend a task. Daily use does not require running prepare again.

<a id="9-load-the-private-extension-and-bind-this-exact-chat"></a>
<a id="keep-the-early-private-extension-path"></a>
## Optional, after success: Chrome completion reminders

From the extracted package folder, use **only your platform's command**:

```bash
./prepare reminders
```

```powershell
.\Start-Bridge.ps1 reminders
```

This action needs a completed, matching core installation with the new
`reminders` action. Approve the optional project/completion-metadata access only if you want it.
Fresh Windows setup asks for a new private Windows-local NTFS folder; an existing
reminder installation keeps its recorded identity and loading folder.

Keep the **printed private extension path and expected extension ID**. In Chrome,
open `chrome://extensions`, enable Developer mode, choose **Load unpacked**, and
select that exact folder (Windows: the final Windows path, not a Linux staging
folder). Check the extension ID. Do not load the source template or move/rebuild
an existing extension to make a warning disappear.

Open the intended Project Chat, select that exact tab in the extension, and
explicitly **bind/enable** it before later delegation. Each Chat needs its own
choice. A reminder does not prove task success or report review. Existing drafts
are preserved; an appended reminder is not sent for you. A failed or uncertain
send must not be replayed. Non-English ChatGPT UI may block primary-control
recognition. `PRIMARY_UNKNOWN_OR_AMBIGUOUS` can also have other causes: check the
selected Chat and its visible controls first; temporarily switching ChatGPT to
English can help isolate a language issue.
See [reminder limits](LIFECYCLE-RESTART-CONTRACT.md#chrome-notification-authority-and-recovery).

<a id="if-a-step-stops"></a>
## If a step stops

| Where it stops | What to do |
| --- | --- |
| Account controls absent | Ask the workspace administrator. Local reinstall cannot enable Web MCP or Skills access. |
| Preparation reports a path/permission or service error | Keep the exact non-secret error code, stage and path for review. Fix only the identified owner-controlled path after diagnosis; do not change permissions across your workspace or replace generated files. |
| Local checks pass, Web call fails | Check the same workspace/Tunnel association, key expiry and permissions. Local service activity is not remote authentication. |
| Tools work, Skills do not | Keep the working connection. Check Creator capability/access and installed Skill entries; reinstalling Tunnel cannot fix Skill discovery. |
| Optional reminders stop | Keep the recorded folder, pairing and drafts. Core use does not require reminders; do not reset identity or retry an uncertain send. |

For **read-only service inspection**, use [the autostart page](AUTOSTART.md#already-completed-prepare-start-here).
Keep credentials private; never publish raw logs or secret-bearing URLs. Advanced manual foreground setup
is in [Quickstart](QUICKSTART.md), not another step after normal preparation.
