#!/usr/bin/env bash

# cloudflared availability and installation.

_EVERSPARK_REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
# shellcheck disable=SC1091
source "${_EVERSPARK_REPO_ROOT}/Runtime/Logging/log.sh"
# shellcheck disable=SC1091
source "${_EVERSPARK_REPO_ROOT}/Shared/Shell/common.sh"

core_cloudflared_require() {
  if ! core_command_exists cloudflared; then
    core_die "cloudflared is not installed."
    return 1
  fi
}

core_cloudflared_install() {
  if core_command_exists cloudflared; then
    core_ok "cloudflared already exists: $(cloudflared --version 2>/dev/null || true)"
    return 0
  fi

  core_require_root || return 1

  local install_path="${CLOUDFLARED_INSTALL_PATH:-/usr/local/bin/cloudflared}"
  local download_url="${CLOUDFLARED_DOWNLOAD_URL:-https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64}"
  local temporary_file
  temporary_file="$(mktemp)"

  core_info "Installing cloudflared: $install_path"

  if core_command_exists curl; then
    curl -fL "$download_url" -o "$temporary_file"
  elif core_command_exists wget; then
    wget -O "$temporary_file" "$download_url"
  else
    rm -f "$temporary_file"
    core_die "curl or wget is required to install cloudflared."
    return 1
  fi

  chmod +x "$temporary_file"
  mv "$temporary_file" "$install_path"
  core_ok "cloudflared installed: $(cloudflared --version 2>/dev/null || true)"
}
