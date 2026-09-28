from __future__ import annotations

import io
import json
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
        else:
            raise AssertionError(url)
        return io.BytesIO(json.dumps(result).encode())


class Identity:
    private_key = Path("/tmp/test-private-key")
    known_hosts = Path("/tmp/test-known-hosts")

    def public_key(self):
        return "ssh-ed25519 TEST"


class DeploymentTests(unittest.TestCase):
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
            manager = DeploymentManager(machines, Identity(), run=run, state_path=state)
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
            self.assertEqual(DeploymentManager(machines, Identity(), run=run,
                                                state_path=state).status(99)["status"], "source_updated")
        self.assertTrue(any("deploy.sh" in call[-1] for call in commands))
        self.assertTrue(any("update_source.sh" in call[-1] for call in commands))
        self.assertTrue(any(call[0].endswith("/ssh") and call[2]["ssh_key"].startswith("ssh-ed25519")
                            for call in provider.calls))

    def test_image_requires_compatible_offer(self):
        with self.assertRaises(ValueError):
            select_base_image({"cuda_max_good": 12.1})

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
            manager = DeploymentManager(machines, Identity(), state_path=Path(directory) / "states.json",
                run=lambda args, **kw: CompletedProcess(args, 255, "", "Permission denied (publickey)."))
            failed = complete(manager)
            self.assertEqual(failed["stage"], "ssh_connection")
            self.assertEqual(failed["exit_code"], 255)
            self.assertIn("Permission denied", failed["detail"])

            manager.run = lambda args, **kw: CompletedProcess(args, 1, "", "zstd: command not found")
            failed = complete(manager)
            self.assertEqual(failed["stage"], "pod_command")
            self.assertEqual(failed["exit_code"], 1)
            self.assertIn("zstd", failed["detail"])

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
                with self.assertRaises(HTTPError) as arbitrary:
                    post("/api/machines/vast/rent", {"offer_id": 72})
                self.assertEqual(arbitrary.exception.code, 409)
            finally:
                for server in (portal, gate):
                    server.shutdown(); server.server_close()
                for worker in workers: worker.join(timeout=3)


if __name__ == "__main__":
    unittest.main()
