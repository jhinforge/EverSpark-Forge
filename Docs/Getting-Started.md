# Getting started with EverSpark Forge

EverSpark Forge is a distributed AI OS. The host handles control and orchestration; selected Forge Nodes execute model tasks. This guide follows the tested Windows host and Linux NVIDIA GPU Pod setup.

## 1. Choose a launcher

| Launcher | Requirements | Entry point |
| --- | --- | --- |
| Windows standard ZIP | Windows x64, installed WebView2 | Extract and double-click `EverSpark.exe` |
| Windows full ZIP | Windows x64; fixed WebView2 included | Extract and double-click `EverSpark.exe` |
| Windows source | Git and Python 3.11.9 | PowerShell: `.\everspark.cmd archon start` |

Both ZIPs include portable Python; neither requires a separate Python installation. Models, Tailscale, SSH and rclone are not bundled. Choose full when WebView2 is absent. The software is free; GPU rental, bandwidth and third-party model services may incur charges.

Download v0.2.0: [standard ZIP](https://github.com/jhinforge/EverSpark-Forge/releases/download/v0.2.0/EverSpark-Forge-0.2.0-windows-x64-standard.zip) or [full ZIP](https://github.com/jhinforge/EverSpark-Forge/releases/download/v0.2.0/EverSpark-Forge-0.2.0-windows-x64-full.zip). [Release notes and SHA-256 files](https://github.com/jhinforge/EverSpark-Forge/releases/tag/v0.2.0). GitHub's Source code downloads contain source, not the portable Windows client. The current development branch is `refactor/distributed-architecture`. Successful Windows portable client Actions runs provide both ZIPs and SHA-256 files. Actions artifacts are temporary test distribution, not permanent release URLs.

Extract the chosen ZIP completely into a writable directory such as `D:\EverSpark-Forge`, then run the EXE. Do not run inside the ZIP. For an Actions artifact, unpack the outer artifact first, then extract its standard or full ZIP. An open window means the host started; generation still requires ready Forges.

### Start from source

Run on your Windows computer:

```powershell
git clone --branch refactor/distributed-architecture https://github.com/jhinforge/EverSpark-Forge.git
cd EverSpark-Forge
python --version
.\everspark.cmd archon start
```

Open the printed Portal URL, normally `http://127.0.0.1:8780/`. Keep the terminal running; Ctrl+C stops it. Avoid running the CLI host and desktop client together. The desktop client assigns dynamic loopback ports; use its window rather than assuming port 8780.

### SSH tools and existing machines (when needed)

OpenSSH is not bundled. SSH deployment/connectivity fallback requires `ssh` and `ssh-keygen` on the host; check `ssh -V` in PowerShell. New automatic Nodes normally need no manual login. For existing machines or direct SSH, use the provider's actual user, address, port and public-key registration entry.

To create your own key, run `ssh-keygen -t ed25519 -C "everspark-cloud"` locally without overwriting an existing private key. Display the default public key with `Get-Content "$HOME/.ssh/id_ed25519.pub"` and register its complete line. Keep the private key locally. This manual flow differs from EverSpark's automatically managed deployment identity; do not replace its identity files arbitrarily.

## 2. Configure accounts and Node connectivity

1. Open the [official Tailscale Windows download page](https://tailscale.com/download/windows), install Tailscale on the Windows host, then sign in and connect to your tailnet.
2. In **Settings → Accounts and Nodes**, enter your Vast API Key and click **Verify and save**. It is stored in this Windows user's Credential Manager.
3. Using the same Tailscale account as the Windows host, open the [Auth Key management page](https://console.tailscale.com/admin/settings/keys) and select **Generate auth key**. Enable **Reusable** if you want to rent multiple Pods with the same key; a one-off key is sufficient for one new Pod. Set an expiry, select **Generate key**, and copy the complete generated key.
4. Return to **Automatic Node connection** in EverSpark and enter that **Auth Key** (normally beginning with `tskey-auth-`), rather than a Tailscale API Key. It lets Pods join the host's tailnet. Match single-use or reusable mode to the key's Reusable setting; a long expiry does not imply reuse.
5. Click **Configure automatic connection** and confirm readiness. This key is held for the current Archon session only. Configure it again before renting new Pods after restarting the client. Existing Nodes have independent identities.

For details on key options, see the [official Tailscale Auth Key guide](https://tailscale.com/docs/features/access-control/auth-keys).

Tailnet policy and the Windows firewall must permit Nodes to reach the host's reported Agent port (default TCP 8766) and permit the host to access Node media services. Allowing only registration can leave playback and direct downloads inaccessible; media services use dynamic ports.

## 3. Rent a Pod and deploy Forges

1. In **Compute → Rent GPU**, choose GPU, region and disk filters, then search offers. Searching does not rent anything. Review the cost and machine requirements before renting.
2. In **Compute → My machines**, wait for the Pod and Node Agent to become online. New automatic Pods join Tailscale and start their Agent through the startup flow; an initial manual SSH session is normally unnecessary.
3. If the optional network test requests Ookla terms confirmation, review and decide in the UI. Testing does not block Forge deployment.
4. Deploy the required Concept, Image or Audio Forge from the machine card. Select its machine as the corresponding execution Node after deployment, source verification and health checks succeed.

Forges may share a machine or use separate machines. Shared deployment does not guarantee enough VRAM to load every model together. Start with image generation, then deploy Audio to test speech. Preserve the stage, exit code and diagnostic details on failure; see [Troubleshooting](Troubleshooting.md).

## 4. Generate the first result

| Mode | Required capabilities |
| --- | --- |
| Image | Concept capability (Ollama Node or compatible API) and Image Forge |
| Audio | Concept capability and Audio Forge; no Image Forge required |
| Image + audio | Concept capability, Image Forge and Audio Forge |

1. Open **Creation** and select the model service and necessary Forge Nodes. Configure and test hosted language services first using [Configuration](Configuration.md).
2. For images, check Workflow and Checkpoint resources. Audio mode hides image settings. If resources are missing, install compatible models under **Resources**, then refresh.
3. Select a mode and submit a natural-language request. For example: `Draw a silver-haired girl wearing a blue ceremonial dress.` For speech: `Say “你好” in Chinese with a young female voice.` For combined mode, describe both the scene and spoken words.
4. Watch the Forge, execution Node and state for each task. Cross-machine deployment does not imply automatic parallel execution; the current runner follows the planned dependency order.
5. View results in Creation or **Asset library → Images / Audio**. Try individual-file and ZIP downloads. Desktop downloads open Save As for directory and filename selection; cancellation saves nothing. Browser downloads follow browser settings.

For reusable character identity, discuss a character first, then select it for generation. See [Usage](Usage.md) and [Runtime and data](Runtime-and-Data.md).

## 5. End the session

Closing the desktop client stops its own local host processes. It **does not destroy Pods or end cloud billing**. Stop or destroy unused instances yourself in Compute, after saving their outputs. See [Updating](Updating.md) for upgrades.

## Linux single-machine mode (separate path)

An existing Linux NVIDIA GPU environment can still use `./everspark setup --plan`, `./everspark setup` and `./everspark start` for local managed services. Open local port 8780, or explicitly run `./everspark share` for a temporary link. This differs from Windows `archon start`; do not run Linux GPU installation commands on the Windows control host. See [Commands](Commands.md).
