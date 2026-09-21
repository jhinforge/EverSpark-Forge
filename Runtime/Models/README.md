# Managed Models

`default_models.json` is the repository-owned initial model catalog. It is not
user configuration and contains no credentials.

The initial catalog selects:

- Qwen3 4B GGUF Q4_K_M for Concept Forge;
- Illustrious XL v1.0 for Image Forge.

Model binaries are downloaded to ignored paths under `Data/Models/` and are
never committed. `model_manager.py` supports plan, status, download, and
Concept Forge import operations. Gated Hugging Face repositories can use the
standard `HF_TOKEN` environment variable, but the public defaults do not
require one.
