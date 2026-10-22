# Developer quickstart

[English](QUICKSTART.md) | [简体中文](QUICKSTART.zh-CN.md)

**Installing Bridge for the first time?** Follow [Getting started](GETTING-STARTED.md),
which has separate **native Ubuntu Desktop** and **Windows + WSL2** paths.
You do not need this page after completing that guide.

This page is the **advanced, manual foreground route**: run Bridge in one terminal
and, for Web access, a Tunnel client in a second terminal. Closing either process
breaks that connection. Choose it to inspect the source setup or troubleshoot,
not as another installation step.

**Already completed `./prepare`?** That command creates its own application copy
and private Python environment, then installs, enables and starts **both**
Bridge and Tunnel services on supported Linux with systemd. It is an installer,
not just a prerequisite check. Do not start the foreground copies below alongside
those services. Chrome reminders are optional later setup in [Getting started](GETTING-STARTED.md#9-load-the-private-extension-and-bind-this-exact-chat),
not part of default preparation. For service management, read [Autostart](AUTOSTART.md).

### Choose your terminal

| Your machine | Where to run this guide |
| --- | --- |
| **Ubuntu Desktop, installed directly** | Open **Terminal**. Use Bash as your normal Linux user, with files under your home folder. Skip every Windows/WSL subsection; no WSL or PowerShell is needed. |
| **Windows + WSL2 Ubuntu** | First follow [Windows and WSL2](#windows-and-wsl2). Open the selected Ubuntu distribution as your Linux user; run the Bash blocks there. Use PowerShell only for blocks labelled PowerShell. |
| **Ubuntu Server / no desktop** | Advanced only: run Bash on that server. Bridge, Herdr and the Tunnel client must share that Linux environment. A remote ChatGPT browser can use the Tunnel, but its local extension cannot be assumed to reach the server's loopback notification feed. Browser reminders need separate validation. |

The commands require Git, **Python 3.10+ with venv**, Bash and GNU coreutils.
A venv is a private Python package environment; here it is the `.venv` folder in
your source checkout (the folder created by Git clone). Bridge does not install
Herdr, an Agent CLI or its provider login. Windows-native/macOS-native Bridge and
WSL1 are outside this guide.

### Pick one route before starting

- **Normal installation:** [Getting started](GETTING-STARTED.md); stop using this page.
- **Manual local check:** steps 1–4 below. This checks your machine, not ChatGPT.
- **Manual Web connection:** steps 1–2, [Tunnel preparation steps 1–3](#foreground-secure-mcp-tunnel),
  then step 3 below and [combined step 4](#combined-step-4). **Skip standalone step 4**:
  it deletes the one-use private token handoff needed by the combined block.
- **Manual services instead of foreground:** after steps 1–2, use
  [Autostart](AUTOSTART.md). Do not also launch the foreground processes.

The Web target is ordinary **ChatGPT Web Project Chat**. Work or local Codex
success is not that check; this choice does not enforce Web-only visibility.

## 1. Prepare Herdr and an existing Agent

You need Git, Python 3.10+ with `venv` support, and Herdr on the Bridge process's
`PATH`, or selected with an absolute `BRIDGE_HERDR_BIN` before Bridge starts.
**The bundled core preparation requires Herdr v0.9.0**. The maintainer's existing
working setup uses it; v0.9.3 is reported incompatible in that setup. First follow the
[Herdr compatibility guide](#herdr-compatibility-and-version-selection) to check an existing install
or choose a separate, checksum-verified v0.9.0 binary. Do not reinstall a usable
0.9.0 setup. The generic official installer tracks latest and does not pin this
version. Herdr is a separate prerequisite, not a Python requirement.

For the first-use demo, clone the Bridge source in Step 2 and
[prepare its independent demo Git root](#bootstrap-your-own-disposable-git-repository)
before Agent launch or registration. An initial demo commit is optional.
[The optional Herdr/Codex demo](#optional-demo-agent-with-herdr)
explains how to install/sign in and launch in an observed idle shell pane.
Use the Bridge code checkout for the server/client steps, the demo root for its
Agent and project_register; keep those roots distinct.

For delegation (not Bridge installation or health), have Herdr running with real,
already launched Herdr-managed coding Agents in the
Git checkout you intend to use. Choose the provider/model and make sure its quota
is available. Bridge does not create or launch Agents for you. Check the CLI and
existing session with these read-only commands. In **Ubuntu Terminal** or your
selected **WSL Ubuntu Bash**, use your normal user; the current folder does not
matter for these three observations:

```sh
command -v herdr
herdr --version
herdr api snapshot
```

**Check the result:** the first command prints the Linux executable path, the
second should report `0.9.0`, and the snapshot must succeed. If the executable is
missing or has another version, use the compatibility section linked above; do
not install a random latest version. A failed snapshot means Herdr is not yet a
usable session: resolve that in Herdr before delegation. Do not share raw output.

Before delegating, the snapshot must succeed and show the intended existing Agents.
Bridge and its Web tools may start first; no daily prepare or restart is needed
when you later open Herdr and start an Agent. A CLI found on
`PATH` alone does not establish a usable session or an eligible project Agent.
Keep session output private if it contains local paths or terminal information.

## 2. Clone and install direct dependencies

In **Ubuntu Terminal / WSL Ubuntu Bash**, start in your Linux home folder
(`cd ~`), not a Windows drive or another Bridge checkout. The block below creates
a new `gpt-agent-bridge` folder, enters it, creates `.venv`, and installs the
Python package there. If that folder already exists, stop and inspect it; do not
clone over it. You may substitute your own fork's URL.

This is **source clone + manual pip installation**, not the bundled installer.
It does not create the complete installation ZIP, configure Chrome, install
services, connect ChatGPT or install the four Skills. Those are separate steps
in [Getting started](GETTING-STARTED.md). Do not switch to `./prepare` midway
expecting it to leave this foreground setup untouched.

```sh
git clone https://github.com/HowAreAllWell/gpt-agent-bridge.git
cd gpt-agent-bridge
python3 --version
python3 -m venv .venv
.venv/bin/python -m pip install -e .
```

**Check before continuing:** read the printed Python version before creating
the environment; it must be 3.10 or newer. Pip must finish successfully, and the
shell should remain in the new Bridge folder. Run these commands one line at a
time; stop at the first error. If Git, Python or venv is missing, return to your
platform's prerequisites in [Getting started](GETTING-STARTED.md) and install
through the trusted OS package manager with your approval. Do not use `sudo pip`
or `sudo ./prepare` to work around a failure.

**Advanced dependency detail:**

[`pyproject.toml`](../pyproject.toml) installs the `src/gpt_agent_bridge` package
and pins the same direct runtime roots as [`requirements.txt`](../requirements.txt), imported
by product source: [mcp 2.0.0](https://pypi.org/project/mcp/2.0.0/),
[pydantic 2.13.4](https://pypi.org/project/pydantic/2.13.4/) and
[typing-extensions 4.16.0](https://pypi.org/project/typing-extensions/4.16.0/).
The pins match local installed-package METADATA and each release exists on PyPI.
Pip resolves their transitive dependencies. These are direct dependency pins,
not a transitive hash lock or complete cross-platform reproducibility guarantee.
Do not use the maintainer's full virtualenv `pip freeze` as a portable lock.

## 3. Run the local server in the foreground

Use **Terminal 1: Ubuntu Terminal / WSL Ubuntu Bash**, still in the Bridge
folder from step 2. Select your Herdr binary in this shell before starting.
Confirm that no installed service or other process is already using port 8765;
if it is, stop and choose one deployment rather than running a second Bridge.

This block starts Bridge and **keeps this terminal busy**. It prints a private
file pathname for Terminal 2; keep that pathname locally. The file contains a
secret token (a password-like value allowing access), not something to attach to
Chat. Disable shell tracing/history before generating it, and keep terminal
capture and logs private. The token's value is not printed:

```bash
set +x
set +o history
umask 077
export BRIDGE_WORKSPACE="$(pwd -P)"
export BRIDGE_PORT=8765
export BRIDGE_PATH_TOKEN="$(.venv/bin/python -c 'import secrets; print(secrets.token_urlsafe(32))')"
bridge_client_env="$(mktemp "${XDG_RUNTIME_DIR:-/tmp}/bridge-client-env.XXXXXXXX")"
printf 'export BRIDGE_PORT=%q\nexport BRIDGE_PATH_TOKEN=%q\n' \
  "$BRIDGE_PORT" "$BRIDGE_PATH_TOKEN" > "$bridge_client_env"
printf 'Private client environment file: %s\n' "$bridge_client_env"
"$BRIDGE_WORKSPACE/.venv/bin/python" -m gpt_agent_bridge
```

**Check the result:** the `Private client environment file:` line appears and
Bridge stays running. A returned shell prompt or startup error means it did not
stay running; inspect privately before step 4. A printed pathname alone does not
prove health. The initialized client check in step 4 provides that evidence.

`BRIDGE_WORKSPACE` is required and must be an exact absolute, existing non-bare
Git checkout root, never `src/`, the package directory or site-packages. Install
the package into this checkout's `.venv` before invoking the module. The code and
registered workspace may be separate Git roots. Use an available port if
8765 is already occupied; keep the client and relay settings consistent with it.
The foreground server listens on `127.0.0.1:8765`, with Streamable HTTP at
`/mcp/<token>`. The token is a secret capability: supply the actual value only in
private client/relay configuration. Never put its value or a token-bearing URL in
README, tracked files, reports, shared terminal captures or public logs. The
temporary file created with `mktemp` is outside the checkout, owner-readable only
(mode 0600), and **contains the secret** so a second private shell can reuse it.
Treat that file as sensitive and remove it after the local check. Generating another
token will not match this running server. Stop this foreground process with Ctrl-C
when finished.

## 4. Check through an initialized MCP client

**Choose before consuming the token handoff:** for the recommended private
OpenAI Secure MCP Tunnel connection, run the complete
[combined step 4](#combined-step-4) **instead of** the
standalone local-only block below. Prepare that guide's account/access and
verified client first. The combined alternative checks local health and starts
the tunnel within the same token-holding subshell.

A raw `curl GET` does not establish MCP initialization or a successful tool call.
Use an MCP client with Streamable HTTP support. For a local read-only check,
run this example from the checkout in a **second private Bash shell**. Replace
the quoted `bridge_client_env` pathname with the private file path printed by
Step 3 (including any spaces). Verify it is your own newly created file before
sourcing it; never source an arbitrary file. The subshell preserves a nonzero
client exit status, and removes the temporary secret file even if the client
fails or the shell exits early. Once sourced, the secret remains in the
subshell's environment until it exits. The example does not import
`gpt_agent_bridge.server` or launch another server. The pinned SDK's
`Client(..., mode="legacy")` performs the initialize handshake when entering
its async context:

```bash
(
  set -e
  set +x
  set +o history
  bridge_client_env="/absolute/private/path/printed/in/step-3"
  [[ "$bridge_client_env" == */bridge-client-env.???????? &&
     -f "$bridge_client_env" && ! -L "$bridge_client_env" &&
     -O "$bridge_client_env" ]] || {
    printf 'Invalid or unowned client environment file\n' >&2
    exit 1
  }
  [[ "$(stat -c %a -- "$bridge_client_env")" == 600 ]] || {
    printf 'Client environment file must have mode 0600\n' >&2
    exit 1
  }
  trap 'rm -f -- "$bridge_client_env"' EXIT
  source "$bridge_client_env"
  rm -f -- "$bridge_client_env"  # Secret file is no longer needed.
  .venv/bin/python - <<'PY'
import asyncio
import os
from mcp import Client

async def main():
    port = os.environ.get("BRIDGE_PORT", "8765")
    token = os.environ["BRIDGE_PATH_TOKEN"]
    endpoint = f"http://127.0.0.1:{port}/mcp/{token}"
    async with Client(endpoint, mode="legacy") as client:
        result = await client.call_tool("bridge_health", {})
        if result.is_error:
            raise RuntimeError("bridge_health tool call failed")
        health = result.structured_content
        if not isinstance(health, dict):
            raise RuntimeError("bridge_health did not return structured data")
        status = health.get("herdr", {}).get("status")
        print("Herdr status:", status)
        if status != "reachable":
            print("Bridge is ready; start your Herdr session/Agent before delegation, then request fresh context.")

asyncio.run(main())
PY
)
```

**Check the result in Terminal 2:** expect `Herdr status: reachable` if Herdr is
running. `Bridge is ready; start your Herdr session/Agent before delegation...`
means the local Bridge responded but Herdr is unavailable; it is not permission
to delegate. Any traceback or nonzero exit means stop and inspect privately;
do not rerun the block against the deleted handoff file.

Inspect **`herdr.status == "reachable"`**, not only the outer `ok:true`: Bridge
returns that outer flag even when Herdr is unavailable. This check establishes
Bridge responsiveness and an observed Herdr snapshot, not Agent readiness, task
success, HTTPS reachability or ChatGPT's bound tool schema. Keep client error logs
private too, since transport errors may include the endpoint.

The standalone block deletes its temporary handoff and exits with the token
confined to that subshell. A later shell cannot retrieve it from the deleted
file. If you already ran it and now want a tunnel, stop and choose a separately
authorized private handoff from the original first shell retaining the token,
or a deliberate fresh Bridge restart. Never mint a different client token and
expect it to match the still-running server; no automatic restart is implied.

## 5. Connect your own ChatGPT Web App and authorize a project

For this step, switch to your **browser**, after the combined Tunnel block is
running. An App is ChatGPT's saved connection to Bridge tools; a Skill is a
separate set of reusable instructions. Neither installs the other.

ChatGPT Web cannot reach your loopback address directly. The recommended private
connection is [OpenAI Secure MCP Tunnel](#foreground-secure-mcp-tunnel): follow its
combined step 4 before the standalone block consumes the handoff, then select
your tunnel in ChatGPT's custom MCP connection. Account permissions/workspace
association and a running client are required; source checks are not Web acceptance.

Alternatively, operate your own public HTTPS relay to the running local endpoint
and register your own App using that HTTPS MCP endpoint. Forwarded Host/Origin,
authentication and sustained SSE reachability must be adapted and checked in the
actual environment. No arbitrary tunnel is guaranteed to work. Preserve the
Streamable HTTP path and SSE support; source checks do not prove a Web connection.

The server exposes `BRIDGE_MCP_ENABLE_DNS_REBINDING_PROTECTION`,
`BRIDGE_MCP_ALLOWED_HOSTS` and `BRIDGE_MCP_ALLOWED_ORIGINS` for transport checks.
If enabling protection, supply nonempty exact allowed Hosts and an appropriate
exact Origin list as JSON arrays; the values must match what the server actually
receives through your relay. Do not copy another deployment's allowlist.

For the actual clicks, use [Getting started: connect the Tunnel](GETTING-STARTED.md#5-connect-the-tunnel-to-your-private-chatgpt-plugin),
then its Skill and Project steps. In **ordinary Web Project Chat**, check the
connected tool catalog and request the read-only `bridge_health` call. Confirm
all **four** native Skills are available separately. Missing Plugin Creator or
connection controls require your plan/workspace administrator's support.

**Advanced, optional file-based consumer configuration:** normal Web Plugin
Creator setup updates your existing personal Bridge plugin through Creator;
no manual JSON editing is involved.
[`../.app.example.json`](../.app.example.json) shows the `bridge` alias with
`required: true`. Its `asdk_app_REPLACE_WITH_OWN_APP_ID` is a placeholder, not a
working connection. For a consumer that actually requires a file, use your
newly registered App ID in your own independent consumer's
`.app.json`. Do not overwrite another developer's working binding. The copyright
name is not the GitHub login: clone from the actual repository owner.

After registering the App and checking `bridge_health` through it, the user must
explicitly authorize `project_register(project_ref, path)` for an existing absolute
Git checkout root. Apply the returned Project Binding instructions on the ChatGPT
Project side. Registration grants no task authority. Separately authorize
`project_initialize(project_ref, seed)` for fresh continuity, using the actual tool
schema and existing rule files; see [Project continuity](PROJECT-CONTINUITY.md).
It leaves an already canonical manifest untouched and refuses a noncanonical
`.principal/` rather than overwriting it. App registration alone performs neither
step. Use `context(project_ref)` to discover the real eligible Agent handles, then
authorize a bounded task before `delegate(project_ref, assignments=[...])`.
Report availability is evidence to inspect, not proof that the task succeeded.

## Optional later systemd adoption

For a first installation without adopting a running process, use the separate
[Bridge + Tunnel autostart guide](AUTOSTART.md), with explicit
install/configure/enable/start stages and readbacks. Do not combine the
first-install units with the running-process adopter below.
For Bridge-only setup and the optional WSL anchor, see the
[Bridge component guide](AUTOSTART.md#bridge-component-contract).

Only after a Bridge process is already running for this checkout, an operator may
separately choose the installer described in [technical reference](TECHNICAL-REFERENCE.md#optional-system-service-adoption).
Adoption requires the exact absolute-interpreter launch in Step 3:
`/absolute/checkout/.venv/bin/python -m gpt_agent_bridge`, with that checkout as
cwd and its package installed in that venv. Relative interpreter paths, console
entrypoints, flags and extra arguments are refused. The installer revalidates
process cwd, executable, NUL-separated argv and starttime before publication;
these guard accidental adoption, not malicious same-UID processes or loaded-code
attestation. A different launch needs a separate relaunch decision; the installer
does not restart it automatically.

It adopts that process and its environment, installs and verifies the unit, and
does **not start or enable** it. It cannot bootstrap a clean clone with no running
Bridge. Installation and later service control require explicit operator action;
they are not prerequisites for this foreground quickstart.

## Native Ubuntu Desktop and Server

On **Ubuntu Desktop**, open Terminal as your normal user and use Bash. Keep the
source checkout and `.venv` under your Linux home. Start with steps 1–2; for Web
access prepare the Tunnel before starting Terminal 1. Open a second Ubuntu
Terminal for the combined health/Tunnel block. No `wsl.exe`, PowerShell or
`/mnt/c` path belongs in this route. Use the same local browser for the optional
extension if reminders are needed; follow its loading instructions in Getting started.

On **Ubuntu Server**, the service and Tunnel route may be useful without a desktop,
but a headless Herdr/Agent session and remote-browser reminders are separate
cases not covered by this guide. The browser's `127.0.0.1` refers to its own computer, not the
server. Do not expose Bridge or the notification feed publicly to fix this.
This guide supplies no verified headless Agent launch recipe.

## Windows and WSL2

**Native Ubuntu users: skip this entire section.** Windows users who have not
prepared WSL should follow [Getting started](GETTING-STARTED.md) first. These are
advanced environment notes, not another required newcomer flow.
Windows PowerShell `wsl --list --verbose` identifies the actual distro and its
VERSION 2; `wsl --version` describes components and may be unavailable on older
hosts. Reuse an existing distro and its Linux user. Missing WSL/distro, WSL1
conversion and systemd enablement are explicit operator decisions under
[Microsoft guidance](https://learn.microsoft.com/windows/wsl/install), never
implicit Bridge changes. The supported route is Linux/WSL2, not native Windows
or macOS Bridge. After listing distributions, use **PowerShell** to open the exact selected one:
`wsl.exe --distribution Ubuntu --user your_linux_user` (replace both example
values with the observed distribution name and Linux username). Continue only
when you see that user's Linux shell prompt. If the distribution/user is missing,
stop and resolve WSL setup; do not fall back to an arbitrary default distribution.

Use Linux Git/Python 3.10+/venv/pip and Linux Herdr in the same selected distro.
Keep the developer checkout/venv in Linux home, not `/mnt/c`; see
[filesystem guidance](https://learn.microsoft.com/windows/wsl/filesystems).
Install missing prerequisites through your trusted OS package manager only with
explicit consent, then follow steps 1–2 above. A Windows `herdr.exe` is not the
Linux prerequisite. Set `BRIDGE_WORKSPACE` to the actual Linux absolute Git root,
not a drive path. Keep the separate demo root distinct from Bridge code.

For foreground Web use choose [the combined token handoff](#combined-step-4)
before standalone step 4 consumes it. Both shells/client/server must share the
selected distro/network. Windows→WSL localhost and WSL→Windows are different
routes; NAT/mirrored mode, firewall and VPN can change them. Verify initialized
MCP from the actual client; do not broaden bind/allowlists or disable protection
to compensate. See [WSL networking](https://learn.microsoft.com/windows/wsl/networking).
For persistence use [Autostart](AUTOSTART.md), not a second foreground client.
Systemd alone does not keep WSL alive. No Windows login/restart/24x7 guarantee
follows from a local foreground check.

## Herdr compatibility and version selection

Bundled core preparation requires Linux **Herdr 0.9.0**.
Binary download, architecture choice, SHA256, permissions and version checks are
maintained only in [Getting Started's Herdr prerequisite](GETTING-STARTED.md#herdr-090-prerequisite).
**Installing Bridge for the first time? After 0.9.0 appears there, continue that
page's step 2. No snapshot or running Agent is needed.** The session checks below
are only for users deliberately choosing this manual foreground route and later delegation.

<a id="1-check-before-installing"></a>
### 1. Check before installing

For the binary check, use [the beginner section](GETTING-STARTED.md#herdr-090-prerequisite).
A correct CLI version does not prove a running server or Agent is ready; that is
the separate advanced check below.

<a id="2-optional-separate-v090-installation"></a>
### 2. Optional separate v0.9.0 installation

The pinned download commands have moved to [the single Herdr installation recipe](GETTING-STARTED.md#herdr-090-prerequisite).
This page does not duplicate its download URLs or digests.

<a id="3-select-the-cli-and-check-the-actual-session"></a>
### 3. Select the CLI and check the actual session

**Only after the separate installation succeeds**, select it for the current
shell. If reusing an existing v0.9.0 installation, keep its verified selection
instead of pointing at an uncreated directory.

```bash
export BRIDGE_HERDR_BIN="$HOME/.local/opt/herdr-v0.9.0/herdr"
export PATH="$HOME/.local/opt/herdr-v0.9.0:$PATH"
hash -r
command -v herdr
"$BRIDGE_HERDR_BIN" --version
```

`BRIDGE_HERDR_BIN` is an **absolute CLI path used by Bridge**; set it before
starting Bridge. The temporary `PATH` selection makes manual `herdr` commands
use the same binary. Repeat the selection in each separate Bridge, Herdr launch
or control shell: a new terminal does not inherit another terminal's exports.
Neither selection changes an already running Herdr server's version.

Open Herdr yourself using that selected version if you need a new session,
following the [optional demo Agent setup](#optional-demo-agent-with-herdr).
Do not automatically stop, downgrade or restart an existing session. Check the
session privately with the selected CLI:

```bash
herdr api snapshot
```

The snapshot must succeed and show the intended real Agents. Where the API
reports it, check the connected server's `result.snapshot.version` is **0.9.0**,
not just the CLI's `--version`. If it differs or cannot be established, pause
before delegation and resolve the session selection; do not infer compatibility
from the binary path. Keep snapshot output private.

Continue with [Quickstart](#1-prepare-herdr-and-an-existing-agent).
Its initialized MCP check must find `herdr.status == "reachable"`; health alone
does not certify Agent readiness or version compatibility. This manual session
check does not automatically enforce the running Herdr server version; bundled
preparation checks the selected CLI for 0.9.0. Detection manifests may update
independently of the binary; this pin is not a complete environment lock and
does not change Herdr settings.

## Foreground Secure MCP Tunnel

This section provides a private connection route
after [Quickstart](#3-run-the-local-server-in-the-foreground). OpenAI hosts the
tunnel endpoint; you run the official Linux client next to Bridge. A separate
public HTTPS relay is not required for this route. Account access and a
continuously running client are.

```text
ChatGPT → OpenAI tunnel service ← outbound tunnel-client in Linux/WSL2
                                         ↓ local HTTP
                           Bridge on 127.0.0.1 → local Herdr/Agents
```

The [official tunnel guide](https://developers.openai.com/api/docs/guides/secure-mcp-tunnels)
describes outbound HTTPS to api.openai.com:443 by default. Enterprise control-plane
mTLS has separate requirements. Bridge does not need a public inbound listener.

For unattended boot / owner WSL2 login, use
[Bridge + Secure MCP Tunnel autostart](AUTOSTART.md). This page remains the
foreground transport/account guide: its combined Step 4 means local health plus
a foreground client. Do not launch a second client alongside the companion.

### 1. Choose the combined path before consuming the handoff

**What you are preparing:** Terminal 1 runs Bridge; Terminal 2 runs one Tunnel
client. The Tunnel carries tool requests over an outbound connection to OpenAI.
You do not open Bridge to the Internet. This manual recipe is for a temporary
foreground exercise, not a background service.

First finish **Quickstart steps 1–2** and the account/client preparation below.
Then start Bridge with **Quickstart step 3** in your first private Linux Bash
shell. It generates one token and creates an owner-only temporary handoff file.

**Instead of running standalone Quickstart step 4**, use the complete
[combined step 4 below](#combined-step-4) in a second private Bash shell.
Standalone step 4 sources and deletes the handoff, then exits its subshell;
a later third shell cannot obtain that token from the deleted file.

If you already completed standalone step 4, **stop**. Do not read a nonexistent
file or generate another token for the still-running Bridge. Choose a separately
authorized new private handoff from the **original first shell that retains the
token**, or consciously choose a fresh Bridge restart and repeat step 3. This
guide performs neither recovery nor restart automatically.

**Native Ubuntu:** keep using Ubuntu Terminal and skip the next PowerShell
block. **Windows only:** use [Windows + WSL2](#windows-and-wsl2). Check in
**PowerShell**:

```powershell
wsl --list --verbose
```

Use a version-2 distro. Everything below belongs in **Ubuntu/WSL Bash** or Linux
Bash, not PowerShell. Use the Linux client in the same distro/network as Bridge:
its localhost must reach the intended server. Native Windows/macOS Bridge and
WSL1 are not verified paths. Keep Bridge on loopback; its actual HTTP endpoint is
http://127.0.0.1:<port>/mcp/<current private token>, never bare /mcp.

### 2. Prepare your account, tunnel and permissions first

Open [Platform tunnel settings](https://platform.openai.com/settings/organization/tunnels)
in your browser. Select your own personal Platform organization, or the intended
organization managed by your administrator. Create a tunnel and privately retain
the complete returned tunnel ID. Associate it with the owning Platform organization
**and the ChatGPT workspace where you will create/use the plugin**.

[Tunnel permissions](https://github.com/openai/tunnel-client/blob/v0.0.16/docs/permissions.md)
are organization-level: creation/editing requires **Tunnels Read + Manage**;
running the client and selecting the tunnel for an App require **Read + Use**.
A person doing both needs both capabilities. ChatGPT's custom-MCP workspace
permission is separate. Missing controls or permission is a blocker, not a
reason to bypass policy; a subscription alone does not prove eligibility.

Create a runtime API key in [Platform runtime keys](https://platform.openai.com/settings/organization/api-keys)
under the intended organization, with a principal allowed Read + Use. Use a
runtime key, not an admin key. This **control-plane key authenticates the tunnel
client**; Bridge does not require a separate OpenAI model API Principal.
ChatGPT supplies Principal reasoning. Do not infer that tunnel/key use is free
or unmetered; check current account terms. Agent-provider costs and quotas are
separate. Do not paste keys or private identifiers into Chat, instructions,
tracked files, screenshots or published reports.

### 3. Obtain and verify the pinned Linux client

The combined block below is specifically checked against **tunnel-client v0.0.16**.
Download that official [tagged release](https://github.com/openai/tunnel-client/releases/tag/v0.0.16),
or a matching v0.0.16 download supplied by Platform settings. Do not silently use
another release for this recipe. Choose the full Linux bundle matching the
Linux architecture; use `uname -m` in Ubuntu Terminal or WSL Bash to distinguish x86_64/amd64 from
aarch64/arm64. Follow that release's checksum/provenance instructions.

Extract outside your Git checkout into your own Linux directory, preserving
bundle layout/companions. Retain the **absolute path** to the verified executable.
Make that verified file executable if extraction lost its executable bit.
Do not pipe an unknown download URL into a shell or guess an asset URL.

In **Ubuntu Terminal / WSL Ubuntu Bash**, change to the extracted client's
folder, not the Bridge folder. Before starting Quickstart step 3, run:

```bash
./tunnel-client --version
./tunnel-client help quickstart
```

**Check the result:** version output must report 0.0.16 (possibly with build
metadata), and `help quickstart` must display help. A missing executable, another
version or failed verification means stop and obtain the matching verified full
package; do not guess flags or switch versions.
The combined block checks it again. It does not install dependencies, run sudo,
initialize a profile or start an Agent. Enterprise proxy/private-CA/mTLS setups
need a separately reviewed recipe; the minimal environment below deliberately
does not inherit those overrides.

<a id="combined-step-4"></a>
### 4. Combined step 4: initialized local health, then foreground tunnel

**Before using this particular block, Herdr must be running and reachable.**
Unlike normal `./prepare` and the standalone local check, this preserved manual
recipe stops when Herdr is unavailable. It does not require an Agent for the
health call; delegation later requires your existing authorized Agents.

Now leave **Quickstart step 3 running in Shell 1**. In **Shell 2**, change to the
same Bridge checkout with its installed .venv. Use a private terminal without
capture, and disable tracing/history **in Shell 2 before pasting the block**:

```bash
set +x
set +o history
```

Copy the **whole following block**, including both parentheses. Enter only the
private handoff **pathname** printed by step 3, not its contents. Verify this is
your own freshly created file. The block sources it once and immediately deletes
it, checks initialized MCP health, and continues with that same token before the
subshell exits. No token generation or third-shell transfer occurs.

```bash
(
  set -e
  set +x
  set +o history
  umask 077
  [[ -t 0 && -t 1 ]] || {
    printf 'FALSE: use a private interactive Bash terminal\n' >&2
    exit 1
  }
  read -r -p 'Private handoff pathname printed by Quickstart step 3: ' bridge_client_env
  [[ "$bridge_client_env" == */bridge-client-env.???????? &&
     -f "$bridge_client_env" && ! -L "$bridge_client_env" &&
     -O "$bridge_client_env" ]] || {
    printf 'FALSE: invalid or unowned handoff file\n' >&2
    exit 1
  }
  [[ "$(stat -c %a -- "$bridge_client_env")" == 600 ]] || {
    printf 'FALSE: handoff file must have mode 0600\n' >&2
    exit 1
  }

  bridge_tunnel_logs=""
  cleanup() {
    bridge_tunnel_status=$?
    trap - EXIT
    rm -f -- "$bridge_client_env"
    if [[ -n "$bridge_tunnel_logs" ]]; then
      rm -f -- "$bridge_tunnel_logs"/{health,version,doctor,run,setup}.log
      rmdir -- "$bridge_tunnel_logs"
    fi
    exit "$bridge_tunnel_status"
  }
  inspect_failure() {
    printf 'FALSE: %s\n' "$1" >&2
    printf 'Private diagnostic directory: %s\n' "$bridge_tunnel_logs" >&2
    printf 'Inspect locally in another private shell; never paste raw logs into Chat.\n' >&2
    read -r -t 120 -p 'Press Enter to delete logs now (automatic cleanup in 120 seconds): ' bridge_tunnel_ack || true
  }
  trap cleanup EXIT
  trap 'exit 130' INT
  trap 'exit 143' TERM

  source "$bridge_client_env"
  rm -f -- "$bridge_client_env"
  bridge_tunnel_logs="$(mktemp -d /tmp/bridge-tunnel-first-use.XXXXXXXX)"
  chmod 0700 "$bridge_tunnel_logs"
  export BRIDGE_TUNNEL_LOG_DIR="$bridge_tunnel_logs"

  if .venv/bin/python - > "$bridge_tunnel_logs/health.log" 2>&1 <<'PY'
import asyncio
import os
from mcp import Client

async def main():
    port = os.environ.get("BRIDGE_PORT", "8765")
    token = os.environ["BRIDGE_PATH_TOKEN"]
    endpoint = f"http://127.0.0.1:{port}/mcp/{token}"
    async with Client(endpoint, mode="legacy") as client:
        result = await client.call_tool("bridge_health", {})
        if result.is_error:
            raise RuntimeError("bridge_health tool call failed")
        health = result.structured_content
        if not isinstance(health, dict):
            raise RuntimeError("bridge_health did not return structured data")
        status = health.get("herdr", {}).get("status")
        print("Herdr status:", status)
        if status != "reachable":
            raise RuntimeError("Herdr is unavailable; check its session and PATH")

asyncio.run(main())
PY
  then
    printf 'Local initialized health: PASS\n'
  else
    inspect_failure 'local initialized health'
    exit 1
  fi

  if .venv/bin/python - <<'PY'
import getpass
import os
from pathlib import Path
import subprocess
import sys
import traceback
import warnings

logs = Path(os.environ["BRIDGE_TUNNEL_LOG_DIR"])

def private_log(name):
    handle = (logs / name).open("wb")
    os.chmod(logs / name, 0o600)
    return handle

def main():
    # Python's stdin is this heredoc, so interactive input must use the terminal.
    with open("/dev/tty", "r") as terminal_in, open("/dev/tty", "w") as terminal_out:
        print("Absolute path to your verified v0.0.16 Linux tunnel-client: ",
              end="", file=terminal_out, flush=True)
        binary = Path(terminal_in.readline().rstrip("\r\n"))
    if not binary.is_absolute() or not binary.is_file() or not os.access(binary, os.X_OK):
        raise RuntimeError("An absolute executable file path is required")
    # No inherited client profile/config/debug, proxy, or model API variables.
    child_env = {"HOME": os.environ["HOME"], "PATH": "/usr/bin:/bin", "LANG": "C.UTF-8"}
    with private_log("version.log") as output:
        check = subprocess.run([str(binary), "--version"], env=child_env,
                               stdout=output, stderr=subprocess.STDOUT)
    version = (logs / "version.log").read_text().strip().split()
    if check.returncode or not version or version[0].split("+", 1)[0].removeprefix("v") != "0.0.16":
        raise RuntimeError("This recipe requires the verified v0.0.16 release")

    warnings.filterwarnings("error", category=getpass.GetPassWarning)
    child_env["CONTROL_PLANE_TUNNEL_ID"] = getpass.getpass("Your complete tunnel ID: ")
    child_env["CONTROL_PLANE_API_KEY"] = getpass.getpass("Your runtime API key: ")
    if not child_env["CONTROL_PLANE_TUNNEL_ID"] or not child_env["CONTROL_PLANE_API_KEY"]:
        raise RuntimeError("Tunnel ID and runtime key must be nonempty")
    port = os.environ["BRIDGE_PORT"]
    token = os.environ["BRIDGE_PATH_TOKEN"]
    child_env["MCP_SERVER_URL"] = f"http://127.0.0.1:{port}/mcp/{token}"
    child_env["HEALTH_LISTEN_ADDR"] = "127.0.0.1:8080"
    with private_log("doctor.log") as output:
        doctor = subprocess.run([str(binary), "doctor", "--explain"], env=child_env,
                                stdout=output, stderr=subprocess.STDOUT)
    if doctor.returncode:
        raise RuntimeError("Doctor failed; foreground run was not started")
    print("Doctor: PASS. Starting foreground run; this is not readiness or Web acceptance.", flush=True)
    with private_log("run.log") as output:
        run = subprocess.run([str(binary), "run"], env=child_env,
                             stdout=output, stderr=subprocess.STDOUT)
    if run.returncode:
        raise RuntimeError("Foreground run exited unsuccessfully")
    print("Foreground run stopped; no remote success is implied.", flush=True)

try:
    main()
except KeyboardInterrupt:
    sys.exit(130)
except Exception:
    with private_log("setup.log") as output:
        output.write(traceback.format_exc().encode("utf-8"))
    sys.exit(1)
PY
  then
    :
  else
    inspect_failure 'tunnel setup or foreground run'
    exit 1
  fi
)
```

**Check Terminal 2:** first expect `Local initialized health: PASS`, then
`Doctor: PASS. Starting foreground run; this is not readiness or Web acceptance.`
The terminal stays busy while the client runs. Those lines are only intermediate
checks; verify the local UI in the next step and then the actual Web Chat call.
If it prints `FALSE`, stop. Inspect the private diagnostic directory locally
during the offered inspection period; do not publish logs or replay this block
with a consumed token file.

The health portion intentionally matches Quickstart's pinned SDK legacy
initialize handshake and requires **herdr.status == reachable**, not merely
the outer ok flag. It does not import the Bridge server or launch Bridge again.

The [tagged configuration code](https://github.com/openai/tunnel-client/blob/v0.0.16/pkg/runtimeconfig/config.go)
supports CONTROL_PLANE_TUNNEL_ID, CONTROL_PLANE_API_KEY, MCP_SERVER_URL and
HEALTH_LISTEN_ADDR. The [tagged config-source resolver](https://github.com/openai/tunnel-client/blob/v0.0.16/pkg/runtimeconfig/profile.go)
does not select a profile/config when none is requested. Only an explicit child
environment is passed; secrets are not subprocess arguments or profile literals.
There is **no init/profile step**, no stored runtime key and no persistent token
file. Same-user privileged process inspection is not prevented by environment
variables; use a trusted local machine.

### 5. Observe the live client; keep both shells running

Doctor **can print the actual endpoint**, so its entire stdout/stderr goes to a
private log. Local health, version and foreground runtime output are isolated
too. Files are 0600 inside a fresh 0700 directory outside the repo. On failure,
the block prints only a safe label and private diagnostic directory, allowing
up to 120 seconds for local inspection before deletion. Do not share raw logs.
EXIT/INT/TERM cleanup removes the handoff and generated logs; SIGKILL, host crash
or power loss cannot run a shell trap, so inspect and remove leftovers privately.

The client uses its verified default loopback health address, 127.0.0.1:8080.
Doctor stops on a port conflict; do not kill another process or broaden the bind
to fix it. Run can still fail if a conflict arises after doctor. While the client
runs, open **http://127.0.0.1:8080/ui in the browser on the same Ubuntu computer**
(or verify the Windows-to-WSL localhost route first). On a remote headless server,
that browser address is not the server: do not assume it works or broaden the
bind. A separately reviewed private access method is needed. Use the UI privately to check health,
readiness and connection before attempting ChatGPT discovery. A doctor PASS or
the printed starting message is not evidence that the daemon is ready.

Keep Shell 1's Bridge and Shell 2's tunnel running. Ctrl-C ends the foreground
exercise and cleans the temporary logs. WSL suspension/closure, stopped Bridge,
stopped client or unavailable outbound HTTPS interrupts the path. Systemd does
not by itself keep WSL alive. This recipe promises no credential persistence,
automatic supervision, restart, TTL rewrite or long-task acceptance.
After it exits, replay requires a new explicitly chosen token handoff/restart;
do not rerun against the already deleted handoff.

For the account/plugin controls use only
[Getting started step 5](GETTING-STARTED.md#5-connect-the-tunnel-to-your-private-chatgpt-plugin):
Connection Tunnel, your own Tunnel, MCP No authentication (Bridge has no OAuth
server), risk review, installation and an actual ordinary Project Chat health call.
Local readiness, Create as a plugin and a Work-only result are different checks.
This does not install the four native Skills or Core, register a project or grant
Agent input authority. Keep these separate even when transport works.

<a id="7-diagnose-the-failing-layer"></a>

### 6. Diagnose the failing layer

| Symptom | Check without weakening protection |
| --- | --- |
| Tunnel creation denied | Correct Platform organization, Read + Manage, account availability |
| Tunnel absent in ChatGPT | Intended workspace association and creator's Read + Use |
| Runtime denied | Key's organization/principal, Read + Use; never substitute an admin key |
| Local refusal/404 | Same distro/network, running Bridge, sourced current token and port |
| Doctor fails | Private logs; required values, default health port, local HTTP reachability |
| Starting message but no ready tunnel | Actual UI/readiness, outbound HTTPS, runtime errors; no automatic replay |
| Host/Origin rejected | Actual received values against exact configured Bridge allowlists |
| Discovery works but long stream fails | Streamable HTTP/SSE, disconnects, timeout settings, WSL lifetime |
| Tools appear elsewhere, not Project Chat | Target surface selection and workspace policy |
| Tools work but Skills absent | Package installation/discovery, separate from tunnel transport |

Quickstart owns transport protection, authentication and exact Host/Origin
allowlists. Do not guess private values, use wildcard lists or disable protections.
See the [tagged troubleshooting guide](https://github.com/openai/tunnel-client/blob/v0.0.16/docs/troubleshooting.md)
for diagnosis. Enterprise network exceptions need deliberate operator review,
not silently adding inherited debug/proxy/config variables to the allowlist.

<a id="8-record-completion-and-choose-later-deployment-separately"></a>

### 7. Record completion and choose later deployment separately

Record only observed version, local health, client readiness, actual Project
Chat tool result and remaining gaps in a sanitized note. Never publish keys,
token-bearing URLs, private identifiers or raw logs. This doc is not a success
receipt. Both operator cleanup and any later restart are explicit choices.

Secure MCP Tunnel is for private connections/testing, **not public marketplace
submission/distribution**. Public plugins require a stable public HTTPS endpoint.
The alternate public relay route remains separately user-managed, with actual
authentication, forwarding, streaming and allowlists checked for that deployment.

## Optional invoice demo

**Optional practice, after setup or completely offline.** Skip this entire
section if you only want to use Bridge with your own existing repository. Here,
a fixture means two small example Python files with deliberately failing tests.
The exercise creates a separate disposable folder; it is not an installer check.

This stdlib-only synthetic fixture shows task framing, bounded delegation and
evidence-based acceptance. It contains an **intentionally incorrect baseline**,
not a corrected implementation. Its isolated test failures are teaching evidence,
not Bridge product failures. No financial records, credentials or services are used.
This is a small parsing exercise, not a real invoice system or financial advice.

You can inspect and test it without Bridge, Herdr, a plugin or Project instructions.
For the optional connected exercise, first complete the single
[Getting started guide](GETTING-STARTED.md).
This example supplies neither a Principal Core nor a host setup or continuity seed.
No Agent execution, repaired test pass or fresh-chat recovery follows from these files.

### Bootstrap your own disposable Git repository

Use Linux/WSL Bash, Git 2.28+ and Python 3.10+. Start at the root of **your public
Bridge checkout containing this example**, never the private Bridge development
checkout. The source checkout is read-only. Choose a fresh destination directly
under your Linux home; do not substitute either Bridge checkout as the destination.
Use a shell without custom `GIT_*` environment overrides. Run this yourself only
if you authorize creating and copying into that disposable repository:

```bash
(
  set -e
  source_root="$(pwd -P)"
  demo_root="$HOME/bridge-first-use-demo"  # Choose a fresh name if this exists.
  if [[ -e "$demo_root" || -L "$demo_root" ]]; then
    printf 'Destination exists; stop and choose a new path.\n' >&2
    exit 1
  fi
  for file in invoice.py test_invoice.py; do
    [[ -f "$source_root/examples/first-use/$file" ]] || {
      printf 'Missing fixture file; check the public source checkout.\n' >&2
      exit 1
    }
  done
  umask 077
  mkdir -p -- "$demo_root"
  cp -n -- "$source_root/examples/first-use/invoice.py" \
    "$source_root/examples/first-use/test_invoice.py" "$demo_root/"
  git -C "$demo_root" init -b main --template=
  git -C "$demo_root" status --short
  if git -C "$demo_root" rev-parse --verify HEAD >/dev/null 2>&1; then
    printf 'Unexpected existing HEAD; stop and inspect the destination.\n' >&2
    exit 1
  fi
  printf 'Baseline: main, two untracked fixture files, HEAD absent.\n'
)
```

The new root contains only `invoice.py`, `test_invoice.py` and its
own `.git/`; no child example directory or `__init__.py` is needed. `cp -n` avoids
overwriting files. Stop on any error; do not rerun into the partially created
destination. Privately record the actual status. An unborn `HEAD` is expected:
Bridge registration checks an existing non-bare Git root, not a first commit.
Do not register the Bridge source checkout as this demo project.

In **Ubuntu Terminal / WSL Ubuntu Bash**, you are still in the Bridge source
folder after the creation block: it created the demo without changing this
shell's directory. The next block enters the new disposable project in a
subshell and runs its tests there, using a different start path
(replace the path consistently if you chose another name):

```bash
(
  cd -- "$HOME/bridge-first-use-demo" || exit 1
  python3 -B -m unittest discover -s . -p 'test_*.py' -v
)
```

The shipped baseline has nine tests: **three pass and six intentionally fail**.
The nonzero test exit is expected; import/setup errors are not acceptance failures.
Keep the command and actual result, not a fabricated passing receipt.

An initial commit is optional for registration. It can provide a tracked baseline
only under separate staging/commit authorization in this disposable root; this
example grants no Git, project registration, continuity or Agent input authority.
Explicitly authorize each Work's report publication separately from project edits.

### Optional demo Agent with Herdr

This is operator setup for this disposable exercise, not a required installation
step or Bridge delegation. Keep an eligible Agent already running in the demo
root and skip launching another. Otherwise, choose a compatible Agent and finish
its provider installation/sign-in privately; the
[official Codex CLI guide](https://learn.chatgpt.com/docs/codex/cli) is one example,
not a required provider. Do not paste login output or credentials into Chat.

Use the same selected Linux Herdr CLI in each launch/control shell; see
[Herdr compatibility](#herdr-compatibility-and-version-selection). Open Herdr yourself in
the prepared demo root and keep that session open. The Bridge code checkout
holds its server/venv; this separate demo Git root holds the fixture and is the
Agent's cwd and later registration target. Never substitute a Bridge checkout.

Only if you authorize creating a workspace, run this in Linux/WSL Bash. The
[Herdr automation reference](https://herdr.dev/docs/agent-automation/) describes
the returned root-pane field. The command does not send an Agent task:

```bash
demo_root="$HOME/bridge-first-use-demo"  # Use the exact root you prepared.
demo_root="$(cd -- "$demo_root" && pwd -P)" || exit 1
[[ -d "$demo_root/.git" && ! -L "$demo_root/.git" ]] || {
  printf 'Prepare the independent demo Git root first.\n' >&2
  exit 1
}
workspace_json="$(herdr workspace create --cwd "$demo_root" --label bridge-first-use --no-focus)" || exit 1
demo_pane="$(printf '%s\n' "$workspace_json" | python3 -c 'import json, sys; value = json.load(sys.stdin)["result"]["root_pane"]["pane_id"]; assert isinstance(value, str) and value; print(value)')" || exit 1
printf 'Observed root shell pane: %s\n' "$demo_pane"
```

Inspect that actual pane: it must be an **idle interactive shell prompt**, with no
foreground program/editor/Agent, and its cwd must be the demo root. Choose an
unused Agent name. Only after separately authorizing launch, from the same
control shell retaining `demo_pane`, this Codex example starts the Agent:

```bash
herdr agent start demo --kind codex --pane "$demo_pane"
```

If launch fails or its outcome is uncertain, observe the session before another
action; do not relaunch blindly or prompt it to force readiness. Verify the
intended Agent through read-only Herdr observations and fresh Bridge `context`.
Use its actual `agent_ref`; the Herdr name/pane is not a Bridge handle to invent.
Registration, Chat binding and Agent input remain separately authorized actions.

### Acceptance contract

The public function is `total_cents(amounts) -> int` in [invoice.py](../examples/first-use/invoice.py).
It accepts an iterable of individual amount strings and returns exact integer cents.
The amount syntax is deliberately strict:

- ASCII `0` or a nonzero digit followed by ASCII digits, optionally followed by a
  decimal point and one or two ASCII fractional digits: `0`, `2`, `12.3`, `0.29`.
- No signs, whitespace, leading zeros such as `01`, exponents, commas, Unicode
  digits, missing integer/fractional parts, or more than two fractional digits.
- Each invalid value, including `None`, an empty string, numbers and booleans,
  must raise `ValueError`. Do not silently supply zero or return a partial total.
- No float conversion, rounding or truncation of valid amounts. Preserve every cent,
  including the large case below. Empty input totals zero; input lists stay unchanged.
- Keep the function pure, keep its signature, and use only the Python standard library.
  No file/network access or new dependencies. Passing tests alone does not prove purity.

These independently specified examples are acceptance evidence:

| Input | Required outcome |
| --- | --- |
| `[]` | `0` |
| `["0.10", "0.20"]` | `30` |
| `["0.29", "1.15"]` | `144`, with neither cent lost |
| `["90071992547409.93"]` | `9007199254740993` |
| `["1.00", None, "2.00"]` | `ValueError`, rather than an apparently valid total |
| `["1.005"]` or `["1e2"]` | `ValueError`, rather than rounding or accepting a different format |

[test_invoice.py](../examples/first-use/test_invoice.py) has nine acceptance tests with fixed expected
values and rejection cases. Preserve them during implementation; do not weaken
the contract to turn the suite green. They exercise examples, not every possible input.

### Optional demo evaluation

Read the original [invoice.py](../examples/first-use/invoice.py) and
[test_invoice.py](../examples/first-use/test_invoice.py) against the contract above
before delegation. Predicted failures and executed test receipts are different
evidence. No live task is dispatched by this example.

For the alternative check **without copying the example**, open Ubuntu Terminal
or WSL Ubuntu Bash at the **Bridge source checkout root**. This command reads the
example and runs only its isolated tests; it does not start Bridge or an Agent:

```sh
python3 -B -m unittest discover -s examples/first-use -p 'test_*.py' -v
```

In the copied root use `-s .` instead. The shipped nine-test baseline has three
passes and six intentional failures; setup/import errors are not that baseline.
After an authorized repair of only `invoice.py`, rerun the unchanged tests and
record the actual command, interpreter, exit and result. No corrected pass is
bundled. Ordinary product discovery does not collect this separate fixture.

For optional connected review, complete Getting Started first, bind the exact
Chat before dispatch, and use only an Agent observed in fresh context for the
separately registered disposable root. Explicitly authorize one read-only scope
and its private report; unknown delivery is not a reason to resend. Read the
whole report with its hash pin and compare actual source independently. Missing
reports/attention and reminder/host continuation are separate observations.

Implementation needs new explicit authority. Keep tests/contract unchanged;
no Bridge edits, staging, commits, service actions or other project effects are
included. A second Agent may review the resulting diff afterward; this dependent
review is a later stage, not a simultaneous task. If one Agent implements and
re-reviews, label it honestly. Bridge has no generic test execution endpoint.

### Truth rubric

| Evidence | Claim it supports | Claim it does not support |
| --- | --- | --- |
| Direct original-file read | What those observed bytes/lines show | A test was run, or files cannot change afterward |
| Baseline command with acceptance failures | The shipped defect was exercised on that interpreter | A product regression or successful model repair |
| Agent A's report | A reported implementation and its claims | Verified code, genuine test execution or task success |
| Agent B's review | A second stated assessment and any cited counterexample | Correctness by consensus or guaranteed reviewer independence |
| User reruns unchanged nine-test suite after repair | Those cases pass for the inspected version on that interpreter | All inputs, every environment or security properties are proven |
| Principal reads actual resulting source/diff | Independently observed implementation evidence and reasoning | Principal personally executed tests through Bridge |
| Fresh-chat routed-state read, if configured | The recorded decision/boundary was recovered | Restored active Work, automatic recovery or universal host support |

Record source identity, exact test receipts, disagreements and remaining limits.
If source and reports disagree, preserve the contradiction and seek discriminating
evidence. Do not manufacture a passing output, a review disagreement or a timing claim.
No benchmark or superiority over a single Agent is implied by this toy task.

### Optional fresh-chat continuity

Only if the user already configured Project instructions and project-local continuity
and authorizes a handoff, record the accepted or unresolved decision through the
existing workflow. A fresh chat can then recover that decision and its boundaries
through the configured routed reads. Do not initialize continuity merely to run
this fixture. This example reads or writes no `.principal/` files and supplies no
private configuration. Disclose any setup or cuts in a recorded demonstration;
do not present a three-minute walkthrough as guaranteed installation or runtime.
For an actual fresh-chat check, the successor must distinguish review from
implementation, recover the reason for the next action and respect its authority
boundary. Record whether that was observed; file readback alone does not pass it.
