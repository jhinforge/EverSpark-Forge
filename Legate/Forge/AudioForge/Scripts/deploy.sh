#!/usr/bin/env bash
set -euo pipefail
repo="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../.." && pwd)"
if [ -f "${repo}/.env" ]; then
  set -a
  source "${repo}/.env"
  set +a
fi
bash "${repo}/Legate/Crucible/install_audio.sh"
"${repo}/Data/Runtime/audio-venv/bin/python" "${repo}/Legate/Forge/AudioForge/remote_task.py" health '{}'
