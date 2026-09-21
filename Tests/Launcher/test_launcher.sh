#!/usr/bin/env bash
set -euo pipefail

TEST_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${TEST_DIR}/../.." && pwd)"
TEST_ROOT="$(mktemp -d)"
trap 'rm -rf "$TEST_ROOT"' EXIT

help_output="$(bash "${REPO_ROOT}/everspark" help)"
grep -q './everspark image' <<< "$help_output"
grep -q './everspark start' <<< "$help_output"
if grep -Eq 'comfy|ollama' <<< "$help_output"; then
  printf 'legacy backend alias leaked into CLI help\n' >&2
  exit 1
fi

for legacy_alias in \
  comfy comfyui ollama \
  image-forge imageforge concept-forge conceptforge \
  forge-orchestrator web logging; do
  if bash "${REPO_ROOT}/everspark" "$legacy_alias" >"${TEST_ROOT}/${legacy_alias}.out" 2>&1; then
    printf 'legacy alias unexpectedly succeeded: %s\n' "$legacy_alias" >&2
    exit 1
  fi
  grep -q "unknown module: ${legacy_alias}" "${TEST_ROOT}/${legacy_alias}.out"
done

logs_output="$(EVERSPARK_LOG_DIR="${TEST_ROOT}/logs" bash "${REPO_ROOT}/everspark" logs status)"
grep -q '"ok": true' <<< "$logs_output"

image_status="$(bash "${REPO_ROOT}/everspark" image status)"
grep -q '"service": "image"' <<< "$image_status"

runtime_status="$(bash "${REPO_ROOT}/everspark" status)"
grep -q '"service": "concept"' <<< "$runtime_status"
grep -q '"service": "webui"' <<< "$runtime_status"

setup_plan="$(bash "${REPO_ROOT}/everspark" setup --plan --skip-models)"
grep -q 'ComfyUI: v0.37.0' <<< "$setup_plan"
grep -q 'Ollama: 0.34.2' <<< "$setup_plan"

EVERSPARK_LOG_DIR="${TEST_ROOT}/logs" bash "${REPO_ROOT}/everspark" init >/dev/null
grep -q 'No .env file found; local defaults remain active' "${TEST_ROOT}/logs/launcher.log"

doctor_output="$(PATH="${PATH}" EVERSPARK_STORAGE_BACKEND=local EVERSPARK_NETWORK_BACKEND=local \
  bash "${REPO_ROOT}/everspark" doctor 2>&1)"
grep -q 'EverSpark base runtime is ready' <<< "$doctor_output"

install_root="${TEST_ROOT}/install"
EVERSPARK_CLI_PATH="${install_root}/everspark" bash "${REPO_ROOT}/Launcher/install.sh" >/dev/null
installed_help="$(bash "${install_root}/everspark" help)"
grep -q 'EverSpark Forge CLI' <<< "$installed_help"

orchestrator_help="$(bash "${REPO_ROOT}/everspark" orchestrator help)"
grep -q 'everspark orchestrator start' <<< "$orchestrator_help"

webui_help="$(bash "${REPO_ROOT}/everspark" webui help)"
grep -q 'everspark webui start' <<< "$webui_help"

if EVERSPARK_STORAGE_BACKEND=rclone EVERSPARK_NETWORK_BACKEND=local \
  RCLONE_CONFIG= IMAGE_FORGE_RCLONE_REMOTE= CONCEPT_FORGE_RCLONE_REMOTE= \
  bash "${REPO_ROOT}/everspark" doctor >"${TEST_ROOT}/doctor.out" 2>&1; then
  printf 'invalid optional storage configuration unexpectedly succeeded\n' >&2
  exit 1
fi
grep -q 'Enabled backend is missing required configuration' "${TEST_ROOT}/doctor.out"

printf 'launcher tests: OK\n'
