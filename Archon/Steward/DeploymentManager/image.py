"""Deploy Image Forge on a selected registered Pod."""

from __future__ import annotations

import threading
import uuid
import json
from pathlib import Path

from Archon.Steward.vast_instances import VastError


class ImageDeploymentManager:
    def __init__(self, machines, bridge, state_path: Path | None = None):
        self.machines = machines
        self.bridge = bridge
        self.lock = threading.RLock()
        self.state_path = state_path
        try:
            restored = json.loads(state_path.read_text(encoding="utf-8")) if state_path else {}
        except FileNotFoundError:
            restored = {}
        if not isinstance(restored, dict):
            raise ValueError("Invalid Image Forge deployment state")
        self.states: dict[int, dict] = {int(key): (
            {"status": "deployment_unknown"} if value.get("status") == "deploying" else value)
            for key, value in restored.items() if isinstance(value, dict)}
        self.jobs: dict[str, dict] = {}

    def _save(self) -> None:
        if self.state_path is None:
            return
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.state_path.with_name(self.state_path.name + ".tmp")
        temporary.write_text(json.dumps(self.states), encoding="utf-8")
        temporary.replace(self.state_path)

    def status(self, instance_id: int) -> dict:
        with self.lock:
            return self.states.get(instance_id, {"status": "not_deployed"}).copy()

    def job(self, job_id: str) -> dict:
        with self.lock:
            if job_id not in self.jobs:
                raise VastError("Unknown Image Forge deployment job", 404)
            return self.jobs[job_id].copy()

    def retire_instance(self, instance_id: int) -> None:
        with self.lock:
            self.states.pop(instance_id, None)
            self._save()

    def start(self, instance_id: int) -> dict:
        if not self.bridge or not self.bridge.configured(instance_id):
            raise VastError("Image Forge requires a registered Node Agent", 409)
        if self.machines.one(instance_id)["actual_status"] != "running":
            raise VastError("Wait for the Pod to finish starting", 409)
        with self.lock:
            if any(job["instance_id"] == instance_id and job["status"] == "running"
                   for job in self.jobs.values()):
                raise VastError("Image Forge deployment is already running on this Pod", 409)
            job_id = uuid.uuid4().hex
            job = {"id": job_id, "instance_id": instance_id, "action": "deploy-image",
                   "status": "running", "stage": "queued"}
            self.jobs[job_id] = job
            self.states[instance_id] = {"status": "deploying"}
            self._save()
        threading.Thread(target=self._deploy, args=(job_id, instance_id), daemon=True).start()
        return job.copy()

    def _deploy(self, job_id: str, instance_id: int) -> None:
        try:
            for action, timeout in (("deploy", 3600), ("health", 45), ("revision", 45)):
                with self.lock:
                    self.jobs[job_id]["stage"] = action
                output = self.bridge.execute(instance_id, action, timeout=timeout, forge="image")
                if not output.strip():
                    raise VastError(f"Image Forge {action} returned no output")
            with self.lock:
                self.states[instance_id] = {"status": "ready", "revision": output.strip()}
                self._save()
                self.jobs[job_id].update(status="completed", stage="ready", revision=output.strip())
        except Exception as exc:
            with self.lock:
                self.states[instance_id] = {"status": "deployment_failed"}
                self._save()
                self.jobs[job_id].update(status="failed", detail=str(exc)[-1600:])
