# Developer quickstart

This guide covers a GitHub checkout, a foreground local Bridge, and the prerequisites
for first use from ChatGPT Web. On Windows, begin with the
[Windows + WSL2 guide](WINDOWS-WSL.md). Bridge is already used in Windows WSL;
fresh WSL2 installation and fresh virtualenv setup have not been validated.
The shell examples run inside Linux, including WSL, with Bash and GNU coreutils.
Python 3.10+ is required by the pinned SDK. WSL1 has not been validated, and
Windows-native and macOS-native Bridge operation are unsupported by this guide.
Existing WSL use does not certify every distribution, Herdr version or new user's
HTTPS/App connection.

## 1. Prepare Herdr and an existing Agent

You need Git, Python 3.10+ with `venv` support, and Herdr on the Bridge process's
`PATH`. Use the maintainer's [official Herdr installation guide](https://herdr.dev/docs/install/).
It offers an official installation script; inspect the source and what it executes
before running it. Herdr is a separate prerequisite, not a Python requirement.

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
.venv/bin/python -m pip install -r requirements.txt
```

Ensure `python3` is 3.10 or newer before creating the environment. If `venv` is
unavailable, install your operating system's Python venv support first.

[`requirements.txt`](../requirements.txt) pins only direct runtime roots imported
by product source: [mcp 2.0.0](https://pypi.org/project/mcp/2.0.0/),
[pydantic 2.13.4](https://pypi.org/project/pydantic/2.13.4/) and
[typing-extensions 4.16.0](https://pypi.org/project/typing-extensions/4.16.0/).
The pins match local installed-package METADATA and each release exists on PyPI.
Pip resolves their transitive dependencies. This is a direct dependency pin file,
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
.venv/bin/python server.py
```

`BRIDGE_WORKSPACE` must be the absolute checkout root. Use an available port if
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

A raw `curl GET` does not establish MCP initialization or a successful tool call.
Use an MCP client with Streamable HTTP support. For a local read-only check,
run this example from the checkout in a **second private Bash shell**. Replace
the quoted `bridge_client_env` pathname with the private file path printed by
Step 3 (including any spaces). Verify it is your own newly created file before
sourcing it; never source an arbitrary file. The subshell preserves a nonzero
client exit status, and removes the temporary secret file even if the client
fails or the shell exits early. Once sourced, the secret remains in the
subshell's environment until it exits. The example does not import
`server.py` or launch another server. The pinned SDK's
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

## 5. Connect your own ChatGPT Web App and authorize a project

ChatGPT Web cannot reach your loopback address directly. Provide your own HTTPS
relay to the running local endpoint and register your own App in ChatGPT using
that private HTTPS MCP endpoint. Relay configuration, forwarded Host/Origin,
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

Only after a Bridge process is already running for this checkout, an operator may
separately choose the installer described in [README](../README.md#verification-and-deployment-boundaries).
It adopts that process and its environment, installs and verifies the unit, and
does **not start or enable** it. It cannot bootstrap a clean clone with no running
Bridge. Installation and later service control require explicit operator action;
they are not prerequisites for this foreground quickstart.
