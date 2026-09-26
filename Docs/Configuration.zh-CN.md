# 配置 EverSpark Forge（v0.1）

本文说明如何在默认本地模式与私人配置模式之间选择，以及如何接入自己的模型、远程存储和网络入口。首次安装命令见[首次运行指南](Getting-Started.zh-CN.md)。这里的“本地”指数据保存在**运行 EverSpark 的机器**上；如果程序运行在云端机器，本地数据也在那台云端机器上。

## 1. 不提供配置文件时

从源码直接运行 `./everspark setup` 和 `./everspark start` 即可。默认使用本地存储，各服务监听本机地址；R2/rclone 和 Cloudflare Tunnel 不会自动启用。模型、输出、记忆及运行数据保存在仓库下被 Git 忽略的 `Data/` 目录。即使没有远程存储，也可以在 WebUI 的 Storage 页面通过公开直链下载兼容模型。

从自己的电脑访问云端 WebUI 可用 `./everspark access` 输出的 SSH 转发命令；短时间演示还可在启动 WebUI 后运行 `./everspark share`，获得临时公网链接。后者无需 SSH 密钥、`.env`、Cloudflare 账号或 Named Tunnel 凭据，但会主动公开当前无登录验证的 WebUI，使用完运行 `./everspark share stop`。两种方式均不要求配置下文的 Named Tunnel，详情见[首次运行指南](Getting-Started.zh-CN.md)。

## 2. 私人配置文件是什么

可上传的 `env.txt` 与 `.env` **使用同样的 `KEY=VALUE` 内容格式**。`env.txt` 只是便于在自己的电脑上查看、保存和上传的文件名；执行 `./everspark configure` 后，导入器会将其规范化为仓库根目录的 `.env`。如果两种文件名都存在于导入目录，其解析后的配置必须一致；通常保留其中一个即可。

`.env.example` 是可用字段的参考，**不要把整份示例原样当成私人配置导入**。只写你实际需要的项目，尤其不要留下未启用服务的部分配置字段：导入器会检查检测到的 Cloudflare 字段是否齐全。

例如，只想指定其他云端平台的 SSH 连接信息，可以创建这样的 `env.txt`：

```dotenv
EVERSPARK_SSH_HOST=example.com
EVERSPARK_SSH_PORT=22
EVERSPARK_SSH_USER=root
```

把 `example.com`、端口和用户名替换为自己的连接信息。如果云端平台已经提供了启动器可识别的连接信息，则无需填写这些字段。

导入过程按环境变量文件解析内容；值中有空格时需正确加引号。同一文件中不能重复定义同一个键。不要把密码、令牌或私人远程路径写进 Git 跟踪的文件。

## 3. 导入和更新配置

将 `env.txt` **或** `.env` 放入 `Configuration/Import/`，从仓库根目录运行：

```bash
./everspark configure
./everspark setup --plan
./everspark setup
./everspark doctor
./everspark start
```

`Configuration/Import/` 的上传文件不会被移动或删除；导入后的 `.env` 被 Git 忽略。导入器还会将需要的凭据复制到 `Data/Configuration/`，对导入文件设置仅当前用户可读写的权限。已有环境只想更新配置时，重新上传**完整的**环境文件并再次运行 `./everspark configure`；这会替换根目录的 `.env`，不是把新字段追加到旧文件。

如果文件放在其他目录，可用 `./everspark configure --from <目录>`；同一目录中同时有 `.env` 与 `env.txt` 且内容不同，可用 `--env <文件>` 显式指定一个。修改了运行中服务使用的配置后，按需要运行 `./everspark restart` 使服务重新读取配置。

`configure`、`setup`、`doctor` 的具体影响及可选参数见[命令手册：初始化、配置和安装](Commands.zh-CN.md#1-初始化配置和安装)。

## 4. 模型、工作流和输出

**模型不是源码的一部分。** 默认 `setup` 会下载起步所需模型。之后可以在 WebUI 的 Storage 页面分别粘贴 Checkpoint/扩散模型、LoRA、VAE 或 Concept Forge GGUF 的公开直链；需要远程模型库存时，再启用下文的 rclone 模式。在 Forge 选择已安装的资源，不需要在私人配置里手工列出每一个 Checkpoint 或 LoRA。

默认模型与输出位置如下：

| 内容 | 默认位置或方式 |
| --- | --- |
| 图片模型 | `Data/Models/ImageForge/` 下的分类目录 |
| Concept Forge 模型 | `Data/Models/ConceptForge/Ollama/` |
| 输出 | `Data/Outputs/`，可在 Gallery 下载整个目录的 ZIP |
| 工作流 | `ImageForge/Workflows/` 中的 API Format JSON 与相邻的清单文件 |

ComfyUI 是默认绘图工具。可在 Forge 的绘图工具选择器中选择 Diffusers，点击 **安装工具**，按页面提示启用；**设为默认**会保存选择，无需修改 `.env`。Diffusers 当前支持 SDXL 单文件 Checkpoint 及兼容的 LoRA、VAE。ComfyUI 使用已注册的 API Format 工作流；高级使用者可以通过 `EVERSPARK_WORKFLOW_TEMPLATE` 指向其他 API Format 工作流文件。普通 ComfyUI 界面工作流不能直接当作 API Format 文件放入注册目录。限制与节点要求见 [Image Forge 说明](../ImageForge/README.md)。

使用托管语言模型时，在 WebUI 侧边栏打开**模型服务**，填写连接名称、以 `/v1` 结尾的 API 基础地址、API Key 和平台要求的准确模型 ID。测试连接后在 Forge 选择服务与模型，也可设置角色修订使用的默认服务。OpenAI Compatible 适配器默认使用非流式 Chat Completions（`/chat/completions`）；服务要求流式时可在连接中启用，EverSpark 会收齐文本后继续。不会自动发现远端模型 ID。可选 JSON 模式默认关闭，以兼容不支持 `response_format` 的服务。连接和密钥保存在仅当前用户可读写的 `Data/Configuration/ConceptForge/connections.json`；WebUI API 不返回已保存的密钥。选择托管服务后，发送给该服务的提示词会传至对应平台；Ollama 仍可本地使用。

DeepSeek 复用 OpenAI 格式的 Chat Completions 适配器。点击 **Fill DeepSeek settings** 可填入目前官方的 `https://api.deepseek.com/v1` 地址和 `deepseek-flash` 模型；自行填写 DeepSeek 官方 API Key，测试、保存后在 Forge 选择该服务。预设默认关闭流式和 JSON 模式；以后配置时请核对 DeepSeek 官方的最新模型 ID。

角色主体、记忆和输出都是运行数据。搬迁或重建云端机器前，请自行保留需要的数据。即使不配置 rclone，也可在 Storage 的 **角色与 Memory 压缩包** 区域下载角色 JSON 与 Memory SQLite 的 ZIP，之后选择该 ZIP 并点击 **验证并恢复**；恢复后需重启 EverSpark。输出图片、模型及私人配置（包括模型服务连接）需分别保存。远程备份是可选功能，不会因填写了模型来源地址就自动开始上传；详见[运行与数据生命周期](Runtime-and-Data.zh-CN.md)。

## 5. 接入 rclone 远程存储（可选）

准备已有的 `rclone.conf`，与 `env.txt` 一起放入 `Configuration/Import/`。环境文件中至少明确启用后端并配置两个模型扫描根路径，例如：

```dotenv
EVERSPARK_STORAGE_BACKEND=rclone
IMAGE_FORGE_RCLONE_REMOTE=myremote:path/to/image-models
CONCEPT_FORGE_RCLONE_REMOTE=myremote:path/to/ollama-models
```

`myremote:` 必须与自己的 `rclone.conf` 中的 remote 名称一致，示例路径需要改成真实路径。`configure` 会将 `rclone.conf` 导入 `Data/Configuration/rclone/rclone.conf`，并在生成的 `.env` 中设置 `RCLONE_CONFIG`。仅上传 `rclone.conf` **不会**启用远程存储；显式设置 `EVERSPARK_STORAGE_BACKEND=rclone` 后，`setup` 才会在支持的 apt 系 Linux 环境安装 rclone。

两个远程地址是**扫描根目录**。Storage 页面可以发现其下的模型分类目录；如果目录结构不同，可在页面保存手工路径及可写的上传目标。只读或聚合的 remote 可以用于扫描；上传时需要选择真实可写的目标。

如需指定输出及角色数据的可写备份目录，可额外设置：

```dotenv
EVERSPARK_BACKUP_REMOTE=myremote:path/to/everspark-backups
```

不设置时，程序会尝试在第一个图片模型来源桶下使用 `everspark-backups` 前缀。输出目录按整个文件夹同步；角色 JSON 与 SQLite 按成批快照上传与恢复。上传不会删除远程已有文件。导入并安装后运行 `./everspark doctor`，检查 rclone 配置和扫描根目录能否访问。

## 6. 接入 Cloudflare Named Tunnel（可选）

以下是使用自己的域名和凭据的持久入口；临时 `./everspark share` 链接无需导入这些文件，也不会仅因运行 `./everspark start` 自动开启。

如果已经拥有 Named Tunnel，把 `<CF_TUNNEL_UUID>.json` 与 `env.txt` 一起放入导入目录，并在环境文件中提供完整设置：

```dotenv
EVERSPARK_NETWORK_BACKEND=cloudflare
CF_TUNNEL_UUID=你的隧道UUID
CF_HOSTNAME=你的域名
CF_LOCAL_PORT=8780
```

这里是字段示意，请用真实的 UUID 与域名；凭据 JSON 内的 `TunnelID` 必须匹配 UUID。`CF_LOCAL_PORT` 必须等于 WebUI 监听端口（默认 `8780`）。导入器验证凭据并将其复制到 `Data/Configuration/cloudflare/`；启动器随后管理 Tunnel 生命周期。没有使用 Tunnel 时，环境文件里省略 `CF_*` 字段即可。

## 7. 源码与私人数据的边界

| 可以随源码保存 | 保存在私人环境或另行备份 |
| --- | --- |
| 程序代码、公开示例、可公开的工作流 | `.env`、`env.txt`、`rclone.conf`、Tunnel 凭据 |
| 公开的配置字段说明 | `Data/` 下的模型、生成输出、角色及记忆 |

仓库的 `.gitignore` 已忽略 `.env`、`Configuration/Import/` 中的上传文件和 `Data/` 运行目录。Git 忽略规则只防止普通提交，不代替自己的数据备份；也不要使用强制添加命令把私人文件提交到公开仓库。

更完整的导入细节见 [`Configuration/README.md`](../Configuration/README.md)，全部可选字段见 [`.env.example`](../.env.example)。
