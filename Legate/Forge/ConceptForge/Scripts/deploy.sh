#!/usr/bin/env bash
set -euo pipefail

repo="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../.." && pwd)"
if [ -f "${repo}/.env" ]; then
  set -a
  # shellcheck disable=SC1091
  source "${repo}/.env"
  set +a
fi

bash "${repo}/Legate/Crucible/init.sh"
bash "${repo}/Legate/Forge/ConceptForge/Scripts/install_runtime.sh"
bash "${repo}/Legate/Crucible/install_models.sh" --models concept --keep-concept-running
