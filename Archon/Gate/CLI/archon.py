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
               "EVERSPARK_CONCEPT_INSTANCE_ID", "EVERSPARK_IMAGE_INSTANCE_ID",
               "EVERSPARK_REMOTE_ORCHESTRATOR_PORT", "EVERSPARK_CONCEPT_NODE_ID",
               "EVERSPARK_IMAGE_NODE_ID", "EVERSPARK_NODE_HOST", "EVERSPARK_NODE_PORT",
               "EVERSPARK_NODE_STATE",
               "EVERSPARK_LOG_DIR", "EVERSPARK_WEBUI_LOG", "EVERSPARK_OUTPUT_DIR",
               "EVERSPARK_STORAGE_BACKEND", "RCLONE_CONFIG", "RCLONE_BIN",
               "IMAGE_FORGE_RCLONE_REMOTE", "CONCEPT_FORGE_RCLONE_REMOTE",
               "EVERSPARK_BACKUP_REMOTE", "EVERSPARK_LOG_LEVEL",
               "EVERSPARK_LOG_FORMAT", "EVERSPARK_LOG_CONSOLE", "EVERSPARK_RUN_ID"}
    config = REPO_ROOT / ".env"
    if config.is_file():
        sys.path.insert(0, str(REPO_ROOT))
        from Archon.Vault.import_config import parse_env
        for key, value in parse_env(config).items():
            if key in allowed:
                os.environ.setdefault(key, value)

    # The control-only mode is always local, even if a legacy .env points elsewhere.
    os.environ["EVERSPARK_WEBUI_HOST"] = "127.0.0.1"
    os.environ["EVERSPARK_ORCHESTRATOR_HOST"] = "127.0.0.1"
    backend_port = int(os.environ.get("EVERSPARK_ORCHESTRATOR_PORT", "8765"))
    os.environ["EVERSPARK_ORCHESTRATOR_URL"] = f"http://127.0.0.1:{backend_port}"
    os.environ["EVERSPARK_ARCHON_CONTROL_URL"] = f"http://127.0.0.1:{backend_port}"
    if os.environ.get("EVERSPARK_CONCEPT_NODE_ID") or os.environ.get("EVERSPARK_CONCEPT_INSTANCE_ID"):
        remote_port = int(os.environ.get("EVERSPARK_REMOTE_ORCHESTRATOR_PORT", str(backend_port + 2)))
        os.environ["EVERSPARK_ORCHESTRATOR_URL"] = f"http://127.0.0.1:{remote_port}"
        os.environ.pop("EVERSPARK_ARCHON_ONLY", None)
    else:
        os.environ["EVERSPARK_ARCHON_ONLY"] = "1"


def start(*, stop_event=None, ready_callback=None) -> int:
    _load_local_settings()
    sys.path.insert(0, str(REPO_ROOT))
    from Archon.Gate.CLI.windows_console import disable_quick_edit
    disable_quick_edit()
    from Archon.Gate.control_server import ControlServer
    from Archon.Steward.vast_instances import VastInstances
    from Archon.Steward.vast_offers import VastOffers
    from Archon.Vault.windows_credentials import WindowsCredentialStore
    from Archon.Vault.ssh_identity import SSHIdentity
    from Archon.Steward.DeploymentManager.manager import DeploymentManager
    from Archon.Steward.DeploymentManager.image import ImageDeploymentManager
    from Archon.Steward.DeploymentManager.audio import AudioDeploymentManager
    from Archon.Steward.NodeManager import NodeManager
    from Archon.Steward.DeploymentManager.providers.network import tailscale_ip
    from Archon.Steward.DeploymentManager.providers.vast_nodes import VastNodes
    from Archon.Steward.DeploymentManager.providers.migration import migrate_legacy_registry
    from Archon.Gate.forge_bindings import ForgeBindings
    from Archon.Portal.app import LOG_DIR, LOG_FILE, WebUIServer, get_logger, load_settings

    logger = get_logger("webui", LOG_FILE)
    backend_logger = get_logger("gate", LOG_DIR / "archon/gate.log")
    backend = None
    portal = None
    worker = None
    portal_worker = None
    remote_server = None
    remote_worker = None
    bridge = None
    nodes = None
    forge_bindings = None
    try:
        backend_port = int(os.environ.get("EVERSPARK_ORCHESTRATOR_PORT", "8765"))
        store = WindowsCredentialStore() if sys.platform == "win32" else None
        machines = VastInstances(store) if store else None
        offers = VastOffers(store) if store else None
        auth_key = os.environ.pop("EVERSPARK_TAILSCALE_AUTH_KEY", "")
        node_state = Path(os.environ.get("EVERSPARK_NODE_STATE", str(
            Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "EverSpark" / "nodes.json")))
        bindings_path = node_state.with_name("vast_node_bindings.json")
        migrate_legacy_registry(node_state, bindings_path, WindowsCredentialStore if store else None)
        node_host = os.environ.get("EVERSPARK_NODE_HOST")
        if not node_host:
            node_host = tailscale_ip() if machines and (auth_key or bindings_path.is_file()) else "127.0.0.1"
        nodes = NodeManager(node_host, int(os.environ.get("EVERSPARK_NODE_PORT", "8766")),
                            state_path=node_state, credential_factory=WindowsCredentialStore if store else None)
        nodes.start()
        bridge = VastNodes(nodes, bindings_path, auth_key) if machines else None
        deployments = DeploymentManager(machines, SSHIdentity(), bridge=bridge) if machines else None
        image_deployments = ImageDeploymentManager(
            machines, bridge, state_path=node_state.with_name("image_deployments.json")) if machines else None
        audio_deployments = AudioDeploymentManager(
            machines, bridge, state_path=node_state.with_name("audio_deployments.json")) if machines else None
        backend = ControlServer(("127.0.0.1", backend_port), machines, offers, deployments,
                                image_deployments=image_deployments, node_manager=nodes,
                                audio_deployments=audio_deployments, logger=backend_logger)
        control_url = f"http://127.0.0.1:{backend.server_port}"
        os.environ["EVERSPARK_ARCHON_CONTROL_URL"] = control_url
        if os.environ["EVERSPARK_ORCHESTRATOR_URL"] == f"http://127.0.0.1:{backend_port}":
            os.environ["EVERSPARK_ORCHESTRATOR_URL"] = control_url
        forge_bindings = ForgeBindings(nodes, node_state.with_name("forge_bindings.json"),
            f"http://127.0.0.1:{backend.server_port}")
        backend.forge_bindings = forge_bindings
        forge_bindings.restore()
        if not forge_bindings.bindings and (os.environ.get("EVERSPARK_CONCEPT_NODE_ID") or os.environ.get("EVERSPARK_CONCEPT_INSTANCE_ID")):
            for path in ("Archon/Orchestrator", "Legate/Forge", "Legate/Forge/ConceptForge",
                         "Legate/Forge/ImageForge", "Legate/Forge/ConceptForge/Memory",
                         "Aegis/Logging"):
                sys.path.insert(0, str(REPO_ROOT / path))
            from Archon.Vault.runtime_config import load_config
            from Archon.Gate.application import GateApplication
            from orchestrator.core.server import OrchestratorServer
            remote_port = int(os.environ.get("EVERSPARK_REMOTE_ORCHESTRATOR_PORT", str(backend_port + 2)))
            remote_server = OrchestratorServer(("127.0.0.1", remote_port),
                                               GateApplication(load_config()))
            os.environ["EVERSPARK_ORCHESTRATOR_URL"] = f"http://127.0.0.1:{remote_server.server_port}"
        portal = WebUIServer(load_settings(), logger, forge_bindings=forge_bindings)
        worker = threading.Thread(target=backend.serve_forever, name="archon-backend", daemon=True)
        worker.start()
        if remote_server:
            remote_worker = threading.Thread(target=remote_server.serve_forever,
                                             name="archon-orchestrator", daemon=True)
            remote_worker.start()
        backend_logger.ok("server.ready", "Archon control backend is ready", port=backend.server_port)
        logger.ok("server.ready", "Archon Portal is ready", port=portal.server_port)
        print(f"Archon backend: http://127.0.0.1:{backend.server_port}", flush=True)
        print(f"Portal: http://127.0.0.1:{portal.server_port}", flush=True)
        if stop_event is None:
            portal.serve_forever()
        else:
            portal_worker = threading.Thread(target=portal.serve_forever,
                                             name="archon-portal", daemon=True)
            portal_worker.start()
            if ready_callback:
                ready_callback(f"http://127.0.0.1:{portal.server_port}")
            stop_event.wait()
    except KeyboardInterrupt:
        pass
    except (OSError, ValueError, RuntimeError) as exc:
        print(f"Archon startup failed: {exc}", file=sys.stderr)
        return 1
    finally:
        if portal is not None:
            if portal_worker is not None:
                portal.shutdown()
                portal_worker.join(timeout=5)
            portal.server_close()
        if forge_bindings is not None:
            forge_bindings.close()
        if remote_server is not None:
            if remote_worker is not None:
                remote_server.shutdown()
                remote_worker.join(timeout=5)
            remote_server.server_close()
        if backend is not None:
            if worker is not None:
                backend.shutdown()
                worker.join(timeout=5)
            backend.server_close()
        if nodes is not None:
            nodes.close()
        backend_logger.close()
        logger.close()
    return 0


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if args[:1] == ["configure"]:
        sys.path.insert(0, str(REPO_ROOT))
        from Archon.Vault.import_config import main as configure
        return configure(args[1:])
    if args[:1] == ["archon"]:
        args = args[1:]
    if args == ["start"]:
        return start()
    print("Usage: everspark archon start | everspark configure [--from DIRECTORY]")
    return 0 if args in ([], ["help"], ["--help"]) else 2


if __name__ == "__main__":
    raise SystemExit(main())
