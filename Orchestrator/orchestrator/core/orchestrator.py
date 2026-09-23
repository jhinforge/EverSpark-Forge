from __future__ import annotations

import threading
import sys
from pathlib import Path
from typing import Any

from concept_forge.subjects import compile_subject, update_subject, validate_subject
from everspark_memory import SQLiteMemoryStore

from .task_runner import TaskRunner
from .text import normalize_unicode

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT / "Infrastructure" / "Storage"))
from r2_manager import R2StorageManager  # noqa: E402
from download_manager import DirectDownloadManager  # noqa: E402
from backup_manager import BackupManager  # noqa: E402


class BusyError(RuntimeError):
    pass


class SubjectNotFoundError(LookupError):
    pass


class Orchestrator:
    def __init__(self, config: dict[str, Any]):
        self.runner = TaskRunner(config)
        self.storage = R2StorageManager(config)
        self.downloads = DirectDownloadManager(config)
        self.backups = BackupManager(config)
        memory_config = config["memory"]
        self.memory = SQLiteMemoryStore(
            memory_config["database"],
            memory_config.get("max_history_messages", 20),
        )
        self._task_lock = threading.Lock()

    def submit(
        self,
        user_text: str,
        session_id: str,
        selection: dict[str, Any] | None = None,
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
        selected = self._normalize_selection(selection)
        try:
            history = self.memory.get_history(session)
            document = self._refresh_session_subject(
                session,
                text,
                history,
                llm_model=str(selected.get("llm", "")),
            )
            compiled_subject = compile_subject(document)
            result = self.runner.run(
                text,
                history=history,
                notify=notices.append,
                subject=compiled_subject,
                selection=selected,
            )
            self.memory.record_success(session, text, result)
            return {"ok": True, "notices": notices, "result": result}
        finally:
            self._task_lock.release()

    def discuss(
        self,
        user_text: str,
        session_id: str,
        selection: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        text = normalize_unicode(user_text).strip()
        session = normalize_unicode(session_id).strip()
        if not text:
            raise ValueError("Message cannot be empty")
        if not session:
            raise ValueError("session_id cannot be empty")
        if len(session) > 128:
            raise ValueError("session_id is too long")
        if not self._task_lock.acquire(blocking=False):
            raise BusyError("The first-version Orchestrator is already running one task")
        selected = self._normalize_selection(selection)
        llm_model = str(selected.get("llm", ""))
        try:
            history = self.memory.get_history(session)
            if llm_model:
                reply = self.runner.concept.discuss(text, history, model=llm_model)
            else:
                reply = self.runner.concept.discuss(text, history)
            document = self._refresh_session_subject(
                session,
                text,
                history,
                assistant_reply=reply,
                llm_model=llm_model,
            )
            self.memory.record_conversation(session, text, reply)
            return {"ok": True, "reply": reply, "subject": document}
        finally:
            self._task_lock.release()

    def _refresh_session_subject(
        self,
        session_id: str,
        user_text: str,
        history: list[dict[str, str]],
        assistant_reply: str = "",
        llm_model: str = "",
    ) -> dict[str, Any]:
        subject_id = self.memory.get_or_create_session_subject_id(session_id)
        existing = self.memory.get_subject(subject_id)
        kwargs = {"history": history, "assistant_reply": assistant_reply}
        if llm_model:
            kwargs["model"] = llm_model
        document = self.runner.concept.generate_subject(
            user_text, subject_id, existing, **kwargs
        )
        if existing is not None:
            comparable_existing = {**existing, "revision": document["revision"]}
            if comparable_existing == document:
                return existing
        return self.memory.save_subject(document)

    def get_session_subject(self, session_id: str) -> dict[str, Any] | None:
        session = normalize_unicode(session_id).strip()
        if not session:
            raise ValueError("session_id cannot be empty")
        subject_id = self.memory.get_session_subject_id(session)
        return None if subject_id is None else self.memory.get_subject(subject_id)

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

    def resources(self) -> dict[str, Any]:
        return self.runner.resources()

    def storage_resources(self) -> dict[str, Any]:
        return self.storage.resources()

    def backup_resources(self) -> dict[str, Any]:
        return self.backups.resources()

    def start_backup(self, names: list[str], memory: bool = False) -> dict[str, Any]:
        return self.backups.start(names, memory)

    def backup_job(self, job_id: str = "") -> dict[str, Any] | None:
        return self.backups.job(job_id)

    def start_storage_pull(self, kind: str, name: str) -> dict[str, Any]:
        return self.storage.start_pull(kind, name)

    def storage_job(self, job_id: str = "") -> dict[str, Any] | None:
        return self.storage.job(job_id)

    def start_download(
        self,
        kind: str,
        url: str,
        filename: str = "",
        runtime_name: str = "",
    ) -> dict[str, Any]:
        return self.downloads.start(kind, url, filename, runtime_name)

    def download_job(self, job_id: str = "") -> dict[str, Any] | None:
        return self.downloads.job(job_id)

    def cancel_download(self, job_id: str) -> dict[str, Any]:
        return self.downloads.cancel(job_id)

    def retry_download(self, job_id: str) -> dict[str, Any]:
        return self.downloads.retry(job_id)

    @staticmethod
    def _normalize_selection(
        selection: dict[str, Any] | None,
    ) -> dict[str, Any]:
        if selection is None:
            return {}
        if not isinstance(selection, dict):
            raise ValueError("selection must be a JSON object")
        return selection
