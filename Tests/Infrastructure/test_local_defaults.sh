#!/usr/bin/env bash
set -euo pipefail

TEST_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${TEST_DIR}/../.." && pwd)"
TEST_ROOT="$(mktemp -d)"
trap 'rm -rf "$TEST_ROOT"' EXIT

# shellcheck disable=SC1091
source "${REPO_ROOT}/Configuration/load_config.sh"

unset EVERSPARK_TEST_VALUE || true
core_config_default EVERSPARK_TEST_VALUE local
[ "$EVERSPARK_TEST_VALUE" = "local" ]
core_config_require EVERSPARK_TEST_VALUE

export EVERSPARK_NETWORK_BACKEND=local
export EVERSPARK_LOG_DIR="${TEST_ROOT}/logs"

bash "${REPO_ROOT}/Infrastructure/Network/Tunnel/start_tunnel.sh"
bash "${REPO_ROOT}/Infrastructure/Network/Tunnel/check_tunnel.sh"
bash "${REPO_ROOT}/Infrastructure/Network/Tunnel/stop_tunnel.sh"

grep -q "Cloudflare Tunnel is disabled" "${TEST_ROOT}/logs/tunnel.log"

# Enabling the optional remote backend installs rclone exactly once. Keep this
# test isolated from the host package manager by replacing only the command
# probe and apt boundary after the production module has been sourced.
# shellcheck disable=SC1091
source "${REPO_ROOT}/Infrastructure/Storage/rclone.sh"
rclone_available=0
rclone_install_calls=0
core_command_exists() {
  [ "$1" = "rclone" ] && [ "$rclone_available" -eq 1 ]
}
core_apt_install_missing() {
  [ "$1" = "rclone" ]
  rclone_install_calls=$((rclone_install_calls + 1))
  rclone_available=1
}
rclone() {
  printf '%s\n' "rclone v-test"
}

core_rclone_install
[ "$rclone_install_calls" -eq 1 ]
core_rclone_install
[ "$rclone_install_calls" -eq 1 ]

printf 'local infrastructure defaults: OK\n'
