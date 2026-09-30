"""Optional Tailscale network setup belongs to provisioning, not Node identity."""
import os
import shutil
import ipaddress
import subprocess
from pathlib import Path
def _tailscale_cli() -> str:
    configured = os.environ.get("EVERSPARK_TAILSCALE_EXE")
    if configured:
        if Path(configured).is_file():
            return configured
        raise RuntimeError("EVERSPARK_TAILSCALE_EXE does not point to tailscale.exe")

    executable = shutil.which("tailscale")
    if executable:
        return executable
    # The Windows installer does not always add its CLI to PATH.
    for root in (os.environ.get("ProgramFiles"), os.environ.get("ProgramFiles(x86)")):
        if root:
            candidate = Path(root) / "Tailscale" / "tailscale.exe"
            if candidate.is_file():
                return str(candidate)
    raise RuntimeError("Tailscale CLI not found. Install Tailscale or set "
                       "EVERSPARK_TAILSCALE_EXE to the full path of tailscale.exe")


def tailscale_ip(run=subprocess.run) -> str:
    try:
        result = run([_tailscale_cli(), "ip", "-4"], capture_output=True, text=True, timeout=5)
    except FileNotFoundError as exc:
        raise RuntimeError("Tailscale CLI executable is missing; check "
                           "EVERSPARK_TAILSCALE_EXE or reinstall Tailscale") from exc
    address = result.stdout.strip().splitlines()[0] if result.stdout.strip() else ""
    try:
        valid = ipaddress.ip_address(address) in ipaddress.ip_network("100.64.0.0/10")
    except ValueError:
        valid = False
    if result.returncode or not valid:
        raise RuntimeError("Connect this Windows host to Tailscale before starting Archon")
    return address
