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
