# 首次使用 EverSpark Forge

EverSpark Forge 是分布式 AI OS：主机运行控制与编排，Forge 在选定节点执行模型任务。本指南以已实测的 Windows 主机与 Linux NVIDIA GPU Pod 为主。

## 1. 选择启动方式

| 方式 | 需要准备 | 启动入口 |
| --- | --- | --- |
| Windows standard ZIP | Windows x64、系统已有 WebView2 | 解压后双击 `EverSpark.exe` |
| Windows full ZIP | Windows x64；包内附带固定版本 WebView2 | 解压后双击 `EverSpark.exe` |
| Windows 源码 | Git、Python 3.11.9 | PowerShell 执行 `.\everspark.cmd archon start` |

两个 ZIP 都包含便携 Python Runtime，不要求先安装 Python；不包含 GPU 模型、Tailscale、SSH 或 rclone。系统没有 WebView2 时选择 full。软件免费，GPU 租赁、网络和第三方模型服务可能另行收费。

从[官方仓库](https://github.com/jhinforge/EverSpark-Forge)公布的发布入口获取客户端。当前开发分支为 `refactor/distributed-architecture`；GitHub Actions 的 Windows portable client 成功运行提供两个 ZIP 和 SHA-256 文件。Actions 构建附件是临时测试分发，不是永久发布地址。

完整解压对应版本 ZIP 到可写目录，例如 `D:\EverSpark-Forge`，再双击 EXE；不要在压缩包内部运行。如果下载的是 Actions 附件，先解压外层附件，再选择 standard 或 full ZIP 解压。页面打开只代表主机启动成功，尚未部署 Forge 时不能生成。

### 从源码启动

在自己的 Windows PowerShell 中执行：

```powershell
git clone --branch refactor/distributed-architecture https://github.com/jhinforge/EverSpark-Forge.git
cd EverSpark-Forge
python --version
.\everspark.cmd archon start
```

浏览器打开终端打印的 Portal 地址，默认 `http://127.0.0.1:8780/`。保持终端运行，Ctrl+C 停止。不要同时运行命令行主机和桌面客户端。客户端使用动态本机端口，直接使用窗口即可，不要假定始终是 8780。

### SSH 工具与已有机器（按需）

客户端不附带 OpenSSH。SSH 部署／连接回退需要主机能运行 `ssh` 和 `ssh-keygen`；可先在 PowerShell 执行 `ssh -V` 检查。新自动节点通常不用手动登录；已有机器或直接使用 SSH 时，按云服务提供的用户、地址、端口和公钥入口配置。

需要自己创建密钥时，在本机运行 `ssh-keygen -t ed25519 -C "everspark-cloud"`，不要覆盖已有私钥。默认公钥可用 `Get-Content "$HOME/.ssh/id_ed25519.pub"` 查看，将完整公钥添加到机器授权入口；私钥留在本机。此手工密钥流程与 EverSpark 自动管理的部署身份不同，不要随意替换自动身份文件。

## 2. 配置账户与节点连接

1. 打开 [Tailscale Windows 官方下载页](https://tailscale.com/download/windows)，在 Windows 主机安装 Tailscale，然后登录并确认已连接自己的虚拟局域网。
2. 在 **设置 → 账户与节点** 填写自己的 Vast API Key，点击 **验证并保存**。密钥保存在当前 Windows 用户的凭据管理器。
3. 使用与 Windows 主机相同的 Tailscale 账户打开 [Auth Key 管理页](https://console.tailscale.com/admin/settings/keys)，点击 **Generate auth key**。如果要用同一个密钥租用多台 Pod，开启 **Reusable**；只连接一台新 Pod 时可以使用单次密钥。设置有效期后点击 **Generate key**，复制生成的完整密钥。
4. 回到 EverSpark 同一页的 **自动连接节点**，填入刚生成的 **Auth Key**（通常以 `tskey-auth-` 开头），不是 Tailscale API Key。此密钥用于让 Pod 加入主机所在的 Tailscale 网络。选择单次或可重复使用模式，必须与密钥本身的 Reusable 设置一致；有效期长不等于可重复使用。
5. 点击 **配置自动连接**，确认准备就绪。此密钥仅用于当前 Archon 会话；重新打开客户端后，租新 Pod 前应再次配置。已有节点有独立连接身份。

密钥选项的详细说明见 [Tailscale 官方 Auth Key 教程](https://tailscale.com/docs/features/access-control/auth-keys)。

Tailscale 网络策略和 Windows 防火墙需要允许节点连接主机显示的 Agent 端口（默认 TCP 8766），并允许主机访问节点媒体服务。只允许注册端口可能足以注册，却无法直接播放或下载媒体；节点媒体服务使用动态端口。

## 3. 租用 Pod 并部署 Forge

1. 打开 **计算 → 租用 GPU**，设置 GPU、地区和磁盘条件，搜索报价。搜索不会自动租赁；确认费用与机器条件后使用租用按钮。
2. 在 **计算 → 我的机器** 等待 Pod 和 Node Agent 在线。新 Pod 的启动流程自动加入 Tailscale 并启动 Agent，通常无需先手动 SSH。
3. 如网络测速要求确认 Ookla 条款，在页面查看条款后自行决定是否确认；测速不阻止 Forge 部署。
4. 在机器卡片部署需要的 Concept、Image 或 Audio Forge。等任务完成、源码检查和健康检查通过后，再选择该机器作为对应 Forge 的执行节点。

Forge 可部署在同一台或不同机器；同机部署不保证显存足以同时装载所有模型。首次生成可先完成图片模式，再部署 Audio 测试。部署失败时保留页面的阶段、退出码和诊断信息，见[排障指南](Troubleshooting.zh-CN.md)。

## 4. 完成第一次生成

| 模式 | 需要 |
| --- | --- |
| 图片 | Concept 能力（Ollama 节点或兼容 API）与 Image Forge |
| 音频 | Concept 能力与 Audio Forge；不要求 Image Forge |
| 图片＋音频 | Concept 能力、Image Forge、Audio Forge |

1. 打开 **创作**，选择模型服务与所需 Forge 节点。使用外部语言模型时，先按[配置指南](Configuration.zh-CN.md)保存并测试连接。
2. 图片模式检查 Workflow、Checkpoint 等资源；音频模式不显示图片设置。节点未提供资源时，在 **资源** 安装兼容模型后刷新。
3. 选择生成模式，输入自然语言需求并提交。例如：图片用“画一位银白色长发、穿蓝色礼服的少女”；音频用“用年轻少女的声音，以中文说：你好”；组合模式同时描述画面和台词。
4. 观察任务列表中的 Forge、执行节点和状态。跨机器部署不代表任务自动并行；当前任务按计划依赖顺序执行。
5. 在创作结果或 **资产库 → 图像／音频** 查看结果，尝试单文件和 ZIP 下载。桌面客户端下载会弹出另存为，可选目录和文件名；取消不保存。浏览器版遵循浏览器的下载设置。

需要角色一致性时，可先在讨论模式形成角色，再选择当前角色生成。日常操作见[使用指南](Usage.zh-CN.md)，数据位置与备份见[数据指南](Runtime-and-Data.zh-CN.md)。

## 5. 完成本次使用

关闭客户端会关闭它启动的本地主机进程，**不会销毁 Pod 或停止云端计费**。在计算页自行停止或销毁不再使用的实例，并先保存所需输出。更新流程见[更新指南](Updating.zh-CN.md)。

## Linux 单机模式（另一路径）

已有 Linux NVIDIA GPU 环境仍可使用 `./everspark setup --plan`、`./everspark setup`、`./everspark start` 部署本机托管服务；访问本机 8780，或显式运行 `./everspark share` 获取临时链接。此模式与 Windows 的 `archon start` 不同；不要要求 Windows 主机运行 Linux GPU 安装命令。详见[命令手册](Commands.zh-CN.md)。
