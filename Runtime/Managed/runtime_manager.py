from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import urlopen


REPO_ROOT = Path(__file__).resolve().parents[2]
STATE_DIR = REPO_ROOT / "Data" / "Runtime" / "Services"


class RuntimeManagerError(RuntimeError):
    pass


@dataclass(frozen=True)
class ServiceDefinition:
    name: str
    command: tuple[str, ...]
    health_url: str
    log_file: str
    timeout: int


@dataclass(frozen=True)
class ProcessState:
    service: str
    pid: int
    start_ticks: str
    command: list[str]


def _load_dotenv(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.is_file():
        return values
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if key and key.replace("_", "").isalnum():
            values[key] = value.strip().strip("\"'")
    return values


def _configured_log_dir() -> Path:
    values = {**_load_dotenv(REPO_ROOT / ".env"), **os.environ}
    selected = Path(values.get("EVERSPARK_LOG_DIR", "Data/Logs")).expanduser()
    return selected if selected.is_absolute() else (REPO_ROOT / selected).resolve()


LOG_DIR = _configured_log_dir()


def service_definitions() -> dict[str, ServiceDefinition]:
    values = {**_load_dotenv(REPO_ROOT / ".env"), **os.environ}
    ollama_url = values.get("OLLAMA_BASE_URL", "http://127.0.0.1:11434").rstrip("/")
    comfy_url = values.get("COMFYUI_BASE_URL", "http://127.0.0.1:8188").rstrip("/")
    orchestrator_url = values.get(
        "EVERSPARK_ORCHESTRATOR_URL", "http://127.0.0.1:8765"
    ).rstrip("/")
    web_host = values.get("EVERSPARK_WEBUI_HOST", "127.0.0.1")
    if web_host in {"0.0.0.0", "::"}:
        web_host = "127.0.0.1"
    web_port = values.get("EVERSPARK_WEBUI_PORT", "8780")
    return {
        "concept": ServiceDefinition(
            "concept",
            ("bash", str(REPO_ROOT / "ConceptForge" / "Scripts" / "start_runtime.sh")),
            f"{ollama_url}/api/tags",
            "ollama-service.log",
            90,
        ),
        "image": ServiceDefinition(
            "image",
            ("bash", str(REPO_ROOT / "ImageForge" / "Scripts" / "start_runtime.sh")),
            f"{comfy_url}/system_stats",
            "comfyui.log",
            300,
        ),
        "orchestrator": ServiceDefinition(
            "orchestrator",
            ("bash", str(REPO_ROOT / "Orchestrator" / "Scripts" / "start_core.sh")),
            f"{orchestrator_url}/health",
            "orchestrator-service.log",
            60,
        ),
        "webui": ServiceDefinition(
            "webui",
            ("bash", str(REPO_ROOT / "WebUI" / "Scripts" / "start_webui.sh")),
            f"http://{web_host}:{web_port}/api/health",
            "webui-service.log",
            60,
        ),
    }


def _state_path(name: str) -> Path:
    return STATE_DIR / f"{name}.json"


def _process_start_ticks(pid: int) -> str:
    try:
        content = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8")
    except (FileNotFoundError, PermissionError, ProcessLookupError):
        return ""
    # The parenthesized process name may itself contain spaces, so indexes from
    # a naive split are not reliable. Fields after the final ") " begin at state.
    separator = content.rfind(") ")
    if separator < 0:
        return ""
    fields = content[separator + 2 :].split()
    if len(fields) <= 19 or fields[0] == "Z":
        return ""
    return fields[19]


def _read_state(name: str) -> ProcessState | None:
    path = _state_path(name)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return ProcessState(
            service=str(payload["service"]),
            pid=int(payload["pid"]),
            start_ticks=str(payload["start_ticks"]),
            command=[str(item) for item in payload["command"]],
        )
    except (FileNotFoundError, KeyError, TypeError, ValueError, json.JSONDecodeError):
        return None


def _state_is_live(state: ProcessState | None) -> bool:
    return bool(
        state
        and state.pid > 1
        and state.start_ticks
        and _process_start_ticks(state.pid) == state.start_ticks
    )


def _healthy(url: str, timeout: float = 1.5) -> bool:
    try:
        with urlopen(url, timeout=timeout) as response:
            return 200 <= response.status < 300
    except (HTTPError, URLError, TimeoutError, OSError):
        return False


def _tail(path: Path, lines: int = 20) -> str:
    try:
        content = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except FileNotFoundError:
        return ""
    return "\n".join(content[-lines:])


def _ensure_managed_vae_path() -> None:
    """Upgrade the generated ComfyUI model paths without overwriting custom entries."""
    path = REPO_ROOT / "Data/Runtime/ComfyUI/source/extra_model_paths.yaml"
    if not path.is_file():
        return
    content = path.read_text(encoding="utf-8")
    lines = content.splitlines(keepends=True)
    start = next((i for i, line in enumerate(lines) if line.strip() == "everspark:" and not line.startswith((" ", "\t"))), None)
    if start is None:
        return
    end = next((i for i in range(start + 1, len(lines)) if lines[i].strip() and not lines[i].startswith((" ", "\t", "#"))), len(lines))
    block = lines[start + 1:end]
    expected = f"  base_path: {REPO_ROOT}/Data/Models/ImageForge"
    if not any(line.strip() == expected.strip() for line in block):
        return
    if any(line.strip().startswith("vae:") for line in block):
        return
    lines.insert(end, "  vae: vae\n")
    path.write_text("".join(lines), encoding="utf-8")


def start_service(definition: ServiceDefinition) -> dict[str, Any]:
    state = _read_state(definition.name)
    if _state_is_live(state):
        if _healthy(definition.health_url):
            return {"service": definition.name, "state": "running", "pid": state.pid}
        raise RuntimeManagerError(
            f"{definition.name} is running but unhealthy; inspect its log or restart it"
        )
    if state and not _state_is_live(state):
        _state_path(definition.name).unlink(missing_ok=True)
    if _healthy(definition.health_url):
        return {"service": definition.name, "state": "external", "pid": None}

    command_path = Path(definition.command[1])
    if not command_path.is_file():
        raise RuntimeManagerError(
            f"Start command is missing for {definition.name}: {command_path}"
        )
    if definition.name == "image":
        _ensure_managed_vae_path()
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_path = LOG_DIR / definition.log_file
    with log_path.open("ab", buffering=0) as log_handle:
        process = subprocess.Popen(
            definition.command,
            cwd=REPO_ROOT,
            stdin=subprocess.DEVNULL,
            stdout=log_handle,
            stderr=subprocess.STDOUT,
            start_new_session=True,
            env=os.environ.copy(),
        )
    start_ticks = ""
    for _ in range(20):
        start_ticks = _process_start_ticks(process.pid)
        if start_ticks:
            break
        time.sleep(0.05)
    if not start_ticks:
        raise RuntimeManagerError(f"Could not record process identity: {definition.name}")
    state = ProcessState(
        definition.name, process.pid, start_ticks, list(definition.command)
    )
    _state_path(definition.name).write_text(
        json.dumps(asdict(state), indent=2) + "\n", encoding="utf-8"
    )

    deadline = time.monotonic() + definition.timeout
    while time.monotonic() < deadline:
        if process.poll() is not None:
            _state_path(definition.name).unlink(missing_ok=True)
            detail = _tail(log_path)
            raise RuntimeManagerError(
                f"{definition.name} exited before becoming healthy"
                + (f":\n{detail}" if detail else "")
            )
        if _healthy(definition.health_url):
            # The service is intentionally detached. Linux reparents it when this
            # short-lived manager exits; PID/start-time state remains authoritative.
            process.returncode = 0
            return {
                "service": definition.name,
                "state": "started",
                "pid": process.pid,
                "health_url": definition.health_url,
            }
        time.sleep(1)
    stop_service(definition)
    raise RuntimeManagerError(
        f"Timed out waiting for {definition.name}: {definition.health_url}\n"
        f"{_tail(log_path)}"
    )


def stop_service(definition: ServiceDefinition) -> dict[str, Any]:
    state = _read_state(definition.name)
    if not _state_is_live(state):
        _state_path(definition.name).unlink(missing_ok=True)
        return {"service": definition.name, "state": "not-managed"}
    assert state is not None
    try:
        os.killpg(state.pid, signal.SIGTERM)
    except ProcessLookupError:
        _state_path(definition.name).unlink(missing_ok=True)
        return {"service": definition.name, "state": "stopped"}
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline and _state_is_live(state):
        time.sleep(0.25)
    if _state_is_live(state):
        os.killpg(state.pid, signal.SIGKILL)
    _state_path(definition.name).unlink(missing_ok=True)
    return {"service": definition.name, "state": "stopped"}


def service_status(definition: ServiceDefinition) -> dict[str, Any]:
    state = _read_state(definition.name)
    live = _state_is_live(state)
    healthy = _healthy(definition.health_url)
    return {
        "service": definition.name,
        "managed": live,
        "pid": state.pid if live and state else None,
        "healthy": healthy,
        "state": (
            "running"
            if live and healthy
            else "unhealthy"
            if live
            else "external"
            if healthy
            else "stopped"
        ),
        "health_url": definition.health_url,
        "log": str(LOG_DIR / definition.log_file),
    }


def _selected(target: str, definitions: dict[str, ServiceDefinition]) -> list[str]:
    if target == "all":
        return ["concept", "image", "orchestrator", "webui"]
    if target not in definitions:
        raise RuntimeManagerError(f"Unknown service: {target}")
    return [target]


def main() -> int:
    parser = argparse.ArgumentParser(description="EverSpark managed service runtime")
    parser.add_argument("command", choices=("start", "stop", "restart", "status"))
    parser.add_argument("service", nargs="?", default="all")
    args = parser.parse_args()
    definitions = service_definitions()
    try:
        names = _selected(args.service, definitions)
        if args.command == "status":
            result = [service_status(definitions[name]) for name in names]
        elif args.command == "stop":
            result = [stop_service(definitions[name]) for name in reversed(names)]
        else:
            if args.command == "restart":
                for name in reversed(names):
                    stop_service(definitions[name])
            result = []
            started: list[str] = []
            try:
                for name in names:
                    item = start_service(definitions[name])
                    result.append(item)
                    if item["state"] == "started":
                        started.append(name)
            except Exception:
                for name in reversed(started):
                    stop_service(definitions[name])
                raise
        print(json.dumps({"ok": True, "services": result}, indent=2))
        return 0
    except (RuntimeManagerError, OSError, subprocess.SubprocessError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
