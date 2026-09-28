#!/usr/bin/env bash
set -euo pipefail

repo="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
test -z "$(git -C "$repo" status --porcelain)" || { echo 'Source has local changes'; exit 1; }
test "$(git -C "$repo" branch --show-current)" = "refactor/distributed-architecture" || {
  echo 'Unexpected source branch'; exit 1;
}
git -C "$repo" pull --ff-only origin refactor/distributed-architecture
git -C "$repo" rev-parse --short HEAD
