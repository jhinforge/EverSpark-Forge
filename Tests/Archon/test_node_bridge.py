from __future__ import annotations

import json
import tempfile
import threading
import time
import unittest
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from Archon.Steward.DeploymentManager.manager import DeploymentManager
from Archon.Steward.NodeManager.bridge import NodeBridge
from Archon.Steward.vast_instances import VastError
from Legate.Envoy.node_agent import execute


class Machine:
    def one(self, instance_id):
        return {"id": instance_id, "actual_status": "running", "ssh_host": None,
                "ssh_port": None}


class Identity:
    def public_key(self):
        raise AssertionError("Agent deployment must not attach an SSH key")


def post(url, path, body):
    request = Request(url + path, data=json.dumps(body).encode("utf-8"),
                      headers={"Content-Type": "application/json"})
    with urlopen(request, timeout=20) as response:
        return json.load(response)


class NodeBridgeTests(unittest.TestCase):
    def test_agent_rejects_unknown_action_without_shell(self):
        self.assertEqual(execute("shell", "rm -rf /"),
                         {"status": "failed", "output": "Unknown Node Agent task",
                          "exit_code": 2})

    def test_agent_registers_and_executes_deployment_without_ssh(self):
        bridge = NodeBridge("127.0.0.1", 0)
        bridge.auth_key = "one-off-test-key"
        bridge.start()
        try:
            bootstrap = bridge.reserve()
            bridge.bind(bootstrap, 99)
            self.assertIsNone(bridge.auth_key)
            with self.assertRaises(HTTPError) as wrong_id:
                post(bridge.url, "/node/register", {"instance_id": 100,
                                                     "bootstrap": bootstrap})
            self.assertEqual(wrong_id.exception.code, 403)
            session = post(bridge.url, "/node/register", {"instance_id": 99,
                                                           "bootstrap": bootstrap})["session"]
            with self.assertRaises(HTTPError) as replay:
                post(bridge.url, "/node/register", {"instance_id": 99,
                                                     "bootstrap": bootstrap})
            self.assertEqual(replay.exception.code, 403)
            with self.assertRaises(HTTPError) as wrong_session:
                post(bridge.url, "/node/next", {"instance_id": 99, "session": "bad"})
            self.assertEqual(wrong_session.exception.code, 403)

            with tempfile.TemporaryDirectory() as directory:
                manager = DeploymentManager(Machine(), Identity(), bridge=bridge,
                    run=lambda *_args, **_kw: self.fail("SSH must not be called"),
                    state_path=Path(directory) / "state.json",
                    log_path=Path(directory) / "deployment.log")
                job = manager.start(99, "deploy")
                seen = []

                def agent():
                    for _ in range(2):
                        task = post(bridge.url, "/node/next", {"instance_id": 99,
                                                                 "session": session})
                        seen.append(task["action"])
                        post(bridge.url, "/node/result", {"instance_id": 99,
                            "session": session, "task_id": task["id"], "result": {
                                "status": "completed", "output": "abc123" if
                                task["action"] == "revision" else "ready", "exit_code": 0}})

                worker = threading.Thread(target=agent)
                worker.start()
                worker.join(3)
                self.assertFalse(worker.is_alive())
                for _ in range(100):
                    result = manager.job(job["id"])
                    if result["status"] != "running":
                        break
                    time.sleep(.01)
                self.assertEqual(result["status"], "completed")
                self.assertEqual(result["revision"], "abc123")
                self.assertEqual(seen, ["deploy", "revision"])
                self.assertEqual(manager.status(99)["status"], "ready")
                self.assertEqual(bridge.status(99), {"status": "online"})
                self.assertIn('"event": "agent_exit"',
                              (Path(directory) / "deployment.log").read_text())
        finally:
            bridge.close()


if __name__ == "__main__":
    unittest.main()
