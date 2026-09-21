# Image Forge

Image workflow preparation and execution through pluggable adapters.

The current migrated slice contains:

- a ComfyUI execution adapter;
- API Format workflow loading;
- positive prompt, negative prompt, and seed replacement;
- a public, intentionally empty workflow placeholder.

ComfyUI is an adapter rather than the module identity. A user workflow can be
selected with `EVERSPARK_WORKFLOW_TEMPLATE`; importing or building a portable
default workflow will be handled separately from the old personal workflow.
