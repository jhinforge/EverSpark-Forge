"""Capacity and current availability are distinct; this does not place tasks."""
import math
from dataclasses import asdict
from .models.resource import ResourceSet
from .errors import NodeError


def quantity(value, integer=False):
    if (isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value)
            or value < 0 or (integer and int(value) != value)):
        raise NodeError("Invalid resource quantity", 400)
    return int(value) if integer else value


def resource_set(raw):
    if not isinstance(raw, dict) or set(raw) != {"cpu", "memory", "disk", "gpu"}:
        raise NodeError("Invalid resource set", 400)
    devices = raw["gpu"]
    if not isinstance(devices, dict) or len(devices) > 256:
        raise NodeError("Invalid GPU resources", 400)
    gpu = {}
    for key, values in devices.items():
        if not isinstance(key, str) or not key or len(key) > 128 or not isinstance(values, dict) or set(values) != {"vram"}:
            raise NodeError("Invalid GPU device", 400)
        gpu[key] = {"vram": quantity(values["vram"], integer=True)}
    return asdict(ResourceSet(quantity(raw["cpu"]), quantity(raw["memory"], True), quantity(raw["disk"], True), gpu))


def allocatable(raw, capacity):
    available = resource_set(raw)
    if any(available[k] > capacity[k] for k in ("cpu", "memory", "disk")) or set(available["gpu"]) != set(capacity["gpu"]):
        raise NodeError("Allocatable exceeds or differs from capacity", 400)
    if any(v["vram"] > capacity["gpu"][key]["vram"] for key, v in available["gpu"].items()):
        raise NodeError("Allocatable VRAM exceeds capacity", 400)
    return available


def resources(raw):
    if not isinstance(raw, dict) or set(raw) != {"capacity", "allocatable"}:
        raise NodeError("Capacity and allocatable required", 400)
    capacity = resource_set(raw["capacity"])
    return {"capacity": capacity, "allocatable": allocatable(raw["allocatable"], capacity)}
