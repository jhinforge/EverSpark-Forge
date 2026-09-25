from __future__ import annotations

import json
import stat
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "ConceptForge"))

from concept_forge.connections import ConceptConnections  # noqa: E402
from concept_forge.service import ConceptService  # noqa: E402


class CompatibleHandler(BaseHTTPRequestHandler):
    requests = []

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        self.requests.append((self.path, body, self.headers.get("Authorization")))
        if self.headers.get("Authorization") != "Bearer private-key":
            self.send_error(401)
            return
        if body.get("response_format"):
            content = json.dumps({"model": "illustrious", "positive_prompt": "portrait",
                                  "negative_prompt": "artifact", "count": 1, "status": "over"})
        else:
            content = "OK"
        data = json.dumps({"choices": [{"message": {"content": content}}]}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *_args):
        pass


class ModelConnectionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), CompatibleHandler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        CompatibleHandler.requests = []
        self.path = Path(self.tmp.name) / "connections.json"
        self.config = {"provider": "ollama", "providers": {
            "ollama": {"base_url": "http://127.0.0.1:11434", "model": "local"}}}
        self.manager = ConceptConnections(self.config, self.path)
        self.payload = {"name": "Testing", "base_url": f"http://127.0.0.1:{self.server.server_port}/v1",
                        "api_key": "private-key", "model": "actual-model", "json_mode": True}

    def test_connection_persists_privately_and_routes_generated_prompts(self):
        self.assertTrue(self.manager.test(self.payload)["connected"])
        public = self.manager.save(self.payload)
        identifier = public["connections"][-1]["id"]
        self.assertNotIn("private-key", json.dumps(public))
        self.assertEqual(stat.S_IMODE(self.path.stat().st_mode), 0o600)
        self.assertEqual(ConceptService(self.manager.gateway).discuss(
            "hello", model="actual-model", provider=identifier), "OK")
        self.manager.set_default(identifier)
        restored = ConceptConnections(self.config, self.path)
        self.assertEqual(restored.gateway.default, identifier)
        plan = ConceptService(restored.gateway).generate_prompt("draw a portrait")
        self.assertEqual(plan.positive_prompt, "portrait")
        path, request, auth = CompatibleHandler.requests[-1]
        self.assertEqual(path, "/v1/chat/completions")
        self.assertEqual(request["model"], "actual-model")
        self.assertEqual(request["response_format"], {"type": "json_object"})
        self.assertEqual(auth, "Bearer private-key")
        edited = self.manager.save({**self.payload, "id": identifier, "api_key": "", "name": "Renamed"})
        self.assertEqual(edited["connections"][-1]["name"], "Renamed")
        self.assertNotIn("private-key", json.dumps(edited))
        self.manager.remove(identifier)
        self.assertEqual(self.manager.gateway.default, "ollama")

    def test_rejects_insecure_remote_url_without_persisting_key(self):
        with self.assertRaisesRegex(ValueError, "HTTPS"):
            self.manager.save({**self.payload, "base_url": "http://remote.example/v1"})
        self.assertFalse(self.path.exists())


if __name__ == "__main__":
    unittest.main()
