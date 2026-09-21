const state = {
  subjects: [],
  selectedSubject: null,
  subjectMode: "create",
  pollTimer: null,
};

const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => [...document.querySelectorAll(selector)];

const elements = {
  notice: $("#notice"),
  noticeText: $("#noticeText"),
  subjectSelect: $("#subjectSelect"),
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
  galleryGrid: $("#galleryGrid"),
  runtimeGrid: $("#runtimeGrid"),
  healthDot: $("#globalHealthDot"),
  healthTitle: $("#globalHealthTitle"),
  healthDetail: $("#globalHealthDetail"),
  subjectModal: $("#subjectModal"),
  subjectForm: $("#subjectForm"),
  subjectModalKicker: $("#subjectModalKicker"),
  subjectModalTitle: $("#subjectModalTitle"),
  subjectModalCopy: $("#subjectModalCopy"),
  subjectIdRow: $("#subjectIdRow"),
  subjectIdInput: $("#subjectIdInput"),
  subjectDescriptionInput: $("#subjectDescriptionInput"),
  subjectDescriptionLabel: $("#subjectDescriptionLabel"),
  saveSubjectButton: $("#saveSubjectButton"),
  revisionModal: $("#revisionModal"),
  revisionList: $("#revisionList"),
  imageViewer: $("#imageViewer"),
  viewerImage: $("#viewerImage"),
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

function setView(name) {
  $$(".nav-item").forEach((button) => button.classList.toggle("active", button.dataset.view === name));
  $$("[data-view-panel]").forEach((panel) => panel.classList.toggle("active", panel.dataset.viewPanel === name));
  $("#viewEyebrow").textContent = viewCopy[name][0];
  $("#viewTitle").textContent = viewCopy[name][1];
  if (name === "history") loadHistory();
  if (name === "runtime") loadRuntime();
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
  $("#editSubjectButton").disabled = !hasSubject;

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

function renderSubjectOptions() {
  const current = state.selectedSubject?.subject_id || localStorage.getItem("everspark.subject") || "";
  elements.subjectSelect.replaceChildren();
  const none = document.createElement("option");
  none.value = "";
  none.textContent = "No subject · scene only";
  elements.subjectSelect.appendChild(none);
  for (const item of state.subjects) {
    const option = document.createElement("option");
    option.value = item.subject_id;
    option.textContent = `${item.display_name || item.subject_id} · R${item.revision}`;
    elements.subjectSelect.appendChild(option);
  }
  elements.subjectSelect.value = state.subjects.some((item) => item.subject_id === current) ? current : "";
}

function renderSubjectGrid() {
  elements.subjectGrid.replaceChildren();
  if (!state.subjects.length) {
    const empty = document.createElement("div");
    empty.className = "empty-collection";
    empty.textContent = "No subjects yet. Create the first reusable character identity.";
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

    const actions = document.createElement("div");
    actions.className = "subject-card-actions";
    const use = document.createElement("button");
    use.type = "button";
    use.textContent = "Use in Forge";
    use.addEventListener("click", async () => {
      await selectSubject(item.subject_id);
      setView("forge");
    });
    const revise = document.createElement("button");
    revise.type = "button";
    revise.textContent = "Update";
    revise.addEventListener("click", async () => {
      await selectSubject(item.subject_id);
      openSubjectModal("update");
    });
    actions.append(use, revise);
    card.append(top, meta, actions);
    elements.subjectGrid.appendChild(card);
  }
}

async function loadSubjects(preferredId = null) {
  try {
    const data = await api("/api/subjects");
    state.subjects = data.subjects || [];
    elements.subjectCount.textContent = String(state.subjects.length);
    renderSubjectOptions();
    renderSubjectGrid();
    const candidate = preferredId ?? elements.subjectSelect.value;
    if (candidate && state.subjects.some((item) => item.subject_id === candidate)) {
      await selectSubject(candidate, false);
    } else if (state.selectedSubject && !state.subjects.some((item) => item.subject_id === state.selectedSubject.subject_id)) {
      await selectSubject("", false);
    } else {
      renderSelectedSubject();
    }
  } catch (error) {
    state.subjects = [];
    elements.subjectCount.textContent = "0";
    renderSubjectOptions();
    renderSubjectGrid();
    renderSelectedSubject();
    showNotice(error.message);
  }
}

async function selectSubject(subjectId, persist = true) {
  if (!subjectId) {
    state.selectedSubject = null;
    elements.subjectSelect.value = "";
    if (persist) localStorage.removeItem("everspark.subject");
    renderSelectedSubject();
    return;
  }
  try {
    const query = new URLSearchParams({ subject_id: subjectId });
    const data = await api(`/api/subjects?${query}`);
    state.selectedSubject = data.document;
    elements.subjectSelect.value = subjectId;
    if (persist) localStorage.setItem("everspark.subject", subjectId);
    renderSelectedSubject();
  } catch (error) {
    showNotice(error.message);
  }
}

function openSubjectModal(mode) {
  state.subjectMode = mode;
  const update = mode === "update";
  if (update && !state.selectedSubject) {
    showNotice("Select a subject before updating it.");
    return;
  }
  elements.subjectModalKicker.textContent = update ? "NEW IMMUTABLE REVISION" : "NEW STRUCTURED IDENTITY";
  elements.subjectModalTitle.textContent = update ? "Update this subject" : "Create a subject";
  elements.subjectModalCopy.textContent = update
    ? "Describe only what changed. Unmentioned identity fields remain intact and a new revision is saved."
    : "Describe stable visual identity only. Scene, pose, camera and background belong in the Forge prompt.";
  elements.subjectIdRow.classList.toggle("hidden", update);
  elements.subjectDescriptionLabel.textContent = update ? "Requested identity change" : "Identity description";
  elements.subjectDescriptionInput.placeholder = update
    ? "Change the hair to silver and keep every other trait unchanged..."
    : "A young woman with waist-length black hair, sharp amber eyes, a black high-collar coat...";
  elements.saveSubjectButton.textContent = update ? "Create revision" : "Build subject";
  elements.subjectIdInput.value = update ? state.selectedSubject.subject_id : "";
  elements.subjectDescriptionInput.value = "";
  elements.subjectModal.showModal();
  setTimeout(() => (update ? elements.subjectDescriptionInput : elements.subjectIdInput).focus(), 30);
}

async function saveSubject(event) {
  event.preventDefault();
  if (event.submitter?.value === "cancel") {
    elements.subjectModal.close();
    return;
  }
  const subjectId = (state.subjectMode === "update" ? state.selectedSubject?.subject_id : elements.subjectIdInput.value).trim();
  const text = elements.subjectDescriptionInput.value.trim();
  if (!subjectId || !text) {
    showNotice("Subject ID and identity description are required.");
    return;
  }
  if (!/^[a-z0-9][a-z0-9-]*$/.test(subjectId)) {
    showNotice("Subject ID must use lowercase letters, numbers and hyphens.");
    return;
  }
  elements.saveSubjectButton.disabled = true;
  elements.saveSubjectButton.textContent = state.subjectMode === "update" ? "Creating revision..." : "Building subject...";
  try {
    const data = await api("/api/subjects/generate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ subject_id: subjectId, text }),
    });
    elements.subjectModal.close();
    hideNotice();
    await loadSubjects(data.document.subject_id);
  } catch (error) {
    showNotice(error.message);
  } finally {
    elements.saveSubjectButton.disabled = false;
    elements.saveSubjectButton.textContent = state.subjectMode === "update" ? "Create revision" : "Build subject";
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
  const message = elements.scenePrompt.value.trim();
  if (!message || elements.generateButton.disabled) {
    if (!message) showNotice("Describe the scene before generating.");
    return;
  }
  if (state.pollTimer) clearInterval(state.pollTimer);
  hideNotice();
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
        session_id: "main",
        subject_id: state.selectedSubject?.subject_id || "",
      }),
    });
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
  [$("#newSubjectButton"), $("#emptyNewSubjectButton"), $("#subjectsNewButton")].forEach((button) => button.addEventListener("click", () => openSubjectModal("create")));
  $("#editSubjectButton").addEventListener("click", () => openSubjectModal("update"));
  elements.subjectSelect.addEventListener("change", () => selectSubject(elements.subjectSelect.value));
  elements.subjectForm.addEventListener("submit", saveSubject);
  $("#viewRevisionsButton").addEventListener("click", showRevisions);
  $("#closeRevisionModal").addEventListener("click", () => elements.revisionModal.close());
  elements.generateButton.addEventListener("click", generate);
  elements.scenePrompt.addEventListener("keydown", (event) => {
    if (event.ctrlKey && event.key === "Enter") generate();
  });
  $("#refreshButton").addEventListener("click", async () => {
    hideNotice();
    await Promise.all([loadSubjects(), loadRuntime()]);
  });
  $("#refreshHistoryButton").addEventListener("click", loadHistory);
  $("#refreshRuntimeButton").addEventListener("click", loadRuntime);
  $("#dismissNotice").addEventListener("click", hideNotice);
  $("#closeImageViewer").addEventListener("click", () => elements.imageViewer.close());
  elements.imageViewer.addEventListener("click", (event) => {
    if (event.target === elements.imageViewer) elements.imageViewer.close();
  });
}

async function initialize() {
  bindEvents();
  renderSelectedSubject();
  await Promise.all([loadSubjects(), loadRuntime()]);
  setInterval(loadRuntime, 20000);
}

initialize();
