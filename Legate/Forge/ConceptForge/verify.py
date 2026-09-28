"""Run one real discussion on this node, using its local Concept Forge adapter."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from concept_forge.adapters.ollama import OllamaAdapter
from concept_forge.gateway import ConceptGateway
from concept_forge.service import ConceptService


def main() -> int:
    if len(sys.argv) != 2 or not 1 <= len(sys.argv[1].strip()) <= 500:
        return 2
    service = ConceptService(ConceptGateway({"ollama": OllamaAdapter({
        "base_url": "http://127.0.0.1:11434", "model": "everspark-concept",
        "prompt_mode": "no_think", "timeout": 180,
    })}, "ollama"))
    print(service.discuss(sys.argv[1].strip()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
