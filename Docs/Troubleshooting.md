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

See [log commands](Commands.md#5-log-status-and-maintenance) for the checks above and for `logs rotate`, which can change or remove log files.

## 1. Setup did not finish

**Check:** Find the first error from `./everspark setup`. Use `./everspark setup --plan` to inspect download sources and destinations. Confirm the GPU with `nvidia-smi`, and run `./everspark doctor` for platform and command checks. Runtime installation and model downloads require network access.

**Fix:** Address that error and rerun `./everspark setup`. If runtimes installed but models are missing, run `./everspark models status`. A running WebUI does not mean generation models are ready. Check terminal output and relevant installation, model, and service logs in `Data/Logs/`.

## 2. WebUI does not open

1. On the cloud machine, run `./everspark status webui`. If stopped, run `./everspark start`; if startup fails, inspect `Data/Logs/webui-service.log`.
2. If `http://127.0.0.1:8780` opens **on the cloud machine** but not on your computer, run `./everspark access`. Execute its SSH forwarding command **on your computer**, keep the SSH session open, and visit the printed local address (normally `http://127.0.0.1:8080`).
3. If no complete command is shown, verify the public SSH address and port. If necessary, configure `EVERSPARK_SSH_HOST` and `EVERSPARK_SSH_PORT` privately, then rerun `./everspark access`.
4. For a temporary link, run `./everspark share status`. If none is running, run `./everspark share` on the cloud machine and open the printed URL. If an existing link fails, check WebUI readiness, whether sharing is still running, and connectivity from the cloud machine to Cloudflare. Restarting sharing may change the URL.

The default WebUI listens only on localhost. The cloud machine's `127.0.0.1:8780` is not your computer's remote address.

## 3. Runtime reports an unready service

| Service | Check first | Default process log |
| --- | --- | --- |
| Concept Forge | `./everspark status concept`; Ollama for the built-in provider; Orchestrator for external requests | `Data/Logs/ollama-service.log` or `Data/Logs/orchestrator-service.log` |
| Image Forge | `./everspark status image`; selected engine and GPU | `Data/Logs/comfyui.log` or `Data/Logs/diffusers.log` |
| Orchestrator | `./everspark status orchestrator`; upstream services and settings | `Data/Logs/orchestrator-service.log` |
| WebUI | `./everspark status webui`; listening port and process | `Data/Logs/webui-service.log` |

`external` means a healthy service started elsewhere was discovered; it does not mean stopped. `unhealthy` means a managed process is running but failed its health check. Inspect logs, then use `./everspark restart <service>` if appropriate; do not guess process IDs.

## 4. Missing model or workflow choices

In **Forge**, inspect the selected **Drawing tool**, **Workflow** (ComfyUI), **Checkpoint**, **VAE**, and **Concept LLM**. Run `./everspark models status`. For user downloads, check that the task completed under **Storage** and that you chose the correct Checkpoint/diffusion, LoRA, VAE, or GGUF card. Interrupted or failed direct downloads are not exposed as complete models. For a hosted language model, open **Model services**, verify the `/v1` base URL and exact model ID, then use **Test**; these IDs are entered explicitly rather than discovered from `/models`.

ComfyUI workflows must be registered **API Format JSON** with a matching manifest. A regular ComfyUI UI workflow cannot simply be placed in the registered workflow directory. Diffusers does not use those workflows and currently accepts SDXL single-file checkpoints. Installed models must match the chosen engine. See [Image Forge](../ImageForge/README.md) for node, LoRA, and VAE constraints. For remote libraries, check scanned model directories and set manual paths for unusual layouts. Public direct URL downloads work without rclone.

## 5. Generation fails or no result appears

Read the on-page task error and recent **Gallery** results, then run `./everspark status`. Inspect `Data/Logs/comfyui.log` for ComfyUI or `Data/Logs/diffusers.log` for the managed Diffusers worker; plugin installation tasks may report `Data/Logs/image-plugin-diffusers.log`. Check `Data/Logs/orchestrator-service.log` for task submission and planning. Diffusers installations made before PEFT was added can show **Repair required**: use **Repair tool** in Forge before retrying LoRA or VAE. If failures began after changing a workflow, checkpoint, VAE, or LoRA, record the selection and error and compare it with the selected engine's requirements.

If the browser reports HTTP 502 while generating, first check the background task in Forge and the result in Gallery: planning and generation run asynchronously, and an image may have completed. Capture WebUI and Orchestrator logs if the task status still cannot be polled. For an OpenAI Compatible error, test the connection in **Model services** and check the Orchestrator log. The adapter expects non-streaming Chat Completions and text in `choices[0].message.content`; optional JSON mode should remain off if the service rejects `response_format`.

Successful images go to `Data/Outputs/`; **Download outputs ZIP** exports the entire folder. A failed generation does not imply any backup occurred.

## 6. An existing character is listed but not used

Select it in **Forge** and click **Use in Forge**. Merely seeing it in **Subjects** does not select it for the current conversation. Confirm the current character card in Forge before generating. If selection fails, record browser feedback and errors at the same time in `Data/Logs/orchestrator-service.log` and `Data/Logs/webui-service.log`.

## 7. Local ZIP export/restore or remote transfer fails

**Character and Memory ZIP:** If **Download data ZIP** fails under **Storage → Character and Memory ZIP**, check that Orchestrator is ready and `Data/Memory/everspark.db` is available. Inspect the page error and `Data/Logs/orchestrator-service.log` and `Data/Logs/webui-service.log`. If **Validate and restore** fails, confirm the file came from EverSpark's **Download data ZIP**, is no larger than 128 MiB, and has not been damaged or changed. Validation checks the manifest, hashes, SQLite integrity, and agreement between all four character JSON documents and the database; arbitrary ZIP files are not accepted. Restart EverSpark after a successful restore. Previous data lives in `Data/Recovery/`; the upload is staged in `Data/Imports/` and cleaned up by WebUI after success or failure. This ZIP contains no images or models.

**Remote models and data:** Run `./everspark doctor`. rclone needs valid `rclone.conf`, image and Concept model scanning roots, and an accessible remote. Manual paths or upload destinations pointing at a read-only or aggregate remote need a real writable target for uploads. Inspect the UI task error and `Data/Logs/rclone.log`.

For outputs, choose **Outputs folder** to upload the whole directory. Remote restore points also contain batched character JSON and Memory SQLite and require the prompted restart. Neither restore method brings back output images or models. See [Runtime and data](Runtime-and-Data.md).

## 8. Temporary link or Named Tunnel inaccessible publicly

**Temporary link from `./everspark share`:** On the cloud machine, run `./everspark status webui` and `./everspark share status`. For startup failures, read the command error and `Data/Logs/quick-tunnel.log` (or your `EVERSPARK_LOG_DIR`). Check WebUI health and outbound Cloudflare connectivity. Installing a missing `cloudflared` needs root and download access. Quick Tunnel is rejected when `~/.cloudflared/config.yaml` or `config.yml` exists for this user; check whether another Tunnel relies on that configuration before temporarily moving it. The temporary link does not use Named Tunnel settings such as `CF_TUNNEL_UUID`.

**Configured Named Tunnel:** First verify WebUI locally on the cloud machine at `http://127.0.0.1:8780` and with `./everspark status webui`. Check Tunnel with `./everspark status`, then the UUID, hostname, credential file, and `CF_LOCAL_PORT` in your private settings. The latter must match the WebUI port at import. Inspect Tunnel-related logs under `Data/Logs/`. SSH forwarding works for access from your own computer; a temporary link can serve a short demo without Named Tunnel configuration. Stop the public link with `./everspark share stop` when finished; the WebUI has no login protection.

## Filing an issue

Include your Linux environment, commands, failing step, and **first error**, plus relevant `./everspark status` and `./everspark doctor` output and a short tail of the appropriate service log. On the cloud machine, use `tail -n 80 Data/Logs/<log-file>`. Redact public IPs, private paths, tokens, signed model URLs, and credentials. Do not upload your `.env` or `rclone.conf`.
