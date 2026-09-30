#!/usr/bin/env bash
set -euo pipefail
phase() {
  if [ "${EVERSPARK_DEPLOY_PROGRESS:-0}" = 1 ]; then
    printf '[EverSpark:deploy] %s\n' "$1"
  fi
}

repo="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../.." && pwd)"
if [ -f "${repo}/.env" ]; then
  set -a
  # shellcheck disable=SC1091
  source "${repo}/.env"
  set +a
fi

bash "${repo}/Legate/Crucible/setup.sh" --models image
phase starting_service
backend="$(python3 "${repo}/Legate/Warden/image_backend.py")"
if [ "$backend" = diffusers ]; then
  python3 "${repo}/Legate/Warden/runtime_manager.py" start diffusers
else
  python3 "${repo}/Legate/Warden/runtime_manager.py" start image
fi
phase checking_health
python3 "${repo}/Legate/Forge/ImageForge/verify.py"
