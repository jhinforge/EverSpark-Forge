"""Static Node fingerprint and separately maintained runtime Lease."""
from dataclasses import dataclass, field


@dataclass
class Node:
    node_id: str
    enrollment_id: str
    hostname: str
    system: dict
    hardware: dict
    resources: dict
    provider_metadata: dict = field(default_factory=dict)
    status: str = "joining"
    last_seen: str | None = None


@dataclass
class Lease:
    runtime_id: str
    session: str
    renewed_at: float
    last_seen: str
    allocatable: dict
    load: dict = field(default_factory=dict)
