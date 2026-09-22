from __future__ import annotations

import argparse
import configparser
import json
import os
import re
import shlex
import tempfile
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_IMPORT_DIRECTORY = REPO_ROOT / "Configuration" / "Import"
_KEY = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_TUNNEL_ID = re.compile(r"^[A-Za-z0-9-]{16,64}$")
_HOSTNAME = re.compile(
    r"^(?=.{1,253}\.?$)(?:[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)+"
    r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.?$"
)


class ConfigurationImportError(ValueError):
    pass


def parse_env(path: Path) -> dict[str, str]:
    try:
        lines = path.read_text(encoding="utf-8-sig").splitlines()
    except FileNotFoundError as exc:
        raise ConfigurationImportError(f"Environment file not found: {path}") from exc
    values: dict[str, str] = {}
    for line_number, raw in enumerate(lines, 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        if "=" not in line:
            raise ConfigurationImportError(
                f"Invalid environment entry at {path}:{line_number}"
            )
        key, raw_value = line.split("=", 1)
        key = key.strip()
        if not _KEY.fullmatch(key):
            raise ConfigurationImportError(
                f"Invalid environment key at {path}:{line_number}: {key!r}"
            )
        if key in values:
            raise ConfigurationImportError(f"Duplicate environment key: {key}")
        value_text = raw_value.strip()
        if not value_text:
            value = ""
        else:
            try:
                parts = shlex.split(value_text, comments=False, posix=True)
            except ValueError as exc:
                raise ConfigurationImportError(
                    f"Invalid environment value for {key}: {exc}"
                ) from exc
            if len(parts) != 1:
                raise ConfigurationImportError(
                    f"Environment value for {key} must be quoted when it contains spaces"
                )
            value = parts[0]
        if "\n" in value or "\r" in value or "\x00" in value:
            raise ConfigurationImportError(f"Environment value for {key} is invalid")
        values[key] = value
    return values


def _select_environment(source_dir: Path, explicit: Path | None) -> tuple[Path, dict[str, str]]:
    if explicit is not None:
        selected = explicit.expanduser()
        if not selected.is_absolute():
            selected = source_dir / selected
        selected = selected.resolve()
        return selected, parse_env(selected)

    dot_env = source_dir / ".env"
    text_env = source_dir / "env.txt"
    available = [path for path in (dot_env, text_env) if path.is_file()]
    if not available:
        raise ConfigurationImportError(
            f"No .env or env.txt found in configuration source: {source_dir}"
        )
    if len(available) == 2:
        dot_values = parse_env(dot_env)
        text_values = parse_env(text_env)
        if dot_values != text_values:
            raise ConfigurationImportError(
                ".env and env.txt contain different settings; keep one or make them identical"
            )
        return dot_env, dot_values
    return available[0], parse_env(available[0])


def _validated_port(value: str, name: str) -> int:
    try:
        port = int(value)
    except ValueError as exc:
        raise ConfigurationImportError(f"{name} must be an integer") from exc
    if not 1 <= port <= 65535:
        raise ConfigurationImportError(f"{name} must be between 1 and 65535")
    return port


def _validate_tunnel(values: dict[str, str]) -> bool:
    tunnel_keys = {
        "CF_TUNNEL_UUID",
        "CF_HOSTNAME",
        "CF_LOCAL_PORT",
        "CF_TUNNEL_NAME",
        "CF_CREDENTIAL_SOURCE",
    }
    configured = any(values.get(key, "").strip() for key in tunnel_keys)
    backend = values.get("EVERSPARK_NETWORK_BACKEND", "").strip().lower()
    if not configured and backend != "cloudflare":
        return False
    required = [
        key
        for key in ("CF_TUNNEL_UUID", "CF_HOSTNAME", "CF_LOCAL_PORT")
        if not values.get(key, "").strip()
    ]
    if required:
        raise ConfigurationImportError(
            "Cloudflare configuration is missing: " + ", ".join(required)
        )
    tunnel_id = values["CF_TUNNEL_UUID"].strip()
    hostname = values["CF_HOSTNAME"].strip()
    if not _TUNNEL_ID.fullmatch(tunnel_id):
        raise ConfigurationImportError("CF_TUNNEL_UUID has an invalid format")
    if not _HOSTNAME.fullmatch(hostname):
        raise ConfigurationImportError("CF_HOSTNAME has an invalid format")
    tunnel_port = _validated_port(values["CF_LOCAL_PORT"], "CF_LOCAL_PORT")
    webui_port = _validated_port(
        values.get("EVERSPARK_WEBUI_PORT", "8780"), "EVERSPARK_WEBUI_PORT"
    )
    if tunnel_port != webui_port:
        raise ConfigurationImportError(
            f"CF_LOCAL_PORT must match EverSpark WebUI port {webui_port}; got {tunnel_port}"
        )
    if backend and backend not in {"local", "cloudflare"}:
        raise ConfigurationImportError(
            f"Unsupported EVERSPARK_NETWORK_BACKEND: {backend}"
        )
    if not backend:
        values["EVERSPARK_NETWORK_BACKEND"] = "cloudflare"
    return values["EVERSPARK_NETWORK_BACKEND"].lower() == "cloudflare"


def _credential_source(source_dir: Path, values: dict[str, str]) -> Path:
    configured = values.get("CF_CREDENTIAL_SOURCE", "").strip()
    if configured:
        candidate = Path(configured).expanduser()
        if not candidate.is_absolute():
            candidate = source_dir / candidate
        return candidate.resolve()
    return (source_dir / f"{values['CF_TUNNEL_UUID']}.json").resolve()


def _validate_credential(path: Path, expected_tunnel_id: str) -> None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except FileNotFoundError as exc:
        raise ConfigurationImportError(
            f"Cloudflare credential not found: {path.name}"
        ) from exc
    except json.JSONDecodeError as exc:
        raise ConfigurationImportError(
            f"Cloudflare credential is not valid JSON: {path.name}"
        ) from exc
    if not isinstance(payload, dict):
        raise ConfigurationImportError("Cloudflare credential root must be an object")
    missing = [
        key
        for key in ("AccountTag", "TunnelSecret", "TunnelID")
        if not isinstance(payload.get(key), str) or not payload[key].strip()
    ]
    if missing:
        raise ConfigurationImportError(
            "Cloudflare credential is missing required fields: " + ", ".join(missing)
        )
    if payload["TunnelID"].lower() != expected_tunnel_id.lower():
        raise ConfigurationImportError(
            "Cloudflare credential TunnelID does not match CF_TUNNEL_UUID"
        )


def _validate_rclone(path: Path) -> list[str]:
    parser = configparser.RawConfigParser(strict=False)
    try:
        with path.open("r", encoding="utf-8-sig") as handle:
            parser.read_file(handle)
    except (OSError, configparser.Error) as exc:
        raise ConfigurationImportError(f"Invalid rclone.conf: {exc}") from exc
    remotes = parser.sections()
    if not remotes:
        raise ConfigurationImportError("rclone.conf does not define any remotes")
    return remotes


def _atomic_write(path: Path, content: bytes, mode: int = 0o600) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, mode)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _render_env(values: dict[str, str]) -> bytes:
    lines = [f"{key}={shlex.quote(value)}" for key, value in values.items()]
    return ("\n".join(lines) + "\n").encode("utf-8")


def import_configuration(
    source: str | Path,
    *,
    explicit_env: str | Path | None = None,
    repo_root: Path = REPO_ROOT,
) -> dict[str, Any]:
    source_dir = Path(source).expanduser().resolve()
    if not source_dir.is_dir():
        raise ConfigurationImportError(f"Configuration source is not a directory: {source_dir}")
    explicit_path = Path(explicit_env) if explicit_env is not None else None
    selected_env, values = _select_environment(source_dir, explicit_path)
    configured_log_dir = values.get("EVERSPARK_LOG_DIR", "").strip()
    if configured_log_dir:
        log_path = Path(configured_log_dir).expanduser()
        if not log_path.is_absolute():
            values["EVERSPARK_LOG_DIR"] = str((repo_root / log_path).resolve())
    cloudflare_enabled = _validate_tunnel(values)

    credential_destination: Path | None = None
    credential_content: bytes | None = None
    if cloudflare_enabled:
        credential = _credential_source(source_dir, values)
        _validate_credential(credential, values["CF_TUNNEL_UUID"])
        credential_destination = (
            repo_root
            / "Data"
            / "Configuration"
            / "cloudflare"
            / f"{values['CF_TUNNEL_UUID']}.json"
        ).resolve()
        credential_content = credential.read_bytes()
        values["CF_CREDENTIAL_SOURCE"] = str(credential_destination)

    rclone_source = source_dir / "rclone.conf"
    rclone_destination: Path | None = None
    rclone_content: bytes | None = None
    remotes: list[str] = []
    if rclone_source.is_file():
        remotes = _validate_rclone(rclone_source)
        rclone_destination = (
            repo_root / "Data" / "Configuration" / "rclone" / "rclone.conf"
        ).resolve()
        rclone_content = rclone_source.read_bytes()
        values["RCLONE_CONFIG"] = str(rclone_destination)

    destination_env = (repo_root / ".env").resolve()
    if credential_destination is not None and credential_content is not None:
        _atomic_write(credential_destination, credential_content)
    if rclone_destination is not None and rclone_content is not None:
        _atomic_write(rclone_destination, rclone_content)
    _atomic_write(destination_env, _render_env(values))
    return {
        "environment_source": str(selected_env),
        "environment_file": str(destination_env),
        "network_backend": values.get("EVERSPARK_NETWORK_BACKEND", "local"),
        "cloudflare_credential": (
            str(credential_destination) if credential_destination else None
        ),
        "rclone_config": str(rclone_destination) if rclone_destination else None,
        "rclone_remotes": remotes,
        "storage_backend": values.get("EVERSPARK_STORAGE_BACKEND", "local"),
    }


def _render_result(result: dict[str, Any]) -> str:
    lines = [
        "EverSpark configuration imported",
        f"  Environment: {result['environment_file']}",
        f"  Network backend: {result['network_backend']}",
        f"  Cloudflare credential: {result['cloudflare_credential'] or 'not provided'}",
        f"  rclone config: {result['rclone_config'] or 'not provided'}",
        f"  Storage backend: {result['storage_backend']}",
    ]
    if result["rclone_remotes"]:
        lines.append("  rclone remotes: " + ", ".join(result["rclone_remotes"]))
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Import private EverSpark configuration")
    parser.add_argument(
        "--from",
        dest="source",
        default=str(DEFAULT_IMPORT_DIRECTORY),
        help=(
            "configuration directory "
            "(default: <repository>/Configuration/Import)"
        ),
    )
    parser.add_argument("--env", dest="environment", help="explicit .env or env.txt path")
    parser.add_argument("--json", action="store_true", help="print machine-readable output")
    args = parser.parse_args()
    try:
        result = import_configuration(args.source, explicit_env=args.environment)
    except (ConfigurationImportError, OSError) as exc:
        if args.json:
            print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
        else:
            print(f"[ERROR] {exc}")
        return 1
    if args.json:
        print(json.dumps({"ok": True, **result}, ensure_ascii=False, indent=2))
    else:
        print(_render_result(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
