"""Deploy Image Forge on a selected registered Pod."""

from __future__ import annotations

import threading
import uuid
import json
from pathlib import Path

from Archon.Steward.vast_instances import VastError
from .verification import ConnectionVerification
from .progress import job_progress, active_job
from .job_store import JobStore


class ImageDeploymentManager:
    forge = "image"
    label = "Image Forge"

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
            raise ValueError(f"Invalid {self.label} deployment state")
        self.states: dict[int, dict] = {int(key): (
            {"status": "deployment_unknown"} if value.get("status") == "deploying" else
            {"status": "verification_required"} if value.get("status") in {"verifying", "ready"} else value)
            for key, value in restored.items() if isinstance(value, dict)}
        self.job_store = JobStore(state_path, self.forge)
        self.jobs = self.job_store.load()
        self.retired_instances = set()
        self.connection_verification = ConnectionVerification(self, self.forge)
        for job_id, job in list(self.jobs.items()):
            if job["status"] == "running":
                self.states[job["instance_id"]] = {"status": "recovering"}
                threading.Thread(target=self._recover, args=(job_id,), daemon=True,
                                 name=f"{self.forge}-deployment-recovery").start()

    def _save(self) -> None:
        if self.state_path is None:
            return
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.state_path.with_name(self.state_path.name + ".tmp")
        temporary.write_text(json.dumps(self.states), encoding="utf-8")
        temporary.replace(self.state_path)

    def status(self, instance_id: int) -> dict:
        runtime = self.bridge.runtime_id(instance_id) if self.bridge and hasattr(self.bridge, "runtime_id") else None
        with self.lock:
            state = self.states.get(instance_id, {"status": "not_deployed"})
            if state.get("status") == "ready" and runtime and runtime != state.get("runtime_id"):
                state = self.states[instance_id] = {"status": "verification_required"}
                self._save()
            return active_job(self, instance_id, state.copy())

    def reconcile_machine(self, machine):
        instance_id = machine["id"]
        if machine.get("actual_status") == "stopped":
            with self.lock:
                if self.states.get(instance_id, {}).get("status") == "ready":
                    self.states[instance_id] = {"status": "verification_required"}
                    self._save()
        if machine.get("actual_status") == "running":
            self.connection_verification.consider(instance_id)

    def job(self, job_id: str) -> dict:
        with self.lock:
            if job_id not in self.jobs:
                raise VastError(f"Unknown {self.label} deployment job", 404)
            return job_progress(self.bridge, self.jobs[job_id].copy())

    def retire_instance(self, instance_id: int) -> None:
        with self.lock:
            self.retired_instances.add(instance_id)
            self.states.pop(instance_id, None)
            self._save()

    def start(self, instance_id: int, action: str = "deploy") -> dict:
        if action not in {"deploy", "verify"}:
            raise VastError(f"Unsupported {self.label} deployment action", 400)
        if not self.bridge or not self.bridge.configured(instance_id):
            raise VastError(f"{self.label} requires a registered Node Agent", 409)
        if self.machines.one(instance_id)["actual_status"] != "running":
            raise VastError("Wait for the Pod to finish starting", 409)
        with self.lock:
            if any(job["instance_id"] == instance_id and job["status"] == "running"
                   for job in self.jobs.values()):
                raise VastError(f"{self.label} deployment is already running on this Pod", 409)
            job_id = uuid.uuid4().hex
            job = {"id": job_id, "instance_id": instance_id, "action": f"{action}-{self.forge}",
                   "status": "running", "stage": "queued"}
            self.jobs[job_id] = job
            self.job_store.save(self.jobs)
            self.states[instance_id] = {"status": "deploying" if action == "deploy" else "verifying"}
            self._save()
        threading.Thread(target=self._deploy, args=(job_id, instance_id, action), daemon=True).start()
        return job.copy()

    def _recover(self, job_id):
        """Read the original Agent result, then verify without reinstalling."""
        with self.lock:
            job = self.jobs[job_id].copy()
        instance_id = job["instance_id"]
        operation = "deploy" if job["action"] == f"deploy-{self.forge}" else "verify"
        confirmed_failure = False
        try:
            found = json.loads(self.bridge.execute(instance_id, "recover", job["task_id"],
                                                  timeout=3700, forge=self.forge))
            if not isinstance(found, dict) or found.get("state") != "completed" or found.get("status") not in {"completed", "failed"}:
                raise VastError(f"Agent cannot confirm the previous {self.forge} task; outcome unknown")
            if found["status"] == "failed":
                confirmed_failure = True
                from Archon.Steward.NodeManager.errors import NodeTaskError
                error = NodeTaskError(str(found.get("output", "")), found.get("exit_code"))
                error.stage = found.get("stage") or job["task_action"]
                raise error
        except Exception as exc:
            if not confirmed_failure:
                exc = VastError(f"{self.forge} task recovery could not confirm the result; outcome unknown: {exc}")
                exc.stage = "recovery_unknown"
            self._failed(job_id, instance_id, operation, exc)
            return
        self._deploy(job_id, instance_id, "verify")

    def _deploy(self, job_id: str, instance_id: int, operation: str = "deploy") -> None:
        try:
            steps = {"deploy": (("deploy", 3600), ("health", 45), ("revision", 45)),
                     "verify": (("health", 45), ("revision", 45))}
            for action, timeout in steps[operation]:
                with self.lock:
                    self.jobs[job_id]["stage"] = action
                task_id = uuid.uuid4().hex
                with self.lock:
                    self.jobs[job_id]["task_id"] = task_id
                    self.jobs[job_id]["task_action"] = action
                    self.job_store.save(self.jobs)
                output = self.bridge.execute(instance_id, action, timeout=timeout, forge=self.forge, task_id=task_id)
                if not output.strip():
                    raise VastError(f"{self.label} {action} returned no output")
            with self.lock:
                if instance_id in self.retired_instances:
                    raise VastError("Node instance was destroyed", 404)
                runtime = self.bridge.runtime_id(instance_id) if hasattr(self.bridge, "runtime_id") else None
                self.states[instance_id] = {"status": "ready", "revision": output.strip(),
                                            **({"runtime_id": runtime} if runtime else {})}
                self._save()
                self.jobs[job_id].update(status="completed", stage="ready", revision=output.strip())
                self.job_store.save(self.jobs)
        except Exception as exc:
            self._failed(job_id, instance_id, operation, exc)

    def _failed(self, job_id, instance_id, operation, exc):
        with self.lock:
            detail = str(getattr(exc, "detail", None) or str(exc))[-1600:]
            stage = getattr(exc, "stage", self.jobs[job_id]["stage"])
            if instance_id not in self.retired_instances:
                self.states[instance_id] = {"status": "deployment_unknown" if "outcome unknown" in detail or getattr(exc, "status", None) == 504 else
                    "deployment_failed" if operation == "deploy" else "verification_required", "detail": detail,
                    "stage": stage, "exit_code": getattr(exc, "exit_code", None)}
            self._save()
            self.jobs[job_id].update(status="failed", stage=stage, detail=detail)
            if isinstance(getattr(exc, "exit_code", None), int):
                self.jobs[job_id]["exit_code"] = exc.exit_code
            self.job_store.save(self.jobs)
