# EverSpark Forge

EverSpark Forge is a personal AI infrastructure and orchestration system.
It is designed to turn user intent into reusable, structured AI workflows
without binding those workflows to one machine, one model provider, or one
execution backend.

> [!IMPORTANT]
> The source code is available for testing. A versioned public release has not
> been published yet.

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

Users with existing private configuration can upload `.env` or `env.txt`, a
Cloudflare `<UUID>.json` credential, and an optional `rclone.conf` into the
tracked but ignored `Configuration/Import/` inbox, then normalize and validate
them before setup:

```bash
./everspark configure
./everspark setup
./everspark doctor
./everspark start
```

`--from <directory>` remains available for advanced or external upload paths.

The input files remain untouched. Cloudflare joins the managed lifecycle only
when its backend is enabled. When the rclone storage backend is explicitly
enabled, setup installs rclone automatically; merely importing `rclone.conf`
does not activate remote storage or install anything.

When rclone storage is enabled, the Runtime page can scan and selectively
download remote Checkpoints, diffusion models, LoRAs, and Ollama models. Image
resources are written only into `Data/Models/ImageForge`; Concept resources are
restored from Ollama manifests and content-addressed blobs into
`Data/Models/ConceptForge/Ollama`. Legacy ComfyUI program files and Ollama
identity keys are never restored. Active transfers show bytes, percentage,
speed, ETA, and file counts, and the page can resume monitoring after refresh.

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
The setup process also selects a pinned PyTorch 2.9.1 CUDA profile from the
detected GPU architecture and NVIDIA driver capability; users do not choose a
CUDA wheel family manually. A runtime-profile change rebuilds only the managed
ComfyUI virtual environment and retains models, workflows, configuration,
outputs, and memory.
The WebUI can select installed Ollama models, ComfyUI checkpoints, VAE models, and
registered API Format workflows. Standard SDXL/Illustrious workflows can add
multiple LoRAs per request without modifying the bundled workflow file.
The Gallery can package the complete `Data/Outputs` tree into a timestamped ZIP
and download it through the same WebUI connection.

The Runtime page also includes a direct model downloader that works without R2.
Users can paste a public model URL, choose the Image Forge model type, or install
a Concept Forge GGUF and have it registered with Ollama automatically. Downloads
show byte progress, speed, ETA, cancellation, and retry state; incomplete files
are never exposed to the model scanners.

The Storage page discovers nested remote model directories from configured
rclone roots. Users can save manual paths when directory names differ and select
physical upload destinations when multiple paths match. Directly downloaded
image models go back to the chosen image model directory; GGUF source files go
to a separately discoverable GGUF directory. `EVERSPARK_BACKUP_REMOTE` optionally
sets a writable data backup location; by default the first image source bucket
uses an `everspark-backups` prefix. Local output files can be uploaded there.
Character JSON and SQLite are uploaded and restored as verified batches. Restore
saves the previous local data in `Data/Recovery` before replacing it.

## Repository status

- [x] Public repository created
- [x] Initial names and module boundaries defined
- [x] Local-first configuration contract added
- [x] Configuration, logging, storage, and network foundation migrated
- [x] Portable private configuration import and Tunnel lifecycle implemented
- [x] Launcher foundation, initialization, and diagnostics implemented
- [x] Existing v0.1 execution chain migrated across module boundaries
- [x] Concept Forge Character Subject v1 schema implemented
- [x] Working Memory v0 persistence migrated
- [x] Managed default model catalog and installer implemented
- [x] Image checkpoint discovery and deterministic fallback implemented
- [x] Manual workflow, Checkpoint, LLM, and standard LoRA selection implemented
- [x] Managed ComfyUI/Ollama installation and service lifecycle implemented
- [x] Character Subject structured state and revision history implemented
- [x] Conversation-derived automatic current subject implemented
- [ ] Episodic memory implemented
- [x] WebUI subject, generation, gallery, and runtime workflow implemented
- [x] Direct Image Forge and Concept Forge model downloads implemented
- [x] Manual model, output, and Memory snapshot uploads implemented
- [ ] First public release

## License

EverSpark Forge is licensed under the GNU Affero General Public License,
version 3 only (AGPL-3.0-only). See [LICENSE](LICENSE) for the full terms.

Models, workflows, and other third-party resources retain their own licenses.
