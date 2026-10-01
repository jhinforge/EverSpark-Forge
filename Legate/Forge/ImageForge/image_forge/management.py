"""Image Forge owns its engines, resources, generated history and plugins."""
from __future__ import annotations
import secrets
import time
from pathlib import Path
from typing import Any
from Aegis.Shared.errors import TaskError
from .port import ImageRequest

class ImageManagement:
    def __init__(self, gateway, plugins):
        self.gateway = gateway
        self.plugins = plugins

    def resources(self, engine=""):
        return self.gateway.resources(engine)

    def image_health(self) -> dict[str, Any]:
        engine = self.gateway.select()
        return {"ok": engine.health(), "engine": engine.name}

    def image_plugins(self) -> dict[str, Any]:
        return self.plugins.plugins()

    def image_plugin_job(self, job_id: str) -> dict[str, Any]:
        return self.plugins.job(job_id)

    def start_image_plugin(self, name: str, action: str) -> dict[str, Any]:
        return self.plugins.start(name, action)

    def set_default_image_plugin(self, name: str) -> dict[str, Any]:
        return self.plugins.set_default(name)

    def image_results(self, job_ids: list[str]) -> list[dict[str, Any]]:
        return self.gateway.results(job_ids)

    def image_history(self, limit: int) -> list[dict[str, str]]:
        return self.gateway.history(limit)

    def image_path(self, filename: str, subfolder: str, kind: str) -> Path:
        return self.gateway.image_path(filename, subfolder, kind)

    def generate(self, instruction, selection=None, notify=None):
        selected = selection or {}
        engine_name = str(selected.get("engine", "")).strip().lower()
        selected_engine = self.gateway.select(engine_name)
        if not selected_engine.health():
            raise TaskError(f"Enable {selected_engine.name} before generating")
        workflow_id = str(selected.get("workflow", ""))
        checkpoint = str(selected.get("checkpoint", "")).strip()
        vae = str(selected.get("vae", "")).strip()
        loras = selected.get("loras", [])
        if not isinstance(loras, list):
            raise TaskError("selection.loras must be a list")
        positive_prompt = instruction["positive_prompt"]
        saved_negative_prompt = instruction.get("saved_negative_prompt")
        change_negative_prompt = instruction.get("change_negative_prompt", False)
        if saved_negative_prompt is not None:
            negative_prompt = saved_negative_prompt
        else:
            default_negative = (selected_engine.default_negative_prompt(workflow_id)
                                if not change_negative_prompt and
                                hasattr(selected_engine, "default_negative_prompt") else "")
            negative_prompt = self._merge_unique_terms(
                default_negative, instruction["negative_prompt"],
                instruction.get("extra_negative_prompt", ""),
            )

        items = []
        selected_checkpoint = ""
        selected_vae = ""
        selected_loras: list[dict[str, Any]] = []
        for index in range(1, instruction["count"] + 1):
            seed = secrets.randbelow(2**63)
            prompt_id, resolved = self.gateway.submit(ImageRequest(
                positive_prompt=positive_prompt, negative_prompt=negative_prompt,
                seed=seed, workflow=workflow_id, checkpoint=checkpoint,
                vae=vae, loras=loras), notify or (lambda _message: None),
                engine=selected_engine.name)
            workflow_id = resolved["workflow"]
            selected_checkpoint = resolved["checkpoint"]
            selected_vae = resolved["vae"]
            selected_loras = resolved["loras"]
            items.append({"index": index, "prompt_id": prompt_id, "seed": seed})

        return {
            "status": "queued", "model": instruction["model"],
            "positive_prompt": positive_prompt, "negative_prompt": negative_prompt,
            "count": instruction["count"],
            "selection": {"workflow": workflow_id, "engine": selected_engine.name,
                "checkpoint": selected_checkpoint, "vae": selected_vae,
                "loras": selected_loras},
            "items": items,
        }

    def execute(self, instruction, selection=None, notify=None):
        result = self.generate(instruction, selection, notify)
        deadline = time.monotonic() + 600
        identities = [item["prompt_id"] for item in result["items"]]
        while time.monotonic() < deadline:
            outputs = self.image_results(identities)
            failed = next((item for item in outputs if item.get("status") == "failed"), None)
            if failed:
                raise TaskError(failed.get("error") or "Image Forge generation failed")
            if len(outputs) == len(identities) and all(item.get("status") == "completed" for item in outputs):
                result.update(status="completed", outputs=outputs)
                return result
            time.sleep(1)
        raise TaskError("Image Forge generation timed out")

    @staticmethod
    def _merge_unique_terms(*prompts: str) -> str:
        terms: list[str] = []
        seen: set[str] = set()
        for prompt in prompts:
            for raw in prompt.split(","):
                term = raw.strip()
                if term and term.casefold() not in seen:
                    terms.append(term)
                    seen.add(term.casefold())
        return ", ".join(terms)
