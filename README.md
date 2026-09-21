# EverSpark Forge

EverSpark Forge is a personal AI infrastructure and orchestration system.
It is designed to turn user intent into reusable, structured AI workflows
without binding those workflows to one machine, one model provider, or one
execution backend.

> [!IMPORTANT]
> This repository is currently being initialized. The one-command launcher is
> available for initialization, diagnostics, and the migrated Orchestrator,
> but this is not yet a finished release.

## Product goal

The intended user experience is:

1. Clone the repository.
2. Run one launcher command.
3. Let EverSpark create its local directories and default configuration.
4. Open the WebUI and start using the system.

The default installation will require no R2 or Cloudflare configuration.
External storage and public networking will remain optional integrations.

## Default behavior

- Local storage is enabled by default.
- The WebUI binds to localhost by default.
- R2 integration is disabled by default.
- Cloudflare Tunnel integration is disabled by default.
- User secrets and runtime data are never committed to the repository.
- If an optional integration is explicitly enabled but misconfigured,
  EverSpark must stop with an actionable error instead of silently falling
  back to another backend.

## Architecture

| Module | Responsibility |
| --- | --- |
| **Orchestrator** | Central routing, session coordination, and task execution |
| **Concept Forge** | Discussion, structured intent, schema validation, and prompt compilation |
| **Memory** | Working, episodic, and structured state memory |
| **Image Forge** | Image workflow execution through pluggable backends such as ComfyUI |
| **EverSpark WebUI** | The user-facing conversation, generation, and runtime interface |
| **Runtime** | Health checks, processes, hardware discovery, and logging |
| **Infrastructure** | Optional storage and network integrations |
| **Launcher** | Installation, initialization, configuration validation, and startup |

Top-level module names describe EverSpark capabilities. External tools such as
ComfyUI, Ollama, R2, and Cloudflare belong inside adapters, providers, or
backends rather than defining the architecture themselves.

See [Docs/Architecture.md](Docs/Architecture.md) for the initial module
boundaries and data flow.

## Configuration model

The initial configuration contract is defined in
[Configuration/default.yaml](Configuration/default.yaml).

Configuration precedence will be:

1. Command-line arguments
2. Environment variables
3. User configuration
4. Repository defaults

Copy `.env.example` to `.env` only when optional integrations are needed.

## Current launcher

```bash
git clone https://github.com/jhinforge/EverSpark-Forge.git
cd EverSpark-Forge
./everspark init
./everspark doctor
```

No `.env` file is needed for the default local mode. The migrated Orchestrator
can be started with `./everspark orchestrator start`; generation also requires
the selected Ollama model, ComfyUI environment, and an API Format workflow.

## Repository status

- [x] Public repository created
- [x] Initial names and module boundaries defined
- [x] Local-first configuration contract added
- [x] Configuration, logging, storage, and network foundation migrated
- [x] Launcher foundation, initialization, and diagnostics implemented
- [x] Existing v0.1 execution chain migrated across module boundaries
- [x] Concept Forge Character Subject v1 schema implemented
- [x] Working Memory v0 persistence migrated
- [x] Character Subject structured state and revision history implemented
- [ ] Episodic memory implemented
- [ ] WebUI conversation workflow implemented
- [ ] First public release

## License

No open-source license has been selected yet. Until a license is added, all
rights are reserved by the repository owner.
