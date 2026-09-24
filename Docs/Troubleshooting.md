# Troubleshooting (v0.1)

This guide covers the cloud Linux deployment in [Getting started](Getting-Started.md). Locate the failing layer first: installation, WebUI connection, service startup, models and workflows, generation, or remote storage.

## Collect three results

From the repository root:

```bash
./everspark status
./everspark doctor
./everspark logs status
```

`status` reports service health and log locations. `doctor` checks basic commands, GPU visibility, and enabled backend settings. `logs status` lists managed log status. WebUI **Runtime** also shows readiness. Logs default to `Data/Logs/`; if `EVERSPARK_LOG_DIR` is configured, use the actual location shown by `status`.

## 1. Setup did not finish

**Check:** Find the first error from `./everspark setup`. Use `./everspark setup --plan` to inspect download sources and destinations. Confirm the GPU with `nvidia-smi`, and run `./everspark doctor` for platform and command checks. Runtime installation and model downloads require network access.

**Fix:** Address that error and rerun `./everspark setup`. If runtimes installed but models are missing, run `./everspark models status`. A running WebUI does not mean generation models are ready. Check terminal output and relevant installation, model, and service logs in `Data/Logs/`.

## 2. WebUI does not open

1. On the cloud machine, run `./everspark status webui`. If stopped, run `./everspark start`; if startup fails, inspect `Data/Logs/webui-service.log`.
2. If `http://127.0.0.1:8780` opens **on the cloud machine** but not on your computer, run `./everspark access`. Execute its SSH forwarding command **on your computer**, keep the SSH session open, and visit the printed local address (normally `http://127.0.0.1:8080`).
3. If no complete command is shown, verify the public SSH address and port. If necessary, configure `EVERSPARK_SSH_HOST` and `EVERSPARK_SSH_PORT` privately, then rerun `./everspark access`.

The default WebUI listens only on localhost. The cloud machine's `127.0.0.1:8780` is not your computer's remote address.

## 3. Runtime reports an unready service

| Service | Check first | Default process log |
| --- | --- | --- |
| Concept Forge | `./everspark status concept`; Ollama and its model | `Data/Logs/ollama-service.log` |
| Image Forge | `./everspark status image`; ComfyUI and GPU | `Data/Logs/comfyui.log` |
| Orchestrator | `./everspark status orchestrator`; upstream services and settings | `Data/Logs/orchestrator-service.log` |
| WebUI | `./everspark status webui`; listening port and process | `Data/Logs/webui-service.log` |

`external` means a healthy service started elsewhere was discovered; it does not mean stopped. `unhealthy` means a managed process is running but failed its health check. Inspect logs, then use `./everspark restart <service>` if appropriate; do not guess process IDs.

## 4. Missing model or workflow choices

In **Forge**, inspect **Workflow**, **Checkpoint**, **VAE**, and **Concept LLM**. Run `./everspark models status`. For user downloads, check that the task completed under **Storage** and that you chose the correct model category. Interrupted or failed direct downloads are not exposed as complete models.

Workflows must be registered **API Format JSON** with a matching manifest. A regular ComfyUI UI workflow cannot simply be placed in the registered workflow directory. Installed models must also match the workflow. See [Image Forge](../ImageForge/README.md) for node and LoRA constraints. For remote libraries, check scanned model directories and set manual paths for unusual layouts. Public direct URL downloads work without rclone.

## 5. Generation fails or no result appears

Read the on-page task error and recent **Gallery** results, then run `./everspark status`. Inspect `Data/Logs/comfyui.log` for Image Forge problems and `Data/Logs/orchestrator-service.log` for submission problems. If failures began after changing a workflow, checkpoint, VAE, or LoRA, record the selection and error and compare it with the workflow's model and node requirements.

Successful images go to `Data/Outputs/`; **Download outputs ZIP** exports the entire folder. A failed generation does not imply any backup occurred.

## 6. An existing character is listed but not used

Select it in **Forge** and click **Use in Forge**. Merely seeing it in **Subjects** does not select it for the current conversation. Confirm the current character card in Forge before generating. If selection fails, record browser feedback and errors at the same time in `Data/Logs/orchestrator-service.log` and `Data/Logs/webui-service.log`.

## 7. Remote pull, upload, or character restore fails

Run `./everspark doctor`. rclone needs valid `rclone.conf`, image and Concept model scanning roots, and an accessible remote. Manual paths or upload destinations pointing at a read-only or aggregate remote need a real writable target for uploads. Inspect the UI task error and `Data/Logs/rclone.log`.

For outputs, choose **Outputs folder** to upload the whole directory. Character restore handles batch snapshots of character JSON and Memory SQLite and requires the prompted restart. It does not restore output images or models. See [Runtime and data](Runtime-and-Data.md).

## 8. Tunnel enabled but inaccessible publicly

First verify WebUI locally on the cloud machine at `http://127.0.0.1:8780` and with `./everspark status webui`. Check Tunnel with `./everspark status`, then the UUID, hostname, credential file, and `CF_LOCAL_PORT` in your private settings. The latter must match the WebUI port at import. Inspect Tunnel-related logs under `Data/Logs/`. SSH forwarding is sufficient if you simply need browser access from your computer.

## Filing an issue

Include your Linux environment, commands, failing step, and **first error**, plus relevant `./everspark status` and `./everspark doctor` output and a short tail of the appropriate service log. On the cloud machine, use `tail -n 80 Data/Logs/<log-file>`. Redact public IPs, private paths, tokens, signed model URLs, and credentials. Do not upload your `.env` or `rclone.conf`.
