# Tests

Unit, integration, startup, and migration verification.

- `Runtime/Logging` verifies structured logs and retention.
- `Runtime/Hardware` and `Runtime/System` verify host discovery.
- `Infrastructure` verifies local-mode defaults.
- `Launcher` verifies routing, initialization, diagnostics, and installation.
- `Orchestrator` verifies configuration, Unicode handling, batching, workflows,
  and the local HTTP API.
- `Memory` verifies SQLite persistence, history limits, and clearing.
- `ConceptForge` verifies Character Subject schema validation, protected
  updates, compilation, provider output, and CLI commands.
