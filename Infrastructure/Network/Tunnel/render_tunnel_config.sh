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

LOG_DIR="${EVERSPARK_LOG_DIR:-${REPO_ROOT}/Data/Logs}"
TUNNEL_LOG="${TUNNEL_LOG:-${LOG_DIR}/tunnel.log}"
core_log_init tunnel.config "$TUNNEL_LOG"

core_config_require CF_TUNNEL_UUID CF_HOSTNAME CF_LOCAL_PORT

[[ "$CF_TUNNEL_UUID" =~ ^[A-Za-z0-9-]+$ ]] \
  || core_die tunnel.uuid.invalid "Invalid tunnel UUID"
[[ "$CF_HOSTNAME" =~ ^[A-Za-z0-9.-]+$ ]] \
  || core_die tunnel.hostname.invalid "Invalid tunnel hostname" "hostname=$CF_HOSTNAME"
[[ "$CF_LOCAL_PORT" =~ ^[0-9]+$ ]] \
  || core_die tunnel.port.invalid "Invalid tunnel local port" "port=$CF_LOCAL_PORT"

CF_CONFIG_DIR="${CF_CONFIG_DIR:-${REPO_ROOT}/Data/Cloudflare}"
CF_CONFIG_FILE="${CF_CONFIG_FILE:-${CF_CONFIG_DIR}/config.yml}"
CF_CREDENTIAL_FILE="${CF_CREDENTIAL_FILE:-${CF_CONFIG_DIR}/${CF_TUNNEL_UUID}.json}"
CF_TEMPLATE_FILE="${CF_TEMPLATE_FILE:-${SCRIPT_DIR}/config.template.yml}"

core_require_file "$CF_TEMPLATE_FILE"
core_ensure_dir "$CF_CONFIG_DIR"

sed \
  -e "s#__CF_TUNNEL_UUID__#${CF_TUNNEL_UUID}#g" \
  -e "s#__CF_HOSTNAME__#${CF_HOSTNAME}#g" \
  -e "s#__CF_LOCAL_PORT__#${CF_LOCAL_PORT}#g" \
  -e "s#__CF_CREDENTIAL_FILE__#${CF_CREDENTIAL_FILE}#g" \
  "$CF_TEMPLATE_FILE" > "$CF_CONFIG_FILE"

if grep -q '__CF_' "$CF_CONFIG_FILE"; then
  core_die tunnel.config.unresolved "Tunnel configuration contains unresolved placeholders" \
    "path=$CF_CONFIG_FILE"
  exit 1
fi

core_ok tunnel.config.ready "Tunnel configuration rendered" "path=$CF_CONFIG_FILE"
