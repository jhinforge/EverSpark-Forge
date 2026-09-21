# EverSpark Forge Architecture

## Naming rules

- Product and documentation names use title case: `Image Forge`.
- Top-level component directories use PascalCase: `ImageForge/`.
- Python packages will use lowercase snake case: `image_forge`.
- Third-party products appear below EverSpark-owned abstractions.

## Primary flow

```text
EverSpark WebUI
    -> Orchestrator
        <-> Concept Forge
        <-> Memory
        -> Image Forge
            -> ComfyUI adapter
```

## Component boundaries

### Orchestrator

Owns routing, sessions, task state, and coordination. It does not generate
prompts, store long-term knowledge, or implement an execution backend.

### Concept Forge

Turns discussion and user intent into validated structured state. It owns
schemas, builders, validators, prompt compilation, and model providers. Ollama
is the first provider, not the module identity.

### Memory

Provides working memory, episodic memory, and structured state memory. The
first state object will be a reusable character subject document produced by
Concept Forge.

### Image Forge

Executes image workflows from validated input. ComfyUI is the first adapter,
not the module identity.

### Runtime

Owns health checks, process state, hardware discovery, and logs exposed to the
WebUI.

### Infrastructure

Contains optional environment-facing backends. Local storage and local
networking are defaults. R2 and Cloudflare are opt-in integrations.

## Configuration behavior

No user configuration means local mode. Explicitly enabling an optional
backend makes all of its required values mandatory. Validation failures must
stop startup and identify the missing or invalid setting.

## Migration baseline

All migrated implementation code uses
`gpu-bootstrap@feature/everspark-webui-v1` commit `606640c` as its sole source
baseline. Other branches remain historical references and are not mixed into
the new repository.
