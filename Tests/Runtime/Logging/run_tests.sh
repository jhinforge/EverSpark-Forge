#!/usr/bin/env bash
set -euo pipefail

TEST_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

bash "${TEST_DIR}/test_log.sh"
python -m unittest discover -s "$TEST_DIR" -p 'test_*.py' -v
