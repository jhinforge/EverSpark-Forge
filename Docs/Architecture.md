# EverSpark Forge architecture

Orchestrator coordinates tasks between Forges. Concept Forge owns provider/model
execution, Memory and Subject business logic. Image Forge owns its ComfyUI and
Diffusers backends and their execution resources.

| Module | Responsibility | Code |
| --- | --- | --- |
| Portal / Gate | WebUI, HTTP routing, composition, explicit Forge Node bindings | `Archon/Portal/`, `Archon/Gate/` |
| Orchestrator | Task admission and state, Concept → Image coordination, result references | `Archon/Orchestrator/` |
| Concept Forge | Providers, connection tests, conversation, Memory, Subjects, prompt planning | `Legate/Forge/ConceptForge/` |
| Ledger | Long-term persistence, transactions, revision integrity and reads | `Archon/Ledger/` |
| Image Forge | Engines, workflows, checkpoint/VAE/LoRA, plugins, health and generation history | `Legate/Forge/ImageForge/` |
| Storage | Downloads, files, output transfers/cache, upload, sync, backup and restore | `Aegis/Storage/` |
| Vault | Credentials, private provider configuration and runtime configuration | `Archon/Vault/` |
| Steward | Node registration, leases, reported resources, lifecycle and deployment | `Archon/Steward/` |
| Warden / Envoy | Node runtime/process/backend lifecycle and the existing Agent task channel | `Legate/Warden/`, `Legate/Envoy/` |

Gate composes the modules and preserves the existing HTTP API. Orchestrator asks
Concept Forge for an opaque generation instruction, transfers it to Image Forge,
and invokes Concept's completion callback with the result. Concept alone reads,
compiles and updates Subject/Memory through Ledger. Image alone resolves the UI's
legacy resource options. Output file lookup and chunk transfers are provided by
Storage. Orchestrator retains the resulting task references and response.

Forge management code still runs on the local host in distributed mode. Its
existing remote adapters use the unchanged NodeManager / Envoy channel to call
the two remote execution nodes. This migration changes code ownership, not the
registration or task protocol. Concept persistence remains on the host.

Runtime configuration defaults and loading moved to `Archon/Vault/`; the legacy
`EVERSPARK_ORCHESTRATOR_CONFIG` environment variable and Python loader import
remain supported. Existing private provider data stays under
`Data/Configuration/ConceptForge/`, with persistence owned by Vault. The old
`orchestrator.core.server` module is a launcher shim for Gate's HTTP server.

One generation request remains active at a time. A task job's `completed` means
planning and image submission completed; rendering status and history belong to
Image Forge. The existing Orchestrator job map remains in memory. No parallel
scheduler, durable workflow recovery, or automatic generation replay was added.
Audio and Video remain future independent Forge boundaries.

See the [migration inventory](Orchestrator-Boundaries.zh-CN.md) for public method
ownership, changed files, tests, and the verified two-node generation path.
