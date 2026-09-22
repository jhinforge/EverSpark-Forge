#!/usr/bin/env bash

# Internal PyTorch/CUDA compatibility profile selection.
# Users do not select a profile. EverSpark derives it from the GPU architecture
# and the CUDA capability exposed by the NVIDIA driver. The Pod/base-image
# runtime is used only when the driver capability cannot be queried.

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
  local driver_cuda="${2:-}"
  local base_cuda="${3:-}"
  local available_cuda="$driver_cuda"

  [ -n "$available_cuda" ] || available_cuda="$base_cuda"

  # PyTorch wheels carry their CUDA runtime, so driver capability is the
  # primary boundary. cu128 is preferred whenever the host can load it;
  # cu126 remains the modern compatibility floor for older drivers.
  if core_version_at_least "$available_cuda" "12.8"; then
    printf '%s\n' "cu128"
    return 0
  fi

  # Blackwell requires the cu128 family and must not silently fall back to a
  # wheel family that cannot support the architecture.
  if [[ "$sm_code" =~ ^[0-9]+$ ]] && [ "$sm_code" -ge 120 ]; then
    return 1
  fi

  printf '%s\n' "cu126"
}

core_torch_profile_detect() {
  local sm_code=""
  local driver_cuda=""
  local base_cuda=""
  sm_code="$(core_gpu_sm_code || true)"
  driver_cuda="$(core_gpu_driver_cuda_version || true)"
  base_cuda="$(core_cuda_runtime_version || true)"
  core_torch_profile_select "$sm_code" "$driver_cuda" "$base_cuda"
}

core_torch_profile_index() {
  case "$1" in
    cu126) printf '%s\n' "https://download.pytorch.org/whl/cu126" ;;
    cu128) printf '%s\n' "https://download.pytorch.org/whl/cu128" ;;
    *) return 1 ;;
  esac
}

core_torch_profile_expected_cuda() {
  case "$1" in
    cu126) printf '%s\n' "12.6" ;;
    cu128) printf '%s\n' "12.8" ;;
    *) return 1 ;;
  esac
}
