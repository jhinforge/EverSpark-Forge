"""Provider-neutral text model request and response contract."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


class ConceptError(RuntimeError):
    """A text model could not complete a Concept Forge request."""


@dataclass(frozen=True)
class ChatRequest:
    messages: list[dict[str, str]]
    model: str
    json_mode: bool = False


@dataclass(frozen=True)
class ChatResponse:
    content: str


class ConceptAdapter(Protocol):
    name: str
    model: str

    def chat(self, request: ChatRequest) -> ChatResponse: ...

    def list_models(self) -> list[str]: ...
