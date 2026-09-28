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
- Select the default ComfyUI engine or install the optional Diffusers plugin in Forge; save an engine default without editing `.env`.
- Select a registered ComfyUI workflow and image models, and choose an installed Ollama model or a tested OpenAI Compatible connection under **Model services**.
- Add one or more standard LoRAs with independent MODEL and CLIP strengths.
- Submit image tasks in the background, poll planning status, then track their
  exact Image Forge prompt identifiers without holding an HTTP request open.
- Display current results and recent Image Forge history, and download the
  complete output directory as a timestamped ZIP archive.
- Show local Orchestrator, Image Forge, and logging readiness.
- Explain missing first-run services without requiring R2 or Cloudflare.
- Scan optional R2 model roots and start selective background downloads with
  live byte progress, transfer speed, ETA, and refresh recovery.
- Download Checkpoints, diffusion models, LoRAs, VAEs, and GGUF language models from
  direct public HTTP URLs without enabling R2. Partial files remain isolated,
  interrupted transfers can be retried, and GGUF files are registered with
  Ollama automatically.

## Boundaries

The browser never connects directly to Orchestrator or an Image Forge engine.
`WebUI/app.py` exposes a same-origin proxy and does not store
subject state itself. Users never fill the internal JSON template or choose a
subject ID. Character identity remains in Memory; scene, pose,
camera, and background remain request-level task input.

Resource choices are discovered through Orchestrator. Image models and
workflows come from the selected drawing engine; language models come from
Ollama or an explicitly configured OpenAI Compatible service. The latter uses
non-streaming Chat Completions, with a manually entered model ID. Connections
are saved in `Data/Configuration/ConceptForge/connections.json`; stored keys
are not returned in WebUI responses or character data ZIPs. Selections are attached to
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
- `EVERSPARK_IMAGE_BACKEND` (optional initial drawing tool; Forge saves later default choices)
- `EVERSPARK_WEBUI_REQUEST_TIMEOUT`
- `EVERSPARK_OUTPUT_DIR`
