#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [ "$#" -eq 0 ] || [ "${1:-}" = "help" ]; then
  set -- --help
fi
exec bash "${SCRIPT_DIR}/Scripts/run_cli.sh" "$@"
