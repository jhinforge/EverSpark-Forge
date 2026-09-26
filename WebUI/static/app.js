const i18n = window.EverSparkI18n;
const t = (key, args) => i18n.t(key, args);
const uiText = (node, key, args) => i18n.bind(node, key, args);
const uiAttr = (node, property, key, args) => i18n.bind(node, key, args, property);

const state = {
  subjects: [],
  selectedSubject: null,
  selectingSubject: false,
  mode: "discuss",
  resources: { workflows: [], checkpoints: [], vaes: [], loras: [], llms: [], defaults: {}, loraStrengthMode: "independent" },
  remoteStorage: null,
  pathsLoaded: false,
  selectedLoras: [],
  imagePlugins: [],
  modelConnections: [],
  defaultImagePlugin: "comfyui",
  sessionId: localStorage.getItem("everspark.session") || crypto.randomUUID(),
  pollTimer: null,
  pollFailures: 0,
  storagePollJobId: null,
  remoteScanTimer: null,
  backupPollJobId: null,
  directDownloadPollJobId: null,
  directDownloadJob: null,
  storageJob: null,
  backupJob: null,
};
localStorage.setItem("everspark.session", state.sessionId);

const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => [...document.querySelectorAll(selector)];

const elements = {
  notice: $("#notice"),
  languageSelect: $("#languageSelect"),
  noticeText: $("#noticeText"),
  subjectCount: $("#subjectCount"),
  selectedEmpty: $("#selectedSubjectEmpty"),
  selectedCard: $("#selectedSubjectCard"),
  selectedName: $("#selectedSubjectName"),
  selectedId: $("#selectedSubjectId"),
  selectedRevision: $("#selectedSubjectRevision"),
  selectedTraits: $("#selectedSubjectTraits"),
  subjectAvatar: $("#subjectAvatar"),
  composerContext: $("#composerSubjectContext"),
  subjectGrid: $("#subjectGrid"),
  subjectPicker: $("#subjectPicker"),
  useSubjectButton: $("#useSubjectButton"),
  resultStage: $("#resultStage"),
  generationState: $("#generationState"),
  scenePrompt: $("#scenePrompt"),
  generateButton: $("#generateButton"),
  conversationFeed: $("#conversationFeed"),
  discussModeButton: $("#discussModeButton"),
  generateModeButton: $("#generateModeButton"),
  galleryGrid: $("#galleryGrid"),
  downloadOutputsButton: $("#downloadOutputsButton"),
  downloadDataButton: $("#downloadDataButton"),
  localDataFile: $("#localDataFile"),
  restoreDataButton: $("#restoreDataButton"),
  runtimeGrid: $("#runtimeGrid"),
  healthDot: $("#globalHealthDot"),
  healthTitle: $("#globalHealthTitle"),
  healthDetail: $("#globalHealthDetail"),
  revisionModal: $("#revisionModal"),
  revisionList: $("#revisionList"),
  imageViewer: $("#imageViewer"),
  viewerImage: $("#viewerImage"),
  workflowSelect: $("#workflowSelect"),
  imageEngineSelect: $("#imageEngineSelect"),
  imageEngineStatus: $("#imageEngineStatus"),
  imageEngineAction: $("#imageEngineAction"),
  imageEngineDefault: $("#imageEngineDefault"),
  checkpointSelect: $("#checkpointSelect"),
  vaeSelect: $("#vaeSelect"),
  llmSelect: $("#llmSelect"),
  conceptProviderSelect: $("#conceptProviderSelect"),
  modelServiceList: $("#modelServiceList"),
  modelServiceForm: $("#modelServiceForm"),
  modelServiceId: $("#modelServiceId"),
  modelServiceName: $("#modelServiceName"),
  modelServiceUrl: $("#modelServiceUrl"),
  modelServiceModel: $("#modelServiceModel"),
  modelServiceKey: $("#modelServiceKey"),
  modelServiceJsonMode: $("#modelServiceJsonMode"),
  modelServiceStream: $("#modelServiceStream"),
  loraSelect: $("#loraSelect"),
  addLoraButton: $("#addLoraButton"),
  selectedLoras: $("#selectedLoras"),
  storageSummary: $("#storageSummary"),
  refreshStorageButton: $("#refreshStorageButton"),
  storageProgress: $("#storageProgress"),
  storageProgressBar: $("#storageProgressBar"),
  storageJobStatus: $("#storageJobStatus"),
  storageProgressDetail: $("#storageProgressDetail"),
  backupSummary: $("#backupSummary"),
  backupFiles: $("#backupFiles"),
  backupMemory: $("#backupMemory"),
  startBackupButton: $("#startBackupButton"),
  backupProgress: $("#backupProgress"),
  backupProgressBar: $("#backupProgressBar"),
  backupJobStatus: $("#backupJobStatus"),
  backupProgressDetail: $("#backupProgressDetail"),
  remotePathsForm: $("#remotePathsForm"),
  conceptSourcePath: $("#conceptSourcePath"),
  conceptUploadPath: $("#conceptUploadPath"),
  dataBackupPath: $("#dataBackupPath"),
  restorePointSelect: $("#restorePointSelect"),
  startRestoreButton: $("#startRestoreButton"),
  refreshRestoreButton: $("#refreshRestoreButton"),
  remoteCheckpointSelect: $("#remoteCheckpointSelect"),
  remoteDiffusionSelect: $("#remoteDiffusionSelect"),
  remoteLoraSelect: $("#remoteLoraSelect"),
  remoteVaeSelect: $("#remoteVaeSelect"),
  remoteConceptSelect: $("#remoteConceptSelect"),
  imageDownloadForm: $("#imageDownloadForm"),
  imageDownloadKind: $("#imageDownloadKind"),
  imageDownloadUrl: $("#imageDownloadUrl"),
  imageDownloadFilename: $("#imageDownloadFilename"),
  loraDownloadForm: $("#loraDownloadForm"),
  loraDownloadUrl: $("#loraDownloadUrl"),
  loraDownloadFilename: $("#loraDownloadFilename"),
  vaeDownloadForm: $("#vaeDownloadForm"),
  vaeDownloadUrl: $("#vaeDownloadUrl"),
  vaeDownloadFilename: $("#vaeDownloadFilename"),
  conceptDownloadForm: $("#conceptDownloadForm"),
  conceptDownloadUrl: $("#conceptDownloadUrl"),
  conceptDownloadFilename: $("#conceptDownloadFilename"),
  conceptRuntimeName: $("#conceptRuntimeName"),
  directDownloadProgress: $("#directDownloadProgress"),
  directDownloadProgressBar: $("#directDownloadProgressBar"),
  directDownloadStatus: $("#directDownloadStatus"),
  directDownloadDetail: $("#directDownloadDetail"),
  cancelDirectDownload: $("#cancelDirectDownload"),
  retryDirectDownload: $("#retryDirectDownload"),
};

const viewCopy = {
  forge: ["WORKSPACE / FORGE", "Turn an idea into an image."],
  subjects: ["WORKSPACE / SUBJECTS", "Build identity that persists."],
  history: ["WORKSPACE / GALLERY", "Review the latest outputs."],
  storage: ["WORKSPACE / STORAGE", "Manage models and backups."],
  runtime: ["WORKSPACE / RUNTIME", "Know what is ready."],
  models: ["WORKSPACE / MODEL SERVICES", "Connect language models."],
};

async function api(path, options = {}) {
  const response = await fetch(path, { cache: "no-store", ...options });
  let data;
  try {
    data = await response.json();
  } catch (_error) {
    if (response.status === 524) {
      const error = new Error(t("Cloudflare timed out waiting for the server (HTTP 524). Check the Storage scan status or retry over SSH."));
      error.httpStatus = 524;
      throw error;
    }
    const error = new Error(`${t("Invalid server response (HTTP {status})", { status: response.status })} · ${path.split("?")[0]}`);
    error.httpStatus = response.status;
    throw error;
  }
  if (!response.ok || data.ok === false) {
    const error = new Error(data.error || t("Request failed (HTTP {status})", { status: response.status }));
    error.httpStatus = response.status;
    throw error;
  }
  return data;
}

function transientApiError(error) {
  return [502, 503, 504, 524].includes(error.httpStatus) || error instanceof TypeError;
}

function showNotice(message, type = "error") {
  elements.noticeText.textContent = message;
  elements.notice.classList.toggle("error", type === "error");
  elements.notice.classList.remove("hidden");
}

function hideNotice() {
  elements.notice.classList.add("hidden");
}

function initials(name) {
  const words = String(name || "ES").trim().split(/\s+/).filter(Boolean);
  return words.slice(0, 2).map((word) => word[0]).join("").toUpperCase() || "ES";
}

function formatDate(value) {
  if (!value) return t("Unknown time");
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? String(value) : date.toLocaleString(i18n.language);
}

function uiDate(node, value) {
  node.dataset.date = value || "";
  node.textContent = formatDate(value);
}

function formatBytes(value) {
  const bytes = Math.max(0, Number(value) || 0);
  if (bytes < 1024) return `${bytes.toFixed(0)} B`;
  const units = ["KiB", "MiB", "GiB", "TiB"];
  let scaled = bytes;
  let index = -1;
  do {
    scaled /= 1024;
    index += 1;
  } while (scaled >= 1024 && index < units.length - 1);
  return `${scaled.toFixed(scaled >= 100 ? 0 : 1)} ${units[index]}`;
}

function formatDuration(value) {
  const seconds = Math.max(0, Math.round(Number(value) || 0));
  if (seconds < 60) return `${seconds}s`;
  const minutes = Math.floor(seconds / 60);
  const remainder = seconds % 60;
  return `${minutes}m ${remainder}s`;
}

function fillSelect(select, items, valueFor, labelFor, preferred = "") {
  const previous = select.value;
  select.replaceChildren();
  for (const item of items) {
    const option = document.createElement("option");
    option.value = valueFor(item);
    option.textContent = labelFor(item);
    select.appendChild(option);
  }
  const candidates = [previous, preferred].filter(Boolean);
  for (const candidate of candidates) {
    const match = [...select.options].find((option) => option.value.toLowerCase() === candidate.toLowerCase());
    if (match) {
      select.value = match.value;
      break;
    }
  }
}

function selectedWorkflow() {
  return state.resources.workflows.find((item) => item.id === elements.workflowSelect.value);
}

function updateLoraAvailability() {
  const enabled = Boolean(selectedWorkflow()?.supports?.lora_injection && state.resources.loras.length);
  elements.loraSelect.disabled = !enabled;
  elements.addLoraButton.disabled = !enabled;
  if (!enabled && state.selectedLoras.length) {
    state.selectedLoras = [];
    renderSelectedLoras();
  }
}

function renderSelectedLoras() {
  elements.selectedLoras.replaceChildren();
  if (state.selectedLoras.length) {
    const header = document.createElement("div");
    header.className = "lora-row lora-header";
    for (const label of ["Selected LoRA", "Model", "CLIP", ""]) {
      const cell = document.createElement("span");
      uiText(cell, label);
      header.appendChild(cell);
    }
    elements.selectedLoras.appendChild(header);
  }
  for (const item of state.selectedLoras) {
    const row = document.createElement("div");
    row.className = "lora-row";
    const name = document.createElement("span");
    name.className = "lora-name";
    name.textContent = item.name;
    const model = document.createElement("input");
    model.type = "number";
    model.step = "0.05";
    model.min = "-10";
    model.max = "10";
    model.value = String(item.strength_model);
    uiAttr(model, "title", "Model strength");
    uiAttr(model, "aria-label", "{name} model strength", { name: item.name });
    model.addEventListener("change", () => {
      item.strength_model = Number(model.value);
      if (state.resources.loraStrengthMode === "shared") {
        item.strength_clip = item.strength_model;
        clip.value = model.value;
      }
    });
    const clip = document.createElement("input");
    clip.type = "number";
    clip.step = "0.05";
    clip.min = "-10";
    clip.max = "10";
    clip.value = String(item.strength_clip);
    clip.disabled = state.resources.loraStrengthMode === "shared";
    uiAttr(clip, "title", "CLIP strength");
    uiAttr(clip, "aria-label", "{name} CLIP strength", { name: item.name });
    clip.addEventListener("change", () => { item.strength_clip = Number(clip.value); });
    const remove = document.createElement("button");
    remove.type = "button";
    remove.textContent = "×";
    uiAttr(remove, "aria-label", "Remove {name}", { name: item.name });
    remove.addEventListener("click", () => {
      state.selectedLoras = state.selectedLoras.filter((selected) => selected !== item);
      renderSelectedLoras();
    });
    row.append(name, model, clip, remove);
    elements.selectedLoras.appendChild(row);
  }
}

function addSelectedLora() {
  const name = elements.loraSelect.value;
  if (!name || state.selectedLoras.some((item) => item.name === name)) return;
  state.selectedLoras.push({ name, strength_model: 1, strength_clip: 1 });
  renderSelectedLoras();
}

function generationSelection() {
  return {
    engine: elements.imageEngineSelect.value,
    workflow: elements.workflowSelect.value,
    checkpoint: elements.checkpointSelect.value,
    vae: elements.vaeSelect.value,
    llm: elements.llmSelect.value,
    concept_provider: elements.conceptProviderSelect.value,
    loras: state.selectedLoras.map((item) => ({ ...item })),
  };
}

function renderImagePlugin() {
  const plugin = state.imagePlugins.find((item) => item.id === elements.imageEngineSelect.value);
  if (!plugin) return;
  elements.imageEngineStatus.textContent = plugin.job_id ? t("Installing tool") :
    !plugin.installed ? t(plugin.online ? "Repair required" : "Not installed") :
    plugin.online ? t("Ready") : t("Offline");
  elements.imageEngineAction.hidden = (plugin.online && plugin.installed) || Boolean(plugin.job_id);
  elements.imageEngineAction.textContent = t(plugin.installed ? "Enable tool" :
    plugin.online ? "Repair tool" : "Install tool");
  elements.imageEngineAction.disabled = !plugin.installed && !plugin.installable;
  elements.imageEngineDefault.hidden = plugin.id === state.defaultImagePlugin || !plugin.installed;
}

async function loadImagePlugins() {
  try {
    const data = await api("/api/image/plugins");
    state.imagePlugins = data.plugins || [];
    state.defaultImagePlugin = data.default;
    fillSelect(elements.imageEngineSelect, state.imagePlugins, (item) => item.id, (item) => item.name, data.default);
    renderImagePlugin();
  } catch (error) {
    showNotice(error.message);
  }
}

async function manageImagePlugin() {
  const plugin = state.imagePlugins.find((item) => item.id === elements.imageEngineSelect.value);
  if (!plugin) return;
  const action = plugin.installed ? "enable" : "install";
  elements.imageEngineAction.disabled = true;
  try {
    const data = await api(`/api/image/plugins/${action}`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ plugin: plugin.id }),
    });
    elements.imageEngineStatus.textContent = t(action === "install" ? "Installing tool" : "Enabling tool");
    const poll = async () => {
      try {
        const result = await api(`/api/image/plugins/jobs?job_id=${encodeURIComponent(data.job.id)}`);
        if (result.job.status === "running") { setTimeout(poll, 2500); return; }
        await loadImagePlugins();
        if (result.job.status === "failed") showNotice(result.job.error);
        else await loadResources();
      } catch (error) { showNotice(error.message); }
    };
    setTimeout(poll, 2500);
  } catch (error) { showNotice(error.message); elements.imageEngineAction.disabled = false; }
}

async function defaultImagePlugin() {
  try {
    await api("/api/image/plugins/default", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ plugin: elements.imageEngineSelect.value }),
    });
    await loadImagePlugins();
  } catch (error) { showNotice(error.message); }
}

function updateConceptModels() {
  const provider = elements.conceptProviderSelect.value;
  const models = state.resources.conceptModels?.[provider] || [];
  const preferred = provider === state.resources.defaults.concept_provider
    ? state.resources.defaults.llm : state.resources.conceptProviders?.find((item) => item.id === provider)?.model;
  fillSelect(elements.llmSelect, models, (item) => item, (item) => item, preferred);
  elements.llmSelect.disabled = !models.length;
}

async function loadResources() {
  try {
    const engine = elements.imageEngineSelect.value;
    const plugin = state.imagePlugins.find((item) => item.id === engine);
    if (plugin && !plugin.online) {
      for (const select of [elements.workflowSelect, elements.checkpointSelect,
        elements.vaeSelect, elements.loraSelect]) {
        select.replaceChildren();
        select.disabled = true;
      }
      elements.addLoraButton.disabled = true;
      return;
    }
    const data = await api(`/api/resources?engine=${encodeURIComponent(engine)}`);
    if (engine !== elements.imageEngineSelect.value) return;
    state.resources = {
      workflows: data.workflows || [],
      checkpoints: data.checkpoints || [],
      vaes: data.vaes || [],
      loras: data.loras || [],
      llms: data.llms || [],
      defaults: data.defaults || {},
      loraStrengthMode: data.lora_strength_mode || "independent",
    };
    if (state.resources.loraStrengthMode === "shared") {
      state.selectedLoras.forEach((item) => { item.strength_clip = item.strength_model; });
      renderSelectedLoras();
    }
    fillSelect(elements.workflowSelect, state.resources.workflows, (item) => item.id, (item) => item.name, state.resources.defaults.workflow);
    fillSelect(elements.checkpointSelect, state.resources.checkpoints, (item) => item, (item) => item, state.resources.defaults.checkpoint);
    fillSelect(elements.vaeSelect, ["", ...state.resources.vaes], (item) => item, (item) => item || t("Checkpoint VAE"));
    state.resources.conceptProviders = data.concept_providers || [];
    state.resources.conceptModels = data.concept_models || {};
    fillSelect(elements.conceptProviderSelect, state.resources.conceptProviders,
      (item) => item.id, (item) => item.name, state.resources.defaults.concept_provider);
    updateConceptModels();
    fillSelect(elements.loraSelect, state.resources.loras, (item) => item, (item) => item);
    elements.workflowSelect.disabled = !state.resources.workflows.length;
    elements.checkpointSelect.disabled = !state.resources.checkpoints.length;
    elements.vaeSelect.disabled = !state.resources.vaes.length;
    elements.conceptProviderSelect.disabled = !state.resources.conceptProviders.length;
    updateLoraAvailability();
  } catch (error) {
    elements.workflowSelect.disabled = true;
    elements.checkpointSelect.disabled = true;
    elements.vaeSelect.disabled = true;
    elements.llmSelect.disabled = true;
    elements.conceptProviderSelect.disabled = true;
    elements.loraSelect.disabled = true;
    elements.addLoraButton.disabled = true;
    showNotice(error.message);
  }
}

function fillRemoteSelect(select, items) {
  select.replaceChildren();
  if (!items.length) {
    const option = document.createElement("option");
    option.value = "";
    uiText(option, "No remote models found");
    select.appendChild(option);
    select.disabled = true;
    return;
  }
  for (const item of items) {
    const option = document.createElement("option");
    option.value = item.id || item.name;
    option.textContent = `${item.name}${item.source ? ` · ${item.source}` : ""}`;
    if (item.installed) uiText(option, "{name} · installed", { name: option.textContent });
    option.dataset.installed = item.installed ? "true" : "false";
    select.appendChild(option);
  }
  select.disabled = false;
}

function storageSelect(kind) {
  return {
    checkpoint: elements.remoteCheckpointSelect,
    diffusion_model: elements.remoteDiffusionSelect,
    lora: elements.remoteLoraSelect,
    vae: elements.remoteVaeSelect,
    concept_model: elements.remoteConceptSelect,
  }[kind];
}

function updateStorageButtons() {
  $$(".storage-pull-button").forEach((button) => {
    const selected = storageSelect(button.dataset.kind)?.selectedOptions?.[0];
    const installed = selected?.dataset.installed === "true";
    button.disabled = !state.remoteStorage?.enabled || !selected?.value || installed;
    uiText(button, installed ? "Installed" : "Download");
  });
}

async function loadRemoteStorage(force = false) {
  if (state.remoteScanTimer) { window.clearTimeout(state.remoteScanTimer); state.remoteScanTimer = null; }
  try {
    let scan = await api("/api/storage/scan");
    if (force || scan.status === "idle") {
      scan = await api("/api/storage/scan", { method: "POST",
        headers: { "Content-Type": "application/json" }, body: "{}" });
    }
    elements.refreshStorageButton.disabled = scan.status === "running";
    if (scan.status === "failed") throw new Error(scan.error || t("Remote scan failed"));
    if (scan.status === "running") {
      uiText(elements.storageSummary, "Scanning remote model directories…");
      state.remoteScanTimer = window.setTimeout(() => { void loadRemoteStorage(); }, 3000);
      if (!scan.result) return;
    }
    const data = scan.result;
    if (!data) throw new Error(t("Remote scan returned no data"));
    state.remoteStorage = data;
    const image = data.image || {};
    fillRemoteSelect(elements.remoteCheckpointSelect, image.checkpoint || []);
    fillRemoteSelect(elements.remoteDiffusionSelect, image.diffusion_model || []);
    fillRemoteSelect(elements.remoteLoraSelect, image.lora || []);
    fillRemoteSelect(elements.remoteVaeSelect, image.vae || []);
    fillRemoteSelect(elements.remoteConceptSelect, data.concept?.models || []);
    if (!state.pathsLoaded && data.paths) {
      const configured = data.paths.configured || {};
      $$("[data-path-kind]").forEach((input) => {
        const kind = input.dataset.pathKind;
        input.value = input.dataset.pathField === "source"
          ? (configured.image_manual?.[kind] || []).join(", ")
          : (configured.image_upload?.[kind] || "");
      });
      elements.conceptSourcePath.value = (configured.concept_manual || []).join(", ");
      elements.conceptUploadPath.value = configured.concept_upload || "";
      elements.dataBackupPath.value = configured.backup_remote || "";
      state.pathsLoaded = true;
    }
    if (scan.status !== "running") uiText(elements.storageSummary, data.enabled
      ? "R2 is connected. Downloads are selective and never restore the legacy ComfyUI runtime."
      : "Remote storage is disabled in local mode. Configure the rclone backend to enable it.");
    updateStorageButtons();
    const jobs = await api("/api/storage/jobs");
    const active = jobs.job;
    if (active) {
      renderStorageJob(active);
      if (["queued", "running"].includes(active.status) && state.storagePollJobId !== active.job_id) {
        void pollStorageJob(active.job_id).catch((error) => {
          showNotice(error.message);
          updateStorageButtons();
        });
      }
    }
  } catch (error) {
    state.remoteStorage = null;
    elements.refreshStorageButton.disabled = false;
    i18n.unbind(elements.storageSummary);
    elements.storageSummary.textContent = error.message;
    $$(".storage-pull-button").forEach((button) => { button.disabled = true; });
  }
}

async function saveRemotePaths(event) {
  event.preventDefault();
  const paths = { image_manual: {}, image_upload: {}, concept_manual: [],
    concept_upload: elements.conceptUploadPath.value.trim(),
    backup_remote: elements.dataBackupPath.value.trim() };
  const split = (text) => text.split(/[,\n]+/).map((value) => value.trim()).filter(Boolean);
  $$("[data-path-kind]").forEach((input) => {
    const kind = input.dataset.pathKind;
    if (input.dataset.pathField === "source") paths.image_manual[kind] = split(input.value);
    else if (input.value.trim()) paths.image_upload[kind] = input.value.trim();
  });
  paths.concept_manual = split(elements.conceptSourcePath.value);
  try {
    await api("/api/storage/paths", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ paths }) });
    showNotice(t("Remote mappings saved."), "success");
    await Promise.all([loadRemoteStorage(true), loadBackup(), loadRestorePoints()]);
  } catch (error) { showNotice(error.message); }
}

async function loadBackup() {
  try {
    const data = await api("/api/backup/resources");
    elements.backupFiles.replaceChildren();
    elements.startBackupButton.disabled = !data.enabled;
    elements.backupMemory.disabled = !data.enabled || !data.memory;
    if (data.enabled) uiText(elements.backupSummary,
      "{count} local files found. Data backup target: {remote}. Character JSON and SQLite are saved together.",
      { count: data.files.length, remote: data.remote });
    else uiText(elements.backupSummary, "Enable rclone storage to upload backups.");
    if (data.enabled) {
      const outputs = data.files.filter((file) => file.name.startsWith("outputs/"));
      const pending = outputs.filter((file) => !file.backed_up).length;
      const folder = document.createElement("label");
      folder.className = "backup-file backup-output-folder";
      const checkbox = document.createElement("input");
      checkbox.type = "checkbox";
      checkbox.id = "backupOutputs";
      checkbox.checked = pending > 0;
      checkbox.disabled = !outputs.length;
      const description = document.createElement("span");
      uiText(description, !outputs.length ? "Outputs folder · no files"
        : pending ? "Outputs folder · {count} files · {size} · {pending} pending"
          : "Outputs folder · {count} files · {size} · up to date",
      { count: outputs.length, size: formatBytes(outputs.reduce((sum, file) => sum + file.bytes, 0)), pending });
      folder.append(checkbox, description);
      elements.backupFiles.append(folder);
    }
    for (const file of data.files) {
      if (file.name.startsWith("outputs/")) continue;
      const label = document.createElement("label");
      label.className = "backup-file";
      const checkbox = document.createElement("input");
      checkbox.type = "checkbox";
      checkbox.className = "backup-choice";
      checkbox.value = file.name;
      checkbox.checked = !file.backed_up;
      const description = document.createElement("span");
      uiText(description, file.backed_up ? "{name} · {size} · same size remotely" : "{name} · {size} · needs upload",
        { name: file.name, size: formatBytes(file.bytes) });
      label.append(checkbox, description);
      if (file.targets?.length) {
        const target = document.createElement("select");
        target.className = "backup-target";
        uiAttr(target, "aria-label", "Upload destination for {name}", { name: file.name });
        for (const path of file.targets) {
          const option = document.createElement("option"); option.value = path; option.textContent = path;
          target.append(option);
        }
        label.append(target);
      } else if (file.name.startsWith("models/image/")) {
        const hint = document.createElement("span");
        uiText(hint, "No writable target: set a category upload path above.");
        label.append(hint);
        checkbox.checked = false;
        checkbox.disabled = true;
      }
      elements.backupFiles.append(label);
    }
    const active = (await api("/api/backup/jobs")).job;
    if (active) {
      renderBackupJob(active);
      if (["queued", "running"].includes(active.status) && state.backupPollJobId !== active.job_id) {
        void pollBackupJob(active.job_id);
      }
    }
  } catch (error) {
    i18n.unbind(elements.backupSummary);
    elements.backupSummary.textContent = error.message;
    elements.startBackupButton.disabled = true;
  }
}

function renderBackupJob(job) {
  state.backupJob = job;
  const progress = job.progress || {};
  elements.backupProgress.classList.remove("hidden");
  elements.backupProgressBar.value = Number(progress.percent) || 0;
  uiText(elements.backupJobStatus, "{status}: {current}",
    { status: t(job.status), current: job.current ? t(job.current) : t("preparing") });
  uiText(elements.backupProgressDetail, "{done}/{total} files · {copied} / {size}",
    { done: progress.completed || 0, total: progress.total || 0,
      copied: formatBytes(progress.bytes_completed || 0), size: formatBytes(progress.bytes_total || 0) });
  if (job.status === "failed") uiText(elements.backupJobStatus, job.error || "Upload failed");
}

async function pollBackupJob(jobId) {
  state.backupPollJobId = jobId;
  try {
    while (true) {
      const job = (await api(`/api/backup/jobs?job_id=${encodeURIComponent(jobId)}`)).job;
      if (!job) throw new Error(t("Backup job disappeared"));
      renderBackupJob(job);
      if (["completed", "failed"].includes(job.status)) {
        if (job.status === "completed") await loadBackup();
        else showNotice(job.error || t("Backup upload failed"));
        return;
      }
      await new Promise((resolve) => setTimeout(resolve, 1500));
    }
  } catch (error) {
    showNotice(error.message);
  } finally {
    state.backupPollJobId = null;
    elements.startBackupButton.disabled = false;
  }
}

async function startBackup() {
  const names = $$(".backup-choice:checked").map((input) => input.value);
  const targets = Object.fromEntries($$(".backup-choice:checked").map((input) =>
    [input.value, input.closest("label")?.querySelector(".backup-target")?.value || ""]));
  const memory = elements.backupMemory.checked;
  const outputs = Boolean($("#backupOutputs")?.checked);
  if (!names.length && !memory && !outputs) return showNotice(t("Select a file, outputs folder, or Memory snapshot first."));
  elements.startBackupButton.disabled = true;
  try {
    const data = await api("/api/backup/upload", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ names, memory, outputs, targets }),
    });
    elements.backupMemory.checked = false;
    await pollBackupJob(data.job.job_id);
  } catch (error) {
    showNotice(error.message);
    elements.startBackupButton.disabled = false;
  }
}

async function loadRestorePoints() {
  try {
    const { points } = await api("/api/backup/restore-points");
    elements.restorePointSelect.replaceChildren();
    for (const point of points) {
      const option = document.createElement("option"); option.value = point.id;
      uiText(option, "{date} · {count} characters · {size}",
        { date: point.created_at || point.id, count: point.subjects, size: formatBytes(point.bytes) });
      elements.restorePointSelect.append(option);
    }
    elements.startRestoreButton.disabled = !points.length;
  } catch (error) {
    elements.startRestoreButton.disabled = true;
    if (state.remoteStorage?.enabled) showNotice(error.message);
  }
}

async function startRestore() {
  const id = elements.restorePointSelect.value;
  if (!id || !window.confirm(t("Replace local character JSON and SQLite with this backup? Current data will be kept in Data/Recovery. Restart EverSpark after restore."))) return;
  elements.startRestoreButton.disabled = true;
  try {
    const data = await api("/api/backup/restore", { method: "POST",
      headers: { "Content-Type": "application/json" }, body: JSON.stringify({ id }) });
    await pollBackupJob(data.job.job_id);
  } catch (error) { showNotice(error.message); }
  finally { elements.startRestoreButton.disabled = false; }
}

function renderStorageJob(job) {
  state.storageJob = job;
  const progress = job.progress || {};
  const percent = Math.max(0, Math.min(100, Number(progress.percent) || 0));
  const completedBytes = Number(progress.bytes_completed) || 0;
  const totalBytes = Number(progress.bytes_total) || 0;
  const speed = Number(progress.speed_bytes_per_second) || 0;
  const eta = Number(progress.eta_seconds) || 0;
  elements.storageProgress.classList.remove("hidden");
  elements.storageProgressBar.value = percent;
  uiText(elements.storageJobStatus, "{name}: {status} · {percent}%",
    { name: job.name, status: t(job.status), percent: percent.toFixed(1) });
  const parts = [];
  if (totalBytes) parts.push(`${formatBytes(completedBytes)} / ${formatBytes(totalBytes)}`);
  if (speed && ["queued", "running"].includes(job.status)) parts.push(`${formatBytes(speed)}/s`);
  if (eta && ["queued", "running"].includes(job.status)) parts.push(t("ETA {time}", { time: formatDuration(eta) }));
  if (progress.total) parts.push(t("{count} files", { count: `${progress.completed || 0}/${progress.total}` }));
  elements.storageProgressDetail.textContent = parts.join(" · ");
}

async function pollStorageJob(jobId) {
  state.storagePollJobId = jobId;
  try {
    while (true) {
      const data = await api(`/api/storage/jobs?job_id=${encodeURIComponent(jobId)}`);
      const job = data.job;
      if (!job) throw new Error(t("Remote download job disappeared"));
      renderStorageJob(job);
      if (job.status === "completed") {
        state.storagePollJobId = null;
        await Promise.all([loadRemoteStorage(), loadResources()]);
        return;
      }
      if (job.status === "failed") throw new Error(job.error || t("Remote download failed"));
      await new Promise((resolve) => setTimeout(resolve, 1000));
    }
  } finally {
    if (state.storagePollJobId === jobId) state.storagePollJobId = null;
  }
}

async function pullRemoteResource(button) {
  const kind = button.dataset.kind;
  const name = storageSelect(kind)?.value;
  if (!name) return;
  $$(".storage-pull-button").forEach((item) => { item.disabled = true; });
  renderStorageJob({
    name,
    status: "queued",
    progress: { percent: 0, bytes_completed: 0, bytes_total: 0 },
  });
  try {
    const data = await api("/api/storage/pull", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ kind, name }),
    });
    await pollStorageJob(data.job.job_id);
  } catch (error) {
    i18n.unbind(elements.storageJobStatus);
    elements.storageJobStatus.textContent = error.message;
    showNotice(error.message);
    updateStorageButtons();
  }
}

function setDirectDownloadControls(running) {
  $$(".direct-download-start").forEach((button) => { button.disabled = running; });
  elements.cancelDirectDownload.disabled = !running;
}

function renderDirectDownloadJob(job) {
  state.directDownloadJob = job;
  const progress = job.progress || {};
  const percent = Math.max(0, Math.min(100, Number(progress.percent) || 0));
  const completed = Number(progress.bytes_completed) || 0;
  const total = Number(progress.bytes_total) || 0;
  const speed = Number(progress.speed_bytes_per_second) || 0;
  const eta = Number(progress.eta_seconds) || 0;
  const running = ["queued", "downloading"].includes(job.status);
  const active = ["queued", "downloading", "registering"].includes(job.status);
  elements.directDownloadProgress.classList.remove("hidden");
  if (total) {
    elements.directDownloadProgressBar.value = percent;
  } else {
    elements.directDownloadProgressBar.removeAttribute("value");
  }
  uiText(elements.directDownloadStatus, "{name}: {status}{progress}",
    { name: job.name, status: t(job.status), progress: total ? ` · ${percent.toFixed(1)}%` : "" });
  const parts = [];
  if (total) parts.push(`${formatBytes(completed)} / ${formatBytes(total)}`);
  else if (completed) parts.push(formatBytes(completed));
  if (speed && running) parts.push(`${formatBytes(speed)}/s`);
  if (eta && running) parts.push(t("ETA {time}", { time: formatDuration(eta) }));
  if (job.status === "registering") parts.push(t("Registering {name} with Ollama", { name: job.runtime_name || t("Model") }));
  if (job.error) parts.push(job.error);
  elements.directDownloadDetail.textContent = parts.join(" · ");
  elements.cancelDirectDownload.classList.toggle("hidden", !running);
  elements.retryDirectDownload.classList.toggle("hidden", !["failed", "cancelled"].includes(job.status));
  setDirectDownloadControls(active);
}

async function pollDirectDownload(jobId) {
  state.directDownloadPollJobId = jobId;
  try {
    while (true) {
      const data = await api(`/api/downloads/jobs?job_id=${encodeURIComponent(jobId)}`);
      const job = data.job;
      if (!job) throw new Error(t("Direct download job disappeared"));
      renderDirectDownloadJob(job);
      if (job.status === "completed") {
        state.directDownloadPollJobId = null;
        await loadResources();
        return;
      }
      if (["failed", "cancelled"].includes(job.status)) return;
      await new Promise((resolve) => setTimeout(resolve, 800));
    }
  } finally {
    if (state.directDownloadPollJobId === jobId) state.directDownloadPollJobId = null;
  }
}

async function startDirectDownload(kind, url, filename = "", runtimeName = "") {
  hideNotice();
  setDirectDownloadControls(true);
  try {
    const data = await api("/api/downloads", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ kind, url, filename, runtime_name: runtimeName }),
    });
    renderDirectDownloadJob(data.job);
    await pollDirectDownload(data.job.job_id);
  } catch (error) {
    setDirectDownloadControls(false);
    showNotice(error.message);
  }
}

async function loadDirectDownload() {
  try {
    const data = await api("/api/downloads/jobs");
    if (!data.job) return;
    renderDirectDownloadJob(data.job);
    if (["queued", "downloading", "registering"].includes(data.job.status)
        && state.directDownloadPollJobId !== data.job.job_id) {
      await pollDirectDownload(data.job.job_id);
    }
  } catch (error) {
    showNotice(error.message);
  }
}

async function cancelDirectDownload() {
  const job = state.directDownloadJob;
  if (!job) return;
  try {
    await api("/api/downloads/cancel", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ job_id: job.job_id }),
    });
  } catch (error) {
    showNotice(error.message);
  }
}

async function retryDirectDownload() {
  const job = state.directDownloadJob;
  if (!job) return;
  try {
    const data = await api("/api/downloads/retry", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ job_id: job.job_id }),
    });
    renderDirectDownloadJob(data.job);
    await pollDirectDownload(data.job.job_id);
  } catch (error) {
    showNotice(error.message);
  }
}

function resetModelServiceForm() {
  elements.modelServiceForm.reset();
  elements.modelServiceId.value = "";
  uiText($("#modelServiceFormTitle"), "Add model service");
  $("#cancelModelServiceEdit").classList.add("hidden");
}

function useDeepSeekPreset() {
  resetModelServiceForm();
  elements.modelServiceName.value = "DeepSeek";
  elements.modelServiceUrl.value = "https://api.deepseek.com/v1";
  elements.modelServiceModel.value = "deepseek-flash";
  elements.modelServiceKey.focus();
}

function modelServicePayload() {
  return {
    id: elements.modelServiceId.value,
    name: elements.modelServiceName.value.trim(),
    base_url: elements.modelServiceUrl.value.trim(),
    model: elements.modelServiceModel.value.trim(),
    api_key: elements.modelServiceKey.value,
    json_mode: elements.modelServiceJsonMode.checked,
    stream: elements.modelServiceStream.checked,
  };
}

async function modelServiceRequest(path, payload) {
  return api(`/api/concept/connections/${path}`, {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

function renderModelConnections() {
  elements.modelServiceList.replaceChildren();
  for (const connection of state.modelConnections) {
    const card = document.createElement("article");
    card.className = "model-service-card";
    const heading = document.createElement("h3");
    heading.textContent = connection.name;
    const model = document.createElement("p");
    model.textContent = `${connection.type === "ollama" ? "Ollama" : "OpenAI Compatible"} · ${connection.model}`;
    const detail = document.createElement("p");
    uiText(detail, connection.id === state.defaultModelService ? "Default model service" :
      (connection.builtin ? "Built-in connection" : "API Key saved on server"));
    card.append(heading, model, detail);
    if (connection.base_url) {
      const url = document.createElement("p");
      url.textContent = connection.base_url;
      card.appendChild(url);
    }
    const actions = document.createElement("div");
    actions.className = "model-service-card-actions";
    if (connection.id !== state.defaultModelService) {
      const setDefault = document.createElement("button");
      setDefault.type = "button";
      setDefault.className = "secondary-button";
      uiText(setDefault, "Set as default");
      setDefault.addEventListener("click", async () => {
        try {
          await modelServiceRequest("default", { id: connection.id });
          await Promise.all([loadModelConnections(), loadResources()]);
          elements.conceptProviderSelect.value = connection.id;
          updateConceptModels();
        } catch (error) { showNotice(error.message); }
      });
      actions.appendChild(setDefault);
    }
    if (!connection.builtin) {
      const edit = document.createElement("button");
      edit.type = "button";
      edit.className = "secondary-button";
      uiText(edit, "Edit connection");
      edit.addEventListener("click", () => {
        elements.modelServiceId.value = connection.id;
        elements.modelServiceName.value = connection.name;
        elements.modelServiceUrl.value = connection.base_url;
        elements.modelServiceModel.value = connection.model;
        elements.modelServiceKey.value = "";
        elements.modelServiceJsonMode.checked = connection.json_mode;
        elements.modelServiceStream.checked = connection.stream === true;
        uiText($("#modelServiceFormTitle"), "Edit model service");
        $("#cancelModelServiceEdit").classList.remove("hidden");
        elements.modelServiceName.focus();
      });
      const remove = document.createElement("button");
      remove.type = "button";
      remove.className = "ghost-button";
      uiText(remove, "Remove connection");
      remove.addEventListener("click", async () => {
        if (!window.confirm(t("Remove this model connection?"))) return;
        try {
          await modelServiceRequest("remove", { id: connection.id });
          if (elements.modelServiceId.value === connection.id) resetModelServiceForm();
          await Promise.all([loadModelConnections(), loadResources()]);
        } catch (error) { showNotice(error.message); }
      });
      actions.append(edit, remove);
    }
    card.appendChild(actions);
    elements.modelServiceList.appendChild(card);
  }
}

async function loadModelConnections() {
  try {
    const data = await api("/api/concept/connections");
    state.modelConnections = data.connections || [];
    state.defaultModelService = data.default;
    renderModelConnections();
  } catch (error) { showNotice(error.message); }
}

async function saveModelService(event) {
  event.preventDefault();
  hideNotice();
  const button = $("#saveModelService");
  button.disabled = true;
  try {
    await modelServiceRequest("save", modelServicePayload());
    resetModelServiceForm();
    await Promise.all([loadModelConnections(), loadResources()]);
    showNotice(t("Model connection saved."), "success");
  } catch (error) { showNotice(error.message); }
  finally { button.disabled = false; }
}

async function testModelService() {
  hideNotice();
  const button = $("#testModelService");
  button.disabled = true;
  try {
    const started = await modelServiceRequest("test", modelServicePayload());
    if (!started.job?.id) throw new Error(t("Model connection test did not start."));
    showNotice(t("Testing model connection..."), "success");
    const deadline = Date.now() + 150000;
    let failures = 0;
    while (Date.now() < deadline) {
      await new Promise((resolve) => setTimeout(resolve, 1500));
      let job;
      try {
        const response = await api(`/api/concept/connections/test/jobs?job_id=${encodeURIComponent(started.job.id)}`);
        job = response.job;
        failures = 0;
      } catch (error) {
        if (transientApiError(error) && ++failures < 4) continue;
        throw error;
      }
      if (job?.status === "completed") {
        showNotice(t("Model connection works."), "success");
        return;
      }
      if (job?.status === "failed") throw new Error(job.error || t("Model connection test failed."));
      if (job?.status !== "running") throw new Error(t("Invalid model connection test status."));
    }
    throw new Error(t("Model connection test timed out."));
  } catch (error) { showNotice(error.message); }
  finally { button.disabled = false; }
}

function setView(name) {
  $$(".nav-item").forEach((button) => button.classList.toggle("active", button.dataset.view === name));
  $$("[data-view-panel]").forEach((panel) => panel.classList.toggle("active", panel.dataset.viewPanel === name));
  uiText($("#viewEyebrow"), viewCopy[name][0]);
  uiText($("#viewTitle"), viewCopy[name][1]);
  if (name === "history") loadHistory();
  if (name === "runtime") loadRuntime();
  if (name === "models") loadModelConnections();
  if (name === "storage") Promise.all([loadRemoteStorage(), loadDirectDownload(), loadBackup(), loadRestorePoints()]);
}

function traitValues(document) {
  if (!document) return [];
  const appearance = document.appearance || {};
  const body = appearance.body || {};
  const face = appearance.face || {};
  const hair = appearance.hair || {};
  const wardrobe = document.wardrobe || {};
  return [
    hair.color && `${hair.color} hair`,
    hair.length,
    face.eye_color && `${face.eye_color} eyes`,
    body.build,
    wardrobe.default_outfit,
    ...(appearance.distinguishing_features || []),
  ].filter(Boolean).slice(0, 7);
}

function updateSubjectPickerButton() {
  elements.useSubjectButton.disabled = state.selectingSubject || !elements.subjectPicker.value
    || elements.subjectPicker.value === state.selectedSubject?.subject_id;
}

function renderSubjectPicker() {
  const previous = elements.subjectPicker.value;
  elements.subjectPicker.replaceChildren();
  const placeholder = document.createElement("option");
  placeholder.value = "";
  uiText(placeholder, "Choose a character");
  elements.subjectPicker.appendChild(placeholder);
  for (const item of state.subjects) {
    const option = document.createElement("option");
    option.value = item.subject_id;
    option.textContent = `${item.display_name || item.subject_id} · ${item.subject_id}`;
    elements.subjectPicker.appendChild(option);
  }
  const current = state.selectedSubject?.subject_id;
  elements.subjectPicker.value = [current, previous].find((id) =>
    [...elements.subjectPicker.options].some((option) => option.value === id)) || "";
  elements.subjectPicker.disabled = !state.subjects.length || state.selectingSubject;
  updateSubjectPickerButton();
}

async function selectExistingSubject(subjectId, openForge = false) {
  if (!subjectId || state.selectingSubject) return;
  state.selectingSubject = true;
  const generationWasDisabled = elements.generateButton.disabled;
  elements.generateButton.disabled = true;
  renderSubjectPicker();
  const sessionId = state.sessionId;
  try {
    const data = await api("/api/subjects/select", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ session_id: sessionId, subject_id: subjectId }),
    });
    if (state.sessionId === sessionId) {
      state.selectedSubject = data.document;
      renderSelectedSubject();
      if (openForge) setView("forge");
      hideNotice();
    }
  } catch (error) {
    showNotice(error.message);
  } finally {
    state.selectingSubject = false;
    if (!generationWasDisabled) elements.generateButton.disabled = false;
    renderSubjectPicker();
  }
}

function renderSelectedSubject() {
  const subject = state.selectedSubject;
  const hasSubject = Boolean(subject);
  elements.selectedEmpty.classList.toggle("hidden", hasSubject);
  elements.selectedCard.classList.toggle("hidden", !hasSubject);
  renderSubjectPicker();

  elements.composerContext.replaceChildren();
  const miniAvatar = document.createElement("span");
  miniAvatar.className = "mini-avatar";
  const contextText = document.createElement("span");

  if (!hasSubject) {
    miniAvatar.textContent = "—";
    uiText(contextText, "No persistent subject");
    elements.composerContext.append(miniAvatar, contextText);
    return;
  }

  const displayName = subject.identity?.display_name || subject.subject_id;
  elements.selectedName.textContent = displayName;
  elements.selectedId.textContent = subject.subject_id;
  elements.selectedRevision.textContent = `R${subject.revision}`;
  elements.subjectAvatar.textContent = initials(displayName);
  elements.selectedTraits.replaceChildren();
  const traits = traitValues(subject);
  if (!traits.length) {
    const trait = document.createElement("span");
    trait.className = "trait";
    uiText(trait, "Identity ready");
    elements.selectedTraits.appendChild(trait);
  } else {
    for (const value of traits) {
      const trait = document.createElement("span");
      trait.className = "trait";
      trait.textContent = value;
      elements.selectedTraits.appendChild(trait);
    }
  }
  miniAvatar.textContent = initials(displayName);
  uiText(contextText, "{name} · revision {revision}", { name: displayName, revision: subject.revision });
  elements.composerContext.append(miniAvatar, contextText);
}

function renderSubjectGrid() {
  elements.subjectGrid.replaceChildren();
  if (!state.subjects.length) {
    const empty = document.createElement("div");
    empty.className = "empty-collection";
    uiText(empty, "No subjects yet. Start a conversation and EverSpark will extract one automatically.");
    elements.subjectGrid.appendChild(empty);
    return;
  }

  for (const item of state.subjects) {
    const card = document.createElement("article");
    card.className = "subject-card";
    const top = document.createElement("div");
    top.className = "subject-card-top";
    const avatar = document.createElement("div");
    avatar.className = "subject-card-avatar";
    avatar.textContent = initials(item.display_name || item.subject_id);
    const identity = document.createElement("div");
    identity.style.minWidth = "0";
    const title = document.createElement("h3");
    title.textContent = item.display_name || item.subject_id;
    const id = document.createElement("p");
    id.className = "subject-card-id";
    id.textContent = item.subject_id;
    identity.append(title, id);
    top.append(avatar, identity);

    const meta = document.createElement("div");
    meta.className = "subject-card-meta";
    const revision = document.createElement("span");
    uiText(revision, "REVISION {number}", { number: item.revision });
    const updated = document.createElement("span");
    uiDate(updated, item.updated_at);
    meta.append(revision, updated);

    card.append(top, meta);
    const inspect = document.createElement("button");
    inspect.className = "text-button";
    inspect.type = "button";
    uiText(inspect, "View four JSON documents →");
    const groups = document.createElement("div");
    groups.className = "subject-documents hidden";
    inspect.addEventListener("click", async () => {
      if (!groups.classList.contains("hidden")) {
        groups.classList.add("hidden");
        uiText(inspect, "View four JSON documents →");
        return;
      }
      inspect.disabled = true;
      try {
        const query = new URLSearchParams({ subject_id: item.subject_id });
        const { bundle } = await api(`/api/subjects/bundle?${query}`);
        renderSubjectDocuments(groups, bundle);
        groups.classList.remove("hidden");
        uiText(inspect, "Hide documents ↑");
      } catch (error) {
        showNotice(error.message);
      } finally {
        inspect.disabled = false;
      }
    });
    const actions = document.createElement("div");
    actions.className = "subject-card-actions";
    const use = document.createElement("button");
    use.type = "button";
    use.className = "text-button";
    uiText(use, "Use in Forge");
    use.addEventListener("click", () => { void selectExistingSubject(item.subject_id, true); });
    actions.append(inspect, use);
    card.append(actions, groups);
    elements.subjectGrid.appendChild(card);
  }
}

function renderSubjectDocuments(container, bundle) {
  container.replaceChildren();
  for (const [group, label] of [
    ["subject", "Subject JSON"],
    ["metadata", "Metadata JSON"],
    ["positive_prompt", "Positive prompt JSON"],
    ["negative_prompt", "Negative prompt JSON"],
  ]) {
    const section = document.createElement("section");
    section.className = "subject-document";
    const heading = document.createElement("h4");
    uiText(heading, label);
    const pre = document.createElement("pre");
    pre.textContent = JSON.stringify(bundle[group], null, 2);
    const form = document.createElement("form");
    form.className = "subject-document-form";
    const input = document.createElement("textarea");
    input.required = true;
    input.rows = 2;
    uiAttr(input, "placeholder", "Tell Concept Forge what to change in {group}", { group: { i18nKey: label } });
    uiAttr(input, "aria-label", "Describe changes to {group}", { group: { i18nKey: label } });
    const submit = document.createElement("button");
    submit.className = "secondary-button";
    submit.type = "submit";
    uiText(submit, "Ask model to update");
    form.append(input, submit);
    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      const instruction = input.value.trim();
      if (!instruction) return;
      submit.disabled = true;
      try {
        const data = await api("/api/subjects/revise", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ subject_id: bundle.subject_id, group, instruction }),
        });
        renderSubjectDocuments(container, data.bundle);
        const revision = container.closest(".subject-card")?.querySelector(".subject-card-meta span");
        if (revision) uiText(revision, "REVISION {number}", { number: data.bundle.subject.revision });
        if (state.selectedSubject?.subject_id === bundle.subject_id) await loadCurrentSubject();
        hideNotice();
      } catch (error) {
        showNotice(error.message);
        submit.disabled = false;
      }
    });
    section.append(heading, pre, form);
    container.appendChild(section);
  }
}

async function loadSubjects() {
  try {
    const data = await api("/api/subjects");
    state.subjects = data.subjects || [];
    elements.subjectCount.textContent = String(state.subjects.length);
    renderSubjectGrid();
    renderSubjectPicker();
  } catch (error) {
    state.subjects = [];
    elements.subjectCount.textContent = "0";
    renderSubjectGrid();
    renderSubjectPicker();
    showNotice(error.message);
  }
}

async function loadCurrentSubject() {
  try {
    const query = new URLSearchParams({ session_id: state.sessionId });
    const data = await api(`/api/subjects/current?${query}`);
    state.selectedSubject = data.document || null;
    renderSelectedSubject();
  } catch (error) {
    showNotice(error.message);
  }
}

async function showRevisions() {
  if (!state.selectedSubject) return;
  elements.revisionList.replaceChildren();
  const loading = document.createElement("p");
  loading.className = "section-copy";
  uiText(loading, "Loading revision history...");
  elements.revisionList.appendChild(loading);
  elements.revisionModal.showModal();
  try {
    const query = new URLSearchParams({ subject_id: state.selectedSubject.subject_id });
    const data = await api(`/api/subjects/revisions?${query}`);
    elements.revisionList.replaceChildren();
    for (const item of data.revisions || []) {
      const row = document.createElement("article");
      row.className = "revision-item";
      const head = document.createElement("div");
      head.className = "revision-item-head";
      const title = document.createElement("strong");
      uiText(title, "Revision {number}", { number: item.revision });
      const time = document.createElement("time");
      uiDate(time, item.created_at);
      const pre = document.createElement("pre");
      pre.textContent = JSON.stringify(item.document, null, 2);
      head.append(title, time);
      row.append(head, pre);
      elements.revisionList.appendChild(row);
    }
  } catch (error) {
    elements.revisionList.replaceChildren();
    const message = document.createElement("p");
    message.className = "section-copy";
    message.textContent = error.message;
    elements.revisionList.appendChild(message);
  }
}

function appendConversation(role, content, generated = null) {
  const message = document.createElement("article");
  message.className = `conversation-message ${role}`;
  const label = document.createElement("strong");
  uiText(label, role === "user" ? "You" : "Concept Forge");
  const body = document.createElement("p");
  if (generated) uiText(body, generated.key, generated.args);
  else body.textContent = content;
  message.append(label, body);
  elements.conversationFeed.appendChild(message);
  elements.conversationFeed.scrollTop = elements.conversationFeed.scrollHeight;
}

async function loadConversation() {
  elements.conversationFeed.replaceChildren();
  try {
    const query = new URLSearchParams({ session_id: state.sessionId });
    const data = await api(`/api/conversation/history?${query}`);
    for (const message of data.messages || []) {
      let content = message.content;
      let generated = null;
      if (message.role === "assistant") {
        try {
          const parsed = JSON.parse(content);
          if (parsed.status === "over") generated = { key: "Queued {count} image request.", args: { count: parsed.count || 1 } };
        } catch (_error) {
          // Visible discussion replies are stored as plain text.
        }
      }
      appendConversation(message.role, content, generated);
    }
  } catch (error) {
    showNotice(error.message);
  }
}

function setMode(mode) {
  state.mode = mode;
  const discussing = mode === "discuss";
  elements.discussModeButton.classList.toggle("active", discussing);
  elements.generateModeButton.classList.toggle("active", !discussing);
  uiText(elements.generateButton.firstElementChild, discussing ? "Discuss" : "Forge image");
  uiAttr(elements.scenePrompt, "placeholder", discussing
    ? "Let's design a character with long black hair and amber eyes..."
    : "Place the current character on a rooftop at blue hour...");
}

async function discuss() {
  const message = elements.scenePrompt.value.trim();
  if (!message || elements.generateButton.disabled) {
    if (!message) showNotice(t("Say something about the current character."));
    return;
  }
  hideNotice();
  elements.generateButton.disabled = true;
  appendConversation("user", message);
  elements.scenePrompt.value = "";
  setGenerationState("Thinking", "running");
  try {
    const data = await api("/api/conversation", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        message,
        session_id: state.sessionId,
        selection: generationSelection(),
      }),
    });
    appendConversation("assistant", data.reply);
    state.selectedSubject = data.subject || null;
    renderSelectedSubject();
    await loadSubjects();
    setGenerationState("Ready", "success");
  } catch (error) {
    setGenerationState("Failed", "error");
    showNotice(error.message);
  } finally {
    elements.generateButton.disabled = false;
  }
}

async function newConversation() {
  state.sessionId = crypto.randomUUID();
  localStorage.setItem("everspark.session", state.sessionId);
  state.selectedSubject = null;
  elements.subjectPicker.value = "";
  elements.conversationFeed.replaceChildren();
  elements.scenePrompt.value = "";
  renderSelectedSubject();
  setMode("discuss");
  setGenerationState("Ready", "idle");
}

function setGenerationState(label, mode = "idle", args = {}) {
  elements.generationState.dataset.state = mode;
  uiText(elements.generationState.lastChild, label, args);
}

function renderWaiting(items) {
  elements.resultStage.replaceChildren();
  const grid = document.createElement("div");
  grid.className = "result-grid";
  for (const item of items) {
    const card = document.createElement("div");
    card.className = "waiting-card";
    const core = document.createElement("div");
    core.className = "waiting-core";
    const spinner = document.createElement("span");
    spinner.className = "spinner";
    const label = document.createElement("span");
    uiText(label, "Frame {number} · queued", { number: item.index });
    core.append(spinner, label);
    card.appendChild(core);
    grid.appendChild(card);
  }
  elements.resultStage.appendChild(grid);
}

function imageButton(image, className) {
  const button = document.createElement("button");
  button.type = "button";
  button.className = className;
  const img = document.createElement("img");
  img.src = image.url;
  if (image.filename) img.alt = image.filename;
  else uiAttr(img, "alt", "Generated image");
  img.loading = "lazy";
  button.appendChild(img);
  button.addEventListener("click", () => {
    elements.viewerImage.src = image.url;
    if (image.filename) elements.viewerImage.alt = image.filename;
    else uiAttr(elements.viewerImage, "alt", "Generated image");
    elements.imageViewer.showModal();
  });
  return button;
}

function renderResults(results) {
  elements.resultStage.replaceChildren();
  const grid = document.createElement("div");
  grid.className = "result-grid";
  for (const item of results) {
    if (item.images?.length) {
      for (const image of item.images) grid.appendChild(imageButton(image, "result-card"));
    } else {
      const card = document.createElement("div");
      card.className = "waiting-card";
      const core = document.createElement("div");
      core.className = "waiting-core";
      if (item.status !== "failed") {
        const spinner = document.createElement("span");
        spinner.className = "spinner";
        core.appendChild(spinner);
      }
      const label = document.createElement("span");
      uiText(label, item.status === "failed" ? "Generation failed" : "Image Forge is working");
      if (item.status === "running" && Number.isFinite(Number(item.progress))) {
        label.textContent += ` · ${Math.round(Number(item.progress))}%`;
      }
      if (item.status === "failed" && item.error) label.title = item.error;
      core.appendChild(label);
      card.appendChild(core);
      grid.appendChild(card);
    }
  }
  elements.resultStage.appendChild(grid);
}

async function pollResults(items) {
  const query = new URLSearchParams();
  items.forEach((item) => query.append("prompt_id", item.prompt_id));
  try {
    const data = await api(`/api/results?${query}`);
    renderResults(data.results);
    const failed = data.results.some((item) => item.status === "failed");
    const finished = data.results.every((item) => ["completed", "failed"].includes(item.status));
    state.pollFailures = 0;
    if (!finished) {
      scheduleResultPoll(items);
      return;
    }
    clearTimeout(state.pollTimer);
    state.pollTimer = null;
    elements.generateButton.disabled = false;
    setGenerationState(failed ? "Failed" : "Complete", failed ? "error" : "success");
    if (failed) showNotice(data.results.find((item) => item.status === "failed")?.error ||
      t("Image Forge returned a failed task. Check the runtime logs."));
  } catch (error) {
    if (transientApiError(error) && ++state.pollFailures <= 24) {
      setGenerationState("Waiting for image service", "running");
      scheduleResultPoll(items, 5000);
      return;
    }
    clearTimeout(state.pollTimer);
    state.pollTimer = null;
    elements.generateButton.disabled = false;
    setGenerationState("Unavailable", "error");
    showNotice(error.message);
  }
}

function scheduleResultPoll(items, delay = 1800) {
  if (state.pollTimer) clearTimeout(state.pollTimer);
  state.pollTimer = setTimeout(() => {
    state.pollTimer = null;
    void pollResults(items);
  }, delay);
}

async function waitForGeneration(jobId) {
  let failedChecks = 0;
  while (true) {
    await new Promise((resolve) => setTimeout(resolve, 1800));
    let data;
    try {
      data = await api(`/api/generate/jobs?job_id=${encodeURIComponent(jobId)}`);
      failedChecks = 0;
    } catch (error) {
      if (++failedChecks < (transientApiError(error) ? 36 : 3)) {
        setGenerationState("Waiting for image service", "running");
        continue;
      }
      throw error;
    }
    if (data.job.status === "completed") return data.job.response;
    if (data.job.status === "failed") throw new Error(data.job.error || t("Generation failed"));
  }
}

async function generate() {
  if (state.mode === "discuss") {
    await discuss();
    return;
  }
  const message = elements.scenePrompt.value.trim();
  if (!message || elements.generateButton.disabled) {
    if (!message) showNotice(t("Describe the scene before generating."));
    return;
  }
  if (state.pollTimer) clearTimeout(state.pollTimer);
  state.pollFailures = 0;
  hideNotice();
  appendConversation("user", message);
  elements.scenePrompt.value = "";
  elements.generateButton.disabled = true;
  setGenerationState("Planning", "running");
  elements.resultStage.replaceChildren();
  const pending = document.createElement("div");
  pending.className = "stage-empty";
  const spinner = document.createElement("span");
  spinner.className = "spinner";
  const title = document.createElement("h3");
  uiText(title, "Concept Forge is shaping the request");
  const detail = document.createElement("p");
  uiText(detail, state.selectedSubject ? "Stable identity is being merged with this scene." : "This task uses scene direction only.");
  pending.append(spinner, title, detail);
  elements.resultStage.appendChild(pending);
  try {
    const requestId = crypto.randomUUID().replaceAll("-", "");
    const request = {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        message,
        session_id: state.sessionId,
        selection: generationSelection(),
        request_id: requestId,
      }),
    };
    let accepted;
    try {
      accepted = await api("/api/generate/start", request);
    } catch (error) {
      // The proxy may lose the acceptance response after the server starts the task.
      if (!transientApiError(error)) throw error;
      accepted = { job: { id: requestId } };
    }
    const data = await waitForGeneration(accepted.job.id);
    await Promise.all([loadCurrentSubject(), loadSubjects()]);
    const items = data.result?.items || [];
    if (!items.length) throw new Error(t("Orchestrator did not return any queued frames."));
    renderWaiting(items);
    setGenerationState("{count} queued", "running", { count: items.length });
    await pollResults(items);
  } catch (error) {
    elements.generateButton.disabled = false;
    setGenerationState("Failed", "error");
    showNotice(error.message);
  }
}

async function loadHistory() {
  elements.galleryGrid.replaceChildren();
  const loading = document.createElement("div");
  loading.className = "empty-collection";
  uiText(loading, "Loading Image Forge history...");
  elements.galleryGrid.appendChild(loading);
  try {
    const data = await api("/api/history?limit=36");
    elements.galleryGrid.replaceChildren();
    if (!data.images?.length) {
      const empty = document.createElement("div");
      empty.className = "empty-collection";
      uiText(empty, "No generated images are available yet.");
      elements.galleryGrid.appendChild(empty);
      return;
    }
    for (const image of data.images) elements.galleryGrid.appendChild(imageButton(image, "gallery-card"));
  } catch (error) {
    elements.galleryGrid.replaceChildren();
    const empty = document.createElement("div");
    empty.className = "empty-collection";
    empty.textContent = error.message;
    elements.galleryGrid.appendChild(empty);
  }
}

function downloadOutputsArchive() {
  hideNotice();
  elements.downloadOutputsButton.disabled = true;
  uiText(elements.downloadOutputsButton, "Preparing ZIP…");
  const link = document.createElement("a");
  link.href = `/api/outputs/archive?requested_at=${Date.now()}`;
  link.download = "EverSpark-Outputs.zip";
  document.body.appendChild(link);
  link.click();
  link.remove();
  window.setTimeout(() => {
    elements.downloadOutputsButton.disabled = false;
    uiText(elements.downloadOutputsButton, "Download outputs ZIP");
  }, 1500);
}

async function downloadDataArchive() {
  hideNotice();
  elements.downloadDataButton.disabled = true;
  try {
    const response = await fetch("/api/data/archive", { cache: "no-store" });
    if (!response.ok) {
      let message = t("Could not create data ZIP");
      try { message = (await response.json()).error || message; } catch (_error) { /* keep fallback */ }
      throw new Error(message);
    }
    const blob = await response.blob();
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = "EverSpark-Data.zip";
    document.body.appendChild(link);
    link.click();
    link.remove();
    window.setTimeout(() => URL.revokeObjectURL(url), 60000);
  } catch (error) { showNotice(error.message); }
  finally { elements.downloadDataButton.disabled = false; }
}

async function restoreDataArchive() {
  const file = elements.localDataFile.files?.[0];
  if (!file) { showNotice(t("Choose an EverSpark data ZIP first.")); return; }
  if (file.size < 1 || file.size > 128 * 1024 * 1024) {
    showNotice(t("ZIP upload must be between 1 byte and 128 MiB")); return;
  }
  if (!window.confirm(t("Replace local character JSON and SQLite with this ZIP? Current data will be kept in Data/Recovery. Restart EverSpark after restore."))) return;
  hideNotice();
  elements.restoreDataButton.disabled = true;
  try {
    const result = await api("/api/data/import", {
      method: "POST", headers: { "Content-Type": "application/zip" }, body: file,
    });
    elements.localDataFile.value = "";
    showNotice(t("Restored {count} characters. Previous data is in {path}. Restart EverSpark to load the restored Memory.",
      { count: result.subjects, path: result.recovery }), "success");
  } catch (error) { showNotice(error.message); }
  finally { elements.restoreDataButton.disabled = false; }
}

function runtimeCard(title, online, copy, args = {}) {
  const card = document.createElement("article");
  card.className = "runtime-card";
  const head = document.createElement("div");
  head.className = "runtime-card-head";
  const name = document.createElement("h3");
  uiText(name, title);
  const dot = document.createElement("span");
  dot.className = `runtime-status ${online ? "online" : "offline"}`;
  const detail = document.createElement("p");
  uiText(detail, copy, args);
  head.append(name, dot);
  card.append(head, detail);
  return card;
}

async function loadRuntime() {
  try {
    const data = await api("/api/runtime/status");
    const orchestrator = Boolean(data.services?.orchestrator?.online);
    const imageForge = Boolean(data.services?.image_forge?.online);
    const logging = Boolean(data.logging?.ready);
    elements.runtimeGrid.replaceChildren(
      runtimeCard("Orchestrator", orchestrator, orchestrator ? "Task routing and subject APIs are online." : "Start with ./everspark orchestrator start"),
      runtimeCard("Image Forge", imageForge, imageForge ? "The configured image adapter is responding." : "Start or configure the image execution adapter."),
      runtimeCard("Runtime logs", logging, logging ? "{present}/{configured} managed logs are present." : "The runtime log manifest is unavailable.",
        { present: data.logging?.present, configured: data.logging?.configured }),
    );
    elements.healthDot.className = `pulse-dot ${data.ready ? "online" : "partial"}`;
    uiText(elements.healthTitle, data.ready ? "System ready" : "Setup required");
    uiText(elements.healthDetail, data.ready ? "All local services responding" : "Open Runtime for details");
  } catch (error) {
    elements.healthDot.className = "pulse-dot partial";
    uiText(elements.healthTitle, "Status unavailable");
    uiText(elements.healthDetail, "WebUI could not complete checks");
    if ($("#runtimeView").classList.contains("active")) showNotice(error.message);
  }
}

function bindEvents() {
  elements.subjectPicker.addEventListener("change", updateSubjectPickerButton);
  elements.useSubjectButton.addEventListener("click", () => {
    void selectExistingSubject(elements.subjectPicker.value);
  });
  elements.languageSelect.addEventListener("change", () => {
    i18n.setLanguage(elements.languageSelect.value);
    $$('[data-date]').forEach((node) => { node.textContent = formatDate(node.dataset.date); });
    if (state.storageJob) renderStorageJob(state.storageJob);
    if (state.backupJob) renderBackupJob(state.backupJob);
    if (state.directDownloadJob) renderDirectDownloadJob(state.directDownloadJob);
    const fallback = elements.vaeSelect.querySelector('option[value=""]');
    if (fallback) fallback.textContent = t("Checkpoint VAE");
  });
  $$(".nav-item").forEach((button) => button.addEventListener("click", () => setView(button.dataset.view)));
  $("#newConversationButton").addEventListener("click", newConversation);
  elements.discussModeButton.addEventListener("click", () => setMode("discuss"));
  elements.generateModeButton.addEventListener("click", () => setMode("generate"));
  elements.workflowSelect.addEventListener("change", updateLoraAvailability);
  elements.conceptProviderSelect.addEventListener("change", updateConceptModels);
  elements.modelServiceForm.addEventListener("submit", saveModelService);
  $("#useDeepSeekPreset").addEventListener("click", useDeepSeekPreset);
  $("#testModelService").addEventListener("click", testModelService);
  $("#cancelModelServiceEdit").addEventListener("click", resetModelServiceForm);
  $("#refreshModelServices").addEventListener("click", loadModelConnections);
  elements.imageEngineSelect.addEventListener("change", () => {
    state.selectedLoras = [];
    renderSelectedLoras();
    renderImagePlugin();
    void loadResources();
  });
  elements.imageEngineAction.addEventListener("click", manageImagePlugin);
  elements.imageEngineDefault.addEventListener("click", defaultImagePlugin);
  elements.addLoraButton.addEventListener("click", addSelectedLora);
  $("#viewRevisionsButton").addEventListener("click", showRevisions);
  $("#closeRevisionModal").addEventListener("click", () => elements.revisionModal.close());
  elements.generateButton.addEventListener("click", generate);
  elements.scenePrompt.addEventListener("keydown", (event) => {
    if (event.ctrlKey && event.key === "Enter") generate();
  });
  $("#refreshButton").addEventListener("click", async () => {
    hideNotice();
    await Promise.all([loadSubjects(), loadRuntime(), loadImagePlugins(), loadRemoteStorage()]);
    await loadResources();
  });
  $("#refreshHistoryButton").addEventListener("click", loadHistory);
  elements.downloadOutputsButton.addEventListener("click", downloadOutputsArchive);
  elements.downloadDataButton.addEventListener("click", downloadDataArchive);
  elements.restoreDataButton.addEventListener("click", restoreDataArchive);
  $("#refreshRuntimeButton").addEventListener("click", loadRuntime);
  elements.refreshStorageButton.addEventListener("click", () => { void loadRemoteStorage(true); });
  $("#refreshBackupButton").addEventListener("click", loadBackup);
  elements.startBackupButton.addEventListener("click", startBackup);
  elements.imageDownloadForm.addEventListener("submit", (event) => {
    event.preventDefault();
    void startDirectDownload(
      elements.imageDownloadKind.value,
      elements.imageDownloadUrl.value.trim(),
      elements.imageDownloadFilename.value.trim(),
    );
  });
  elements.loraDownloadForm.addEventListener("submit", (event) => {
    event.preventDefault();
    void startDirectDownload("lora", elements.loraDownloadUrl.value.trim(), elements.loraDownloadFilename.value.trim());
  });
  elements.vaeDownloadForm.addEventListener("submit", (event) => {
    event.preventDefault();
    void startDirectDownload("vae", elements.vaeDownloadUrl.value.trim(), elements.vaeDownloadFilename.value.trim());
  });
  elements.conceptDownloadForm.addEventListener("submit", (event) => {
    event.preventDefault();
    void startDirectDownload(
      "concept_model",
      elements.conceptDownloadUrl.value.trim(),
      elements.conceptDownloadFilename.value.trim(),
      elements.conceptRuntimeName.value.trim(),
    );
  });
  elements.cancelDirectDownload.addEventListener("click", cancelDirectDownload);
  elements.retryDirectDownload.addEventListener("click", retryDirectDownload);
  $$(".storage-pull-button").forEach((button) => button.addEventListener("click", () => pullRemoteResource(button)));
  elements.remotePathsForm.addEventListener("submit", saveRemotePaths);
  elements.refreshRestoreButton.addEventListener("click", loadRestorePoints);
  elements.startRestoreButton.addEventListener("click", startRestore);
  [elements.remoteCheckpointSelect, elements.remoteDiffusionSelect, elements.remoteLoraSelect, elements.remoteVaeSelect, elements.remoteConceptSelect]
    .forEach((select) => select.addEventListener("change", updateStorageButtons));
  $("#dismissNotice").addEventListener("click", hideNotice);
  $("#closeImageViewer").addEventListener("click", () => elements.imageViewer.close());
  elements.imageViewer.addEventListener("click", (event) => {
    if (event.target === elements.imageViewer) elements.imageViewer.close();
  });
}

async function initialize() {
  i18n.bindStatic();
  bindEvents();
  setMode("discuss");
  renderSelectedSubject();
  await Promise.all([loadSubjects(), loadCurrentSubject(), loadConversation(), loadRuntime(), loadImagePlugins(), loadRemoteStorage(), loadDirectDownload(), loadBackup(), loadModelConnections()]);
  await loadResources();
  setInterval(loadRuntime, 20000);
}

initialize();
