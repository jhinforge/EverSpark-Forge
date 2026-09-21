#!/usr/bin/env bash

# Generic rclone connection and transfer capabilities.
# Forge modules own remote paths, manifests, excludes, and transfer policy.

_EVERSPARK_REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
# shellcheck disable=SC1091
source "${_EVERSPARK_REPO_ROOT}/Runtime/Logging/log.sh"
# shellcheck disable=SC1091
source "${_EVERSPARK_REPO_ROOT}/Shared/Shell/common.sh"

core_rclone_require() {
  if ! core_command_exists rclone; then
    core_die "rclone is not installed."
    return 1
  fi
}

core_rclone_config_path() {
  if [ -n "${RCLONE_CONFIG:-}" ]; then
    printf '%s\n' "$RCLONE_CONFIG"
    return 0
  fi

  printf '%s\n' "${XDG_CONFIG_HOME:-${HOME}/.config}/rclone/rclone.conf"
}

core_rclone_ensure_config() {
  local source_config="${1:-}"
  local runtime_config="${2:-$(core_rclone_config_path)}"

  if [ -d "$runtime_config" ]; then
    core_die "rclone config path is a directory: $runtime_config"
    return 1
  fi

  if [ -f "$runtime_config" ]; then
    chmod 600 "$runtime_config"
    core_ok "rclone config ready: $runtime_config"
    return 0
  fi

  if [ -z "$source_config" ]; then
    core_die "rclone config not found: $runtime_config"
    return 1
  fi

  if [ ! -f "$source_config" ]; then
    core_die "rclone source config not found: $source_config"
    return 1
  fi

  core_ensure_dir "$(dirname "$runtime_config")" || return 1
  cp "$source_config" "$runtime_config"
  chmod 600 "$runtime_config"
  core_ok "rclone config installed: $source_config -> $runtime_config"
}

core_rclone_remote_exists() {
  core_rclone_require || return 1

  local remote_name="${1%:}:"
  rclone listremotes 2>/dev/null | grep -Fxq "$remote_name"
}

core_rclone_check_remote() {
  core_rclone_require || return 1

  local remote_path="$1"

  if rclone lsf "$remote_path" --max-depth 1 >/dev/null 2>&1; then
    core_ok "rclone remote accessible: $remote_path"
    return 0
  fi

  core_die "Unable to access rclone remote: $remote_path"
}

core_rclone_copy() {
  core_rclone_require || return 1
  rclone copy "$@"
}

core_rclone_copyto() {
  core_rclone_require || return 1
  rclone copyto "$@"
}

core_rclone_sync() {
  core_rclone_require || return 1
  rclone sync "$@"
}

core_rclone_lsf() {
  core_rclone_require || return 1
  rclone lsf "$@"
}

core_rclone_lsd() {
  core_rclone_require || return 1
  rclone lsd "$@"
}

core_rclone_listremotes() {
  core_rclone_require || return 1
  rclone listremotes "$@"
}
