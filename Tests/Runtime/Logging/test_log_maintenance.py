from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path


TEST_DIR = Path(__file__).resolve().parent
REPO_ROOT = TEST_DIR.parents[2]
LOGGING_DIR = REPO_ROOT / "Runtime" / "Logging"
import sys

sys.path.insert(0, str(LOGGING_DIR))

from log_maintenance import initialize_log_directories, maintain_logs  # noqa: E402
from log_manifest import ManifestError, collect_log_status, load_manifest  # noqa: E402


def write_manifest(path: Path) -> None:
    path.write_text(
        json.dumps(
            {
                "version": 1,
                "defaults": {
                    "max_bytes": 10,
                    "keep_files": 2,
                    "max_age_days": 2,
                },
                "logs": [
                    {
                        "id": "test",
                        "label": "Test",
                        "filename": "test.log",
                        "kind": "structured",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )


class ManifestTests(unittest.TestCase):
    def test_bundled_manifest_is_valid(self) -> None:
        manifest = load_manifest(LOGGING_DIR / "log_manifest.json")
        self.assertEqual(len(manifest["logs"]), 23)
        self.assertIn("concept/conceptforge.log", [item["filename"] for item in manifest["logs"]])

    def test_rejects_path_traversal(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            manifest = Path(directory) / "manifest.json"
            write_manifest(manifest)
            payload = json.loads(manifest.read_text())
            payload["logs"][0]["filename"] = "../secret"
            manifest.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaises(ManifestError):
                load_manifest(manifest)

    def test_status_reports_only_manifest_entries(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = root / "manifest.json"
            logs = root / "logs"
            logs.mkdir()
            write_manifest(manifest)
            (logs / "test.log").write_text("hello", encoding="utf-8")
            (logs / "unmanaged.log").write_text("ignored", encoding="utf-8")
            status = collect_log_status(manifest, logs, environ={})
            self.assertEqual(status["configured"], 1)
            self.assertEqual(status["present"], 1)
            self.assertEqual(status["logs"][0]["filename"], "test.log")

    def test_nested_log_directories_are_created_and_reported(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = root / "manifest.json"
            write_manifest(manifest)
            data = json.loads(manifest.read_text())
            data["logs"][0]["filename"] = "concept/test.log"
            manifest.write_text(json.dumps(data), encoding="utf-8")
            logs = root / "logs"
            initialize_log_directories(manifest, logs)
            (logs / "concept/test.log").write_text("0123456789ABCDEF")
            self.assertEqual(collect_log_status(manifest, logs, environ={})["present"], 1)
            maintain_logs(manifest, logs, environ={})
            self.assertEqual((logs / "concept/test.log.1").read_text(), "0123456789ABCDEF")

    def test_nested_symlink_parent_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = root / "manifest.json"
            write_manifest(manifest)
            data = json.loads(manifest.read_text())
            data["logs"][0]["filename"] = "concept/test.log"
            manifest.write_text(json.dumps(data), encoding="utf-8")
            logs = root / "logs"
            logs.mkdir()
            (logs / "concept").symlink_to(root, target_is_directory=True)
            with self.assertRaises(ManifestError):
                initialize_log_directories(manifest, logs)
            self.assertFalse(collect_log_status(manifest, logs, environ={})["logs"][0]["safe"])


class MaintenanceTests(unittest.TestCase):
    def test_copytruncate_rotation_and_retention(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = root / "manifest.json"
            logs = root / "logs"
            logs.mkdir()
            write_manifest(manifest)
            current = logs / "test.log"
            current.write_text("0123456789ABCDEF", encoding="utf-8")
            inode = current.stat().st_ino

            result = maintain_logs(manifest, logs, environ={})

            self.assertTrue(result["ok"])
            self.assertEqual(current.stat().st_ino, inode)
            self.assertEqual(current.read_text(encoding="utf-8"), "")
            self.assertEqual(
                (logs / "test.log.1").read_text(encoding="utf-8"),
                "0123456789ABCDEF",
            )
            self.assertTrue(
                any(action["action"] == "copytruncate" for action in result["actions"])
            )

    def test_dry_run_does_not_modify_logs(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = root / "manifest.json"
            logs = root / "logs"
            logs.mkdir()
            write_manifest(manifest)
            current = logs / "test.log"
            current.write_text("0123456789ABCDEF", encoding="utf-8")

            result = maintain_logs(manifest, logs, dry_run=True, environ={})

            self.assertTrue(result["dry_run"])
            self.assertEqual(current.read_text(encoding="utf-8"), "0123456789ABCDEF")
            self.assertFalse((logs / "test.log.1").exists())
            self.assertFalse((logs / ".maintenance.lock").exists())

    def test_expired_rotation_is_removed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = root / "manifest.json"
            logs = root / "logs"
            logs.mkdir()
            write_manifest(manifest)
            backup = logs / "test.log.1"
            backup.write_text("old", encoding="utf-8")
            os.utime(backup, (100, 100))

            result = maintain_logs(
                manifest,
                logs,
                now=100 + 3 * 86400,
                environ={},
            )

            self.assertFalse(backup.exists())
            self.assertTrue(
                any(action["reason"] == "exceeds_max_age" for action in result["actions"])
            )

    def test_symlink_is_never_rotated_or_truncated(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = root / "manifest.json"
            logs = root / "logs"
            logs.mkdir()
            write_manifest(manifest)
            target = root / "private.txt"
            target.write_text("must remain intact", encoding="utf-8")
            (logs / "test.log").symlink_to(target)

            result = maintain_logs(manifest, logs, environ={})
            status = collect_log_status(manifest, logs, environ={})

            self.assertEqual(target.read_text(encoding="utf-8"), "must remain intact")
            self.assertTrue(
                any(action["reason"] == "unsafe_file_type" for action in result["actions"])
            )
            self.assertFalse(status["logs"][0]["safe"])
            self.assertFalse(status["logs"][0]["exists"])


if __name__ == "__main__":
    unittest.main()
