"""Image engines register with Image Forge through local plugin manifests."""

from __future__ import annotations

import importlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..workflow.manager import WorkflowManager

REPO_ROOT = Path(__file__).resolve().parents[3]
PLUGIN_DIRECTORY = REPO_ROOT / "ImageForge/Plugins"


@dataclass(frozen=True)
class PluginManifest:
    id: str
    name: str
    module: str
    class_name: str
    managed_service: str
    runtime_marker: str
    installer: str = ""
    uses_workflow: bool = False

    def public(self) -> dict[str, str]:
        return {"id": self.id, "name": self.name, "managed_service": self.managed_service}


def discover_plugins(directory: Path = PLUGIN_DIRECTORY) -> dict[str, PluginManifest]:
    """Discover plugin metadata in the local checkout."""
    plugins: dict[str, PluginManifest] = {}
    for path in sorted(directory.glob("*.json")):
        document = json.loads(path.read_text(encoding="utf-8"))
        plugin_id = str(document["id"])
        if path.stem != plugin_id or not plugin_id.replace("_", "").isalnum():
            raise ValueError(f"Invalid image plugin manifest: {path.name}")
        if plugin_id in plugins:
            raise ValueError(f"Duplicate image plugin: {plugin_id}")
        module = str(document["module"])
        if not module.startswith("image_forge.adapters."):
            raise ValueError(f"Image plugin must reside in image_forge.adapters: {plugin_id}")
        for key in ("runtime_marker", "installer"):
            value = str(document.get(key, ""))
            if value and (Path(value).is_absolute() or ".." in Path(value).parts):
                raise ValueError(f"Unsafe image plugin {key}: {plugin_id}")
        plugins[plugin_id] = PluginManifest(
            plugin_id, str(document["name"]), module, str(document["class"]),
            str(document["managed_service"]), str(document["runtime_marker"]),
            str(document.get("installer", "")),
            document.get("uses_workflow") is True,
        )
    if "comfyui" not in plugins:
        raise ValueError("The built-in ComfyUI image plugin is missing")
    return plugins


def create_engines(config: dict[str, Any], workflow_config: dict[str, Any],
                   manifests: dict[str, PluginManifest] | None = None) -> dict[str, Any]:
    engines: dict[str, Any] = {}
    for name, manifest in (manifests if manifests is not None else discover_plugins()).items():
        module = importlib.import_module(manifest.module)
        engine_type = getattr(module, manifest.class_name)
        engine_config = config.get(name, {})
        engines[name] = (engine_type(engine_config, WorkflowManager(workflow_config))
                         if manifest.uses_workflow else engine_type(engine_config))
        if engines[name].name != name:
            raise ValueError(f"Image plugin ID mismatch: {name}")
    return engines


def create_engine(name: str, config: dict[str, Any], workflow_config: dict[str, Any]):
    """Compatibility entry point for callers that instantiate one engine."""
    manifests = discover_plugins()
    if name not in manifests:
        raise ValueError(f"Unsupported Image Forge adapter: {name}")
    return create_engines({name: config}, workflow_config, {name: manifests[name]})[name]


__all__ = ["PluginManifest", "discover_plugins", "create_engines", "create_engine"]
