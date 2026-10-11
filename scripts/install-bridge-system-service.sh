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

# Adopt the running Bridge process for the given repository. Prints the pid on
# success. The systemd MainPID is only used when its working directory
# revalidates against the repository; otherwise the process table is scanned
# and exactly one working-directory match is required.
bridge_adopt_pid() {
  local repo=$1
  local candidate=""
  if systemctl is-active --quiet gpt-agent-bridge.service 2>/dev/null; then
    candidate=$(systemctl show gpt-agent-bridge.service -p MainPID --value)
    if [[ "$candidate" =~ ^[1-9][0-9]*$ ]]; then
      local cwd
      cwd=$(readlink -f "/proc/$candidate/cwd" 2>/dev/null || true)
      if [[ "$cwd" != "$repo" ]]; then
        echo "systemd MainPID does not run in $repo; refusing service adoption" >&2
        return 1
      fi
      printf '%s\n' "$candidate"
      return 0
    fi
  fi
  local pids=() pid matches=() cwd
  mapfile -t pids < <(pgrep -f 'server\.py' || true)
  for pid in "${pids[@]}"; do
    cwd=$(readlink -f "/proc/$pid/cwd" 2>/dev/null || true)
    [[ "$cwd" == "$repo" ]] && matches+=("$pid")
  done
  if ((${#matches[@]} == 0)); then
    echo "no running Bridge process for this repository was found" >&2
    return 1
  fi
  if ((${#matches[@]} > 1)); then
    echo "expected exactly one running Bridge process for this repository, found ${#matches[@]}" >&2
    return 1
  fi
  printf '%s\n' "${matches[0]}"
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
  [[ -x "$bridge_repo/.venv/bin/python" && -f "$bridge_repo/server.py" ]] || {
    echo "missing Bridge checkout contents under: $bridge_repo" >&2
    return 1
  }
  [[ -f "$template_source" ]] || {
    echo "missing unit template: $template_source" >&2
    return 1
  }

  local bridge_pid
  bridge_pid=$(bridge_adopt_pid "$bridge_repo")
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

  local proc_environ="/proc/$bridge_pid/environ"
  local config_dir="$bridge_home/.config/gpt-agent-bridge"
  local env_dest="$config_dir/bridge.env"
  local unit_dest="/etc/systemd/system/gpt-agent-bridge.service"

  # Stage everything in a private directory and publish only after the
  # rendered unit verifies. The cleanup trap references the staging directory
  # alone, which is always set.
  local stage_dir
  stage_dir=$(mktemp -d)
  trap 'rm -rf "$stage_dir"' EXIT
  local staged_env="$stage_dir/bridge.env"
  local staged_unit="$stage_dir/gpt-agent-bridge.service"

  umask 077
  bridge_stage_env \
    "$staged_env" "$proc_environ" "$bridge_user" "$bridge_home" \
    "$bridge_repo" "$proxy_url"
  chmod 600 "$staged_env"
  chown "$bridge_user_live:$bridge_user_live" "$staged_env"

  bridge_render_unit "$template_source" "$bridge_user" "$bridge_home" \
    "$bridge_repo" > "$staged_unit"
  bridge_verify_unit "$staged_unit"

  bridge_publish "$stage_dir" "$env_dest" "$unit_dest" "$bridge_user_live"
  systemctl daemon-reload
  trap - EXIT
  rm -rf "$stage_dir"

  echo "staged Bridge env and installed verified unit; service was not started or enabled"
  echo "env_file=$env_dest"
  echo "unit_file=$unit_dest"
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
  main "$@"
fi
