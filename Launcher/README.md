# Launcher

Installation, initialization, configuration validation, and command routing.

Run from a fresh clone:

```bash
./everspark init
./everspark doctor
```

`init` creates ignored runtime directories under `Data/` without creating a
personal configuration file. Local storage and localhost networking therefore
remain active automatically.

To make the command available through the user PATH without root access:

```bash
bash Launcher/install.sh
```

Public module commands are `image`, `concept`, `orchestrator`, and `webui`.
Backend names such as ComfyUI and Ollama are configuration details rather than
public module commands.
