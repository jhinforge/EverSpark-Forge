#!/usr/bin/env bash

# Common host platform checks.

_EVERSPARK_REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
# shellcheck disable=SC1091
source "${_EVERSPARK_REPO_ROOT}/Runtime/Logging/log.sh"

core_check_linux_x86_64() {
  if [ ! -f /etc/os-release ]; then
    core_die system.os.unsupported "Unsupported OS: /etc/os-release is missing"
    return 1
  fi

  if [ "$(uname -s)" != "Linux" ]; then
    core_die system.os.unsupported "Unsupported operating system" "os=$(uname -s)"
    return 1
  fi

  case "$(uname -m)" in
    x86_64|amd64)
      ;;
    *)
      core_die system.arch.unsupported "Unsupported architecture" "architecture=$(uname -m)"
      return 1
      ;;
  esac

  core_ok system.platform.ready "Linux x86_64 detected"
}
