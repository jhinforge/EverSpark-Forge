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
        speech = {"text": "你好呀，今天也一起度过愉快的一天吧。"}
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
