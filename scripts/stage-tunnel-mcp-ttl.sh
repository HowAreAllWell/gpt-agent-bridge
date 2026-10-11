#!/usr/bin/env bash

# Stage an explicit MCP connection max TTL into the deployed Secure MCP Tunnel
# profile. tunnel-client (v0.0.10) defaults MCP transport connections to a 10m
# TTL and stops response forwarding when the TTL is reached, which kills
# in-flight semantic joins that legitimately run longer than ten minutes
# ("MCP connection TTL reached; stopping response forwarding" followed by a
# control-plane 502). This project stages the key explicitly so reinstall or
# profile regeneration does not silently fall back to the 10m default.
#
# Project default TTL is 60m; override per invocation with --ttl or the
# BRIDGE_TUNNEL_MCP_CONNECTION_MAX_TTL environment variable. This script only
# mutates the profile file; it never starts, restarts, or probes the running
# tunnel service. The change takes effect on the next external tunnel restart.

TUNNEL_TTL_DEFAULT="60m"

tunnel_ttl_usage() {
  cat <<'EOF'
usage: stage-tunnel-mcp-ttl.sh [--profile PATH] [--ttl DURATION]

Stage an explicit `connection_max_ttl` under the profile's top-level `mcp:`
section. Idempotent: re-staging the same value is a no-op. A timestamped
backup is created before the first mutation of each run that changes the file.

  --profile PATH       Tunnel profile YAML to stage
                       (default: $BRIDGE_TUNNEL_PROFILE, else
                       ~/.config/gpt-agent-bridge/tunnel-profiles/secure-bridge.yaml)
  --ttl DURATION       Positive Go duration (ms|s|m|h single unit)
                       (default: $BRIDGE_TUNNEL_MCP_CONNECTION_MAX_TTL, else 60m)

Exit codes: 0 staged or already staged, 1 fail-closed error, 2 usage error.
EOF
}

tunnel_ttl_is_valid_duration() {
  # Positive single-unit Go duration; "0"/zero values and compound or
  # negative forms are rejected fail-closed (the client requires positive).
  [[ "$1" =~ ^[1-9][0-9]*(ms|s|m|h)$ ]]
}

# Print the 1-based line number of the single top-level `mcp:` key, or nothing.
tunnel_ttl_find_mcp_line() {
  local profile=$1
  grep -n '^mcp:[[:space:]]*$' "$profile" 2>/dev/null | awk -F: '{print $1}' | tr '\n' ' '
}

# Print the existing `connection_max_ttl:` lines (with line numbers) that live
# inside the top-level `mcp:` block, one per line as "<lineno>:<indent>".
tunnel_ttl_find_existing_lines() {
  local profile=$1 mcp_line=$2
  awk -v start="$mcp_line" 'NR > start && /^[^[:space:]#-]/ { exit } NR > start && /^[[:space:]]+connection_max_ttl:/ { printf "%d:%s\n", NR, $0 }' "$profile"
}

# Leading whitespace of the first mapping-key child inside the mcp: block
# (skips comments and list items), or empty when the block has no such child.
tunnel_ttl_child_indent() {
  local profile=$1 mcp_line=$2
  awk -v start="$mcp_line" \
    'NR > start && /^[^[:space:]#-]/ { exit } NR > start && /^[[:space:]]+[^[:space:]#-]/ { sub(/[^[:space:]].*$/, ""); print; exit }' \
    "$profile"
}

tunnel_ttl_post_verify() {
  local profile=$1 ttl=$2
  [[ $(tunnel_ttl_find_existing_lines "$profile" "$(tunnel_ttl_find_mcp_line "$profile" | awk '{print $1}')" | grep -c "connection_max_ttl:[[:space:]]*${ttl}[[:space:]]*$" || true) -eq 1 ]]
}

# Upsert `connection_max_ttl` inside the profile's top-level `mcp:` block.
# stdout: "already-staged" or "staged". Fail closed leaves the file untouched.
tunnel_profile_stage_connection_ttl() {
  local profile=$1 ttl=$2
  local mcp_lines existing tmp backup indent

  if [[ ! -f "$profile" || -L "$profile" ]]; then
    echo "tunnel profile is missing or not a regular file: $profile" >&2
    return 1
  fi
  if ! tunnel_ttl_is_valid_duration "$ttl"; then
    echo "invalid TTL '$ttl': expected a positive duration like 60m (ms|s|m|h)" >&2
    return 1
  fi

  mcp_lines=$(tunnel_ttl_find_mcp_line "$profile")
  set -- $mcp_lines
  if [[ "$#" -ne 1 ]]; then
    echo "profile must contain exactly one top-level 'mcp:' section (found $#): $profile" >&2
    return 1
  fi

  existing=$(tunnel_ttl_find_existing_lines "$profile" "$1")
  if [[ -n "$existing" ]] && [[ "$(printf '%s\n' "$existing" | grep -c .)" -gt 1 ]]; then
    echo "profile has multiple connection_max_ttl keys inside mcp:; refusing ambiguous edit" >&2
    return 1
  fi

  if [[ -n "$existing" ]] && [[ "$existing" =~ connection_max_ttl:[[:space:]]*${ttl}[[:space:]]*$ ]]; then
    if tunnel_ttl_post_verify "$profile" "$ttl"; then
      echo "already-staged"
      return 0
    fi
    echo "post-stage verification failed for $profile" >&2
    return 1
  fi

  tmp=$(mktemp "${profile}.tmp.XXXXXX") || return 1
  if [[ -n "$existing" ]]; then
    # Replace the existing value at its exact line, preserving its indent.
    local target_line
    target_line=$(printf '%s\n' "$existing" | head -1 | cut -d: -f1)
    indent=$(printf '%s\n' "$existing" | head -1 | sed 's/^[0-9]*://' | grep -oE '^[[:space:]]*' || true)
    awk -v target="$target_line" -v repl="${indent}connection_max_ttl: ${ttl}" \
      'NR == target { print repl; next } { print }' "$profile" > "$tmp"
  else
    # Insert as the first key of the mcp: block, matching the indentation of
    # its sibling mapping keys (2-space fallback for an empty block).
    indent=$(tunnel_ttl_child_indent "$profile" "$1")
    indent="${indent:-  }"
    awk -v start="$1" -v repl="${indent}connection_max_ttl: ${ttl}" \
      '{ print; if (NR == start) print repl }' "$profile" > "$tmp"
  fi
  if ! tunnel_ttl_post_verify_tmp "$tmp" "$ttl" "$1"; then
    echo "staged copy failed verification; profile left untouched" >&2
    rm -f "$tmp"
    return 1
  fi
  chmod --reference="$profile" "$tmp"
  backup="${profile}.bak.$(date +%Y%m%d-%H%M%S)"
  local seq=0
  while [[ -e "$backup" ]]; do
    seq=$((seq + 1))
    backup="${profile}.bak.$(date +%Y%m%d-%H%M%S).${seq}"
  done
  cp -p "$profile" "$backup" || { rm -f "$tmp"; echo "backup failed; profile left untouched" >&2; return 1; }
  mv -f "$tmp" "$profile" || { rm -f "$tmp"; echo "atomic replace failed" >&2; return 1; }
  if ! tunnel_ttl_post_verify "$profile" "$ttl"; then
    echo "post-stage verification failed for $profile" >&2
    return 1
  fi
  echo "staged backup=$backup"
}

# Verify a not-yet-moved temp copy against the same block rules.
tunnel_ttl_post_verify_tmp() {
  local tmp=$1 ttl=$2 mcp_line=$3
  [[ $(awk -v start="$mcp_line" 'NR > start && /^[^[:space:]#-]/ { exit } NR > start && /^[[:space:]]+connection_max_ttl:[[:space:]]*'"$ttl"'[[:space:]]*$/ { found++ } END { print found + 0 }' "$tmp") -eq 1 ]]
}

main() {
  local profile="${BRIDGE_TUNNEL_PROFILE:-${HOME}/.config/gpt-agent-bridge/tunnel-profiles/secure-bridge.yaml}"
  local ttl="${BRIDGE_TUNNEL_MCP_CONNECTION_MAX_TTL:-$TUNNEL_TTL_DEFAULT}"
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --profile) profile=${2:?}; shift 2 ;;
      --ttl) ttl=${2-}; shift 2 ;;
      -h|--help) tunnel_ttl_usage; return 0 ;;
      *) echo "unknown option: $1" >&2; tunnel_ttl_usage >&2; return 2 ;;
    esac
  done

  tunnel_profile_stage_connection_ttl "$profile" "$ttl"
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
  set -u -o pipefail
  main "$@"
fi