from __future__ import annotations

import sqlite3
import sys
import tempfile
import time
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "Infrastructure/Storage"))
from backup_manager import BackupManager, StorageError  # noqa: E402


class FakeRclone:
    def __init__(self):
        self.remote: dict[str, bytes] = {}

    def validate(self):
        pass

    def file_size(self, name):
        if name not in self.remote:
            raise StorageError("missing")
        return len(self.remote[name])

    def run(self, action, *arguments, **_kwargs):
        if action == "copyto":
            self.remote[arguments[1]] = Path(arguments[0]).read_bytes()
        elif action == "moveto":
            self.remote[arguments[1]] = self.remote.pop(arguments[0])
        elif action == "deletefile":
            self.remote.pop(arguments[0], None)


class BackupUploadTests(unittest.TestCase):
    def test_uploads_selected_image_gguf_output_and_consistent_memory_snapshot(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            image = root / "image/checkpoints/new.safetensors"
            image.parent.mkdir(parents=True)
            image.write_bytes(b"model")
            vae = root / "image/vae/SDXL/custom.safetensors"
            vae.parent.mkdir(parents=True)
            vae.write_bytes(b"VAE-data")
            subject = root / "Subjects/subject-1/subject.json"
            subject.parent.mkdir(parents=True)
            subject.write_text('{"identity": {}}', encoding="utf-8")
            gguf = root / "Data/Models/ConceptForge/new.gguf"
            gguf.parent.mkdir(parents=True)
            gguf.write_bytes(b"GGUF-test")
            output = root / "Data/Outputs/sub/image.png"
            output.parent.mkdir(parents=True)
            output.write_bytes(b"PNG")
            database = root / "memory.db"
            with sqlite3.connect(database) as connection:
                connection.execute("CREATE TABLE message (value TEXT)")
                connection.execute("INSERT INTO message VALUES ('saved')")
            config = {"storage": {"backend": "rclone", "rclone": {
                "enabled": True, "image_remote": "r:images", "concept_remote": "r:ollama",
                "backup_remote": "r:backup"}}, "memory": {"database": str(database)}}
            with patch("backup_manager.REPO_ROOT", root):
                manager = BackupManager(config)
                manager.settings = replace(manager.settings, image_root=root / "image")
                fake = FakeRclone()
                manager.client = fake
                names = ["models/image/checkpoints/new.safetensors", "models/image/vae/SDXL/custom.safetensors", "models/concept/new.gguf", "outputs/sub/image.png", "subjects/subject-1/subject.json"]
                job = manager.start(names, memory=True)
                for _ in range(200):
                    current = manager.job(job["job_id"])
                    if current["status"] in {"completed", "failed"}:
                        break
                    time.sleep(.01)
                self.assertEqual(current["status"], "completed", current["error"])
                self.assertEqual(fake.remote["r:images/checkpoints/new.safetensors"], b"model")
                self.assertEqual(fake.remote["r:images/vae/SDXL/custom.safetensors"], b"VAE-data")
                self.assertEqual(fake.remote["r:backup/models/concept/new.gguf"], b"GGUF-test")
                self.assertEqual(fake.remote["r:backup/outputs/sub/image.png"], b"PNG")
                self.assertEqual(fake.remote["r:backup/subjects/subject-1/subject.json"], b'{"identity": {}}')
                self.assertEqual(len([key for key in fake.remote if key.startswith("r:backup/memory/")]), 1)
                self.assertTrue(all(not key.endswith(".partial") for key in fake.remote))
                self.assertTrue(all(item["backed_up"] for item in manager.resources()["files"]))
                with self.assertRaises(StorageError):
                    manager.start(["../../.env"])


if __name__ == "__main__":
    unittest.main()
