"""Manage remote Forge deployment jobs without importing Forge execution code."""

from __future__ import annotations

import re
import shlex
import subprocess
import threading
import uuid
import json
import os
from pathlib import Path

from Archon.Steward.vast_instances import VastError


REPO = "/workspace/EverSpark-Forge"
_HOST = re.compile(r"[A-Za-z0-9.-]{1,253}\Z")


class DeploymentManager:
    def __init__(self, machines, identity, *, run=subprocess.run, state_path: Path | None = None):
        self.machines = machines
        self.identity = identity
        self.run = run
        self.jobs = {}
        self.state_path = state_path or (Path(os.environ.get("LOCALAPPDATA", str(Path.home())))
                                   / "EverSpark" / "deployment_states.json")
        try:
            data = json.loads(self.state_path.read_text(encoding="utf-8"))
            self.states = {int(key): value for key, value in data.items()
                           if isinstance(value, dict) and key.isdecimal()}
            for value in self.states.values():
                if value.get("status") in {"deploying", "updating"}:
                    value["status"] = ("deployment_failed" if value["status"] == "deploying"
                                       else "update_failed")
        except (OSError, ValueError, TypeError):
            self.states = {}
        self.lock = threading.Lock()

    def _save(self) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.state_path.with_suffix(".tmp")
        temporary.write_text(json.dumps(self.states), encoding="utf-8")
        temporary.replace(self.state_path)

    def status(self, instance_id: int) -> dict:
        with self.lock:
            return dict(self.states.get(instance_id, {"status": "not_deployed"}))

    def job(self, job_id: str) -> dict:
        with self.lock:
            if job_id not in self.jobs:
                raise VastError("Deployment job was not found", 404)
            return dict(self.jobs[job_id])

    def start(self, instance_id: int, action: str, message: str = "") -> dict:
        if action not in {"deploy", "update", "discuss"}:
            raise VastError("Unknown deployment action", 400)
        if action == "discuss" and (not isinstance(message, str) or not 1 <= len(message.strip()) <= 500):
            raise VastError("Enter a discussion message (up to 500 characters)", 400)
        machine = self.machines.one(instance_id)
        if machine["actual_status"] != "running":
            raise VastError("Wait for the Pod to finish starting", 409)
        if not machine.get("ssh_host") or not machine.get("ssh_port"):
            raise VastError("The Pod does not have an SSH address yet", 409)
        if action == "discuss" and self.status(instance_id).get("status") != "ready":
            raise VastError("Deploy Concept Forge before testing discussion", 409)
        with self.lock:
            if any(job["instance_id"] == instance_id and job["status"] == "running"
                   for job in self.jobs.values()):
                raise VastError("This Pod already has a running task", 409)
            job_id = uuid.uuid4().hex
            self.jobs[job_id] = {"id": job_id, "instance_id": instance_id,
                                 "action": action, "status": "running"}
            if action != "discuss":
                self.states[instance_id] = {"status": "deploying" if action == "deploy" else "updating"}
                self._save()
        threading.Thread(target=self._execute, args=(job_id, machine, message), daemon=True).start()
        return self.job(job_id)

    def _execute(self, job_id: str, machine: dict, message: str) -> None:
        action = self.jobs[job_id]["action"]
        instance_id = machine["id"]
        try:
            self.machines.attach_ssh(instance_id, self.identity.public_key())
            if action == "deploy":
                command = f"test -d {REPO}/.git && bash {REPO}/Legate/Forge/ConceptForge/Scripts/deploy.sh"
            elif action == "update":
                command = f"bash {REPO}/Legate/Envoy/update_source.sh"
            else:
                command = (f"python3 {REPO}/Legate/Forge/ConceptForge/verify.py "
                           f"{shlex.quote(message.strip())}")
            output = self._ssh(machine, command)
            update = {"status": "completed"}
            if action == "discuss":
                update["reply"] = output[-4000:]
            else:
                update["revision"] = self._ssh(machine, f"git -C {REPO} rev-parse --short HEAD").strip()
        except (VastError, OSError, subprocess.SubprocessError, RuntimeError, ValueError):
            update = {"status": "failed"}
        with self.lock:
            self.jobs[job_id].update(update)
            if action != "discuss":
                self.states[instance_id] = {"status": (
                    "ready" if action == "deploy" and update["status"] == "completed" else
                    "source_updated" if action == "update" and update["status"] == "completed" else
                    "deployment_failed" if action == "deploy" else "update_failed"),
                    **({"revision": update["revision"]} if "revision" in update else {})}
                self._save()

    def _ssh(self, machine: dict, command: str) -> str:
        host, port = machine["ssh_host"], machine["ssh_port"]
        if not isinstance(host, str) or not _HOST.fullmatch(host) or not isinstance(port, int) or not 1 <= port <= 65535:
            raise VastError("Invalid SSH address from Vast")
        result = self.run(["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=12",
                           "-o", "StrictHostKeyChecking=accept-new",
                           "-o", f"UserKnownHostsFile={self.identity.known_hosts}",
                           "-i", str(self.identity.private_key), "-p", str(port),
                           f"root@{host}", command], capture_output=True, text=True, timeout=1800)
        if result.returncode:
            raise VastError("Remote operation failed")
        return result.stdout.strip()
