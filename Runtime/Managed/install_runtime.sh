#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
COMFY_VERSION="${EVERSPARK_COMFYUI_VERSION:-v0.37.0}"
COMFY_COMMIT="${EVERSPARK_COMFYUI_COMMIT:-73c9bad4d21e7addbe1d13bc92eee0f1431b017d}"
OLLAMA_VERSION="${EVERSPARK_OLLAMA_VERSION:-0.34.2}"
COMFY_RUNTIME="${REPO_ROOT}/Data/Runtime/ComfyUI"
COMFY_ROOT="${COMFY_RUNTIME}/source"
COMFY_VENV="${COMFY_RUNTIME}/venv"
TORCH_PROFILE_STATE="${COMFY_RUNTIME}/torch-profile"

# shellcheck disable=SC1091
source "${REPO_ROOT}/Runtime/Logging/log.sh"
# shellcheck disable=SC1091
source "${REPO_ROOT}/Shared/Shell/common.sh"
# shellcheck disable=SC1091
source "${REPO_ROOT}/Runtime/System/apt.sh"
# shellcheck disable=SC1091
source "${REPO_ROOT}/Runtime/Hardware/torch_profile.sh"

TORCH_PROFILE="$(core_torch_profile_detect)"
TORCH_INDEX_URL="$(core_torch_profile_index "$TORCH_PROFILE")"
TORCH_EXPECTED_CUDA="$(core_torch_profile_expected_cuda "$TORCH_PROFILE")"
TORCH_PROFILE_REVISION="${TORCH_PROFILE}-v1"
DETECTED_GPU="$(core_gpu_name 2>/dev/null || true)"
DETECTED_COMPUTE_CAPABILITY="$(core_gpu_compute_capability 2>/dev/null || true)"
DETECTED_BASE_CUDA="$(core_cuda_runtime_version 2>/dev/null || true)"
DETECTED_GPU="${DETECTED_GPU:-unknown}"
DETECTED_COMPUTE_CAPABILITY="${DETECTED_COMPUTE_CAPABILITY:-unknown}"
DETECTED_BASE_CUDA="${DETECTED_BASE_CUDA:-unknown}"

LOG_DIR="${EVERSPARK_LOG_DIR:-${REPO_ROOT}/Data/Logs}"
if [[ "$LOG_DIR" != /* ]]; then
  LOG_DIR="${REPO_ROOT}/${LOG_DIR#./}"
fi
core_log_init runtime.install "${LOG_DIR}/runtime-install.log"

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
  Detected GPU: ${DETECTED_GPU}
  Detected compute capability: ${DETECTED_COMPUTE_CAPABILITY}
  Detected base CUDA: ${DETECTED_BASE_CUDA}
  Selected PyTorch profile: ${TORCH_PROFILE}
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

core_info runtime.torch.profile "Selected managed PyTorch compatibility profile" \
  "profile=${TORCH_PROFILE}" \
  "gpu=${DETECTED_GPU}" \
  "compute_capability=${DETECTED_COMPUTE_CAPABILITY}" \
  "base_cuda=${DETECTED_BASE_CUDA}"

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

installed_profile=""
if [ -f "$TORCH_PROFILE_STATE" ]; then
  installed_profile="$(tr -d '[:space:]' < "$TORCH_PROFILE_STATE")"
fi
environment_matches=0
if [ -x "${COMFY_VENV}/bin/python" ] \
  && [ "$installed_profile" = "$TORCH_PROFILE_REVISION" ]; then
  installed_cuda="$("${COMFY_VENV}/bin/python" - <<'PY' 2>/dev/null || true
try:
    import torch
    print(torch.version.cuda or "")
except Exception:
    pass
PY
)"
  if [[ "$installed_cuda" == "$TORCH_EXPECTED_CUDA"* ]]; then
    environment_matches=1
  fi
fi
if [ -d "$COMFY_VENV" ] && [ "$environment_matches" -ne 1 ]; then
  core_info runtime.torch.rebuild "Rebuilding managed environment for selected profile" \
    "installed=${installed_profile:-legacy}" "selected=${TORCH_PROFILE_REVISION}" \
    "installed_cuda=${installed_cuda:-unknown}"
  rm -rf -- "$COMFY_VENV"
fi

new_environment=0
if [ ! -x "${COMFY_VENV}/bin/python" ]; then
  python3 -m venv "$COMFY_VENV"
  new_environment=1
fi
"${COMFY_VENV}/bin/python" -m pip install --disable-pip-version-check --upgrade pip wheel
if [ "$new_environment" -eq 1 ]; then
  case "$TORCH_PROFILE" in
    cu121)
      "${COMFY_VENV}/bin/python" -m pip install \
        --index-url "$TORCH_INDEX_URL" \
        --extra-index-url https://pypi.org/simple \
        "torch==2.5.1+cu121" \
        "torchvision==0.20.1+cu121" \
        "torchaudio==2.5.1+cu121"
      "${COMFY_VENV}/bin/python" -m pip install \
        "xformers==0.0.27.post2" --no-deps
      ;;
    cu128)
      "${COMFY_VENV}/bin/python" -m pip install \
        torch torchvision torchaudio --index-url "$TORCH_INDEX_URL"
      ;;
    *)
      core_die runtime.torch.profile "Unsupported internal PyTorch profile" \
        "profile=${TORCH_PROFILE}"
      exit 1
      ;;
  esac
fi
"${COMFY_VENV}/bin/python" -m pip install -r "${COMFY_ROOT}/requirements.txt"

EVERSPARK_EXPECTED_TORCH_CUDA="$TORCH_EXPECTED_CUDA" \
EVERSPARK_ALLOW_CPU="${EVERSPARK_ALLOW_CPU:-0}" \
  "${COMFY_VENV}/bin/python" - <<'PY'
import os

import torch

expected = os.environ["EVERSPARK_EXPECTED_TORCH_CUDA"]
actual = str(torch.version.cuda or "")
print("EverSpark PyTorch health check")
print("  torch:", torch.__version__)
print("  torch CUDA:", actual or "unavailable")
print("  CUDA available:", torch.cuda.is_available())

if not actual.startswith(expected):
    raise SystemExit(f"PyTorch CUDA mismatch: expected {expected}, got {actual or 'none'}")

if os.environ.get("EVERSPARK_ALLOW_CPU") != "1":
    if not torch.cuda.is_available():
        raise SystemExit("CUDA is unavailable in the selected PyTorch profile")
    print("  device:", torch.cuda.get_device_name(0))
    print("  capability:", torch.cuda.get_device_capability(0))
    print("  CUDA tensor:", torch.ones(1, device="cuda"))
PY

printf '%s\n' "$TORCH_PROFILE_REVISION" > "$TORCH_PROFILE_STATE"

cat >"${COMFY_ROOT}/extra_model_paths.yaml" <<EOF
everspark:
  base_path: ${REPO_ROOT}/Data/Models/ImageForge
  checkpoints: checkpoints
  diffusion_models: diffusion_models
  loras: loras
EOF

core_ok runtime.comfy.ready "Managed ComfyUI runtime is ready" \
  "version=${COMFY_VERSION}" "path=${COMFY_ROOT}"
