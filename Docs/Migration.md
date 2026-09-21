# Migration Baseline

EverSpark Forge is being extracted from `jhinforge/gpu-bootstrap` rather
than copied wholesale.

## Authoritative source

- Branch: `feature/everspark-webui-v1`
- Commit: `606640c`

No implementation is merged from `main` or `core-refactor`. Their history may
be consulted to understand earlier decisions, but the WebUI branch is the sole
code baseline.

## Migration rules

1. Preserve tested behavior before reorganizing internals.
2. Replace personal paths, domains, remote names, and credentials with user
   configuration.
3. Keep local storage and localhost networking as safe defaults.
4. Treat ComfyUI, Ollama, rclone/R2, and Cloudflare as adapters, providers, or
   optional backends.
5. Run the relevant source tests after every migrated layer.

## First foundation batch

| Source | Destination |
| --- | --- |
| `core/config` | `Configuration` |
| `core/logging` | `Runtime/Logging` |
| `core/storage` | `Infrastructure/Storage` |
| `core/network` | `Infrastructure/Network` |
| `core/utils/common.sh` | `Shared/Shell/common.sh` |

The first batch intentionally preserves the existing `core_*` shell function
names as a compatibility boundary. Public commands and module names use the
new EverSpark naming scheme; internal function renaming can happen after the
full execution chain is migrated and covered by tests.

## Second foundation batch

| Source | Destination |
| --- | --- |
| `core/hardware` | `Runtime/Hardware` |
| `core/system` | `Runtime/System` |
| `core/cli/everspark` | `Launcher/everspark` and repository-root `everspark` |
| `core/cli/install.sh` | `Launcher/install.sh` |

The new public CLI uses capability names (`image`, `concept`, `orchestrator`,
and `webui`) without exposing legacy backend names as command aliases. `init`
creates local runtime directories, while `doctor` validates the base runtime
and fails when an explicitly enabled rclone or Cloudflare backend is
incomplete.
