# Developer quickstart

[English](QUICKSTART.md) | [简体中文](QUICKSTART.zh-CN.md)

**New users:** use the [single preparation flow](GETTING-STARTED.md). The commands below are the advanced foreground/reference route, not required steps for that entry. A pip install alone does not provide the complete release assets.

This guide covers a GitHub checkout, a foreground local Bridge, and the prerequisites
for first use from ChatGPT Web. On Windows, begin with the
[Windows + WSL2 guide](#windows-and-wsl2). Bridge is already used in Windows WSL;
fresh WSL2 installation and fresh virtualenv setup have not been validated.
The shell examples run inside Linux, including WSL, with Bash and GNU coreutils.
Python 3.10+ is required by the pinned SDK. WSL1 has not been validated, and
Windows-native and macOS-native Bridge operation are unsupported by this guide.
Existing WSL use does not certify every distribution, Herdr version or new user's
HTTPS/App connection.

For unattended Linux boot or owner Windows WSL2 login, choose
[Bridge + Secure MCP Tunnel autostart](AUTOSTART.md) after Step 2 package setup,
before the foreground steps below. It uses two services and one optional WSL
anchor; Herdr and Agents remain manual. This page is the foreground route.

## 1. Prepare Herdr and an existing Agent

You need Git, Python 3.10+ with `venv` support, and Herdr on the Bridge process's
`PATH`, or selected with an absolute `BRIDGE_HERDR_BIN` before Bridge starts.
**Herdr v0.9.0 is recommended for this release** from the maintainer's existing
working setup; v0.9.3 is reported incompatible in that setup. First follow the
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
existing session with these read-only commands:

```sh
command -v herdr
herdr --version
herdr api snapshot
```

Before delegating, the snapshot must succeed and show the intended existing Agents.
Bridge and its Web tools may start first; no daily prepare or restart is needed
when you later open Herdr and start an Agent. A CLI found on
`PATH` alone does not establish a usable session or an eligible project Agent.
Keep session output private if it contains local paths or terminal information.

## 2. Clone and install direct dependencies

Clone the public repository below, or substitute your own fork's URL:

```sh
git clone https://github.com/HowAreAllWell/gpt-agent-bridge.git
cd gpt-agent-bridge
python3 --version
python3 -m venv .venv
.venv/bin/python -m pip install -e .
```

Ensure `python3` is 3.10 or newer before creating the environment. If `venv` is
unavailable, install your operating system's Python venv support first.

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

Use a private Bash shell in the checkout. Disable shell tracing/history before
generating the secret, and keep terminal capture and logs private. These commands
generate the token in an environment variable without printing its value:

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

[`../.app.example.json`](../.app.example.json) shows the `bridge` alias with
`required: true`. Its `asdk_app_REPLACE_WITH_OWN_APP_ID` is a placeholder, not a
working connection. The public root `.app.json` also contains that nonfunctional placeholder. In your
independent configuration, use your newly registered App ID in the consumer's
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

## Windows and WSL2

These are advanced environment notes, not another required newcomer flow.
Windows PowerShell `wsl --list --verbose` identifies the actual distro and its
VERSION 2; `wsl --version` describes components and may be unavailable on older
hosts. Reuse an existing distro and its Linux user. Missing WSL/distro, WSL1
conversion and systemd enablement are explicit operator decisions under
[Microsoft guidance](https://learn.microsoft.com/windows/wsl/install), never
implicit Bridge changes. The supported route is Linux/WSL2, not native Windows
or macOS Bridge. Fresh install and restart acceptance remain unverified.

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

**Use Herdr v0.9.0 for this Bridge release.** The maintainer's existing WSL setup
reports `herdr 0.9.0`, a healthy Bridge and reachable Herdr. Herdr v0.9.3 is
**reported incompatible in that setup**; this is not a claim that every v0.9.3
scenario fails. This temporary recommendation should change only after support
for another version is verified. It is field evidence, not a fresh-install or
cross-version acceptance test.

### 1. Check before installing

Run these read-only commands in the Linux/WSL shell you will use for Bridge:

```bash
command -v herdr
herdr --version
```

If the selected CLI already reports **0.9.0** and your Herdr session is usable,
**do not reinstall**. Continue with the session checks below. If Herdr is absent
or another version is selected, the optional instructions below install a
separate binary without replacing your current installation.

The [official installation guide](https://herdr.dev/docs/install/) remains the
general reference. Its generic installer follows the latest release rather than
pinning v0.9.0, so use the explicit release assets below for this recommendation.
Do not run an update command expecting it to preserve the pin.

### 2. Optional separate v0.9.0 installation

These are **user-run installation instructions**, not actions performed by
Bridge. Use Ubuntu/Linux Bash, including inside WSL; a Windows `herdr.exe` is
not this prerequisite. You need `curl` and GNU `sha256sum`. On Ubuntu, if they
are missing, you may choose to install them with `sudo apt install curl coreutils`.

The official [v0.9.0 release](https://github.com/herdrdev/herdr/releases/tag/v0.9.0)
and its [GitHub release metadata](https://api.github.com/repos/herdrdev/herdr/releases/tags/v0.9.0)
publish these assets and SHA256 digests:

| `uname -m` | Official asset | SHA256 |
| --- | --- | --- |
| `x86_64` | [herdr-linux-x86_64](https://github.com/herdrdev/herdr/releases/download/v0.9.0/herdr-linux-x86_64) | `4fa1a01158dd8043da92d31b270780b0dcc10603038d9b61cac4d81ab63fb71f` |
| `aarch64` / `arm64` | [herdr-linux-aarch64](https://github.com/herdrdev/herdr/releases/download/v0.9.0/herdr-linux-aarch64) | `9c8db20fb7e7427b138d5367113f1621ffd319f2f65d6f009e2594029115f0d2` |

The following block refuses an existing destination, including a dangling
symlink. It creates a private version directory **outside the checkout**, downloads
to a distinct temporary filename and checks the pinned digest **before** making
the binary executable. It does not execute Herdr or change persistent `PATH`.

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
  printf 'Verified binary installed in the new version directory.\n'
)
```

Continue only if the **whole block succeeds**. A failure leaves the new directory
for inspection; it does not authorize deleting or overwriting it for a retry.
These hashes check correspondence with the published asset metadata, not an
independent security review of the binary.

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
does not certify Agent readiness or version compatibility. This guide adds no
automatic version enforcement to Bridge. Detection manifests may update
independently of the binary; this pin is not a complete environment lock and
does not change Herdr settings.

## Foreground Secure MCP Tunnel

This guide, reviewed on **2026-10-11**, provides a private connection
route after [Quickstart](#3-run-the-local-server-in-the-foreground). It has not been executed as a fresh-account,
fresh-WSL or deployed acceptance test. OpenAI hosts the tunnel endpoint; you run
the official Linux client next to Bridge. A separate public HTTPS relay is not
required for this route. Account access and a continuously running client are.

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

On Windows, use [Windows + WSL2](#windows-and-wsl2). Check in **PowerShell**:

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
distro architecture; use uname -m in WSL Bash to distinguish x86_64/amd64 from
aarch64/arm64. Follow that release's checksum/provenance instructions.

Extract outside your Git checkout into your own Linux directory, preserving
bundle layout/companions. Retain the **absolute path** to the verified executable.
Make that verified file executable if extraction lost its executable bit.
Do not pipe an unknown download URL into a shell or guess an asset URL.

From its containing directory, check before starting Quickstart step 3:

```bash
./tunnel-client --version
./tunnel-client help quickstart
```

The reported semantic version must be 0.0.16 (possibly with build metadata).
The combined block checks it again. It does not install dependencies, run sudo,
initialize a profile or start an Agent. Enterprise proxy/private-CA/mTLS setups
need a separately reviewed recipe; the minimal environment below deliberately
does not inherit those overrides.

<a id="combined-step-4"></a>
### 4. Combined step 4: initialized local health, then foreground tunnel

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
runs, use its local UI at http://127.0.0.1:8080/ui privately to check health,
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

### 7. Diagnose the failing layer

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

### 8. Record completion and choose later deployment separately

Record only observed version, local health, client readiness, actual Project
Chat tool result and remaining gaps in a sanitized note. Never publish keys,
token-bearing URLs, private identifiers or raw logs. This doc is not a success
receipt. Both operator cleanup and any later restart are explicit choices.

Secure MCP Tunnel is for private connections/testing, **not public marketplace
submission/distribution**. Public plugins require a stable public HTTPS endpoint.
The alternate public relay route remains separately user-managed, with actual
authentication, forwarding, streaming and allowlists checked for that deployment.

## Optional invoice demo

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

From the disposable root, run the same isolated tests with a different start path
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

From the source checkout an explicitly authorized isolated check is:

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
