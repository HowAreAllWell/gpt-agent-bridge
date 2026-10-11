# Windows + WSL2 onboarding

Run Bridge in Ubuntu inside WSL2, using Linux Bash and Linux binaries. Bridge
already operates inside WSL on Windows; this guide documents that deployment
shape. The clean WSL2 installation and onboarding sequence below has **not been
independently field-tested**. Existing WSL operation uses the Linux codepath and
does not establish separately tested bare-metal Linux acceptance. Windows-native
and macOS-native Bridge operation are unsupported and unverified here.

You need Git, Python 3.10+ with venv, Linux Herdr and existing Herdr-managed Agents.
ChatGPT Web additionally needs your own Secure MCP Tunnel or verified HTTPS
relay and registered App.
The first local run uses a foreground server; systemd is optional later.

## Phase 1: Check or prepare WSL2 in Windows

These commands belong in **Windows PowerShell**, not Ubuntu Bash. First inspect
your existing setup:

```powershell
wsl --version
wsl --list --verbose
```

`wsl --version` describes the WSL components. The `VERSION` column of
`wsl --list --verbose` identifies each distribution's WSL version: the Ubuntu
distribution you will use must show **2**. WSL1 is not validated for this guide.
An older WSL command may lack `--version`; that alone does not mean WSL is absent.
If WSL and the intended Ubuntu distribution are already installed, do not
reinstall them. Follow Microsoft's
[WSL installation and version guidance](https://learn.microsoft.com/windows/wsl/install)
if your distribution or WSL version needs preparation.

**If WSL or the intended Ubuntu distribution is missing**, first confirm that
Windows meets Microsoft's simplified-install prerequisites: Windows 11 or
Windows 10 version 2004 (build 19041) or later. Open **PowerShell as Administrator**
and install Ubuntu only when needed:

```powershell
wsl --install -d Ubuntu
```

Restart Windows if prompted, then launch Ubuntu and complete its first-run Linux
user setup. For an existing Ubuntu distribution, open its terminal or select it
from PowerShell:

```powershell
wsl --distribution Ubuntu
```

While Ubuntu is open, rerun `wsl --list --verbose` in a separate PowerShell window.
Check that the intended distribution shows `Running` and `VERSION` **2**. `Stopped`
before opening it is normal. Use your actual distribution name if it differs from
`Ubuntu`. Installation, upgrades and WSL configuration changes are operator choices;
reading this guide does not perform them.

## Phase 2: Prepare the Linux checkout and Herdr inside Ubuntu

All commands from this phase onward belong in **Ubuntu Bash inside the same WSL2
distribution**, not PowerShell. Install the Linux prerequisites if needed:

```bash
sudo apt-get update
sudo apt-get install git python3 python3-venv python3-pip
```

Keep the checkout in your Linux home, such as `~/gpt-agent-bridge`, rather than
`/mnt/c`. Microsoft's [WSL filesystem guidance](https://learn.microsoft.com/windows/wsl/filesystems)
recommends keeping files with the operating system whose tools use them; Linux
filesystem permissions, case behavior and performance also differ from Windows
mounts. Clone the public repository and create its virtualenv:

```bash
cd ~
git clone https://github.com/HowAreAllWell/gpt-agent-bridge.git
cd gpt-agent-bridge
python3 --version
```

Confirm Python is **3.10 or newer** before continuing. If the checkout already
exists, enter it instead of cloning over it. When using a fork, use its clone URL.

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
```

The [Quickstart dependency notes](QUICKSTART.md#2-clone-and-install-direct-dependencies)
explain the direct pins and their reproducibility limits. This guide does not
certify a fresh install on every Ubuntu or Python version.

Install the **Linux Herdr binary matching your WSL CPU architecture** inside this
distribution using the [official Herdr guide](https://herdr.dev/docs/install/).
Verify the download source and inspect any installation script and what it executes
before running it. A Windows `herdr.exe` installation is not the Linux prerequisite.
Ensure Linux Herdr is on the Bridge shell's `PATH` and that real, already launched
Herdr-managed Agents use the same WSL distribution and Herdr session, in the Git
checkout you intend to authorize. For first use, prepare the
[disposable demo Git root](../examples/first-use/README.md#bootstrap-your-own-disposable-git-repository)
**before** launching an Agent or registering it; keep it distinct from the Bridge
code checkout. Its initial commit is optional, not required by registration.
Follow the [officially grounded Herdr/Codex setup example](CHATGPT-PROJECT-SETUP.md#prepare-a-demo-agent-with-herdr)
for installation/sign-in, your actual root pane and Agent launch, or keep a
compatible existing Agent. Choose an available provider/model and quota.
Bridge does not launch Agents for you.

Follow [Quickstart Step 1](QUICKSTART.md#1-prepare-herdr-and-an-existing-agent)
for the read-only CLI/session checks. Finding a binary alone does not prove a
usable session or eligible Agents; keep snapshot output private.

## Phase 3: Run foreground Bridge and check MCP inside WSL

From the **Bridge code checkout**, not the demo root, in a private Ubuntu Bash
shell, follow
[Quickstart Step 3](QUICKSTART.md#3-run-the-local-server-in-the-foreground).
`BRIDGE_WORKSPACE` must be the **Linux absolute checkout path**, as obtained by
`pwd -P`, not a Windows drive path. Keep the server on `127.0.0.1`, use a private
token, and follow that step's tracing, history and secret-file precautions.

Leave the foreground server running. **Choose before consuming the handoff:**
for recommended private Web first use, prepare the
[Secure MCP Tunnel guide](OPENAI-SECURE-MCP-TUNNEL.md) and use its
[combined Step 4](OPENAI-SECURE-MCP-TUNNEL.md#combined-step-4) in a **second private
Ubuntu Bash shell in the same WSL distribution and checkout**, instead of the
standalone local-only [Quickstart Step 4](QUICKSTART.md#4-check-through-an-initialized-mcp-client).
The combined route checks initialized `bridge_health`, deletes the temporary
secret file and starts the Linux tunnel client in the same token-holding subshell.
For a local-only check or your own relay, use the standalone route and plan its
separate private configuration before the handoff is consumed.
Do not substitute a raw `curl GET` or generate
a different token for the client. Check `herdr.status == "reachable"`, not just
the outer `ok` flag. This establishes local responsiveness and an observed Herdr
snapshot, not Agent readiness, completed work or a ChatGPT Web connection.

## Phase 4: Connect your own Web App and verify networking

ChatGPT Web cannot reach WSL loopback directly. For private first use,
use the [OpenAI Secure MCP Tunnel setup](OPENAI-SECURE-MCP-TUNNEL.md)
selected in Phase 3. Its combined workflow checks local health and runs the
**Linux** client in the same WSL distribution as Bridge, using your own tunnel
and runtime key. Then select that tunnel in ChatGPT. If you already consumed
the handoff with the standalone check, stop and follow the guide's explicit
private-handoff or deliberate-restart choice; do not improvise recovery.
The local Bridge's current private MCP path
and authentication must be preserved. The tunnel guide owns the safe token
handoff and tunnel diagnostics; do not improvise a new token or paste it into
logs or tracked files.

Alternatively, [Quickstart Step 5](QUICKSTART.md#5-connect-your-own-chatgpt-web-app-and-authorize-a-project)
describes the generic requirements for an independently managed public HTTPS
relay with Streamable HTTP/SSE support. Verify actual forwarded Host/Origin
and authentication behavior. A tunnel or example App ID is not proof of a
working connection; preserve existing bindings rather than overwriting them.

For Windows-side clients, Microsoft documents access to WSL services through
`localhost` in common configurations, but NAT/mirrored networking, forwarding,
firewall and VPN settings can affect the route. See the official
[WSL networking guidance](https://learn.microsoft.com/windows/wsl/networking).
Do not assume a Windows-native host App or relay can reach this WSL endpoint
without explicitly checking that client and its initialized MCP connection.
Windows-to-WSL access and WSL-to-Windows access are different routes. Do not
automatically broaden the bind address, disable protection or open firewall ports
to compensate for an unverified route. Bridge remains a Linux process inside WSL.

## Optional later: systemd and WSL lifetime

After the foreground run works, an operator may choose
[Quickstart's optional systemd adoption](QUICKSTART.md#optional-later-systemd-adoption).
It is not required for the first run. Some WSL Ubuntu installations already use
systemd; others may require explicit enabling according to Microsoft's
[WSL systemd guide](https://learn.microsoft.com/windows/wsl/systemd).
Do not assume it is enabled or change WSL configuration as part of the local MCP
check. The Bridge installer adopts an already running process and does not start
or enable the service; installation and service control need separate operator action.

Systemd services alone do **not** keep the WSL instance alive. Windows shutdown,
WSL termination and distribution lifetime still affect availability. A passing
foreground check is not a persistence guarantee or fresh-install/live HTTPS
acceptance. Return to the [Quickstart](QUICKSTART.md) for the shared contracts and
the [README](../README.md) for product navigation.
