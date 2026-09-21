#!/usr/bin/env bash

# Generic shell helpers shared by Core modules.

core_command_exists() {
  command -v "$1" >/dev/null 2>&1
}

core_require_root() {
  if [ "${EUID:-$(id -u)}" -ne 0 ]; then
    core_die "This operation must be run as root."
    return 1
  fi
}

core_require_file() {
  local file="$1"
  local hint="${2:-}"

  if [ -f "$file" ]; then
    return 0
  fi

  if [ -n "$hint" ]; then
    core_die "Missing file: $file. $hint"
  else
    core_die "Missing file: $file"
  fi
}

core_ensure_dir() {
  local directory="$1"

  if [ -e "$directory" ] && [ ! -d "$directory" ]; then
    core_die "Path exists but is not a directory: $directory"
    return 1
  fi

  mkdir -p "$directory"
}

core_version_ge() {
  local current="$1"
  local required="$2"

  [ "$(printf '%s\n%s\n' "$required" "$current" | sort -V | head -n 1)" = "$required" ]
}

core_source_module() {
  local module="$1"

  if [ ! -f "$module" ]; then
    printf '[ERROR] EverSpark module not found: %s\n' "$module" >&2
    return 1
  fi

  # shellcheck disable=SC1090
  source "$module"
}
