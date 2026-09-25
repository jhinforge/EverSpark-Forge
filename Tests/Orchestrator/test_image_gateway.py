from __future__ import annotations

import sys
import tempfile
import threading
import time
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "ImageForge"))
from image_forge.gateway import ImageGateway  # noqa: E402
from image_forge.adapters import PluginManifest, discover_plugins  # noqa: E402
from image_forge.plugins import PluginManager  # noqa: E402
from image_forge.port import ImageRequest  # noqa: E402
from image_forge.adapters.diffusers import DiffusersAdapter  # noqa: E402
from image_forge.adapters.comfyui import ComfyUIAdapter  # noqa: E402
from image_forge import diffusers_worker  # noqa: E402
from image_forge.workflow.manager import WorkflowManager  # noqa: E402


class FakeEngine:
    name = "comfyui"

    def __init__(self):
        self.received = None
        self.status = "running"

    def health(self):
        return False

    def submit(self, request, notify=None):
        self.received = request
        return "backend-job", {"workflow": "demo", "checkpoint": "test.safetensors",
                               "vae": "", "loras": []}

    def poll(self, job_id):
        assert job_id == "backend-job"
        return {"status": self.status, "images": (
            [{"filename": "sample.png", "subfolder": "", "type": "output"}]
            if self.status == "completed" else [])}


class ImageGatewayTests(unittest.TestCase):
    def test_registered_engines_route_by_task_and_keep_saved_default(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            outputs = root / "outputs"
            outputs.mkdir()
            comfy = FakeEngine()
            diffusers = FakeEngine()
            diffusers.name = "diffusers"
            gateway = ImageGateway({"comfyui": comfy, "diffusers": diffusers},
                                   str(root / "memory.db"), outputs)
            first, _ = gateway.submit(ImageRequest("one", "", 1), engine="comfyui")
            second, _ = gateway.submit(ImageRequest("two", "", 2), engine="diffusers")
            self.assertEqual(comfy.received.positive_prompt, "one")
            self.assertEqual(diffusers.received.positive_prompt, "two")
            gateway.set_default("diffusers")
            restored = ImageGateway({"comfyui": comfy, "diffusers": diffusers},
                                    str(root / "memory.db"), outputs)
            self.assertEqual(restored.default(), "diffusers")
            self.assertEqual(restored.result(first)["status"], "running")
            self.assertEqual(restored.result(second)["status"], "running")

    def test_plugin_manifests_and_background_job_are_discoverable(self):
        manifests = discover_plugins()
        self.assertEqual(set(manifests), {"comfyui", "diffusers"})
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "outputs").mkdir()
            gateway = ImageGateway({"comfyui": FakeEngine()}, str(root / "memory.db"),
                                   root / "outputs")
            manager = PluginManager({"comfyui": PluginManifest(
                "comfyui", "ComfyUI", "image_forge.adapters.comfyui", "ComfyUIAdapter",
                "image", "missing", "install.sh")}, gateway, root)
            with patch("image_forge.plugins.subprocess.run", side_effect=OSError("install unavailable")):
                started = manager.start("comfyui", "install")
                for _ in range(100):
                    job = manager.job(started["id"])
                    if job["status"] != "running":
                        break
                    time.sleep(0.01)
            self.assertEqual(job["status"], "failed")
            self.assertIn("install unavailable", job["error"])

    def test_existing_worker_is_stopped_before_dependency_repair(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "outputs").mkdir()
            class Worker(FakeEngine):
                name = "diffusers"
                online = True

                def health(self):
                    return self.online

            worker = Worker()
            gateway = ImageGateway(worker, str(root / "memory.db"), root / "outputs")
            manifest = PluginManifest("diffusers", "Diffusers", "image_forge.adapters.diffusers",
                                      "DiffusersAdapter", "diffusers", "Data/Runtime/Diffusers/peft-ready",
                                      "Runtime/Managed/install_diffusers.sh")
            manager = PluginManager({"diffusers": manifest}, gateway, root)
            self.assertFalse(manager.plugins()["plugins"][0]["installed"])
            actions = []

            def run(command, **_kwargs):
                actions.append(command)
                if "stop" in command:
                    worker.online = False
                if command[0] == "bash":
                    marker = root / manifest.runtime_marker
                    marker.parent.mkdir(parents=True)
                    marker.write_text("peft-ready")

            with patch("image_forge.plugins.subprocess.run", side_effect=run):
                started = manager.start("diffusers", "install")
                for _ in range(100):
                    result = manager.job(started["id"])
                    if result["status"] != "running":
                        break
                    time.sleep(0.01)
            self.assertEqual(result["status"], "completed")
            self.assertEqual(["stop" if "stop" in args else "install" if args[0] == "bash"
                              else "start" for args in actions], ["stop", "install", "start"])

    def test_comfyui_adapter_translates_shared_request_into_workflow(self):
        config = {"directory": str(ROOT / "ImageForge/Workflows"),
                  "default_workflow": "base-illustrious",
                  "managed_default_checkpoint": "Illustrious-XL-v1.0.safetensors"}
        adapter = ComfyUIAdapter({"base_url": "http://127.0.0.1:8188"},
                                 WorkflowManager(config))
        captured = []
        with (patch.object(adapter, "list_checkpoints", return_value=["sample.safetensors"]),
              patch.object(adapter, "list_loras", return_value=["style.safetensors"]),
              patch.object(adapter, "queue_prompt", side_effect=lambda graph: (
                  captured.append(graph) or "queued-on-comfyui"))):
            engine_id, selection = adapter.submit(ImageRequest(
                "red hair", "blurry", 123, checkpoint="sample.safetensors",
                loras=[{"name": "style.safetensors"}]))
        self.assertEqual(engine_id, "queued-on-comfyui")
        self.assertEqual(selection["checkpoint"], "sample.safetensors")
        self.assertEqual(captured[0]["34"]["inputs"]["text"], "red hair")
        self.assertEqual(captured[0]["31"]["inputs"]["seed"], 123)
        self.assertEqual(captured[0]["35"]["inputs"]["lora_name"], "style.safetensors")

    def test_jobs_and_images_survive_restart_and_backend_change(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            outputs = root / "outputs"
            outputs.mkdir()
            (outputs / "sample.png").write_bytes(b"image")
            db = str(root / "memory" / "memory.db")
            engine = FakeEngine()
            gateway = ImageGateway(engine, db, outputs)
            job_id, selection = gateway.submit(ImageRequest("portrait", "blurry", 5))
            self.assertEqual(selection["checkpoint"], "test.safetensors")
            self.assertEqual(engine.received.positive_prompt, "portrait")
            self.assertEqual(gateway.result(job_id)["status"], "running")
            engine.status = "completed"
            result = gateway.result(job_id)
            self.assertEqual(result["images"][0]["url"].split("?")[0], "/api/image/view")
            self.assertEqual(gateway.image_path("sample.png").read_bytes(), b"image")
            with self.assertRaises(ValueError):
                gateway.image_path("../private.png")

            replacement = FakeEngine()
            replacement.name = "diffusers"
            restored = ImageGateway(replacement, db, outputs)
            self.assertEqual(restored.result(job_id)["status"], "completed")
            self.assertEqual(restored.history()[0]["filename"], "sample.png")
            (outputs / "old.png").write_bytes(b"old output")
            self.assertIn("old.png", [item["filename"] for item in restored.history()])

    def test_inflight_job_fails_cleanly_after_engine_switch(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            outputs = root / "outputs"
            outputs.mkdir()
            first = ImageGateway(FakeEngine(), str(root / "memory.db"), outputs)
            job_id, _ = first.submit(ImageRequest("portrait", "", 7))
            changed = FakeEngine()
            changed.name = "diffusers"
            second = ImageGateway(changed, str(root / "memory.db"), outputs)
            self.assertEqual(second.result(job_id)["status"], "failed")
            self.assertIn("unavailable", second.result(job_id)["error"])

    def test_diffusers_worker_uses_same_port_without_ml_imports(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            models = root / "models"
            (models / "checkpoints").mkdir(parents=True)
            (models / "checkpoints" / "sample.safetensors").write_bytes(b"fixture")
            outputs = root / "outputs"
            outputs.mkdir()

            def fake_generation(job_id, data):
                self.assertEqual(data["positive_prompt"], "red hair")
                (outputs / "sample.png").write_bytes(b"png fixture")
                diffusers_worker.write_job(job_id, {"status": "completed", "images": [
                    {"filename": "sample.png", "type": "output"}]})
                with diffusers_worker.lock:
                    diffusers_worker.active_jobs.discard(job_id)

            with (patch.object(diffusers_worker, "MODELS", models),
                  patch.object(diffusers_worker, "OUTPUTS", outputs),
                  patch.object(diffusers_worker, "JOBS", root / "jobs"),
                  patch.object(diffusers_worker, "generate", fake_generation)):
                server = ThreadingHTTPServer(("127.0.0.1", 0), diffusers_worker.Handler)
                thread = threading.Thread(target=server.serve_forever, daemon=True)
                thread.start()
                try:
                    adapter = DiffusersAdapter({"base_url": f"http://127.0.0.1:{server.server_port}",
                                                "default_checkpoint": "sample.safetensors"})
                    gateway = ImageGateway(adapter, str(root / "memory.db"), outputs)
                    self.assertTrue(adapter.health())
                    self.assertIn("sample.safetensors", gateway.resources()["checkpoints"])
                    job_id, _ = gateway.submit(ImageRequest("red hair", "bad", 23))
                    for _ in range(100):
                        result = gateway.result(job_id)
                        if result["status"] == "completed":
                            break
                        time.sleep(.01)
                    self.assertEqual(result["status"], "completed")
                    self.assertEqual(gateway.image_path(result["images"][0]["filename"]).read_bytes(), b"png fixture")
                finally:
                    server.shutdown()
                    server.server_close()
                    thread.join(timeout=2)


if __name__ == "__main__":
    unittest.main()
