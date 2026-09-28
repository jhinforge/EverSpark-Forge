#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MAINTENANCE="${SCRIPT_DIR}/log_maintenance.py"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
if [ -f "${REPO_ROOT}/.env" ]; then
  set -a
  # shellcheck disable=SC1091
  source "${REPO_ROOT}/.env"
  set +a
fi
if [ -n "${EVERSPARK_LOG_DIR:-}" ] && [[ "$EVERSPARK_LOG_DIR" != /* ]]; then
  export EVERSPARK_LOG_DIR="${REPO_ROOT}/${EVERSPARK_LOG_DIR#./}"
fi

usage() {
  cat <<'EOF'
EverSpark managed log commands

Usage:
  everspark logs status
  everspark logs init
  everspark logs rotate
  everspark logs rotate --dry-run
EOF
}

case "${1:-help}" in
  status|init)
    command="$1"
    shift
    exec python3 "$MAINTENANCE" "$command" "$@"
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
