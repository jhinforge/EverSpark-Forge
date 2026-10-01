#!/usr/bin/env bash
set -euo pipefail
repo="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
source "${repo}/Aegis/Shared/Shell/common.sh"
source "${repo}/Legate/Crucible/System/apt.sh"
core_deploy_phase installing_system_dependencies
if [ "${EUID:-$(id -u)}" -eq 0 ] && command -v apt-get >/dev/null 2>&1; then
  core_apt_install_missing python3-venv python3-dev build-essential libsndfile1 git
fi
runtime="${repo}/Data/Runtime/audio-venv"
python3 -c 'import sys; assert (3, 10) <= sys.version_info[:2] < (3, 13), "Audio Forge requires Python 3.10–3.12"'
python3 -m venv "$runtime"
# Ubuntu's venv can seed an old pip without wheel. Bootstrap this isolated
# environment before resolving the Torch/VoxCPM dependency graphs, also on retry.
core_deploy_phase installing_python_dependencies
"${runtime}/bin/python" -m pip install --upgrade 'pip>=24,<26' 'setuptools>=70,<81' 'wheel>=0.43,<1'
source "${repo}/Legate/Warden/Hardware/torch_profile.sh"
profile="$(core_torch_profile_detect)"
core_deploy_phase installing_torch
# Install both binary packages from the same CUDA index. Exact local versions
# also repair an existing mismatched venv when deployment is retried.
constraints="${runtime}/torch-constraints.txt"
printf 'torch==2.9.1+%s\ntorchaudio==2.9.1+%s\n' "$profile" "$profile" > "$constraints"
"${runtime}/bin/python" -m pip install --upgrade --index-url "$(core_torch_profile_index "$profile")" \
  "torch==2.9.1+${profile}" "torchaudio==2.9.1+${profile}"
core_deploy_phase installing_python_dependencies
# Pin the current upstream source by full commit, rather than following main.
"${runtime}/bin/python" -m pip install --upgrade --constraint "$constraints" \
  --requirement "${repo}/Legate/Forge/AudioForge/requirements.txt" soundfile huggingface_hub
"${runtime}/bin/python" -m pip check
# Import native extensions and the actual SDK before downloading models.
PYTHONPATH="${repo}${PYTHONPATH:+:${PYTHONPATH}}" "${runtime}/bin/python" -c \
  'from Legate.Forge.AudioForge.audio_forge.voxcpm import validate_runtime; validate_runtime()'
core_deploy_phase downloading_models
"${runtime}/bin/python" "${repo}/Aegis/Storage/model_snapshot.py"
