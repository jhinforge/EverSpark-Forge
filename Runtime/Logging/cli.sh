#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MAINTENANCE="${SCRIPT_DIR}/log_maintenance.py"

usage() {
  cat <<'EOF'
EverSpark managed log commands

Usage:
  everspark logs status
  everspark logs rotate
  everspark logs rotate --dry-run
EOF
}

case "${1:-help}" in
  status)
    shift
    exec python3 "$MAINTENANCE" status "$@"
    ;;
  rotate)
    shift
    exec python3 "$MAINTENANCE" rotate "$@"
    ;;
  help|-h|--help)
    usage
    ;;
  *)
    usage >&2
    printf 'Unknown logs command: %s\n' "$1" >&2
    exit 1
    ;;
esac
