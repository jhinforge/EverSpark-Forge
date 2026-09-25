#!/usr/bin/env bash
set -euo pipefail

TEST_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${TEST_DIR}/../.." && pwd)"
TEST_ROOT="$(mktemp -d)"
trap 'rm -rf "$TEST_ROOT"' EXIT

help_output="$(bash "${REPO_ROOT}/everspark" help)"
grep -q './everspark image' <<< "$help_output"
grep -q './everspark start' <<< "$help_output"
grep -q './everspark access' <<< "$help_output"
grep -q './everspark configure' <<< "$help_output"
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

access_output="$(PUBLIC_IPADDR=203.0.113.10 VAST_TCP_PORT_22=40222 \
  bash "${REPO_ROOT}/everspark" access)"
grep -q 'ssh -p 40222 -L 8080:127.0.0.1:8780 root@203.0.113.10' <<< "$access_output"

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

# A completed setup installs the CLI; dry runs and failed setup do not.
setup_root="${TEST_ROOT}/setup-fixture"
mkdir -p "${setup_root}/Launcher" "${setup_root}/Runtime/Managed"
cp "${REPO_ROOT}/Launcher/setup.sh" "${REPO_ROOT}/Launcher/install.sh" "${setup_root}/Launcher/"
cp "${REPO_ROOT}/everspark" "${setup_root}/everspark"
printf '#!/usr/bin/env bash\nexit 0\n' > "${setup_root}/Launcher/init.sh"
cat > "${setup_root}/Runtime/Managed/install_runtime.sh" <<'SH'
#!/usr/bin/env bash
if [ "${FAIL_RUNTIME:-0}" = 1 ]; then exit 9; fi
SH
setup_cli="${TEST_ROOT}/setup-cli/everspark"
EVERSPARK_CLI_PATH="$setup_cli" bash "${setup_root}/Launcher/setup.sh" --plan --skip-models
[ ! -e "$setup_cli" ]
if FAIL_RUNTIME=1 EVERSPARK_CLI_PATH="$setup_cli" \
    bash "${setup_root}/Launcher/setup.sh" --skip-models >/dev/null 2>&1; then
  printf 'failed setup unexpectedly installed the CLI\n' >&2
  exit 1
fi
[ ! -e "$setup_cli" ]
EVERSPARK_CLI_PATH="$setup_cli" bash "${setup_root}/Launcher/setup.sh" --skip-models >/dev/null
[ "$(readlink -f "$setup_cli")" = "${setup_root}/everspark" ]
EVERSPARK_CLI_PATH="$setup_cli" bash "${setup_root}/Launcher/setup.sh" --skip-models >/dev/null
printf 'another command\n' > "${TEST_ROOT}/collision"
if EVERSPARK_CLI_PATH="${TEST_ROOT}/collision" bash "${setup_root}/Launcher/install.sh" >/dev/null 2>&1; then
  printf 'CLI installer overwrote an existing command\n' >&2
  exit 1
fi
grep -q 'another command' "${TEST_ROOT}/collision"

# A user without ~/.local/bin in PATH receives idempotent shell setup.
cli_home="${TEST_ROOT}/cli-home"
mkdir -p "$cli_home"
HOME="$cli_home" PATH=/usr/bin:/bin bash "${setup_root}/Launcher/install.sh" >/dev/null
[ -L "$cli_home/.local/bin/everspark" ]
HOME="$cli_home" PATH=/usr/bin:/bin bash "${setup_root}/Launcher/install.sh" >/dev/null
[ "$(grep -Fc 'export PATH="$HOME/.local/bin:$PATH"' "$cli_home/.bashrc")" = 1 ]

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
