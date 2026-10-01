"""Real process supervision and streaming deployment cleanup."""
import os
import json
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch
from Tests.Archon import test_node_registration as protocol
from Archon.Steward.NodeManager import NodeManager
from Legate.Envoy.executor import progress
from Legate.Envoy.executor.process import run_deployment
from Legate.Envoy.executor.tasks import execute
from Archon.Steward.NodeManager.task_progress import validate_progress
from Archon.Steward.NodeManager.errors import NodeError
from Legate.Envoy.process_lock import identity_lock

ROOT = Path(__file__).resolve().parents[2]


class AgentSupervisionTests(unittest.TestCase):
    def test_model_count_survives_streaming_and_heartbeat_validation(self):
        progress.begin("f"*32)
        try:
            done = run_deployment([sys.executable, "-c",
                "print('[EverSpark:deploy] downloading_models 1/2'); print('[EverSpark:deploy] downloading_models 3/2')"], ROOT, 5)
            self.assertEqual(done.returncode, 0)
            value = validate_progress(progress.snapshot())
            self.assertEqual((value["completed"], value["total"]), (1, 2))
            with self.assertRaises(NodeError):
                validate_progress({**value, "completed": True})
            with self.assertRaises(NodeError):
                validate_progress({**value, "total": 0})
        finally:
            progress.finish()

    def test_deployment_timeout_preserves_phase_diagnostics_and_exit_code(self):
        progress.begin("f"*32)
        args = [sys.executable, "-c", "import time; print('[EverSpark:deploy] installing_torch', flush=True); print('waiting for dependency server', flush=True); time.sleep(10)"]
        try:
            with patch("Legate.Envoy.executor.tasks.command", return_value=(args, .5)):
                result = execute("deploy", "", "image")
            self.assertEqual(result["status"], "failed")
            self.assertEqual(result["exit_code"], 124)
            self.assertEqual(result["stage"], "installing_torch")
            self.assertIn("waiting for dependency server", result["output"])
            self.assertIn("timed out", result["output"])
        finally:
            progress.finish()

    def test_identity_directory_has_only_one_live_owner(self):
        with tempfile.TemporaryDirectory() as directory:
            with identity_lock(Path(directory)):
                with self.assertRaises(RuntimeError), identity_lock(Path(directory)):
                    pass
            with identity_lock(Path(directory)):
                pass

    def test_phase_is_visible_before_command_finishes_and_errors_are_bounded(self):
        result = {}
        progress.begin("f"*32)
        def run():
            result["command"] = run_deployment([sys.executable, "-c",
                "import time; print('[EverSpark:deploy] downloading_models', flush=True); time.sleep(.5); print('x'*20000); print('download failed'); raise SystemExit(7)"], ROOT, 5)
        worker = threading.Thread(target=run)
        worker.start()
        try:
            protocol.wait_for(lambda: progress.snapshot()["stage"] == "downloading_models", 3)
            self.assertTrue(worker.is_alive())
            worker.join(5)
            self.assertEqual(result["command"].returncode, 7)
            self.assertTrue(result["command"].stdout.endswith("download failed\n"))
            self.assertLessEqual(len(result["command"].stdout), 4000)
        finally:
            worker.join(5)
            progress.finish()

    @unittest.skipUnless(sys.platform.startswith("linux"), "Linux process supervision")
    def test_supervisor_recovers_killed_agent_and_explicit_stop_expires_lease(self):
        with tempfile.TemporaryDirectory() as directory:
            manager = NodeManager("127.0.0.1", 0, heartbeat_interval=.1, lease_timeout=.7)
            manager.start()
            env = {k:v for k,v in os.environ.items() if not k.startswith("EVERSPARK_NODE_")}
            env.update(EVERSPARK_NODE_URL=manager.url, EVERSPARK_NODE_JOIN_TOKEN=manager.issue_join_token(),
                EVERSPARK_NODE_DATA_DIR=directory, EVERSPARK_TASK_JOURNAL=directory+"/journal.json")
            supervisor = subprocess.Popen([sys.executable, "-m", "Legate.Envoy.supervisor"], cwd=ROOT, env=env,
                                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            try:
                protocol.wait_for(lambda: len(manager.registry.nodes) == 1)
                node_id = manager.list_nodes()[0]["node_id"]
                runtime = manager.runtime_id(node_id)
                status = Path(directory)/"supervisor.json"
                protocol.wait_for(status.exists, 2)
                os.kill(json.loads(status.read_text())["agent_pid"], 9)
                protocol.wait_for(lambda: manager.runtime_id(node_id) != runtime and manager.status(node_id)["status"] == "online", 8)
                self.assertEqual(len(manager.registry.nodes), 1)
                self.assertTrue(manager.execute(node_id, "revision", timeout=5, forge="image").strip())
                supervisor.terminate(); supervisor.wait(timeout=5)
                protocol.wait_for(lambda: manager.status(node_id)["status"] == "offline", 3)
            finally:
                if supervisor.poll() is None:
                    supervisor.terminate(); supervisor.wait(timeout=5)
                manager.close()

    @unittest.skipUnless(sys.platform.startswith("linux"), "Linux command group cleanup")
    def test_deployment_stops_when_owning_agent_disappears(self):
        with tempfile.TemporaryDirectory() as directory:
            marker = Path(directory)/"finished"
            started = Path(directory)/"started"
            command = f"import pathlib,time; pathlib.Path({str(started)!r}).touch(); time.sleep(1.5); pathlib.Path({str(marker)!r}).touch()"
            owner_script = f"from Legate.Envoy.executor.process import run_deployment; import sys; run_deployment([sys.executable,'-c',{command!r}], {str(ROOT)!r}, 10)"
            owner = subprocess.Popen([sys.executable, "-c", owner_script], cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            try:
                protocol.wait_for(started.exists, 3)
                owner.kill(); owner.wait(timeout=3)
                time.sleep(1.7)
                self.assertFalse(marker.exists())
            finally:
                if owner.poll() is None:
                    owner.kill(); owner.wait(timeout=3)
