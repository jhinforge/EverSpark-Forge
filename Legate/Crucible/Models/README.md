# Managed Models

`default_models.json` is the repository-owned initial model catalog. It is not
user configuration and contains no credentials.

The legacy Linux single-machine starter catalog selects:

- Qwen3 4B GGUF Q4_K_M for Concept Forge;
- Illustrious XL v1.0 for Image Forge.

Model binaries are downloaded to ignored paths under `Data/Models/` and are
never committed. `model_manager.py` supports plan, status, download, and
Concept Forge import operations. Gated Hugging Face repositories can use the
standard `HF_TOKEN` environment variable, but the public defaults do not
require one.

Distributed model operations run on selected Image/Concept Nodes via
`Aegis/Storage/distributed_models.py` and `Legate/Warden/model_storage.py`.
Audio deployment prepares its own weights. See
[Configuration](../../../Docs/Configuration.md).
