from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import shutil
import sqlite3
import subprocess
import tempfile
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from r2_manager import RcloneClient, StorageError, StorageSettings
from remote_paths import RemotePathMap, safe_relative


REPO_ROOT = Path(__file__).resolve().parents[2]
MODEL_DIRS = {
    "checkpoint": "checkpoints",
    "diffusion_model": "diffusion_models",
    "lora": "loras",
    "vae": "vae",
}


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


class BackupManager:
    def __init__(self, config: dict[str, Any], *, run=subprocess.run):
        self.settings = StorageSettings.from_config(config)
        self.client = RcloneClient(self.settings, run=run)
        self.paths = RemotePathMap(self.settings)
        self.memory_path = Path(config["memory"]["database"]).resolve()
        self.subject_root = (self.memory_path.parent.parent if self.memory_path.parent.name == "Memory" else self.memory_path.parent) / "Subjects"
        self._lock = threading.Lock()
        self._roots_cache: tuple[float, int, dict[str, list[str]]] | None = None
        self._jobs: dict[str, dict[str, Any]] = {}
        self._active = ""

    def _validate(self) -> None:
        self.client.validate()
        self.paths.backup_root()

    def _image_targets(self, kind: str) -> list[str]:
        explicit = self.paths.read().get("image_upload", {}).get(kind)
        if explicit:
            return [self.paths.writable(explicit)]
        version = self.paths.path.stat().st_mtime_ns if self.paths.path and self.paths.path.is_file() else 0
        if not self._roots_cache or self._roots_cache[0] < time.monotonic() - 30 or self._roots_cache[1] != version:
            self._roots_cache = (time.monotonic(), version, self.paths.image_roots(self.client))
        return list(dict.fromkeys(self.paths.writable(root)
                                  for root in self._roots_cache[2][kind]
                                  if self._is_writable(root)))

    def _is_writable(self, root: str) -> bool:
        try:
            self.paths.writable(root)
            return True
        except StorageError:
            return False

    def _targets(self, name: str) -> list[str]:
        if name.startswith("models/image/"):
            directory = name.split("/", 3)[2]
            kind = next((key for key, value in MODEL_DIRS.items() if value == directory), None)
            if kind is None:
                raise StorageError("Unknown image model category")
            suffix = name.split("/", 3)[3]
            return [f"{root}/{suffix}" for root in self._image_targets(kind)]
        if name.startswith("models/concept/"):
            return [f"{self.paths.concept_upload_root()}/{name.rsplit('/', 1)[-1]}"]
        return [f"{self.paths.backup_root()}/{name}"]

    def _files(self) -> dict[str, Path]:
        result: dict[str, Path] = {}
        image_root = self.settings.image_root
        for kind, directory in MODEL_DIRS.items():
            root = image_root / directory
            if root.is_dir():
                paths = root.rglob("*")
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

    def _remote_for(self, name: str, targets: dict[str, str] | None = None) -> str:
        options = self._targets(name)
        chosen = (targets or {}).get(name, "")
        if chosen and chosen not in options:
            raise StorageError(f"Upload target is not mapped for {name}")
        if not chosen and len(options) != 1:
            raise StorageError(f"Choose an upload destination for {name}")
        return chosen or options[0]

    def resources(self) -> dict[str, Any]:
        if not self.settings.enabled:
            return {"enabled": False, "files": [], "memory": self.memory_path.is_file()}
        self._validate()
        files = []
        for name, path in self._files().items():
            size = path.stat().st_size
            options = self._targets(name)
            try:
                remote_size = self.client.file_size(options[0]) if len(options) == 1 else -1
            except StorageError:
                remote_size = -1
            files.append({"name": name, "bytes": size, "targets": options,
                          "backed_up": remote_size == size})
        return {"enabled": True, "files": files, "memory": self.memory_path.is_file(),
                "remote": self.paths.backup_root()}

    def start(self, names: list[str], memory: bool = False,
              targets: dict[str, str] | None = None) -> dict[str, Any]:
        self._validate()
        if targets is None:
            targets = {}
        if not isinstance(names, list) or len(names) > 5000 or any(not isinstance(item, str) for item in names):
            raise StorageError("Select valid backup files")
        available = self._files()
        selected = list(dict.fromkeys(names))
        if not isinstance(targets, dict):
            raise StorageError("Upload targets must be a JSON object")
        if any(name not in available for name in selected):
            raise StorageError("A selected local backup file was not found")
        if memory and not self.memory_path.is_file():
            raise StorageError("Memory database was not found")
        if not selected and not memory:
            raise StorageError("Select at least one file or the Memory database")
        ordinary = [name for name in selected if not name.startswith("subjects/")]
        data_selected = memory or len(ordinary) < len(selected)
        resolved = {name: self._remote_for(name, targets) for name in ordinary}
        data_remote = self.paths.backup_root()
        with self._lock:
            if self._active and self._jobs[self._active]["status"] in {"queued", "running"}:
                raise StorageError("A backup upload is already running")
            job_id = uuid.uuid4().hex
            job = {"job_id": job_id, "status": "queued", "progress": {"completed": 0, "total": len(ordinary) + int(data_selected), "bytes_completed": 0, "bytes_total": sum(available[name].stat().st_size for name in ordinary), "percent": 0}, "error": "", "current": ""}
            self._jobs[job_id] = job
            self._active = job_id
        threading.Thread(target=self._upload, args=(job_id, [(name, available[name]) for name in ordinary],
                                                   data_selected, resolved, data_remote), daemon=True).start()
        return copy.deepcopy(job)

    def job(self, job_id: str = "") -> dict[str, Any] | None:
        with self._lock:
            job = self._jobs.get(job_id or self._active)
            return copy.deepcopy(job) if job else None

    def restore_points(self) -> list[dict[str, Any]]:
        self._validate()
        root = f"{self.paths.backup_root()}/data_sets"
        manifests = [name for name in self.client.list_files(root, recursive=True, max_depth=2)
                     if name.endswith("/manifest.json") and len(name.split("/")) == 2]
        points = [self.restore_preview(name.split("/", 1)[0]) for name in manifests[:200]]
        return sorted(points, key=lambda item: item["created_at"], reverse=True)[:50]

    def restore_preview(self, batch_id: str) -> dict[str, Any]:
        self._validate()
        if not re.fullmatch(r"[0-9a-f]{32}", batch_id):
            raise StorageError("Invalid restore point")
        manifest = self.client.read_json(f"{self.paths.backup_root()}/data_sets/{batch_id}/manifest.json")
        files = manifest.get("files")
        if manifest.get("version") != 1 or not isinstance(files, dict) or "memory/everspark.db" not in files:
            raise StorageError("Invalid data set manifest")
        subjects: dict[str, set[str]] = {}
        for name, record in files.items():
            if not isinstance(name, str) or not safe_relative(name) or not isinstance(record, dict):
                raise StorageError("Invalid data set file path")
            if name != "memory/everspark.db":
                parts = name.split("/")
                if (len(parts) != 3 or parts[0] != "subjects" or
                        not re.fullmatch(r"[a-z0-9][a-z0-9._-]{0,127}", parts[1]) or
                        parts[2] not in {"subject.json", "metadata.json", "positive_prompt.json", "negative_prompt.json"}):
                    raise StorageError("Unexpected data set file")
                subjects.setdefault(parts[1], set()).add(parts[2])
            if (not isinstance(record.get("bytes"), int) or record["bytes"] < 0 or
                    not isinstance(record.get("sha256"), str) or
                    not re.fullmatch(r"[0-9a-f]{64}", record["sha256"])):
                raise StorageError("Invalid data set checksum")
        if any(len(names) != 4 for names in subjects.values()):
            raise StorageError("Incomplete character documents in restore point")
        return {"id": batch_id, "created_at": str(manifest.get("created_at", "")),
                "files": len(files), "subjects": len(subjects),
                "bytes": sum(record["bytes"] for record in files.values()),
                "replaces": [str(self.subject_root), str(self.memory_path)]}

    def start_restore(self, batch_id: str, task_lock: threading.Lock,
                      subject_lock: threading.RLock) -> dict[str, Any]:
        preview = self.restore_preview(batch_id)
        data_remote = self.paths.backup_root()
        if not task_lock.acquire(blocking=False):
            raise StorageError("Wait for the current generation to finish before restoring")
        with self._lock:
            if self._active and self._jobs[self._active]["status"] in {"queued", "running"}:
                task_lock.release()
                raise StorageError("Wait for the current backup job to finish")
            job_id = uuid.uuid4().hex
            self._jobs[job_id] = {"job_id": job_id, "status": "queued", "kind": "restore",
                                  "current": "", "error": "", "progress": {"percent": 0, "completed": 0,
                                  "total": preview["files"], "bytes_completed": 0, "bytes_total": preview["bytes"]}}
            self._active = job_id
        threading.Thread(target=self._restore, args=(job_id, batch_id, data_remote, task_lock, subject_lock), daemon=True).start()
        return self.job(job_id)

    def _restore(self, job_id: str, batch_id: str, data_remote: str, task_lock: threading.Lock,
                 subject_lock: threading.RLock) -> None:
        try:
            with self._lock:
                self._jobs[job_id]["status"] = "running"
            manifest = self.client.read_json(f"{data_remote}/data_sets/{batch_id}/manifest.json")
            # Validate again before using paths provided by the remote.
            self.restore_preview(batch_id)
            with tempfile.TemporaryDirectory(prefix="everspark-restore-") as temp:
                stage = Path(temp)
                for index, (name, record) in enumerate(manifest["files"].items()):
                    path = stage / name
                    with self._lock:
                        self._jobs[job_id]["current"] = name
                    self.client.copy_file(f"{data_remote}/data_sets/{batch_id}/{name}",
                                          path, known_size=record["bytes"])
                    if file_sha256(path) != record["sha256"]:
                        raise StorageError(f"Checksum mismatch: {name}")
                    with self._lock:
                        progress = self._jobs[job_id]["progress"]
                        progress["completed"] = index + 1
                        progress["bytes_completed"] += record["bytes"]
                        progress["percent"] = round(95 * progress["completed"] / progress["total"], 1)
                db = stage / "memory/everspark.db"
                with sqlite3.connect(f"file:{db}?mode=ro", uri=True) as connection:
                    if connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                        raise StorageError("Restored SQLite database did not pass integrity check")
                    rows = connection.execute("SELECT subject_id, revision, document FROM subjects").fetchall()
                    prompt_rows = dict(connection.execute(
                        "SELECT subject_id, document FROM subject_prompt_revisions "
                        "WHERE id IN (SELECT MAX(id) FROM subject_prompt_revisions GROUP BY subject_id)"
                    ).fetchall())
                folders = list((stage / "subjects").iterdir()) if (stage / "subjects").is_dir() else []
                if len(rows) != len(folders):
                    raise StorageError("Restore point has mismatched subject folders")
                for subject_id, revision, document in rows:
                    folder = stage / "subjects" / subject_id
                    subject = json.loads((folder / "subject.json").read_text())
                    subject["metadata"] = json.loads((folder / "metadata.json").read_text())
                    if subject != json.loads(document) or subject["revision"] != revision:
                        raise StorageError("Restore point subject document mismatch")
                    if subject_id in prompt_rows:
                        prompts = {key: json.loads((folder / f"{key}.json").read_text())[key]
                                   for key in ("positive_prompt", "negative_prompt")}
                        if prompts != json.loads(prompt_rows[subject_id]):
                            raise StorageError("Restore point prompt document mismatch")
                recovery = self.memory_path.parent.parent / "Recovery" / job_id
                self.memory_path.parent.mkdir(parents=True, exist_ok=True)
                self.subject_root.parent.mkdir(parents=True, exist_ok=True)
                staged_db = self.memory_path.with_name(f".{self.memory_path.name}.{job_id}.restore")
                staged_subjects = self.subject_root.parent / f".subjects-{job_id}.restore"
                try:
                    shutil.copy2(db, staged_db)
                    (stage / "subjects").mkdir(exist_ok=True)
                    shutil.copytree(stage / "subjects", staged_subjects)
                    with subject_lock:
                        recovery.mkdir(parents=True, exist_ok=False)
                        old_db = recovery / "everspark.db"
                        old_subjects = recovery / "Subjects"
                        installed_db = False
                        installed_subjects = False
                        try:
                            if self.memory_path.exists():
                                os.replace(self.memory_path, old_db)
                            for suffix in ("-wal", "-shm"):
                                sidecar = Path(str(self.memory_path) + suffix)
                                if sidecar.exists():
                                    os.replace(sidecar, recovery / ("everspark.db" + suffix))
                            if self.subject_root.exists():
                                os.replace(self.subject_root, old_subjects)
                            os.replace(staged_db, self.memory_path)
                            installed_db = True
                            os.replace(staged_subjects, self.subject_root)
                            installed_subjects = True
                        except Exception:
                            if installed_db:
                                self.memory_path.unlink(missing_ok=True)
                            if old_db.exists():
                                os.replace(old_db, self.memory_path)
                            for suffix in ("-wal", "-shm"):
                                sidecar = recovery / ("everspark.db" + suffix)
                                if sidecar.exists():
                                    os.replace(sidecar, Path(str(self.memory_path) + suffix))
                            if installed_subjects:
                                shutil.rmtree(self.subject_root)
                            if old_subjects.exists():
                                os.replace(old_subjects, self.subject_root)
                            raise
                finally:
                    staged_db.unlink(missing_ok=True)
                    if staged_subjects.exists():
                        shutil.rmtree(staged_subjects)
            with self._lock:
                self._jobs[job_id]["status"] = "completed"
                self._jobs[job_id]["progress"]["percent"] = 100.0
                self._jobs[job_id]["current"] = "Restart EverSpark to reload the restored data"
        except Exception as exc:
            with self._lock:
                self._jobs[job_id]["status"] = "failed"
                self._jobs[job_id]["error"] = str(exc)
        finally:
            task_lock.release()

    def _upload(self, job_id: str, files: list[tuple[str, Path]], memory: bool,
                destinations: dict[str, str], data_remote: str) -> None:
        try:
            with self._lock:
                self._jobs[job_id]["status"] = "running"
            data_bytes = self._upload_data_set(job_id, data_remote) if memory else 0
            if memory:
                with self._lock:
                    self._jobs[job_id]["progress"]["completed"] = 1
                    self._jobs[job_id]["progress"]["percent"] = round(100 / (len(files) + 1), 1)
            completed_bytes = data_bytes
            for index, (name, path) in enumerate(files):
                with self._lock:
                    self._jobs[job_id]["current"] = name
                size = path.stat().st_size
                remote = destinations[name]
                try:
                    if self.client.file_size(remote) == size:
                        completed_bytes += size
                        with self._lock:
                            progress = self._jobs[job_id]["progress"]
                            progress["completed"] = index + 1 + int(memory)
                            progress["bytes_completed"] = completed_bytes
                            progress["percent"] = round(100 * progress["completed"] / progress["total"], 1)
                        continue
                    raise StorageError(f"Remote file already exists with different size: {remote}")
                except StorageError as exc:
                    if "already exists" in str(exc):
                        raise
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
                    progress["completed"] = index + 1 + int(memory)
                    progress["bytes_completed"] = completed_bytes
                    progress["percent"] = round(100 * (index + 1 + int(memory)) / (len(files) + int(memory)), 1)
            with self._lock:
                self._jobs[job_id]["status"] = "completed"
                self._jobs[job_id]["progress"]["percent"] = 100.0
        except Exception as exc:
            with self._lock:
                self._jobs[job_id]["status"] = "failed"
                self._jobs[job_id]["error"] = str(exc)

    def _upload_file(self, path: Path, remote: str, job_id: str) -> None:
        temporary = f"{remote}.{job_id}.partial"
        try:
            self.client.run("copyto", str(path), temporary, timeout=24 * 60 * 60)
            if self.client.file_size(temporary) != path.stat().st_size:
                raise StorageError(f"Uploaded size mismatch: {remote}")
            self.client.run("moveto", temporary, remote, timeout=24 * 60 * 60)
        finally:
            try:
                self.client.run("deletefile", temporary)
            except StorageError:
                pass

    def _upload_data_set(self, job_id: str, data_remote: str) -> int:
        if not self.memory_path.is_file():
            raise StorageError("Memory database was not found")
        with tempfile.TemporaryDirectory(prefix="everspark-data-set-") as temp:
            stage = Path(temp)
            manifest: dict[str, Any] = {"version": 1,
                                        "created_at": datetime.now(timezone.utc).isoformat(), "files": {}}
            # Verify the subject files against the SQLite snapshot. A concurrent
            # subject edit causes a retry rather than producing a mixed set.
            for attempt in range(3):
                shutil.rmtree(stage / "subjects", ignore_errors=True)
                snapshot = stage / "memory/everspark.db"
                snapshot.parent.mkdir(parents=True, exist_ok=True)
                with sqlite3.connect(f"file:{self.memory_path}?mode=ro", uri=True) as source:
                    with sqlite3.connect(snapshot) as destination:
                        source.backup(destination)
                if self.subject_root.is_dir():
                    for folder in self.subject_root.iterdir():
                        if (folder.is_dir() and not folder.is_symlink() and
                                re.fullmatch(r"[a-z0-9][a-z0-9._-]{0,127}", folder.name)):
                            target = stage / "subjects" / folder.name
                            target.mkdir(parents=True, exist_ok=True)
                            for name in ("subject.json", "metadata.json", "positive_prompt.json", "negative_prompt.json"):
                                path = folder / name
                                if path.is_file() and not path.is_symlink():
                                    shutil.copy2(path, target / name)
                with sqlite3.connect(snapshot) as connection:
                    rows = connection.execute("SELECT subject_id, revision, document FROM subjects").fetchall()
                    try:
                        prompts = dict(connection.execute(
                            "SELECT subject_id, document FROM subject_prompt_revisions "
                            "WHERE id IN (SELECT MAX(id) FROM subject_prompt_revisions GROUP BY subject_id)"
                        ).fetchall())
                    except sqlite3.OperationalError:
                        prompts = {}
                folders = list((stage / "subjects").iterdir()) if (stage / "subjects").is_dir() else []
                consistent = len(folders) == len(rows)
                for subject_id, revision, raw in rows:
                    folder = stage / "subjects" / subject_id
                    try:
                        subject = json.loads((folder / "subject.json").read_text())
                        subject["metadata"] = json.loads((folder / "metadata.json").read_text())
                        positive = json.loads((folder / "positive_prompt.json").read_text())
                        negative = json.loads((folder / "negative_prompt.json").read_text())
                        latest = json.loads(prompts[subject_id]) if subject_id in prompts else None
                        consistent &= (subject["revision"] == revision and
                                       all(subject.get(key) == value for key, value in json.loads(raw).items()) and
                                       (latest is None or latest == {"positive_prompt": positive["positive_prompt"],
                                                                      "negative_prompt": negative["negative_prompt"]}))
                    except (OSError, ValueError, KeyError, TypeError):
                        consistent = False
                if consistent:
                    break
            else:
                raise StorageError("Subjects changed during snapshot; retry the backup")
            paths = [path for path in sorted(stage.rglob("*")) if path.is_file()]
            batch_bytes = sum(path.stat().st_size for path in paths)
            with self._lock:
                self._jobs[job_id]["progress"]["bytes_total"] += batch_bytes
            transferred = 0
            for path in paths:
                if path.is_file():
                    name = path.relative_to(stage).as_posix()
                    manifest["files"][name] = {"sha256": file_sha256(path), "bytes": path.stat().st_size}
                    with self._lock:
                        self._jobs[job_id]["current"] = name
                    self._upload_file(path, f"{data_remote}/data_sets/{job_id}/{name}", job_id)
                    transferred += path.stat().st_size
                    with self._lock:
                        self._jobs[job_id]["progress"]["bytes_completed"] = transferred
            manifest_path = stage / "manifest.json"
            manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            self._upload_file(manifest_path, f"{data_remote}/data_sets/{job_id}/manifest.json", job_id)
            return transferred
