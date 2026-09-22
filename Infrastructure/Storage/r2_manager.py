from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import threading
import uuid
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Callable


REPO_ROOT = Path(__file__).resolve().parents[2]
IMAGE_KINDS = {
    "checkpoint": "checkpoints",
    "diffusion_model": "diffusion_models",
    "lora": "loras",
}
DIGEST_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")


class StorageError(RuntimeError):
    pass


@dataclass(frozen=True)
class StorageSettings:
    enabled: bool
    backend: str
    config_file: Path | None
    image_remote: str
    concept_remote: str
    image_root: Path
    concept_root: Path
    timeout: int = 60

    @classmethod
    def from_config(cls, config: dict[str, Any]) -> "StorageSettings":
        storage = config.get("storage", {})
        if not isinstance(storage, dict):
            raise StorageError("storage configuration must be an object")
        backend = str(storage.get("backend", "local")).strip().lower()
        rclone = storage.get("rclone", {})
        if not isinstance(rclone, dict):
            raise StorageError("storage.rclone must be an object")
        raw_config = str(rclone.get("config_file") or "").strip()
        config_file = Path(raw_config).expanduser() if raw_config else None
        if config_file is not None and not config_file.is_absolute():
            config_file = (REPO_ROOT / config_file).resolve()
        enabled = backend == "rclone" and bool(rclone.get("enabled", True))
        return cls(
            enabled=enabled,
            backend=backend,
            config_file=config_file,
            image_remote=_clean_remote(str(rclone.get("image_remote") or "")),
            concept_remote=_clean_remote(str(rclone.get("concept_remote") or "")),
            image_root=(REPO_ROOT / "Data/Models/ImageForge").resolve(),
            concept_root=(REPO_ROOT / "Data/Models/ConceptForge/Ollama").resolve(),
            timeout=int(rclone.get("timeout", 60)),
        )


def _clean_remote(value: str) -> str:
    cleaned = value.strip().rstrip("/")
    if "\n" in cleaned or "\r" in cleaned:
        raise StorageError("rclone remote path cannot contain newlines")
    return cleaned


class RcloneClient:
    def __init__(
        self,
        settings: StorageSettings,
        run: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
    ):
        self.settings = settings
        self._run_command = run

    def validate(self) -> None:
        if not self.settings.enabled:
            raise StorageError("Remote storage is disabled")
        if self.settings.backend != "rclone":
            raise StorageError(f"Unsupported storage backend: {self.settings.backend}")
        if shutil.which("rclone") is None:
            raise StorageError("rclone is not installed")
        if self.settings.config_file is None:
            raise StorageError("RCLONE_CONFIG is required when remote storage is enabled")
        if not self.settings.config_file.is_file():
            raise StorageError(f"rclone config not found: {self.settings.config_file}")
        if not self.settings.image_remote:
            raise StorageError("IMAGE_FORGE_RCLONE_REMOTE is required")
        if not self.settings.concept_remote:
            raise StorageError("CONCEPT_FORGE_RCLONE_REMOTE is required")

    def run(self, *arguments: str, timeout: int | None = None) -> str:
        command = ["rclone", *arguments]
        if self.settings.config_file is not None:
            command.extend(["--config", str(self.settings.config_file)])
        log_root = Path(
            os.environ.get("EVERSPARK_LOG_DIR", str(REPO_ROOT / "Data/Logs"))
        ).expanduser()
        if not log_root.is_absolute():
            log_root = (REPO_ROOT / log_root).resolve()
        log_root.mkdir(parents=True, exist_ok=True)
        command.extend(["--log-file", str(log_root / "rclone.log"), "--log-level", "INFO"])
        try:
            completed = self._run_command(
                command,
                check=False,
                capture_output=True,
                text=True,
                timeout=timeout or self.settings.timeout,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise StorageError(f"Could not run rclone: {exc}") from exc
        if completed.returncode != 0:
            detail = (completed.stderr or completed.stdout or "unknown error").strip()
            raise StorageError(f"rclone failed: {detail}")
        return completed.stdout

    def list_files(self, remote: str, *, recursive: bool = False) -> list[str]:
        arguments = ["lsf", remote, "--files-only"]
        if recursive:
            arguments.append("-R")
        output = self.run(*arguments)
        return [line.strip().removesuffix("/") for line in output.splitlines() if line.strip()]

    def read_json(self, remote_file: str) -> dict[str, Any]:
        raw = self.run("cat", remote_file)
        try:
            value = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise StorageError(f"Remote Ollama manifest is invalid JSON: {remote_file}") from exc
        if not isinstance(value, dict):
            raise StorageError(f"Remote Ollama manifest must be an object: {remote_file}")
        return value

    def copy_file(self, remote_file: str, local_file: Path) -> None:
        local_file.parent.mkdir(parents=True, exist_ok=True)
        self.run(
            "copyto",
            remote_file,
            str(local_file),
            timeout=24 * 60 * 60,
        )


class R2StorageManager:
    def __init__(
        self,
        config: dict[str, Any],
        *,
        run: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
    ):
        self.settings = StorageSettings.from_config(config)
        self.client = RcloneClient(self.settings, run=run)
        self._lock = threading.Lock()
        self._jobs: dict[str, dict[str, Any]] = {}
        self._active_job = ""

    def resources(self) -> dict[str, Any]:
        if not self.settings.enabled:
            return {
                "enabled": False,
                "backend": self.settings.backend,
                "image": {key: [] for key in IMAGE_KINDS},
                "concept": {"models": []},
            }
        self.client.validate()
        image: dict[str, list[dict[str, Any]]] = {}
        for kind, directory in IMAGE_KINDS.items():
            remote = f"{self.settings.image_remote}/{directory}"
            local_names = self._local_name_map(self.settings.image_root / directory)
            image[kind] = [
                {
                    "name": name,
                    "installed": name.casefold() in local_names,
                }
                for name in self.client.list_files(remote)
            ]

        manifests_root = f"{self.settings.concept_remote}/manifests"
        concept_models = []
        for path in self.client.list_files(manifests_root, recursive=True):
            self._safe_remote_relative(path)
            model_name = self._ollama_model_name(path)
            if not model_name:
                continue
            local_manifest = self.settings.concept_root / "manifests" / PurePosixPath(path)
            concept_models.append(
                {
                    "name": model_name,
                    "manifest": path,
                    "installed": local_manifest.is_file(),
                }
            )
        concept_models.sort(key=lambda item: item["name"].casefold())
        return {
            "enabled": True,
            "backend": "rclone",
            "image": image,
            "concept": {"models": concept_models},
        }

    def start_pull(self, kind: str, name: str) -> dict[str, Any]:
        normalized_kind = str(kind).strip().lower()
        normalized_name = str(name).strip()
        if normalized_kind not in {*IMAGE_KINDS, "concept_model"}:
            raise StorageError(f"Unsupported remote resource kind: {kind}")
        if not normalized_name:
            raise StorageError("Remote resource name is required")
        self.client.validate()
        with self._lock:
            if self._active_job:
                active = self._jobs.get(self._active_job, {})
                if active.get("status") in {"queued", "running"}:
                    raise StorageError("A remote storage download is already running")
            job_id = uuid.uuid4().hex
            job = {
                "job_id": job_id,
                "kind": normalized_kind,
                "name": normalized_name,
                "status": "queued",
                "progress": {"completed": 0, "total": 0},
                "error": "",
            }
            self._jobs[job_id] = job
            self._active_job = job_id
        thread = threading.Thread(
            target=self._run_pull,
            args=(job_id,),
            name=f"everspark-r2-{job_id[:8]}",
            daemon=True,
        )
        thread.start()
        return dict(job)

    def job(self, job_id: str = "") -> dict[str, Any] | None:
        with self._lock:
            selected = job_id or self._active_job
            job = self._jobs.get(selected)
            return json.loads(json.dumps(job)) if job else None

    def _run_pull(self, job_id: str) -> None:
        with self._lock:
            job = self._jobs[job_id]
            job["status"] = "running"
            kind = str(job["kind"])
            name = str(job["name"])
        try:
            if kind == "concept_model":
                self._pull_concept_model(job_id, name)
            else:
                self._pull_image_model(job_id, kind, name)
            with self._lock:
                self._jobs[job_id]["status"] = "completed"
        except Exception as exc:
            with self._lock:
                self._jobs[job_id]["status"] = "failed"
                self._jobs[job_id]["error"] = str(exc)

    def _pull_image_model(self, job_id: str, kind: str, requested: str) -> None:
        directory = IMAGE_KINDS[kind]
        remote_dir = f"{self.settings.image_remote}/{directory}"
        available = self.client.list_files(remote_dir)
        match = {name.casefold(): name for name in available}.get(requested.casefold())
        if not match:
            raise StorageError(f"Remote {kind} was not found: {requested}")
        if PurePosixPath(match).name != match:
            raise StorageError("Image model names must not contain directories")
        self._set_progress(job_id, 0, 1)
        destination = self.settings.image_root / directory / match
        self.client.copy_file(f"{remote_dir}/{match}", destination)
        self._set_progress(job_id, 1, 1)

    def _pull_concept_model(self, job_id: str, requested: str) -> None:
        manifests_root = f"{self.settings.concept_remote}/manifests"
        paths = self.client.list_files(manifests_root, recursive=True)
        models = {
            self._ollama_model_name(self._safe_remote_relative(path)).casefold(): path
            for path in paths
        }
        manifest_path = models.get(requested.casefold())
        if not manifest_path:
            raise StorageError(f"Remote Concept Forge model was not found: {requested}")
        manifest_remote = f"{manifests_root}/{manifest_path}"
        manifest = self.client.read_json(manifest_remote)
        digests = self._manifest_digests(manifest)
        self._set_progress(job_id, 0, len(digests) + 1)
        completed = 0
        for digest in digests:
            blob_name = digest.replace(":", "-", 1)
            destination = self.settings.concept_root / "blobs" / blob_name
            if not destination.is_file() or destination.stat().st_size == 0:
                self.client.copy_file(
                    f"{self.settings.concept_remote}/blobs/{blob_name}", destination
                )
            completed += 1
            self._set_progress(job_id, completed, len(digests) + 1)
        manifest_destination = (
            self.settings.concept_root / "manifests" / PurePosixPath(manifest_path)
        )
        self.client.copy_file(manifest_remote, manifest_destination)
        self._set_progress(job_id, len(digests) + 1, len(digests) + 1)

    @staticmethod
    def _manifest_digests(manifest: dict[str, Any]) -> list[str]:
        candidates: list[Any] = []
        config = manifest.get("config")
        if isinstance(config, dict):
            candidates.append(config.get("digest"))
        layers = manifest.get("layers")
        if isinstance(layers, list):
            candidates.extend(
                layer.get("digest") for layer in layers if isinstance(layer, dict)
            )
        digests: list[str] = []
        for value in candidates:
            digest = str(value or "")
            if not DIGEST_PATTERN.fullmatch(digest):
                raise StorageError(f"Unsafe or invalid Ollama blob digest: {digest}")
            if digest not in digests:
                digests.append(digest)
        if not digests:
            raise StorageError("Remote Ollama manifest contains no blobs")
        return digests

    @staticmethod
    def _ollama_model_name(path: str) -> str:
        parts = PurePosixPath(path).parts
        if len(parts) < 3:
            return ""
        tag = parts[-1]
        namespace = parts[1]
        model_parts = parts[2:-1] if namespace == "library" else parts[1:-1]
        if not model_parts or not tag:
            return ""
        return f"{'/'.join(model_parts)}:{tag}"

    @staticmethod
    def _safe_remote_relative(path: str) -> str:
        candidate = PurePosixPath(path)
        if candidate.is_absolute() or any(part in {"", ".", ".."} for part in candidate.parts):
            raise StorageError(f"Unsafe remote path: {path}")
        return path

    @staticmethod
    def _local_name_map(directory: Path) -> dict[str, str]:
        if not directory.is_dir():
            return {}
        return {
            path.name.casefold(): path.name
            for path in directory.iterdir()
            if path.is_file()
        }

    def _set_progress(self, job_id: str, completed: int, total: int) -> None:
        with self._lock:
            self._jobs[job_id]["progress"] = {
                "completed": completed,
                "total": total,
            }
