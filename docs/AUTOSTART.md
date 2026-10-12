# Bridge + Secure MCP Tunnel autostart

Use this route for a one-time, explicitly authorized private setup, followed by
**both Linux services starting at boot**. On Windows + WSL2, one optional owner
logon anchor wakes and holds the same distro while systemd starts both services.
Herdr and Agents remain manual. There is no Work, prompt or session replay.
Source tests do not establish Linux reboot, Windows login or remote ChatGPT
acceptance. No pre-login, logout, suspend or 24x7 guarantee is made.

The [Bridge component guide](BRIDGE-AUTOSTART.md) and
[Tunnel component guide](TUNNEL-AUTOSTART.md) own their security and removal
contracts. The [foreground route](OPENAI-SECURE-MCP-TUNNEL.md) remains available;
choose one route rather than running a foreground client alongside these units.

## 1. Prepare and choose the owner

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
[Herdr compatibility guide](HERDR-COMPATIBILITY.md); reuse a usable installation.
It can be stopped: do not start Herdr just for Bridge readiness. Obtain and independently verify the complete official
[v0.0.16 Tunnel package](OPENAI-SECURE-MCP-TUNNEL.md#3-obtain-and-verify-the-pinned-linux-client),
then have an administrator place it at a trusted root-owned location. The
reviewed binary digest is not proof of official provenance by itself. No
download, Herdr start or account operation is performed by these installers.

**Migration STOP:** existing foreground Bridge/Tunnel, the old adopter unit,
unknown units/drop-ins, prior installation/snapshot directories, occupied ports,
existing Tunnel profiles or required proxy/CA/mTLS settings need an explicit
operator decision first. Nothing inspects process environments, imports keys,
kills processes, changes App bindings or takes over a live deployment.

Run the following complete blocks separately in the same owner's Linux Bash
session, after inspecting the previous result. Replace all examples explicitly:

```bash
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

Compare both plans' user/UID/GID/HOME with your selected values. Plans are
nonsecret, read-only observations; they do not certify runtime readiness.
TTL defaults to 10m; 60m is an explicit alternative, not an infinite connection.

## 2. Define fail-stop observations

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

Review both controllers and production templates first. Do not run a
user-controlled checkout or its venv as root. Copy only reviewed installer
assets to **two new root-private directories**, never overwrite an old snapshot:

```bash
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

Explicitly authorize each install separately. Bridge generates one stable token.
For an authorized existing-token migration use its protected `--token-file`
option; never regenerate a second token for Tunnel. After Bridge install:

```bash
# gate: bridge-install
set -euo pipefail
sudo /usr/bin/python3 -I -B "$bridge_installer" install \
  --user "$bridge_user" --repo "$bridge_repo" --workspace "$bridge_workspace" \
  --herdr-bin "$herdr_bin" --port 8765 || exit 1
require_bridge inactive disabled || exit 1
```

Only after that readback, separately authorize Tunnel install:

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

```bash
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

```bash
# gate: bridge-enable
set -euo pipefail
require_bridge inactive disabled || exit 1
sudo /usr/bin/python3 -I -B "$bridge_installer" enable || exit 1
require_bridge inactive enabled || exit 1
```

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

```bash
# gate: tunnel-enable
set -euo pipefail
require_bridge active enabled || exit 1
require_bridge_health || exit 1
require_tunnel inactive disabled || exit 1
sudo /usr/bin/python3 -I -B "$tunnel_installer" enable || exit 1
require_tunnel inactive enabled || exit 1
```

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

Local Tunnel `ready` is not cloud authentication, remote reachability or Web App
readiness. Separately verify your own account/workspace permissions and
[ChatGPT connection](OPENAI-SECURE-MCP-TUNNEL.md#6-connect-and-install-in-the-correct-chatgpt-project-chat).
Do not update an existing App binding automatically. Open Herdr and Agents
manually when local delegation is needed. Actual boot/login/cloud acceptance
requires a later, separately authorized target-host exercise.

For WSL2 use exactly one optional current-owner-SID anchor, with the same distro
and Linux owner: follow the [Windows anchor steps](BRIDGE-AUTOSTART.md#windows-owner-logon-anchor-optional).
Its Install is disabled; Enable and readback are separate. It holds WSL lifetime
while the **two enabled Linux units** start, not a second Tunnel task. Services
alone do not keep WSL alive. No real Windows/PowerShell execution is proved here.

## Pause and remove deliberately

Disable future boot activation and stop each unit separately, Tunnel before
Bridge. Confirm inactive/disabled with the observations above before each
component uninstall. The Tunnel removal preserves private credential/state
evidence and does not revoke keys; Bridge removal has its own strict inventory
and token-removal contract. See [Tunnel removal](TUNNEL-AUTOSTART.md#provision-privately-then-explicitly-enable-and-start)
and [Bridge removal](BRIDGE-AUTOSTART.md#pause-removal-and-unknown-outcomes).
Do not blindly reinstall or delete unknown/foreign partial publication.
Windows anchor Disable/StopAnchor/Uninstall is a separate layer, not Linux
disable/stop/uninstall; ending the anchor may interrupt both services as WSL exits.
