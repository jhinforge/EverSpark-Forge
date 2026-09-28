"""Correlate one HTTP request with its Concept Forge adapter calls."""

from contextlib import contextmanager
from contextvars import ContextVar
from typing import Iterator

_trace_id: ContextVar[str] = ContextVar("concept_forge_trace_id", default="")


def current_trace_id() -> str:
    return _trace_id.get()


@contextmanager
def trace_scope(identifier: str) -> Iterator[None]:
    token = _trace_id.set(identifier)
    try:
        yield
    finally:
        _trace_id.reset(token)
