"""Local WebUI setup for provider bootstrap networking; never exposes secrets."""
import hashlib
import ipaddress
import re
import subprocess
from urllib.parse import urlsplit
from Archon.Steward.vast_instances import VastError
from .network import tailscale_ip


def status(bridge):
    if bridge is None:
        return {"ready": False, "reason": "unavailable"}
    address = urlsplit(bridge.url).hostname
    try:
        ip = ipaddress.ip_address(address)
        reachable = not ip.is_loopback and not ip.is_unspecified
    except ValueError:
        reachable = bool(address and address != "localhost")
    return {"ready": bool(bridge.auth_key and reachable),
            "reason": "ready" if bridge.auth_key and reachable else "key_required",
            "listener": bridge.url, "key_available": bool(bridge.auth_key), "reusable": bridge.reusable}


def configure(bridge, payload):
    if bridge is None:
        raise VastError("Node deployment is unavailable", 503)
    key = payload.get("key")
    reusable = payload.get("reusable", False)
    if not isinstance(reusable, bool):
        raise VastError("Invalid Tailscale key mode", 400)
    if set(payload) - {"key", "reusable"} or not isinstance(key, str) or not re.fullmatch(r"tskey-auth-[A-Za-z0-9_-]{8,512}", key):
        raise VastError("Enter a valid Tailscale auth key", 400)
    with bridge.lock:
        if bridge.pending:
            raise VastError("Wait for the current rental to finish", 409)
        if not reusable and key and hashlib.sha256(key.encode()).hexdigest() == bridge.used_key_hash:
            raise VastError("This Tailscale key was already used; enter a new key", 409)
        try:
            bridge.manager.listen_on(tailscale_ip())
        except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
            raise VastError("Tailscale must be connected on the Archon host before configuring automatic nodes", 409) from exc
        bridge.configure_auth_key(key, reusable=reusable)
        return status(bridge)
