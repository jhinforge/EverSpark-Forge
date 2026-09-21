#!/usr/bin/env bash
set -euo pipefail

LAUNCHER_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${LAUNCHER_DIR}/.." && pwd)"

# shellcheck disable=SC1091
source "${REPO_ROOT}/Runtime/Logging/log.sh"
# shellcheck disable=SC1091
source "${REPO_ROOT}/Shared/Shell/common.sh"

LOG_DIR="${EVERSPARK_LOG_DIR:-${REPO_ROOT}/Data/Logs}"
core_log_init launcher.init "${LOG_DIR}/launcher.log"

directories=(
  "${REPO_ROOT}/Data/Logs"
  "${REPO_ROOT}/Data/Outputs"
  "${REPO_ROOT}/Data/Memory"
  "${REPO_ROOT}/Data/Runtime"
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
