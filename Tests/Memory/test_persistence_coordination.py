"""Maintenance excludes complete persistence units without Forge dependencies."""
import json
import shutil
import sqlite3
import sys
import tempfile
import threading
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
for relative in ("", "Legate/Forge/ConceptForge/Memory", "Aegis/Storage", "Legate/Forge", "Legate/Forge/ImageForge"):
    sys.path.insert(0, str(ROOT / relative))
from Archon.Ledger.coordination import coordinator_for
from Aegis.Shared.errors import BusyError
from everspark_memory import SQLiteMemoryStore
from local_data_archive import LocalDataArchive
from backup_manager import BackupManager
from Tests.Infrastructure.test_backup_upload import FakeRclone


class PersistenceCoordinationTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.database = self.root / "Data/Memory/everspark.db"
        self.store = SQLiteMemoryStore(str(self.database))
        self.document = json.loads((ROOT / "Legate/Forge/ConceptForge/Examples/character_subject.example.json").read_text())
        self.store.save_subject(self.document)
        self.archive = LocalDataArchive(self.database, self.store.subject_root, self.root)
        self.errors, self.workers = [], []
        self.addCleanup(self.join_workers)

    def spawn(self, work):
        def run():
            try:
                work()
            except BaseException as exc:
                self.errors.append(exc)
        thread = threading.Thread(target=run, daemon=True)
        self.workers.append(thread)
        thread.start()
        return thread

    def join_workers(self):
        for thread in self.workers:
            thread.join(3)
        self.assertFalse(any(thread.is_alive() for thread in self.workers), "deadlocked worker")
        self.assertEqual(self.errors, [])

    def test_coordinator_is_owned_by_dataset_path_and_shared_across_store_instances(self):
        second = SQLiteMemoryStore(str(self.database.parent / "." / self.database.name))
        self.assertIs(second.coordination, self.store.coordination)
        self.assertIs(self.archive.coordination, self.store.coordination)
        self.assertIsNot(coordinator_for(self.root / "other.db"), self.store.coordination)

    def test_nonblocking_maintenance_rejects_active_operation_and_exceptions_release_scopes(self):
        entered, release = threading.Event(), threading.Event()
        self.addCleanup(release.set)
        def write():
            with self.store.operation():
                entered.set()
                self.assertTrue(release.wait(3))
        self.spawn(write)
        self.assertTrue(entered.wait(2))
        with self.assertRaises(BusyError):
            with self.archive.coordination.maintenance(blocking=False):
                self.fail("entered during write")
        release.set()
        self.join_workers()
        with self.assertRaisesRegex(RuntimeError, "failure"):
            with self.store.coordination.maintenance():
                raise RuntimeError("failure")
        self.store.record_conversation("after-failure", "hello", "ok")
        self.assertEqual(len(self.store.get_history("after-failure")), 2)
        with self.store.operation():
            with self.store.operation():
                self.assertIsNotNone(self.store.get_subject(self.document["subject_id"]))
            with self.assertRaises(BusyError):
                with self.archive.coordination.maintenance():
                    self.fail("maintenance nested in normal operation")

    def test_archive_waits_for_file_and_sql_commit_in_one_subject_write(self):
        staged, release, snapshot_started, verified = [threading.Event() for _ in range(4)]
        self.addCleanup(release.set)
        original_write = self.store._write_subject_files
        original_verify = self.archive._verify_database
        updated = {**self.document, "revision": 2}
        result = {}
        def write_files(*args):
            previous = original_write(*args)
            staged.set()
            self.assertTrue(release.wait(3))
            return previous
        def verify(stage):
            verified.set()
            return original_verify(stage)
        def export():
            snapshot_started.set()
            result["archive"] = self.archive.export()
        with patch.object(self.store, "_write_subject_files", side_effect=write_files), \
             patch.object(self.archive, "_verify_database", side_effect=verify):
            self.spawn(lambda: self.store.save_subject(updated))
            self.assertTrue(staged.wait(2))
            self.spawn(export)
            self.assertTrue(snapshot_started.wait(2))
            self.assertFalse(verified.wait(.1))
            release.set()
            self.join_workers()
        with zipfile.ZipFile(result["archive"][1]) as archive:
            saved = json.loads(archive.read(f'subjects/{self.document["subject_id"]}/subject.json'))
            self.assertEqual(saved["revision"], 2)
        self.assertEqual(self.store.get_subject(self.document["subject_id"])["revision"], 2)

    def backup_manager(self):
        config = {"storage": {"backend": "rclone", "rclone": {
            "enabled": True, "image_remote": "r:images", "concept_remote": "r:models",
            "backup_remote": "r:backup"}}, "memory": {"database": str(self.database)}}
        manager = BackupManager(config)
        manager.client = FakeRclone()
        return manager

    def wait_job(self, manager, job):
        # Join the actual asynchronous restore worker through a terminal-state event.
        for _ in range(300):
            status = manager.job(job["job_id"])
            if status["status"] in {"completed", "failed"}:
                return status
            threading.Event().wait(.01)
        self.fail("restore did not finish")

    def exercise_restore(self, start_restore, wait_restore):
        installing, release, reader_started, writer_started, read_done, write_done = [threading.Event() for _ in range(6)]
        self.addCleanup(release.set)
        import os
        original_replace = os.replace
        def replace(source, destination):
            if Path(destination) == self.database and str(source).endswith(".restore"):
                installing.set()
                self.assertTrue(release.wait(3))
            return original_replace(source, destination)
        def read():
            reader_started.set()
            self.store.get_history("during-restore")
            read_done.set()
        def write():
            writer_started.set()
            self.store.record_conversation("during-restore", "new", "record")
            write_done.set()
        with patch("os.replace", side_effect=replace):
            self.spawn(start_restore)
            self.assertTrue(installing.wait(2))
            self.spawn(read)
            self.spawn(write)
            self.assertTrue(reader_started.wait(2))
            self.assertTrue(writer_started.wait(2))
            self.assertFalse(read_done.wait(.1))
            self.assertFalse(write_done.wait(.1))
            release.set()
            self.join_workers()
        wait_restore()
        self.assertTrue(read_done.is_set())
        self.assertTrue(write_done.is_set())
        self.assertEqual(len(self.store.get_history("during-restore")), 2)
        self.assertIsNotNone(self.store.get_subject(self.document["subject_id"]))

    def test_local_restore_excludes_history_reads_and_writes_until_replacement_finishes(self):
        archive_id, path = self.archive.export()
        self.archive.imports.mkdir(parents=True)
        shutil.copy2(path, self.archive.import_path(archive_id))
        self.exercise_restore(lambda: self.archive.restore(archive_id), lambda: None)

    def test_remote_restore_worker_owns_its_maintenance_scope_and_excludes_writes(self):
        manager = self.backup_manager()
        manager._jobs["snapshot"] = {"progress": {"bytes_total": 0, "bytes_completed": 0}}
        manager._upload_data_set("snapshot", "r:backup")
        # Restore identifiers use 32 hexadecimal characters.
        for name, data in list(manager.client.remote.items()):
            manager.client.remote[name.replace("/snapshot/", "/" + "a" * 32 + "/")] = data
        result = {}
        def start():
            result["job"] = manager.start_restore("a" * 32)
        def finish():
            state = self.wait_job(manager, result["job"])
            self.assertEqual(state["status"], "completed", state)
        self.exercise_restore(start, finish)

    def test_remote_snapshot_protects_copy_but_does_not_hold_scope_during_upload(self):
        manager = self.backup_manager()
        self.assertIs(manager.coordination, self.store.coordination)
        manager._jobs["snapshot"] = {"progress": {"bytes_total": 0, "bytes_completed": 0}}
        upload_checked = threading.Event()
        def upload(path, remote, job_id):
            completed = threading.Event()
            self.spawn(lambda: (self.store.record_conversation("upload", "hello", "ok"), completed.set()))
            self.assertTrue(completed.wait(2), "network upload retained maintenance lock")
            upload_checked.set()
        copied, release_copy, writing, written = [threading.Event() for _ in range(4)]
        self.addCleanup(release_copy.set)
        original_copy = shutil.copy2
        def copy(source, destination, *args, **kwargs):
            copied.set()
            self.assertTrue(release_copy.wait(3))
            return original_copy(source, destination, *args, **kwargs)
        def write():
            writing.set()
            self.store.record_conversation("snapshot-copy", "hello", "ok")
            written.set()
        with patch.object(manager, "_upload_file", side_effect=upload), \
             patch("backup_manager.shutil.copy2", side_effect=copy):
            self.spawn(lambda: manager._upload_data_set("snapshot", "r:backup"))
            self.assertTrue(copied.wait(2))
            self.spawn(write)
            self.assertTrue(writing.wait(2))
            self.assertFalse(written.wait(.1), "write overlapped snapshot copy")
            release_copy.set()
            self.join_workers()
        self.assertTrue(upload_checked.is_set())

    def test_failed_restore_rolls_back_before_writers_resume_and_releases_scope(self):
        archive_id, path = self.archive.export()
        self.archive.imports.mkdir(parents=True)
        shutil.copy2(path, self.archive.import_path(archive_id))
        import os
        original_replace = os.replace
        def replace(source, destination):
            if Path(destination) == self.store.subject_root and str(source).endswith(".restore"):
                raise OSError("install failure")
            return original_replace(source, destination)
        with patch("os.replace", side_effect=replace):
            with self.assertRaisesRegex(OSError, "install failure"):
                self.archive.restore(archive_id)
        self.store.record_conversation("after-rollback", "hello", "ok")
        self.assertEqual(len(self.store.get_history("after-rollback")), 2)
        self.assertEqual(self.store.get_subject(self.document["subject_id"]), self.document)

    def test_connection_is_closed_before_operation_scope_is_released(self):
        with self.store._connect() as connection:
            connection.execute("SELECT 1")
        with self.assertRaises(sqlite3.ProgrammingError):
            connection.execute("SELECT 1")

    def test_image_catalog_and_memory_use_one_lock_order_during_generation(self):
        from image_forge.gateway import ImageGateway
        from image_forge.port import ImageRequest
        class Engine:
            name = "test"
            def submit(self, request, notify):
                return "engine-id", {}
        gateway = ImageGateway(Engine(), str(self.database), self.root / "Outputs", "test")
        attempted, finished = threading.Event(), threading.Event()
        def read_catalog():
            attempted.set()
            self.assertEqual(gateway.default(), "test")
            finished.set()
        with self.store.operation():
            self.spawn(read_catalog)
            self.assertTrue(attempted.wait(2))
            self.assertFalse(finished.wait(.1))
            # A concurrent catalog reader must not retain another lock needed by
            # the generation thread which already owns the persistence scope.
            job_id, _ = gateway.submit(ImageRequest("portrait", "bad", 1))
            self.assertTrue(job_id)
        self.assertTrue(finished.wait(2))

    def test_connection_failure_rolls_back_and_allows_maintenance(self):
        with self.assertRaises(sqlite3.OperationalError):
            with self.store._connect() as connection:
                connection.execute("INSERT INTO sessions VALUES ('rollback', 'now', 'now')")
                connection.execute("SELECT * FROM nonexistent_table")
        with self.store.coordination.maintenance():
            with sqlite3.connect(self.database) as connection:
                self.assertIsNone(connection.execute(
                    "SELECT session_id FROM sessions WHERE session_id='rollback'").fetchone())
