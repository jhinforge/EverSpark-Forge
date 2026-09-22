#!/usr/bin/env bash

# Internal PyTorch/CUDA compatibility profile selection.
# Users do not select a profile. EverSpark derives it from the GPU architecture
# and the CUDA runtime shipped by the Pod/base image.

_EVERSPARK_TORCH_PROFILE_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
# shellcheck disable=SC1091
source "${_EVERSPARK_TORCH_PROFILE_ROOT}/Runtime/Hardware/gpu.sh"

core_version_at_least() {
  local actual="$1"
  local required="$2"
  [ -n "$actual" ] || return 1
  [ "$(printf '%s\n%s\n' "$required" "$actual" | sort -V | head -n 1)" = "$required" ]
}

core_torch_profile_select() {
  local sm_code="${1:-}"
  local base_cuda="${2:-}"

  # Validated compatibility matrix migrated from gpu-bootstrap:
  # - Blackwell/sm_120+ on a CUDA 12.8+ base uses the cu128 wheel family.
  # - Older architectures, unknown hardware, and older bases use the stable
  #   cu121 profile.
  if [[ "$sm_code" =~ ^[0-9]+$ ]] \
    && [ "$sm_code" -ge 120 ] \
    && core_version_at_least "$base_cuda" "12.8"; then
    printf '%s\n' "cu128"
    return 0
  fi

  printf '%s\n' "cu121"
}

core_torch_profile_detect() {
  local sm_code=""
  local base_cuda=""
  sm_code="$(core_gpu_sm_code || true)"
  base_cuda="$(core_cuda_runtime_version || true)"
  core_torch_profile_select "$sm_code" "$base_cuda"
}

core_torch_profile_index() {
  case "$1" in
    cu121) printf '%s\n' "https://download.pytorch.org/whl/cu121" ;;
    cu128) printf '%s\n' "https://download.pytorch.org/whl/cu128" ;;
    *) return 1 ;;
  esac
}

core_torch_profile_expected_cuda() {
  case "$1" in
    cu121) printf '%s\n' "12.1" ;;
    cu128) printf '%s\n' "12.8" ;;
    *) return 1 ;;
  esac
}

