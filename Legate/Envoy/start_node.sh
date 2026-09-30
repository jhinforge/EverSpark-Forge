#!/usr/bin/env bash
set -euo pipefail
stage=install_tailscale
status_file=/workspace/everspark-startup.status
printf '%s\n' "$stage" > "$status_file"
trap 'printf "failed:%s\n" "$stage" > "$status_file"; printf "[EverSpark] startup failed at %s\n" "$stage" >&2' ERR
printf '[EverSpark] stage: %s\n' "$stage"

# Vast's SSH container cannot be assumed to expose /dev/net/tun.
# Tailscale's userspace HTTP proxy carries Agent -> Archon registration/polls.
if ! command -v tailscaled >/dev/null 2>&1; then
  curl -fsSL https://tailscale.com/install.sh | sh
fi
stage=start_tailscaled
printf '%s\n' "$stage" > "$status_file"
printf '[EverSpark] stage: %s\n' "$stage"
if ! tailscale status >/dev/null 2>&1; then
  tailscaled --tun=userspace-networking \
    --outbound-http-proxy-listen=127.0.0.1:1055 \
    --state=/workspace/everspark-tailscale.state >/workspace/everspark-tailscale.log 2>&1 &
fi
for attempt in $(seq 1 30); do
  if tailscale status >/dev/null 2>&1; then break; fi
  sleep 1
done
if ! tailscale ip -4 >/dev/null 2>&1; then
  stage=authenticate_tailscale
  printf '%s\n' "$stage" > "$status_file"
  printf '[EverSpark] stage: %s\n' "$stage"
  # The auth key supplies the node identity; a hardcoded tag requires a
  # corresponding tagOwners rule in the user's tailnet and blocks registration.
  # A previous failed attempt may have left the old tag preference in state.
  # Tailscale requires --reset when changing that preference.
  if ! output=$(tailscale up --reset --auth-key="${EVERSPARK_TAILSCALE_AUTH_KEY:?}" 2>&1); then
    printf '%s\n' "$output" | sed -E 's/tskey-[[:alnum:]_-]+/[REDACTED]/g' >&2
    printf 'failed:%s\n' "$stage" > "$status_file"
    printf '[EverSpark] startup failed at %s\n' "$stage" >&2
    exit 1
  fi
fi
unset EVERSPARK_TAILSCALE_AUTH_KEY
stage=register_agent
printf '%s\n' "$stage" > "$status_file"
printf '[EverSpark] stage: %s\n' "$stage"
cd /workspace/EverSpark-Forge
export EVERSPARK_NODE_PROVIDER=vast
export EVERSPARK_NODE_PROVIDER_INSTANCE_ID="${CONTAINER_ID:-}"
export EVERSPARK_NODE_PROXY=http://127.0.0.1:1055
export EVERSPARK_NODE_DATA_DIR=/workspace/everspark-node
export EVERSPARK_TASK_JOURNAL=/workspace/everspark-agent-tasks.json
export EVERSPARK_STARTUP_STATUS="$status_file"
exec python3 -m Legate.Envoy.supervisor
