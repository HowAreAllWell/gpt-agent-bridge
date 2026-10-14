# Prepare Bridge and collaborate from ordinary ChatGPT Web

This release prepares **one Bridge, one Secure MCP Tunnel companion and one browser
extension for multiple local projects**. Codex is not required to install Bridge.
Herdr and compatible Agent CLIs are user-managed prerequisites across providers.
Bridge discovers Agents you have already started; it does not manage their environment. This is a
Linux/systemd or WSL2 candidate, tested with isolated source fixtures; a fresh
Windows machine, your account permissions and real Web delivery still need the
checks below. No Work Chat, API Principal or desktop replacement is required.

## 1. Get and trust the complete directory

Obtain a complete release from a source you trust and extract it. Review its
LICENSE and release identity before executing code or granting sudo. The directory
must contain `prepare`, `Start-Bridge.ps1`, `release-manifest.json`, `src/`, `scripts/`,
`systemd/`, `browser-extension/`, `templates/` and all four `skills/*/SKILL.md` files.
**A pip wheel alone is not this distribution.** The manifest detects missing or
changed bytes; it is not an independent publisher signature. Maintainers build the
allowlisted directory with `python3 scripts/build-distribution.py /absolute/new/output`
from the reviewed Git candidate. No private working App binding or connection token
is included. Public plugin/store submission is not performed by this flow.

A clean complete public Git checkout is also accepted by both entries: they automatically
build their allowlisted release outside the checkout before installing. A dirty
checkout stops for review; it is not silently treated as a published release.

On Linux/WSL, run `./prepare` once from the complete directory. On Windows, run the
reviewed `.\Start-Bridge.ps1` in your own PowerShell. Do not disable machine execution
policy globally. If Windows blocks the downloaded file, review its Properties /
Unblock or ask your administrator under your normal trust policy.

The Windows entry detects and uses the current default WSL distro. With no distro
it offers official Ubuntu installation, with Windows elevation; complete any reboot
and first Linux user creation, then run the same entry again. It does not change
the default distro or existing sessions. It can install Python 3, venv and Git via
apt with your consent, then copies only checked release files into your Linux home.
Non-apt distributions need their own package manager for these three prerequisites.
See [Microsoft's WSL installation instructions](https://learn.microsoft.com/en-us/windows/wsl/install).
The existing [WSL logon adapter](AUTOSTART.md) remains optional; preparation does
not claim a suspended/shutdown WSL instance stays running after Windows logout.

## 2. Let the entry prepare software

Approve the displayed scope only after reviewing the release. It uses
`~/.local/share/gpt-agent-bridge/` for its private product, Python environment,
downloads and handoff files. No work-project selection is needed yet. A small Git
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

For first association, another project, or explicit recovery only (not daily use),
re-enter from the same extracted directory: Linux `./prepare project` or
`./prepare status`; Windows `.\Start-Bridge.ps1 project` or
`.\Start-Bridge.ps1 status`. No PATH setup is needed. Windows forwards the action
to the installed product after checking the source; checkout input must be clean.

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

The entry prints the private extension loading directory and expected stable ID.
In Chrome open `chrome://extensions`, enable Developer mode, **Load unpacked**, and
select that directory. See [Chrome's official unpacked installation guide](https://developer.chrome.com/docs/extensions/get-started/tutorial/hello-world#load-unpacked)
and [manifest key identity](https://developer.chrome.com/docs/extensions/reference/manifest/key).
On Windows use the WSL filesystem location of the printed Linux directory (Explorer's
Linux node / `\\wsl.localhost\<distro>\…`). Actual UNC loading and the current Chrome
permission prompts must be checked on that machine. Do not copy the extension to a
public folder or expose `connection.js`. Expected ID must match Chrome's displayed ID;
a mismatch stops local feed access, rather than weakening authorization.

For an existing 0.3.4 installation use `prepare --existing-extension /original/private/load/path`
only after authorizing that exact update. It preserves its original ID/key (including
an absent key), path and token, saves original files privately, and preserves original browser records. The new worker imports records unchanged
once into transactional extension storage; originals remain as migration evidence. Unsafe permissions or unknown changes stop. Reload is the user's
Chrome action; do not uninstall/reinstall or clear storage to bypass an unknown intent.
This candidate has not been deployed over the maintainer's current installation.

After software preparation, choose an existing local Git root at the prompt and
confirm its authorization. `prepare project` later adds another root without
reinstalling software. A deterministic opaque ref is generated, registered through
Bridge and checked against the canonical root; the program generates Binding and
notification eligibility from that result. A matching persisted registration is
rechecked through read-only context instead of writing registration again. Canonical
root and ref are rechecked after Web handoff; conflicting
or uncertain mapping stops preparation.

Select the local projects for this Web Project by their displayed numbers. The
entry assembles one complete `Project-Instructions-<digest>.txt` with unchanged
Core once and all selected Binding entries. Review that file. In the selected ChatGPT
Project's menu, open its instructions editor and review/save Project instructions
using the control actually offered to your account ([official Projects guide](https://learn.chatgpt.com/docs/projects)).
When adding another local root to the same Web Project, select its existing
authorized roots together with the new one; the program does the text assembly.
Retain any existing user-authored instructions in the Web editor; preparation never
reads or replaces them. Only review/save in the Web UI remains manual. Never paste credentials or raw runtime state.
ChatGPT Project and local project are distinct identities.

Open the exact existing ordinary Chat destination. In the extension choose the
local project, tick automatic notification authorization, then **bind current Chat
and enable**. One local project has one destination; no broadcast or recent-tab guess.
Multiple local projects can share a Chat or select different Chats. Keep one ordinary
non-private tab for that exact full route open. The entry checks a recent extension
binding observation once before first collaboration. If absent, inspect popup/local
connectivity and re-enter; that observation is not evidence of message delivery.
**Bind before delegation:** older completions are not backfilled on first enable.

## 5. Daily collaboration: user-managed Agents, independent Web entry

After the one-time software setup and each project's first explicit Chat association,
there is no daily `prepare` or `prepare project` step. Open Herdr yourself, change
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
