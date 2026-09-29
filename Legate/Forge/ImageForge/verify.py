"""Probe the image runtime on this node without reaching a local Orchestrator."""

from __future__ import annotations

import json
import os
from urllib.error import URLError
from urllib.request import urlopen


def main() -> int:
    backend = os.environ.get("EVERSPARK_IMAGE_BACKEND", "comfyui").lower()
    if backend == "comfyui":
        url = os.environ.get("COMFYUI_BASE_URL", "http://127.0.0.1:8188").rstrip("/") + "/system_stats"
    elif backend == "diffusers":
        url = os.environ.get("EVERSPARK_DIFFUSERS_URL", "http://127.0.0.1:8190").rstrip("/") + "/health"
    else:
        raise ValueError("Unsupported Image Forge backend")
    try:
        with urlopen(url, timeout=10) as response:
            if response.status != 200:
                return 1
            json.load(response)
    except (OSError, URLError, ValueError):
        return 1
    print("Image Forge ready")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
