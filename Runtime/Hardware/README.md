# Hardware

NVIDIA GPU discovery and optional module-to-GPU assignment.

- `gpu.sh` reports driver, CUDA, compute-capability, and runtime facts.
- `torch_profile.sh` converts those facts into an internal PyTorch 2.9.1
  `cu126`/`cu128` compatibility profile. Driver capability takes precedence
  over the base-image CUDA toolkit; users do not select wheel families.
- `gpu_assignment.sh` leaves zero- and one-GPU hosts unchanged.
- On multi-GPU hosts, Image Forge defaults to GPU 0 and Concept Forge to GPU 1.
- `IMAGE_FORGE_GPU_INDEX` and `CONCEPT_FORGE_GPU_INDEX` override those defaults.

The existing `core_*` function names remain temporarily available while the
execution modules are migrated from the source repository.
