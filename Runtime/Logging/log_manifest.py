from __future__ import annotations

import json
import os
import re
import stat
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping


DEFAULT_MANIFEST = Path(__file__).with_name("log_manifest.json")
DEFAULT_LOG_DIR = Path(__file__).resolve().parents[2] / "Data" / "Logs"
_ID = re.compile(r"^[a-z0-9][a-z0-9-]*$")
_KINDS = {"structured", "raw"}
_POLICY_ENV = {
    "max_bytes": "EVERSPARK_LOG_MAX_BYTES",
    "keep_files": "EVERSPARK_LOG_KEEP_FILES",
    "max_age_days": "EVERSPARK_LOG_MAX_AGE_DAYS",
}


class ManifestError(ValueError):
    pass


def configured_manifest_path(environ: Mapping[str, str] | None = None) -> Path:
    env = os.environ if environ is None else environ
    return Path(env.get("EVERSPARK_LOG_MANIFEST", str(DEFAULT_MANIFEST))).expanduser()


def configured_log_dir(environ: Mapping[str, str] | None = None) -> Path:
    env = os.environ if environ is None else environ
    return Path(env.get("EVERSPARK_LOG_DIR", str(DEFAULT_LOG_DIR))).expanduser()


def _positive_int(value: Any, name: str) -> int:
    if isinstance(value, bool):
        raise ManifestError(f"{name} must be a positive integer")
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ManifestError(f"{name} must be a positive integer") from exc
    if parsed < 1:
        raise ManifestError(f"{name} must be a positive integer")
    return parsed


def _validate_policy(policy: Mapping[str, Any], prefix: str) -> dict[str, int]:
    required = ("max_bytes", "keep_files", "max_age_days")
    missing = [name for name in required if name not in policy]
    if missing:
        raise ManifestError(f"{prefix} is missing: {', '.join(missing)}")
    return {
        name: _positive_int(policy[name], f"{prefix}.{name}")
        for name in required
    }


def load_manifest(path: str | Path | None = None) -> dict[str, Any]:
    manifest_path = Path(path or configured_manifest_path())
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ManifestError(f"log manifest not found: {manifest_path}") from exc
    except json.JSONDecodeError as exc:
        raise ManifestError(f"invalid log manifest JSON: {manifest_path}: {exc}") from exc

    if not isinstance(payload, dict) or payload.get("version") != 1:
        raise ManifestError("log manifest version must be 1")
    defaults = payload.get("defaults")
    entries = payload.get("logs")
    if not isinstance(defaults, dict):
        raise ManifestError("log manifest defaults must be an object")
    if not isinstance(entries, list):
        raise ManifestError("log manifest logs must be an array")

    normalized_defaults = _validate_policy(defaults, "defaults")
    normalized_entries: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    seen_files: set[str] = set()
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            raise ManifestError(f"logs[{index}] must be an object")
        log_id = str(entry.get("id", ""))
        filename = str(entry.get("filename", ""))
        label = str(entry.get("label", ""))
        kind = str(entry.get("kind", ""))
        if not _ID.fullmatch(log_id):
            raise ManifestError(f"logs[{index}].id is invalid: {log_id}")
        if log_id in seen_ids:
            raise ManifestError(f"duplicate log id: {log_id}")
        parts = filename.split("/")
        if (not parts or any(not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", part)
                             or part in {".", ".."} for part in parts)
                or "\\" in filename):
            raise ManifestError(f"logs[{index}].filename must be a safe relative path")
        if filename in seen_files:
            raise ManifestError(f"duplicate log filename: {filename}")
        if not label:
            raise ManifestError(f"logs[{index}].label is required")
        if kind not in _KINDS:
            raise ManifestError(f"logs[{index}].kind must be structured or raw")

        normalized = {
            "id": log_id,
            "label": label,
            "filename": filename,
            "kind": kind,
        }
        rotation = entry.get("rotation")
        if rotation is not None:
            if not isinstance(rotation, dict):
                raise ManifestError(f"logs[{index}].rotation must be an object")
            normalized["rotation"] = _validate_policy(
                {**normalized_defaults, **rotation},
                f"logs[{index}].rotation",
            )
        normalized_entries.append(normalized)
        seen_ids.add(log_id)
        seen_files.add(filename)

    return {
        "version": 1,
        "defaults": normalized_defaults,
        "logs": normalized_entries,
    }


def resolve_policy(
    manifest: Mapping[str, Any],
    entry: Mapping[str, Any],
    environ: Mapping[str, str] | None = None,
) -> dict[str, int]:
    env = os.environ if environ is None else environ
    policy = dict(manifest["defaults"])
    policy.update(entry.get("rotation", {}))
    for name, env_name in _POLICY_ENV.items():
        if env_name in env:
            policy[name] = _positive_int(env[env_name], env_name)
    return policy


def _modified_at(path: Path) -> str | None:
    if not path.exists():
        return None
    return datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat(
        timespec="seconds"
    )


def rotated_files(path: Path) -> list[tuple[int, Path]]:
    pattern = re.compile(rf"^{re.escape(path.name)}\.(\d+)$")
    matches: list[tuple[int, Path]] = []
    if not path.parent.is_dir():
        return matches
    for candidate in path.parent.iterdir():
        match = pattern.fullmatch(candidate.name)
        if (
            match
            and not candidate.is_symlink()
            and candidate.is_file()
            and candidate.stat().st_nlink == 1
        ):
            matches.append((int(match.group(1)), candidate))
    return sorted(matches)


def is_safe_regular_file(path: Path) -> bool:
    if not os.path.lexists(path):
        return False
    metadata = path.lstat()
    return stat.S_ISREG(metadata.st_mode) and metadata.st_nlink == 1


def is_safe_log_parent(root: Path, path: Path) -> bool:
    """Do not follow a symlink in a manifest-owned module directory."""
    current = root
    for part in path.relative_to(root).parts[:-1]:
        current = current / part
        if os.path.lexists(current) and (current.is_symlink() or not current.is_dir()):
            return False
    return True


def collect_log_status(
    manifest_path: str | Path | None = None,
    log_dir: str | Path | None = None,
    environ: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    env = os.environ if environ is None else environ
    manifest = load_manifest(manifest_path or configured_manifest_path(env))
    root = Path(log_dir or configured_log_dir(env))
    logs: list[dict[str, Any]] = []
    for entry in manifest["logs"]:
        path = root / entry["filename"]
        rotations = rotated_files(path)
        path_present = os.path.lexists(path)
        safe = is_safe_log_parent(root, path) and (
            not path_present or is_safe_regular_file(path))
        exists = path_present and safe
        size = path.stat().st_size if exists else 0
        rotated_size = sum(candidate.stat().st_size for _, candidate in rotations)
        policy = resolve_policy(manifest, entry, env)
        logs.append(
            {
                **entry,
                "exists": exists,
                "safe": safe,
                "size_bytes": size,
                "modified_at": _modified_at(path) if exists else None,
                "rotation_count": len(rotations),
                "rotated_size_bytes": rotated_size,
                "total_size_bytes": size + rotated_size,
                "needs_rotation": safe and size >= policy["max_bytes"],
                "policy": policy,
            }
        )
    return {
        "version": manifest["version"],
        "log_dir_ready": root.is_dir(),
        "configured": len(logs),
        "present": sum(1 for item in logs if item["exists"]),
        "needs_rotation": sum(1 for item in logs if item["needs_rotation"]),
        "logs": logs,
    }
