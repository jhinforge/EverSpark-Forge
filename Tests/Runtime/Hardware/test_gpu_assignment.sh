#!/usr/bin/env bash
set -euo pipefail

TEST_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${TEST_DIR}/../../.." && pwd)"
TEST_ROOT="$(mktemp -d)"
trap 'rm -rf "$TEST_ROOT"' EXIT

mkdir -p "${TEST_ROOT}/bin"
FAKE_NVIDIA_SMI="${TEST_ROOT}/bin/nvidia-smi"
touch "$FAKE_NVIDIA_SMI"
chmod +x "$FAKE_NVIDIA_SMI"

write_fake_gpu_count() {
  local count="$1"
  {
    printf '%s\n' '#!/usr/bin/env bash'
    printf '%s\n' 'if [[ "$*" == *"--query-gpu=index"* ]]; then'
    local index
    for ((index = 0; index < count; index++)); do
      printf "  printf '%%s\\n' '%s'\n" "$index"
    done
    printf '%s\n' 'elif [[ "$*" == *"--query-gpu=name"* ]]; then'
    printf '%s\n' '  printf "%s\n" "Fake GPU"'
    printf '%s\n' 'fi'
  } > "$FAKE_NVIDIA_SMI"
}

export PATH="${TEST_ROOT}/bin:${PATH}"
export EVERSPARK_LOG_CONSOLE=0
# shellcheck disable=SC1091
source "${REPO_ROOT}/Runtime/Hardware/gpu_assignment.sh"

write_fake_gpu_count 1
export CUDA_VISIBLE_DEVICES=7
core_gpu_assign_forge image
[ "$CUDA_VISIBLE_DEVICES" = "7" ]

write_fake_gpu_count 2
core_gpu_assign_forge image
[ "$CUDA_VISIBLE_DEVICES" = "0" ]
[ "$EVERSPARK_ASSIGNED_GPU" = "0" ]

core_gpu_assign_forge concept
[ "$CUDA_VISIBLE_DEVICES" = "1" ]
[ "$EVERSPARK_ASSIGNED_GPU" = "1" ]

export IMAGE_FORGE_GPU_INDEX=9
if core_gpu_assign_forge image; then
  printf 'invalid GPU index unexpectedly succeeded\n' >&2
  exit 1
fi

printf 'GPU assignment tests: OK\n'
