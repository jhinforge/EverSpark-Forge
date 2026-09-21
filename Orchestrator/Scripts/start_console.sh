#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
REPO_ROOT="$(cd "${PROJECT_ROOT}/.." && pwd)"
if [ -f "${REPO_ROOT}/.env" ]; then
  set -a
  # shellcheck disable=SC1091
  source "${REPO_ROOT}/.env"
  set +a
fi
export PYTHONPATH="${REPO_ROOT}/Orchestrator:${REPO_ROOT}/ConceptForge:${REPO_ROOT}/ImageForge:${REPO_ROOT}/Memory:${PYTHONPATH:+:${PYTHONPATH}}"
cd "$PROJECT_ROOT"
exec python3 -m orchestrator.cli.console
