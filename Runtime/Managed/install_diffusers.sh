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
source "${REPO_ROOT}/Runtime/Hardware/torch_profile.sh"

TORCH_VERSION="2.9.1"
TORCH_PROFILE="$(core_torch_profile_detect)"
TORCH_INDEX_URL="$(core_torch_profile_index "$TORCH_PROFILE")"
TORCH_EXPECTED_CUDA="$(core_torch_profile_expected_cuda "$TORCH_PROFILE")"
TORCH_PROFILE_REVISION="${TORCH_PROFILE}-torch${TORCH_VERSION}-v2"
DIFFUSERS_RUNTIME="${REPO_ROOT}/Data/Runtime/Diffusers"
DIFFUSERS_VENV="${DIFFUSERS_RUNTIME}/venv"

if [ -d "$DIFFUSERS_VENV" ] && [ "$(cat "${DIFFUSERS_RUNTIME}/torch-profile" 2>/dev/null || true)" != "$TORCH_PROFILE_REVISION" ]; then
  rm -rf -- "$DIFFUSERS_VENV"
fi
if [ ! -x "${DIFFUSERS_VENV}/bin/python" ]; then
  python3 -m venv "$DIFFUSERS_VENV"
  "${DIFFUSERS_VENV}/bin/python" -m pip install --disable-pip-version-check \
    --index-url "$TORCH_INDEX_URL" "torch==${TORCH_VERSION}"
fi
rm -f -- "${DIFFUSERS_RUNTIME}/peft-ready"
"${DIFFUSERS_VENV}/bin/python" -m pip install --disable-pip-version-check \
  'diffusers==0.35.1' 'transformers>=4.44,<5' 'accelerate>=1,<2' \
  'peft>=0.17,<0.20' safetensors
EVERSPARK_EXPECTED_TORCH_VERSION="$TORCH_VERSION" \
EVERSPARK_EXPECTED_TORCH_CUDA="$TORCH_EXPECTED_CUDA" \
  "${DIFFUSERS_VENV}/bin/python" - <<'PY'
import os
import diffusers
import torch
import peft
from diffusers.utils import USE_PEFT_BACKEND

if not USE_PEFT_BACKEND:
    raise SystemExit("Diffusers PEFT backend is unavailable")

if not torch.__version__.startswith(os.environ["EVERSPARK_EXPECTED_TORCH_VERSION"]):
    raise SystemExit(f"Wrong Diffusers PyTorch version: {torch.__version__}")
if not (torch.version.cuda or "").startswith(os.environ["EVERSPARK_EXPECTED_TORCH_CUDA"]):
    raise SystemExit(f"Wrong Diffusers CUDA profile: {torch.version.cuda}")
if not torch.cuda.is_available() and os.environ.get("EVERSPARK_ALLOW_CPU") != "1":
    raise SystemExit("CUDA is unavailable to Diffusers")
print("Diffusers:", diffusers.__version__, "PEFT:", peft.__version__,
      "PyTorch:", torch.__version__)
PY
printf '%s\n' "$TORCH_PROFILE_REVISION" > "${DIFFUSERS_RUNTIME}/torch-profile"
printf '%s\n' 'peft-ready' > "${DIFFUSERS_RUNTIME}/peft-ready"
