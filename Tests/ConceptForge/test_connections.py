from __future__ import annotations

import json
import logging
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
from concept_forge.port import ConceptError  # noqa: E402
from concept_forge.service import ConceptService  # noqa: E402
sys.path.insert(0, str(REPO_ROOT / "Runtime/Logging"))
from everspark_logging import LogConfig, get_logger  # noqa: E402


class CompatibleHandler(BaseHTTPRequestHandler):
    requests = []

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        self.requests.append((self.path, body, self.headers.get("Authorization")))
        if self.headers.get("Authorization") != "Bearer private-key":
            self.send_error(401)
            return
        if body["model"] == "gateway-error":
            data = json.dumps({"error": {"message":
                "Gateway rejected Bearer private-key (key: private-key)"}}).encode()
            self.send_response(502)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return
        if body["model"] == "html-error":
            self.send_error(502, "Proxy error")
            return
        if body["model"] == "flat-error":
            data = json.dumps({"code": "UPSTREAM_FAILURE", "message": "Route unavailable"}).encode()
            self.send_response(502)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return
        if body["model"] == "forbidden":
            self.send_error(403)
            return
        if body["model"] == "no-json-mode" and body.get("response_format"):
            self.send_error(400, "Unsupported response_format")
            return
        if body["model"] == "stream-required":
            if not body.get("stream"):
                self.send_error(502, "Streaming required")
                return
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            self.wfile.write(b'data: {"choices":[{"delta":{"role":"assistant"}}]}\n\n')
            self.wfile.write(b'data: {"choices":[{"delta":{"content":"O"}}]}\n\n')
            self.wfile.write(b'data: {"choices":[{"delta":{"content":"K"}}]}\n\n')
            self.wfile.write(b'data: {"choices":[],"usage":{"total_tokens":3}}\n\n')
            self.wfile.write(b'data: [DONE]\n\n')
            return
        if body["model"] == "broken-stream":
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            self.wfile.write(b'data: {"choices":[{"delta":{"content":"partial"}}]}\n\n')
            return
        if body.get("response_format") or body["model"] == "no-json-mode":
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

    def test_provider_error_is_visible_without_leaking_key(self):
        with self.assertRaises(ConceptError) as raised:
            self.manager.test({**self.payload, "model": "gateway-error"})
        self.assertIn("OpenAI Compatible HTTP 502: Gateway rejected", str(raised.exception))
        self.assertNotIn("private-key", str(raised.exception))
        with self.assertRaisesRegex(ConceptError, "^OpenAI Compatible HTTP 502$"):
            self.manager.test({**self.payload, "model": "html-error"})
        with self.assertRaisesRegex(ConceptError, "OpenAI Compatible HTTP 502: Route unavailable"):
            self.manager.test({**self.payload, "model": "flat-error"})

    def test_provider_error_is_logged_in_concept_layer_without_key(self):
        log = Path(self.tmp.name) / "concept/conceptforge.log"
        logger = get_logger("conceptforge", log,
                            config=LogConfig(logging.INFO, "json", False, "test-run"))
        try:
            manager = ConceptConnections(self.config, self.path, logger=logger)
            with self.assertRaises(ConceptError):
                manager.test({**self.payload, "model": "gateway-error", "_trace_id": "test-123"})
        finally:
            logger.close()
        records = [json.loads(line) for line in log.read_text().splitlines()]
        self.assertEqual([record["event"] for record in records],
                         ["api.request", "api.http_error"] * 2)
        self.assertEqual(records[1]["fields"]["http_status"], 502)
        self.assertEqual(records[1]["fields"]["trace_id"], "test-123")
        self.assertNotIn("private-key", log.read_text())

    def test_streaming_fallback_collects_chunks_without_user_setting(self):
        payload = {**self.payload, "model": "stream-required", "json_mode": False}
        self.assertTrue(self.manager.test(payload)["connected"])
        self.assertEqual([entry[1]["stream"] for entry in CompatibleHandler.requests],
                         [False, True])
        public = self.manager.save(payload)
        identifier = public["connections"][-1]["id"]
        self.assertFalse(public["connections"][-1]["stream"])
        restored = ConceptConnections(self.config, self.path)
        self.assertEqual(ConceptService(restored.gateway).discuss(
            "hello", provider=identifier), "OK")
        _, request, _ = CompatibleHandler.requests[-1]
        self.assertTrue(request["stream"])
        self.assertEqual(request["stream_options"], {"include_usage": True})
        before = len(CompatibleHandler.requests)
        self.assertEqual(ConceptService(restored.gateway).discuss(
            "hello again", provider=identifier), "OK")
        self.assertEqual(len(CompatibleHandler.requests), before + 1)
        with self.assertRaisesRegex(ConceptError, "invalid stream"):
            self.manager.test({**payload, "model": "broken-stream", "stream": True})

    def test_json_mode_falls_back_without_response_format(self):
        public = self.manager.save({**self.payload, "model": "no-json-mode"})
        identifier = public["connections"][-1]["id"]
        service = ConceptService(self.manager.gateway)
        self.assertEqual(service.generate_prompt("draw", provider=identifier).positive_prompt,
                         "portrait")
        self.assertEqual([bool(entry[1].get("response_format")) for entry in
                          CompatibleHandler.requests], [True, False])

    def test_forbidden_does_not_retry(self):
        with self.assertRaisesRegex(ConceptError, "HTTP 403"):
            self.manager.test({**self.payload, "model": "forbidden"})
        self.assertEqual(len(CompatibleHandler.requests), 1)


if __name__ == "__main__":
    unittest.main()
