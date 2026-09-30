"""EverSpark identities do not derive from hostnames or provider identifiers."""
import secrets
from .errors import NodeError


def new_id():
    return secrets.token_hex(16)


def validate_id(value, name="node_id"):
    if not isinstance(value, str) or len(value) != 32 or any(c not in "0123456789abcdef" for c in value):
        raise NodeError(f"Invalid {name}", 400)
    return value
