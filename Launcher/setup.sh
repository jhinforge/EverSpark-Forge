#!/usr/bin/env bash
set -euo pipefail

LAUNCHER_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${LAUNCHER_DIR}/.." && pwd)"
MODEL_TOOLS="${REPO_ROOT}/Data/Runtime/ModelTools"
SELECTION="all"
PLAN_ONLY=false
SKIP_IMPORT=false
SKIP_MODELS=false

if [ -f "${REPO_ROOT}/.env" ]; then
  set -a
  # shellcheck disable=SC1091
  source "${REPO_ROOT}/.env"
  set +a
fi

usage() {
  cat <<'EOF'
Usage: ./everspark setup [--plan] [--models all|concept|image]
                         [--skip-models] [--skip-concept-import]

Downloads the selected official default models from Hugging Face. Concept setup
also imports the local GGUF into Ollama unless --skip-concept-import is supplied.
ComfyUI and Ollama runtimes are installed before models. Optional Diffusers
can be installed later from the Forge drawing tool selector in WebUI.
--plan only prints the sources and destinations and makes no changes.
EOF
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --plan) PLAN_ONLY=true ;;
    --models)
      [ "$#" -ge 2 ] || { printf '[ERROR] --models requires a value\n' >&2; exit 2; }
      SELECTION="$2"
      shift
      ;;
    --skip-concept-import) SKIP_IMPORT=true ;;
    --skip-models) SKIP_MODELS=true ;;
    -h|--help) usage; exit 0 ;;
    *) printf '[ERROR] unknown setup option: %s\n' "$1" >&2; usage >&2; exit 2 ;;
  esac
  shift
done

case "$SELECTION" in all|concept|image) ;; *) printf '[ERROR] invalid model selection: %s\n' "$SELECTION" >&2; exit 2 ;; esac

if [ "$PLAN_ONLY" = true ]; then
  bash "${REPO_ROOT}/Runtime/Managed/install_runtime.sh" --plan
  if [ "$SKIP_MODELS" = false ]; then
    python3 "${REPO_ROOT}/Runtime/Models/model_manager.py" plan --models "$SELECTION"
  fi
  exit 0
fi

bash "${LAUNCHER_DIR}/init.sh"

if [ "${EVERSPARK_NETWORK_BACKEND:-local}" = "cloudflare" ]; then
  # shellcheck disable=SC1091
  source "${REPO_ROOT}/Infrastructure/Network/cloudflared.sh"
  core_cloudflared_install
fi

if [ "${EVERSPARK_STORAGE_BACKEND:-local}" = "rclone" ]; then
  # shellcheck disable=SC1091
  source "${REPO_ROOT}/Infrastructure/Storage/rclone.sh"
  core_rclone_install
fi

bash "${REPO_ROOT}/Runtime/Managed/install_runtime.sh"
if [ -f "${REPO_ROOT}/Runtime/Managed/image_backend.py" ] &&
   [ "$(python3 "${REPO_ROOT}/Runtime/Managed/image_backend.py")" = "diffusers" ]; then
  bash "${REPO_ROOT}/Runtime/Managed/install_diffusers.sh"
fi

if [ "$SKIP_MODELS" = true ]; then
  bash "${LAUNCHER_DIR}/install.sh"
  exit 0
fi

python3 -m venv "$MODEL_TOOLS"
"${MODEL_TOOLS}/bin/python" -m pip install --disable-pip-version-check 'huggingface_hub>=1,<2'
"${MODEL_TOOLS}/bin/python" "${REPO_ROOT}/Runtime/Models/model_manager.py" download --models "$SELECTION"

if { [ "$SELECTION" = all ] || [ "$SELECTION" = concept ]; } && [ "$SKIP_IMPORT" = false ]; then
  concept_was_running=false
  if python3 "${REPO_ROOT}/Runtime/Managed/runtime_manager.py" status concept \
    | grep -q '"managed": true'; then
    concept_was_running=true
  fi
  python3 "${REPO_ROOT}/Runtime/Managed/runtime_manager.py" start concept
  cleanup_setup_concept() {
    if [ "$concept_was_running" = false ]; then
      python3 "${REPO_ROOT}/Runtime/Managed/runtime_manager.py" stop concept \
        >/dev/null 2>&1 || true
    fi
  }
  trap cleanup_setup_concept EXIT
  export OLLAMA_HOST="${EVERSPARK_OLLAMA_HOST:-127.0.0.1:11434}"
  export OLLAMA_MODELS="${OLLAMA_MODELS:-${REPO_ROOT}/Data/Models/ConceptForge/Ollama}"
  "${MODEL_TOOLS}/bin/python" "${REPO_ROOT}/Runtime/Models/model_manager.py" import-concept
  trap - EXIT
  cleanup_setup_concept
fi

bash "${LAUNCHER_DIR}/install.sh"
