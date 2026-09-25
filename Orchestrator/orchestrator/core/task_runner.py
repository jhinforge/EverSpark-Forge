from __future__ import annotations

import secrets
from pathlib import Path
from typing import Any, Callable

from concept_forge.providers.ollama import GenerationPlan, OllamaProvider
from concept_forge.subjects import CompiledSubject
from image_forge.adapters import create_engines, discover_plugins
from image_forge.gateway import ImageGateway
from image_forge.port import ImageRequest
from image_forge.plugins import PluginManager


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
        self.concept = OllamaProvider(concept_config["providers"][provider])
        self.manifests = discover_plugins()
        self.engines = create_engines(image_config["adapters"], config["workflow"],
                                      self.manifests)
        self.gateway = ImageGateway(
            self.engines, config["memory"]["database"],
            image_config.get("output_directory", str(
                Path(config["memory"]["database"]).parents[1] / "Outputs")),
            default_engine=adapter,
        )
        self.plugins = PluginManager(self.manifests, self.gateway)
        self.image = self.gateway.select()
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
        selection: dict[str, Any] | None = None,
        saved_negative_prompt: str | None = None,
        previous_positive_prompt: str = "",
    ) -> dict[str, Any]:
        selected = selection or {}
        engine_name = str(selected.get("engine", "")).strip().lower()
        selected_engine = self.gateway.select(engine_name)
        if hasattr(self, "plugins") and not selected_engine.health():
            raise TaskError(f"Enable {selected_engine.name} before generating")
        workflow_id = str(selected.get("workflow", ""))
        checkpoint = str(selected.get("checkpoint", "")).strip()
        vae = str(selected.get("vae", "")).strip()
        llm_model = str(selected.get("llm", "")).strip()
        loras = selected.get("loras", [])
        if not isinstance(loras, list):
            raise TaskError("selection.loras must be a list")
        if llm_model:
            available_llms = self.concept.list_models()
            resolved_llm = self._resolve_ollama_model(llm_model, available_llms)
            if not resolved_llm:
                raise TaskError(f"Selected LLM is unavailable: {llm_model}")
            llm_model = resolved_llm
        prompt_history = list(history or [])
        if previous_positive_prompt:
            prompt_history.append({
                "role": "assistant",
                "content": "Previous complete positive prompt for this character (keep "
                           "reusable user edits and suitable quality/style choices; "
                           "replace scene and composition details according to the "
                           "current request): " + previous_positive_prompt,
            })
        plan = self._get_valid_plan(
            user_text,
            prompt_history,
            notify or (lambda _message: None),
            llm_model,
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
        negative_prompt = (saved_negative_prompt if saved_negative_prompt is not None
                           else plan.negative_prompt)
        negative_prompt = self._merge_prompts(
            negative_prompt, subject.negative_prompt if subject else ""
        )

        items = []
        selected_checkpoint = ""
        selected_vae = ""
        selected_loras: list[dict[str, Any]] = []
        for index in range(1, plan.count + 1):
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
            "status": "queued",
            "model": plan.model,
            "positive_prompt": positive_prompt,
            "negative_prompt": negative_prompt,
            "count": plan.count,
            "selection": {
                "workflow": workflow_id,
                "engine": selected_engine.name,
                "checkpoint": selected_checkpoint,
                "vae": selected_vae,
                "llm": llm_model or str(getattr(self.concept, "model", "")),
                "loras": selected_loras,
            },
            "items": items,
            "subject": (
                {"subject_id": subject.subject_id, "revision": subject.revision}
                if subject
                else None
            ),
        }

    def resources(self, engine: str = "") -> dict[str, Any]:
        llms = self.concept.list_models()
        default_llm = self._resolve_ollama_model(self.concept.model, llms)
        resources = self.gateway.resources(engine)
        resources["llms"] = llms
        resources["defaults"]["llm"] = default_llm or self.concept.model
        return resources

    @staticmethod
    def _resolve_ollama_model(requested: str, available: list[str]) -> str:
        normalized = requested.strip()
        lookup = {name.casefold(): name for name in available}
        exact = lookup.get(normalized.casefold())
        if exact:
            return exact
        if normalized and ":" not in normalized:
            return lookup.get(f"{normalized}:latest".casefold(), "")
        return ""

    @staticmethod
    def _merge_prompts(*prompts: str) -> str:
        return ", ".join(prompt.strip(" ,") for prompt in prompts if prompt.strip(" ,"))

    def _get_valid_plan(
        self,
        user_text: str,
        history: list[dict[str, str]],
        notify: Callable[[str], None],
        llm_model: str = "",
    ) -> GenerationPlan:
        attempts = self.max_model_retries + 1
        for attempt in range(attempts):
            if llm_model:
                plan = self.concept.generate_prompt(
                    user_text, history, model=llm_model
                )
            else:
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
