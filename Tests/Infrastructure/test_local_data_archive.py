from __future__ import annotations

import json
import sqlite3
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "Infrastructure/Storage"))
from local_data_archive import DataArchiveError, LocalDataArchive  # noqa: E402


class LocalDataArchiveTests(unittest.TestCase):
    def test_roundtrip_preserves_characters_and_memory_and_keeps_previous_data(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            database = root / "Data/Memory/everspark.db"
            database.parent.mkdir(parents=True)
            folder = root / "Data/Subjects/hero"
            folder.mkdir(parents=True)
            document = {"subject_id": "hero", "revision": 1, "identity": {"name": "Hero"}}
            (folder / "subject.json").write_text(json.dumps(document))
            (folder / "metadata.json").write_text('{}')
            (folder / "positive_prompt.json").write_text('{"positive_prompt":"portrait"}')
            (folder / "negative_prompt.json").write_text('{"negative_prompt":"blur"}')
            with sqlite3.connect(database) as connection:
                connection.execute("CREATE TABLE subjects (subject_id TEXT, revision INTEGER, document TEXT)")
                connection.execute("INSERT INTO subjects VALUES (?, ?, ?)", ("hero", 1, json.dumps({**document, "metadata": {}})))
                connection.execute("CREATE TABLE subject_prompt_revisions (id INTEGER PRIMARY KEY, subject_id TEXT, document TEXT)")
                connection.execute("INSERT INTO subject_prompt_revisions VALUES (1, ?, ?)", ("hero", json.dumps({"positive_prompt": "portrait", "negative_prompt": "blur"})))
                connection.execute("CREATE TABLE messages (body TEXT)")
                connection.execute("INSERT INTO messages VALUES ('original')")
            manager = LocalDataArchive(database, folder.parent, root)
            archive_id, zip_path = manager.export()
            with zipfile.ZipFile(zip_path) as archive:
                self.assertIn("subjects/hero/subject.json", archive.namelist())
                self.assertIn("memory/everspark.db", archive.namelist())
            manager.imports.mkdir(parents=True)
            import_id = "1" * 32
            manager.import_path(import_id).write_bytes(zip_path.read_bytes())
            (folder / "subject.json").write_text("changed")
            with sqlite3.connect(database) as connection:
                connection.execute("UPDATE messages SET body='newer'")
            result = manager.restore(import_id)
            self.assertTrue(result["restart_required"])
            self.assertEqual(result["subjects"], 1)
            self.assertEqual(json.loads((folder / "subject.json").read_text()), document)
            with sqlite3.connect(database) as connection:
                self.assertEqual(connection.execute("SELECT body FROM messages").fetchone()[0], "original")
            recovery = Path(result["recovery"])
            self.assertEqual((recovery / "Subjects/hero/subject.json").read_text(), "changed")
            with sqlite3.connect(recovery / "everspark.db") as connection:
                self.assertEqual(connection.execute("SELECT body FROM messages").fetchone()[0], "newer")

    def test_rejects_tampering_and_unsafe_paths_before_replacement(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            db = root / "Data/Memory/everspark.db"
            db.parent.mkdir(parents=True)
            db.write_bytes(b"original")
            manager = LocalDataArchive(db, root / "Data/Subjects", root)
            manager.imports.mkdir(parents=True)
            import_id = "2" * 32
            with zipfile.ZipFile(manager.import_path(import_id), "w") as archive:
                archive.writestr("manifest.json", json.dumps({"version": 1, "files": {"memory/everspark.db": {"bytes": 4, "sha256": "0" * 64}}}))
                archive.writestr("memory/everspark.db", b"evil")
            with self.assertRaises(DataArchiveError):
                manager.restore(import_id)
            self.assertEqual(db.read_bytes(), b"original")
            with zipfile.ZipFile(manager.import_path(import_id), "w") as archive:
                archive.writestr("manifest.json", "{}")
                archive.writestr("memory/everspark.db", b"test")
                archive.writestr("../outside.txt", b"evil")
            with self.assertRaises(DataArchiveError):
                manager.restore(import_id)
            self.assertFalse((root / "outside.txt").exists())


if __name__ == "__main__":
    unittest.main()
