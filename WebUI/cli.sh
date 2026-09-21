#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

usage() {
  cat <<'EOF'
EverSpark WebUI commands

Usage:
  everspark webui start
EOF
}

case "${1:-help}" in
  start)
    exec bash "${SCRIPT_DIR}/Scripts/start_webui.sh"
    ;;
  help|-h|--help)
    usage
    ;;
  *)
    usage >&2
    printf '[ERROR] unknown WebUI command: %s\n' "$1" >&2
    exit 1
    ;;
esac
