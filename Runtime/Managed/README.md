# Managed Runtime

This layer owns the disposable local service installations and process state
under `Data/Runtime/`. It never stores personal configuration in the repository.

- ComfyUI is installed at a pinned tag and verified commit in `Data/Runtime/ComfyUI/`.
- Ollama is installed through its official Linux installer when unavailable.
- PID identity includes the Linux process start time to avoid killing a reused PID.
- Services bind to localhost by default and write raw process output to `Data/Logs/`.

Default pinned versions are ComfyUI `v0.37.0` at commit
`73c9bad4d21e7addbe1d13bc92eee0f1431b017d` and Ollama `0.34.2`. They can be
overridden explicitly through `.env`; when changing ComfyUI, override both its
version and expected commit. Selected values are validated before being passed
to installers.

On a single GPU, Concept Forge sets `OLLAMA_KEEP_ALIVE=0`. Qwen is unloaded
after its response so Image Forge can reclaim GPU memory before diffusion. On
two or more GPUs, the existing assignment policy defaults Image Forge to GPU 0
and Concept Forge to GPU 1.

## Automatic PyTorch compatibility

EverSpark selects the managed PyTorch environment from detected hardware and
the Pod/base-image CUDA runtime. Blackwell (`sm_120+`) on CUDA 12.8 or newer
uses the validated `cu128` profile. Other and unknown combinations use the
stable `cu121` profile. The selection is internal: there is no public CUDA
wheel URL or profile override.

The selected profile is recorded under `Data/Runtime/ComfyUI`. If a clone is
moved to hardware requiring a different profile, only the managed ComfyUI venv
is rebuilt; models, workflows, outputs, configuration, and memory are retained.

`access_info.py` converts the platform's connection metadata into a safe SSH
forwarding command. It recognizes Vast.ai's `PUBLIC_IPADDR` and
`VAST_TCP_PORT_22`, supports explicit cross-platform overrides, and never
guesses missing public connection details.
