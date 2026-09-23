from __future__ import annotations

import json
import uuid
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class ComfyUIError(RuntimeError):
    pass


class ComfyUIAdapter:
    def __init__(self, config: dict[str, Any]):
        self.base_url = str(config["base_url"]).rstrip("/")
        self.timeout = int(config.get("timeout", 60))
        self.client_id = str(uuid.uuid4())

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
