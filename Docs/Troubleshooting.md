# Troubleshooting

Record the About version/commit, time, complete UI error, Node and task ID first. Preserve surrounding logs. Do not publish API/auth keys, signed download URLs or complete private configuration.

## Client does not open

Fully extract the ZIP into a writable directory on Windows x64. Standard requires installed WebView2; use full when absent. Do not copy only the EXE. Check `Data/Logs/client/backend.log`. Close a concurrently running source host first. The CLI entry is `everspark.cmd archon start`; desktop ports are dynamic, not necessarily 8780.

## Node offline or Forge unavailable

Check host Tailscale, Agent heartbeat and machine connectivity, then deployment, source verification and Forge health. An online Agent does not imply a working Forge. Before a new rental, check auth-key validity, single-use consumption and the Reusable setting.

If jobs continue while health is temporarily unconfirmed, preserve the stage and last successful check and wait for rechecking. Do not immediately duplicate deployment or generation. Long-running tasks use an independent probe channel; one timeout does not prove the Pod is offline.

## Deployment failed or outcome unknown

Record the failed stage, exit code and diagnostic tail. Model downloads, Python dependencies, GPU/drivers and service startup are different stages. Agent reconnection and host restart can recover task queries; interrupted execution can have an unknown outcome without automatic reinstall. Verify actual services/resources before redeploying.

Audio installation checks its source pin and matching Torch/torchaudio; repair through Audio deployment. Update host and Node for source mismatches using [Updating](Updating.md).

## Generation failed

Each mode needs its corresponding Forges; Audio does not require Image. Test hosted Concept APIs, including URL, model ID and authentication. Resource lists belong to the selected Node, not another machine.

`Concept Forge returned an invalid creative decomposition` indicates an invalid plan structure or mode. Record the model, mode and full error and verify updates on both host and Concept execution side. Do not require Image configuration for an audio-only request.

Inspect failed/skipped steps and result polling separately. Image submission does not imply completed rendering. Check character selection and model/workflow/LoRA/VAE compatibility.

## Cloud scanning or model pull failed

Check enabled storage, rclone executable, imported connection and at least one model directory. Image and Concept are independent. Custom category names require a model type. Pulls target the corresponding Forge Node. Old Node model-storage processes need updates and restarts; restarting only the Agent may not reload them.

Sources may be read-only; upload/backup destinations must be writable. Remote paths, task errors and Node model-storage `service.log` distinguish directory failures from service failures.

## Media or ZIP downloads failed

For playback or individual files, check Node availability and Tailscale policy/firewall access. Refresh expired URLs in Asset library.

Remote ZIPs are prepared on the Pod and downloaded using temporary URLs. Confirm archive completion, then inspect whether transfer started. Forge generation health does not prove media URL service health. For `Image URL service unavailable` or archive HTTP 503, inspect the Node service running `Aegis/Storage/node_media_access.py`. `Cannot assign requested address` means the bind address is not local and bindable; update and restart the Node media service.

Choose a destination in desktop Save As; cancellation saves nothing. If an active transfer is slow, compare individual files and ZIPs and check the host-to-Pod route. Public speed tests measure a different path. Completion messages show the actual saved path.

Character/Memory ZIP restoration instead checks its 128 MiB limit, manifest and SQLite consistency. It does not use the remote-media ZIP path.

## Logs

| Location | Start with |
| --- | --- |
| Desktop directory | `Data/Logs/client/backend.log` |
| Host log root | `archon/gate.log`, `webui/webui.log` and affected module logs |
| Agent directory | Logs, task records and `bandwidth.log` under `/workspace/everspark-node/` |
| Node checkout | Forge `Data/Logs/` and `Data/Runtime/model-storage/service.log` |

Paths can be overridden; use the task's actual diagnostics. Host logs normally live under `Data/Logs/`. Include steps, mode, version, task ID and redacted logs in an Issue. Identify desktop, source-host or Linux single-machine execution.
