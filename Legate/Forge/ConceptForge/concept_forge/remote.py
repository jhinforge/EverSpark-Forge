"""Concept adapter using the Archon node bridge, independent of local Ollama."""

from __future__ import annotations

import json
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from concept_forge.port import ChatRequest, ChatResponse, ConceptError
from concept_forge.connections import ConceptConnections
from Archon.Gate.remote_target import target


class RemoteConceptAdapter:
    name = "ollama"

    def __init__(self, model: str, instance_id: int | str, control_url: str):
        self.model = model
        self.instance_id = instance_id  # Kept for compatibility; may now be a node_id string.
        self.url, self.target_identity = target(instance_id, control_url)

    def chat(self, request: ChatRequest) -> ChatResponse:
        message = json.dumps({"messages": request.messages, "model": request.model or self.model,
                              "json_mode": request.json_mode}, ensure_ascii=False)
        if len(message.encode("utf-8")) > 60000:
            raise ConceptError("Concept request exceeds the node task limit")
        body = json.dumps({**self.target_identity, "forge": "concept",
                           "action": "chat", "message": message}, ensure_ascii=False).encode("utf-8")
        call = Request(self.url, data=body, headers={"Content-Type": "application/json",
                       "Host": self.url.split("/")[2]}, method="POST")
        try:
            with urlopen(call, timeout=250) as response:
                result = json.load(response)
        except HTTPError as exc:
            raise ConceptError(f"Remote Concept Forge failed (HTTP {exc.code})") from exc
        except (URLError, TimeoutError, OSError, ValueError) as exc:
            raise ConceptError("Remote Concept Forge is unavailable") from exc
        content = result.get("output") if isinstance(result, dict) else None
        if not isinstance(content, str):
            raise ConceptError("Remote Concept Forge returned invalid output")
        return ChatResponse(content)

    def list_models(self) -> list[str]:
        return [self.model]


class RemoteConceptConnections(ConceptConnections):
    def __init__(self, config: dict, instance_id: int | str, control_url: str, logger=None):
        self.remote_instance_id = instance_id
        self.remote_control_url = control_url
        super().__init__(config, logger=logger)
        self.default = "ollama"
        self.gateway.default = "ollama"
        self._apply_remote()

    def _apply_remote(self) -> None:
        self.gateway.adapters["ollama"] = RemoteConceptAdapter(
            str(self.configured["providers"]["ollama"]["model"]),
            self.remote_instance_id, self.remote_control_url)

    def _refresh(self) -> None:
        super()._refresh()
        self._apply_remote()
