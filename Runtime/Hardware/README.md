# Hardware

NVIDIA GPU discovery and optional module-to-GPU assignment.

- `gpu.sh` reports driver, CUDA, compute-capability, and runtime facts.
- `gpu_assignment.sh` leaves zero- and one-GPU hosts unchanged.
- On multi-GPU hosts, Image Forge defaults to GPU 0 and Concept Forge to GPU 1.
- `IMAGE_FORGE_GPU_INDEX` and `CONCEPT_FORGE_GPU_INDEX` override those defaults.

The existing `core_*` function names remain temporarily available while the
execution modules are migrated from the source repository.
