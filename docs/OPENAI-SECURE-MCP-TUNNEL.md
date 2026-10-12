# Connect local Bridge with OpenAI Secure MCP Tunnel

This guide, reviewed on **2026-10-11**, provides a private connection
route after [Quickstart](QUICKSTART.md). It has not been executed as a fresh-account,
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

## 1. Choose the combined path before consuming the handoff

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

On Windows, use [Windows + WSL2](WINDOWS-WSL.md). Check in **PowerShell**:

```powershell
wsl --list --verbose
```

Use a version-2 distro. Everything below belongs in **Ubuntu/WSL Bash** or Linux
Bash, not PowerShell. Use the Linux client in the same distro/network as Bridge:
its localhost must reach the intended server. Native Windows/macOS Bridge and
WSL1 are not verified paths. Keep Bridge on loopback; its actual HTTP endpoint is
http://127.0.0.1:<port>/mcp/<current private token>, never bare /mcp.

## 2. Prepare your account, tunnel and permissions first

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

## 3. Obtain and verify the pinned Linux client

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
## 4. Combined step 4: initialized local health, then foreground tunnel

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

## 5. Observe the live client; keep both shells running

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

## 6. Connect and install in the correct ChatGPT Project Chat

Follow [OpenAI's connect-and-test guide](https://developers.openai.com/plugins/deploy/connect-chatgpt)
while the client is healthy:

1. Open **ChatGPT Plugins → plus → Add custom MCP server** in the intended workspace.
2. Name it. Under **Connection**, choose **Tunnel**, then select your tunnel or
   enter its complete ID privately. Do not use the localhost URL as a public URL.
3. Review authentication and the risk warning, then **Create as a plugin**.
   The control-plane runtime key is not an App authentication credential to paste
   here. Bridge's path-token capability does not itself implement OAuth.
4. Review tools, **Install**, then start a new **Chat in your intended Project**.
   Enable/select the plugin there (the documented selection uses @) and request
   only a read-only bridge_health tool call.

Require an actual result in that Project Chat. Local health, plugin creation or
a Work-only test does not establish it. Account/workspace policy can change
controls; missing Tunnel/Install/Project Chat access remains an eligibility gap.
No universal Plus/Pro or fresh-account support is promised.

The custom MCP connection does not install the four Bridge Skills or Core.
Follow [Project setup](CHATGPT-PROJECT-SETUP.md) and [Plugin Skills](PLUGIN-SKILLS.md)
for eligible package installation/discovery and manual Project Instructions.
Separately authorize project_register, then append its returned Project Binding;
continuity and Agent delegation require their own authorization.
Use [First use](FIRST-USE-WALKTHROUGH.md) after those independent checkpoints.

## 7. Diagnose the failing layer

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

## 8. Record completion and choose later deployment separately

Record only observed version, local health, client readiness, actual Project
Chat tool result and remaining gaps in a sanitized note. Never publish keys,
token-bearing URLs, private identifiers or raw logs. This doc is not a success
receipt. Both operator cleanup and any later restart are explicit choices.

Secure MCP Tunnel is for private connections/testing, **not public marketplace
submission/distribution**. Public plugins require a stable public HTTPS endpoint.
The alternate public relay route remains separately user-managed, with actual
authentication, forwarding, streaming and allowlists checked for that deployment.
