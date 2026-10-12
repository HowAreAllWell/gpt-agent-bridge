#!/usr/bin/env bash

# Portable installer for the GPT-Agent Bridge system service. Renders the unit
# template for an explicit user/home/repository triple, adopts the running
# Bridge process fail-closed, stages a 0600 env file from an explicit allowlist
# inside a private staging directory, verifies the rendered unit, and only then
# publishes both files. The service is never started or enabled here.
#
# usage: install-bridge-system-service.sh --user USER --repo PATH
#                                        [--proxy URL] [--print-unit]
#
#   --user USER   Account the service runs as; must own the running Bridge
#                 process (fail-closed adoption identity).
#   --repo PATH   Absolute path of this Bridge checkout; must match the
#                 running process working directory (fail-closed).
#   --proxy URL   When given, the running environment's HTTP_PROXY,
#                 HTTPS_PROXY, http_proxy and https_proxy must equal URL, a
#                 nonempty NO_PROXY is required, and all five values are
#                 staged. When omitted, no proxy lines are staged.
#   --print-unit  Render the unit for the given user/repository to stdout and
#                 exit; no adoption, staging, or privileges required.

repo_root_default() {
  cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd
}

# Read one approved key from a process environment, never a staged env file.
# Validate the entire compared/migrated key set before returning a value.
bridge_env_value() {
  local -A runtime=()
  bridge_env_load "$1" runtime || return 1
  printf '%s' "${runtime[$2]-}"
}

bridge_render_unit() {
  local template=$1 user=$2 home=$3 repo=$4 content
  content=$(<"$template")
  content=${content//@BRIDGE_USER@/$user}
  content=${content//@BRIDGE_HOME@/$home}
  content=${content//@BRIDGE_REPO@/$repo}
  printf '%s\n' "$content"
}

bridge_usage() {
  cat <<'EOF'
usage: install-bridge-system-service.sh --user USER --repo PATH
                                        [--proxy URL] [--print-unit]

  --user USER   Service account; must own the running Bridge process.
  --repo PATH   Absolute path of the Bridge checkout to serve.
  --proxy URL   Stage proxy settings only when this is provided; the running
                environment's proxy variables must then equal URL and a
                nonempty NO_PROXY must exist.
  --print-unit  Print the rendered unit to stdout; no adoption, staging,
                systemd install, or privileges.

Installs /etc/systemd/system/gpt-agent-bridge.service, runs
systemd-analyze verify, and never starts or enables the service.
EOF
}

bridge_require_value() {
  local label=$1 value=$2
  [[ -n "$value" ]] || {
    echo "$label is required" >&2
    return 1
  }
}

# Emit proxy configuration for the staged env file. With a proxy, the live
# environment must already match it and carry a nonempty NO_PROXY (fail-closed
# adoption). Without a proxy, only existing NO_PROXY values are staged.
bridge_env_proxy_lines() {
  local -n proxy_values=$1
  local proxy=$2 out=$3 key no_proxy=${proxy_values[NO_PROXY]-}
  bridge_env_check_value --proxy "$proxy" || return 1
  if [[ -n "$proxy" ]]; then
    for key in HTTP_PROXY HTTPS_PROXY http_proxy https_proxy; do
      [[ "${proxy_values[$key]-}" == "$proxy" ]] || {
        echo "$key does not match --proxy in the current Bridge environment" >&2
        return 1
      }
    done
    [[ -n "$no_proxy" ]] || {
      echo "NO_PROXY is missing from the current Bridge environment" >&2
      return 1
    }
  fi
  # Preserve the existing policy: uppercase NO_PROXY supplies both spellings.
  # An explicitly different lowercase value cannot be silently overwritten.
  if [[ -v 'proxy_values[no_proxy]' && "${proxy_values[no_proxy]}" != "$no_proxy" ]]; then
    echo "no_proxy does not match NO_PROXY; refusing migration" >&2
    return 1
  fi
  if [[ -n "$proxy" ]]; then
    for key in HTTP_PROXY HTTPS_PROXY http_proxy https_proxy; do
      bridge_env_emit "$key" "$proxy" >> "$out" || return 1
    done
  fi
  if [[ -v 'proxy_values[NO_PROXY]' ]]; then
    bridge_env_emit NO_PROXY "$no_proxy" >> "$out" || return 1
    bridge_env_emit no_proxy "$no_proxy" >> "$out" || return 1
  fi
}

# Kept as a function so synthetic tests can substitute a disposable proc tree.
# Production never takes a proc root from the environment or command line.
bridge_proc_root() { printf '/proc'; }

# Verify the configured launch, not a process-name substring. The fingerprint
# includes Linux starttime to detect PID reuse, and is rechecked before publish.
# This is an adoption guard, not a sandbox: a malicious same-UID process can
# spoof argv or change its memory; proc metadata cannot attest loaded Python code.
bridge_validate_pid() {
  local repo=$1 pid=$2 expected=${3-} proc_root
  [[ "$pid" =~ ^[1-9][0-9]*$ ]] || return 1
  bridge_require_package "$repo" >/dev/null 2>&1 || return 1
  proc_root=$(bridge_proc_root) || return 1
  "$repo/.venv/bin/python" -I -B - "$repo" "$pid" "$proc_root" "$expected" <<'PY'
import hashlib
import os
from pathlib import Path
import stat
import sys

def read_regular(path, limit):
    # No FIFOs, symlinks, unbounded reads, or diagnostics containing argv.
    fd = os.open(path, os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        mode = os.fstat(fd).st_mode
        if not stat.S_ISREG(mode) or not mode & 0o444:
            raise ValueError("not a regular proc file")
        with os.fdopen(fd, "rb", closefd=False) as stream:
            data = stream.read(limit + 1)
        if len(data) > limit:
            raise ValueError("oversized proc file")
        return data
    finally:
        os.close(fd)

try:
    repo, pid, proc_root, expected = sys.argv[1:]
    checkout = Path(repo)
    if not checkout.is_absolute() or str(checkout.resolve(strict=True)) != repo:
        raise ValueError("noncanonical checkout")
    proc = Path(proc_root) / pid
    python = checkout / ".venv/bin/python"
    binary = python.resolve(strict=True)
    binary_stat = binary.stat()

    def starttime():
        raw = read_regular(proc / "stat", 4096)
        leader, separator, tail = raw.rpartition(b") ")
        if not separator or leader.split(b" (", 1)[0] != pid.encode():
            raise ValueError("invalid proc stat")
        fields = tail.split()
        if fields[0] in (b"Z", b"X", b"x"):
            raise ValueError("dead process")
        started = int(fields[19])  # field 22, after pid and parenthesized comm
        if started <= 0:
            raise ValueError("invalid starttime")
        return started

    def snapshot():
        before = starttime()
        cwd = (proc / "cwd").resolve(strict=True)
        exe = (proc / "exe").resolve(strict=True)
        exe_stat = (proc / "exe").stat()
        argv = read_regular(proc / "cmdline", 16384)
        required = os.fsencode(python) + b"\0-m\0gpt_agent_bridge\0"
        if (cwd != checkout or exe != binary or
                (exe_stat.st_dev, exe_stat.st_ino) !=
                (binary_stat.st_dev, binary_stat.st_ino) or argv != required):
            raise ValueError("launch identity mismatch")
        if before != starttime():
            raise ValueError("PID reused")
        return hashlib.sha256(
            repr((pid, before, str(cwd), str(exe), exe_stat.st_dev,
                  exe_stat.st_ino)).encode() + b"\0" + argv).hexdigest()

    first = snapshot()
    if first != snapshot() or (expected and expected != first):
        raise ValueError("process identity changed")
    print(first)
except (OSError, ValueError, IndexError):
    raise SystemExit(1)
PY
}

# Both active MainPID and pgrep enumeration use the same validator. Only the
# absolute checkout/.venv/bin/python -m gpt_agent_bridge launch is adoptable;
# console entrypoints, flags and extra arguments deliberately fail closed.
bridge_adopt_pid() {
  local repo=$1
  local candidate="" identity="" listing status pid
  BRIDGE_ADOPTED_PID="" BRIDGE_ADOPTED_IDENTITY=""
  if systemctl is-active --quiet gpt-agent-bridge.service 2>/dev/null; then
    if ! candidate=$(systemctl show gpt-agent-bridge.service -p MainPID --value) ||
       ! identity=$(bridge_validate_pid "$repo" "$candidate"); then
      echo "systemd MainPID failed Bridge launch validation; refusing service adoption" >&2
      return 1
    fi
  else
    status=$?
    if ((status != 3)); then
      echo "service activity query failed; refusing service adoption" >&2
      return 1
    fi
    local matches=() identities=() seen=" "
    if listing=$(pgrep -f '(^|[[:space:]])[^[:space:]]*python[^[:space:]]*[[:space:]]+-m[[:space:]]+gpt_agent_bridge([[:space:]]|$)'); then
      status=0
    else
      status=$?
    fi
    if ((status > 1)); then
      echo "process enumeration failed; refusing service adoption" >&2
      return 1
    fi
    while IFS= read -r pid; do
      [[ -n "$pid" ]] || continue
      if [[ ! "$pid" =~ ^[1-9][0-9]*$ || "$seen" == *" $pid "* ]]; then
        echo "invalid process enumeration; refusing service adoption" >&2
        return 1
      fi
      seen+="$pid "
      if identity=$(bridge_validate_pid "$repo" "$pid"); then
        matches+=("$pid") identities+=("$identity")
      fi
    done <<< "$listing"
    if ((${#matches[@]} == 0)); then
      echo "no running Bridge process with the exact configured launch was found" >&2
      return 1
    fi
    if ((${#matches[@]} > 1)); then
      echo "expected exactly one running Bridge process for this repository, found ${#matches[@]}" >&2
      return 1
    fi
    candidate=${matches[0]} identity=${identities[0]}
  fi
  if ! bridge_validate_pid "$repo" "$candidate" "$identity" >/dev/null; then
    echo "Bridge process changed during selection; refusing service adoption" >&2
    return 1
  fi
  BRIDGE_ADOPTED_PID=$candidate BRIDGE_ADOPTED_IDENTITY=$identity
  printf '%s\n' "$candidate"
}

# Assemble the staged env file from the adopted process environment. Fails
# closed on repository/identity mismatch, a missing path token, or missing
# PATH. Proxy lines follow bridge_env_proxy_lines. Appends the explicitly
# allowlisted keys and the live store overrides from the shared library.
bridge_stage_env() {
  local out=$1 env_file=$2 user=$3 home=$4 repo=$5 proxy=$6
  local -A runtime=()
  local port
  # Parse once, before any output. All readers share this validated snapshot.
  bridge_env_load "$env_file" runtime || return 1
  bridge_env_check_value --repo "$repo" || return 1
  bridge_env_check_value --proxy "$proxy" || return 1
  if [[ -z "${runtime[BRIDGE_PATH_TOKEN]-}" ||
        "${runtime[BRIDGE_WORKSPACE]-}" != "$repo" || -z "${runtime[PATH]-}" ]]; then
    echo "current Bridge environment does not match this repository" >&2
    return 1
  fi
  # A fixed listener needs a concrete TCP port for the exact Host rule. Do not
  # silently map an explicit empty/invalid value or ephemeral port 0 to 8765.
  port=${runtime[BRIDGE_PORT]-8765}
  if [[ ! "$port" =~ ^[0-9]{1,5}$ ]] || ((10#$port < 1 || 10#$port > 65535)); then
    echo "BRIDGE_PORT must be a decimal port in 1..65535; refusing migration" >&2
    return 1
  fi
  port=$((10#$port))
  # Keep failures explicit even when the caller invokes this function in an
  # if/|| context (where Bash's errexit is disabled inside functions).
  bridge_env_proxy_lines runtime "$proxy" "$out" || return 1
  bridge_env_emit_keys runtime "$out" BRIDGE_PATH_TOKEN BRIDGE_WORKSPACE PATH \
    BRIDGE_PORT BRIDGE_AWAIT_LEASE_SECONDS BRIDGE_WORKSPACE_REGISTRY \
    BRIDGE_HERDR_BIN BRIDGE_HERDR_ENABLED \
    BRIDGE_MCP_AUTH_SECRET BRIDGE_MCP_AUTH_PREVIOUS_SECRET \
    BRIDGE_WORKSPACE_STORE_PATH XDG_STATE_HOME || return 1
  bridge_env_emit BRIDGE_MCP_ENABLE_DNS_REBINDING_PROTECTION true >> "$out" || return 1
  bridge_env_emit BRIDGE_MCP_ALLOWED_HOSTS "[\"127.0.0.1:$port\"]" >> "$out" || return 1
  bridge_env_emit BRIDGE_MCP_ALLOWED_ORIGINS '[]' >> "$out"
}

bridge_verify_unit() {
  local unit=$1
  systemd-analyze verify "$unit"
}

bridge_publish() {
  local stage_dir=$1 env_dest=$2 unit_dest=$3 user=$4
  local config_dir unit_dir
  config_dir=$(dirname "$env_dest")
  install -d -o "$user" -g "$user" -m 700 "$config_dir"
  install -o "$user" -g "$user" -m 600 "$stage_dir/bridge.env" "$env_dest"
  unit_dir=$(dirname "$unit_dest")
  install -d -m 755 "$unit_dir"
  if (( EUID == 0 )); then
    install -o root -g root -m 644       "$stage_dir/gpt-agent-bridge.service" "$unit_dest"
  else
    # Unprivileged callers (tests, --print-unit style checks) publish to a
    # user-owned destination; root keeps the product ownership.
    install -m 644 "$stage_dir/gpt-agent-bridge.service" "$unit_dest"
  fi
}

# Read-only package admission; never import/bootstrap the configured server.
bridge_require_package() {
  local repo=$1
  [[ -x "$repo/.venv/bin/python" && -f "$repo/pyproject.toml" && -f "$repo/src/gpt_agent_bridge/__main__.py" ]] || {
    echo "missing Bridge checkout contents under: $repo" >&2
    return 1
  }
  if ! "$repo/.venv/bin/python" -I -B -c '
import importlib.util, pathlib, sys
spec = importlib.util.find_spec("gpt_agent_bridge")
expected = pathlib.Path(sys.argv[1]) / "src/gpt_agent_bridge/__init__.py"
raise SystemExit(0 if spec and spec.origin and expected.is_file() and expected.resolve() == expected and pathlib.Path(spec.origin).resolve() == expected else 1)
' "$repo"; then
    echo "Bridge package is not installed from this checkout in its .venv; run pip install -e . first" >&2
    return 1
  fi
}

# Stage ownership stays with the installer until bridge_publish installs the
# final user-owned env. Held descriptors identify our objects even if a path is
# replaced. Never recursively remove unknown content or follow cleanup symlinks.
bridge_stage_guard() {
  "$BRIDGE_STAGE_PYTHON" -I -B - "$1" "$BRIDGE_STAGE_DIR" \
    "$BRIDGE_STAGE_IDENTITY" "$BRIDGE_STAGE_DIR_FD" "$BRIDGE_STAGE_PARENT_FD" \
    "${BRIDGE_STAGE_ENV_FD-}" "${BRIDGE_STAGE_UNIT_FD-}" <<'PY'
import os
from pathlib import Path
import re
import stat
import sys

try:
    action, path, identity, directory, parent, env_fd, unit_fd = sys.argv[1:]
    path = Path(path)
    if (action not in ("check", "cleanup") or not path.is_absolute() or
            not re.fullmatch(r"gpt-agent-bridge-stage\.[A-Za-z0-9]{8}", path.name)):
        raise ValueError("invalid stage")
    directory, parent = int(directory), int(parent)
    expected = tuple(map(int, identity.split(":")))
    current = os.fstat(directory)
    def owned_directory(info):
        return (stat.S_ISDIR(info.st_mode) and stat.S_IMODE(info.st_mode) == 0o700
                and (info.st_dev, info.st_ino, info.st_uid) == expected
                and info.st_uid == os.geteuid())
    if not owned_directory(current):
        raise ValueError("directory changed")
    def same_path():
        try:
            return owned_directory(os.stat(path.name, dir_fd=parent, follow_symlinks=False))
        except FileNotFoundError:
            return False
    originals = {}
    for name, fd in (("bridge.env", env_fd), ("gpt-agent-bridge.service", unit_fd)):
        if fd:
            info = os.fstat(int(fd))
            if (not stat.S_ISREG(info.st_mode) or stat.S_IMODE(info.st_mode) != 0o600
                    or info.st_uid != os.geteuid() or info.st_nlink != 1):
                raise ValueError("staged object changed")
            originals[(info.st_dev, info.st_ino)] = name
    entries = os.listdir(directory)
    recognized = []
    exact = same_path() and set(entries) == set(originals.values())
    for name in entries:
        info = os.stat(name, dir_fd=directory, follow_symlinks=False)
        original = originals.get((info.st_dev, info.st_ino))
        if (original and stat.S_ISREG(info.st_mode) and info.st_uid == os.geteuid()
                and stat.S_IMODE(info.st_mode) == 0o600 and info.st_nlink == 1):
            recognized.append(name)
            exact = exact and name == original
        else:
            exact = False
    if action == "check":
        if not exact:
            raise ValueError("stage changed")
    else:
        # Remove only inode-identified objects, including an original renamed
        # inside this held directory. Preserve every unrecognized entry.
        for name in recognized:
            os.unlink(name, dir_fd=directory)
        if os.listdir(directory) or not same_path():
            raise ValueError("unrecognized content or directory replacement")
        os.rmdir(path.name, dir_fd=parent)
except (OSError, ValueError):
    print("private stage changed or cleanup unavailable; preserve for operator review",
          file=sys.stderr)
    raise SystemExit(1)
PY
}

bridge_stage_exit() {
  local status=$1 cleanup_status=0
  trap - EXIT
  # Finish this single cleanup attempt without a second signal-triggered pass.
  trap '' HUP INT TERM
  if [[ -n "${BRIDGE_STAGE_DIR-}" ]]; then
    if [[ -n "${BRIDGE_STAGE_IDENTITY-}" ]]; then
      bridge_stage_guard cleanup || cleanup_status=$?
    else
      cleanup_status=1
    fi
    if ((cleanup_status != 0)); then
      printf 'private staging needs operator review: %s\n' "$BRIDGE_STAGE_DIR" >&2
      ((status != 0)) || status=1
    fi
  fi
  exit "$status"
}

# Child-shell globals remain bound through EXIT even when main returns. All
# failures are explicit, including callers that disable Bash errexit with ||.
bridge_install_staged() (
  set -euo pipefail
  umask 077
  local bridge_repo=$1 bridge_pid=$2 bridge_identity=$3 bridge_user_live=$4
  local bridge_home=$5 proxy_url=$6 template_source=$7 env_dest=$8 unit_dest=$9
  BRIDGE_STAGE_PYTHON="$1/.venv/bin/python"
  BRIDGE_STAGE_DIR="" BRIDGE_STAGE_IDENTITY=""
  BRIDGE_STAGE_DIR_FD="" BRIDGE_STAGE_PARENT_FD=""
  BRIDGE_STAGE_ENV_FD="" BRIDGE_STAGE_UNIT_FD=""
  trap 'bridge_stage_exit $?' EXIT
  trap 'exit 129' HUP
  trap 'exit 130' INT
  trap 'exit 143' TERM
  BRIDGE_STAGE_DIR=$(mktemp -d "${TMPDIR:-/tmp}/gpt-agent-bridge-stage.XXXXXXXX") || exit 1
  exec {BRIDGE_STAGE_DIR_FD}< "$BRIDGE_STAGE_DIR" || exit 1
  exec {BRIDGE_STAGE_PARENT_FD}< "$(dirname "$BRIDGE_STAGE_DIR")" || exit 1
  BRIDGE_STAGE_IDENTITY=$("$BRIDGE_STAGE_PYTHON" -I -B -c '
import os, stat, sys
s = os.fstat(int(sys.argv[1]))
assert stat.S_ISDIR(s.st_mode) and stat.S_IMODE(s.st_mode) == 0o700 and s.st_uid == os.geteuid()
print(f"{s.st_dev}:{s.st_ino}:{s.st_uid}")
' "$BRIDGE_STAGE_DIR_FD") || exit 1
  # Exclusive creation; later writes use held descriptors, not mutable paths.
  set -o noclobber
  exec {BRIDGE_STAGE_ENV_FD}> "$BRIDGE_STAGE_DIR/bridge.env" || exit 1
  exec {BRIDGE_STAGE_UNIT_FD}> "$BRIDGE_STAGE_DIR/gpt-agent-bridge.service" || exit 1
  set +o noclobber
  stage_dir=$BRIDGE_STAGE_DIR
  staged_env="$stage_dir/bridge.env"
  staged_unit="$stage_dir/gpt-agent-bridge.service"
  bridge_stage_guard check || exit 1
  bridge_validate_pid "$bridge_repo" "$bridge_pid" "$bridge_identity" >/dev/null || {
    echo "Bridge process changed before environment staging; refusing adoption" >&2
    exit 1
  }
  bridge_stage_env "/dev/fd/$BRIDGE_STAGE_ENV_FD" "$(bridge_proc_root)/$bridge_pid/environ" \
    "$bridge_user_live" "$bridge_home" "$bridge_repo" "$proxy_url" || exit 1
  bridge_render_unit "$template_source" "$bridge_user_live" "$bridge_home" \
    "$bridge_repo" >&"$BRIDGE_STAGE_UNIT_FD" || exit 1
  bridge_stage_guard check || exit 1
  bridge_verify_unit "$staged_unit" || exit 1
  bridge_validate_pid "$bridge_repo" "$bridge_pid" "$bridge_identity" >/dev/null || {
    echo "Bridge process changed before publication; refusing adoption" >&2
    exit 1
  }
  bridge_stage_guard check || exit 1
  bridge_publish "$stage_dir" "$env_dest" "$unit_dest" "$bridge_user_live" || {
    echo "publication failed; outputs may be partial and were retained; inspect before retry" >&2
    exit 1
  }
  systemctl daemon-reload || {
    echo "daemon-reload failed after publication; installed outputs were retained" >&2
    exit 1
  }
)

main() {
  set -euo pipefail
  local print_unit=false bridge_user="" bridge_repo="" proxy_url=""
  while (($#)); do
    case $1 in
      --user) bridge_user=${2-}; shift 2 ;;
      --repo) bridge_repo=${2-}; shift 2 ;;
      --proxy) proxy_url=${2-}; shift 2 ;;
      --print-unit) print_unit=true; shift ;;
      -h | --help) bridge_usage; return 0 ;;
      *) echo "unknown argument: $1" >&2; bridge_usage >&2; return 2 ;;
    esac
  done
  bridge_require_value "--user" "$bridge_user" || return 2
  bridge_require_value "--repo" "$bridge_repo" || return 2

  local repo_root template_source
  repo_root=$(repo_root_default)
  source "$repo_root/scripts/bridge-env-allowlist.sh"
  template_source="$repo_root/systemd/gpt-agent-bridge.service.template"

  if $print_unit; then
    local print_home
    print_home=$(getent passwd "$bridge_user" | cut -d: -f6)
    [[ -n "$print_home" ]] || {
      echo "cannot resolve the home directory of: $bridge_user" >&2
      return 1
    }
    bridge_render_unit "$template_source" "$bridge_user" "$print_home" "$bridge_repo"
    return 0
  fi

  if (( EUID != 0 )); then
    echo "run this installer from an external shell with sudo" >&2
    return 1
  fi
  [[ "$bridge_repo" == /* ]] || {
    echo "--repo must be an absolute path" >&2
    return 2
  }
  bridge_require_package "$bridge_repo" || return 1
  [[ -f "$template_source" ]] || {
    echo "missing unit template: $template_source" >&2
    return 1
  }

  local bridge_pid bridge_identity
  # Do not use command substitution: keep the selected starttime fingerprint
  # in this shell so later checks cannot silently adopt a reused PID.
  bridge_adopt_pid "$bridge_repo" >/dev/null || return 1
  bridge_pid=$BRIDGE_ADOPTED_PID bridge_identity=$BRIDGE_ADOPTED_IDENTITY
  local bridge_user_live bridge_home
  bridge_user_live=$(ps -o user= -p "$bridge_pid" | xargs)
  bridge_home=$(getent passwd "$bridge_user_live" | cut -d: -f6)
  [[ -n "$bridge_home" ]] || {
    echo "cannot resolve the home directory of: $bridge_user_live" >&2
    return 1
  }
  if [[ "$bridge_user_live" != "$bridge_user" ]]; then
    echo "running Bridge process is owned by '$bridge_user_live', not '$bridge_user'" >&2
    return 1
  fi

  local config_dir="$bridge_home/.config/gpt-agent-bridge"
  local env_dest="$config_dir/bridge.env"
  local unit_dest="/etc/systemd/system/gpt-agent-bridge.service"
  bridge_install_staged "$bridge_repo" "$bridge_pid" "$bridge_identity" \
    "$bridge_user_live" "$bridge_home" "$proxy_url" "$template_source" \
    "$env_dest" "$unit_dest" || return $?

  echo "staged Bridge env and installed verified unit; service was not started or enabled"
  echo "env_file=$env_dest"
  echo "unit_file=$unit_dest"
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
  main "$@"
fi
