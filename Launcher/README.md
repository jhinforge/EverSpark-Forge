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

Existing Pod configuration can be imported before setup:

```bash
./everspark configure --from /root
./everspark setup
./everspark doctor
```

Both `.env` and the Windows-friendly `env.txt` alias are accepted. Cloudflare
credentials and `rclone.conf` are copied into ignored private runtime
directories; source files are preserved.

`setup --plan` prints pinned runtime versions, official Hugging Face sources,
and local destinations without changing the machine. `setup` installs the
managed runtimes, creates isolated Python environments, downloads the selected
defaults, and imports the Concept Forge GGUF into Ollama. Use `--models
concept` or `--models image` to download only one model side, `--skip-models`
to prepare runtimes only, and `--skip-concept-import` when Ollama will be
attached later.

Model-only commands are also available through `./everspark models`:

```bash
./everspark models status
./everspark models plan --models image
```

Managed services share one lifecycle entry point:

```bash
./everspark start
./everspark status
./everspark restart image
./everspark stop
```

After all services (or WebUI alone) start, the launcher prints local access
instructions. On Vast.ai it uses `PUBLIC_IPADDR` and `VAST_TCP_PORT_22` to
build the SSH tunnel command automatically. Print the instructions again with:

```bash
./everspark access
```

Other platforms can provide `EVERSPARK_SSH_HOST` and `EVERSPARK_SSH_PORT`.
The browser-side port defaults to 8080 and can be changed with
`EVERSPARK_LOCAL_WEBUI_PORT`.

EverSpark does not stop a healthy external service that it did not start.
Managed PID files include the Linux process start time so stale/reused PIDs are
not terminated accidentally.

When `EVERSPARK_NETWORK_BACKEND=cloudflare`, the same lifecycle commands also
start, check, restart, and stop the configured Tunnel after the WebUI service.

To make the command available through the user PATH without root access:

```bash
bash Launcher/install.sh
```

Public module commands are `image`, `concept`, `orchestrator`, and `webui`.
Backend names such as ComfyUI and Ollama are configuration details rather than
public module commands.
