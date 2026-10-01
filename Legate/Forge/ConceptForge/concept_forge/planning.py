"""Prompt planning and provider/model selection owned by Concept Forge."""
from __future__ import annotations
from typing import Any, Callable
from Aegis.Shared.errors import TaskError

class ConceptPlanning:
    def __init__(self, config, service, max_batch_size=20):
        self.concept = service
        self.supported_models = {str(model).strip().lower() for model in
            config.get("supported_models", ["illustrious"])}
        self.max_model_retries = int(config.get("max_model_retries", 3))
        self.max_batch_size = max_batch_size

    def plan(self, user_text, history=None, notify=None, subject=None, selection=None,
             saved_negative_prompt=None, previous_positive_prompt="",
             change_negative_prompt=False):
        selected = selection or {}
        llm_model = str(selected.get("llm", "")).strip()
        concept_provider = str(selected.get("concept_provider", "")).strip()
        if llm_model:
            available_llms = self.concept.list_models(concept_provider) if concept_provider else self.concept.list_models()
            resolved_llm = self._resolve_model(llm_model, available_llms)
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
            concept_provider,
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
        selected_llm = (llm_model or (self.concept.gateway.select(concept_provider).model
            if hasattr(self.concept, "gateway") else str(getattr(self.concept, "model", ""))))
        return {
            "model": plan.model, "count": plan.count,
            "positive_prompt": positive_prompt,
            "negative_prompt": plan.negative_prompt,
            "extra_negative_prompt": subject.negative_prompt if subject else "",
            "saved_negative_prompt": saved_negative_prompt,
            "change_negative_prompt": change_negative_prompt,
        }, {"llm": selected_llm, "concept_provider": concept_provider or
            str(getattr(getattr(self.concept, "gateway", None), "default", "ollama"))}

    @staticmethod
    def _resolve_model(requested: str, available: list[str]) -> str:
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
        concept_provider: str = "",
    ) -> Any:
        attempts = self.max_model_retries + 1
        for attempt in range(attempts):
            kwargs = {}
            if llm_model:
                kwargs["model"] = llm_model
            if concept_provider:
                kwargs["provider"] = concept_provider
            plan = self.concept.generate_prompt(user_text, history, **kwargs)
            if plan.model in self.supported_models:
                return plan
            if attempt < attempts - 1:
                notify("Error Model,Reloading.....")
        supported = ", ".join(sorted(self.supported_models))
        raise TaskError(
            "Concept Forge did not return a supported model "
            f"after {attempts} attempts: {supported}"
        )
