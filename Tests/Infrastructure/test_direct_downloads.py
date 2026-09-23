from __future__ import annotations

import io
import subprocess
import sys
import tempfile
import time
import unittest
from dataclasses import replace
from email.message import Message
from pathlib import Path
from unittest.mock import patch


REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "Infrastructure" / "Storage"))

from download_manager import (  # noqa: E402
    DirectDownloadManager,
    DownloadError,
    _validate_public_url,
)


def config() -> dict:
    return {
        "concept_forge": {
            "providers": {
                "ollama": {"base_url": "http://127.0.0.1:11434"}
            }
        }
    }


class FakeResponse:
    def __init__(
        self,
        payload: bytes,
        *,
        filename: str,
        status: int = 200,
        content_range: str = "",
    ):
        self.status = status
        self._source = io.BytesIO(payload)
        self.headers = Message()
        self.headers["Content-Length"] = str(len(payload))
        self.headers["Content-Disposition"] = f'attachment; filename="{filename}"'
        if content_range:
            self.headers["Content-Range"] = content_range

    def read(self, size: int = -1) -> bytes:
        return self._source.read(size)

    def close(self) -> None:
        self._source.close()

    def getcode(self) -> int:
        return self.status


class FakeOpener:
    def __init__(self, payload: bytes, filename: str):
        self.payload = payload
        self.filename = filename
        self.requests: list[dict[str, str]] = []

    def __call__(self, _url: str, headers: dict[str, str], _timeout: int):
        self.requests.append(dict(headers))
        raw_range = headers.get("Range", "")
        offset = int(raw_range.removeprefix("bytes=").removesuffix("-")) if raw_range else 0
        remaining = self.payload[offset:]
        return FakeResponse(
            remaining,
            filename=self.filename,
            status=206 if offset else 200,
            content_range=(
                f"bytes {offset}-{len(self.payload) - 1}/{len(self.payload)}"
                if offset
                else ""
            ),
        )


class DirectDownloadTests(unittest.TestCase):
    def make_manager(
        self,
        root: Path,
        opener: FakeOpener,
        run=subprocess.run,
    ) -> DirectDownloadManager:
        manager = DirectDownloadManager(config(), open_url=opener, run=run)
        manager.settings = replace(
            manager.settings,
            image_root=root / "image",
            concept_root=root / "concept",
            temporary_root=root / "downloads",
            modelfile_root=root / "modelfiles",
        )
        return manager

    def test_downloads_checkpoint_to_managed_directory(self) -> None:
        payload = b"safe-model-data"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manager = self.make_manager(
                root, FakeOpener(payload, "hero.safetensors")
            )
            started = manager.start("checkpoint", "https://models.example/download/1")
            job = self.wait_for_job(manager, started["job_id"])
            target = root / "image/checkpoints/hero.safetensors"
            self.assertEqual(job["status"], "completed")
            self.assertEqual(job["progress"]["percent"], 100.0)
            self.assertEqual(target.read_bytes(), payload)

    def test_vae_download_keeps_explicit_sdxl_subdirectory(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manager = self.make_manager(root, FakeOpener(b"VAE-data", "remote.safetensors"))
            started = manager.start("vae", "https://models.example/download/1",
                                    filename="SDXL/illustration.safetensors")
            job = self.wait_for_job(manager, started["job_id"])
            self.assertEqual(job["status"], "completed")
            self.assertEqual((root / "image/vae/SDXL/illustration.safetensors").read_bytes(), b"VAE-data")
            with self.assertRaises(DownloadError):
                manager.start("vae", "https://models.example/download/2",
                              filename="../outside.safetensors")

    def test_rejects_wrong_extension_without_installing_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manager = self.make_manager(
                root, FakeOpener(b"not-a-model", "archive.zip")
            )
            started = manager.start("checkpoint", "https://models.example/archive")
            job = self.wait_for_job(manager, started["job_id"])
            self.assertEqual(job["status"], "failed")
            self.assertIn("extension", job["error"])
            self.assertFalse((root / "image/checkpoints/archive.zip").exists())

    @patch("download_manager.shutil.which", return_value="/usr/bin/ollama")
    def test_registers_downloaded_gguf_with_ollama(self, _which) -> None:
        calls: list[list[str]] = []

        def fake_run(command, **_kwargs):
            calls.append(command)
            return subprocess.CompletedProcess(command, 0, "", "")

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manager = self.make_manager(
                root, FakeOpener(b"GGUF-data", "Qwen Test.gguf"), run=fake_run
            )
            started = manager.start(
                "concept_model",
                "https://models.example/qwen",
                runtime_name="qwen-test",
            )
            job = self.wait_for_job(manager, started["job_id"])
            self.assertEqual(job["status"], "completed")
            self.assertEqual(job["runtime_name"], "qwen-test")
            self.assertEqual(calls[0][1:3], ["create", "qwen-test"])
            self.assertTrue((root / "concept/Qwen Test.gguf").is_file())

    @patch("download_manager.shutil.which", return_value="/usr/bin/ollama")
    def test_retry_after_registration_failure_reuses_downloaded_gguf(self, _which) -> None:
        attempts = 0

        def flaky_run(command, **_kwargs):
            nonlocal attempts
            attempts += 1
            return subprocess.CompletedProcess(
                command,
                1 if attempts == 1 else 0,
                "",
                "temporary Ollama failure" if attempts == 1 else "",
            )

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            opener = FakeOpener(b"GGUF-data", "model.gguf")
            manager = self.make_manager(root, opener, run=flaky_run)
            started = manager.start(
                "concept_model", "https://models.example/model", runtime_name="model-a"
            )
            failed = self.wait_for_job(manager, started["job_id"])
            self.assertEqual(failed["status"], "failed")
            retried = manager.retry(failed["job_id"])
            completed = self.wait_for_job(manager, retried["job_id"])
            self.assertEqual(completed["status"], "completed")
            self.assertEqual(len(opener.requests), 1)
            self.assertEqual(attempts, 2)

    @patch("download_manager.shutil.which", return_value="/usr/bin/ollama")
    def test_registration_error_shows_only_ollama_error(self, _which) -> None:
        def failed_run(command, **_kwargs):
            return subprocess.CompletedProcess(
                command, 1, "", "\x1b[?25l\x1b[1Ggathering model components ⠋ \x1b[K\r"
                'Error: unsupported tensor "output.weight" size overflows\n',
            )

        with tempfile.TemporaryDirectory() as directory:
            manager = self.make_manager(
                Path(directory), FakeOpener(b"GGUF-data", "model.gguf"), run=failed_run
            )
            started = manager.start("concept_model", "https://models.example/model")
            failed = self.wait_for_job(manager, started["job_id"])
            self.assertEqual(
                failed["error"],
                'Ollama model registration failed: Error: unsupported tensor "output.weight" size overflows',
            )

    def test_rejects_non_gguf_payload(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manager = self.make_manager(root, FakeOpener(b"<html>login</html>", "model.gguf"))
            started = manager.start("concept_model", "https://models.example/model")
            failed = self.wait_for_job(manager, started["job_id"])
            self.assertIn("not a GGUF", failed["error"])
            self.assertFalse((root / "concept/model.gguf").exists())

    def test_rejects_mismatched_resume_range(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            opener = FakeOpener(b"GGUF-model", "model.gguf")
            manager = self.make_manager(root, opener)
            target = root / "concept/model.gguf"
            target.parent.mkdir(parents=True)
            digest = __import__("hashlib").sha256(b"https://models.example/model").hexdigest()[:12]
            (target.parent / f".model.gguf.{digest}.part").write_bytes(b"GGUF")

            def wrong_range(url, headers, timeout):
                response = opener(url, headers, timeout)
                if "Range" in headers:
                    response.headers.replace_header("Content-Range", "bytes 0-5/10")
                return response

            manager._open_url = wrong_range
            started = manager.start("concept_model", "https://models.example/model")
            failed = self.wait_for_job(manager, started["job_id"])
            self.assertIn("invalid resume range", failed["error"])
            self.assertFalse(target.exists())

    def test_rejects_invalid_requests_before_starting_thread(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            manager = self.make_manager(
                Path(directory), FakeOpener(b"data", "model.safetensors")
            )
            with self.assertRaises(DownloadError):
                manager.start("unknown", "https://models.example/model")
            with self.assertRaises(DownloadError):
                manager.start("checkpoint", "file:///tmp/model.safetensors")
            with self.assertRaises(DownloadError):
                manager.start(
                    "concept_model",
                    "https://models.example/model.gguf",
                    runtime_name="bad name",
                )

    @patch(
        "download_manager.socket.getaddrinfo",
        return_value=[(2, 1, 6, "", ("127.0.0.1", 80))],
    )
    def test_public_url_guard_rejects_private_addresses(self, _resolve) -> None:
        with self.assertRaises(DownloadError):
            _validate_public_url("http://internal.example/model.safetensors")

    @staticmethod
    def wait_for_job(manager: DirectDownloadManager, job_id: str) -> dict:
        for _ in range(200):
            job = manager.job(job_id)
            if job and job["status"] in {"completed", "failed", "cancelled"}:
                return job
            time.sleep(0.01)
        raise AssertionError("direct download job did not complete")


if __name__ == "__main__":
    unittest.main()
