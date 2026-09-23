# Infrastructure

Optional environment-facing backends. Local storage and localhost networking
are the defaults. Nothing in this directory is required for a local-only
EverSpark session.

## Storage

`Storage/rclone.sh` preserves the verified rclone abstraction from the WebUI
branch. Image Forge and Concept Forge own their remote paths and transfer
policies; Infrastructure only provides connection and transfer primitives.

`Storage/r2_manager.py` adds the managed resource layer used by Orchestrator
and WebUI. It scans flat Image Forge model directories, parses Ollama manifests,
and downloads only the selected model. Transfers use an isolated partial file,
publish live byte progress, and atomically replace the final target only after
size validation. It never restores a complete legacy ComfyUI directory or
copies Ollama identity keys.

`Storage/download_manager.py` provides the local-first direct model downloader.
It accepts public HTTP(S) model links independently of rclone, routes each model
type into its fixed managed directory, preserves resumable hidden partial files,
and atomically publishes completed downloads. Local and private network targets
are rejected. Concept Forge GGUF files are imported with `ollama create` after
the download completes.

R2 is enabled by selecting an rclone-backed storage mode and supplying an
existing rclone configuration. Missing or invalid remote configuration is a
startup error after the backend has been explicitly enabled.

The two remote values point to resource roots, not buckets in general:

```text
IMAGE_FORGE_RCLONE_REMOTE=remote:path/models_cold
CONCEPT_FORGE_RCLONE_REMOTE=remote:path/.ollama/models
```

Image Forge expects `checkpoints`, `diffusion_models`, and `loras` below its
root. Concept Forge expects standard Ollama `blobs` and `manifests` directories.

## Network

`Network/Tunnel` implements the existing Cloudflare Named Tunnel flow using a
tunnel UUID, hostname, local port, and credential JSON. The scripts exit
successfully without starting cloudflared while
`EVERSPARK_NETWORK_BACKEND=local`.

The public launcher starts the Tunnel only after WebUI is healthy, checks it as
part of `./everspark status`, and stops it before WebUI shutdown. The private
configuration importer requires the Tunnel ingress port to equal the WebUI
port so Image Forge is not exposed directly.
