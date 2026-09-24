# First run: EverSpark Forge (v0.1)

This guide targets a **cloud Linux x86_64 machine with an NVIDIA GPU**. The author's full test used the base image `nvidia/cuda:12.8.0-cudnn-runtime-ubuntu22.04`. Running the stack locally on Windows has not been verified; Windows can be used for the browser and SSH client.

EverSpark Forge ships as source code. The first `setup` installs managed runtimes and downloads starter models over the network; allow time and disk space for both. You can also connect your own models and remote storage. **R2, Cloudflare, and private configuration files are not required for the default local mode.**

## 1. Prepare the machine

- Linux x86_64 with an NVIDIA GPU, network access, `bash`, `python3`, and `git`.
- Space for runtimes and models; inspect sources and destinations with `setup --plan` first.
- Browser access from your own computer can use SSH forwarding or an optional temporary Cloudflare link.

The base image's CUDA version differs from the PyTorch CUDA build installed by EverSpark. The source selects `cu126` or `cu128` from **NVIDIA driver capability and GPU architecture**; it consults the base image CUDA runtime only if driver capability cannot be read. Blackwell GPUs require a driver supporting CUDA 12.8 and the `cu128` profile.

## 2. Start from source without private configuration

Run on the cloud machine:

```bash
git clone https://github.com/jhinforge/EverSpark-Forge.git
cd EverSpark-Forge
./everspark setup --plan
./everspark setup
./everspark doctor
./everspark start
./everspark status
```

`setup --plan` lists intended runtimes, model sources, and local destinations without changing the machine. `setup` creates the Git-ignored `Data/` directory, installs managed ComfyUI, Ollama, and Python environments, downloads starter models, and imports the Concept Forge model into Ollama. Check the plan for actual download sizes and destinations.

`doctor` checks basic commands, configuration, and GPU visibility. `start` launches Concept Forge, Image Forge, Orchestrator, and WebUI in dependency order. `status` checks their health. If setup fails, fix the reported dependency or network issue and rerun it. An accessible WebUI alone does not establish that the models are ready for generation.

For options, effects, and file changes see the command reference for [installation](Commands.md#1-initialization-configuration-and-installation) and [service management](Commands.md#2-service-management).

Without `.env`, storage stays on the machine running EverSpark and services bind to localhost by default. On that machine, open `http://127.0.0.1:8780`.

## 3. Access the cloud WebUI from your computer

### Temporary link without SSH

On the cloud machine, after `./everspark start` succeeds, run:

```bash
./everspark share
```

Open the printed `https://*.trycloudflare.com` URL on your computer. This
optional Quick Tunnel requires no `.env`, Cloudflare account, domain, SSH key,
or tunnel credentials; the cloud machine must still reach Cloudflare. If
`cloudflared` is missing, the command uses the existing installer (which
requires root and network access for the download). View the link again with
`./everspark access` or `./everspark share status`; close it with
`./everspark share stop` or `./everspark stop`. A new sharing session may have
a different URL. Quick Tunnel startup is rejected if `~/.cloudflared/config.yaml`
or `config.yml` exists. For failure details check `Data/Logs/quick-tunnel.log`
(or `EVERSPARK_LOG_DIR` when configured). The WebUI has no login protection:
anyone holding this URL can use it. Use this option for short tests or demos,
not public deployment.

### First-time SSH key setup (optional)

**Already able to SSH into this cloud machine from your computer? Skip to [Get and run the forwarding command](#get-and-run-the-forwarding-command).** Otherwise, open Windows PowerShell or a Linux/macOS terminal **on your own computer** and run:

```bash
ssh-keygen -t ed25519 -C "everspark-cloud"
```

Choose a location and passphrase at the prompts; first-time users can accept the default path. **Do not overwrite an existing private key** if prompted: use that key or choose another filename. This creates a private key such as `id_ed25519` and a public key ending in `.pub`. Display the **public key**:

| Terminal on your computer | Command (default filename) |
| --- | --- |
| Windows PowerShell | `Get-Content "$HOME/.ssh/id_ed25519.pub"` |
| Linux/macOS | `cat ~/.ssh/id_ed25519.pub` |

Add the public key's **entire line** to your cloud environment's SSH public key settings. If it has no such setting, add it to the target account's `~/.ssh/authorized_keys` using that machine's administration method. **Keep the private key on your computer; never upload it to the cloud, paste it into a public key field, or commit it to the repository.**

Test login from your own computer, substituting the actual username, public address, and mapped SSH port:

```bash
ssh -p 22 root@example.com
```

For a non-default key path, add `-i PATH_TO_PRIVATE_KEY` to the `ssh` command. If login fails, check the cloud environment's public address, mapped port, username, and registered public key. After successful login, type `exit` to return to your local terminal.

### Get and run the forwarding command

`./everspark start` prints access instructions. Print them again at any time:

```bash
./everspark access
```

If the cloud environment supplies connection information the launcher recognizes, the output includes the complete SSH forwarding command. **Run that command on your own computer**; add `-i PATH_TO_PRIVATE_KEY` to it if you use a non-default key file. Keep the SSH session open and visit the local browser address shown (normally `http://127.0.0.1:8080`). The cloud machine's `127.0.0.1:8780` is not an address on your computer.

See [WebUI access commands](Commands.md#3-webui-access-and-temporary-sharing) for all `access` and `share` options and stop behavior.

If the platform does not supply that information, set `EVERSPARK_SSH_HOST` and `EVERSPARK_SSH_PORT` in your private `.env` (and `EVERSPARK_SSH_USER` if needed), then rerun `./everspark access`. Forwarding requires SSH access to the machine.

## 4. Generate your first image

1. In WebUI, check **Runtime** for ready services. If anything is unavailable, run `./everspark status`.
2. In **Forge**, describe a character in **Discuss** to create the current character subject, or select an existing subject and click **Use in Forge**.
3. Check the available **Workflow**, **Checkpoint**, and **Concept LLM** resources. The starter installation supplies models and an API Format workflow.
4. Switch to **Generate**, enter a scene, submit, and wait for the result in the page.
5. Inspect recent results in **Gallery**. **Download outputs ZIP** packages the entire `Data/Outputs` directory.

A reusable character's stable traits are separate from the scene, pose, and camera direction for a particular request.

## 5. Import existing private configuration first (optional)

Upload any files you need into `Configuration/Import/`:

| File | Use |
| --- | --- |
| `env.txt` or `.env` | Custom endpoints, remote storage, or Cloudflare Tunnel settings; identical content format |
| `rclone.conf` | Existing rclone/R2 connection |
| `<CF_TUNNEL_UUID>.json` | Cloudflare Named Tunnel credentials |

Then run from the repository root:

```bash
./everspark configure
./everspark setup --plan
./everspark setup
./everspark doctor
./everspark start
```

`env.txt` is a convenient name for viewing, saving, and uploading `.env` contents on your own machine: both use the same `KEY=VALUE` format. `configure` validates and copies it to the Git-ignored root `.env`, leaving the uploaded original in place. Importing `rclone.conf` **does not activate** remote storage: set `EVERSPARK_STORAGE_BACKEND=rclone` and the required remote paths explicitly. Cloudflare likewise needs complete configuration. See [the configuration guide](Configuration.md), [`Configuration/README.md`](../Configuration/README.md), and [`.env.example`](../.env.example).

If `doctor` reports remote paths or credentials, fix the enabled backend before starting. The repository ignores private configuration and `Data/`; do not force-add credentials or personal data to Git.

## 6. Daily commands and diagnosis

```bash
./everspark status
./everspark access
./everspark share status
./everspark share stop
./everspark restart image
./everspark stop
```

Managed service logs are in `Data/Logs/`. If WebUI opens but generation fails, check Runtime, `./everspark status`, available models, and the relevant service log. Rerun `./everspark doctor` for environment and configuration checks. Other cloud images and local Windows deployments have not been verified.

See the [starter model commands](Commands.md#4-manifest-starter-models) and [log commands](Commands.md#5-log-status-and-maintenance) for their separate scopes.
