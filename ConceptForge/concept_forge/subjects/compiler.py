from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from .schema import validate_subject


@dataclass(frozen=True)
class CompiledSubject:
    subject_id: str
    revision: int
    positive_prompt: str
    negative_prompt: str


def _clean(values: Iterable[Any]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = str(value).strip()
        key = text.casefold()
        if text and key not in seen:
            result.append(text)
            seen.add(key)
    return result


def _combined_feature(parts: Iterable[Any], suffix: str) -> str:
    values = _clean(parts)
    if not values:
        return ""
    if values[-1].casefold().endswith(suffix.casefold()):
        return " ".join(values)
    return " ".join([*values, suffix])


def compile_subject(document: dict[str, Any], prompts: dict[str, Any] | None = None) -> CompiledSubject:
    subject = validate_subject(document)
    identity = subject["identity"]
    appearance = subject["appearance"]
    body = appearance["body"]
    face = appearance["face"]
    hair = appearance["hair"]
    wardrobe = subject["wardrobe"]
    prompts = prompts or {}

    positive = _clean(
        [
            identity["species"],
            identity["age_descriptor"],
            identity["gender_presentation"],
            body["build"],
            body["height_descriptor"],
            body["skin_tone"],
            face["shape"],
            _combined_feature([face["eye_color"], face["eye_style"]], "eyes"),
            _combined_feature([hair["length"], hair["color"], hair["style"]], "hair"),
            *appearance["distinguishing_features"],
            wardrobe["default_outfit"],
            *wardrobe["items"],
            *wardrobe["accessories"],
            prompts.get("positive_prompt", ""),
        ]
    )
    negative = _clean([prompts.get("negative_prompt", "")])
    return CompiledSubject(
        subject_id=subject["subject_id"],
        revision=subject["revision"],
        positive_prompt=", ".join(positive),
        negative_prompt=", ".join(negative),
    )
