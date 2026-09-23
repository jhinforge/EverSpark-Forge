from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import time
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch


REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "Infrastructure" / "Storage"))

from r2_manager import R2StorageManager, StorageError  # noqa: E402


class FakeRclone:
    def __init__(self, manifest: dict | None = None):
        self.manifest = manifest or {}
        self.copies: list[tuple[str, str]] = []

    def __call__(self, command, **_kwargs):
        action = command[1]
        source = command[2] if len(command) > 2 else ""
        if action == "lsf":
            if source.endswith("/checkpoints"):
                output = "Hero.SAFETENSORS\n"
            elif source.endswith("/diffusion_models"):
                output = "flux.safetensors\n"
            elif source.endswith("/loras"):
                output = "style.safetensors\n"
            elif source.endswith("/vae"):
                output = "flat.safetensors\nSDXL/illustration.safetensors\n"
            elif source.endswith("/manifests"):
                output = "registry.ollama.ai/library/gemma3test/latest\n"
            else:
                output = ""
            return subprocess.CompletedProcess(command, 0, output, "")
        if action == "cat":
            return subprocess.CompletedProcess(command, 0, json.dumps(self.manifest), "")
        if action == "size":
            return subprocess.CompletedProcess(
                command, 0, json.dumps({"count": 1, "bytes": 11}), ""
            )
        if action == "copyto":
            if "--inplace" in command:
                return subprocess.CompletedProcess(command, 1, "", "unknown flag: --inplace")
            destination = Path(command[3])
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(b"remote-data")
            self.copies.append((source, str(destination)))
            return subprocess.CompletedProcess(command, 0, "", "")
        return subprocess.CompletedProcess(command, 1, "", "unexpected command")


class SlowFakeRclone(FakeRclone):
    def __call__(self, command, **kwargs):
        action = command[1]
        if action == "size":
            return subprocess.CompletedProcess(
                command, 0, json.dumps({"count": 1, "bytes": 12}), ""
            )
        if action == "copyto":
            if "--inplace" in command:
                return subprocess.CompletedProcess(command, 1, "", "unknown flag: --inplace")
            source = command[2]
            destination = Path(command[3])
            destination.parent.mkdir(parents=True, exist_ok=True)
            with destination.open("wb", buffering=0) as handle:
                handle.write(b"remote")
                time.sleep(0.4)
                handle.write(b"-data!")
            self.copies.append((source, str(destination)))
            return subprocess.CompletedProcess(command, 0, "", "")
        return super().__call__(command, **kwargs)


def enabled_config(config_file: Path) -> dict:
    return {
        "storage": {
            "backend": "rclone",
            "rclone": {
                "enabled": True,
                "config_file": str(config_file),
                "image_remote": "r2-assets:comfyui-assets/models_cold",
                "concept_remote": "r2-assets:ollama-forge/.ollama/models",
            },
        }
    }


class R2StorageTests(unittest.TestCase):
    def make_manager(self, root: Path, fake: FakeRclone) -> R2StorageManager:
        config_file = root / "rclone.conf"
        config_file.write_text("[r2-assets]\ntype = s3\n", encoding="utf-8")
        manager = R2StorageManager(enabled_config(config_file), run=fake)
        manager.settings = replace(
            manager.settings,
            image_root=root / "image",
            concept_root=root / "concept",
        )
        manager.client.settings = manager.settings
        return manager

    @patch("r2_manager.shutil.which", return_value="/usr/bin/rclone")
    def test_scans_flat_image_models_and_ollama_manifests(self, _which) -> None:
        with tempfile.TemporaryDirectory() as directory:
            manager = self.make_manager(Path(directory), FakeRclone())
            resources = manager.resources()
        self.assertTrue(resources["enabled"])
        self.assertEqual(resources["image"]["checkpoint"][0]["name"], "Hero.SAFETENSORS")
        self.assertEqual(resources["concept"]["models"][0]["name"], "gemma3test:latest")

    @patch("r2_manager.shutil.which", return_value="/usr/bin/rclone")
    def test_image_pull_matches_filename_case_insensitively(self, _which) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fake = FakeRclone()
            manager = self.make_manager(root, fake)
            job = manager.start_pull("checkpoint", "hero.safetensors")
            completed = self.wait_for_job(manager, job["job_id"])
            self.assertEqual(completed["status"], "completed")
            self.assertEqual(completed["progress"]["percent"], 100.0)
            self.assertEqual(completed["progress"]["bytes_completed"], 11)
            self.assertEqual(completed["progress"]["bytes_total"], 11)
            self.assertTrue((root / "image/checkpoints/Hero.SAFETENSORS").is_file())

    @patch("r2_manager.shutil.which", return_value="/usr/bin/rclone")
    def test_vae_pull_preserves_remote_subdirectory(self, _which) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fake = FakeRclone()
            manager = self.make_manager(root, fake)
            resources = manager.resources()
            self.assertEqual([item["name"] for item in resources["image"]["vae"]],
                             ["flat.safetensors", "SDXL/illustration.safetensors"])
            started = manager.start_pull("vae", "sdxl/ILLUSTRATION.safetensors")
            job = self.wait_for_job(manager, started["job_id"])
            self.assertEqual(job["status"], "completed")
            self.assertTrue((root / "image/vae/SDXL/illustration.safetensors").is_file())
            self.assertIn("/vae/SDXL/illustration.safetensors", fake.copies[0][0])
            self.assertTrue(manager.resources()["image"]["vae"][1]["installed"])

    @patch("r2_manager.shutil.which", return_value="/usr/bin/rclone")
    def test_concept_pull_copies_blobs_before_manifest(self, _which) -> None:
        digest = "sha256:" + "a" * 64
        manifest = {"config": {"digest": digest}, "layers": [{"digest": digest}]}
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fake = FakeRclone(manifest)
            manager = self.make_manager(root, fake)
            job = manager.start_pull("concept_model", "gemma3test:latest")
            completed = self.wait_for_job(manager, job["job_id"])
            self.assertEqual(completed["status"], "completed")
            self.assertEqual(completed["progress"]["percent"], 100.0)
            self.assertEqual(completed["progress"]["bytes_total"], 22)
            self.assertEqual(len(fake.copies), 2)
            self.assertIn("/blobs/sha256-", fake.copies[0][0])
            self.assertIn("/manifests/", fake.copies[1][0])

    @patch("r2_manager.shutil.which", return_value="/usr/bin/rclone")
    def test_image_pull_reports_live_byte_progress(self, _which) -> None:
        with tempfile.TemporaryDirectory() as directory:
            manager = self.make_manager(Path(directory), SlowFakeRclone())
            started = manager.start_pull("checkpoint", "hero.safetensors")
            observed = None
            for _ in range(100):
                job = manager.job(started["job_id"])
                progress = job["progress"] if job else {}
                if 0 < progress.get("bytes_completed", 0) < 12:
                    observed = progress
                    break
                time.sleep(0.01)
            self.assertIsNotNone(observed)
            self.assertGreater(observed["percent"], 0)
            self.assertLess(observed["percent"], 100)
            completed = self.wait_for_job(manager, started["job_id"])
            self.assertEqual(completed["status"], "completed")

    def test_rejects_unsafe_ollama_digest(self) -> None:
        with self.assertRaises(StorageError):
            R2StorageManager._manifest_digests(
                {"config": {"digest": "../../private-key"}}
            )

    @staticmethod
    def wait_for_job(manager: R2StorageManager, job_id: str) -> dict:
        for _ in range(100):
            job = manager.job(job_id)
            if job and job["status"] in {"completed", "failed"}:
                return job
            time.sleep(0.01)
        raise AssertionError("storage job did not complete")


if __name__ == "__main__":
    unittest.main()
