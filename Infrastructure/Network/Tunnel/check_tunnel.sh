#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../../.." && pwd)"

# shellcheck disable=SC1091
source "${REPO_ROOT}/Runtime/Logging/log.sh"
# shellcheck disable=SC1091
source "${REPO_ROOT}/Shared/Shell/common.sh"
# shellcheck disable=SC1091
source "${REPO_ROOT}/Configuration/load_config.sh"
# shellcheck disable=SC1091
source "${REPO_ROOT}/Infrastructure/Network/cloudflared.sh"

EVERSPARK_CONFIG_FILE="${EVERSPARK_CONFIG_FILE:-${CORE_CONFIG_FILE:-${REPO_ROOT}/.env}}"
if [ -f "$EVERSPARK_CONFIG_FILE" ]; then
  set -a
  # shellcheck disable=SC1090
  source "$EVERSPARK_CONFIG_FILE"
  set +a
fi

LOG_DIR="${EVERSPARK_LOG_DIR:-${REPO_ROOT}/Data/Logs}"
TUNNEL_LOG="${TUNNEL_LOG:-${LOG_DIR}/tunnel/tunnel.log}"
CLOUDFLARED_LOG="${CLOUDFLARED_LOG:-${LOG_DIR}/tunnel/cloudflared.log}"
core_log_init tunnel.check "$TUNNEL_LOG"

if [ "${EVERSPARK_NETWORK_BACKEND:-local}" != "cloudflare" ]; then
  core_info tunnel.disabled "Cloudflare Tunnel is disabled" \
    "backend=${EVERSPARK_NETWORK_BACKEND:-local}"
  exit 0
fi

core_config_require CF_TUNNEL_UUID CF_HOSTNAME CF_LOCAL_PORT
core_cloudflared_require

CF_CONFIG_DIR="${CF_CONFIG_DIR:-${REPO_ROOT}/Data/Cloudflare}"
CF_CONFIG_FILE="${CF_CONFIG_FILE:-${CF_CONFIG_DIR}/config.yml}"
CF_CREDENTIAL_FILE="${CF_CREDENTIAL_FILE:-${CF_CONFIG_DIR}/${CF_TUNNEL_UUID}.json}"

core_require_file "$CF_CONFIG_FILE"
core_require_file "$CF_CREDENTIAL_FILE"

PROCESS_PATTERN="cloudflared.*--config ${CF_CONFIG_FILE}.*run"
core_info tunnel.check.start "Checking tunnel health" \
  "hostname=$CF_HOSTNAME" "local_port=$CF_LOCAL_PORT"

if pgrep -af "$PROCESS_PATTERN" >/dev/null 2>&1; then
  core_ok tunnel.process.running "Tunnel process is running"
else
  core_die tunnel.process.missing "Tunnel process is not running"
  exit 1
fi

if curl -fsS "http://127.0.0.1:${CF_LOCAL_PORT}" >/dev/null 2>&1; then
  core_ok tunnel.local.ready "Local service is reachable" "port=$CF_LOCAL_PORT"
else
  core_warn tunnel.local.pending "Local service is not reachable" "port=$CF_LOCAL_PORT"
fi

if [ -f "$CLOUDFLARED_LOG" ]; then
  if grep -q "Registered tunnel connection" "$CLOUDFLARED_LOG"; then
    core_ok tunnel.registration.ready "Tunnel registration is present"
  else
    core_warn tunnel.registration.pending "Tunnel registration is not visible yet"
  fi
else
  core_warn tunnel.log.missing "cloudflared output log was not found" \
    "path=$CLOUDFLARED_LOG"
fi

core_ok tunnel.check.complete "Tunnel health check completed"
