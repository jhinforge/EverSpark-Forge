"""Start Portal and the control-only Orchestrator without a shell or worker."""

from __future__ import annotations

import os
import sys
import threading
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]


def _load_local_settings() -> None:
    """Read only control-side settings; never activate legacy runtime settings."""
    allowed = {"EVERSPARK_WEBUI_PORT", "EVERSPARK_ORCHESTRATOR_PORT",
               "EVERSPARK_LOG_DIR", "EVERSPARK_WEBUI_LOG", "EVERSPARK_OUTPUT_DIR"}
    config = REPO_ROOT / ".env"
    if config.is_file():
        for raw in config.read_text(encoding="utf-8-sig").splitlines():
            line = raw.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                if key.strip() in allowed:
                    os.environ.setdefault(key.strip(), value.strip().strip("\"'"))

    # The control-only mode is always local, even if a legacy .env points elsewhere.
    os.environ["EVERSPARK_WEBUI_HOST"] = "127.0.0.1"
    os.environ["EVERSPARK_ORCHESTRATOR_HOST"] = "127.0.0.1"
    backend_port = int(os.environ.get("EVERSPARK_ORCHESTRATOR_PORT", "8765"))
    os.environ["EVERSPARK_ORCHESTRATOR_URL"] = f"http://127.0.0.1:{backend_port}"
    os.environ["EVERSPARK_ARCHON_CONTROL_URL"] = f"http://127.0.0.1:{backend_port}"
    os.environ["EVERSPARK_ARCHON_ONLY"] = "1"


def start() -> int:
    _load_local_settings()
    sys.path.insert(0, str(REPO_ROOT))
    from Archon.Gate.control_server import ControlServer
    from Archon.Steward.vast_instances import VastInstances
    from Archon.Vault.windows_credentials import WindowsCredentialStore
    from Archon.Portal.app import LOG_DIR, LOG_FILE, WebUIServer, get_logger, load_settings

    logger = get_logger("webui", LOG_FILE)
    backend_logger = get_logger("gate", LOG_DIR / "archon/gate.log")
    backend = None
    portal = None
    worker = None
    try:
        backend_port = int(os.environ.get("EVERSPARK_ORCHESTRATOR_PORT", "8765"))
        machines = VastInstances(WindowsCredentialStore()) if sys.platform == "win32" else None
        backend = ControlServer(("127.0.0.1", backend_port), machines)
        portal = WebUIServer(load_settings(), logger)
        worker = threading.Thread(target=backend.serve_forever, name="archon-backend", daemon=True)
        worker.start()
        backend_logger.ok("server.ready", "Archon control backend is ready", port=backend.server_port)
        logger.ok("server.ready", "Archon Portal is ready", port=portal.server_port)
        print(f"Archon backend: http://127.0.0.1:{backend.server_port}", flush=True)
        print(f"Portal: http://127.0.0.1:{portal.server_port}", flush=True)
        portal.serve_forever()
    except KeyboardInterrupt:
        pass
    except (OSError, ValueError) as exc:
        print(f"Archon startup failed: {exc}", file=sys.stderr)
        return 1
    finally:
        if portal is not None:
            portal.server_close()
        if backend is not None:
            if worker is not None:
                backend.shutdown()
                worker.join(timeout=5)
            backend.server_close()
        backend_logger.close()
        logger.close()
    return 0


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if args == ["start"]:
        return start()
    print("Usage: everspark archon start")
    return 0 if args in ([], ["help"], ["--help"]) else 2


if __name__ == "__main__":
    raise SystemExit(main())
