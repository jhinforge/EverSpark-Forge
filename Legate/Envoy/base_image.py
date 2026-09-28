"""Choose the initial NVIDIA image from a Vast offer's CUDA capability."""

from __future__ import annotations


def select_base_image(offer: dict) -> str:
    try:
        cuda = float(offer["cuda_max_good"])
    except (KeyError, TypeError, ValueError):
        raise ValueError("Vast offer does not report CUDA compatibility") from None
    if cuda >= 12.8:
        return "nvidia/cuda:12.8.0-cudnn-runtime-ubuntu22.04"
    raise ValueError("This offer cannot run the supported NVIDIA CUDA 12.8 image")
