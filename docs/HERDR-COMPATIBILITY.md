# Herdr compatibility and version selection

**Use Herdr v0.9.0 for this Bridge release.** The maintainer's existing WSL setup
reports `herdr 0.9.0`, a healthy Bridge and reachable Herdr. Herdr v0.9.3 is
**reported incompatible in that setup**; this is not a claim that every v0.9.3
scenario fails. This temporary recommendation should change only after support
for another version is verified. It is field evidence, not a fresh-install or
cross-version acceptance test.

## 1. Check before installing

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

## 2. Optional separate v0.9.0 installation

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

## 3. Select the CLI and check the actual session

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
following the [optional demo Agent setup](../examples/first-use/README.md#optional-demo-agent-with-herdr).
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

Continue with [Quickstart](QUICKSTART.md#1-prepare-herdr-and-an-existing-agent).
Its initialized MCP check must find `herdr.status == "reachable"`; health alone
does not certify Agent readiness or version compatibility. This guide adds no
automatic version enforcement to Bridge. Detection manifests may update
independently of the binary; this pin is not a complete environment lock and
does not change Herdr settings.
