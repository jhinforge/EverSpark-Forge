"""Diffusers worker adapter. Heavy ML imports live only in the worker's venv."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen

from ..port import ImageRequest

DEFAULT_NEGATIVE_PROMPT = (
    "lowres, bad anatomy, bad hands, extra fingers, missing fingers, "
    "extra limbs, bad proportions, blurry, worst quality, low quality, "
    "jpeg artifacts, text, watermark, signature"
)


class DiffusersAdapter:
    name = "diffusers"

    def __init__(self, config: dict[str, Any]):
        self.base_url = str(config.get("base_url", "http://127.0.0.1:8190")).rstrip("/")
        self.timeout = int(config.get("timeout", 60))
        self.default_checkpoint = str(config.get("default_checkpoint", "Illustrious-XL-v1.0.safetensors"))
        self.job_directory = Path(config.get("job_directory", Path(__file__).resolve().parents[3]
                                             / "Data/Runtime/Diffusers/jobs"))

    def _get(self, path: str) -> dict[str, Any]:
        with urlopen(Request(self.base_url + path), timeout=self.timeout) as response:
            return json.load(response)

    def resources(self) -> dict[str, Any]:
        inventory = self._get("/models")
        return {"workflows": [{"id": "diffusers-sdxl", "name": "Diffusers SDXL",
                               "model_family": "sdxl", "default": True,
                               "supports": {"checkpoint_override": True, "lora_injection": True}}],
                "checkpoints": inventory["checkpoints"], "loras": inventory["loras"],
                "vaes": inventory["vaes"],
                "defaults": {"workflow": "diffusers-sdxl", "checkpoint": self.default_checkpoint},
                "capabilities": ["text_to_image", "loras", "vae"],
                "lora_strength_mode": "shared"}

    def default_negative_prompt(self, workflow_id: str = "") -> str:
        if workflow_id and workflow_id != "diffusers-sdxl":
            raise ValueError("Diffusers supports the diffusers-sdxl workflow only")
        return DEFAULT_NEGATIVE_PROMPT

    def submit(self, request: ImageRequest, notify: Any = None) -> tuple[str, dict[str, Any]]:
        if request.workflow and request.workflow != "diffusers-sdxl":
            raise ValueError("Diffusers supports the diffusers-sdxl workflow only")
        inventory = self.resources()
        checkpoint = request.checkpoint or self.default_checkpoint
        if checkpoint not in inventory["checkpoints"]:
            raise ValueError(f"Selected checkpoint is unavailable: {checkpoint}")
        if request.vae and request.vae not in inventory["vaes"]:
            raise ValueError(f"Selected VAE is unavailable: {request.vae}")
        for item in request.loras:
            if item.get("name") not in inventory["loras"]:
                raise ValueError(f"Selected LoRA is unavailable: {item.get('name')}")
            if float(item.get("strength_model", 1)) != float(item.get("strength_clip", 1)):
                raise ValueError("Diffusers SDXL currently requires equal model and CLIP LoRA strengths")
        body = {"positive_prompt": request.positive_prompt,
                "negative_prompt": request.negative_prompt, "seed": request.seed,
                "checkpoint": checkpoint, "vae": request.vae, "loras": request.loras}
        payload = json.dumps(body).encode("utf-8")
        with urlopen(Request(self.base_url + "/jobs", data=payload, method="POST",
                             headers={"Content-Type": "application/json"}),
                     timeout=self.timeout) as response:
            job_id = json.load(response)["id"]
        return job_id, {"workflow": "diffusers-sdxl", "checkpoint": checkpoint,
                        "vae": request.vae, "loras": request.loras}

    def poll(self, job_id: str) -> dict[str, Any]:
        if len(job_id) != 32 or any(c not in "0123456789abcdef" for c in job_id):
            raise ValueError("Invalid image job ID")
        # The managed worker writes each status atomically. Reading its local
        # catalog keeps progress responsive while GPU inference is busy.
        path = self.job_directory / f"{job_id}.json"
        try:
            result = json.loads(path.read_text(encoding="utf-8"))
            if result.get("status") in {"queued", "running", "completed", "failed"}:
                if result["status"] == "queued":
                    result["status"] = "running"
                return result
        except (OSError, ValueError):
            pass
        return self._get("/jobs/" + job_id)

    def health(self) -> bool:
        try:
            with urlopen(Request(self.base_url + "/health"), timeout=min(self.timeout, 2)) as response:
                return json.load(response).get("ok") is True
        except (OSError, TimeoutError):
            return False
