#!/usr/bin/env bash
set -euo pipefail

TEST_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
bash "${TEST_DIR}/test_gpu_assignment.sh"
bash "${TEST_DIR}/test_torch_profile.sh"
