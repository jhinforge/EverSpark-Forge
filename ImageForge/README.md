# Image Forge

Image workflow preparation and execution through pluggable adapters.

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
connects `Data/Models/ImageForge/checkpoints` through ComfyUI's
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
