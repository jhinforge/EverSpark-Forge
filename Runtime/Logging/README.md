# EverSpark Forge logging

Status: foundation and caller migration complete  
Scope owner: `Runtime/Logging`

## Contract

Shell and Python loggers emit the same fields:

- RFC 3339 timestamp with timezone
- level: `DEBUG`, `INFO`, `OK`, `WARN`, or `ERROR`
- component and event
- human-readable message
- run ID and process ID
- optional key/value fields with sensitive values redacted

Text output is optimized for operators:

```text
2026-08-21T10:15:30+09:00 INFO  comfyui.recovery step.start run_id=... pid=... message=Step started step=r2_pull
```

JSON output carries the same fields as native JSON values.

## Configuration

| Setting | Default | Purpose |
| --- | --- | --- |
| `EVERSPARK_LOG_DIR` | `<repository>/Data/Logs` | Root directory for managed logs |
| `EVERSPARK_LOG_LEVEL` | `INFO` | Minimum emitted level |
| `EVERSPARK_LOG_FORMAT` | `text` | `text` or `json` |
| `EVERSPARK_RUN_ID` | generated | Correlates one recovery/start run |
| `EVERSPARK_LOG_CONSOLE` | `1` | Mirrors managed records to the console |
| `EVERSPARK_LOG_MANIFEST` | bundled manifest | Logical log manifest override |
| `EVERSPARK_LOG_MAX_BYTES` | manifest policy | Global rotation-size override |
| `EVERSPARK_LOG_KEEP_FILES` | manifest policy | Global retained-file-count override |
| `EVERSPARK_LOG_MAX_AGE_DAYS` | manifest policy | Global retention-age override |

All product-owned configuration uses the `EVERSPARK_*` namespace.

## Shell API

Source `Runtime/Logging/log.sh`, then initialize a component:

```bash
core_log_init comfyui.recovery "${EVERSPARK_LOG_DIR}/recovery.log"
core_info recovery.start "Recovery started" "profile=$TORCH_PROFILE"
core_run_step restore.core bash "$SCRIPT_DIR/restore_comfyui_core.sh"
```

The public functions are:

- `core_log_init COMPONENT [LOG_FILE]`
- `core_debug|core_info|core_ok|core_warn|core_error EVENT MESSAGE [key=value ...]`
- `core_step_start NAME [key=value ...]`
- `core_step_end NAME [ok|failed] [key=value ...]`
- `core_run_step NAME COMMAND...`
- `core_run_optional_step NAME COMMAND...`
- `core_die EVENT MESSAGE [key=value ...]`

Existing one-argument calls such as `core_info "Config loaded"` remain supported and emit the event `message`. This compatibility form should disappear as callers are migrated.

## Python API

`Runtime/Logging/everspark_logging.py` uses the standard `logging` package with the shared contract:

```python
from everspark_logging import get_logger

logger = get_logger(
    "orchestrator",
    "Data/Logs/orchestrator.log",
)
logger.info("server.ready", "Server is ready", port=8765)
```

Call `logger.close()` during orderly service shutdown so file handlers are released immediately.

## Managed file layout

The caller migration will converge on:

```text
Data/Logs/
  recovery.log
  bootstrap.log
  start_all.log
  comfyui.log
  boot_repair.log
  boot_repair.nohup.log
  auto_deps.log
  ollama.log
  ollama-service.log
  orchestrator.log
  webui.log
  tunnel.log
  cloudflared.log
  r2.log
  rclone.log
```

The canonical file list and per-log policy live in
`Runtime/Logging/log_manifest.json`. WebUI Runtime consumes this manifest instead
of hard-coding paths.

`comfyui.log` and `ollama-service.log` contain raw third-party process output.
The other service files contain EverSpark lifecycle or application records that
follow the structured logging contract.

## Rotation and retention

Rotation uses copy-and-truncate so processes that keep a log file descriptor
open continue writing to the active filename. The default policy is 50 MiB,
five retained files, and fourteen days. High-volume raw process logs use larger
size limits and shorter retention from the manifest.

Inspect or apply the policy with:

```bash
everspark logs status
everspark logs rotate --dry-run
everspark logs rotate
```

The maintenance process takes an exclusive lock. It only manages basenames
declared in the manifest and never follows an arbitrary API-supplied path.

## Runtime status API

EverSpark WebUI exposes:

- `GET /api/health`: compatibility health response for ComfyUI and Orchestrator.
- `GET /api/runtime/status`: service health plus a compact logging summary.
- `GET /api/runtime/logs`: manifest-backed metadata for each managed log.

The API returns filenames, sizes, modification times, rotation counts, and
policy state. It does not return log contents or accept filesystem paths.

## Security and failure behavior

- Field names containing credential, authorization, cookie, password, secret, token, or API-key terms are redacted.
- Matching `key=value` secrets embedded in messages are also redacted.
- Log directories and files are created with modes `0750` and `0640` where supported.
- `ERROR` records go to stderr; other console records go to stdout in the shell adapter.
- A file append failure is reported to stderr without replacing the original command status.
- Tokens, full environment dumps, authorization headers, and private rclone configuration must never be deliberately logged.

## Tests

Run both adapters' tests with:

```bash
bash Tests/Runtime/Logging/run_tests.sh
```

The tests cover text and JSON output, level filtering, compatibility calls,
redaction, step results, invalid configuration, file permissions, manifest
validation, copy-truncate rotation, retention, dry runs, and Runtime status.

## Migration phases

- [x] Canonical naming and `EVERSPARK_*` configuration
- [x] Shell/Python logging foundation and tests
- [x] Critical recovery path: recovery, service, bootstrap, core restore, dependencies, R2, and tunnel
- [x] Long-running services: ComfyUI, Ollama Forge, Orchestrator, WebUI
- [x] Rotation, retention, log manifest, and status API

Each phase must remain independently runnable. Logging migration must not be combined with unrelated dependency or service changes.
