"""The backend-neutral contract between EverSpark and image engines."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass(frozen=True)
class ImageRequest:
    positive_prompt: str
    negative_prompt: str
    seed: int
    workflow: str = ""
    checkpoint: str = ""
    vae: str = ""
    loras: list[dict[str, Any]] = field(default_factory=list)


class ImageEngine(Protocol):
    name: str

    def resources(self) -> dict[str, Any]: ...

    def submit(self, request: ImageRequest, notify: Any = None) -> tuple[str, dict[str, Any]]: ...

    def poll(self, job_id: str) -> dict[str, Any]: ...

    def health(self) -> bool: ...
