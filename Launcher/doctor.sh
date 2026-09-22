#!/usr/bin/env bash
set -euo pipefail

LAUNCHER_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${LAUNCHER_DIR}/.." && pwd)"

# shellcheck disable=SC1091
source "${REPO_ROOT}/Runtime/Logging/log.sh"
# shellcheck disable=SC1091
source "${REPO_ROOT}/Shared/Shell/common.sh"
# shellcheck disable=SC1091
source "${REPO_ROOT}/Configuration/load_config.sh"

core_log_init launcher.doctor

if [ -f "${REPO_ROOT}/.env" ]; then
  core_load_config "${REPO_ROOT}/.env"
fi

errors=0

check_command() {
  local command_name="$1"
  if core_command_exists "$command_name"; then
    core_ok doctor.command.ready "Required command is available" "command=$command_name"
  else
    core_error doctor.command.missing "Required command is missing" "command=$command_name"
    errors=$((errors + 1))
  fi
}

check_value() {
  local variable_name="$1"
  if [ -n "${!variable_name:-}" ]; then
    return 0
  fi
  core_error doctor.config.missing "Enabled backend is missing required configuration" \
    "variable=$variable_name"
  errors=$((errors + 1))
}

case "$(uname -s):$(uname -m)" in
  Linux:x86_64|Linux:amd64)
    core_ok doctor.platform.ready "Supported host platform detected" \
      "os=$(uname -s)" "architecture=$(uname -m)"
    ;;
  *)
    core_error doctor.platform.unsupported "Unsupported host platform" \
      "os=$(uname -s)" "architecture=$(uname -m)"
    errors=$((errors + 1))
    ;;
esac

check_command bash
check_command python3
check_command git

storage_backend="${EVERSPARK_STORAGE_BACKEND:-local}"
case "$storage_backend" in
  local)
    core_ok doctor.storage.local "Local storage backend is active"
    ;;
  rclone)
    if ! core_command_exists rclone; then
      core_error doctor.storage.command "rclone storage is enabled but rclone is unavailable"
      errors=$((errors + 1))
    fi
    check_value RCLONE_CONFIG
    check_value IMAGE_FORGE_RCLONE_REMOTE
    check_value CONCEPT_FORGE_RCLONE_REMOTE
    if [ -n "${RCLONE_CONFIG:-}" ] && [ ! -f "$RCLONE_CONFIG" ]; then
      core_error doctor.storage.config "rclone config file does not exist" "path=$RCLONE_CONFIG"
      errors=$((errors + 1))
    fi
    if core_command_exists rclone && [ -f "${RCLONE_CONFIG:-}" ]; then
      for remote_variable in IMAGE_FORGE_RCLONE_REMOTE CONCEPT_FORGE_RCLONE_REMOTE; do
        remote_path="${!remote_variable:-}"
        if [ -z "$remote_path" ]; then
          continue
        fi
        if rclone lsf "$remote_path" --max-depth 1 --config "$RCLONE_CONFIG" >/dev/null 2>&1; then
          core_ok doctor.storage.remote "Remote model root is accessible" \
            "variable=$remote_variable" "remote=$remote_path"
        else
          core_error doctor.storage.remote "Remote model root is not accessible" \
            "variable=$remote_variable" "remote=$remote_path"
          errors=$((errors + 1))
        fi
      done
    fi
    ;;
  *)
    core_error doctor.storage.backend "Unknown storage backend" "backend=$storage_backend"
    errors=$((errors + 1))
    ;;
esac

network_backend="${EVERSPARK_NETWORK_BACKEND:-local}"
case "$network_backend" in
  local)
    core_ok doctor.network.local "Localhost networking is active"
    ;;
  cloudflare)
    if ! core_command_exists cloudflared; then
      core_error doctor.network.command "Cloudflare networking is enabled but cloudflared is unavailable"
      errors=$((errors + 1))
    fi
    check_value CF_TUNNEL_UUID
    check_value CF_HOSTNAME
    check_value CF_CREDENTIAL_SOURCE
    if [ -n "${CF_CREDENTIAL_SOURCE:-}" ] && [ ! -f "$CF_CREDENTIAL_SOURCE" ]; then
      core_error doctor.network.credential "Cloudflare credential file does not exist" \
        "path=$CF_CREDENTIAL_SOURCE"
      errors=$((errors + 1))
    fi
    ;;
  *)
    core_error doctor.network.backend "Unknown network backend" "backend=$network_backend"
    errors=$((errors + 1))
    ;;
esac

if core_command_exists nvidia-smi && nvidia-smi >/dev/null 2>&1; then
  gpu_count="$(nvidia-smi --query-gpu=index --format=csv,noheader 2>/dev/null | awk 'NF { count++ } END { print count + 0 }')"
  core_ok doctor.gpu.detected "NVIDIA GPU runtime detected" "gpu_count=$gpu_count"
else
  core_warn doctor.gpu.unavailable "NVIDIA GPU runtime was not detected; GPU-backed modules may be unavailable"
fi

if [ "$errors" -gt 0 ]; then
  core_error doctor.failed "EverSpark diagnostics found blocking problems" "error_count=$errors"
  exit 1
fi

core_ok doctor.ready "EverSpark base runtime is ready"
