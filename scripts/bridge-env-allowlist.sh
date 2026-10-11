#!/usr/bin/env bash

# All compared/migrated process keys use one NUL-aware parser. Unknown keys
# (including retired configuration) are ignored, never imported into the shell.
bridge_env_load() {
  local process_env_file=$1 line="" key value
  local -n bridge_env_result=$2
  bridge_env_result=()
  [[ -r "$process_env_file" && ! -d "$process_env_file" ]] || {
    echo "cannot read the current Bridge environment: $process_env_file" >&2
    return 1
  }
  while IFS= read -r -d '' line; do
    key=${line%%=*}
    case "$key" in
      BRIDGE_PATH_TOKEN|BRIDGE_WORKSPACE|PATH|\
      BRIDGE_PORT|BRIDGE_AWAIT_LEASE_SECONDS|BRIDGE_WORKSPACE_REGISTRY|\
      BRIDGE_HERDR_BIN|BRIDGE_HERDR_ENABLED|\
      BRIDGE_MCP_AUTH_SECRET|BRIDGE_MCP_AUTH_PREVIOUS_SECRET|\
      BRIDGE_WORKSPACE_STORE_PATH|XDG_STATE_HOME|\
      HTTP_PROXY|HTTPS_PROXY|http_proxy|https_proxy|NO_PROXY|no_proxy) ;;
      *) continue ;;
    esac
    if [[ "$line" != *=* || -v "bridge_env_result[$key]" ]]; then
      echo "ambiguous runtime configuration for $key; refusing migration" >&2
      return 1
    fi
    value=${line#*=}
    bridge_env_check_value "$key" "$value" || return 1
    bridge_env_result[$key]=$value
  done < "$process_env_file" || {
    echo "cannot open the current Bridge environment: $process_env_file" >&2
    return 1
  }
  if [[ -n "$line" ]]; then
    echo "current Bridge environment is not NUL-terminated" >&2
    return 1
  fi
}

# Supported values: valid UTF-8, single line, no C0/C1/DEL controls, Unicode
# line/paragraph separators, BOM or noncharacters (systemd rejects noncharacters).
# iconv validates bytes, but accepts noncharacters; exclude those explicitly.
# No locale-dependent %q.
# Fail closed if validation is unavailable; never print a rejected value.
bridge_env_check_value() {
  local key=$1 value=$2 LC_ALL=C
  if [[ "$value" == *[[:cntrl:]]* ||
        "$value" == *$'\xc2'[$'\x80'-$'\x9f']* ||
        "$value" == *$'\xe2\x80\xa8'* || "$value" == *$'\xe2\x80\xa9'* ||
        "$value" == *$'\xef\xbb\xbf'* ||
        "$value" == *$'\xef\xb7'[$'\x90'-$'\xaf']* ||
        "$value" == *$'\xef\xbf'[$'\xbe'-$'\xbf']* ||
        "$value" == *[$'\xf0'-$'\xf4'][$'\x8f\x9f\xaf\xbf']$'\xbf'[$'\xbe'-$'\xbf']* ]] ||
      ! printf '%s' "$value" | iconv -f UTF-8 -t UTF-8 >/dev/null 2>&1; then
    echo "unsupported runtime environment value for $key; refusing migration" >&2
    return 1
  fi
}

# EnvironmentFile is NOT a shell script: always double-quote, escaping only
# backslash and double quote. systemd does not expand dollars or backticks.
# Preserve empty values and surrounding spaces. Do not source the output.
bridge_env_emit() {
  local key=$1 value=$2
  bridge_env_check_value "$key" "$value" || return 1
  value=${value//\\/\\\\}
  value=${value//\"/\\\"}
  printf '%s="%s"\n' "$key" "$value"
}

bridge_env_emit_keys() {
  local -n bridge_env_values=$1
  local output_file=$2 key
  shift 2
  for key in "$@"; do
    if [[ -v "bridge_env_values[$key]" ]]; then
      bridge_env_emit "$key" "${bridge_env_values[$key]}" >> "$output_file" || return 1
    fi
  done
}

bridge_env_append_allowlist() {
  local -A runtime=()
  bridge_env_load "$1" runtime || return 1
  bridge_env_emit_keys runtime "$2" \
    BRIDGE_PORT BRIDGE_AWAIT_LEASE_SECONDS BRIDGE_WORKSPACE_REGISTRY \
    BRIDGE_HERDR_BIN BRIDGE_HERDR_ENABLED \
    BRIDGE_MCP_AUTH_SECRET BRIDGE_MCP_AUTH_PREVIOUS_SECRET
}

bridge_append_live_store_overrides() {
  local -A runtime=()
  bridge_env_load "$1" runtime || return 1
  bridge_env_emit_keys runtime "$2" BRIDGE_WORKSPACE_STORE_PATH XDG_STATE_HOME
}
