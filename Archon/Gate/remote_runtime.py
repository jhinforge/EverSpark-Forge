"""Compose the existing Orchestrator with explicitly selected remote Nodes."""
import sys
import threading
from pathlib import Path


class RemoteRuntime:
    def __init__(self, server):
        self.server = server
        self.url = f"http://127.0.0.1:{server.server_port}"
        self.thread = threading.Thread(target=server.serve_forever, daemon=True,
                                       name="archon-remote-orchestrator")
        self.thread.start()

    def busy(self):
        orchestrator = self.server.orchestrator
        with orchestrator._task_jobs_lock:
            queued = any(job["status"] in {"queued", "running"}
                         for job in orchestrator._task_jobs.values())
        return queued or orchestrator._task_lock.locked()

    def close(self):
        self.server.shutdown()
        self.thread.join(5)
        self.server.server_close()


def create_runtime(bindings, control_url, config_loader=None):
    # Import only after both remote endpoints have been selected. Control-only
    # startup continues to require no local Forge services or execution setup.
    root = Path(__file__).resolve().parents[2]
    for relative in ("Archon/Orchestrator", "Legate/Forge", "Legate/Forge/ConceptForge",
                     "Legate/Forge/ImageForge", "Legate/Forge/ConceptForge/Memory", "Aegis/Logging"):
        path = str(root / relative)
        if path not in sys.path:
            sys.path.insert(0, path)
    from orchestrator.config.config import load_config
    from orchestrator.core.orchestrator import Orchestrator
    from orchestrator.core.server import OrchestratorServer
    config = (config_loader or load_config)()
    config["remote_nodes"] = {f"{forge}_node_id": node_id for forge, node_id in bindings.items()}
    config["remote_nodes"]["control_url"] = control_url
    config["concept_forge"]["provider"] = "ollama"
    return RemoteRuntime(OrchestratorServer(("127.0.0.1", 0), Orchestrator(config)))
