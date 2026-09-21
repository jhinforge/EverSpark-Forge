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

- Create a versioned Character Subject from a natural-language identity
  description.
- Update an existing subject without replacing unspecified traits.
- Inspect immutable subject revision documents.
- Select a subject and combine its stable traits with a temporary scene.
- Submit image tasks and track their exact Image Forge prompt identifiers.
- Display current results and recent Image Forge history.
- Show local Orchestrator, Image Forge, and logging readiness.
- Explain missing first-run services without requiring R2 or Cloudflare.

## Boundaries

The browser never connects directly to Orchestrator or the configured Image
Forge adapter. `WebUI/app.py` exposes a same-origin proxy and does not store
subject state itself. Character identity remains in Memory; scene, pose,
camera, and background remain request-level task input.

Default endpoints can be overridden when needed:

- `EVERSPARK_WEBUI_HOST`
- `EVERSPARK_WEBUI_PORT`
- `EVERSPARK_ORCHESTRATOR_URL`
- `EVERSPARK_IMAGE_FORGE_URL`
- `EVERSPARK_WEBUI_REQUEST_TIMEOUT`
- `EVERSPARK_IMAGE_FORGE_TIMEOUT`
