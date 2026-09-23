from __future__ import annotations

import copy
from typing import Any

from .schema import validate_subject


EDITABLE_SECTIONS = {
    "identity",
    "appearance",
    "wardrobe",
    "metadata",
}


def new_subject(subject_id: str, display_name: str) -> dict[str, Any]:
    document: dict[str, Any] = {
        "schema_version": "1.0",
        "document_type": "character_subject",
        "subject_id": subject_id,
        "revision": 1,
        "identity": {
            "display_name": display_name,
            "aliases": [],
            "species": "",
            "age_descriptor": "",
            "gender_presentation": "",
        },
        "appearance": {
            "body": {"build": "", "height_descriptor": "", "skin_tone": ""},
            "face": {"shape": "", "eye_color": "", "eye_style": ""},
            "hair": {"color": "", "length": "", "style": ""},
            "distinguishing_features": [],
        },
        "wardrobe": {"default_outfit": "", "items": [], "accessories": []},
        "metadata": {"tags": [], "notes": ""},
    }
    return validate_subject(document)


def _merge_object(target: dict[str, Any], changes: dict[str, Any]) -> None:
    for key, value in changes.items():
        if key not in target:
            raise ValueError(f"Unknown subject field: {key}")
        if isinstance(target[key], dict) and isinstance(value, dict):
            _merge_object(target[key], value)
        else:
            target[key] = copy.deepcopy(value)


def update_subject(document: dict[str, Any], changes: dict[str, Any]) -> dict[str, Any]:
    current = copy.deepcopy(validate_subject(document))
    if not isinstance(changes, dict):
        raise ValueError("Subject changes must be an object")
    forbidden = sorted(set(changes) - EDITABLE_SECTIONS)
    if forbidden:
        raise ValueError(
            "Subject changes contain protected or unknown fields: "
            + ", ".join(forbidden)
        )
    for section, section_changes in changes.items():
        if not isinstance(section_changes, dict):
            raise ValueError(f"Subject section update must be an object: {section}")
        _merge_object(current[section], section_changes)
    current["revision"] += 1
    return validate_subject(current)
