"""OpenAI Chat Completions wire format for user-configured compatible services."""

from __future__ import annotations

import json
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from ..port import ChatRequest, ChatResponse, ConceptError


class OpenAICompatibleAdapter:
    name = "openai_compatible"

    def __init__(self, config: dict[str, Any]):
        self.base_url = str(config["base_url"]).rstrip("/")
        self.api_key = str(config["api_key"])
        self.model = str(config["model"])
        self.timeout = int(config.get("timeout", 180))
        self.json_mode = bool(config.get("json_mode", False))

    def list_models(self) -> list[str]:
        # /models is optional on compatible services. This is the tested model ID.
        return [self.model]

    def chat(self, request: ChatRequest) -> ChatResponse:
        payload: dict[str, Any] = {
            "model": request.model or self.model,
            "messages": request.messages,
            "stream": False,
        }
        if request.json_mode and self.json_mode:
            payload["response_format"] = {"type": "json_object"}
        wire = Request(
            f"{self.base_url}/chat/completions",
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {self.api_key}"},
            method="POST",
        )
        try:
            with urlopen(wire, timeout=self.timeout) as response:
                result = json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            # Do not forward arbitrary upstream bodies: some proxies echo request headers.
            raise ConceptError(f"OpenAI Compatible HTTP {exc.code}") from exc
        except URLError as exc:
            raise ConceptError(f"OpenAI Compatible connection failed: {exc.reason}") from exc
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ConceptError("OpenAI Compatible returned invalid JSON") from exc
        try:
            content = result["choices"][0]["message"]["content"]
        except (IndexError, KeyError, TypeError) as exc:
            raise ConceptError("OpenAI Compatible returned an invalid chat response") from exc
        if not isinstance(content, str):
            raise ConceptError("OpenAI Compatible returned a non-text response")
        return ChatResponse(content)
