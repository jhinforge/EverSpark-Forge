#!/usr/bin/env bash
set -euo pipefail

TEST_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${TEST_DIR}/../.." && pwd)"
TEST_ROOT="$(mktemp -d)"
TUNNEL_ID="11111111-2222-3333-4444-555555555555"
CONFIG_FILE="${TEST_ROOT}/env"
CF_DIR="${TEST_ROOT}/cloudflare"
LOG_DIR="${TEST_ROOT}/logs"

cleanup() {
  EVERSPARK_CONFIG_FILE="$CONFIG_FILE" \
    PATH="${TEST_ROOT}/bin:${PATH}" \
    bash "${REPO_ROOT}/Infrastructure/Network/Tunnel/stop_tunnel.sh" \
    >/dev/null 2>&1 || true
  rm -rf "$TEST_ROOT"
}
trap cleanup EXIT

mkdir -p "${TEST_ROOT}/bin" "$CF_DIR" "$LOG_DIR"

cat >"${TEST_ROOT}/bin/cloudflared" <<'EOF'
#!/usr/bin/env bash
echo 'Registered tunnel connection'
sleep 30 &
wait
EOF
chmod +x "${TEST_ROOT}/bin/cloudflared"

cat >"${TEST_ROOT}/${TUNNEL_ID}.json" <<EOF
{"AccountTag":"test","TunnelSecret":"test","TunnelID":"${TUNNEL_ID}"}
EOF

cat >"$CONFIG_FILE" <<EOF
EVERSPARK_NETWORK_BACKEND=cloudflare
EVERSPARK_LOG_DIR=${LOG_DIR}
CF_TUNNEL_UUID=${TUNNEL_ID}
CF_HOSTNAME=example.test
CF_LOCAL_PORT=8780
CF_TUNNEL_NAME=test
CF_CONFIG_DIR=${CF_DIR}
CF_CREDENTIAL_SOURCE=${TEST_ROOT}/${TUNNEL_ID}.json
EOF

export EVERSPARK_CONFIG_FILE="$CONFIG_FILE"
export PATH="${TEST_ROOT}/bin:${PATH}"

bash "${REPO_ROOT}/Infrastructure/Network/Tunnel/start_tunnel.sh"
test -f "${CF_DIR}/config.yml"
test -f "${CF_DIR}/${TUNNEL_ID}.json"
grep -q 'service: http://127.0.0.1:8780' "${CF_DIR}/config.yml"

bash "${REPO_ROOT}/Infrastructure/Network/Tunnel/check_tunnel.sh"
bash "${REPO_ROOT}/Infrastructure/Network/Tunnel/stop_tunnel.sh"

if pgrep -af "cloudflared.*--config ${CF_DIR}/config.yml.*run" >/dev/null 2>&1; then
  printf 'fake cloudflared process was not stopped\n' >&2
  exit 1
fi

printf 'cloudflare lifecycle tests: OK\n'
