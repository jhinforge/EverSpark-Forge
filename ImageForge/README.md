# Image Forge

Image workflow preparation and execution through pluggable adapters. Image
Forge owns the backend-neutral request, job IDs, status, and gallery. WebUI
accesses image results through Orchestrator, never through a model runtime.

## Select a drawing engine

ComfyUI is the default drawing tool. Image Forge discovers plugins from
`ImageForge/Plugins/*.json`. In the Forge drawing tool selector, choose
Diffusers and click **Install tool** (once), then **Enable tool** after a
restart if needed. Choose **Set as default** to save the default in the
memory database; no `.env` edit is needed. A generation request records its
chosen tool, so jobs and the gallery continue working after changing the
selector. The managed Diffusers worker runs as a separate optional service
on port 8190 and shares checkpoint, LoRA, VAE and output directories with
ComfyUI. Default and imported `.safetensors`/`.ckpt` checkpoints are listed,
but this Diffusers adapter currently supports SDXL single-file checkpoints
only. Set `image_forge.adapters.diffusers.default_checkpoint` in the config
when changing the default model.

Diffusers currently supports SDXL text-to-image, checkpoint selection, SDXL
LoRA files, and optional compatible VAE files. Its LoRA model and CLIP strength
must have the same value; different values are rejected instead of silently
changing the user's settings. ComfyUI API Format workflows remain specific to
the ComfyUI adapter. The engines may produce different images from the same
seed and prompts. Diffusers may need access to model configuration files when
loading a single-file checkpoint.

The job catalog is stored alongside EverSpark Memory in its SQLite database;
images remain in `Data/Outputs`. Earlier images in that directory appear in
the gallery even if their ComfyUI job ID was never registered. Completed jobs
remain visible after switching engines; an unfinished job is marked failed if
its engine changes.

The current migrated slice contains:

- a ComfyUI execution adapter;
- API Format workflow loading;
- manifest-backed API Format workflow discovery and selection;
- positive prompt, negative prompt, and seed replacement;
- explicit Checkpoint selection from ComfyUI's reported inventory;
- task-local standard `LoraLoader` injection with multiple LoRAs;
- a public, LoRA-free Illustrious API Format workflow built from standard nodes.

ComfyUI is an adapter rather than the module identity. A user workflow can be
selected with `EVERSPARK_WORKFLOW_TEMPLATE`; importing or building a portable
workflow remains independent from personal workflows. The managed runtime
connects `Data/Models/ImageForge/checkpoints`, `loras`, and `vae` through ComfyUI's
`extra_model_paths.yaml` mechanism.

## Workflow registry

Runtime workflows live in `ImageForge/Workflows`. Each selectable API Format
JSON has a sibling `*.workflow.json` manifest that provides its stable ID,
display name, prompt/seed node IDs, model family, and supported mutations. The
bundled example is `base.workflow.json`.

The first registry version executes API Format JSON only. A normal ComfyUI UI
workflow cannot be placed in the registry directly. Automated UI-to-API
conversion is deferred until it can use ComfyUI's frontend graph conversion
rather than an incomplete JSON rewrite.

Standard LoRA injection currently requires exactly one
`CheckpointLoaderSimple` node. Image Forge creates a temporary chain of
`LoraLoader` nodes for the task and rewires MODEL and CLIP consumers while
leaving the tracked workflow unchanged. Flux, SD3, separate UNET/CLIP loaders,
and custom LoRA nodes require future workflow adapters.
