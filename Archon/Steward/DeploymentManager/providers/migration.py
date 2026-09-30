"""One-time migration of the former Vast-keyed index, outside NodeManager."""
import json
import time
from pathlib import Path
from Archon.Steward.NodeManager.identity import new_id
from Archon.Steward.NodeManager.transport.auth import digest


def migrate_legacy_registry(path, bindings_path, credential_factory):
    path, bindings_path = Path(path), Path(bindings_path)
    if not path.exists():
        return
    raw = json.loads(path.read_text())
    if raw.get("version") != 1:
        return
    if credential_factory is None:
        raise RuntimeError("Legacy Node migration requires its existing credential store")
    joins, bindings = {}, {}
    for instance_id, phase in raw["nodes"].items():
        if not instance_id.isdecimal() or int(instance_id) < 1 or phase not in {"joining", "online"}:
            raise RuntimeError("Invalid legacy Node registry")
        token = credential_factory(f"EverSpark Forge/Node {instance_id}/joining").get()
        if not token:
            raise RuntimeError("Legacy bootstrap credential missing")
        reference = digest(token)
        joins[reference] = {"expires_at": time.time()+86400, "enrollment_id": None, "node_id": new_id()}
        bindings[instance_id] = reference
    backup = path.with_name(path.name+".v1.bak")
    if not backup.exists():
        backup.write_text(json.dumps(raw))
    # Bindings first: interruption before registry publication is safely repeatable.
    bindings_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = bindings_path.with_name(bindings_path.name+".tmp")
    temporary.write_text(json.dumps({"bindings": bindings, "used_key_hash": raw.get("used_key_hash", "")}))
    temporary.replace(bindings_path)
    temporary = path.with_name(path.name+".tmp")
    temporary.write_text(json.dumps({"version": 2, "nodes": {}, "joins": joins}))
    temporary.replace(path)
