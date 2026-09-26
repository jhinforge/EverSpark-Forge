#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../../.." && pwd)"

# shellcheck disable=SC1091
source "${REPO_ROOT}/Runtime/Logging/log.sh"

EVERSPARK_CONFIG_FILE="${EVERSPARK_CONFIG_FILE:-${CORE_CONFIG_FILE:-${REPO_ROOT}/.env}}"
if [ -f "$EVERSPARK_CONFIG_FILE" ]; then
  set -a
  # shellcheck disable=SC1090
  source "$EVERSPARK_CONFIG_FILE"
  set +a
fi

LOG_DIR="${EVERSPARK_LOG_DIR:-${REPO_ROOT}/Data/Logs}"
TUNNEL_LOG="${TUNNEL_LOG:-${LOG_DIR}/tunnel/tunnel.log}"
core_log_init tunnel.lifecycle "$TUNNEL_LOG"

if [ "${EVERSPARK_NETWORK_BACKEND:-local}" != "cloudflare" ]; then
  core_info tunnel.disabled "Cloudflare Tunnel is disabled" \
    "backend=${EVERSPARK_NETWORK_BACKEND:-local}"
  exit 0
fi

CF_CONFIG_DIR="${CF_CONFIG_DIR:-${REPO_ROOT}/Data/Cloudflare}"
CF_CONFIG_FILE="${CF_CONFIG_FILE:-${CF_CONFIG_DIR}/config.yml}"
PROCESS_PATTERN="cloudflared.*--config ${CF_CONFIG_FILE}.*run"

if ! pgrep -af "$PROCESS_PATTERN" >/dev/null 2>&1; then
  core_info tunnel.already_stopped "Tunnel is not running"
  exit 0
fi

core_info tunnel.stop "Stopping tunnel"
pkill -f "$PROCESS_PATTERN" 2>/dev/null || true
sleep 2

if pgrep -af "$PROCESS_PATTERN" >/dev/null 2>&1; then
  core_error tunnel.stop.failed "Tunnel is still running"
  pgrep -af "$PROCESS_PATTERN" >&2 || true
  exit 1
fi

core_ok tunnel.stopped "Tunnel stopped"
