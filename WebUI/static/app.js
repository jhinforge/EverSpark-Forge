const state = {
  subjects: [],
  selectedSubject: null,
  mode: "discuss",
  resources: { workflows: [], checkpoints: [], loras: [], llms: [], defaults: {} },
  remoteStorage: null,
  selectedLoras: [],
  sessionId: localStorage.getItem("everspark.session") || crypto.randomUUID(),
  pollTimer: null,
};
localStorage.setItem("everspark.session", state.sessionId);

const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => [...document.querySelectorAll(selector)];

const elements = {
  notice: $("#notice"),
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
  resultStage: $("#resultStage"),
  generationState: $("#generationState"),
  scenePrompt: $("#scenePrompt"),
  generateButton: $("#generateButton"),
  conversationFeed: $("#conversationFeed"),
  discussModeButton: $("#discussModeButton"),
  generateModeButton: $("#generateModeButton"),
  galleryGrid: $("#galleryGrid"),
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
  llmSelect: $("#llmSelect"),
  loraSelect: $("#loraSelect"),
  addLoraButton: $("#addLoraButton"),
  selectedLoras: $("#selectedLoras"),
  storageSummary: $("#storageSummary"),
  storageJobStatus: $("#storageJobStatus"),
  remoteCheckpointSelect: $("#remoteCheckpointSelect"),
  remoteDiffusionSelect: $("#remoteDiffusionSelect"),
  remoteLoraSelect: $("#remoteLoraSelect"),
  remoteConceptSelect: $("#remoteConceptSelect"),
};

const viewCopy = {
  forge: ["WORKSPACE / FORGE", "Turn an idea into an image."],
  subjects: ["WORKSPACE / SUBJECTS", "Build identity that persists."],
  history: ["WORKSPACE / GALLERY", "Review the latest outputs."],
  runtime: ["WORKSPACE / RUNTIME", "Know what is ready."],
};

async function api(path, options = {}) {
  const response = await fetch(path, { cache: "no-store", ...options });
  let data;
  try {
    data = await response.json();
  } catch (_error) {
    throw new Error(`Invalid server response (HTTP ${response.status})`);
  }
  if (!response.ok || data.ok === false) {
    throw new Error(data.error || `Request failed (HTTP ${response.status})`);
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
  if (!value) return "Unknown time";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? String(value) : date.toLocaleString();
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
      cell.textContent = label;
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
    model.title = "Model strength";
    model.setAttribute("aria-label", `${item.name} model strength`);
    model.addEventListener("change", () => { item.strength_model = Number(model.value); });
    const clip = document.createElement("input");
    clip.type = "number";
    clip.step = "0.05";
    clip.min = "-10";
    clip.max = "10";
    clip.value = String(item.strength_clip);
    clip.title = "CLIP strength";
    clip.setAttribute("aria-label", `${item.name} CLIP strength`);
    clip.addEventListener("change", () => { item.strength_clip = Number(clip.value); });
    const remove = document.createElement("button");
    remove.type = "button";
    remove.textContent = "×";
    remove.setAttribute("aria-label", `Remove ${item.name}`);
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
      loras: data.loras || [],
      llms: data.llms || [],
      defaults: data.defaults || {},
    };
    fillSelect(elements.workflowSelect, state.resources.workflows, (item) => item.id, (item) => item.name, state.resources.defaults.workflow);
    fillSelect(elements.checkpointSelect, state.resources.checkpoints, (item) => item, (item) => item, state.resources.defaults.checkpoint);
    fillSelect(elements.llmSelect, state.resources.llms, (item) => item, (item) => item, state.resources.defaults.llm);
    fillSelect(elements.loraSelect, state.resources.loras, (item) => item, (item) => item);
    elements.workflowSelect.disabled = !state.resources.workflows.length;
    elements.checkpointSelect.disabled = !state.resources.checkpoints.length;
    elements.llmSelect.disabled = !state.resources.llms.length;
    updateLoraAvailability();
  } catch (error) {
    elements.workflowSelect.disabled = true;
    elements.checkpointSelect.disabled = true;
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
    option.textContent = "No remote models found";
    select.appendChild(option);
    select.disabled = true;
    return;
  }
  for (const item of items) {
    const option = document.createElement("option");
    option.value = item.name;
    option.textContent = `${item.name}${item.installed ? " · installed" : ""}`;
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
    concept_model: elements.remoteConceptSelect,
  }[kind];
}

function updateStorageButtons() {
  $$(".storage-pull-button").forEach((button) => {
    const selected = storageSelect(button.dataset.kind)?.selectedOptions?.[0];
    const installed = selected?.dataset.installed === "true";
    button.disabled = !state.remoteStorage?.enabled || !selected?.value || installed;
    button.textContent = installed ? "Installed" : "Download";
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
    fillRemoteSelect(elements.remoteConceptSelect, data.concept?.models || []);
    elements.storageSummary.textContent = data.enabled
      ? "R2 is connected. Downloads are selective and never restore the legacy ComfyUI runtime."
      : "Remote storage is disabled in local mode. Configure the rclone backend to enable it.";
    updateStorageButtons();
  } catch (error) {
    state.remoteStorage = null;
    elements.storageSummary.textContent = error.message;
    $$(".storage-pull-button").forEach((button) => { button.disabled = true; });
  }
}

async function pollStorageJob(jobId) {
  while (true) {
    const data = await api(`/api/storage/jobs?job_id=${encodeURIComponent(jobId)}`);
    const job = data.job;
    if (!job) throw new Error("Remote download job disappeared");
    const progress = job.progress || {};
    elements.storageJobStatus.textContent = `${job.name}: ${job.status} ${progress.completed || 0}/${progress.total || 0}`;
    if (job.status === "completed") {
      await Promise.all([loadRemoteStorage(), loadResources()]);
      return;
    }
    if (job.status === "failed") throw new Error(job.error || "Remote download failed");
    await new Promise((resolve) => setTimeout(resolve, 1000));
  }
}

async function pullRemoteResource(button) {
  const kind = button.dataset.kind;
  const name = storageSelect(kind)?.value;
  if (!name) return;
  $$(".storage-pull-button").forEach((item) => { item.disabled = true; });
  elements.storageJobStatus.textContent = `${name}: queued`;
  try {
    const data = await api("/api/storage/pull", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ kind, name }),
    });
    await pollStorageJob(data.job.job_id);
  } catch (error) {
    elements.storageJobStatus.textContent = error.message;
    showNotice(error.message);
    updateStorageButtons();
  }
}

function setView(name) {
  $$(".nav-item").forEach((button) => button.classList.toggle("active", button.dataset.view === name));
  $$("[data-view-panel]").forEach((panel) => panel.classList.toggle("active", panel.dataset.viewPanel === name));
  $("#viewEyebrow").textContent = viewCopy[name][0];
  $("#viewTitle").textContent = viewCopy[name][1];
  if (name === "history") loadHistory();
  if (name === "runtime") Promise.all([loadRuntime(), loadRemoteStorage()]);
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

function renderSelectedSubject() {
  const subject = state.selectedSubject;
  const hasSubject = Boolean(subject);
  elements.selectedEmpty.classList.toggle("hidden", hasSubject);
  elements.selectedCard.classList.toggle("hidden", !hasSubject);

  elements.composerContext.replaceChildren();
  const miniAvatar = document.createElement("span");
  miniAvatar.className = "mini-avatar";
  const contextText = document.createElement("span");

  if (!hasSubject) {
    miniAvatar.textContent = "—";
    contextText.textContent = "No persistent subject";
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
    trait.textContent = "Identity ready";
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
  contextText.textContent = `${displayName} · revision ${subject.revision}`;
  elements.composerContext.append(miniAvatar, contextText);
}

function renderSubjectGrid() {
  elements.subjectGrid.replaceChildren();
  if (!state.subjects.length) {
    const empty = document.createElement("div");
    empty.className = "empty-collection";
    empty.textContent = "No subjects yet. Start a conversation and EverSpark will extract one automatically.";
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
    revision.textContent = `REVISION ${item.revision}`;
    const updated = document.createElement("span");
    updated.textContent = formatDate(item.updated_at);
    meta.append(revision, updated);

    card.append(top, meta);
    elements.subjectGrid.appendChild(card);
  }
}

async function loadSubjects() {
  try {
    const data = await api("/api/subjects");
    state.subjects = data.subjects || [];
    elements.subjectCount.textContent = String(state.subjects.length);
    renderSubjectGrid();
  } catch (error) {
    state.subjects = [];
    elements.subjectCount.textContent = "0";
    renderSubjectGrid();
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
  loading.textContent = "Loading revision history...";
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
      title.textContent = `Revision ${item.revision}`;
      const time = document.createElement("time");
      time.textContent = formatDate(item.created_at);
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

function appendConversation(role, content) {
  const message = document.createElement("article");
  message.className = `conversation-message ${role}`;
  const label = document.createElement("strong");
  label.textContent = role === "user" ? "You" : "Concept Forge";
  const body = document.createElement("p");
  body.textContent = content;
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
      if (message.role === "assistant") {
        try {
          const parsed = JSON.parse(content);
          if (parsed.status === "over") content = `Queued ${parsed.count || 1} image request.`;
        } catch (_error) {
          // Visible discussion replies are stored as plain text.
        }
      }
      appendConversation(message.role, content);
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
  elements.generateButton.firstElementChild.textContent = discussing ? "Discuss" : "Forge image";
  elements.scenePrompt.placeholder = discussing
    ? "Let's design a character with long black hair and amber eyes..."
    : "Place the current character on a rooftop at blue hour...";
}

async function discuss() {
  const message = elements.scenePrompt.value.trim();
  if (!message || elements.generateButton.disabled) {
    if (!message) showNotice("Say something about the current character.");
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
  elements.conversationFeed.replaceChildren();
  elements.scenePrompt.value = "";
  renderSelectedSubject();
  setMode("discuss");
  setGenerationState("Ready", "idle");
}

function setGenerationState(label, mode = "idle") {
  elements.generationState.dataset.state = mode;
  elements.generationState.lastChild.textContent = ` ${label}`;
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
    label.textContent = `Frame ${item.index} · queued`;
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
  img.alt = image.filename || "Generated image";
  img.loading = "lazy";
  button.appendChild(img);
  button.addEventListener("click", () => {
    elements.viewerImage.src = image.url;
    elements.viewerImage.alt = image.filename || "Generated image";
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
      label.textContent = item.status === "failed" ? "Generation failed" : "Image Forge is working";
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
    if (failed) showNotice("Image Forge returned a failed task. Check the runtime logs.");
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
    if (!message) showNotice("Describe the scene before generating.");
    return;
  }
  if (state.pollTimer) clearInterval(state.pollTimer);
  hideNotice();
  appendConversation("user", message);
  elements.generateButton.disabled = true;
  setGenerationState("Planning", "running");
  elements.resultStage.replaceChildren();
  const pending = document.createElement("div");
  pending.className = "stage-empty";
  const spinner = document.createElement("span");
  spinner.className = "spinner";
  const title = document.createElement("h3");
  title.textContent = "Concept Forge is shaping the request";
  const detail = document.createElement("p");
  detail.textContent = state.selectedSubject ? "Stable identity is being merged with this scene." : "This task uses scene direction only.";
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
    elements.scenePrompt.value = "";
    await Promise.all([loadCurrentSubject(), loadSubjects()]);
    const items = data.result?.items || [];
    if (!items.length) throw new Error("Orchestrator did not return any queued frames.");
    renderWaiting(items);
    setGenerationState(`${items.length} queued`, "running");
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
  loading.textContent = "Loading Image Forge history...";
  elements.galleryGrid.appendChild(loading);
  try {
    const data = await api("/api/history?limit=36");
    elements.galleryGrid.replaceChildren();
    if (!data.images?.length) {
      const empty = document.createElement("div");
      empty.className = "empty-collection";
      empty.textContent = "No generated images are available yet.";
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

function runtimeCard(title, online, copy) {
  const card = document.createElement("article");
  card.className = "runtime-card";
  const head = document.createElement("div");
  head.className = "runtime-card-head";
  const name = document.createElement("h3");
  name.textContent = title;
  const dot = document.createElement("span");
  dot.className = `runtime-status ${online ? "online" : "offline"}`;
  const detail = document.createElement("p");
  detail.textContent = copy;
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
      runtimeCard("Runtime logs", logging, logging ? `${data.logging.present}/${data.logging.configured} managed logs are present.` : "The runtime log manifest is unavailable."),
    );
    elements.healthDot.className = `pulse-dot ${data.ready ? "online" : "partial"}`;
    elements.healthTitle.textContent = data.ready ? "System ready" : "Setup required";
    elements.healthDetail.textContent = data.ready ? "All local services responding" : "Open Runtime for details";
  } catch (error) {
    elements.healthDot.className = "pulse-dot partial";
    elements.healthTitle.textContent = "Status unavailable";
    elements.healthDetail.textContent = "WebUI could not complete checks";
    if ($("#runtimeView").classList.contains("active")) showNotice(error.message);
  }
}

function bindEvents() {
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
  $("#refreshRuntimeButton").addEventListener("click", loadRuntime);
  $("#refreshStorageButton").addEventListener("click", loadRemoteStorage);
  $$(".storage-pull-button").forEach((button) => button.addEventListener("click", () => pullRemoteResource(button)));
  [elements.remoteCheckpointSelect, elements.remoteDiffusionSelect, elements.remoteLoraSelect, elements.remoteConceptSelect]
    .forEach((select) => select.addEventListener("change", updateStorageButtons));
  $("#dismissNotice").addEventListener("click", hideNotice);
  $("#closeImageViewer").addEventListener("click", () => elements.imageViewer.close());
  elements.imageViewer.addEventListener("click", (event) => {
    if (event.target === elements.imageViewer) elements.imageViewer.close();
  });
}

async function initialize() {
  bindEvents();
  setMode("discuss");
  renderSelectedSubject();
  await Promise.all([loadSubjects(), loadCurrentSubject(), loadConversation(), loadRuntime(), loadResources(), loadRemoteStorage()]);
  setInterval(loadRuntime, 20000);
}

initialize();
