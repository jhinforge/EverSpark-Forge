from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from ..subjects import new_subject, validate_subject

SYSTEM_PROMPT = """You are the Concept Forge component of EverSpark Forge.
Convert the user's image request into one complete JSON object and output JSON only.
Use the conversation history to resolve follow-up instructions such as changing one
detail, keeping the rest unchanged, or generating more images.
The only supported image model is illustrious.
Use exactly these fields:
{"model":"illustrious","positive_prompt":"...","negative_prompt":"...","count":1,"status":"over"}
count is the number of images requested by the user and defaults to 1.
Prompts should be suitable for an Illustrious/booru-style image workflow.
Do not use Markdown and do not add explanations outside the JSON object.
"""

SUBJECT_SYSTEM_PROMPT = """You are the Character Subject builder inside EverSpark Concept Forge.
Return exactly one complete JSON object and no Markdown or commentary.
The output must preserve every key in the supplied Character Subject v1 template,
must not add keys, and must use arrays and strings with the same types as the template.
Fill visual identity fields from the user's description. Preserve existing values when
the user does not request a change. Do not add scene, pose, camera, or background details
to the persistent character identity. Use concise image-generation terms where useful.
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

    def generate_prompt(
        self, user_text: str, history: list[dict[str, str]] | None = None
    ) -> GenerationPlan:
        messages = [{"role": "system", "content": SYSTEM_PROMPT}]
        messages.extend(history or [])
        messages.append({"role": "user", "content": user_text})
        payload = {
            "model": self.model,
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
        messages = [
            {
                "role": "system",
                "content": SUBJECT_SYSTEM_PROMPT
                + "\n"
                + context
                + "\nThe required output template/current document is:\n"
                + json.dumps(target, ensure_ascii=False),
            },
            {"role": "user", "content": user_text},
        ]
        response = self._post_json(
            "/api/chat",
            {
                "model": self.model,
                "stream": False,
                "format": "json",
                "messages": messages,
            },
        )
        try:
            document = json.loads(response["message"]["content"])
        except (KeyError, TypeError, json.JSONDecodeError) as exc:
            raise OllamaError("Ollama returned an invalid subject JSON response") from exc
        try:
            validate_subject(document)
        except ValueError as exc:
            raise OllamaError(str(exc)) from exc
        if document["subject_id"] != subject_id:
            raise OllamaError("Ollama changed the protected subject_id")
        if document["revision"] != expected_revision:
            raise OllamaError(
                f"Ollama returned revision {document['revision']}; "
                f"expected {expected_revision}"
            )
        return document

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
