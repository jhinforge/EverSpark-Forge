# EverSpark Forge command reference (v0.1)

This reference describes the current `./everspark` entry point, its options, and their effects. Run these commands from the **repository root on cloud Linux**. The unprefixed `everspark` form works after `bash Launcher/install.sh` adds the launcher to your user PATH. Running the stack locally on Windows has not been verified.

For deployment steps see [Getting started](Getting-Started.md), for private files see [Configuration](Configuration.md), and for data locations see [Runtime and data](Runtime-and-Data.md). Run `./everspark help` for the top-level list. Square brackets indicate optional arguments; angle brackets are placeholders to replace, not characters to type literally.

## 1. Initialization, configuration, and installation

| Command | What it does |
| --- | --- |
| `./everspark help` | Lists top-level commands. Running `./everspark` without arguments does the same. Some options appear only in a subcommand's `--help`. |
| `./everspark init` | Creates `Data/Logs`, `Data/Outputs`, `Data/Memory`, model and runtime directories, and the configuration import directory. It does not install runtimes, download models, or create `.env`. It writes an initialization log. |
| `./everspark configure` | Reads `env.txt` or `.env` from `Configuration/Import/`, validates it, and imports it as the root `.env`. It can import rclone and Named Tunnel credentials. **Running it again replaces `.env` rather than appending settings.** Uploaded source files remain. Default local mode does not need it. |
| `./everspark configure --from <directory>` | Reads private files from another directory. Use `--env <file>` to select one of two conflicting environment files; `--json` prints a machine-readable result. |
| `./everspark setup --plan` | Displays planned managed runtimes, model sources, and local destinations **without installing or downloading**. Run this before first deployment. |
| `./everspark setup` | Creates runtime directories, installs managed ComfyUI/Ollama and Python environments, downloads manifest starter models, and imports the Concept model into Ollama. Requires network and disk space; installing optional backends can require root. Address a failure and rerun it. |
| `./everspark doctor` | Checks Linux platform, base commands, GPU visibility, and enabled backend settings. With rclone, it also checks remote model roots. It neither generates an image nor proves every model and workflow is usable. |

Optional `setup` switches:

| Option | Meaning |
| --- | --- |
| `--models all\|concept\|image` | Download all, Concept Forge, or Image Forge starter models from the manifest; default `all`. Managed runtimes still install. |
| `--skip-models` | Prepare runtimes without starter downloads or Concept import. A running service may still lack generation resources. |
| `--skip-concept-import` | Download the Concept GGUF without importing it into Ollama, for example if Ollama will be connected later. |
| `--plan` | Print only the plan; combined with `--skip-models`, it omits the model plan. |

Run `./everspark setup --help` for installation options. See [Configuration](Configuration.md) for private file formats and backend requirements.

## 2. Service management

`[target]` is `all`, `concept`, `image`, `orchestrator`, or `webui`; omitting it selects `all`. `concept` corresponds to Ollama and `image` to ComfyUI. A full start goes Concept Forge → Image Forge → Orchestrator → WebUI; a full stop uses the reverse order.

| Command | What it does |
| --- | --- |
| `./everspark start [target]` | Starts managed services and waits for health checks. `start image`, for example, starts only Image Forge and does not install models. Starting all or WebUI also handles an **explicitly enabled** Named Tunnel and prints access instructions; it does not automatically create a temporary sharing link. |
| `./everspark status [target]` | Checks processes and health without starting services. `running` means a managed healthy process, `external` a healthy service started elsewhere, `unhealthy` a managed process failing health checks, and `stopped` unavailable. For all or WebUI it also checks Tunnel and temporary sharing status. |
| `./everspark restart [target]` | Stops and starts the selected managed services. For all or WebUI it handles the configured Named Tunnel and prints access instructions. Unlike `stop`, it **does not explicitly close** an active temporary `share` link. |
| `./everspark stop [target]` | Stops launcher-managed processes; it does not terminate a healthy service detected as `external`. Stopping all or WebUI also closes an active `share` link and the configured Named Tunnel. |

For status records and logs see [Runtime and data](Runtime-and-Data.md). To restart only the image backend:

```bash
./everspark status image
./everspark restart image
```

## 3. WebUI access and temporary sharing

| Command | What it does |
| --- | --- |
| `./everspark access` | **Only displays** the cloud machine's local address, a discoverable SSH forwarding command, and any currently active temporary URL. It does not start services, create a link, or connect over SSH. `--json` prints structured output. |
| `./everspark share` or `./everspark share start` | Checks local WebUI health, then starts a temporary Cloudflare link and prints a `https://*.trycloudflare.com` URL. Repeating it reuses the live link. Requires no `.env`, SSH key, or Cloudflare account, but does need outbound connectivity; automatic installation of missing `cloudflared` requires root. |
| `./everspark share status` | Reports an active temporary link without creating one. |
| `./everspark share stop` | Closes the launcher-managed temporary link without stopping WebUI. `./everspark stop` and `./everspark stop webui` also close it. A future sharing session may get a different URL. |

**The temporary link exposes a WebUI that currently has no login protection. Anyone with the URL can operate it.** Start it explicitly for short tests or demos and close it afterward. SSH forwarding and a credentialed Named Tunnel on your own hostname are separate access choices. See [Getting started](Getting-Started.md).

## 4. Manifest starter models

The `models` command handles **starter models** in `Runtime/Models/default_models.json`. It is separate from the WebUI Storage page's arbitrary public URL downloader and rclone library scans.

| Command | What it does |
| --- | --- |
| `./everspark models plan` | Displays manifest model sources, revisions, licenses, and local targets; does not download them. |
| `./everspark models status` | Checks whether manifest targets exist and are nonempty; prints JSON. This is not a list of all installed models on the machine. |
| `./everspark models download` | Downloads selected manifest models into `Data/Models/`. It needs `huggingface_hub`, normally prepared by `setup`. Skips an existing nonempty target. **Does not import models into Ollama automatically.** |
| `./everspark models import-concept` | Imports the manifest Concept GGUF with `ollama create`; requires the model file and an available Ollama installation. Writes `Data/Runtime/Models/ConceptForge.Modelfile`. |

Use `--models all|concept|image` to filter `plan`, `status`, or `download`. Advanced users can override the manifest with `--manifest <JSON-path>`. `import-concept` still uses the manifest's Concept model, not a different model selected by `--models`. `setup` combines runtime installation, downloading, and optional import; standalone `models download` does not install ComfyUI/Ollama.

## 5. Log status and maintenance

| Command | What it does |
| --- | --- |
| `./everspark logs status` | Reports managed log status as JSON; does not rotate files. |
| `./everspark logs rotate --dry-run` | Previews which managed logs would be rotated, renamed, or removed without applying those actions. |
| `./everspark logs rotate` | **Applies** rotation and retention. It can truncate the current log after copying it and delete old rotated files exceeding count or age limits. Export logs first if you need failure evidence. |

`status` shows service log paths. Raw logs default to `Data/Logs/`; `EVERSPARK_LOG_DIR` can change that. See [Troubleshooting](Troubleshooting.md) for diagnosis order.

## 6. Module entry points (development and isolated diagnosis)

For ordinary use, manage services with the top-level `start|stop|restart|status` commands. The following entry points have narrower uses.

| Command | What it does |
| --- | --- |
| `./everspark image start|stop|restart|status` | The corresponding managed Image Forge action, equivalent to `./everspark start|stop|restart|status image`. |
| `./everspark concept new <subject_id> <display_name>` | Creates blank Character Subject v1 JSON and prints it; **does not save a file or select it for a conversation**. |
| `./everspark concept validate <file>` | Reads and validates a character subject JSON file, printing the result without changing the file. |
| `./everspark concept compile <file>` | Validates a subject and prints positive and negative prompt fragments; does not submit an image task. |
| `./everspark orchestrator start` | Starts the Orchestrator server process directly for isolated diagnosis; it is not the full managed startup sequence of `./everspark start`. |
| `./everspark webui start` | Starts the WebUI server process directly for isolated diagnosis; does not start other modules. |
| `./everspark orchestrator console` | Opens an interactive terminal that sends requests to a running Orchestrator. `/history` reads current session context, `/subject <id>` attaches a subject, `/subject clear` detaches it, and `/exit` quits. **`/clear` or `/new` clears the current session context.** |

For supported module subcommands run `./everspark image help`, `./everspark concept --help`, `./everspark orchestrator help`, or `./everspark webui help`.
