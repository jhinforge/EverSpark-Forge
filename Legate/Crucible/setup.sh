#!/usr/bin/env bash
set -euo pipefail

LAUNCHER_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${LAUNCHER_DIR}/../.." && pwd)"
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
  bash "${REPO_ROOT}/Legate/Crucible/install_runtime.sh" --plan
  if [ "$SKIP_MODELS" = false ]; then
    python3 "${REPO_ROOT}/Legate/Crucible/Models/model_manager.py" plan --models "$SELECTION"
  fi
  exit 0
fi

bash "${LAUNCHER_DIR}/init.sh"

if [ "${EVERSPARK_NETWORK_BACKEND:-local}" = "cloudflare" ]; then
  # shellcheck disable=SC1091
  source "${REPO_ROOT}/Aegis/Network/cloudflared.sh"
  core_cloudflared_install
fi

if [ "${EVERSPARK_STORAGE_BACKEND:-local}" = "rclone" ]; then
  # shellcheck disable=SC1091
  source "${REPO_ROOT}/Aegis/Storage/rclone.sh"
  core_rclone_install
fi

bash "${REPO_ROOT}/Legate/Crucible/install_runtime.sh"
if [ -f "${REPO_ROOT}/Legate/Warden/image_backend.py" ] &&
   [ "$(python3 "${REPO_ROOT}/Legate/Warden/image_backend.py")" = "diffusers" ]; then
  bash "${REPO_ROOT}/Legate/Crucible/install_diffusers.sh"
fi

if [ "$SKIP_MODELS" = true ]; then
  bash "${REPO_ROOT}/Archon/Gate/CLI/install.sh"
  exit 0
fi

model_options=(--models "$SELECTION")
if [ "$SKIP_IMPORT" = true ]; then model_options+=(--skip-concept-import); fi
bash "${REPO_ROOT}/Legate/Crucible/install_models.sh" "${model_options[@]}"

bash "${REPO_ROOT}/Archon/Gate/CLI/install.sh"
