# Orchestrator

Central routing, session coordination, task state, and execution control.

This migration preserves the verified v0.1 behavior from
`feature/everspark-webui-v1@606640c`:

- one active generation request at a time;
- batch submission with an independent seed for every image;
- Unicode surrogate-pair repair;
- bounded conversation history supplied to Concept Forge;
- successful task persistence through the Memory module;
- local HTTP API and interactive console.

## Run

Start the local service:

```bash
./everspark orchestrator start
```

Open the console in another terminal:

```bash
./everspark orchestrator console
```

The service binds to `127.0.0.1:8765` by default and exposes:

- `GET /health`
- `POST /tasks`
- `GET /memory/history?session_id=...`
- `POST /memory/clear`
- `GET /subjects`
- `GET /subjects?subject_id=...`
- `GET /subjects/revisions?subject_id=...`
- `POST /subjects`
- `POST /subjects/generate`
- `POST /subjects/update`
- `POST /subjects/compile`

Generation requests may include `subject_id`. Orchestrator loads that revision
from Memory, asks Concept Forge to compile its stable traits, and merges them
with the request-level scene prompt before sending the workflow to Image Forge.

## Configuration

The component runtime defaults are in
`orchestrator/config/default_config.json`. Environment variables can override
the Orchestrator address, provider/adapter endpoints, Memory database, and
workflow template without modifying tracked files.

The bundled Image Forge workflow is intentionally an empty placeholder. The
old source workflow referenced personal checkpoints, LoRAs, and custom nodes,
so it is not suitable for a public repository.
