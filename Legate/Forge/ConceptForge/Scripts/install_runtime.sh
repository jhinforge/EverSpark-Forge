#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../../../.." && pwd)"
OLLAMA_VERSION="${EVERSPARK_OLLAMA_VERSION:-0.34.2}"

# shellcheck disable=SC1091
source "${REPO_ROOT}/Aegis/Logging/log.sh"
# shellcheck disable=SC1091
source "${REPO_ROOT}/Aegis/Shared/Shell/common.sh"
# shellcheck disable=SC1091
source "${REPO_ROOT}/Legate/Crucible/System/apt.sh"

LOG_DIR="${EVERSPARK_LOG_DIR:-${REPO_ROOT}/Data/Logs}"
if [[ "$LOG_DIR" != /* ]]; then
  LOG_DIR="${REPO_ROOT}/${LOG_DIR#./}"
fi
core_log_init concept.runtime "${LOG_DIR}/runtime/concept-install.log"

if ! [[ "$OLLAMA_VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+([.-][A-Za-z0-9]+)?$ ]]; then
  core_die runtime.version.invalid "Invalid EVERSPARK_OLLAMA_VERSION" "version=${OLLAMA_VERSION}"
  exit 1
fi
if [ "$(uname -s)" != "Linux" ] || ! [[ "$(uname -m)" =~ ^(x86_64|amd64)$ ]]; then
  core_die runtime.platform.unsupported "Managed runtime requires Linux x86_64"
  exit 1
fi
if [ "${EVERSPARK_ALLOW_CPU:-0}" != "1" ]; then
  if ! command -v nvidia-smi >/dev/null 2>&1 || ! nvidia-smi >/dev/null 2>&1; then
    core_die runtime.gpu.missing "NVIDIA GPU runtime was not detected; set EVERSPARK_ALLOW_CPU=1 only for diagnostics"
    exit 1
  fi
fi

# The full setup and the Pod deployment share these Concept Forge prerequisites.
# In particular, Ollama's installer requires zstd to unpack the runtime.
concept_packages=(git curl ca-certificates python3 python3-venv zstd)
if [ "${EUID:-$(id -u)}" -eq 0 ] && command -v apt-get >/dev/null 2>&1; then
  core_apt_install_missing "${concept_packages[@]}"
else
  for command_name in git curl python3 zstd; do
    command -v "$command_name" >/dev/null 2>&1 || {
      core_die runtime.command.missing "Missing Concept Forge command: ${command_name}"
      exit 1
    }
  done
fi
if ! python3 -c 'import venv' >/dev/null 2>&1; then
  core_die runtime.python.venv "Python venv support is unavailable; install python3-venv"
  exit 1
fi

mkdir -p "${REPO_ROOT}/Data/Runtime" "${REPO_ROOT}/Data/Models/ConceptForge"
if ! command -v ollama >/dev/null 2>&1; then
  core_info runtime.ollama.install "Installing pinned Ollama runtime" "version=${OLLAMA_VERSION}"
  curl -fsSL https://ollama.com/install.sh | OLLAMA_VERSION="$OLLAMA_VERSION" sh
fi
core_ok runtime.ollama.ready "Ollama runtime is available" \
  "version=$(ollama --version 2>/dev/null || true)"
