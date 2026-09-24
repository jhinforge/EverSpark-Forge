# 排障指南（v0.1）

本文面向[首次运行指南](Getting-Started.zh-CN.md)所述的云端 Linux 部署。遇到问题时，先定位失败发生在**安装、连接 WebUI、服务启动、模型与工作流、生成，还是远程存储**，然后只检查对应一层。

## 先收集三个结果

在仓库根目录运行：

```bash
./everspark status
./everspark doctor
./everspark logs status
```

`status` 报告各服务是否健康，以及日志位置；`doctor` 检查基本命令、GPU 可见性与已启用后端的配置；`logs status` 列出托管日志状态。WebUI 的 **Runtime** 页面也会显示服务就绪情况。默认日志在 `Data/Logs/`；如果设置了 `EVERSPARK_LOG_DIR`，请以实际配置和 `status` 输出为准。

这些检查命令的含义及会修改日志文件的 `logs rotate` 见[命令手册：查看与整理日志](Commands.zh-CN.md#5-查看与整理日志)。

## 1. `setup` 没有完成

**检查：** 回看 `./everspark setup` 最先出现的错误；先运行 `./everspark setup --plan` 确认下载来源与目标。检查 `nvidia-smi` 是否能看到 GPU，`./everspark doctor` 是否报告平台或基础命令问题。安装运行时与下载模型都需要网络。

**处理：** 按第一条明确错误修复环境或网络后，重新运行 `./everspark setup`。如果安装运行时成功但模型不全，用 `./everspark models status` 查看当前模型状态。不要仅凭 WebUI 可以启动就认定生成所需模型已经准备好。

**查看：** `Data/Logs/` 中与安装、模型或服务相关的日志；安装命令的终端输出通常包含最直接的失败原因。

## 2. WebUI 打不开

1. 在云端机器运行 `./everspark status webui`，检查 WebUI 是否健康。未启动时运行 `./everspark start`；启动失败则查看 `Data/Logs/webui-service.log`。
2. 如果云端机器可以打开 `http://127.0.0.1:8780`，但自己的电脑打不开，运行 `./everspark access`，在**自己的电脑**执行输出的 SSH 转发命令，并保持 SSH 会话连接。浏览器打开输出的本地地址，默认 `http://127.0.0.1:8080`。
3. 如果 `access` 没有给出完整命令，确认 SSH 公网地址和端口；必要时在私人配置中设置 `EVERSPARK_SSH_HOST`、`EVERSPARK_SSH_PORT`，再运行 `./everspark access`。
4. 如果选用临时链接，先运行 `./everspark share status`；未启动时在云端机器运行 `./everspark share`，打开命令输出的链接。已有链接打不开时检查 WebUI 是否仍就绪、共享进程是否仍在，以及云端机器能否访问 Cloudflare；关闭后重新运行 `share` 可能得到不同链接。

默认 WebUI 仅监听本机地址。不要将云端机器的 `127.0.0.1:8780` 直接填进自己电脑的浏览器，并期待它连接远端。

## 3. 页面能打开，但 Runtime 显示某个服务未就绪

| 未就绪的服务 | 先检查 | 默认原始进程日志 |
| --- | --- | --- |
| Concept Forge | `./everspark status concept`，Ollama 与模型是否可用 | `Data/Logs/ollama-service.log` |
| Image Forge | `./everspark status image`，ComfyUI 是否启动、GPU 是否可用 | `Data/Logs/comfyui.log` |
| Orchestrator | `./everspark status orchestrator`，上游服务与配置 | `Data/Logs/orchestrator-service.log` |
| WebUI | `./everspark status webui`，监听端口与进程 | `Data/Logs/webui-service.log` |

`status` 的 `external` 表示发现了健康的外部服务，并不等于服务已停止。`unhealthy` 表示托管进程仍在但健康检查未通过；先看日志，再按需执行 `./everspark restart <服务名>`。不要通过猜测进程号来结束服务。

## 4. 模型或工作流选不到

在 WebUI 的 **Forge** 检查 **Workflow**、**Checkpoint**、**VAE**、**Concept LLM** 的资源列表；运行 `./everspark models status`，确认安装所需模型。如果是自己下载的模型，在 **Storage** 查看下载任务是否真正完成，并确认选对了模型类别。中断或失败的直链下载不会把不完整文件当作可用模型展示。

工作流必须是注册的 **API Format JSON**，并有相应清单。普通 ComfyUI 界面工作流不能直接当成可执行文件放入工作流目录。模型虽然安装成功，也必须与所选工作流匹配；工作流和 LoRA 的节点限制见 [Image Forge 说明](../ImageForge/README.md)。

如果使用远程模型库，还要确认 Storage 扫描的是实际模型目录；目录结构特殊时设置手工扫描路径。没有启用 rclone 时，仍可使用 Storage 的公开直链下载功能。

## 5. 点击生成后失败，或结果没有出现

先看页面显示的任务错误与 **Gallery** 中的最近结果，再检查 `./everspark status`。如果 Image Forge 未就绪，查看 `Data/Logs/comfyui.log`；如果 Orchestrator 未就绪或无法提交任务，查看 `Data/Logs/orchestrator-service.log`。这些日志比单纯重复点击生成更能说明故障发生在哪一层。

如果是换了工作流、Checkpoint、VAE 或 LoRA 后才失败，先记录当前选择及报错，再对照所选工作流的模型与节点要求。生成失败不等于输出目录已经备份；成功结果默认写在 `Data/Outputs/`，Gallery 的 **Download outputs ZIP** 可下载整个输出目录。

## 6. 旧角色在列表里，但当前对话没用上

在 **Forge** 选择已有角色并点击 **Use in Forge**；只在 **Subjects** 列表中看到它，不代表当前对话已经选用了它。切回 Forge 检查当前角色卡，再提交生成。如果选择后页面没有更新，记录浏览器提示和 `Data/Logs/orchestrator-service.log`、`Data/Logs/webui-service.log` 中相同时间的错误。

## 7. 本地 ZIP 导出/恢复或远程传输失败

**角色与 Memory ZIP：** 在 **Storage → 角色与 Memory 压缩包** 下载失败时先确认 Orchestrator 就绪、`Data/Memory/everspark.db` 可用，并查看页面报错与 `Data/Logs/orchestrator-service.log`、`Data/Logs/webui-service.log`。选择 ZIP 后点击 **验证并恢复** 若失败，确认文件来自 EverSpark 的 **下载数据 ZIP**、文件大小不超过 128 MiB，且 ZIP 未损坏或更改。系统会验证清单、校验值、SQLite 完整性及四份角色 JSON 与数据库的一致性；不接受任意 ZIP。恢复成功后按提示重启 EverSpark。原数据位于 `Data/Recovery/`；暂存上传文件在 `Data/Imports/`，完成或失败后由 WebUI 清理。这个 ZIP 不包含输出图片或模型。

**远程模型与数据：** 先运行 `./everspark doctor`。启用 rclone 时，需要有效的 `rclone.conf`、图片与 Concept 模型扫描根路径，以及可访问的 remote。Storage 页面中的手工目录或上传目标如果指向只读、聚合 remote，需改为实际可写的目标。检查页面的任务错误和 `Data/Logs/rclone.log`。

上传输出时选择 **Outputs folder**；它会按整个输出目录处理，无须逐张选择。远程恢复点也只针对成批保存的角色 JSON 与 Memory SQLite；恢复后按页面提示重启 EverSpark。输出图片和模型不会随任一种角色恢复方式一并取回。数据的位置及迁移步骤见[运行时与数据生命周期](Runtime-and-Data.zh-CN.md)。

## 8. 临时链接或 Named Tunnel 在外网打不开

**使用 `./everspark share` 的临时链接：** 在云端机器运行 `./everspark status webui` 和 `./everspark share status`。启动失败先看命令报错及 `Data/Logs/quick-tunnel.log`（自定义日志目录时检查 `EVERSPARK_LOG_DIR`）。确认 WebUI 健康、云端机器可连接 Cloudflare；如尚未安装 `cloudflared`，自动安装需要 root 权限和下载网络。当前用户主目录下存在 `~/.cloudflared/config.yaml` 或 `config.yml` 时，临时链接会被拒绝；如要临时移开配置文件，应先确认自己没有依赖该配置运行的隧道。临时链接不使用 `CF_TUNNEL_UUID` 等 Named Tunnel 配置。

**使用已配置的 Named Tunnel：** 先确认本地 WebUI 正常：在云端机器访问 `http://127.0.0.1:8780`，并检查 `./everspark status webui`。之后运行 `./everspark status` 检查 Tunnel。确认私人配置中的 Tunnel UUID、域名、凭据文件及 `CF_LOCAL_PORT`；导入时后者必须与 WebUI 端口一致。查看 `Data/Logs/` 中与 Tunnel 相关的日志。

如果只是希望从自己的电脑访问云端机器，可用 SSH 转发；短时间演示可选临时链接，不要求配置 Named Tunnel。临时公网链接没有登录保护，使用完运行 `./everspark share stop`。

## 提交 Issue 时附什么

说明你使用的 Linux 环境、执行的命令、失败步骤和**第一条错误信息**；附 `./everspark status` 与 `./everspark doctor` 的相关输出，以及对应服务日志的最后一小段。可以在云端机器用 `tail -n 80 Data/Logs/<日志文件>` 查看末尾内容。提交前检查并遮盖公网 IP、私人路径、访问令牌、模型直链中的签名参数和其他凭据；不要上传 `.env` 或 `rclone.conf` 原件。
