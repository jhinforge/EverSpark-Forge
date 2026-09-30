"""Enrich deployment jobs using authenticated execution progress."""
def job_progress(bridge, job):
    if job.get("status") == "running" and job.get("task_id") and hasattr(bridge, "task_status"):
        job["progress"] = bridge.task_status(job["instance_id"], job["task_id"])
    return job


def active_job(manager, instance_id, state):
    running = next((job for job in reversed(list(manager.jobs.values()))
                    if job["instance_id"] == instance_id and job["status"] == "running"), None)
    if running:
        state["job"] = job_progress(manager.bridge, running.copy())
    return state
