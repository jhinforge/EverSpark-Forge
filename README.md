# EverSpark Forge · v0.1

EverSpark Forge treats compute environments as disposable, while preserving workflows, configuration, and user-owned data as persistent state.

EverSpark Forge is a personal AI infrastructure and orchestration system.
It is designed to turn user intent into reusable, structured AI workflows
without binding those workflows to one machine, one model provider, or one
execution backend.

**v0.1 is the first public source release.** EverSpark Forge can be installed
from this repository on a supported Linux GPU machine. Models, configuration,
generated outputs, and other personal data are managed separately from the
source code.

## Product goal

The basic workflow is:

1. Clone the repository.
2. Run one launcher command.
3. Let EverSpark create its local directories and default configuration.
4. Open the WebUI and start using the system.

The default installation requires no R2 or Cloudflare configuration. External
storage and public networking are optional integrations.

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

See [Docs/Architecture.md](Docs/Architecture.md) for the module
boundaries and data flow.

## Configuration model

The default configuration is defined in
[Configuration/default.yaml](Configuration/default.yaml).

Optional integrations use private environment settings; see
[Configuration/README.md](Configuration/README.md). Copy `.env.example` to
`.env` only when those integrations are needed.

## Quick start

中文首次运行指南：[Docs/Getting-Started.zh-CN.md](Docs/Getting-Started.zh-CN.md)。
中文配置指南：[Docs/Configuration.zh-CN.md](Docs/Configuration.zh-CN.md)。
中文运行与数据指南：[Docs/Runtime-and-Data.zh-CN.md](Docs/Runtime-and-Data.zh-CN.md)。
中文排障指南：[Docs/Troubleshooting.zh-CN.md](Docs/Troubleshooting.zh-CN.md)。
中文架构指南：[Docs/Architecture.zh-CN.md](Docs/Architecture.zh-CN.md)。

The managed runtime targets Linux x86_64 with an NVIDIA GPU. Setup needs an
internet connection for runtimes and models; run the plan first to review the
downloads without changing the machine.

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

When rclone storage is enabled, the Storage page can scan and selectively
download remote checkpoints, diffusion models, LoRAs, VAEs, and Ollama models. Image
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

The default setup installs a usable Concept Forge model and an Image Forge
checkpoint; both can be replaced with compatible models. A public, LoRA-free
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

The Storage page also includes a direct model downloader that works without R2.
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

## In v0.1

- Discuss a character in the WebUI, reuse an existing subject, and generate
  images through Concept Forge, Orchestrator, and Image Forge.
- Select installed workflows, language models, checkpoints, VAEs, and LoRAs.
- Download models by direct URL or from optional rclone storage; upload models
  to mapped remote directories and back up outputs, character data, and memory.
- Inspect runtime health, manage services through `./everspark`, and export the
  output folder from the Gallery.

Working and structured character memory are available in v0.1. Episodic memory
is planned for a later release.

## License

EverSpark Forge is licensed under the GNU Affero General Public License,
version 3 only (AGPL-3.0-only). See [LICENSE](LICENSE) for the full terms.

Models, workflows, and other third-party resources retain their own licenses.
