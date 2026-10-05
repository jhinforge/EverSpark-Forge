"""Two-stage Concept calls, opaque Forge inputs and task-owned dependencies."""
import json
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parents[2]
for relative in ("", "Archon/Orchestrator", "Legate/Forge", "Legate/Forge/ConceptForge",
                 "Legate/Forge/ConceptForge/Memory", "Legate/Forge/ImageForge"):
    sys.path.insert(0, str(ROOT / relative))
from Archon.Vault.runtime_config import load_config
from orchestrator.core.orchestrator import Orchestrator
from orchestrator.core.task_runner import TaskRunner
from concept_forge.workspace import ConceptWorkspace
from concept_forge.service import ConceptService, GenerationPlan
from concept_forge.subjects import new_subject
from concept_forge.port import ConceptError
from Aegis.Shared.errors import TaskError


STEPS = [{"key": "voice", "forge": "audio", "brief": "Read the scene in Japanese",
          "depends_on": ["frame"]},
         {"key": "frame", "forge": "image", "brief": "One portrait", "depends_on": []}]


class CreationTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        config = load_config()
        config["memory"]["database"] = str(Path(self.directory.name) / "memory.db")
        self.trace = []
        trace = self.trace
        class Model:
            model = "test-model"
            def decompose(self, text, history, available, **kwargs):
                trace.append("decompose")
                return {"steps": STEPS}
            def generate_subject(self, text, subject_id, existing, **kwargs):
                return new_subject(subject_id, "Character")
            def generate_prompt(self, text, history, **kwargs):
                trace.append("image-prompt")
                return GenerationPlan("illustrious", "portrait", "bad", 1, "over")
            def generate_speech(self, brief, context, **kwargs):
                trace.append(("speech-text", context["dependencies"]))
                return {"text": "こんにちは。"}
        self.concept = ConceptWorkspace(config, Model(), Mock())
        self.image, self.audio = Mock(), Mock()
        self.image.execute.side_effect = self.render
        self.audio.execute.side_effect = self.speak
        self.runner = TaskRunner(self.concept, self.image, self.audio)

    def render(self, instruction, selection, notify):
        self.trace.append("image")
        self.assertEqual(instruction["positive_prompt"], "portrait")
        return {"model": "illustrious", "positive_prompt": "portrait", "negative_prompt": "bad", "selection": {},
                "count": 1, "items": [{"prompt_id": "image-ref"}],
                "outputs": [{"status": "completed", "images": [{"filename": "frame.png"}]}]}

    def speak(self, instruction, selection, notify):
        self.trace.append("audio")
        self.assertEqual(instruction, {"text": "こんにちは。"})
        return {"status": "completed", "audio": [{"filename": "speech.wav"}]}

    def test_audio_mode_keeps_concept_and_never_calls_image(self):
        self.concept.service.decompose = Mock(return_value={"steps": [{**STEPS[0], "depends_on": []}]})
        result = self.runner.run("Write a warm welcome in Chinese", "speech", {"creation_mode": "audio"})
        self.image.execute.assert_not_called()
        self.image.generate.assert_not_called()
        self.audio.execute.assert_called_once()
        self.assertEqual(self.concept.service.decompose.call_args.args[2], ["audio"])
        self.assertEqual(self.concept.service.decompose.call_args.kwargs["generation_mode"], "audio")
        self.assertEqual(result["items"], [])
        self.assertEqual(len(result["audio"]), 1)

    def test_selected_mode_rejects_wrong_outputs_before_execution(self):
        for mode, steps in (("audio", STEPS), ("image_audio", [STEPS[1]])):
            self.concept.service.decompose = Mock(return_value={"steps": steps})
            with self.subTest(mode=mode), self.assertRaisesRegex(TaskError, "selected generation mode"):
                self.runner.run("create", "s", {"creation_mode": mode})
        self.image.execute.assert_not_called()
        self.audio.execute.assert_not_called()

    def test_audio_mode_requires_audio_binding_and_invalid_modes_fail(self):
        runner = TaskRunner(self.concept, self.image)
        with self.assertRaisesRegex(TaskError, "Audio Forge node"):
            runner.run("speak", "s", {"creation_mode": "audio"})
        with self.assertRaisesRegex(TaskError, "Invalid generation mode"):
            self.runner.run("speak", "s", {"creation_mode": "unknown"})

    def test_decomposition_then_tasks_then_prompts_then_forges_and_aggregation(self):
        events = []
        result = self.runner.run("portrait and narration", "session", {"creation_mode": "plan"}, events.append)
        self.assertEqual(self.trace[:3], ["decompose", "image-prompt", "image"])
        self.assertEqual(self.trace[-1], "audio")
        self.assertEqual(self.trace[3][0], "speech-text")
        self.assertEqual(self.trace[3][1][0]["items"][0]["prompt_id"], "image-ref")
        tasks = result["tasks"]
        self.assertEqual([t["forge"] for t in tasks], ["image", "audio"])
        self.assertEqual(tasks[1]["depends_on"], [tasks[0]["id"]])
        self.assertTrue(all(len(t["id"]) == 32 and t["status"] == "completed" for t in tasks))
        self.assertTrue(all("specification" not in t for t in tasks))
        self.assertEqual(result["audio"][0]["filename"], "speech.wav")
        self.assertEqual(len(self.concept.get_history("session")), 4)
        self.assertFalse(self.concept.busy())

    def test_voice_without_dialogue_receives_creative_context_without_image_prompt(self):
        text = "生成一张女孩的肖像，并给她配上年轻女孩的声音"
        speech = {"text": "你好呀，今天也一起度过愉快的一天吧。", "voice_description": "young female voice"}
        self.concept.service.generate_speech = Mock(return_value=speech)
        self.audio.execute.side_effect = lambda instruction, *args: {"status": "completed", "audio": [
            {"filename": "speech.wav", "text": instruction["text"]}]}
        result = self.runner.run(text, "character-voice", {"creation_mode": "plan"})
        brief, context = self.concept.service.generate_speech.call_args.args
        self.assertEqual(context["request"], text)
        self.assertEqual(context["related_briefs"], ["One portrait"])
        self.assertIsNotNone(context["character"])
        self.assertEqual(context["dependencies"][0]["items"][0]["prompt_id"], "image-ref")
        self.assertNotIn("positive_prompt", context["dependencies"][0])
        self.assertNotIn("negative_prompt", context["dependencies"][0])
        self.assertNotIn("selection", context["dependencies"][0])
        self.assertIn("positive_prompt", result["tasks"][0]["result"])
        self.assertEqual(result["audio"][0]["text"], speech["text"])
        self.assertEqual(self.audio.execute.call_args.args[0], speech)

    def test_invalid_dependencies_fail_before_any_second_stage_or_execution(self):
        for steps in ([{**STEPS[0], "depends_on": ["missing"]}],
                      [{**STEPS[1], "depends_on": ["voice"]}, STEPS[0]],
                      [STEPS[1], STEPS[1]], [{**STEPS[1], "forge": "video"}]):
            with self.subTest(steps=steps), self.assertRaises(TaskError):
                self.runner._tasks({"steps": steps})
        self.image.execute.assert_not_called()
        self.audio.execute.assert_not_called()

    def test_failed_image_skips_audio_and_releases_concept_and_orchestrator(self):
        self.image.execute.side_effect = RuntimeError("image offline")
        owner = Orchestrator(self.runner)
        job = owner.start_task("create", "session", {"creation_mode": "plan"})
        state = self.wait(owner, job["id"])
        self.assertEqual(state["status"], "failed")
        self.assertEqual([t["status"] for t in state["tasks"]], ["failed", "skipped"])
        self.audio.execute.assert_not_called()
        self.assertFalse(self.concept.busy())
        self.assertFalse(owner._task_lock.locked())
        self.assertEqual(self.concept.get_history("session"), [])

    def test_running_task_progress_and_request_idempotency(self):
        entered, release = threading.Event(), threading.Event()
        def speak(*args):
            entered.set()
            if not release.wait(3):
                raise RuntimeError("Test release timed out")
            return self.speak(*args)
        self.audio.execute.side_effect = speak
        owner = Orchestrator(self.runner)
        job = owner.start_task("create", "session", {"creation_mode": "plan"}, "a" * 32)
        try:
            self.assertTrue(entered.wait(2))
            state = owner.task_job(job["id"])
            self.assertEqual([t["status"] for t in state["tasks"]], ["completed", "running"])
            repeated = owner.start_task("create", "session", {"creation_mode": "plan"}, "a" * 32)
            self.assertEqual(repeated["id"], job["id"])
        finally:
            release.set()
        self.assertEqual(self.wait(owner, job["id"])["status"], "completed")
        self.audio.execute.assert_called_once()

    def test_audio_not_advertised_without_an_audio_binding(self):
        runner = TaskRunner(self.concept, self.image)
        with self.assertRaises(TaskError):
            runner._tasks({"steps": STEPS})

    def test_speech_only_creation_does_not_generate_or_modify_an_image_subject(self):
        self.concept.service.decompose = lambda *args, **kwargs: {"steps": [
            {**STEPS[0], "depends_on": []}]}
        result = self.runner.run("Japanese greeting", "speech", {"creation_mode": "plan"})
        self.image.execute.assert_not_called()
        self.assertIsNone(self.concept.get_session_subject("speech"))
        self.assertEqual(result["items"], [])
        self.assertEqual(len(result["audio"]), 1)
        self.assertEqual(len(self.concept.get_history("speech")), 2)

    @staticmethod
    def wait(owner, identity):
        for _ in range(200):
            state = owner.task_job(identity)
            if state["status"] not in {"queued", "running"}:
                return state
            time.sleep(.01)
        raise AssertionError("Task did not terminate")


class ConceptStageTests(unittest.TestCase):
    def service(self, response):
        gateway = Mock()
        gateway.select.return_value = SimpleNamespace(model="test")
        gateway.chat.return_value = SimpleNamespace(content=response)
        return ConceptService(gateway)

    def test_explicit_audio_mode_and_translation_rules_reach_concept(self):
        service = self.service(json.dumps({"steps": [{**STEPS[0], "depends_on": []}]}))
        service.decompose("Write a Chinese welcome", [], ["audio"], generation_mode="audio")
        request = service.gateway.chat.call_args.args[0]
        payload = json.loads(request.messages[-1]["content"])
        self.assertEqual(payload["generation_mode"], "audio")
        self.assertEqual(payload["available_forges"], ["audio"])
        self.assertIn("create only", request.messages[0]["content"])
        service.gateway.chat.return_value.content = '{"text":"欢迎！"}'
        service.generate_speech("Translate welcome", {"request": "Translate welcome into Chinese"})
        self.assertIn("translate the spoken content", service.gateway.chat.call_args.args[0].messages[0]["content"])

    def test_audio_example_contains_only_audio_and_preserves_request(self):
        plan = {"steps": [{"key": "speech", "forge": "audio", "brief": "年轻少女用中文说你好", "depends_on": []}]}
        service = self.service(json.dumps(plan))
        text = "给她配上年轻少女的声音用中文说你好"
        self.assertEqual(service.decompose(text, [], ["audio"], generation_mode="audio"), plan)
        request = service.gateway.chat.call_args.args[0]
        self.assertNotIn('"forge": "image"', request.messages[0]["content"])
        self.assertIn('"forge": "audio"', request.messages[0]["content"])
        self.assertEqual(json.loads(request.messages[-1]["content"])["request"], text)
        service.gateway.chat.assert_called_once()

    def test_audio_format_failure_is_corrected_before_returning_plan(self):
        valid = {"steps": [{"key": "speech", "forge": "audio", "brief": "少女用中文说你好", "depends_on": []}]}
        invalid_plans = [
            "not JSON",
            json.dumps({"steps": [STEPS[1]]}),
            json.dumps({"steps": [{"key": "speech", "forge": "audio", "brief": "你好"}]}),
            json.dumps({"steps": [{**valid["steps"][0], "depends_on": ["frame"]}]}),
        ]
        for invalid in invalid_plans:
            with self.subTest(invalid=invalid):
                service = self.service(invalid)
                requests = []
                responses = iter([invalid, json.dumps(valid)])
                def chat(request, provider=""):
                    requests.append([dict(message) for message in request.messages])
                    return SimpleNamespace(content=next(responses))
                service.gateway.chat.side_effect = chat
                self.assertEqual(service.decompose("给她配上年轻少女的声音用中文说你好", [], ["audio"],
                                                  model="everspark-concept", generation_mode="audio"), valid)
                self.assertEqual(len(requests), 2)
                self.assertIn("failed validation", requests[1][-1]["content"])
                self.assertIn("generation_mode=audio", requests[1][-1]["content"])
                self.assertEqual(service.gateway.chat.call_args.args[0].model, "everspark-concept")

    def test_decomposition_retries_are_bounded_and_errors_explain_the_field(self):
        service = self.service('{"steps":[{"text":"你好"}]}')
        service.max_model_retries = 1
        with self.assertRaisesRegex(ConceptError, "after 2 attempts: Step 1 must have exactly"):
            service.decompose("说你好", [], ["audio"], generation_mode="audio")
        self.assertEqual(service.gateway.chat.call_count, 2)

    def test_decomposition_does_not_retry_transport_errors(self):
        service = self.service("")
        service.gateway.chat.side_effect = ConceptError("Cannot connect to Ollama")
        with self.assertRaisesRegex(ConceptError, "Cannot connect"):
            service.decompose("说你好", [], ["audio"], generation_mode="audio")
        service.gateway.chat.assert_called_once()

    def test_dependency_cycle_and_missing_multimodal_output_are_rejected(self):
        for steps, reason in (([{**STEPS[0]}, {**STEPS[1], "depends_on": ["voice"]}], "cycle"),
                              ([STEPS[1]], "requires exactly")):
            with self.subTest(reason=reason):
                service = self.service(json.dumps({"steps": steps}))
                service.max_model_retries = 0
                with self.assertRaisesRegex(ConceptError, reason):
                    service.decompose("图像和声音", [], ["image", "audio"], generation_mode="image_audio")

    def test_creative_json_and_speech_are_distinct_model_calls(self):
        service = self.service(json.dumps({"steps": STEPS}))
        self.assertEqual(service.decompose("create", [], ["image", "audio"]), {"steps": STEPS})
        service.gateway.chat.return_value.content = '{"text":"こんにちは。"}'
        self.assertEqual(service.generate_speech("narrate", {}), {"text": "こんにちは。"})
        self.assertEqual(service.gateway.chat.call_count, 2)

    def test_speech_model_receives_original_language_and_automatic_character_dialogue_rule(self):
        text = "生成一张女孩的肖像，并给她配上年轻女孩的声音"
        service = self.service('{"text":"你好呀，今天也一起度过愉快的一天吧。"}')
        result = service.generate_speech("a portrait with a youthful voice", {"request": text})
        call = service.gateway.chat.call_args.args[0]
        context = json.loads(call.messages[-1]["content"])
        self.assertEqual(context["context"]["request"], text)
        self.assertIn("one short, natural line spoken by the character", call.messages[0]["content"])
        self.assertIn("Never read or translate an image prompt", call.messages[0]["content"])
        self.assertIn("language of that request", call.messages[0]["content"])
        self.assertEqual(result, {"text": "你好呀，今天也一起度过愉快的一天吧。"})

    def test_concept_keeps_voice_description_separate_from_spoken_text(self):
        expected = {"text": "你好呀。", "voice_description": "young female voice"}
        service = self.service(json.dumps(expected, ensure_ascii=False))
        result = service.generate_speech("年轻女孩", {"request": "给她配上年轻女孩的声音"})
        self.assertEqual(result, expected)
        prompt = service.gateway.chat.call_args.args[0].messages[0]["content"]
        self.assertIn("voice_description", prompt)
        self.assertIn("Never put the voice description into text", prompt)
        for value in ({"text": "hello", "voice_description": None},
                      {"text": "hello", "voice_description": "x" * 1001},
                      {"voice_description": "female"}):
            with self.subTest(value=value), self.assertRaises(ConceptError):
                self.service(json.dumps(value)).generate_speech("voice", {})

    def test_explicit_dialogue_is_returned_verbatim_without_voice_instructions(self):
        spoken = "こんにちは！今日は一緒に出かけよう。"
        service = self.service(json.dumps({"text": spoken}, ensure_ascii=False))
        result = service.generate_speech("年轻女孩", {"request": "用日语说：" + spoken})
        self.assertEqual(result, {"text": spoken})
        prompt = service.gateway.chat.call_args.args[0].messages[0]["content"]
        self.assertIn("Preserve explicitly supplied dialogue verbatim", prompt)
        self.assertIn("only words to be spoken", prompt)

    def test_invalid_or_executor_owned_fields_are_rejected(self):
        for response in ('[]', '{}', '{"steps":[]}', json.dumps({"steps": [
            {**STEPS[0], "engine": "voxcpm2"}]}), json.dumps({"steps": [STEPS[0]]})):
            with self.subTest(response=response), self.assertRaises(ConceptError):
                self.service(response).decompose("create", [], ["image"])
        for response in ('{"text":""}', '{"text":"hello","seed":1}', '[]'):
            with self.subTest(response=response), self.assertRaises(ConceptError):
                self.service(response).generate_speech("speak", {})
