#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
COMFY_VERSION="${EVERSPARK_COMFYUI_VERSION:-v0.37.0}"
COMFY_COMMIT="${EVERSPARK_COMFYUI_COMMIT:-73c9bad4d21e7addbe1d13bc92eee0f1431b017d}"
OLLAMA_VERSION="${EVERSPARK_OLLAMA_VERSION:-0.34.2}"
TORCH_INDEX_URL="${EVERSPARK_TORCH_INDEX_URL:-https://download.pytorch.org/whl/cu130}"
COMFY_RUNTIME="${REPO_ROOT}/Data/Runtime/ComfyUI"
COMFY_ROOT="${COMFY_RUNTIME}/source"
COMFY_VENV="${COMFY_RUNTIME}/venv"

# shellcheck disable=SC1091
source "${REPO_ROOT}/Runtime/Logging/log.sh"
# shellcheck disable=SC1091
source "${REPO_ROOT}/Shared/Shell/common.sh"
# shellcheck disable=SC1091
source "${REPO_ROOT}/Runtime/System/apt.sh"

core_log_init runtime.install "${REPO_ROOT}/Data/Logs/runtime-install.log"

if ! [[ "$COMFY_VERSION" =~ ^v[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
  core_die runtime.version.invalid "Invalid EVERSPARK_COMFYUI_VERSION" \
    "version=${COMFY_VERSION}"
  exit 1
fi
if ! [[ "$COMFY_COMMIT" =~ ^[0-9a-f]{40}$ ]]; then
  core_die runtime.version.invalid "Invalid EVERSPARK_COMFYUI_COMMIT" \
    "commit=${COMFY_COMMIT}"
  exit 1
fi
if ! [[ "$OLLAMA_VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+([.-][A-Za-z0-9]+)?$ ]]; then
  core_die runtime.version.invalid "Invalid EVERSPARK_OLLAMA_VERSION" \
    "version=${OLLAMA_VERSION}"
  exit 1
fi

if [ "${1:-}" = "--plan" ]; then
  cat <<EOF
Managed runtime plan
  ComfyUI: ${COMFY_VERSION}
  ComfyUI commit: ${COMFY_COMMIT}
  ComfyUI root: ${COMFY_ROOT}
  PyTorch index: ${TORCH_INDEX_URL}
  Ollama: ${OLLAMA_VERSION}
  Service state: ${REPO_ROOT}/Data/Runtime/Services
EOF
  exit 0
fi

if [ "$(uname -s)" != "Linux" ] || ! [[ "$(uname -m)" =~ ^(x86_64|amd64)$ ]]; then
  core_die runtime.platform.unsupported "Managed runtime requires Linux x86_64"
  exit 1
fi

if [ "${EVERSPARK_ALLOW_CPU:-0}" != "1" ]; then
  if ! command -v nvidia-smi >/dev/null 2>&1 || ! nvidia-smi >/dev/null 2>&1; then
    core_die runtime.gpu.missing \
      "NVIDIA GPU runtime was not detected; set EVERSPARK_ALLOW_CPU=1 only for diagnostics"
    exit 1
  fi
fi

required_commands=(git curl python3)
missing_commands=()
for command_name in "${required_commands[@]}"; do
  command -v "$command_name" >/dev/null 2>&1 || missing_commands+=("$command_name")
done
if [ "${#missing_commands[@]}" -gt 0 ]; then
  if [ "${EUID:-$(id -u)}" -ne 0 ]; then
    core_die runtime.command.missing \
      "Missing commands require administrator installation: ${missing_commands[*]}"
    exit 1
  fi
  core_apt_install_missing git curl ca-certificates python3 python3-venv zstd
elif [ "${EUID:-$(id -u)}" -eq 0 ] && command -v apt-get >/dev/null 2>&1; then
  core_apt_install_missing git curl ca-certificates python3 python3-venv zstd
fi

if ! python3 -c 'import venv' >/dev/null 2>&1; then
  core_die runtime.python.venv "Python venv support is unavailable; install python3-venv"
  exit 1
fi

mkdir -p "${REPO_ROOT}/Data/Runtime" "${REPO_ROOT}/Data/Models/ImageForge/checkpoints"

if ! command -v ollama >/dev/null 2>&1; then
  core_info runtime.ollama.install "Installing pinned Ollama runtime" \
    "version=${OLLAMA_VERSION}"
  curl -fsSL https://ollama.com/install.sh | OLLAMA_VERSION="$OLLAMA_VERSION" sh
fi
core_ok runtime.ollama.ready "Ollama runtime is available" \
  "version=$(ollama --version 2>/dev/null || true)"

if [ ! -d "${COMFY_ROOT}/.git" ]; then
  if [ -e "$COMFY_ROOT" ]; then
    core_die runtime.comfy.path "ComfyUI runtime path exists but is not a Git checkout" \
      "path=${COMFY_ROOT}"
    exit 1
  fi
  core_info runtime.comfy.clone "Cloning pinned ComfyUI" "version=${COMFY_VERSION}"
  git clone --depth 1 --branch "$COMFY_VERSION" \
    https://github.com/Comfy-Org/ComfyUI.git "$COMFY_ROOT"
else
  core_info runtime.comfy.update "Refreshing pinned ComfyUI checkout" \
    "version=${COMFY_VERSION}"
  git -C "$COMFY_ROOT" fetch --depth 1 origin tag "$COMFY_VERSION"
  git -C "$COMFY_ROOT" checkout --detach FETCH_HEAD
fi

actual_comfy_commit="$(git -C "$COMFY_ROOT" rev-parse HEAD)"
if [ "$actual_comfy_commit" != "$COMFY_COMMIT" ]; then
  core_die runtime.comfy.commit \
    "ComfyUI tag did not resolve to the expected pinned commit" \
    "version=${COMFY_VERSION}" "expected=${COMFY_COMMIT}" \
    "actual=${actual_comfy_commit}"
  exit 1
fi

if [ ! -x "${COMFY_VENV}/bin/python" ]; then
  python3 -m venv "$COMFY_VENV"
fi
"${COMFY_VENV}/bin/python" -m pip install --disable-pip-version-check --upgrade pip wheel
"${COMFY_VENV}/bin/python" -m pip install \
  torch torchvision torchaudio --index-url "$TORCH_INDEX_URL"
"${COMFY_VENV}/bin/python" -m pip install -r "${COMFY_ROOT}/requirements.txt"

cat >"${COMFY_ROOT}/extra_model_paths.yaml" <<EOF
everspark:
  base_path: ${REPO_ROOT}/Data/Models/ImageForge
  checkpoints: checkpoints
EOF

core_ok runtime.comfy.ready "Managed ComfyUI runtime is ready" \
  "version=${COMFY_VERSION}" "path=${COMFY_ROOT}"
