"""Compatibility import for callers using the former OllamaProvider interface."""

from __future__ import annotations

from typing import Any

from ..adapters.ollama import OllamaAdapter
from ..gateway import ConceptGateway
from ..port import ConceptError
from ..service import ConceptService, GenerationPlan

OllamaError = ConceptError


class OllamaProvider(ConceptService):
    def __init__(self, config: dict[str, Any]):
        super().__init__(ConceptGateway({"ollama": OllamaAdapter(config)}, "ollama"))
