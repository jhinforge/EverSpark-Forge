from __future__ import annotations

import threading
from typing import Any

from everspark_memory import SQLiteMemoryStore

from .task_runner import TaskRunner
from .text import normalize_unicode


class BusyError(RuntimeError):
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

    def submit(self, user_text: str, session_id: str) -> dict[str, Any]:
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
            result = self.runner.run(text, history=history, notify=notices.append)
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
