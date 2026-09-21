#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

case "${1:-help}" in
  start|stop|restart|status)
    exec python3 "${REPO_ROOT}/Runtime/Managed/runtime_manager.py" "$1" image
    ;;
  help|-h|--help)
    cat <<'EOF'
EverSpark Image Forge commands

Usage:
  everspark image start
  everspark image stop
  everspark image restart
  everspark image status
EOF
    ;;
  *)
    printf '[ERROR] unknown Image Forge command: %s\n' "$1" >&2
    exit 1
    ;;
esac
