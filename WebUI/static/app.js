const i18n = window.EverSparkI18n;
const t = (key, args) => i18n.t(key, args);
const uiText = (node, key, args) => i18n.bind(node, key, args);
const uiAttr = (node, property, key, args) => i18n.bind(node, key, args, property);

const state = {
  subjects: [],
  selectedSubject: null,
  selectingSubject: false,
  mode: "discuss",
  resources: { workflows: [], checkpoints: [], vaes: [], loras: [], llms: [], defaults: {} },
  remoteStorage: null,
  pathsLoaded: false,
  selectedLoras: [],
  sessionId: localStorage.getItem("everspark.session") || crypto.randomUUID(),
  pollTimer: null,
  storagePollJobId: null,
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
  runtimeGrid: $("#runtimeGrid"),
  healthDot: $("#globalHealthDot"),
  healthTitle: $("#globalHealthTitle"),
  healthDetail: $("#globalHealthDetail"),
  revisionModal: $("#revisionModal"),
  revisionList: $("#revisionList"),
  imageViewer: $("#imageViewer"),
  viewerImage: $("#viewerImage"),
  workflowSelect: $("#workflowSelect"),
  checkpointSelect: $("#checkpointSelect"),
  vaeSelect: $("#vaeSelect"),
  llmSelect: $("#llmSelect"),
  loraSelect: $("#loraSelect"),
  addLoraButton: $("#addLoraButton"),
  selectedLoras: $("#selectedLoras"),
  storageSummary: $("#storageSummary"),
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
};

async function api(path, options = {}) {
  const response = await fetch(path, { cache: "no-store", ...options });
  let data;
  try {
    data = await response.json();
  } catch (_error) {
    throw new Error(t("Invalid server response (HTTP {status})", { status: response.status }));
  }
  if (!response.ok || data.ok === false) {
    throw new Error(data.error || t("Request failed (HTTP {status})", { status: response.status }));
  }
  return data;
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
    model.addEventListener("change", () => { item.strength_model = Number(model.value); });
    const clip = document.createElement("input");
    clip.type = "number";
    clip.step = "0.05";
    clip.min = "-10";
    clip.max = "10";
    clip.value = String(item.strength_clip);
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
    workflow: elements.workflowSelect.value,
    checkpoint: elements.checkpointSelect.value,
    vae: elements.vaeSelect.value,
    llm: elements.llmSelect.value,
    loras: state.selectedLoras.map((item) => ({ ...item })),
  };
}

async function loadResources() {
  try {
    const data = await api("/api/resources");
    state.resources = {
      workflows: data.workflows || [],
      checkpoints: data.checkpoints || [],
      vaes: data.vaes || [],
      loras: data.loras || [],
      llms: data.llms || [],
      defaults: data.defaults || {},
    };
    fillSelect(elements.workflowSelect, state.resources.workflows, (item) => item.id, (item) => item.name, state.resources.defaults.workflow);
    fillSelect(elements.checkpointSelect, state.resources.checkpoints, (item) => item, (item) => item, state.resources.defaults.checkpoint);
    fillSelect(elements.vaeSelect, ["", ...state.resources.vaes], (item) => item, (item) => item || t("Checkpoint VAE"));
    fillSelect(elements.llmSelect, state.resources.llms, (item) => item, (item) => item, state.resources.defaults.llm);
    fillSelect(elements.loraSelect, state.resources.loras, (item) => item, (item) => item);
    elements.workflowSelect.disabled = !state.resources.workflows.length;
    elements.checkpointSelect.disabled = !state.resources.checkpoints.length;
    elements.vaeSelect.disabled = !state.resources.vaes.length;
    elements.llmSelect.disabled = !state.resources.llms.length;
    updateLoraAvailability();
  } catch (error) {
    elements.workflowSelect.disabled = true;
    elements.checkpointSelect.disabled = true;
    elements.vaeSelect.disabled = true;
    elements.llmSelect.disabled = true;
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

async function loadRemoteStorage() {
  try {
    const data = await api("/api/storage/resources");
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
    uiText(elements.storageSummary, data.enabled
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
    await Promise.all([loadRemoteStorage(), loadBackup(), loadRestorePoints()]);
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
    for (const file of data.files) {
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
  if (!names.length && !memory) return showNotice(t("Select a file or Memory snapshot first."));
  elements.startBackupButton.disabled = true;
  try {
    const data = await api("/api/backup/upload", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ names, memory, targets }),
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

function setView(name) {
  $$(".nav-item").forEach((button) => button.classList.toggle("active", button.dataset.view === name));
  $$("[data-view-panel]").forEach((panel) => panel.classList.toggle("active", panel.dataset.viewPanel === name));
  uiText($("#viewEyebrow"), viewCopy[name][0]);
  uiText($("#viewTitle"), viewCopy[name][1]);
  if (name === "history") loadHistory();
  if (name === "runtime") loadRuntime();
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
    if (!finished) return;
    clearInterval(state.pollTimer);
    state.pollTimer = null;
    elements.generateButton.disabled = false;
    setGenerationState(failed ? "Failed" : "Complete", failed ? "error" : "success");
    if (failed) showNotice(t("Image Forge returned a failed task. Check the runtime logs."));
  } catch (error) {
    clearInterval(state.pollTimer);
    state.pollTimer = null;
    elements.generateButton.disabled = false;
    setGenerationState("Unavailable", "error");
    showNotice(error.message);
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
  if (state.pollTimer) clearInterval(state.pollTimer);
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
    const data = await api("/api/generate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        message,
        session_id: state.sessionId,
        selection: generationSelection(),
      }),
    });
    await Promise.all([loadCurrentSubject(), loadSubjects()]);
    const items = data.result?.items || [];
    if (!items.length) throw new Error(t("Orchestrator did not return any queued frames."));
    renderWaiting(items);
    setGenerationState("{count} queued", "running", { count: items.length });
    await pollResults(items);
    if (!state.pollTimer && elements.generateButton.disabled) {
      state.pollTimer = setInterval(() => pollResults(items), 1800);
    }
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
  elements.addLoraButton.addEventListener("click", addSelectedLora);
  $("#viewRevisionsButton").addEventListener("click", showRevisions);
  $("#closeRevisionModal").addEventListener("click", () => elements.revisionModal.close());
  elements.generateButton.addEventListener("click", generate);
  elements.scenePrompt.addEventListener("keydown", (event) => {
    if (event.ctrlKey && event.key === "Enter") generate();
  });
  $("#refreshButton").addEventListener("click", async () => {
    hideNotice();
    await Promise.all([loadSubjects(), loadRuntime(), loadResources(), loadRemoteStorage()]);
  });
  $("#refreshHistoryButton").addEventListener("click", loadHistory);
  elements.downloadOutputsButton.addEventListener("click", downloadOutputsArchive);
  $("#refreshRuntimeButton").addEventListener("click", loadRuntime);
  $("#refreshStorageButton").addEventListener("click", loadRemoteStorage);
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
  await Promise.all([loadSubjects(), loadCurrentSubject(), loadConversation(), loadRuntime(), loadResources(), loadRemoteStorage(), loadDirectDownload(), loadBackup()]);
  setInterval(loadRuntime, 20000);
}

initialize();
