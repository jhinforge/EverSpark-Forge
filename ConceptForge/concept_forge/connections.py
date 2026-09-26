"""Persist user-managed text model connections on the server, with private keys."""

from __future__ import annotations

import json
import os
import threading
import uuid
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from .adapters import create_adapters
from .adapters.openai_compatible import OpenAICompatibleAdapter
from .gateway import ConceptGateway
from .port import ChatRequest

DEFAULT_PATH = Path(__file__).resolve().parents[2] / "Data/Configuration/ConceptForge/connections.json"


class ConceptConnections:
    def __init__(self, config: dict[str, Any], path: Path = DEFAULT_PATH, logger: Any = None):
        self.path = path
        self.lock = threading.RLock()
        self.configured = config
        self.logger = logger
        if path.is_file():
            data = json.loads(path.read_text(encoding="utf-8"))
            self.connections = data["connections"]
            self.default = data.get("default", config.get("provider", "ollama"))
        else:
            self.connections = []
            self.default = config.get("provider", "ollama")
        self.gateway = ConceptGateway(create_adapters(self._settings()), self.default)

    def _settings(self) -> dict[str, dict[str, Any]]:
        settings = dict(self.configured["providers"])
        for entry in self.connections:
            settings[entry["id"]] = {**entry, "provider_type": "openai_compatible",
                                      "_logger": self.logger}
        return settings

    def _refresh(self) -> None:
        gateway = ConceptGateway(create_adapters(self._settings()), self.default)
        self.gateway.adapters = gateway.adapters
        self.gateway.default = gateway.default

    def _write(self) -> None:
        self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        temporary = self.path.with_name(f".{self.path.name}.{uuid.uuid4().hex}.tmp")
        try:
            fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as output:
                json.dump({"default": self.default, "connections": self.connections}, output, ensure_ascii=False)
            os.replace(temporary, self.path)
            os.chmod(self.path, 0o600)
        finally:
            temporary.unlink(missing_ok=True)

    def public(self) -> dict[str, Any]:
        with self.lock:
            builtin = [{"id": name, "name": name.capitalize(), "type": name,
                        "model": str(value["model"]), "builtin": True}
                       for name, value in self.configured["providers"].items()]
            custom = [{"id": entry["id"], "name": entry["name"],
                       "type": "openai_compatible", "base_url": entry["base_url"],
                       "model": entry["model"], "json_mode": entry["json_mode"],
                       "has_api_key": bool(entry["api_key"]), "builtin": False}
                      for entry in self.connections]
            return {"default": self.default, "connections": builtin + custom}

    @staticmethod
    def _validated(payload: dict[str, Any], existing: dict[str, Any] | None = None) -> dict[str, Any]:
        name = str(payload.get("name", "")).strip()
        model = str(payload.get("model", "")).strip()
        base_url = str(payload.get("base_url", "")).strip().rstrip("/")
        api_key = str(payload.get("api_key", "")) or (existing or {}).get("api_key", "")
        parsed = urlparse(base_url)
        if not name or len(name) > 80 or not model or len(model) > 200:
            raise ValueError("Connection name and model ID are required")
        if not api_key or len(api_key) > 2048 or any(c in api_key for c in "\r\n"):
            raise ValueError("A valid API Key is required")
        if (parsed.scheme not in {"http", "https"} or not parsed.hostname
                or parsed.username or parsed.password or parsed.query or parsed.fragment
                or (parsed.scheme == "http" and parsed.hostname not in {"localhost", "127.0.0.1", "::1"})):
            raise ValueError("Use an HTTPS API base URL (HTTP only for local services)")
        if not base_url.endswith("/v1"):
            raise ValueError("API base URL must end in /v1")
        return {"name": name, "base_url": base_url, "api_key": api_key,
                "model": model, "json_mode": payload.get("json_mode", False) is True}

    def save(self, payload: dict[str, Any]) -> dict[str, Any]:
        with self.lock:
            identifier = str(payload.get("id", ""))
            old = next((entry for entry in self.connections if entry["id"] == identifier), None)
            if identifier and old is None:
                raise ValueError("Unknown model connection")
            entry = {"id": identifier or "api_" + uuid.uuid4().hex,
                     **self._validated(payload, old)}
            updated = [item for item in self.connections if item["id"] != identifier]
            updated.append(entry)
            self.connections = updated
            self._refresh()
            self._write()
            return self.public()

    def remove(self, identifier: str) -> dict[str, Any]:
        with self.lock:
            if not any(item["id"] == identifier for item in self.connections):
                raise ValueError("Unknown model connection")
            self.connections = [item for item in self.connections if item["id"] != identifier]
            if self.default == identifier:
                self.default = self.configured.get("provider", "ollama")
            self._refresh()
            self._write()
            return self.public()

    def set_default(self, identifier: str) -> dict[str, Any]:
        with self.lock:
            if identifier not in self.gateway.adapters:
                raise ValueError("Unknown model connection")
            self.default = identifier
            self._refresh()
            self._write()
            return self.public()

    def test(self, payload: dict[str, Any]) -> dict[str, Any]:
        with self.lock:
            identifier = str(payload.get("id", ""))
            old = next((entry for entry in self.connections if entry["id"] == identifier), None)
            settings = self._validated(payload, old)
        adapter = OpenAICompatibleAdapter({**settings, "timeout": 120,
                                           "_logger": self.logger,
                                           "_trace_id": str(payload.get("_trace_id", ""))})
        response = adapter.chat(ChatRequest(
            [{"role": "user", "content": "Reply with OK."}], settings["model"]
        ))
        if not response.content.strip():
            raise ValueError("Model returned an empty response")
        return {"model": settings["model"], "connected": True}
