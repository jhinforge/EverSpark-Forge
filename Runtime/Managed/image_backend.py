"""Resolve the managed image engine from environment or Orchestrator config."""

from __future__ import annotations

import json
import os
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def _config(values: dict[str, str]) -> dict:
    configured = values.get("EVERSPARK_ORCHESTRATOR_CONFIG", "").strip()
    path = Path(configured).expanduser() if configured else (
        ROOT / "Orchestrator/orchestrator/config/default_config.json")
    if not path.is_absolute():
        path = ROOT / path
    return json.loads(path.read_text(encoding="utf-8"))


def selected_backend(values: dict[str, str] | None = None) -> str:
    values = values if values is not None else os.environ
    explicit = values.get("EVERSPARK_IMAGE_BACKEND", "").strip().lower()
    if explicit:
        backend = explicit
    else:
        backend = str(_config(values)["image_forge"].get("adapter", "comfyui")).lower()
    if backend not in {"comfyui", "diffusers"}:
        raise ValueError(f"Unsupported Image Forge engine: {backend}")
    return backend


def diffusers_url(values: dict[str, str] | None = None) -> str:
    values = values if values is not None else os.environ
    return (values.get("EVERSPARK_DIFFUSERS_URL", "").strip() or
            _config(values)["image_forge"].get("adapters", {}).get("diffusers", {}).get(
                "base_url", "http://127.0.0.1:8190"))


if __name__ == "__main__":
    import sys
    print(diffusers_url() if "--url" in sys.argv else selected_backend())
