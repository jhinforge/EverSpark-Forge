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

    def test_network_loss_between_inventory_polls_still_reverifies(self):
        status = self.bridge.status
        self.bridge.connection = "first"
        self.bridge.status = lambda instance_id: {**status(instance_id), "connection_id": self.bridge.connection}
        self.poll(); self.settle()
        self.bridge.connection = "reconnected"
        self.poll(); self.settle()
        self.assertEqual(self.bridge.calls, ["health", "revision", "health", "revision"])

    def test_reconnect_during_health_check_requires_another_check(self):
        status = self.bridge.status
        self.bridge.connection = "first"
        self.bridge.status = lambda instance_id: {**status(instance_id), "connection_id": self.bridge.connection}
        self.bridge.release.clear()
        self.poll()
        self.assertTrue(self.bridge.entered.wait(2))
        self.bridge.connection = "reconnected"
        self.poll()
        self.bridge.release.set()
        self.settle()
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

    def restore_task(self, result):
        job_id = "f"*32
        self.path.with_name("image.jobs.json").write_text(json.dumps({job_id: {
            "id": job_id, "instance_id": 99, "action": "deploy-image", "status": "running",
            "stage": "deploy", "task_id": "d"*32, "task_action": "deploy"}}))
        original = self.bridge.execute
        def execute(instance_id, action, message="", **kwargs):
            if action == "recover":
                self.bridge.calls.append(action)
                self.assertEqual(message, "d"*32)
                self.assertEqual(kwargs["forge"], "image")
                return json.dumps(result)
            return original(instance_id, action, message, **kwargs)
        self.bridge.execute = execute
        self.manager = ImageDeploymentManager(concept.Machines(), self.bridge, self.path)
        self.settle()
        return self.manager.job(job_id)

    def test_host_restart_recovers_completed_agent_result_without_reinstalling(self):
        job = self.restore_task({"state": "completed", "status": "completed"})
        self.assertEqual(self.bridge.calls, ["recover", "health", "revision"])
        self.assertEqual(job["status"], "completed")
        self.assertEqual(self.manager.status(99)["status"], "ready")
        saved = json.loads(self.path.with_name("image.jobs.json").read_text())
        self.assertEqual(saved[job["id"]]["task_action"], "revision")

    def test_interrupted_or_missing_result_never_reexecutes_deployment(self):
        for result in ({"state": "not_seen"}, {"state": "running"},
                       {"state": "completed", "status": "failed", "output": "outcome unknown",
                        "stage": "outcome_unknown"}):
            with self.subTest(result=result):
                self.bridge.calls.clear()
                job = self.restore_task(result)
                self.assertEqual(self.bridge.calls, ["recover"])
                self.assertEqual(job["status"], "failed")
                self.assertEqual(self.manager.status(99)["status"], "deployment_unknown")

    def test_recovered_failure_preserves_download_stage_and_exit_code(self):
        job = self.restore_task({"state": "completed", "status": "failed",
            "output": "Model download failed", "exit_code": 7, "stage": "downloading_models"})
        self.assertEqual(job["stage"], "downloading_models")
        self.assertEqual(job["exit_code"], 7)
        self.assertEqual(self.manager.status(99)["status"], "deployment_failed")
        self.assertEqual(self.bridge.calls, ["recover"])

    def test_failed_health_after_recovery_cannot_mark_forge_ready(self):
        self.bridge.fail = True
        job = self.restore_task({"state": "completed", "status": "completed"})
        self.assertEqual(self.bridge.calls, ["recover", "health"])
        self.assertEqual(job["status"], "failed")
        self.assertEqual(self.manager.status(99)["status"], "verification_required")
