"""EverSpark Concept Forge."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))

from .providers.ollama import GenerationPlan, OllamaProvider
from .service import ConceptService
from .gateway import ConceptGateway
from .port import ChatRequest, ChatResponse, ConceptError
from .subjects import (
    CompiledSubject,
    SubjectValidationError,
    compile_subject,
    new_subject,
    update_subject,
    validate_subject,
)

__all__ = [
    "CompiledSubject",
    "ChatRequest",
    "ChatResponse",
    "ConceptError",
    "ConceptGateway",
    "ConceptService",
    "GenerationPlan",
    "OllamaProvider",
    "SubjectValidationError",
    "compile_subject",
    "new_subject",
    "update_subject",
    "validate_subject",
]
