# Tests

Unit, integration, startup, and migration verification.

- `Runtime/Logging` verifies structured logs and retention.
- `Runtime/Managed` verifies safe PID identity and managed process lifecycle.
- `Runtime/Hardware` and `Runtime/System` verify host discovery, GPU assignment,
  and automatic PyTorch compatibility-profile selection.
- `Infrastructure` verifies local defaults, the managed Cloudflare lifecycle,
  selective R2 model discovery, byte progress, and safe Ollama manifest restoration.
- `Configuration` verifies private configuration import, validation, and normalization.
- `Launcher` verifies routing, initialization, diagnostics, and installation.
- `Orchestrator` verifies configuration, Unicode handling, batching, workflows,
  and the local HTTP API.
- `Memory` verifies SQLite persistence, history limits, and clearing.
- `ConceptForge` verifies Character Subject schema validation, protected
  updates, compilation, provider output, and CLI commands.
- `WebUI` verifies static delivery, subject proxy routes, subject-aware task
  submission, exact result polling, image proxy safety, output ZIP downloads,
  and runtime status.
