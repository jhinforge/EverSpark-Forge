"""Image reconnect uses the same verification boundary as Concept."""
import json
import tempfile
import time
import unittest
from pathlib import Path
from Tests.Archon import test_connection_verification as concept
from Archon.Steward.DeploymentManager.image import ImageDeploymentManager


class ImageReconnectionTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name)/"image.json"
        self.path.write_text(json.dumps({"99": {"status": "ready", "runtime_id": "a"*32}}))
        self.bridge = concept.Bridge()
        self.manager = ImageDeploymentManager(concept.Machines(), self.bridge, self.path)

    def poll(self):
        self.manager.reconcile_machine({"id": 99, "actual_status": "running"})

    def settle(self):
        deadline = time.monotonic()+3
        while time.monotonic() < deadline:
            with self.manager.lock, self.manager.connection_verification.lock:
                if not self.manager.connection_verification.pending and not any(j["status"] == "running" for j in self.manager.jobs.values()):
                    return
            time.sleep(.01)
        self.fail("verification did not finish")

    def test_host_restart_and_new_runtime_verify_without_deploying(self):
        self.assertEqual(self.manager.status(99)["status"], "verification_required")
        self.poll(); self.settle()
        self.assertEqual(self.manager.status(99)["status"], "ready")
        self.bridge.runtime = "b"*32
        self.poll(); self.settle()
        self.assertEqual(self.bridge.calls, ["health", "revision", "health", "revision"])
        self.assertEqual(self.manager.status(99)["runtime_id"], "b"*32)

    def test_same_runtime_network_loss_reverifies_on_reconnect(self):
        self.poll(); self.settle()
        self.bridge.online = False
        self.poll()
        self.assertEqual(self.manager.status(99)["status"], "verification_required")
        self.bridge.online = True
        self.poll(); self.settle()
        self.assertEqual(self.bridge.calls, ["health", "revision", "health", "revision"])

    def test_failure_is_visible_and_does_not_cause_polling_retry_storm(self):
        self.bridge.fail = True
        self.poll(); self.settle()
        for _ in range(5): self.poll()
        self.assertEqual(self.bridge.calls, ["health"])
        self.assertIn("health failed", self.manager.status(99)["detail"])
        self.bridge.fail = False
        self.manager.start(99, "verify"); self.settle()
        self.assertEqual(self.manager.status(99)["status"], "ready")

    def test_running_job_survives_host_restart_as_unknown(self):
        path = self.path.with_name("image.jobs.json")
        path.write_text(json.dumps({"f"*32: {"id": "f"*32, "instance_id": 99, "action": "deploy-image", "status": "running", "stage": "deploy"}}))
        restored = ImageDeploymentManager(concept.Machines(), self.bridge, self.path)
        job = restored.job("f"*32)
        self.assertEqual(job["stage"], "archon_restart")
        self.assertIn("outcome unknown", job["detail"])
