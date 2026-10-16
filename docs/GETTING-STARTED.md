# Prepare Bridge and collaborate from ordinary ChatGPT Web

This release prepares **one Bridge, one Secure MCP Tunnel companion and one browser
extension for multiple local projects**. Codex is not required to install Bridge.
Herdr and compatible Agent CLIs are user-managed prerequisites across providers.
Bridge discovers Agents you have already started; it does not manage their environment. This is a
Linux/systemd or WSL2 candidate, tested with isolated source fixtures; a fresh
Windows machine, your account permissions and real Web delivery still need the
checks below. No Work Chat, API Principal or desktop replacement is required.

## 1. Get and trust the complete directory

Review the source and LICENSE before executing code or granting system permissions.
Choose one acquisition path:

- **Git checkout:** install Git on the machine/shell where you clone, then run:

  ```sh
  git clone https://github.com/HowAreAllWell/gpt-agent-bridge.git
  cd gpt-agent-bridge
  ```

  Both entries accept this complete, clean checkout and automatically build their
  allowlisted release outside it. A dirty checkout stops for review.
- **Prepared Release ZIP:** if a maintainer-published asset is available on
  [Releases](https://github.com/HowAreAllWell/gpt-agent-bridge/releases), extract it
  and enter the directory containing `prepare`, `Start-Bridge.ps1` and
  `release-manifest.json`. It also contains `src/`, `scripts/`, `systemd/`,
  `browser-extension/`, `templates/` and all four `skills/*/SKILL.md` files.
  The manifest checks bytes; it is not an independent publisher signature.

GitHub's **Code → Download ZIP** and automatic **Source code (zip)** archives are
not prepared Release ZIPs: they lack both the generated manifest and Git metadata.
Do not run preparation from those archives; use the Git checkout path when no
prepared asset is published. A pip wheel alone is not the complete distribution.
You do not need to assemble files, edit JSON or manually build a distribution.
No working App binding or connection token ships in either supported source.

From the checkout or extracted prepared directory, run once:

Linux/WSL:
```sh
./prepare
```

Windows PowerShell:
```powershell
.\Start-Bridge.ps1
```

Do not disable machine execution policy globally. If Windows blocks the downloaded
file, review its Properties / Unblock or ask your administrator under your normal
trust policy.

The Windows entry lists verified **WSL2** distributions before preparing files.
With one installed distro, confirm its displayed name with Enter (or decline with
`n`). With several, enter the exact name of one listed WSL2 distro. WSL1, an unknown
name, an ambiguous version or an unavailable selected distro stops preparation.
Every later WSL call uses that same selection and its default Linux user; the entry
does not change the system default distro, WSL version or systemd settings, or restart WSL.
With no distro it offers official Ubuntu installation, with Windows elevation;
complete any reboot and first Linux user creation, then run the same entry again.
It can install Python 3, venv and Git via apt with your consent, then copies only
checked release files into that Linux user's home. Re-enter using the same distro
and Linux user to retain the same private installation.
Non-apt distributions need their own package manager for these three prerequisites.
See [Microsoft's WSL installation instructions](https://learn.microsoft.com/en-us/windows/wsl/install).
The existing [WSL logon adapter](AUTOSTART.md) remains optional; preparation does
not claim a suspended/shutdown WSL instance stays running after Windows logout.

## 2. Let the entry prepare software

Approve the displayed scope only after reviewing the release. It uses
`~/.local/share/gpt-agent-bridge/` for its private product, Python environment,
downloads and handoff files. No work-project selection belongs in installation. A small Git
root there serves only as the server bootstrap workspace, not as a registered
user work project. Your repositories are not moved.

The entry verifies release files and installs Bridge's Python dependencies into
its own venv. Herdr is an external host you provide, not an installed component of
Bridge. It detects an existing executable on PATH or from `BRIDGE_HERDR_BIN`, or
asks for its absolute Linux path, and checks the supported CLI version (0.9.0).
See [Herdr compatibility and prerequisites](HERDR-COMPATIBILITY.md). It does not
download, upgrade, open or take over Herdr, and does not install, log into, launch
or restore any provider's Agent. Keep your existing provider/model choice.
**Herdr's session may be closed and no Agent needs to exist during installation.**

The only pinned external download in this entry is the necessary Secure MCP Tunnel
runtime 0.0.16, verified against its official SHA256 before publishing. Pins come
from [OpenAI Tunnel release metadata](https://github.com/openai/tunnel-client/releases/tag/v0.0.16).
Matching finished files are reused; unknown files are not replaced. Bridge and
Tunnel run in the background after first setup. No daily preparation command is
needed, and their service health does not require a live Herdr session.

Sudo is requested for the existing strict Bridge and Tunnel system installers.
They validate ownership, their installed manifests and service activation before
continuing missing steps. Port **8765** must be free for a new installation; no
other listener or service is killed. A different/legacy running deployment is
refused for explicit operator review, not silently migrated. Supported paths are
absolute Linux paths accepted by those installers (not `/mnt`, symlink paths or
paths with spaces). Missing systemd/unsupported account layout is a concrete
prerequisite failure, not permission to weaken the install checks.

Repeat/interruption: re-enter the same release/path. Matching finished objects are
observed and reused; enable/start are only attempted from confirmed disabled/inactive
states. Failed/transitional/changed installations stop. An interrupted download is
never used before its checksum passes. No journal entry is treated as proof that
an uncertain mutation failed. Services' original status tools are the diagnostic
fallback in [Bridge autostart](BRIDGE-AUTOSTART.md) and [Tunnel autostart](TUNNEL-AUTOSTART.md).
An owned, interrupted venv is completed in place on re-entry. A pre-existing
unmarked partial venv is refused for inspection, not deleted or guessed to be ours.
All preparation entry actions share `~/.local/share/gpt-agent-bridge/prepare.lock`.
Other same-owner editors must also hold that flock before editing generated files;
read/compare/rename detects observed conflicts but is **not a global atomic CAS**.
An external editor ignoring this protocol can still write in the last comparison
window. Do not edit generated configuration concurrently. No automatic upgrade
daemon or forced reinstall is installed.

For software status or explicit recovery (not daily use), re-enter from the same
extracted directory: Linux `./prepare status` or `./prepare`; Windows
`.\Start-Bridge.ps1 status` or `.\Start-Bridge.ps1`. No PATH setup is needed.
The installer has no project registration command. Repository connection belongs
to the existing project-onboarding Skill in ordinary Web.

## 3. Complete the account and permission steps locally

The entry pauses for the actions only you/your administrator can authorize:

| Step | Official action and fields | Local handoff, success and recovery |
| --- | --- | --- |
| Tunnel | Open [Platform tunnel settings](https://platform.openai.com/settings/organization/tunnels). Reuse a suitable Tunnel or create one; associate the intended ChatGPT workspace as well as the owning Platform organization. | Obtain its `tunnel_id`. Creating/editing needs **Tunnels Read + Manage**; running/selecting needs **Read + Use**. A missing tunnel in ChatGPT usually needs association/role correction, not another Bridge installation. |
| Runtime key | In the owning Platform organization open [Runtime API keys](https://platform.openai.com/settings/organization/api-keys), create a **Restricted** key and select **Tunnels Read + Use**. Never select **All** or use an Admin API key for the daemon. This is not a ChatGPT password, subscription token, browser cookie, Bridge path token or notification token. | Enter Tunnel ID/key only into the local hidden installer prompts. They go to the owner-only Tunnel credential file, never chat, Core, CLI arguments or release files. If the role or selector is missing, ask the organization owner/RBAC administrator through [Organization roles](https://platform.openai.com/settings/organization/people/roles) to grant Read + Use on this Tunnel. Runtime, management/Admin and model API uses are distinct; no model-API Principal is needed. |
| Bridge MCP | Go to [ChatGPT Plugins](https://chatgpt.com/plugins), plus → **Add custom MCP server**. Enter a name/description, choose **Connection: Tunnel**, select the same tunnel or enter its ID. For this private Tunnel connection choose **No authentication** (Bridge has no OAuth server; Tunnel roles and its local secret endpoint remain in force), review the warning, **I understand and want to continue** → **Create as a plugin**. | The local Tunnel already obtains the secret loopback Bridge endpoint from its protected installer contract; you do not paste it in chat. This Bridge does not implement public OAuth discovery. Review discovered tools, install/select the private plugin in a new ordinary Chat via `@`, then request one read-only `bridge_health`. Local readiness alone is not Web access. |
| Native Skills | In an ordinary Web Chat, type `@`, select **Plugin Creator**, attach the prepared four named Markdown files and LICENSE; select your existing Bridge App. Review four separate native Skills and finish the controls actually offered. | The entry prints `Creator-attachments/`. Use the brief below. If you already have an official native own-App ID, optional hidden local input produces a deterministic full native plugin zip and local marketplace. A `plugin_asdk_app_…` browser URL is not that App ID; do not transform its prefix. Missing native packaging/permissions is an account checkpoint, not a reason to switch to Work. |

The runtime key is passed privately as `CONTROL_PLANE_API_KEY`. `OPENAI_ADMIN_KEY`
is only for management API/CLI operations, not this daemon. The key's principal must
have Read + Use; a key's selected permissions do not grant its owner a missing role.
See the pinned runtime's [official permissions guide](https://github.com/openai/tunnel-client/blob/v0.0.16/docs/permissions.md).
After provisioning, the owned Tunnel status must report readiness and the ordinary
Web plugin must successfully call read-only `bridge_health`; a saved file alone
proves neither. For 403, check the key's organization, principal's Tunnel role and
Restricted Read + Use permissions. For a missing picker entry, check the target
ChatGPT workspace association and the plugin operator's Use permission. For an
expired/wrong key, issue a correctly scoped replacement at Runtime API keys.
Never paste either key in Chat, Core, logs or issue reports.

To replace a saved wrong key, re-enter `./prepare credentials` (Windows:
`.\Start-Bridge.ps1 credentials`). Confirm replacement and enter ID/key in the
hidden local prompts. The entry validates the owned installation and old file,
refuses known Admin key syntax, and replaces the owner-only file under the preparation
lock. It does not infer RBAC from the key string and initially leaves services unchanged. The entry then separately asks whether
to activate it with sudo: it observes the owned Tunnel state, stops only that
service, confirms inactive, then starts it. Declining leaves activation deferred.
Use [Tunnel lifecycle](TUNNEL-AUTOSTART.md#provision-privately-then-explicitly-enable-and-start)
for the read-only status command, then retry the read-only Web check. Do not repeat a lifecycle
mutation with unknown outcome. Bridge itself need not restart. Credential replacement
and lifecycle transitions are covered by synthetic tests, not a live key change.

These steps follow the current [Secure MCP Tunnel](https://developers.openai.com/api/docs/guides/secure-mcp-tunnels),
[connect a plugin](https://developers.openai.com/plugins/deploy/connect-chatgpt),
[custom MCP authentication options](https://developers.openai.com/api/docs/guides/custom-mcp-server) and
[Plugin Creator](https://learn.chatgpt.com/docs/build-plugins) documentation.
The latter explicitly describes Chat or Work, while some screenshots show Work;
only your **ordinary Web Chat** discovery counts here. Use plugins permission,
Creator availability, custom MCP access and Tunnel RBAC are separate gates. If one
is absent, ask the relevant administrator and resume at that gate. Do not install
Codex as a substitute for missing Web access. Public plugin submission cannot use
this private Tunnel route; no public endpoint or submission is created.

Creator brief (no credentials):

> Create a private GPT-Agent Bridge plugin with four separate native Skills named
> project-onboarding, project-resume, handoff-preparation and team-deliberation.
> Preserve the four attached reviewed texts and LICENSE. Select my existing working
> Bridge App through the host's eligible App picker. Do not recreate the MCP connection,
> alter permissions, collect credentials, publish/share, or turn the Skills into only
> reference attachments. Show the four procedures and App selection for review; stop
> if exact native packaging is unavailable.

## 4. Load one extension, then choose projects and Chats

Use **Chrome 120 or newer**. The notification adapter is presently verified only
against the **English ChatGPT Web / Project Chat DOM**. Other languages or changed
page structures may safely wait or decline; multilingual delivery is not guaranteed.

As soon as the private extension files are prepared or verified, **before** the
Bridge/Tunnel service and account steps, the entry prints:

- `Private extension Linux path:` — the actual loading directory, normally
  `<Linux account home>/.local/share/gpt-agent-bridge/extension/`.
- `Expected extension ID:` — the identity to compare with Chrome.
- On WSL, `WSL distro:` and `Private extension Windows path (copy into Chrome Load unpacked):`,
  followed by a complete `\\wsl.localhost\…` path on its own line. Copy that entire
  line; do not substitute a Windows username or guess the distro/home.

The path comes from the verified extension result, including a previously recorded
or explicitly adopted directory. The Linux account home need not equal `$HOME`.
The Windows path is converted and checked back against the actual Linux path.
If it cannot be verified, the entry says `Windows extension path: unavailable/unverified`
and stops before service setup. Keep the prepared files; check the selected distro
and `wslpath`, then re-enter the same release/distro/user. Do not create a second
extension, change its key or delete its receipt to get past the failure.

In Chrome open `chrome://extensions`, enable **Developer mode**, choose **Load
unpacked**, and select the printed **private prepared extension folder**. On Windows
use the complete printed Windows path; on Linux use the printed Linux path.
Do not select the public checkout, ZIP, staging directory or
`product/browser-extension/extension` template. Compare Chrome's displayed ID with
the expected ID. See [Chrome's unpacked installation guide](https://developer.chrome.com/docs/extensions/get-started/tutorial/hello-world#load-unpacked)
and [manifest key identity](https://developer.chrome.com/docs/extensions/reference/manifest/key).
Actual UNC loading and the permission prompts remain machine-specific acceptance
checks, not outcomes established by path conversion. Keep the directory private;
never share its `connection.js`. An ID mismatch stops local feed access.

“Extension files prepared” does not mean Chrome has loaded them, services have
started, or Chat is connected. Later local health checks cover Bridge/Tunnel;
the read-only Web MCP check in step 3 separately establishes Chat access. If a later
step fails, the printed extension paths remain useful, but are not a success receipt
for that failed step. Re-entry preserves a recognized receipt's path/identity/token
and reuses matching files; unknown changed files still stop for inspection.

For an existing 0.3.4 installation use `prepare --existing-extension /original/private/load/path`
only after authorizing that exact update. It preserves its original ID/key (including
an absent key), path and token, saves original files privately, and preserves original browser records. The new worker imports records unchanged
once into transactional extension storage; originals remain as migration evidence. Unsafe permissions or unknown changes stop. Reload is the user's
Chrome action; do not uninstall/reinstall or clear storage to bypass an unknown intent.
This preparation flow is not a general cross-version updater: changed installed
files may be refused and preserved for operator review. Do not delete them or
reset browser history to force an upgrade.

Software preparation ends after health checks and the software/Skills handoff.
It needs no repository, running Herdr session or Agent. The unchanged Core is
printed as a file path; four unchanged Skills and account guidance remain available.

In your ChatGPT Project, open **Project Instructions**, review the printed
Principal Core and save its text there, preserving your existing user instructions.
Then open an ordinary **Chat inside that Project** and invoke the
**project-onboarding Skill** to connect your chosen existing local Git repository.
Principal confirms the authorized root/ref, uses `project_register` only when
needed, checks overview/context and returns the Project Binding (Host Binding).
Review and append that returned Binding to the **same Project Instructions**,
alongside the Core; save without replacing unrelated instructions. Core and Binding
are not Creator Skill attachments, a one-off Chat message, or the extension's
connection configuration. Connection-only stops there; fresh continuity
initialization needs a separate request. ChatGPT Project and local project are
distinct identities; their names do not establish a mapping.

During installation, explicitly authorize the single installed extension to read
registered project refs, canonical roots and completion metadata, including future
authorized registrations. This loopback capability cannot fetch report text or
invoke tasks. The live registry is its only catalog: a later Skill registration
appears without local list input, a sync command, restart or another installation.
Registration alone does not authorize a task or a notification destination.

Old single-project/version-2 notification configurations remain restricted to their
original pinned rows until an explicitly authorized software preparation expands
metadata discovery. That migration preserves token, installation path/ID, old
configuration bytes and legacy root proof; extension histories/unknown intents are
not rewritten. A changed or unverified root cannot inherit an enabled destination.
No old Binding files or browser history are removed.

Open the exact existing ordinary Chat destination. In the extension choose the
local project, tick automatic notification authorization, then use **绑定当前 Chat 并启用**.
One local project has one destination;
no broadcast or recent-tab guess.
Multiple local projects can share a Chat or select different Chats. Keep one ordinary
non-private tab for that exact full route open. Check the selected project/root and enabled binding in the popup before first
collaboration. If unavailable, inspect the Bridge registration and local connection;
a binding observation is not evidence of delivery.
**Bind before delegation:** older completions are not backfilled on first enable.

## 5. Daily collaboration: user-managed Agents, independent Web entry

After the one-time software setup and each project's first explicit Chat association,
there is no daily preparation step. Open Herdr yourself, change
to the intended authorized Git repository, then launch and log into your chosen
compatible Agent as usual. Open ordinary ChatGPT Web before, after or alongside
that work; neither side depends on the other's startup order. These third-party
environments, accounts, upgrades and recovery remain yours.

Bridge stays running when Herdr is closed or there are no Agents. `bridge_health`
continues to distinguish Bridge responsiveness from Herdr availability. In Web,
fresh `context(project_ref)` discovers existing eligible Agents at the authorized
canonical root. If none have been started, start them yourself and request fresh
context: no Bridge restart, new registration or repeat preparation is needed.
An incomplete/error discovery is unknown, not proof that no Agents exist. Check
your selected Herdr executable/session and request a fresh observation; Bridge
never creates a pane/workspace/Agent to resolve that uncertainty. CLI compatibility
alone does not prove that the running session or a discovered Agent is eligible.

In the intended ordinary Web Chat, verify Bridge tools **and all four native Skills**.
State a real bounded task and its allowed changes. Continuity initialization via
project-onboarding is optional and requires its own project authority; it is not
a mandatory demonstration or first-task prerequisite. Principal discovers actual
handles, delegates, continues useful work and reads each complete `work_report`,
following every page with its full SHA pin. The notification only supplies source
project and original Work refs; it is not report text, task success or acknowledgement.
If no real task is authorized, stop here; setup sends no smoke Work or test message.

An unknown reminder is never replayed, even after re-entry, disabling or adding
another project. Busy/draft/IME/attachments/routes still gate sending. Project A's
blocked feed or page does not halt independent B. Full rules and migration limits:
[extension README](../browser-extension/README.zh-CN.md).

Keep evidence levels separate: distribution/source regressions; real local install;
Web MCP call; native four-Skill discovery; actual reminder plus full report reading.
Passing an earlier level does not certify a later one. No fresh account, second
Windows machine or real notification delivery is claimed by candidate tests.
