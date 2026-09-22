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
- `GET /resources`
- `POST /tasks`
- `POST /conversation`
- `GET /memory/history?session_id=...`
- `POST /memory/clear`
- `GET /subjects`
- `GET /subjects/current?session_id=...`
- `GET /subjects?subject_id=...`
- `GET /subjects/revisions?subject_id=...`
- `POST /subjects`
- `POST /subjects/generate`
- `POST /subjects/update`
- `POST /subjects/compile`

Every conversation automatically owns one current subject. Orchestrator asks
Concept Forge to extract that internal JSON document from the bounded user and
assistant context, validates it, and stores a revision only when its content
changes. Generation compiles the current subject automatically and merges its
stable traits with the request-level scene prompt before sending the workflow
to Image Forge. Clients do not select or configure a subject ID.

The explicit subject write endpoints remain available as developer/debugging
interfaces; they are not part of the normal WebUI workflow.

## Configuration

The component runtime defaults are in
`orchestrator/config/default_config.json`. Environment variables can override
the Orchestrator address, provider/adapter endpoints, Memory database, and
workflow template without modifying tracked files.

The bundled Image Forge workflow is a minimal 1024 x 1536 Illustrious workflow
made entirely from standard ComfyUI nodes. It contains no LoRAs, personal
paths, or custom-node dependencies.

When the replacement API Format workflow contains a
`CheckpointLoaderSimple` node, Orchestrator asks Image Forge for the currently
available checkpoints. It keeps the workflow's requested name when present,
otherwise selects the managed Illustrious default, then falls back to the
first compatible checkpoint in stable alphabetical order. Every fallback is
reported to the caller.

`GET /resources` exposes the selectable workflow, Checkpoint, LoRA, and Ollama
model inventories used by the WebUI. `POST /tasks` and `POST /conversation`
accept an optional `selection` object. Workflow mutations are performed on an
isolated task copy: explicit Checkpoint selection is validated against
ComfyUI, and selected LoRAs are inserted as a standard `LoraLoader` chain.
