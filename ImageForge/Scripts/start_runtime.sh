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

# shellcheck disable=SC1091
source "${REPO_ROOT}/Runtime/Hardware/gpu_assignment.sh"
core_gpu_assign_forge image

COMFY_ROOT="${EVERSPARK_COMFYUI_ROOT:-${REPO_ROOT}/Data/Runtime/ComfyUI/source}"
COMFY_PYTHON="${EVERSPARK_COMFYUI_PYTHON:-${REPO_ROOT}/Data/Runtime/ComfyUI/venv/bin/python}"
OUTPUT_DIRECTORY="${EVERSPARK_OUTPUT_DIR:-${REPO_ROOT}/Data/Outputs}"
if [[ "$OUTPUT_DIRECTORY" != /* ]]; then
  OUTPUT_DIRECTORY="${REPO_ROOT}/${OUTPUT_DIRECTORY#./}"
fi

[ -f "${COMFY_ROOT}/main.py" ] || {
  printf '[ERROR] Managed ComfyUI is not installed. Run ./everspark setup first.\n' >&2
  exit 1
}
[ -x "$COMFY_PYTHON" ] || {
  printf '[ERROR] Managed ComfyUI Python is unavailable: %s\n' "$COMFY_PYTHON" >&2
  exit 1
}

mkdir -p "$OUTPUT_DIRECTORY"
cd "$COMFY_ROOT"
exec "$COMFY_PYTHON" main.py \
  --listen "${EVERSPARK_IMAGE_FORGE_HOST:-127.0.0.1}" \
  --port "${EVERSPARK_IMAGE_FORGE_PORT:-8188}" \
  --output-directory "$OUTPUT_DIRECTORY" \
  --disable-auto-launch
