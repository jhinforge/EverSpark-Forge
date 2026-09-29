#!/usr/bin/env bash
set -euo pipefail

# Vast's SSH container cannot be assumed to expose /dev/net/tun.
# Tailscale's userspace HTTP proxy carries Agent -> Archon registration/polls.
if ! command -v tailscaled >/dev/null 2>&1; then
  curl -fsSL https://tailscale.com/install.sh | sh
fi
tailscaled --tun=userspace-networking \
  --outbound-http-proxy-listen=127.0.0.1:1055 \
  --state=/workspace/everspark-tailscale.state >/workspace/everspark-tailscale.log 2>&1 &
for attempt in $(seq 1 30); do
  if tailscale status >/dev/null 2>&1; then break; fi
  sleep 1
done
if ! tailscale ip -4 >/dev/null 2>&1; then
  # The auth key supplies the node identity; a hardcoded tag requires a
  # corresponding tagOwners rule in the user's tailnet and blocks registration.
  tailscale up --auth-key="${EVERSPARK_TAILSCALE_AUTH_KEY:?}"
fi
unset EVERSPARK_TAILSCALE_AUTH_KEY
cd /workspace/EverSpark-Forge
exec python3 -m Legate.Envoy.node_agent
