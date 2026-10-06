# 运行与数据

分布式模式不能把整个系统的数据都理解为主机的 `Data/`。下表以默认路径为例，环境变量可覆盖路径。

## 文件归属

| 内容 | 所在位置 | 保存方式 |
| --- | --- | --- |
| 源码、公开工作流 | Git 仓库 | Git／发布源码 |
| 主机角色与 Memory | 主机 `Data/Subjects/`、`Data/Memory/everspark.db` | 资产库的角色与 Memory 数据 ZIP |
| 模型 API 连接、rclone 配置 | 主机 `Data/Configuration/` | 单独保存私人配置 |
| 根环境配置 | 主机 `.env` | 单独备份；不进入 Git |
| Vast API Key | 当前 Windows 用户凭据管理器 | 新电脑重新填写 |
| Node 和绑定索引 | 默认 `%LOCALAPPDATA%/EverSpark/`，可由 `EVERSPARK_NODE_STATE` 覆盖 | 属于主机运行状态；移机后重新验证节点身份和连接 |
| Tailscale 租赁用 auth key | 当前主机会话 | 重启后租新 Pod 前重新配置 |
| Windows Python／WebView2 | 客户端 `Runtime/`；standard 不含固定 WebView2 | 从发布包重建 |
| Windows 浏览器配置与日志 | 客户端 `Data/Runtime/WebView2/`、`Data/Logs/client/` | 按需要保存 |
| Image 模型与结果 | 执行节点 `Data/Models/ImageForge/`、`Data/Outputs/` | 模型重新拉取，输出主动下载 |
| Concept 模型 | 执行节点 `Data/Models/ConceptForge/` | 下载或云端拉取并按需导入 |
| Audio 环境、模型和输出 | Audio 执行节点，由适配器配置决定 | 权重重新部署，输出主动下载 |
| Agent 状态、日志、测速 | 节点通常为 `/workspace/everspark-node/` | 排障时保存所需记录 |

Git 忽略不代表已备份。复制客户端文件夹也不会自动迁移 Windows 凭据管理器、Tailscale 身份或外部 Node 状态目录。

## 三类 ZIP

| ZIP | 包含 | 不包含 |
| --- | --- | --- |
| 图片输出 ZIP | 对应 Image 节点的图片输出 | 其他节点、音频、角色、模型、凭据 |
| 音频输出 ZIP | 对应 Audio 节点的音频输出 | 图片、角色、模型、凭据 |
| 角色与 Memory 数据 ZIP | 四份角色 JSON 与一致的 SQLite 快照 | 输出媒体、模型、模型 API 密钥和私人配置 |

角色 JSON 为 `subject.json`、`metadata.json`、`positive_prompt.json`、`negative_prompt.json`。数据 ZIP 通过清单、校验值、SQLite 完整性与数据一致性验证；不是任意 ZIP 都能恢复。上传上限为 128 MiB，恢复前的数据保存在主机 `Data/Recovery/`，恢复后重启主机。

数据 ZIP 使用主机归档流程；远端媒体 ZIP 由 Pod 打包并提供临时下载 URL。两者不要混淆。下载取消不等于生成结果已删除。

## 媒体访问与生命周期

结果接口返回引用和访问 URL，原件仍在生成节点。节点文件服务监听可用的本机 Tailscale 地址，访问使用带有效期的签名；绑定地址与公布地址分别处理。单文件读取有转发备用通道，远端 ZIP 下载使用节点临时 URL，不再使用旧主机转发 ZIP 的链路。

URL 过期后刷新资产库以获取新链接。临时归档按服务清理策略回收，不是长期备份。Pod 离线时无法读取原件，销毁 Pod 前必须确认已保存需要的内容。停止主机不会自动销毁 Pod。

## 云端备份与搬迁

云端扫描或模型拉取不会自动备份。上传和恢复需主动提交任务，选择实际可写的备份位置并等任务完成。角色与 Memory 按完整快照处理，输出和模型另行保存。

换电脑时先导出角色与 Memory、下载媒体、备份私人配置；在新主机配置账户与 Tailscale、恢复数据、重新验证节点连接。重建 Pod 时重新部署 Forge 和模型。图片／音频结果不会因恢复角色 ZIP 而自动回来。

见[更新指南](Updating.zh-CN.md)与[配置指南](Configuration.zh-CN.md)。
