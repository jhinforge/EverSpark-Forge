"""Image Forge gateway backed by a separate Node Agent and an output cache."""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from Aegis.Storage.output_resources import OutputResources
from image_forge.port import ImageRequest
from Archon.Gate.remote_target import target


class RemoteImageEngine:
    def __init__(self, gateway: "RemoteImageGateway", name: str):
        self.gateway = gateway
        self.name = name

    def health(self) -> bool:
        try:
            return bool(self.gateway.resources(self.name))
        except (OSError, RuntimeError, ValueError):
            return False

    def default_negative_prompt(self, workflow_id: str = "") -> str:
        return self.gateway._call("default_negative", {"engine": self.name,
                                                        "workflow": workflow_id})["negative_prompt"]


class RemoteImageGateway:
    def __init__(self, instance_id: int | str, control_url: str, output_directory: str | Path,
                 default_engine: str):
        self.instance_id = instance_id
        self.url, self.target_identity = target(instance_id, control_url)
        self.output_directory = (Path(output_directory) / "remote" / str(instance_id)).resolve()
        self.outputs = OutputResources(self.output_directory, {".png", ".jpg", ".jpeg", ".webp"})
        self.default_engine = default_engine
        self.engines = {name: RemoteImageEngine(self, name) for name in ("comfyui", "diffusers")}

    def _call(self, action: str, payload: dict) -> dict:
        message = json.dumps(payload, ensure_ascii=False)
        if len(message.encode("utf-8")) > 60000:
            raise ValueError("Image Forge task exceeds the node limit")
        body = json.dumps({**self.target_identity, "forge": "image",
                           "action": action, "message": message}, ensure_ascii=False).encode("utf-8")
        request = Request(self.url, data=body, headers={"Content-Type": "application/json"},
                          method="POST")
        try:
            with urlopen(request, timeout=320) as response:
                envelope = json.load(response)
        except HTTPError as exc:
            raise RuntimeError(f"Remote Image Forge failed (HTTP {exc.code})") from exc
        except (URLError, OSError, ValueError) as exc:
            raise RuntimeError("Remote Image Forge is unavailable") from exc
        try:
            value = json.loads(envelope["output"])
        except (KeyError, TypeError, ValueError) as exc:
            raise RuntimeError("Remote Image Forge returned invalid output") from exc
        if not isinstance(value, dict):
            raise RuntimeError("Remote Image Forge returned an invalid result")
        return value

    def select(self, name: str = "") -> RemoteImageEngine:
        selected = name or self.default_engine
        if selected not in self.engines:
            raise ValueError(f"Unknown image plugin: {selected}")
        return self.engines[selected]

    def resources(self, name: str = "") -> dict:
        return self._call("resources", {"engine": name})

    def submit(self, request: ImageRequest, notify=None, engine: str = "") -> tuple[str, dict]:
        result = self._call("submit", {"request": asdict(request), "engine": engine})
        return result["prompt_id"], result["selection"]

    def result(self, job_id: str) -> dict:
        result = self._call("poll", {"prompt_id": job_id})
        for image in result.get("images", []):
            self.image_path(image["filename"], image.get("subfolder", ""), image.get("type", "output"))
        return result

    def results(self, job_ids: list[str]) -> list[dict]:
        return [self.result(job_id) for job_id in job_ids]

    def history(self, limit: int = 24) -> list[dict]:
        images = self._call("history", {"limit": limit})["images"]
        if not isinstance(images, list):
            raise RuntimeError("Remote Image Forge returned invalid history")
        # Return descriptors immediately; the file endpoint fills the cache on demand.
        # Fetching every full image here blocks the gallery behind the Node task queue.
        for image in images:
            if image.get("type", "output") != "output":
                raise ValueError("Invalid image path")
            self.outputs.path(image["filename"], image.get("subfolder", ""), require_file=False)
        return images

    def image_path(self, filename: str, subfolder: str = "", kind: str = "output") -> Path:
        if kind != "output":
            raise ValueError("Invalid image path")
        return self.outputs.receive(filename, subfolder, lambda offset:
            self._call("fetch", {"filename": filename, "subfolder": subfolder,
                                 "type": kind, "offset": offset}))


class RemoteImagePlugins:
    def __init__(self, gateway: RemoteImageGateway):
        self.gateway = gateway

    def plugins(self) -> dict:
        result = self.gateway._call("plugins", {})
        for plugin in result["plugins"]:
            plugin["remote"] = True
        return result

    def job(self, _job_id: str) -> dict:
        raise ValueError("Image runtime management belongs to the remote node")

    def start(self, _name: str, _action: str) -> dict:
        raise ValueError("Image runtime management belongs to the remote node")

    def set_default(self, _name: str) -> dict:
        raise ValueError("Image runtime management belongs to the remote node")
