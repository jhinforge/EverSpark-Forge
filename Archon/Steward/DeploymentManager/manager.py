"""Manage remote Forge deployment jobs without importing Forge execution code."""

from __future__ import annotations

import re
import shlex
import subprocess
import threading
import uuid
import json
import os
import sys
import time
import traceback
from pathlib import Path
from datetime import datetime, timezone

from Archon.Steward.vast_instances import VastError


REPO = "/workspace/EverSpark-Forge"
_HOST = re.compile(r"[A-Za-z0-9.-]{1,253}\Z")
LOG_PATH = Path(__file__).with_name("deployment.log")
LOG_LIMIT = 2 * 1024 * 1024


class RemoteCommandError(VastError):
    def __init__(self, stage: str, exit_code: int, detail: str):
        super().__init__("Remote operation failed")
        self.stage = stage
        self.exit_code = exit_code
        self.detail = detail[-1600:] or "No output from remote command"


class DeploymentManager:
    def __init__(self, machines, identity, *, run=subprocess.run, state_path: Path | None = None,
                 log_path: Path | None = None, bridge=None):
        self.machines = machines
        self.identity = identity
        self.bridge = bridge
        self.run = run
        self.jobs = {}
        self.threads = {}
        self.log_path = log_path if log_path is not None else LOG_PATH
        self.log_lock = threading.Lock()
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
        self.retired_instances = set()

    def _event(self, job_id: str, instance_id: int, action: str, event: str, **fields) -> None:
        # Only pass controlled metadata here. Commands, prompts, keys and SSH output
        # must never be persisted in the local task log.
        entry = {"at": datetime.now(timezone.utc).isoformat(), "job_id": job_id,
                 "instance_id": instance_id, "action": action, "event": event, **fields}
        try:
            with self.log_lock:
                self.log_path.parent.mkdir(parents=True, exist_ok=True)
                if self.log_path.exists() and self.log_path.stat().st_size >= LOG_LIMIT:
                    self.log_path.replace(self.log_path.with_suffix(".log.1"))
                with self.log_path.open("a", encoding="utf-8") as log:
                    log.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except OSError:
            # A read-only checkout must not prevent deploying or testing a Forge.
            pass

    def _save(self) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.state_path.with_suffix(".tmp")
        temporary.write_text(json.dumps(self.states), encoding="utf-8")
        temporary.replace(self.state_path)

    def status(self, instance_id: int) -> dict:
        with self.lock:
            return dict(self.states.get(instance_id, {"status": "not_deployed"}))

    def reconcile_instances(self, first_page: dict) -> bool:
        """Forget destroyed instances only after a complete, valid Vast inventory."""
        known = set()
        seen_cursors = set()
        page = first_page
        while True:
            for machine in page["instances"]:
                instance_id = machine.get("id")
                if not isinstance(instance_id, int) or isinstance(instance_id, bool) or instance_id < 1:
                    return False
                known.add(instance_id)
            cursor = page.get("next_token")
            if not cursor:
                break
            if cursor in seen_cursors or not isinstance(cursor, str):
                return False
            seen_cursors.add(cursor)
            try:
                page = self.machines.list(cursor)
            except VastError:
                return False
        total = first_page.get("total")
        if isinstance(total, int) and total > len(known):
            return False
        with self.lock:
            candidates = set(self.states) - known
        if self.bridge:
            candidates.update(self.bridge.instance_ids() - known)
        for instance_id in candidates:
            try:
                self.machines.one(instance_id)
            except VastError as exc:
                if exc.status == 404:
                    continue
            # A transient inventory gap or failed inspection must not revoke a node.
            known.add(instance_id)
        removed_nodes = self.bridge.prune(known) if self.bridge else set()
        with self.lock:
            removed = set(self.states) - known
            self.retired_instances.update(removed | removed_nodes)
            if removed:
                for instance_id in removed:
                    self.states.pop(instance_id)
                self._save()
        return True

    def job(self, job_id: str) -> dict:
        with self.lock:
            if job_id not in self.jobs:
                raise VastError("Deployment job was not found", 404)
            result = dict(self.jobs[job_id])
            worker = self.threads.get(job_id)
            if result["status"] == "running" and worker is not None and worker.ident is not None:
                if not worker.is_alive():
                    result.update({"status": "failed", "stage": "worker_exit",
                                   "detail": "Background deployment worker exited unexpectedly"})
                    self.jobs[job_id].update(result)
                    self._event(job_id, result["instance_id"], result["action"],
                                "finished", status="failed", stage="worker_exit")
                else:
                    frame = sys._current_frames().get(worker.ident)
                    if frame is not None:
                        result["worker_stack"] = [
                            f"{Path(entry.filename).name}:{entry.lineno}:{entry.name}"
                            for entry in traceback.extract_stack(frame)[-8:]
                        ]
            return result

    def start(self, instance_id: int, action: str, message: str = "") -> dict:
        if action not in {"deploy", "update", "discuss"}:
            raise VastError("Unknown deployment action", 400)
        if action == "discuss" and (not isinstance(message, str) or not 1 <= len(message.strip()) <= 500):
            raise VastError("Enter a discussion message (up to 500 characters)", 400)
        machine = self.machines.one(instance_id)
        if machine["actual_status"] != "running":
            raise VastError("Wait for the Pod to finish starting", 409)
        if not (self.bridge and self.bridge.configured(instance_id)) and (
            not machine.get("ssh_host") or not machine.get("ssh_port")
        ):
            raise VastError("The Pod does not have an SSH address yet", 409)
        if action == "discuss" and self.status(instance_id).get("status") != "ready":
            raise VastError("Deploy Concept Forge before testing discussion", 409)
        with self.lock:
            if any(job["instance_id"] == instance_id and job["status"] == "running"
                   for job in self.jobs.values()):
                raise VastError("This Pod already has a running task", 409)
            key_ready = self.states.get(instance_id, {}).get("status") in {"ready", "source_updated"}
            job_id = uuid.uuid4().hex
            self.jobs[job_id] = {"id": job_id, "instance_id": instance_id,
                                 "action": action, "status": "running", "stage": "queued"}
            if action != "discuss":
                self.states[instance_id] = {"status": "deploying" if action == "deploy" else "updating"}
                self._save()
        worker = threading.Thread(target=self._execute,
                                  args=(job_id, machine, message, key_ready), daemon=True)
        with self.lock:
            self.threads[job_id] = worker
        self._event(job_id, instance_id, action, "queued")
        worker.start()
        return self.job(job_id)

    def _stage(self, job_id: str, value: str) -> None:
        with self.lock:
            self.jobs[job_id]["stage"] = value
            self.jobs[job_id]["stage_at"] = datetime.now(timezone.utc).isoformat()
            instance_id, action = self.jobs[job_id]["instance_id"], self.jobs[job_id]["action"]
        self._event(job_id, instance_id, action, "stage", stage=value)

    def _execute(self, job_id: str, machine: dict, message: str, key_ready: bool) -> None:
        action = self.jobs[job_id]["action"]
        instance_id = machine["id"]
        stage = "ssh_identity"
        error_type = None
        try:
            use_agent = bool(self.bridge and self.bridge.configured(instance_id))
            if not key_ready and not use_agent:
                self._stage(job_id, stage)
                public_key = self.identity.public_key()
                stage = "attach_ssh_key"
                self._stage(job_id, stage)
                try:
                    self.machines.attach_ssh(instance_id, public_key)
                    self._event(job_id, instance_id, action, "vast_attach", status="completed")
                except VastError as attachment_error:
                    self._event(job_id, instance_id, action, "vast_attach", status="rejected",
                                http_status=attachment_error.status)
                    # An already attached key can be rejected as a duplicate.
                    # Continue only if this exact local identity works.
                    stage = "ssh_probe"
                    self._stage(job_id, stage)
                    try:
                        self._ssh(machine, "true", timeout=30, job_id=job_id, action=action,
                                  stage="ssh_probe")
                    except (VastError, OSError, subprocess.SubprocessError):
                        raise attachment_error from None
            if action == "deploy":
                command = (f"test -d {REPO}/.git || {{ echo 'Pod repository is missing' >&2; exit 1; }}; "
                           f"bash {REPO}/Legate/Forge/ConceptForge/Scripts/deploy.sh")
            elif action == "update":
                command = f"bash {REPO}/Legate/Envoy/update_source.sh"
            else:
                command = (f"python3 {REPO}/Legate/Forge/ConceptForge/verify.py "
                           f"{shlex.quote(message.strip())}")
            stage = "agent_execution" if use_agent else "remote_execution"
            self._stage(job_id, stage)
            if use_agent:
                self._event(job_id, instance_id, action, "agent_start", stage=stage)
                output = self.bridge.execute(instance_id, action, message,
                                              timeout=240 if action == "discuss" else 1800)
                self._event(job_id, instance_id, action, "agent_exit", stage=stage)
            else:
                output = self._ssh(machine, command, timeout=240 if action == "discuss" else 1800,
                                   job_id=job_id, action=action, stage=stage)
            update = {"status": "completed"}
            if action == "discuss":
                update["reply"] = output[-4000:]
            else:
                stage = "read_revision"
                self._stage(job_id, stage)
                update["revision"] = (self.bridge.execute(instance_id, "revision", timeout=45)
                                      if use_agent else self._ssh(
                                          machine, f"git -C {REPO} rev-parse --short HEAD",
                                          stage="read_revision", job_id=job_id,
                                          action=action)).strip()
        except Exception as exc:
            # A background thread must always finish its job, including when
            # Windows subprocess decoding or provider response handling fails.
            error_type = type(exc).__name__
            update = {"status": "failed", "stage": getattr(exc, "stage", stage),
                      "detail": getattr(exc, "detail", str(exc))[-1600:] or type(exc).__name__}
            if isinstance(getattr(exc, "exit_code", None), int):
                update["exit_code"] = exc.exit_code
        with self.lock:
            self.jobs[job_id].update(update)
            self.jobs[job_id]["finished_at"] = datetime.now(timezone.utc).isoformat()
            if action != "discuss" and instance_id not in self.retired_instances:
                self.states[instance_id] = {"status": (
                    "ready" if action == "deploy" and update["status"] == "completed" else
                    "source_updated" if action == "update" and update["status"] == "completed" else
                    "deployment_failed" if action == "deploy" else "update_failed"),
                    **({"revision": update["revision"]} if "revision" in update else {})}
                self._save()
        self._event(job_id, instance_id, action, "finished", status=update["status"],
                    stage=update.get("stage", stage),
                    **({"error_type": error_type} if error_type else {}),
                    **({"exit_code": update["exit_code"]} if "exit_code" in update else {}))

    def _ssh(self, machine: dict, command: str, *, stage: str = "pod_command",
             timeout: int = 1800, job_id: str | None = None, action: str = "") -> str:
        host, port = machine["ssh_host"], machine["ssh_port"]
        if not isinstance(host, str) or not _HOST.fullmatch(host) or not isinstance(port, int) or not 1 <= port <= 65535:
            raise VastError("Invalid SSH address from Vast")
        ssh = "ssh"
        if os.name == "nt":
            windows_ssh = Path(os.environ.get("WINDIR", "C:\\Windows")) / "System32" / "OpenSSH" / "ssh.exe"
            if windows_ssh.is_file():
                ssh = str(windows_ssh)
        if job_id is not None:
            self._event(job_id, machine["id"], action, "ssh_start", stage=stage,
                        timeout_seconds=timeout)
        started = time.monotonic()
        try:
            result = self.run([ssh, "-o", "BatchMode=yes", "-o", "ConnectTimeout=12",
                           "-o", "StrictHostKeyChecking=accept-new",
                           "-o", f"UserKnownHostsFile={self.identity.known_hosts}",
                           "-i", str(self.identity.private_key), "-p", str(port),
                           f"root@{host}", command], capture_output=True, text=True,
                              encoding="utf-8", errors="replace", stdin=subprocess.DEVNULL, timeout=timeout)
        except Exception as exc:
            if job_id is not None:
                self._event(job_id, machine["id"], action, "ssh_error", stage=stage,
                            error_type=type(exc).__name__,
                            elapsed_ms=round((time.monotonic() - started) * 1000))
            raise
        if job_id is not None:
            self._event(job_id, machine["id"], action, "ssh_exit", stage=stage,
                        exit_code=result.returncode,
                        elapsed_ms=round((time.monotonic() - started) * 1000))
        if result.returncode:
            detail = "\n".join(part for part in (result.stderr.strip(), result.stdout.strip()) if part)
            raise RemoteCommandError("ssh_connection" if result.returncode == 255 else stage,
                                     result.returncode, detail)
        return result.stdout.strip()
