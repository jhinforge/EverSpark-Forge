/* UI copy only. Brand names, model names, paths, JSON and user content stay intact. */
(() => {
  const zh = {
    "Workspace navigation": "工作区导航",
    "Forge Console": "Forge 控制台",
    "Subjects": "角色",
    "Gallery": "图库",
    "Storage": "存储",
    "Runtime": "运行状态",
    "Language": "语言",
    "Checking runtime": "正在检查运行环境",
    "Connecting to local services": "正在连接本地服务",
    "LOCAL-FIRST · V0.1": "本地优先 · V0.1",
    "Source code": "源代码",
    "WORKSPACE / FORGE": "工作区 / FORGE",
    "WORKSPACE / SUBJECTS": "工作区 / 角色",
    "WORKSPACE / GALLERY": "工作区 / 图库",
    "WORKSPACE / STORAGE": "工作区 / 存储",
    "WORKSPACE / RUNTIME": "工作区 / 运行状态",
    "Turn an idea into an image.": "把想法变成图像。",
    "Build identity that persists.": "建立可持续使用的角色形象。",
    "Review the latest outputs.": "查看最近生成的图像。",
    "Manage models and backups.": "管理模型与备份。",
    "Know what is ready.": "查看各服务是否就绪。",
    "Refresh": "刷新",
    "＋ New conversation": "＋ 新建对话",
    "New conversation": "新建对话",
    "Dismiss": "关闭提示",
    "CHARACTER SUBJECT": "角色主体",
    "Identity anchor": "主体形象",
    "Current character": "当前角色",
    "Choose a character": "选择已有角色",
    "Use in Forge": "用于 Forge",
    "No identity extracted yet": "尚未生成角色形象",
    "Talk naturally. EverSpark will build the current character from this conversation.": "直接描述你的想法，EverSpark 会根据对话建立当前角色。",
    "View revision history →": "查看修订历史 →",
    "Identity is extracted automatically. Scene, pose and camera remain request-level details.": "主体形象会自动提取；场景、姿势和镜头由每次请求决定。",
    "IMAGE FORGE": "IMAGE FORGE",
    "Generation canvas": "生成画布",
    "Ready": "就绪",
    "Workflow": "工作流",
    "Drawing tool": "绘图工具",
    "Set as default": "设为默认",
    "Install tool": "安装工具",
    "Enable tool": "启动工具",
    "Not installed": "未安装",
    "Offline": "未运行",
    "Installing tool": "正在安装工具",
    "Enabling tool": "正在启动工具",
    "Concept LLM": "Concept LLM",
    "Add": "添加",
    "Your next frame starts here": "下一张图像从这里开始",
    "Discuss the character or switch to Generate when the current concept is ready.": "先讨论角色，准备好后切换到生成。",
    "Conversation": "对话",
    "Conversation mode": "对话模式",
    "Generation resources": "生成资源",
    "Discuss": "讨论",
    "Generate": "生成",
    "Forge image": "生成图像",
    "No persistent subject": "暂无角色主体",
    "Let's design a character with long black hair and amber eyes...": "我们来设计一个黑色长发、琥珀色眼睛的角色……",
    "Place the current character on a rooftop at blue hour...": "让当前角色站在蓝调时刻的屋顶上……",
    "STRUCTURED STATE": "结构化数据",
    "Character subjects": "角色主体",
    "Each character has four JSON documents. Ask Concept Forge to revise a selected group, or choose Use in Forge to work with it in this conversation.": "每个角色包含四份 JSON。你可以让 Concept Forge 修改指定内容，或点击「用于 Forge」在当前对话中使用该角色。",
    "IMAGE FORGE OUTPUT": "IMAGE FORGE 输出",
    "Recent gallery": "最近生成",
    "Recent images reported by the configured image execution adapter.": "查看 Image Forge 最近生成的图像。",
    "Download outputs ZIP": "下载全部输出 ZIP",
    "Refresh gallery": "刷新图库",
    "LOCAL RUNTIME": "本地运行环境",
    "Service readiness": "服务状态",
    "Local mode requires no Cloudflare or R2 configuration.": "本地模式无需配置 Cloudflare 或 R2。",
    "Run checks": "检查状态",
    "FIRST RUN": "首次使用",
    "Bring each layer online": "启动各项服务",
    "Install runtime and models": "安装运行环境和模型",
    "Start every local service": "启动本地服务",
    "Verify readiness": "确认服务状态",
    "Image generation also needs a configured Image Forge adapter and workflow. Optional remote storage and Cloudflare networking remain disabled until explicitly enabled.": "图像生成还需配置 Image Forge 适配器和工作流。远端存储与 Cloudflare 网络功能需主动启用。",
    "MODELS & DATA": "模型与数据",
    "Install models, pull from remote storage, and back up local data.": "安装模型、从远端拉取资源，以及备份本地数据。",
    "OPTIONAL R2 STORAGE": "可选 R2 存储",
    "Remote model library": "远端模型库",
    "Remote storage is disabled in local mode.": "本地模式尚未启用远端存储。",
    "Scanning remote model directories…": "正在扫描远端模型目录……",
    "Remote scan failed": "远端扫描失败",
    "Cloudflare timed out waiting for the server (HTTP 524). Check the Storage scan status or retry over SSH.": "Cloudflare 等待服务器超时（HTTP 524）。请查看 Storage 扫描状态，或通过 SSH 访问后重试。",
    "Remote scan returned no data": "远端扫描没有返回数据",
    "Scan R2": "扫描 R2",
    "Diffusion model": "扩散模型",
    "Download": "下载",
    "REMOTE PATHS": "远端路径",
    "Directory mappings": "目录映射",
    "Automatic discovery searches model folders within the configured remotes. Add manual source directories when names differ. Upload targets must be writable physical remotes, not a union.": "系统会在配置的远端目录中自动寻找模型文件夹。名称不同时可手动指定来源；上传目标须为可写的实际远端路径，不能使用 union。",
    "Checkpoint source": "Checkpoint 来源目录",
    "Checkpoint upload target": "Checkpoint 上传目录",
    "Diffusion source": "扩散模型来源目录",
    "Diffusion upload target": "扩散模型上传目录",
    "LoRA source": "LoRA 来源目录",
    "LoRA upload target": "LoRA 上传目录",
    "VAE source": "VAE 来源目录",
    "VAE upload target": "VAE 上传目录",
    "Ollama/GGUF source": "Ollama/GGUF 来源目录",
    "GGUF upload target": "GGUF 上传目录",
    "Data backup target": "数据备份目录",
    "Default: bucket/everspark-backups": "默认：bucket/everspark-backups",
    "Save mapping and scan": "保存映射并扫描",
    "LOCAL DATA": "本地数据",
    "Character and Memory ZIP": "角色与 Memory 压缩包",
    "Download the four JSON documents for every character with a consistent Memory SQLite snapshot. Choose a ZIP below and click Validate and restore to upload, verify and place its data. Current data is saved in Data/Recovery; restart EverSpark after restoring.": "打包每个角色的四份 JSON 与一致的 Memory SQLite 快照。选择下面的 ZIP，点击「验证并恢复」后会上传、校验并归位。当前数据会保存在 Data/Recovery；恢复后请重启 EverSpark。",
    "Download data ZIP": "下载数据 ZIP",
    "Choose EverSpark data ZIP": "选择 EverSpark 数据 ZIP",
    "Validate and restore": "验证并恢复",
    "Could not create data ZIP": "无法生成数据 ZIP",
    "Choose an EverSpark data ZIP first.": "请先选择 EverSpark 数据 ZIP。",
    "ZIP upload must be between 1 byte and 128 MiB": "ZIP 大小须在 1 字节至 128 MiB 之间",
    "Replace local character JSON and SQLite with this ZIP? Current data will be kept in Data/Recovery. Restart EverSpark after restore.": "要用这个 ZIP 替换本地角色 JSON 和 SQLite 吗？原有数据将保存在 Data/Recovery。恢复后请重启 EverSpark。",
    "Restored {count} characters. Previous data is in {path}. Restart EverSpark to load the restored Memory.": "已恢复 {count} 个角色。原有数据位于 {path}。请重启 EverSpark 以加载恢复后的 Memory。",
    "REMOTE BACKUP": "远端备份",
    "Upload local data": "上传本地数据",
    "Select local models and character JSON files, or the complete outputs folder. Back up Memory too to preserve subject links and revisions.": "选择本地模型、角色 JSON 或整个输出文件夹。建议同时备份 Memory，以保存角色关联与修订记录。",
    "Scan changes": "扫描本地文件",
    "Save a new Memory database snapshot": "生成新的 Memory 数据库快照",
    "Upload selected": "上传所选文件",
    "Restore character data": "恢复角色数据",
    "Restore one complete batch of character JSON and Memory SQLite. Current data is saved under Data/Recovery before replacement. Restart EverSpark after restoring.": "选择完整备份批次，恢复角色 JSON 与 Memory SQLite。覆盖前会把当前数据保存到 Data/Recovery；恢复后请重启 EverSpark。",
    "Find restore points": "查找恢复点",
    "Data restore point": "数据恢复点",
    "Restore selected batch": "恢复所选批次",
    "DIRECT DOWNLOADS": "直链下载",
    "Install models from a URL": "通过链接安装模型",
    "Paste a direct HTTP download link. Files are staged safely, then added to EverSpark's managed model paths.": "粘贴模型直链。文件会先暂存，下载完成后加入 EverSpark 管理的模型目录。",
    "Image model": "图像模型",
    "Model type": "模型类型",
    "Direct URL": "直链地址",
    "File name": "文件名",
    "optional": "可选",
    "Download image model": "下载图像模型",
    "GGUF language model": "GGUF 语言模型",
    "Ollama name": "Ollama 模型名",
    "Download and register": "下载并注册",
    "Cancel": "取消",
    "Retry": "重试",
    "IMMUTABLE HISTORY": "修订历史",
    "Subject revisions": "角色修订记录",
    "Close": "关闭",
    "Generated image": "生成图像",
    "Unknown time": "时间未知",
    "Selected LoRA": "已选择的 LoRA",
    "Model": "模型",
    "Model strength": "模型强度",
    "CLIP strength": "CLIP 强度",
    "Remove {name}": "移除 {name}",
    "{name} model strength": "{name} 模型强度",
    "{name} CLIP strength": "{name} CLIP 强度",
    "Checkpoint VAE": "Checkpoint 内置 VAE",
    "No remote models found": "没有找到远端模型",
    "{name} · installed": "{name} · 已安装",
    "Installed": "已安装",
    "R2 is connected. Downloads are selective and never restore the legacy ComfyUI runtime.": "R2 已连接。模型按需下载，不会恢复旧版 ComfyUI 运行目录。",
    "Remote storage is disabled in local mode. Configure the rclone backend to enable it.": "本地模式尚未启用远端存储。请配置 rclone 后再使用。",
    "Remote mappings saved.": "远端映射已保存。",
    "{count} local files found. Data backup target: {remote}. Character JSON and SQLite are saved together.": "找到 {count} 个本地文件。数据备份目录：{remote}。角色 JSON 与 SQLite 会成套备份。",
    "Enable rclone storage to upload backups.": "启用 rclone 存储后即可上传备份。",
    "{name} · {size} · same size remotely": "{name} · {size} · 远端文件大小相同",
    "{name} · {size} · needs upload": "{name} · {size} · 待上传",
    "Outputs folder · no files": "输出文件夹 · 暂无文件",
    "Outputs folder · {count} files · {size} · {pending} pending": "输出文件夹 · {count} 个文件 · {size} · {pending} 个待上传",
    "Outputs folder · {count} files · {size} · up to date": "输出文件夹 · {count} 个文件 · {size} · 已同步",
    "Upload destination for {name}": "{name} 的上传目标",
    "No writable target: set a category upload path above.": "没有可写目标，请在上方设置该类模型的上传目录。",
    "{status}: {current}": "{status}：{current}",
    "{name}: {status} · {percent}%": "{name}：{status} · {percent}%",
    "{name}: {status}{progress}": "{name}：{status}{progress}",
    "{done}/{total} files · {copied} / {size}": "{done}/{total} 个文件 · {copied} / {size}",
    "Backup job disappeared": "备份任务已不存在",
    "Backup upload failed": "备份上传失败",
    "Upload failed": "上传失败",
    "Select a file, outputs folder, or Memory snapshot first.": "请先选择文件、输出文件夹或 Memory 快照。",
    "{date} · {count} characters · {size}": "{date} · {count} 个角色 · {size}",
    "Replace local character JSON and SQLite with this backup? Current data will be kept in Data/Recovery. Restart EverSpark after restore.": "要使用此备份替换本地角色 JSON 和 SQLite 吗？当前数据会保存在 Data/Recovery。恢复后请重启 EverSpark。",
    "queued": "排队中",
    "running": "进行中",
    "registering": "注册中",
    "downloading": "下载中",
    "completed": "已完成",
    "failed": "失败",
    "cancelled": "已取消",
    "preparing": "准备中",
    "ETA {time}": "预计剩余 {time}",
    "{count} files": "{count} 个文件",
    "Remote download job disappeared": "远端下载任务已不存在",
    "Remote download failed": "远端下载失败",
    "Registering {name} with Ollama": "正在向 Ollama 注册 {name}",
    "Direct download job disappeared": "直链下载任务已不存在",
    "No persistent subject": "暂无角色主体",
    "Identity ready": "主体形象已就绪",
    "{name} · revision {revision}": "{name} · 第 {revision} 版",
    "No subjects yet. Start a conversation and EverSpark will extract one automatically.": "尚无角色。开始对话后，EverSpark 会自动提取。",
    "REVISION {number}": "第 {number} 版",
    "View four JSON documents →": "查看四份 JSON →",
    "Hide documents ↑": "收起文档 ↑",
    "Subject JSON": "主体形象 JSON",
    "Metadata JSON": "Metadata JSON",
    "Positive prompt JSON": "正面提示词 JSON",
    "Negative prompt JSON": "负面提示词 JSON",
    "Tell Concept Forge what to change in {group}": "告诉 Concept Forge 如何修改{group}",
    "Describe changes to {group}": "描述对{group}的修改",
    "Ask model to update": "让模型修改",
    "Loading revision history...": "正在读取修订历史……",
    "Revision {number}": "第 {number} 版",
    "You": "你",
    "Queued {count} image request.": "已提交 {count} 张图像请求。",
    "Thinking": "思考中",
    "Failed": "失败",
    "Complete": "已完成",
    "Unavailable": "暂不可用",
    "Planning": "规划中",
    "{count} queued": "{count} 张图像已入队",
    "Say something about the current character.": "请先描述当前角色。",
    "Describe the scene before generating.": "生成前请先描述场景。",
    "Frame {number} · queued": "第 {number} 张 · 排队中",
    "Generation failed": "生成失败",
    "Image Forge is working": "Image Forge 正在处理",
    "Image Forge returned a failed task. Check the runtime logs.": "Image Forge 的任务失败，请查看运行日志。",
    "Concept Forge is shaping the request": "Concept Forge 正在处理请求",
    "Stable identity is being merged with this scene.": "正在将角色主体形象与场景合并。",
    "This task uses scene direction only.": "本次任务仅使用场景描述。",
    "Orchestrator did not return any queued frames.": "Orchestrator 没有返回已入队的图像。",
    "Loading Image Forge history...": "正在读取 Image Forge 历史……",
    "No generated images are available yet.": "目前还没有生成图像。",
    "Preparing ZIP…": "正在准备 ZIP……",
    "System ready": "系统已就绪",
    "Setup required": "需要完成配置",
    "All local services responding": "所有本地服务均有响应",
    "Open Runtime for details": "打开运行状态查看详情",
    "Status unavailable": "无法获取状态",
    "WebUI could not complete checks": "WebUI 未能完成检查",
    "Task routing and subject APIs are online.": "任务调度和角色 API 已就绪。",
    "Start with ./everspark orchestrator start": "请先运行 ./everspark orchestrator start",
    "The configured image adapter is responding.": "已配置的图像适配器有响应。",
    "Start or configure the image execution adapter.": "请启动或配置图像执行适配器。",
    "Runtime logs": "运行日志",
    "{present}/{configured} managed logs are present.": "已找到 {present}/{configured} 份托管日志。",
    "The runtime log manifest is unavailable.": "运行日志清单不可用。",
    "Invalid server response (HTTP {status})": "服务器响应无效（HTTP {status}）",
    "Request failed (HTTP {status})": "请求失败（HTTP {status}）",
  };

  const storageKey = "everspark.language";
  let language;
  try { language = localStorage.getItem(storageKey); } catch (_error) { /* Private browsing. */ }
  if (language !== "zh-CN" && language !== "en") {
    language = String(navigator.language || "").toLowerCase().startsWith("zh") ? "zh-CN" : "en";
  }
  const bound = new Set();
  const t = (key, args = {}) => {
    const template = language === "zh-CN" ? zh[key] || key : key;
    return template.replace(/\{([a-z_]+)\}/g, (match, name) =>
      Object.hasOwn(args, name) ? String(args[name]?.i18nKey ? t(args[name].i18nKey) : args[name]) : match);
  };
  function unbind(node) {
    for (const item of bound) if (item.node === node) bound.delete(item);
  }
  function bind(node, key, args = {}, property = "textContent") {
    if (!node) return;
    for (const item of bound) {
      if (item.node === node && item.property === property) bound.delete(item);
    }
    bound.add({ node, key, args, property });
    if (property === "textContent" && node.nodeType === Node.TEXT_NODE) node.textContent = t(key, args);
    else if (property in node) node[property] = t(key, args);
    else node.setAttribute(property, t(key, args));
  }
  function refresh() {
    for (const item of bound) {
      if (!item.node.isConnected) { bound.delete(item); continue; }
      const value = t(item.key, item.args);
      if (item.property === "staticText") item.node.textContent = item.prefix + value + item.suffix;
      else if (item.property === "textContent" && item.node.nodeType === Node.TEXT_NODE) item.node.textContent = value;
      else if (item.property in item.node) item.node[item.property] = value;
      else item.node.setAttribute(item.property, value);
    }
    document.documentElement.lang = language;
    const selector = document.getElementById("languageSelect");
    if (selector) selector.value = language;
  }
  function bindStatic() {
    const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
    const nodes = [];
    while (walker.nextNode()) nodes.push(walker.currentNode);
    for (const node of nodes) {
      if (node.parentElement?.closest("script, style, pre, code, select, [contenteditable], #conversationFeed, #subjectGrid")) continue;
      const key = node.textContent.trim();
      if (key && Object.hasOwn(zh, key)) {
        const prefix = node.textContent.match(/^\s*/)[0];
        const suffix = node.textContent.match(/\s*$/)[0];
        bound.add({ node, key, args: {}, property: "staticText", prefix, suffix });
      }
    }
    for (const element of document.querySelectorAll("[placeholder], [aria-label], [title], img[alt]")) {
      for (const attr of ["placeholder", "aria-label", "title", "alt"]) {
        const key = element.getAttribute(attr);
        if (key && Object.hasOwn(zh, key)) bind(element, key, {}, attr);
      }
    }
    refresh();
  }
  function setLanguage(next) {
    if (next !== "en" && next !== "zh-CN") return;
    language = next;
    try { localStorage.setItem(storageKey, language); } catch (_error) { /* Private browsing. */ }
    refresh();
  }
  window.EverSparkI18n = { t, bind, unbind, bindStatic, setLanguage, get language() { return language; }, translations: zh };
})();
