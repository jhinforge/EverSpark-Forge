#!/usr/bin/env bash
set -euo pipefail

repo="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../.." && pwd)"
cd "$repo"
export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y curl ca-certificates python3 python3-venv python3-dev

if ! command -v ollama >/dev/null 2>&1; then
  curl -fsSL https://ollama.com/install.sh | OLLAMA_VERSION=0.34.2 sh
fi

python3 Legate/Warden/runtime_manager.py start concept
tools="$repo/Data/Runtime/ModelTools"
if [ ! -x "$tools/bin/python" ]; then python3 -m venv "$tools"; fi
"$tools/bin/python" -m pip install --disable-pip-version-check 'huggingface_hub>=1,<2'
"$tools/bin/python" Legate/Crucible/Models/model_manager.py download --models concept
"$tools/bin/python" Legate/Crucible/Models/model_manager.py import-concept
"$tools/bin/python" Legate/Crucible/Models/model_manager.py status --models concept
