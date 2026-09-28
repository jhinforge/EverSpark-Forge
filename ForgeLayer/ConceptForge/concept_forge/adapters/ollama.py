"""Translate normalized text requests to and from the Ollama HTTP API."""

from __future__ import annotations

import json
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from ..port import ChatRequest, ChatResponse, ConceptError


class OllamaAdapter:
    name = "ollama"

    def __init__(self, config: dict[str, Any]):
        self.base_url = str(config["base_url"]).rstrip("/")
        self.model = str(config["model"])
        self.timeout = int(config.get("timeout", 180))
        self.prompt_mode = str(config.get("prompt_mode", "")).strip().lower()

    def chat(self, request: ChatRequest) -> ChatResponse:
        messages = [dict(message) for message in request.messages]
        if self.prompt_mode == "no_think":
            for message in messages:
                if message["role"] == "system":
                    message["content"] = message["content"].rstrip() + "\n/no_think\n"
        payload: dict[str, Any] = {
            "model": request.model or self.model,
            "stream": False,
            "messages": messages,
        }
        if request.json_mode:
            payload["format"] = "json"
        response = self._post_json("/api/chat", payload)
        try:
            content = response["message"]["content"]
        except (KeyError, TypeError) as exc:
            raise ConceptError("Ollama returned an invalid chat response") from exc
        if not isinstance(content, str):
            raise ConceptError("Ollama returned a non-text chat response")
        return ChatResponse(content)

    def list_models(self) -> list[str]:
        response = self._get_json("/api/tags")
        models = response.get("models", [])
        if not isinstance(models, list):
            raise ConceptError("Ollama model list has an invalid shape")
        names = []
        for item in models:
            if isinstance(item, dict) and isinstance(item.get("name"), str):
                name = item["name"].strip()
                if name:
                    names.append(name)
        return sorted(set(names), key=lambda item: (item.casefold(), item))

    def _get_json(self, path: str) -> dict[str, Any]:
        request = Request(f"{self.base_url}{path}", method="GET")
        return self._request_json(request)

    def _post_json(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        request = Request(
            f"{self.base_url}{path}",
            data=json.dumps(payload, ensure_ascii=True).encode("utf-8"),
            headers={"Content-Type": "application/json; charset=utf-8"},
            method="POST",
        )
        return self._request_json(request)

    def _request_json(self, request: Request) -> dict[str, Any]:
        try:
            with urlopen(request, timeout=self.timeout) as response:
                result = json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise ConceptError(f"Ollama HTTP {exc.code}: {detail}") from exc
        except URLError as exc:
            raise ConceptError(f"Cannot connect to Ollama at {self.base_url}: {exc.reason}") from exc
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ConceptError("Ollama returned invalid HTTP JSON") from exc
        if not isinstance(result, dict):
            raise ConceptError("Ollama returned an invalid JSON object")
        return result
