from __future__ import annotations

import io
import json
import threading
import unittest
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlsplit
from urllib.request import Request, urlopen

import sys
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from Archon.Gate.control_server import ControlServer
from Archon.Portal.app import Settings, WebUIServer
from Archon.Steward.vast_instances import VastError, VastInstances
from Archon.Steward.vast_offers import VastOffers


class FakeCredentialStore:
    def __init__(self):
        self.key = None

    def get(self):
        return self.key

    def set(self, value):
        self.key = value

    def delete(self):
        self.key = None


class FakeVast:
    def __init__(self):
        self.calls = []

    def __call__(self, request, timeout):
        self.calls.append((request.full_url, request.get_header("Authorization"), timeout))
        if request.get_header("Authorization") == "Bearer bad-key":
            raise HTTPError(request.full_url, 401, "Unauthorized", {}, None)
        if request.full_url.endswith("/users/current"):
            return io.BytesIO(json.dumps({"balance": 12.345, "email": "private@example.com",
                                          "ssh_key": "private-key"}).encode())
        if request.get_method() == "DELETE":
            return io.BytesIO(b'{"success": true, "msg": "Instance destroyed successfully"}')
        cursor = parse_qs(urlsplit(request.full_url).query).get("after_token", [""])[0]
        payload = {"success": True, "total_instances": 2,
                   "next_token": "next+/=" if not cursor else None,
                   "instances": [{"id": 1 if not cursor else 2, "label": "GPU node",
                                  "actual_status": "running", "gpu_name": "RTX 3090",
                                  "num_gpus": 1, "dph_total": 0.35,
                                  "extra_env": [["SECRET", "leak-me"]],
                                  "jupyter_token": "leak-me"}]}
        return io.BytesIO(json.dumps(payload).encode())


class FakeOffers:
    def __init__(self):
        self.calls = []

    def __call__(self, request, timeout):
        query = json.loads(request.data) if request.data else None
        self.calls.append((request.full_url, request.get_header("Authorization"), query))
        if request.full_url.endswith("/gpu_names/unique/"):
            return io.BytesIO(json.dumps({"gpu_names": ["RTX 3090", "RTX 4090"]}).encode())
        payload = {"offers": [{"id": 71, "gpu_name": "RTX 3090", "num_gpus": 1,
                               "gpu_ram": 24576, "geolocation": "Tokyo, JP",
                               "dph_total": 0.42, "reliability": 0.99,
                               "disk_space": 120, "storage_cost": 0.05,
                               "secret": "must-not-leak"}]}
        return io.BytesIO(json.dumps(payload).encode())


class VastMachineTests(unittest.TestCase):
    def test_balance_is_allowlisted_and_destroy_requires_provider_confirmation(self):
        store, provider = FakeCredentialStore(), FakeVast()
        store.set("test-key")
        machines = VastInstances(store, opener=provider)
        self.assertEqual(machines.balance(), {"balance_usd": 12.345})
        self.assertNotIn("private@example.com", json.dumps(machines.balance()))
        with self.assertRaises(VastError) as invalid:
            machines.destroy(True)
        self.assertEqual(invalid.exception.status, 400)
        machines.destroy(23)
        self.assertEqual(provider.calls[-1][0], "https://console.vast.ai/api/v0/instances/23")

        def unconfirmed(request, timeout):
            return io.BytesIO(b'{"success": false}')
        with self.assertRaisesRegex(VastError, "did not confirm"):
            VastInstances(store, opener=unconfirmed).destroy(23)

    def test_missing_instance_is_distinct_from_provider_failure(self):
        store = FakeCredentialStore()
        store.set("key")

        def missing(request, timeout):
            raise HTTPError(request.full_url, 404, "Not Found", {}, None)

        with self.assertRaises(VastError) as gone:
            VastInstances(store, opener=missing).one(99)
        self.assertEqual(gone.exception.status, 404)

    def test_validation_persistence_pagination_and_response_allowlist(self):
        store, provider = FakeCredentialStore(), FakeVast()
        machines = VastInstances(store, opener=provider)
        with self.assertRaisesRegex(VastError, "rejected"):
            machines.save("bad-key")
        self.assertIsNone(store.get())
        machines.save("test-key")
        self.assertEqual(store.get(), "test-key")
        with self.assertRaisesRegex(VastError, "rejected"):
            machines.save("bad-key")
        self.assertEqual(store.get(), "test-key")
        restarted = VastInstances(store, opener=provider)
        first = restarted.list()
        second = restarted.list(first["next_token"])
        self.assertEqual([first["instances"][0]["id"], second["instances"][0]["id"]], [1, 2])
        self.assertNotIn("leak-me", json.dumps(first))
        self.assertEqual(provider.calls[0][1], "Bearer bad-key")
        self.assertEqual(provider.calls[-1][1], "Bearer test-key")
        self.assertIn("after_token=next%2B%2F%3D", provider.calls[-1][0])
        with self.assertRaises(VastError):
            restarted.list("../../")
        restarted.remove()
        self.assertIsNone(store.get())

    def test_portal_gate_machine_path_and_origin(self):
        store, provider, market = FakeCredentialStore(), FakeVast(), FakeOffers()
        backend = ControlServer(("127.0.0.1", 0), VastInstances(store, opener=provider),
                                VastOffers(store, opener=market))
        portal = WebUIServer(Settings(port=0,
            control_url=f"http://127.0.0.1:{backend.server_port}"))
        workers = [threading.Thread(target=server.serve_forever, daemon=True)
                   for server in (backend, portal)]
        for worker in workers:
            worker.start()
        url = f"http://127.0.0.1:{portal.server_port}"
        try:
            def get(path):
                with urlopen(url + path) as response:
                    return json.load(response)

            def post(path, body, headers=None):
                request = Request(url + path, data=json.dumps(body).encode(), method="POST",
                    headers={"Content-Type": "application/json", **(headers or {})})
                with urlopen(request) as response:
                    return json.load(response)

            self.assertFalse(get("/api/machines/vast/credential")["configured"])
            with self.assertRaises(HTTPError) as forbidden:
                post("/api/machines/vast/credential", {"key": "test-key"},
                     {"Origin": "https://example.invalid"})
            self.assertEqual(forbidden.exception.code, 403)
            self.assertIsNone(store.get())
            with self.assertRaises(HTTPError) as invalid_type:
                urlopen(Request(url + "/api/machines/vast/credential",
                                data=b'{"key":"test-key"}',
                                headers={"Content-Type": "text/plain"}), timeout=3)
            self.assertEqual(invalid_type.exception.code, 415)
            self.assertIsNone(store.get())
            saved = post("/api/machines/vast/credential", {"key": "test-key"})
            self.assertTrue(saved["configured"])
            self.assertEqual(saved["instances"][0]["id"], 1)
            self.assertNotIn("test-key", json.dumps(saved))
            self.assertNotIn("leak-me", json.dumps(saved))
            self.assertNotIn("test-key", json.dumps(get("/api/machines/vast/credential")))
            page = get("/api/machines/vast/instances")
            self.assertEqual(page["instances"][0]["gpu_name"], "RTX 3090")
            self.assertNotIn("leak-me", json.dumps(page))
            self.assertEqual(get("/api/machines/vast/balance")["balance_usd"], 12.345)
            self.assertNotIn("private@example.com", json.dumps(get("/api/machines/vast/balance")))
            with self.assertRaises(HTTPError) as invalid_destroy:
                post("/api/machines/vast/destroy", {"instance_id": True})
            self.assertEqual(invalid_destroy.exception.code, 400)
            with self.assertRaises(HTTPError) as forbidden_destroy:
                post("/api/machines/vast/destroy", {"instance_id": 23},
                     {"Origin": "https://example.invalid"})
            self.assertEqual(forbidden_destroy.exception.code, 403)
            self.assertEqual(post("/api/machines/vast/destroy", {"instance_id": 23}),
                             {"ok": True, "instance_id": 23})
            self.assertIn("RTX 3090", get("/api/machines/vast/gpu-names")["gpu_names"])
            offers = post("/api/machines/vast/offers", {
                "gpu_name": "rtx 3090", "num_gpus": 2, "country": "jp", "min_gpu_ram_gb": 24,
                "max_hourly_usd": 0.5, "min_reliability": 0.98, "disk_gb": 50,
                "sort": "price",
            })
            self.assertEqual(offers["offers"][0]["id"], 71)
            self.assertEqual(offers["disk_gb"], 50)
            self.assertNotIn("must-not-leak", json.dumps(offers))
            self.assertEqual(market.calls[-1][1], "Bearer test-key")
            query = market.calls[-1][2]
            self.assertEqual(query["gpu_name"], {"eq": "RTX 3090"})
            self.assertEqual(query["num_gpus"], {"eq": 2})
            self.assertEqual(query["geolocation"], {"eq": "JP"})
            self.assertEqual(query["gpu_ram"], {"gte": 24000})
            self.assertEqual(query["allocated_storage"], 50)
            self.assertEqual(query["dph_total"], {"lte": 0.5})
            self.assertEqual(query["order"], [["dph_total", "asc"]])
            self.assertEqual(query["rentable"], {"eq": True})
            post("/api/machines/vast/offers", {"gpu_name": "3090"})
            self.assertEqual(market.calls[-1][2]["gpu_name"], {"eq": "RTX 3090"})
            post("/api/machines/vast/offers", {"gpu_name": "RTX_3090"})
            self.assertEqual(market.calls[-1][2]["gpu_name"], {"eq": "RTX 3090"})
            with self.assertRaises(HTTPError) as bad_filter:
                post("/api/machines/vast/offers", {"country": "../../"})
            self.assertEqual(bad_filter.exception.code, 400)
            with self.assertRaises(HTTPError) as bad_count:
                post("/api/machines/vast/offers", {"num_gpus": 1.5})
            self.assertEqual(bad_count.exception.code, 400)
            with self.assertRaises(HTTPError) as forbidden_offer:
                post("/api/machines/vast/offers", {}, {"Origin": "https://example.invalid"})
            self.assertEqual(forbidden_offer.exception.code, 403)
            self.assertEqual(len([call for call in market.calls if call[2] is not None]), 3)
            with urlopen(url + "/") as response:
                self.assertIn(b'id="machinesView"', response.read())
            post("/api/machines/vast/credential/remove", {})
            self.assertFalse(get("/api/machines/vast/credential")["configured"])
            with self.assertRaises(HTTPError) as missing_key:
                post("/api/machines/vast/offers", {})
            self.assertEqual(missing_key.exception.code, 409)
        finally:
            for server in (portal, backend):
                server.shutdown()
                server.server_close()
            for worker in workers:
                worker.join(timeout=3)


if __name__ == "__main__":
    unittest.main()
