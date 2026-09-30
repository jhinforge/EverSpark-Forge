"""Validation of static Node inventory, shared by registration and persistence."""
import copy
from .errors import NodeError
from .resources import resources


def inventory(info):
    if not isinstance(info, dict) or not isinstance(info.get("hostname"), str) or not 1 <= len(info["hostname"]) <= 253:
        raise NodeError("Node hostname required", 400)
    if not isinstance(info.get("system"), dict) or any(not isinstance(info["system"].get(k), str) or not 1 <= len(info["system"][k]) <= 128 for k in ("os", "architecture")):
        raise NodeError("OS and architecture required", 400)
    if not isinstance(info.get("hardware"), dict) or not isinstance(info.get("provider_metadata", {}), dict):
        raise NodeError("Invalid Node inventory", 400)
    return {"hostname": info["hostname"], "system": copy.deepcopy(info["system"]), "hardware": copy.deepcopy(info["hardware"]),
            "provider_metadata": copy.deepcopy(info.get("provider_metadata", {})), "resources": resources(info.get("resources"))}
