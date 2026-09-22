#!/usr/bin/env bash
set -euo pipefail

TEST_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${TEST_DIR}/../../.." && pwd)"

export EVERSPARK_LOG_CONSOLE=0
# shellcheck disable=SC1091
source "${REPO_ROOT}/Runtime/Hardware/torch_profile.sh"

[ "$(core_torch_profile_select 120 12.8)" = "cu128" ]
[ "$(core_torch_profile_select 120 12.10)" = "cu128" ]
[ "$(core_torch_profile_select 120 12.1)" = "cu121" ]
[ "$(core_torch_profile_select 80 12.8)" = "cu121" ]
[ "$(core_torch_profile_select '' 12.8)" = "cu121" ]
[ "$(core_torch_profile_select 120 '')" = "cu121" ]

core_gpu_sm_code() { printf '%s\n' 120; }
core_cuda_runtime_version() { printf '%s\n' 12.8; }

# A similarly named environment variable must not become a user override.
export TORCH_PROFILE=cu121
[ "$(core_torch_profile_detect)" = "cu128" ]

[ "$(core_torch_profile_index cu121)" = "https://download.pytorch.org/whl/cu121" ]
[ "$(core_torch_profile_index cu128)" = "https://download.pytorch.org/whl/cu128" ]

printf 'PyTorch profile selection tests: OK\n'

