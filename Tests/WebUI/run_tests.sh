#!/usr/bin/env bash
set -euo pipefail

TEST_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${TEST_DIR}/../.." && pwd)"

PYTHONPATH="${REPO_ROOT}/Aegis/Logging${PYTHONPATH:+:${PYTHONPATH}}" \
  python3 -m unittest discover -s "${TEST_DIR}" -p 'test_*.py' -v

if command -v node >/dev/null 2>&1; then
  node --check "${REPO_ROOT}/Archon/Portal/static/app.js"
fi

bash -n "${REPO_ROOT}/Archon/Portal/cli.sh"
bash -n "${REPO_ROOT}/Archon/Portal/Scripts/start_webui.sh"

printf 'WebUI tests: OK\n'
