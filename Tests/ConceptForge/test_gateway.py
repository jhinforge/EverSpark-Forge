from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch


REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "ConceptForge"))

from concept_forge.adapters import create_adapters  # noqa: E402
from concept_forge.adapters.ollama import OllamaAdapter  # noqa: E402
from concept_forge.gateway import ConceptGateway  # noqa: E402
from concept_forge.port import ChatRequest, ChatResponse, ConceptError  # noqa: E402


class ConceptGatewayTests(unittest.TestCase):
    def test_gateway_routes_normalized_requests_by_adapter(self) -> None:
        class FakeAdapter:
            def __init__(self, name):
                self.name = name
                self.model = name + "-model"
                self.received = []

            def chat(self, request):
                self.received.append(request)
                return ChatResponse(self.name + " reply")

            def list_models(self):
                return [self.model]

        first, second = FakeAdapter("first"), FakeAdapter("second")
        gateway = ConceptGateway({"first": first, "second": second}, "first")
        request = ChatRequest([{"role": "user", "content": "hello"}], "custom", True)
        self.assertEqual(gateway.chat(request).content, "first reply")
        self.assertEqual(gateway.chat(request, "second").content, "second reply")
        self.assertEqual(first.received, [request])
        self.assertEqual(second.received, [request])
        self.assertEqual(gateway.list_models("second"), ["second-model"])

    def test_discovery_loads_configured_ollama_adapter(self) -> None:
        adapters = create_adapters({"ollama": {"base_url": "http://localhost:11434", "model": "local"}})
        self.assertIsInstance(adapters["ollama"], OllamaAdapter)
        self.assertEqual(adapters["ollama"].model, "local")

    def test_ollama_input_and_output_use_only_the_adapter(self) -> None:
        adapter = OllamaAdapter({"base_url": "http://localhost:11434", "model": "local",
                                 "prompt_mode": "no_think"})
        messages = [{"role": "system", "content": "Be concise"},
                    {"role": "user", "content": "hello"}]
        request = ChatRequest(messages, "another-model", True)
        with patch.object(adapter, "_post_json", return_value={"message": {"content": "{\"ok\":true}"}}) as post:
            response = adapter.chat(request)
        self.assertEqual(response.content, '{"ok":true}')
        payload = post.call_args.args[1]
        self.assertEqual(payload["model"], "another-model")
        self.assertEqual(payload["format"], "json")
        self.assertFalse(payload["stream"])
        self.assertEqual(payload["messages"][0]["content"], "Be concise\n/no_think\n")
        self.assertEqual(messages[0]["content"], "Be concise")
        with patch.object(adapter, "_post_json", return_value={"message": {}}):
            with self.assertRaises(ConceptError):
                adapter.chat(request)


if __name__ == "__main__":
    unittest.main()
