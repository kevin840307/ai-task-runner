const $ = (id) => document.getElementById(id);
const state = {
  projects: [], project: null, runtime: null, lastStream: "", lastRunId: "",
  view: "chat",
  studioFiles: { workflows: [], prompts: [] }, studioFile: null,
  studioOriginal: "", studioHash: "", studioDirty: false,
  studioGuard: { editable: true, active_projects: [] }, studioMode: "visual", studioSourceKind: "workflow",
  visual: null, visualDirty: false, selectedFlowIndex: -1, stepActionMenuExpanded: false,
  promptTags: [], stageEditorDirty: false, addStageDirty: false, newWorkflowDirty: false, newPromptDirty: false, importAssetDirty: false, generateWorkflowDirty: false, syntaxTimer: 0,
};

async function api(path, options = {}) {
  const response = await fetch(path, { headers: { "Content-Type": "application/json" }, ...options });
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || `HTTP ${response.status}`);
  return data;
}
function selectedWorkflowItem() { const value = $("workflowSelect")?.value || ""; return (state.studioFiles.workflows || []).find((item) => item.path === value) || null; }
function payload(extra = {}) {
  const workflow = selectedWorkflowItem();
  return {
    project: state.project?.path || "",
    backend: $("backend").value,
    validator: workflow?.requires_python_validator ? $("validator").value.trim() : "",
    workflow: workflow?.path || "",
    ...extra,
  };
}
function projectQuery() { return state.project ? `&project=${encodeURIComponent(state.project.path)}` : ""; }
function escapeHtml(value) { return String(value ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c])); }
function normalizedPath(value) { return String(value || "").replaceAll("\\", "/").replace(/^\.\//, "").toLowerCase(); }
function showToast(message, tone = "success", duration = 2200) {
  let stack = document.querySelector(".app-toast-stack");
  if (!stack) { stack = document.createElement("div"); stack.className = "app-toast-stack"; document.body.appendChild(stack); }
  const node = document.createElement("div"); node.className = `app-toast ${tone}`; node.setAttribute("role", tone === "error" ? "alert" : "status"); node.setAttribute("aria-live", tone === "error" ? "assertive" : "polite"); node.textContent = message; stack.appendChild(node);
  requestAnimationFrame(() => node.classList.add("show"));
  setTimeout(() => { node.classList.remove("show"); setTimeout(() => node.remove(), 180); }, duration);
}
function showActionError(message, fallback = "Action failed") {
  const detail = String(message || "").trim(); const firstLine = detail.split(/\r?\n/).find((line) => line.trim())?.trim() || fallback; const summary = firstLine.length > 180 ? `${firstLine.slice(0, 177)}...` : firstLine;
  showToast(summary, "error", 3200);
}
function confirmDialog({ title, message, confirmLabel = "Confirm", danger = false }) {
  return new Promise((resolve) => {
    const box = document.createElement("div"); box.className = "designer-export-box designer-confirm-box";
    box.innerHTML = `<div class="designer-export-card" style="width:min(480px,96vw);"><div class="designer-step-card-title"><div><h2 style="margin:0;">${escapeHtml(title)}</h2><p class="designer-form-hint">${escapeHtml(message)}</p></div><button type="button" data-confirm-close aria-label="Close">×</button></div><div class="designer-footer-actions"><button type="button" data-confirm-close>Cancel</button><button type="button" data-confirm-ok class="${danger ? "designer-danger-button" : "primary"}">${escapeHtml(confirmLabel)}</button></div></div>`;
    document.body.appendChild(box);
    const finish = (value) => { box.remove(); resolve(value); };
    box.querySelectorAll("[data-confirm-close]").forEach((b) => b.onclick = () => finish(false));
    box.querySelector("[data-confirm-ok]").onclick = () => finish(true);
    box.addEventListener("click", (e) => { if (e.target === box) finish(false); });
    box.querySelector("[data-confirm-ok]").focus();
  });
}
function syncComposerReserve() {
  const panel = $("composePanel"); if (!panel || panel.hidden) return;
  const reserve = Math.ceil(panel.getBoundingClientRect().height + 18);
  $("chatView")?.style.setProperty("--composer-reserve", `${reserve}px`);
}

// ------------------------------ Projects / Chat ------------------------------
async function loadProjects() {
  const data = await api("/api/projects"); state.projects = data.projects || []; renderProjects();
  if (!state.project && state.projects.length) { const first = state.projects.find((p) => p.exists !== false); if (first) await selectProject(first); }
}
const projectMenuOwners = new WeakMap();
function restoreProjectMenu(menu) {
  const owner = projectMenuOwners.get(menu);
  menu.classList.remove("project-action-menu-portal");
  menu.style.left = ""; menu.style.top = ""; menu.style.right = ""; menu.style.bottom = "";
  if (owner?.row?.isConnected && menu.parentElement !== owner.row) owner.row.appendChild(menu);
}
function closeProjectMenus(except = null) {
  document.querySelectorAll(".project-action-menu").forEach((menu) => {
    if (menu === except) return;
    menu.hidden = true; restoreProjectMenu(menu);
  });
}
function positionProjectMenu(menu, anchor) {
  if (!menu || !anchor || menu.hidden || !anchor.isConnected) return;
  const anchorRect = anchor.getBoundingClientRect(), menuRect = menu.getBoundingClientRect(), pad = 8, gap = 6;
  const maxLeft = Math.max(pad, window.innerWidth - menuRect.width - pad);
  const left = Math.min(maxLeft, Math.max(pad, anchorRect.right - menuRect.width));
  let top = anchorRect.bottom + gap;
  if (top + menuRect.height > window.innerHeight - pad) top = anchorRect.top - menuRect.height - gap;
  top = Math.min(Math.max(pad, top), Math.max(pad, window.innerHeight - menuRect.height - pad));
  menu.style.left = `${Math.round(left)}px`; menu.style.top = `${Math.round(top)}px`; menu.style.right = "auto"; menu.style.bottom = "auto";
}
function openProjectMenu(menu, anchor, row) {
  closeProjectMenus(); projectMenuOwners.set(menu, { anchor, row });
  menu.hidden = false; menu.classList.add("project-action-menu-portal"); document.body.appendChild(menu);
  positionProjectMenu(menu, anchor);
}
function renderProjects() {
  const root = $("projectList"); closeProjectMenus(); root.innerHTML = ""; root.onscroll = () => closeProjectMenus();
  for (const project of state.projects) {
    const row = document.createElement("div"); row.className = "project-tree project-row";
    if (state.project?.path === project.path) row.classList.add("active");
    if (project.exists === false) row.classList.add("missing");
    const button = document.createElement("button"); button.className = "project-root"; button.type = "button";
    const mark = document.createElement("span"); mark.className = "project-mark";
    const copy = document.createElement("span"); copy.className = "project-copy";
    const name = document.createElement("strong"); name.textContent = project.name;
    const path = document.createElement("small"); path.textContent = project.exists === false ? `Missing · ${project.path}` : project.path;
    copy.append(name, path); button.append(mark, copy); button.onclick = () => project.exists === false ? null : selectProject(project);

    const menuButton = document.createElement("button"); menuButton.className = "project-menu-button"; menuButton.type = "button"; menuButton.title = "Project actions"; menuButton.setAttribute("aria-label", `Project actions for ${project.name}`); menuButton.innerHTML = "<span aria-hidden=\"true\"></span>";
    const menu = document.createElement("div"); menu.className = "project-action-menu"; menu.hidden = true;
    const remove = document.createElement("button"); remove.type = "button"; remove.className = "danger-text"; remove.textContent = "Remove project";
    menu.appendChild(remove);
    menuButton.onclick = (event) => {
      event.stopPropagation(); const open = menu.hidden;
      if (open) openProjectMenu(menu, menuButton, row); else closeProjectMenus();
    };
    remove.onclick = async (event) => {
      event.stopPropagation();
      if (!confirmDiscardStudio()) return;
      const ok = await confirmDialog({ title: "Remove Project?", message: `Remove ${project.name} from this UI? Project files are not deleted.`, confirmLabel: "Remove Project", danger: true });
      if (!ok) return;
      closeStageEditor(true); closeAddStageModal(true); closeProjectMenus();
      try { await api("/api/projects/remove", { method: "POST", body: JSON.stringify({ path: project.path }) }); if (state.project?.path === project.path) { state.project = null; showEmpty(); } await loadProjects(); showToast("Project removed"); }
      catch (error) { showAppError(error.message); showActionError(error.message, "Remove Project failed"); }
    };
    row.append(button, menuButton, menu); root.appendChild(row);
  }
}
function showAppError(message) { if (state.view === "workflow") setStudioStatus(message, true); else $("errorText").textContent = message || ""; }
function showEmpty() {
  $("projectName").textContent = "Select a project"; $("projectPath").textContent = "Open a local project folder to begin.";
  $("summary").hidden = true; $("messages").hidden = true; $("composePanel").hidden = true; $("emptyState").hidden = false;
}
async function selectProject(project) {
  if (state.project?.path !== project.path && !confirmDiscardStudio()) return;
  if (state.project?.path !== project.path) { closeStageEditor(true); closeAddStageModal(true); }
  state.project = project; state.lastStream = ""; renderProjects();
  $("projectName").textContent = project.name; $("projectPath").textContent = project.path; $("emptyState").hidden = true;
  $("summary").hidden = false; $("messages").hidden = false; $("composePanel").hidden = false; $("errorText").textContent = ""; requestAnimationFrame(syncComposerReserve);
  await Promise.all([refreshMessages(), refreshRuntime(), refreshStudioFiles()]);
}
async function refreshMessages() {
  if (!state.project) return; const data = await api(`/api/project/messages?project=${encodeURIComponent(state.project.path)}`);
  const root = $("messages"); const live = root.querySelector(".live-activity"); root.innerHTML = "";
  for (const message of data.messages || []) {
    const item = document.createElement("article"); item.className = `message ${message.role}`; item.dataset.role = message.role || "assistant";
    const body = document.createElement("div"); body.className = "message-body"; body.textContent = message.content || ""; item.appendChild(body); root.appendChild(item);
  }
  if (live) root.appendChild(live); root.scrollTop = root.scrollHeight;
}
function ensureLiveCard() {
  let card = $("messages").querySelector(".live-activity"); if (card) return card;
  card = document.createElement("article"); card.className = "live-activity";
  card.innerHTML = `<div class="live-activity-head"><span class="live-dot"></span><strong class="live-title">Working</strong><small class="live-progress"></small></div><div class="live-meta"></div><pre class="live-output"></pre>`;
  $("messages").appendChild(card); return card;
}
function removeLiveCard() { $("messages")?.querySelector(".live-activity")?.remove(); }
async function refreshRuntime() { if (!state.project) return; try { const runtime = await api(`/api/project/runtime?project=${encodeURIComponent(state.project.path)}`); state.runtime = runtime; renderRuntime(runtime); } catch (error) { $("errorText").textContent = error.message; } }
function renderRuntime(runtime) {
  const badge = $("statusBadge"); badge.className = "runtime-badge"; let label = "Idle";
  if (runtime.running) { label = "Running"; badge.classList.add("running"); }
  else if (runtime.stale && runtime.resumable) { label = "Interrupted"; badge.classList.add("interrupted"); }
  else if (runtime.last_error && runtime.resumable) { label = "Stopped"; badge.classList.add("failed"); }
  else if (runtime.completed) { label = "Completed"; badge.classList.add("completed"); }
  badge.textContent = label; $("currentStage").textContent = runtime.stage || label; $("progressText").textContent = runtime.total ? `${runtime.current} / ${runtime.total}` : "—"; $("currentTask").textContent = runtime.task || (runtime.last_error || "Waiting");
  $("stopButton").hidden = !runtime.running;
  $("resumeButton").hidden = runtime.running || !runtime.resumable;
  $("rerunButton").hidden = runtime.running || !runtime.completed || !hasUserMessage();
  $("resetButton").hidden = runtime.running || !runtime.resettable;
  $("resetButton").textContent = runtime.completed ? "New Task" : "Reset";
  const blockNew = runtime.running || runtime.resumable;
  $("sendButton").disabled = blockNew; $("messageInput").disabled = blockNew;
  if (runtime.resumable) $("messageInput").placeholder = "Stopped task: Continue or Reset before starting another task.";
  else $("messageInput").placeholder = "描述要完成的功能或修復內容...";
  if (runtime.running || runtime.stream) {
    const card = ensureLiveCard(); card.querySelector(".live-title").textContent = runtime.stage ? `Running · ${runtime.stage}` : label; card.querySelector(".live-progress").textContent = runtime.total ? `${runtime.current} / ${runtime.total}` : "";
    const meta = []; if (runtime.task) meta.push(runtime.task); if (runtime.pid) meta.push(`PID ${runtime.pid}`); card.querySelector(".live-meta").textContent = meta.join(" · ");
    if (runtime.stream !== state.lastStream) { state.lastStream = runtime.stream || ""; const out = card.querySelector(".live-output"); out.textContent = state.lastStream || "Waiting for output..."; out.scrollTop = out.scrollHeight; $("messages").scrollTop = $("messages").scrollHeight; }
  } else removeLiveCard();
  if (runtime.completed && runtime.run_id && runtime.run_id !== state.lastRunId) { state.lastRunId = runtime.run_id; refreshMessages(); }
}
function hasUserMessage() { return $("messages")?.querySelector(".message.user") !== null; }
function resizeComposerInput() { const ta = $("messageInput"); if (!ta) return; ta.style.height = "72px"; syncComposerReserve(); }
async function sendMessage() {
  const text = $("messageInput").value.trim(); if (!text || !state.project) return; $("errorText").textContent = "";
  try { await api("/api/project/message", { method: "POST", body: JSON.stringify(payload({ message: text })) }); $("messageInput").value = ""; resizeComposerInput(); await refreshMessages(); showToast("Task started"); setTimeout(refreshRuntime, 250); }
  catch (error) { $("errorText").textContent = error.message; showActionError(error.message, "Task start failed"); }
}

// ------------------------------ Workflow picker ------------------------------
async function refreshStudioFiles() {
  try {
    const data = await api(`/api/studio/files?x=1${projectQuery()}`); state.studioFiles = data; state.studioGuard = data.guard || { editable: true, active_projects: [] };
    renderStudioGuard(); renderStudioFiles(); renderWorkflowPicker(); fillAddStagePromptOptions(); refreshPromptTags();
  } catch (error) { setStudioStatus(error.message, true); }
}
function closeWorkflowDropdown() {
  const menu = $("workflowDropdownMenu"), picker = $("workflowPicker"), button = $("workflowDropdownButton"); if (!menu || !picker || !button) return;
  menu.hidden = true; menu.classList.remove("workflow-dropdown-portal"); menu.removeAttribute("style");
  if (menu.parentElement !== picker) picker.appendChild(menu);
  picker.classList.remove("open"); button.setAttribute("aria-expanded", "false");
}
function positionWorkflowDropdown() {
  const menu = $("workflowDropdownMenu"), button = $("workflowDropdownButton"); if (!menu || !button || menu.hidden) return;
  const rect = button.getBoundingClientRect(); const gap = 10; const viewportPad = 10;
  const width = Math.min(460, Math.max(280, Math.min(window.innerWidth - viewportPad * 2, rect.width + 120)));
  menu.style.width = `${width}px`; menu.style.maxHeight = `${Math.max(160, Math.min(360, rect.top - 28))}px`;
  const left = Math.min(window.innerWidth - width - viewportPad, Math.max(viewportPad, rect.right - width));
  menu.style.left = `${left}px`; menu.style.right = "auto"; menu.style.bottom = `${Math.max(viewportPad, window.innerHeight - rect.top + gap)}px`; menu.style.top = "auto";
}
function openWorkflowDropdown() {
  const menu = $("workflowDropdownMenu"), picker = $("workflowPicker"), button = $("workflowDropdownButton"); if (!menu || !picker || !button) return;
  if (menu.parentElement !== document.body) document.body.appendChild(menu);
  menu.classList.add("workflow-dropdown-portal"); menu.hidden = false; picker.classList.add("open"); button.setAttribute("aria-expanded", "true");
  positionWorkflowDropdown();
}

function renderWorkflowPicker() {
  const select = $("workflowSelect"), menu = $("workflowDropdownMenu"), label = $("workflowSelectedLabel"); if (!select || !menu || !label) return;
  const previous = select.value; select.innerHTML = ""; menu.innerHTML = "";
  const rows = (state.studioFiles.workflows || []).map((item) => ({ value: item.path, label: item.name, meta: `${item.group || item.scope}${item.requires_python_validator ? " · Python validation" : ""}${item.has_ai_validator ? " · AI validation" : ""}`, scope: item.scope }));
  for (const row of rows) {
    const option = document.createElement("option"); option.value = row.value; option.textContent = row.label; select.appendChild(option);
    const button = document.createElement("button"); button.type = "button"; button.className = "workflow-dropdown-option"; button.setAttribute("role", "option");
    button.innerHTML = `<span class="workflow-option-main"><strong></strong><small></small></span><span class="workflow-option-badge"></span>`;
    button.querySelector("strong").textContent = row.label; button.querySelector("small").textContent = row.meta; button.querySelector(".workflow-option-badge").textContent = row.scope === "system" ? "SYSTEM" : row.scope.toUpperCase();
    button.onclick = () => { select.value = row.value; label.textContent = row.label; closeWorkflowDropdown(); renderWorkflowPickerSelection(); };
    menu.appendChild(button);
  }
  if ([...select.options].some((option) => option.value === previous)) select.value = previous;
  else if (select.options.length) select.selectedIndex = 0;
  label.textContent = select.options[select.selectedIndex]?.textContent || "No workflow";
  renderWorkflowPickerSelection();
}
function renderWorkflowPickerSelection() {
  const value = $("workflowSelect")?.value || "";
  document.querySelectorAll("#workflowDropdownMenu .workflow-dropdown-option").forEach((button, index) => { const active = $("workflowSelect")?.options[index]?.value === value; button.classList.toggle("active", active); button.setAttribute("aria-selected", String(active)); });
  const workflow = selectedWorkflowItem();
  const validatorPicker = $("validatorPicker");
  if (validatorPicker) validatorPicker.hidden = !workflow?.requires_python_validator;
  if (!workflow?.requires_python_validator && $("validator")) $("validator").value = "";
  updateValidatorPicker();
  syncComposerReserve();
}
function updateValidatorPicker() {
  const input = $("validator"), clear = $("clearValidatorButton"); if (!input) return;
  const value = input.value.trim(); input.title = value; if (clear) clear.hidden = !value;
}
async function browseValidator() {
  const button = $("browseValidatorButton"); if (!button) return; const original = button.textContent; button.disabled = true; button.textContent = "Choosing…";
  try { const result = await api("/api/files/pick", { method: "POST", body: JSON.stringify({ kind: "python" }) }); if (!result.cancelled && result.path) { $("validator").value = result.path; updateValidatorPicker(); showToast("Python validator selected"); } }
  catch (error) { showToast(error.message, "error", 3200); }
  finally { button.disabled = false; button.textContent = original; }
}

// ------------------------------ Workflow Studio ------------------------------
function switchView(view) {
  if (view === "workflow") {
    state.view = "workflow"; $("chatView").hidden = true; $("workflowView").hidden = false; $("workflowNav").classList.add("active"); $("chatNav").classList.remove("active"); refreshStudioFiles(); return;
  }
  if (state.view === "workflow" && !confirmDiscardStudio()) return;
  closeStageEditor(true); closeAddStageModal(true); closeNewWorkflowModal(true); state.view = "chat"; $("workflowView").hidden = true; $("chatView").hidden = false; $("chatNav").classList.add("active"); $("workflowNav").classList.remove("active");
}
function visibleStudioFiles() { return state.studioSourceKind === "prompt" ? (state.studioFiles.prompts || []) : (state.studioFiles.workflows || []); }
function renderStudioFiles() {
  const root = $("studioFileList"); root.innerHTML = "";
  $("studioSourceTabs").hidden = false;
  $("studioListTitle").textContent = state.studioSourceKind === "prompt" ? "Prompts" : "Workflows";
  $("yamlWorkflowSource").classList.toggle("active", state.studioSourceKind === "workflow"); $("yamlPromptSource").classList.toggle("active", state.studioSourceKind === "prompt");
  $("newWorkflowButton").hidden = false; $("newWorkflowButton").title = state.studioSourceKind === "prompt" ? "New custom prompt" : "New custom workflow";
  const groups = [["System", []], ["Custom", []], ["Project", []]];
  const groupMap = new Map(groups);
  for (const item of visibleStudioFiles()) (groupMap.get(item.group || "Project") || groupMap.get("Project")).push(item);
  for (const [group, items] of groups) {
    if (!items.length) continue;
    const heading = document.createElement("div"); heading.className = "studio-file-group"; heading.textContent = group; root.appendChild(heading);
    for (const item of items) {
      const button = document.createElement("button"); button.type = "button"; button.className = "studio-file-item designer-workflow-pill"; if (state.studioFile?.id === item.id) button.classList.add("active"); if (item.readonly) button.classList.add("readonly");
      const name = document.createElement("strong"); name.textContent = item.name; const metaNode = document.createElement("small"); metaNode.textContent = item.readonly ? "System · read only" : (item.scope === "custom" ? "Custom" : "Project"); button.append(name, metaNode); button.onclick = () => openStudioFile(item); root.appendChild(button);
    }
  }
  if (!root.querySelector(".studio-file-item")) { const empty = document.createElement("div"); empty.className = "studio-list-empty"; empty.textContent = state.studioSourceKind === "prompt" ? "No prompts" : "No workflows"; root.appendChild(empty); }
}
function clearStudioEditor() {
  state.studioFile = null; state.studioOriginal = ""; state.studioHash = ""; state.studioDirty = false; state.visual = null; state.visualDirty = false; state.selectedFlowIndex = -1;
  $("studioEditor").hidden = true; $("studioEmpty").hidden = false; $("validationOutput").hidden = true; $("studioTextarea").value = ""; $("studioPromptTextarea").value = ""; updateLineNumbers(); updateDirtyState(); renderStudioPanels();
}
async function openStudioFile(item) {
  if (state.studioFile?.id !== item.id && !confirmDiscardStudio()) return;
  try {
    const data = await api(`/api/studio/file?id=${encodeURIComponent(item.id)}${projectQuery()}`);
    let visual = null;
    if (item.kind === "workflow") visual = await api(`/api/studio/visual?id=${encodeURIComponent(item.id)}${projectQuery()}`);
    state.studioFile = data; state.studioOriginal = data.content; state.studioHash = data.hash; state.studioDirty = false; state.visual = visual; state.visualDirty = false; state.selectedFlowIndex = visual?.flow?.length ? 0 : -1; state.studioGuard = data.guard || state.studioGuard;
    $("studioEmpty").hidden = true; $("studioEditor").hidden = false; $("studioFileName").textContent = data.name; $("studioFilePath").textContent = `${data.scope} · ${data.path}`; $("studioKindLabel").textContent = data.kind === "prompt" ? "Prompt" : "Workflow"; $("validationOutput").hidden = true;
    if (data.kind === "prompt") $("studioPromptTextarea").value = data.content; else $("studioTextarea").value = data.content;
    renderStudioGuard(); renderStudioFiles(); renderStudioPanels(); renderVisualDesigner(); renderPromptTags(); updateLineNumbers(); updateDirtyState(); scheduleSyntaxCheck(); setStudioStatus("");
  } catch (error) { setStudioStatus(error.message, true); }
}
function renderStudioPanels() {
  const prompt = state.studioFile?.kind === "prompt";
  const workflow = state.studioFile?.kind === "workflow";
  $("promptEditorPanel").hidden = !prompt;
  $("visualDesignerPanel").hidden = !workflow || state.studioMode !== "visual";
  $("yamlEditorPanel").hidden = !workflow || state.studioMode !== "yaml";
}
function setStudioMode(mode) {
  if (mode === state.studioMode) return;
  // Prompt uses the same editor in both modes; mode only matters to Workflow files.
  if (state.studioFile?.kind === "workflow" && !confirmDiscardStudio()) return;
  state.studioMode = mode;
  $("visualModeButton").classList.toggle("active", mode === "visual"); $("yamlModeButton").classList.toggle("active", mode === "yaml");
  renderStudioPanels(); updateDirtyState(); scheduleSyntaxCheck();
}
function setStudioSource(kind) {
  if (kind === state.studioSourceKind) return;
  if (!confirmDiscardStudio()) return;
  closeStageEditor(true); state.studioSourceKind = kind; clearStudioEditor(); renderStudioFiles();
}
function flowStageName(item) { return typeof item === "string" ? item : String(item?.stage || ""); }
function stageConfig(name) { return (state.visual?.stages || []).find((s) => s.name === name) || { name, type: "base", status: "", prompt: "", recover: [] }; }
function renderVisualDesigner() {
  const root = $("visualFlowList"); if (!root) return; root.innerHTML = ""; const flow = state.visual?.flow || [];
  flow.forEach((item, index) => {
    const name = flowStageName(item), cfg = stageConfig(name);
    const card = document.createElement("article");
    card.className = "visual-flow-card designer-step-card designer-step-card-compact";
    card.draggable = state.studioGuard.editable && !state.studioFile?.readonly;
    card.dataset.index = String(index); card.dataset.stepId = name;
    card.tabIndex = 0;
    card.title = `Click to select. Double-click to edit ${name || "Stage"}`;
    if (index === state.selectedFlowIndex) card.classList.add("active");
    const ix = document.createElement("span"); ix.className = "visual-flow-index designer-step-index"; ix.textContent = String(index + 1);
    const copy = document.createElement("div"); copy.className = "visual-flow-copy designer-step-card-title";
    const displayTitle = String(item?.status ?? cfg.status ?? "").trim() || name || "Unnamed";
    const strong = document.createElement("strong"); strong.textContent = displayTitle; strong.title = displayTitle;
    const small = document.createElement("small"); small.textContent = `${name || "Unnamed"} · ${cfg.type}${item?.scope ? ` · ${item.scope}` : ""}`; small.title = small.textContent;
    copy.append(strong, small); card.append(ix, copy);
    card.addEventListener("click", () => { state.selectedFlowIndex = index; renderVisualDesigner(); });
    card.addEventListener("dblclick", async (event) => { event.preventDefault(); state.selectedFlowIndex = index; renderVisualDesigner(); await openStageEditor(index); });
    card.addEventListener("keydown", async (event) => { if (event.key === "Enter") { event.preventDefault(); state.selectedFlowIndex = index; renderVisualDesigner(); } if (event.key === " " && !event.repeat) { event.preventDefault(); state.selectedFlowIndex = index; renderVisualDesigner(); } });
    card.addEventListener("dragstart", (e) => { card.classList.add("dragging"); e.dataTransfer.setData("text/plain", String(index)); e.dataTransfer.effectAllowed = "move"; });
    card.addEventListener("dragend", () => card.classList.remove("dragging"));
    card.addEventListener("dragover", (e) => { if (state.studioGuard.editable) e.preventDefault(); });
    card.addEventListener("drop", (e) => { e.preventDefault(); const from = Number(e.dataTransfer.getData("text/plain")); if (!Number.isInteger(from) || from === index || !state.studioGuard.editable) return; const moved = flow.splice(from, 1)[0]; flow.splice(index, 0, moved); state.visualDirty = true; state.selectedFlowIndex = index; renderVisualDesigner(); updateDirtyState(); });
    root.appendChild(card);
  });
  if (!flow.length) { const empty = document.createElement("div"); empty.className = "studio-list-empty"; empty.textContent = "No flow steps. Use + Stage."; root.appendChild(empty); return; }
  renderStepFloatingActions(root);
}
function selectedFlowEntry() {
  const flow = state.visual?.flow || []; const index = state.selectedFlowIndex;
  if (!Number.isInteger(index) || index < 0 || index >= flow.length) return null;
  return { index, item: flow[index], name: flowStageName(flow[index]), total: flow.length };
}
function renderStepFloatingActions(root = $("visualFlowList")) {
  const selected = selectedFlowEntry(); if (!root || !selected) return;
  const aside = document.createElement("aside");
  aside.className = `designer-step-floating-actions ${state.stepActionMenuExpanded ? "expanded" : "collapsed"}`;
  aside.setAttribute("aria-label", "Selected Stage actions");
  const readonly = !state.studioGuard.editable || !!state.studioFile?.readonly;
  aside.innerHTML = `
    <button type="button" class="designer-action-fab designer-action-toggle" data-flow-action="toggle" aria-expanded="${state.stepActionMenuExpanded ? "true" : "false"}" title="${state.stepActionMenuExpanded ? "Collapse Stage actions" : "Expand Stage actions"}" aria-label="Stage actions"><span class="designer-action-icon" aria-hidden="true">${state.stepActionMenuExpanded ? "−" : "+"}</span></button>
    <div class="designer-floating-panel" aria-hidden="${state.stepActionMenuExpanded ? "false" : "true"}">
      <span class="designer-floating-step-context" title="${escapeHtml(selected.name)}"><strong>${selected.index + 1} / ${selected.total}</strong><span>${escapeHtml(String(selected.item?.status ?? stageConfig(selected.name).status ?? "").trim() || selected.name || "Selected Stage")}</span></span>
      <span class="designer-floating-action-buttons">
        <button type="button" class="designer-action-fab designer-floating-primary" data-flow-action="edit" title="Edit Stage" aria-label="Edit Stage"><span class="designer-action-icon" aria-hidden="true">✎</span></button>
        <button type="button" class="designer-action-fab" data-flow-action="up" title="Move up" aria-label="Move up" ${readonly || selected.index <= 0 ? "disabled" : ""}><span class="designer-action-icon" aria-hidden="true">↑</span></button>
        <button type="button" class="designer-action-fab" data-flow-action="down" title="Move down" aria-label="Move down" ${readonly || selected.index >= selected.total - 1 ? "disabled" : ""}><span class="designer-action-icon" aria-hidden="true">↓</span></button>
        <button type="button" class="designer-action-fab designer-danger" data-flow-action="remove" title="Remove from flow" aria-label="Remove from flow" ${readonly ? "disabled" : ""}><span class="designer-action-icon" aria-hidden="true">×</span></button>
      </span>
    </div>`;
  aside.querySelector('[data-flow-action="toggle"]').onclick = () => { state.stepActionMenuExpanded = !state.stepActionMenuExpanded; renderVisualDesigner(); };
  aside.querySelector('[data-flow-action="edit"]').onclick = () => openStageEditor(selected.index);
  aside.querySelector('[data-flow-action="up"]').onclick = () => moveSelectedFlow(-1);
  aside.querySelector('[data-flow-action="down"]').onclick = () => moveSelectedFlow(1);
  aside.querySelector('[data-flow-action="remove"]').onclick = () => removeSelectedFlow();
  root.appendChild(aside);
}
function moveSelectedFlow(offset) {
  if (!state.studioGuard.editable || state.studioFile?.readonly) return; const flow = state.visual?.flow || []; const index = state.selectedFlowIndex; const target = index + offset;
  if (index < 0 || target < 0 || target >= flow.length) return;
  const [item] = flow.splice(index, 1); flow.splice(target, 0, item); state.selectedFlowIndex = target; state.visualDirty = true; renderVisualDesigner(); updateDirtyState();
}
async function removeSelectedFlow() {
  if (!state.studioGuard.editable || state.studioFile?.readonly) return; const flow = state.visual?.flow || []; const index = state.selectedFlowIndex;
  if (index < 0 || index >= flow.length) return; const name = flowStageName(flow[index]) || "Stage";
  if (!(await confirmDialog({ title: "Remove Stage from Flow?", message: `Remove ${name} from this Workflow flow? The Stage definition is kept in YAML.`, confirmLabel: "Remove Stage", danger: true }))) return;
  flow.splice(index, 1); state.selectedFlowIndex = flow.length ? Math.min(index, flow.length - 1) : -1; state.visualDirty = true; renderVisualDesigner(); updateDirtyState(); showToast(`${name} removed from flow`);
}
async function saveVisualFlow() {
  if (!state.studioFile || state.studioFile.kind !== "workflow" || !state.visualDirty || !state.studioGuard.editable) return true;
  try {
    const data = await api("/api/studio/visual/save", { method: "POST", body: JSON.stringify({ id: state.studioFile.id, project: state.project?.path || "", flow: state.visual.flow, hash: state.studioHash }) });
    state.studioFile = data; state.studioOriginal = data.content; state.studioHash = data.hash; state.studioDirty = false; state.visualDirty = false; $("studioTextarea").value = data.content; state.visual = await api(`/api/studio/visual?id=${encodeURIComponent(data.id)}${projectQuery()}`); renderVisualDesigner(); updateLineNumbers(); updateDirtyState(); setStudioStatus("Saved"); showToast("Workflow saved"); return true;
  } catch (error) { setStudioStatus(error.message, true); showActionError(error.message, "Workflow save failed"); return false; }
}

// ------------------------------ Prompt Editor ------------------------------
async function refreshPromptTags() {
  try { const data = await api("/api/studio/prompt-tags"); state.promptTags = data.tags || []; renderPromptTags(); }
  catch (_) { state.promptTags = []; renderPromptTags(); }
}
function renderPromptTags() {
  const root = $("studioPromptParamList"); if (!root) return; root.innerHTML = "";
  for (const tag of state.promptTags || []) {
    const button = document.createElement("button"); button.type = "button"; button.className = "designer-param-chip"; button.dataset.param = tag.key; button.textContent = `{{${tag.key}}}`; button.title = tag.description || tag.key; button.disabled = !state.studioGuard.editable || state.studioFile?.kind !== "prompt"; button.onclick = () => insertPromptTag(tag.key); root.appendChild(button);
  }
}
function insertPromptTag(key) {
  const ta = $("studioPromptTextarea"); if (!ta || ta.readOnly) return; const token = `{{${key}}}`; const start = ta.selectionStart, end = ta.selectionEnd; ta.setRangeText(token, start, end, "end"); ta.focus(); ta.dispatchEvent(new Event("input"));
}
function promptDiagnostics(result) {
  const target = $("studioPromptDiagnostics"), badge = $("promptSyntaxBadge"); if (!target || !badge) return;
  if (!result) { target.textContent = ""; target.hidden = true; badge.className = "studio-syntax-badge neutral"; badge.textContent = "Jinja"; return; }
  badge.className = `studio-syntax-badge ${result.ok ? "valid" : "invalid"}`; badge.textContent = result.ok ? "Prompt valid" : (result.line ? `Jinja line ${result.line}` : "Prompt warning");
  target.hidden = !!result.ok; target.innerHTML = result.ok ? "" : `<span class="designer-template-warning">${escapeHtml(result.summary || "Prompt validation failed")}</span>`;
}
async function checkPromptSyntax() {
  if (state.studioFile?.kind !== "prompt") return;
  try { const result = await api("/api/studio/prompt/check", { method: "POST", body: JSON.stringify({ id: state.studioFile.id, project: state.project?.path || "", content: $("studioPromptTextarea").value }) }); promptDiagnostics(result); }
  catch (error) { promptDiagnostics({ ok: false, summary: error.message }); }
}

// ------------------------------ Stage Editor ------------------------------
function fieldValue(id) { return $(id)?.value ?? ""; }
function checked(id) { return Boolean($(id)?.checked); }
function stageTypesOptions(selected) { return ["base", "task", "review", "plan", "ai_validator", "command"].map((v) => `<option value="${v}" ${v === selected ? "selected" : ""}>${v}</option>`).join(""); }
function parserOptions(selected) { return [["", "Stage default"], ["review", "review"], ["validation", "validation"]].map(([value, label]) => `<option value="${value}" ${value === (selected || "") ? "selected" : ""}>${label}</option>`).join(""); }
function flowStageOptions(selected) {
  const max = Math.max(0, state.selectedFlowIndex); const seen = new Set(); const rows = ['<option value="">None</option>'];
  for (const item of (state.visual?.flow || []).slice(0, max + 1)) { const name = flowStageName(item); if (!name || seen.has(name)) continue; seen.add(name); rows.push(`<option value="${escapeHtml(name)}" ${name === selected ? "selected" : ""}>${escapeHtml(name)}</option>`); }
  return rows.join("");
}
function pathWithSlashes(value) { return String(value || "").replaceAll("\\", "/").replace(/^\.\//, ""); }
function promptRef(item) {
  const original = pathWithSlashes(item.path); const lowered = original.toLowerCase();
  if (item.scope === "system") { const marker = "/runner/prompts/"; const at = lowered.lastIndexOf(marker); if (at >= 0) return original.slice(at + marker.length); }
  if (item.scope === "custom") { const marker = "/runner/prompts/custom/"; const at = lowered.lastIndexOf(marker); if (at >= 0) return `custom/${original.slice(at + marker.length)}`; }
  if (item.scope === "project") { const marker = "/prompts/"; const at = lowered.lastIndexOf(marker); if (at >= 0) return `prompts/${original.slice(at + marker.length)}`; }
  return item.name;
}
function promptOptionRows(current) {
  const rows = [`<option value="">No prompt</option>`]; let matched = !current;
  for (const item of state.studioFiles.prompts || []) {
    const ref = promptRef(item); const selected = normalizedPath(ref) === normalizedPath(current) || normalizedPath(item.path).endsWith(normalizedPath(current)); matched ||= selected;
    rows.push(`<option value="${escapeHtml(ref)}" ${selected ? "selected" : ""}>${escapeHtml(item.scope)} · ${escapeHtml(item.name)}</option>`);
  }
  if (current && !matched) rows.push(`<option value="${escapeHtml(current)}" selected>Current · ${escapeHtml(current)}</option>`);
  return rows.join("");
}
function stageSupportsPrompt(type) { return ["base", "task", "review", "ai_validator"].includes(type); }
function stageSupportsParser(type) { return !["command", "plan"].includes(type); }
function currentStageModal() { return document.querySelector(".designer-step-modal-box"); }
function markStageEditorDirty() { state.stageEditorDirty = true; }
async function openStageEditor(index = state.selectedFlowIndex) {
  if (!state.visual?.flow?.length || index < 0) return;
  if (currentStageModal() && !closeStageEditor()) return;
  if (state.visualDirty && !(await saveVisualFlow())) return;
  state.selectedFlowIndex = index; state.stageEditorDirty = false;
  const item = state.visual.flow[index], name = flowStageName(item), cfg = stageConfig(name), total = state.visual.flow.length;
  const box = document.createElement("div"); box.className = "designer-export-box designer-step-modal-box";
  box.innerHTML = `
    <div class="designer-export-card designer-step-modal-card" role="dialog" aria-modal="true" aria-labelledby="designerStepModalTitle">
      <div class="designer-step-modal-head">
        <div class="designer-step-modal-title-wrap">
          <div class="designer-step-modal-title-line"><h2 id="designerStepModalTitle">${escapeHtml(name || "Stage Settings")}</h2><span class="designer-step-type">${escapeHtml(cfg.type || "base")}</span></div>
          <p class="designer-form-hint">Stage ${index + 1} / ${total} · Prompt content (when supported) is edited from the Prompt workspace.</p>
        </div>
        <div class="designer-step-modal-tools">
          <div class="designer-step-modal-nav"><button type="button" data-stage-prev>← Prev</button><span data-stage-position>${index + 1} / ${total}</span><button type="button" data-stage-next>Next →</button></div>
          <button type="button" class="stage-modal-close" data-stage-close aria-label="Close">×</button>
        </div>
      </div>
      <div class="designer-tabs designer-step-modal-tabs studio-stage-tabs" role="tablist">
        <button type="button" class="designer-tab active" data-stage-tab="settings">Settings</button>
        <button type="button" class="designer-tab" data-stage-tab="control">Control</button>
      </div>
      <div class="designer-step-settings designer-step-modal-settings">
        <div data-stage-panel="settings" class="designer-form-grid"></div>
        <div data-stage-panel="control" hidden class="designer-form-grid"></div>
      </div>
      <div class="designer-footer-actions designer-step-modal-footer">
        <div class="designer-step-modal-footer-nav"><button type="button" data-stage-prev>← Previous Stage</button><button type="button" data-stage-next>Next Stage →</button></div>
        <span id="stageEditorStatus" class="designer-form-hint"></span>
        <div class="stage-modal-save-actions"><button id="validateStageButton" type="button">Validate Draft</button><button type="button" data-stage-close>Cancel</button><button id="saveStageButton" class="primary" type="button">Save Changes</button></div>
      </div>
    </div>`;
  document.body.appendChild(box); renderStageEditorContent(cfg, item);
  box.querySelectorAll("[data-stage-close]").forEach((b) => b.onclick = () => closeStageEditor());
  box.querySelectorAll("[data-stage-prev]").forEach((b) => { b.disabled = index <= 0; b.onclick = () => openStageEditor(index - 1); });
  box.querySelectorAll("[data-stage-next]").forEach((b) => { b.disabled = index >= total - 1; b.onclick = () => openStageEditor(index + 1); });
  box.querySelectorAll("[data-stage-tab]").forEach((b) => b.onclick = () => activateStageTab(b.dataset.stageTab));
  box.addEventListener("input", markStageEditorDirty); box.addEventListener("change", markStageEditorDirty); box.addEventListener("click", (e) => { if (e.target === box) closeStageEditor(); });
  $("validateStageButton").disabled = !state.studioGuard.editable || !!state.studioFile?.readonly; $("validateStageButton").onclick = () => validateStageEditor(index, name, cfg, item); $("saveStageButton").disabled = !state.studioGuard.editable || !!state.studioFile?.readonly; $("saveStageButton").onclick = () => saveStageEditor(index, name, cfg, item); syncStageTypeUi(cfg);
}
function activateStageTab(tab) {
  const box = currentStageModal(); if (!box) return;
  const target = box.querySelector(`[data-stage-tab="${tab}"]`); if (!target) tab = "settings";
  box.querySelectorAll("[data-stage-tab]").forEach((x) => x.classList.toggle("active", x.dataset.stageTab === tab)); box.querySelectorAll("[data-stage-panel]").forEach((x) => x.hidden = x.dataset.stagePanel !== tab);
}
function renderStageEditorContent(cfg, item) {
  const box = currentStageModal(); if (!box) return; const disabled = !state.studioGuard.editable ? "disabled" : "";
  const settings = box.querySelector('[data-stage-panel="settings"]');
  settings.innerHTML = `
    ${!state.studioGuard.editable ? '<div class="designer-warning-box"><strong>Read only</strong><span>Stop active Runtime before editing Workflow settings.</span></div>' : ''}
    <div class="stage-identity-strip"><span><strong>${escapeHtml(cfg.name)}</strong><small>Stage key</small></span><span><strong>${escapeHtml(cfg.type || "base")}</strong><small>Current type</small></span></div>
    <div class="stage-section-head"><div><strong>Stage</strong><span>常用設定優先；低頻 runtime overrides 收在 Advanced。</span></div></div>
    <div class="stage-form-two-col stage-primary-fields">
      <label class="designer-form-row"><span class="designer-label">Type</span><select id="stageType" class="designer-select" ${disabled}>${stageTypesOptions(cfg.type || "base")}</select></label>
      <label class="designer-form-row"><span class="designer-label">Status</span><input id="stageStatus" class="designer-input" value="${escapeHtml(item?.status ?? cfg.status ?? "")}" placeholder="User-facing runtime status" ${disabled} /></label>
      <label id="stagePromptSelectRow" class="designer-form-row stage-form-wide"><span class="designer-label">Prompt</span><select id="stagePromptSelect" class="designer-select" ${disabled}>${promptOptionRows(item?.prompt ?? cfg.prompt ?? "")}</select><span class="designer-form-hint">Prompt content is edited in Workflow Studio → Prompt. Continuation Prompt is an advanced YAML override and is intentionally not duplicated here.</span></label>
      <label class="designer-form-row"><span class="designer-label">Timeout (seconds)</span><input id="stageTimeout" class="designer-input" type="number" min="0" step="0.1" value="${cfg.timeout ?? ""}" placeholder="Stage default" ${disabled} /></label>
      <label class="designer-form-row"><span class="designer-label">Flow scope</span><select id="stageScope" class="designer-select" ${disabled}><option value="" ${!item?.scope ? "selected" : ""}>Workflow</option><option value="task" ${item?.scope === "task" ? "selected" : ""}>Per task</option></select></label>
      <label class="designer-form-row stage-form-wide"><span class="designer-label">Flow label</span><input id="stageFlowLabel" class="designer-input" value="${escapeHtml(item?.label || "")}" placeholder="Optional display / routing label" ${disabled} /></label>
      <label class="designer-form-row stage-form-wide"><span class="designer-label">Detail</span><textarea id="stageDetail" class="designer-textarea" rows="2" placeholder="Optional Stage detail / context" ${disabled}>${escapeHtml(cfg.detail || "")}</textarea></label>
    </div>
    <div id="stageTypeSpecific" class="stage-type-specific"></div>
    <details id="stageAdvancedOverrides" class="stage-advanced-overrides" ${hasAdvancedStageOverrides(cfg) ? "open" : ""}>
      <summary><span><strong>Advanced overrides</strong><small>Only use when the Stage type default is not enough.</small></span><span aria-hidden="true">⌄</span></summary>
      <div class="stage-form-two-col stage-advanced-grid">
        <label class="designer-form-row"><span class="designer-label">Run state</span><input id="stageRunState" class="designer-input" value="${escapeHtml(cfg.run_state || "")}" placeholder="Stage default" ${disabled} /></label>
        <label class="designer-form-row"><span class="designer-label">Actor</span><input id="stageActor" class="designer-input" value="${escapeHtml(cfg.actor || "")}" placeholder="Stage default" ${disabled} /></label>
        <label class="designer-form-row"><span class="designer-label">Mode</span><select id="stageMode" class="designer-select" ${disabled}><option value="" ${!cfg.mode ? "selected" : ""}>Stage default</option><option value="readonly" ${cfg.mode === "readonly" ? "selected" : ""}>readonly</option><option value="write" ${cfg.mode === "write" ? "selected" : ""}>write</option></select></label>
        <label id="stageParserRow" class="designer-form-row"><span class="designer-label">Parser</span><select id="stageParser" class="designer-select" ${disabled}>${parserOptions(cfg.parser)}</select></label>
        <label class="designer-form-row"><span class="designer-label">Produces</span><input id="stageProduces" class="designer-input" value="${escapeHtml(cfg.produces || "")}" placeholder="tasks" ${disabled} /></label>
        <label id="stageSessionKeyRow" class="designer-form-row"><span class="designer-label">Session key</span><input id="stageSessionKey" class="designer-input" value="${escapeHtml(cfg.session_key || "")}" placeholder="Optional session cache key" ${disabled} /></label>
        <label id="stageInstructionsRow" class="designer-form-row stage-form-wide"><span class="designer-label">Extra instructions</span><textarea id="stageInstructions" class="designer-textarea" rows="2" placeholder="Optional inline instructions" ${disabled}>${escapeHtml(cfg.instructions || "")}</textarea></label>
      </div>
    </details>`;

  const control = box.querySelector('[data-stage-panel="control"]');
  control.innerHTML = `
    <div class="stage-section-head"><div><strong>Flow routing</strong><span>These options apply only to this Flow invocation.</span></div></div>
    <div class="stage-form-two-col">
      <label class="designer-form-row"><span class="designer-label">Restart at</span><select id="stageRestartAt" class="designer-select" ${disabled}>${flowStageOptions(item?.restart_at || "")}</select></label>
      <label class="designer-form-row"><span class="designer-label">Repeat</span><input id="stageRepeat" class="designer-input" type="number" min="1" value="${item?.repeat ?? ""}" placeholder="No repeat" ${disabled} /></label>
      <label class="designer-form-row"><span class="designer-label">Fresh after same failures</span><input id="stageFreshAfterSameFailures" class="designer-input" type="number" min="1" value="${item?.fresh_after_same_failures ?? ""}" placeholder="Default recovery policy" ${disabled} /></label>
    </div>
    <div class="stage-section-head"><div><strong>Recovery & reliability</strong><span>Only explicit changes are written; empty defaults are not added to YAML.</span></div></div>
    <div class="stage-form-two-col">
      <label class="designer-form-row stage-form-wide"><span class="designer-label">Recover stages</span><input id="stageRecover" class="designer-input" value="${escapeHtml((cfg.recover || []).join(", "))}" placeholder="repair, repair_plan" ${disabled} /></label>
      <label class="designer-form-row"><span class="designer-label">Retry</span><input id="stageRetry" class="designer-input" type="number" min="-1" value="${cfg.retry ?? ""}" placeholder="Stage default" ${disabled} /><span class="designer-form-hint">-1 = keep retrying until PASS; 0 = no retry.</span></label>
      <label id="stageStructuredRetriesRow" class="designer-form-row"><span class="designer-label">Structured retries</span><input id="stageStructuredRetries" class="designer-input" type="number" min="0" value="${cfg.structured_retries ?? ""}" placeholder="Stage default" ${disabled} /></label>
      <label id="stageStructuredFreshRetriesRow" class="designer-form-row"><span class="designer-label">Structured fresh retries</span><input id="stageStructuredFreshRetries" class="designer-input" type="number" min="0" value="${cfg.structured_fresh_retries ?? ""}" placeholder="Stage default" ${disabled} /></label>
      <label id="stageCleanWorkRow" class="designer-form-row stage-form-wide"><span class="designer-label">Clean work paths</span><input id="stageCleanWork" class="designer-input" value="${escapeHtml((cfg.clean_work || []).join(", "))}" placeholder="validator-reports" ${disabled} /></label>
    </div>
    <div class="stage-switch-grid">
      ${switchRow("stageSkipOnError", "Skip on error", "Continue when the Stage itself errors.", cfg.skip_on_error, disabled)}
      <span id="stageFreshOnStartRow">${switchRow("stageFreshOnStart", "Fresh session on start", "Start this Stage in a new AI session.", cfg.fresh_session_on_start, disabled)}</span>
      <span id="stageFreshEachRunRow">${switchRow("stageFreshEachRun", "Fresh session each run", "Use a new session for every multi-run validation.", cfg.fresh_session_each_run, disabled)}</span>
      ${switchRow("stageTrackChanges", "Track changes", "Track project changes produced by this Stage.", cfg.track_changes, disabled)}
      ${switchRow("stageTolerateRestored", "Tolerate restored changes", "Allow restored readonly changes without failing the Stage.", cfg.tolerate_restored_changes, disabled)}
      <span id="stageAllowProjectReadRow">${switchRow("stageAllowProjectRead", "Allow project read", "Permit readonly AI stages to inspect project files.", cfg.allow_project_read, disabled)}</span>
    </div>`;

  $("stageType").addEventListener("change", () => { state.stageEditorDirty = true; renderTypeSpecific(cfg, disabled); syncStageTypeUi(cfg); }); renderTypeSpecific(cfg, disabled); syncStageTypeUi(cfg);
}
function hasAdvancedStageOverrides(cfg) { return ["run_state", "actor", "mode", "parser", "produces", "session_key", "instructions"].some((key) => cfg[key] !== undefined && cfg[key] !== ""); }
function switchRow(id, title, hint, value, disabled) { return `<label class="designer-switch-row"><input id="${id}" type="checkbox" ${value ? "checked" : ""} ${disabled} /><span><strong>${escapeHtml(title)}</strong><small>${escapeHtml(hint)}</small></span></label>`; }
function renderTypeSpecific(cfg, disabled) {
  const root = $("stageTypeSpecific"); if (!root) return; const type = $("stageType")?.value || cfg.type || "base"; const parts = [];
  if (type === "command") {
    parts.push(`<div class="stage-section-head"><div><strong>Command</strong><span>Command runtime settings.</span></div></div><div class="stage-form-two-col"><label class="designer-form-row stage-form-wide"><span class="designer-label">Command</span><textarea id="stageCommand" class="designer-textarea" rows="4" ${disabled}>${escapeHtml(Array.isArray(cfg.command) ? cfg.command.join(" ") : (cfg.command || ""))}</textarea></label><label class="designer-form-row"><span class="designer-label">Result kind</span><select id="stageResultKind" class="designer-select" ${disabled}><option value="" ${!cfg.result_kind ? "selected" : ""}>Stage default</option><option value="generic" ${cfg.result_kind === "generic" ? "selected" : ""}>generic</option><option value="validation" ${cfg.result_kind === "validation" ? "selected" : ""}>validation</option></select></label><label class="designer-form-row"><span class="designer-label">Working directory</span><input id="stageCwd" class="designer-input" value="${escapeHtml(cfg.cwd || "")}" placeholder="Project root" ${disabled} /></label></div>`);
  } else {
    if (type === "plan") parts.push(`<div class="stage-section-head"><div><strong>Plan</strong><span>Task-plan generation settings. Plan prompt is owned by the Plan Stage implementation.</span></div></div><div class="stage-form-two-col"><label class="designer-form-row"><span class="designer-label">Minimum tasks</span><input id="stageMinTasks" class="designer-input" type="number" min="1" value="${cfg.min_tasks ?? ""}" placeholder="Default" ${disabled} /></label>${switchRow("stageRepairPlan", "Repair plan", "Generate a repair-oriented TODO plan.", cfg.repair_plan, disabled)}</div>`);
    if (type === "ai_validator") parts.push(`<div class="stage-section-head"><div><strong>AI validation</strong><span>Fresh-session multi-run validation settings.</span></div></div><div class="stage-form-two-col"><label class="designer-form-row"><span class="designer-label">Validator</span><input id="stageValidator" class="designer-input" value="${escapeHtml(cfg.validator || "")}" placeholder="ai" ${disabled} /></label><label class="designer-form-row"><span class="designer-label">Runs</span><input id="stageRuns" class="designer-input" type="number" min="1" value="${cfg.runs ?? ""}" placeholder="Configured default" ${disabled} /></label><label class="designer-form-row"><span class="designer-label">Required passes</span><input id="stageRequiredPasses" class="designer-input" type="number" min="1" value="${cfg.required_passes ?? ""}" placeholder="Majority" ${disabled} /></label></div>`);
    else if (["base", "task", "review"].includes(type) && (cfg.runs !== undefined || cfg.required_passes !== undefined)) parts.push(`<div class="stage-section-head"><div><strong>Multi-run override</strong><span>Existing advanced multi-run configuration.</span></div></div><div class="stage-form-two-col"><label class="designer-form-row"><span class="designer-label">Runs</span><input id="stageRuns" class="designer-input" type="number" min="1" value="${cfg.runs ?? ""}" placeholder="Stage default" ${disabled} /></label><label class="designer-form-row"><span class="designer-label">Required passes</span><input id="stageRequiredPasses" class="designer-input" type="number" min="1" value="${cfg.required_passes ?? ""}" placeholder="Majority" ${disabled} /></label></div>`);
  }
  root.innerHTML = parts.join("");
}
function syncStageTypeUi(cfg) {
  const box = currentStageModal(); if (!box) return; const type = $("stageType")?.value || cfg.type || "base"; const promptAllowed = stageSupportsPrompt(type); const aiBacked = type !== "command";
  if ($("stagePromptSelectRow")) $("stagePromptSelectRow").hidden = !promptAllowed;
  const parserRow = $("stageParserRow"); if (parserRow) parserRow.hidden = !stageSupportsParser(type);
  if ($("stageSessionKeyRow")) $("stageSessionKeyRow").hidden = !aiBacked;
  if ($("stageInstructionsRow")) $("stageInstructionsRow").hidden = !promptAllowed;
  for (const id of ["stageStructuredRetriesRow", "stageStructuredFreshRetriesRow", "stageFreshOnStartRow", "stageFreshEachRunRow", "stageAllowProjectReadRow"]) if ($(id)) $(id).hidden = !aiBacked;
  if ($("stageCleanWorkRow")) $("stageCleanWorkRow").hidden = type !== "command";
  const chip = box.querySelector(".designer-step-type"); if (chip) chip.textContent = type;
}
function valueOrNull(id) { const value = fieldValue(id).trim(); return value === "" ? null : value; }
function numberOrNull(id) { const value = fieldValue(id).trim(); return value === "" ? null : Number(value); }
function listOrNull(id) { const values = fieldValue(id).split(",").map((x) => x.trim()).filter(Boolean); return values.length ? values : null; }
function changedFields(cfg, item) {
  const type = fieldValue("stageType"); const aiBacked = type !== "command"; const flowHasStatus = !!item && Object.prototype.hasOwnProperty.call(item, "status"); const flowHasPrompt = !!item && Object.prototype.hasOwnProperty.call(item, "prompt"); const candidates = {
    type, run_state: valueOrNull("stageRunState"), actor: valueOrNull("stageActor"), mode: valueOrNull("stageMode"), timeout: numberOrNull("stageTimeout"), produces: valueOrNull("stageProduces"), detail: valueOrNull("stageDetail"),
    recover: listOrNull("stageRecover"), retry: numberOrNull("stageRetry"), skip_on_error: checked("stageSkipOnError"), track_changes: checked("stageTrackChanges"), tolerate_restored_changes: checked("stageTolerateRestored"),
  };
  if (!flowHasStatus) candidates.status = valueOrNull("stageStatus");
  if (stageSupportsParser(type)) candidates.parser = valueOrNull("stageParser");
  if (aiBacked) {
    candidates.session_key = valueOrNull("stageSessionKey"); candidates.fresh_session_on_start = checked("stageFreshOnStart"); candidates.fresh_session_each_run = checked("stageFreshEachRun"); candidates.allow_project_read = checked("stageAllowProjectRead"); candidates.structured_retries = numberOrNull("stageStructuredRetries"); candidates.structured_fresh_retries = numberOrNull("stageStructuredFreshRetries");
    if (stageSupportsPrompt(type)) { if (!flowHasPrompt) candidates.prompt = valueOrNull("stagePromptSelect"); candidates.instructions = valueOrNull("stageInstructions"); }
    if ($("stageRuns")) candidates.runs = numberOrNull("stageRuns"); if ($("stageRequiredPasses")) candidates.required_passes = numberOrNull("stageRequiredPasses");
  }
  if (type === "command") { candidates.command = valueOrNull("stageCommand"); candidates.result_kind = valueOrNull("stageResultKind"); candidates.cwd = valueOrNull("stageCwd"); candidates.clean_work = listOrNull("stageCleanWork"); }
  if (type === "plan") { candidates.min_tasks = numberOrNull("stageMinTasks"); candidates.repair_plan = checked("stageRepairPlan"); }
  if (type === "ai_validator") candidates.validator = valueOrNull("stageValidator") || "ai";
  const booleanKeys = new Set(["skip_on_error", "fresh_session_on_start", "fresh_session_each_run", "track_changes", "tolerate_restored_changes", "allow_project_read", "repair_plan"]); const result = {};
  for (const [key, value] of Object.entries(candidates)) { if (booleanKeys.has(key) && cfg[key] === undefined && value === false) continue; const before = cfg[key] === undefined ? null : cfg[key]; if (JSON.stringify(before) !== JSON.stringify(value)) result[key] = value; }
  if (type !== "command" && cfg.type === "command") for (const key of ["command", "result_kind", "cwd", "clean_work"]) if (cfg[key] !== undefined) result[key] = null;
  if (type !== "plan" && cfg.type === "plan") for (const key of ["min_tasks", "repair_plan"]) if (cfg[key] !== undefined) result[key] = null;
  if (type !== "ai_validator" && cfg.type === "ai_validator" && cfg.validator !== undefined) result.validator = null;
  if (!aiBacked && cfg.type !== "command") for (const key of ["prompt", "continuation_prompt", "instructions", "session_key", "parser", "structured_retries", "structured_fresh_retries", "fresh_session_each_run", "fresh_session_on_start", "allow_project_read", "runs", "required_passes"]) if (cfg[key] !== undefined) result[key] = null;
  if (aiBacked && !stageSupportsPrompt(type) && stageSupportsPrompt(cfg.type)) for (const key of ["prompt", "continuation_prompt", "instructions"]) if (cfg[key] !== undefined) result[key] = null;
  return result;
}
function changedFlowFields(item) { const result = { label: valueOrNull("stageFlowLabel"), restart_at: valueOrNull("stageRestartAt"), repeat: numberOrNull("stageRepeat"), fresh_after_same_failures: numberOrNull("stageFreshAfterSameFailures") }; if (item && Object.prototype.hasOwnProperty.call(item, "status")) result.status = valueOrNull("stageStatus"); if (item && Object.prototype.hasOwnProperty.call(item, "prompt")) result.prompt = stageSupportsPrompt(fieldValue("stageType")) ? valueOrNull("stagePromptSelect") : null; return result; }
async function validateStageEditor(index, name, cfg, item) {
  if (!state.studioFile || !state.studioGuard.editable) return; const status = $("stageEditorStatus"); status.textContent = "Validating draft…"; status.classList.remove("error");
  try {
    const fields = changedFields(cfg, item); const scope = fieldValue("stageScope");
    const result = await api("/api/studio/stage/validate", { method: "POST", body: JSON.stringify({ id: state.studioFile.id, project: state.project?.path || "", stage: name, fields, flow_index: index, scope, flow_fields: changedFlowFields(item), hash: state.studioHash }) });
    status.textContent = result.summary || "Validation passed"; showToast("Workflow validation passed");
  } catch (error) { status.textContent = error.message; status.classList.add("error"); showActionError(error.message, "Workflow validation failed"); }
}
async function saveStageEditor(index, name, cfg, item) {
  if (!state.studioFile || !state.studioGuard.editable) return; const status = $("stageEditorStatus"); status.textContent = "Saving…"; status.classList.remove("error");
  try {
    const fields = changedFields(cfg, item); const scope = fieldValue("stageScope");
    const result = await api("/api/studio/stage/save", { method: "POST", body: JSON.stringify({ id: state.studioFile.id, project: state.project?.path || "", stage: name, fields, flow_index: index, scope, flow_fields: changedFlowFields(item), hash: state.studioHash }) });
    state.studioFile = result.file; state.studioOriginal = result.file.content; state.studioHash = result.file.hash; state.studioDirty = false; state.visualDirty = false; state.visual = result.visual; $("studioTextarea").value = result.file.content; updateLineNumbers(); renderVisualDesigner(); updateDirtyState(); setStudioStatus("Stage saved"); state.stageEditorDirty = false; status.textContent = "Saved";
    showToast("Stage saved");
    setTimeout(async () => { if (currentStageModal()) { closeStageEditor(true); await openStageEditor(index); const reopened = $("stageEditorStatus"); if (reopened) reopened.textContent = "Saved"; } }, 120);
  } catch (error) { status.textContent = error.message; status.classList.add("error"); showActionError(error.message, "Stage save failed"); }
}
function closeStageEditor(force = false) {
  if (!currentStageModal()) return true; if (!force && state.stageEditorDirty && !window.confirm("Discard unsaved Stage changes?")) return false; document.querySelectorAll(".designer-step-modal-box").forEach((node) => node.remove()); state.stageEditorDirty = false; return true;
}

// ------------------------------ Add Stage modal ------------------------------
function fillAddStagePromptOptions() { const select = $("addStagePrompt"); if (!select) return; const current = select.value; select.innerHTML = promptOptionRows(current); }
async function openAddStageModal() {
  if (!state.studioFile || state.studioFile.kind !== "workflow") return setStudioStatus("Select a Workflow first.", true);
  if (!state.studioGuard.editable) return setStudioStatus("Stop active Runtime before editing Workflow.", true);
  if (state.visualDirty && !(await saveVisualFlow())) return;
  state.addStageDirty = false; $("addStageName").value = ""; $("addStageType").value = "task"; $("addStageStatus").value = ""; $("addStageCommand").value = ""; $("addStageToFlow").checked = true; $("addStageHint").textContent = ""; $("addStageHint").classList.remove("error"); fillAddStagePromptOptions(); updateAddStageType(); $("addStageBackdrop").hidden = false; setTimeout(() => $("addStageName").focus(), 0);
}
function closeAddStageModal(force = false) {
  if ($("addStageBackdrop").hidden) return true;
  if (!force && state.addStageDirty && !window.confirm("Discard this new Stage?")) return false;
  $("addStageBackdrop").hidden = true; state.addStageDirty = false; return true;
}
function updateAddStageType() {
  const type = $("addStageType").value, command = type === "command"; $("addStageCommandRow").hidden = !command; $("addStagePromptRow").hidden = !stageSupportsPrompt(type);
  const help = { task: "Execute one task with the configured prompt.", review: "Review the current result and return PASS / FAIL.", plan: "Generate the task plan used by the workflow.", ai_validator: "Run final AI validation, optionally multiple fresh sessions.", command: "Run an external command or validation process.", base: "Generic AI / executor Stage with explicit settings." };
  if ($("addStageTypeBadge")) $("addStageTypeBadge").textContent = type; if ($("addStageTypeHelp")) $("addStageTypeHelp").textContent = help[type] || "Workflow stage";
}
async function confirmAddStage() {
  const name = $("addStageName").value.trim(); if (!name) { $("addStageHint").textContent = "Stage key is required."; $("addStageHint").classList.add("error"); return; }
  try {
    const result = await api("/api/studio/stage/add", { method: "POST", body: JSON.stringify({ id: state.studioFile.id, project: state.project?.path || "", stage: name, type: $("addStageType").value, status: $("addStageStatus").value.trim(), prompt: stageSupportsPrompt($("addStageType").value) ? $("addStagePrompt").value : "", command: $("addStageCommand").value.trim(), add_to_flow: $("addStageToFlow").checked, hash: state.studioHash }) });
    state.studioFile = result.file; state.studioOriginal = result.file.content; state.studioHash = result.file.hash; state.studioDirty = false; state.visualDirty = false; state.visual = result.visual; $("studioTextarea").value = result.file.content; updateLineNumbers(); renderVisualDesigner(); updateDirtyState(); state.addStageDirty = false; closeAddStageModal(true); setStudioStatus(`Stage ${name} added`); showToast(`Stage ${name} added`);
    const index = (state.visual.flow || []).findIndex((x) => flowStageName(x) === name); if (index >= 0) await openStageEditor(index);
  } catch (error) { $("addStageHint").textContent = error.message; $("addStageHint").classList.add("error"); showActionError(error.message, "Add Stage failed"); }
}

// ------------------------------ YAML / Prompt editor ------------------------------
function updateLineNumbers() { const ta = $("studioTextarea"), lines = Math.max(1, ta.value.split("\n").length); $("studioLineNumbers").textContent = Array.from({ length: lines }, (_, i) => i + 1).join("\n"); }
function handleEditorKeydown(event) {
  const ta = event.currentTarget;
  if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "s") { event.preventDefault(); saveStudio(); return; }
  if (event.key === "Tab") {
    event.preventDefault(); const start = ta.selectionStart, end = ta.selectionEnd; const value = ta.value; const first = value.lastIndexOf("\n", start - 1) + 1; const lastBreak = value.indexOf("\n", end); const last = lastBreak < 0 ? value.length : lastBreak;
    if (start !== end) { const block = value.slice(first, last); const lines = block.split("\n"); const changed = event.shiftKey ? lines.map((line) => line.replace(/^ {1,2}/, "")).join("\n") : lines.map((line) => `  ${line}`).join("\n"); ta.setRangeText(changed, first, last, "select"); }
    else if (event.shiftKey) { const removable = value.slice(first, Math.min(first + 2, value.length)).match(/^ {1,2}/)?.[0].length || 0; ta.setRangeText("", first, first + removable, "end"); }
    else ta.setRangeText("  ", start, end, "end"); ta.dispatchEvent(new Event("input")); return;
  }
  if (event.key === "Enter" && !event.shiftKey) {
    const pos = ta.selectionStart; const lineStart = ta.value.lastIndexOf("\n", pos - 1) + 1; const before = ta.value.slice(lineStart, pos); const indent = before.match(/^\s*/)?.[0] || ""; const trimmed = before.trim(); let next = indent; if (trimmed.endsWith(":")) next += "  "; else if (/^-\s+\S/.test(trimmed)) next += "- "; event.preventDefault(); ta.setRangeText(`\n${next}`, pos, ta.selectionEnd, "end"); ta.dispatchEvent(new Event("input"));
  }
}
function handlePromptEditorKeydown(event) { if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "s") { event.preventDefault(); saveStudio(); } }
function currentEditorContent() { return state.studioFile?.kind === "prompt" ? $("studioPromptTextarea").value : $("studioTextarea").value; }
function scheduleSyntaxCheck() {
  clearTimeout(state.syntaxTimer); const badge = $("syntaxBadge");
  if (!state.studioFile) { badge.hidden = true; promptDiagnostics(null); return; }
  if (state.studioFile.kind === "prompt") { badge.hidden = true; state.syntaxTimer = setTimeout(checkPromptSyntax, 320); return; }
  promptDiagnostics(null);
  if (state.studioMode !== "yaml") { badge.hidden = true; return; }
  $("editorLanguage").textContent = "YAML"; state.syntaxTimer = setTimeout(checkYamlSyntax, 320);
}
async function checkYamlSyntax() {
  if (!state.studioFile || state.studioFile.kind !== "workflow" || state.studioMode !== "yaml") return; const badge = $("syntaxBadge");
  try { const result = await api("/api/studio/check", { method: "POST", body: JSON.stringify({ id: state.studioFile.id, project: state.project?.path || "", content: $("studioTextarea").value }) }); badge.hidden = false; badge.className = `studio-syntax-badge ${result.ok ? "valid" : "invalid"}`; badge.textContent = result.ok ? "YAML valid" : `YAML ${result.line || "?"}:${result.column || "?"}`; badge.title = result.summary || ""; }
  catch (error) { badge.hidden = false; badge.className = "studio-syntax-badge invalid"; badge.textContent = "YAML check failed"; badge.title = error.message; }
}
function updateDirtyState() {
  state.studioDirty = !!state.studioFile && currentEditorContent() !== state.studioOriginal; const dirty = state.studioDirty || state.visualDirty || state.stageEditorDirty; $("dirtyBadge").hidden = !dirty;
  const locked = !state.studioGuard.editable || !!state.studioFile?.readonly; $("studioTextarea").readOnly = locked; $("studioPromptTextarea").readOnly = locked; renderPromptTags();
  const saveNeeded = state.studioFile?.kind === "prompt" ? state.studioDirty : (state.studioMode === "visual" ? state.visualDirty : state.studioDirty);
  $("saveStudioButton").disabled = locked || !saveNeeded; $("validateStudioButton").hidden = state.studioFile?.kind === "prompt"; $("validateStudioButton").disabled = !state.studioFile || state.studioFile.kind !== "workflow"; $("addFlowStepButton").disabled = locked || !state.studioFile || state.studioFile.kind !== "workflow";
  $("newWorkflowButton").disabled = !state.studioGuard.editable; $("importAssetButton").disabled = !state.studioGuard.editable;
  $("exportStudioButton").disabled = !state.studioFile; $("deleteStudioButton").hidden = !state.studioFile || !!state.studioFile.readonly; $("deleteStudioButton").disabled = !state.studioGuard.editable || !state.studioFile?.deletable;
}
function renderStudioGuard() {
  const guard = state.studioGuard || { editable: true, active_projects: [] }, badge = $("studioLockBadge"), banner = $("studioLockBanner"); badge.className = "runtime-badge";
  if (guard.editable) { badge.textContent = "Editable"; badge.classList.add("completed"); banner.hidden = true; }
  else { badge.textContent = "Read only"; badge.classList.add("interrupted"); const names = (guard.active_projects || []).map((p) => `${p.name}${p.pid ? ` (PID ${p.pid})` : ""}`).join(", "); banner.textContent = `Workflow editing locked while runtime is active: ${names || "active project"}`; banner.hidden = false; }
  updateDirtyState(); renderVisualDesigner(); applyStudioGuardToDialogs();
}
function applyStudioGuardToDialogs() {
  const locked = !state.studioGuard.editable || !!state.studioFile?.readonly, box = currentStageModal();
  if (box) { box.querySelectorAll('[data-stage-panel] input:not(#stageKey), [data-stage-panel] select, [data-stage-panel] textarea').forEach((node) => { node.disabled = locked; }); if ($("saveStageButton")) $("saveStageButton").disabled = locked; if (locked && $("stageEditorStatus")) $("stageEditorStatus").textContent = "Read only while a Runtime is active."; else if (!locked && $("stageEditorStatus")?.textContent.startsWith("Read only")) $("stageEditorStatus").textContent = ""; }
  if (!$("addStageBackdrop").hidden) { $("addStageBackdrop").querySelectorAll('input, select, textarea').forEach((node) => { node.disabled = locked; }); $("addStageConfirm").disabled = locked; if (locked) $("addStageHint").textContent = "Runtime started; Stage creation is temporarily read only."; else if ($("addStageHint").textContent.startsWith("Runtime started")) $("addStageHint").textContent = ""; }
  if (!$("newWorkflowBackdrop").hidden) { $("newWorkflowBackdrop").querySelectorAll('input, select').forEach((node) => { node.disabled = locked; }); $("newWorkflowConfirm").disabled = locked; }
  if (!$("generateWorkflowBackdrop").hidden) { $("generateWorkflowBackdrop").querySelectorAll('input, select, textarea').forEach((node) => { node.disabled = locked; }); $("generateWorkflowConfirm").disabled = locked; if (locked) { $("generateWorkflowHint").textContent = "Runtime started; Workflow generation is temporarily read only."; $("generateWorkflowHint").classList.add("error"); } }
}
async function refreshStudioGuard() { if (state.view !== "workflow") return; try { state.studioGuard = await api("/api/studio/guard"); renderStudioGuard(); } catch (_) {} }
async function saveStudio() {
  if (!state.studioFile || !state.studioGuard.editable) return;
  try {
    if (state.studioFile.kind === "workflow" && state.studioMode === "visual") return await saveVisualFlow(); if (!state.studioDirty) return;
    const content = currentEditorContent();
    if (state.studioFile.kind === "workflow") { const check = await api("/api/studio/check", { method: "POST", body: JSON.stringify({ id: state.studioFile.id, project: state.project?.path || "", content }) }); if (!check.ok) { const message = `YAML ${check.line || "?"}:${check.column || "?"} · ${check.summary}`; setStudioStatus(message, true); showActionError(message, "Workflow save failed"); return; } }
    else { const check = await api("/api/studio/prompt/check", { method: "POST", body: JSON.stringify({ id: state.studioFile.id, project: state.project?.path || "", content }) }); promptDiagnostics(check); if (!check.ok) { setStudioStatus(check.summary, true); showActionError(check.summary, "Prompt save failed"); return; } }
    const data = await api("/api/studio/save", { method: "POST", body: JSON.stringify({ id: state.studioFile.id, project: state.project?.path || "", content, hash: state.studioHash }) });
    state.studioFile = data; state.studioOriginal = data.content; state.studioHash = data.hash; state.studioDirty = false; state.visualDirty = false; if (data.kind === "workflow") { $("studioTextarea").value = data.content; state.visual = await api(`/api/studio/visual?id=${encodeURIComponent(data.id)}${projectQuery()}`); } else $("studioPromptTextarea").value = data.content; renderVisualDesigner(); updateDirtyState(); scheduleSyntaxCheck(); setStudioStatus("Saved"); showToast(data.kind === "prompt" ? "Prompt saved" : "Workflow saved");
  } catch (error) { setStudioStatus(error.message, true); showActionError(error.message, state.studioFile?.kind === "prompt" ? "Prompt save failed" : "Workflow save failed"); }
}
async function reloadStudio() { if (!state.studioFile || !confirmDiscardStudio()) return; await openStudioFile(state.studioFile); }
async function validateStudio() {
  if (!state.studioFile || state.studioFile.kind !== "workflow") return;
  const body = { id: state.studioFile.id, project: state.project?.path || "" };
  if (state.studioMode === "visual") body.flow = state.visual?.flow || []; else body.content = $("studioTextarea").value;
  try {
    setStudioStatus("Validating current draft…");
    const result = await api("/api/studio/validate", { method: "POST", body: JSON.stringify(body) });
    if (result.ok) { $("validationOutput").hidden = true; setStudioStatus(""); showToast("Workflow validation passed"); }
    else { $("validationOutput").hidden = false; $("validationOutput").textContent = result.output || result.summary; setStudioStatus(result.summary, true); showToast("Workflow validation failed", "error", 3200); }
  } catch (error) { setStudioStatus(error.message, true); showActionError(error.message, "Workflow validation failed"); }
}
function setStudioStatus(text, error = false) { $("studioStatus").textContent = text || ""; $("studioStatus").classList.toggle("error", !!error); }
function confirmDiscardStudio() { return !(state.studioDirty || state.visualDirty || state.stageEditorDirty) || window.confirm("You have unsaved Workflow / Stage / Prompt changes. Discard them?"); }

// ------------------------------ New Workflow / Prompt / Import / Export ------------------------------
function openNewWorkflowModal() {
  if (!state.studioGuard.editable) return setStudioStatus("Stop active Runtime before creating Workflow.", true);
  state.newWorkflowDirty = false; $("newWorkflowName").value = ""; $("newWorkflowDestination").value = "custom"; $("newWorkflowDestination").querySelector('option[value="project"]').disabled = !state.project; $("newWorkflowHint").textContent = ""; $("newWorkflowHint").classList.remove("error"); $("newWorkflowBackdrop").hidden = false; setTimeout(() => $("newWorkflowName").focus(), 0);
}
function closeNewWorkflowModal(force = false) { if ($("newWorkflowBackdrop").hidden) return true; if (!force && state.newWorkflowDirty && !window.confirm("Discard this new Workflow?")) return false; $("newWorkflowBackdrop").hidden = true; state.newWorkflowDirty = false; return true; }
async function confirmNewWorkflow() {
  const name = $("newWorkflowName").value.trim(); if (!name) { $("newWorkflowHint").textContent = "Workflow name is required."; $("newWorkflowHint").classList.add("error"); return; }
  try { const result = await api("/api/studio/workflow/create", { method: "POST", body: JSON.stringify({ project: state.project?.path || "", name, destination: $("newWorkflowDestination").value }) }); closeNewWorkflowModal(true); state.studioSourceKind = "workflow"; await refreshStudioFiles(); const item = (state.studioFiles.workflows || []).find((row) => row.id === result.item.id) || result.item; if (item) await openStudioFile(item); showToast(`Workflow ${result.file.name} created`); }
  catch (error) { $("newWorkflowHint").textContent = error.message; $("newWorkflowHint").classList.add("error"); showActionError(error.message, "Workflow creation failed"); }
}
function openNewPromptModal() {
  if (!state.studioGuard.editable) return setStudioStatus("Stop active Runtime before creating Prompt.", true);
  state.newPromptDirty = false; $("newPromptName").value = ""; $("newPromptDestination").value = "custom"; $("newPromptDestination").querySelector('option[value="project"]').disabled = !state.project; $("newPromptHint").textContent = ""; $("newPromptHint").classList.remove("error"); $("newPromptBackdrop").hidden = false; setTimeout(() => $("newPromptName").focus(), 0);
}
function closeNewPromptModal(force = false) { if ($("newPromptBackdrop").hidden) return true; if (!force && state.newPromptDirty && !window.confirm("Discard this new Prompt?")) return false; $("newPromptBackdrop").hidden = true; state.newPromptDirty = false; return true; }
async function confirmNewPrompt() {
  const name = $("newPromptName").value.trim(); if (!name) { $("newPromptHint").textContent = "Prompt name is required."; $("newPromptHint").classList.add("error"); return; }
  try { const result = await api("/api/studio/prompt/create", { method: "POST", body: JSON.stringify({ project: state.project?.path || "", name, destination: $("newPromptDestination").value }) }); closeNewPromptModal(true); state.studioSourceKind = "prompt"; await refreshStudioFiles(); const item = (state.studioFiles.prompts || []).find((row) => row.id === result.item.id) || result.item; if (item) await openStudioFile(item); showToast(`Prompt ${result.file.name} created`); }
  catch (error) { $("newPromptHint").textContent = error.message; $("newPromptHint").classList.add("error"); showActionError(error.message, "Prompt creation failed"); }
}
function openImportAssetModal() {
  if (!state.studioGuard.editable) return setStudioStatus("Stop active Runtime before importing.", true);
  const kind = state.studioSourceKind; state.importAssetDirty = false; $("importAssetTitle").textContent = `Import ${kind === "prompt" ? "Prompt" : "Workflow"}`; $("importAssetName").value = ""; $("importAssetContent").value = ""; $("importAssetFile").value = ""; $("importAssetFileName").textContent = "No file selected"; $("importAssetDestination").value = "custom"; $("importAssetDestination").querySelector('option[value="project"]').disabled = !state.project; $("importAssetHint").textContent = ""; $("importAssetHint").classList.remove("error"); $("importAssetPreview").textContent = "Choose a file or paste content."; $("importAssetBackdrop").hidden = false;
}
function closeImportAssetModal(force = false) { if ($("importAssetBackdrop").hidden) return true; if (!force && state.importAssetDirty && !window.confirm("Discard this import?")) return false; $("importAssetBackdrop").hidden = true; state.importAssetDirty = false; return true; }
function parseImportedText(text, fallbackName) {
  const trimmed = String(text || "").trim(); if (!trimmed) return { name: fallbackName || "", content: "" };
  try { const parsed = JSON.parse(trimmed); if (parsed && typeof parsed === "object" && ["workflow", "prompt"].includes(parsed.kind) && typeof parsed.content === "string") return { name: parsed.name || fallbackName || "", content: parsed.content, kind: parsed.kind }; } catch (_) {}
  return { name: fallbackName || "", content: text };
}
async function readImportAssetFile() {
  const file = $("importAssetFile").files?.[0]; if (!file) return; $("importAssetFileName").textContent = file.name; const text = await file.text(); const parsed = parseImportedText(text, file.name); $("importAssetName").value = parsed.name || file.name; $("importAssetContent").value = parsed.content; if (parsed.kind && parsed.kind !== state.studioSourceKind) $("importAssetHint").textContent = `Export package contains ${parsed.kind}; switch Workflow/Prompt source before importing.`; else $("importAssetHint").textContent = "File loaded. Import will validate Prompt references before writing."; state.importAssetDirty = true; $("importAssetPreview").textContent = `${(parsed.content || "").split("\n").length} lines ready to validate.`;
}
async function confirmImportAsset() {
  const parsed = parseImportedText($("importAssetContent").value, $("importAssetName").value.trim()); const kind = parsed.kind || state.studioSourceKind;
  if (kind !== state.studioSourceKind) { $("importAssetHint").textContent = `This package is ${kind}; switch Studio source first.`; $("importAssetHint").classList.add("error"); return; }
  try { const result = await api("/api/studio/import", { method: "POST", body: JSON.stringify({ project: state.project?.path || "", kind, name: parsed.name || $("importAssetName").value.trim(), content: parsed.content, destination: $("importAssetDestination").value }) }); closeImportAssetModal(true); await refreshStudioFiles(); const list = kind === "prompt" ? state.studioFiles.prompts : state.studioFiles.workflows; const item = (list || []).find((row) => row.id === result.item.id) || result.item; if (item) await openStudioFile(item); showToast(`${kind === "prompt" ? "Prompt" : "Workflow"} imported`); }
  catch (error) { $("importAssetHint").textContent = error.message; $("importAssetHint").classList.add("error"); $("importAssetPreview").textContent = error.message; showActionError(error.message, "Import failed"); }
}
async function exportStudioAsset() {
  if (!state.studioFile) return;
  try { const data = await api(`/api/studio/export?id=${encodeURIComponent(state.studioFile.id)}${projectQuery()}`); const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" }); const url = URL.createObjectURL(blob); const a = document.createElement("a"); a.href = url; a.download = `${data.name}.export.json`; document.body.appendChild(a); a.click(); a.remove(); URL.revokeObjectURL(url); showToast(`${data.kind === "prompt" ? "Prompt" : "Workflow"} exported`); }
  catch (error) { setStudioStatus(error.message, true); showActionError(error.message, "Export failed"); }
}
async function deleteStudioAsset() {
  if (!state.studioFile || state.studioFile.readonly) return; const current = state.studioFile; const label = current.kind === "prompt" ? "Prompt" : "Workflow";
  if (!(await confirmDialog({ title: `Delete ${label}?`, message: `Delete ${current.name}?${current.kind === "prompt" ? " Deletion is blocked if any Workflow Stage still uses this Prompt." : ""}`, confirmLabel: `Delete ${label}`, danger: true }))) return;
  try { await api("/api/studio/delete", { method: "POST", body: JSON.stringify({ id: current.id, project: state.project?.path || "" }) }); clearStudioEditor(); await refreshStudioFiles(); showToast(`${label} deleted`); }
  catch (error) { setStudioStatus(error.message, true); showActionError(error.message, `${label} deletion failed`); }
}


// ------------------------------ AI Workflow Builder modal ------------------------------
async function openGenerateWorkflowModal() {
  if (!state.project) return setStudioStatus("Open a Project before generating a Workflow.", true);
  if (!state.studioGuard.editable) return setStudioStatus("Stop active Runtime before generating a Workflow.", true);
  state.generateWorkflowDirty = false;
  $("generateWorkflowName").value = "";
  $("generateWorkflowDestination").value = "custom";
  $("generateWorkflowDestination").querySelector('option[value="project"]').disabled = !state.project;
  $("generateWorkflowRequest").value = "";
  $("generateWorkflowHint").textContent = "Checking System Workflow Builder…";
  $("generateWorkflowHint").classList.remove("error");
  try {
    const info = await api("/api/studio/draft");
    if (!info.available) throw new Error(info.message || "AI Workflow Builder is unavailable.");
    $("generateWorkflowHint").textContent = info.message || "AI Workflow Builder is ready.";
    $("generateWorkflowBackdrop").hidden = false;
    setTimeout(() => $("generateWorkflowName").focus(), 0);
  } catch (error) {
    $("generateWorkflowHint").textContent = error.message;
    $("generateWorkflowHint").classList.add("error");
    showToast(error.message, "error", 3200);
  }
}
function closeGenerateWorkflowModal(force = false) {
  if ($("generateWorkflowBackdrop").hidden) return true;
  if (!force && state.generateWorkflowDirty && !window.confirm("Discard this AI Workflow request?")) return false;
  $("generateWorkflowBackdrop").hidden = true;
  state.generateWorkflowDirty = false;
  return true;
}
async function confirmGenerateWorkflow() {
  const name = $("generateWorkflowName").value.trim();
  const request = $("generateWorkflowRequest").value.trim();
  if (!name) { $("generateWorkflowHint").textContent = "Workflow name is required."; $("generateWorkflowHint").classList.add("error"); return; }
  if (!request) { $("generateWorkflowHint").textContent = "Workflow requirements are required."; $("generateWorkflowHint").classList.add("error"); return; }
  $("generateWorkflowConfirm").disabled = true;
  $("generateWorkflowHint").classList.remove("error");
  $("generateWorkflowHint").textContent = "Starting System Workflow Builder…";
  try {
    const result = await api("/api/studio/generate", { method: "POST", body: JSON.stringify({
      project: state.project?.path || "",
      name,
      destination: $("generateWorkflowDestination").value,
      request,
      backend: $("backend").value,
    }) });
    closeGenerateWorkflowModal(true);
    showToast("Workflow Builder started. Publish occurs only after validation passes.", "success", 3200);
    setStudioStatus(result.message || "Workflow Builder started");
    setTimeout(refreshStudioFiles, 1500);
  } catch (error) {
    $("generateWorkflowHint").textContent = error.message;
    $("generateWorkflowHint").classList.add("error");
    showToast(error.message, "error", 3200);
  } finally {
    $("generateWorkflowConfirm").disabled = !state.studioGuard.editable;
  }
}

// ------------------------------ Add Project modal ------------------------------
function openProjectModal() { $("projectPathInput").value = ""; $("projectModalHint").textContent = "可直接貼上路徑，或使用 Browse 選擇資料夾。"; $("projectModalHint").classList.remove("error"); $("projectModalBackdrop").hidden = false; setTimeout(() => $("projectPathInput").focus(), 0); }
function closeProjectModal() { $("projectModalBackdrop").hidden = true; }
async function browseProject() {
  $("projectModalHint").textContent = "Opening folder picker…";
  try { const result = await api("/api/projects/pick", { method: "POST", body: "{}" }); if (!result.cancelled && result.path) { $("projectPathInput").value = result.path; $("projectModalHint").textContent = "Folder selected. Click Open Project to add it."; } else $("projectModalHint").textContent = "Folder selection cancelled."; }
  catch (error) { $("projectModalHint").textContent = `${error.message} · You can still paste the folder path.`; $("projectModalHint").classList.add("error"); }
}
async function confirmProjectModal() {
  const path = $("projectPathInput").value.trim(); if (!path) { $("projectModalHint").textContent = "Project path is required."; $("projectModalHint").classList.add("error"); return; }
  try { const added = await api("/api/projects/add", { method: "POST", body: JSON.stringify({ path }) }); closeProjectModal(); await loadProjects(); const picked = state.projects.find((p) => p.path === added.path); if (picked) await selectProject(picked); showToast("Project added"); }
  catch (error) { $("projectModalHint").textContent = error.message; $("projectModalHint").classList.add("error"); showActionError(error.message, "Add Project failed"); }
}

// ------------------------------ handlers ------------------------------
$("openProject").onclick = openProjectModal;
$("projectModalClose").onclick = closeProjectModal; $("projectModalCancel").onclick = closeProjectModal; $("projectModalConfirm").onclick = confirmProjectModal; $("browseProjectButton").onclick = browseProject; $("projectModalBackdrop").addEventListener("click", (e) => { if (e.target === $("projectModalBackdrop")) closeProjectModal(); });
$("projectPathInput").addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); confirmProjectModal(); } });
$("chatNav").onclick = () => switchView("chat"); $("workflowNav").onclick = () => switchView("workflow");
$("visualModeButton").onclick = () => setStudioMode("visual"); $("yamlModeButton").onclick = () => setStudioMode("yaml"); $("yamlWorkflowSource").onclick = () => setStudioSource("workflow"); $("yamlPromptSource").onclick = () => setStudioSource("prompt");
$("studioTextarea").addEventListener("input", () => { updateLineNumbers(); updateDirtyState(); scheduleSyntaxCheck(); }); $("studioTextarea").addEventListener("keydown", handleEditorKeydown); $("studioTextarea").addEventListener("scroll", () => { $("studioLineNumbers").scrollTop = $("studioTextarea").scrollTop; });
$("studioPromptTextarea").addEventListener("input", () => { updateDirtyState(); scheduleSyntaxCheck(); }); $("studioPromptTextarea").addEventListener("keydown", handlePromptEditorKeydown);
$("saveStudioButton").onclick = saveStudio; $("reloadStudioButton").onclick = reloadStudio; $("validateStudioButton").onclick = validateStudio; $("exportStudioButton").onclick = exportStudioAsset; $("deleteStudioButton").onclick = deleteStudioAsset; $("importAssetButton").onclick = openImportAssetModal; $("addFlowStepButton").onclick = openAddStageModal; $("newWorkflowButton").onclick = () => state.studioSourceKind === "prompt" ? openNewPromptModal() : openNewWorkflowModal();
$("newWorkflowClose").onclick = () => closeNewWorkflowModal(); $("newWorkflowCancel").onclick = () => closeNewWorkflowModal(); $("newWorkflowConfirm").onclick = confirmNewWorkflow; $("newWorkflowBackdrop").addEventListener("click", (e) => { if (e.target === $("newWorkflowBackdrop")) closeNewWorkflowModal(); }); $("newWorkflowBackdrop").addEventListener("input", () => { state.newWorkflowDirty = true; }); $("newWorkflowName").addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); confirmNewWorkflow(); } });
$("newPromptClose").onclick = () => closeNewPromptModal(); $("newPromptCancel").onclick = () => closeNewPromptModal(); $("newPromptConfirm").onclick = confirmNewPrompt; $("newPromptBackdrop").addEventListener("click", (e) => { if (e.target === $("newPromptBackdrop")) closeNewPromptModal(); }); $("newPromptBackdrop").addEventListener("input", () => { state.newPromptDirty = true; });
$("importAssetClose").onclick = () => closeImportAssetModal(); $("importAssetCancel").onclick = () => closeImportAssetModal(); $("importAssetConfirm").onclick = confirmImportAsset; $("importAssetChooseButton").onclick = () => $("importAssetFile").click(); $("importAssetFile").onchange = readImportAssetFile; $("importAssetBackdrop").addEventListener("click", (e) => { if (e.target === $("importAssetBackdrop")) closeImportAssetModal(); }); $("importAssetBackdrop").addEventListener("input", () => { state.importAssetDirty = true; });
$("addStageClose").onclick = () => closeAddStageModal(); $("addStageCancel").onclick = () => closeAddStageModal(); $("addStageConfirm").onclick = confirmAddStage; $("addStageType").onchange = () => { state.addStageDirty = true; updateAddStageType(); }; $("addStageBackdrop").addEventListener("click", (e) => { if (e.target === $("addStageBackdrop")) closeAddStageModal(); });
$("addStageBackdrop").addEventListener("input", (e) => { if (["INPUT", "TEXTAREA", "SELECT"].includes(e.target.tagName)) state.addStageDirty = true; });
$("generateWorkflowButton").onclick = openGenerateWorkflowModal; $("generateWorkflowClose").onclick = () => closeGenerateWorkflowModal(); $("generateWorkflowCancel").onclick = () => closeGenerateWorkflowModal(); $("generateWorkflowConfirm").onclick = confirmGenerateWorkflow; $("generateWorkflowBackdrop").addEventListener("click", (e) => { if (e.target === $("generateWorkflowBackdrop")) closeGenerateWorkflowModal(); }); $("generateWorkflowBackdrop").addEventListener("input", (e) => { if (["INPUT", "TEXTAREA", "SELECT"].includes(e.target.tagName)) state.generateWorkflowDirty = true; });
$("workflowDropdownButton").onclick = (event) => { event.stopPropagation(); const menu = $("workflowDropdownMenu"); menu.hidden ? openWorkflowDropdown() : closeWorkflowDropdown(); };
document.addEventListener("click", (event) => {
  const menu = $("workflowDropdownMenu"), picker = $("workflowPicker");
  if (!picker?.contains(event.target) && !menu?.contains(event.target)) closeWorkflowDropdown();
  if (!event.target.closest?.(".project-tree") && !event.target.closest?.(".project-action-menu")) closeProjectMenus();
});
$("optionsButton").onclick = () => { const open = $("optionsPanel").hidden; $("optionsPanel").hidden = !open; $("optionsButton").classList.toggle("active", open); $("optionsButton").setAttribute("aria-expanded", String(open)); requestAnimationFrame(syncComposerReserve); };
$("sendButton").onclick = sendMessage; $("messageInput").addEventListener("input", resizeComposerInput); $("messageInput").addEventListener("keydown", (event) => { if (event.key === "Enter" && !event.shiftKey) { event.preventDefault(); sendMessage(); } });
$("browseValidatorButton").onclick = browseValidator;
$("clearValidatorButton").onclick = () => { $("validator").value = ""; updateValidatorPicker(); };
$("stopButton").onclick = async () => { try { await api("/api/project/stop", { method: "POST", body: JSON.stringify(payload()) }); showToast("Stop requested"); setTimeout(refreshRuntime, 250); } catch (error) { $("errorText").textContent = error.message; showActionError(error.message, "Stop failed"); } };
$("resumeButton").onclick = async () => { try { await api("/api/project/resume", { method: "POST", body: JSON.stringify(payload()) }); showToast("Task continued"); setTimeout(refreshRuntime, 250); } catch (error) { $("errorText").textContent = error.message; showActionError(error.message, "Continue failed"); } };
$("resetButton").onclick = async () => {
  const completed = Boolean(state.runtime?.completed); const ok = await confirmDialog({ title: completed ? "Start New Task?" : "Reset stopped task?", message: completed ? "Clear old Runner runtime state and keep this Project task history?" : "Discard resumable Runner state? UI task history and request snapshots are kept.", confirmLabel: completed ? "New Task" : "Reset", danger: !completed }); if (!ok) return;
  try { await api("/api/project/reset", { method: "POST", body: JSON.stringify(payload()) }); state.lastStream = ""; removeLiveCard(); await refreshRuntime(); showToast(completed ? "Ready for a new task" : "Runtime reset"); } catch (error) { $("errorText").textContent = error.message; showActionError(error.message, "Reset failed"); }
};
$("rerunButton").onclick = async () => { try { await api("/api/project/rerun", { method: "POST", body: JSON.stringify(payload()) }); showToast("Task rerun started"); setTimeout(refreshRuntime, 250); } catch (error) { $("errorText").textContent = error.message; showActionError(error.message, "Rerun failed"); } };
window.addEventListener("keydown", (event) => { if (event.key !== "Escape") return; if (!$("workflowDropdownMenu").hidden) return closeWorkflowDropdown(); if (document.querySelector(".project-action-menu:not([hidden])")) return closeProjectMenus(); if (document.querySelector(".designer-step-modal-box")) return closeStageEditor(); if (!$("addStageBackdrop").hidden) return closeAddStageModal(); if (!$("importAssetBackdrop").hidden) return closeImportAssetModal(); if (!$("newPromptBackdrop").hidden) return closeNewPromptModal(); if (!$("newWorkflowBackdrop").hidden) return closeNewWorkflowModal(); if (!$("generateWorkflowBackdrop").hidden) return closeGenerateWorkflowModal(); if (!$("projectModalBackdrop").hidden) return closeProjectModal(); });
window.addEventListener("beforeunload", (event) => { if (state.studioDirty || state.visualDirty || state.stageEditorDirty) { event.preventDefault(); event.returnValue = ""; } });
showEmpty(); resizeComposerInput(); if (window.ResizeObserver) new ResizeObserver(syncComposerReserve).observe($("composePanel")); window.addEventListener("resize", () => {
  syncComposerReserve(); positionWorkflowDropdown();
  const menu = document.querySelector(".project-action-menu.project-action-menu-portal:not([hidden])"), owner = menu ? projectMenuOwners.get(menu) : null;
  if (menu && owner?.anchor) positionProjectMenu(menu, owner.anchor);
}); loadProjects(); refreshPromptTags(); setInterval(refreshRuntime, 750); setInterval(refreshStudioGuard, 1000);
