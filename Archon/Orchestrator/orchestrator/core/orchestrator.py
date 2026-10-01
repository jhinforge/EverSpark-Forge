"""Inter-Forge task admission, status and result aggregation only."""
from __future__ import annotations
import threading
import uuid
from typing import Any
from Aegis.Shared.errors import BusyError
from Aegis.Shared.text import normalize_unicode
from .task_runner import TaskRunner

class Orchestrator:
    def __init__(self, runner: TaskRunner, logger=None):
        self.logger = logger
        self.runner = runner
        self._task_lock = threading.Lock()
        self._task_jobs_lock = threading.Lock()
        self._task_jobs = {}

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
            result = self.submit(text, session, selection,
                _progress=lambda event: self._progress(job_id, event))
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

    def _progress(self, job_id, event):
        with self._task_jobs_lock:
            self._task_jobs[job_id]["tasks"] = event["tasks"]

    def submit(self, user_text: str, session_id: str, selection=None, *, _progress=None):
        text = normalize_unicode(user_text).strip()
        session = normalize_unicode(session_id).strip()
        if not text:
            raise ValueError("Task text cannot be empty")
        if not session or len(session) > 128:
            raise ValueError("session_id must contain 1 to 128 characters")
        if selection is not None and not isinstance(selection, dict):
            raise ValueError("selection must be a JSON object")
        if not self._task_lock.acquire(blocking=False):
            raise BusyError("A generation task is already running")
        notices = []
        try:
            def notify(event):
                if isinstance(event, dict) and "tasks" in event:
                    if _progress:
                        _progress(event)
                else:
                    notices.append(event)
            result = self.runner.run(text, session, selection or {}, notify)
            return {"ok": True, "notices": notices, "result": result}
        finally:
            self._task_lock.release()
