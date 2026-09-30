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

phase initializing
bash "${repo}/Legate/Crucible/init.sh"
phase installing_runtime
bash "${repo}/Legate/Forge/ConceptForge/Scripts/install_runtime.sh"
phase downloading_models
bash "${repo}/Legate/Crucible/install_models.sh" --models concept --keep-concept-running
