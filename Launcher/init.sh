#!/usr/bin/env bash
set -euo pipefail

LAUNCHER_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${LAUNCHER_DIR}/.." && pwd)"

# shellcheck disable=SC1091
source "${REPO_ROOT}/Runtime/Logging/log.sh"
# shellcheck disable=SC1091
source "${REPO_ROOT}/Shared/Shell/common.sh"

if [ -f "${REPO_ROOT}/.env" ]; then
  set -a
  # shellcheck disable=SC1091
  source "${REPO_ROOT}/.env"
  set +a
fi

LOG_DIR="${EVERSPARK_LOG_DIR:-${REPO_ROOT}/Data/Logs}"
if [[ "$LOG_DIR" != /* ]]; then
  LOG_DIR="${REPO_ROOT}/${LOG_DIR#./}"
fi
core_log_init launcher.init "${LOG_DIR}/launcher/launcher.log"

directories=(
  "${REPO_ROOT}/Data/Logs"
  "${LOG_DIR}/launcher"
  "${LOG_DIR}/runtime"
  "${LOG_DIR}/concept"
  "${LOG_DIR}/image"
  "${LOG_DIR}/orchestrator"
  "${LOG_DIR}/webui"
  "${LOG_DIR}/tunnel"
  "${LOG_DIR}/storage"
  "${REPO_ROOT}/Data/Outputs"
  "${REPO_ROOT}/Data/Memory"
  "${REPO_ROOT}/Data/Runtime"
  "${REPO_ROOT}/Data/Runtime/Services"
  "${REPO_ROOT}/Configuration/Import"
  "${REPO_ROOT}/Data/Configuration/cloudflare"
  "${REPO_ROOT}/Data/Configuration/rclone"
  "${REPO_ROOT}/Data/Cloudflare"
  "${REPO_ROOT}/Data/Models/ConceptForge"
  "${REPO_ROOT}/Data/Models/ImageForge/checkpoints"
)

for directory in "${directories[@]}"; do
  core_ensure_dir "$directory"
done

core_ok launcher.init.ready "Local EverSpark directories are ready" \
  "data_directory=${REPO_ROOT}/Data"

if [ -f "${REPO_ROOT}/.env" ]; then
  core_info launcher.config.detected "Optional environment configuration detected" \
    "path=${REPO_ROOT}/.env"
else
  core_info launcher.config.defaults "No .env file found; local defaults remain active"
fi
