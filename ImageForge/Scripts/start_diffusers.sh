#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
if [ -f "${REPO_ROOT}/.env" ]; then
  set -a
  # shellcheck disable=SC1091
  source "${REPO_ROOT}/.env"
  set +a
fi

DIFFUSERS_PYTHON="${REPO_ROOT}/Data/Runtime/Diffusers/venv/bin/python"
[ -x "$DIFFUSERS_PYTHON" ] || {
  printf '[ERROR] Diffusers is not installed. Install it from Image Forge in WebUI.\n' >&2
  exit 1
}
export EVERSPARK_DIFFUSERS_URL="$(python3 "${REPO_ROOT}/Runtime/Managed/image_backend.py" --url)"
export PYTHONPATH="${REPO_ROOT}/ImageForge${PYTHONPATH:+:${PYTHONPATH}}"
# shellcheck disable=SC1091
source "${REPO_ROOT}/Runtime/Hardware/gpu_assignment.sh"
core_gpu_assign_forge image
cd "$REPO_ROOT"
exec "$DIFFUSERS_PYTHON" -m image_forge.diffusers_worker
