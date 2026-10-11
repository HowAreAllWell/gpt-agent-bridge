# Windows + WSL2 onboarding

Run Bridge, Python, Linux Herdr and your coding Agents inside one Ubuntu WSL2
distribution. Your browser and ChatGPT Web can remain on Windows.
Bridge is already used in Windows WSL. That existing use is distinct from a
fresh WSL2 installation: the installation path and fresh virtualenv setup below
have not been validated end to end. WSL1 has not been validated; Windows-native
and macOS-native Bridge operation are unsupported by this guide.

The commands below are setup instructions for you to run when appropriate.
Keep the shell boundaries clear: **PowerShell commands run on Windows**;
**Ubuntu Bash commands run inside WSL**. The first local run needs no systemd
setup or service installation.

## 1. Prepare Ubuntu on WSL2 — Windows PowerShell

Use Windows 10 version 2004 or newer (build 19041+) or Windows 11. Only if WSL
or your target Ubuntu distribution is missing, open **PowerShell as Administrator**
and follow
[Microsoft's WSL installation guide](https://learn.microsoft.com/windows/wsl/install):

```powershell
wsl --install -d Ubuntu
```

Restart Windows if requested. Open Ubuntu and finish its first-run setup,
including your Linux username and password. If WSL is already installed but
Ubuntu is missing, the command installs that distribution. If both already
exist, reuse the intended distribution; do not reinstall WSL or Ubuntu.

In **Windows PowerShell**, check the installation:

```powershell
wsl --version
wsl --list --verbose
```

The Ubuntu row's **VERSION 2** in `wsl --list --verbose` is the authoritative
check of that distribution's WSL2 mode. `wsl --version` reports the WSL software
version and may be unsupported by older WSL CLIs; an unrecognized `--version`
does not mean WSL is absent. Use the distribution list to check its mode. If
Ubuntu shows VERSION 1 or the list cannot establish VERSION 2, follow
Microsoft's instructions before continuing rather than reinstalling blindly.
These checks do not validate Bridge or its dependencies.

Open the intended Ubuntu distribution from Windows Terminal or, in PowerShell:

```powershell
wsl -d Ubuntu
```

If your existing distribution has a different name, use that exact name from
`wsl --list --verbose`. Run the remaining Bash commands in that distribution.

## 2. Prepare Python and the checkout — Ubuntu Bash

Inside **Ubuntu Bash**, install the Linux prerequisites:

```bash
sudo apt update
sudo apt install -y git python3 python3-venv python3-pip
```

Clone into your WSL home directory, then create the environment:

```bash
cd ~
git clone https://github.com/HowAreAllWell/gpt-agent-bridge.git
cd ~/gpt-agent-bridge
python3 --version
```

Confirm Python is **3.10 or newer** before proceeding. If this Ubuntu release
provides an older Python, use an appropriate Python 3.10+ environment first.

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
```

Keep this checkout and `.venv` in the Linux filesystem under `~/`, rather than
`/mnt/c`. Microsoft recommends storing files alongside the operating system's
tools for better filesystem performance; see its
[Windows/Linux filesystem guidance](https://learn.microsoft.com/windows/wsl/filesystems).
Reuse an existing checkout only after confirming its location and preserving
any local work; do not clone over it.

[`requirements.txt`](../requirements.txt) pins direct runtime dependencies.
Pip still resolves transitive dependencies; this is not a transitive hash lock
or a guarantee of complete cross-platform reproducibility. A fresh installation
of these pins in a new WSL2 environment has not yet been validated.

## 3. Prepare Linux Herdr and existing Agents — Ubuntu Bash

Follow [Herdr's official installation guide](https://herdr.dev/docs/install/)
from **inside Ubuntu**, using its Linux installation path. If choosing the
official installer script, inspect its source and what it executes first.
Use the Linux `herdr` executable on the WSL shell's `PATH`; a Windows
`herdr.exe` installation is not the backend for this workflow.

Have Herdr running with real, already launched Herdr-managed coding Agents in
the same WSL distribution and intended Herdr session, using the Git checkout
where you want work performed. Choose the provider/model and confirm its quota
is available. Bridge discovers existing Agents; it does not launch them.

Check the CLI and session in **Ubuntu Bash** with read-only commands:

```bash
command -v herdr
herdr --version
herdr api snapshot
```

Confirm the command resolves to your Linux installation and the snapshot
succeeds with the intended Agents. Finding the executable alone does not prove
Agent eligibility or readiness. Keep snapshots, terminal output and session
secrets private; do not paste them into public issues or reports.

## 4. Run Bridge and check MCP — Ubuntu Bash

Continue with the canonical quickstart's
[Step 3: foreground Bridge](QUICKSTART.md#3-run-the-local-server-in-the-foreground)
and [Step 4: initialized MCP client](QUICKSTART.md#4-check-through-an-initialized-mcp-client).
Run both from `~/gpt-agent-bridge` in the **same WSL distribution**, using two
private Ubuntu Bash shells. Follow those steps' token generation, private
environment handoff and cleanup exactly; this guide does not duplicate the
secret-handling code.

The default listener is `127.0.0.1:8765` inside WSL. The local MCP check must
initialize the protocol and inspect `herdr.status == "reachable"`; a raw GET
or the outer `ok:true` does not prove a usable backend. Keep the foreground
terminal open while using this run, and use Ctrl-C when finished.

## 5. Connect ChatGPT Web separately

Follow [Quickstart Step 5](QUICKSTART.md#5-connect-your-own-chatgpt-web-app-and-authorize-a-project)
for your own HTTPS relay, registered App and explicit project authorization.
ChatGPT Web needs an externally reachable HTTPS MCP endpoint; it cannot connect
directly to the WSL loopback listener.

Check the actual relay-to-WSL route, forwarded Host/Origin, authentication and
sustained SSE reachability in your environment. Windows-to-WSL localhost
forwarding and access from a Windows-native tunnel are not guaranteed by this
guide. A browser running on Windows does not establish relay or ChatGPT access.
No arbitrary tunnel is guaranteed to work.

The public [App example](../.app.example.json) contains a nonfunctional App ID
placeholder. Use your own registered ID in your independent configuration.
App registration does not register a local project, initialize continuity or
authorize Agent input; follow the quickstart's separate user-authorized steps
and use the real Agent handles discovered for that WSL checkout.

## Optional later systemd adoption

First complete the foreground run and local MCP check. Only then consider the
quickstart's [optional systemd adoption](QUICKSTART.md#optional-later-systemd-adoption)
as a separate operator choice. The Bridge installer requires an already running
process for that checkout and does not start or enable the service.

WSL's systemd availability depends on your WSL version and distribution setup;
additional setup may be needed. Microsoft also states that systemd services
**do not keep a WSL instance alive**. See
[Microsoft's systemd guidance](https://learn.microsoft.com/windows/wsl/systemd)
before planning persistent operation. Service adoption is not automatic
deployment, a Windows startup integration or a guarantee of continued WSL/HTTPS
availability.
