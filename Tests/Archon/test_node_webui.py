"""WebUI bootstrap setup and rental admission, using real Portal/Gate HTTP routes."""
import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from Archon.Gate.control_server import ControlServer
from Archon.Portal.app import Settings, WebUIServer
from Archon.Steward.NodeManager import NodeManager
from Archon.Steward.DeploymentManager.providers.vast_nodes import VastNodes
from Legate.Envoy.transport import Transport
from test_node_registration import INFO


class NodeWebUITests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.nodes = NodeManager("127.0.0.1", 0)
        self.nodes.start()
        self.bridge = VastNodes(self.nodes)
        self.rentals = []
        owner = self
        class Machines:
            def create(self, offer, image, node_env=None):
                owner.rentals.append(node_env)
                return {"instance_id": 99}
        class Offers:
            def quote(self, offer_id):
                return {"id": offer_id, "cuda_max_good": 12.8}
        deployments = type("Deployments", (), {"bridge": self.bridge})()
        self.gate = ControlServer(("127.0.0.1", 0), Machines(), Offers(), deployments, node_manager=self.nodes)
        self.portal = WebUIServer(Settings(port=0, control_url=f"http://127.0.0.1:{self.gate.server_port}"))
        self.workers = []
        for server in (self.gate, self.portal):
            worker = threading.Thread(target=server.serve_forever, daemon=True)
            worker.start(); self.workers.append(worker)
        self.url = f"http://127.0.0.1:{self.portal.server_port}"

    def tearDown(self):
        for server in (self.portal, self.gate):
            server.shutdown(); server.server_close()
        for worker in self.workers:
            worker.join(5)
        self.nodes.close()
        self.directory.cleanup()

    def call(self, path, body=None):
        request = Request(self.url+"/api/machines/vast/"+path,
                          data=json.dumps(body).encode() if body is not None else None,
                          headers={"Content-Type": "application/json"})
        with urlopen(request) as response:
            return json.load(response)

    def test_webui_blocks_rental_before_agent_bootstrap_is_configured(self):
        self.assertFalse(self.call("node-connection")["ready"])
        with self.assertRaises(HTTPError) as blocked:
            self.call("rent", {"offer_id": 71, "require_agent": True})
        self.assertEqual(blocked.exception.code, 409)
        self.assertEqual(self.rentals, [])

    def test_webui_configures_then_rents_and_agent_registers_without_provider_identity(self):
        key = "tskey-auth-test-fresh-key-12345"
        original_url = self.nodes.url
        def listener(host):
            self.nodes.url = f"http://{host}:{self.nodes.server.server_port}"
        with patch("Archon.Steward.DeploymentManager.providers.onboarding.tailscale_ip", return_value="100.64.0.9"), patch.object(self.nodes, "listen_on", side_effect=listener):
            response = self.call("node-connection", {"key": key})
        self.assertTrue(response["ready"])
        self.assertNotIn(key, json.dumps(response))
        self.assertNotIn(key, json.dumps(self.call("node-connection")))
        result = self.call("rent", {"offer_id": 71, "require_agent": True})
        self.assertEqual(result["node_mode"], "agent")
        environment = self.rentals[0]
        self.assertEqual(environment["EVERSPARK_TAILSCALE_AUTH_KEY"], key)
        self.assertIn("EVERSPARK_NODE_JOIN_TOKEN", environment)
        self.assertNotIn("CONTAINER_ID", environment)
        response = Transport(original_url).request("/node/register", {
            "join_token": environment["EVERSPARK_NODE_JOIN_TOKEN"], "enrollment_id": "a"*32, "runtime_id": "b"*32, "info": INFO})
        self.assertEqual(self.bridge.status(99)["node_id"], response["node_id"])
        self.assertFalse(self.call("node-connection")["ready"])
        with self.assertRaises(HTTPError):
            self.call("rent", {"offer_id": 71, "require_agent": True})
        self.assertEqual(len(self.rentals), 1)

    def test_listener_change_preserves_node_identity_and_session(self):
        old_url = self.nodes.url
        response = Transport(old_url).request("/node/register", {
            "join_token": self.nodes.issue_join_token(), "enrollment_id": "a"*32, "runtime_id": "b"*32, "info": INFO})
        self.nodes.listen_on("127.0.0.2")
        result = Transport(self.nodes.url).request("/node/heartbeat", {
            **{key: response[key] for key in ("node_id", "runtime_id", "session")}, "allocatable": INFO["resources"]["allocatable"]})
        self.assertEqual(result["status"], "online")
        self.assertEqual(self.nodes.status(response["node_id"])["node_id"], response["node_id"])
