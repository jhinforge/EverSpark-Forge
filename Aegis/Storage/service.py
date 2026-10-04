"""Resource management and maintenance, independent of task orchestration."""
from __future__ import annotations
from pathlib import Path
from typing import Any
import sys
from contextlib import contextmanager
import copy
import threading
sys.path.insert(0, str(Path(__file__).resolve().parent))
from r2_manager import R2StorageManager
from download_manager import DirectDownloadManager
from backup_manager import BackupManager
from local_data_archive import LocalDataArchive

class StorageService:
    def __init__(self, config):
        self.config = copy.deepcopy(config)
        self.configuration_lock = threading.RLock()
        self.storage = R2StorageManager(config)
        self.downloads = DirectDownloadManager(config)
        self.remote = None
        if config.get("remote_nodes", {}).get("remote_only") or any(
                config.get("remote_nodes", {}).get(f"{role}_node_id") for role in ("image", "concept")):
            from .remote_models import RemoteModels
            self.remote = RemoteModels(config, self.storage)
            local_resources = self.storage.resources
            self.storage.resources = lambda: self.remote.annotate(local_resources())
        self.backups = BackupManager(config)
        self.data_archive = LocalDataArchive(self.backups.memory_path,
            self.backups.subject_root, Path(__file__).resolve().parents[2])

    @contextmanager
    def configuration_guard(self):
        with self.configuration_lock:
            if self.storage.scan_status()["status"] == "running" or any(
                    job.get("status") in {"queued", "running"} for job in
                    [*self.storage._jobs.values(), *self.backups._jobs.values()]):
                raise ValueError("Wait for the current storage operation before changing configuration")
            yield

    def reconfigure(self, values):
        with self.configuration_lock:
            with self.storage._lock, self.backups._lock:
                if self.storage.scan_status()["status"] == "running" or any(
                        job.get("status") in {"queued", "running"} for job in
                        [*self.storage._jobs.values(), *self.backups._jobs.values()]):
                    raise ValueError("Wait for the current storage operation before changing configuration")
                config = copy.deepcopy(self.config)
                config["storage"]["backend"] = values["EVERSPARK_STORAGE_BACKEND"]
                mapping = {"RCLONE_CONFIG": "config_file", "RCLONE_BIN": "binary",
                           "IMAGE_FORGE_RCLONE_REMOTE": "image_remote",
                           "CONCEPT_FORGE_RCLONE_REMOTE": "concept_remote"}
                for key, field in mapping.items():
                    config["storage"]["rclone"][field] = values[key]
                config["storage"]["rclone"]["enabled"] = config["storage"]["backend"] == "rclone"
                catalog = R2StorageManager(config)
                backups = BackupManager(config)
                # Keep direct-download and remote-transfer jobs, and node routing.
                if self.remote:
                    self.remote.config = config
                    self.remote.catalog = catalog
                    original = catalog.resources
                    catalog.resources = lambda: self.remote.annotate(original())
                catalog._jobs, catalog._active_job = self.storage._jobs, self.storage._active_job
                backups._jobs, backups._active = self.backups._jobs, self.backups._active
                self.config, self.storage, self.backups = config, catalog, backups

    def storage_resources(self) -> dict[str, Any]:
        return self.storage.resources()

    def export_data_archive(self) -> str:
        archive_id, _ = self.data_archive.export()
        return archive_id

    def restore_data_archive(self, archive_id: str) -> dict[str, Any]:
        return self.data_archive.restore(archive_id)

    def storage_scan(self) -> dict[str, Any]:
        return self.storage.scan_status()

    def start_storage_scan(self) -> dict[str, Any]:
        with self.configuration_lock:
            return self.storage.start_scan()

    def backup_resources(self) -> dict[str, Any]:
        return self.backups.resources()

    def restore_points(self) -> list[dict[str, Any]]:
        return self.backups.restore_points()

    def start_restore(self, batch_id: str) -> dict[str, Any]:
        with self.configuration_lock:
            return self.backups.start_restore(batch_id)

    def save_storage_paths(self, mapping: dict[str, Any]) -> dict[str, Any]:
        with self.configuration_lock:
            return self.storage.save_paths(mapping)

    def start_backup(self, names: list[str], memory: bool = False,
                     targets: dict[str, str] | None = None, outputs: bool = False) -> dict[str, Any]:
        with self.configuration_lock:
            return self.backups.start(names, memory, targets, outputs)

    def backup_job(self, job_id: str = "") -> dict[str, Any] | None:
        return self.backups.job(job_id)

    def start_storage_pull(self, kind: str, name: str) -> dict[str, Any]:
        with self.configuration_lock:
            if self.remote:
                return self.remote.start("pull", kind, name=name)
            return self.storage.start_pull(kind, name)

    def storage_job(self, job_id: str = "") -> dict[str, Any] | None:
        if self.remote:
            return self.remote.job("pull", job_id)
        return self.storage.job(job_id)

    def start_download(
        self,
        kind: str,
        url: str,
        filename: str = "",
        runtime_name: str = "",
    ) -> dict[str, Any]:
        if self.remote:
            return self.remote.start("download", kind, url=url, filename=filename, runtime_name=runtime_name)
        return self.downloads.start(kind, url, filename, runtime_name)

    def download_job(self, job_id: str = "") -> dict[str, Any] | None:
        if self.remote:
            return self.remote.job("download", job_id)
        return self.downloads.job(job_id)

    def cancel_download(self, job_id: str) -> dict[str, Any]:
        if self.remote:
            return self.remote.job("download", job_id, "cancel")
        return self.downloads.cancel(job_id)

    def retry_download(self, job_id: str) -> dict[str, Any]:
        if self.remote:
            return self.remote.job("download", job_id, "retry")
        return self.downloads.retry(job_id)
