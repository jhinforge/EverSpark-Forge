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

## Third migration batch

| Source | Destination |
| --- | --- |
| `forge-orchestrator/forge_orchestrator/core` | `Orchestrator/orchestrator/core` |
| `forge-orchestrator/forge_orchestrator/core/context_store.py` | `Memory/everspark_memory/store.py` |
| `clients/ollama_client.py` | `ConceptForge/concept_forge/providers/ollama.py` |
| `clients/comfyui_client.py` | `ImageForge/image_forge/adapters/comfyui.py` |
| `workflow/workflow_manager.py` | `ImageForge/image_forge/workflow/manager.py` |

The HTTP context routes are now `/memory/history` and `/memory/clear`. The old
personal workflow JSON was not copied because it referenced private runtime
assets and custom nodes. `ImageForge/Workflows/base_workflow_api.json` is a
tracked empty placeholder and fails with an actionable message until the user
selects a workflow.

## Fourth development batch

This batch adds the first new architecture built on top of the migrated v0.1
chain rather than copying another source directory:

- `ConceptForge/Schemas/character_subject.v1.schema.json` defines the fixed,
  versioned role-subject contract.
- `ConceptForge/concept_forge/subjects` validates, updates, and compiles it.
- Memory stores the current subject plus every immutable revision.
- Orchestrator exposes subject CRUD-style routes and accepts `subject_id` on
  generation tasks.

Persistent subjects contain reusable character identity only. Request-level
scene details are merged at execution time and are not written back into the
subject document.

## Fifth development batch

The old `everspark-webui` behavior was used as a reference for result polling,
image proxying, and local service health checks. The interface itself was
rebuilt around the new module boundaries:

- `WebUI/app.py` provides a standard-library same-origin proxy.
- `WebUI/static` contains the new responsive Forge workspace.
- Character Subject creation, natural-language revision, selection, and
  immutable history are available in the interface.
- Scene generation references `subject_id` without writing scene details into
  structured identity.
- Runtime guidance assumes local mode and treats remote storage and Cloudflare
  as optional integrations.

The public WebUI contains no personal domain, workflow, model asset, or remote
storage configuration.
