"""Own one control backend for a desktop window; stdin EOF also stops it."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
import threading

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))


def run(ready_file: Path, nonce: str) -> int:
    # The launcher assigns the process to its Windows Job before releasing it.
    if sys.stdin.readline().strip() != "start":
        return 1
    from Archon.Gate.CLI.archon import start

    stop = threading.Event()
    def watch_parent():
        # No network shutdown API, shared PID file, or process-name termination.
        sys.stdin.readline()
        stop.set()

    threading.Thread(target=watch_parent, name="desktop-owner", daemon=True).start()
    def ready(url):
        ready_file.parent.mkdir(parents=True, exist_ok=True)
        temporary = ready_file.with_suffix(".tmp")
        temporary.write_text(json.dumps({"pid": os.getpid(), "nonce": nonce,
                                         "url": url}), encoding="utf-8")
        temporary.replace(ready_file)

    try:
        return start(stop_event=stop, ready_callback=ready)
    finally:
        ready_file.unlink(missing_ok=True)
        ready_file.with_suffix(".tmp").unlink(missing_ok=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--ready-file", type=Path, required=True)
    parser.add_argument("--nonce", required=True)
    args = parser.parse_args()
    raise SystemExit(run(args.ready_file, args.nonce))
