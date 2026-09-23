# Configuration

EverSpark is local-first. With no user configuration, storage remains local
and services bind to localhost.

`default.yaml` is the public configuration contract. The migrated shell
foundation continues to accept environment files through `load_config.sh`
until the unified Python configuration loader is introduced.

Configuration precedence is intended to be:

1. Command-line arguments
2. Environment variables
3. User configuration
4. Repository defaults

Optional integrations must be explicitly enabled. Once enabled, incomplete
R2/rclone or Cloudflare settings are treated as errors rather than silently
falling back to local behavior.

## Private configuration import

EverSpark accepts both `.env` and `env.txt`. The latter is a portable alias for
Windows file management and Pod upload workflows; both use the same `KEY=VALUE`
format. The repository includes `Configuration/Import/` as the standard private
upload inbox. Put all configuration files there and run:

```bash
./everspark configure
```

The inbox contents are ignored by Git. `--from <directory>` remains available
when an external source directory is preferred.

When both names are present, their parsed settings must be identical. An
explicit file can be selected with `--env`. The importer never executes the
input as shell code and never moves or deletes the source files.

For a configured Cloudflare backend, the source directory must also contain
`<CF_TUNNEL_UUID>.json`. Its required fields and `TunnelID` are validated, and
the tunnel port must match the EverSpark WebUI port (8780 by default). If
`rclone.conf` is present, it is validated and staged but does not enable a
remote storage policy automatically.

Once `EVERSPARK_STORAGE_BACKEND=rclone` is explicitly selected, `setup`
installs rclone automatically on the supported apt-based Linux runtime.

To enable selective remote model downloads after import, add the following to
the private environment file using paths from the user's own rclone remote:

```text
EVERSPARK_STORAGE_BACKEND=rclone
IMAGE_FORGE_RCLONE_REMOTE=remote:path/models_cold
CONCEPT_FORGE_RCLONE_REMOTE=remote:path/.ollama/models
EVERSPARK_BACKUP_REMOTE=remote:path/everspark-backups
```

The Runtime page then scans Checkpoints, diffusion models, LoRAs, and Ollama
manifests. Ollama identity files outside `models/` are deliberately ignored.
The separate backup root enables manual upload of locally added image models,
direct-download GGUF files, outputs, and timestamped SQLite Memory snapshots.
Uploads never remove remote files. Image models go to the existing image remote
and can be downloaded through the remote model picker. Original GGUF files,
outputs, and Memory snapshots go to the separate backup root; restoring these
backup files is not yet provided in the WebUI.

Private files are normalized to ignored runtime locations:

| Input | Private destination |
| --- | --- |
| `.env` or `env.txt` | `<repository>/.env` |
| `<UUID>.json` | `Data/Configuration/cloudflare/<UUID>.json` |
| `rclone.conf` | `Data/Configuration/rclone/rclone.conf` |

All imported files receive mode `0600`. Cloudflare is inferred only when the
environment contains complete tunnel settings; local mode remains the default
when no private configuration is supplied.
