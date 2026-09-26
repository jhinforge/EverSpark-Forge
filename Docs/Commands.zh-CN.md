# EverSpark Forge 命令手册（v0.1）

本文按当前源码中的 `./everspark` 入口整理命令、参数和实际影响。以下命令从**云端 Linux 仓库根目录**执行；正式 `./everspark setup` 成功后会自动安装全局命令，之后也可以直接输入 `everspark`；`setup --plan` 不安装。本地 Windows 运行环境尚未验证。

需要完整部署步骤请先看[首次运行指南](Getting-Started.zh-CN.md)；私人文件怎么准备见[配置指南](Configuration.zh-CN.md)，运行数据位置见[运行与数据](Runtime-and-Data.zh-CN.md)。可以随时运行 `./everspark help` 查看顶层清单。方括号表示可选参数，尖括号表示要换成自己的值；不要照抄括号。

## 1. 初始化、配置和安装

| 命令 | 用途与实际影响 |
| --- | --- |
| `./everspark help` | 列出顶层入口。直接运行 `./everspark` 也是显示帮助；部分子命令的参数需要运行各自的 `--help` 才能看到。 |
| `./everspark init` | 创建 `Data/Logs`、`Data/Outputs`、`Data/Memory`、模型和运行时等目录，以及配置导入目录；不会安装运行时、下载模型或生成 `.env`。会写入初始化日志。 |
| `./everspark configure` | 从 `Configuration/Import/` 读取 `env.txt` 或 `.env`，验证并导入为仓库根目录的 `.env`；可导入 rclone 与 Named Tunnel 凭据。**再次执行会替换 `.env`，不会在旧配置上追加字段**；原始上传文件保留。默认本地模式无需运行。 |
| `./everspark configure --from <目录>` | 从指定目录读取私人配置。`--env <文件>` 在两个环境文件冲突时明确选择一个；`--json` 输出适合程序读取的结果。 |
| `./everspark setup --plan` | 显示准备安装的托管运行时、模型来源和目标位置，**不安装或下载**。首次部署建议先运行。 |
| `./everspark setup` | 初始化目录、安装托管 ComfyUI/Ollama 与 Python 环境、下载清单中的起步模型，并将 Concept Forge 模型导入 Ollama。需要网络、磁盘空间；安装可选后端时还可能需要 root 权限。失败后处理错误再重试。成功后自动安装 `everspark` 命令，仓库内的 `./everspark` 仍可使用；普通用户首次安装后可能需打开新终端使 PATH 生效。 |
| `./everspark doctor` | 检查 Linux 平台、基础命令、GPU 可见性和已启用后端的配置；rclone 模式还会尝试访问远程模型根路径。它不会替你生成图像，也不表示所有模型和工作流都可用。 |

`setup` 的可选参数：

| 参数 | 含义 |
| --- | --- |
| `--models all\|concept\|image` | 选择下载清单中的全部、Concept Forge 或 Image Forge 起步模型；默认 `all`。托管运行时仍会安装。 |
| `--skip-models` | 只准备运行时，不下载起步模型，也不进行 Concept 模型导入。此时服务启动成功不代表生成资源齐全。 |
| `--skip-concept-import` | 下载模型但不把 Concept GGUF 导入 Ollama；适合稍后接入 Ollama 的情况。 |
| `--plan` | 只打印计划；与 `--skip-models` 联用时不显示模型计划。 |

`./everspark setup --help` 提供安装参数清单。配置文件格式及启用条件见[配置指南](Configuration.zh-CN.md)。

## 2. 管理服务

`[目标]` 可填 `all`、`concept`、`image`、`orchestrator`、`webui`；不填默认为 `all`。`concept` 对应 Ollama，`image` 对应 ComfyUI。完整启动会依次处理 Concept Forge → Image Forge → Orchestrator → WebUI；停止时顺序相反。

| 命令 | 用途与实际影响 |
| --- | --- |
| `./everspark start [目标]` | 启动指定的托管服务并等待健康检查；例如 `./everspark start image` 仅启动 Image Forge，不会自动安装模型。启动全部或 WebUI 时也会处理**已配置启用**的 Named Tunnel，并打印访问说明；不会自动开启临时分享链接。 |
| `./everspark status [目标]` | 查看进程和健康状态，不会启动服务。`running` 表示托管进程健康；`external` 是发现了健康的外部服务；`unhealthy` 表示进程存在但健康检查未通过；`stopped` 表示未就绪。查看全部或 WebUI 时也检查 Tunnel 与临时链接状态。 |
| `./everspark restart [目标]` | 先停再启动目标托管服务。重启全部或 WebUI 时会处理已启用的 Named Tunnel 并打印访问说明；与 `stop` 不同，此命令**不会主动关闭**已经运行的临时 `share` 链接。 |
| `./everspark stop [目标]` | 停止启动器管理的进程；不会终止被识别为 `external` 的健康服务。停止全部或 WebUI 时还会关闭临时 `share` 链接及已配置的 Named Tunnel。 |

服务状态、日志和进程记录的位置见[运行与数据](Runtime-and-Data.zh-CN.md)。例如只重启图像后端：

```bash
./everspark status image
./everspark restart image
```

## 3. 查看和开启 WebUI 访问

| 命令 | 用途与实际影响 |
| --- | --- |
| `./everspark access` | **只显示**云端本机地址、可识别的 SSH 转发命令，以及当前正在运行的临时链接；不会启动服务、创建链接或建立 SSH 连接。`--json` 输出结构化结果。 |
| `./everspark share` 或 `./everspark share start` | 先检查本机 WebUI 健康，再启动临时 Cloudflare 链接；返回 `https://*.trycloudflare.com` 地址。重复执行会复用仍在运行的链接。无需 `.env`、SSH 密钥或 Cloudflare 账号，但云端需要网络；缺少 `cloudflared` 时自动安装需要 root。 |
| `./everspark share status` | 查看是否有当前临时链接；不会新建链接。 |
| `./everspark share stop` | 关闭这个启动器管理的临时链接，不停止 WebUI；`./everspark stop` 与 `./everspark stop webui` 也会关闭链接。重新开启时地址可能变化。 |

**临时链接会公开当前没有登录验证的 WebUI，持有地址的人可以操作页面。** 仅在短时间测试或演示时主动开启，用完关闭。SSH 转发与使用自己域名和凭据的 Named Tunnel 是另外两种访问方式；完整步骤见[首次运行指南](Getting-Started.zh-CN.md)。

## 4. 管理清单中的起步模型

这里的 `models` 针对 `Runtime/Models/default_models.json` 中的**起步模型**，与 WebUI Storage 页面下载任意公开直链、扫描 rclone 模型库的功能不同。

| 命令 | 用途与实际影响 |
| --- | --- |
| `./everspark models plan` | 显示清单中的模型来源、版本、许可证和本地目标，不下载。 |
| `./everspark models status` | 检查清单所列模型的目标文件是否存在且非空，打印 JSON；不是整台机器所有已安装模型的列表。 |
| `./everspark models download` | 将选中的清单模型下载到 `Data/Models/`；需要 `huggingface_hub`，通常先运行 `setup` 准备它。文件已存在且非空时会跳过；**不会自动导入 Ollama**。 |
| `./everspark models import-concept` | 将清单指定的 Concept GGUF 通过 `ollama create` 导入 Ollama；需要模型文件及可用的 Ollama。会写入 `Data/Runtime/Models/ConceptForge.Modelfile`。 |

`plan`、`status`、`download` 可加 `--models all|concept|image` 筛选；`--manifest <JSON路径>` 可覆盖默认清单，属于高级用法。`import-concept` 仍使用清单里的 Concept 模型，不用 `--models` 指定另外一种模型。`setup` 会组合执行运行时安装、模型下载和按需导入；单独的 `models download` 不安装 ComfyUI/Ollama。

## 5. 查看与整理日志

| 命令 | 用途与实际影响 |
| --- | --- |
| `./everspark logs status` | 按日志清单报告托管日志的状态，输出 JSON；不轮转文件。 |
| `./everspark logs init` | 在配置的日志根目录下创建模块文件夹；原有根目录日志保留作为历史。 |
| `./everspark logs rotate --dry-run` | 预览将轮转、重命名或删除哪些托管日志文件；不执行这些操作。 |
| `./everspark logs rotate` | **实际执行**日志轮转与保留策略，可能截断当前日志并删除超出数量或时间限制的旧轮转文件。需要保留故障证据时先导出。 |

`status` 给出服务日志路径；原始日志默认在 `Data/Logs/`，可通过 `EVERSPARK_LOG_DIR` 自定义。日志排查顺序见[排障指南](Troubleshooting.zh-CN.md)。

## 6. 模块入口（开发与单独调试）

日常使用优先通过上面的 `start|stop|restart|status` 管理服务；以下入口各有自己的用途。

| 命令 | 用途与实际影响 |
| --- | --- |
| `./everspark image start|stop|restart|status` | 对 Image Forge 执行对应的托管服务操作，分别等价于 `./everspark start|stop|restart|status image`。 |
| `./everspark concept new <subject_id> <display_name>` | 创建空的 Character Subject v1 JSON 并打印到终端，**不会自动保存为文件或加入当前会话**。 |
| `./everspark concept validate <文件>` | 读取并校验角色主体 JSON，打印结果，不改原文件。 |
| `./everspark concept compile <文件>` | 校验角色主体并输出正、负向提示词片段；不向 Image Forge 提交生成。 |
| `./everspark orchestrator start` | 直接启动 Orchestrator 服务进程，适合单独调试；它不是按顺序启动整套托管服务的 `./everspark start`。 |
| `./everspark webui start` | 直接启动 WebUI 服务进程，适合单独调试；不会启动其余模块。 |
| `./everspark orchestrator console` | 启动交互终端，向正在运行的 Orchestrator 提交请求。`/history` 查看当前会话上下文，`/subject <id>` 指定主体，`/subject clear` 取消指定，`/exit` 退出；**`/clear` 或 `/new` 会清空当前会话上下文**。 |

模块入口可分别运行 `./everspark image help`、`./everspark concept --help`、`./everspark orchestrator help`、`./everspark webui help` 查看当前支持的子命令。
