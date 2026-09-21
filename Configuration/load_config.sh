#!/usr/bin/env bash

# Environment-file loading and validation.

_EVERSPARK_REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck disable=SC1091
source "${_EVERSPARK_REPO_ROOT}/Runtime/Logging/log.sh"

core_load_config() {
  local config_file="$1"
  local required="${2:-1}"

  if [ ! -f "$config_file" ]; then
    if [ "$required" = "1" ]; then
      core_die "Config file not found: $config_file"
      return 1
    fi

    core_warn "Optional config file not found: $config_file"
    return 0
  fi

  set -a
  # shellcheck disable=SC1090
  source "$config_file"
  set +a

  core_ok "Config loaded: $config_file"
}

core_config_require() {
  local name
  local missing=()

  for name in "$@"; do
    if [ -z "${!name:-}" ]; then
      missing+=("$name")
    fi
  done

  if [ "${#missing[@]}" -gt 0 ]; then
    core_die "Missing required config values: ${missing[*]}"
    return 1
  fi
}

core_config_default() {
  local name="$1"
  local value="$2"

  if [ -z "${!name:-}" ]; then
    printf -v "$name" '%s' "$value"
    export "$name"
  fi
}
