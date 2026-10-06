"""Two provider-free Nodes selected in WebUI drive real Orchestrator routing."""
import base64
import json
import tempfile
import threading
import time
import unittest
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from unittest.mock import patch
from Archon.Gate.control_server import ControlServer
from Archon.Gate.forge_bindings import ForgeBindings
from Archon.Gate.remote_runtime import create_runtime
from Archon.Portal.app import Settings, WebUIServer
from Archon.Steward.NodeManager import NodeManager
from test_node_registration import INFO


class RemoteCreationWebUITests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        self.nodes = NodeManager("127.0.0.1", 0, state_path=self.root / "nodes.json")
        self.nodes.start()
        self.gate = ControlServer(("127.0.0.1", 0), node_manager=self.nodes)
        self.seen, self.agent_errors, self.speech_inputs = [], [], []
        self.stop = threading.Event()
        self.agents, self.identities = [], {}
        self.image_bytes = b"\x89PNG\r\n\x1a\nremote-output"
        for role, enrollment in (("concept", "a" * 32), ("image", "b" * 32)):
            response = self.nodes.registration.register({"join_token": self.nodes.issue_join_token(),
                "enrollment_id": enrollment, "runtime_id": enrollment, "info": INFO})
            self.identities[role] = response["node_id"]
            authentication = {key: response[key] for key in ("node_id", "runtime_id", "session")}
            worker = threading.Thread(target=self.agent, args=(role, authentication), daemon=True)
            worker.start()
            self.agents.append(worker)
        def factory(bindings, control_url):
            # Real runtime composition, with isolated data and a fixed character
            # fixture so this test concentrates on transport and task routing.
            def config_loader():
                from orchestrator.config.config import load_config
                config = load_config()
                config["memory"]["database"] = str(self.root / "memory.db")
                config["image_forge"]["output_directory"] = str(self.root / "outputs")
                config["audio_forge"]["output_directory"] = str(self.root / "audio")
                return config
            runtime = create_runtime(bindings, control_url, config_loader)
            from concept_forge.subjects import new_subject
            document = new_subject("test-remote-character", "Test remote character")
            if not getattr(self, "real_subject", False):
                runtime.server.application.concept._refresh_session_subject = lambda *args, **kwargs: document
            return runtime
        self.factory = factory
        self.bindings = ForgeBindings(self.nodes, self.root / "forge_bindings.json",
            f"http://127.0.0.1:{self.gate.server_port}", factory=factory)
        self.gate.forge_bindings = self.bindings
        self.portal = WebUIServer(Settings(port=0, request_timeout=5,
            orchestrator_url=f"http://127.0.0.1:{self.gate.server_port}",
            control_url=f"http://127.0.0.1:{self.gate.server_port}"), forge_bindings=self.bindings)
        self.workers = []
        for server in (self.gate, self.portal):
            worker = threading.Thread(target=server.serve_forever, daemon=True)
            worker.start()
            self.workers.append(worker)
        self.url = f"http://127.0.0.1:{self.portal.server_port}"

    def tearDown(self):
        self.stop.set()
        for server in (self.portal, self.gate):
            server.shutdown()
            server.server_close()
        self.bindings.close()
        self.nodes.close()
        for worker in self.workers + self.agents:
            worker.join(2)
        self.directory.cleanup()

    def call(self, path, body=None):
        request = Request(self.url + path, data=json.dumps(body).encode() if body is not None else None,
                          headers={"Content-Type": "application/json"})
        with urlopen(request, timeout=10) as response:
            return json.load(response)

    def agent(self, role, authentication):
        resources = {"engine": "comfyui", "workflows": [{"id": "base", "name": "Base"}],
            "checkpoints": ["model.safetensors"], "vaes": [], "loras": [],
            "defaults": {"workflow": "base", "checkpoint": "model.safetensors"}}
        handlers = {
            "probe": lambda _: {"ok": True},
            "chat": self.concept_response,
            "models": lambda _: ["everspark-concept", "downloaded-llm:latest"],
            "plugins": lambda _: {"default": "comfyui", "plugins": [{"id": "comfyui", "name": "ComfyUI", "installed": True, "online": True}]},
            "models_download_start": lambda p: {"job_id": "f" * 32, "kind": p["kind"], "status": "queued"},
            "models_download_job": lambda p: {"job_id": p["job_id"], "kind": "checkpoint", "status": "completed"},
            "models_download_cancel": lambda p: {"job_id": p["job_id"], "kind": "checkpoint", "status": "cancelled"},
            "resources": lambda _: resources,
            "default_negative": lambda _: {"negative_prompt": "bad"},
            "submit": lambda _: {"prompt_id": "remote-job", "selection": {"workflow": "base", "checkpoint": "model.safetensors", "vae": "", "loras": []}},
            "poll": lambda _: {"prompt_id": "remote-job", "status": "completed", "images": [{"filename": "render.png", "subfolder": "", "type": "output"}]},
            "fetch": lambda p: self.output_chunk(role, p),
            "archive": lambda _: {"status": "ready", "job_id": "d" * 32,
                                    "url": "http://100.64.0.2:9000/archive?token=fixture"},
            "synthesize": lambda p: {"status": "completed", "audio": [{
                "filename": "speech.wav", "sample_rate": 48000, "text": p["text"],
                **({"voice_description": p["voice_description"]} if p.get("voice_description") else {})}]},
            "history": lambda _: {"audio": [{"filename": "speech.wav"}]} if role == "audio" else {"images": getattr(self, "history_images", [])},
        }
        try:
            while not self.stop.is_set():
                task = self.nodes.tasks.next_task(authentication)
                if not task:
                    continue
                self.seen.append((role, task["forge"], task["action"]))
                if role == "audio" and task["action"] == "synthesize" and getattr(self, "audio_failure", False):
                    self.nodes.tasks.finish({**authentication, "task_id": task["id"],
                        "result": {"status": "failed", "output": "RuntimeError: audio inference failed",
                                   "exit_code": 7}})
                    continue
                payload = json.loads(task["message"])
                if task["action"] == "synthesize":
                    self.speech_inputs.append(payload)
                if task["action"] == "stream":
                    data = self.audio_bytes if task["forge"] == "audio" else self.image_bytes
                    request = Request(self.nodes.url + "/node/output", data=data, method="POST",
                        headers={"Content-Type": "application/octet-stream",
                                 "Authorization": "Bearer " + payload["token"]})
                    with urlopen(request, timeout=5) as response:
                        value = json.load(response)
                elif task["action"] == "fetch":
                    value = self.output_chunk(task["forge"], payload)
                elif task["action"] == "history" and task["forge"] == "audio":
                    value = {"audio": [{"filename": "speech.wav"}]}
                else:
                    value = handlers[task["action"]](payload)
                output = json.dumps(value)
                self.nodes.tasks.finish({**authentication, "task_id": task["id"],
                    "result": {"status": "completed", "output": output, "exit_code": 0}})
        except Exception as exc:
            if not self.stop.is_set():
                self.agent_errors.append(exc)

    def concept_response(self, payload):
        delimiter = "The required output template/current document is:\n"
        system = payload["messages"][0]["content"]
        if "creative planning stage" in system:
            context = json.loads(payload["messages"][-1]["content"])
            if context.get("generation_mode") == "audio":
                self.assertEqual(context["available_forges"], ["audio"])
                return {"steps": [{"key": "voice", "forge": "audio", "brief": "Chinese welcome", "depends_on": []}]}
            return {"steps": [{"key": "frame", "forge": "image", "brief": "A portrait", "depends_on": []},
                {"key": "voice", "forge": "audio", "brief": "Japanese greeting", "depends_on": ["frame"]}]}
        if "speech-writing stage" in system:
            if getattr(self, "audio_only", False):
                context = json.loads(payload["messages"][-1]["content"])["context"]
                self.assertEqual(context["request"], "Write a welcome message in Chinese")
                return {"text": "欢迎！", "voice_description": "warm voice"}
            if getattr(self, "chinese_dialogue", False):
                context = json.loads(payload["messages"][-1]["content"])["context"]
                self.assertEqual(context["request"], "生成一张女孩的肖像，并给她配上年轻女孩的声音")
                for result in context["dependencies"]:
                    self.assertNotIn("positive_prompt", result)
                    self.assertNotIn("selection", result)
                return {"text": "你好呀，今天也一起度过愉快的一天吧。", "voice_description": "young female voice"}
            return {"text": "こんにちは。"}
        if delimiter in system:
            document = json.loads(system.split(delimiter, 1)[1])
            document["identity"]["display_name"] = "Remote character"
            return document
        return {"model": "illustrious", "positive_prompt": "portrait",
                "negative_prompt": "bad", "count": 1, "status": "over"}

    def output_chunk(self, role, payload):
        data = self.audio_bytes if role == "audio" else self.image_bytes
        offset = payload.get("offset", 0)
        return {"size": len(data), "data": base64.b64encode(data[offset:offset+24576]).decode()}

    def select_audio(self):
        import io
        import wave
        buffer = io.BytesIO()
        with wave.open(buffer, "wb") as stream:
            stream.setnchannels(1)
            stream.setsampwidth(2)
            stream.setframerate(48000)
            stream.writeframes(b"\x00\x00" * 16000)
        self.audio_bytes = buffer.getvalue()
        enrollment = "c" * 32
        response = self.nodes.registration.register({"join_token": self.nodes.issue_join_token(),
            "enrollment_id": enrollment, "runtime_id": enrollment, "info": INFO})
        self.identities["audio"] = response["node_id"]
        authentication = {key: response[key] for key in ("node_id", "runtime_id", "session")}
        worker = threading.Thread(target=self.agent, args=("audio", authentication), daemon=True)
        worker.start()
        self.agents.append(worker)
        self.select_pair()
        self.assertIsNone(self.bindings.runtime.server.application.audio)
        self.call("/api/forge-bindings", {"forge": "audio", "node_id": self.identities["audio"]})

    def test_audio_mode_reaches_concept_and_audio_without_image_binding(self):
        self.select_audio()
        # Recompose with only Concept and Audio; Image must be unnecessary.
        self.bindings.close()
        configured = {role: node for role, node in self.bindings.bindings.items() if role != "image"}
        self.bindings.bindings = configured
        self.bindings.runtime = self.factory(configured, self.bindings.control_url)
        self.audio_only = True
        job = self.call("/api/generate/start", {"message": "Write a welcome message in Chinese",
            "session_id": "audio-only", "selection": {"creation_mode": "audio"}})["job"]
        for _ in range(200):
            state = self.call("/api/generate/jobs?job_id=" + job["id"])["job"]
            if state["status"] not in {"queued", "running"}:
                break
            time.sleep(.01)
        self.assertEqual(state["status"], "completed", state)
        self.assertEqual([t["forge"] for t in state["response"]["result"]["tasks"]], ["audio"])
        self.assertEqual(state["response"]["result"]["items"], [])
        self.assertFalse(any(forge == "image" for _, forge, _ in self.seen))
        self.assertEqual(self.speech_inputs[-1]["text"], "欢迎！")

    def test_two_stage_creation_reaches_audio_node_and_returns_playable_wav(self):
        self.select_audio()
        request = {"message": "portrait with Japanese narration", "session_id": "creation",
                   "selection": {"creation_mode": "plan"}, "request_id": "d" * 32}
        job = self.call("/api/generate/start", request)["job"]
        for _ in range(200):
            state = self.call("/api/generate/jobs?job_id=" + job["id"])["job"]
            if state["status"] not in {"queued", "running"}:
                break
            time.sleep(.01)
        self.assertEqual(state["status"], "completed", state)
        result = state["response"]["result"]
        self.assertEqual([t["forge"] for t in result["tasks"]], ["image", "audio"])
        self.assertEqual(result["tasks"][1]["depends_on"], [result["tasks"][0]["id"]])
        self.assertEqual(result["audio"][0]["text"], "こんにちは。")
        self.assertEqual(self.seen.count(("concept", "concept", "chat")), 3)
        self.assertEqual(self.seen.count(("audio", "audio", "synthesize")), 1)
        self.assertEqual(self.seen.count(("audio", "audio", "fetch")), 0)

        with urlopen(self.url + "/api/audio/file?filename=speech.wav", timeout=5) as response:
            self.assertEqual(response.headers["Content-Type"], "audio/wav")
            self.assertEqual(response.read(), self.audio_bytes)
        history = self.call("/api/audio/history?limit=36")
        self.assertEqual(history["audio"][0]["filename"], "speech.wav")
        self.assertIn("fallback_url", history["audio"][0])
        self.call("/api/generate/start", request)
        self.assertEqual(self.seen.count(("audio", "audio", "synthesize")), 1)
        self.assertTrue(all(role == forge for role, forge, _ in self.seen))
        self.assertEqual(self.agent_errors, [])


    def test_model_downloads_follow_forge_nodes_and_job_queries_keep_original_target(self):
        self.select_pair()
        for kind in ("checkpoint", "lora", "vae", "concept_model"):
            job = self.call("/api/downloads", {"kind": kind, "url": "https://models.example/model"})["job"]
            forge = "concept" if kind == "concept_model" else "image"
            self.assertEqual(job["target_node_id"], self.identities[forge])
            self.assertIn((forge, forge, "models_download_start"), self.seen)
        job_id = self.identities["image"] + ":image:" + "f" * 32
        # Rebinding to the other ready node must not retarget the original job.
        self.call("/api/forge-bindings", {"forge": "image", "node_id": self.identities["concept"]})
        self.call("/api/downloads/jobs?job_id=" + job_id)
        self.call("/api/downloads/cancel", {"job_id": job_id})
        self.assertIn(("image", "image", "models_download_job"), self.seen)
        self.assertIn(("image", "image", "models_download_cancel"), self.seen)

    def test_image_only_node_uses_third_party_api_and_preserves_default_after_recomposition(self):
        from Archon.Vault.concept_configuration import ConceptConfigurationVault
        from concept_forge.port import ChatResponse
        vault_path = self.root / "api-connections.json"
        with patch("concept_forge.connections.ConceptConfigurationVault", side_effect=lambda _: ConceptConfigurationVault(vault_path)):
            self.call("/api/forge-bindings", {"forge": "image", "node_id": self.identities["image"]})
            saved = self.call("/api/concept/connections/save", {"name": "Third party", "model": "fixture-model",
                "base_url": "https://api.example/v1", "api_key": "private-fixture"})
            identifier = next(entry["id"] for entry in saved["connections"] if not entry["builtin"])
            self.call("/api/concept/connections/default", {"id": identifier})
            with patch("concept_forge.adapters.openai_compatible.OpenAICompatibleAdapter.chat", side_effect=lambda request:
                    ChatResponse(json.dumps(self.concept_response({"messages": request.messages})))) as chat:
                result = self.call("/api/generate", {"message": "portrait", "session_id": "api-only",
                    "selection": {"concept_provider": identifier, "llm": "fixture-model"}})
                self.assertTrue(result["ok"], result)
                self.assertGreater(chat.call_count, 0)
                resources = self.call("/api/resources")
                self.assertEqual(resources["defaults"]["concept_provider"], identifier)
                self.assertEqual(resources["concept_models"][identifier], ["fixture-model"])
            self.assertNotIn(("concept", "concept", "chat"), self.seen)
            self.call("/api/forge-bindings", {"forge": "concept", "node_id": self.identities["concept"]})
            self.assertEqual(self.bindings.runtime.server.application.concept.connections.gateway.default, identifier)
            plugins = self.call("/api/image/plugins")
            self.assertTrue(plugins["plugins"][0]["online"])
            self.assertTrue(plugins["plugins"][0]["remote"])
            self.nodes.remove(self.identities["concept"])
            self.assertTrue(self.bindings.url)
            self.assertTrue(self.bindings.status()["ready"])
            # An unavailable optional Ollama node must not block explicit API use.
            with patch("concept_forge.adapters.openai_compatible.OpenAICompatibleAdapter.chat",
                    side_effect=lambda request: ChatResponse(json.dumps(self.concept_response({"messages": request.messages})))):
                self.assertTrue(self.call("/api/generate", {"message": "another portrait", "session_id": "api-only",
                    "selection": {"concept_provider": identifier, "llm": "fixture-model"}})["ok"])

    def test_character_voice_without_dialogue_routes_original_chinese_line_to_audio(self):
        self.chinese_dialogue = True
        self.select_audio()
        job = self.call("/api/generate/start", {"message": "生成一张女孩的肖像，并给她配上年轻女孩的声音",
            "session_id": "character-dialogue", "selection": {"creation_mode": "plan"}})["job"]
        for _ in range(200):
            state = self.call("/api/generate/jobs?job_id=" + job["id"])["job"]
            if state["status"] not in {"queued", "running"}:
                break
            time.sleep(.01)
        self.assertEqual(state["status"], "completed", state)
        self.assertEqual(self.speech_inputs, [{"text": "你好呀，今天也一起度过愉快的一天吧。",
                                               "voice_description": "young female voice"}])
        self.assertEqual(state["response"]["result"]["audio"][0]["voice_description"], "young female voice")
        self.assertEqual(state["response"]["result"]["audio"][0]["text"], self.speech_inputs[0]["text"])
        self.assertEqual(self.agent_errors, [])

    def test_image_and_audio_can_share_one_registered_node(self):
        self.select_audio()
        self.call("/api/forge-bindings", {"forge": "audio", "node_id": self.identities["image"]})
        job = self.call("/api/generate/start", {"message": "portrait with narration", "session_id": "shared-node",
                       "selection": {"creation_mode": "plan"}})["job"]
        for _ in range(200):
            state = self.call("/api/generate/jobs?job_id=" + job["id"])["job"]
            if state["status"] not in {"queued", "running"}:
                break
            time.sleep(.01)
        self.assertEqual(state["status"], "completed", state)
        self.assertIn(("image", "image", "submit"), self.seen)
        self.assertIn(("image", "audio", "synthesize"), self.seen)
        self.assertNotIn(("audio", "audio", "synthesize"), self.seen)
        with urlopen(self.url + "/api/audio/file?filename=speech.wav") as response:
            self.assertEqual(response.read(), self.audio_bytes)
        self.assertEqual(self.agent_errors, [])

    def test_audio_failure_reports_node_stderr_and_preserves_completed_image(self):
        self.audio_failure = True
        self.select_audio()
        request = {"message": "portrait with narration", "session_id": "failed-audio",
                   "selection": {"creation_mode": "plan"}, "request_id": "f" * 32}
        job = self.call("/api/generate/start", request)["job"]
        for _ in range(200):
            state = self.call("/api/generate/jobs?job_id=" + job["id"])["job"]
            if state["status"] not in {"queued", "running"}:
                break
            time.sleep(.01)
        self.assertEqual(state["status"], "failed", state)
        self.assertIn("HTTP 503, exit code 7", state["error"])
        self.assertIn("audio inference failed", state["error"])
        self.assertEqual([t["status"] for t in state["tasks"]], ["completed", "failed"])
        image = state["tasks"][0]["result"]["outputs"][0]["images"][0]
        self.assertEqual(image["filename"], "render.png")
        with urlopen(self.url + "/api/image/view?filename=render.png") as response:
            self.assertEqual(response.read(), self.image_bytes)
        self.call("/api/generate/start", request)
        self.assertEqual(self.seen.count(("audio", "audio", "synthesize")), 1)
        self.assertEqual(self.agent_errors, [])

    def test_complete_concept_business_and_ledger_survive_two_node_generation(self):
        self.real_subject = True
        self.select_pair()
        job = self.call("/api/generate/start", {"message": "portrait", "session_id": "owned-by-concept"})["job"]
        for _ in range(100):
            result = self.call("/api/generate/jobs?job_id=" + job["id"])["job"]
            if result["status"] not in {"queued", "running"}:
                break
            time.sleep(.01)
        self.assertEqual(result["status"], "completed", result)
        current = self.call("/api/subjects/current?session_id=owned-by-concept")["document"]
        self.assertEqual(current["identity"]["display_name"], "Remote character")
        self.assertEqual(current["subject_id"], result["response"]["result"]["subject"]["subject_id"])
        self.assertEqual(len(self.call("/api/conversation/history?session_id=owned-by-concept")["messages"]), 2)
        self.assertEqual(self.seen.count(("concept", "concept", "chat")), 2)
        self.assertEqual(self.seen.count(("image", "image", "submit")), 1)
        orchestrator = self.bindings.runtime.server.orchestrator
        self.assertFalse(hasattr(orchestrator, "memory"))
        self.assertFalse(hasattr(orchestrator, "image_history"))
        from everspark_memory import SQLiteMemoryStore
        ledger_backed_memory = SQLiteMemoryStore(str(self.root / "memory.db"))
        self.assertEqual(ledger_backed_memory.get_subject(current["subject_id"]), current)
        poll = self.call("/api/results?prompt_id=remote-job")
        self.assertEqual(poll["results"][0]["status"], "completed")
        with urlopen(self.url + "/api/image/view?filename=render.png", timeout=5) as response:
            self.assertEqual(response.read(), self.image_bytes)
        self.assertEqual(self.agent_errors, [])

    def select_pair(self):
        for role in ("concept", "image"):
            self.call("/api/forge-bindings", {"forge": role, "node_id": self.identities[role]})

    def test_results_and_zip_preparation_do_not_stream_remote_files(self):
        self.select_pair()
        result = self.call("/api/results?prompt_id=remote-job")
        self.assertEqual(result["results"][0]["status"], "completed")
        self.assertNotIn(("image", "image", "fetch"), self.seen)
        self.assertNotIn(("image", "image", "stream"), self.seen)
        with self.assertRaises(HTTPError) as caught:
            urlopen(self.url + "/api/outputs/archive", timeout=5)
        self.assertEqual(caught.exception.code, 410)
        archive = self.call("/api/outputs/archive/prepare?forge=image")
        self.assertEqual(archive["status"], "ready")
        self.assertEqual(archive["url"], "http://100.64.0.2:9000/archive?token=fixture")
        self.assertEqual(self.seen.count(("image", "image", "archive")), 1)
        self.assertNotIn(("image", "image", "stream"), self.seen)
        self.assertFalse(list((self.root / "outputs").rglob("*.png")))
        self.assertEqual(self.agent_errors, [])

    def test_gallery_lists_remote_outputs_before_transferring_any_image(self):
        self.history_images = [{"filename": "render.png", "subfolder": "", "type": "output",
                                "url": "/api/image/view?filename=render.png"}]
        self.select_pair()
        history = self.call("/api/history?limit=36")
        self.assertEqual(len(history["images"]), 1)
        image = history["images"][0]
        self.assertEqual(image["filename"], "render.png")
        self.assertEqual(image["subfolder"], "")
        self.assertEqual(image["type"], "output")
        self.assertIn("node_id=", image["fallback_url"])
        self.assertEqual(image["url"], image["fallback_url"])
        self.assertNotIn(("image", "image", "fetch"), self.seen)
        with urlopen(self.url + history["images"][0]["url"], timeout=5) as response:
            self.assertEqual(response.read(), self.image_bytes)
        self.assertEqual(self.seen.count(("image", "image", "stream")), 1)
        self.assertFalse(list((self.root / "outputs").rglob("*.png")))
        self.assertEqual(self.agent_errors, [])

    def test_selection_generation_result_transfer_and_persistent_restore(self):
        with patch.dict("os.environ", {"EVERSPARK_ARCHON_ONLY": "1"}):
            self.assertFalse(self.call("/api/forge-bindings")["ready"])
            self.select_pair()
            status = self.call("/api/runtime/status")
            self.assertEqual(status["mode"], "full")
            self.assertTrue(status["remote"])
            self.assertTrue(status["services"]["image_forge"]["online"])
            resources = self.call("/api/resources")
            self.assertEqual(resources["checkpoints"], ["model.safetensors"])
            job = self.call("/api/generate/start", {"message": "画一张肖像", "session_id": "remote-test"})["job"]
            for _ in range(100):
                result = self.call("/api/generate/jobs?job_id=" + job["id"])["job"]
                if result["status"] not in {"queued", "running"}:
                    break
                time.sleep(.01)
            self.assertEqual(result["status"], "completed", result)
            self.assertEqual(result["response"]["result"]["items"][0]["prompt_id"], "remote-job")
            poll = self.call("/api/results?prompt_id=remote-job")
            self.assertEqual(poll["results"][0]["status"], "completed")
            with urlopen(self.url + "/api/image/view?filename=render.png", timeout=5) as response:
                self.assertEqual(response.read(), self.image_bytes)
            self.assertTrue(all(role == forge for role, forge, _ in self.seen))
            self.assertIn(("concept", "concept", "chat"), self.seen)
            self.assertIn(("image", "image", "submit"), self.seen)
            self.assertIn(("image", "image", "stream"), self.seen)
            self.bindings.close()
            restored = ForgeBindings(self.nodes, self.root / "forge_bindings.json",
                f"http://127.0.0.1:{self.gate.server_port}", factory=self.factory)
            restored.restore()
            self.bindings = restored
            self.gate.forge_bindings = restored
            self.portal.forge_bindings = restored
            self.assertEqual(self.call("/api/forge-bindings")["bindings"], self.identities)
            self.assertEqual(self.call("/api/resources")["checkpoints"], ["model.safetensors"])
            self.assertEqual(self.agent_errors, [])

    def test_binding_api_rejects_nonlocal_origin_and_extra_provider_identity(self):
        request = Request(self.url + "/api/forge-bindings", data=b'{}', headers={
            "Content-Type": "application/json", "Origin": "https://untrusted.invalid"})
        with self.assertRaises(HTTPError) as caught:
            urlopen(request)
        self.assertEqual(caught.exception.code, 403)
        with self.assertRaises(HTTPError) as caught:
            self.call("/api/forge-bindings", {"forge": "image", "node_id": self.identities["image"], "instance_id": 99})
        self.assertEqual(caught.exception.code, 400)

    def test_offline_selected_node_rejects_generation_without_queueing_a_task(self):
        self.select_pair()
        self.stop.set()
        node_id = self.identities["image"]
        with self.nodes.lock:
            self.nodes.leases[node_id].renewed_at = time.monotonic() - 100
            self.nodes.lifecycle.expire()
        state = self.call("/api/forge-bindings")
        self.assertFalse(state["ready"])
        self.assertEqual(state["nodes"]["image"], "offline")
        with self.assertRaises(HTTPError) as caught:
            self.call("/api/generate/start", {"message": "portrait", "session_id": "offline-test"})
        self.assertEqual(caught.exception.code, 503)
        self.assertIn("offline", caught.exception.read().decode())
        self.assertEqual(self.bindings.runtime.server.orchestrator._task_jobs, {})
