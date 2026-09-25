#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
CLI_SOURCE="${REPO_ROOT}/everspark"

if [ -n "${EVERSPARK_CLI_PATH:-}" ]; then
  CLI_TARGET="$EVERSPARK_CLI_PATH"
elif [ "${EUID}" -eq 0 ] && [ -w /usr/local/bin ] && [[ ":${PATH}:" == *":/usr/local/bin:"* ]]; then
  CLI_TARGET=/usr/local/bin/everspark
else
  CLI_TARGET="${HOME}/.local/bin/everspark"
fi

if [ ! -f "$CLI_SOURCE" ]; then
  printf '[ERROR] EverSpark CLI source not found: %s\n' "$CLI_SOURCE" >&2
  exit 1
fi

if [ -e "$CLI_TARGET" ] || [ -L "$CLI_TARGET" ]; then
  if [ ! -L "$CLI_TARGET" ] || [ "$(readlink -f "$CLI_TARGET")" != "$CLI_SOURCE" ]; then
    printf '[ERROR] Refusing to replace an existing command: %s\n' "$CLI_TARGET" >&2
    exit 1
  fi
else
  install -d "$(dirname "$CLI_TARGET")"
  ln -s "$CLI_SOURCE" "$CLI_TARGET"
fi

printf '[OK] EverSpark CLI installed: %s -> %s\n' "$CLI_TARGET" "$CLI_SOURCE"
case ":${PATH}:" in
  *":$(dirname "$CLI_TARGET"):"*) ;;
  *)
    if [ -z "${EVERSPARK_CLI_PATH:-}" ] && [ "$(dirname "$CLI_TARGET")" = "${HOME}/.local/bin" ]; then
      path_line='export PATH="$HOME/.local/bin:$PATH"'
      for profile in "${HOME}/.profile" "${HOME}/.bashrc"; do
        if [ ! -e "$profile" ] || [ -f "$profile" ]; then
          if ! grep -Fxq "$path_line" "$profile" 2>/dev/null; then
            printf '\n# EverSpark CLI\n%s\n' "$path_line" >> "$profile"
          fi
        fi
      done
      printf '[INFO] Open a new shell to use `everspark` from any directory.\n'
    else
      printf '[INFO] Add %s to PATH to run `everspark` from any directory.\n' "$(dirname "$CLI_TARGET")"
    fi
    ;;
esac
