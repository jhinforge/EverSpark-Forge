# Configure EverSpark Forge (v0.1)

This guide covers the default local mode, private configuration, models, remote storage, and network access. See [Getting started](Getting-Started.md) for installation. “Local” means on the machine running EverSpark, including when that machine is in the cloud.

## 1. Without configuration files

Run `./everspark setup` and `./everspark start` from source. Storage stays local, services bind to localhost, and R2/rclone and Cloudflare Tunnel remain disabled. Models, outputs, memory, and runtime files live under the Git-ignored `Data/` directory. The WebUI **Storage** page can download compatible models from public direct URLs without remote storage. For cloud access, use SSH forwarding as printed by `./everspark access`, or run `./everspark share` after WebUI starts for a temporary public link. The latter needs no SSH key, `.env`, Cloudflare account, or Named Tunnel credentials, but exposes a WebUI with no login protection. Close it with `./everspark share stop`. Neither option requires the Named Tunnel below; see [Getting started](Getting-Started.md).

## 2. Private environment files

`env.txt` and `.env` use **exactly the same `KEY=VALUE` format**. The `env.txt` filename makes it convenient to view, save, and upload from your own computer. `./everspark configure` imports it as the repository root `.env`. If both names exist in the import directory, their parsed settings must agree; normally keep one.

Use `.env.example` as a field reference; **do not import the entire example unchanged**. Include only settings you need. A partial set of Cloudflare fields, even for an integration you do not intend to use, can fail validation.

For example, to provide SSH details when the cloud platform does not supply them:

```dotenv
EVERSPARK_SSH_HOST=example.com
EVERSPARK_SSH_PORT=22
EVERSPARK_SSH_USER=root
```

Replace these with your actual connection details. Quote values containing spaces correctly. Do not define the same key twice in a file or commit passwords, tokens, and private remote paths.

## 3. Import and update

Place `env.txt` **or** `.env` in `Configuration/Import/`, then run:

```bash
./everspark configure
./everspark setup --plan
./everspark setup
./everspark doctor
./everspark start
```

Uploaded files remain in the inbox. The root `.env` is ignored by Git; required credentials are copied into `Data/Configuration/` with permissions restricted to the current user. To update settings, upload the **complete** environment file and rerun `configure`: it replaces the root `.env` rather than merging new keys into old values. Use `--from <directory>` for another source directory or `--env <file>` to explicitly select one of two conflicting environment files. Restart affected running services with `./everspark restart` after changing their configuration.

See the [command reference for initialization and configuration](Commands.md#1-initialization-configuration-and-installation) for options and effects of `configure`, `setup`, and `doctor`.

## 4. Models, workflows, and outputs

**Models are not part of the source release.** Default setup downloads starter models. Later you can download an image model or Concept Forge GGUF by public direct URL in **Storage**. Enable rclone only if you need a remote model library. Select installed resources in Storage instead of listing each checkpoint or LoRA in your environment file.

| Content | Default location |
| --- | --- |
| Image models | Category directories under `Data/Models/ImageForge/` |
| Concept Forge models | `Data/Models/ConceptForge/Ollama/` |
| Outputs | `Data/Outputs/`; Gallery exports the entire directory as a ZIP |
| Workflows | API Format JSON and adjacent manifests in `ImageForge/Workflows/` |

WebUI selects registered workflows and installed models. Advanced users can point `EVERSPARK_WORKFLOW_TEMPLATE` to another API Format workflow. See [Image Forge](../ImageForge/README.md) for manifests and node requirements. A regular ComfyUI interface workflow is not directly executable as an API Format file. Character subjects, memory, and outputs are runtime data: save what you need before replacing a cloud machine. A model source URL never enables automatic backups.

## 5. rclone remote storage (optional)

Place your existing `rclone.conf` and `env.txt` in `Configuration/Import/`. Explicitly enable the backend and set both model scanning roots:

```dotenv
EVERSPARK_STORAGE_BACKEND=rclone
IMAGE_FORGE_RCLONE_REMOTE=myremote:path/to/image-models
CONCEPT_FORGE_RCLONE_REMOTE=myremote:path/to/ollama-models
```

The `myremote:` name must match your `rclone.conf`; replace all example paths. `configure` imports the file to `Data/Configuration/rclone/rclone.conf` and sets `RCLONE_CONFIG` in the generated `.env`. Importing `rclone.conf` alone **does not enable remote storage**. With the backend explicitly enabled, setup installs rclone on supported apt-based Linux systems.

These remote addresses are **scanning roots**. Storage discovers model categories below them; save manual paths and writable upload destinations in the UI for unusual layouts. Read-only or aggregate remotes can be scanned, but uploads require a real writable destination.

To choose a writable destination for outputs and character backups, optionally add:

```dotenv
EVERSPARK_BACKUP_REMOTE=myremote:path/to/everspark-backups
```

Otherwise the system attempts an `everspark-backups` prefix in the first image model source bucket. Outputs synchronize as a whole folder; character JSON and SQLite are uploaded and restored in verified batch snapshots. Uploads do not delete existing remote files. After importing and installing, run `./everspark doctor` to check remote access.

## 6. Cloudflare Named Tunnel (optional)

The following persistent entry point uses your own hostname and credentials. The temporary `./everspark share` link does not import these files and does not start automatically with `./everspark start`.

For an existing Named Tunnel, import `<CF_TUNNEL_UUID>.json` with `env.txt` and complete settings:

```dotenv
EVERSPARK_NETWORK_BACKEND=cloudflare
CF_TUNNEL_UUID=your-tunnel-uuid
CF_HOSTNAME=your.domain.example
CF_LOCAL_PORT=8780
```

Use your real UUID and hostname. The credential JSON `TunnelID` must match. `CF_LOCAL_PORT` must equal the WebUI listen port (default `8780`). The importer validates and copies credentials into `Data/Configuration/cloudflare/`; the launcher then manages the Tunnel. Omit `CF_*` fields when not using it.

## 7. Source and personal data

| Suitable for source control | Keep private or back up separately |
| --- | --- |
| Code, public examples, shareable workflows | `.env`, `env.txt`, `rclone.conf`, Tunnel credentials |
| Public configuration field descriptions | Models, outputs, subjects, and memory under `Data/` |

`.gitignore` excludes `.env`, private imports under `Configuration/Import/`, and `Data/`. Ignored files are not backups; do not force-add them to a public repository. See [`Configuration/README.md`](../Configuration/README.md) for importer details and [`.env.example`](../.env.example) for optional fields.
