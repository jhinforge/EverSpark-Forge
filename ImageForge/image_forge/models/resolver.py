from __future__ import annotations

from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Iterable


CHECKPOINT_EXTENSIONS = {".ckpt", ".safetensors"}


class CheckpointResolutionError(RuntimeError):
    pass


@dataclass(frozen=True)
class CheckpointResolution:
    name: str
    source: str
    warning: str = ""


def _normalise(name: str) -> str:
    return name.strip().replace("\\", "/")


def _compatible(names: Iterable[str]) -> list[str]:
    checkpoints = {
        _normalise(name)
        for name in names
        if isinstance(name, str)
        and PurePosixPath(_normalise(name)).suffix.lower() in CHECKPOINT_EXTENSIONS
    }
    return sorted(checkpoints, key=lambda item: (item.casefold(), item))


def resolve_checkpoint(
    requested: str,
    available: Iterable[str],
    managed_default: str = "",
) -> CheckpointResolution:
    candidates = _compatible(available)
    if not candidates:
        raise CheckpointResolutionError(
            "Image Forge did not report any compatible checkpoint files"
        )

    lookup = {name.casefold(): name for name in candidates}
    requested_name = _normalise(requested)
    default_name = _normalise(managed_default)

    if requested_name and requested_name.casefold() in lookup:
        return CheckpointResolution(lookup[requested_name.casefold()], "workflow")
    if default_name and default_name.casefold() in lookup:
        selected = lookup[default_name.casefold()]
        return CheckpointResolution(
            selected,
            "managed_default",
            f"Checkpoint '{requested_name or '<unset>'}' is unavailable; using managed default '{selected}'.",
        )

    selected = candidates[0]
    return CheckpointResolution(
        selected,
        "first_available",
        f"Checkpoint '{requested_name or '<unset>'}' is unavailable; using first available checkpoint '{selected}'.",
    )
