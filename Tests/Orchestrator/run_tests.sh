#!/usr/bin/env bash
set -euo pipefail

TEST_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${TEST_DIR}/../.." && pwd)"
export PYTHONPATH="${REPO_ROOT}/Archon/Orchestrator:${REPO_ROOT}/Legate/Forge:${REPO_ROOT}/Legate/Forge/ConceptForge:${REPO_ROOT}/Legate/Forge/ImageForge:${REPO_ROOT}/Legate/Forge/ConceptForge/Memory:${REPO_ROOT}/Aegis/Logging${PYTHONPATH:+:${PYTHONPATH}}"

python3 -m unittest discover -s "$TEST_DIR" -p 'test_*.py' -v
python3 -m unittest discover -s "${REPO_ROOT}/Tests/Memory" -p 'test_*.py' -v
