from __future__ import annotations

import secrets
from typing import Any, Callable

from concept_forge.providers.ollama import GenerationPlan, OllamaProvider
from concept_forge.subjects import CompiledSubject
from image_forge.adapters.comfyui import ComfyUIAdapter
from image_forge.workflow.manager import WorkflowManager


class TaskError(RuntimeError):
    pass


class TaskRunner:
    def __init__(self, config: dict[str, Any]):
        concept_config = config["concept_forge"]
        image_config = config["image_forge"]
        provider = str(concept_config.get("provider", "")).strip().lower()
        adapter = str(image_config.get("adapter", "")).strip().lower()
        if provider != "ollama":
            raise TaskError(f"Unsupported Concept Forge provider: {provider}")
        if adapter != "comfyui":
            raise TaskError(f"Unsupported Image Forge adapter: {adapter}")

        self.concept = OllamaProvider(concept_config["providers"][provider])
        self.image = ComfyUIAdapter(image_config["adapters"][adapter])
        self.workflow = WorkflowManager(config["workflow"])
        self.supported_models = {
            str(model).strip().lower()
            for model in concept_config.get("supported_models", ["illustrious"])
        }
        self.max_model_retries = int(concept_config.get("max_model_retries", 3))
        self.max_batch_size = int(config["orchestrator"].get("max_batch_size", 20))

    def run(
        self,
        user_text: str,
        history: list[dict[str, str]] | None = None,
        notify: Callable[[str], None] | None = None,
        subject: CompiledSubject | None = None,
    ) -> dict[str, Any]:
        plan = self._get_valid_plan(
            user_text, history or [], notify or (lambda _message: None)
        )
        if plan.status != "over":
            raise TaskError(
                f"Concept Forge returned unexpected status: {plan.status}"
            )
        if plan.count < 1 or plan.count > self.max_batch_size:
            raise TaskError(
                f"Image count must be between 1 and {self.max_batch_size}: {plan.count}"
            )

        positive_prompt = self._merge_prompts(
            subject.positive_prompt if subject else "", plan.positive_prompt
        )
        negative_prompt = self._merge_prompts(
            plan.negative_prompt, subject.negative_prompt if subject else ""
        )

        items = []
        available_checkpoints: list[str] | None = None
        for index in range(1, plan.count + 1):
            seed = secrets.randbelow(2**63)
            workflow = self.workflow.build(
                positive_prompt, negative_prompt, seed=seed
            )
            if available_checkpoints is None:
                available_checkpoints = self.image.list_checkpoints()
            self.workflow.bind_checkpoint(
                workflow, available_checkpoints, notify or (lambda _message: None)
            )
            prompt_id = self.image.queue_prompt(workflow)
            items.append({"index": index, "prompt_id": prompt_id, "seed": seed})

        return {
            "status": "queued",
            "model": plan.model,
            "positive_prompt": positive_prompt,
            "negative_prompt": negative_prompt,
            "count": plan.count,
            "items": items,
            "subject": (
                {"subject_id": subject.subject_id, "revision": subject.revision}
                if subject
                else None
            ),
        }

    @staticmethod
    def _merge_prompts(*prompts: str) -> str:
        return ", ".join(prompt.strip(" ,") for prompt in prompts if prompt.strip(" ,"))

    def _get_valid_plan(
        self,
        user_text: str,
        history: list[dict[str, str]],
        notify: Callable[[str], None],
    ) -> GenerationPlan:
        attempts = self.max_model_retries + 1
        for attempt in range(attempts):
            plan = self.concept.generate_prompt(user_text, history)
            if plan.model in self.supported_models:
                return plan
            if attempt < attempts - 1:
                notify("Error Model,Reloading.....")
        supported = ", ".join(sorted(self.supported_models))
        raise TaskError(
            "Concept Forge did not return a supported model "
            f"after {attempts} attempts: {supported}"
        )
