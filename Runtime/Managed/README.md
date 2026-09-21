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
