"""Portable character and Memory snapshots, independent of remote storage."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import sqlite3
import tempfile
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
MAX_UPLOAD = 128 * 1024 * 1024
MAX_UNPACKED = 512 * 1024 * 1024
SUBJECT_FILES = ("subject.json", "metadata.json", "positive_prompt.json", "negative_prompt.json")
SUBJECT_ID = re.compile(r"[a-z0-9][a-z0-9._-]{0,127}\Z")
ARCHIVE_ID = re.compile(r"[a-f0-9]{32}\Z")
HASH = re.compile(r"[a-f0-9]{64}\Z")


class DataArchiveError(ValueError):
    pass


def _hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


class LocalDataArchive:
    def __init__(self, database: Path, subjects: Path, root: Path = REPO_ROOT):
        self.database = Path(database).resolve()
        self.subjects = Path(subjects).resolve()
        self.imports = root / "Data/Imports"
        self.archives = root / "Data/Runtime/Archives"
        self.recovery = root / "Data/Recovery"

    def archive_path(self, archive_id: str) -> Path:
        if not ARCHIVE_ID.fullmatch(archive_id):
            raise DataArchiveError("Invalid archive identifier")
        return self.archives / f"everspark-data-{archive_id}.zip"

    def import_path(self, archive_id: str) -> Path:
        if not ARCHIVE_ID.fullmatch(archive_id):
            raise DataArchiveError("Invalid import identifier")
        return self.imports / f"{archive_id}.zip"

    def _snapshot(self, stage: Path) -> dict:
        if not self.database.is_file():
            raise DataArchiveError("Memory database is not available")
        snapshot = stage / "memory/everspark.db"
        snapshot.parent.mkdir(parents=True)
        for _ in range(3):
            shutil.rmtree(stage / "subjects", ignore_errors=True)
            with sqlite3.connect(f"file:{self.database}?mode=ro", uri=True) as source:
                with sqlite3.connect(snapshot) as destination:
                    source.backup(destination)
            if self.subjects.is_dir():
                for folder in self.subjects.iterdir():
                    if folder.is_dir() and not folder.is_symlink() and SUBJECT_ID.fullmatch(folder.name):
                        target = stage / "subjects" / folder.name
                        target.mkdir(parents=True)
                        for filename in SUBJECT_FILES:
                            path = folder / filename
                            if path.is_file() and not path.is_symlink():
                                shutil.copy2(path, target / filename)
            try:
                self._verify_database(stage)
                break
            except (DataArchiveError, OSError, ValueError, KeyError, TypeError):
                continue
        else:
            raise DataArchiveError("Character data changed during snapshot; try again")
        files = {p.relative_to(stage).as_posix(): {"bytes": p.stat().st_size, "sha256": _hash(p)}
                 for p in sorted(stage.rglob("*")) if p.is_file()}
        return {"version": 1, "created_at": datetime.now(timezone.utc).isoformat(), "files": files}

    def export(self) -> tuple[str, Path]:
        self.archives.mkdir(parents=True, exist_ok=True)
        archive_id = uuid.uuid4().hex
        target = self.archive_path(archive_id)
        try:
            with tempfile.TemporaryDirectory(prefix="everspark-snapshot-") as directory:
                stage = Path(directory)
                manifest = self._snapshot(stage)
                with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as output:
                    output.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
                    for name in manifest["files"]:
                        output.write(stage / name, name)
            if target.stat().st_size > MAX_UPLOAD:
                raise DataArchiveError("Data ZIP exceeds the 128 MiB upload limit")
            return archive_id, target
        except Exception:
            target.unlink(missing_ok=True)
            raise

    @staticmethod
    def _allowed(name: str) -> bool:
        if name == "memory/everspark.db":
            return True
        parts = name.split("/")
        return (len(parts) == 3 and parts[0] == "subjects" and
                SUBJECT_ID.fullmatch(parts[1]) is not None and parts[2] in SUBJECT_FILES)

    def _unpack(self, archive: Path, stage: Path) -> None:
        try:
            if not archive.is_file() or archive.stat().st_size > MAX_UPLOAD:
                raise DataArchiveError("ZIP file is missing or too large")
            with zipfile.ZipFile(archive) as source:
                members = source.infolist()
                names = [entry.filename for entry in members]
                if (len(names) != len(set(names)) or len(names) > 5000 or
                        "manifest.json" not in names or "memory/everspark.db" not in names or
                        any(not (self._allowed(name) or name == "manifest.json") for name in names) or
                        any(entry.is_dir() or ((entry.external_attr >> 16) & 0o170000) == 0o120000
                            or entry.flag_bits & 0x1 for entry in members) or
                        sum(entry.file_size for entry in members) > MAX_UNPACKED or
                        any(entry.file_size > MAX_UPLOAD or entry.compress_size > MAX_UPLOAD for entry in members)):
                    raise DataArchiveError("ZIP contains invalid or oversized files")
                manifest_file = source.getinfo("manifest.json")
                if manifest_file.file_size > 1_000_000:
                    raise DataArchiveError("ZIP manifest is too large")
                manifest = json.loads(source.read(manifest_file))
                files = manifest.get("files") if isinstance(manifest, dict) else None
                if not isinstance(manifest, dict) or manifest.get("version") != 1 or not isinstance(files, dict) or set(files) != set(names) - {"manifest.json"}:
                    raise DataArchiveError("ZIP manifest does not match its files")
                subjects: dict[str, set[str]] = {}
                for name, record in files.items():
                    entry = source.getinfo(name)
                    if (not isinstance(record, dict) or type(record.get("bytes")) is not int or
                            record["bytes"] != entry.file_size or not isinstance(record.get("sha256"), str) or
                            not HASH.fullmatch(record["sha256"])):
                        raise DataArchiveError("ZIP manifest contains invalid checksums")
                    if name.startswith("subjects/"):
                        _, subject_id, filename = name.split("/")
                        subjects.setdefault(subject_id, set()).add(filename)
                if any(names != set(SUBJECT_FILES) for names in subjects.values()):
                    raise DataArchiveError("ZIP has incomplete character documents")
                for name, record in files.items():
                    destination = stage / name
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    digest = hashlib.sha256()
                    actual = 0
                    with source.open(name) as reader, destination.open("wb") as writer:
                        for chunk in iter(lambda: reader.read(1024 * 1024), b""):
                            actual += len(chunk)
                            if actual > record["bytes"] or actual > MAX_UPLOAD:
                                raise DataArchiveError("ZIP contents exceed declared size")
                            writer.write(chunk)
                            digest.update(chunk)
                    if actual != record["bytes"] or digest.hexdigest() != record["sha256"]:
                        raise DataArchiveError(f"ZIP checksum mismatch: {name}")
        except (zipfile.BadZipFile, RuntimeError, NotImplementedError, json.JSONDecodeError, KeyError, OSError) as exc:
            raise DataArchiveError("ZIP is damaged or not an EverSpark data archive") from exc

    @staticmethod
    def _verify_database(stage: Path) -> int:
        database = stage / "memory/everspark.db"
        with sqlite3.connect(f"file:{database}?mode=ro", uri=True) as connection:
            if connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise DataArchiveError("SQLite integrity check failed")
            rows = connection.execute("SELECT subject_id, revision, document FROM subjects").fetchall()
            try:
                prompts = dict(connection.execute(
                    "SELECT subject_id, document FROM subject_prompt_revisions "
                    "WHERE id IN (SELECT MAX(id) FROM subject_prompt_revisions GROUP BY subject_id)"
                ).fetchall())
            except sqlite3.OperationalError:
                prompts = {}
        folders = list((stage / "subjects").iterdir()) if (stage / "subjects").is_dir() else []
        if len(rows) != len(folders):
            raise DataArchiveError("SQLite and character folders do not match")
        for subject_id, revision, raw in rows:
            if not isinstance(subject_id, str) or not SUBJECT_ID.fullmatch(subject_id):
                raise DataArchiveError("Invalid character identifier in SQLite")
            folder = stage / "subjects" / subject_id
            subject = json.loads((folder / "subject.json").read_text(encoding="utf-8"))
            subject["metadata"] = json.loads((folder / "metadata.json").read_text(encoding="utf-8"))
            if subject["revision"] != revision or any(subject.get(key) != value for key, value in json.loads(raw).items()):
                raise DataArchiveError("SQLite and character documents do not match")
            positive = json.loads((folder / "positive_prompt.json").read_text(encoding="utf-8"))
            negative = json.loads((folder / "negative_prompt.json").read_text(encoding="utf-8"))
            if subject_id in prompts:
                if json.loads(prompts[subject_id]) != {
                    "positive_prompt": positive["positive_prompt"], "negative_prompt": negative["negative_prompt"]
                }:
                    raise DataArchiveError("SQLite and prompt documents do not match")
        return len(rows)

    def restore(self, archive_id: str) -> dict:
        archive = self.import_path(archive_id)
        with tempfile.TemporaryDirectory(prefix="everspark-local-restore-") as directory:
            stage = Path(directory)
            self._unpack(archive, stage)
            try:
                count = self._verify_database(stage)
            except (sqlite3.DatabaseError, OSError, KeyError, TypeError, ValueError) as exc:
                raise DataArchiveError("ZIP character data or SQLite is invalid") from exc
            restore_id = uuid.uuid4().hex
            recovery = self.recovery / restore_id
            self.database.parent.mkdir(parents=True, exist_ok=True)
            self.subjects.parent.mkdir(parents=True, exist_ok=True)
            staged_db = self.database.with_name(f".{self.database.name}.{restore_id}.restore")
            staged_subjects = self.subjects.parent / f".subjects-{restore_id}.restore"
            try:
                shutil.copy2(stage / "memory/everspark.db", staged_db)
                (stage / "subjects").mkdir(exist_ok=True)
                shutil.copytree(stage / "subjects", staged_subjects)
                recovery.mkdir(parents=True, exist_ok=False)
                old_db = recovery / "everspark.db"
                old_subjects = recovery / "Subjects"
                installed_db = installed_subjects = False
                try:
                    if self.database.exists():
                        os.replace(self.database, old_db)
                    for suffix in ("-wal", "-shm"):
                        sidecar = Path(str(self.database) + suffix)
                        if sidecar.exists():
                            os.replace(sidecar, recovery / ("everspark.db" + suffix))
                    if self.subjects.exists():
                        os.replace(self.subjects, old_subjects)
                    os.replace(staged_db, self.database)
                    installed_db = True
                    os.replace(staged_subjects, self.subjects)
                    installed_subjects = True
                except Exception:
                    if installed_db:
                        self.database.unlink(missing_ok=True)
                    if old_db.exists():
                        os.replace(old_db, self.database)
                    for suffix in ("-wal", "-shm"):
                        previous = recovery / ("everspark.db" + suffix)
                        if previous.exists():
                            os.replace(previous, Path(str(self.database) + suffix))
                    if installed_subjects:
                        shutil.rmtree(self.subjects)
                    if old_subjects.exists():
                        os.replace(old_subjects, self.subjects)
                    raise
            finally:
                staged_db.unlink(missing_ok=True)
                if staged_subjects.exists():
                    shutil.rmtree(staged_subjects)
        return {"subjects": count, "recovery": str(recovery), "restart_required": True}
