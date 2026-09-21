from __future__ import annotations

import threading
from typing import Any

from concept_forge.subjects import compile_subject, update_subject, validate_subject
from everspark_memory import SQLiteMemoryStore

from .task_runner import TaskRunner
from .text import normalize_unicode


class BusyError(RuntimeError):
    pass


class SubjectNotFoundError(LookupError):
    pass


class Orchestrator:
    def __init__(self, config: dict[str, Any]):
        self.runner = TaskRunner(config)
        memory_config = config["memory"]
        self.memory = SQLiteMemoryStore(
            memory_config["database"],
            memory_config.get("max_history_messages", 20),
        )
        self._task_lock = threading.Lock()

    def submit(
        self, user_text: str, session_id: str, subject_id: str = ""
    ) -> dict[str, Any]:
        text = normalize_unicode(user_text).strip()
        session = normalize_unicode(session_id).strip()
        if not text:
            raise ValueError("Task text cannot be empty")
        if not session:
            raise ValueError("session_id cannot be empty")
        if len(session) > 128:
            raise ValueError("session_id is too long")
        if not self._task_lock.acquire(blocking=False):
            raise BusyError("The first-version Orchestrator is already running one task")
        notices: list[str] = []
        try:
            history = self.memory.get_history(session)
            compiled_subject = None
            normalized_subject_id = normalize_unicode(subject_id).strip()
            if normalized_subject_id:
                document = self.get_subject(normalized_subject_id)
                compiled_subject = compile_subject(document)
            result = self.runner.run(
                text,
                history=history,
                notify=notices.append,
                subject=compiled_subject,
            )
            self.memory.record_success(session, text, result)
            return {"ok": True, "notices": notices, "result": result}
        finally:
            self._task_lock.release()

    def get_history(self, session_id: str) -> list[dict[str, str]]:
        return self.memory.get_history(normalize_unicode(session_id).strip())

    def clear_memory(self, session_id: str) -> None:
        session = normalize_unicode(session_id).strip()
        if not session:
            raise ValueError("session_id cannot be empty")
        self.memory.clear_session(session)

    def save_subject(self, document: dict[str, Any]) -> dict[str, Any]:
        return self.memory.save_subject(validate_subject(document))

    def generate_subject(self, subject_id: str, user_text: str) -> dict[str, Any]:
        normalized = normalize_unicode(subject_id).strip()
        text = normalize_unicode(user_text).strip()
        if not normalized:
            raise ValueError("subject_id cannot be empty")
        if not text:
            raise ValueError("Subject description cannot be empty")
        existing = self.memory.get_subject(normalized)
        document = self.runner.concept.generate_subject(text, normalized, existing)
        return self.memory.save_subject(document)

    def update_subject(
        self, subject_id: str, changes: dict[str, Any]
    ) -> dict[str, Any]:
        current = self.get_subject(subject_id)
        updated = update_subject(current, changes)
        return self.memory.save_subject(updated)

    def get_subject(self, subject_id: str) -> dict[str, Any]:
        normalized = normalize_unicode(subject_id).strip()
        if not normalized:
            raise ValueError("subject_id cannot be empty")
        document = self.memory.get_subject(normalized)
        if document is None:
            raise SubjectNotFoundError(f"Subject not found: {normalized}")
        return document

    def list_subjects(self) -> list[dict[str, Any]]:
        return self.memory.list_subjects()

    def get_subject_revisions(self, subject_id: str) -> list[dict[str, Any]]:
        normalized = normalize_unicode(subject_id).strip()
        self.get_subject(normalized)
        return self.memory.get_subject_revisions(normalized)

    def compile_subject(self, subject_id: str) -> dict[str, Any]:
        compiled = compile_subject(self.get_subject(subject_id))
        return {
            "subject_id": compiled.subject_id,
            "revision": compiled.revision,
            "positive_prompt": compiled.positive_prompt,
            "negative_prompt": compiled.negative_prompt,
        }
