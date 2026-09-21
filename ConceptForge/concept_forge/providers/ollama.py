from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

SYSTEM_PROMPT = """You are the Concept Forge component of EverSpark Forge.
Convert the user's image request into one complete JSON object and output JSON only.
Use the conversation history to resolve follow-up instructions such as changing one
detail, keeping the rest unchanged, or generating more images.
The only supported image model is illustrious.
Use exactly these fields:
{"model":"illustrious","positive_prompt":"...","negative_prompt":"...","count":1,"status":"over"}
count is the number of images requested by the user and defaults to 1.
Prompts should be suitable for an Illustrious/booru-style image workflow.
Do not use Markdown and do not add explanations outside the JSON object.
"""


class OllamaError(RuntimeError):
    pass


@dataclass(frozen=True)
class GenerationPlan:
    model: str
    positive_prompt: str
    negative_prompt: str
    count: int
    status: str


class OllamaProvider:
    def __init__(self, config: dict[str, Any]):
        self.base_url = str(config["base_url"]).rstrip("/")
        self.model = str(config["model"])
        self.timeout = int(config.get("timeout", 180))

    def generate_prompt(
        self, user_text: str, history: list[dict[str, str]] | None = None
    ) -> GenerationPlan:
        messages = [{"role": "system", "content": SYSTEM_PROMPT}]
        messages.extend(history or [])
        messages.append({"role": "user", "content": user_text})
        payload = {
            "model": self.model,
            "stream": False,
            "format": "json",
            "messages": messages,
        }
        response = self._post_json("/api/chat", payload)
        try:
            result = json.loads(response["message"]["content"])
        except (KeyError, TypeError, json.JSONDecodeError) as exc:
            raise OllamaError("Ollama returned an invalid prompt JSON response") from exc
        required = ("model", "positive_prompt", "negative_prompt", "status")
        if any(not isinstance(result.get(key), str) for key in required):
            raise OllamaError("Ollama prompt JSON is missing required string fields")
        try:
            count = int(result.get("count", 1))
        except (TypeError, ValueError) as exc:
            raise OllamaError("Ollama prompt JSON contains an invalid count") from exc
        return GenerationPlan(
            result["model"].strip().lower(),
            result["positive_prompt"].strip(),
            result["negative_prompt"].strip(),
            count,
            result["status"].strip().lower(),
        )

    def _post_json(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        request = Request(f"{self.base_url}{path}", data=json.dumps(payload, ensure_ascii=True).encode("utf-8"), headers={"Content-Type": "application/json; charset=utf-8"}, method="POST")
        try:
            with urlopen(request, timeout=self.timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise OllamaError(f"Ollama HTTP {exc.code}: {detail}") from exc
        except URLError as exc:
            raise OllamaError(f"Cannot connect to Ollama at {self.base_url}: {exc.reason}") from exc
        except json.JSONDecodeError as exc:
            raise OllamaError("Ollama returned invalid HTTP JSON") from exc
