"""Resource management and maintenance, independent of task orchestration."""
from __future__ import annotations
from pathlib import Path
from typing import Any
from Aegis.Shared.errors import BusyError
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
from r2_manager import R2StorageManager
from download_manager import DirectDownloadManager
from backup_manager import BackupManager
from local_data_archive import LocalDataArchive

class StorageService:
    def __init__(self, config, maintenance_lock, persistence_lock):
        self.storage = R2StorageManager(config)
        self.downloads = DirectDownloadManager(config)
        self.backups = BackupManager(config)
        self.data_archive = LocalDataArchive(self.backups.memory_path,
            self.backups.subject_root, Path(__file__).resolve().parents[2])
        self._task_lock = maintenance_lock
        self._persistence_lock = persistence_lock

    def storage_resources(self) -> dict[str, Any]:
        return self.storage.resources()

    def export_data_archive(self) -> str:
        if not self._task_lock.acquire(blocking=False):
            raise BusyError("A task is running; try again after it completes")
        try:
            with self._persistence_lock:
                archive_id, _ = self.data_archive.export()
            return archive_id
        finally:
            self._task_lock.release()

    def restore_data_archive(self, archive_id: str) -> dict[str, Any]:
        if not self._task_lock.acquire(blocking=False):
            raise BusyError("A task is running; try again after it completes")
        try:
            with self._persistence_lock:
                return self.data_archive.restore(archive_id)
        finally:
            self._task_lock.release()

    def storage_scan(self) -> dict[str, Any]:
        return self.storage.scan_status()

    def start_storage_scan(self) -> dict[str, Any]:
        return self.storage.start_scan()

    def backup_resources(self) -> dict[str, Any]:
        return self.backups.resources()

    def restore_points(self) -> list[dict[str, Any]]:
        return self.backups.restore_points()

    def start_restore(self, batch_id: str) -> dict[str, Any]:
        return self.backups.start_restore(batch_id, self._task_lock, self._persistence_lock)

    def save_storage_paths(self, mapping: dict[str, Any]) -> dict[str, Any]:
        return self.storage.save_paths(mapping)

    def start_backup(self, names: list[str], memory: bool = False,
                     targets: dict[str, str] | None = None, outputs: bool = False) -> dict[str, Any]:
        return self.backups.start(names, memory, targets, outputs)

    def backup_job(self, job_id: str = "") -> dict[str, Any] | None:
        return self.backups.job(job_id)

    def start_storage_pull(self, kind: str, name: str) -> dict[str, Any]:
        return self.storage.start_pull(kind, name)

    def storage_job(self, job_id: str = "") -> dict[str, Any] | None:
        return self.storage.job(job_id)

    def start_download(
        self,
        kind: str,
        url: str,
        filename: str = "",
        runtime_name: str = "",
    ) -> dict[str, Any]:
        return self.downloads.start(kind, url, filename, runtime_name)

    def download_job(self, job_id: str = "") -> dict[str, Any] | None:
        return self.downloads.job(job_id)

    def cancel_download(self, job_id: str) -> dict[str, Any]:
        return self.downloads.cancel(job_id)

    def retry_download(self, job_id: str) -> dict[str, Any]:
        return self.downloads.retry(job_id)
