"""Generic protocol, durability and real portable Agent process regressions."""
import ast
import copy
import json
import os
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from Archon.Steward.NodeManager import NodeManager
from Archon.Steward.NodeManager.errors import NodeError
from Archon.Steward.NodeManager.transport.auth import digest
from Archon.Steward.NodeManager.transport.operator import OperatorServer
from Archon.Steward.DeploymentManager.providers.vast_nodes import VastNodes
from Archon.Steward.DeploymentManager.providers.migration import migrate_legacy_registry
from Legate.Envoy.identity import Identity
from Legate.Envoy.registration import Registration
from Legate.Envoy.transport import Transport, BridgeError
from Legate.Envoy.heartbeat import Heartbeat
from Legate.Envoy.executor.journal import execute_once
from Legate.Envoy.fingerprint.hardware import fingerprint

ROOT = Path(__file__).resolve().parents[2]
INFO = {"hostname": "machine-b", "system": {"os": "Linux", "architecture": "x86_64"},
        "hardware": {"gpu": [{"id": "GPU-1", "name": "Test GPU", "vram": 24000}]},
        "resources": {"capacity": {"cpu": 8, "memory": 64000, "disk": 200000, "gpu": {"GPU-1": {"vram": 24000}}},
                      "allocatable": {"cpu": 4, "memory": 32000, "disk": 100000, "gpu": {"GPU-1": {"vram": 12000}}}}}


def call(url, path, body):
    request = Request(url+path, data=json.dumps({"protocol_version": 2, **body}).encode(),
                      headers={"Content-Type": "application/json"})
    with urlopen(request, timeout=20) as response:
        return json.load(response)


def wait_for(predicate, timeout=10):
    deadline = time.monotonic()+timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(.025)
    raise AssertionError("Condition did not become true before timeout")


def auth(response):
    return {key: response[key] for key in ("node_id", "runtime_id", "session")}


class NodeRegistrationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.directory = Path(self.temporary.name)
        self.manager = NodeManager("127.0.0.1", 0, state_path=self.directory/"nodes.json", heartbeat_interval=.1, lease_timeout=.7)
        self.manager.start()
        self.token = self.manager.issue_join_token()
        self.body = {"join_token": self.token, "enrollment_id": "e"*32, "runtime_id": "a"*32, "info": copy.deepcopy(INFO)}

    def tearDown(self):
        self.manager.close()
        self.temporary.cleanup()

    def register(self, body=None):
        return call(self.manager.url, "/node/register", body or self.body)

    def heartbeat(self, response, **changes):
        return call(self.manager.url, "/node/heartbeat", {**auth(response), "allocatable": INFO["resources"]["allocatable"], **changes})

    def restart_host(self):
        port = self.manager.server.server_port
        self.manager.close()
        self.manager = NodeManager("127.0.0.1", port, state_path=self.directory/"nodes.json", heartbeat_interval=.1, lease_timeout=.7)
        self.manager.start()

    def test_probe_lane_completes_while_execution_lane_is_occupied(self):
        response = self.register()
        self.heartbeat(response)
        results = {}
        def execute(action):
            results[action] = self.manager.execute(response['node_id'], action, '{}', timeout=3, forge='image')
        main = threading.Thread(target=execute, args=('submit',))
        main.start()
        wait_for(lambda: bool(self.manager.tasks.queues[response['node_id']]['tasks']))
        running = self.manager.tasks.next_task({**auth(response), 'lane': 'execution'})
        probe = threading.Thread(target=execute, args=('probe',))
        probe.start()
        wait_for(lambda: bool(self.manager.tasks.queues[response['node_id']]['tasks']))
        check = call(self.manager.url, '/node/probe/next', auth(response))
        self.assertEqual(check['action'], 'probe')
        self.manager.tasks.finish({**auth(response), 'task_id': check['id'],
            'result': {'status': 'completed', 'output': '{"ok":true}', 'exit_code': 0}})
        probe.join(1)
        self.assertEqual(results['probe'], '{"ok":true}')
        self.assertTrue(main.is_alive())
        self.manager.tasks.finish({**auth(response), 'task_id': running['id'],
            'result': {'status': 'completed', 'output': 'done', 'exit_code': 0}})
        main.join(1)
        self.assertEqual(results['submit'], 'done')

    def test_independent_identity_without_any_provider(self):
        response = self.register()
        record = self.manager.status(response["node_id"])
        self.assertRegex(record["node_id"], r"^[a-f0-9]{32}$")
        self.assertEqual(record["provider_metadata"], {})
        self.assertEqual(record["hostname"], "machine-b")
        self.assertEqual(record["resources"], INFO["resources"])
        self.assertNotIn("forge", record)
        self.assertNotIn("capabilities", record)
        other = self.register({**self.body, "enrollment_id": "d"*32, "join_token": self.manager.issue_join_token()})
        self.assertNotEqual(response["node_id"], other["node_id"])

    def test_provider_metadata_never_authorizes_or_selects_a_node(self):
        info = {**INFO, "provider_metadata": {"provider": "any-future-provider", "provider_instance_id": 123456}}
        first = self.register({**self.body, "info": info})
        second = self.register({**self.body, "enrollment_id": "b"*32, "join_token": self.manager.issue_join_token(), "info": info})
        self.assertNotEqual(first["node_id"], second["node_id"])
        self.assertEqual(self.manager.status(first["node_id"])["provider_metadata"], info["provider_metadata"])
        with self.assertRaises(HTTPError) as invalid:
            call(self.manager.url, "/node/register", {"instance_id": 123456, "bootstrap": self.token})
        self.assertEqual(invalid.exception.code, 400)

    def test_claim_is_idempotent_for_lost_response_and_denies_another_enrollment(self):
        first = self.register()
        retry = self.register()
        self.assertEqual(first, retry)
        with self.assertRaises(HTTPError) as claimed:
            self.register({**self.body, "enrollment_id": "f"*32})
        self.assertEqual(claimed.exception.code, 403)
        self.restart_host()
        recovered = self.register()
        self.assertEqual(first["node_id"], recovered["node_id"])
        self.assertEqual(first["credential"], recovered["credential"])
        self.assertNotEqual(first["session"], recovered["session"])
        with self.assertRaises(HTTPError) as fenced:
            self.heartbeat(first)
        self.assertEqual(fenced.exception.code, 403)

    def test_credential_recovers_same_node_after_join_expires_and_fences_runtime(self):
        first = self.register()
        with self.manager.lock:
            nodes, joins = self.manager.registry.candidates()
            joins[digest(self.token)]["expires_at"] = 0
            self.manager.registry.publish(nodes, joins)
        second = self.register({"node_id": first["node_id"], "credential": first["credential"],
                                "enrollment_id": self.body["enrollment_id"], "runtime_id": "b"*32, "info": INFO})
        self.assertEqual(first["node_id"], second["node_id"])
        self.assertNotEqual(first["session"], second["session"])
        with self.assertRaises(HTTPError) as fenced:
            self.heartbeat(first)
        self.assertEqual(fenced.exception.code, 403)
        self.heartbeat(second)
        self.restart_host()
        third = self.register({"node_id": first["node_id"], "credential": first["credential"],
                               "enrollment_id": self.body["enrollment_id"], "runtime_id": "c"*32, "info": INFO})
        self.assertEqual(first["node_id"], third["node_id"])

    def test_expired_or_revoked_join_is_denied(self):
        self.manager.revoke_join_token(self.token)
        with self.assertRaises(HTTPError) as revoked:
            self.register()
        self.assertEqual(revoked.exception.code, 403)
        self.token = self.manager.issue_join_token()
        with self.manager.lock:
            nodes, joins = self.manager.registry.candidates()
            joins[digest(self.token)]["expires_at"] = 0
            self.manager.registry.publish(nodes, joins)
        with self.assertRaises(HTTPError) as expired:
            self.register({**self.body, "join_token": self.token})
        self.assertEqual(expired.exception.code, 403)

    def test_heartbeat_sends_only_dynamic_data_and_lease_expires_without_reads(self):
        response = self.register()
        initial = self.manager.registry.path.read_bytes()
        dynamic = copy.deepcopy(INFO["resources"]["allocatable"])
        dynamic["gpu"]["GPU-1"]["vram"] = 4000
        self.heartbeat(response, allocatable=dynamic, load={"cpu_1m": 1.5})
        self.assertEqual(self.manager.registry.path.read_bytes(), initial)
        status = self.manager.status(response["node_id"])
        self.assertEqual(status["resources"]["allocatable"], dynamic)
        self.assertEqual(status["resources"]["capacity"], INFO["resources"]["capacity"])
        wait_for(lambda: self.manager.registry.nodes[response["node_id"]]["status"] == "offline", 3)
        self.assertIsNone(self.manager.status(response["node_id"])["resources"]["allocatable"])
        self.heartbeat(response)
        self.assertEqual(self.manager.status(response["node_id"])["status"], "online")

    def test_unhealthy_and_removed_lifecycle_reject_tasks_and_authentication(self):
        response = self.register()
        self.heartbeat(response, status="unhealthy")
        self.assertEqual(self.manager.status(response["node_id"])["status"], "unhealthy")
        with self.assertRaises(HTTPError) as unhealthy:
            call(self.manager.url, "/node/next", auth(response))
        self.assertEqual(unhealthy.exception.code, 409)
        self.manager.remove(response["node_id"])
        self.assertEqual(self.manager.status(response["node_id"])["status"], "removed")
        self.assertIsNone(self.manager.registry.credential(response["node_id"]).get())
        with self.assertRaises(HTTPError) as removed:
            self.heartbeat(response)
        self.assertEqual(removed.exception.code, 403)
        with self.assertRaises(HTTPError):
            self.register()
        self.restart_host()
        self.assertEqual(self.manager.status(response["node_id"])["status"], "removed")

    def test_resource_limits_and_nonfinite_values_are_rejected(self):
        response = self.register()
        for key, bad in (("cpu", 100), ("memory", -1), ("disk", float("nan")), ("memory", True)):
            available = copy.deepcopy(INFO["resources"]["allocatable"])
            available[key] = bad
            with self.subTest(key=key, bad=bad), self.assertRaises(HTTPError) as invalid:
                self.heartbeat(response, allocatable=available)
            self.assertEqual(invalid.exception.code, 400)
        available = copy.deepcopy(INFO["resources"]["allocatable"])
        available["gpu"]["GPU-1"]["vram"] = 24001
        with self.assertRaises(HTTPError):
            self.heartbeat(response, allocatable=available)
        with self.assertRaises(HTTPError):
            self.heartbeat(response, load={"cpu_1m": float("inf")})

    def test_task_channel_does_not_renew_lease_and_results_survive_offline(self):
        response = self.register()
        output = []
        worker = threading.Thread(target=lambda: output.append(self.manager.execute(response["node_id"], "revision", timeout=5, forge="image")))
        worker.start()
        task = call(self.manager.url, "/node/next", auth(response))
        renewed = self.manager.leases[response["node_id"]].renewed_at
        wait_for(lambda: self.manager.registry.nodes[response["node_id"]]["status"] == "offline", 3)
        self.assertEqual(self.manager.leases[response["node_id"]].renewed_at, renewed)
        call(self.manager.url, "/node/result", {**auth(response), "task_id": task["id"],
                                              "result": {"status": "completed", "output": "same channel", "exit_code": 0}})
        worker.join(2)
        self.assertEqual(output, ["same channel"])
        with self.assertRaises(HTTPError) as offline:
            call(self.manager.url, "/node/next", auth(response))
        self.assertEqual(offline.exception.code, 409)

    def test_registry_failure_does_not_consume_join_or_publish_session(self):
        original = Path.replace
        def fail(path, target):
            if Path(target) == self.manager.registry.path:
                raise OSError("Injected publication failure")
            return original(path, target)
        with patch.object(Path, "replace", fail), self.assertRaises(HTTPError) as unavailable:
            self.register()
        self.assertEqual(unavailable.exception.code, 503)
        self.assertEqual(self.manager.registry.nodes, {})
        self.assertEqual(self.manager.registry.joins[digest(self.token)]["enrollment_id"], None)
        self.assertEqual(self.manager.leases, {})
        self.register()

    def test_durable_index_contains_no_bearer_secrets(self):
        response = self.register()
        raw = self.manager.registry.path.read_text()
        for value in (self.token, response["credential"], response["session"]):
            self.assertNotIn(value, raw)
        self.assertEqual((self.directory/"nodes_credentials"/response["node_id"]).stat().st_mode & 0o777, 0o600)

    def test_agent_identity_recovers_registration_after_response_loss(self):
        path = self.directory/"agent"/"identity.json"
        identity = Identity(path)
        identity.bootstrap(self.token)
        transport = Transport(self.manager.url)
        registration = Registration(identity, transport, INFO)
        original = transport.request
        def lost(path, body):
            original(path, body)
            raise OSError("Lost reply")
        with patch.object(transport, "request", lost), self.assertRaises(OSError):
            registration.register()
        node_id = self.manager.list_nodes()[0]["node_id"]
        self.restart_host()
        restored = Identity(path)
        recovered = Registration(restored, Transport(self.manager.url), INFO)
        self.assertEqual(recovered.register()["node_id"], node_id)
        self.assertNotIn("join_token", json.loads(path.read_text()))
        self.assertEqual(Identity(path).value["node_id"], node_id)

    def test_heartbeat_thread_keeps_node_online_during_long_executor_call(self):
        identity = Identity(self.directory/"agent"/"identity.json")
        identity.bootstrap(self.token)
        registration = Registration(identity, Transport(self.manager.url), INFO)
        response = registration.register()
        heartbeat = Heartbeat(registration, self.directory)
        with patch("Legate.Envoy.heartbeat.dynamic", return_value=(INFO["resources"]["allocatable"], {"cpu_1m": 1})):
            heartbeat.thread.start()
            try:
                def slow(*args):
                    time.sleep(1.5)
                    return {"status": "completed", "output": "long task", "exit_code": 0}
                task = {"id": "f"*32, "forge": "image", "action": "deploy", "message": ""}
                result = execute_once(task, self.directory/"journal.json", executor=slow)
                self.assertEqual(result["status"], "completed")
                self.assertEqual(self.manager.status(response["node_id"])["status"], "online")
            finally:
                heartbeat.close()

    def test_provider_can_bind_after_registration_and_prunes_only_its_nodes(self):
        provider = VastNodes(self.manager, self.directory/"bindings.json", "tailscale-key")
        token = provider.reserve()
        response = self.register({**self.body, "join_token": token})
        provider.bind(token, 123456)
        self.assertEqual(provider.node_id(123456), response["node_id"])
        self.assertEqual(provider.status(123456)["status"], "online")
        other = self.register({**self.body, "enrollment_id": "f"*32, "join_token": self.manager.issue_join_token()})
        restored = VastNodes(self.manager, self.directory/"bindings.json", "tailscale-key")
        self.assertIsNone(restored.auth_key)
        self.assertEqual(restored.prune(set()), {123456})
        self.assertEqual(self.manager.status(response["node_id"])["status"], "removed")
        self.assertEqual(self.manager.status(other["node_id"])["status"], "online")

    def test_operator_routes_work_without_machine_management_and_check_origin(self):
        operator = OperatorServer(("127.0.0.1", 0), self.manager)
        worker = threading.Thread(target=operator.serve_forever, daemon=True)
        worker.start()
        url = f"http://127.0.0.1:{operator.server_port}"
        try:
            request = Request(url+"/nodes/join", data=b'{}', headers={"Content-Type": "application/json", "Origin": "https://attacker.invalid"})
            with self.assertRaises(HTTPError) as denied:
                urlopen(request)
            self.assertEqual(denied.exception.code, 403)
            grant = Request(url+"/nodes/join", data=b'{}', headers={"Content-Type": "application/json"})
            with urlopen(grant) as result:
                token = json.load(result)["join_token"]
            node = self.register({**self.body, "join_token": token})
            with urlopen(url+"/nodes") as result:
                records = json.load(result)["nodes"]
            self.assertEqual(records[0]["node_id"], node["node_id"])
            self.assertNotIn("session", records[0])
        finally:
            operator.shutdown()
            operator.server_close()
            worker.join(2)

    def test_joining_identity_survives_failed_admission_then_retries_same_node(self):
        original = Path.replace
        writes = []
        def fail_admission(path, target):
            if Path(target) == self.manager.registry.path:
                writes.append(True)
                if len(writes) == 2:
                    raise OSError("Injected admission publication failure")
            return original(path, target)
        with patch.object(Path, "replace", fail_admission), self.assertRaises(HTTPError) as failure:
            self.register()
        self.assertEqual(failure.exception.code, 503)
        node = self.manager.list_nodes()[0]
        self.assertEqual(node["status"], "joining")
        self.assertIsNone(node["resources"]["allocatable"])
        self.assertEqual(self.manager.leases, {})
        response = self.register()
        self.assertEqual(response["node_id"], node["node_id"])
        self.assertEqual(self.manager.status(node["node_id"])["status"], "online")

    def test_failed_offline_or_remove_publication_preserves_live_credential_and_session(self):
        response = self.register()
        original = Path.replace
        def fail(path, target):
            if Path(target) == self.manager.registry.path:
                raise OSError("Injected publication failure")
            return original(path, target)
        with patch.object(Path, "replace", fail):
            with self.assertRaises(OSError):
                self.manager.remove(response["node_id"])
            self.assertEqual(self.manager.registry.nodes[response["node_id"]]["status"], "online")
            self.assertEqual(self.manager.registry.credential(response["node_id"]).get(), response["credential"])
            before = self.manager.leases[response["node_id"]].renewed_at
            with self.assertRaises(HTTPError) as failure:
                self.heartbeat(response, status="unhealthy")
            self.assertEqual(failure.exception.code, 503)
            self.assertEqual(self.manager.leases[response["node_id"]].renewed_at, before)
        self.heartbeat(response)

    def test_destroyed_provider_inventory_retains_stopped_nodes_and_local_nodes(self):
        from Archon.Steward.DeploymentManager.manager import DeploymentManager
        from Archon.Steward.vast_instances import VastError
        provider = VastNodes(self.manager, self.directory/"bindings.json", "key")
        token = provider.reserve()
        provider.bind(token, 99)
        owned = self.register({**self.body, "join_token": token})
        local = self.register({**self.body, "join_token": self.manager.issue_join_token(), "enrollment_id": "d"*32})
        class Machines:
            destroyed = False
            failed = False
            def one(self, instance_id):
                if self.destroyed:
                    raise VastError("Not found", 404)
                return {"id": instance_id}
            def list(self, cursor):
                if self.failed:
                    raise VastError("Temporary outage")
                return {"instances": [{"id": 99, "actual_status": "stopped"}], "next_token": None}
        machines = Machines()
        deployment = DeploymentManager(machines, object(), bridge=provider,
            state_path=self.directory/"deploy.json", log_path=self.directory/"deploy.log")
        deployment.states[99] = {"status": "ready"}
        inventory = {"instances": [], "next_token": "next", "total": 1}
        self.assertTrue(deployment.reconcile_instances(inventory))
        self.assertEqual(deployment.status(99)["status"], "verification_required")
        self.assertTrue(provider.configured(99))
        machines.failed = True
        self.assertFalse(deployment.reconcile_instances(inventory))
        self.assertTrue(provider.configured(99))
        self.assertFalse(deployment.reconcile_instances({"instances": [], "next_token": None, "total": 1}))
        machines.destroyed = True
        self.assertTrue(deployment.reconcile_instances({"instances": [], "next_token": None, "total": 0}))
        self.assertFalse(provider.configured(99))
        self.assertEqual(self.manager.status(owned["node_id"])["status"], "removed")
        self.assertEqual(self.manager.status(local["node_id"])["status"], "online")

    def test_legacy_index_migration_is_deployment_owned_and_uses_generic_join(self):
        values = {"EverSpark Forge/Node 99/joining": "legacy-join", "EverSpark Forge/Node 99/online": "old-session"}
        class Credential:
            def __init__(self, target):
                self.target = target
            def get(self):
                return values.get(self.target)
            def set(self, value):
                values[self.target] = value
            def delete(self):
                values.pop(self.target, None)
        path, bindings = self.directory/"legacy.json", self.directory/"legacy_bindings.json"
        path.write_text(json.dumps({"version": 1, "nodes": {"99": "online"}, "used_key_hash": digest("used-key")}))
        migrate_legacy_registry(path, bindings, Credential)
        self.assertEqual(json.loads(path.read_text())["version"], 2)
        self.assertNotIn("legacy-join", path.read_text())
        self.assertTrue(path.with_name("legacy.json.v1.bak").exists())
        manager = NodeManager("127.0.0.1", 0, state_path=path, credential_factory=Credential)
        manager.start()
        try:
            provider = VastNodes(manager, bindings, "used-key")
            self.assertIsNone(provider.auth_key)
            self.assertEqual(provider.status(99)["status"], "joining")
            response = call(manager.url, "/node/register", {**self.body, "join_token": "legacy-join"})
            self.assertEqual(provider.node_id(99), response["node_id"])
            self.assertNotEqual(response["node_id"], "99")
            self.assertNotEqual(response["session"], "old-session")
        finally:
            manager.close()

    def test_removed_tombstone_denies_access_when_secret_cleanup_fails(self):
        response = self.register()
        from Archon.Steward.NodeManager.transport.credentials import FileCredential
        with patch.object(FileCredential, "delete", side_effect=OSError("Store unavailable")):
            self.manager.remove(response["node_id"])
        self.assertEqual(self.manager.registry.credential(response["node_id"]).get(), response["credential"])
        with self.assertRaises(HTTPError) as denied:
            self.heartbeat(response)
        self.assertEqual(denied.exception.code, 403)
        self.restart_host()
        self.assertIsNone(self.manager.registry.credential(response["node_id"]).get())
        self.assertEqual(self.manager.status(response["node_id"])["status"], "removed")

    def test_corrupt_agent_identity_is_not_silently_replaced(self):
        path = self.directory/"bad-identity.json"
        path.write_text('{"node_id":"bad"}')
        with self.assertRaises(RuntimeError):
            Identity(path)
        self.assertEqual(path.read_text(), '{"node_id":"bad"}')

    def test_real_agent_process_registers_heartbeats_restarts_and_runs_existing_tasks(self):
        env = {k: v for k, v in os.environ.items() if not k.startswith("EVERSPARK_NODE_") and k != "CONTAINER_ID"}
        env.update({"EVERSPARK_NODE_URL": self.manager.url, "EVERSPARK_NODE_JOIN_TOKEN": self.token,
                    "EVERSPARK_NODE_DATA_DIR": str(self.directory/"real-agent"), "EVERSPARK_NODE_BANDWIDTH": "0"})
        process = None
        def start():
            return subprocess.Popen([sys.executable, "-m", "Legate.Envoy.node_agent"], cwd=ROOT, env=env,
                                    stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        def stop():
            nonlocal process
            if process:
                process.terminate()
                process.communicate(timeout=5)
                process = None
        try:
            process = start()
            wait_for(lambda: len(self.manager.registry.nodes) == 1)
            node_id = self.manager.list_nodes()[0]["node_id"]
            runtime = self.manager.runtime_id(node_id)
            self.assertEqual(self.manager.status(node_id)["provider_metadata"], {})
            time.sleep(1.2)
            self.assertEqual(self.manager.status(node_id)["status"], "online")
            expected = subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT).decode().strip()
            self.assertEqual(self.manager.execute(node_id, "revision", timeout=10).strip(), expected)
            stop()
            wait_for(lambda: self.manager.registry.nodes[node_id]["status"] == "offline", 3)
            env.pop("EVERSPARK_NODE_JOIN_TOKEN")
            process = start()
            wait_for(lambda: self.manager.runtime_id(node_id) != runtime and self.manager.status(node_id)["status"] == "online")
            self.assertEqual(len(self.manager.registry.nodes), 1)
            self.assertEqual(self.manager.execute(node_id, "revision", timeout=10, forge="image").strip(), expected)
            self.restart_host()
            wait_for(lambda: self.manager.status(node_id)["status"] == "online", 12)
            self.assertEqual(self.manager.execute(node_id, "revision", timeout=10).strip(), expected)
        finally:
            stop()

    def test_bandwidth_heartbeat_is_persisted_and_survives_registration(self):
        response = self.register()
        speed = {"status": "completed", "region": "AS", "server_region": "AS", "download_mb_s": 50, "server_name": "Fixture", "finished_at": "2026-10-02T00:00:00Z"}
        self.heartbeat(response, bandwidth=speed)
        stored = self.manager.status(response["node_id"])["bandwidth"]
        self.assertTrue(stored["qualified"])
        self.heartbeat(response, bandwidth={"status": "completed", "download_mb_s": float("nan")})
        self.assertEqual(self.manager.status(response["node_id"])["bandwidth"], stored)
        body = {**self.body, "node_id": response["node_id"], "credential": response["credential"]}
        self.register(body)
        self.assertEqual(self.manager.status(response["node_id"])["bandwidth"], stored)
        self.restart_host()
        self.assertEqual(self.manager.status(response["node_id"])["bandwidth"], stored)

    def test_core_has_no_provider_implementation_dependency(self):
        for path in (ROOT/"Archon/Steward/NodeManager").rglob("*.py"):
            source = path.read_text()
            tree = ast.parse(source)
            imports = [node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)]
            self.assertFalse(any("vast" in value.lower() or "DeploymentManager" in value for value in imports), str(path))
            self.assertNotIn("VastError", source)
            self.assertNotIn("provider ==", source)


if __name__ == "__main__":
    unittest.main()
