"""Verify the existing image runtime through Portal and Gate without deploying."""
import json
import tempfile
import threading
import time
import unittest
from pathlib import Path
from urllib.request import Request, urlopen
from Archon.Gate.control_server import ControlServer
from Archon.Portal.app import Settings, WebUIServer
from Archon.Steward.DeploymentManager.image import ImageDeploymentManager


class ImageVerificationWebUITests(unittest.TestCase):
    def test_verify_image_endpoint_checks_existing_runtime_only(self):
        calls = []
        class Machines:
            def one(self, instance_id):
                return {"id": instance_id, "actual_status": "running"}
        class Bridge:
            def configured(self, instance_id):
                return True
            def execute(self, instance_id, action, **kwargs):
                calls.append((instance_id, action, kwargs["forge"]))
                return "abc123" if action == "revision" else "Image Forge ready"
        with tempfile.TemporaryDirectory() as directory:
            manager = ImageDeploymentManager(Machines(), Bridge(), Path(directory) / "image.json")
            gate = ControlServer(("127.0.0.1", 0), Machines(), image_deployments=manager)
            portal = WebUIServer(Settings(port=0, control_url=f"http://127.0.0.1:{gate.server_port}"))
            workers = []
            try:
                for server in (gate, portal):
                    worker = threading.Thread(target=server.serve_forever, daemon=True)
                    worker.start()
                    workers.append(worker)
                base = f"http://127.0.0.1:{portal.server_port}/api/machines/vast"
                request = Request(base + "/verify-image", data=b'{"instance_id":99}',
                                  headers={"Content-Type": "application/json"})
                with urlopen(request, timeout=3) as response:
                    data = json.load(response)
                self.assertEqual(data["job"]["action"], "verify-image")
                for _ in range(100):
                    with urlopen(base + "/image-deployment-job?id=" + data["job"]["id"], timeout=3) as response:
                        job = json.load(response)["job"]
                    if job["status"] != "running":
                        break
                    time.sleep(.01)
                self.assertEqual(job["status"], "completed")
                self.assertEqual(calls, [(99, "health", "image"), (99, "revision", "image")])
                self.assertEqual(manager.status(99)["status"], "ready")
            finally:
                for server in (portal, gate):
                    server.shutdown()
                    server.server_close()
                for worker in workers:
                    worker.join(3)
