"""Run a normalized Concept Forge chat request on the node's local model."""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from concept_forge.adapters.ollama import OllamaAdapter
from concept_forge.port import ChatRequest


def main() -> int:
    if len(sys.argv) != 2 or len(sys.argv[1]) > 60000:
        return 2
    request = json.loads(sys.argv[1])
    if (not isinstance(request, dict) or not isinstance(request.get("messages"), list)
            or not isinstance(request.get("model"), str)
            or not isinstance(request.get("json_mode"), bool)):
        return 2
    messages = request["messages"]
    if any(not isinstance(item, dict) or set(item) != {"role", "content"}
           or item["role"] not in {"system", "user", "assistant"}
           or not isinstance(item["content"], str) for item in messages):
        return 2
    adapter = OllamaAdapter({"base_url": "http://127.0.0.1:11434",
                             "model": "everspark-concept", "prompt_mode": "no_think",
                             "timeout": 180})
    content = adapter.chat(ChatRequest(messages, request["model"], request["json_mode"])).content
    print(content)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
