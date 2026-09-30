from __future__ import annotations

import json
import base64
import os
import subprocess
import tempfile
import threading
import time
import unittest
import sys
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from Archon.Steward.DeploymentManager.manager import DeploymentManager
from Archon.Steward.DeploymentManager.image import ImageDeploymentManager
from Archon.Gate.control_server import ControlServer
from Archon.Steward.NodeManager import NodeManager
from Archon.Steward.NodeManager.errors import NodeError
from Archon.Steward.DeploymentManager.providers.vast_nodes import VastNodes
from Archon.Steward.DeploymentManager.providers.network import tailscale_ip
from Archon.Steward.vast_instances import VastError
from Archon.Vault.windows_credentials import CredentialError
from Legate.Envoy.agent import startup_status
from Legate.Envoy.executor.tasks import execute
from Legate.Envoy.executor.journal import execute_once
from Legate.Envoy.forge_tasks import command as forge_command

ROOT = Path(__file__).resolve().parents[2]
for module_path in ("Archon/Orchestrator", "Legate/Forge", "Legate/Forge/ConceptForge",
                    "Legate/Forge/ImageForge", "Legate/Forge/ConceptForge/Memory",
                    "Aegis/Logging"):
    sys.path.insert(0, str(ROOT / module_path))

from orchestrator.config.config import load_config
from orchestrator.core.orchestrator import Orchestrator
from orchestrator.core.remote_image import RemoteImageGateway
from image_forge.port import ImageRequest
from concept_forge.subjects import new_subject
from Legate.Forge.ImageForge import remote_task


class Machine:
    def one(self, instance_id):
        return {"id": instance_id, "actual_status": "running", "ssh_host": None,
                "ssh_port": None}


class Identity:
    def public_key(self):
        raise AssertionError("Agent deployment must not attach an SSH key")


class Credentials:
    values = {}
    fail_targets = set()

    def __init__(self, target):
        self.target = target

    def get(self):
        return self.values.get(self.target)

    def set(self, secret):
        self.values[self.target] = secret

    def delete(self):
        if self.target in self.fail_targets:
            raise CredentialError("Cannot delete the Windows credential")
        self.values.pop(self.target, None)


# These deployment regressions keep provider-facing instance IDs. Only this test
# fixture translates their simulated Agent messages to the actual generic protocol.
FIXTURES = {}
INFO = {"hostname": "test", "system": {"os": "Linux", "architecture": "x86_64"},
        "hardware": {}, "resources": {"capacity": {"cpu": 4, "memory": 1024, "disk": 2048, "gpu": {}},
        "allocatable": {"cpu": 4, "memory": 1024, "disk": 2048, "gpu": {}}}}


class NodeBridge(VastNodes):
    def __init__(self, host, port, **kwargs):
        manager = NodeManager(host, port, **kwargs)
        path = kwargs.get("state_path")
        super().__init__(manager, path.with_name("bindings.json") if path else None)
        self.sessions = {}
        FIXTURES[self.url] = self

    def start(self):
        self.manager.start()

    def close(self):
        FIXTURES.pop(self.url, None)
        self.manager.close()

    def registration_body(self, token, instance_id, runtime_id=None):
        return {"join_token": token, "enrollment_id": format(instance_id, "032x"),
                "runtime_id": runtime_id or "a"*32, "info": INFO}

    def remember(self, response):
        self.sessions[response["session"]] = {k: response[k] for k in ("node_id", "runtime_id", "session")}
        return response

    def register(self, token, instance_id, runtime_id=None):
        return self.remember(self.manager.registration.register(self.registration_body(token, instance_id, runtime_id)))

    def next_task(self, instance_id, session):
        try:
            return self.manager.tasks.next_task(self.sessions.get(session, {"node_id": self.node_id(instance_id), "runtime_id": "a"*32, "session": session}))
        except NodeError as exc:
            raise VastError(str(exc), exc.status) from exc


def post(url, path, body):
    fixture = FIXTURES.get(url)
    if fixture and "instance_id" in body:
        instance_id = body["instance_id"]
        if path == "/node/register":
            body = fixture.registration_body(body["bootstrap"], instance_id, body.get("runtime_id"))
        else:
            body = {**body, **fixture.sessions.get(body["session"], {"node_id": fixture.node_id(instance_id), "runtime_id": "a"*32})}
            body.pop("instance_id")
    request = Request(url + path, data=json.dumps({"protocol_version": 2, **body}).encode("utf-8"),
                      headers={"Content-Type": "application/json"})
    with urlopen(request, timeout=20) as response:
        value = json.load(response)
    return fixture.remember(value) if fixture and path == "/node/register" else value


class NodeBridgeTests(unittest.TestCase):
    def test_agent_startup_status_contains_only_stage(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "startup.status"
            with patch("Legate.Envoy.agent.STARTUP_STATUS", path):
                startup_status("registration_failed:http_403")
            self.assertEqual(path.read_text(), "registration_failed:http_403\n")

    def test_interrupted_deployment_recovers_result_without_redeploying(self):
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory) / "states.json"
            state.write_text(json.dumps({"99": {"status": "deploying"}}))
            job_id, task_id = "c" * 32, "d" * 32
            state.with_name("states_jobs.json").write_text(json.dumps({job_id: {
                "id": job_id, "instance_id": 99, "action": "deploy", "status": "running",
                "stage": "agent_execution", "agent_mode": True, "task_id": task_id,
                "task_action": "deploy"}}))
            bridge = NodeBridge("127.0.0.1", 0)
            bridge.auth_key = "test-key"
            bridge.start()
            try:
                token = bridge.reserve()
                bridge.bind(token, 99)
                session = bridge.register(token, 99, "a" * 32)["session"]
                manager = DeploymentManager(Machine(), Identity(), bridge=bridge,
                    state_path=state, log_path=Path(directory) / "deploy.log")
                seen = []
                def agent():
                    for expected in ("recover", "health", "revision"):
                        task = post(bridge.url, "/node/next", {"instance_id": 99,
                            "session": session})
                        seen.append(task["action"])
                        self.assertEqual(task["action"], expected)
                        output = (json.dumps({"state": "completed", "status": "completed",
                                  "output": "installed", "exit_code": 0}) if expected == "recover"
                                  else "abc123" if expected == "revision" else "就绪")
                        post(bridge.url, "/node/result", {"instance_id": 99,
                            "session": session, "task_id": task["id"], "result": {
                                "status": "completed", "output": output, "exit_code": 0}})
                worker = threading.Thread(target=agent)
                worker.start()
                worker.join(3)
                self.assertFalse(worker.is_alive())
                for _ in range(100):
                    if manager.job(job_id)["status"] != "running":
                        break
                    time.sleep(.01)
                self.assertEqual(seen, ["recover", "health", "revision"])
                self.assertEqual(manager.job(job_id)["status"], "completed")
                self.assertEqual(manager.status(99)["status"], "ready")
            finally:
                bridge.close()

    def test_uncertain_agent_result_is_not_reexecuted(self):
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory) / "states.json"
            state.write_text(json.dumps({"99": {"status": "deploying"}}))
            job_id = "e" * 32
            state.with_name("states_jobs.json").write_text(json.dumps({job_id: {
                "id": job_id, "instance_id": 99, "action": "deploy", "status": "running",
                "stage": "agent_execution", "agent_mode": True, "task_id": "f" * 32,
                "task_action": "deploy"}}))
            bridge = NodeBridge("127.0.0.1", 0)
            bridge.auth_key = "test-key"
            bridge.start()
            try:
                token = bridge.reserve()
                bridge.bind(token, 99)
                session = bridge.register(token, 99)["session"]
                manager = DeploymentManager(Machine(), Identity(), bridge=bridge,
                    state_path=state, log_path=Path(directory) / "deploy.log")
                task = post(bridge.url, "/node/next", {"instance_id": 99, "session": session})
                self.assertEqual(task["action"], "recover")
                post(bridge.url, "/node/result", {"instance_id": 99, "session": session,
                    "task_id": task["id"], "result": {"status": "completed",
                    "output": json.dumps({"state": "not_seen"}), "exit_code": 0}})
                for _ in range(100):
                    if manager.job(job_id)["status"] != "running":
                        break
                    time.sleep(.01)
                self.assertEqual(manager.job(job_id)["stage"], "recovery_unknown")
                self.assertEqual(manager.status(99)["status"], "deployment_unknown")
                self.assertFalse(bridge.manager.tasks.queues[bridge.node_id(99)]["tasks"])
            finally:
                bridge.close()

    def test_agent_runtime_change_invalidates_readiness_across_archon_restart(self):
        with tempfile.TemporaryDirectory() as directory:
            Credentials.values = {}
            registry = {"state_path": Path(directory) / "nodes.json",
                        "credential_factory": Credentials}
            state = Path(directory) / "deployments.json"
            state.write_text(json.dumps({"99": {"status": "ready", "runtime_id": "a" * 32}}))
            first = NodeBridge("127.0.0.1", 0, **registry)
            try:
                first.configure_auth_key("one-off-key")
                token = first.reserve()
                first.bind(token, 99)
                session = first.register(token, 99, "a" * 32)["session"]
                self.assertEqual(first.runtime_id(99), "a" * 32)
                self.assertEqual(first.register(token, 99, "a" * 32)["session"], session)
            finally:
                first.close()
            restored = NodeBridge("127.0.0.1", 0, **registry)
            try:
                manager = DeploymentManager(Machine(), Identity(), bridge=restored,
                    state_path=state, log_path=Path(directory) / "deploy.log")
                old_session = restored.register(token, 99, "a" * 32)["session"]
                # Archon restart already conservatively requires verification.
                self.assertEqual(manager.status(99)["status"], "verification_required")
                manager.states[99] = {"status": "ready", "runtime_id": "a" * 32}
                restarted_session = restored.register(token, 99, "b" * 32)["session"]
                self.assertNotEqual(session, restarted_session)
                with self.assertRaises(VastError):
                    restored.next_task(99, old_session)
                self.assertEqual(manager.status(99)["status"], "verification_required")
                self.assertEqual(json.loads(state.read_text())["99"]["status"],
                                 "verification_required")
            finally:
                restored.close()

    def test_agent_journal_replays_result_without_running_command_twice(self):
        with tempfile.TemporaryDirectory() as directory:
            journal = Path(directory) / "agent.json"
            task = {"id": "a" * 32, "action": "deploy", "message": ""}
            with patch("Legate.Envoy.executor.journal.execute", return_value={
                "status": "completed", "output": "ready", "exit_code": 0}) as command:
                self.assertEqual(execute_once(task, journal)["output"], "ready")
                self.assertEqual(execute_once(task, journal)["output"], "ready")
                command.assert_called_once()
            self.assertNotIn("message", journal.read_text())
            with self.assertRaisesRegex(ValueError, "collision"):
                execute_once({**task, "message": "changed"}, journal)

    def test_agent_journal_never_reexecutes_uncertain_task(self):
        with tempfile.TemporaryDirectory() as directory:
            journal = Path(directory) / "agent.json"
            task = {"id": "b" * 32, "action": "deploy", "message": ""}
            with patch("Legate.Envoy.executor.journal.execute", side_effect=KeyboardInterrupt):
                with self.assertRaises(KeyboardInterrupt):
                    execute_once(task, journal)
            with patch("Legate.Envoy.executor.journal.execute") as command:
                result = execute_once(task, journal)
                command.assert_not_called()
            self.assertEqual(result["status"], "failed")
            self.assertIn("outcome unknown", result["output"])

    def test_archon_restart_keeps_interrupted_job_visible_without_replaying(self):
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory) / "deployment_states.json"
            state.write_text(json.dumps({"99": {"status": "deploying"}}))
            jobs = Path(directory) / "deployment_states_jobs.json"
            jobs.write_text(json.dumps({"job123": {"id": "job123", "instance_id": 99,
                "action": "deploy", "status": "running", "stage": "agent_execution"}}))
            manager = DeploymentManager(Machine(), Identity(), state_path=state,
                log_path=Path(directory) / "deploy.log")
            self.assertEqual(manager.status(99)["status"], "deployment_unknown")
            self.assertEqual(manager.job("job123")["stage"], "archon_restart")
            self.assertIn("outcome is unknown", manager.job("job123")["detail"])
            self.assertEqual(json.loads(jobs.read_text())["job123"]["status"], "failed")
            manager.jobs["job123"]["detail"] = "secret from remote output"
            manager._save_jobs()
            self.assertNotIn("secret from remote output", jobs.read_text())

    def test_waiting_provider_binding_remains_separate_from_node_registry(self):
        bridge = NodeBridge("127.0.0.1", 0)
        try:
            bridge.configure_auth_key("test-key")
            token = bridge.reserve()
            bridge.bind(token, 99)
            self.assertEqual(bridge.status(99)["stage"], "awaiting_agent")
            self.assertEqual(bridge.manager.list_nodes(), [])
            with self.assertRaises(VastError) as error:
                bridge.execute(99, "deploy", timeout=0)
            self.assertEqual(error.exception.status, 504)
            bridge.register(token, 99)
            self.assertEqual(bridge.status(99)["status"], "online")
        finally:
            bridge.close()

    def test_machine_list_reconciles_destroyed_node(self):
        with tempfile.TemporaryDirectory() as directory:
            Credentials.values = {}
            Credentials.fail_targets = set()
            bridge = NodeBridge("127.0.0.1", 0, state_path=Path(directory) / "nodes.json",
                                credential_factory=Credentials)
            bridge.configure_auth_key("test-key")
            token = bridge.reserve()
            bridge.bind(token, 99)

            class EmptyInventory(Machine):
                def list(self, _cursor):
                    return {"instances": [], "next_token": None, "total": 0}

                def one(self, _instance_id):
                    raise VastError("Vast instance was not found", 404)

            machines = EmptyInventory()
            manager = DeploymentManager(machines, Identity(), bridge=bridge,
                state_path=Path(directory) / "deployments.json",
                log_path=Path(directory) / "deploy.log")
            backend = ControlServer(("127.0.0.1", 0), machines, deployments=manager)
            worker = threading.Thread(target=backend.serve_forever)
            worker.start()
            try:
                with urlopen(f"http://127.0.0.1:{backend.server_port}/machines/vast/instances") as reply:
                    self.assertEqual(json.load(reply)["instances"], [])
                self.assertFalse(bridge.configured(99))
                self.assertNotIn("EverSpark Forge/Node 99/joining", Credentials.values)
            finally:
                backend.shutdown()
                backend.server_close()
                worker.join(3)
                bridge.close()

    def test_used_agent_key_does_not_silently_rent_in_ssh_mode(self):
        bridge = NodeBridge("127.0.0.1", 0)
        bridge.configure_auth_key("one-off-key")
        token = bridge.reserve()
        bridge.bind(token, 99)

        class Offers:
            def quote(self, _offer_id):
                return {"cuda_max_good": 12.8}

        class Machines:
            def create(self, *_args, **_kwargs):
                raise AssertionError("Should not rent an SSH Pod with an exhausted Agent key")

        backend = ControlServer(("127.0.0.1", 0), Machines(), Offers(),
                                type("Deployments", (), {"bridge": bridge})())
        worker = threading.Thread(target=backend.serve_forever)
        worker.start()
        try:
            url = f"http://127.0.0.1:{backend.server_port}/machines/vast/rent"
            request = Request(url, data=b'{"offer_id":71}',
                              headers={"Content-Type": "application/json"})
            with self.assertRaises(HTTPError) as exhausted:
                urlopen(request, timeout=3)
            self.assertEqual(exhausted.exception.code, 409)
            self.assertIn("new key", exhausted.exception.read().decode())
        finally:
            backend.shutdown()
            backend.server_close()
            worker.join(3)
            bridge.close()

    def test_tailscale_ip_finds_windows_install_without_path(self):
        with tempfile.TemporaryDirectory() as directory:
            executable = Path(directory) / "Tailscale" / "tailscale.exe"
            executable.parent.mkdir()
            executable.touch()
            calls = []

            def run(command, **_kwargs):
                calls.append(command)
                return subprocess.CompletedProcess(command, 0, "100.77.3.5\n", "")

            with patch.dict(os.environ, {"ProgramFiles": directory}, clear=True), \
                 patch("Archon.Steward.DeploymentManager.providers.network.shutil.which", return_value=None):
                self.assertEqual(tailscale_ip(run=run), "100.77.3.5")
            self.assertEqual(calls, [[str(executable), "ip", "-4"]])

    def test_tailscale_ip_reports_missing_executable(self):
        with patch.dict(os.environ, {}, clear=True), \
             patch("Archon.Steward.DeploymentManager.providers.network.shutil.which", return_value=None):
            with self.assertRaisesRegex(RuntimeError, "Tailscale CLI not found"):
                tailscale_ip()

    def test_agent_rejects_unknown_action_without_shell(self):
        self.assertEqual(execute("shell", "rm -rf /"),
                         {"status": "failed", "output": "Unknown Node Agent task",
                          "exit_code": 2})

    def test_forge_identity_routes_to_independent_deployment_and_health(self):
        self.assertIn("ConceptForge/Scripts/deploy.sh", forge_command("concept", "deploy", "")[0][-1])
        self.assertIn("ImageForge/Scripts/deploy.sh", forge_command("image", "deploy", "")[0][-1])
        self.assertIn("ImageForge/verify.py", forge_command("image", "health", "")[0][-1])
        self.assertIsNone(forge_command("image", "discuss", "hello"))
        self.assertIsNone(forge_command("unknown", "deploy", ""))
        with tempfile.TemporaryDirectory() as directory:
            journal = Path(directory) / "agent.json"
            task = {"id": "f" * 32, "forge": "image", "action": "deploy", "message": ""}
            with patch("Legate.Envoy.executor.journal.execute", return_value={
                "status": "completed", "output": "ready", "exit_code": 0}) as worker:
                execute_once(task, journal)
                worker.assert_called_once_with("deploy", "", "image")
            with self.assertRaisesRegex(ValueError, "collision"):
                execute_once({**task, "forge": "concept"}, journal)

    def test_bridge_delivers_forge_identity_to_node(self):
        bridge = NodeBridge("127.0.0.1", 0)
        bridge.auth_key = "test-key"
        bridge.start()
        try:
            token = bridge.reserve()
            bridge.bind(token, 99)
            session = bridge.register(token, 99)["session"]
            def agent():
                task = post(bridge.url, "/node/next", {"instance_id": 99, "session": session})
                self.assertEqual(task["forge"], "image")
                self.assertEqual(task["action"], "health")
                post(bridge.url, "/node/result", {"instance_id": 99, "session": session,
                    "task_id": task["id"], "result": {"status": "completed",
                    "output": "Image Forge ready", "exit_code": 0}})
            worker = threading.Thread(target=agent)
            worker.start()
            self.assertEqual(bridge.execute(99, "health", forge="image"), "Image Forge ready")
            worker.join(2)
            self.assertFalse(worker.is_alive())
        finally:
            bridge.close()

    def test_orchestrator_discussion_traverses_remote_concept_node(self):
        self._exercise_orchestrator_discussion_traverses_remote_concept_node()

    def test_orchestrator_discussion_traverses_remote_concept_node_through_independent_node_id(self):
        self._exercise_orchestrator_discussion_traverses_remote_concept_node(node_target=True)

    def _exercise_orchestrator_discussion_traverses_remote_concept_node(self, node_target=False):
        bridge = NodeBridge("127.0.0.1", 0)
        bridge.auth_key = "test-key"
        bridge.start()
        control = None
        worker = None
        try:
            token = bridge.reserve()
            bridge.bind(token, 99)
            session = bridge.register(token, 99)["session"]
            control = ControlServer(("127.0.0.1", 0), machines=None if node_target else object(),
                                    deployments=None if node_target else type("Deployments", (), {"bridge": bridge})(),
                                    node_manager=bridge.manager)
            worker = threading.Thread(target=control.serve_forever, daemon=True)
            worker.start()
            with tempfile.TemporaryDirectory() as directory:
                config = load_config()
                config["memory"]["database"] = str(Path(directory) / "memory.db")
                config["remote_nodes"] = {("concept_node_id" if node_target else "concept_instance_id"): bridge.node_id(99) if node_target else 99,
                                          "control_url": f"http://127.0.0.1:{control.server_port}"}
                orchestrator = Orchestrator(config)
                orchestrator._refresh_session_subject = lambda *args, **kwargs: {"subject_id": "test"}
                tasks = []
                def agent():
                    task = post(bridge.url, "/node/next", {"instance_id": 99, "session": session})
                    tasks.append(task)
                    post(bridge.url, "/node/result", {"instance_id": 99, "session": session,
                        "task_id": task["id"], "result": {"status": "completed",
                        "output": "来自远端 Concept Forge 的回复", "exit_code": 0}})
                agent_worker = threading.Thread(target=agent)
                agent_worker.start()
                result = orchestrator.discuss("你好", "remote-session")
                agent_worker.join(2)
                self.assertEqual(result["reply"], "来自远端 Concept Forge 的回复")
                self.assertEqual(tasks[0]["forge"], "concept")
                self.assertEqual(tasks[0]["action"], "chat")
                self.assertIn("你好", tasks[0]["message"])
        finally:
            if control:
                control.shutdown()
                if worker:
                    worker.join(2)
                control.server_close()
            bridge.close()

    def test_remote_image_submit_poll_and_output_transfer(self):
        self._exercise_remote_image_submit_poll_and_output_transfer()

    def test_remote_image_submit_poll_and_output_transfer_through_independent_node_id(self):
        self._exercise_remote_image_submit_poll_and_output_transfer(node_target=True)

    def _exercise_remote_image_submit_poll_and_output_transfer(self, node_target=False):
        bridge = NodeBridge("127.0.0.1", 0)
        bridge.auth_key = "test-key"
        bridge.start()
        control = None
        worker = None
        try:
            token = bridge.reserve()
            bridge.bind(token, 101)
            session = bridge.register(token, 101)["session"]
            control = ControlServer(("127.0.0.1", 0), machines=None if node_target else object(),
                                    deployments=None if node_target else type("Deployments", (), {"bridge": bridge})(),
                                    node_manager=bridge.manager)
            worker = threading.Thread(target=control.serve_forever, daemon=True)
            worker.start()
            actions = []
            image_data = b"\x89PNG\r\n\x1a\nremote-node-image"
            def agent():
                for expected in ("submit", "poll", "fetch"):
                    task = post(bridge.url, "/node/next", {"instance_id": 101, "session": session})
                    actions.append((task["forge"], task["action"]))
                    self.assertEqual(task["action"], expected)
                    payload = json.loads(task["message"])
                    if expected == "submit":
                        self.assertEqual(payload["request"]["positive_prompt"], "portrait")
                        output = {"prompt_id": "remote-job", "selection": {"workflow": "base",
                            "checkpoint": "model", "vae": "", "loras": []}}
                    elif expected == "poll":
                        output = {"prompt_id": "remote-job", "status": "completed",
                                  "images": [{"filename": "render.png", "subfolder": "", "type": "output"}]}
                    else:
                        output = {"size": len(image_data), "data": base64.b64encode(image_data).decode()}
                    post(bridge.url, "/node/result", {"instance_id": 101, "session": session,
                        "task_id": task["id"], "result": {"status": "completed",
                        "output": json.dumps(output), "exit_code": 0}})
            agent_worker = threading.Thread(target=agent)
            agent_worker.start()
            with tempfile.TemporaryDirectory() as directory:
                gateway = RemoteImageGateway(bridge.node_id(101) if node_target else 101, f"http://127.0.0.1:{control.server_port}",
                                             directory, "comfyui")
                job_id, _ = gateway.submit(ImageRequest("portrait", "bad", 42), engine="comfyui")
                self.assertEqual(job_id, "remote-job")
                self.assertEqual(gateway.result(job_id)["status"], "completed")
                self.assertEqual(gateway.image_path("render.png").read_bytes(), image_data)
            agent_worker.join(2)
            self.assertEqual(actions, [("image", action) for action in ("submit", "poll", "fetch")])
        finally:
            if control:
                control.shutdown()
                if worker:
                    worker.join(2)
                control.server_close()
            bridge.close()

    def test_image_deployment_preserves_agent_failure_details(self):
        class FailedBridge:
            def configured(self, instance_id):
                return True

            def execute(self, *args, **kwargs):
                error = VastError("Node Agent execution failed")
                error.detail, error.exit_code = "Model download connection failed", 1
                raise error

        with tempfile.TemporaryDirectory() as directory:
            manager = ImageDeploymentManager(Machine(), FailedBridge(),
                state_path=Path(directory) / "image.json")
            job = manager.start(99)
            for _ in range(100):
                result = manager.job(job["id"])
                if result["status"] != "running":
                    break
                time.sleep(.01)
            self.assertEqual(result["status"], "failed")
            self.assertEqual(result["detail"], "Model download connection failed")
            self.assertEqual(result["exit_code"], 1)
            self.assertEqual(result["stage"], "deploy")

    def test_image_deployment_isolated_from_concept_deployment(self):
        class ReadyBridge:
            def __init__(self):
                self.calls = []

            def configured(self, instance_id):
                return instance_id == 99

            def execute(self, instance_id, action, **kwargs):
                self.calls.append((instance_id, action, kwargs["forge"]))
                return "abc123" if action == "revision" else "ready"

        bridge = ReadyBridge()
        with tempfile.TemporaryDirectory() as directory:
            state_path = Path(directory) / "image.json"
            manager = ImageDeploymentManager(Machine(), bridge, state_path=state_path)
            job = manager.start(99)
            for _ in range(100):
                if manager.job(job["id"])["status"] != "running":
                    break
                time.sleep(0.01)
            self.assertEqual(manager.job(job["id"])["status"], "completed")
            self.assertEqual(manager.status(99), {"status": "ready", "revision": "abc123"})
            self.assertEqual(ImageDeploymentManager(Machine(), bridge, state_path=state_path).status(99),
                             {"status": "ready", "revision": "abc123"})
            self.assertEqual(bridge.calls, [(99, action, "image")
                                            for action in ("deploy", "health", "revision")])

    def test_orchestrator_task_uses_separate_concept_and_image_pods(self):
        self._exercise_orchestrator_task_uses_separate_concept_and_image_pods()

    def test_orchestrator_task_uses_separate_concept_and_image_pods_through_independent_node_id(self):
        self._exercise_orchestrator_task_uses_separate_concept_and_image_pods(node_target=True)

    def _exercise_orchestrator_task_uses_separate_concept_and_image_pods(self, node_target=False):
        bridge = NodeBridge("127.0.0.1", 0)
        bridge.auth_key = "test-key"
        bridge.start()
        control = None
        worker = None
        try:
            sessions = {}
            for instance_id in (99, 101):
                bridge.auth_key = "test-key"
                bridge.claimed = False
                token = bridge.reserve()
                bridge.bind(token, instance_id)
                sessions[instance_id] = bridge.register(token, instance_id)["session"]
            control = ControlServer(("127.0.0.1", 0), machines=None if node_target else object(),
                                    deployments=None if node_target else type("Deployments", (), {"bridge": bridge})(),
                                    node_manager=bridge.manager)
            worker = threading.Thread(target=control.serve_forever, daemon=True)
            worker.start()
            seen = []
            def agent(instance_id, count):
                while sum(item[0] == instance_id for item in seen) < count:
                    task = post(bridge.url, "/node/next", {"instance_id": instance_id,
                                                           "session": sessions[instance_id]})
                    if not task:
                        continue
                    seen.append((instance_id, task["forge"], task["action"]))
                    if task["action"] == "chat":
                        output = """{"model":"illustrious","positive_prompt":"portrait","negative_prompt":"bad","count":1,"status":"over"}"""
                    elif task["action"] == "resources":
                        output = json.dumps({"engine": "comfyui"})
                    elif task["action"] == "default_negative":
                        output = json.dumps({"negative_prompt": "bad"})
                    else:
                        output = json.dumps({"prompt_id": "remote-image-task", "selection": {
                            "workflow": "base", "checkpoint": "model", "vae": "", "loras": []}})
                    post(bridge.url, "/node/result", {"instance_id": instance_id,
                        "session": sessions[instance_id], "task_id": task["id"],
                        "result": {"status": "completed", "output": output, "exit_code": 0}})
            with tempfile.TemporaryDirectory() as directory:
                config = load_config()
                config["memory"]["database"] = str(Path(directory) / "memory.db")
                config["image_forge"]["output_directory"] = str(Path(directory) / "outputs")
                config["remote_nodes"] = {("concept_node_id" if node_target else "concept_instance_id"): bridge.node_id(99) if node_target else 99, ("image_node_id" if node_target else "image_instance_id"): bridge.node_id(101) if node_target else 101,
                    "control_url": f"http://127.0.0.1:{control.server_port}"}
                orchestrator = Orchestrator(config)
                document = new_subject("remote-character", "Remote character")
                orchestrator._refresh_session_subject = lambda *args, **kwargs: document
                concept_worker = threading.Thread(target=agent, args=(99, 1), daemon=True)
                image_worker = threading.Thread(target=agent, args=(101, 3), daemon=True)
                concept_worker.start()
                image_worker.start()
                result = orchestrator.submit("画一张肖像", "remote-session")
                self.assertTrue(result["ok"])
                self.assertEqual(result["result"]["items"][0]["prompt_id"], "remote-image-task")
            concept_worker.join(2)
            image_worker.join(2)
            self.assertEqual(set(seen), {(99, "concept", "chat"),
                (101, "image", "resources"), (101, "image", "default_negative"),
                (101, "image", "submit")})
        finally:
            if control:
                control.shutdown()
                if worker:
                    worker.join(2)
                control.server_close()
            bridge.close()

    def test_image_node_entry_uses_local_gateway_and_reads_output(self):
        class Engine:
            name = "comfyui"

            def submit(self, _request, _notify):
                return "engine-job", {"workflow": "base", "checkpoint": "model", "vae": "", "loras": []}

            def poll(self, _job_id):
                return {"status": "completed", "images": [{"filename": "render.png"}]}

        with tempfile.TemporaryDirectory() as directory:
            outputs = Path(directory) / "outputs"
            outputs.mkdir()
            (outputs / "render.png").write_bytes(b"remote-image")
            config = load_config()
            config["memory"]["database"] = str(Path(directory) / "jobs.db")
            config["image_forge"]["output_directory"] = str(outputs)
            with patch.object(remote_task, "load_config", return_value=config), \
                 patch.object(remote_task, "discover_plugins", return_value={}), \
                 patch.object(remote_task, "create_engines", return_value={"comfyui": Engine()}):
                submitted = remote_task.run("submit", {"engine": "comfyui", "request": {
                    "positive_prompt": "portrait", "negative_prompt": "bad", "seed": 42}})
                result = remote_task.run("poll", {"prompt_id": submitted["prompt_id"]})
                transferred = remote_task.run("fetch", {"filename": "render.png", "offset": 0})
            self.assertEqual(result["status"], "completed")
            self.assertEqual(base64.b64decode(transferred["data"]), b"remote-image")

    def test_agent_registers_and_executes_deployment_without_ssh(self):
        bridge = NodeBridge("127.0.0.1", 0)
        bridge.auth_key = "one-off-test-key"
        bridge.start()
        try:
            bootstrap = bridge.reserve()
            bridge.bind(bootstrap, 99)
            self.assertIsNone(bridge.auth_key)
            session = post(bridge.url, "/node/register", {"instance_id": 99,
                                                           "bootstrap": bootstrap,
                                                           "runtime_id": "a" * 32})["session"]
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
                    for _ in range(3):
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
                self.assertEqual(seen, ["deploy", "health", "revision"])
                self.assertEqual(manager.status(99)["status"], "ready")
                self.assertEqual(manager.status(99)["runtime_id"], "a" * 32)
                self.assertEqual(bridge.status(99)["status"], "online")
                self.assertIn('"event": "agent_exit"',
                              (Path(directory) / "deployment.log").read_text())

                def discuss(active_session):
                    job = manager.start(99, "discuss", "你好")
                    task = post(bridge.url, "/node/next", {"instance_id": 99,
                        "session": active_session})
                    self.assertEqual(task["action"], "discuss")
                    post(bridge.url, "/node/result", {"instance_id": 99,
                        "session": active_session, "task_id": task["id"], "result": {
                            "status": "completed", "output": "你好，Jhin", "exit_code": 0}})
                    for _ in range(100):
                        result = manager.job(job["id"])
                        if result["status"] != "running":
                            break
                        time.sleep(.01)
                    self.assertEqual(result["reply"], "你好，Jhin")

                discuss(session)

                new_session = post(bridge.url, "/node/register", {"instance_id": 99,
                    "bootstrap": bootstrap, "runtime_id": "b" * 32})["session"]
                with self.assertRaises(HTTPError) as old_session:
                    post(bridge.url, "/node/next", {"instance_id": 99, "session": session})
                self.assertEqual(old_session.exception.code, 403)
                self.assertEqual(manager.status(99)["status"], "verification_required")
                with self.assertRaisesRegex(VastError, "Deploy Concept Forge"):
                    manager.start(99, "discuss", "你好")

                verified = manager.start(99, "verify")
                def verify_agent():
                    for expected in ("health", "revision"):
                        task = post(bridge.url, "/node/next", {"instance_id": 99,
                            "session": new_session})
                        self.assertEqual(task["action"], expected)
                        post(bridge.url, "/node/result", {"instance_id": 99,
                            "session": new_session, "task_id": task["id"], "result": {
                                "status": "completed", "output": "abc123" if expected == "revision"
                                else "就绪", "exit_code": 0}})
                worker = threading.Thread(target=verify_agent)
                worker.start()
                worker.join(3)
                self.assertFalse(worker.is_alive())
                for _ in range(100):
                    if manager.job(verified["id"])["status"] != "running":
                        break
                    time.sleep(.01)
                self.assertEqual(manager.job(verified["id"])["status"], "completed")
                self.assertEqual(manager.status(99)["status"], "ready")
                self.assertEqual(manager.status(99)["runtime_id"], "b" * 32)
                discuss(new_session)
        finally:
            bridge.close()


if __name__ == "__main__":
    unittest.main()
