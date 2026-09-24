from __future__ import annotations

import sqlite3
import json
import threading
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

    def list_files(self, root, *, recursive=False, max_depth=0):
        return [name.removeprefix(root + "/") for name in self.remote if name.startswith(root + "/")]

    def read_json(self, name):
        return json.loads(self.remote[name])

    def copy_file(self, remote, local, known_size=None, **_kwargs):
        local.parent.mkdir(parents=True, exist_ok=True)
        local.write_bytes(self.remote[remote])

    def run(self, action, *arguments, **_kwargs):
        if action == "copyto":
            self.remote[arguments[1]] = Path(arguments[0]).read_bytes()
        elif action == "moveto":
            self.remote[arguments[1]] = self.remote.pop(arguments[0])
        elif action == "deletefile":
            self.remote.pop(arguments[0], None)


class BackupUploadTests(unittest.TestCase):
    def test_outputs_folder_selection_includes_every_file_at_job_start(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "Data/Outputs"
            (output / "sub").mkdir(parents=True)
            (output / "sub/image.png").write_bytes(b"PNG")
            config = {"storage": {"backend": "rclone", "rclone": {
                "enabled": True, "image_remote": "r:images", "concept_remote": "r:ollama",
                "backup_remote": "r:backup"}}, "memory": {"database": str(root / "memory.db")}}
            with patch("backup_manager.REPO_ROOT", root):
                manager = BackupManager(config)
                manager.client = FakeRclone()
                self.assertEqual([item["name"] for item in manager.resources()["files"]],
                                 ["outputs/sub/image.png"])
                (output / "sub/new.png").write_bytes(b"NEW")
                (output / "metadata.txt").write_bytes(b"META")
                job = manager.start([], outputs=True)
                for _ in range(100):
                    result = manager.job(job["job_id"])
                    if result["status"] in {"completed", "failed"}:
                        break
                    time.sleep(.01)
                self.assertEqual(result["status"], "completed", result["error"])
                self.assertEqual(result["progress"]["total"], 3)
                self.assertEqual(manager.client.remote["r:backup/outputs/sub/new.png"], b"NEW")
                self.assertEqual(manager.client.remote["r:backup/outputs/metadata.txt"], b"META")
                (output / "last.png").write_bytes(b"LAST")
                legacy = manager.start(["outputs/sub/image.png"])
                for _ in range(100):
                    result = manager.job(legacy["job_id"])
                    if result["status"] in {"completed", "failed"}:
                        break
                    time.sleep(.01)
                self.assertEqual(result["status"], "completed", result["error"])
                self.assertEqual(result["progress"]["total"], 4)
                self.assertEqual(manager.client.remote["r:backup/outputs/last.png"], b"LAST")

    def test_union_upload_requires_physical_target_and_does_not_overwrite(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config_file = root / "rclone.conf"
            config_file.write_text("[r2]\ntype = s3\n[models]\ntype = union\n"
                                   "upstreams = r2:bucket/cold:ro r2:bucket/live:ro\n")
            config = {"storage": {"backend": "rclone", "rclone": {
                "enabled": True, "config_file": str(config_file), "image_remote": "models:",
                "concept_remote": "r2:bucket/ollama"}}, "memory": {"database": str(root / "memory.db")}}
            (root / "memory.db").touch()
            image = root / "image/loras/fresh.safetensors"
            image.parent.mkdir(parents=True)
            image.write_bytes(b"fresh")
            with patch("backup_manager.REPO_ROOT", root), patch("backup_manager.shutil.which", return_value="/usr/bin/rclone"):
                manager = BackupManager(config)
                manager.settings = replace(manager.settings, image_root=root / "image")
                manager.client = FakeRclone()
                name = "models/image/loras/fresh.safetensors"
                targets = manager._targets(name)
                self.assertEqual(targets, ["r2:bucket/cold/loras/fresh.safetensors",
                                           "r2:bucket/live/loras/fresh.safetensors"])
                with self.assertRaisesRegex(StorageError, "Choose an upload destination"):
                    manager.start([name])
                with self.assertRaisesRegex(StorageError, "not mapped"):
                    manager.start([name], targets={name: "models:loras/fresh.safetensors"})
                started = manager.start([name], targets={name: targets[0]})
                for _ in range(100):
                    result = manager.job(started["job_id"])
                    if result["status"] in {"completed", "failed"}:
                        break
                    time.sleep(.01)
                self.assertEqual(result["status"], "completed", result["error"])
                self.assertEqual(manager.client.remote[targets[0]], b"fresh")
                image.write_bytes(b"different-size")
                with self.assertRaisesRegex(StorageError, "union remote"):
                    manager.paths.save({"image_upload": {"lora": "models:loras"}})
                started = manager.start([name], targets={name: targets[0]})
                for _ in range(100):
                    result = manager.job(started["job_id"])
                    if result["status"] in {"completed", "failed"}:
                        break
                    time.sleep(.01)
                self.assertEqual(result["status"], "failed")
                self.assertEqual(manager.client.remote[targets[0]], b"fresh")

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
            subject.write_text('{"subject_id":"subject-1","revision":1,"identity":{}}', encoding="utf-8")
            for name in ("metadata", "positive_prompt", "negative_prompt"):
                (subject.parent / f"{name}.json").write_text("{}", encoding="utf-8")
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
                connection.execute("CREATE TABLE subjects (subject_id TEXT, revision INTEGER, document TEXT)")
                connection.execute("INSERT INTO subjects VALUES (?,?,?)", ("subject-1", 1,
                                    json.dumps({**json.loads(subject.read_text()), "metadata": {}})))
                connection.execute("CREATE TABLE subject_prompt_revisions (id INTEGER PRIMARY KEY, subject_id TEXT, document TEXT)")
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
                self.assertEqual(fake.remote["r:backup/everspark-gguf/new.gguf"], b"GGUF-test")
                self.assertEqual(fake.remote["r:backup/outputs/sub/image.png"], b"PNG")
                self.assertEqual(fake.remote[f"r:backup/data_sets/{job['job_id']}/subjects/subject-1/subject.json"], subject.read_bytes())
                self.assertIn(f"r:backup/data_sets/{job['job_id']}/manifest.json", fake.remote)
                self.assertTrue(all(not key.endswith(".partial") for key in fake.remote))
                self.assertTrue(all(item["backed_up"] for item in manager.resources()["files"] if not item["name"].startswith("subjects/")))
                self.assertEqual(manager.restore_points()[0]["subjects"], 1)
                subject.write_text('{"revision":99}', encoding="utf-8")
                with sqlite3.connect(database) as connection:
                    connection.execute("UPDATE message SET value='changed'")
                restore = manager.start_restore(job["job_id"], threading.Lock(), threading.RLock())
                for _ in range(200):
                    restored = manager.job(restore["job_id"])
                    if restored["status"] in {"completed", "failed"}:
                        break
                    time.sleep(.01)
                self.assertEqual(restored["status"], "completed", restored["error"])
                self.assertIn('"revision":1', subject.read_text())
                with sqlite3.connect(database) as connection:
                    self.assertEqual(connection.execute("SELECT value FROM message").fetchone()[0], "saved")
                bad = f"r:backup/data_sets/{job['job_id']}/subjects/subject-1/subject.json"
                fake.remote[bad] = b"changed"  # Same batch can no longer be trusted.
                failed = manager.start_restore(job["job_id"], threading.Lock(), threading.RLock())
                for _ in range(200):
                    stopped = manager.job(failed["job_id"])
                    if stopped["status"] in {"completed", "failed"}:
                        break
                    time.sleep(.01)
                self.assertEqual(stopped["status"], "failed")
                self.assertIn('"revision":1', subject.read_text())
                with self.assertRaises(StorageError):
                    manager.start(["../../.env"])


if __name__ == "__main__":
    unittest.main()
