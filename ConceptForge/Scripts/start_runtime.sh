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

command -v ollama >/dev/null 2>&1 || {
  printf '[ERROR] Ollama is not installed. Run ./everspark setup first.\n' >&2
  exit 1
}

mkdir -p "${REPO_ROOT}/Data/Models/ConceptForge/Ollama"
export OLLAMA_HOST="${EVERSPARK_OLLAMA_HOST:-127.0.0.1:11434}"
export OLLAMA_MODELS="${OLLAMA_MODELS:-${REPO_ROOT}/Data/Models/ConceptForge/Ollama}"

gpu_count="$(core_gpu_count)"
if [ "$gpu_count" -ge 2 ]; then
  core_gpu_assign_forge concept
else
  # Release the language model after each request so a single GPU can return
  # its memory to Image Forge before diffusion starts.
  export OLLAMA_KEEP_ALIVE="${OLLAMA_KEEP_ALIVE:-0}"
fi

exec ollama serve
