from __future__ import annotations

import copy
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..models.resolver import CheckpointResolutionError, resolve_checkpoint


class WorkflowError(RuntimeError):
    pass


@dataclass(frozen=True)
class WorkflowDefinition:
    workflow_id: str
    name: str
    api_path: Path
    positive_node: str
    negative_node: str
    seed_node: str
    model_family: str = "unknown"
    supports_lora: bool = False

    def public(self, default: bool = False) -> dict[str, Any]:
        return {
            "id": self.workflow_id,
            "name": self.name,
            "model_family": self.model_family,
            "default": default,
            "supports": {
                "checkpoint_override": True,
                "lora_injection": self.supports_lora,
            },
        }


class WorkflowManager:
    def __init__(self, config: dict[str, Any]):
        self.managed_default_checkpoint = str(
            config.get("managed_default_checkpoint", "")
        ).strip()
        self._definitions = self._load_definitions(config)
        configured_default = str(config.get("default_workflow", "")).strip()
        if configured_default and configured_default not in self._definitions:
            raise WorkflowError(
                f"Default workflow is not registered: {configured_default}"
            )
        self.default_workflow_id = configured_default or next(iter(self._definitions))

    def list_workflows(self) -> list[dict[str, Any]]:
        return [
            definition.public(workflow_id == self.default_workflow_id)
            for workflow_id, definition in self._definitions.items()
        ]

    def build(
        self,
        positive_prompt: str,
        negative_prompt: str,
        seed: int | None = None,
        workflow_id: str = "",
    ) -> dict[str, Any]:
        definition = self._definition(workflow_id)
        workflow = copy.deepcopy(self._load_template(definition.api_path))
        self._replace_text(
            workflow, definition.positive_node, positive_prompt, "positive"
        )
        self._replace_text(
            workflow, definition.negative_node, negative_prompt, "negative"
        )
        if seed is not None:
            self._replace_seed(workflow, definition.seed_node, seed)
        return workflow

    def selected_workflow_id(self, workflow_id: str = "") -> str:
        return self._definition(workflow_id).workflow_id

    def default_negative_prompt(self, workflow_id: str = "") -> str:
        definition = self._definition(workflow_id)
        workflow = self._load_template(definition.api_path)
        node = workflow.get(definition.negative_node)
        if not isinstance(node, dict) or not isinstance(node.get("inputs"), dict):
            raise WorkflowError("Registered workflow has no negative prompt node")
        text = node["inputs"].get("text")
        if not isinstance(text, str):
            raise WorkflowError("Registered workflow negative prompt must be text")
        return text.strip()

    def bind_checkpoint(
        self,
        workflow: dict[str, Any],
        available: list[str],
        notify: Any = None,
        requested: str = "",
    ) -> str:
        checkpoint_nodes = [
            node
            for node in workflow.values()
            if isinstance(node, dict)
            and node.get("class_type") == "CheckpointLoaderSimple"
        ]
        if not checkpoint_nodes:
            if requested:
                raise WorkflowError(
                    "The selected workflow has no CheckpointLoaderSimple node"
                )
            return ""

        explicit = requested.strip().replace("\\", "/")
        lookup = {item.casefold(): item for item in available if isinstance(item, str)}
        if explicit and explicit.casefold() not in lookup:
            raise WorkflowError(f"Selected checkpoint is unavailable: {explicit}")

        selected = ""
        for node in checkpoint_nodes:
            inputs = node.get("inputs")
            if not isinstance(inputs, dict):
                raise WorkflowError("CheckpointLoaderSimple node has no inputs object")
            if explicit:
                selected = lookup[explicit.casefold()]
                inputs["ckpt_name"] = selected
                continue
            current = str(inputs.get("ckpt_name", ""))
            try:
                resolution = resolve_checkpoint(
                    current, available, self.managed_default_checkpoint
                )
            except CheckpointResolutionError as exc:
                raise WorkflowError(str(exc)) from exc
            selected = resolution.name
            inputs["ckpt_name"] = selected
            if resolution.warning and notify is not None:
                notify(resolution.warning)
        return selected

    def inject_loras(
        self,
        workflow: dict[str, Any],
        selections: list[dict[str, Any]],
        available: list[str],
        workflow_id: str = "",
    ) -> list[dict[str, Any]]:
        if not selections:
            return []
        definition = self._definition(workflow_id)
        if not definition.supports_lora:
            raise WorkflowError(
                f"Workflow '{definition.name}' does not support standard LoRA injection"
            )

        checkpoint_ids = [
            str(node_id)
            for node_id, node in workflow.items()
            if isinstance(node, dict)
            and node.get("class_type") == "CheckpointLoaderSimple"
        ]
        if len(checkpoint_ids) != 1:
            raise WorkflowError(
                "Standard LoRA injection requires exactly one CheckpointLoaderSimple node"
            )

        lookup = {item.casefold(): item for item in available if isinstance(item, str)}
        normalized: list[dict[str, Any]] = []
        for selection in selections:
            if not isinstance(selection, dict):
                raise WorkflowError("Each LoRA selection must be an object")
            requested = str(selection.get("name", "")).strip().replace("\\", "/")
            if not requested or requested.casefold() not in lookup:
                raise WorkflowError(f"Selected LoRA is unavailable: {requested or '<empty>'}")
            try:
                strength_model = float(selection.get("strength_model", 1.0))
                strength_clip = float(selection.get("strength_clip", 1.0))
            except (TypeError, ValueError) as exc:
                raise WorkflowError("LoRA strengths must be numbers") from exc
            if not -10.0 <= strength_model <= 10.0 or not -10.0 <= strength_clip <= 10.0:
                raise WorkflowError("LoRA strengths must be between -10 and 10")
            normalized.append(
                {
                    "name": lookup[requested.casefold()],
                    "strength_model": strength_model,
                    "strength_clip": strength_clip,
                }
            )

        checkpoint_id = checkpoint_ids[0]
        original_nodes = list(workflow.items())
        numeric_ids = [int(key) for key in workflow if str(key).isdigit()]
        next_id = max(numeric_ids, default=0) + 1
        previous_id = checkpoint_id
        for selection in normalized:
            node_id = str(next_id)
            next_id += 1
            workflow[node_id] = {
                "inputs": {
                    "model": [previous_id, 0],
                    "clip": [previous_id, 1],
                    "lora_name": selection["name"],
                    "strength_model": selection["strength_model"],
                    "strength_clip": selection["strength_clip"],
                },
                "class_type": "LoraLoader",
                "_meta": {"title": f"EverSpark LoRA · {selection['name']}"},
            }
            previous_id = node_id

        for node_id, node in original_nodes:
            if str(node_id) == checkpoint_id or not isinstance(node, dict):
                continue
            inputs = node.get("inputs")
            if isinstance(inputs, dict):
                self._rewrite_checkpoint_links(inputs, checkpoint_id, previous_id)
        return normalized

    def bind_vae(self, workflow: dict[str, Any], requested: str, available: list[str]) -> str:
        name = requested.strip().replace("\\", "/")
        if not name:
            return ""
        lookup = {item.casefold(): item for item in available if isinstance(item, str)}
        if name.casefold() not in lookup:
            raise WorkflowError(f"Selected VAE is unavailable: {name}")
        sources = {
            str(node_id) for node_id, node in workflow.items()
            if isinstance(node, dict) and node.get("class_type") == "CheckpointLoaderSimple"
        }
        consumers = []
        for node in workflow.values():
            if not isinstance(node, dict) or not isinstance(node.get("inputs"), dict):
                continue
            inputs = node["inputs"]
            link = inputs.get("vae")
            if (isinstance(link, list) and len(link) == 2
                    and str(link[0]) in sources and link[1] == 2):
                consumers.append(inputs)
        if not consumers:
            raise WorkflowError("Selected workflow has no checkpoint VAE connection to replace")
        numeric_ids = [int(key) for key in workflow if str(key).isdigit()]
        node_id = str(max(numeric_ids, default=0) + 1)
        selected = lookup[name.casefold()]
        workflow[node_id] = {
            "inputs": {"vae_name": selected},
            "class_type": "VAELoader",
            "_meta": {"title": f"EverSpark VAE · {selected}"},
        }
        for inputs in consumers:
            inputs["vae"] = [node_id, 0]
        return selected

    def _load_definitions(
        self, config: dict[str, Any]
    ) -> dict[str, WorkflowDefinition]:
        definitions: dict[str, WorkflowDefinition] = {}
        directory_value = str(config.get("directory", "")).strip()
        if directory_value:
            directory = Path(directory_value)
            for manifest_path in sorted(directory.glob("*.workflow.json")):
                manifest = self._read_json(manifest_path)
                workflow_id = str(manifest.get("id", "")).strip()
                api_file = str(manifest.get("api", "")).strip()
                nodes = manifest.get("nodes", {})
                supports = manifest.get("supports", {})
                if not workflow_id or not api_file or not isinstance(nodes, dict):
                    raise WorkflowError(f"Invalid workflow manifest: {manifest_path}")
                api_path = (manifest_path.parent / api_file).resolve()
                try:
                    api_path.relative_to(directory.resolve())
                except ValueError as exc:
                    raise WorkflowError(
                        f"Workflow API file escapes its registry: {manifest_path}"
                    ) from exc
                if workflow_id in definitions:
                    raise WorkflowError(f"Duplicate workflow id: {workflow_id}")
                definitions[workflow_id] = WorkflowDefinition(
                    workflow_id=workflow_id,
                    name=str(manifest.get("name", workflow_id)).strip() or workflow_id,
                    api_path=api_path,
                    positive_node=str(nodes.get("positive_prompt", "")).strip(),
                    negative_node=str(nodes.get("negative_prompt", "")).strip(),
                    seed_node=str(nodes.get("seed", "")).strip(),
                    model_family=str(manifest.get("model_family", "unknown")).strip(),
                    supports_lora=bool(
                        isinstance(supports, dict)
                        and supports.get("lora_injection", False)
                    ),
                )

        if definitions:
            return definitions

        template_path = Path(str(config["template"]))
        workflow_id = str(config.get("default_workflow", "default")).strip() or "default"
        return {
            workflow_id: WorkflowDefinition(
                workflow_id=workflow_id,
                name=str(config.get("name", "Base workflow")),
                api_path=template_path,
                positive_node=str(config.get("positive_prompt_node", "")).strip(),
                negative_node=str(config.get("negative_prompt_node", "")).strip(),
                seed_node=str(config.get("seed_node", "")).strip(),
                model_family=str(config.get("model_family", "unknown")),
                supports_lora=bool(config.get("supports_lora", False)),
            )
        }

    def _definition(self, workflow_id: str = "") -> WorkflowDefinition:
        selected = workflow_id.strip() or self.default_workflow_id
        try:
            return self._definitions[selected]
        except KeyError as exc:
            raise WorkflowError(f"Unknown workflow: {selected}") from exc

    @staticmethod
    def _read_json(path: Path) -> dict[str, Any]:
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError as exc:
            raise WorkflowError(f"Workflow file not found: {path}") from exc
        except json.JSONDecodeError as exc:
            raise WorkflowError(f"Invalid workflow JSON: {path}: {exc}") from exc
        if not isinstance(value, dict):
            raise WorkflowError(f"Workflow JSON must be an object: {path}")
        return value

    def _load_template(self, path: Path) -> dict[str, Any]:
        workflow = self._read_json(path)
        if not workflow:
            raise WorkflowError(
                "Image Forge workflow is an empty placeholder. Export a ComfyUI "
                "workflow in API Format before running a generation task."
            )
        return workflow

    @staticmethod
    def _replace_text(
        workflow: dict[str, Any], node_id: str, prompt: str, label: str
    ) -> None:
        if not node_id:
            raise WorkflowError(f"The {label}_prompt_node is not configured")
        node = workflow.get(node_id)
        if not isinstance(node, dict):
            raise WorkflowError(f"Workflow node {node_id} ({label}) was not found")
        inputs = node.get("inputs")
        if not isinstance(inputs, dict) or "text" not in inputs:
            raise WorkflowError(f"Workflow node {node_id} ({label}) has no inputs.text")
        inputs["text"] = prompt

    @staticmethod
    def _replace_seed(workflow: dict[str, Any], node_id: str, seed: int) -> None:
        if not node_id:
            raise WorkflowError("The seed_node is not configured")
        node = workflow.get(node_id)
        if not isinstance(node, dict):
            raise WorkflowError(f"Workflow seed node {node_id} was not found")
        inputs = node.get("inputs")
        if not isinstance(inputs, dict) or "seed" not in inputs:
            raise WorkflowError(f"Workflow seed node {node_id} has no inputs.seed")
        inputs["seed"] = seed

    @classmethod
    def _rewrite_checkpoint_links(
        cls, value: Any, checkpoint_id: str, replacement_id: str
    ) -> None:
        if isinstance(value, dict):
            for nested in value.values():
                cls._rewrite_checkpoint_links(nested, checkpoint_id, replacement_id)
            return
        if not isinstance(value, list):
            return
        if (
            len(value) == 2
            and str(value[0]) == checkpoint_id
            and value[1] in {0, 1}
        ):
            value[0] = replacement_id
            return
        for nested in value:
            cls._rewrite_checkpoint_links(nested, checkpoint_id, replacement_id)
