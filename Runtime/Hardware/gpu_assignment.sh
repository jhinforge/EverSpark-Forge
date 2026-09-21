#!/usr/bin/env bash

# Dynamic GPU assignment for EverSpark Forge modules.
# Single-GPU systems keep the user's existing CUDA visibility unchanged.
# Multi-GPU systems default Image Forge to GPU 0 and Concept Forge to GPU 1.

_EVERSPARK_REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
# shellcheck disable=SC1091
source "${_EVERSPARK_REPO_ROOT}/Runtime/Logging/log.sh"
# shellcheck disable=SC1091
source "${_EVERSPARK_REPO_ROOT}/Shared/Shell/common.sh"

core_gpu_count() {
  if ! core_command_exists nvidia-smi; then
    printf '%s\n' "0"
    return 0
  fi

  nvidia-smi --query-gpu=index --format=csv,noheader 2>/dev/null \
    | awk 'NF { count++ } END { print count + 0 }'
}

core_gpu_name_by_index() {
  local gpu_index="$1"

  nvidia-smi --id="$gpu_index" --query-gpu=name --format=csv,noheader 2>/dev/null \
    | head -n 1
}

core_gpu_assign_forge() {
  local forge_name="${1,,}"
  local gpu_count gpu_index gpu_name

  gpu_count="$(core_gpu_count)"

  if [ "$gpu_count" -lt 2 ]; then
    core_info gpu.assignment.skipped "Dedicated GPU assignment was skipped" \
      "module=$forge_name" "gpu_count=$gpu_count"
    return 0
  fi

  case "$forge_name" in
    image|image-forge|imageforge|comfy|comfyui)
      gpu_index="${IMAGE_FORGE_GPU_INDEX:-0}"
      forge_name="image-forge"
      ;;
    concept|concept-forge|conceptforge|ollama)
      gpu_index="${CONCEPT_FORGE_GPU_INDEX:-1}"
      forge_name="concept-forge"
      ;;
    *)
      core_die gpu.assignment.unknown "Unknown Forge module for GPU assignment" \
        "module=$forge_name"
      return 1
      ;;
  esac

  if ! [[ "$gpu_index" =~ ^[0-9]+$ ]] || [ "$gpu_index" -ge "$gpu_count" ]; then
    core_die gpu.assignment.invalid "Configured GPU index is unavailable" \
      "module=$forge_name" "gpu_index=$gpu_index" "gpu_count=$gpu_count"
    return 1
  fi

  gpu_name="$(core_gpu_name_by_index "$gpu_index" || true)"
  export CUDA_VISIBLE_DEVICES="$gpu_index"
  export EVERSPARK_ASSIGNED_GPU="$gpu_index"

  core_ok gpu.assignment.ready "GPU assigned" \
    "module=$forge_name" "gpu_index=$gpu_index" "gpu_name=${gpu_name:-unknown}"
}
