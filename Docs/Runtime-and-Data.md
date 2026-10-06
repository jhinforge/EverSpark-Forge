# Runtime and data

In distributed mode, not all data lives in the host's `Data/`. These are default locations; environment settings may override them.

## Ownership and locations

| Content | Location | Preservation |
| --- | --- | --- |
| Code and public workflows | Git checkout | Git or released source |
| Characters and Memory | Host `Data/Subjects/`, `Data/Memory/everspark.db` | Asset library character/Memory ZIP |
| Model API and rclone configuration | Host `Data/Configuration/` | Separate private backup |
| Environment settings | Host `.env` | Separate backup; excluded from Git |
| Vast API Key | Windows user's Credential Manager | Re-enter on another computer |
| Node/binding index | Normally `%LOCALAPPDATA%/EverSpark/`; overridable by `EVERSPARK_NODE_STATE` | Host state; revalidate Node identity/connectivity when moving |
| Rental Tailscale auth key | Current host session | Configure again before new rentals after restart |
| Portable Python / WebView2 | Client `Runtime/`; standard omits fixed WebView2 | Recreate from release package |
| Browser profile and desktop logs | Client `Data/Runtime/WebView2/`, `Data/Logs/client/` | Preserve if needed |
| Image models/results | Execution Node `Data/Models/ImageForge/`, `Data/Outputs/` | Pull models again; export outputs |
| Concept models | Execution Node `Data/Models/ConceptForge/` | Download/pull and import as needed |
| Audio runtime/models/results | Audio Node; adapter configuration determines paths | Redeploy weights; export outputs |
| Agent state/logs/network results | Normally Node `/workspace/everspark-node/` | Preserve relevant diagnostics |

Git exclusion is not backup. Copying a client folder does not automatically transfer Windows Credential Manager, Tailscale identity or external Node state directories.

## Three ZIP types

| ZIP | Includes | Excludes |
| --- | --- | --- |
| Image outputs | Corresponding Image Node's image outputs | Other Nodes, audio, characters, models and secrets |
| Audio outputs | Corresponding Audio Node's audio outputs | Images, characters, models and secrets |
| Character/Memory data | Four character JSON documents and consistent SQLite snapshot | Media, models, API keys and private configuration |

Character documents are `subject.json`, `metadata.json`, `positive_prompt.json` and `negative_prompt.json`. Restore validates the manifest, hashes, SQLite integrity and data consistency; arbitrary ZIPs are not accepted. Uploads are limited to 128 MiB. Previous data is saved under host `Data/Recovery/`; restart the host after restoration.

Data ZIPs use host-side archiving. Remote media ZIPs are packaged on the Pod and downloaded through temporary URLs. Cancellation does not delete generated outputs.

## Media access and lifetime

Result endpoints return references and URLs; originals remain on their execution Nodes. The Node file service binds to an available local Tailscale address and uses expiring signatures; bind and advertised addresses are handled separately. Individual files have a forwarding fallback. Remote ZIP downloads use the temporary Node URL, not the former host-forwarded ZIP path.

Refresh Asset library after URL expiry. Temporary archives are cleaned according to service policy and are not durable backups. Originals are inaccessible while their Pod is offline; save required files before destruction. Stopping the host does not destroy Pods.

## Cloud backup and migration

Scanning and model pulls do not automatically back up data. Submit uploads/restores explicitly, choose a writable destination and wait for completion. Characters and Memory are handled as complete snapshots; outputs and models require separate preservation.

Before changing computers, export character/Memory data, download media and back up private configuration. Configure accounts and Tailscale on the new host, restore data and revalidate Node connectivity. Rebuilding a Pod requires deploying Forges and models again. Restoring a character ZIP does not recover media automatically.

See [Updating](Updating.md) and [Configuration](Configuration.md).
