# 首次运行 EverSpark Forge（v0.1）

本文以**云端 Linux x86_64 + NVIDIA GPU** 为首发运行环境。作者完成全量测试时使用的基础镜像为 `nvidia/cuda:12.8.0-cudnn-runtime-ubuntu22.04`。本地 Windows 运行尚未验证；Windows 可以作为浏览器及 SSH 客户端使用。

EverSpark Forge 发布的是源码。首次 `setup` 会联网安装托管运行时，并下载用于起步的模型；这些下载需要时间和存储空间。你也可以在配置模式下接入自己的模型与远程存储。**不需要 R2、Cloudflare 或私人配置文件，也能运行默认本地模式。**

## 1. 准备环境

- 一台可使用 NVIDIA GPU 的 Linux x86_64 机器，具有网络连接，以及 `bash`、`python3`、`git`。
- 供安装程序和模型使用的可用磁盘空间；具体下载来源和目标位置可先用 `setup --plan` 查看。
- 如果从自己的电脑访问云端 WebUI，需要能通过 SSH 连接这台机器，并知道云端机器的公网地址和 SSH 端口。

镜像中的 CUDA 版本与 EverSpark 安装的 PyTorch CUDA 档位是两回事。当前源码会根据 **NVIDIA 驱动能力和 GPU 架构**自动选择 PyTorch `cu126` 或 `cu128`；只有无法读取驱动能力时才以基础镜像的 CUDA runtime 作为回退判断。Blackwell GPU 需要支持 CUDA 12.8 的驱动及 `cu128` 档位。当前安装脚本**没有 `cu121` 档位**，也不要求用户手动指定 wheel 地址。

## 2. 无私人配置：从源码启动

在云端机器的终端运行：

```bash
git clone https://github.com/jhinforge/EverSpark-Forge.git
cd EverSpark-Forge
./everspark setup --plan
./everspark setup
./everspark doctor
./everspark start
./everspark status
```

`setup --plan` 只列出准备安装的运行时、模型来源与本地目标，不修改机器。`setup` 创建被 Git 忽略的 `Data/` 运行目录，安装托管的 ComfyUI、Ollama 及 Python 环境，下载起步模型，并将 Concept Forge 模型导入 Ollama。下载量以计划输出为准。

`doctor` 检查基础命令、配置及 GPU 可见性；`start` 按依赖顺序启动 Concept Forge、Image Forge、Orchestrator 和 WebUI；`status` 用于复查服务状态。若 `setup` 中途失败，先根据报错处理依赖或网络问题，再重新运行；不要在模型尚未准备好时把“WebUI 能打开”当作生成链路已可用。

没有 `.env` 时，存储默认为本地，服务默认监听本机地址。启动后可在云端机器打开 `http://127.0.0.1:8780`。

## 3. 从自己的电脑访问云端 WebUI

`./everspark start` 会打印访问说明。之后随时可以重新查看：

```bash
./everspark access
```

如果云端环境提供了脚本能够识别的连接信息，输出会包含完整的 SSH 端口转发命令。**在自己的电脑上运行输出的命令**，保持该 SSH 会话连接，然后访问输出的本地浏览器地址（默认 `http://127.0.0.1:8080`）。不要把云端机器上的 `127.0.0.1:8780` 当作自己电脑上的地址。

如果平台没有提供这些连接信息，在私人 `.env` 中设置 `EVERSPARK_SSH_HOST` 和 `EVERSPARK_SSH_PORT`（需要时还可设置 `EVERSPARK_SSH_USER`），然后重新运行 `./everspark access`。端口转发依赖你已拥有该机器的 SSH 访问权限。

## 4. 完成第一次生成

1. 打开 WebUI，进入 **Runtime**，确认相关服务就绪；如有异常，先运行 `./everspark status`。
2. 回到 **Forge**。可以先在 **Discuss** 模式描述角色，系统会从对话中整理当前角色主体；也可以按界面提示选择已有角色并点击 **Use in Forge**。
3. 检查页面上的 **Workflow**、**Checkpoint**、**Concept LLM** 等可选资源。起步安装会提供模型及 API Format 工作流，资源列表应能加载出来。
4. 切到 **Generate**，输入场景描述并提交；等待生成结果显示在页面中。
5. 在 **Gallery** 查看近期结果。**Download outputs ZIP** 会将整个 `Data/Outputs` 目录打包下载。

角色的稳定特征与这次生成的场景是不同的数据：讨论形成的角色可继续使用，而场景、姿势和镜头描述属于本次请求。

## 5. 已有私人配置：先导入，再安装

如果你已有 Pod 上使用的配置，可先将以下文件上传到仓库里的 `Configuration/Import/`：

| 文件 | 什么时候需要 |
| --- | --- |
| `env.txt` 或 `.env` | 自定义端点、启用远程存储或 Cloudflare Tunnel 等配置；两者内容格式相同 |
| `rclone.conf` | 使用已有的 rclone/R2 连接时 |
| `<CF_TUNNEL_UUID>.json` | 启用 Cloudflare Named Tunnel 时 |

然后在仓库根目录执行：

```bash
./everspark configure
./everspark setup --plan
./everspark setup
./everspark doctor
./everspark start
```

`env.txt` 就是方便在自己的电脑上查看、保存和上传的 `.env`：仅文件名不同，均使用相同的 `KEY=VALUE` 格式。`configure` 会验证它并复制为仓库根目录下被 Git 忽略的 `.env`，保留原始上传文件。`rclone.conf` 的存在**不会自动启用**远程存储；需要在私人环境配置中显式设置 `EVERSPARK_STORAGE_BACKEND=rclone` 及相应远程路径。Cloudflare 集成同样需要完整配置。配置的格式、路径和启用条件见 [`Configuration/README.md`](../Configuration/README.md) 和 [`.env.example`](../.env.example)。

导入后如果 `doctor` 报远程路径或凭据错误，请先修复启用的后端配置，再启动。仓库的 `.gitignore` 忽略私人配置和 `Data/` 运行数据；不要强制将凭据或个人数据加入 Git。

## 6. 日常命令与问题定位

```bash
./everspark status
./everspark access
./everspark restart image
./everspark stop
```

托管服务的原始输出写在 `Data/Logs/`。当 WebUI 可以打开但不能生成时，依次检查 Runtime 页面、`./everspark status`、模型资源是否可见，以及对应服务的日志。基础环境与配置可再次用 `./everspark doctor` 检查。

本页的主流程针对**云端 Linux 首次部署**；其他云端镜像及本地 Windows 部署尚未验证。
