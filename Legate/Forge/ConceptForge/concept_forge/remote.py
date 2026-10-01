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
        return ChatResponse(self._request("chat", message))

    def _request(self, action, message):
        if len(message.encode("utf-8")) > 60000:
            raise ConceptError("Concept request exceeds the node task limit")
        body = json.dumps({**self.target_identity, "forge": "concept",
                           "action": action, "message": message}, ensure_ascii=False).encode("utf-8")
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
        return content

    def list_models(self) -> list[str]:
        try:
            if "node_id" in self.target_identity:
                parts = urlsplit(self.url)
                with urlopen(Request(f"{parts.scheme}://{parts.netloc}/nodes"), timeout=5) as response:
                    nodes = json.load(response)["nodes"]
                if not any(node.get("node_id") == self.target_identity["node_id"]
                           and node.get("status") == "online" for node in nodes):
                    return []
            names = json.loads(self._request("models", "{}"))
            if not isinstance(names, list) or any(not isinstance(name, str) for name in names):
                raise ValueError("Invalid model list")
            return names
        except (ValueError, OSError, KeyError, TypeError) as exc:
            raise ConceptError("Remote Concept Forge returned invalid models") from exc


class RemoteConceptConnections(ConceptConnections):
    def __init__(self, config: dict, instance_id: int | str, control_url: str, logger=None):
        self.remote_instance_id = instance_id
        self.remote_control_url = control_url
        super().__init__(config, logger=logger)
        self._apply_remote()

    def _apply_remote(self) -> None:
        self.gateway.adapters["ollama"] = RemoteConceptAdapter(
            str(self.configured["providers"]["ollama"]["model"]),
            self.remote_instance_id, self.remote_control_url)

    def _refresh(self) -> None:
        super()._refresh()
        self._apply_remote()
