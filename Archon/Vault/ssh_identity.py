"""A dedicated, per-user SSH identity for managed Vast instances."""

from __future__ import annotations

import getpass
import os
import subprocess
from pathlib import Path


class SSHIdentity:
    def __init__(self, root: Path | None = None, *, run=subprocess.run):
        self.root = root or Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "EverSpark" / "SSH"
        self.run = run

    @property
    def private_key(self) -> Path:
        return self.root / "deployment_ed25519"

    @property
    def known_hosts(self) -> Path:
        return self.root / "known_hosts"

    def public_key(self) -> str:
        self.root.mkdir(parents=True, exist_ok=True)
        private = self.private_key
        public = Path(str(private) + ".pub")
        if not private.is_file() or not public.is_file():
            if private.exists() or public.exists():
                raise RuntimeError("Incomplete deployment SSH identity")
            result = self.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "",
                               "-f", str(private)], capture_output=True, text=True, timeout=30)
            if result.returncode:
                raise RuntimeError("Could not create deployment SSH identity")
        if os.name == "nt":
            user = getpass.getuser()
            for path in (private, public):
                result = self.run(["icacls", str(path), "/inheritance:r", "/grant:r", f"{user}:F"],
                                  capture_output=True, text=True, timeout=15)
                if result.returncode:
                    raise RuntimeError("Could not secure deployment SSH identity")
        else:
            private.chmod(0o600)
        value = public.read_text(encoding="utf-8").strip()
        if not value.startswith("ssh-ed25519 "):
            raise RuntimeError("Invalid deployment SSH public key")
        return value
