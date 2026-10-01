"""Concept Forge owns conversation, Subject, Memory and provider management.

The existing model gateway may use a local adapter or the unchanged Envoy
remote transport. Persistent data is provided by Ledger through Memory.
"""
from __future__ import annotations
import re
from contextlib import contextmanager
import threading
import time
import uuid
from typing import Any
from urllib.error import HTTPError
from urllib.parse import urlparse
from Aegis.Shared.text import normalize_unicode
from Aegis.Shared.errors import BusyError
from everspark_memory import SQLiteMemoryStore
from .subjects import compile_subject, update_subject, validate_subject
from .planning import ConceptPlanning

class SubjectNotFoundError(LookupError):
    pass

def _safe_header(headers: Any, name: str) -> str:
    value = headers.get(name, "") if headers is not None else ""
    return value if isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9._:-]{1,128}", value) else ""

class ConceptWorkspace:
    def __init__(self, config, service, connections, logger=None):
        self.service = service
        self.connections = connections
        self.logger = logger
        self.memory = SQLiteMemoryStore(config["memory"]["database"],
            config["memory"].get("max_history_messages", 20))
        self._task_lock = threading.Lock()
        self._connection_test_lock = threading.Lock()
        self._connection_test_jobs = {}
        self.planning = ConceptPlanning(config["concept_forge"], service)

    def busy(self):
        return self._task_lock.locked()

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
        selected = self._normalize_selection(selection)
        if not self._task_lock.acquire(blocking=False):
            raise BusyError("The first-version Concept Forge is already running one task")
        llm_model = str(selected.get("llm", ""))
        concept_provider = str(selected.get("concept_provider", ""))
        try:
            with self.memory.operation():
                history = self.memory.get_history(session)
                kwargs = {}
                if llm_model:
                    kwargs["model"] = llm_model
                if concept_provider:
                    kwargs["provider"] = concept_provider
                reply = self.service.discuss(text, history, **kwargs)
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
        document = self.service.generate_subject(
            user_text, subject_id, existing, **kwargs
        )
        if existing is not None:
            comparable_existing = {**existing, "revision": document["revision"]}
            if comparable_existing == document:
                return existing
        return self.memory.save_subject(document) if persist else document

    def get_session_subject(self, session_id: str) -> dict[str, Any] | None:
        with self.memory.operation():
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
            with self.memory.operation():
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
            raise BusyError("Concept Forge is busy")
        try:
            with self.memory.operation():
                self.memory.clear_session(session)
        finally:
            self._task_lock.release()

    def save_subject(self, document: dict[str, Any]) -> dict[str, Any]:
        if not self._task_lock.acquire(blocking=False):
            raise BusyError("Concept Forge is busy")
        try:
            with self.memory.operation():
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
            raise BusyError("Concept Forge is busy")
        try:
            with self.memory.operation():
                existing = self.memory.get_subject(normalized)
                document = self.service.generate_subject(text, normalized, existing)
                return self.memory.save_subject(document)
        finally:
            self._task_lock.release()

    def update_subject(
        self, subject_id: str, changes: dict[str, Any]
    ) -> dict[str, Any]:
        if not self._task_lock.acquire(blocking=False):
            raise BusyError("Concept Forge is busy")
        try:
            with self.memory.operation():
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
        with self.memory.operation():
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
            raise BusyError("Concept Forge is already running one task")
        try:
            with self.memory.operation():
                current = self.get_subject(subject_id)
                if group in {"positive_prompt", "negative_prompt"}:
                    prompts = self.memory.get_subject_prompt(subject_id) or {}
                    value = self.service.revise_prompt(text, group, prompts.get(group, ""))
                    self.memory.save_subject_prompt(
                        subject_id,
                        value if group == "positive_prompt" else prompts.get("positive_prompt", ""),
                        value if group == "negative_prompt" else prompts.get("negative_prompt", ""),
                    )
                else:
                    generated = self.service.revise_subject_section(text, group, current)
                    if {**current, "revision": generated["revision"]} != generated:
                        self.memory.save_subject(validate_subject(generated))
                return self.subject_bundle(subject_id)
        finally:
            self._task_lock.release()

    def list_subjects(self) -> list[dict[str, Any]]:
        return self.memory.list_subjects()

    def get_subject_revisions(self, subject_id: str) -> list[dict[str, Any]]:
        with self.memory.operation():
            normalized = normalize_unicode(subject_id).strip()
            self.get_subject(normalized)
            return self.memory.get_subject_revisions(normalized)

    def compile_subject(self, subject_id: str) -> dict[str, Any]:
        with self.memory.operation():
            subject = self.get_subject(subject_id)
            prompts = self.memory.get_subject_prompt(subject_id)
            compiled = compile_subject(subject)
            return {
                "subject_id": compiled.subject_id,
                "revision": compiled.revision,
                "positive_prompt": prompts["positive_prompt"] if prompts and prompts["positive_prompt"] else compiled.positive_prompt,
                "negative_prompt": prompts["negative_prompt"] if prompts else "",
            }

    def concept_connections(self) -> dict[str, Any]:
        return self.connections.public()

    def save_concept_connection(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self.connections.save(payload)

    def test_concept_connection(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self.connections.test(payload)

    def start_concept_connection_test(self, payload: dict[str, Any]) -> dict[str, Any]:
        job_id = uuid.uuid4().hex
        with self._connection_test_lock:
            if len(self._connection_test_jobs) >= 100:
                for old_id, old in self._connection_test_jobs.copy().items():
                    if old["status"] in {"completed", "failed"}:
                        del self._connection_test_jobs[old_id]
                        break
            if len(self._connection_test_jobs) >= 100:
                raise BusyError("Too many model connection tests are running")
            job = {"id": job_id, "status": "running"}
            self._connection_test_jobs[job_id] = job
        threading.Thread(target=self._run_concept_connection_test,
                         args=(job_id, payload.copy()), daemon=True).start()
        return job.copy()

    def _run_concept_connection_test(self, job_id: str, payload: dict[str, Any]) -> None:
        started = time.monotonic()
        logger = getattr(self, "logger", None)
        try:
            if logger is not None:
                parsed = urlparse(str(payload.get("base_url", "")))
                logger.info(
                    "concept.connection_test.start", "Model connection test started",
                    job_id=job_id, host=parsed.hostname or "",
                    path=("/v1/chat/completions" if parsed.path == "/v1"
                          else "[custom path]/chat/completions"),
                    model=str(payload.get("model", "")), method="POST",
                    transport="urllib.request", json_mode=False,
                )
            result = self.test_concept_connection({**payload, "_trace_id": job_id})
            update = {"status": "completed", "result": result}
            if logger is not None:
                logger.ok(
                    "concept.connection_test.ok", "Model connection test completed",
                    job_id=job_id, http_status=200,
                    elapsed_ms=round((time.monotonic() - started) * 1000),
                )
        except Exception as exc:
            update = {"status": "failed", "error": str(exc)}
            if logger is not None:
                upstream = exc.__cause__ if isinstance(exc.__cause__, HTTPError) else None
                headers = upstream.headers if upstream is not None else None
                logger.error(
                    "concept.connection_test.failed", "Model connection test failed",
                    job_id=job_id, error_type=type(exc).__name__,
                    http_status=upstream.code if upstream is not None else None,
                    key_origin="form" if payload.get("api_key") else "saved",
                    upstream_request_id=_safe_header(headers, "x-request-id"),
                    cf_ray=_safe_header(headers, "cf-ray"),
                    elapsed_ms=round((time.monotonic() - started) * 1000),
                    error=(str(exc).replace(str(payload.get("api_key", "")), "[REDACTED]")
                           if payload.get("api_key") else str(exc)),
                )
        with self._connection_test_lock:
            self._connection_test_jobs[job_id].update(update)

    def concept_connection_test_job(self, job_id: str) -> dict[str, Any]:
        if len(job_id) != 32 or any(char not in "0123456789abcdef" for char in job_id):
            raise ValueError("Invalid model connection test ID")
        with self._connection_test_lock:
            job = self._connection_test_jobs.get(job_id)
            if job is None:
                raise ValueError("Unknown model connection test")
            return job.copy()

    def remove_concept_connection(self, identifier: str) -> dict[str, Any]:
        return self.connections.remove(identifier)

    def default_concept_connection(self, identifier: str) -> dict[str, Any]:
        return self.connections.set_default(identifier)

    @staticmethod
    def _normalize_selection(
        selection: dict[str, Any] | None,
    ) -> dict[str, Any]:
        if selection is None:
            return {}
        if not isinstance(selection, dict):
            raise ValueError("selection must be a JSON object")
        return selection

    @contextmanager
    def prepare_generation(self, text, session, selection, notify):
        if not self._task_lock.acquire(blocking=False):
            raise BusyError("Concept Forge is busy")
        try:
            with self.memory.operation():
                yield self._prepare_generation(text, session, selection, notify)
        finally:
            self._task_lock.release()

    def _prepare_generation(self, text, session, selection, notify):
        history = self.memory.get_history(session)
        document = self._refresh_session_subject(
            session,
            text,
            history,
            llm_model=str(selection.get("llm", "")),
            concept_provider=str(selection.get("concept_provider", "")),
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
        instruction, model_selection = self.planning.plan(
            text, history=history, notify=notify, subject=compiled_subject,
            selection=selection,
            saved_negative_prompt=(saved_prompts["negative_prompt"]
                if saved_prompts and saved_prompts["negative_prompt"] and not changes_negative else None),
            previous_positive_prompt=saved_prompts["positive_prompt"] if saved_prompts else "",
            change_negative_prompt=changes_negative)
        return PreparedGeneration(self, session, text, document, instruction, model_selection)

    def resources(self):
        llms = self.service.list_models()
        default_llm = self.planning._resolve_model(self.service.model, llms)
        providers = self.connections.public()["connections"]
        models = {self.service.gateway.default: llms}
        for entry in providers:
            if entry["id"] not in models:
                try:
                    models[entry["id"]] = self.service.list_models(entry["id"])
                except (OSError, RuntimeError):
                    models[entry["id"]] = []
        return {"llms": llms, "concept_providers": providers, "concept_models": models,
            "defaults": {"llm": default_llm or self.service.model,
                         "concept_provider": self.service.gateway.default}}

class PreparedGeneration:
    """Concept-owned context; the coordinator only transfers its instruction."""
    def __init__(self, owner, session, text, document, instruction, model_selection):
        self.owner, self.session, self.text = owner, session, text
        self.document, self.instruction = document, instruction
        self.model_selection = model_selection

    def complete(self, result):
        result["selection"].update(self.model_selection)
        result["subject"] = {"subject_id": self.document["subject_id"],
                             "revision": self.document["revision"]}
        memory = self.owner.memory
        latest = memory.get_subject(self.document["subject_id"])
        if latest is not None and latest == self.document:
            memory.save_subject_prompt(self.document["subject_id"],
                result["positive_prompt"], result["negative_prompt"])
        else:
            memory.save_subject(self.document, {"positive_prompt": result["positive_prompt"],
                "negative_prompt": result["negative_prompt"]})
        memory.record_success(self.session, self.text, result)
        return result
