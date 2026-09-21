#!/usr/bin/env bash
set -euo pipefail

TEST_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${TEST_DIR}/../../.." && pwd)"
LOGGING_DIR="${REPO_ROOT}/Runtime/Logging"
TEST_ROOT="$(mktemp -d)"
trap 'rm -rf "$TEST_ROOT"' EXIT

# shellcheck disable=SC1091
source "${LOGGING_DIR}/log.sh"

fail() {
  printf 'FAIL: %s\n' "$*" >&2
  exit 1
}

export EVERSPARK_LOG_LEVEL=INFO
export EVERSPARK_LOG_FORMAT=json
export EVERSPARK_LOG_CONSOLE=0
export EVERSPARK_RUN_ID=test-run

core_log_init test.shell "${TEST_ROOT}/shell.log"
core_debug debug.hidden "hidden"
core_info startup.begin "Started" "mode=test" "token=visible-secret"
core_info "Compatibility message"
core_run_step success true
if core_run_step expected_failure false; then
  fail "failed command unexpectedly returned success"
fi
core_run_optional_step optional_failure false

[ "$(wc -l < "${TEST_ROOT}/shell.log")" -eq 8 ] || fail "unexpected record count"
grep -q '"component":"test.shell"' "${TEST_ROOT}/shell.log" || fail "component missing"
grep -q '"event":"startup.begin"' "${TEST_ROOT}/shell.log" || fail "event missing"
grep -q '"event":"message"' "${TEST_ROOT}/shell.log" || fail "compatibility event missing"
grep -q '"token":"\[REDACTED\]"' "${TEST_ROOT}/shell.log" || fail "secret was not redacted"
grep -q '"optional":"true"' "${TEST_ROOT}/shell.log" || fail "optional step metadata missing"
if grep -q 'visible-secret\|debug.hidden' "${TEST_ROOT}/shell.log"; then
  fail "secret or filtered debug record leaked"
fi
python - "${TEST_ROOT}/shell.log" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as handle:
    for line in handle:
        json.loads(line)
PY

EVERSPARK_LOG_FORMAT=invalid
CORE_LOG_INITIALIZED=0
if core_log_init test.shell "${TEST_ROOT}/invalid.log" 2>/dev/null; then
  fail "invalid format was accepted"
fi

printf 'shell logging tests: OK\n'
