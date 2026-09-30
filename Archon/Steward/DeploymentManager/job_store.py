"""Atomic durable job metadata; a lost worker never silently becomes successful."""
import json
import re


class JobStore:
    def __init__(self, state_path):
        self.path = state_path.with_name(state_path.stem + ".jobs.json") if state_path else None

    def load(self):
        try:
            jobs = json.loads(self.path.read_text(encoding="utf-8")) if self.path else {}
        except FileNotFoundError:
            jobs = {}
        if not isinstance(jobs, dict) or any(not isinstance(job, dict) for job in jobs.values()):
            raise ValueError("Invalid deployment job journal")
        for job_id, job in jobs.items():
            if (not isinstance(job_id, str) or not re.fullmatch(r"[0-9a-f]{32}", job_id)
                    or job.get("id") != job_id or job.get("action") not in {"deploy-image", "verify-image"}
                    or job.get("status") not in {"running", "completed", "failed"}
                    or isinstance(job.get("instance_id"), bool) or not isinstance(job.get("instance_id"), int)
                    or job["instance_id"] < 1):
                raise ValueError("Invalid deployment job metadata")
            if job.get("status") == "running":
                job.update(status="failed", stage="archon_restart",
                           detail="Archon restarted during execution; outcome unknown. Verify Forge health before retrying.")
        return jobs

    def save(self, jobs):
        if not self.path:
            return
        fields = {"id", "instance_id", "action", "status", "stage", "task_id", "exit_code"}
        value = {key: {k: v for k, v in job.items() if k in fields} for key, job in jobs.items()}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_name(self.path.name + ".tmp")
        temporary.write_text(json.dumps(value), encoding="utf-8")
        temporary.replace(self.path)
