"""Audio uses the existing deployment/task/output boundaries, without a GPU in CI."""
import ast
import json
import io
from urllib.error import HTTPError
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
from Archon.Vault.runtime_config import load_config
from Archon.Steward.DeploymentManager.audio import AudioDeploymentManager
from Archon.Steward.DeploymentManager.job_store import JobStore
from Archon.Steward.NodeManager.transport.operator import task
from Archon.Steward.NodeManager.errors import NodeError
from Legate.Envoy.forge_tasks import command
from Legate.Envoy.executor.tasks import execute
from Legate.Forge.AudioForge.audio_forge.voxcpm import synthesize, validate_runtime, validate_source_pin
from Legate.Forge.AudioForge.audio_forge.service import AudioService
from Legate.Forge.AudioForge.remote_task import run
from Aegis.Storage.output_resources import OutputResources
from test_forge_bindings import Nodes, Runtime
from Archon.Gate.forge_bindings import ForgeBindings


class AudioTests(unittest.TestCase):
    def test_source_pin_accepts_exact_git_commit_and_rejects_old_or_untracked_installs(self):
        revision = "f0c787f0937dc1c9a8f4f64d9a332d9c5da2e629"
        provenance = {"url": "https://github.com/OpenBMB/VoxCPM.git",
                      "vcs_info": {"vcs": "git", "commit_id": revision}}
        distribution = Mock()
        with patch("Legate.Forge.AudioForge.audio_forge.voxcpm.importlib.metadata.distribution", return_value=distribution):
            distribution.read_text.return_value = json.dumps(provenance)
            self.assertEqual(validate_source_pin(), revision)
            for invalid in (None, "broken json", "[]", json.dumps({**provenance,
                    "vcs_info": {"vcs": "git", "commit_id": "a" * 40}}),
                    json.dumps({**provenance, "url": "https://github.com/other/VoxCPM.git"})):
                distribution.read_text.return_value = invalid
                with self.subTest(provenance=invalid), self.assertRaisesRegex(RuntimeError, "redeploy Audio Forge"):
                    validate_source_pin()

    @patch("Legate.Forge.AudioForge.audio_forge.voxcpm.validate_source_pin")
    def test_runtime_validation_checks_matching_cuda_builds_without_loading_model(self, source_pin):
        for profile, cuda in (("cu126", "12.6"), ("cu128", "12.8")):
            torch = SimpleNamespace(__version__="2.9.1+" + profile, version=SimpleNamespace(cuda=cuda))
            sdk = SimpleNamespace(VoxCPM=Mock())
            with patch.dict("sys.modules", {"torch": torch, "torchaudio": SimpleNamespace(__version__=torch.__version__),
                                          "voxcpm": sdk}):
                self.assertIs(validate_runtime(), torch)
                sdk.VoxCPM.assert_not_called()
        torch = SimpleNamespace(__version__="2.9.1+cu128", version=SimpleNamespace(cuda="12.8"))
        with patch.dict("sys.modules", {"torch": torch, "torchaudio": SimpleNamespace(__version__="2.10.0+cu130")}):
            with self.assertRaisesRegex(RuntimeError, "matching Torch/torchaudio"):
                validate_runtime()

    def test_health_rejects_native_sdk_import_failure_before_reporting_ready(self):
        with patch("Legate.Forge.AudioForge.remote_task.validate_runtime",
                   side_effect=OSError("libcudart.so.13 missing")):
            with self.assertRaisesRegex(OSError, "libcudart.so.13"):
                run("health", {}, {"audio_forge": {}})

    def test_remote_failure_includes_action_http_status_exit_code_and_stderr(self):
        config = load_config()
        config["remote_nodes"]["audio_node_id"] = "a" * 32
        service = AudioService(config)
        failure = HTTPError(service.url, 503, "Service Unavailable", {}, io.BytesIO(json.dumps({
            "error": "Node Agent execution failed", "detail": "RuntimeError: real backend failure",
            "exit_code": 7, "stage": "agent_execution"}).encode()))
        with patch("Legate.Forge.AudioForge.audio_forge.service.urlopen", side_effect=failure):
            with self.assertRaisesRegex(RuntimeError, "synthesize failed.*HTTP 503, exit code 7.*real backend failure"):
                service.execute({"text": "hello"})

    def test_audio_history_lists_only_final_outputs_without_loading_model(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "speech.wav").write_bytes(b"RIFF")
            (root / "unfinished.part").write_bytes(b"part")
            (root / "nested").mkdir()
            (root / "nested" / "other.wav").write_bytes(b"RIFF")
            (root / "link.wav").symlink_to(root / "speech.wav")
            config = {"audio_forge": {"output_directory": directory}}
            with patch("Legate.Forge.AudioForge.remote_task.synthesize", side_effect=AssertionError("model")):
                self.assertEqual(run("history", {"limit": 36}, config), {"audio": [{"filename": "speech.wav"}]})
                with self.assertRaises(ValueError):
                    run("history", {"limit": True}, config)
            self.assertIsNotNone(command("audio", "history", '{"limit":36}'))

    def test_audio_journal_and_recovery_use_audio_identity_without_redeployment(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            jobs = JobStore(path, "audio")
            job_id, task_id = "a" * 32, "b" * 32
            jobs.save({job_id: {"id": job_id, "instance_id": 1, "status": "running",
                "action": "deploy-audio", "task_action": "deploy", "task_id": task_id}})
            self.assertEqual(jobs.load()[job_id]["stage"], "recovering")
            bridge = Mock()
            bridge.runtime_id.return_value = "c" * 32
            bridge.execute.side_effect = [json.dumps({"state": "completed", "status": "completed"}),
                                          "ready", "revision"]
            with patch("Archon.Steward.DeploymentManager.image.threading.Thread"):
                manager = AudioDeploymentManager(Mock(), bridge, path)
            manager._recover(job_id)
            self.assertEqual(manager.jobs[job_id]["status"], "completed")
            self.assertEqual([c.args[1] for c in bridge.execute.call_args_list], ["recover", "health", "revision"])
            self.assertTrue(all(c.kwargs["forge"] == "audio" for c in bridge.execute.call_args_list))
            self.assertEqual(JobStore(path, "audio").load()[job_id]["status"], "completed")

    def test_operator_timeout_is_bounded_and_does_not_change_agent_protocol(self):
        manager = Mock()
        body = {"node_id": "a" * 32, "forge": "audio", "action": "synthesize", "timeout": 610}
        task(manager, body)
        self.assertEqual(manager.execute.call_args.kwargs["timeout"], 610)
        for timeout in (True, 0, 3701, "610"):
            with self.subTest(timeout=timeout), self.assertRaises(NodeError):
                task(manager, {**body, "timeout": timeout})

    def test_voxcpm_adapter_uses_text_only_and_model_sample_rate_with_atomic_output(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "config.json").write_text("{}")
            settings = {"model_directory": directory, "output_directory": str(root / "out"),
                        "max_text_chars": 12000}
            model = Mock()
            model.tts_model.sample_rate = 48000
            model.generate.return_value = [0.0, 0.1]
            voxcpm = SimpleNamespace(VoxCPM=Mock())
            voxcpm.VoxCPM.from_pretrained.return_value = model
            def write(path, wav, rate, format):
                self.assertEqual(rate, 48000)
                self.assertEqual(format, "WAV")
                Path(path).write_bytes(b"RIFF-fake-waveform")
            with patch.dict("sys.modules", {"voxcpm": voxcpm,
                            "soundfile": SimpleNamespace(write=write)}):
                result = synthesize({"text": "こんにちは。"}, settings)
            model.generate.assert_called_once_with(text="こんにちは。", cfg_value=2.0, inference_timesteps=10)
            voxcpm.VoxCPM.from_pretrained.assert_called_once_with(directory, load_denoiser=False)
            self.assertEqual(result["audio"][0]["sample_rate"], 48000)
            filename = result["audio"][0]["filename"]
            self.assertTrue((root / "out" / filename).is_file())
            self.assertEqual(list((root / "out").glob("*.part")), [])
            chunk = run("fetch", {"filename": filename, "offset": 0}, {"audio_forge": settings})
            self.assertGreater(chunk["size"], 0)
            with self.assertRaises(ValueError):
                run("fetch", {"filename": "../secret.wav", "offset": 0}, {"audio_forge": settings})

    def test_voice_design_prefix_is_built_only_in_audio_and_result_keeps_pure_dialogue(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "config.json").write_text("{}")
            settings = {"model_directory": directory, "output_directory": str(root / "out"), "max_text_chars": 12000}
            model = Mock()
            model.tts_model.sample_rate = 48000
            model.generate.return_value = [0.0]
            sdk = SimpleNamespace(VoxCPM=Mock())
            sdk.VoxCPM.from_pretrained.return_value = model
            def write(path, *args, **kwargs):
                Path(path).write_bytes(b"RIFF")
            instruction = {"text": "你好呀。（这是原文）", "voice_description": "(young female voice)\n gentle（clear）"}
            with patch.dict("sys.modules", {"voxcpm": sdk, "soundfile": SimpleNamespace(write=write)}):
                result = synthesize(instruction, settings)
            model.generate.assert_called_once_with(text="(young female voice gentleclear)你好呀。（这是原文）",
                                                   cfg_value=2.0, inference_timesteps=10)
            self.assertEqual(result["audio"][0]["text"], instruction["text"])
            self.assertEqual(result["audio"][0]["voice_description"], "young female voice gentleclear")

    def test_audio_rejects_reference_audio_and_seed_before_loading_backend(self):
        settings = {"max_text_chars": 10}
        for payload in ({"text": ""}, {"text": "long" * 10}, {"text": "hello", "seed": 1},
                        {"text": "hello", "reference_wav_path": "/tmp/a.wav"},
                        {"text": "hello", "voice_description": []},
                        {"text": "hello", "voice_description": "x" * 1001}):
            with self.subTest(payload=payload), self.assertRaises(ValueError):
                synthesize(payload, settings)

    def test_audio_commands_and_executor_use_existing_allowlist(self):
        args, timeout = command("audio", "synthesize", '{"text":"hello"}')
        self.assertTrue(args[0].endswith("audio-venv/bin/python"))
        self.assertEqual(timeout, 600)
        self.assertIsNone(command("audio", "shell", "echo attack"))
        self.assertIsNone(command("audio", "synthesize", "[]"))
        with patch("Legate.Envoy.executor.tasks.subprocess.run", return_value=
                   SimpleNamespace(returncode=0, stdout='{"status":"completed"}', stderr="")):
            self.assertEqual(execute("synthesize", '{"text":"hello"}', "audio")["status"], "completed")

    def test_audio_binding_is_optional_and_persists_without_breaking_image_pair(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bindings.json"
            bindings = ForgeBindings(Nodes(), path, "http://127.0.0.1:8765",
                                     factory=lambda choices, url: Runtime(choices))
            self.addCleanup(bindings.close)
            bindings.select({"forge": "concept", "node_id": "a" * 32})
            bindings.select({"forge": "image", "node_id": "b" * 32})
            self.assertTrue(bindings.status()["ready"])
            bindings.select({"forge": "audio", "node_id": "c" * 32})
            self.assertEqual(json.loads(path.read_text())["audio"], "c" * 32)
            restored = ForgeBindings(Nodes(), path, "http://127.0.0.1:8765",
                                     factory=lambda choices, url: Runtime(choices))
            self.addCleanup(restored.close)
            restored.restore()
            self.assertTrue(restored.status()["ready"])

    def test_remote_audio_uses_storage_chunk_cache_and_never_loads_local_voxcpm(self):
        with tempfile.TemporaryDirectory() as directory:
            config = load_config()
            config["audio_forge"]["output_directory"] = directory
            config["remote_nodes"]["audio_node_id"] = "a" * 32
            source = OutputResources(Path(directory) / "source", {".wav"})
            source.directory.mkdir()
            (source.directory / "speech.wav").write_bytes(b"RIFF" + b"x" * 30000)
            service = AudioService(config)
            def call(action, payload):
                if action == "synthesize":
                    self.assertEqual(payload, {"text": "hello", "voice_description": "young female voice"})
                    return {"status": "completed", "audio": [{"filename": "speech.wav"}]}
                return source.chunk(payload["filename"], "", payload["offset"])
            with patch.object(service, "_call", side_effect=call), patch(
                    "Legate.Forge.AudioForge.audio_forge.service.run", side_effect=AssertionError("local execution")):
                result = service.execute({"text": "hello", "voice_description": "young female voice"})
                self.assertEqual(service.audio_path(result["audio"][0]["filename"]).read_bytes(),
                                 (source.directory / "speech.wav").read_bytes())

    def test_audio_deployment_reuses_registered_node_flow_and_forge_identity(self):
        with tempfile.TemporaryDirectory() as directory:
            bridge = Mock()
            bridge.execute.return_value = "ready"
            bridge.runtime_id.return_value = "a" * 32
            manager = AudioDeploymentManager(Mock(), bridge, Path(directory) / "state.json")
            manager.jobs["job"] = {"id": "job", "instance_id": 1, "stage": "queued", "status": "running"}
            manager._deploy("job", 1)
            self.assertEqual(manager.jobs["job"]["status"], "completed")
            self.assertEqual([c.kwargs["forge"] for c in bridge.execute.call_args_list], ["audio"] * 3)
            self.assertEqual([c.args[1] for c in bridge.execute.call_args_list], ["deploy", "health", "revision"])

    def test_orchestrator_does_not_select_audio_backend_or_interpret_speech(self):
        root = Path(__file__).resolve().parents[2]
        for path in (root / "Archon/Orchestrator/orchestrator/core").glob("*.py"):
            source = path.read_text()
            self.assertNotIn("VoxCPM", source)
            self.assertNotIn("audio_forge", source)
            tree = ast.parse(source)
            strings = {n.value for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str)}
            self.assertFalse(strings & {"sample_rate", "model_directory", "cfg_value", "inference_timesteps"})
