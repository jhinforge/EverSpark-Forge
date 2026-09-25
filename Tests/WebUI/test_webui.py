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
from unittest.mock import patch


REPO_ROOT = Path(__file__).resolve().parents[2]
APP_PATH = REPO_ROOT / "WebUI" / "app.py"
sys.path.insert(0, str(REPO_ROOT / "Runtime" / "Logging"))
SPEC = importlib.util.spec_from_file_location("everspark_webui", APP_PATH)
assert SPEC and SPEC.loader
app = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = app
SPEC.loader.exec_module(app)

PNG_BYTES = b"\x89PNG\r\n\x1a\npublic-test-image"


class MockUpstreamHandler(BaseHTTPRequestHandler):
    received_task: dict | None = None
    revision = 1
    archive_root: Path | None = None
    received_import: bytes | None = None

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
            "metadata": {"tags": [], "notes": ""},
        }

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        query = parse_qs(parsed.query)
        if parsed.path in {"/health", "/image/health"}:
            self._json(200, {"ok": True})
        elif parsed.path == "/image/plugins":
            self._json(200, {"ok": True, "default": "comfyui", "plugins": [
                {"id": "comfyui", "name": "ComfyUI", "installed": True, "online": True},
                {"id": "diffusers", "name": "Diffusers", "installed": False, "online": False}]})
        elif parsed.path == "/image/plugins/jobs":
            self._json(200, {"ok": True, "job": {"id": query.get("job_id", [""])[0], "status": "completed"}})
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
        elif parsed.path == "/storage/scan":
            self._json(200, {"ok": True, "status": "completed", "error": "", "result": {
                "enabled": True, "image": {"checkpoint": [{"name": "remote.safetensors"}]},
                "concept": {"models": []}}})
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
        elif parsed.path == "/backup/restore-points":
            self._json(200, {"ok": True, "points": [{"id": "a" * 32, "subjects": 1, "files": 5}]})
        elif parsed.path == "/downloads/jobs":
            self._json(
                200,
                {
                    "ok": True,
                    "job": {
                        "job_id": query.get("job_id", [""])[0] or "download-job-1",
                        "name": "direct.safetensors",
                        "status": "completed",
                        "progress": {"percent": 100.0},
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
        elif parsed.path == "/subjects/bundle":
            self._json(200, {"ok": True, "bundle": {
                "subject_id": "ember-keeper", "subject": self.subject(),
                "metadata": self.subject()["metadata"],
                "positive_prompt": {"positive_prompt": "portrait"},
                "negative_prompt": {"negative_prompt": "bad anatomy"},
            }})
        elif parsed.path == "/subjects/current":
            self._json(200, {"ok": True, "session_id": query.get("session_id", [""])[0], "document": self.subject()})
        elif parsed.path == "/memory/history":
            self._json(200, {"ok": True, "messages": []})
        elif parsed.path == "/image/results":
            self._json(200, {"ok": True, "results": [{
                "prompt_id": "prompt-1", "status": "completed", "images": [{
                    "filename": "EverSpark_00001.png", "subfolder": "", "type": "output",
                    "url": "/api/image/view?filename=EverSpark_00001.png&subfolder=&type=output"
                }]}]})
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
        elif parsed.path == "/image/file":
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
        elif self.path in {"/image/plugins/install", "/image/plugins/enable"}:
            self._json(202, {"ok": True, "job": {"id": "a" * 32, "plugin": payload["plugin"], "status": "running"}})
        elif self.path == "/image/plugins/default":
            self._json(200, {"ok": True, "default": payload["plugin"]})
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
        elif self.path == "/subjects/revise":
            self._json(200, {"ok": True, "bundle": {
                "subject_id": payload["subject_id"],
                payload["group"]: {payload["group"]: payload["instruction"]},
            }})
        elif self.path == "/subjects/select":
            self._json(200, {"ok": True, "document": self.subject(),
                             "session_id": payload["session_id"]})
        elif self.path == "/storage/scan":
            self._json(202, {"ok": True, "status": "running", "error": "", "result": None})
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
        elif self.path == "/storage/paths":
            self._json(200, {"ok": True, "paths": payload["paths"]})
        elif self.path == "/data/archive":
            path = self.archive_root / "Data/Runtime/Archives" / ("everspark-data-" + "a" * 32 + ".zip")
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"test archive")
            self._json(200, {"ok": True, "id": "a" * 32})
        elif self.path == "/data/import":
            type(self).received_import = (self.archive_root / "Data/Imports" / (payload["id"] + ".zip")).read_bytes()
            self._json(200, {"ok": True, "subjects": 1, "recovery": "Data/Recovery/test", "restart_required": True})
        elif self.path == "/backup/upload":
            self._json(202, {"ok": True, "job": {"job_id": "backup-1", "outputs": payload.get("outputs")}})
        elif self.path == "/backup/restore":
            self._json(202, {"ok": True, "job": {"id": payload["id"], "status": "queued"}})
        elif self.path in {"/downloads", "/downloads/retry", "/downloads/cancel"}:
            self._json(
                202,
                {
                    "ok": True,
                    "job": {
                        "job_id": "download-job-1",
                        "kind": payload.get("kind", "checkpoint"),
                        "name": payload.get("filename", "direct.safetensors"),
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
                request_timeout=3,
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
        self.assertIn("Install models from a URL", page)
        self.assertLess(page.index('/static/i18n.js'), page.index('/static/app.js'))
        self.assertIn('id="languageSelect"', page)
        self.assertIn('id="subjectPicker"', page)
        self.assertIn('id="useSubjectButton"', page)
        with urlopen(self.base_url + "/static/i18n.js", timeout=5) as response:
            translations = response.read().decode("utf-8")
        self.assertIn('"Character subjects": "角色主体"', translations)
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

    def test_remote_scan_is_proxied_without_waiting_for_model_listing(self) -> None:
        status, started = self.request_json("/api/storage/scan", {})
        self.assertEqual(status, 202)
        self.assertEqual(started["status"], "running")
        status, polled = self.request_json("/api/storage/scan")
        self.assertEqual(status, 200)
        self.assertEqual(polled["result"]["image"]["checkpoint"][0]["name"], "remote.safetensors")

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
        status, uploaded = self.request_json("/api/backup/upload", {"names": [], "outputs": True})
        self.assertEqual(status, 202)
        self.assertTrue(uploaded["job"]["outputs"])
        _, saved = self.request_json("/api/storage/paths", {"paths": {"concept_manual": ["r:llms"]}})
        self.assertEqual(saved["paths"]["concept_manual"], ["r:llms"])
        _, points = self.request_json("/api/backup/restore-points")
        self.assertEqual(points["points"][0]["subjects"], 1)
        status, restored = self.request_json("/api/backup/restore", {"id": "a" * 32})
        self.assertEqual(status, 202)
        self.assertEqual(restored["job"]["id"], "a" * 32)

    def test_direct_download_routes_are_proxied(self) -> None:
        status, started = self.request_json(
            "/api/downloads",
            {
                "kind": "checkpoint",
                "url": "https://models.example/direct.safetensors",
                "filename": "direct.safetensors",
            },
        )
        self.assertEqual(status, 202)
        self.assertEqual(started["job"]["job_id"], "download-job-1")
        status, fetched = self.request_json(
            "/api/downloads/jobs?job_id=download-job-1"
        )
        self.assertEqual(status, 200)
        self.assertEqual(fetched["job"]["status"], "completed")

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

    def test_subject_group_routes_are_available_in_webui(self) -> None:
        _, selected = self.request_json("/api/subjects/select", {
            "session_id": "another-session", "subject_id": "ember-keeper",
        })
        self.assertEqual(selected["document"]["subject_id"], "ember-keeper")
        self.assertEqual(selected["session_id"], "another-session")
        _, viewed = self.request_json("/api/subjects/bundle?subject_id=ember-keeper")
        self.assertEqual(viewed["bundle"]["positive_prompt"]["positive_prompt"], "portrait")
        _, revised = self.request_json("/api/subjects/revise", {
            "subject_id": "ember-keeper", "group": "negative_prompt", "instruction": "remove watermark",
        })
        self.assertEqual(revised["bundle"]["negative_prompt"]["negative_prompt"], "remove watermark")

    def test_image_proxy_rejects_parent_paths(self) -> None:
        with self.assertRaises(HTTPError) as caught:
            urlopen(self.base_url + "/api/image/view?filename=../private", timeout=5)
        self.assertEqual(caught.exception.code, 400)

    def test_image_plugin_management_is_proxied(self) -> None:
        _, listing = self.request_json("/api/image/plugins")
        self.assertEqual([item["id"] for item in listing["plugins"]], ["comfyui", "diffusers"])
        _, installing = self.request_json("/api/image/plugins/install", {"plugin": "diffusers"})
        self.assertEqual(installing["job"]["plugin"], "diffusers")
        _, job = self.request_json("/api/image/plugins/jobs?job_id=" + "a" * 32)
        self.assertEqual(job["job"]["status"], "completed")
        _, default = self.request_json("/api/image/plugins/default", {"plugin": "diffusers"})
        self.assertEqual(default["default"], "diffusers")

    def test_local_data_archive_download_and_restore_upload(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            MockUpstreamHandler.archive_root = root
            with patch.object(app, "REPO_ROOT", root):
                with urlopen(self.base_url + "/api/data/archive", timeout=5) as response:
                    self.assertEqual(response.headers["Content-Type"], "application/zip")
                    self.assertEqual(response.read(), b"test archive")
                self.assertFalse((root / "Data/Runtime/Archives" / ("everspark-data-" + "a" * 32 + ".zip")).exists())
                request = Request(self.base_url + "/api/data/import", data=b"test archive",
                                  headers={"Content-Type": "application/zip"}, method="POST")
                with urlopen(request, timeout=5) as response:
                    self.assertEqual(json.loads(response.read())["subjects"], 1)
                self.assertEqual(MockUpstreamHandler.received_import, b"test archive")
                self.assertEqual(list((root / "Data/Imports").iterdir()), [])
            MockUpstreamHandler.archive_root = None

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
