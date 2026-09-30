import hashlib
import hmac
import secrets
from ..errors import NodeError
from ..identity import validate_id


def secret():
    return secrets.token_urlsafe(32)


def digest(value):
    if not isinstance(value, str) or not value:
        raise NodeError("Credential required", 403)
    return hashlib.sha256(value.encode()).hexdigest()


def authenticate(manager, body):
    node_id = validate_id(body.get("node_id"))
    node = manager.registry.nodes.get(node_id)
    lease = manager.leases.get(node_id)
    session = body.get("session")
    if (not node or node["status"] == "removed" or not lease or not isinstance(session, str)
            or not hmac.compare_digest(session, lease.session) or body.get("runtime_id") != lease.runtime_id):
        raise NodeError("Invalid Node session or runtime", 403)
    return node, lease
