# EverSpark Forge architecture (v0.1)

EverSpark Forge routes discussion and generation through a coordinator to separate concept processing and image execution modules. This path works in v0.1. The modules are designed to allow replacement, but **the implemented concept provider is Ollama and the image adapter is ComfyUI**. This guide describes present code and data flow without treating planned capabilities as implemented.

## 1. System boundaries

| Layer | Current responsibility | Main code |
| --- | --- | --- |
| WebUI | Browser interaction, same-origin API proxy, results and images, runtime status | `WebUI/` |
| Orchestrator | Sessions and request routing, generation tasks, resource choices, download and backup task entry points | `Orchestrator/` |
| Concept Forge | Language model interaction, character subject creation and validation, prompt compilation | `ConceptForge/` |
| Memory | Conversation history, character associations and revisions, prompt documents, task records | `Memory/`; data in `Data/Memory/` and `Data/Subjects/` |
| Image Forge | Read API Format workflows, populate prompts and parameters, submit image tasks | `ImageForge/` |
| Runtime / Launcher | Install and launch managed services, discover hardware, check processes and health, log output | `Runtime/`, `Launcher/`, root `everspark` |
| Infrastructure | Optional rclone storage and Cloudflare Tunnel; unnecessary in local mode | `Infrastructure/` |

ComfyUI and Ollama live in the managed runtime, rather than naming EverSpark modules. Models, private configuration, outputs, and memory are outside the published source. See [Runtime and data](Runtime-and-Data.md) for paths and migration.

## 2. Request flow

```mermaid
sequenceDiagram
    participant W as WebUI service
    participant O as Orchestrator
    participant C as Concept Forge
    participant M as Memory
    participant I as Image backend
    W->>O: Discussion message and session ID
    O->>M: Read bounded history and current subject
    O->>C: Reply and update character subject
    O->>M: Save conversation and subject revision
    W->>O: Scene and resource choices
    O->>C: Prepare character and prompt
    O->>I: Submit workflow with independent seeds
    I-->>O: Return prompt ID
    O->>M: Save prompt and task records
    W->>I: Poll results by prompt ID
    I-->>W: Status and image metadata
```

The browser talks to WebUI alone. The WebUI service proxies discussion, generation, character, and storage requests to Orchestrator. For result polling and image retrieval, **the WebUI service** contacts the configured Image Forge backend and returns data through same-origin endpoints to the browser. In v0.1 the image backend is ComfyUI, while Ollama sits behind the Concept Forge provider. The sequence summarizes responsibilities; validation and failure paths also occur during subject updates, prompt creation, and database writes.

### Discussion and character subjects

Each conversation has one current character subject. Orchestrator obtains bounded conversation history and the current document from Memory, asks Concept Forge to create or revise a subject from the discussion, validates it, and saves a revision. The user can select an existing character for the current conversation in WebUI.

`Character Subject v1` stores **reusable character identity**. Scene, pose, camera, and background belong to an individual request, rather than identity fields. The system separately stores the most recent positive and negative prompt documents; the positive prompt can include the previous scene for subsequent generation context. Those documents are distinct from the identity document.

### Generation and retrieval

Orchestrator reads the current subject and context again. Concept Forge prepares a generation plan and prompts, merging compiled character identity with this request's scene. Image Forge makes a **per-task copy** of a registered API Format workflow, binds available checkpoint, VAE, and LoRA choices, assigns an independent seed to each image in a batch, and submits through the ComfyUI adapter. Selecting resources does not rewrite the workflow file in the repository.

Orchestrator returns the submitted `prompt_id`. WebUI then polls the image backend's task history and displays the result. v0.1 coordinates one Orchestrator request at a time; a batch of images belongs to that request. Recent results appear in Gallery and outputs default to `Data/Outputs/`.

## 3. Configuration and resources

Without a private `.env`, storage and networking are local. Runtime defaults are spread across module configuration files, including `orchestrator/config/default_config.json`. `Configuration/default.yaml` describes the public configuration contract; during this migration, not every service loads from one shared YAML loader. See [Configuration](Configuration.md) for importing `env.txt` / `.env` and enabling optional backends.

Orchestrator aggregates resources for WebUI: registered workflows from Image Forge, checkpoints, VAEs, and LoRAs visible to ComfyUI, and language models from Ollama. Choices accompany individual requests. Execution depends on workflow node structure and model compatibility.

Managed setup prepares a usable starter path but does not require a particular private model. The v0.1 workflow registry executes only API Format JSON; standard LoRA injection depends on supported workflow structure. See [Image Forge](../ImageForge/README.md) for constraints.

## 4. Runtime, storage, and access

`./everspark setup` installs managed runtimes and prepares models. `./everspark start` launches Concept Forge, Image Forge, Orchestrator, and WebUI in order. Runtime checks processes, health endpoints, GPU, and logs; WebUI **Runtime** displays readiness.

Local mode needs no remote storage, and public direct model downloads work independently. When rclone is enabled, Orchestrator uses Infrastructure storage to scan and pull remote models, upload outputs, and create and restore character snapshots. Users initiate uploads; outputs are selected as a whole folder, and character JSON and Memory SQLite are restored as a batch. WebUI binds to localhost by default: use SSH forwarding, or explicitly launch a temporary public entry point with `./everspark share` through `Runtime/Managed/quick_tunnel.py`. Sharing needs no private configuration but WebUI has no login protection. A credentialed Named Tunnel with your own hostname is a separate optional configuration.

## 5. Scope in v0.1

- **Implemented:** shared session for discussion and generation; persistent character subjects and revisions; API Format image workflows; runtime status; local model downloads; optional remote models and data backups.
- **Current limits:** Ollama concept provider and ComfyUI image adapter; one Orchestrator request at a time; registered API Format workflows and supported parameter changes only.
- **Not yet implemented:** automatic episodic memory extraction, retrieval, and consolidation. Other concept providers and image adapters cannot be activated just by changing a setting.

For changes, start with the relevant module README and the request flow above. See [Getting started](Getting-Started.md) for installation and [Troubleshooting](Troubleshooting.md) for failures.
