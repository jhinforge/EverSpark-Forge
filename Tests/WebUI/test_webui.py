from __future__ import annotations

import importlib.util
import io
import json
import sys
import tempfile
import threading
import unittest
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlparse
from urllib.request import Request, urlopen


REPO_ROOT = Path(__file__).resolve().parents[2]
APP_PATH = REPO_ROOT / "WebUI" / "app.py"
sys.path.insert(0, str(REPO_ROOT / "Runtime" / "Logging"))
SPEC = importlib.util.spec_from_file_location("everspark_webui", APP_PATH)
assert SPEC and SPEC.loader
app = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = app
SPEC.loader.exec_module(app)

PNG_BYTES = b"\x89PNG\r\n\x1a\npublic-test-image"


class ParsingTests(unittest.TestCase):
    def test_extracts_image_and_builds_local_proxy_url(self) -> None:
        images = app.extract_images(
            {
                "outputs": {
                    "9": {
                        "images": [
                            {
                                "filename": "EverSpark_00001.png",
                                "subfolder": "batch",
                                "type": "output",
                            }
                        ]
                    }
                }
            }
        )
        self.assertEqual(images[0]["node_id"], "9")
        self.assertIn("/api/image/view?", images[0]["url"])
        self.assertIn("subfolder=batch", images[0]["url"])
        self.assertEqual(app.history_status({}, images), "completed")

    def test_failed_and_running_history_states(self) -> None:
        self.assertEqual(
            app.history_status({"status": {"status_str": "error"}}, []),
            "failed",
        )
        self.assertEqual(app.history_status({}, []), "running")


class MockUpstreamHandler(BaseHTTPRequestHandler):
    received_task: dict | None = None
    revision = 1

    @classmethod
    def subject(cls) -> dict:
        return {
            "schema_version": "1.0",
            "document_type": "character_subject",
            "subject_id": "ember-keeper",
            "revision": cls.revision,
            "identity": {
                "display_name": "Ember Keeper",
                "aliases": [],
                "species": "human",
                "age_descriptor": "young adult",
                "gender_presentation": "woman",
            },
            "appearance": {
                "body": {"build": "slender", "height_descriptor": "tall", "skin_tone": "warm"},
                "face": {"shape": "oval", "eye_color": "amber", "eye_style": "sharp"},
                "hair": {"color": "black", "length": "long", "style": "straight"},
                "distinguishing_features": [],
            },
            "wardrobe": {"default_outfit": "black coat", "items": [], "accessories": []},
            "prompt_contract": {"positive_terms": [], "negative_terms": [], "locked_traits": [], "flexible_traits": []},
            "metadata": {"tags": [], "notes": ""},
        }

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        query = parse_qs(parsed.query)
        if parsed.path in {"/health", "/system_stats"}:
            self._json(200, {"ok": True})
        elif parsed.path == "/resources":
            self._json(
                200,
                {
                    "ok": True,
                    "workflows": [
                        {
                            "id": "base-illustrious",
                            "name": "Base Illustrious",
                            "supports": {"lora_injection": True},
                        }
                    ],
                    "checkpoints": ["base.safetensors"],
                    "loras": ["style.safetensors"],
                    "llms": ["concept:latest"],
                    "defaults": {
                        "workflow": "base-illustrious",
                        "checkpoint": "base.safetensors",
                        "llm": "concept:latest",
                    },
                },
            )
        elif parsed.path == "/storage/resources":
            self._json(
                200,
                {
                    "ok": True,
                    "enabled": True,
                    "backend": "rclone",
                    "image": {
                        "checkpoint": [{"name": "remote.safetensors", "installed": False}],
                        "diffusion_model": [],
                        "lora": [],
                    },
                    "concept": {"models": [{"name": "gemma3test:latest", "installed": False}]},
                },
            )
        elif parsed.path == "/storage/jobs":
            self._json(
                200,
                {
                    "ok": True,
                    "job": {
                        "job_id": query.get("job_id", [""])[0],
                        "name": "remote.safetensors",
                        "status": "completed",
                        "progress": {"completed": 1, "total": 1},
                    },
                },
            )
        elif parsed.path == "/subjects" and query.get("subject_id"):
            self._json(200, {"ok": True, "document": self.subject()})
        elif parsed.path == "/subjects":
            self._json(
                200,
                {
                    "ok": True,
                    "subjects": [
                        {
                            "subject_id": "ember-keeper",
                            "revision": self.revision,
                            "display_name": "Ember Keeper",
                            "created_at": "2026-01-01T00:00:00+00:00",
                            "updated_at": "2026-01-01T00:00:00+00:00",
                        }
                    ],
                },
            )
        elif parsed.path == "/subjects/revisions":
            self._json(
                200,
                {
                    "ok": True,
                    "subject_id": "ember-keeper",
                    "revisions": [
                        {
                            "revision": self.revision,
                            "document": self.subject(),
                            "created_at": "2026-01-01T00:00:00+00:00",
                        }
                    ],
                },
            )
        elif parsed.path == "/subjects/current":
            self._json(200, {"ok": True, "session_id": query.get("session_id", [""])[0], "document": self.subject()})
        elif parsed.path == "/memory/history":
            self._json(200, {"ok": True, "messages": []})
        elif parsed.path == "/history/prompt-1":
            self._json(
                200,
                {
                    "prompt-1": {
                        "outputs": {
                            "9": {
                                "images": [
                                    {
                                        "filename": "EverSpark_00001.png",
                                        "subfolder": "",
                                        "type": "output",
                                    }
                                ]
                            }
                        }
                    }
                },
            )
        elif parsed.path == "/history":
            self._json(
                200,
                {
                    "prompt-1": {
                        "outputs": {
                            "9": {
                                "images": [
                                    {
                                        "filename": "EverSpark_00001.png",
                                        "subfolder": "",
                                        "type": "output",
                                    }
                                ]
                            }
                        }
                    }
                },
            )
        elif parsed.path == "/view":
            self.send_response(200)
            self.send_header("Content-Type", "image/png")
            self.send_header("Content-Length", str(len(PNG_BYTES)))
            self.end_headers()
            self.wfile.write(PNG_BYTES)
        else:
            self._json(404, {"ok": False, "error": "Not found"})

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", "0"))
        payload = json.loads(self.rfile.read(length).decode("utf-8"))
        if self.path == "/tasks":
            type(self).received_task = payload
            self._json(
                200,
                {
                    "ok": True,
                    "result": {
                        "count": 1,
                        "items": [{"index": 1, "prompt_id": "prompt-1", "seed": 7}],
                        "subject": {"subject_id": payload.get("subject_id"), "revision": self.revision},
                    },
                },
            )
        elif self.path == "/conversation":
            self._json(
                200,
                {"ok": True, "reply": "Tell me more about the character.", "subject": self.subject()},
            )
        elif self.path == "/memory/clear":
            self._json(200, {"ok": True, "session_id": payload.get("session_id")})
        elif self.path == "/subjects/generate":
            type(self).revision += 1
            self._json(201, {"ok": True, "document": self.subject()})
        elif self.path == "/storage/pull":
            self._json(
                202,
                {
                    "ok": True,
                    "job": {
                        "job_id": "storage-job-1",
                        "kind": payload.get("kind"),
                        "name": payload.get("name"),
                        "status": "queued",
                    },
                },
            )
        else:
            self._json(404, {"ok": False, "error": "Not found"})

    def _json(self, status: int, payload: dict) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:
        pass


class WebUIIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.output_temp = tempfile.TemporaryDirectory()
        cls.output_root = Path(cls.output_temp.name)
        (cls.output_root / "batch").mkdir()
        (cls.output_root / "image-a.png").write_bytes(PNG_BYTES)
        (cls.output_root / "batch" / "image-b.txt").write_text(
            "nested output", encoding="utf-8"
        )
        cls.upstream = ThreadingHTTPServer(("127.0.0.1", 0), MockUpstreamHandler)
        upstream_url = f"http://127.0.0.1:{cls.upstream.server_port}"
        cls.webui = app.WebUIServer(
            app.Settings(
                host="127.0.0.1",
                port=0,
                orchestrator_url=upstream_url,
                image_forge_url=upstream_url,
                request_timeout=3,
                image_timeout=3,
                output_directory=cls.output_root,
            )
        )
        cls.base_url = f"http://127.0.0.1:{cls.webui.server_port}"
        cls.threads = [
            threading.Thread(target=cls.upstream.serve_forever, daemon=True),
            threading.Thread(target=cls.webui.serve_forever, daemon=True),
        ]
        for thread in cls.threads:
            thread.start()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.webui.shutdown()
        cls.upstream.shutdown()
        cls.webui.server_close()
        cls.upstream.server_close()
        for thread in cls.threads:
            thread.join(timeout=2)
        cls.output_temp.cleanup()

    def request_json(self, path: str, payload: dict | None = None) -> tuple[int, dict]:
        data = None
        headers = {}
        if payload is not None:
            data = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"
        request = Request(self.base_url + path, data=data, headers=headers)
        with urlopen(request, timeout=5) as response:
            return response.status, json.loads(response.read().decode("utf-8"))

    def test_static_application_and_runtime_health(self) -> None:
        with urlopen(self.base_url + "/", timeout=5) as response:
            page = response.read().decode("utf-8")
        self.assertIn("EverSpark Forge", page)
        self.assertIn("Character subjects", page)
        self.assertIn("New conversation", page)
        self.assertNotIn("Subject ID", page)
        status, health = self.request_json("/api/runtime/status")
        self.assertEqual(status, 200)
        self.assertTrue(health["services"]["orchestrator"]["online"])
        self.assertTrue(health["services"]["image_forge"]["online"])

    def test_subject_list_detail_revisions_and_generation(self) -> None:
        _, listed = self.request_json("/api/subjects")
        self.assertEqual(listed["subjects"][0]["subject_id"], "ember-keeper")
        _, fetched = self.request_json("/api/subjects?subject_id=ember-keeper")
        self.assertEqual(fetched["document"]["identity"]["display_name"], "Ember Keeper")
        _, revisions = self.request_json("/api/subjects/revisions?subject_id=ember-keeper")
        self.assertEqual(revisions["revisions"][0]["document"]["subject_id"], "ember-keeper")
        _, updated = self.request_json(
            "/api/subjects/generate",
            {"subject_id": "ember-keeper", "text": "silver hair"},
        )
        self.assertGreaterEqual(updated["document"]["revision"], 2)

    def test_generation_uses_session_subject_and_result_uses_exact_prompt(self) -> None:
        _, queued = self.request_json(
            "/api/generate",
            {"message": "blue hour rooftop", "session_id": "session-a"},
        )
        self.assertEqual(queued["result"]["items"][0]["prompt_id"], "prompt-1")
        self.assertEqual(MockUpstreamHandler.received_task["session_id"], "session-a")
        self.assertNotIn("subject_id", MockUpstreamHandler.received_task)
        _, result = self.request_json("/api/results?prompt_id=prompt-1")
        self.assertEqual(result["results"][0]["status"], "completed")
        image_url = result["results"][0]["images"][0]["url"]
        with urlopen(self.base_url + image_url, timeout=5) as response:
            self.assertEqual(response.read(), PNG_BYTES)

    def test_resources_and_generation_selection_are_proxied(self) -> None:
        _, resources = self.request_json("/api/resources")
        self.assertEqual(resources["workflows"][0]["id"], "base-illustrious")
        selection = {
            "workflow": "base-illustrious",
            "checkpoint": "base.safetensors",
            "llm": "concept:latest",
            "loras": [
                {
                    "name": "style.safetensors",
                    "strength_model": 0.8,
                    "strength_clip": 0.7,
                }
            ],
        }
        self.request_json(
            "/api/generate",
            {
                "message": "blue hour rooftop",
                "session_id": "session-resources",
                "selection": selection,
            },
        )
        self.assertEqual(MockUpstreamHandler.received_task["selection"], selection)

    def test_remote_storage_routes_are_proxied(self) -> None:
        status, resources = self.request_json("/api/storage/resources")
        self.assertEqual(status, 200)
        self.assertEqual(resources["image"]["checkpoint"][0]["name"], "remote.safetensors")
        status, started = self.request_json(
            "/api/storage/pull",
            {"kind": "checkpoint", "name": "remote.safetensors"},
        )
        self.assertEqual(status, 202)
        self.assertEqual(started["job"]["job_id"], "storage-job-1")

    def test_discussion_and_current_subject_follow_the_session(self) -> None:
        _, discussed = self.request_json(
            "/api/conversation",
            {"message": "She has silver hair", "session_id": "session-a"},
        )
        self.assertIn("reply", discussed)
        _, current = self.request_json(
            "/api/subjects/current?session_id=session-a"
        )
        self.assertEqual(current["document"]["subject_id"], "ember-keeper")

    def test_image_proxy_rejects_parent_paths(self) -> None:
        with self.assertRaises(HTTPError) as caught:
            urlopen(self.base_url + "/api/image/view?filename=../private", timeout=5)
        self.assertEqual(caught.exception.code, 400)

    def test_output_archive_contains_the_complete_output_tree(self) -> None:
        with urlopen(self.base_url + "/api/outputs/archive", timeout=5) as response:
            self.assertEqual(response.headers.get_content_type(), "application/zip")
            self.assertIn("EverSpark-Outputs-", response.headers["Content-Disposition"])
            payload = response.read()
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            self.assertEqual(
                set(archive.namelist()),
                {
                    "EverSpark-Outputs/",
                    "EverSpark-Outputs/image-a.png",
                    "EverSpark-Outputs/batch/image-b.txt",
                },
            )
            self.assertEqual(
                archive.read("EverSpark-Outputs/batch/image-b.txt"),
                b"nested output",
            )


if __name__ == "__main__":
    unittest.main()
