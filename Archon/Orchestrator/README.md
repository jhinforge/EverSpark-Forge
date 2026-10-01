# Orchestrator

Orchestrator coordinates tasks between Forges. It receives generation requests,
maintains task admission and status, passes Concept Forge's instruction to Image
Forge, and returns task result references. Its public API is `submit`,
`start_task`, and `task_job`. `TaskRunner.run` implements the existing serial
Concept → Image pipeline through injected Forge interfaces.

Concept Forge owns conversations, Memory, Subjects, prompt planning, provider
selection, and connection tests. Image Forge owns its engines, workflows,
checkpoints, VAE, LoRA, plugins, health and generated history. Aegis/Storage owns
resource downloads, output-file transfers, archives, backups and restores.
Ledger provides long-term persistence; Vault stores private configuration.

## Existing entry points

`./everspark orchestrator start` still starts the existing HTTP service, and
`./everspark orchestrator console` still opens its console. The HTTP implementation
is now `Archon/Gate/application_server.py`; the old Python server module is a
launcher compatibility import. Gate's `GateApplication` composes the modules and
forwards the existing routes to their owners. HTTP URLs and WebUI response shapes
are preserved, including `/tasks`, `/tasks/start`, `/tasks/jobs`, `/conversation`,
`/subjects/*`, `/memory/*`, `/concept/connections/*`, `/image/*`, `/storage/*`,
`/downloads/*`, `/backup/*` and `/data/*`.

The shared runtime configuration loader and default JSON now belong to
`Archon/Vault/runtime_config.py` and `Archon/Vault/default_config.json`.
`EVERSPARK_ORCHESTRATOR_CONFIG` and the old loader import remain supported for
existing installations. Generation options from the existing UI are forwarded
unchanged by Orchestrator and interpreted only inside the responsible Forge.

## Distributed execution

Gate retains explicit Concept and Image Node bindings. The corresponding Forge
adapters retain the existing Archon NodeManager / Envoy task channel. Selecting
a Forge Node locates an execution target; selecting its internal resources is
owned by that Forge. Orchestrator owns neither Node registration nor runtime
lifecycle state.

One generation request remains active at a time. A generation job's `completed`
status means Concept planning and Image submission completed; image rendering
status and gallery history are queried from Image Forge. Task result references
remain in Orchestrator's existing in-memory job map. This responsibility migration
does not add durable workflow scheduling, automatic generation replay, or parallel
execution. See [the migration inventory](../../Docs/Orchestrator-Boundaries.zh-CN.md)
for module responsibilities, public APIs, changed files and validation.
