"""Coordinate Forge steps without resolving their internal resources."""
from Aegis.Shared.errors import TaskError
import uuid

class TaskRunner:
    def __init__(self, concept, image, audio=None, *, execution_targets=None):
        self.concept = concept
        self.image = image
        self.execution_targets = dict(execution_targets or {})
        self.forges = {"image": image}
        if audio is not None:
            self.forges["audio"] = audio

    def run(self, user_text, session_id, selection=None, notify=None):
        mode = (selection or {}).get("creation_mode", "image")
        if mode not in {"image", "audio", "image_audio", "plan"}:
            raise TaskError("Invalid generation mode")
        if mode in {"audio", "image_audio", "plan"}:
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
            target = self.execution_targets.get(step["forge"])
            if target:
                key = "target_node_id" if isinstance(target, str) and len(target) == 32 else "target_instance_id"
                tasks[-1][key] = target
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
        mode = selection.get("creation_mode", "plan")
        required = {"audio"} if mode == "audio" else {"image", "audio"} if mode == "image_audio" else set()
        if required - self.forges.keys():
            raise TaskError("Select an Audio Forge node first")
        available = [forge for forge in self.forges if not required or forge in required]
        with self.concept.prepare_creation(text, session, selection,
                                          available, notify) as creation:
            tasks = self._tasks(creation.plan)
            targets = {task["forge"] for task in tasks}
            if required and (targets != required):
                raise TaskError("Concept Forge task list does not match the selected generation mode")
            notify({"tasks": self._public_tasks(tasks)})
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
