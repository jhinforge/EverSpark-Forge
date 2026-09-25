"""EverSpark-owned job and gallery records; engine formats stop at this boundary."""

from __future__ import annotations

import json
import sqlite3
import threading
import time
import uuid
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

from .port import ImageEngine, ImageRequest


class ImageGateway:
    def __init__(self, engine: ImageEngine | dict[str, ImageEngine], database: str,
                 output_directory: str | Path, default_engine: str = "comfyui"):
        self.engines = (engine if isinstance(engine, dict) else {engine.name: engine})
        if not self.engines:
            raise ValueError("Image Forge needs at least one registered plugin")
        self.configured_default = (default_engine if default_engine in self.engines
                                   else next(iter(self.engines)))
        self.engine = self.engines[self.configured_default]
        self.database = database
        Path(database).parent.mkdir(parents=True, exist_ok=True)
        self.output_directory = Path(output_directory).resolve()
        self._lock = threading.RLock()
        with self._connect() as connection:
            connection.execute("""CREATE TABLE IF NOT EXISTS image_jobs (
                id TEXT PRIMARY KEY, engine TEXT NOT NULL, engine_id TEXT NOT NULL,
                status TEXT NOT NULL, created REAL NOT NULL, images TEXT NOT NULL,
                details TEXT NOT NULL DEFAULT '{}'
            )""")
            connection.execute("""CREATE TABLE IF NOT EXISTS image_preferences (
                name TEXT PRIMARY KEY, value TEXT NOT NULL
            )""")

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database, timeout=15)
        connection.row_factory = sqlite3.Row
        return connection

    def default(self) -> str:
        with self._lock, self._connect() as connection:
            row = connection.execute("SELECT value FROM image_preferences WHERE name='default_engine'").fetchone()
        value = row["value"] if row else self.configured_default
        return value if value in self.engines else self.configured_default

    def set_default(self, name: str) -> None:
        if name not in self.engines:
            raise ValueError(f"Unknown image plugin: {name}")
        with self._lock, self._connect() as connection:
            connection.execute("""INSERT INTO image_preferences (name, value)
                VALUES ('default_engine', ?) ON CONFLICT(name) DO UPDATE SET value=excluded.value""",
                               (name,))

    def select(self, name: str = "") -> ImageEngine:
        selected = name or self.default()
        if selected not in self.engines:
            raise ValueError(f"Unknown image plugin: {selected}")
        return self.engines[selected]

    def resources(self, name: str = "") -> dict[str, Any]:
        selected = self.select(name)
        return {**selected.resources(), "engine": selected.name}

    def submit(self, request: ImageRequest, notify: Any = None,
               engine: str = "") -> tuple[str, dict[str, Any]]:
        selected = self.select(engine)
        engine_id, selection = selected.submit(request, notify)
        job_id = uuid.uuid4().hex
        with self._lock, self._connect() as connection:
            connection.execute("""INSERT INTO image_jobs
                (id, engine, engine_id, status, created, images) VALUES (?, ?, ?, ?, ?, ?)""",
                               (job_id, selected.name, engine_id, "running", time.time(), "[]"))
        return job_id, selection

    @staticmethod
    def _public_image(image: dict[str, str]) -> dict[str, str]:
        result = {"filename": image["filename"],
                  "subfolder": image.get("subfolder", ""),
                  "type": image.get("type", "output")}
        result["url"] = "/api/image/view?" + urlencode(result)
        return result

    def result(self, job_id: str) -> dict[str, Any]:
        with self._lock, self._connect() as connection:
            row = connection.execute("SELECT * FROM image_jobs WHERE id = ?", (job_id,)).fetchone()
            if row is None:
                raise KeyError(job_id)
            status, images = row["status"], json.loads(row["images"])
            details = json.loads(row["details"])
            if status not in {"completed", "failed"}:
                selected = self.engines.get(row["engine"])
                update = (selected.poll(row["engine_id"]) if selected is not None else
                          {"status": "failed", "images": [],
                           "error": "The image plugin used for this task is unavailable"})
                status, images = update["status"], update["images"]
                details = {key: update[key] for key in ("progress", "error") if key in update}
                if status not in {"running", "completed", "failed"}:
                    raise ValueError("Image plugin returned an invalid status")
                for image in images:
                    self.image_path(image["filename"], image.get("subfolder", ""),
                                    image.get("type", "output"))
                connection.execute("UPDATE image_jobs SET status=?, images=?, details=? WHERE id=?",
                                   (status, json.dumps(images), json.dumps(details), job_id))
        return {"prompt_id": job_id, "status": status,
                "images": [self._public_image(image) for image in images], **details}

    def results(self, job_ids: list[str]) -> list[dict[str, Any]]:
        return [self.result(job_id) for job_id in job_ids]

    def history(self, limit: int = 24) -> list[dict[str, str]]:
        with self._lock, self._connect() as connection:
            rows = connection.execute("SELECT * FROM image_jobs ORDER BY created DESC LIMIT ?",
                                      (max(1, min(100, limit)),)).fetchall()
        images: list[dict[str, str]] = []
        for row in rows:
            # Refresh unfinished jobs as well when gallery is opened after a restart.
            try:
                result = self.result(row["id"])
            except (OSError, TimeoutError):
                continue
            for image in result["images"]:
                images.append({**image, "prompt_id": row["id"]})
        # Include existing ComfyUI outputs created before the image job catalog.
        known = {(image["subfolder"], image["filename"]) for image in images}
        legacy = sorted((path for path in self.output_directory.rglob("*")
                         if path.is_file() and not path.is_symlink() and
                         path.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"}),
                        key=lambda path: path.stat().st_mtime, reverse=True)
        for path in legacy:
            if path.is_symlink():
                continue
            subfolder = path.relative_to(self.output_directory).parent.as_posix()
            subfolder = "" if subfolder == "." else subfolder
            if (subfolder, path.name) not in known:
                images.append({**self._public_image({"filename": path.name,
                                                     "subfolder": subfolder}), "prompt_id": ""})
            if len(images) >= limit:
                break
        return images[:limit]

    def image_path(self, filename: str, subfolder: str = "", kind: str = "output") -> Path:
        if kind != "output" or not filename or not self.output_directory.is_dir():
            raise ValueError("Image is unavailable")
        path = (self.output_directory / subfolder / filename).resolve()
        if path == self.output_directory or self.output_directory not in path.parents:
            raise ValueError("Invalid image path")
        if path.suffix.lower() not in {".png", ".jpg", ".jpeg", ".webp"} or not path.is_file():
            raise ValueError("Image is unavailable")
        return path
