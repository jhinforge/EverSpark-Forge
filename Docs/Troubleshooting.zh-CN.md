# 排障指南

先记录“关于”页版本／提交、发生时间、页面完整错误、对应 Node 与任务 ID。保留错误前后的日志；不要公开 API Key、auth key、签名下载 URL 或完整私人配置。

## 客户端无法打开

确认 ZIP 已完整解压、目录可写、Windows 为 x64；standard 需要已有 WebView2，缺少时使用 full。不要只拷贝 EXE。查看 `Data/Logs/client/backend.log`；同时运行源码主机时先关闭它。命令行入口是 `everspark.cmd archon start`，桌面客户端动态端口不应照抄 8780。

## Node 离线或 Forge 不可用

先确认主机 Tailscale 在线，机器卡片的 Agent 心跳和连接状态正常；再确认 Forge 已部署、源码版本验证与健康检查通过。Agent 在线不代表 Forge 可生成。租新 Pod 前检查 auth key 是否有效、单次密钥是否已用过、Reusable 设置是否匹配。

若任务仍正常进行而检查暂未确认，保留阶段和最近成功检查时间，等待复查；不要立即重复部署或提交生成。长任务的健康探测走独立探测通道，不能只凭一次检查超时推断 Pod 已离线。

## 部署失败／结果未知

记录机器卡片的失败阶段、退出码和诊断尾部。模型下载、Python 依赖、GPU／驱动和服务启动是不同阶段。Agent 重连与主机重启可恢复已有任务查询；执行被中断时结果可能未知，不自动重复安装。先验证实际服务和已安装资源，再决定是否重新部署。

Audio 源码 pin 和匹配的 Torch／torchaudio 由安装器检查，使用 Audio 部署流程修复。源码不一致时按[更新指南](Updating.zh-CN.md)更新主机与节点。

## 生成失败

图片、音频、组合模式分别需要相应 Forge；音频不要求 Image 节点。外部 Concept API 先测试连接，核对基础 URL、模型 ID 和认证。模型和工作流列表来自当前所选节点，不能拿另一节点的模型名称直接使用。

`Concept Forge returned an invalid creative decomposition` 表示创作计划未满足结构／模式要求；记录所用模型、模式和完整错误，确认主机与 Concept 执行端都已更新。不要因此要求音频用户先配置 Image Forge。

任务列表中的 failed／skipped 和结果查询分别查看；图片提交成功不等于已经完成渲染。检查角色是否确实在当前对话中选用，LoRA／VAE 是否兼容所选模型与工作流。

## 云端模型扫描／拉取失败

确认云端存储已启用、rclone 路径有效、连接已导入，并至少配置一种模型目录。图片与 Concept 独立；自定义目录名称要指定模型类型。确认模型拉取目标是对应 Forge 节点。旧节点模型存储服务需更新并重启，单重启 Agent 可能无效。

扫描源可以只读，上传和备份目的地必须可写。远端路径、模型任务错误和节点模型存储 `service.log` 有助于区分源目录问题与节点服务问题。

## 图片／音频／ZIP 下载失败

单文件或播放失败：检查节点是否在线、Tailscale 访问是否被策略／防火墙阻止；链接过期时刷新资产库。

远端 ZIP 采用 Pod 归档后临时 URL 下载。先确认归档任务完成，再看客户端下载是否开始；Forge 生成健康并不等于媒体 URL 服务健康。`Image URL service unavailable` 或归档 HTTP 503 应检查节点 `Aegis/Storage/node_media_access.py` 服务日志。`Cannot assign requested address` 表示监听地址不是可绑定的本机地址；更新节点媒体服务后重新启动。

客户端弹出另存为时选择实际目录，取消不保存；已开始传输但慢时分别比较单文件与 ZIP、主机到 Pod 的连接情况。公网测速不是这条链路的速度。下载完成提示包含实际路径。

角色与 Memory ZIP 的恢复则检查 128 MiB 上限、清单和 SQLite 一致性；它不使用远端媒体 ZIP 链路。

## 日志在哪里

| 位置 | 优先查看 |
| --- | --- |
| 桌面客户端目录 | `Data/Logs/client/backend.log` |
| 主机日志根目录 | `archon/gate.log`、`webui/webui.log` 及相关模块日志 |
| 节点 Agent 目录 | `/workspace/everspark-node/` 内日志、任务记录和 `bandwidth.log` |
| 节点仓库 | 对应 Forge `Data/Logs/`、`Data/Runtime/model-storage/service.log` |

路径可由环境配置覆盖，以任务实际输出为准。主机日志根目录默认 `Data/Logs/`。提交 Issue 时附步骤、模式、版本、任务 ID 和脱敏日志；说明是客户端、源码主机还是 Linux 单机模式。
