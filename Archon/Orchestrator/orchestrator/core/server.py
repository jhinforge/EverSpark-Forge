"""Compatibility launcher for Gate's existing HTTP API."""
from Archon.Gate.application_server import OrchestratorServer, RequestHandler, main

if __name__ == "__main__":
    raise SystemExit(main())
