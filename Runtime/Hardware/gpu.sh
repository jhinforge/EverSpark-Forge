#!/usr/bin/env bash

# NVIDIA GPU and CUDA fact detection.
# This module reports hardware facts only. Forge modules decide how to use them.

_EVERSPARK_REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
# shellcheck disable=SC1091
source "${_EVERSPARK_REPO_ROOT}/Runtime/Logging/log.sh"
# shellcheck disable=SC1091
source "${_EVERSPARK_REPO_ROOT}/Shared/Shell/common.sh"

core_gpu_require_nvidia_smi() {
  if ! core_command_exists nvidia-smi; then
    core_die gpu.unavailable "nvidia-smi was not found"
    return 1
  fi

  if ! nvidia-smi >/dev/null 2>&1; then
    core_die gpu.unhealthy "nvidia-smi failed"
    return 1
  fi
}

core_gpu_name() {
  nvidia-smi --query-gpu=name --format=csv,noheader 2>/dev/null | head -n 1
}

core_gpu_driver_version() {
  nvidia-smi --query-gpu=driver_version --format=csv,noheader 2>/dev/null | head -n 1
}

core_gpu_driver_cuda_version() {
  nvidia-smi 2>/dev/null \
    | sed -n 's/.*CUDA Version: \([0-9.]*\).*/\1/p' \
    | head -n 1
}

core_gpu_compute_capability() {
  nvidia-smi --query-gpu=compute_cap --format=csv,noheader 2>/dev/null | head -n 1
}

core_gpu_sm_code() {
  local capability
  capability="$(core_gpu_compute_capability)"

  if [[ "$capability" =~ ^([0-9]+)\.([0-9]+) ]]; then
    printf '%s\n' "$((10#${BASH_REMATCH[1]} * 10 + 10#${BASH_REMATCH[2]}))"
    return 0
  fi

  return 1
}

core_cuda_runtime_version() {
  local version=""

  if [ -f /usr/local/cuda/version.txt ]; then
    version="$(grep -oE '[0-9]+\.[0-9]+' /usr/local/cuda/version.txt | head -n 1 || true)"
  fi

  if [ -z "$version" ] && core_command_exists nvcc; then
    version="$(nvcc --version 2>/dev/null \
      | grep -oE 'release [0-9]+\.[0-9]+' \
      | awk '{print $2}' \
      | head -n 1 || true)"
  fi

  if [ -z "$version" ] && [ -d /usr/local ]; then
    version="$(find /usr/local -maxdepth 1 -type d \
      -regextype posix-extended \
      -regex '.*/cuda-[0-9]+\.[0-9]+' 2>/dev/null \
      | sed -E 's#.*/cuda-([0-9]+\.[0-9]+).*#\1#' \
      | sort -V \
      | tail -n 1 || true)"
  fi

  printf '%s\n' "$version"
}

core_gpu_report() {
  core_gpu_require_nvidia_smi || return 1

  local sm_code=""
  sm_code="$(core_gpu_sm_code || true)"

  core_info gpu.name "GPU detected" "name=$(core_gpu_name)"
  core_info gpu.driver "NVIDIA driver detected" "version=$(core_gpu_driver_version)"
  core_info gpu.cuda.driver "Driver CUDA capability detected" "version=$(core_gpu_driver_cuda_version)"
  core_info gpu.compute "GPU compute capability detected" \
    "capability=$(core_gpu_compute_capability)" "sm=${sm_code:-unknown}"
  core_info gpu.cuda.runtime "Base CUDA runtime inspected" \
    "version=$(core_cuda_runtime_version || true)"
}
