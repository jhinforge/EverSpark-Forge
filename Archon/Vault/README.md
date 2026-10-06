# Vault

Vault owns credentials, private provider configuration, storage configuration and
runtime configuration loading. `default_config.json` and `runtime_config.py`
provide the Python runtime defaults/loader; the compatibility
`EVERSPARK_ORCHESTRATOR_CONFIG` override remains supported.

`import_config.py` accepts `.env` or the `env.txt` alias, validates input, preserves
originals and writes normalized private settings. The standard inbox is
`Archon/Vault/Import/`. Whole environment imports replace `.env` rather than merge.
`storage_config.py` implements UI rclone import, directory selection, validation
and transactional save/application. At least one Image or Concept source is
required for cloud model storage; the roles can be cleared independently.
`concept_configuration.py` persists model-service connections without exposing
saved keys in API responses. `windows_credentials.py` uses this Windows user's
Credential Manager for Vast and Node secrets.

Typical private destinations are root `.env`,
`Data/Configuration/rclone/rclone.conf`, `Data/Configuration/cloudflare/` and
`Data/Configuration/ConceptForge/connections.json`. File permissions are tightened
where supported. A character/Memory ZIP excludes these secrets.

See [Configuration](../../Docs/Configuration.md) and
[Runtime and data](../../Docs/Runtime-and-Data.md). Tests: `Tests/Configuration/`.
