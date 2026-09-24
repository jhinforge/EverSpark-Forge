# 运行时与数据生命周期（v0.1）

这篇文档说明 EverSpark Forge 在云端 Linux 上安装、运行和迁移时，哪些内容来自源码，哪些保存在当前机器，哪些需要你自己带到下一台机器。安装步骤见[首次运行](Getting-Started.zh-CN.md)，私人配置的写法见[配置指南](Configuration.zh-CN.md)。

## 1. 从源码到运行中的服务

```text
获取源码 → setup 安装运行时与起步模型 → start 启动服务
       → WebUI 中讨论与生成 → 数据写入当前机器
       → 按需导出或上传 → 在新机器重新安装并恢复
```

`./everspark setup --plan` 先列出下载来源与目标，不改动机器。`./everspark setup` 创建运行目录，安装托管的 ComfyUI 与 Ollama，配置 Python 环境、模型路径并准备起步模型。`./everspark start` 依次启动 Concept Forge、Image Forge、Orchestrator、WebUI；`./everspark status` 返回服务的健康状态。默认只监听本机地址，云端机器可通过 `./everspark access` 给出的 SSH 转发方式访问 WebUI。

服务状态与进程身份记录在 `Data/Runtime/Services/`。`./everspark stop` 停止启动器管理的服务；对原本就在运行、由其他人或程序启动的健康服务，启动器会标为外部服务，不把它当作自己的进程停止。

## 2. 文件分别在哪里

以下路径均相对于仓库根目录；个人数据与安装产物不会随公开源码一起发布。

| 内容 | 默认位置 | 迁移时怎么处理 |
| --- | --- | --- |
| 程序代码、公开工作流 | Git 仓库，工作流在 `ImageForge/Workflows/` | 从仓库重新获取；自行新增但未提交的工作流要另行保存 |
| 私人环境配置 | 根目录 `.env` | 单独保存，或在新机器重新准备 `env.txt` 并导入 |
| 远程存储及 Tunnel 凭据、路径映射 | `Data/Configuration/` | 单独保存原始凭据和映射，或在新机器重新配置 |
| 托管的 ComfyUI、虚拟环境、进程状态 | `Data/Runtime/` | 通常由新机器上的 `setup` 重建 |
| 图片模型 | `Data/Models/ImageForge/` | 在新机器重新下载，或从自己配置的远程模型库选择性拉取 |
| Concept Forge 模型 | `Data/Models/ConceptForge/` | 重新下载，或从远程库恢复并按需导入 Ollama |
| 对话、任务记录、角色关联 | `Data/Memory/everspark.db` | 备份并恢复；只恢复角色 JSON 不足以保留这些关联 |
| 角色文档 | `Data/Subjects/` | 与 Memory 数据库一起备份和恢复 |
| 生成图片 | `Data/Outputs/` | 下载整个输出目录的 ZIP，或启用远程存储后上传整个目录 |
| 服务日志 | `Data/Logs/` | 排障时留存；新环境会重新生成 |
| 数据恢复前的本地旧版本 | `Data/Recovery/` | 恢复角色数据时生成；其安全性取决于当前机器是否仍在 |

Git 默认忽略 `.env`、`Configuration/Import/` 下的私人上传文件及 `Data/`。**“被 Git 忽略”只表示不会随普通提交进入仓库，不表示已经有备份。** 如果云端机器的磁盘是临时的，删除实例前应确认所需数据已传到别处。

## 3. 生成时发生了什么

WebUI 的讨论模式通过 Concept Forge 更新当前对话的角色主体；角色文档和修订记录由 Memory 保留。生成模式将角色的稳定特征与本次场景描述组合，由 Orchestrator 提交给 Image Forge，再在 WebUI 显示结果。模型、工作流、Checkpoint、VAE 与 LoRA 的选择来自当前机器可用的资源。

Gallery 显示近期结果，**Download outputs ZIP** 将当前 `Data/Outputs` 整棵目录打包下载。这是手动导出：打开过 Gallery 或看见生成图片，不等于文件已经离开云端机器。

## 4. 备份：先确定需要保存什么

不开启 rclone 时，可通过 Gallery 下载输出 ZIP，并自行保存私人配置、角色与 Memory 数据及所需模型。不要在服务仍写入 SQLite 时仅随手复制单个数据库文件，就把它视为一致的角色备份。

启用并验证 rclone 后，在 WebUI 的 **Storage → Upload local data** 中按需发起上传：

1. 模型可按类别选择，上传目标需要是可写的实际 remote；多个目标时要选定位置。
2. 选择 **Outputs folder** 会上传整个 `Data/Outputs` 中当前找到的文件；不需要逐张勾选。新文件不会因为以前上传过就自动同步，需要再次发起上传。
3. 保存角色时选择 **Save a new Memory database snapshot**。角色 JSON 与 SQLite 会作为同一批数据快照上传；恢复点包含校验信息。页面选择角色文件时，后端也会按完整数据集处理，而不是上传孤立的角色 JSON。
4. 等待上传任务显示完成，再检查远程位置或恢复点。仅配置远程地址、扫描资源或启动服务，都不会替你自动完成这些上传。

如未指定 `EVERSPARK_BACKUP_REMOTE`，程序使用第一个图片模型来源桶下的 `everspark-backups` 前缀。这个目录用于输出与角色数据备份；模型按各自分类的远程目录处理。上传不会清理远程旧文件。

## 5. 换一台云端机器时

以下是一条基于 v0.1 现有功能的恢复顺序：

1. 从 Git 获取源码，在新机器准备 Linux、NVIDIA GPU 和网络环境。
2. 如需原有远程资源或 Tunnel，将 `env.txt`、`rclone.conf`、Tunnel 凭据等原始文件上传到 `Configuration/Import/`，执行 `./everspark configure`。在旧机器 Storage 页面保存过的**手工远程路径映射**存放在 `Data/Configuration/rclone/model_paths.json`；若没有单独带走它，需在新机器重新设置。
3. 执行 `./everspark setup --plan`、`./everspark setup`、`./everspark doctor`、`./everspark start`，确认服务就绪。
4. 在 Storage 页面按需要从远程库拉取模型；如果没有远程库，可用直链重新下载。检查所选工作流所需的模型是否已在新机器上。
5. 如果做过角色数据快照，在 **Storage → Restore character data** 选择恢复点。程序会检查下载文件、SQLite 与角色文档，并把当前本地数据移到 `Data/Recovery/` 后替换。任务完成后重启 EverSpark，使服务重新读取恢复的数据。
6. 输出图片如果仍在原机器，可用 Gallery 下载 ZIP 并自行转移；如果已上传远程存储，也需通过自己的存储工具取回。v0.1 的 WebUI 恢复按钮只负责**角色数据快照**，不会一并取回输出图片。

不能从源码或默认 `setup` 推出你的个人角色、历史、输出或私人模型。迁移是否完整，取决于这些内容在旧机器删除前是否实际完成了备份或导出。

## 6. 运行状态与日志

```bash
./everspark status
./everspark doctor
./everspark restart image
./everspark stop
```

`status` 检查服务的进程与健康接口；`doctor` 检查基础命令、已启用后端的配置和 GPU 可见性。WebUI 的 **Runtime** 页面可查看就绪状态。托管服务的原始输出写在 `Data/Logs/`；如果生成、模型拉取或上传失败，先看对应服务的状态和任务报错，再查日志。日志有助于排障，但并不代替模型、角色或输出的备份。
