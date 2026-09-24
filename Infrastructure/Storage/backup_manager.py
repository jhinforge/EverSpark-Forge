from __future__ import annotations

import copy
import sqlite3
import subprocess
import tempfile
import threading
import time
import uuid
from pathlib import Path
from typing import Any

from r2_manager import RcloneClient, StorageError, StorageSettings


REPO_ROOT = Path(__file__).resolve().parents[2]
MODEL_DIRS = {
    "checkpoint": "checkpoints",
    "diffusion_model": "diffusion_models",
    "lora": "loras",
    "vae": "vae",
}


class BackupManager:
    def __init__(self, config: dict[str, Any], *, run=subprocess.run):
        self.settings = StorageSettings.from_config(config)
        self.client = RcloneClient(self.settings, run=run)
        self.remote = str(config.get("storage", {}).get("rclone", {}).get("backup_remote") or "").strip().rstrip("/")
        self.memory_path = Path(config["memory"]["database"]).resolve()
        self.subject_root = (self.memory_path.parent.parent if self.memory_path.parent.name == "Memory" else self.memory_path.parent) / "Subjects"
        self._lock = threading.Lock()
        self._jobs: dict[str, dict[str, Any]] = {}
        self._active = ""

    def _validate(self) -> None:
        self.client.validate()
        if not self.remote or ":" not in self.remote or ".." in self.remote.split(":", 1)[1].split("/"):
            raise StorageError("EVERSPARK_BACKUP_REMOTE must name a separate rclone remote directory")

    def _files(self) -> dict[str, Path]:
        result: dict[str, Path] = {}
        image_root = self.settings.image_root
        for kind, directory in MODEL_DIRS.items():
            root = image_root / directory
            if root.is_dir():
                paths = root.rglob("*") if kind == "vae" else root.iterdir()
                for path in sorted(paths):
                    if (path.is_file() and not path.is_symlink()
                            and not any(parent.is_symlink() for parent in path.parents if parent != root.parent)
                            and path.suffix.lower() in ({".safetensors", ".ckpt", ".pt"} if kind == "vae" else {".safetensors", ".ckpt"})):
                        result[f"models/image/{directory}/{path.relative_to(root).as_posix()}"] = path
        concept_root = REPO_ROOT / "Data/Models/ConceptForge"
        if concept_root.is_dir():
            for path in sorted(concept_root.glob("*.gguf")):
                if path.is_file() and not path.is_symlink():
                    result[f"models/concept/{path.name}"] = path
        if self.subject_root.is_dir():
            for path in sorted(self.subject_root.glob("*/*.json")):
                if (path.is_file() and not path.is_symlink()
                        and not path.parent.is_symlink()
                        and not path.parent.name.startswith(".")):
                    result[f"subjects/{path.relative_to(self.subject_root).as_posix()}"] = path
        output_root = REPO_ROOT / "Data/Outputs"
        if output_root.is_dir():
            for path in sorted(output_root.rglob("*")):
                if path.is_file() and not path.is_symlink() and not any(parent.is_symlink() for parent in path.parents if parent != output_root.parent):
                    result[f"outputs/{path.relative_to(output_root).as_posix()}"] = path
        return result

    def _remote_for(self, name: str) -> str:
        if name.startswith("models/image/"):
            return f"{self.settings.image_remote}/{name.removeprefix('models/image/')}"
        return f"{self.remote}/{name}"

    def resources(self) -> dict[str, Any]:
        if not self.settings.enabled:
            return {"enabled": False, "files": [], "memory": self.memory_path.is_file()}
        self._validate()
        files = []
        for name, path in self._files().items():
            size = path.stat().st_size
            try:
                remote_size = self.client.file_size(self._remote_for(name))
            except StorageError:
                remote_size = -1
            files.append({"name": name, "bytes": size, "backed_up": remote_size == size})
        return {"enabled": True, "files": files, "memory": self.memory_path.is_file()}

    def start(self, names: list[str], memory: bool = False) -> dict[str, Any]:
        self._validate()
        if not isinstance(names, list) or len(names) > 5000 or any(not isinstance(item, str) for item in names):
            raise StorageError("Select valid backup files")
        available = self._files()
        selected = list(dict.fromkeys(names))
        if any(name not in available for name in selected):
            raise StorageError("A selected local backup file was not found")
        if memory and not self.memory_path.is_file():
            raise StorageError("Memory database was not found")
        if not selected and not memory:
            raise StorageError("Select at least one file or the Memory database")
        with self._lock:
            if self._active and self._jobs[self._active]["status"] in {"queued", "running"}:
                raise StorageError("A backup upload is already running")
            job_id = uuid.uuid4().hex
            job = {"job_id": job_id, "status": "queued", "progress": {"completed": 0, "total": len(selected) + int(memory), "bytes_completed": 0, "bytes_total": sum(available[name].stat().st_size for name in selected), "percent": 0}, "error": "", "current": ""}
            self._jobs[job_id] = job
            self._active = job_id
        threading.Thread(target=self._upload, args=(job_id, [(name, available[name]) for name in selected], memory), daemon=True).start()
        return copy.deepcopy(job)

    def job(self, job_id: str = "") -> dict[str, Any] | None:
        with self._lock:
            job = self._jobs.get(job_id or self._active)
            return copy.deepcopy(job) if job else None

    def _upload(self, job_id: str, files: list[tuple[str, Path]], memory: bool) -> None:
        snapshot: Path | None = None
        try:
            with self._lock:
                self._jobs[job_id]["status"] = "running"
            if memory:
                with tempfile.NamedTemporaryFile(prefix="everspark-memory-", suffix=".db", delete=False) as handle:
                    snapshot = Path(handle.name)
                with sqlite3.connect(f"file:{self.memory_path}?mode=ro", uri=True) as source:
                    with sqlite3.connect(snapshot) as destination:
                        source.backup(destination)
                stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
                files.append((f"memory/everspark-{stamp}-{job_id[:8]}.db", snapshot))
                with self._lock:
                    self._jobs[job_id]["progress"]["bytes_total"] += snapshot.stat().st_size
            completed_bytes = 0
            for index, (name, path) in enumerate(files):
                with self._lock:
                    self._jobs[job_id]["current"] = name
                size = path.stat().st_size
                remote = self._remote_for(name)
                temporary = f"{remote}.{job_id}.partial"
                try:
                    self.client.run("copyto", str(path), temporary, timeout=24 * 60 * 60)
                    if self.client.file_size(temporary) != size:
                        raise StorageError(f"Uploaded size mismatch: {name}")
                    self.client.run("moveto", temporary, remote, timeout=24 * 60 * 60)
                    if self.client.file_size(remote) != size:
                        raise StorageError(f"Remote verification failed: {name}")
                except Exception:
                    try:
                        self.client.run("deletefile", temporary)
                    except StorageError:
                        pass
                    raise
                completed_bytes += size
                with self._lock:
                    progress = self._jobs[job_id]["progress"]
                    progress["completed"] = index + 1
                    progress["bytes_completed"] = completed_bytes
                    progress["percent"] = round(100 * (index + 1) / len(files), 1)
            with self._lock:
                self._jobs[job_id]["status"] = "completed"
        except Exception as exc:
            with self._lock:
                self._jobs[job_id]["status"] = "failed"
                self._jobs[job_id]["error"] = str(exc)
        finally:
            if snapshot is not None:
                snapshot.unlink(missing_ok=True)
