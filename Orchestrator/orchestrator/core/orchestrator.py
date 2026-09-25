from __future__ import annotations

import re

import threading
import uuid
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
from local_data_archive import LocalDataArchive  # noqa: E402


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
        self.data_archive = LocalDataArchive(
            self.backups.memory_path, self.backups.subject_root, REPO_ROOT
        )
        memory_config = config["memory"]
        self.memory = SQLiteMemoryStore(
            memory_config["database"],
            memory_config.get("max_history_messages", 20),
        )
        self._task_lock = threading.Lock()
        self._task_jobs_lock = threading.Lock()
        self._task_jobs: dict[str, dict[str, Any]] = {}

    def start_task(
        self, user_text: str, session_id: str,
        selection: dict[str, Any] | None = None, request_id: str = "",
    ) -> dict[str, Any]:
        if not normalize_unicode(user_text).strip():
            raise ValueError("Task text cannot be empty")
        if not normalize_unicode(session_id).strip() or len(session_id) > 128:
            raise ValueError("session_id must contain 1 to 128 characters")
        if selection is not None and not isinstance(selection, dict):
            raise ValueError("selection must be a JSON object")
        job_id = request_id or uuid.uuid4().hex
        if len(job_id) != 32 or any(char not in "0123456789abcdef" for char in job_id):
            raise ValueError("Invalid task request ID")
        with self._task_jobs_lock:
            existing = self._task_jobs.get(job_id)
            if existing:
                if existing["session_id"] != session_id or existing["text"] != user_text or existing["selection"] != (selection or {}):
                    raise ValueError("Task request ID already belongs to another request")
                return {key: value for key, value in existing.items() if key not in {"session_id", "text", "selection"}}
            if any(item["status"] in {"queued", "running"} for item in self._task_jobs.values()):
                raise BusyError("A generation task is already running")
            if len(self._task_jobs) >= 100:
                for stale_id in list(self._task_jobs):
                    if self._task_jobs[stale_id]["status"] in {"completed", "failed"}:
                        del self._task_jobs[stale_id]
                        break
            job = {"id": job_id, "status": "queued", "session_id": session_id,
                   "text": user_text, "selection": selection or {}}
            self._task_jobs[job_id] = job
            threading.Thread(target=self._execute_task, args=(job_id,), daemon=True).start()
            return {"id": job_id, "status": "queued"}

    def _execute_task(self, job_id: str) -> None:
        with self._task_jobs_lock:
            job = self._task_jobs[job_id]
            job["status"] = "running"
            text, session, selection = job["text"], job["session_id"], job["selection"]
        try:
            result = self.submit(text, session, selection)
            update = {"status": "completed", "response": result}
        except Exception as exc:
            update = {"status": "failed", "error": str(exc)}
        with self._task_jobs_lock:
            self._task_jobs[job_id].update(update)

    def task_job(self, job_id: str) -> dict[str, Any]:
        if len(job_id) != 32 or any(char not in "0123456789abcdef" for char in job_id):
            raise ValueError("Invalid task request ID")
        with self._task_jobs_lock:
            job = self._task_jobs.get(job_id)
            if job is None:
                raise ValueError("Unknown generation task")
            return {key: value for key, value in job.items() if key not in {"session_id", "text", "selection"}}

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
                concept_provider=str(selected.get("concept_provider", "")),
                persist=False,
            )
            saved_prompts = self.memory.get_subject_prompt(document["subject_id"])
            compiled_subject = compile_subject(document)
            # An existing negative prompt is immutable unless the request explicitly
            # asks to change negative prompting.
            changes_negative = bool(re.search(
                r"(?:修改|更改|调整|重写|替换|清空|删除|添加|增加|改|换|加|删).{0,12}(?:负面|负向)提示词"
                r"|(?:负面|负向)提示词.{0,12}(?:修改|更改|调整|重写|替换|清空|删除|添加|增加|改|换|加|删)"
                r"|(?:change|edit|update|replace|remove|add|clear).{0,30}negative\s+(?:prompt|terms)",
                text, re.IGNORECASE,
            )) and not bool(re.search(r"(?:不要|别|不必|无需).{0,8}(?:修改|更改|调整|重写|替换|清空|删除|添加|增加|改|换|加|删).{0,12}(?:负面|负向)提示词", text))
            result = self.runner.run(
                text,
                history=history,
                notify=notices.append,
                subject=compiled_subject,
                selection=selected,
                saved_negative_prompt=(saved_prompts["negative_prompt"]
                                       if saved_prompts and saved_prompts["negative_prompt"] and not changes_negative else None),
                previous_positive_prompt=(saved_prompts["positive_prompt"]
                                          if saved_prompts else ""),
            )
            latest = self.memory.get_subject(document["subject_id"])
            if latest is not None and latest == document:
                self.memory.save_subject_prompt(
                    document["subject_id"], result["positive_prompt"], result["negative_prompt"]
                )
            else:
                self.memory.save_subject(document, {
                    "positive_prompt": result["positive_prompt"],
                    "negative_prompt": result["negative_prompt"],
                })
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
        concept_provider = str(selected.get("concept_provider", ""))
        try:
            history = self.memory.get_history(session)
            kwargs = {}
            if llm_model:
                kwargs["model"] = llm_model
            if concept_provider:
                kwargs["provider"] = concept_provider
            reply = self.runner.concept.discuss(text, history, **kwargs)
            document = self._refresh_session_subject(
                session,
                text,
                history,
                assistant_reply=reply,
                llm_model=llm_model,
                concept_provider=concept_provider,
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
        concept_provider: str = "",
        persist: bool = True,
    ) -> dict[str, Any]:
        subject_id = self.memory.get_or_create_session_subject_id(session_id)
        existing = self.memory.get_subject(subject_id)
        kwargs = {"history": history, "assistant_reply": assistant_reply}
        if llm_model:
            kwargs["model"] = llm_model
        if concept_provider:
            kwargs["provider"] = concept_provider
        document = self.runner.concept.generate_subject(
            user_text, subject_id, existing, **kwargs
        )
        if existing is not None:
            comparable_existing = {**existing, "revision": document["revision"]}
            if comparable_existing == document:
                return existing
        return self.memory.save_subject(document) if persist else document

    def get_session_subject(self, session_id: str) -> dict[str, Any] | None:
        session = normalize_unicode(session_id).strip()
        if not session:
            raise ValueError("session_id cannot be empty")
        subject_id = self.memory.get_session_subject_id(session)
        return None if subject_id is None else self.memory.get_subject(subject_id)

    def select_session_subject(self, session_id: str, subject_id: str) -> dict[str, Any]:
        session = normalize_unicode(session_id).strip()
        if not session or len(session) > 128:
            raise ValueError("session_id must contain 1 to 128 characters")
        if not self._task_lock.acquire(blocking=False):
            raise BusyError("Wait for the current task before switching characters")
        try:
            subject = self.get_subject(normalize_unicode(subject_id).strip())
            self.memory.select_session_subject(session, subject["subject_id"])
            return subject
        finally:
            self._task_lock.release()

    def get_history(self, session_id: str) -> list[dict[str, str]]:
        return self.memory.get_history(normalize_unicode(session_id).strip())

    def clear_memory(self, session_id: str) -> None:
        session = normalize_unicode(session_id).strip()
        if not session:
            raise ValueError("session_id cannot be empty")
        if not self._task_lock.acquire(blocking=False):
            raise BusyError("Orchestrator is busy")
        try:
            self.memory.clear_session(session)
        finally:
            self._task_lock.release()

    def save_subject(self, document: dict[str, Any]) -> dict[str, Any]:
        if not self._task_lock.acquire(blocking=False):
            raise BusyError("Orchestrator is busy")
        try:
            return self.memory.save_subject(validate_subject(document))
        finally:
            self._task_lock.release()

    def generate_subject(self, subject_id: str, user_text: str) -> dict[str, Any]:
        normalized = normalize_unicode(subject_id).strip()
        text = normalize_unicode(user_text).strip()
        if not normalized:
            raise ValueError("subject_id cannot be empty")
        if not text:
            raise ValueError("Subject description cannot be empty")
        if not self._task_lock.acquire(blocking=False):
            raise BusyError("Orchestrator is busy")
        try:
            existing = self.memory.get_subject(normalized)
            document = self.runner.concept.generate_subject(text, normalized, existing)
            return self.memory.save_subject(document)
        finally:
            self._task_lock.release()

    def update_subject(
        self, subject_id: str, changes: dict[str, Any]
    ) -> dict[str, Any]:
        if not self._task_lock.acquire(blocking=False):
            raise BusyError("Orchestrator is busy")
        try:
            current = self.get_subject(subject_id)
            updated = update_subject(current, changes)
            return self.memory.save_subject(updated)
        finally:
            self._task_lock.release()

    def get_subject(self, subject_id: str) -> dict[str, Any]:
        normalized = normalize_unicode(subject_id).strip()
        if not normalized:
            raise ValueError("subject_id cannot be empty")
        document = self.memory.get_subject(normalized)
        if document is None:
            raise SubjectNotFoundError(f"Subject not found: {normalized}")
        return document

    def subject_bundle(self, subject_id: str) -> dict[str, Any]:
        document = self.get_subject(subject_id)
        prompts = self.memory.get_subject_prompt(document["subject_id"]) or {}
        return {
            "subject_id": document["subject_id"],
            "subject": {key: value for key, value in document.items() if key != "metadata"},
            "metadata": document["metadata"],
            "positive_prompt": {"positive_prompt": prompts.get("positive_prompt", "")},
            "negative_prompt": {"negative_prompt": prompts.get("negative_prompt", "")},
        }

    def revise_subject_group(self, subject_id: str, group: str, instruction: str) -> dict[str, Any]:
        text = normalize_unicode(instruction).strip()
        if not text:
            raise ValueError("Describe the change to make")
        if group not in {"subject", "metadata", "positive_prompt", "negative_prompt"}:
            raise ValueError("Unknown subject group")
        if not self._task_lock.acquire(blocking=False):
            raise BusyError("Orchestrator is already running one task")
        try:
            current = self.get_subject(subject_id)
            if group in {"positive_prompt", "negative_prompt"}:
                prompts = self.memory.get_subject_prompt(subject_id) or {}
                value = self.runner.concept.revise_prompt(text, group, prompts.get(group, ""))
                self.memory.save_subject_prompt(
                    subject_id,
                    value if group == "positive_prompt" else prompts.get("positive_prompt", ""),
                    value if group == "negative_prompt" else prompts.get("negative_prompt", ""),
                )
            else:
                generated = self.runner.concept.revise_subject_section(text, group, current)
                if {**current, "revision": generated["revision"]} != generated:
                    self.memory.save_subject(validate_subject(generated))
            return self.subject_bundle(subject_id)
        finally:
            self._task_lock.release()

    def list_subjects(self) -> list[dict[str, Any]]:
        return self.memory.list_subjects()

    def get_subject_revisions(self, subject_id: str) -> list[dict[str, Any]]:
        normalized = normalize_unicode(subject_id).strip()
        self.get_subject(normalized)
        return self.memory.get_subject_revisions(normalized)

    def compile_subject(self, subject_id: str) -> dict[str, Any]:
        subject = self.get_subject(subject_id)
        prompts = self.memory.get_subject_prompt(subject_id)
        compiled = compile_subject(subject)
        return {
            "subject_id": compiled.subject_id,
            "revision": compiled.revision,
            "positive_prompt": prompts["positive_prompt"] if prompts and prompts["positive_prompt"] else compiled.positive_prompt,
            "negative_prompt": prompts["negative_prompt"] if prompts else "",
        }

    def resources(self, engine: str = "") -> dict[str, Any]:
        return self.runner.resources(engine)

    def concept_connections(self) -> dict[str, Any]:
        return self.runner.concept_connections.public()

    def save_concept_connection(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self.runner.concept_connections.save(payload)

    def test_concept_connection(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self.runner.concept_connections.test(payload)

    def remove_concept_connection(self, identifier: str) -> dict[str, Any]:
        return self.runner.concept_connections.remove(identifier)

    def default_concept_connection(self, identifier: str) -> dict[str, Any]:
        return self.runner.concept_connections.set_default(identifier)

    def image_health(self) -> dict[str, Any]:
        engine = self.runner.gateway.select()
        return {"ok": engine.health(), "engine": engine.name}

    def image_plugins(self) -> dict[str, Any]:
        return self.runner.plugins.plugins()

    def image_plugin_job(self, job_id: str) -> dict[str, Any]:
        return self.runner.plugins.job(job_id)

    def start_image_plugin(self, name: str, action: str) -> dict[str, Any]:
        return self.runner.plugins.start(name, action)

    def set_default_image_plugin(self, name: str) -> dict[str, Any]:
        return self.runner.plugins.set_default(name)

    def image_results(self, job_ids: list[str]) -> list[dict[str, Any]]:
        return self.runner.gateway.results(job_ids)

    def image_history(self, limit: int) -> list[dict[str, str]]:
        return self.runner.gateway.history(limit)

    def image_path(self, filename: str, subfolder: str, kind: str) -> Path:
        return self.runner.gateway.image_path(filename, subfolder, kind)

    def storage_resources(self) -> dict[str, Any]:
        return self.storage.resources()

    def export_data_archive(self) -> str:
        if not self._task_lock.acquire(blocking=False):
            raise BusyError("A task is running; try again after it completes")
        try:
            with self.memory._subject_lock:
                archive_id, _ = self.data_archive.export()
            return archive_id
        finally:
            self._task_lock.release()

    def restore_data_archive(self, archive_id: str) -> dict[str, Any]:
        if not self._task_lock.acquire(blocking=False):
            raise BusyError("A task is running; try again after it completes")
        try:
            with self.memory._subject_lock:
                return self.data_archive.restore(archive_id)
        finally:
            self._task_lock.release()

    def storage_scan(self) -> dict[str, Any]:
        return self.storage.scan_status()

    def start_storage_scan(self) -> dict[str, Any]:
        return self.storage.start_scan()

    def backup_resources(self) -> dict[str, Any]:
        return self.backups.resources()

    def restore_points(self) -> list[dict[str, Any]]:
        return self.backups.restore_points()

    def start_restore(self, batch_id: str) -> dict[str, Any]:
        return self.backups.start_restore(batch_id, self._task_lock, self.memory._subject_lock)

    def save_storage_paths(self, mapping: dict[str, Any]) -> dict[str, Any]:
        return self.storage.save_paths(mapping)

    def start_backup(self, names: list[str], memory: bool = False,
                     targets: dict[str, str] | None = None, outputs: bool = False) -> dict[str, Any]:
        return self.backups.start(names, memory, targets, outputs)

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
