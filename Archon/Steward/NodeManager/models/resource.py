"""CPU in logical cores; memory, disk and device VRAM in bytes."""
from dataclasses import dataclass, field


@dataclass
class ResourceSet:
    cpu: float
    memory: int
    disk: int
    gpu: dict = field(default_factory=dict)
