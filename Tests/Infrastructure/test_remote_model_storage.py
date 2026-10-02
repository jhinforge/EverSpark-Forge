"""Transfers use node disks and retain their node identity across rebinding."""
import json
import os
import signal
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
from http.server import ThreadingHTTPServer
from Archon.Vault.runtime_config import load_config
from Aegis.Storage.service import StorageService
from Aegis.Storage.remote_models import RemoteModels
from Legate.Warden import model_storage as worker
from Legate.Envoy.forge_tasks import command
from test_direct_downloads import FakeOpener
from test_r2_storage import TreeRclone
from download_manager import DownloadError


class RemoteModelTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.config = load_config()
        self.config["remote_nodes"] = {"remote_only": True, "image_node_id": "a" * 32,
            "concept_node_id": "b" * 32, "control_url": "http://127.0.0.1:8765"}

    def test_all_resource_types_route_and_old_jobs_survive_runtime_replacement(self):
        service = StorageService(self.config)
        with patch.object(service.downloads, "start", side_effect=AssertionError("host download")), \
                patch.object(service.remote, "call", return_value={"job_id": "c" * 32, "status": "queued"}) as call:
            for kind in ("checkpoint", "diffusion_model", "lora", "vae", "concept_model"):
                job = service.start_download(kind, "https://models.example/model")
                forge = "concept" if kind == "concept_model" else "image"
                node = "b" * 32 if forge == "concept" else "a" * 32
                self.assertEqual(call.call_args.args[:3], (node, forge, "models_download_start"))
                self.assertEqual(job["target_node_id"], node)
        self.config["remote_nodes"]["image_node_id"] = "d" * 32
        replacement = StorageService(self.config)
        old_id = "a" * 32 + ":image:" + "c" * 32
        with patch.object(replacement.remote, "call", return_value={"job_id": "c" * 32, "kind": "checkpoint"}) as call:
            for method in (replacement.download_job, replacement.cancel_download, replacement.retry_download):
                method(old_id)
                self.assertEqual(call.call_args.args[:2], ("a" * 32, "image"))
        del self.config["remote_nodes"]["concept_node_id"]
        with self.assertRaisesRegex(DownloadError, "Select a Concept"):
            StorageService(self.config).start_download("concept_model", "https://models.example/model")

    def test_cloud_credentials_are_sent_to_target_without_host_paths_and_inventory_is_node_scoped(self):
        config_file = self.root / "host-private/rclone.conf"
        config_file.parent.mkdir()
        config_file.write_text("[cloud]\ntype = s3\nsecret_access_key = private-fixture\n")
        self.config["storage"] = {"backend": "rclone", "rclone": {"config_file": str(config_file),
            "image_remote": "cloud:images", "concept_remote": "cloud:concept",
            "binary": r"C:\rclone\rclone.exe"}}
        service = StorageService(self.config)
        with patch.object(service.remote, "call", return_value={"job_id": "c" * 32}) as call:
            result = service.start_storage_pull("lora", "cloud:images/loras::girl.safetensors")
            self.assertEqual(call.call_args.args[:3], ("a" * 32, "image", "models_pull_start"))
            cloud = call.call_args.args[3]["cloud"]
            self.assertNotIn("config_file", cloud["storage"]["rclone"])
            self.assertNotIn("binary", cloud["storage"]["rclone"])
            self.assertNotIn("private-fixture", json.dumps(result))
        catalog = {"image": {"checkpoint": [{"name": "same.safetensors", "installed": True}]},
                   "concept": {"models": [{"name": "llm", "format": "ollama", "installed": False}]}}
        with patch.object(service.remote, "call", side_effect=[[False], [True]]):
            annotated = service.remote.annotate(catalog)
        self.assertFalse(annotated["image"]["checkpoint"][0]["installed"])
        self.assertTrue(annotated["concept"]["models"][0]["installed"])
        self.assertTrue(catalog["image"]["checkpoint"][0]["installed"])

    def make_worker(self):
        config = load_config()
        with patch("download_manager.REPO_ROOT", self.root), patch("r2_manager.REPO_ROOT", self.root):
            return worker.ModelStorage(config)

    def wait(self, models, action, job_id, forge):
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            job = models.dispatch(action, {"job_id": job_id}, forge)
            if job["status"] not in {"queued", "downloading", "registering", "running"}:
                return job
            time.sleep(.01)
        self.fail("Transfer did not finish")

    def test_node_download_installs_bytes_and_gguf_registration_uses_node_ollama(self):
        models = self.make_worker()
        for kind, filename in (("checkpoint", "model.safetensors"), ("lora", "girl.safetensors"), ("vae", "vae.safetensors")):
            models.downloads._open_url = FakeOpener(b"model-bytes", filename)
            job = models.dispatch("models_download_start", {"kind": kind, "url": "https://models.example/file"}, "image")
            self.assertEqual(self.wait(models, "models_download_job", job["job_id"], "image")["status"], "completed")
        self.assertEqual((self.root / "Data/Models/ImageForge/loras/girl.safetensors").read_bytes(), b"model-bytes")
        models.downloads._open_url = FakeOpener(b"GGUF-model", "llm.gguf")
        models.downloads._run = Mock(return_value=subprocess.CompletedProcess([], 0, "", ""))
        with patch("download_manager.shutil.which", return_value="/usr/bin/ollama"):
            job = models.dispatch("models_download_start", {"kind": "concept_model", "url": "https://models.example/file",
                "runtime_name": "downloaded-llm"}, "concept")
            done = self.wait(models, "models_download_job", job["job_id"], "concept")
        self.assertEqual(done["status"], "completed", done)
        self.assertEqual(models.downloads._run.call_args.kwargs["env"]["OLLAMA_HOST"], "127.0.0.1:11434")
        self.assertIn(str(self.root), Path(models.downloads._run.call_args.args[0][-1]).read_text())
        with self.assertRaises(ValueError):
            models.dispatch("models_download_job", {"job_id": job["job_id"]}, "image")

    def test_cloud_pull_writes_node_disk_and_keeps_credentials_in_private_snapshot(self):
        models = self.make_worker()
        files = {"cloud:images/loras/girl.safetensors": b"cloud-model"}
        real_manager = worker.R2StorageManager
        def manager(config):
            with patch("r2_manager.REPO_ROOT", self.root):
                result = real_manager(config, run=TreeRclone(files))
            return result
        cloud = {"storage": {"backend": "rclone", "rclone": {"enabled": True,
            "image_remote": "cloud:images", "concept_remote": "cloud:concept"}},
            "rclone_config": "[cloud]\ntype = s3\nsecret_access_key = private-fixture\n", "paths": {}}
        with patch.object(worker, "STATE", self.root / "service"), patch.object(worker, "R2StorageManager", side_effect=manager), \
                patch("r2_manager.shutil.which", return_value="/usr/bin/rclone"):
            job = models.dispatch("models_pull_start", {"kind": "lora", "name": "girl.safetensors", "cloud": cloud}, "image")
            done = self.wait(models, "models_pull_job", job["job_id"], "image")
        self.assertEqual(done["status"], "completed", done)
        self.assertEqual((self.root / "Data/Models/ImageForge/loras/girl.safetensors").read_bytes(), b"cloud-model")
        config_file = next((self.root / "service").rglob("rclone.conf"))
        self.assertEqual(config_file.stat().st_mode & 0o777, 0o600)
        self.assertNotIn("private-fixture", json.dumps(done))

    def test_storage_http_uses_private_token_and_background_jobs_outlive_the_request(self):
        models = self.make_worker()
        models.downloads._open_url = FakeOpener(b"http-model", "http.safetensors")
        server = ThreadingHTTPServer(("127.0.0.1", 0), worker.Handler)
        server.models, server.token = models, "test-token"
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            endpoint = {"port": server.server_port, "token": server.token}
            job = worker.call_endpoint(endpoint, "models_download_start", {"kind": "checkpoint", "url": "https://models.example/file"}, "image")
            done = self.wait(models, "models_download_job", job["job_id"], "image")
            self.assertEqual(done["status"], "completed")
            with self.assertRaises(Exception):
                worker.call_endpoint({**endpoint, "token": "wrong"}, "models_installed", {"entries": []}, "image")
        finally:
            server.shutdown()
            server.server_close()
            thread.join()

    def test_envoy_only_allows_model_actions_with_bounded_objects(self):
        self.assertIsNotNone(command("image", "models_download_start", '{"kind":"checkpoint"}'))
        self.assertIsNone(command("audio", "models_download_start", "{}"))
        self.assertIsNone(command("image", "models_shell", "{}"))
        self.assertIsNone(command("image", "models_download_start", "[]"))

    def test_short_lived_envoy_commands_reuse_one_node_storage_process(self):
        state = self.root / "daemon"
        environment = {**os.environ, "EVERSPARK_MODEL_STORAGE_STATE": str(state)}
        args = [sys.executable, worker.__file__, "image", "models_installed", '{"entries":[]}']
        pid = None
        try:
            first = subprocess.run(args, env=environment, capture_output=True, text=True, timeout=15)
            self.assertEqual(first.returncode, 0, first.stderr)
            self.assertEqual(json.loads(first.stdout), [])
            endpoint = json.loads((state / "endpoint.json").read_text())
            pid = endpoint["pid"]
            second = subprocess.run(args, env=environment, capture_output=True, text=True, timeout=15)
            self.assertEqual(second.returncode, 0, second.stderr)
            self.assertEqual(json.loads(second.stdout), [])
            self.assertEqual(json.loads((state / "endpoint.json").read_text())["pid"], pid)
            self.assertEqual((state / "endpoint.json").stat().st_mode & 0o777, 0o600)
        finally:
            if pid:
                os.kill(pid, signal.SIGTERM)
