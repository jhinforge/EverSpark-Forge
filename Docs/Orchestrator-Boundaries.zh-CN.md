# Orchestrator 职责迁移记录

目标分支：`refactor/distributed-architecture`。审查基线：`b4607ab6920fb94fa5555f1ca46bfc77a66d4a29`。

本次将已有职责归回模块，复用现有 Subject、Memory、Provider、图像适配器、Storage 和 Node/Envoy 通道。Orchestrator 不再初始化 Storage 或 Memory，不管理连接测试，不读取或编译 Subject，也不解析 Forge 内部资源。

## 新模块职责表

| 模块 | 所有权与职责 | 主要实现 |
| --- | --- | --- |
| Orchestrator | 接收生成任务、单任务准入、任务状态、请求 ID 去重、失败响应、任务结果/引用汇总 | `Archon/Orchestrator/orchestrator/core/orchestrator.py` |
| TaskRunner | Concept → Image 串行步骤、指令转交、结果转交 Concept 完成回调 | `Archon/Orchestrator/orchestrator/core/task_runner.py` |
| Concept Forge | Provider/模型、连接管理和测试；讨论、会话、Memory、Subject、提示词计划及生成成功记录 | `concept_forge/workspace.py`、`planning.py`、`factory.py`、既有 `service.py` / `subjects` / `Memory` |
| Ledger | 复用原 SQLite/四文档持久化实现，提供事务、历史读取、修订一致性和文档保存；不生成或解释 Subject | `Archon/Ledger/store.py` |
| Image Forge | ComfyUI/Diffusers 选择、workflow/checkpoint/VAE/LoRA 解析、种子及批量提交、插件/健康/历史、生成结果查询 | `image_forge/management.py`、`factory.py`、既有 `gateway.py` / adapters |
| Aegis / Storage | R2、直接下载、路径配置、资源扫描/拉取、输出文件读取/分块传输/缓存、上传、备份、恢复、归档 | `Aegis/Storage/service.py`、`output_resources.py`、既有四个管理器 |
| Vault | 私有连接配置读写、凭据、运行配置载入；保持既有私有数据文件格式和位置 | `Archon/Vault/concept_configuration.py`、`runtime_config.py`、既有凭据实现 |
| Gate / Portal | 模块装配、旧 HTTP API 转发、WebUI、资源目录响应合并、Forge Node binding/remote target | `Archon/Gate/application.py`、`application_server.py`、既有 `forge_bindings.py` |
| Steward / NodeManager | 注册、心跳、online/offline、节点资源与生命周期状态 | 本次未更改协议或实现 |
| Steward / DeploymentManager | 部署和部署进度 | 本次未更改 |
| Warden / Envoy | 节点运行时、进程/后端生命周期、既有 Agent 通信 | Warden 仅更新默认配置路径；Envoy 未更改 |
| Audio / Video Forge | 后续独立 Forge 的边界 | 本次未新增执行通道 |

## 从 Orchestrator 移出的全部 public methods（47 个）

以下方法保留原 HTTP 行为，由 Gate 显式转发给业务所有者；Orchestrator 类中不存在这些方法。

### Concept Forge（21 个）

实现：`Legate/Forge/ConceptForge/concept_forge/workspace.py`。

`discuss`, `get_session_subject`, `select_session_subject`, `get_history`, `clear_memory`, `save_subject`, `generate_subject`, `update_subject`, `get_subject`, `subject_bundle`, `revise_subject_group`, `list_subjects`, `get_subject_revisions`, `compile_subject`, `concept_connections`, `save_concept_connection`, `test_concept_connection`, `start_concept_connection_test`, `concept_connection_test_job`, `remove_concept_connection`, `default_concept_connection`。

### Image Forge（8 个）

实现：`Legate/Forge/ImageForge/image_forge/management.py`。

`image_health`, `image_plugins`, `image_plugin_job`, `start_image_plugin`, `set_default_image_plugin`, `image_results`, `image_history`, `image_path`。

### Storage（17 个）

实现：`Aegis/Storage/service.py`。

`storage_resources`, `export_data_archive`, `restore_data_archive`, `storage_scan`, `start_storage_scan`, `backup_resources`, `restore_points`, `start_restore`, `save_storage_paths`, `start_backup`, `backup_job`, `start_storage_pull`, `storage_job`, `start_download`, `download_job`, `cancel_download`, `retry_download`。

### Gate（1 个）

`resources`：只合并 Concept 和 Image 各自提供的目录，业务资源的枚举/默认选择分别归 Forge。

`image_results` 原本按 Image job IDs 查询结果，不是 Orchestrator task 的结果接口，因此整体移给 Image Forge。Orchestrator task 的结果引用和汇总仍在 `task_job(...)["response"]` 中。

## 保留的职责和 public methods

| 方法 | 当前行为 |
| --- | --- |
| `Orchestrator.submit` | 输入验证、准入、调用 TaskRunner、收集通知并汇总响应、失败时释放准入 |
| `Orchestrator.start_task` | 创建后台任务；维护 queued/running/completed/failed；同一 request ID 防重复提交；拒绝 ID 冲突 |
| `Orchestrator.task_job` | 返回该编排任务的状态、失败信息或结果汇总 |
| `TaskRunner.run` | 调用 Concept 的生成准备接口 → 把不透明指令交给 Image → 将结果交还 Concept 完成接口 |

Orchestrator 持有注入的 Forge 调用接口。具体 Node 定位仍由 Gate 的 Forge binding/remote target 完成，并由各 Forge 的远端适配器使用既有 NodeManager/Envoy 通道执行。没有删除“选择 Forge / 调用远端 Forge”的能力。

原 TaskRunner 的 Provider/模型枚举、模型校验与提示词计划迁入 Concept；engine/workflow/checkpoint/VAE/LoRA/seed/batch submission 迁入 Image。Orchestrator 只完整转交旧 UI options，不读取这些字段。

`_connection_test_jobs` 及测试锁/线程迁入 Concept；`_task_jobs` 留在 Orchestrator。生成期间的 Concept 维护锁供 Storage 归档/恢复协调使用，Storage 不再访问 Orchestrator 或其状态。Forge binding 的 busy 判断继续覆盖生成、讨论和维护。

本次保存现有任务语义：`completed` 表示规划和图像提交完成，实际图像渲染状态由 Image Forge 返回。任务 map 仍在内存中；没有新增并行调度、工作流持久化、自动重新生成或新的超时/重试系统。编排层的后续超时、失败、重试、恢复应针对 Forge 调用与步骤，Forge 内模型输出重试仍属于 Concept。

## 兼容性与运行位置

- HTTP URL、WebUI 数据形状、Node 注册协议和 Envoy task action 保持一致。
- 保留原 Python server/config/remote adapter/binding import 的薄兼容入口；它们不再含业务实现。
- 默认运行 JSON 与 loader 移至 Vault，旧 `EVERSPARK_ORCHESTRATOR_CONFIG` 和自定义配置文件继续使用。
- 私有连接数据仍在 `Data/Configuration/ConceptForge/connections.json`，由 Vault 读写，不需要导入第二份连接/Subject/Memory 系统。
- 分布式模式的 Forge 管理代码仍在本地主机运行，通过既有远端 adapter 调用两个 Node 上的执行器。Concept 的 Ledger 数据仍在本地主机；本次不新增远端业务服务协议。

## 测试与验证

| 测试范围 | 结果 |
| --- | --- |
| Archon | 115 个通过 |
| Orchestrator / Image / HTTP / 新职责边界 | 45 个通过 |
| Memory / Ledger 兼容 | 7 个通过 |
| Concept Forge | 21 个通过；另有 new/validate/compile CLI smoke 通过 |
| Storage / Infrastructure | 27 个通过 |
| WebUI Python | 15 个通过 |
| Configuration | 8 个通过 |
| Runtime Models | 4 个通过 |
| Runtime Logging | 14 个通过；日志 shell 用例通过 |
| Runtime Managed | 18 个中 16 个通过，2 个失败；基线 b4607ab 同样失败 |
| WebUI JS | 5 个测试文件共 14 个 Node test cases 通过；app.js 语法检查通过 |
| Launcher / System / Hardware / 本地基础设施 | shell 用例通过 |
| Cloudflare lifecycle | 停止用例失败；基线 b4607ab 同样失败 |
| 编译/差异检查 | Python compileall、启动脚本 bash -n、git diff --check 通过 |

现有 Python 范围共 274 个测试：272 通过，2 个失败。本次迁移直接相关的 230 个 Python 测试全部通过。

基线复现的失败：`test_share_reuses_link_and_stops_only_its_owned_process`（fake Cloudflare process 立即退出）；`test_managed_process_start_status_and_stop`（无法记录进程身份，单独复测曾通过）；`test_cloudflare_lifecycle.sh`（停止后仍检测到 fake tunnel）。本次未修改相关进程与网络生命周期实现，未将这类修复加入职责迁移。

新增 12 个用例覆盖：Orchestrator public API/依赖边界、TaskRunner 不透明指令传递、失败释放准入、Ledger 不解释 Concept 业务、Vault 私有配置持久化、Image 失败不写入 Subject/prompt/history、非法会话 options 不泄漏锁、Storage/Concept 维护互斥、输出传输原子性/缓存/大小校验/路径越界，以及完整两节点 Concept 业务和 Ledger 保存。

特别验证的分布式闭环：本地主机 WebUI → Gate Node binding → Orchestrator → Concept Node（Subject 生成与提示词规划）→ Image Node（资源/默认负面提示词/提交）→ 结果轮询 → Storage 输出缓存/文件回传。新增用例没有替换 Subject 处理逻辑，确认两个 Concept chat、一次 Image submit，Subject 与任务引用一致，历史写入成功，重新打开 Ledger 能读取 Subject，输出字节一致。另有既有绑定恢复、离线拒绝和独立 Node ID / 旧 provider ID 通道回归用例通过。

这些是使用确定性执行结果的 Node/HTTP 集成测试；当前环境没有用户的两台 GPU 实机，未把集成测试等同于真实模型重新生成。

## 修改文件清单

- `Aegis/Shared/errors.py`
- `Aegis/Shared/text.py`
- `Aegis/Storage/output_resources.py`
- `Aegis/Storage/service.py`
- `Archon/Gate/CLI/archon.py`
- `Archon/Gate/application.py`
- `Archon/Gate/application_server.py`
- `Archon/Gate/forge_services.py`
- `Archon/Gate/remote_runtime.py`
- `Archon/Gate/remote_target.py`
- `Archon/Ledger/__init__.py`
- `Archon/Ledger/store.py`
- `Archon/Orchestrator/README.md`
- `Archon/Orchestrator/Scripts/start_core.sh`
- `Archon/Orchestrator/orchestrator/__init__.py`
- `Archon/Orchestrator/orchestrator/config/config.py`
- `Archon/Orchestrator/orchestrator/config/default_config.json`
- `Archon/Orchestrator/orchestrator/core/forge_bindings.py`
- `Archon/Orchestrator/orchestrator/core/orchestrator.py`
- `Archon/Orchestrator/orchestrator/core/remote_concept.py`
- `Archon/Orchestrator/orchestrator/core/remote_image.py`
- `Archon/Orchestrator/orchestrator/core/remote_target.py`
- `Archon/Orchestrator/orchestrator/core/server.py`
- `Archon/Orchestrator/orchestrator/core/task_runner.py`
- `Archon/Orchestrator/orchestrator/core/text.py`
- `Archon/Vault/concept_configuration.py`
- `Archon/Vault/default_config.json`
- `Archon/Vault/runtime_config.py`
- `Docs/Architecture.md`
- `Docs/Architecture.zh-CN.md`
- `Docs/Orchestrator-Boundaries.zh-CN.md`
- `Legate/Forge/ConceptForge/Memory/everspark_memory/__init__.py`
- `Legate/Forge/ConceptForge/Memory/everspark_memory/store.py`
- `Legate/Forge/ConceptForge/concept_forge/__init__.py`
- `Legate/Forge/ConceptForge/concept_forge/connections.py`
- `Legate/Forge/ConceptForge/concept_forge/factory.py`
- `Legate/Forge/ConceptForge/concept_forge/planning.py`
- `Legate/Forge/ConceptForge/concept_forge/remote.py`
- `Legate/Forge/ConceptForge/concept_forge/service.py`
- `Legate/Forge/ConceptForge/concept_forge/workspace.py`
- `Legate/Forge/ImageForge/image_forge/__init__.py`
- `Legate/Forge/ImageForge/image_forge/factory.py`
- `Legate/Forge/ImageForge/image_forge/gateway.py`
- `Legate/Forge/ImageForge/image_forge/management.py`
- `Legate/Forge/ImageForge/image_forge/remote.py`
- `Legate/Forge/ImageForge/remote_task.py`
- `Legate/Forge/forge_errors.py`
- `Legate/Warden/image_backend.py`
- `Tests/Archon/test_node_bridge.py`
- `Tests/Archon/test_remote_creation_webui.py`
- `Tests/Infrastructure/test_output_resources.py`
- `Tests/Orchestrator/test_boundaries.py`
- `Tests/Orchestrator/test_orchestrator.py`
