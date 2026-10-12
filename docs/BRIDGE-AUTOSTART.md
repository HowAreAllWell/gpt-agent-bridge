# Bridge autostart: explicit first installation

For **both Bridge and Tunnel** after boot / owner WSL2 login, start with the
[combined first-use guide](AUTOSTART.md). This page owns the Bridge-only component
and its optional single Windows lifetime anchor.

This v0 installs **only Bridge** as a Linux system service. After an operator
explicitly installs and enables it, systemd starts it at Linux boot and restarts
it on failure. On WSL2, a separate opt-in Windows task holds a named distro open
after its owner logs in. The Linux unit needs no foreground Bridge terminal; the optional Windows anchor still requires target-host acceptance.
This implementation has synthetic tests; real Linux reboot and Windows logon
acceptance are still required. It does not promise pre-login operation, continuous
availability during suspend, or Work/process resumption after restart.

Herdr and the Secure MCP Tunnel remain separate prerequisites. They are **not**
installed, started or supervised here. Bridge can start while Herdr is unavailable;
local service availability alone does not make ChatGPT's connection available.
For the component-only route, retain separate Tunnel management. In the
combined route, the companion manages Tunnel; Herdr/Agents remain manual.

## Choose the correct installer

- This [first-install script](../scripts/install-bridge-autostart.py) needs no
  existing Bridge process. It creates a distinct `gpt-agent-bridge-autostart.service`.
- The separate [adopter](../scripts/install-bridge-system-service.sh)
  inspects an already running Bridge for that checkout, installs its own unit,
  and never starts or enables it. Do not combine the two service installations.

Finish [dependency installation](QUICKSTART.md#2-clone-and-install-direct-dependencies)
and select a compatible Herdr executable first. Use one explicit nonroot Linux
account, its existing checkout, a Git workspace it owns, and Linux-filesystem
paths. This small v0 rejects symlinked checkout/Herdr/config paths, `/mnt/` paths,
spaces and metacharacters in Linux paths. A normal venv Python symlink is allowed.
It installs no dependencies and grants no sudo authority to Bridge tools.
Herdr v0.9.0 is the recommended binary; it may be stopped. Follow the public
[Herdr compatibility guide](HERDR-COMPATIBILITY.md) and reuse a usable install.

Code, workspace, account home, Herdr and their controlling directories must be
owned by the selected service account or root, without group/world write access.
The source package and entire venv dependency tree (including `.pth` files and
resolved interpreter) are checked before invoking that interpreter. A root-owned
sticky temporary ancestor is allowed above a private checkout; shared writable
home/code/venv directories are refused. Unexpected dependency symlinks, foreign
owners or an inventory over the safety bound require operator review. Checks run
again before publication, enable/start, and runtime execution. They protect
against other accounts modifying the launch inputs, not a malicious selected
account or root changing files between checks.

The only supported entrypoint is the checkout's `.venv/bin/python -m gpt_agent_bridge`;
the loader and runtime add `-I -B` isolation flags so inherited Python path/user-site
settings or the working directory cannot change the checked package origin.
Install this src package into that exact venv with `pip install -e .` as described
in Quickstart. There is no root `server.py` or other legacy entrypoint fallback.
Both the code root and `BRIDGE_WORKSPACE` must be explicit absolute, existing
non-bare Git checkout roots; a subdirectory is refused. Package-origin checks use
`python -I -B` and `importlib.util.find_spec`, without importing configured server
code. If invoked with sudo, these user-controlled checks run as the selected
nonroot account with supplementary groups cleared and a minimal environment.

## Linux plan, install, enable and start

Linux Bash, from the approved checkout; replace all sample paths and username:

```bash
bridge_user='your_linux_user'
bridge_repo='/absolute/linux/path/gpt-agent-bridge'
bridge_workspace='/absolute/linux/path/your-git-project'
herdr_bin='/absolute/linux/path/to/herdr'
python3 -I -B "$bridge_repo/scripts/install-bridge-autostart.py" plan \
  --user "$bridge_user" --repo "$bridge_repo" \
  --workspace "$bridge_workspace" --herdr-bin "$herdr_bin" --port 8765 || exit 1
```

Plan validates local inputs without systemctl, network probes, credentials reads,
file writes or service actions. Its paths are configuration, not a scan of running
processes. Verify the workspace is the intended Bridge registration authority;
register each project explicitly as described in [Project setup](CHATGPT-PROJECT-SETUP.md).

Before installation, have the operator stop any foreground Bridge using this
port. This script refuses an occupied listener, an existing adopter unit, an
unknown unit/drop-in, or existing installation files. It never stops/adopts an
unknown process. Before publication it checks the manager's unit lookup paths
against a finite supported list, root directory permissions, disk unit names,
aliases, dependency links (even dangling), and unit/dash-prefix/`service.d`
drop-ins. Foreign or uncertain activation policy is a refusal; it never deletes
such files. This deliberately refuses inherited customization. WSL must already have systemd as PID 1; see
[Microsoft's systemd instructions](https://learn.microsoft.com/windows/wsl/systemd).
The script does not update WSL or edit its configuration.

Each following command is a **separate explicit operator action**. First review
the installer bytes, then copy only that script into an operator-owned private
root directory. The privileged installer refuses a user-owned source script or
a non-private source directory; do not run sudo directly on the user checkout. `install`
requires sudo, generates a new stable capability token once, verifies a staged
unit, and publishes files without overwriting. It does not enable/start the unit.

```bash
installer='/root/gpt-agent-bridge-autostart-setup/installer.py'
# mkdir fails if a prior/unknown setup directory exists: do not overwrite it.
sudo mkdir --mode=0700 -- "$(dirname "$installer")" || exit 1
sudo install -o root -g root -m 0700 "$bridge_repo/scripts/install-bridge-autostart.py" "$installer" || exit 1
# Privately compare this copy with the reviewed source before proceeding.
sudo cmp -- "$bridge_repo/scripts/install-bridge-autostart.py" "$installer" || exit 1
sudo python3 -I -B "$installer" install \
  --user "$bridge_user" --repo "$bridge_repo" \
  --workspace "$bridge_workspace" --herdr-bin "$herdr_bin" --port 8765 || exit 1
```

Proceed only after install reports exact loaded fragment, no extra drop-ins,
inactive state and disabled enablement. Any failure or unknown result stops this
sequence: preserve the published evidence for private operator inspection.
Enable boot startup only as a separate conscious choice:

```bash
sudo python3 -I -B "$installer" enable || exit 1
```

Starting now is another separate choice, after a successful enable result:

```bash
sudo python3 -I -B "$installer" start || exit 1
```

Use a fresh root setup directory; do not overwrite a prior or unknown installer.
The copy commands above are operator actions, not automatic setup. Only run sudo
against the reviewed root-owned copy. Its fixed service template is checked by
SHA256 against the installer before publication. User-owned application code still runs as
the selected nonroot account. The installed root-owned loader and unit are fixed;
runtime configuration is JSON, never sourced as shell code. A root-owned,
readable manifest fixes public runtime paths/identity; owner-writable settings
cannot redirect the launcher, workspace or Herdr path. The capability token is
kept only in the owner-private settings. The installed runner is root-owned. The unit uses
`Restart=on-failure`, a five-second delay and a five-attempt/60-second start limit.
An intentional `stop` stays stopped until an explicit start or next enabled boot.
`disable` removes future boot enablement but does not stop an active service.
`NoNewPrivileges=true` means this v0 does not enable in-product sudo service restart.

## Private token and client handoff

`/var/lib/gpt-agent-bridge-autostart/` has mode 0700, owned by the service user;
`settings.json` has mode 0600 and contains the stable path token. The loader checks
ownership, symlinks, type, hard links and modes before reading it. Only minimal
runtime variables are passed; unrelated shell credentials/proxies are not copied.
Application stdout/stderr go to `null`, because transport diagnostics can contain
secret URLs. Systemd still records unit state. Debugging needs a separately
approved private foreground session after stopping the service, not public logs.

For a deliberate migration retaining an existing token, supply `install --token-file`
with an owner-only 0600 regular file in that user's 0700 directory, containing
only the token. The script never reads a live process or Quickstart handoff.
Otherwise this fresh installation uses a **new** token: an old registered tunnel
URL will not work until deliberately updated. Never generate a second client token.

For the alternative foreground health + Tunnel flow, create an explicit
temporary handoff as the service owner (not sudo). The unattended
[combined route](AUTOSTART.md) reads protected records directly and needs no handoff:

```bash
"$bridge_repo/.venv/bin/python" -I -B /usr/local/lib/gpt-agent-bridge-autostart/runner.py handoff || exit 1
```

It creates the handoff inside the private state directory and prints only its
pathname, not the token or full MCP URL; it never uses a shell's `TMPDIR` checkout.
The file contains exports and must be kept private. Use that pathname in
[Tunnel combined step 4](OPENAI-SECURE-MCP-TUNNEL.md#combined-step-4), from the
same distro and checkout, **instead of generating a token or launching another
Bridge**. That guide sources/deletes the file and keeps health check + tunnel in
the same subshell. Run only one tunnel client; this helper does not start it or
make it persistent. Unused handoffs must be removed by their owner before uninstall.
A tunnel
control-plane key is separate; never place it in this service configuration.

## Read-only status and initialized MCP health

```bash
python3 -I -B "$bridge_repo/scripts/install-bridge-autostart.py" status || exit 1
"$bridge_repo/.venv/bin/python" -I -B /usr/local/lib/gpt-agent-bridge-autostart/runner.py probe || exit 1
```

Status reads systemd state without private config or repair. Probe runs as the
service owner, reads protected settings, enters an MCP client initialize context
and calls only `bridge_health`. It emits bounded categories, never raw transport
exceptions, capability URL, Agent details or Herdr error text:

- `bridge_mcp=initialized_healthy` requires an initialized dictionary response,
  exact `bridge=gpt-agent-bridge`, and Boolean `ok=true` (not a truthy substitute).
- `herdr=reachable` / `unavailable` is reported separately; outer `ok` is not enough.
- `unavailable_or_invalid` / `unknown` means inspect, not automatically retry or restart.
- `work_resume=not_established` always; health is not work completion or resumption.

Probe exits zero when `bridge_mcp=initialized_healthy`, including when Herdr is
`unavailable` or `unknown`; Herdr is a separate nonblocking readiness category.
A missing/invalid initialized Bridge response exits nonzero. It does not start
anything; `bridge_health` may perform Herdr's read-only snapshot. Confirm the
remote ChatGPT App independently; local MCP cannot prove tunnel/host availability.

## Windows owner logon anchor (optional)

Use the owning user's Windows PowerShell 5.1+ on Windows 10 build 19041+ or Windows
11, with WSL2 and ScheduledTasks. This helper does not run as SYSTEM, store passwords,
bypass execution policy, or configure WSL. If local policy prevents scripts/tasks,
stop and get operator approval; do not bypass it. Before Install/Enable, explicitly
open the selected distro and verify its nonroot user and systemd. The helper only
issues read-only checks to an already running distro; Plan never launches one.

Use the actual `wsl -l -v` distro name and actual Linux username; the example is
PowerShell, **not Bash**. Point the script path at your reviewed Windows-accessible
copy of the helper (for example via the distro's `\\wsl.localhost\` share):

```powershell
$helper = '\\wsl.localhost\Ubuntu\home\your_linux_user\gpt-agent-bridge\scripts\install-bridge-wsl-logon-task.ps1'
& $helper -Action Plan -Distro 'Ubuntu' -LinuxUser 'your_linux_user'
if (-not $?) { throw 'Previous helper result failed or is uncertain; stop and inspect.' }
& $helper -Action Install -Distro 'Ubuntu' -LinuxUser 'your_linux_user'
if (-not $?) { throw 'Previous helper result failed or is uncertain; stop and inspect.' }
& $helper -Action Status -Distro 'Ubuntu' -LinuxUser 'your_linux_user'
if (-not $?) { throw 'Previous helper result failed or is uncertain; stop and inspect.' }
& $helper -Action Enable -Distro 'Ubuntu' -LinuxUser 'your_linux_user'
if (-not $?) { throw 'Previous helper result failed or is uncertain; stop and inspect.' }
```

Install uses the documented `New-ScheduledTaskSettingsSet -Disable` and reads
back both XML and task state before reporting **disabled**. Enable/Disable also
read back the requested state and exact owned policy. Enable opts into current-user
logon scheduling; it does not explicitly run the task. Task Scheduler restart can
also trigger matching already-logged-on users, so this is not an absolute promise
of waiting until the next fresh login. The one fixed action directly invokes the system
`wsl.exe --distribution "Ubuntu" --user "your_linux_user" --exec /usr/bin/sleep infinity`.
No shell interpolation, passwords, token or execution bypass enters the task.
It uses current-user LogonTrigger/InteractiveToken/LeastPrivilege, `PT0S`
for **task settings**, `IgnoreNew`, and permits battery operation. This does
not establish a zero effective trigger-specific cap; the helper rejects an
explicit nonzero trigger limit, but an omitted limit still needs real Windows
acceptance. No >72-hour lifetime guarantee is made.
Unknown distro/user, non-WSL2, unknown existing task or unsupported host is refused.
Names containing quotes/backslashes/metacharacters are unsupported rather than guessed.

The anchor is intended to keep WSL active while Linux systemd manages Bridge.
[Microsoft explicitly says systemd services alone do not keep WSL alive](https://learn.microsoft.com/windows/wsl/systemd#how-does-enabling-systemd-affect-wsl-architecture).
The helper rejects unknown task structure, checks description in XML and CIM,
and verifies owner SID, InteractiveToken/LeastPrivilege, battery policy, one
action/trigger/principal and the requested enabled state. An unexpected XML
serialization or HKCU distro registry representation is a refusal, not proven
absence. Task-level `PT0S` does not certify all lifecycle limits; trigger-specific
caps and actual >72-hour logon-triggered execution need acceptance. `IgnoreNew`
only deduplicates instances of this same task, not other task names.

No-window execution, sleep-infinity lifetime, exact registry/task XML compatibility,
logoff and suspend behavior **must be validated on target Windows**. This is not a
pre-login or 24x7 design. Forced WSL shutdown ends the anchor; it does not promise
automatic recovery until another logon. No task restart/reconnect magic is claimed. Logout is not lock/unlock; interactive
session lifetime must not be advertised as continued hosting after logout.
WSL startup may also run preexisting enabled units/boot commands: separately
review distro boot policy. The combined route intentionally enables Tunnel;
Herdr/Agent startup and other existing boot policy remain outside this setup.
Do not install a competing login task that launches the same services.

## Pause, removal and unknown outcomes

```bash
sudo python3 -I -B "$installer" disable || exit 1
sudo python3 -I -B "$installer" stop || exit 1
sudo python3 -I -B "$installer" uninstall || exit 1
```

Uninstall requires disabled + inactive service, matching root-owned installation
files and no extra files in its directories. It removes only this installation,
including its token, and never another unit/config. Service data in your project
is not removed. Pre-publication verification failure cleans only new staged files;
after unit publication an uncertain manager result leaves evidence for inspection.
Cleanup checks recorded inode/type/owner/mode/content and never recursively
deletes unknown files; changed or foreign content is preserved for operator review.
Do not blindly rerun install, overwrite files or retry uncertain service actions.

```powershell
& $helper -Action Disable -Distro 'Ubuntu' -LinuxUser 'your_linux_user' -StopAnchor
if (-not $?) { throw 'Previous helper result failed or is uncertain; stop and inspect.' }
& $helper -Action Uninstall -Distro 'Ubuntu' -LinuxUser 'your_linux_user'
if (-not $?) { throw 'Previous helper result failed or is uncertain; stop and inspect.' }
```

Without `-StopAnchor`, Disable only removes future triggers; a running anchor
continues. Removing a running or queued task requires explicit `-StopAnchor`; unknown
states refuse removal. Uninstall first disables and verifies that state, then
checks task state and COM instance enumeration before unregistering. Optional
StopAnchor also needs disabled/state/zero-instance readback; a stop request alone
is not proof of termination. A refusal is not authorization to retry blindly. This does not
call WSL shutdown or directly stop Linux services. Ending the last anchor may
indirectly permit WSL shutdown and interrupt Bridge; the exact shutdown timing
is unverified. Pause both layers deliberately. A running task alone does not prove
Bridge health. This component task does not directly launch Tunnel/Herdr; in the
combined route systemd starts the separately enabled Tunnel unit.

## Acceptance before relying on persistence

Synthetic tests cover permissions, no-clobber, input safety, unit rendering,
failure gates, secret redaction and initialized-health classification. They do
not exercise real systemd or Windows. Operator acceptance must separately cover
Linux reboot, deliberate stop vs crash, occupied port, unavailable Herdr, missing
tunnel, task disabled/enabled, owner logon/relogon, >72-hour lifetime, no visible
console, battery/suspend/logoff, unknown distro/user and intentional WSL shutdown.
Check Bridge MCP, Herdr and tunnel/ChatGPT independently. Work tokens and running
Agent terminals are process/session state; none of these checks establishes resume.

References: [WSL commands](https://learn.microsoft.com/windows/wsl/basic-commands),
[task execution limit](https://learn.microsoft.com/windows/win32/taskschd/tasksettings-executiontimelimit),
[task principal](https://learn.microsoft.com/powershell/module/scheduledtasks/new-scheduledtaskprincipal).

The unit-policy inventory follows systemd's finite system-manager lookup and
drop-in/dependency rules; custom lookup roots are unsupported rather than guessed.
See [systemd.unit](https://www.freedesktop.org/software/systemd/man/latest/systemd.unit.html).

Official task contracts: [disabled settings construction](https://learn.microsoft.com/powershell/module/scheduledtasks/new-scheduledtasksettingsset),
[LogonTrigger](https://learn.microsoft.com/windows/win32/taskschd/logontrigger),
[interactive logon types](https://learn.microsoft.com/windows/win32/api/taskschd/ne-taskschd-task_logon_type).
These contracts do not establish real Windows acceptance of this helper.
