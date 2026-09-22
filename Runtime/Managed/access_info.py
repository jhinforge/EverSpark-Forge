from __future__ import annotations

import argparse
import ipaddress
import json
import os
import re
import shlex
from pathlib import Path
from typing import Mapping


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_WEBUI_PORT = 8780
DEFAULT_LOCAL_PORT = 8080
_HOSTNAME = re.compile(
    r"^(?=.{1,253}\.?$)(?:[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)*"
    r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.?$"
)
_USERNAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_.-]{0,31}$")


class AccessInfoError(ValueError):
    pass


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


def _port(values: Mapping[str, str], key: str, default: int | None = None) -> int | None:
    raw = values.get(key)
    if raw is None or not raw.strip():
        return default
    try:
        port = int(raw)
    except ValueError as exc:
        raise AccessInfoError(f"{key} must be an integer between 1 and 65535") from exc
    if not 1 <= port <= 65535:
        raise AccessInfoError(f"{key} must be between 1 and 65535")
    return port


def _host(raw: str | None) -> str | None:
    if raw is None or not raw.strip():
        return None
    host = raw.strip()
    try:
        ipaddress.ip_address(host)
    except ValueError:
        if not _HOSTNAME.fullmatch(host):
            raise AccessInfoError("SSH host is not a valid IP address or hostname")
    return host


def build_access_info(values: Mapping[str, str]) -> dict[str, object]:
    webui_port = _port(values, "EVERSPARK_WEBUI_PORT", DEFAULT_WEBUI_PORT)
    local_port = _port(values, "EVERSPARK_LOCAL_WEBUI_PORT", DEFAULT_LOCAL_PORT)
    ssh_port = _port(values, "EVERSPARK_SSH_PORT")
    if ssh_port is None:
        ssh_port = _port(values, "VAST_TCP_PORT_22")

    host = _host(values.get("EVERSPARK_SSH_HOST") or values.get("PUBLIC_IPADDR"))
    user = values.get("EVERSPARK_SSH_USER", "root").strip()
    if not _USERNAME.fullmatch(user):
        raise AccessInfoError("EVERSPARK_SSH_USER is not a valid SSH username")

    command: str | None = None
    if host is not None and ssh_port is not None:
        destination_host = f"[{host}]" if ":" in host else host
        arguments = [
            "ssh",
            "-p",
            str(ssh_port),
            "-L",
            f"{local_port}:127.0.0.1:{webui_port}",
            f"{user}@{destination_host}",
        ]
        command = " ".join(shlex.quote(item) for item in arguments)

    return {
        "ready": command is not None,
        "provider": "vast" if values.get("VAST_TCP_PORT_22") else "custom",
        "pod_url": f"http://127.0.0.1:{webui_port}",
        "local_url": f"http://127.0.0.1:{local_port}",
        "ssh_host": host,
        "ssh_port": ssh_port,
        "ssh_user": user,
        "command": command,
    }


def render_access_info(info: Mapping[str, object]) -> str:
    lines = [
        "",
        "EverSpark Forge WebUI access",
        f"  Inside this machine: {info['pod_url']}",
        "",
    ]
    if info["ready"]:
        lines.extend(
            [
                "Run this on your local computer:",
                f"  {info['command']}",
                "",
                "Then open:",
                f"  {info['local_url']}",
            ]
        )
    else:
        missing = []
        if info["ssh_host"] is None:
            missing.append("SSH host")
        if info["ssh_port"] is None:
            missing.append("SSH port")
        lines.extend(
            [
                f"Automatic SSH command unavailable (missing {' and '.join(missing)}).",
                "Set EVERSPARK_SSH_HOST and EVERSPARK_SSH_PORT, then run:",
                "  ./everspark access",
            ]
        )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Show how to access EverSpark WebUI")
    parser.add_argument("--json", action="store_true", help="print machine-readable output")
    args = parser.parse_args()
    try:
        info = build_access_info(discovery_environment())
    except AccessInfoError as exc:
        if args.json:
            print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
        else:
            print(f"[ERROR] {exc}")
        return 1
    if args.json:
        print(json.dumps({"ok": True, **info}, indent=2))
    else:
        print(render_access_info(info))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
