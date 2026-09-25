# Runtime and data lifecycle (v0.1)

This guide shows what comes from source, what remains on the current cloud Linux machine, and what you must transfer when moving machines. See [Getting started](Getting-Started.md) and [Configuration](Configuration.md).

## 1. Source to running services

```text
Clone source → setup installs runtimes and starter models → start services
             → discuss and generate in WebUI → write data on this machine
             → export or upload as needed → install and restore elsewhere
```

`./everspark setup --plan` lists downloads and destinations without changing the machine. `setup` creates runtime directories, installs managed ComfyUI and Ollama, configures Python and model paths, and prepares starter models. `start` launches Concept Forge, Image Forge, Orchestrator, and WebUI in order; `status` checks health. Services bind to localhost by default. For cloud access, use the SSH forwarding instructions from `./everspark access`, or opt in to a temporary public URL with `./everspark share` after WebUI starts. Stop sharing with `./everspark share stop` after the demo; the link does not back up any data.

Process identities and state are recorded under `Data/Runtime/Services/`. `./everspark stop` stops launcher-managed services; a healthy service started externally is marked external and is not treated as a launcher-owned process.

## 2. Where files live

Paths are relative to the repository root. Private data and installation artifacts are not shipped with public source.

| Content | Default location | When migrating |
| --- | --- | --- |
| Code and public workflows | Git repository; `ImageForge/Workflows/` | Clone again; separately save uncommitted custom workflows |
| Private environment settings | Root `.env` | Save separately or import `env.txt` on the new machine |
| Remote storage, Tunnel and model service credentials, path mappings | `Data/Configuration/` | Save original credentials and mappings or configure again |
| Managed ComfyUI and Ollama; optional Diffusers worker, virtual environments, process state | `Data/Runtime/` | Usually rebuild with `setup`; install the optional plugin again in Forge |
| Image models | `Data/Models/ImageForge/` | Redownload or selectively pull from your remote library |
| Concept Forge models | `Data/Models/ConceptForge/` | Redownload or restore and import into Ollama as needed |
| Conversations, tasks, character associations | `Data/Memory/everspark.db` | Back up and restore with subjects; JSON alone loses these links |
| Character documents | `Data/Subjects/` | Back up and restore with the Memory database |
| Local data ZIP staging | `Data/Runtime/Archives/`, `Data/Imports/` | Used while preparing a download or receiving an upload; cleaned up after transfer or processing, not durable backups |
| Generated images | `Data/Outputs/` | Export its ZIP from Gallery or upload the whole folder |
| Service logs | `Data/Logs/` | Preserve for diagnosis if needed; recreated on the new machine |
| Previous local data before restoration | `Data/Recovery/` | Created during character restore; remains only on this machine |

Git ignores `.env`, private `Configuration/Import/` uploads, and `Data/`. **Ignored by Git does not mean backed up.** Confirm data has left an ephemeral cloud disk before deleting the instance.

## 3. What happens during generation

In Discuss, Concept Forge updates the current conversation's character subject and Memory retains its documents and revisions. In Generate, stable character traits combine with this request's scene direction; Orchestrator submits to Image Forge, and WebUI displays results. Model, workflow, checkpoint, VAE, and LoRA choices depend on available resources on the current machine.

The default language model is Ollama; Forge can select a tested OpenAI Compatible connection from **Model services**. ComfyUI is the default drawing engine; Diffusers can be installed and selected in Forge. Gallery shows recent images; **Download outputs ZIP** packages the entire `Data/Outputs` tree. This is a manual export: merely viewing Gallery does not move images off the cloud machine.

## 4. Back up what you need

Without rclone, you can still use **Storage → Character and Memory ZIP → Download data ZIP** for a consistent SQLite snapshot and four JSON files per character: `subject.json`, `metadata.json`, `positive_prompt.json`, and `negative_prompt.json`. Save the downloaded file on your own computer or another persistent location. Save private configuration, including `Data/Configuration/ConceptForge/connections.json` if you configured model services, models, and the Gallery output ZIP separately; the data ZIP excludes credentials, models, and generated images.

With rclone enabled and verified, initiate uploads under **Storage → Upload local data**:

1. Select model categories and a real writable remote upload destination.
2. **Outputs folder** uploads all currently found files in `Data/Outputs`; you do not select images individually. New files require another manual upload.
3. Select **Save a new Memory database snapshot** for character data. Character JSON and SQLite are uploaded as one batch with verification information. Choosing character files in the UI also causes the backend to handle the complete dataset.
4. Wait for the task to complete and check the remote destination or restore point. Configuring a remote, scanning models, or starting services does not upload data automatically.

Absent `EVERSPARK_BACKUP_REMOTE`, the first image model source bucket uses an `everspark-backups` prefix. Output and character backups go there; models use their respective remote category directories. Uploads do not delete older remote files.

## 5. Moving to another cloud machine

1. Clone source on a Linux machine with an NVIDIA GPU and network access.
2. To keep remote resources or a Tunnel, upload original `env.txt`, `rclone.conf`, and Tunnel credentials into `Configuration/Import/`, then run `./everspark configure`. Manual remote path mappings saved in Storage live in `Data/Configuration/rclone/model_paths.json`; transfer that file separately or re-enter those mappings. Re-enter model services in WebUI or transfer `Data/Configuration/ConceptForge/connections.json` securely; the character ZIP does not include it.
3. Run `./everspark setup --plan`, `./everspark setup`, `./everspark doctor`, and `./everspark start`; confirm services are ready.
4. Pull required models from remote Storage, or redownload by direct URL. Check compatibility with the selected workflow.
5. For a downloaded EverSpark data ZIP, choose it under **Storage → Character and Memory ZIP** and click the adjacent **Validate and restore** button (maximum uploaded ZIP size: 128 MiB). The file is staged in `Data/Imports/`. The system checks its manifest and hashes, SQLite integrity, and agreement between character documents and the database before replacing the current subjects and Memory database. It saves the previous data in `Data/Recovery/` and removes the staged ZIP. Alternatively, select a remote restore point under **Storage → Restore character data**. Restart EverSpark after either restore.
6. Transfer outputs separately: download a ZIP from Gallery on the old machine or retrieve previously uploaded files using your own storage tools. These WebUI restore actions restore **character data snapshots only**, not outputs.

Neither source nor default setup contains your characters, history, outputs, or private models. A complete move depends on exporting or backing these up before the old machine disappears.

## 6. Status and logs

```bash
./everspark status
./everspark doctor
./everspark restart image
./everspark stop
```

`status` checks processes and health endpoints; `doctor` checks basic tools, enabled backends, and GPU visibility. WebUI **Runtime** shows readiness. Managed service output goes to `Data/Logs/`. For failed generation or transfers, check the task error and service status, then the corresponding logs. Logs help diagnose failures but are not backups.

See [service management](Commands.md#2-service-management) for `start|stop|restart|status` behavior and [log maintenance](Commands.md#5-log-status-and-maintenance) for retention and rotation commands.
