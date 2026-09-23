from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from ..subjects import new_subject, validate_subject
from ..subjects.document import _merge_object

SYSTEM_PROMPT = """You are the Concept Forge component of EverSpark Forge.
Convert the user's image request into one complete JSON object and output JSON only.
Use the conversation history to resolve follow-up instructions such as changing one
detail, keeping the rest unchanged, or generating more images.
The only supported image model is illustrious.
Use exactly these fields:
{"model":"illustrious","positive_prompt":"...","negative_prompt":"...","count":1,"status":"over"}
count is the number of images requested by the user and defaults to 1.
Prompts should be suitable for an Illustrious/booru-style image workflow.
Translate the user's intent into a complete, usable image prompt. When the user
leaves visual details unspecified, add fitting image-quality, composition,
framing, lighting, and background terms that help depict the requested subject.
Choose details based on the request and conversation instead of repeating a
fixed list of tags. Preserve all explicit user choices and constraints; do not
invent another character or contradict the requested scene or style. Keep
temporary scene and composition details in positive_prompt, not the persistent
character identity. Put unwanted visual artifacts in negative_prompt.
Do not use Markdown and do not add explanations outside the JSON object.
"""

SUBJECT_SYSTEM_PROMPT = """You are the Character Subject builder inside EverSpark Concept Forge.
Return exactly one complete JSON object and no Markdown or commentary.
Return only the identity, appearance, wardrobe, or metadata fields that need updating.
Do not add keys outside the supplied Character Subject v1 template; keep field types.
Prompt terms are managed separately and must not appear in this JSON.
Fill visual identity fields from the user's description. Preserve existing values when
the user does not request a change. For a new subject, infer sensible reusable visual
details when the conversation leaves them open instead of asking the user to configure
schema fields. Do not add scene, pose, camera, or background details to the persistent
character identity. Use concise image-generation terms where useful. Protected document
metadata is owned by Orchestrator and will be applied after your response.
"""

DISCUSSION_SYSTEM_PROMPT = """You are the conversational Concept Forge component of EverSpark Forge.
Discuss the user's current character concept naturally and concisely. Help clarify stable
visual identity such as face, hair, body, clothing, and distinguishing features. You may
suggest or infer sensible details when the user leaves them open. Do not expose internal
JSON, schema fields, or implementation details. Do not claim that an image was generated.
Reply in the user's language.
"""


class OllamaError(RuntimeError):
    pass


@dataclass(frozen=True)
class GenerationPlan:
    model: str
    positive_prompt: str
    negative_prompt: str
    count: int
    status: str


class OllamaProvider:
    def __init__(self, config: dict[str, Any]):
        self.base_url = str(config["base_url"]).rstrip("/")
        self.model = str(config["model"])
        self.timeout = int(config.get("timeout", 180))
        self.prompt_mode = str(config.get("prompt_mode", "")).strip().lower()

    def _system_prompt(self, prompt: str) -> str:
        if self.prompt_mode == "no_think":
            return prompt.rstrip() + "\n/no_think\n"
        return prompt

    def generate_prompt(
        self,
        user_text: str,
        history: list[dict[str, str]] | None = None,
        model: str = "",
    ) -> GenerationPlan:
        messages = [{"role": "system", "content": self._system_prompt(SYSTEM_PROMPT)}]
        messages.extend(history or [])
        messages.append({"role": "user", "content": user_text})
        payload = {
            "model": model.strip() or self.model,
            "stream": False,
            "format": "json",
            "messages": messages,
        }
        response = self._post_json("/api/chat", payload)
        try:
            result = json.loads(response["message"]["content"])
        except (KeyError, TypeError, json.JSONDecodeError) as exc:
            raise OllamaError("Ollama returned an invalid prompt JSON response") from exc
        required = ("model", "positive_prompt", "negative_prompt", "status")
        if any(not isinstance(result.get(key), str) for key in required):
            raise OllamaError("Ollama prompt JSON is missing required string fields")
        try:
            count = int(result.get("count", 1))
        except (TypeError, ValueError) as exc:
            raise OllamaError("Ollama prompt JSON contains an invalid count") from exc
        return GenerationPlan(
            result["model"].strip().lower(),
            result["positive_prompt"].strip(),
            result["negative_prompt"].strip(),
            count,
            result["status"].strip().lower(),
        )

    def generate_subject(
        self,
        user_text: str,
        subject_id: str,
        existing: dict[str, Any] | None = None,
        history: list[dict[str, str]] | None = None,
        assistant_reply: str = "",
        model: str = "",
    ) -> dict[str, Any]:
        if existing is None:
            target = new_subject(subject_id, subject_id)
            expected_revision = 1
            context = "Create the initial subject document from the user description."
        else:
            target = validate_subject(existing)
            if target["subject_id"] != subject_id:
                raise OllamaError("Existing subject_id does not match the requested subject")
            expected_revision = int(target["revision"]) + 1
            context = (
                "Update the existing subject document. Preserve every field not changed "
                "by the user."
            )
        target = json.loads(json.dumps(target, ensure_ascii=False))
        target["revision"] = expected_revision
        subject_prompt = (
            SUBJECT_SYSTEM_PROMPT
            + "\n"
            + context
            + "\nThe required output template/current document is:\n"
            + json.dumps(target, ensure_ascii=False)
        )
        conversation = list(history or [])
        conversation.append({"role": "user", "content": user_text})
        if assistant_reply:
            conversation.append({"role": "assistant", "content": assistant_reply})
        messages = [
            {
                "role": "system",
                "content": self._system_prompt(subject_prompt),
            },
            {
                "role": "user",
                "content": (
                    "Extract the current persistent character identity from this complete "
                    "conversation. Ignore scene-only details. Conversation:\n"
                    + json.dumps(conversation, ensure_ascii=False)
                ),
            },
        ]
        response = self._post_json(
            "/api/chat",
            {
                "model": model.strip() or self.model,
                "stream": False,
                "format": "json",
                "messages": messages,
            },
        )
        try:
            document = json.loads(response["message"]["content"])
        except (KeyError, TypeError, json.JSONDecodeError) as exc:
            raise OllamaError("Ollama returned an invalid subject JSON response") from exc
        if not isinstance(document, dict):
            raise OllamaError("Ollama returned a non-object subject JSON response")

        # Identity and version sequencing are Orchestrator state, not model output.
        # Small local models can echo an earlier revision from conversation context;
        # always stamp the protected envelope before validating the editable content.
        for protected_key in (
            "schema_version",
            "document_type",
            "subject_id",
            "revision",
        ):
            document[protected_key] = target[protected_key]
        try:
            editable = {key: value for key, value in document.items()
                        if key not in ("schema_version", "document_type", "subject_id", "revision")}
            result = json.loads(json.dumps(target, ensure_ascii=False))
            _merge_object(result, editable)
            validate_subject(result)
        except ValueError as exc:
            raise OllamaError(str(exc)) from exc
        return result

    def discuss(
        self,
        user_text: str,
        history: list[dict[str, str]] | None = None,
        model: str = "",
    ) -> str:
        messages = [
            {"role": "system", "content": self._system_prompt(DISCUSSION_SYSTEM_PROMPT)}
        ]
        messages.extend(history or [])
        messages.append({"role": "user", "content": user_text})
        response = self._post_json(
            "/api/chat",
            {
                "model": model.strip() or self.model,
                "stream": False,
                "messages": messages,
            },
        )
        try:
            reply = str(response["message"]["content"]).strip()
        except (KeyError, TypeError) as exc:
            raise OllamaError("Ollama returned an invalid discussion response") from exc
        if not reply:
            raise OllamaError("Ollama returned an empty discussion response")
        return reply

    def list_models(self) -> list[str]:
        response = self._get_json("/api/tags")
        models = response.get("models", [])
        if not isinstance(models, list):
            raise OllamaError("Ollama model list has an invalid shape")
        names = []
        for item in models:
            if isinstance(item, dict) and isinstance(item.get("name"), str):
                name = item["name"].strip()
                if name:
                    names.append(name)
        return sorted(set(names), key=lambda item: (item.casefold(), item))

    def _get_json(self, path: str) -> dict[str, Any]:
        request = Request(f"{self.base_url}{path}", method="GET")
        try:
            with urlopen(request, timeout=self.timeout) as response:
                result = json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise OllamaError(f"Ollama HTTP {exc.code}: {detail}") from exc
        except URLError as exc:
            raise OllamaError(
                f"Cannot connect to Ollama at {self.base_url}: {exc.reason}"
            ) from exc
        except json.JSONDecodeError as exc:
            raise OllamaError("Ollama returned invalid HTTP JSON") from exc
        if not isinstance(result, dict):
            raise OllamaError("Ollama returned an invalid JSON object")
        return result

    def _post_json(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        request = Request(f"{self.base_url}{path}", data=json.dumps(payload, ensure_ascii=True).encode("utf-8"), headers={"Content-Type": "application/json; charset=utf-8"}, method="POST")
        try:
            with urlopen(request, timeout=self.timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise OllamaError(f"Ollama HTTP {exc.code}: {detail}") from exc
        except URLError as exc:
            raise OllamaError(f"Cannot connect to Ollama at {self.base_url}: {exc.reason}") from exc
        except json.JSONDecodeError as exc:
            raise OllamaError("Ollama returned invalid HTTP JSON") from exc
