#!/usr/bin/env bash
set -euo pipefail

TEST_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${TEST_DIR}/../../.." && pwd)"

export EVERSPARK_LOG_CONSOLE=0
# shellcheck disable=SC1091
source "${REPO_ROOT}/Runtime/Hardware/torch_profile.sh"

[ "$(core_torch_profile_select 89 12.8 12.8)" = "cu128" ]
[ "$(core_torch_profile_select 120 12.8 12.8)" = "cu128" ]
[ "$(core_torch_profile_select 89 12.6 12.8)" = "cu126" ]
[ "$(core_torch_profile_select 80 '' 12.8)" = "cu128" ]
[ "$(core_torch_profile_select '' 12.6 '')" = "cu126" ]
if core_torch_profile_select 120 12.6 12.8 >/dev/null; then
  printf 'Blackwell unexpectedly accepted a pre-cu128 driver\n' >&2
  exit 1
fi

core_gpu_sm_code() { printf '%s\n' 89; }
core_gpu_driver_cuda_version() { printf '%s\n' 12.8; }
core_cuda_runtime_version() { printf '%s\n' 12.8; }

# A similarly named environment variable must not become a user override.
export TORCH_PROFILE=cu126
[ "$(core_torch_profile_detect)" = "cu128" ]

[ "$(core_torch_profile_index cu126)" = "https://download.pytorch.org/whl/cu126" ]
[ "$(core_torch_profile_index cu128)" = "https://download.pytorch.org/whl/cu128" ]
[ "$(core_torch_profile_expected_cuda cu126)" = "12.6" ]
[ "$(core_torch_profile_expected_cuda cu128)" = "12.8" ]

printf 'PyTorch profile selection tests: OK\n'
