from __future__ import annotations

import io
import json
import subprocess
import tempfile
import threading
import time
import unittest
from pathlib import Path
from subprocess import CompletedProcess
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from test_vast_machines import FakeCredentialStore

from Archon.Steward.vast_instances import VastError, VastInstances
from Archon.Steward.vast_offers import VastOffers
from Archon.Steward.DeploymentManager.manager import DeploymentManager
from Archon.Gate.control_server import ControlServer
from Archon.Portal.app import Settings, WebUIServer
from Legate.Envoy.base_image import select_base_image


class Provider:
    def __init__(self):
        self.calls = []

    def __call__(self, request, timeout):
        payload = json.loads(request.data) if request.data else None
        self.calls.append((request.full_url, request.get_method(), payload))
        url = request.full_url
        if url.endswith("/bundles/"):
            result = {"offers": [{"id": 71, "gpu_name": "RTX 3090", "num_gpus": 1,
                                  "cuda_max_good": 12.8, "dph_total": 0.42}]}
        elif url.endswith("/asks/71/"):
            result = {"success": True, "new_contract": 99}
        elif url.endswith("/instances/99/ssh"):
            result = {"success": True}
        elif url.endswith("/instances/99"):
            result = {"instances": {"id": 99, "actual_status": "running",
                                    "ssh_host": "ssh123.vast.ai", "ssh_port": 12345}}
        elif url.endswith("/instances/command/99"):
            result = {"result_url": "https://s3.amazonaws.com/vast.ai/instance_logs/test"}
        elif url == "https://s3.amazonaws.com/vast.ai/instance_logs/test":
            return io.BytesIO(b"failed:authenticate_tailscale\n")
        else:
            raise AssertionError(url)
        return io.BytesIO(json.dumps(result).encode())


class Identity:
    private_key = Path("/tmp/test-private-key")
    known_hosts = Path("/tmp/test-known-hosts")

    def public_key(self):
        return "ssh-ed25519 TEST"


class DeploymentTests(unittest.TestCase):
    def test_destroyed_instance_is_retired_without_touching_other_nodes(self):
        class Bridge:
            def __init__(self):
                self.remaining = {99, 100}

            def instance_ids(self):
                return set(self.remaining)

            def prune(self, live_ids):
                self.remaining.intersection_update(live_ids)

        provider, store, bridge = Provider(), FakeCredentialStore(), Bridge()
        store.set("key")
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory) / "states.json"
            state.write_text(json.dumps({"99": {"status": "ready"},
                                         "100": {"status": "ready"}}))
            manager = DeploymentManager(VastInstances(store, opener=provider), Identity(),
                bridge=bridge, state_path=state, log_path=Path(directory) / "deploy.log")
            manager.retire_instance(99)
            self.assertEqual(bridge.remaining, {100})
            self.assertEqual(json.loads(state.read_text()), {"100": {"status": "verification_required"}})
            self.assertIn(99, manager.retired_instances)

    def test_startup_diagnostics_uses_fixed_command_and_sanitized_stage(self):
        provider, store = Provider(), FakeCredentialStore()
        store.set("sensitive-key")
        machines = VastInstances(store, opener=provider)
        self.assertEqual(machines.startup_diagnostics(99), {"stage": "failed:authenticate_tailscale"})
        self.assertEqual(provider.calls[-2][2], {"command": "cat /workspace/everspark-startup.status"})
        with self.assertRaises(VastError):
            machines.startup_diagnostics(True)

    def test_startup_diagnostics_rejects_untrusted_result_url(self):
        provider, store = Provider(), FakeCredentialStore()
        store.set("key")
        def hostile(request, timeout):
            return io.BytesIO(json.dumps({"result_url": "https://evil.example/vast.ai/instance_logs/test"}).encode())
        with self.assertRaisesRegex(VastError, "invalid startup result URL"):
            VastInstances(store, opener=hostile).startup_diagnostics(99)

    def test_startup_diagnostics_available_through_local_gate(self):
        provider, store = Provider(), FakeCredentialStore()
        store.set("key")
        server = ControlServer(("127.0.0.1", 0), VastInstances(store, opener=provider))
        worker = threading.Thread(target=server.serve_forever)
        worker.start()
        try:
            request = Request(f"http://127.0.0.1:{server.server_port}/machines/vast/startup-diagnostics",
                data=b'{"instance_id":99}', headers={"Content-Type": "application/json"})
            with urlopen(request, timeout=3) as response:
                self.assertEqual(json.load(response), {"ok": True, "stage": "failed:authenticate_tailscale"})
        finally:
            server.shutdown()
            server.server_close()
            worker.join(3)

    def test_verify_restores_readiness_without_redeploying(self):
        provider, store = Provider(), FakeCredentialStore()
        store.set("key")
        calls = []

        def run(argv, **_kwargs):
            calls.append(argv[-1])
            output = "abc123" if "rev-parse" in argv[-1] else "就绪"
            return CompletedProcess(argv, 0, output, "")

        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory) / "states.json"
            state.write_text(json.dumps({"99": {"status": "verification_required"}}))
            manager = DeploymentManager(VastInstances(store, opener=provider), Identity(),
                run=run, state_path=state, log_path=Path(directory) / "deploy.log")
            job = manager.start(99, "verify")
            for _ in range(100):
                result = manager.job(job["id"])
                if result["status"] != "running":
                    break
                time.sleep(.01)
            self.assertEqual(result["status"], "completed")
            self.assertEqual(manager.status(99)["status"], "ready")
            self.assertTrue(any("verify.py" in call for call in calls))
            self.assertFalse(any("deploy.sh" in call for call in calls))

    def test_deploy_is_not_ready_when_real_discussion_probe_is_empty(self):
        provider, store = Provider(), FakeCredentialStore()
        store.set("key")
        machines = VastInstances(store, opener=provider)
        calls = []

        def run(argv, **_kwargs):
            calls.append(argv[-1])
            return CompletedProcess(argv, 0, "" if "verify.py" in argv[-1] else "abc123", "")

        with tempfile.TemporaryDirectory() as directory:
            manager = DeploymentManager(machines, Identity(), run=run,
                state_path=Path(directory) / "states.json",
                log_path=Path(directory) / "deployment.log")
            job = manager.start(99, "deploy")
            for _ in range(100):
                result = manager.job(job["id"])
                if result["status"] != "running":
                    break
                time.sleep(.01)
            self.assertEqual(result["status"], "failed")
            self.assertEqual(result["stage"], "concept_health")
            self.assertEqual(manager.status(99)["status"], "deployment_failed")
            self.assertFalse(any("rev-parse" in command for command in calls))

    def test_rent_and_deploy_discussion_then_update(self):
        provider = Provider()
        store = FakeCredentialStore()
        store.set("key")
        offers = VastOffers(store, opener=provider)
        machines = VastInstances(store, opener=provider)
        offers.search({"disk_gb": 50})
        quote = offers.quote(71)
        image = select_base_image(quote)
        rental = machines.create(quote, image)
        self.assertEqual(rental["instance_id"], 99)
        creation = provider.calls[-1][2]
        self.assertEqual(creation["runtype"], "ssh_direct")
        self.assertEqual(creation["disk"], 50)
        self.assertIn("git clone", creation["onstart"])
        self.assertNotIn("deploy.sh", creation["onstart"])
        self.assertNotIn("env", creation)
        with self.assertRaisesRegex(VastError, "expired"):
            offers.quote(72)

        commands = []
        def run(argv, **kwargs):
            commands.append(argv)
            if "verify.py" in argv[-1]:
                return CompletedProcess(argv, 0, "远端讨论成功", "")
            return CompletedProcess(argv, 0, "abc123\n", "")

        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory) / "states.json"
            log_path = Path(directory) / "deployment.log"
            manager = DeploymentManager(machines, Identity(), run=run, state_path=state,
                                        log_path=log_path)
            with self.assertRaisesRegex(VastError, "Deploy Concept"):
                manager.start(99, "discuss", "你好")
            def complete(action, message=""):
                job = manager.start(99, action, message)
                for _ in range(100):
                    found = manager.job(job["id"])
                    if found["status"] != "running":
                        return found
                    time.sleep(.01)
                self.fail("Deployment job did not finish")
            self.assertEqual(complete("deploy")["status"], "completed")
            self.assertEqual(manager.status(99)["status"], "ready")
            self.assertEqual(complete("discuss", "你好")["reply"], "远端讨论成功")
            self.assertEqual(complete("update")["status"], "completed")
            self.assertEqual(manager.status(99)["status"], "source_updated")
            entries = [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines()]
            self.assertTrue(any(item["event"] == "vast_attach" and item["status"] == "completed"
                                for item in entries))
            self.assertTrue(any(item["event"] == "ssh_start" and item["action"] == "discuss"
                                for item in entries))
            self.assertTrue(any(item["event"] == "ssh_exit" and item["exit_code"] == 0
                                for item in entries))
            self.assertTrue(any(item["event"] == "finished" and item["action"] == "discuss"
                                for item in entries))
            self.assertNotIn("你好", log_path.read_text(encoding="utf-8"))
            self.assertNotIn("ssh-ed25519 TEST", log_path.read_text(encoding="utf-8"))
            self.assertEqual(DeploymentManager(machines, Identity(), run=run,
                                                state_path=state).status(99)["status"], "source_updated")
        self.assertTrue(any("deploy.sh" in call[-1] for call in commands))
        self.assertTrue(any("update_source.sh" in call[-1] for call in commands))
        self.assertTrue(any(call[0].endswith("/ssh") and call[2]["ssh_key"].startswith("ssh-ed25519")
                            for call in provider.calls))
        self.assertEqual(sum(call[0].endswith("/ssh") for call in provider.calls), 1)

    def test_image_requires_compatible_offer(self):
        with self.assertRaises(ValueError):
            select_base_image({"cuda_max_good": 12.1})

    def test_agent_rental_passes_credentials_as_instance_env_not_startup_script(self):
        provider, store = Provider(), FakeCredentialStore()
        store.set("key")
        machines = VastInstances(store, opener=provider)
        node_env = {"EVERSPARK_TAILSCALE_AUTH_KEY": "one-off-secret",
                    "EVERSPARK_NODE_BOOTSTRAP": "bootstrap-secret",
                    "EVERSPARK_NODE_BRIDGE_URL": "http://100.101.102.103:8766"}
        machines.create({"id": 71, "disk_gb": 50},
                        "nvidia/cuda:12.8.0-cudnn-runtime-ubuntu22.04", node_env=node_env)
        body = provider.calls[-1][2]
        self.assertEqual(body["env"], node_env)
        self.assertIn("start_node.sh", body["onstart"])
        self.assertNotIn("one-off-secret", body["onstart"])
        self.assertNotIn("bootstrap-secret", body["onstart"])

    def test_failed_job_identifies_ssh_or_pod_execution(self):
        provider, store = Provider(), FakeCredentialStore()
        store.set("key")

        def complete(manager):
            job = manager.start(99, "deploy")
            for _ in range(100):
                found = manager.job(job["id"])
                if found["status"] != "running":
                    return found
                time.sleep(.01)
            self.fail("Deployment job did not finish")

        with tempfile.TemporaryDirectory() as directory:
            machines = VastInstances(store, opener=provider)
            log_path = Path(directory) / "deployment.log"
            manager = DeploymentManager(machines, Identity(), state_path=Path(directory) / "states.json",
                log_path=log_path,
                run=lambda args, **kw: CompletedProcess(args, 255, "", "Permission denied (publickey)."))
            failed = complete(manager)
            self.assertEqual(failed["stage"], "ssh_connection")
            self.assertEqual(failed["exit_code"], 255)
            self.assertIn("Permission denied", failed["detail"])

            manager.run = lambda args, **kw: CompletedProcess(args, 1, "", "zstd: command not found")
            failed = complete(manager)
            self.assertEqual(failed["stage"], "remote_execution")
            self.assertEqual(failed["exit_code"], 1)
            self.assertIn("zstd", failed["detail"])

            def unexpected(argv, **kwargs):
                self.assertEqual(kwargs["encoding"], "utf-8")
                self.assertEqual(kwargs["stdin"], subprocess.DEVNULL)
                raise AttributeError("Unexpected SSH process failure")
            manager.run = unexpected
            failed = complete(manager)
            self.assertEqual(failed["status"], "failed")
            self.assertEqual(failed["stage"], "remote_execution")
            self.assertIn("Unexpected SSH", failed["detail"])
            entries = [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines()]
            self.assertTrue(any(item["event"] == "ssh_error" and
                                item["error_type"] == "AttributeError" for item in entries))
            self.assertTrue(any(item["event"] == "finished" and
                                item["status"] == "failed" for item in entries))
            self.assertNotIn("Permission denied", log_path.read_text(encoding="utf-8"))

    def test_rejected_duplicate_key_is_accepted_only_after_ssh_proof(self):
        class DuplicateKeyProvider(Provider):
            def __call__(self, request, timeout):
                if request.full_url.endswith("/instances/99/ssh"):
                    return io.BytesIO(json.dumps({"success": False,
                        "error": "SSH key already attached"}).encode())
                return super().__call__(request, timeout)

        provider, store = DuplicateKeyProvider(), FakeCredentialStore()
        store.set("key")
        machines = VastInstances(store, opener=provider)
        with self.assertRaisesRegex(VastError, "already attached"):
            machines.attach_ssh(99, "ssh-ed25519 TEST")
        calls = []
        def run(argv, **kwargs):
            calls.append(argv[-1])
            return CompletedProcess(argv, 0, "abc123", "")
        with tempfile.TemporaryDirectory() as directory:
            manager = DeploymentManager(machines, Identity(), run=run,
                state_path=Path(directory) / "states.json")
            job = manager.start(99, "deploy")
            for _ in range(100):
                found = manager.job(job["id"])
                if found["status"] != "running":
                    break
                time.sleep(.01)
            self.assertEqual(found["status"], "completed")
            self.assertEqual(calls[0], "true")
            self.assertTrue(any("deploy.sh" in command for command in calls))

            manager.run = lambda argv, **kwargs: CompletedProcess(argv, 255, "", "Permission denied")
            manager.states[99] = {"status": "not_deployed"}
            failed = manager.start(99, "deploy")
            for _ in range(100):
                found = manager.job(failed["id"])
                if found["status"] != "running":
                    break
                time.sleep(.01)
            self.assertEqual(found["status"], "failed")
            self.assertEqual(found["stage"], "ssh_probe")
            self.assertIn("already attached", found["detail"])

    def test_one_instance_runs_one_remote_task_at_a_time(self):
        provider, store = Provider(), FakeCredentialStore()
        store.set("key")
        started, release = threading.Event(), threading.Event()

        def run(argv, **kwargs):
            started.set()
            release.wait(2)
            return CompletedProcess(argv, 0, "abc123", "")

        with tempfile.TemporaryDirectory() as directory:
            manager = DeploymentManager(VastInstances(store, opener=provider), Identity(),
                run=run, state_path=Path(directory) / "states.json")
            job = manager.start(99, "deploy")
            try:
                self.assertTrue(started.wait(2))
                active = manager.job(job["id"])
                self.assertEqual(active["stage"], "remote_execution")
                self.assertTrue(active["stage_at"])
                self.assertTrue(any("test_vast_deployment.py" in frame
                                    for frame in active["worker_stack"]))
                with self.assertRaisesRegex(VastError, "running task"):
                    manager.start(99, "update")
            finally:
                release.set()
            for _ in range(100):
                if manager.job(job["id"])["status"] != "running":
                    break
                time.sleep(.01)
            self.assertEqual(manager.job(job["id"])["status"], "completed")

    def test_portal_gate_rent_and_deployment_routes(self):
        store, provider = FakeCredentialStore(), Provider()
        store.set("key")
        machines, offers = VastInstances(store, opener=provider), VastOffers(store, opener=provider)
        with tempfile.TemporaryDirectory() as directory:
            manager = DeploymentManager(machines, Identity(),
                run=lambda args, **kw: CompletedProcess(args, 0, "abc123", ""),
                state_path=Path(directory) / "states.json")
            gate = ControlServer(("127.0.0.1", 0), machines, offers, manager)
            portal = WebUIServer(Settings(port=0, control_url=f"http://127.0.0.1:{gate.server_port}"))
            workers = [threading.Thread(target=server.serve_forever, daemon=True)
                       for server in (gate, portal)]
            for worker in workers: worker.start()
            url = f"http://127.0.0.1:{portal.server_port}"
            try:
                def post(path, body, headers=None):
                    request = Request(url + path, data=json.dumps(body).encode(),
                        headers={"Content-Type": "application/json", **(headers or {})})
                    with urlopen(request) as response: return json.load(response)
                post("/api/machines/vast/offers", {"disk_gb": 50})
                with self.assertRaises(HTTPError) as forbidden:
                    post("/api/machines/vast/rent", {"offer_id": 71},
                         {"Origin": "https://example.invalid"})
                self.assertEqual(forbidden.exception.code, 403)
                self.assertEqual(post("/api/machines/vast/rent", {"offer_id": 71})["instance_id"], 99)
                job = post("/api/machines/vast/deploy", {"instance_id": 99})["job"]
                for _ in range(100):
                    with urlopen(url + f"/api/machines/vast/deployment-job?id={job['id']}") as response:
                        status = json.load(response)["job"]["status"]
                    if status != "running": break
                    time.sleep(.01)
                self.assertEqual(status, "completed")
                check = post("/api/machines/vast/verify", {"instance_id": 99})["job"]
                for _ in range(100):
                    with urlopen(url + f"/api/machines/vast/deployment-job?id={check['id']}") as response:
                        checked = json.load(response)["job"]["status"]
                    if checked != "running": break
                    time.sleep(.01)
                self.assertEqual(checked, "completed")
                with self.assertRaises(HTTPError) as arbitrary:
                    post("/api/machines/vast/rent", {"offer_id": 72})
                self.assertEqual(arbitrary.exception.code, 409)
            finally:
                for server in (portal, gate):
                    server.shutdown(); server.server_close()
                for worker in workers: worker.join(timeout=3)


if __name__ == "__main__":
    unittest.main()
