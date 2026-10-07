# EverSpark Forge

**分布式 AI OS**，由 Jhin 开发的免费开源系统。主机负责控制与编排，Concept、Image 和 Audio Forge 在选定机器执行模型任务，可部署在同机或跨地区节点。

[English](README.md) · [首次使用](Docs/Getting-Started.zh-CN.md) · [日常使用](Docs/Usage.zh-CN.md)

## 下载 Windows 客户端 v0.2.0

| 版本 | 下载 | 运行条件 |
| --- | --- | --- |
| standard | [下载 standard ZIP](https://github.com/jhinforge/EverSpark-Forge/releases/download/v0.2.0/EverSpark-Forge-0.2.0-windows-x64-standard.zip) | Windows x64，系统已有 WebView2 |
| full | [下载 full ZIP](https://github.com/jhinforge/EverSpark-Forge/releases/download/v0.2.0/EverSpark-Forge-0.2.0-windows-x64-full.zip) | Windows x64，附带固定版本 WebView2 |

两个版本均包含便携 Python，完整解压后双击 `EverSpark.exe`。[发布说明与 SHA-256 校验文件](https://github.com/jhinforge/EverSpark-Forge/releases/tag/v0.2.0) · [首次使用教程](Docs/Getting-Started.zh-CN.md)。GitHub 的 Source code 下载是源码，不是 Windows 客户端。

## 当前能力

- 自然语言讨论、可复用角色与修订、图片／音频／图片＋音频生成。
- Concept 支持 Ollama 和 OpenAI Compatible API，Image 支持 ComfyUI 与可选 Diffusers，Audio 使用 VoxCPM2。
- Windows 主机管理 Vast Pod，Tailscale Node 主动注册、部署进度与独立服务健康检查。
- 模型直链与云端拉取在对应节点执行；图片与 Concept 云端目录可独立配置。
- 图片／音频直接访问、分别打包 ZIP 下载；角色与 Memory 可导出并验证恢复。
- Windows standard/full 便携客户端，共用 WebUI，双击启动；两者均包含 Python，full 另含固定 WebView2。

跨机器不意味着自动并行；当前任务按依赖顺序执行。未实现的 Video、3D 等不属于当前功能。Demo 是演示，实际能力以对应版本源码为准。

## 开始使用

Windows ZIP 需要完整解压后运行 `EverSpark.exe`。standard 使用系统 WebView2，full 附带固定版本；两者不包含模型、Tailscale 或 rclone。从上方链接下载客户端，或前往 [v0.2.0 发布页](https://github.com/jhinforge/EverSpark-Forge/releases/tag/v0.2.0)查看校验文件与发布说明；当前分支的测试包见 [Windows 构建](https://github.com/jhinforge/EverSpark-Forge/actions/workflows/windows-client.yml)。Actions 附件会过期，不作为永久下载地址。

源码启动（Windows PowerShell，Python 3.11.9）：

```powershell
git clone --branch refactor/distributed-architecture https://github.com/jhinforge/EverSpark-Forge.git
cd EverSpark-Forge
.\everspark.cmd archon start
```

打开终端打印的 Portal 地址。然后配置 Vast／Tailscale、租用 Pod 并部署所需 Forge；完整步骤见[首次使用](Docs/Getting-Started.zh-CN.md)。Linux 单机托管入口仍保留，见[命令手册](Docs/Commands.zh-CN.md)。

## 文档

| 需要做什么 | 指南 |
| --- | --- |
| 启动与首次生成 | [首次使用](Docs/Getting-Started.zh-CN.md) |
| 创作、资产库、机器和下载 | [日常使用](Docs/Usage.zh-CN.md) |
| 模型 API、云端目录和私人配置 | [配置](Docs/Configuration.zh-CN.md) |
| 更新客户端、源码和节点 | [更新](Docs/Updating.zh-CN.md) |
| 数据归属、备份与恢复 | [运行与数据](Docs/Runtime-and-Data.zh-CN.md) |
| 失败与日志定位 | [排障](Docs/Troubleshooting.zh-CN.md) |
| 命令参数与运行模式 | [命令手册](Docs/Commands.zh-CN.md) |
| 模块职责与分布式链路 | [架构](Docs/Architecture.zh-CN.md) |

模块 README 面向开发者；测试入口见 [Tests](Tests/README.md)。

## 第一版归档

第一版已归档，源码 ZIP 与校验文件可在[第一版源码归档发布页](https://github.com/jhinforge/EverSpark-Forge/releases/tag/v1-source-archive)下载。标签 `v1-source-archive` 保留提交 `2a63893dc1306de3206e6202f2a699294f64b1ba`。此包为源码归档，不是 Windows 便携客户端；当前开发与维护以第二版为主。

## 作者、费用与许可证

作者：**Jhin**。官方仓库：[jhinforge/EverSpark-Forge](https://github.com/jhinforge/EverSpark-Forge)。作者不收取软件购买、激活或订阅费用；云 GPU、网络、存储及第三方 API 的费用由对应供应商收取。

许可证见 [LICENSE](LICENSE)。模型、依赖和第三方工具各有自己的许可与条款。关闭客户端不会自动销毁 Pod；删除实例前先保存所需数据。
