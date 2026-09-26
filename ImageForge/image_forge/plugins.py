"""Discover, install and activate local image plugins without editing .env."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import uuid
from pathlib import Path
from typing import Any

from .adapters import PluginManifest
from .gateway import ImageGateway


REPO_ROOT = Path(__file__).resolve().parents[2]


class PluginManager:
    def __init__(self, manifests: dict[str, PluginManifest], gateway: ImageGateway,
                 root: Path = REPO_ROOT):
        self.manifests = manifests
        self.gateway = gateway
        self.root = root
        self.job_directory = root / "Data/Runtime/ImagePlugins/jobs"
        self.job_directory.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._active: dict[str, str] = {}

    def _manifest(self, name: str) -> PluginManifest:
        if name not in self.manifests:
            raise ValueError(f"Unknown image plugin: {name}")
        return self.manifests[name]

    def _installed(self, manifest: PluginManifest) -> bool:
        return (self.root / manifest.runtime_marker).is_file()

    def plugins(self) -> dict[str, Any]:
        result = []
        for name, manifest in self.manifests.items():
            try:
                online = self.gateway.engines[name].health()
            except (OSError, TimeoutError):
                online = False
            with self._lock:
                active = self._active.get(name, "")
            installed = self._installed(manifest)
            result.append({**manifest.public(), "installed": installed if manifest.installer else installed or online,
                           "online": online, "installable": bool(manifest.installer),
                           "job_id": active})
        return {"default": self.gateway.default(), "plugins": result}

    def set_default(self, name: str) -> dict[str, Any]:
        manifest = self._manifest(name)
        if not self._installed(manifest) and not self.gateway.engines[name].health():
            raise ValueError(f"Install {manifest.name} before setting it as default")
        self.gateway.set_default(name)
        return {"default": self.gateway.default()}

    def job(self, job_id: str) -> dict[str, Any]:
        if len(job_id) != 32 or any(c not in "0123456789abcdef" for c in job_id):
            raise ValueError("Invalid plugin job ID")
        try:
            result = json.loads((self.job_directory / f"{job_id}.json").read_text())
        except FileNotFoundError as exc:
            raise ValueError("Unknown plugin job") from exc
        with self._lock:
            if result["status"] == "running" and job_id not in self._active.values():
                result = {**result, "status": "failed", "error": "Plugin operation interrupted"}
        return result

    def _write(self, job_id: str, result: dict[str, Any]) -> None:
        path = self.job_directory / f"{job_id}.json"
        temporary = self.job_directory / f"{job_id}.tmp"
        temporary.write_text(json.dumps(result), encoding="utf-8")
        temporary.replace(path)

    def start(self, name: str, action: str) -> dict[str, Any]:
        manifest = self._manifest(name)
        if action not in {"install", "enable"}:
            raise ValueError("Unknown plugin action")
        if action == "install" and not manifest.installer:
            raise ValueError(f"{manifest.name} is installed by EverSpark setup")
        if action == "enable" and not self._installed(manifest):
            raise ValueError(f"Install {manifest.name} first")
        with self._lock:
            existing = self._active.get(name)
            if existing:
                return self.job(existing)
            job_id = uuid.uuid4().hex
            state = {"id": job_id, "plugin": name, "action": action, "status": "running"}
            self._write(job_id, state)
            self._active[name] = job_id
            threading.Thread(target=self._run, args=(manifest, job_id, state), daemon=True).start()
        return state

    def _run(self, manifest: PluginManifest, job_id: str, state: dict[str, Any]) -> None:
        log_root = Path(os.environ.get("EVERSPARK_LOG_DIR", str(self.root / "Data/Logs"))).expanduser()
        if not log_root.is_absolute():
            log_root = self.root / log_root
        log_path = log_root / "image" / f"image-plugin-{manifest.id}.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            if state["action"] == "install":
                if self.gateway.engines[manifest.id].health():
                    with log_path.open("ab") as log:
                        subprocess.run([sys.executable, str(self.root / "Runtime/Managed/runtime_manager.py"),
                                        "stop", manifest.managed_service], cwd=self.root,
                                       stdout=log, stderr=subprocess.STDOUT,
                                       check=True, timeout=90)
                    if self.gateway.engines[manifest.id].health():
                        raise RuntimeError(f"Stop the existing {manifest.name} worker before repairing it")
                installer = (self.root / manifest.installer).resolve()
                if self.root.resolve() not in installer.parents:
                    raise ValueError("Invalid plugin installer path")
                with log_path.open("ab") as log:
                    subprocess.run(["bash", str(installer)], cwd=self.root,
                                   stdout=log, stderr=subprocess.STDOUT,
                                   check=True, timeout=3600)
            if not self._installed(manifest):
                raise RuntimeError("Plugin installation did not create its runtime")
            with log_path.open("ab") as log:
                subprocess.run([sys.executable, str(self.root / "Runtime/Managed/runtime_manager.py"),
                                "start", manifest.managed_service], cwd=self.root,
                               stdout=log, stderr=subprocess.STDOUT,
                               check=True, timeout=360)
            self._write(job_id, {**state, "status": "completed"})
        except (OSError, RuntimeError, ValueError, subprocess.SubprocessError) as exc:
            try:
                detail = "\n".join(log_path.read_text(errors="replace").splitlines()[-8:])
            except OSError:
                detail = ""
            self._write(job_id, {**state, "status": "failed",
                                 "error": f"{exc}: {detail}"[-1500:]})
        finally:
            with self._lock:
                self._active.pop(manifest.id, None)
