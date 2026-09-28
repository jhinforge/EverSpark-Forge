#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
MODEL_TOOLS="${REPO_ROOT}/Data/Runtime/ModelTools"
SELECTION=all
SKIP_IMPORT=false
KEEP_CONCEPT_RUNNING=false

while [ "$#" -gt 0 ]; do
  case "$1" in
    --models)
      [ "$#" -ge 2 ] || { printf '[ERROR] --models requires a value\n' >&2; exit 2; }
      SELECTION="$2"; shift ;;
    --skip-concept-import) SKIP_IMPORT=true ;;
    --keep-concept-running) KEEP_CONCEPT_RUNNING=true ;;
    *) printf '[ERROR] unknown model install option: %s\n' "$1" >&2; exit 2 ;;
  esac
  shift
done
case "$SELECTION" in all|concept|image) ;; *) printf '[ERROR] invalid model selection: %s\n' "$SELECTION" >&2; exit 2 ;; esac

# These are the same model steps previously run inline by setup.sh.
python3 -m venv "$MODEL_TOOLS"
"${MODEL_TOOLS}/bin/python" -m pip install --disable-pip-version-check 'huggingface_hub>=1,<2'
"${MODEL_TOOLS}/bin/python" "${REPO_ROOT}/Legate/Crucible/Models/model_manager.py" download --models "$SELECTION"

if { [ "$SELECTION" = all ] || [ "$SELECTION" = concept ]; } && [ "$SKIP_IMPORT" = false ]; then
  concept_was_running=false
  if python3 "${REPO_ROOT}/Legate/Warden/runtime_manager.py" status concept \
    | grep -q '"managed": true'; then
    concept_was_running=true
  fi
  python3 "${REPO_ROOT}/Legate/Warden/runtime_manager.py" start concept
  cleanup_setup_concept() {
    if [ "$KEEP_CONCEPT_RUNNING" = false ] && [ "$concept_was_running" = false ]; then
      python3 "${REPO_ROOT}/Legate/Warden/runtime_manager.py" stop concept \
        >/dev/null 2>&1 || true
    fi
  }
  trap cleanup_setup_concept EXIT
  export OLLAMA_HOST="${EVERSPARK_OLLAMA_HOST:-127.0.0.1:11434}"
  export OLLAMA_MODELS="${OLLAMA_MODELS:-${REPO_ROOT}/Data/Models/ConceptForge/Ollama}"
  "${MODEL_TOOLS}/bin/python" "${REPO_ROOT}/Legate/Crucible/Models/model_manager.py" import-concept
  trap - EXIT
  cleanup_setup_concept
fi
