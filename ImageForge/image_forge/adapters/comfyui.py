from __future__ import annotations

import json
import uuid
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from ..port import ImageRequest
from ..workflow.manager import WorkflowManager


class ComfyUIError(RuntimeError):
    pass


class ComfyUIAdapter:
    name = "comfyui"

    def __init__(self, config: dict[str, Any], workflow: WorkflowManager | None = None):
        self.base_url = str(config["base_url"]).rstrip("/")
        self.timeout = int(config.get("timeout", 60))
        self.client_id = str(uuid.uuid4())
        self.workflow = workflow

    def resources(self) -> dict[str, Any]:
        if self.workflow is None:
            raise ComfyUIError("ComfyUI workflow manager is unavailable")
        return {
            "workflows": self.workflow.list_workflows(),
            "checkpoints": self.list_checkpoints(),
            "loras": self.list_loras(),
            "vaes": self.list_vaes(),
            "defaults": {
                "workflow": self.workflow.default_workflow_id,
                "checkpoint": self.workflow.managed_default_checkpoint,
            },
            "capabilities": ["text_to_image", "loras", "vae", "comfyui_workflow"],
            "lora_strength_mode": "independent",
        }

    def submit(self, request: ImageRequest, notify: Any = None) -> tuple[str, dict[str, Any]]:
        if self.workflow is None:
            raise ComfyUIError("ComfyUI workflow manager is unavailable")
        workflow_id = self.workflow.selected_workflow_id(request.workflow)
        graph = self.workflow.build(request.positive_prompt, request.negative_prompt,
                                    seed=request.seed, workflow_id=workflow_id)
        checkpoint = self.workflow.bind_checkpoint(graph, self.list_checkpoints(),
                                                   notify, requested=request.checkpoint)
        vae = (self.workflow.bind_vae(graph, request.vae, self.list_vaes())
               if request.vae else "")
        loras = (self.workflow.inject_loras(graph, request.loras, self.list_loras(),
                                           workflow_id=workflow_id) if request.loras else [])
        job_id = self.queue_prompt(graph)
        return job_id, {"workflow": workflow_id, "checkpoint": checkpoint,
                        "vae": vae, "loras": loras}

    def poll(self, job_id: str) -> dict[str, Any]:
        from urllib.parse import quote

        with urlopen(Request(f"{self.base_url}/history/{quote(job_id, safe='')}"),
                     timeout=self.timeout) as response:
            history = json.load(response)
        item = history.get(job_id)
        if not isinstance(item, dict):
            return {"status": "running", "images": []}
        images: list[dict[str, str]] = []
        for output in item.get("outputs", {}).values():
            if not isinstance(output, dict):
                continue
            for image in output.get("images", []):
                if isinstance(image, dict) and image.get("filename"):
                    images.append({"filename": str(image["filename"]),
                                   "subfolder": str(image.get("subfolder", "")),
                                   "type": str(image.get("type", "output"))})
        status = item.get("status", {})
        failed = isinstance(status, dict) and status.get("status_str") in {"error", "failed"}
        return {"status": "failed" if failed else "completed" if images or (
            isinstance(status, dict) and status.get("completed") is True) else "running",
            "images": images}

    def health(self) -> bool:
        try:
            with urlopen(Request(f"{self.base_url}/system_stats"), timeout=min(self.timeout, 2)) as response:
                return response.status == 200
        except (OSError, TimeoutError):
            return False

    def queue_prompt(self, workflow: dict[str, Any]) -> str:
        request = Request(f"{self.base_url}/prompt", data=json.dumps({"prompt": workflow, "client_id": self.client_id}, ensure_ascii=True).encode("utf-8"), headers={"Content-Type": "application/json; charset=utf-8"}, method="POST")
        try:
            with urlopen(request, timeout=self.timeout) as response:
                result = json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise ComfyUIError(f"ComfyUI HTTP {exc.code}: {detail}") from exc
        except URLError as exc:
            raise ComfyUIError(f"Cannot connect to ComfyUI at {self.base_url}: {exc.reason}") from exc
        except json.JSONDecodeError as exc:
            raise ComfyUIError("ComfyUI returned invalid HTTP JSON") from exc
        prompt_id = result.get("prompt_id")
        if not isinstance(prompt_id, str) or not prompt_id:
            raise ComfyUIError("ComfyUI response did not include prompt_id")
        return prompt_id

    def list_checkpoints(self) -> list[str]:
        return self._list_node_options("CheckpointLoaderSimple", "ckpt_name")

    def list_loras(self) -> list[str]:
        return self._list_node_options("LoraLoader", "lora_name")

    def list_vaes(self) -> list[str]:
        return self._list_node_options("VAELoader", "vae_name")

    def _list_node_options(self, class_type: str, input_name: str) -> list[str]:
        request = Request(f"{self.base_url}/object_info/{class_type}")
        try:
            with urlopen(request, timeout=self.timeout) as response:
                result = json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise ComfyUIError(f"ComfyUI HTTP {exc.code}: {detail}") from exc
        except URLError as exc:
            raise ComfyUIError(
                f"Cannot connect to ComfyUI at {self.base_url}: {exc.reason}"
            ) from exc
        except json.JSONDecodeError as exc:
            raise ComfyUIError(
                f"ComfyUI returned invalid {class_type} metadata"
            ) from exc

        try:
            values = result[class_type]["input"]["required"][input_name][0]
        except (KeyError, IndexError, TypeError) as exc:
            raise ComfyUIError(
                f"ComfyUI {class_type} metadata has an unknown shape"
            ) from exc
        if not isinstance(values, list) or not all(isinstance(item, str) for item in values):
            raise ComfyUIError(
                f"ComfyUI {class_type} metadata did not contain a name list"
            )
        return values
