#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
CLI_SOURCE="${REPO_ROOT}/everspark"
CLI_TARGET="${EVERSPARK_CLI_PATH:-${HOME}/.local/bin/everspark}"

if [ ! -f "$CLI_SOURCE" ]; then
  printf '[ERROR] EverSpark CLI source not found: %s\n' "$CLI_SOURCE" >&2
  exit 1
fi

install -d "$(dirname "$CLI_TARGET")"
ln -sfn "$CLI_SOURCE" "$CLI_TARGET"

printf '[OK] EverSpark CLI installed: %s -> %s\n' "$CLI_TARGET" "$CLI_SOURCE"
case ":${PATH}:" in
  *":$(dirname "$CLI_TARGET"):"*) ;;
  *) printf '[INFO] Add %s to PATH to run `everspark` globally.\n' "$(dirname "$CLI_TARGET")" ;;
esac
