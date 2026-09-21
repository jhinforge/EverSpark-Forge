#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

usage() {
  cat <<'EOF'
EverSpark Orchestrator commands

Usage:
  everspark orchestrator start
  everspark orchestrator console
EOF
}

case "${1:-help}" in
  start)
    exec bash "${SCRIPT_DIR}/Scripts/start_core.sh"
    ;;
  console)
    exec bash "${SCRIPT_DIR}/Scripts/start_console.sh"
    ;;
  help|-h|--help)
    usage
    ;;
  *)
    usage >&2
    printf '[ERROR] unknown Orchestrator command: %s\n' "$1" >&2
    exit 1
    ;;
esac
