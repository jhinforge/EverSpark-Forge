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
./everspark setup --plan
./everspark setup
./everspark start
```

No `.env` file is needed for the default local mode. `setup` installs pinned
ComfyUI and Ollama runtimes, downloads the default models, imports Concept
Forge, and connects the managed Image Forge model directory. `start` launches
Concept Forge, Image Forge, Orchestrator, and WebUI in dependency order.

Open `http://127.0.0.1:8780` locally. On a Vast.ai Pod, `start` reads the
platform-provided public IP and mapped SSH port and prints the complete tunnel
command to run on your local computer. Use `./everspark access` to print it
again. On other Pod platforms, set `EVERSPARK_SSH_HOST` and
`EVERSPARK_SSH_PORT`; the WebUI stays bound to localhost by default.

The managed model foundation currently selects Qwen3 4B GGUF Q4_K_M for
Concept Forge and Illustrious XL v1.0 for Image Forge. Inspect the download
plan with `./everspark setup --plan`; run `./everspark setup` only when you are
ready to download both models (roughly 9.5 GB total). A public, LoRA-free
Illustrious API Format workflow is included for the initial generation path.

## Repository status

- [x] Public repository created
- [x] Initial names and module boundaries defined
- [x] Local-first configuration contract added
- [x] Configuration, logging, storage, and network foundation migrated
- [x] Launcher foundation, initialization, and diagnostics implemented
- [x] Existing v0.1 execution chain migrated across module boundaries
- [x] Concept Forge Character Subject v1 schema implemented
- [x] Working Memory v0 persistence migrated
- [x] Managed default model catalog and installer implemented
- [x] Image checkpoint discovery and deterministic fallback implemented
- [x] Managed ComfyUI/Ollama installation and service lifecycle implemented
- [x] Character Subject structured state and revision history implemented
- [x] Conversation-derived automatic current subject implemented
- [ ] Episodic memory implemented
- [x] WebUI subject, generation, gallery, and runtime workflow implemented
- [ ] First public release

## License

No open-source license has been selected yet. Until a license is added, all
rights are reserved by the repository owner.
