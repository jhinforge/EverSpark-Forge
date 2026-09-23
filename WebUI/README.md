# EverSpark WebUI

The local-first user interface for character subjects, scene generation,
image results, and runtime readiness.

## Run

Start Orchestrator first, then start the WebUI:

```bash
./everspark orchestrator start
./everspark webui start
```

Open `http://127.0.0.1:8780`.

The WebUI uses only the Python standard library and the repository logging
module. It does not require Node.js, a package installation, or a personal
configuration file.

## Current features

- Discuss a character naturally with Concept Forge.
- Automatically extract and revise one current Character Subject per conversation.
- Inspect immutable subject revision documents.
- Switch the same conversation between discussion and image generation.
- Combine the automatically maintained identity with a temporary scene.
- Select a registered workflow, Checkpoint, and installed Ollama model.
- Add one or more standard LoRAs with independent MODEL and CLIP strengths.
- Submit image tasks and track their exact Image Forge prompt identifiers.
- Display current results and recent Image Forge history, and download the
  complete output directory as a timestamped ZIP archive.
- Show local Orchestrator, Image Forge, and logging readiness.
- Explain missing first-run services without requiring R2 or Cloudflare.
- Scan optional R2 model roots and start selective background downloads with
  live byte progress, transfer speed, ETA, and refresh recovery.
- Download Checkpoints, diffusion models, LoRAs, and GGUF language models from
  direct public HTTP URLs without enabling R2. Partial files remain isolated,
  interrupted transfers can be retried, and GGUF files are registered with
  Ollama automatically.

## Boundaries

The browser never connects directly to Orchestrator or the configured Image
Forge adapter. `WebUI/app.py` exposes a same-origin proxy and does not store
subject state itself. Users never fill the internal JSON template or choose a
subject ID. Character identity remains in Memory; scene, pose,
camera, and background remain request-level task input.

Resource choices are discovered through Orchestrator. Checkpoints and LoRAs
come from the configured ComfyUI adapter, LLM names come from Ollama, and
workflows come from the Image Forge registry. The selections are attached to
each request and do not rewrite repository workflow files.

Direct image downloads currently accept `.safetensors` and `.ckpt`; Concept
Forge downloads accept `.gguf`. The optional filename is useful for signed or
API-style links that do not end with a model filename. Direct downloads reject
local/private network destinations and never expose URL query strings through
the job API.

Default endpoints can be overridden when needed:

- `EVERSPARK_WEBUI_HOST`
- `EVERSPARK_WEBUI_PORT`
- `EVERSPARK_ORCHESTRATOR_URL`
- `EVERSPARK_IMAGE_FORGE_URL`
- `EVERSPARK_WEBUI_REQUEST_TIMEOUT`
- `EVERSPARK_IMAGE_FORGE_TIMEOUT`
- `EVERSPARK_OUTPUT_DIR`
