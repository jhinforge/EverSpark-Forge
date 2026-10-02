"""Exercise actual binary HTTP forwarding, node ZIP ownership and stream limits."""
import io
import json
import sys
import tempfile
import threading
import unittest
import zipfile
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from unittest.mock import patch
from Archon.Steward.NodeManager.output_streams import OutputStreams, Transfer
from Archon.Steward.NodeManager.transport.server import NodeServer
from Archon.Steward.NodeManager.transport.operator import OperatorServer
from Aegis.Storage.node_output_stream import send_output

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "Legate/Forge/ImageForge"))
from image_forge.remote import RemoteImageGateway


class OutputStreamTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.node_outputs = self.root / "node"
        self.node_outputs.mkdir()
        self.data = b"fixture-image" * 20000
        (self.node_outputs / "render.png").write_bytes(self.data)
        self.config = {"image_forge": {"output_directory": str(self.node_outputs)},
                       "audio_forge": {"output_directory": str(self.node_outputs)}}
        (self.node_outputs / "speech.wav").write_bytes(self.data)
        self.calls = []
        owner = self
        class Manager:
            def status(self, node_id):
                return {"status": "online"}
            def execute(self, node_id, action, message, **kwargs):
                owner.calls.append((node_id, action))
                return json.dumps(send_output(owner.config, json.loads(message), forge=kwargs.get("forge", "image")))
        self.manager = Manager()
        self.manager.outputs = OutputStreams(self.manager)
        self.node = NodeServer(("127.0.0.1", 0), self.manager)
        self.control = OperatorServer(("127.0.0.1", 0), self.manager)
        self.workers = []
        for server in (self.node, self.control):
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            self.workers.append(thread)
        self.environment = patch.dict("os.environ", {"EVERSPARK_NODE_URL": f"http://127.0.0.1:{self.node.server_port}",
                                                      "EVERSPARK_NODE_PROXY": ""})
        self.environment.start()
        self.gateway = RemoteImageGateway("a" * 32, f"http://127.0.0.1:{self.control.server_port}",
                                          self.root / "host", "comfyui")

    def tearDown(self):
        self.manager.outputs.close()
        for server in (self.control, self.node):
            server.shutdown()
            server.server_close()
        for thread in self.workers:
            thread.join(2)
        self.environment.stop()

    def test_view_uses_one_binary_stream_and_never_caches_on_host(self):
        with self.gateway.open_image("render.png") as source:
            self.assertEqual(source.headers["Content-Type"], "image/png")
            self.assertEqual(int(source.headers["Content-Length"]), len(self.data))
            self.assertEqual(source.read(), self.data)
        self.assertEqual(self.calls, [("a" * 32, "stream")])
        self.assertFalse((self.root / "host").exists())
        self.assertEqual(self.manager.outputs.active, {})

    def test_audio_uses_same_binary_channel_without_automatic_host_download(self):
        from Legate.Forge.AudioForge.audio_forge.service import AudioService
        config = {"audio_forge": {"output_directory": str(self.root / "host-audio"), "max_text_chars": 12000},
                  "remote_nodes": {"audio_node_id": "a" * 32,
                    "control_url": f"http://127.0.0.1:{self.control.server_port}"}}
        service = AudioService(config)
        with patch.object(service, "_call", return_value={"status": "completed", "audio": [{"filename": "speech.wav"}]}) as call:
            result = service.execute({"text": "hello"})
            call.assert_called_once_with("synthesize", {"text": "hello"})
            self.assertIn("fallback_url", result["audio"][0])
        with service.open_audio("speech.wav") as source:
            self.assertEqual(source.read(), self.data)
        self.assertFalse((self.root / "host-audio").exists())
        self.assertEqual(self.calls, [("a" * 32, "stream")])

    def test_results_never_open_a_file_stream(self):
        fixture = {"status": "completed", "images": [{"filename": "render.png"}]}
        with patch.object(self.gateway, "_call", return_value=fixture) as call:
            self.assertEqual(self.gateway.result("job"), fixture)
            call.assert_called_once_with("poll", {"prompt_id": "job"})
        self.assertEqual(self.calls, [])

    def test_explicit_archive_contains_node_outputs_without_host_cache(self):
        with self.gateway.open_archive() as source:
            self.assertEqual(source.headers["Content-Type"], "application/zip")
            with zipfile.ZipFile(io.BytesIO(source.read())) as archive:
                self.assertEqual(archive.read("EverSpark-Outputs/render.png"), self.data)
        self.assertFalse((self.root / "host").exists())
        self.assertEqual(self.calls, [("a" * 32, "stream")])

    def test_unsafe_paths_are_rejected_before_node_task(self):
        for filename, subfolder in (("../private.png", ""), ("render.png", "../outside")):
            with self.assertRaises(ValueError):
                self.gateway.open_image(filename, subfolder)
        self.assertEqual(self.calls, [])

    def test_unknown_or_reused_capability_is_rejected(self):
        for authorization in ("", "Bearer " + "f" * 64):
            request = Request(f"http://127.0.0.1:{self.node.server_port}/node/output", data=b"x",
                              headers={"Authorization": authorization}, method="POST")
            with self.assertRaises(HTTPError) as caught:
                urlopen(request, timeout=2)
            self.assertEqual(caught.exception.code, 403)

    def test_queue_is_bounded_and_consumer_disconnect_aborts_producer(self):
        transfer = Transfer()
        self.assertEqual(transfer.blocks.maxsize, 8)
        transfer.closed.set()
        with self.assertRaises(ConnectionAbortedError):
            transfer.put(b"x")

    def test_missing_node_file_returns_failure_without_hanging(self):
        with self.assertRaises(HTTPError) as caught:
            self.gateway.open_image("missing.png")
        self.assertEqual(caught.exception.code, 502)
        self.assertEqual(self.manager.outputs.active, {})
