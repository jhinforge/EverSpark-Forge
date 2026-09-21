#!/usr/bin/env bash
set -euo pipefail

TEST_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${TEST_DIR}/../../.." && pwd)"

export EVERSPARK_LOG_CONSOLE=0
# shellcheck disable=SC1091
source "${REPO_ROOT}/Runtime/System/platform.sh"

core_check_linux_x86_64
printf 'platform tests: OK\n'
