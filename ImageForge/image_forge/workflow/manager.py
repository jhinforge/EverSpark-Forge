from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

from ..models.resolver import CheckpointResolutionError, resolve_checkpoint


class WorkflowError(RuntimeError):
    pass


class WorkflowManager:
    def __init__(self, config: dict[str, Any]):
        self.template_path = Path(config["template"])
        self.positive_node = str(config.get("positive_prompt_node", "")).strip()
        self.negative_node = str(config.get("negative_prompt_node", "")).strip()
        self.seed_node = str(config.get("seed_node", "")).strip()
        self.managed_default_checkpoint = str(
            config.get("managed_default_checkpoint", "")
        ).strip()

    def build(
        self, positive_prompt: str, negative_prompt: str, seed: int | None = None
    ) -> dict[str, Any]:
        workflow = copy.deepcopy(self._load_template())
        self._replace_text(workflow, self.positive_node, positive_prompt, "positive")
        self._replace_text(workflow, self.negative_node, negative_prompt, "negative")
        if seed is not None:
            self._replace_seed(workflow, seed)
        return workflow

    def bind_checkpoint(
        self,
        workflow: dict[str, Any],
        available: list[str],
        notify: Any = None,
    ) -> None:
        checkpoint_nodes = [
            node
            for node in workflow.values()
            if isinstance(node, dict)
            and node.get("class_type") == "CheckpointLoaderSimple"
        ]
        if not checkpoint_nodes:
            return
        for node in checkpoint_nodes:
            inputs = node.get("inputs")
            if not isinstance(inputs, dict):
                raise WorkflowError("CheckpointLoaderSimple node has no inputs object")
            requested = str(inputs.get("ckpt_name", ""))
            try:
                resolution = resolve_checkpoint(
                    requested, available, self.managed_default_checkpoint
                )
            except CheckpointResolutionError as exc:
                raise WorkflowError(str(exc)) from exc
            inputs["ckpt_name"] = resolution.name
            if resolution.warning and notify is not None:
                notify(resolution.warning)

    def _load_template(self) -> dict[str, Any]:
        try:
            raw = self.template_path.read_text(encoding="utf-8")
        except FileNotFoundError as exc:
            raise WorkflowError(f"Workflow template not found: {self.template_path}") from exc
        if not raw.strip():
            raise WorkflowError("ComfyUI API Format workflow is still an empty placeholder. Export it from ComfyUI before running a generation task.")
        try:
            workflow = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise WorkflowError(f"Invalid workflow JSON: {exc}") from exc
        if not isinstance(workflow, dict):
            raise WorkflowError("Image Forge workflow must be a JSON object")
        if not workflow:
            raise WorkflowError(
                "Image Forge workflow is an empty placeholder. "
                "Export a ComfyUI workflow in API Format and configure its path "
                "before running a generation task."
            )
        return workflow

    @staticmethod
    def _replace_text(workflow: dict[str, Any], node_id: str, prompt: str, label: str) -> None:
        if not node_id:
            raise WorkflowError(f"The {label}_prompt_node is not configured")
        node = workflow.get(node_id)
        if not isinstance(node, dict):
            raise WorkflowError(f"Workflow node {node_id} ({label}) was not found")
        inputs = node.get("inputs")
        if not isinstance(inputs, dict) or "text" not in inputs:
            raise WorkflowError(f"Workflow node {node_id} ({label}) has no inputs.text")
        inputs["text"] = prompt

    def _replace_seed(self, workflow: dict[str, Any], seed: int) -> None:
        if not self.seed_node:
            raise WorkflowError("The seed_node is not configured")
        node = workflow.get(self.seed_node)
        if not isinstance(node, dict):
            raise WorkflowError(f"Workflow seed node {self.seed_node} was not found")
        inputs = node.get("inputs")
        if not isinstance(inputs, dict) or "seed" not in inputs:
            raise WorkflowError(f"Workflow seed node {self.seed_node} has no inputs.seed")
        inputs["seed"] = seed
