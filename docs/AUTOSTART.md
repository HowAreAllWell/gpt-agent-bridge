**English** | [简体中文](AUTOSTART.zh-CN.md)

# Bridge + Secure MCP Tunnel autostart

**First installation?** Follow [Getting started](GETTING-STARTED.md), with separate
**native Ubuntu Desktop** and **Windows + WSL2** paths. This page explains what
runs in the background and gives advanced, fresh manual installation and removal steps.
It is not another checklist to run after the normal installer.

## Already completed `./prepare`? Start here

On supported Linux, `./prepare` creates its own application copy and Python
venv, and **installs, enables and starts both services**. Chrome reminder files
are prepared only by the later optional `reminders` action, not default setup.
A venv is that application's private Python package folder. Do not run the manual
install blocks below again or launch a foreground Bridge/Tunnel beside them.
Never use `sudo ./prepare`.

To inspect startup without changing anything, open **Ubuntu Terminal** (native
Ubuntu) or **Ubuntu Bash in the selected WSL2 distribution** (Windows), as your
normal Linux user. These commands can run from any folder:

```bash
systemctl show gpt-agent-bridge-autostart.service -p ActiveState --value
systemctl is-enabled gpt-agent-bridge-autostart.service
systemctl show gpt-agent-bridge-tunnel.service -p ActiveState --value
systemctl is-enabled gpt-agent-bridge-tunnel.service
```

**Expected after a completed preparation:** `active`, `enabled`, `active`,
`enabled`, in that order. This only checks local services. A missing unit, failed
command or different value means inspect that result; do not reinstall, delete
state or repeatedly start it. For `./prepare` installations, preserve the same
release/path and use [Getting started troubleshooting](GETTING-STARTED.md#if-a-step-stops).
Do not point a manually cloned checkout's installer at the prepared application's
managed files. Verify the actual Web connection separately in [step 7](#7-verify-local-state-then-the-operators-chatgpt-connection).

### What automatic startup means

A **service** is a program Linux can run without an open terminal. **systemd** is
the Linux service manager; these installers require it to be the first system
process, **PID 1**. A **unit** is its saved service definition. **Enable** schedules
startup on a later boot; **start** runs it now. **Disable** cancels future boot
startup but does not stop a running program; **stop** ends it now.

| Platform | What starts Bridge and Tunnel | What you still do |
| --- | --- | --- |
| **Native Ubuntu Desktop** | Two enabled systemd services start when Ubuntu boots. No WSL, PowerShell or Windows task is needed. | Use the browser on Ubuntu; start Herdr and your authorized Agents when you need delegation. |
| **Windows + WSL2** | systemd starts the two services when that Linux distribution starts. An optional Windows login helper can open and keep that same distribution running. | Configure the [Windows-only helper](#windows-owner-logon-anchor-optional) deliberately if wanted; start Herdr/Agents yourself. Services alone do not keep WSL alive. |
| **Ubuntu Server / headless** | The same Linux service model is the intended advanced route. | Validate Herdr/Agent session handling separately. A remote browser may use Tunnel tools, but browser reminders cannot be assumed to reach the server's loopback feed. |

Automatic startup does not resume Work, replay prompts, restore Agent terminals
or start Herdr. It depends on the machine being awake and connected.
No pre-login Windows, logout, suspend or 24x7 guarantee is made.

### Need the manual service route instead?

Use [steps 1–7 below](#1-prepare-and-choose-the-owner) only for an explicitly
authorized **fresh manual installation**, after source dependency setup. They
separate planning, installation, private credentials, enablement and start so you
can inspect each result. If any action fails or its result is unknown, stop;
unknown does not mean nothing changed and is not permission to retry.

For security/removal details, read the advanced [Bridge component reference](#bridge-component-contract)
and [Tunnel component reference](#tunnel-component-contract). They are alternatives
to the combined sequence, not extra installations. The [foreground route](QUICKSTART.md#foreground-secure-mcp-tunnel)
is also an alternative; never run a second client alongside a service.

## 1. Prepare and choose the owner

**Where:** Ubuntu Terminal on native Ubuntu, or the selected WSL Ubuntu Bash on
Windows. Use the Linux account that will own this installation, not a root shell.
Keep this same terminal open through steps 1–7: later blocks use its variables
and functions. `set -euo pipefail` makes errors stop the sequence and may close
that shell; if it exits, inspect before reconstructing the state or continuing.

Both platforms need Linux with systemd already running as PID 1. If it is absent,
stop here; these scripts do not configure the OS. Native Ubuntu needs no Windows
helper. On WSL, review [Microsoft's systemd setup](https://learn.microsoft.com/windows/wsl/systemd)
as a separate OS decision.

Complete [Quickstart dependency setup](QUICKSTART.md#2-clone-and-install-direct-dependencies)
in a **durable Linux-home checkout**, with its src package installed into that
checkout's `.venv`. Runtime uses `.venv/bin/python -I -B -m gpt_agent_bridge`.
Choose a durable release checkout and a separate existing Git
workspace if appropriate; both roots must be exact, non-bare Git checkout roots.

Use the same explicit nonroot account, UID, primary GID and HOME throughout.
Code, workspace, home, interpreter/venv/dependencies and selected Herdr binary
must satisfy the component trust checks: root/selected-owner control, no
group/world write, symlinked code/config, hardlinked code or unsafe ancestry.
Bridge paths reject spaces, metacharacters and `/mnt/`; a checked venv Python
symlink is supported. Tunnel's whole-tree scan is stricter about writable
ancestors; a shared `/tmp` deployment is unsuitable. Unsupported paths, lookup
roots or inventory limits mean stop, not loosen permissions or checks.

Select a compatible Herdr v0.9.0 binary using the
[Herdr compatibility guide](QUICKSTART.md#herdr-compatibility-and-version-selection); reuse a usable installation.
It can be stopped: do not start Herdr just for Bridge readiness. Obtain and independently verify the complete official
[v0.0.16 Tunnel package](QUICKSTART.md#3-obtain-and-verify-the-pinned-linux-client),
then have an administrator place it at a trusted root-owned location. The
reviewed binary digest is not proof of official provenance by itself. No
download, Herdr start or account operation is performed by these installers.

**Fresh manual installation only:** existing foreground Bridge/Tunnel, another unit,
unknown units/drop-ins, prior installation/snapshot directories, occupied ports,
existing Tunnel profiles or required proxy/CA/mTLS settings need an explicit
operator decision first. Nothing inspects process environments, imports keys,
kills processes, changes App bindings or takes over a live deployment.

Before the first block, replace **every example** below with your actual values:

| Variable | What to enter |
| --- | --- |
| `bridge_user`, `bridge_home` | Your nonroot Linux login and its home folder, not your Windows username. `id -un` shows the current Linux login. |
| `bridge_repo` | The durable Bridge source folder containing the `.venv` you prepared. |
| `bridge_workspace` | The existing Git project root you intend to authorize; not a subfolder or Windows drive path. It may differ from the source folder. |
| `herdr_bin` | The absolute path to the verified Linux Herdr v0.9.0 executable. |
| `client_binary`, `client_sha256` | The administrator's root-owned verified v0.0.16 client and its independently reviewed **binary** SHA256. Do not paste a key here or substitute a ZIP hash. |
| `bridge_installer`, `tunnel_installer` | Two new private root review paths. Leave them separate and do not reuse existing snapshot directories. |

UID and GID are Linux's numeric user and group identities; the block reads them
from your current account. HOME must match that account. Run complete blocks
separately in this same Bash session and inspect each result before continuing:

```bash
# gate: combined-plans
set -euo pipefail
bridge_user='your_linux_user'
bridge_home='/home/your_linux_user'
bridge_repo='/home/your_linux_user/gpt-agent-bridge'
bridge_workspace='/home/your_linux_user/your-git-project'
herdr_bin='/home/your_linux_user/.local/bin/herdr'
client_binary='/opt/openai-tunnel-client-v0.0.16/tunnel-client'
client_sha256='REPLACE_WITH_INDEPENDENTLY_REVIEWED_BINARY_SHA256'
bridge_installer='/root/gpt-agent-bridge-autostart-setup/installer.py'
tunnel_installer='/root/gpt-agent-bridge-tunnel-review-v1/installer.py'
[[ "$(id -un)" == "$bridge_user" && "$(id -u)" != 0 && "$HOME" == "$bridge_home" ]] || exit 1
bridge_uid="$(id -u)"
bridge_gid="$(id -g)"
[[ "$(getent passwd "$bridge_user" | cut -d: -f6)" == "$bridge_home" ]] || exit 1
/usr/bin/python3 -I -B "$bridge_repo/scripts/install-bridge-autostart.py" plan \
  --user "$bridge_user" --repo "$bridge_repo" --workspace "$bridge_workspace" \
  --herdr-bin "$herdr_bin" --port 8765 || exit 1
/usr/bin/python3 -I -B "$bridge_repo/scripts/install-bridge-tunnel-autostart.py" plan \
  --user "$bridge_user" --client "$client_binary" --client-sha256 "$client_sha256" \
  --health-socket health.sock --ttl 10m || exit 1
```

**Check the result:** both `plan` commands must succeed. Compare their
user/UID/GID/HOME and paths with your intended installation. A missing prerequisite,
placeholder value or refused path means stop and correct the plan before any
installation. Do not relax ownership or permissions to force it through. Plans are
nonsecret, read-only observations; they do not certify runtime readiness.
TTL defaults to 10m; 60m is an explicit alternative, not an infinite connection.

## 2. Define fail-stop observations

In the **same Linux terminal**, paste this complete block to define the
`require_*` helper functions used later. Defining them produces no service
changes and normally no output; later calls compare the actual state with the
expected state and stop on a mismatch. If pasting fails, do not skip these checks.

These shell checks only observe. They are not another installer or supervisor.
Exit zero or `command_completed` from a mutation does **not** establish its
requested state. Missing, false, unknown or transitional observations stop the
sequence. Do not retry a mutation whose effect is uncertain. A bounded read-only
status/probe observation can diagnose startup; no polling loop is prescribed.

```bash
# gate: observations
set -euo pipefail
require_unit_policy() {
  local observed
  observed="$(/usr/bin/systemctl show "$1" -p LoadState --value)" || return 1
  [[ "$observed" == loaded ]] || return 1
  observed="$(/usr/bin/systemctl show "$1" -p FragmentPath --value)" || return 1
  [[ "$observed" == "/etc/systemd/system/$1" ]] || return 1
  observed="$(/usr/bin/systemctl show "$1" -p DropInPaths --value)" || return 1
  [[ -z "$observed" ]]
}
require_bridge() {
  require_unit_policy gpt-agent-bridge-autostart.service || return 1
  sudo /usr/bin/python3 -I -B "$bridge_installer" status |
    /usr/bin/python3 -I -B -c 'import json,sys; d=json.load(sys.stdin); raise SystemExit(0 if isinstance(d,dict) and d.get("service")==sys.argv[1] and d.get("enabled")==sys.argv[2] else 1)' "$1" "$2"
}
require_bridge_health() {
  "$bridge_repo/.venv/bin/python" -I -B /usr/local/lib/gpt-agent-bridge-autostart/runner.py probe |
    /usr/bin/python3 -I -B -c 'import json,sys; d=json.load(sys.stdin); raise SystemExit(0 if isinstance(d,dict) and d.get("bridge_mcp")=="initialized_healthy" and d.get("herdr") in ("reachable","unavailable","unknown") and d.get("work_resume")=="not_established" else 1)'
}
require_tunnel() {
  require_unit_policy gpt-agent-bridge-tunnel.service || return 1
  /usr/bin/python3 -I -B /usr/local/lib/gpt-agent-bridge-tunnel-autostart/runner.py status |
    /usr/bin/python3 -I -B -c 'import json,sys; d=json.load(sys.stdin); raise SystemExit(0 if isinstance(d,dict) and d.get("process")==sys.argv[1] and d.get("boot_activation")==sys.argv[2] and (not sys.argv[3] or d.get("tunnel_startup")==sys.argv[3]) else 1)' "$1" "$2" "${3:-}"
}
```

The initialized Bridge probe checks exact identity and Boolean `ok=true`;
`ok=1` is invalid. Herdr unavailable does not block this route. Install also
performs its own exact fragment/drop-in/disabled/inactive checks before success.
The observations above additionally guard the boundaries between operator stages.

## 3. Review separate privileged snapshots

In the **same Linux terminal**, review both installer scripts and their service
templates before approving administrator access. A snapshot here means a fixed
copy of those reviewed files, kept apart from your editable checkout. The block
below **creates and copies files as root**; `cmp` silently succeeds when each
copy matches. A password prompt is for your OS's sudo approval, not a Tunnel key.
If a directory already exists or any copy/compare fails, stop and preserve it;
do not remove it or continue with only the remaining commands.

Review both controllers and production templates first. Do not run a
user-controlled checkout or its venv as root. Copy only reviewed installer
assets to **two new root-private directories**, never overwrite an old snapshot:

```bash
# gate: combined-snapshots
set -euo pipefail
sudo mkdir -m 0700 -- "$(dirname "$bridge_installer")" || exit 1
sudo /usr/bin/install -o root -g root -m 0700 "$bridge_repo/scripts/install-bridge-autostart.py" "$bridge_installer" || exit 1
sudo /usr/bin/cmp -- "$bridge_repo/scripts/install-bridge-autostart.py" "$bridge_installer" || exit 1
sudo mkdir -m 0700 -- "$(dirname "$tunnel_installer")" || exit 1
sudo /usr/bin/install -o root -g root -m 0600 "$bridge_repo/scripts/install-bridge-tunnel-autostart.py" "$tunnel_installer" || exit 1
sudo /usr/bin/install -o root -g root -m 0600 "$bridge_repo/systemd/gpt-agent-bridge-tunnel.service.template" "$(dirname "$tunnel_installer")/service.template" || exit 1
sudo /usr/bin/cmp -- "$bridge_repo/scripts/install-bridge-tunnel-autostart.py" "$tunnel_installer" || exit 1
sudo /usr/bin/cmp -- "$bridge_repo/systemd/gpt-agent-bridge-tunnel.service.template" "$(dirname "$tunnel_installer")/service.template" || exit 1
```

Compare bytes/digests privately with the approved release. Bridge validates its
fixed template hash from the selected code root. These copy actions grant no
installation permission by themselves.

## 4. Install disabled and inactive, then configure privately

Explicitly authorize each install separately. Bridge generates one stable token;
Tunnel reuses it rather than generating a second token. In the **same Linux terminal**,
the first block installs Bridge files and checks **inactive + disabled**: installed,
but neither running now nor scheduled for boot. That is the expected result of
this manual stage, unlike the full `./prepare` flow. Failure or an unknown
readback means stop before Tunnel installation:

```bash
# gate: bridge-install
set -euo pipefail
sudo /usr/bin/python3 -I -B "$bridge_installer" install \
  --user "$bridge_user" --repo "$bridge_repo" --workspace "$bridge_workspace" \
  --herdr-bin "$herdr_bin" --port 8765 || exit 1
require_bridge inactive disabled || exit 1
```

Only after that readback, separately authorize Tunnel install in the same
terminal. Expect Tunnel to be **inactive + disabled** too. If its readback fails,
stop before credential entry; do not rerun either installation:

```bash
# gate: tunnel-install
set -euo pipefail
require_bridge inactive disabled || exit 1
sudo /usr/bin/python3 -I -B "$tunnel_installer" install \
  --user "$bridge_user" --client "$client_binary" --client-sha256 "$client_sha256" \
  --health-socket health.sock --ttl 10m || exit 1
require_tunnel inactive disabled || exit 1
```

Their unit, manifest, loader, state and root snapshot paths are independent;
see the component file tables. Configure as the **same owner**, without sudo,
using a private TTY. Privately enter your own Tunnel ID and runtime key. This
key is separate from Bridge's token and from model API reasoning charges.
A private TTY means an interactive terminal you control, without screen sharing
or recording. At the two hidden prompts, enter your own Tunnel ID and runtime
key; typing will not be echoed. Do not put them into the code block, Chat or a
tracked file. Expect configuration to finish while Tunnel remains inactive and
disabled; missing prompts, refusal or a failed check means stop.

```bash
# gate: combined-configure
set -euo pipefail
[[ "$(id -u)" == "$bridge_uid" && "$(id -g)" == "$bridge_gid" && "$HOME" == "$bridge_home" ]] || exit 1
/usr/bin/python3 -I -B /usr/local/lib/gpt-agent-bridge-tunnel-autostart/runner.py configure || exit 1
require_tunnel inactive disabled || exit 1
```

No key enters argv, a repository snippet or public logs. Tunnel reads Bridge's
protected manifest/settings at runtime and builds the capability URL in memory;
there is no second token store or saved duplicate backend URL. Current Tunnel
install/configure/enable/start do not prevalidate Bridge contract: runtime does.
The ordering/checks here are explicit operator gates, not a hidden CLI guarantee.

## 5. Opt into Bridge boot activation and start

Enablement and immediate start are distinct choices. Each block below requires
its own explicit authorization. Do not enter the next block after a failed check.
In the **same Linux terminal**, the first block enables Bridge for boot. Expect
**inactive + enabled**; it should not be running yet:

```bash
# gate: bridge-enable
set -euo pipefail
require_bridge inactive disabled || exit 1
sudo /usr/bin/python3 -I -B "$bridge_installer" enable || exit 1
require_bridge inactive enabled || exit 1
```

Next, in the same terminal, the following block **starts Bridge now**. Expect
**active + enabled** and a successful initialized health probe. If it fails,
observe status privately before any repair; do not launch a foreground copy.

```bash
# gate: bridge-start
set -euo pipefail
require_bridge inactive enabled || exit 1
sudo /usr/bin/python3 -I -B "$bridge_installer" start || exit 1
require_bridge active enabled || exit 1
require_bridge_health || exit 1
```

Stop here unless initialized Bridge health is established. Herdr need not be
running. A failed/pending check is not permission to start another Bridge or
blindly reissue start.

## 6. Opt into Tunnel boot activation and start

Stay in the **same Linux terminal**. The first block checks the working Bridge
and enables Tunnel for boot. Expect Tunnel **inactive + enabled**; this does not
start it yet. A failed check stops the sequence.

```bash
# gate: tunnel-enable
set -euo pipefail
require_bridge active enabled || exit 1
require_bridge_health || exit 1
require_tunnel inactive disabled || exit 1
sudo /usr/bin/python3 -I -B "$tunnel_installer" enable || exit 1
require_tunnel inactive enabled || exit 1
```

Only then, separately approve starting Tunnel now. The next block expects
**active + enabled + ready**. If startup is pending or unknown, stop and inspect
as explained below; do not repeatedly send start commands.

```bash
# gate: tunnel-start
set -euo pipefail
require_bridge active enabled || exit 1
require_bridge_health || exit 1
require_tunnel inactive enabled || exit 1
sudo /usr/bin/python3 -I -B "$tunnel_installer" start || exit 1
require_tunnel active enabled ready || exit 1
```

Startup may still be pending when start returns. A pending/unknown observation
stops this sequence; preserve evidence and diagnose with bounded read-only
status, not another start. The unit has `After=Bridge network-online.target`
without `Wants`, `Requires` or `BindsTo`; neither service starts Herdr or Agents.
Both units must be enabled independently. Restarts do not restore Work.

## 7. Verify local state, then the operator's ChatGPT connection

**Local check:** in the same Linux terminal, the earlier observations must show
both services active and enabled. Local Tunnel `ready` is not cloud authentication,
remote reachability or Web App readiness.

**Browser check:** open your intended **ordinary ChatGPT Web Project Chat**, use
the already authorized Bridge App and request only read-only `bridge_health`.
Check tool discovery and all four native Skills separately using Getting started.
Work/local Codex success or four blue settings toggles are not proof of discovery
in this Chat. This target does not enforce host-side Web-only visibility.

Separately verify your own account/workspace permissions and
[ChatGPT connection](GETTING-STARTED.md#5-connect-the-tunnel-to-your-private-chatgpt-plugin).
Do not update an existing App binding automatically. Open Herdr and Agents
manually when local delegation is needed.

**Native Ubuntu:** skip the Windows helper below. Two enabled units are intended
to start at Ubuntu boot.

**Windows + WSL2 only:** use exactly one optional current-owner-SID anchor, with the same distro
and Linux owner: follow the [Windows anchor steps](#windows-owner-logon-anchor-optional).
Its Install is disabled; Enable and readback are separate. It holds WSL lifetime
while the **two enabled Linux units** start, not a second Tunnel task. Services
alone do not keep WSL alive.

## Pause and remove deliberately

**Choose the effect before running stop/removal commands.** Stop ends a process now;
disable prevents later automatic starts. Removing files is a separate step, not
a way to repair an uncertain start. Record sanitized status first and retain
private evidence; do not publish token-bearing diagnostics.

Disable future boot activation and stop each unit separately, Tunnel before
Bridge. Confirm inactive/disabled with the observations above before each
component uninstall. The Tunnel removal preserves private credential/state
evidence and does not revoke keys; Bridge removal has its own strict inventory
and token-removal contract. See [Tunnel removal](#provision-privately-then-explicitly-enable-and-start)
and [Bridge removal](#pause-removal-and-unknown-outcomes).
Do not blindly reinstall or delete unknown/foreign partial publication.
Windows anchor Disable/StopAnchor/Uninstall is a separate layer, not Linux
disable/stop/uninstall; ending the anchor may interrupt both services as WSL exits.

## Bridge component contract

**Advanced reference — not another newcomer checklist.** Stay with the route
you chose above. The details below explain the exact checks and stored files for
maintainers or operators reviewing a manual change.

The following component-only reference is an alternative to the combined steps,
not a second installation to perform afterward. Each enable/start/removal command
is separately authorized; stop on a failed or unknown result.

### Choose the correct installer

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
[Herdr compatibility guide](QUICKSTART.md#herdr-compatibility-and-version-selection) and reuse a usable install.

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

### Linux plan, install, enable and start

In **Ubuntu Terminal / WSL Ubuntu Bash**, use your normal owner account at the
approved Bridge checkout root. This is the component-only route, not a follow-up
to `./prepare` or the combined installation. Replace every sample path and
username. The next block only plans; expect a successful plan for the chosen
owner and paths. Stop on missing input or refusal:

```bash
# gate: component-bridge-plan
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
connect each project explicitly through [Getting started: connect your project](GETTING-STARTED.md#8-connect-your-existing-git-repository-and-merge-its-binding).

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
# gate: component-bridge-install
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
# gate: component-bridge-enable
sudo python3 -I -B "$installer" enable || exit 1
```

Starting now is another separate choice, after a successful enable result:

```bash
# gate: component-bridge-start
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

### Private token and client handoff

`/var/lib/gpt-agent-bridge-autostart/` has mode 0700, owned by the service user;
`settings.json` has mode 0600 and contains the stable path token. The loader checks
ownership, symlinks, type, hard links and modes before reading it. Only minimal
runtime variables are passed; unrelated shell credentials/proxies are not copied.
Application stdout/stderr go to `null`, because transport diagnostics can contain
secret URLs. Systemd still records unit state. Debugging needs a separately
approved private foreground session after stopping the service, not public logs.

A fresh installation generates one stable token. Tunnel uses that same token;
never generate a second client token.

For the alternative foreground health + Tunnel flow, create an explicit
temporary handoff as the service owner (not sudo). The unattended
[combined route](#1-prepare-and-choose-the-owner) reads protected records directly and needs no handoff:

```bash
# gate: component-bridge-handoff
"$bridge_repo/.venv/bin/python" -I -B /usr/local/lib/gpt-agent-bridge-autostart/runner.py handoff || exit 1
```

It creates the handoff inside the private state directory and prints only its
pathname, not the token or full MCP URL; it never uses a shell's `TMPDIR` checkout.
The file contains exports and must be kept private. Use that pathname in
[Tunnel combined step 4](QUICKSTART.md#combined-step-4), from the
same distro and checkout, **instead of generating a token or launching another
Bridge**. That guide sources/deletes the file and keeps health check + tunnel in
the same subshell. Run only one tunnel client; this helper does not start it or
make it persistent. Unused handoffs must be removed by their owner before uninstall.
A tunnel
control-plane key is separate; never place it in this service configuration.

### Read-only status and initialized MCP health

For the **manual installation described here**, use the same owner's Ubuntu
Terminal / WSL Ubuntu Bash with `bridge_repo` still set to the installed code
root. The first command observes service state; the second calls local read-only
`bridge_health`. Neither starts or repairs anything. Check the output categories
below; missing/invalid results require inspection, not a restart.

```bash
# gate: component-bridge-status
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

### Windows owner logon anchor (optional)

**Native Ubuntu Desktop/Server: skip this entire subsection.** An anchor here
means a Windows login task whose only job is keeping the selected WSL distribution
open. It is not the Linux service installer. Already have this task? Use its
reviewed Status and inspect it; do not run Install again.

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
# gate: component-windows-anchor
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

### Pause, removal and unknown outcomes

For a **manual Bridge installation**, in the Linux Bash session retaining
`installer`, this block disables future boot startup, stops Bridge now, then
removes only the recognized installation and its token. Stop/remove Tunnel first
as described above. Run only after approving all three effects. Each failure
stops the sequence; do not delete leftovers or treat a partial result as rollback.

```bash
# gate: component-bridge-remove
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

**Windows only, in the same owner's PowerShell** with `$helper` pointing to the
reviewed script: this block disables and stops the login anchor, then removes
the recognized task. Expect its verified disabled/stopped state before removal.
If state is unknown, stop; it is not safe to unregister a guessed task.

```powershell
# gate: component-windows-remove
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

### Acceptance before relying on persistence

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

## Tunnel component contract

This component reference uses its own reviewed snapshot variables. Do not run
its install sequence after the combined sequence, and never run a foreground
client alongside this companion.

<a id="two-linux-services-one-wsl-anchor"></a>

### Two Linux services; optional Windows WSL helper

**Native Ubuntu:** systemd manages both units directly. No Windows helper is
needed on Desktop or Server. **Windows + WSL2:** the extra login helper is for
WSL lifetime only, as described below.

The service is `gpt-agent-bridge-tunnel.service`, separate from
`gpt-agent-bridge-autostart.service`. Both must be explicitly enabled in the same
Linux distro. **On Windows + WSL2**, the existing current-owner logon task wakes and keeps
that distro alive; no additional Windows task is needed on Windows. Systemd services alone
do not keep WSL alive. This is an after-owner-login design, not a promise of
availability before login or while Windows is asleep.

The Tunnel unit has `After=Bridge network-online.target`, but **no Wants,
Requires or Herdr dependency**. Starting it does not start Bridge. Its owner-side
launcher waits up to 60 seconds for initialized MCP and a valid `bridge_health`
result with exact Bridge identity and **`ok` equal to Boolean true**;
`herdr.status=unavailable` is acceptable. Connectivity/initialize timeout is
transient: the service retries after ten seconds without a short start-burst
cutoff. Malformed responses, tool errors, wrong identity, missing/false/nonboolean
`ok`, or invalid local configuration refuse with exit 78. A lock held by
the launcher prevents a second companion instance during the child lifetime.

Only verified OpenAI `tunnel-client` **v0.0.16** is accepted. The client handles
control-plane polling retries itself. Process supervision handles unexpected
client exits. `network-online.target`, systemd `active`, and client `/readyz`
do not prove remote authorization or usable ChatGPT access. In particular,
v0.0.16 can report startup ready after an MCP probe timeout. Status reports those
limits explicitly; it does not inspect remote account state.

### Security and stored files

The root-owned installation contains a loader, a unit, and a nonsecret manifest:

| File | Owner and mode | Purpose |
| --- | --- | --- |
| `/usr/local/lib/gpt-agent-bridge-tunnel-autostart/runner.py` | root, 0644 | Nonroot runtime; root provenance checked |
| `/usr/local/lib/gpt-agent-bridge-tunnel-autostart/installation.json` | root, 0644 | Exact owner, client hash/version and installed hashes |
| `/etc/systemd/system/gpt-agent-bridge-tunnel.service` | root, 0644 | No inline secrets |
| `/var/lib/gpt-agent-bridge-tunnel-autostart/credentials.json` | selected nonroot owner, 0600 | User's own Tunnel ID and runtime key |
| `/var/lib/gpt-agent-bridge-tunnel-autostart/runtime.lock` | selected nonroot owner, 0600 | Companion instance lock |

The private state directory is 0700. The unit creates a separate 0700 runtime
directory under `/run/gpt-agent-bridge-tunnel-autostart`; the selected private
Unix health socket lives there. It never uses an assumed-free TCP 8080. An
existing socket/path is refused. Systemd removes its runtime directory on stop;
an externally left or unmanaged object requires operator review, not automatic
deletion.

The existing Bridge token remains only in Bridge's protected settings. The
launcher composes the loopback `/mcp/<token>` URL in memory, passes it to the
MCP readiness subprocess through stdin, and to the Tunnel through its minimal
environment. Tunnel ID/key are never command-line arguments. Child argv is just
the verified absolute client path and `run`.

The environment contains only HOME, PATH, LANG, CONTROL_PLANE_TUNNEL_ID,
CONTROL_PLANE_API_KEY, MCP_SERVER_URL, HEALTH_UNIX_SOCKET and
MCP_CONNECTION_MAX_TTL. There is no OPENAI_API_KEY fallback, inherited profile,
proxy, certificate, debug or shell environment. An enterprise deployment that
needs proxy/CA/mTLS configuration requires a separate reviewed extension; do not
discard an existing deployment's settings to make this minimal route fit.

Raw **Tunnel client** stdout/stderr are discarded and core dumps disabled.
The companion runner emits only fixed nonsecret result/reason codes to the
system journal; its stderr is discarded. Controller errors also use fixed reason
codes. The owner-side health reader discards raw readiness reasons.
Environment delivery does **not** hide credentials from root or the same Linux
account. A future supported-systemd LoadCredential integration can improve
delivery but must still accommodate this client's runtime environment interface.

### Prepare a reviewed installation (operator actions only)

Installation, enablement and starting each need explicit operator
authorization. Synthetic tests do not execute these commands against a real
service installation.

First obtain and verify the exact official v0.0.16 package using the
[manual guide's package verification](QUICKSTART.md#3-obtain-and-verify-the-pinned-linux-client).
An administrator must place a reviewed copy of that complete package in a fresh
root-owned directory, for example `/opt/openai-tunnel-client-v0.0.16`. Preserve
the original user-owned package and any running Tunnel. All selected binary
parents must be root-owned and not group/world writable; symlinks and hardlinks
are refused, as are setuid/setgid bits and file capabilities. The CLI requires
the independently reviewed binary SHA256, not a
claim that hashing any local file proves official origin. No download occurs
inside this installer. Version observation runs only as the nonroot owner.

For this **component-only route**, in the owner's **Ubuntu Terminal / WSL Ubuntu
Bash**, change to the reviewed Bridge source root. Keep this shell open for later
variables. Replace the example client path and binary digest. The next command
only plans; expect the intended owner, client and digest, or stop on refusal:

```bash
# gate: component-tunnel-plan
set -euo pipefail
owner_name="$(id -un)" || exit 1
client_binary=/opt/openai-tunnel-client-v0.0.16/tunnel-client
# Set this to the binary digest from your verified package review, not a token.
client_sha256=REPLACE_WITH_REVIEWED_BINARY_SHA256
/usr/bin/python3 -I -B scripts/install-bridge-tunnel-autostart.py plan \
  --user "$owner_name" --client "$client_binary" \
  --client-sha256 "$client_sha256" --health-socket health.sock --ttl 10m || exit 1
```

Plan hashes regular nonsecret binary bytes but does not execute it, read
credentials, contact services/network, or write files. It marks the Bridge
adapter and nonroot version observation as unverified.

Never run a user-owned checkout or its venv as root. For privileged management,
copy the two reviewed assets to a **new** root-owned 0700 review directory. Run
each complete block as a separate stage in the same Bash session, and inspect
its result before continuing. If any command fails, stop and review unknown
effects; do not continue with later blocks or retry blindly. Never cherry-pick
copy commands around a failed mkdir. The
controller requires itself and the adjacent `service.template` to be root-owned
0600, with trusted non-writable ancestry:

```bash
# gate: component-tunnel-snapshot
set -euo pipefail
# mkdir refuses an existing review directory; do not retry blindly.
sudo mkdir -m 0700 /root/gpt-agent-bridge-tunnel-review-v1 || exit 1
sudo /usr/bin/install -m 0600 scripts/install-bridge-tunnel-autostart.py \
  /root/gpt-agent-bridge-tunnel-review-v1/installer.py || exit 1
sudo /usr/bin/install -m 0600 systemd/gpt-agent-bridge-tunnel.service.template \
  /root/gpt-agent-bridge-tunnel-review-v1/service.template || exit 1
sudo /usr/bin/cmp -- scripts/install-bridge-tunnel-autostart.py \
  /root/gpt-agent-bridge-tunnel-review-v1/installer.py || exit 1
sudo /usr/bin/cmp -- systemd/gpt-agent-bridge-tunnel.service.template \
  /root/gpt-agent-bridge-tunnel-review-v1/service.template || exit 1
```

Compare those exact snapshot bytes with the independently reviewed candidate
and recorded hashes before executing privileged code. Copy/compare success is
not installation authorization. Installation is a separate stage; the nonsecret
owner/client/hash variables from plan must still be set:

```bash
# gate: component-tunnel-install
set -euo pipefail
sudo /usr/bin/python3 -I -B /root/gpt-agent-bridge-tunnel-review-v1/installer.py install \
  --user "$owner_name" --client "$client_binary" --client-sha256 "$client_sha256" \
  --health-socket health.sock --ttl 10m || exit 1
```

Install enumerates the manager's UnitPath and supported persistent/runtime/vendor
paths before staging. Absent optional systemd directories are skipped; present
symlinks, permission-denied paths and real conflicts still refuse. It refuses
aliases, stale target wants/requires links,
exact/dash-prefix/per-type inherited drop-ins, unsafe ancestry and existing paths.
Unpublished `service.d` configuration and unknown discovery conditions are HOLD.
It verifies the staged unit with systemd-analyze, publishes
new files without replacement, reloads unit discovery, and checks disabled and
inactive state. It does not enable or start anything. On mutation uncertainty,
published files remain as evidence; cleanup deletes only proven owned staging
objects. Do not retry or delete unknown partial state automatically.

### Provision privately, then explicitly enable and start

The user must already have their own Tunnel ID (`tunnel_` plus exactly 32
lowercase ASCII letters/digits), runtime API key, and eligible account/workspace
permissions. In **Ubuntu Terminal / WSL Ubuntu Bash**, provision as the configured
nonroot owner using a private interactive terminal, not sudo. Expect two hidden
prompts and successful configuration; absent prompts or refusal mean stop. This
stores credentials locally but does not check cloud permissions or start Tunnel:

```bash
# gate: component-tunnel-configure
set -euo pipefail
/usr/bin/python3 -I -B /usr/local/lib/gpt-agent-bridge-tunnel-autostart/runner.py configure || exit 1
```

Both inputs are hidden. Non-TTY input and getpass fallback are refused. No
trimming or inferred identity is performed. Optionally, `configure
--credentials-file /absolute/private/input.json` reads an owner-owned 0600
regular file in a 0700 directory with exactly `tunnel_id` and `runtime_api_key`.
That input is created privately by the user, never in a Git checkout. The local
runtime-key bound is 16–4096 ASCII letters/digits/underscore/hyphen only; it is an
input safety limit, not proof of provider validity. Configure does not overwrite
credentials, start a service, register anything, or verify remote permissions.

Only after the separately installed Bridge contract is verified, and any old
Tunnel manager has been explicitly resolved by its owner:

```bash
# gate: component-tunnel-enable
set -euo pipefail
sudo /usr/bin/python3 -I -B /root/gpt-agent-bridge-tunnel-review-v1/installer.py enable || exit 1
```

Inspect the enablement result. Immediate start is a separate authorized stage:

```bash
# gate: component-tunnel-start
set -euo pipefail
# Starting now is a separate explicit action, not implied by enabling at boot.
sudo /usr/bin/python3 -I -B /root/gpt-agent-bridge-tunnel-review-v1/installer.py start || exit 1
```

In the **same Linux terminal**, observe the result separately. Expect the
service's process/boot/startup categories; unknown or pending values require
inspection, not replay of start. Status is not a connection acceptance test:

```bash
# gate: component-tunnel-status
set -euo pipefail
/usr/bin/python3 -I -B /usr/local/lib/gpt-agent-bridge-tunnel-autostart/runner.py status || exit 1
```

Bridge boot enablement remains a separate action in its reviewed installer.
With both Linux units enabled, native Ubuntu is intended to start them at boot
without a foreground terminal. **On Windows only**, the WSL owner anchor is an
additional choice for waking/holding the distribution after login. This still needs
real Linux and WSL reboot acceptance. Herdr availability and Agent readiness are
checked manually before delegation.

`stop`, `disable` and `uninstall` are explicit actions through the same reviewed
privileged snapshot. Stop affects only this Tunnel unit; disable affects only
its boot activation. Uninstall requires disabled/inactive state and exact known
code inventory. Captured original inodes remain open; each object is rechecked
for identity, owner, mode, link count and exact bytes, moved to private quarantine,
then checked again before unlink. Replacements and unknown quarantine contents
remain for operator review. It preserves private credentials/lock/state and
does not revoke the key or alter the App. Preserved state deliberately prevents
blind fresh reinstallation.

### Bridge contract adapter and remaining acceptance

The adapter expects root-owned 0644
`/usr/local/lib/gpt-agent-bridge-autostart/installation.json` with a nonsecret
`format`, `plan`, `unit_sha256` and `runner_sha256`, exactly those four fields, and the
selected owner's 0600
`/var/lib/gpt-agent-bridge-autostart/settings.json` under a 0700 private parent.
The settings must equal the complete manifest plan plus only `token`.
The exact plan fields are format, user, uid, gid, home, repo, workspace,
herdr_bin, port and entrypoint. Matching owner fields include user, uid, gid,
home and `entrypoint=module`;
settings also require integer port, absolute repo and a 32–256 character path
token. Manifest and plan must use the independently verified Bridge format
identifier `gpt-agent-bridge-autostart-v1`, directly verified against the frozen
Bridge installer with SHA256
`17ef82d1f6ac15fd91cc5061f187857391117bb06946cf92f30cc61e4668eb12`.
Unknown formats refuse; the adapter never infers one from a private settings file.
Known root-owned Bridge runner/unit hashes are verified **before reading the
token**. The adapter derives
`repo/.venv/bin/python` for the initialized MCP subprocess. Only this venv
interpreter seam permits a resolved Python symlink; its ancestry and target are
checked. Before every interpreter invocation, a root/selected-owner metadata
walk revalidates the entire source/venv code tree, including site-packages and
dependency `.pth` files. It rejects group/world-writable or foreign-owned entries,
unsafe files/hardlinks and external symlinks other than checked Python aliases.
The bound is 30,000 entries and a ten-second scan budget. Top-level `.git`,
`.principal` and actual `.app.json` are excluded non-code state and never opened;
symlinks into that state refuse. The initializer must be inert string/docstring
statements. Isolated nonroot find_spec must resolve this checkout's src package
without importing the server. No source or Bridge settings are modified.

The source marker and writer schema are checked by a cross-component synthetic
test. That test invokes the actual
frozen installer with host/privilege/service operations mocked and all outputs
routed into a temporary sandbox, then feeds its generated records, settings,
runner and unit bytes through the actual Tunnel adapter. It verifies the exact
plan, recorded hashes and unchanged token without persisting a backend URL.
In this source tree the tests use its own hash-verified Bridge controller
by default, without opt-in skips. `BRIDGE_FROZEN_INSTALLER_SOURCE` optionally
selects an explicit source with the same pinned hash. Combined regressions also
use both immutable production templates; host operations and ownership remain
synthetic, while actual publication/adapter/policy checks run. This does **not** establish live Bridge/real Tunnel
acceptance. Independent review and target-host acceptance are required before relying on
a deployed installation. A mismatch is HOLD, not
permission to invent a token, widen permissions, guess an alternative path or
copy secrets elsewhere.

The default TTL is the tagged client's 10 minutes. `--ttl 60m` is an explicit
alternative; neither value makes a connection infinite or restores Work. The
existing YAML TTL staging script is not called. Polling can recover after a
network failure; revoked credentials need deliberate user action.

Fresh installation uses only new state. Existing users must preserve their
exact binding, existing Bridge token and needed private configuration. No
automatic profile import, live process inspection, stop, takeover, key creation,
reauthorization or App installation is implemented. A runtime lock and local
unit/socket checks cannot prove that another unmanaged or remote client does
not use the same Tunnel identity.

Synthetic tests exercise guarded lifecycle actions, no-clobber/identity races,
staging SIGHUP/TERM behavior, hidden provisioning, exact env, Bridge initialization
and unavailable Herdr. They do not establish real systemd compatibility, package
resource integrity, interrupted-request recovery, Windows reboot/login behavior,
Platform authorization or ChatGPT connection acceptance. Those are independent
review and explicitly authorized isolated acceptance gates before deployment.

### Official references

- [OpenAI Secure MCP Tunnels](https://developers.openai.com/api/docs/guides/secure-mcp-tunnels)
- [v0.0.16 systemd deployment pattern](https://github.com/openai/tunnel-client/blob/v0.0.16/docs/deployment/systemd-vm.md)
- [v0.0.16 environment configuration and TTL](https://github.com/openai/tunnel-client/blob/v0.0.16/pkg/runtimeconfig/config.go)
- [v0.0.16 polling retries](https://github.com/openai/tunnel-client/blob/v0.0.16/pkg/controlplane/internal/poller.go)
- [v0.0.16 readiness semantics](https://github.com/openai/tunnel-client/blob/v0.0.16/pkg/runtimehealth/health.go)
- [Microsoft WSL systemd and instance lifetime](https://learn.microsoft.com/en-us/windows/wsl/systemd)
