# Secure MCP Tunnel autostart companion

Use the combined guide to configure **Bridge and your personal OpenAI Secure
MCP Tunnel** to start after Linux reboot, or Windows reboot followed by the configured
owner's WSL2 login. Herdr and CLI Agent sessions stay manual. No unfinished Work
is resumed. The companion does not install a Plugin, create a Tunnel or key,
change account permissions, or configure model API billing.

**Target-host acceptance is still required.** The Bridge first-install installer
is a separate component. Combined synthetic tests check its settings contract
against this adapter; they do not establish real reboot, login or cloud
behavior. Review and explicitly authorize each installation stage. Do not
use these instructions to take over an existing running Tunnel. The manual
[Secure MCP Tunnel guide](OPENAI-SECURE-MCP-TUNNEL.md) remains the supported
foreground alternative.

For a coherent two-service setup, start with [the combined first-use guide](AUTOSTART.md).
This page owns the Tunnel component details; the foreground route remains an
alternative. Neither route is a live boot/cloud acceptance claim.

## Two Linux services, one WSL anchor

The service is `gpt-agent-bridge-tunnel.service`, separate from
`gpt-agent-bridge-autostart.service`. Both must be explicitly enabled in the same
Linux distro. The existing Windows current-owner WSL2 logon task wakes and keeps
that distro alive; no additional Windows task is needed. Systemd services alone
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

## Security and stored files

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

Raw stdout/stderr are discarded, core dumps disabled, and controller errors use
fixed reason codes. The owner-side health reader discards raw readiness reasons.
Environment delivery does **not** hide credentials from root or the same Linux
account. A future supported-systemd LoadCredential integration can improve
delivery but must still accommodate this client's runtime environment interface.

## Prepare a reviewed installation (operator actions only)

Installation, enablement, starting and migration each need explicit operator
authorization. Synthetic tests do not execute these commands against a real
service installation.

First obtain and verify the exact official v0.0.16 package using the
[manual guide's package verification](OPENAI-SECURE-MCP-TUNNEL.md#3-obtain-and-verify-the-pinned-linux-client).
An administrator must place a reviewed copy of that complete package in a fresh
root-owned directory, for example `/opt/openai-tunnel-client-v0.0.16`. Preserve
the original user-owned package and any running Tunnel. All selected binary
parents must be root-owned and not group/world writable; symlinks and hardlinks
are refused, as are setuid/setgid bits and file capabilities. The CLI requires
the independently reviewed binary SHA256, not a
claim that hashing any local file proves official origin. No download occurs
inside this installer. Version observation runs only as the nonroot owner.

From the reviewed source checkout, a read-only plan is:

```bash
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
set -euo pipefail
sudo /usr/bin/python3 -I -B /root/gpt-agent-bridge-tunnel-review-v1/installer.py install \
  --user "$owner_name" --client "$client_binary" --client-sha256 "$client_sha256" \
  --health-socket health.sock --ttl 10m || exit 1
```

Install enumerates the manager's UnitPath and supported persistent/runtime/vendor
paths before staging. It refuses aliases, stale target wants/requires links,
exact/dash-prefix/per-type inherited drop-ins, unsafe ancestry and existing paths.
Unpublished `service.d` configuration and unknown discovery conditions are HOLD.
It verifies the staged unit with systemd-analyze, publishes
new files without replacement, reloads unit discovery, and checks disabled and
inactive state. It does not enable or start anything. On mutation uncertainty,
published files remain as evidence; cleanup deletes only proven owned staging
objects. Do not retry or delete unknown partial state automatically.

## Provision privately, then explicitly enable and start

The user must already have their own Tunnel ID (`tunnel_` plus exactly 32
lowercase ASCII letters/digits), runtime API key, and eligible account/workspace
permissions. Provision as the configured nonroot owner, using a private TTY:

```bash
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
set -euo pipefail
sudo /usr/bin/python3 -I -B /root/gpt-agent-bridge-tunnel-review-v1/installer.py enable || exit 1
```

Inspect the enablement result. Immediate start is a separate authorized stage:

```bash
set -euo pipefail
# Starting now is a separate explicit action, not implied by enabling at boot.
sudo /usr/bin/python3 -I -B /root/gpt-agent-bridge-tunnel-review-v1/installer.py start || exit 1
```

Observe separately; status is not a connection acceptance test:

```bash
set -euo pipefail
/usr/bin/python3 -I -B /usr/local/lib/gpt-agent-bridge-tunnel-autostart/runner.py status || exit 1
```

Bridge boot enablement remains a separate action in its reviewed installer.
With both Linux units enabled and the existing WSL owner anchor configured,
subsequent startup is intended to need no foreground terminal. This still needs
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
blind fresh reinstallation. Rotation/reinstall migration is not automated by v1.

## Bridge contract adapter and remaining acceptance

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

## Official references

- [OpenAI Secure MCP Tunnels](https://developers.openai.com/api/docs/guides/secure-mcp-tunnels)
- [v0.0.16 systemd deployment pattern](https://github.com/openai/tunnel-client/blob/v0.0.16/docs/deployment/systemd-vm.md)
- [v0.0.16 environment configuration and TTL](https://github.com/openai/tunnel-client/blob/v0.0.16/pkg/runtimeconfig/config.go)
- [v0.0.16 polling retries](https://github.com/openai/tunnel-client/blob/v0.0.16/pkg/controlplane/internal/poller.go)
- [v0.0.16 readiness semantics](https://github.com/openai/tunnel-client/blob/v0.0.16/pkg/runtimehealth/health.go)
- [Microsoft WSL systemd and instance lifetime](https://learn.microsoft.com/en-us/windows/wsl/systemd)
