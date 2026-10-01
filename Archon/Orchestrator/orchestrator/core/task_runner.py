"""Coordinate Forge steps without resolving their internal resources."""
from Aegis.Shared.errors import TaskError
import uuid

class TaskRunner:
    def __init__(self, concept, image, audio=None):
        self.concept = concept
        self.image = image
        self.forges = {"image": image}
        if audio is not None:
            self.forges["audio"] = audio

    def run(self, user_text, session_id, selection=None, notify=None):
        if (selection or {}).get("creation_mode") == "plan":
            return self._create(user_text, session_id, selection, notify or (lambda _message: None))
        # The context belongs to Concept Forge; only its opaque instruction and
        # result callback cross this boundary. Legacy options are forwarded intact.
        with self.concept.prepare_generation(user_text, session_id, selection or {},
                                             notify or (lambda _message: None)) as prepared:
            result = self.image.generate(prepared.instruction, selection,
                                         notify or (lambda _message: None))
            return prepared.complete(result)

    def _tasks(self, plan):
        steps = plan.get("steps") if isinstance(plan, dict) else None
        if not isinstance(steps, list) or not 1 <= len(steps) <= 64:
            raise TaskError("Invalid creative task list")
        keys = [s.get("key") for s in steps if isinstance(s, dict)]
        if (len(keys) != len(steps) or any(not isinstance(k, str) or not k for k in keys)
                or len(set(keys)) != len(keys)):
            raise TaskError("Creative step keys must be unique")
        identities = {key: uuid.uuid4().hex for key in keys}
        tasks = []
        for step in steps:
            dependencies = step.get("depends_on")
            if (step.get("forge") not in self.forges or not isinstance(dependencies, list)
                    or any(not isinstance(k, str) or k not in identities or k == step["key"]
                           for k in dependencies)):
                raise TaskError("Invalid Forge target or creative dependency")
            tasks.append({"id": identities[step["key"]], "forge": step["forge"],
                "depends_on": [identities[k] for k in dependencies],
                "status": "queued", "specification": step})
        ordered, remaining = [], list(tasks)
        while remaining:
            done = {t["id"] for t in ordered}
            ready = next((t for t in remaining if set(t["depends_on"]) <= done), None)
            if ready is None:
                raise TaskError("Creative dependencies contain a cycle")
            ordered.append(ready)
            remaining.remove(ready)
        return ordered

    def _create(self, text, session, selection, notify):
        notify("Concept Forge: understanding and creative decomposition")
        with self.concept.prepare_creation(text, session, selection,
                                          list(self.forges), notify) as creation:
            tasks = self._tasks(creation.plan)
            results = {}
            for task in tasks:
                try:
                    task["status"] = "preparing"
                    notify({"tasks": self._public_tasks(tasks)})
                    prepared = creation.prepare(task["specification"],
                        [results[identity] for identity in task["depends_on"]])
                    task["status"] = "running"
                    notify({"tasks": self._public_tasks(tasks)})
                    result = self.forges[task["forge"]].execute(prepared.instruction, selection, notify)
                    results[task["id"]] = prepared.complete(result)
                    task.update(status="completed", result=results[task["id"]])
                    notify({"tasks": self._public_tasks(tasks)})
                except Exception as exc:
                    task.update(status="failed", error=str(exc))
                    for pending in tasks:
                        if pending["status"] == "queued":
                            pending["status"] = "skipped"
                    notify({"tasks": self._public_tasks(tasks)})
                    raise
            return {"status": "completed", "tasks": self._public_tasks(tasks),
                "items": [item for t in tasks if t["forge"] == "image"
                          for item in t["result"].get("items", [])],
                "audio": [item for t in tasks if t["forge"] == "audio"
                          for item in t["result"].get("audio", [])]}

    @staticmethod
    def _public_tasks(tasks):
        return [{k: v for k, v in task.items() if k != "specification"} for task in tasks]
