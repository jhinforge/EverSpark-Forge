# EverSpark Forge

**Distributed AI OS**, a free, open-source system by Jhin. The host handles control and orchestration; Concept, Image and Audio Forges execute on selected machines, sharing a host or running across regions.

[简体中文](README.zh-CN.md) · [Getting started](Docs/Getting-Started.md) · [Usage](Docs/Usage.md)

## Download Windows client v0.2.0

| Package | Download | Requirements |
| --- | --- | --- |
| standard | [Download standard ZIP](https://github.com/jhinforge/EverSpark-Forge/releases/download/v0.2.0/EverSpark-Forge-0.2.0-windows-x64-standard.zip) | Windows x64 with WebView2 installed |
| full | [Download full ZIP](https://github.com/jhinforge/EverSpark-Forge/releases/download/v0.2.0/EverSpark-Forge-0.2.0-windows-x64-full.zip) | Windows x64; fixed WebView2 included |

Both include portable Python. Extract completely, then double-click `EverSpark.exe`. [Release notes and SHA-256 files](https://github.com/jhinforge/EverSpark-Forge/releases/tag/v0.2.0) · [Getting started](Docs/Getting-Started.md). GitHub's Source code downloads contain source, not the Windows client.

## Available capabilities

- Natural-language discussion, reusable characters and revisions; image, speech and combined creation.
- Ollama and OpenAI Compatible APIs for Concept, ComfyUI and optional Diffusers for Image, VoxCPM2 for Audio.
- Windows host management of Vast Pods, active Tailscale Node registration, deployment progress and independent service health checks.
- Direct/cloud model downloads on the corresponding Nodes; independent Image and Concept cloud directories.
- Direct media access and separate image/audio ZIP export; validated character/Memory backup and restoration.
- Standard/full portable Windows clients sharing WebUI and launching by double-click. Both include Python; full also includes fixed WebView2.

Cross-machine deployment does not imply automatic parallelism; tasks follow dependency order. Unimplemented Video/3D features are not available. Demos illustrate behavior; the corresponding source version is authoritative.

## Start

Fully extract a Windows ZIP and run `EverSpark.exe`. Standard uses installed WebView2; full includes a fixed Runtime. Models, Tailscale and rclone are not included. Download the client using the links above, or see the [v0.2.0 release](https://github.com/jhinforge/EverSpark-Forge/releases/tag/v0.2.0) for checksums and release notes. Development test packages appear in successful [Windows builds](https://github.com/jhinforge/EverSpark-Forge/actions/workflows/windows-client.yml). Actions artifacts expire and are not permanent release downloads.

Source entry (Windows PowerShell, Python 3.11.9):

```powershell
git clone --branch refactor/distributed-architecture https://github.com/jhinforge/EverSpark-Forge.git
cd EverSpark-Forge
.\everspark.cmd archon start
```

Open the printed Portal URL. Configure Vast/Tailscale, rent a Pod and deploy the required Forges using [Getting started](Docs/Getting-Started.md). Linux single-machine commands remain available; see [Commands](Docs/Commands.md).

## Documentation

| Task | Guide |
| --- | --- |
| Startup and first generation | [Getting started](Docs/Getting-Started.md) |
| Creation, assets, machines and downloads | [Usage](Docs/Usage.md) |
| Model APIs, cloud paths and private settings | [Configuration](Docs/Configuration.md) |
| Client, source and Node upgrades | [Updating](Docs/Updating.md) |
| Data ownership, backup and restore | [Runtime and data](Docs/Runtime-and-Data.md) |
| Failures and logs | [Troubleshooting](Docs/Troubleshooting.md) |
| Command options and execution modes | [Commands](Docs/Commands.md) |
| Module responsibilities and distributed flow | [Architecture](Docs/Architecture.md) |

Module READMEs target developers. Test entry points are in [Tests](Tests/README.md).

## First-version archive

The first version is archived in the [first-version source release](https://github.com/jhinforge/EverSpark-Forge/releases/tag/v1-source-archive), with its source ZIP and checksum file. Tag `v1-source-archive` preserves commit `2a63893dc1306de3206e6202f2a699294f64b1ba`. This is a source archive, not a portable Windows client; current development and maintenance focus on the second version.

## Author, costs and license

Author: **Jhin**. Official repository: [jhinforge/EverSpark-Forge](https://github.com/jhinforge/EverSpark-Forge). The author charges no software purchase, activation or subscription fees. Cloud GPUs, bandwidth, storage and third-party APIs may be billed by their providers.

See [LICENSE](LICENSE). Models, dependencies and third-party tools have independent licenses and terms. Closing the client does not destroy Pods; preserve required data before deleting an instance.
