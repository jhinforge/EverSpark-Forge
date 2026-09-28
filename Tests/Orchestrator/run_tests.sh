#!/usr/bin/env bash
set -euo pipefail

TEST_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${TEST_DIR}/../.." && pwd)"
export PYTHONPATH="${REPO_ROOT}/Orchestrator:${REPO_ROOT}/ForgeLayer:${REPO_ROOT}/ForgeLayer/ConceptForge:${REPO_ROOT}/ForgeLayer/ImageForge:${REPO_ROOT}/ForgeLayer/ConceptForge/Memory:${REPO_ROOT}/Infrastructure/Logging${PYTHONPATH:+:${PYTHONPATH}}"

python3 -m unittest discover -s "$TEST_DIR" -p 'test_*.py' -v
python3 -m unittest discover -s "${REPO_ROOT}/Tests/Memory" -p 'test_*.py' -v
