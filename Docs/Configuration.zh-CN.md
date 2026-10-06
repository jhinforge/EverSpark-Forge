# 配置指南

默认不启用云端存储。Windows 控制主机不需要先安装 GPU 模型，节点连接步骤见[首次使用](Getting-Started.zh-CN.md)。

## 模型服务

在 **设置 → 模型服务** 填写连接名称、提供商要求的 API 基础地址（通常以 `/v1` 结尾）、准确模型 ID 和 API Key；测试并保存后，在创作页选择连接与模型。不会自动枚举提供商所有模型。

使用 OpenAI Compatible Chat Completions；所选上游错误可能触发响应模式重试，认证失败不因此重试。API 连接由主机调用，密钥不会发送给 Concept 节点。连接保存在 `Data/Configuration/ConceptForge/connections.json`；API 不返回已保存密钥。使用 Ollama 则选择已部署的 Concept 节点。

## 云端模型库

1. 打开 **设置 → 云端存储配置 → 启用云端存储**。
2. 选择自己的 `rclone.conf`，点击 **导入连接**；无需同时提交 `.env` 或 Cloudflare 凭据。
3. 主机找不到 rclone 时填写实际程序位置，例如 `C:\rclone\rclone.exe`。客户端不附带 rclone。
4. 选择连接并浏览目录，用 **设为图片模型目录** 或 **设为 Concept 模型目录**保存选择。图片可选多个来源。
5. 至少选择一种模型目录，再点 **验证并启用**。两种目录独立；没有配置的一类不扫描，可以移除已有 Concept 目录。
6. 返回 **资源**扫描模型，选择资源和对应 Forge 节点后拉取。传输在节点执行，不先下载到主机。

图片目录可以是模型库根目录，也可以是 checkpoints、loras、vae 等分类目录；自定义目录名称需指定模型类型。不要假定系统一定再追加一层 `checkpoints`。Ollama 原生模型目录通常包含 `manifests` 和 `blobs`；独立 GGUF 也支持扫描。

例如，图片来源可选 `r2-assets:comfyui-assets/models_cold`，Concept 可选 `r2-assets:ollama-forge/.ollama/models`；这些只是结构示例，需要改成自己的 remote 和路径。多个图片来源会生成只读 union，上传需选择实际可写目录。

备份目的地与模型来源不是同一概念。可单独设置 `EVERSPARK_BACKUP_REMOTE`；未设置时按已配置的图片或 Concept 来源推导备份前缀。扫描不会自动备份，只读模型来源也不代表可写备份。

## 私人配置与源码导入

`.env` 与 `env.txt` 使用同样的 `KEY=VALUE` 格式。将文件和需要的 `rclone.conf` 放入 `Archon/Vault/Import/`，从仓库根目录执行：

```powershell
.\everspark.cmd configure
```

Linux 使用 `./everspark configure`。导入器保留原文件并生成私人配置；完整环境导入会替换根 `.env`，不要误当作追加。`--from DIRECTORY` 与 `--env FILE` 可指定来源。重启受影响服务后生效，已设置的进程环境变量可能覆盖文件值。字段参见[配置示例](../.env.example)；不要原样导入所有示例字段。

WebUI 的云端配置保存会立即更新主机运行时；既有 Pod 的旧模型存储服务仍需更新并重启，见[更新指南](Updating.zh-CN.md)。

## 可选 Cloudflare 与 Linux 托管模式

Named Tunnel 使用 `EVERSPARK_NETWORK_BACKEND=cloudflare`、`CF_TUNNEL_UUID`、`CF_HOSTNAME`、`CF_LOCAL_PORT` 和匹配的 UUID 凭据。端口必须与所用 WebUI 一致；Windows 客户端是动态端口，不要照抄固定 8780 的隧道配置。

Linux 单机启动后的 `./everspark share` 是另一种临时分享方式，无需 Named Tunnel 配置；WebUI 没有应用登录保护，使用后主动停止分享。分布式首次使用优先采用 Tailscale 主机与节点连接，不要求 Cloudflare。

运行位置、凭据和备份区别见[数据指南](Runtime-and-Data.zh-CN.md)。
