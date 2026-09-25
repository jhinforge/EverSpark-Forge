"""Discover text model adapters using local, versioned manifests."""

from __future__ import annotations

import importlib
import json
from pathlib import Path
from typing import Any

from ..port import ConceptAdapter

PLUGIN_DIRECTORY = Path(__file__).resolve().parents[2] / "Plugins"


def create_adapters(config: dict[str, Any], directory: Path = PLUGIN_DIRECTORY) -> dict[str, ConceptAdapter]:
    manifests: dict[str, dict[str, Any]] = {}
    for path in sorted(directory.glob("*.json")):
        manifest = json.loads(path.read_text(encoding="utf-8"))
        name = manifest["id"]
        module_name = manifest["module"]
        if (not isinstance(name, str) or path.stem != name
                or not name.replace("_", "").isalnum()
                or not isinstance(module_name, str)
                or not module_name.startswith("concept_forge.adapters.")):
            raise ValueError(f"Invalid Concept Forge adapter manifest: {path.name}")
        if name in manifests:
            raise ValueError(f"Duplicate Concept Forge adapter: {name}")
        manifests[name] = manifest
    adapters: dict[str, ConceptAdapter] = {}
    for instance_id, settings in config.items():
        if not isinstance(settings, dict):
            raise ValueError(f"Invalid Concept Forge provider config: {instance_id}")
        kind = settings.get("provider_type", instance_id)
        manifest = manifests.get(kind)
        if manifest is None:
            raise ValueError(f"Unsupported Concept Forge adapter: {kind}")
        module_name = manifest["module"]
        adapter_type = getattr(importlib.import_module(module_name), manifest["class"])
        adapter = adapter_type(settings)
        if adapter.name != kind:
            raise ValueError(f"Concept Forge adapter ID mismatch: {kind}")
        adapters[instance_id] = adapter
    return adapters
