# Developer quickstart

**New users:** use the [single preparation flow](GETTING-STARTED.md). The commands below are the advanced foreground/reference route, not required steps for that entry. A pip install alone does not provide the complete release assets.

This guide covers a GitHub checkout, a foreground local Bridge, and the prerequisites
for first use from ChatGPT Web. On Windows, begin with the
[Windows + WSL2 guide](WINDOWS-WSL.md). Bridge is already used in Windows WSL;
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
[Herdr compatibility guide](HERDR-COMPATIBILITY.md) to check an existing install
or choose a separate, checksum-verified v0.9.0 binary. Do not reinstall a usable
0.9.0 setup. The generic official installer tracks latest and does not pin this
version. Herdr is a separate prerequisite, not a Python requirement.

For the first-use demo, clone the Bridge source in Step 2 and
[prepare its independent demo Git root](../examples/first-use/README.md#bootstrap-your-own-disposable-git-repository)
before Agent launch or registration. An initial demo commit is optional.
[Project setup's Herdr/Codex example](CHATGPT-PROJECT-SETUP.md#prepare-a-demo-agent-with-herdr)
explains how to install/sign in and launch in an observed idle shell pane.
Use the Bridge code checkout for the server/client steps, the demo root for its
Agent and project_register; keep those roots distinct.

Have Herdr running with real, already launched Herdr-managed coding Agents in the
Git checkout you intend to use. Choose the provider/model and make sure its quota
is available. Bridge does not create or launch Agents for you. Check the CLI and
existing session with these read-only commands:

```sh
command -v herdr
herdr --version
herdr api snapshot
```

The snapshot must succeed and show the intended existing Agents. A CLI found on
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
[combined step 4](OPENAI-SECURE-MCP-TUNNEL.md#combined-step-4) **instead of** the
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
            raise RuntimeError("Herdr is unavailable; check its session and PATH")

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
connection is [OpenAI Secure MCP Tunnel](OPENAI-SECURE-MCP-TUNNEL.md): follow its
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
[Bridge component guide](BRIDGE-AUTOSTART.md).

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
