#!/usr/bin/env bash
set -euo pipefail

LAUNCHER_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${LAUNCHER_DIR}/.." && pwd)"
MODEL_TOOLS="${REPO_ROOT}/Data/Runtime/ModelTools"
SELECTION="all"
PLAN_ONLY=false
SKIP_IMPORT=false

usage() {
  cat <<'EOF'
Usage: ./everspark setup [--plan] [--models all|concept|image] [--skip-concept-import]

Downloads the selected official default models from Hugging Face. Concept setup
also imports the local GGUF into Ollama unless --skip-concept-import is supplied.
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
    -h|--help) usage; exit 0 ;;
    *) printf '[ERROR] unknown setup option: %s\n' "$1" >&2; usage >&2; exit 2 ;;
  esac
  shift
done

case "$SELECTION" in all|concept|image) ;; *) printf '[ERROR] invalid model selection: %s\n' "$SELECTION" >&2; exit 2 ;; esac

if [ "$PLAN_ONLY" = true ]; then
  exec python3 "${REPO_ROOT}/Runtime/Models/model_manager.py" plan --models "$SELECTION"
fi

bash "${LAUNCHER_DIR}/init.sh"
python3 -m venv "$MODEL_TOOLS"
"${MODEL_TOOLS}/bin/python" -m pip install --disable-pip-version-check 'huggingface_hub>=1,<2'
"${MODEL_TOOLS}/bin/python" "${REPO_ROOT}/Runtime/Models/model_manager.py" download --models "$SELECTION"

if { [ "$SELECTION" = all ] || [ "$SELECTION" = concept ]; } && [ "$SKIP_IMPORT" = false ]; then
  "${MODEL_TOOLS}/bin/python" "${REPO_ROOT}/Runtime/Models/model_manager.py" import-concept
fi
