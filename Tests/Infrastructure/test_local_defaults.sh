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

printf 'local infrastructure defaults: OK\n'
