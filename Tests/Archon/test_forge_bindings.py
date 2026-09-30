"""Manual Node endpoint persistence and safe runtime replacement."""
import json
import tempfile
import unittest
from pathlib import Path
from Archon.Gate.forge_bindings import ForgeBindings
from Archon.Steward.NodeManager.errors import NodeError


class Nodes:
    def __init__(self):
        self.states = {key * 32: "online" for key in "abc"}
    def configured(self, node_id):
        return self.states.get(node_id) in {"online", "offline"}
    def status(self, node_id):
        return {"status": self.states.get(node_id, "unconfigured")}


class Runtime:
    def __init__(self, bindings):
        self.bindings = dict(bindings)
        self.url = "http://127.0.0.1:12345"
        self.closed = self.running = False
    def busy(self):
        return self.running
    def close(self):
        self.closed = True


class ForgeBindingsTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "bindings.json"
        self.nodes, self.created = Nodes(), []
        def factory(bindings, url):
            self.assertEqual(url, "http://127.0.0.1:8765")
            runtime = Runtime(bindings)
            self.created.append(runtime)
            return runtime
        self.factory = factory
        self.bindings = ForgeBindings(self.nodes, self.path, "http://127.0.0.1:8765", factory=factory)
        self.addCleanup(self.bindings.close)

    def select_pair(self):
        self.bindings.select({"forge": "concept", "node_id": "a" * 32})
        self.bindings.select({"forge": "image", "node_id": "b" * 32})

    def test_lazy_remote_runtime_and_durable_node_ids_restore(self):
        state = self.bindings.select({"forge": "concept", "node_id": "a" * 32})
        self.assertFalse(state["ready"])
        self.assertEqual(self.created, [])
        self.bindings.select({"forge": "image", "node_id": "b" * 32})
        self.assertTrue(self.bindings.status()["ready"])
        self.assertEqual(json.loads(self.path.read_text()), {"concept": "a" * 32, "image": "b" * 32})
        self.nodes.states["a" * 32] = "offline"
        restored = ForgeBindings(self.nodes, self.path, "http://127.0.0.1:8765", factory=self.factory)
        self.addCleanup(restored.close)
        restored.restore()
        self.assertTrue(restored.url)
        self.assertFalse(restored.status()["ready"])
        self.assertEqual(restored.status()["nodes"]["concept"], "offline")
        self.assertEqual(restored.bindings, self.bindings.bindings)

    def test_unknown_offline_or_invalid_nodes_do_not_change_selection(self):
        self.nodes.states["c" * 32] = "offline"
        for body in ({"forge": "image", "node_id": "c" * 32},
                     {"forge": "image", "node_id": "d" * 32},
                     {"forge": "image", "node_id": "99"},
                     {"forge": "audio", "node_id": "a" * 32}):
            with self.subTest(body=body), self.assertRaises(NodeError):
                self.bindings.select(body)
        self.assertEqual(self.bindings.bindings, {})

    def test_active_request_and_async_task_prevent_runtime_switch(self):
        self.select_pair()
        with self.bindings.request() as url:
            self.assertEqual(url, self.bindings.url)
            with self.assertRaises(NodeError):
                self.bindings.select({"forge": "image", "node_id": "c" * 32})
        self.bindings.runtime.running = True
        with self.assertRaises(NodeError):
            self.bindings.select({"forge": "image", "node_id": "c" * 32})
        self.bindings.runtime.running = False
        previous = self.bindings.runtime
        self.bindings.select({"forge": "image", "node_id": "c" * 32})
        self.assertTrue(previous.closed)
        self.assertEqual(self.bindings.bindings["image"], "c" * 32)

    def test_failed_runtime_creation_preserves_working_selection(self):
        self.select_pair()
        previous = self.bindings.runtime
        def fail(*args):
            raise RuntimeError("runtime init failed")
        self.bindings.factory = fail
        with self.assertRaises(RuntimeError):
            self.bindings.select({"forge": "image", "node_id": "c" * 32})
        self.assertIs(self.bindings.runtime, previous)
        self.assertFalse(previous.closed)
        self.assertEqual(json.loads(self.path.read_text())["image"], "b" * 32)

    def test_removed_node_disables_execution_without_silently_selecting_another(self):
        self.select_pair()
        self.nodes.states["b" * 32] = "removed"
        self.assertEqual(self.bindings.url, "")
        self.assertFalse(self.bindings.status()["ready"])
        self.assertEqual(self.bindings.bindings["image"], "b" * 32)
