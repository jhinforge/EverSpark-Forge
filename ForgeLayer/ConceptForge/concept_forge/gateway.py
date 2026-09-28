"""Route normalized Concept Forge requests to a configured text model adapter."""

from __future__ import annotations

from .port import ChatRequest, ChatResponse, ConceptAdapter


class ConceptGateway:
    def __init__(self, adapters: dict[str, ConceptAdapter], default: str):
        if not adapters or default not in adapters:
            raise ValueError(f"Unsupported Concept Forge provider: {default}")
        self.adapters = adapters
        self.default = default

    @property
    def model(self) -> str:
        return self.adapters[self.default].model

    def chat(self, request: ChatRequest, provider: str = "") -> ChatResponse:
        return self.select(provider).chat(request)

    def list_models(self, provider: str = "") -> list[str]:
        return self.select(provider).list_models()

    def select(self, provider: str = "") -> ConceptAdapter:
        selected = provider or self.default
        if selected not in self.adapters:
            raise ValueError(f"Unsupported Concept Forge provider: {selected}")
        return self.adapters[selected]
