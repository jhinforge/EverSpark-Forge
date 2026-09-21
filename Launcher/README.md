# Launcher

Installation, initialization, configuration validation, and command routing.

Run from a fresh clone:

```bash
./everspark init
./everspark doctor
./everspark setup --plan
```

`init` creates ignored runtime directories under `Data/` without creating a
personal configuration file. Local storage and localhost networking therefore
remain active automatically.

`setup --plan` prints the official Hugging Face sources and local destinations
without changing the machine. `setup` creates an ignored model-tool virtual
environment, downloads the selected defaults, and imports the Concept Forge
GGUF into Ollama. Use `--models concept` or `--models image` to install only
one side, and `--skip-concept-import` when Ollama will be attached later.

Model-only commands are also available through `./everspark models`:

```bash
./everspark models status
./everspark models plan --models image
```

To make the command available through the user PATH without root access:

```bash
bash Launcher/install.sh
```

Public module commands are `image`, `concept`, `orchestrator`, and `webui`.
Backend names such as ComfyUI and Ollama are configuration details rather than
public module commands.
