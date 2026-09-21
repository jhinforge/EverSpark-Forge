from __future__ import annotations

import copy
import json
import os
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_CONFIG_PATH = Path(__file__).with_name("default_config.json")


class ConfigError(RuntimeError):
    pass


def _load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ConfigError(f"Config file not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ConfigError(f"Invalid JSON config: {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ConfigError(f"Config root must be a JSON object: {path}")
    return value


def _environment_override(
    config: dict[str, Any], variable: str, path: tuple[str, ...], cast=str
) -> None:
    raw = os.environ.get(variable)
    if raw is None or raw == "":
        return
    target: dict[str, Any] = config
    for key in path[:-1]:
        target = target[key]
    try:
        target[path[-1]] = cast(raw)
    except (TypeError, ValueError) as exc:
        raise ConfigError(f"Invalid {variable}: {raw}") from exc


def _resolve_repo_path(value: str, label: str) -> str:
    if not value.strip():
        raise ConfigError(f"{label} cannot be empty")
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = REPO_ROOT / path
    return str(path.resolve())


def load_config(path: str | Path | None = None) -> dict[str, Any]:
    selected = Path(
        path
        or os.environ.get("EVERSPARK_ORCHESTRATOR_CONFIG", "")
        or DEFAULT_CONFIG_PATH
    ).expanduser()
    if not selected.is_absolute():
        selected = REPO_ROOT / selected
    selected = selected.resolve()
    config = copy.deepcopy(_load_json(selected))

    for section in (
        "orchestrator",
        "concept_forge",
        "image_forge",
        "memory",
        "workflow",
    ):
        if not isinstance(config.get(section), dict):
            raise ConfigError(f"Missing config section: {section}")

    providers = config["concept_forge"].get("providers")
    adapters = config["image_forge"].get("adapters")
    if not isinstance(providers, dict):
        raise ConfigError("concept_forge.providers must be an object")
    if not isinstance(adapters, dict):
        raise ConfigError("image_forge.adapters must be an object")
    if not isinstance(providers.get("ollama"), dict):
        raise ConfigError("Missing Concept Forge provider config: ollama")
    if not isinstance(adapters.get("comfyui"), dict):
        raise ConfigError("Missing Image Forge adapter config: comfyui")

    _environment_override(
        config, "EVERSPARK_ORCHESTRATOR_HOST", ("orchestrator", "host")
    )
    _environment_override(
        config, "EVERSPARK_ORCHESTRATOR_PORT", ("orchestrator", "port"), int
    )
    _environment_override(
        config,
        "OLLAMA_BASE_URL",
        ("concept_forge", "providers", "ollama", "base_url"),
    )
    _environment_override(
        config,
        "OLLAMA_MODEL",
        ("concept_forge", "providers", "ollama", "model"),
    )
    _environment_override(
        config,
        "COMFYUI_BASE_URL",
        ("image_forge", "adapters", "comfyui", "base_url"),
    )
    _environment_override(
        config, "EVERSPARK_MEMORY_DATABASE", ("memory", "database")
    )
    _environment_override(
        config, "EVERSPARK_WORKFLOW_TEMPLATE", ("workflow", "template")
    )

    config["memory"]["database"] = _resolve_repo_path(
        str(config["memory"].get("database", "")), "memory.database"
    )

    workflow_path = Path(str(config["workflow"].get("template", ""))).expanduser()
    if not workflow_path.is_absolute():
        workflow_path = REPO_ROOT / workflow_path
    config["workflow"]["template"] = str(workflow_path.resolve())
    config["_config_path"] = str(selected)
    return config
