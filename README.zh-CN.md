# EverSpark Forge · v0.1

[English](README.md) · **中文**

EverSpark Forge 将计算环境视为可以替换的部分，同时把工作流、配置和用户自己的数据作为需要保留的状态。

EverSpark Forge 是一个自托管 AI 创作平台：它把模型、工作流、生成环境和管理工具放在同一套系统里，让用户在更换机器或环境时仍能继续使用自己的工作流和数据。系统通过讨论形成可复用的角色主体，再根据每次请求的场景生成图像。

**v0.1 是首次公开的源码版本。** 可以在受支持的 Linux GPU 机器上从仓库安装。模型、私人配置、生成结果与其他个人数据独立于源码保存，需要用户自己备份。

## 能做什么

1. 从源码安装托管的 ComfyUI、Ollama 和起步模型。
2. 在 WebUI 中讨论角色，保存并复用角色主体，再提交图像生成请求。
3. 选择已安装的语言模型、Checkpoint、VAE、LoRA 和注册的 API Format 工作流。
4. 下载模型、查看运行状态与生成结果，按需导出输出目录。
5. 可选地接入 rclone 远程模型库与数据备份，或通过 Cloudflare Tunnel 提供访问入口。

默认模式使用当前机器上的本地存储，WebUI 仅监听本机地址；**不需要 R2、Cloudflare 或私人配置文件**。启用了可选后端却没有正确配置时，启动会给出错误，不会悄悄切换成其他后端。

临时演示时也可在 WebUI 启动后运行 `./everspark share`，无需 SSH 转发、Cloudflare 账号或隧道配置即可获得临时公网链接；结束时运行 `./everspark share stop`。WebUI 目前没有登录验证，持有链接的人可以操作页面。详见[首次运行指南](Docs/Getting-Started.zh-CN.md)。

## 快速开始

首发运行环境为**云端 Linux x86_64 + NVIDIA GPU**，需要联网安装运行时和下载模型。作者完成全量测试时使用的基础镜像是 `nvidia/cuda:12.8.0-cudnn-runtime-ubuntu22.04`；本地 Windows 运行尚未验证。先运行计划命令查看下载来源与目标：

```bash
git clone https://github.com/jhinforge/EverSpark-Forge.git
cd EverSpark-Forge
./everspark setup --plan
./everspark setup
./everspark doctor
./everspark start
./everspark status
```

`setup` 创建被 Git 忽略的 `Data/` 目录，安装托管运行时，下载起步模型并准备生成路径；`start` 按依赖顺序启动 Concept Forge、Image Forge、Orchestrator 和 WebUI。没有 `.env` 时，模型、输出和记忆保存在运行 EverSpark 的机器上。

在云端机器上可以访问 `http://127.0.0.1:8780`。如需在自己的电脑上打开 WebUI，可在云端运行 `./everspark share` 获得临时链接，结束时运行 `./everspark share stop`；或运行 `./everspark access`，然后**在自己的电脑上**执行它打印的 SSH 转发命令。云端环境如果未提供可识别的 SSH 连接信息，可在私人配置中设置 `EVERSPARK_SSH_HOST` 与 `EVERSPARK_SSH_PORT`。详细步骤见[首次运行指南](Docs/Getting-Started.zh-CN.md)。

## 文档

| 内容 | 中文 | English |
| --- | --- | --- |
| 首次运行 | [首次运行指南](Docs/Getting-Started.zh-CN.md) | [Getting started](Docs/Getting-Started.md) |
| 私人配置 | [配置指南](Docs/Configuration.zh-CN.md) | [Configuration](Docs/Configuration.md) |
| 数据与迁移 | [运行与数据](Docs/Runtime-and-Data.zh-CN.md) | [Runtime and data](Docs/Runtime-and-Data.md) |
| 故障定位 | [排障指南](Docs/Troubleshooting.zh-CN.md) | [Troubleshooting](Docs/Troubleshooting.md) |
| 模块与请求流 | [架构指南](Docs/Architecture.zh-CN.md) | [Architecture](Docs/Architecture.md) |

## 私人配置与数据

如果已有私人配置，可以把 `env.txt` **或** `.env` 以及需要的 `rclone.conf`、Cloudflare `<UUID>.json` 凭据放入 `Configuration/Import/`，在 `setup` 前运行：

```bash
./everspark configure
./everspark setup --plan
./everspark setup
./everspark doctor
./everspark start
```

`env.txt` 和 `.env` 的内容**完全是同一种 `KEY=VALUE` 格式**；使用 `env.txt` 是为了方便在自己的电脑上查看、保存和上传。`configure` 验证后将其导入为仓库根目录的 `.env`，原始上传文件不会被删除。`.env.example` 只供参考字段，请仅填写实际需要的设置。

仅上传 `rclone.conf` 不会开启远程存储；必须显式启用 rclone 后端并配置模型扫描路径。Cloudflare Tunnel 也只会在配置完整并启用后加入托管生命周期。不启用远程存储时，Storage 页面仍能通过公开直链下载图片模型和 Concept Forge GGUF。详见[配置指南](Docs/Configuration.zh-CN.md)。

运行数据位于被 Git 忽略的 `Data/` 下：图片模型在 `Data/Models/ImageForge/`，Concept Forge 模型在 `Data/Models/ConceptForge/`，生成结果在 `Data/Outputs/`，角色文档与记忆分别在 `Data/Subjects/` 和 `Data/Memory/`。Gallery 的 **Download outputs ZIP** 会打包整个输出目录。启用 rclone 后，可手动上传模型、整个输出目录以及成批的角色 JSON 与 SQLite 快照；这些备份**不会自动进行**。角色数据恢复会先把本地旧数据移入 `Data/Recovery/`，但不会一并恢复图片和模型。迁移前请查看[运行与数据指南](Docs/Runtime-and-Data.zh-CN.md)。

## 架构与当前范围

| 模块 | 职责 |
| --- | --- |
| **Orchestrator** | 会话协调、请求调度和任务管理 |
| **Concept Forge** | 讨论、角色主体、结构化意图和提示词编译；当前使用 Ollama |
| **Memory** | 对话历史、角色及修订、提示词和任务记录 |
| **Image Forge** | 工作流构建与图像任务提交；当前使用 ComfyUI |
| **WebUI** | 讨论、生成、Storage、Gallery 和 Runtime 界面 |
| **Runtime / Launcher** | 安装、启动、健康检查、硬件发现和日志 |
| **Infrastructure** | 可选的远程存储及网络入口 |

v0.1 已实现讨论与生成共用会话、角色主体持久化、注册的 API Format 图像工作流、运行状态、本地模型直链下载，以及可选的远程模型与数据备份。情节式记忆的自动提取、检索和整合尚未实现；其他概念提供者和图像后端也尚不能只靠修改配置切换。模块边界及实际请求流见[架构指南](Docs/Architecture.zh-CN.md)。

## 许可证

EverSpark Forge 采用 **GNU Affero General Public License version 3 only（AGPL-3.0-only）**；完整条款见 [LICENSE](LICENSE)。模型、工作流及其他第三方资源各自遵循其许可证。
