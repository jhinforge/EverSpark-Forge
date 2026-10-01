from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from .subjects import new_subject, validate_subject
from .subjects.document import _merge_object

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
If a previous positive prompt is supplied in the conversation, preserve its
reusable user changes where they fit. Update the scene and composition for the
current request; the current user's choices take priority.
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
metadata is owned by Concept Forge and will be applied after your response.
"""

DISCUSSION_SYSTEM_PROMPT = """You are the conversational Concept Forge component of EverSpark Forge.
Discuss the user's current character concept naturally and concisely. Help clarify stable
visual identity such as face, hair, body, clothing, and distinguishing features. You may
suggest or infer sensible details when the user leaves them open. Do not expose internal
JSON, schema fields, or implementation details. Do not claim that an image was generated.
Reply in the user's language.
"""

CREATION_SYSTEM_PROMPT = """You are EverSpark Concept Forge's creative planning stage.
Understand the user's request and decompose the creative work. Return JSON only:
{"steps":[{"key":"scene-1","forge":"image","brief":"complete creative brief",
"depends_on":[]},{"key":"speech-1","forge":"audio","brief":"spoken content brief",
"depends_on":["scene-1"]}]}
Use only the available Forge names supplied by the caller. Image creates images;
audio synthesizes spoken text, not music or sound effects. Each brief must preserve
the user's language, explicit content and constraints. Keep visual descriptions,
voice characteristics, and spoken content separate in the creative briefs.
Create an audio step only when speech, a voice, or narration is requested. When a
character is given a voice but no dialogue is supplied, the audio brief must ask
for one short, original line spoken by that character, fitting the character and
scene. Default to the language of the user's request unless another spoken language
is explicitly requested. A voice description is a delivery constraint, not dialogue;
never ask Audio to read an image prompt or a list of visual/voice characteristics.
Do not claim that a requested voice characteristic has already been achieved.
Split distinct scenes or
utterances into separate steps when requested. Dependencies refer to step keys and
express creative relationships. Do not invent runtime task IDs, execution states,
providers, models, checkpoints, workflows, paths, or backend settings.
Do not generate final image prompts or speech text yet: that is the second stage.
"""

SPEECH_SYSTEM_PROMPT = """You are EverSpark Concept Forge's speech-writing stage.
Return exactly {"text":"the complete spoken text","voice_description":"natural-language voice description"}
as JSON, no commentary. Keep the two fields separate.
Preserve explicitly supplied dialogue verbatim, including its language and punctuation.
If no dialogue is supplied, create one short, natural line spoken by the character
that fits the character and scene. For an explicitly requested narration or longer
script, compose that content instead. Do not ask the user to provide dialogue.
Use the original user's request to determine the spoken language: an explicit language
request wins; otherwise use the language of that request, not the language of a brief
or image context. For example, a Chinese request for a girl's portrait and a youthful
female voice without dialogue needs an original Chinese character line.
Treat visual descriptions as creative context. Preserve the user's requested voice
characteristics in voice_description: gender, age, timbre, tone, emotion, and pace
when specified. Write a concise English description, up to 1000 characters, without
parentheses or technical settings. For example, 年轻女孩的声音 becomes "young female voice".
Do not invent extra voice characteristics; return an empty voice_description when
none are requested. The voice description's language does not change the spoken language.
Never put the voice description into text or omit it because dialogue is unspecified.
Never read or translate an image prompt, rendering tags, or technical/voice descriptions
as dialogue unless the user explicitly requests those exact words to be spoken.
The text field contains only words to be spoken: no speaker labels, stage directions,
voice instructions, model parameters, paths, or reference audio. Voice delivery is
Audio Forge's responsibility; do not claim a requested voice has been produced.
"""


from .port import ChatRequest, ConceptError
from .gateway import ConceptGateway


@dataclass(frozen=True)
class GenerationPlan:
    model: str
    positive_prompt: str
    negative_prompt: str
    count: int
    status: str


class ConceptService:
    def __init__(self, gateway: ConceptGateway):
        self.gateway = gateway

    @property
    def model(self) -> str:
        return self.gateway.model

    def _chat(self, messages: list[dict[str, str]], model: str = "", json_mode: bool = False,
              provider: str = "") -> str:
        adapter = self.gateway.select(provider)
        return self.gateway.chat(ChatRequest(messages, model or adapter.model, json_mode), provider).content

    def list_models(self, provider: str = "") -> list[str]:
        return self.gateway.list_models(provider)

    def decompose(self, text, history, available_forges, model="", provider=""):
        response = self._chat([
            {"role": "system", "content": CREATION_SYSTEM_PROMPT},
            *(history or []),
            {"role": "user", "content": json.dumps({"request": text,
                "available_forges": available_forges}, ensure_ascii=False)},
        ], model, json_mode=True, provider=provider)
        try:
            value = json.loads(response)
            steps = value["steps"]
            if not isinstance(steps, list) or not 1 <= len(steps) <= 64:
                raise ValueError("Expected 1 to 64 creative steps")
            for step in steps:
                if (not isinstance(step, dict) or set(step) != {"key", "forge", "brief", "depends_on"}
                        or step["forge"] not in available_forges
                        or any(not isinstance(step[k], str) or not step[k].strip()
                               or len(step[k]) > 12000 for k in ("key", "brief"))
                        or not isinstance(step["depends_on"], list)
                        or any(not isinstance(k, str) for k in step["depends_on"])):
                    raise ValueError("Invalid creative step")
            return {"steps": steps}
        except (ValueError, KeyError, TypeError) as exc:
            raise ConceptError("Concept Forge returned an invalid creative decomposition") from exc

    def generate_speech(self, brief, context, model="", provider=""):
        response = self._chat([
            {"role": "system", "content": SPEECH_SYSTEM_PROMPT},
            {"role": "user", "content": json.dumps({"brief": brief,
                "context": context}, ensure_ascii=False)},
        ], model, json_mode=True, provider=provider)
        try:
            value = json.loads(response)
            if (not isinstance(value, dict) or "text" not in value
                    or set(value) - {"text", "voice_description"}
                    or not isinstance(value["text"], str) or not value["text"].strip()
                    or len(value["text"]) > 12000
                    or not isinstance(value.get("voice_description", ""), str)
                    or len(value.get("voice_description", "")) > 1000):
                raise ValueError("Invalid speech text")
            return value
        except (ValueError, TypeError) as exc:
            raise ConceptError("Concept Forge returned invalid speech text") from exc

    def generate_prompt(
        self,
        user_text: str,
        history: list[dict[str, str]] | None = None,
        model: str = "",
        provider: str = "",
    ) -> GenerationPlan:
        messages = [{"role": "system", "content": SYSTEM_PROMPT}]
        messages.extend(history or [])
        messages.append({"role": "user", "content": user_text})
        response = self._chat(messages, model.strip(), json_mode=True, provider=provider)
        try:
            result = json.loads(response)
        except (KeyError, TypeError, json.JSONDecodeError) as exc:
            raise ConceptError("Concept Forge model returned an invalid prompt JSON response") from exc
        if not isinstance(result, dict):
            raise ConceptError("Concept Forge model returned a non-object prompt JSON response")
        required = ("model", "positive_prompt", "negative_prompt", "status")
        if any(not isinstance(result.get(key), str) for key in required):
            raise ConceptError("Concept Forge prompt JSON is missing required string fields")
        try:
            count = int(result.get("count", 1))
        except (TypeError, ValueError) as exc:
            raise ConceptError("Concept Forge prompt JSON contains an invalid count") from exc
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
        provider: str = "",
    ) -> dict[str, Any]:
        if existing is None:
            target = new_subject(subject_id, subject_id)
            expected_revision = 1
            context = "Create the initial subject document from the user description."
        else:
            target = validate_subject(existing)
            if target["subject_id"] != subject_id:
                raise ConceptError("Existing subject_id does not match the requested subject")
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
                "content": subject_prompt,
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
        response = self._chat(messages, model.strip(), json_mode=True, provider=provider)
        try:
            document = json.loads(response)
        except (KeyError, TypeError, json.JSONDecodeError) as exc:
            raise ConceptError("Concept Forge model returned an invalid subject JSON response") from exc
        if not isinstance(document, dict):
            raise ConceptError("Concept Forge model returned a non-object subject JSON response")

        # Identity and version sequencing are Concept Forge state, not model output.
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
            raise ConceptError(str(exc)) from exc
        return result

    def discuss(
        self,
        user_text: str,
        history: list[dict[str, str]] | None = None,
        model: str = "",
        provider: str = "",
    ) -> str:
        messages = [{"role": "system", "content": DISCUSSION_SYSTEM_PROMPT}]
        messages.extend(history or [])
        messages.append({"role": "user", "content": user_text})
        response = self._chat(messages, model.strip(), provider=provider)
        reply = response.strip()
        if not reply:
            raise ConceptError("Concept Forge model returned an empty discussion response")
        return reply

    def revise_prompt(self, user_text: str, field: str, current: str, model: str = "") -> str:
        if field not in {"positive_prompt", "negative_prompt"}:
            raise ValueError("Unsupported prompt field")
        response = self._chat([
                {"role": "system", "content": (
                    f"Update only the complete {field} for an Illustrious image workflow. "
                    f"Return one JSON object with exactly the key {field}. "
                    "Apply the user's change while preserving unrelated prompt details. "
                    "Do not add explanations or other JSON keys."
                )},
                {"role": "user", "content": json.dumps(
                    {"current": current, "request": user_text}, ensure_ascii=False
                )},
            ], model.strip(), json_mode=True)
        try:
            result = json.loads(response)
        except (KeyError, TypeError, json.JSONDecodeError) as exc:
            raise ConceptError("Concept Forge model returned invalid prompt revision JSON") from exc
        if not isinstance(result, dict) or set(result) != {field} or not isinstance(result[field], str):
            raise ConceptError("Concept Forge model returned an invalid prompt revision")
        return result[field].strip()

    def revise_subject_section(
        self, user_text: str, group: str, current: dict[str, Any], model: str = ""
    ) -> dict[str, Any]:
        if group not in {"subject", "metadata"}:
            raise ValueError("Unsupported subject group")
        target = (current["metadata"] if group == "metadata" else
                  {key: value for key, value in current.items()
                   if key in {"identity", "appearance", "wardrobe"}})
        response = self._chat([
                {"role": "system", "content": (
                    f"Revise only this character {group} JSON group. Return an object "
                    "containing only the fields you changed, using the same types and "
                    "field names as the supplied current group. Preserve all other values "
                    "by omitting them. No Markdown or explanation."
                )},
                {"role": "user", "content": json.dumps(
                    {"current": target, "request": user_text}, ensure_ascii=False
                )},
            ], model.strip(), json_mode=True)
        try:
            patch = json.loads(response)
        except (KeyError, TypeError, json.JSONDecodeError) as exc:
            raise ConceptError("Concept Forge model returned invalid subject group JSON") from exc
        if not isinstance(patch, dict):
            raise ConceptError("Concept Forge model returned a non-object subject group")
        updated = json.loads(json.dumps(target, ensure_ascii=False))
        try:
            _merge_object(updated, patch)
            candidate = json.loads(json.dumps(current, ensure_ascii=False))
            if group == "metadata":
                candidate["metadata"] = updated
            else:
                candidate.update(updated)
            candidate["revision"] = current["revision"] + 1
            validate_subject(candidate)
        except ValueError as exc:
            raise ConceptError(str(exc)) from exc
        return candidate
