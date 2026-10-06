# Configuration

Cloud storage is disabled by default. The Windows control host does not need GPU models installed locally. Configure Node connectivity using [Getting started](Getting-Started.md).

## Model services

Under **Settings → Model services**, enter a name, the provider's API base URL (usually ending in `/v1`), exact model ID and API Key. Test and save, then select the connection in Creation. The system does not enumerate every remote model automatically.

The adapter uses OpenAI Compatible Chat Completions. Selected upstream errors can trigger response-mode retries; authentication failures do not. The host calls APIs directly and does not forward keys to the Concept Node. Connections persist in `Data/Configuration/ConceptForge/connections.json`; saved keys are not returned by the API. For Ollama, choose a deployed Concept Node instead.

## Cloud model library

1. Open **Settings → Cloud storage configuration → Enable cloud storage**.
2. Choose your `rclone.conf` and **Import connection**. No `.env` or Cloudflare credential is required for this UI workflow.
3. If rclone cannot be found, enter its actual path, for example `C:\rclone\rclone.exe`. It is not bundled in the client.
4. Browse a connection and choose **Use for image models** or **Use for Concept models**. Images support multiple sources.
5. Select at least one model directory, then **Validate and enable**. The two roles are independent; unconfigured roles are not scanned. An existing Concept selection can be removed.
6. Return to **Resources**, scan and select models, then pull to the corresponding Forge Node. Transfers execute on the Node rather than staging models on the host.

An image path may be a library root or a category such as checkpoints, loras or vae. Choose the model type for custom category names. Do not assume another `checkpoints` level is always appended. Native Ollama directories normally contain `manifests` and `blobs`; independent GGUF files are also discoverable.

Example structures are `r2-assets:comfyui-assets/models_cold` and `r2-assets:ollama-forge/.ollama/models`. Substitute your own remotes and paths. Multiple image sources create a read-only union; uploads require a real writable destination.

Backup destinations differ from model sources. Set `EVERSPARK_BACKUP_REMOTE` explicitly if needed; otherwise the configured image or Concept source determines the backup prefix. Scanning is not automatic backup, and a readable source need not be writable.

## Private configuration and source import

`.env` and `env.txt` share the same `KEY=VALUE` format. Place the file and any required `rclone.conf` in `Archon/Vault/Import/`, then run at the repository root:

```powershell
.\everspark.cmd configure
```

Linux uses `./everspark configure`. Import preserves the originals and writes private settings. A complete environment import replaces the root `.env`; it does not append keys. Use `--from DIRECTORY` or `--env FILE` to select the source. Restart affected services; existing process environment values may override file values. See the [configuration example](../.env.example), but do not import every example field unchanged.

Saving cloud settings in the UI updates the host runtime immediately. Old Pod model-storage processes still need updating and restarting; see [Updating](Updating.md).

## Optional Cloudflare and Linux managed mode

Named Tunnel uses `EVERSPARK_NETWORK_BACKEND=cloudflare`, `CF_TUNNEL_UUID`, `CF_HOSTNAME`, `CF_LOCAL_PORT` and matching UUID credentials. Its port must match the actual WebUI. Desktop ports are dynamic; do not blindly copy port 8780 into tunnel settings.

In Linux single-machine mode, `./everspark share` provides a separate temporary sharing option without Named Tunnel credentials. WebUI has no application login; stop sharing after use. Distributed first use relies on Tailscale and does not require Cloudflare.

See [Runtime and data](Runtime-and-Data.md) for storage locations, credentials and backups.
