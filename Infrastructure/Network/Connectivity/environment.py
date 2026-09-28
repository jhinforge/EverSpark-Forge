"""Connection settings shared by node access and network connectivity."""

import os
from pathlib import Path
from typing import Mapping


REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_WEBUI_PORT = 8780


def _load_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (FileNotFoundError, PermissionError, OSError):
        return values
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if key.startswith("export "):
            key = key[7:].strip()
        if key and key.replace("_", "").isalnum():
            values[key] = value.strip().strip("\"'")
    return values


def discovery_environment(
    environ: Mapping[str, str] | None = None,
    repo_env: Path | None = None,
    system_env: Path | None = None,
) -> dict[str, str]:
    """Return settings in increasing precedence: system, repository, process."""
    values = _load_env_file(system_env or Path("/etc/environment"))
    values.update(_load_env_file(repo_env or REPO_ROOT / ".env"))
    values.update(dict(os.environ if environ is None else environ))
    return values
