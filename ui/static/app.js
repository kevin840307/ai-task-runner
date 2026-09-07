const $ = (id) => document.getElementById(id);
const t = (key, fallback = "") => window.I18n?.t(key, fallback) ?? fallback ?? key;
const tf = (key, values = {}, fallback = "") => window.I18n?.format?.(key, values, fallback) ?? fallback ?? key;
const UI_PREFS_KEY = "ai-task-runner.ui.preferences.v1";
function loadUiPreferences() {
  try {
    const raw = JSON.parse(localStorage.getItem(UI_PREFS_KEY) || "{}");
    return raw && typeof raw === "object" ? { lastProject: String(raw.lastProject || ""), builderBackend: String(raw.builderBackend || ""), projects: raw.projects && typeof raw.projects === "object" ? raw.projects : {} } : { lastProject: "", builderBackend: "", projects: {} };
  } catch (_) { return { lastProject: "", builderBackend: "", projects: {} }; }
}
function saveUiPreferences() { try { localStorage.setItem(UI_PREFS_KEY, JSON.stringify(state.preferences || { lastProject: "", builderBackend: "", projects: {} })); } catch (_) {} }
function currentProjectPreferences() {
  if (!state.preferences) state.preferences = loadUiPreferences();
  const path = state.project?.path || ""; if (!path) return {};
  return state.preferences.projects[path] || (state.preferences.projects[path] = { backend: "", workflow: "", validators: {} });
}
function rememberProjectPreference(key, value) { const prefs = currentProjectPreferences(); if (!state.project) return; prefs[key] = value; saveUiPreferences(); }
function rememberValidator(workflow, value) { if (!state.project || !workflow) return; const prefs = currentProjectPreferences(); prefs.validators = prefs.validators && typeof prefs.validators === "object" ? prefs.validators : {}; prefs.validators[workflow] = value; saveUiPreferences(); }
const state = {
  projects: [], project: null, runtime: null, lastStream: "", lastRunId: "", spinnerFrame: 0, historyPinnedToBottom: true,
  backends: [], defaultBackend: "", preferences: null, validatorWorkflowPath: "",
  view: "chat",
  studioFiles: { workflows: [], prompts: [] }, studioFile: null,
  studioFilters: { workflow: "", prompt: "" },
  studioOriginal: "", studioHash: "", studioDirty: false,
  studioGuard: { editable: true, active_projects: [] }, studioMode: "visual", studioSourceKind: "workflow",
  visual: null, visualDirty: false, selectedFlowIndex: -1, stepActionMenuExpanded: false,
  promptTags: [], stageEditorDirty: false, addStageDirty: false, newWorkflowDirty: false, newPromptDirty: false, importAssetDirty: false,
  generateWorkflowDirty: false, generateWorkflowJobId: "", generateWorkflowPhase: "idle", generateWorkflowPollTimer: 0,
  generateWorkflowDraft: null, generateWorkflowPromptIndex: 0, generateWorkflowReviewTab: "visual", generateWorkflowRequestText: "",
  generateWorkflowWorkspace: "", generateWorkflowWorkspacePattern: "",
  syntaxTimer: 0,
  lastRuntimeSignature: "", runtimeLastChangedAt: 0, lastErrorDetail: "", studioErrorDetail: "", errorDetailsModalText: "", runtimeRefreshPromise: null, projectRefreshPromise: null, studioGuardRefreshPromise: null,
  studioFileCache: new Map(), studioOpenToken: 0, studioCatalogKey: "", studioCatalogLoadedAt: 0, studioFilesRefreshPromise: null,
};

const THEME_STORAGE_KEY = "ai-task-runner.theme";
const APPEARANCE_STORAGE_KEY = "ai-task-runner.appearance";
const THEME_VALUES = new Set(["teal", "blue", "violet", "amber", "rose"]);
const APPEARANCE_VALUES = new Set(["system", "light", "dark"]);
const systemColorScheme = window.matchMedia ? window.matchMedia("(prefers-color-scheme: dark)") : null;
function readThemePreference() { try { const value = localStorage.getItem(THEME_STORAGE_KEY); return THEME_VALUES.has(value) ? value : "teal"; } catch (_) { return "teal"; } }
function readAppearancePreference() { try { const value = localStorage.getItem(APPEARANCE_STORAGE_KEY); return APPEARANCE_VALUES.has(value) ? value : "system"; } catch (_) { return "system"; } }
function resolvedAppearance(preference) { return preference === "system" ? (systemColorScheme?.matches ? "dark" : "light") : preference; }
function applyThemePreferences(theme = readThemePreference(), appearance = readAppearancePreference(), { persist = false } = {}) {
  theme = THEME_VALUES.has(theme) ? theme : "teal"; appearance = APPEARANCE_VALUES.has(appearance) ? appearance : "system";
  document.documentElement.dataset.theme = theme; document.documentElement.dataset.appearancePreference = appearance; document.documentElement.dataset.appearance = resolvedAppearance(appearance);
  if (persist) { try { localStorage.setItem(THEME_STORAGE_KEY, theme); localStorage.setItem(APPEARANCE_STORAGE_KEY, appearance); } catch (_) {} }
  renderThemeControls();
}
function renderThemeControls() {
  const theme = document.documentElement.dataset.theme || "teal", appearance = document.documentElement.dataset.appearancePreference || "system";
  document.querySelectorAll("[data-theme-option]").forEach((button) => { const active = button.dataset.themeOption === theme; button.classList.toggle("active", active); button.setAttribute("aria-pressed", String(active)); });
  document.querySelectorAll("[data-appearance-option]").forEach((button) => { const active = button.dataset.appearanceOption === appearance; button.classList.toggle("active", active); button.setAttribute("aria-pressed", String(active)); });
  const language = window.I18n?.getLanguage?.() || "zh-TW";
  document.querySelectorAll("[data-language-option]").forEach((button) => { const active = button.dataset.languageOption === language; button.classList.toggle("active", active); button.setAttribute("aria-pressed", String(active)); });
}
function positionThemePanel() {
  const panel = $("themePanel"), button = $("themeButton"); if (!panel || !button || panel.hidden) return; const rect = button.getBoundingClientRect(), pad = 12, gap = 8;
  const width = panel.getBoundingClientRect().width || Math.min(320, window.innerWidth - pad * 2); let left = Math.max(pad, Math.min(rect.right - width, window.innerWidth - width - pad)); let top = rect.bottom + gap;
  const height = panel.getBoundingClientRect().height || 320; if (top + height > window.innerHeight - pad) top = Math.max(pad, rect.top - height - gap); panel.style.left = `${Math.round(left)}px`; panel.style.top = `${Math.round(top)}px`;
}
function closeThemePanel() { const panel = $("themePanel"), button = $("themeButton"); if (!panel || !button) return; panel.hidden = true; button.classList.remove("active"); button.setAttribute("aria-expanded", "false"); }
function toggleThemePanel(event) { event?.stopPropagation(); const panel = $("themePanel"), button = $("themeButton"); if (!panel || !button) return; const opening = panel.hidden; if (!opening) return closeThemePanel(); panel.hidden = false; button.classList.add("active"); button.setAttribute("aria-expanded", "true"); renderThemeControls(); requestAnimationFrame(positionThemePanel); }

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
function errorSummary(message, fallback = "Action failed") {
  const detail = String(message || "").trim(); const firstLine = detail.split(/\r?\n/).find((line) => line.trim())?.trim() || fallback;
  return firstLine.length > 180 ? `${firstLine.slice(0, 177)}...` : firstLine;
}
function rememberErrorDetail(message, fallback = "Action failed") {
  state.lastErrorDetail = String(message || fallback).trim() || fallback;
  for (const id of ["errorDetailsButton", "studioErrorDetailsButton"]) { const button = $(id); if (button) button.hidden = !state.lastErrorDetail; }
}
function openErrorDetailsModal(detail) {
  const text = String(detail || "").trim(); if (!text) return;
  state.errorDetailsModalText = text; $("errorDetailsContent").textContent = text; $("errorDetailsBackdrop").hidden = false;
}
function showErrorDetails() { openErrorDetailsModal(state.lastErrorDetail); }
function showStudioErrorDetails() { openErrorDetailsModal(state.studioErrorDetail); }
function closeErrorDetails() { $("errorDetailsBackdrop").hidden = true; state.errorDetailsModalText = ""; }
function showActionError(message, fallback = "Action failed") {
  const summary = errorSummary(message, fallback); rememberErrorDetail(message, fallback); showToast(summary, "error", 3200);
}
const confirmDialog = (options) => window.UiDialogs.confirm(options);
const inputDialog = (options) => window.UiDialogs.input(options);
const choiceDialog = (options) => window.UiDialogs.choice(options);

function syncComposerReserve() {
  const panel = $("composePanel"); if (!panel || panel.hidden) return;
  const reserve = Math.ceil(panel.getBoundingClientRect().height + 18);
  $("chatView")?.style.setProperty("--composer-reserve", `${reserve}px`);
}
function historyNearBottom(root = $("messages"), threshold = 96) {
  if (!root) return true;
  return root.scrollHeight - root.scrollTop - root.clientHeight <= threshold;
}
function followHistoryToBottom(force = false) {
  const root = $("messages"); if (!root) return;
  if (!force && !state.historyPinnedToBottom) return;
  requestAnimationFrame(() => {
    root.scrollTop = root.scrollHeight;
    state.historyPinnedToBottom = true;
  });
}

// ------------------------------ Projects / Chat ------------------------------
async function loadProjects() {
  const data = await api("/api/projects"); state.projects = data.projects || []; renderProjects();
  if (!state.project && state.projects.length) {
    const saved = state.preferences?.lastProject || "";
    const first = state.projects.find((p) => p.path === saved && p.exists !== false) || state.projects.find((p) => p.exists !== false);
    if (first) await selectProject(first);
  }
}

function pollDelay(visibleDelay, hiddenDelay) { return document.hidden ? hiddenDelay : visibleDelay; }
function startNonOverlappingPoll(fn, visibleDelay, hiddenDelay = visibleDelay) {
  let stopped = false, timer = 0;
  const schedule = () => { if (!stopped) timer = window.setTimeout(tick, pollDelay(visibleDelay, hiddenDelay)); };
  const tick = async () => {
    try { await fn(); } catch (_) {}
    finally { schedule(); }
  };
  schedule();
  return () => { stopped = true; if (timer) window.clearTimeout(timer); };
}

function projectRuntimeSignature(projects) { return (projects || []).map((p) => `${p.path}:${p.runtime_status || "idle"}:${p.exists !== false}`).join("|"); }
async function refreshProjectStatuses() {
  if (state.projectRefreshPromise) return state.projectRefreshPromise;
  state.projectRefreshPromise = (async () => {
    try {
      const data = await api("/api/projects"), next = data.projects || [];
      if (projectRuntimeSignature(next) === projectRuntimeSignature(state.projects)) return;
      state.projects = next;
      if (state.project) state.project = next.find((p) => p.path === state.project.path) || state.project;
      renderProjects();
    } catch (_) {}
    finally { state.projectRefreshPromise = null; }
  })();
  return state.projectRefreshPromise;
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
  const labels = { running: "RUN", completed: "DONE", interrupted: "INT", stopped: "STOP", idle: "IDLE", missing: "MISS" };
  for (const project of state.projects) {
    const runtimeStatus = project.exists === false ? "missing" : (project.runtime_status || "idle");
    const row = document.createElement("div"); row.className = `project-tree project-row runtime-${runtimeStatus}`;
    if (state.project?.path === project.path) row.classList.add("active");
    if (project.exists === false) row.classList.add("missing");
    const button = document.createElement("button"); button.className = "project-root"; button.type = "button";
    const mark = document.createElement("span"); mark.className = `project-mark runtime-${runtimeStatus}`; mark.title = runtimeStatus === "running" ? "Running" : runtimeStatus.charAt(0).toUpperCase() + runtimeStatus.slice(1);
    const copy = document.createElement("span"); copy.className = "project-copy";
    const nameLine = document.createElement("span"); nameLine.className = "project-name-line";
    const name = document.createElement("strong"); name.textContent = project.name;
    nameLine.appendChild(name);
    if (labels[runtimeStatus]) { const status = document.createElement("span"); status.className = `project-runtime-label runtime-${runtimeStatus}`; status.textContent = labels[runtimeStatus]; nameLine.appendChild(status); }
    const path = document.createElement("small"); path.textContent = project.exists === false ? `${t("project.missing", "Missing")} · ${project.path}` : project.path;
    copy.append(nameLine, path); button.append(mark, copy); button.onclick = () => project.exists === false ? null : selectProject(project);

    const menuButton = document.createElement("button"); menuButton.className = "project-menu-button"; menuButton.type = "button"; menuButton.title = t("project.actions", "Project actions"); menuButton.setAttribute("aria-label", `${t("project.actions", "Project actions")} · ${project.name}`); menuButton.innerHTML = "<span aria-hidden=\"true\"></span>";
    const menu = document.createElement("div"); menu.className = "project-action-menu"; menu.hidden = true;
    const remove = document.createElement("button"); remove.type = "button"; remove.className = "danger-text"; remove.textContent = t("project.remove", "Remove project");
    menu.appendChild(remove);
    menuButton.onclick = (event) => {
      event.stopPropagation(); const open = menu.hidden;
      if (open) openProjectMenu(menu, menuButton, row); else closeProjectMenus();
    };
    remove.onclick = async (event) => {
      event.stopPropagation();
      if (!(await confirmDiscardStudio())) return;
      const ok = await confirmDialog({ title: "Remove Project?", message: `Remove ${project.name} from this UI? Project files are not deleted.`, confirmLabel: "Remove Project", danger: true });
      if (!ok) return;
      closeStageEditor(true); closeAddStageModal(true); closeProjectMenus();
      try { await api("/api/projects/remove", { method: "POST", body: JSON.stringify({ path: project.path }) }); if (state.project?.path === project.path) { state.project = null; showEmpty(); } await loadProjects(); showToast("Project removed"); }
      catch (error) { showAppError(error.message); showActionError(error.message, "Remove Project failed"); }
    };
    row.append(button, menuButton, menu); root.appendChild(row);
  }
}
function showAppError(message) { rememberErrorDetail(message, "Error"); if (state.view === "workflow") setStudioStatus(message, true); else $("errorText").textContent = errorSummary(message, "Error"); }
function showEmpty() {
  $("projectName").textContent = "Select a project"; $("projectPath").textContent = "Open a local project folder to begin.";
  $("summary").hidden = true; $("messages").hidden = true; $("composePanel").hidden = true; $("emptyState").hidden = false;
}
async function selectProject(project) {
  state.lastRuntimeSignature = "";
  const changingProject = state.project?.path !== project.path;
  if (changingProject && state.studioFile?.scope === "project") {
    if ((state.studioDirty || state.visualDirty) && !(await confirmDiscardStudio())) return;
    clearStudioEditor();
  }
  if (state.view === "workflow" && !(await switchView("chat"))) return;
  state.project = project; state.runtime = null; state.lastStream = ""; state.historyPinnedToBottom = true; state.validatorWorkflowPath = ""; $("clearHistoryButton").disabled = true;
  if (!state.preferences) state.preferences = loadUiPreferences(); state.preferences.lastProject = project.path; saveUiPreferences();
  if ($("workflowSelect")) $("workflowSelect").innerHTML = ""; renderProjects(); renderBackendPicker();
  $("projectName").textContent = project.name; $("projectPath").textContent = project.path; $("emptyState").hidden = true;
  $("summary").hidden = false; $("messages").hidden = false; $("composePanel").hidden = false; $("errorText").textContent = ""; requestAnimationFrame(syncComposerReserve);
  await Promise.all([refreshMessages(), refreshRuntime(), refreshStudioFiles()]);
}
async function refreshMessages({ forceFollow = false } = {}) {
  if (!state.project) return;
  const root = $("messages");
  const shouldFollow = forceFollow || state.historyPinnedToBottom || historyNearBottom(root);
  const data = await api(`/api/project/messages?project=${encodeURIComponent(state.project.path)}`);
  const live = root.querySelector(".live-activity"); root.innerHTML = "";
  for (const message of data.messages || []) {
    const item = document.createElement("article"); item.className = `message ${message.role}`; item.dataset.role = message.role || "assistant";
    const body = document.createElement("div"); body.className = "message-body"; body.textContent = message.content || ""; item.appendChild(body); root.appendChild(item);
  }
  if (live) root.appendChild(live);
  if (shouldFollow) { state.historyPinnedToBottom = true; followHistoryToBottom(true); }
}
const CLI_SPINNER_FRAMES = ["•"];
function ensureLiveCard({ forceVisibleOnCreate = false } = {}) {
  const root = $("messages");
  let card = root.querySelector(".live-activity"); if (card) return card;
  card = document.createElement("article"); card.className = "live-activity cli-runtime-card";
  card.innerHTML = `<div class="live-activity-head"><span class="live-dot" aria-hidden="true"></span><strong class="live-title">CLI Runtime</strong><small class="live-progress">same runtime state</small><small class="live-updated">Last update —</small></div><pre class="cli-runtime-output"></pre>`;
  root.appendChild(card);
  if (forceVisibleOnCreate) { state.historyPinnedToBottom = true; followHistoryToBottom(true); }
  return card;
}
function removeLiveCard() { $("messages")?.querySelector(".live-activity")?.remove(); }
function cliRuntimeText(runtime) {
  const spinner = runtime.running ? CLI_SPINNER_FRAMES[state.spinnerFrame % CLI_SPINNER_FRAMES.length] : " ";
  const lines = Array.isArray(runtime.cli_lines) && runtime.cli_lines.length
    ? runtime.cli_lines
    : [`AI Task Runner  Cycle 1  Progress ${runtime.completed_count || 0}/${runtime.total || 0}`, "", `  {spinner} ${runtime.cli_status || runtime.stage || "準備中"}`];
  return lines.map((line) => String(line).replaceAll("{spinner}", spinner)).join("\n");
}
function setTextIfChanged(node, value) { if (node && node.textContent !== value) node.textContent = value; }
function renderCliRuntimeFrame() {
  const runtime = state.runtime, output = $("messages")?.querySelector(".cli-runtime-output");
  if (!runtime || !output) return;
  setTextIfChanged(output, cliRuntimeText(runtime));
}
function runtimeStatusLabel(runtime) {
  if (runtime?.running) return "Running";
  if (runtime?.stale && runtime?.resumable) return "Interrupted";
  if (runtime?.resumable) return "Stopped";
  if (runtime?.completed) return "Completed";
  return "Idle";
}
function renderLiveRuntimeHeader(runtime) {
  const card = $("messages")?.querySelector(".live-activity"); if (!card || !runtime) return;
  setTextIfChanged(card.querySelector(".live-title"), runtimeStatusLabel(runtime));
  setTextIfChanged(card.querySelector(".live-progress"), runtime.total ? `${runtime.completed_count || 0}/${runtime.total} TODO` : (runtime.console_snapshot_exists ? "CLI synced" : "State fallback")); updateRuntimeFreshness();
}
function animateRuntimeFrame() { if (!document.hidden) updateRuntimeFreshness(); }
function runtimeRenderSignature(runtime) {
  if (!runtime) return "";
  return JSON.stringify([runtime.running, runtime.stale, runtime.resumable, runtime.completed, runtime.run_id || "", runtime.cli_status || "", runtime.stage || "", runtime.completed_count || 0, runtime.total || 0, runtime.task || "", runtime.cli_detail || "", runtime.last_error || "", runtime.console_snapshot_exists || false, runtime.cli_lines || []]);
}
async function refreshRuntime() {
  if (!state.project) return;
  if (state.runtimeRefreshPromise) return state.runtimeRefreshPromise;
  state.runtimeRefreshPromise = (async () => {
    try {
      const runtime = await api(`/api/project/runtime?project=${encodeURIComponent(state.project.path)}`);
      state.runtime = runtime;
      const signature = runtimeRenderSignature(runtime);
      if (signature !== state.lastRuntimeSignature) { state.lastRuntimeSignature = signature; state.runtimeLastChangedAt = Date.now(); renderRuntime(runtime); }
    } catch (error) { setTextIfChanged($("errorText"), error.message); }
    finally { state.runtimeRefreshPromise = null; }
  })();
  return state.runtimeRefreshPromise;
}
function formatFreshness(ts) {
  if (!ts) return "—"; const seconds = Math.max(0, Math.floor((Date.now() - ts) / 1000));
  if (seconds < 5) return "just now"; if (seconds < 60) return `${seconds}s ago`; const minutes = Math.floor(seconds / 60); if (minutes < 60) return `${minutes}m ago`; return `${Math.floor(minutes / 60)}h ago`;
}
function updateRuntimeFreshness() {
  const text = formatFreshness(state.runtimeLastChangedAt); setTextIfChanged($("lastUpdateText"), text); const live = $("messages")?.querySelector(".live-updated"); setTextIfChanged(live, `Last update ${text}`);
  const stale = Boolean(state.runtime?.running && state.runtimeLastChangedAt && Date.now() - state.runtimeLastChangedAt > 30000); $("lastUpdateText")?.classList.toggle("stale", stale);
}
function renderRuntime(runtime) {
  updateRuntimeFreshness();
  const badge = $("statusBadge"); badge.className = "runtime-badge"; const label = runtimeStatusLabel(runtime);
  if (runtime.running) badge.classList.add("running");
  else if (runtime.stale && runtime.resumable) badge.classList.add("interrupted");
  else if (runtime.resumable) badge.classList.add("failed");
  else if (runtime.completed) badge.classList.add("completed");
  setTextIfChanged(badge, label); setTextIfChanged($("currentStage"), runtime.cli_status || runtime.stage || label); setTextIfChanged($("progressText"), runtime.total ? `${runtime.completed_count || 0} / ${runtime.total}` : "—"); setTextIfChanged($("currentTask"), runtime.task || runtime.cli_detail || (runtime.last_error || "Waiting"));
  $("clearHistoryButton").disabled = Boolean(runtime.running); $("clearHistoryButton").title = runtime.running ? "Stop the active task before clearing this chat history" : "Clear chat history";
  $("sendButton").hidden = runtime.running || runtime.resumable;
  $("stopButton").hidden = !runtime.running;
  $("resumeButton").hidden = runtime.running || !runtime.resumable;
  $("resetButton").hidden = runtime.running || !runtime.resumable;
  $("rerunButton").hidden = runtime.running || !runtime.completed || !hasUserMessage();
  const blockNew = runtime.running || runtime.resumable;
  $("sendButton").disabled = blockNew; $("messageInput").disabled = blockNew;
  $("messageInput").placeholder = "描述要完成的功能或修復內容...";
  if (runtime.running || runtime.resumable) {
    const card = ensureLiveCard({ forceVisibleOnCreate: true });
    card.classList.toggle("running", Boolean(runtime.running));
    renderLiveRuntimeHeader(runtime);
    renderCliRuntimeFrame();
    followHistoryToBottom();
  } else removeLiveCard();
  const current = state.projects.find((p) => p.path === state.project?.path);
  if (current) { const nextStatus = runtime.running ? "running" : runtime.completed ? "completed" : runtime.resumable ? (runtime.stale ? "interrupted" : "stopped") : "idle"; if (current.runtime_status !== nextStatus) { current.runtime_status = nextStatus; renderProjects(); } }
  if (runtime.completed && runtime.run_id && runtime.run_id !== state.lastRunId) { state.lastRunId = runtime.run_id; state.historyPinnedToBottom = true; refreshMessages({ forceFollow: true }); }
}
function hasUserMessage() { return $("messages")?.querySelector(".message.user") !== null; }
function resizeComposerInput() { const ta = $("messageInput"); if (!ta) return; ta.style.height = "60px"; syncComposerReserve(); }
async function sendMessage() {
  const text = $("messageInput").value.trim(); if (!text || !state.project) return; $("errorText").textContent = "";
  state.historyPinnedToBottom = true;
  try { await api("/api/project/message", { method: "POST", body: JSON.stringify(payload({ message: text })) }); $("messageInput").value = ""; resizeComposerInput(); await refreshMessages({ forceFollow: true }); showToast("Task started"); setTimeout(refreshRuntime, 250); }
  catch (error) { $("errorText").textContent = error.message; showActionError(error.message, "Task start failed"); }
}

async function refreshBackends() {
  try { const data = await api("/api/backends"); state.backends = Array.isArray(data.backends) ? data.backends : []; state.defaultBackend = String(data.default || ""); renderBackendPicker(); }
  catch (_) { state.backends = ["qwen", "opencode"]; state.defaultBackend = "qwen"; renderBackendPicker(); }
}
function closeBackendDropdown() {
  const menu = $("backendDropdownMenu"), picker = $("backendPicker"), button = $("backendDropdownButton"); if (!menu || !picker || !button) return;
  menu.hidden = true; menu.classList.remove("backend-dropdown-portal"); menu.removeAttribute("style"); if (menu.parentElement !== picker) picker.appendChild(menu); button.setAttribute("aria-expanded", "false");
}
function positionUpwardDropdown(menu, button, rowCount, widthExtra = 80) {
  if (!menu || !button || menu.hidden) return; const rect = button.getBoundingClientRect(), pad = 10, gap = 8;
  const width = Math.min(460, Math.max(220, Math.min(window.innerWidth - pad * 2, rect.width + widthExtra)));
  menu.style.width = `${width}px`; menu.style.left = `${Math.min(window.innerWidth - width - pad, Math.max(pad, rect.right - width))}px`; menu.style.right = "auto"; menu.style.top = "auto"; menu.style.bottom = `${Math.max(pad, window.innerHeight - rect.top + gap)}px`;
  const available = Math.max(120, rect.top - pad * 2); const rows = [...menu.children].slice(0, Math.min(5, rowCount));
  const fiveRowHeight = rows.reduce((sum, row) => sum + row.getBoundingClientRect().height, 0) + Math.max(0, rows.length - 1) * 4 + 12;
  const cap = rowCount > 5 ? Math.max(140, fiveRowHeight) : Math.max(100, menu.scrollHeight); menu.style.maxHeight = `${Math.min(available, cap)}px`; menu.classList.toggle("dropdown-scrollable", rowCount > 5 || menu.scrollHeight > available);
}
function openBackendDropdown() {
  const menu = $("backendDropdownMenu"), button = $("backendDropdownButton"); if (!menu || !button) return; closeWorkflowDropdown();
  if (menu.parentElement !== document.body) document.body.appendChild(menu); menu.classList.add("backend-dropdown-portal"); menu.hidden = false; button.setAttribute("aria-expanded", "true"); positionUpwardDropdown(menu, button, menu.children.length, 70);
}
function renderBackendPicker() {
  const select = $("backend"), menu = $("backendDropdownMenu"), label = $("backendSelectedLabel"); if (!select || !menu || !label) return;
  const prefs = currentProjectPreferences(); const saved = String(prefs.backend || ""); select.innerHTML = ""; menu.innerHTML = "";
  const rows = [{ value: "", label: state.defaultBackend ? `Default · ${state.defaultBackend}` : "Default backend", meta: "Runner default", badge: "DEFAULT" }, ...state.backends.map((name) => ({ value: name, label: name, meta: "AI backend", badge: "BACKEND" }))];
  for (const row of rows) {
    const option = document.createElement("option"); option.value = row.value; option.textContent = row.label; select.appendChild(option);
    const button = document.createElement("button"); button.type = "button"; button.className = "workflow-dropdown-option backend-dropdown-option"; button.setAttribute("role", "option");
    button.innerHTML = `<span class="workflow-option-main"><strong></strong><small></small></span><span class="workflow-option-badge"></span>`; button.querySelector("strong").textContent = row.label; button.querySelector("small").textContent = row.meta; button.querySelector(".workflow-option-badge").textContent = row.badge;
    button.onclick = () => { select.value = row.value; rememberProjectPreference("backend", row.value); closeBackendDropdown(); renderBackendPickerSelection(); }; menu.appendChild(button);
  }
  select.value = [...select.options].some((o) => o.value === saved) ? saved : ""; renderBackendPickerSelection();
}
function renderBackendPickerSelection() {
  const select = $("backend"), label = $("backendSelectedLabel"); if (!select || !label) return; label.textContent = select.options[select.selectedIndex]?.textContent || "Default backend";
  document.querySelectorAll("#backendDropdownMenu .backend-dropdown-option").forEach((button, index) => { const active = select.options[index]?.value === select.value; button.classList.toggle("active", active); button.setAttribute("aria-selected", String(active)); });
}

// ------------------------------ Workflow picker ------------------------------
async function refreshStudioFiles({ force = false } = {}) {
  const key = state.project?.path || "@global";
  const fresh = state.studioCatalogKey === key && state.studioCatalogLoadedAt && (Date.now() - state.studioCatalogLoadedAt) < 8000;
  if (!force && fresh) { renderStudioFiles(); renderWorkflowPicker(); return state.studioFiles; }
  if (state.studioFilesRefreshPromise) return state.studioFilesRefreshPromise;
  state.studioFilesRefreshPromise = (async () => {
    try {
      const data = await api(`/api/studio/files?x=1${projectQuery()}`);
      state.studioFiles = data; state.studioGuard = data.guard || { editable: true, active_projects: [] };
      state.studioCatalogKey = key; state.studioCatalogLoadedAt = Date.now();
      renderStudioGuard(); renderStudioFiles(); renderWorkflowPicker(); fillAddStagePromptOptions(); refreshPromptTags();
      return data;
    } catch (error) { setStudioStatus(error.message, true); return state.studioFiles; }
    finally { state.studioFilesRefreshPromise = null; }
  })();
  return state.studioFilesRefreshPromise;
}
function closeWorkflowDropdown() {
  const menu = $("workflowDropdownMenu"), picker = $("workflowPicker"), button = $("workflowDropdownButton"); if (!menu || !picker || !button) return;
  menu.hidden = true; menu.classList.remove("workflow-dropdown-portal"); menu.removeAttribute("style");
  if (menu.parentElement !== picker) picker.appendChild(menu);
  picker.classList.remove("open"); button.setAttribute("aria-expanded", "false");
}
function positionWorkflowDropdown() { const menu = $("workflowDropdownMenu"), button = $("workflowDropdownButton"); if (!menu || !button || menu.hidden) return; positionUpwardDropdown(menu, button, menu.children.length, 120); }
function openWorkflowDropdown() {
  const menu = $("workflowDropdownMenu"), picker = $("workflowPicker"), button = $("workflowDropdownButton"); if (!menu || !picker || !button) return; closeBackendDropdown();
  if (menu.parentElement !== document.body) document.body.appendChild(menu);
  menu.classList.add("workflow-dropdown-portal"); menu.hidden = false; picker.classList.add("open"); button.setAttribute("aria-expanded", "true");
  positionWorkflowDropdown();
}

function renderWorkflowPicker() {
  const select = $("workflowSelect"), menu = $("workflowDropdownMenu"), label = $("workflowSelectedLabel"); if (!select || !menu || !label) return;
  const previous = select.value; const saved = String(currentProjectPreferences().workflow || ""); select.innerHTML = ""; menu.innerHTML = "";
  const rows = (state.studioFiles.workflows || []).filter((item) => !item.hidden).map((item) => ({ value: item.path, label: item.name, meta: `${item.group || item.scope}${item.requires_python_validator ? " · Python validation" : ""}${item.has_ai_validator ? " · AI validation" : ""}`, scope: item.scope }));
  for (const row of rows) {
    const option = document.createElement("option"); option.value = row.value; option.textContent = row.label; select.appendChild(option);
    const button = document.createElement("button"); button.type = "button"; button.className = "workflow-dropdown-option"; button.setAttribute("role", "option");
    button.innerHTML = `<span class="workflow-option-main"><strong></strong><small></small></span><span class="workflow-option-badge"></span>`;
    button.querySelector("strong").textContent = row.label; button.querySelector("small").textContent = row.meta; button.querySelector(".workflow-option-badge").textContent = row.scope === "system" ? "SYSTEM" : row.scope.toUpperCase();
    button.onclick = () => { select.value = row.value; label.textContent = row.label; rememberProjectPreference("workflow", row.value); closeWorkflowDropdown(); renderWorkflowPickerSelection(); };
    menu.appendChild(button);
  }
  if ([...select.options].some((option) => option.value === saved)) select.value = saved;
  else if ([...select.options].some((option) => option.value === previous)) select.value = previous;
  else if (select.options.length) select.selectedIndex = 0;
  if (select.value) rememberProjectPreference("workflow", select.value);
  label.textContent = select.options[select.selectedIndex]?.textContent || "No workflow";
  renderWorkflowPickerSelection();
}
function renderWorkflowPickerSelection() {
  const value = $("workflowSelect")?.value || "";
  document.querySelectorAll("#workflowDropdownMenu .workflow-dropdown-option").forEach((button, index) => { const active = $("workflowSelect")?.options[index]?.value === value; button.classList.toggle("active", active); button.setAttribute("aria-selected", String(active)); });
  const workflow = selectedWorkflowItem();
  const validatorPicker = $("validatorPicker"), composerTopbar = $("composerTopbar"), input = $("validator");
  if (validatorPicker) validatorPicker.hidden = !workflow?.requires_python_validator;
  if (composerTopbar) composerTopbar.hidden = !workflow?.requires_python_validator;
  if (input && state.validatorWorkflowPath !== value) { const validators = currentProjectPreferences().validators || {}; input.value = workflow?.requires_python_validator ? String(validators[value] || "") : ""; state.validatorWorkflowPath = value; }
  if (!workflow?.requires_python_validator && input) { input.value = ""; state.validatorWorkflowPath = ""; }
  updateValidatorPicker();
  syncComposerReserve();
}
function updateValidatorPicker() {
  const input = $("validator"), clear = $("clearValidatorButton"); if (!input) return;
  const value = input.value.trim(); input.title = value; if (clear) clear.hidden = !value;
}
async function browseValidator() {
  const button = $("browseValidatorButton"); if (!button) return; const original = button.textContent; button.disabled = true; button.textContent = "Choosing…";
  try { const result = await api("/api/files/pick", { method: "POST", body: JSON.stringify({ kind: "python" }) }); if (!result.cancelled && result.path) { $("validator").value = result.path; rememberValidator($("workflowSelect")?.value || "", result.path); updateValidatorPicker(); showToast("Python validator selected"); } }
  catch (error) { showToast(error.message, "error", 3200); }
  finally { button.disabled = false; button.textContent = original; }
}

// ------------------------------ Workflow Studio ------------------------------
async function switchView(view) {
  if (view === "workflow") {
    state.view = "workflow"; $("chatView").hidden = true; $("workflowView").hidden = false; $("workflowNav").classList.add("active"); $("chatNav").classList.remove("active"); renderStudioFiles(); renderWorkflowPicker(); refreshStudioFiles(); return true;
  }
  if (state.view === "workflow" && !$("workflowGeneratorPage").hidden) { if (!(await leaveGenerateWorkflowPage())) return false; }
  // Global Workflow Studio keeps its main draft when navigating to Project Tasks.
  // Only modal-local drafts need confirmation because closing those dialogs would destroy them.
  if (document.querySelector(".designer-step-modal-box") && !(await closeStageEditor())) return false;
  if (!$("addStageBackdrop").hidden && !(await closeAddStageModal())) return false;
  if (!$("newWorkflowBackdrop").hidden && !(await closeNewWorkflowModal())) return false;
  state.view = "chat"; $("workflowView").hidden = true; $("chatView").hidden = false; $("chatNav").classList.add("active"); $("workflowNav").classList.remove("active");
  return true;
}
function visibleStudioFiles() { return state.studioSourceKind === "prompt" ? (state.studioFiles.prompts || []) : (state.studioFiles.workflows || []); }
function studioSearchQuery() { return state.studioFilters?.[state.studioSourceKind] || ""; }
function filteredStudioFiles() { return window.StudioSupport.filterItems(visibleStudioFiles(), studioSearchQuery()); }
function syncStudioSearch() { const input = $("studioSearchInput"), clear = $("studioSearchClear"); if (!input) return; input.value = studioSearchQuery(); input.placeholder = state.studioSourceKind === "prompt" ? "Search prompts..." : "Search workflows..."; if (clear) clear.hidden = !input.value; }
const STUDIO_FOLDER_STATE_KEY = "ai-task-runner.studio.folder-collapse.v1";
function studioFolderState() { try { const raw = JSON.parse(localStorage.getItem(STUDIO_FOLDER_STATE_KEY) || "{}"); return raw && typeof raw === "object" ? raw : {}; } catch (_) { return {}; } }
function studioFolderKey(folder) { return `${state.studioSourceKind}:${folder || "(root)"}`; }
function studioFolderCollapsed(folder, defaultCollapsed = false) {
  if (studioSearchQuery()) return false;
  const value = studioFolderState(), key = studioFolderKey(folder);
  return Object.prototype.hasOwnProperty.call(value, key) ? !!value[key] : !!defaultCollapsed;
}
function setStudioFolderCollapsed(folder, collapsed) { try { const value = studioFolderState(); value[studioFolderKey(folder)] = !!collapsed; localStorage.setItem(STUDIO_FOLDER_STATE_KEY, JSON.stringify(value)); } catch (_) {} }
function customFolderForItem(item) { const display = String(item?.display_name || item?.name || "").replace(/\\/g, "/"); const index = display.lastIndexOf("/"); return index >= 0 ? display.slice(0, index) : ""; }
function appendStudioItem(root, item) {
  const button = document.createElement("button"); button.type = "button"; button.className = "studio-file-item designer-workflow-pill"; if (state.studioFile?.id === item.id) button.classList.add("active"); if (item.readonly) button.classList.add("readonly");
  const name = document.createElement("strong"); name.textContent = item.name; const metaNode = document.createElement("small"); metaNode.textContent = `${item.readonly ? "System · read only" : (item.scope === "custom" ? "Custom" : "Project")}${item.kind === "workflow" && item.hidden ? " · Hidden from Chat" : ""}`; button.append(name, metaNode); button.onclick = () => openStudioFile(item); root.appendChild(button);
}
function appendStudioFolderGroup(root, folder, items, options = {}) {
  const stateKey = options.stateKey || folder;
  const collapsed = studioFolderCollapsed(stateKey, !!options.defaultCollapsed);
  const section = document.createElement("section"); section.className = "studio-folder-group"; section.classList.toggle("collapsed", collapsed);
  if (options.system) section.classList.add("system-group");
  const header = document.createElement("button"); header.type = "button"; header.className = "studio-folder-header"; header.setAttribute("aria-expanded", String(!collapsed));
  const caret = document.createElement("span"); caret.className = "studio-folder-caret"; caret.setAttribute("aria-hidden", "true");
  const label = document.createElement("span"); label.className = "studio-folder-label"; label.textContent = options.label || folder || "Root";
  const count = document.createElement("span"); count.className = "studio-folder-count"; count.textContent = String(items.length); header.append(caret, label, count);
  const body = document.createElement("div"); body.className = "studio-folder-items"; body.hidden = collapsed; items.forEach((item) => appendStudioItem(body, item));
  header.onclick = () => { const next = !body.hidden; body.hidden = next; section.classList.toggle("collapsed", next); header.setAttribute("aria-expanded", String(!next)); setStudioFolderCollapsed(stateKey, next); };
  section.append(header, body); root.appendChild(section);
}
function renderStudioFiles() {
  const root = $("studioFileList"); root.innerHTML = "";
  $("studioSourceTabs").hidden = false;
  $("studioListTitle").textContent = state.studioSourceKind === "prompt" ? "Prompts" : "Workflows";
  $("yamlWorkflowSource").classList.toggle("active", state.studioSourceKind === "workflow"); $("yamlPromptSource").classList.toggle("active", state.studioSourceKind === "prompt");
  $("newWorkflowButton").hidden = false; $("newWorkflowButton").title = state.studioSourceKind === "prompt" ? "New custom prompt" : "New custom workflow"; syncStudioSearch();
  const grouped = { System: [], Custom: [], Project: [] };
  for (const item of filteredStudioFiles()) (grouped[item.group] || grouped.Project).push(item);
  if (grouped.System.length) {
    appendStudioFolderGroup(root, "@system", grouped.System, { stateKey: "@system", label: "SYSTEM", defaultCollapsed: true, system: true });
  }
  if (grouped.Custom.length) {
    const heading = document.createElement("div"); heading.className = "studio-file-group"; heading.textContent = "Custom"; root.appendChild(heading);
    const folders = new Map(); for (const item of grouped.Custom) { const folder = customFolderForItem(item); if (!folders.has(folder)) folders.set(folder, []); folders.get(folder).push(item); }
    for (const folder of [...folders.keys()].sort((a, b) => a.localeCompare(b))) appendStudioFolderGroup(root, folder, folders.get(folder));
  }
  if (grouped.Project.length) {
    const heading = document.createElement("div"); heading.className = "studio-file-group"; heading.textContent = "Project"; root.appendChild(heading); grouped.Project.forEach((item) => appendStudioItem(root, item));
  }
  if (!root.querySelector(".studio-file-item")) { const empty = document.createElement("div"); empty.className = "studio-list-empty"; const noun = state.studioSourceKind === "prompt" ? "prompts" : "workflows"; empty.textContent = studioSearchQuery() ? `No matching ${noun}` : `No ${noun}`; root.appendChild(empty); }
}
function clearStudioEditor() {
  closeStudioAssetMenu();
  state.studioFile = null; state.studioOriginal = ""; state.studioHash = ""; state.studioDirty = false; state.visual = null; state.visualDirty = false; state.selectedFlowIndex = -1;
  $("studioEditor").hidden = true; $("studioEmpty").hidden = false; $("validationOutput").hidden = true; state.studioErrorDetail = ""; if ($("studioErrorDetailsButton")) $("studioErrorDetailsButton").hidden = true; renderStudioVisibilityBadge(); $("studioTextarea").value = ""; $("studioPromptTextarea").value = ""; updateLineNumbers(); updateDirtyState(); renderStudioPanels();
}
function studioCacheVersion(item) { return String(item?.version || ""); }
function renderStudioVisibilityBadge() {
  const badge = $("studioVisibilityBadge"), item = state.studioFile; if (!badge) return;
  const hidden = item?.kind === "workflow" && !!item.hidden; badge.hidden = !hidden;
  if (hidden) { badge.textContent = t("studio.hidden_badge", "Hidden from Chat"); badge.title = t("studio.hidden_badge_tip", "This Workflow is hidden from the Chat picker. Workflow Studio, CLI, and Runner behavior are unchanged."); }
}
function invalidateStudioFileCache(id = "") { if (id) state.studioFileCache.delete(id); else state.studioFileCache.clear(); }
function applyStudioLoaded(data, visual, item, cached = false) {
  const cache = state.studioFileCache.get(item.id);
  state.studioFile = data; state.studioOriginal = data.content; state.studioHash = data.hash; state.studioDirty = false; state.visual = visual; state.visualDirty = false;
  state.selectedFlowIndex = cache?.selectedFlowIndex ?? (visual?.flow?.length ? 0 : -1); state.studioGuard = data.guard || state.studioGuard;
  $("studioEmpty").hidden = true; $("studioEditor").hidden = false; $("studioFileName").textContent = data.name; $("studioFilePath").textContent = `${data.scope} · ${data.path}`; $("studioKindLabel").textContent = data.kind === "prompt" ? "Prompt" : "Workflow"; $("validationOutput").hidden = true; renderStudioVisibilityBadge();
  if (data.kind === "prompt") $("studioPromptTextarea").value = data.content; else $("studioTextarea").value = data.content;
  renderStudioGuard(); renderStudioFiles(); renderStudioPanels(); renderVisualDesigner(); renderPromptTags(); updateLineNumbers(); updateDirtyState(); scheduleSyntaxCheck(); setStudioStatus(cached ? "" : "");
}
async function openStudioFile(item) {
  closeStudioAssetMenu();
  if (state.studioFile?.id === item.id && !state.studioDirty && !state.visualDirty) return;
  if (state.studioFile?.id !== item.id && !(await confirmDiscardStudio())) return;
  if (state.studioFile?.id && state.studioFileCache.has(state.studioFile.id)) state.studioFileCache.get(state.studioFile.id).selectedFlowIndex = state.selectedFlowIndex;
  const token = ++state.studioOpenToken;
  const cached = state.studioFileCache.get(item.id);
  if (cached && cached.version === studioCacheVersion(item) && (Date.now() - Number(cached.loadedAt || 0)) < 15000) {
    applyStudioLoaded(cached.data, cached.visual, item, true);
    if (cached.data.kind === "prompt") refreshPromptTags();
    return;
  }
  // Give immediate selection feedback before localhost file/visual hydration completes.
  state.studioFile = { ...item, content: "", hash: "" }; state.visual = null; state.selectedFlowIndex = -1;
  if (item.kind === "workflow") $("studioTextarea").value = ""; else $("studioPromptTextarea").value = "";
  $("studioEmpty").hidden = true; $("studioEditor").hidden = false; $("studioFileName").textContent = item.name; $("studioFilePath").textContent = `${item.scope} · ${item.path}`; $("studioKindLabel").textContent = item.kind === "prompt" ? "Prompt" : "Workflow"; renderStudioVisibilityBadge();
  renderStudioFiles(); renderStudioPanels(); renderVisualDesigner(); updateLineNumbers(); setStudioStatus("Loading…");
  try {
    const filePromise = api(`/api/studio/file?id=${encodeURIComponent(item.id)}${projectQuery()}`);
    const visualPromise = item.kind === "workflow" ? api(`/api/studio/visual?id=${encodeURIComponent(item.id)}${projectQuery()}`) : Promise.resolve(null);
    const [data, visual] = await Promise.all([filePromise, visualPromise]);
    if (token !== state.studioOpenToken) return;
    state.studioFileCache.set(item.id, { version: studioCacheVersion(item), loadedAt: Date.now(), data, visual, selectedFlowIndex: visual?.flow?.length ? 0 : -1 });
    applyStudioLoaded(data, visual, item);
    if (data.kind === "prompt") await refreshPromptTags();
  } catch (error) { if (token === state.studioOpenToken) setStudioStatus(error.message, true); }
}
function renderStudioPanels() {
  const prompt = state.studioFile?.kind === "prompt";
  const workflow = state.studioFile?.kind === "workflow";
  $("promptEditorPanel").hidden = !prompt;
  $("visualDesignerPanel").hidden = !workflow || state.studioMode !== "visual";
  $("yamlEditorPanel").hidden = !workflow || state.studioMode !== "yaml";
}
async function setStudioMode(mode) {
  if (mode === state.studioMode) return;
  // Prompt uses the same editor in both modes; mode only matters to Workflow files.
  if (state.studioFile?.kind === "workflow" && !(await confirmDiscardStudio())) return;
  state.studioMode = mode;
  $("visualModeButton").classList.toggle("active", mode === "visual"); $("yamlModeButton").classList.toggle("active", mode === "yaml");
  renderStudioPanels(); updateDirtyState(); scheduleSyntaxCheck();
}
async function setStudioSource(kind) {
  if (kind === state.studioSourceKind) return;
  if (!(await confirmDiscardStudio())) return;
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
  if (!state.studioGuard.editable || state.studioFile?.readonly) return; const flow = state.visual?.flow || [], index = state.selectedFlowIndex;
  if (index < 0 || index >= flow.length) return; const name = flowStageName(flow[index]) || "Stage";
  const action = await choiceDialog({ title: "Remove Stage?", message: `Choose whether to remove only this ${name} Flow invocation or also delete its Stage definition. Definition deletion is blocked when other Workflow references still use it.`, choices: [{ value: "flow", label: "Remove from Flow" }, { value: "definition", label: "Delete Definition Too", danger: true }] });
  if (!action) return;
  if (action === "flow") { flow.splice(index, 1); state.selectedFlowIndex = flow.length ? Math.min(index, flow.length - 1) : -1; state.visualDirty = true; renderVisualDesigner(); updateDirtyState(); showToast(`${name} removed from flow`); return; }
  if (state.visualDirty || state.studioDirty) { const ok = await saveVisualFlow(); if (!ok) return; }
  try { const result = await api("/api/studio/stage/delete", { method: "POST", body: JSON.stringify({ id: state.studioFile.id, project: state.project?.path || "", stage: name, flow_index: index, hash: state.studioHash }) }); invalidateStudioFileCache(state.studioFile.id); state.studioFile = result.file; state.studioOriginal = result.file.content; state.studioHash = result.file.hash; state.studioDirty = false; state.visualDirty = false; state.visual = result.visual; state.selectedFlowIndex = state.visual.flow?.length ? Math.min(index, state.visual.flow.length - 1) : -1; $("studioTextarea").value = result.file.content; updateLineNumbers(); renderVisualDesigner(); updateDirtyState(); showToast(`${name} Stage definition deleted`); }
  catch (error) { setStudioStatus(error.message, true); showActionError(error.message, "Stage deletion failed"); }
}

async function saveVisualFlow() {
  if (!state.studioFile || state.studioFile.kind !== "workflow" || !state.visualDirty || !state.studioGuard.editable) return true;
  try {
    const data = await api("/api/studio/visual/save", { method: "POST", body: JSON.stringify({ id: state.studioFile.id, project: state.project?.path || "", flow: state.visual.flow, hash: state.studioHash }) });
    invalidateStudioFileCache(state.studioFile?.id || data.id); state.studioFile = data; state.studioOriginal = data.content; state.studioHash = data.hash; state.studioDirty = false; state.visualDirty = false; $("studioTextarea").value = data.content; state.visual = await api(`/api/studio/visual?id=${encodeURIComponent(data.id)}${projectQuery()}`); renderVisualDesigner(); updateLineNumbers(); updateDirtyState(); setStudioStatus("Saved"); showToast("Workflow saved"); return true;
  } catch (error) { setStudioStatus(error.message, true); showActionError(error.message, "Workflow save failed"); return false; }
}

// ------------------------------ Prompt Editor ------------------------------
async function refreshPromptTags() {
  try {
    const params = new URLSearchParams();
    if (state.studioFile?.kind === "prompt") params.set("id", state.studioFile.id);
    if (state.project?.path) params.set("project", state.project.path);
    const data = await api(`/api/studio/prompt-tags${params.toString() ? `?${params}` : ""}`);
    state.promptTags = data.tags || []; renderPromptTags();
  } catch (_) { state.promptTags = []; renderPromptTags(); }
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
  badge.className = `studio-syntax-badge ${result.ok ? "valid" : "invalid"}`; badge.textContent = result.ok ? "Prompt valid" : (result.line ? `Jinja line ${result.line}` : "Prompt invalid");
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
  if (currentStageModal() && !(await closeStageEditor())) return;
  if (state.visualDirty && !(await saveVisualFlow())) return;
  state.selectedFlowIndex = index; state.stageEditorDirty = false;
  const item = state.visual.flow[index], name = flowStageName(item), cfg = stageConfig(name), total = state.visual.flow.length;
  const box = document.createElement("div"); box.className = "designer-export-box designer-step-modal-box";
  box.innerHTML = `
    <div class="designer-export-card designer-step-modal-card" role="dialog" aria-modal="true" aria-labelledby="designerStepModalTitle">
      <div class="designer-step-modal-head">
        <div class="designer-step-modal-title-wrap">
          <div class="designer-step-modal-title-line"><h2 id="designerStepModalTitle">${escapeHtml(name || "Stage Settings")}</h2><span class="designer-step-type">${escapeHtml(cfg.type || "base")}</span></div>
          <p class="designer-form-hint">${escapeHtml(tf("stage.modal_desc", { index: index + 1, total }, `Stage ${index + 1} / ${total} · Prompt content (when supported) is edited from the Prompt workspace.`))}</p>
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
    ${!state.studioGuard.editable ? `<div class="designer-warning-box"><strong>Read only</strong><span>${escapeHtml(t("stage.readonly_desc", "Stop active Runtime before editing Workflow settings."))}</span></div>` : ''}
    <div class="stage-identity-strip"><span><strong>${escapeHtml(cfg.name)}</strong><small>Stage key</small></span><span><strong>${escapeHtml(cfg.type || "base")}</strong><small>Current type</small></span></div>
    <div class="stage-section-head"><div><strong>Stage</strong><span>${escapeHtml(t("stage.section_desc", "Common settings are shown first; less-used runtime overrides are under Advanced."))}</span></div></div>
    <div class="stage-form-two-col stage-primary-fields">
      <label class="designer-form-row"><span class="designer-label">Type</span><select id="stageType" class="designer-select" ${disabled}>${stageTypesOptions(cfg.type || "base")}</select></label>
      <label class="designer-form-row"><span class="designer-label">Status</span><input id="stageStatus" class="designer-input" value="${escapeHtml(item?.status ?? cfg.status ?? "")}" placeholder="User-facing runtime status" ${disabled} /></label>
      <label id="stagePromptSelectRow" class="designer-form-row stage-form-wide"><span class="designer-label">Prompt</span><select id="stagePromptSelect" class="designer-select" ${disabled}>${promptOptionRows(item?.prompt ?? cfg.prompt ?? "")}</select><span class="designer-form-hint">${escapeHtml(t("stage.prompt_desc", "Edit Prompt content in Workflow Studio → Prompt. Continuation Prompt is an advanced YAML override and is intentionally not duplicated here."))}</span></label>
      <label class="designer-form-row"><span class="designer-label">Timeout (seconds)</span><input id="stageTimeout" class="designer-input" type="number" min="0" step="0.1" value="${cfg.timeout ?? ""}" placeholder="Stage default" ${disabled} /></label>
      <label class="designer-form-row"><span class="designer-label">Flow scope</span><select id="stageScope" class="designer-select" ${disabled}><option value="" ${!item?.scope ? "selected" : ""}>Workflow</option><option value="task" ${item?.scope === "task" ? "selected" : ""}>Per task</option></select></label>
      <label class="designer-form-row stage-form-wide"><span class="designer-label">Flow label</span><input id="stageFlowLabel" class="designer-input" value="${escapeHtml(item?.label || "")}" placeholder="Optional display / routing label" ${disabled} /></label>
      <label class="designer-form-row stage-form-wide"><span class="designer-label">Detail</span><textarea id="stageDetail" class="designer-textarea" rows="2" placeholder="Optional Stage detail / context" ${disabled}>${escapeHtml(cfg.detail || "")}</textarea></label>
    </div>
    <div id="stageTypeSpecific" class="stage-type-specific"></div>
    <details id="stageAdvancedOverrides" class="stage-advanced-overrides" ${hasAdvancedStageOverrides(cfg) ? "open" : ""}>
      <summary><span><strong>Advanced overrides</strong><small>${escapeHtml(t("stage.advanced_desc", "Use only when the Stage type default is not enough."))}</small></span><span aria-hidden="true">⌄</span></summary>
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
    <div class="stage-section-head"><div><strong>Flow</strong><span>${escapeHtml(t("stage.flow_desc", "Routing for this Flow invocation."))}</span></div></div>
    <div class="stage-form-two-col">
      <label class="designer-form-row">${fieldLabel("Restart at", t("stage.help.restart_at", "On semantic FAIL, restart this or an earlier top-level Stage."))}<select id="stageRestartAt" class="designer-select" ${disabled}>${flowStageOptions(item?.restart_at || "")}</select></label>
      <label class="designer-form-row">${fieldLabel("Repeat", t("stage.help.repeat", "Legacy bounded recovery. Leave empty unless this Workflow already relies on repeat."))}<input id="stageRepeat" class="designer-input" type="number" min="1" value="${item?.repeat ?? ""}" placeholder="No repeat" ${disabled} /></label>
      <label class="designer-form-row">${fieldLabel("Fresh after same failures", t("stage.help.fresh_after", "After the same semantic failure repeats this many times, use a Fresh Session for recovery."))}<input id="stageFreshAfterSameFailures" class="designer-input" type="number" min="1" value="${item?.fresh_after_same_failures ?? ""}" placeholder="Default recovery policy" ${disabled} /></label>
    </div>

    <div class="stage-section-head"><div><strong>Recovery gate</strong><span>${escapeHtml(t("stage.recovery_desc", "Semantic FAIL routing and optional bounded recovery."))}</span></div></div>
    <div class="stage-form-two-col">
      <label class="designer-form-row stage-form-wide">${fieldLabel("Recover stages", t("stage.help.recover", "Stages to run when this Stage returns semantic FAIL."))}<input id="stageRecover" class="designer-input" value="${escapeHtml((cfg.recover || []).join(", "))}" placeholder="repair, repair_plan" ${disabled} /></label>
      <label id="stageMaxAttemptsRow" class="designer-form-row">${fieldLabel("Max attempts", t("stage.help.max_attempts", "Maximum FAIL → Recover → Retry attempts in one gate cycle. Leave empty to keep the original unlimited / current recovery behavior."))}<input id="stageMaxAttempts" class="designer-input" type="number" min="1" value="${item?.max_attempts ?? ""}" placeholder="Unlimited / current behavior" ${disabled} /></label>
      <label id="stageOnExhaustedRow" class="designer-form-row">${fieldLabel("On exhausted", t("stage.help.on_exhausted", "What happens when Max attempts is reached. Re-entering this Stage later starts again from attempt 1."))}<select id="stageOnExhausted" class="designer-select" ${disabled}><option value="" ${!item?.on_exhausted ? "selected" : ""}>Fail (default)</option><option value="fail" ${item?.on_exhausted === "fail" ? "selected" : ""}>Fail</option><option value="continue" ${item?.on_exhausted === "continue" ? "selected" : ""}>Continue</option></select></label>
    </div>
    <div id="stageRecoveryBehavior" class="stage-behavior-preview"></div>

    <div class="stage-section-head"><div><strong>Retry & structured output</strong><span>${escapeHtml(t("stage.retry_desc", "Execution-level retry is separate from FAIL → Recover attempts."))}</span></div></div>
    <div class="stage-form-two-col">
      <label class="designer-form-row">${fieldLabel("Retry", t("stage.help.retry", "Technical Stage retry. This is separate from semantic FAIL recovery."))}<input id="stageRetry" class="designer-input" type="number" min="-1" value="${cfg.retry ?? ""}" placeholder="Stage default" ${disabled} /><span class="designer-form-hint">${escapeHtml(t("stage.retry_hint", "-1 = keep retrying until PASS; 0 = no retry."))}</span></label>
      <label id="stageStructuredRetriesRow" class="designer-form-row">${fieldLabel("Structured retries", t("stage.help.structured_retries", "Retry malformed structured output in the current Session."))}<input id="stageStructuredRetries" class="designer-input" type="number" min="0" value="${cfg.structured_retries ?? ""}" placeholder="Stage default" ${disabled} /></label>
      <label id="stageStructuredFreshRetriesRow" class="designer-form-row">${fieldLabel("Structured fresh retries", t("stage.help.structured_fresh_retries", "Retry malformed structured output in a Fresh Session after current-Session retries are exhausted."))}<input id="stageStructuredFreshRetries" class="designer-input" type="number" min="0" value="${cfg.structured_fresh_retries ?? ""}" placeholder="Stage default" ${disabled} /></label>
    </div>

    <div class="stage-section-head"><div><strong>Session & safety</strong><span>${escapeHtml(t("stage.session_desc", "Session isolation and file / change handling."))}</span></div></div>
    <div class="stage-switch-grid">
      ${switchRow("stageSkipOnError", "Skip on error", t("stage.help.skip_on_error", "Continue when the Stage itself errors."), cfg.skip_on_error, disabled)}
      <span id="stageFreshOnStartRow">${switchRow("stageFreshOnStart", "Fresh session on start", t("stage.help.fresh_on_start", "Start this Stage in a new AI Session."), cfg.fresh_session_on_start, disabled)}</span>
      <span id="stageFreshEachRunRow">${switchRow("stageFreshEachRun", "Fresh session each run", t("stage.help.fresh_each_run", "Use a new Session for every multi-run validation."), cfg.fresh_session_each_run, disabled)}</span>
      ${switchRow("stageTrackChanges", "Track changes", t("stage.help.track_changes", "Track project changes produced by this Stage."), cfg.track_changes, disabled)}
      ${switchRow("stageTolerateRestored", "Tolerate restored changes", t("stage.help.tolerate_restored", "Allow restored readonly changes without failing the Stage."), cfg.tolerate_restored_changes, disabled)}
      <span id="stageAllowProjectReadRow">${switchRow("stageAllowProjectRead", "Allow readonly file read", t("stage.help.allow_read", "For Plan, allow readonly inspection of any filesystem path readable by the current account, including paths outside the Current Project."), cfg.allow_project_read ?? ((cfg.type || "base") === "plan"), disabled)}</span>
    </div>
    <div id="stageCleanWorkRow" class="stage-form-two-col stage-command-safety" hidden>
      <label class="designer-form-row stage-form-wide">${fieldLabel("Clean work paths", t("stage.help.clean_work", "Delete these relative paths under the Runner work directory before a Command / Validator run."))}<input id="stageCleanWork" class="designer-input" value="${escapeHtml((cfg.clean_work || []).join(", "))}" placeholder="validator-reports" ${disabled} /></label>
    </div>`;

  const syncRecoveryControls = () => {
    const recover = fieldValue("stageRecover").trim(); const max = fieldValue("stageMaxAttempts").trim();
    const hasRecover = Boolean(recover); const hasMax = Boolean(max);
    if ($("stageMaxAttemptsRow")) $("stageMaxAttemptsRow").hidden = !hasRecover;
    if ($("stageOnExhaustedRow")) $("stageOnExhaustedRow").hidden = !hasRecover || !hasMax;
    if ($("stageRepeat")) $("stageRepeat").disabled = Boolean(disabled) || hasMax;
    if ($("stageRestartAt")) $("stageRestartAt").disabled = Boolean(disabled) || hasMax;
    const preview = $("stageRecoveryBehavior"); if (!preview) return;
    if (!hasRecover) { preview.hidden = true; preview.textContent = ""; return; }
    preview.hidden = false;
    const target = recover.split(",").map((x) => x.trim()).filter(Boolean).join(" → ") || "recovery";
    if (!hasMax) { preview.textContent = tf("stage.behavior.unbounded", { target }, `FAIL → ${target} → Retry · no bounded attempt limit`); return; }
    const exhausted = fieldValue("stageOnExhausted") === "continue" ? "Continue" : "Fail";
    preview.textContent = tf("stage.behavior.bounded", { target, max, exhausted }, `FAIL → ${target} → Retry · up to ${max} attempts · then ${exhausted}. Later re-entry starts again at 1.`);
  };
  $("stageRecover")?.addEventListener("input", syncRecoveryControls); $("stageMaxAttempts")?.addEventListener("input", syncRecoveryControls); $("stageOnExhausted")?.addEventListener("change", syncRecoveryControls); syncRecoveryControls();

  $("stageType").addEventListener("change", () => { state.stageEditorDirty = true; renderTypeSpecific(cfg, disabled); syncStageTypeUi(cfg); }); renderTypeSpecific(cfg, disabled); syncStageTypeUi(cfg);
}
function hasAdvancedStageOverrides(cfg) { return ["run_state", "actor", "mode", "parser", "produces", "session_key", "instructions"].some((key) => cfg[key] !== undefined && cfg[key] !== ""); }
function switchRow(id, title, hint, value, disabled) { return `<label class="designer-switch-row"><input id="${id}" type="checkbox" ${value ? "checked" : ""} ${disabled} /><span><strong>${escapeHtml(title)}</strong><small>${escapeHtml(hint)}</small></span></label>`; }
function helpMark(text) { return `<span class="stage-help" tabindex="0" title="${escapeHtml(text)}" aria-label="${escapeHtml(text)}">?</span>`; }
function fieldLabel(title, help = "") { return `<span class="designer-label">${escapeHtml(title)}${help ? helpMark(help) : ""}</span>`; }
function renderTypeSpecific(cfg, disabled) {
  const root = $("stageTypeSpecific"); if (!root) return; const type = $("stageType")?.value || cfg.type || "base"; const parts = [];
  if (type === "command") {
    parts.push(`<div class="stage-section-head"><div><strong>Command</strong><span>${escapeHtml(t("stage.command_desc", "Command runtime settings."))}</span></div></div><div class="stage-form-two-col"><label class="designer-form-row stage-form-wide"><span class="designer-label">Command</span><textarea id="stageCommand" class="designer-textarea" rows="4" ${disabled}>${escapeHtml(Array.isArray(cfg.command) ? cfg.command.join(" ") : (cfg.command || ""))}</textarea></label><label class="designer-form-row"><span class="designer-label">Result kind</span><select id="stageResultKind" class="designer-select" ${disabled}><option value="" ${!cfg.result_kind ? "selected" : ""}>Stage default</option><option value="generic" ${cfg.result_kind === "generic" ? "selected" : ""}>generic</option><option value="validation" ${cfg.result_kind === "validation" ? "selected" : ""}>validation</option></select></label><label class="designer-form-row"><span class="designer-label">Working directory</span><input id="stageCwd" class="designer-input" value="${escapeHtml(cfg.cwd || "")}" placeholder="Project root" ${disabled} /></label></div>`);
  } else {
    if (type === "plan") parts.push(`<div class="stage-section-head"><div><strong>Plan</strong><span>${escapeHtml(t("stage.plan_desc", "Task-plan generation settings. Plan prompt is owned by the Plan Stage implementation."))}</span></div></div><div class="stage-form-two-col"><label class="designer-form-row"><span class="designer-label">Minimum tasks</span><input id="stageMinTasks" class="designer-input" type="number" min="1" value="${cfg.min_tasks ?? ""}" placeholder="Default" ${disabled} /></label>${switchRow("stageRepairPlan", "Repair plan", t("stage.help.repair_plan", "Generate a repair-oriented TODO plan."), cfg.repair_plan, disabled)}</div>`);
    if (type === "ai_validator") parts.push(`<div class="stage-section-head"><div><strong>AI validation</strong><span>${escapeHtml(t("stage.ai_validation_desc", "AI Validator and multi-run voting settings."))}</span></div></div><div class="stage-form-two-col"><label class="designer-form-row">${fieldLabel("Validator", t("stage.help.validator", "AI validator profile. Usually leave as ai."))}<input id="stageValidator" class="designer-input" value="${escapeHtml(cfg.validator || "")}" placeholder="ai" ${disabled} /></label><label class="designer-form-row">${fieldLabel("Runs", t("stage.help.runs", "How many independent Stage runs to perform in one entry."))}<input id="stageRuns" class="designer-input" type="number" min="1" value="${cfg.runs ?? ""}" placeholder="Configured default" ${disabled} /></label><label class="designer-form-row">${fieldLabel("Required passes", t("stage.help.required_passes", "How many Runs must PASS. Leave empty for the Stage default / majority."))}<input id="stageRequiredPasses" class="designer-input" type="number" min="1" value="${cfg.required_passes ?? ""}" placeholder="Majority" ${disabled} /></label></div>`);
    else if (["base", "task", "review"].includes(type)) parts.push(`<div class="stage-section-head"><div><strong>Multi-run</strong><span>${escapeHtml(t("stage.multi_run_desc", "Optional repeated runs / voting for this Stage."))}</span></div></div><div class="stage-form-two-col"><label class="designer-form-row">${fieldLabel("Runs", t("stage.help.runs", "How many independent Stage runs to perform in one entry."))}<input id="stageRuns" class="designer-input" type="number" min="1" value="${cfg.runs ?? ""}" placeholder="Stage default" ${disabled} /></label><label class="designer-form-row">${fieldLabel("Required passes", t("stage.help.required_passes", "How many Runs must PASS. Leave empty for the Stage default / majority."))}<input id="stageRequiredPasses" class="designer-input" type="number" min="1" value="${cfg.required_passes ?? ""}" placeholder="Majority" ${disabled} /></label></div>`);
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
  if ($("stageAllowProjectRead") && cfg.allow_project_read === undefined) $("stageAllowProjectRead").checked = type === "plan";
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
  for (const [key, value] of Object.entries(candidates)) {
    const implicitBoolean = key === "allow_project_read" && type === "plan";
    if (booleanKeys.has(key) && cfg[key] === undefined && value === implicitBoolean) continue;
    const before = cfg[key] === undefined ? null : cfg[key]; if (JSON.stringify(before) !== JSON.stringify(value)) result[key] = value;
  }
  if (type !== "command" && cfg.type === "command") for (const key of ["command", "result_kind", "cwd", "clean_work"]) if (cfg[key] !== undefined) result[key] = null;
  if (type !== "plan" && cfg.type === "plan") for (const key of ["min_tasks", "repair_plan"]) if (cfg[key] !== undefined) result[key] = null;
  if (type !== "ai_validator" && cfg.type === "ai_validator" && cfg.validator !== undefined) result.validator = null;
  if (!aiBacked && cfg.type !== "command") for (const key of ["prompt", "continuation_prompt", "instructions", "session_key", "parser", "structured_retries", "structured_fresh_retries", "fresh_session_each_run", "fresh_session_on_start", "allow_project_read", "runs", "required_passes"]) if (cfg[key] !== undefined) result[key] = null;
  if (aiBacked && !stageSupportsPrompt(type) && stageSupportsPrompt(cfg.type)) for (const key of ["prompt", "continuation_prompt", "instructions"]) if (cfg[key] !== undefined) result[key] = null;
  return result;
}
function changedFlowFields(item) { const recover = fieldValue("stageRecover").trim(); const maxAttempts = recover ? numberOrNull("stageMaxAttempts") : null; const result = { label: valueOrNull("stageFlowLabel"), restart_at: maxAttempts ? null : valueOrNull("stageRestartAt"), repeat: maxAttempts ? null : numberOrNull("stageRepeat"), max_attempts: maxAttempts, on_exhausted: maxAttempts ? valueOrNull("stageOnExhausted") : null, fresh_after_same_failures: numberOrNull("stageFreshAfterSameFailures") }; if (item && Object.prototype.hasOwnProperty.call(item, "status")) result.status = valueOrNull("stageStatus"); if (item && Object.prototype.hasOwnProperty.call(item, "prompt")) result.prompt = stageSupportsPrompt(fieldValue("stageType")) ? valueOrNull("stagePromptSelect") : null; return result; }
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
    invalidateStudioFileCache(state.studioFile.id); state.studioFile = result.file; state.studioOriginal = result.file.content; state.studioHash = result.file.hash; state.studioDirty = false; state.visualDirty = false; state.visual = result.visual; $("studioTextarea").value = result.file.content; updateLineNumbers(); renderVisualDesigner(); updateDirtyState(); setStudioStatus("Stage saved"); state.stageEditorDirty = false; status.textContent = "Saved";
    showToast("Stage saved");
    setTimeout(async () => { if (currentStageModal()) { closeStageEditor(true); await openStageEditor(index); const reopened = $("stageEditorStatus"); if (reopened) reopened.textContent = "Saved"; } }, 120);
  } catch (error) { status.textContent = error.message; status.classList.add("error"); showActionError(error.message, "Stage save failed"); }
}
async function closeStageEditor(force = false) {
  if (!currentStageModal()) return true;
  if (!force && state.stageEditorDirty) {
    const ok = await confirmDialog({
      title: "Discard Stage changes?",
      message: "Discard unsaved changes in this Stage? The saved Workflow will remain unchanged.",
      confirmLabel: "Discard Changes",
      danger: true,
    });
    if (!ok) return false;
  }
  document.querySelectorAll(".designer-step-modal-box").forEach((node) => node.remove());
  state.stageEditorDirty = false;
  return true;
}

// ------------------------------ Add Stage modal ------------------------------
function fillAddStagePromptOptions() { const select = $("addStagePrompt"); if (!select) return; const current = select.value; select.innerHTML = promptOptionRows(current); }
async function openAddStageModal() {
  if (!state.studioFile || state.studioFile.kind !== "workflow") return setStudioStatus("Select a Workflow first.", true);
  if (!state.studioGuard.editable) return setStudioStatus("Stop active Runtime before editing Workflow.", true);
  if (state.visualDirty && !(await saveVisualFlow())) return;
  state.addStageDirty = false; $("addStageName").value = ""; $("addStageType").value = "task"; $("addStageStatus").value = ""; $("addStageCommand").value = ""; $("addStageToFlow").checked = true; $("addStageHint").textContent = ""; $("addStageHint").classList.remove("error"); fillAddStagePromptOptions(); updateAddStageType(); $("addStageBackdrop").hidden = false; setTimeout(() => $("addStageName").focus(), 0);
}
async function closeAddStageModal(force = false) {
  if ($("addStageBackdrop").hidden) return true;
  if (!force && state.addStageDirty) { const ok = await confirmDialog({ title: "Discard new Stage?", message: "Discard this unsaved Stage? The Workflow will remain unchanged.", confirmLabel: "Discard Stage", danger: true }); if (!ok) return false; }
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
    invalidateStudioFileCache(state.studioFile.id); state.studioFile = result.file; state.studioOriginal = result.file.content; state.studioHash = result.file.hash; state.studioDirty = false; state.visualDirty = false; state.visual = result.visual; $("studioTextarea").value = result.file.content; updateLineNumbers(); renderVisualDesigner(); updateDirtyState(); state.addStageDirty = false; closeAddStageModal(true); setStudioStatus(`Stage ${name} added`); showToast(`Stage ${name} added`);
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
  $("saveStudioButton").disabled = locked || !saveNeeded; $("validateStudioButton").hidden = !state.studioFile; $("validateStudioButton").disabled = !state.studioFile; $("validateStudioButton").textContent = state.studioFile?.kind === "prompt" ? "Validate Prompt" : "Validate Workflow"; $("addFlowStepButton").disabled = locked || !state.studioFile || state.studioFile.kind !== "workflow";
  $("newWorkflowButton").disabled = !state.studioGuard.editable; $("importAssetButton").disabled = !state.studioGuard.editable;
  $("exportStudioButton").disabled = !state.studioFile; $("deleteStudioButton").hidden = !state.studioFile || !!state.studioFile.readonly; $("deleteStudioButton").disabled = !state.studioGuard.editable || !state.studioFile?.deletable;
  $("studioAssetMenuButton").disabled = !state.studioFile; $("renameStudioButton").disabled = !state.studioGuard.editable || !state.studioFile || !!state.studioFile.readonly; $("duplicateStudioButton").disabled = !state.studioGuard.editable || !state.studioFile; const visibilityButton = $("toggleWorkflowVisibilityButton"); if (visibilityButton) { visibilityButton.hidden = state.studioFile?.kind !== "workflow"; visibilityButton.disabled = !state.studioFile || state.studioFile.kind !== "workflow"; visibilityButton.textContent = state.studioFile?.hidden ? "Show in Chat" : "Hide from Chat"; }
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
  if (!$("workflowGeneratorPage").hidden) {
    const building = ["running", "cancelling"].includes(state.generateWorkflowPhase);
    // Draft generation/validation is UI-workspace work and is independent from any
    // selected Project runtime. Only publishing a real asset stays edit-guarded.
    $("generateWorkflowRequest").disabled = building || state.generateWorkflowPhase !== "form";
    $("generateWorkflowBackend").disabled = building || state.generateWorkflowPhase !== "form";
    $("generateWorkflowConfirm").disabled = building;
    $("generateWorkflowSave").disabled = state.generateWorkflowPhase !== "ready" || locked;
    $("generateWorkflowValidate").disabled = state.generateWorkflowPhase !== "ready";
    if (state.generateWorkflowPhase === "form" && $("generateWorkflowHint").textContent.startsWith("Runtime started")) { $("generateWorkflowHint").textContent = "Generate uses an isolated temporary workspace. No Project is required."; $("generateWorkflowHint").classList.remove("error"); }
  }
}
async function refreshStudioGuard() {
  if (state.view !== "workflow") return;
  if (state.studioGuardRefreshPromise) return state.studioGuardRefreshPromise;
  state.studioGuardRefreshPromise = (async () => {
    try { state.studioGuard = await api("/api/studio/guard"); renderStudioGuard(); } catch (_) {}
    finally { state.studioGuardRefreshPromise = null; }
  })();
  return state.studioGuardRefreshPromise;
}
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
async function reloadStudio() { if (!state.studioFile || !(await confirmDiscardStudio())) return; await openStudioFile(state.studioFile); }
async function validateStudio() {
  if (!state.studioFile) return;
  const body = { id: state.studioFile.id, project: state.project?.path || "" };
  const prompt = state.studioFile.kind === "prompt";
  if (prompt) body.content = $("studioPromptTextarea").value;
  else if (state.studioMode === "visual") body.flow = state.visual?.flow || [];
  else body.content = $("studioTextarea").value;
  try {
    setStudioStatus(`Validating current ${prompt ? "Prompt" : "Workflow"} draft…`);
    const result = await api("/api/studio/validate", { method: "POST", body: JSON.stringify(body) });
    if (prompt) promptDiagnostics(result);
    if (result.ok) { $("validationOutput").hidden = true; setStudioStatus(""); showToast(`${prompt ? "Prompt" : "Workflow"} validation passed`); }
    else { const detail = result.output || result.summary || `${prompt ? "Prompt" : "Workflow"} validation failed`; $("validationOutput").hidden = false; $("validationOutput").textContent = detail; setStudioStatus(detail, true); showToast(`${prompt ? "Prompt" : "Workflow"} validation failed`, "error", 3200); }
  } catch (error) { setStudioStatus(error.message, true); showActionError(error.message, `${prompt ? "Prompt" : "Workflow"} validation failed`); }
}
function setStudioStatus(text, error = false) {
  const node = $("studioStatus"), detailsButton = $("studioErrorDetailsButton"); if (!node) return;
  const detail = String(text || "").trim();
  const firstLine = detail.split(/\r?\n/).find((line) => line.trim())?.trim() || "";
  const summary = error && firstLine.length > 220 ? `${firstLine.slice(0, 217)}...` : firstLine;
  node.textContent = summary; node.title = detail; node.classList.toggle("error", !!error);
  state.studioErrorDetail = error ? detail : ""; if (detailsButton) detailsButton.hidden = !state.studioErrorDetail;
}
async function confirmDiscardStudio() {
  if (!(state.studioDirty || state.visualDirty || state.stageEditorDirty)) return true;
  return confirmDialog({ title: "Discard unsaved changes?", message: "You have unsaved Workflow, Stage, or Prompt changes. Leaving this editor will discard them.", confirmLabel: "Discard Changes", danger: true });
}

// ------------------------------ New Workflow / Prompt / Import / Export ------------------------------
function fillCustomFolderSelect(kind, selectId, selected = "") {
  const select = $(selectId); if (!select) return;
  const folders = state.studioFiles?.custom_folders?.[kind] || [""];
  select.innerHTML = "";
  folders.forEach((folder) => { const option = document.createElement("option"); option.value = folder; option.textContent = folder || "Custom root"; select.appendChild(option); });
  if ([...select.options].some((o) => o.value === selected)) select.value = selected;
}
function syncCustomFolderVisibility(kind) {
  const workflow = kind === "workflow"; const destination = $(workflow ? "newWorkflowDestination" : "newPromptDestination")?.value;
  const row = $(workflow ? "newWorkflowFolderRow" : "newPromptFolderRow"); const createRow = $(workflow ? "newWorkflowFolderCreateRow" : "newPromptFolderCreateRow");
  const custom = destination === "custom"; if (row) row.hidden = !custom; if (!custom && createRow) createRow.hidden = true;
}
async function createCustomFolder(kind) {
  const workflow = kind === "workflow"; const input = $(workflow ? "newWorkflowFolderName" : "newPromptFolderName"); const selectId = workflow ? "newWorkflowFolder" : "newPromptFolder"; const row = $(workflow ? "newWorkflowFolderCreateRow" : "newPromptFolderCreateRow");
  const folder = input?.value.trim() || ""; if (!folder) return;
  try { const result = await api("/api/studio/custom-folder/create", { method: "POST", body: JSON.stringify({ kind, folder }) }); state.studioFiles.custom_folders ||= {}; state.studioFiles.custom_folders[kind] = result.folders || [""]; fillCustomFolderSelect(kind, selectId, result.folder); if (input) input.value = ""; if (row) row.hidden = true; showToast(`Folder ${result.folder} ready`); }
  catch (error) { showActionError(error.message, "Folder creation failed"); }
}
function openNewWorkflowModal() {
  if (!state.studioGuard.editable) return setStudioStatus("Stop active Runtime before creating Workflow.", true);
  state.newWorkflowDirty = false; $("newWorkflowName").value = ""; $("newWorkflowDestination").value = "custom"; fillCustomFolderSelect("workflow", "newWorkflowFolder"); $("newWorkflowFolderCreateRow").hidden = true; $("newWorkflowFolderName").value = ""; syncCustomFolderVisibility("workflow"); $("newWorkflowDestination").querySelector('option[value="project"]').disabled = !state.project; $("newWorkflowHint").textContent = ""; $("newWorkflowHint").classList.remove("error"); $("newWorkflowBackdrop").hidden = false; setTimeout(() => $("newWorkflowName").focus(), 0);
}
async function closeNewWorkflowModal(force = false) { if ($("newWorkflowBackdrop").hidden) return true; if (!force && state.newWorkflowDirty) { const ok = await confirmDialog({ title: "Discard new Workflow?", message: "Discard this unsaved Workflow draft?", confirmLabel: "Discard Workflow", danger: true }); if (!ok) return false; } $("newWorkflowBackdrop").hidden = true; state.newWorkflowDirty = false; return true; }
async function confirmNewWorkflow() {
  const name = $("newWorkflowName").value.trim(); if (!name) { $("newWorkflowHint").textContent = "Workflow name is required."; $("newWorkflowHint").classList.add("error"); return; }
  try { const result = await api("/api/studio/workflow/create", { method: "POST", body: JSON.stringify({ project: state.project?.path || "", name, destination: $("newWorkflowDestination").value, folder: $("newWorkflowFolder").value }) }); closeNewWorkflowModal(true); state.studioSourceKind = "workflow"; await refreshStudioFiles({ force: true }); const item = (state.studioFiles.workflows || []).find((row) => row.id === result.item.id) || result.item; if (item) await openStudioFile(item); showToast(`Workflow ${result.file.name} created`); }
  catch (error) { $("newWorkflowHint").textContent = error.message; $("newWorkflowHint").classList.add("error"); showActionError(error.message, "Workflow creation failed"); }
}
function openNewPromptModal() {
  if (!state.studioGuard.editable) return setStudioStatus("Stop active Runtime before creating Prompt.", true);
  state.newPromptDirty = false; $("newPromptName").value = ""; $("newPromptDestination").value = "custom"; fillCustomFolderSelect("prompt", "newPromptFolder"); $("newPromptFolderCreateRow").hidden = true; $("newPromptFolderName").value = ""; syncCustomFolderVisibility("prompt"); $("newPromptDestination").querySelector('option[value="project"]').disabled = !state.project; $("newPromptHint").textContent = ""; $("newPromptHint").classList.remove("error"); $("newPromptBackdrop").hidden = false; setTimeout(() => $("newPromptName").focus(), 0);
}
async function closeNewPromptModal(force = false) { if ($("newPromptBackdrop").hidden) return true; if (!force && state.newPromptDirty) { const ok = await confirmDialog({ title: "Discard new Prompt?", message: "Discard this unsaved Prompt draft?", confirmLabel: "Discard Prompt", danger: true }); if (!ok) return false; } $("newPromptBackdrop").hidden = true; state.newPromptDirty = false; return true; }
async function confirmNewPrompt() {
  const name = $("newPromptName").value.trim(); if (!name) { $("newPromptHint").textContent = "Prompt name is required."; $("newPromptHint").classList.add("error"); return; }
  try { const result = await api("/api/studio/prompt/create", { method: "POST", body: JSON.stringify({ project: state.project?.path || "", name, destination: $("newPromptDestination").value, folder: $("newPromptFolder").value }) }); closeNewPromptModal(true); state.studioSourceKind = "prompt"; await refreshStudioFiles({ force: true }); const item = (state.studioFiles.prompts || []).find((row) => row.id === result.item.id) || result.item; if (item) await openStudioFile(item); showToast(`Prompt ${result.file.name} created`); }
  catch (error) { $("newPromptHint").textContent = error.message; $("newPromptHint").classList.add("error"); showActionError(error.message, "Prompt creation failed"); }
}
function openImportAssetModal() {
  if (!state.studioGuard.editable) return setStudioStatus("Stop active Runtime before importing.", true);
  const kind = state.studioSourceKind; state.importAssetDirty = false; $("importAssetTitle").textContent = `Import ${kind === "prompt" ? "Prompt" : "Workflow"}`; $("importAssetName").value = ""; $("importAssetContent").value = ""; $("importAssetFile").value = ""; $("importAssetFileName").textContent = "No file selected"; $("importAssetDestination").value = "custom"; $("importAssetDestination").querySelector('option[value="project"]').disabled = !state.project; $("importAssetHint").textContent = ""; $("importAssetHint").classList.remove("error"); $("importAssetPreview").textContent = "Choose a file or paste content."; $("importAssetBackdrop").hidden = false;
}
async function closeImportAssetModal(force = false) { if ($("importAssetBackdrop").hidden) return true; if (!force && state.importAssetDirty) { const ok = await confirmDialog({ title: "Discard import?", message: "Discard the selected file and pasted import content?", confirmLabel: "Discard Import", danger: true }); if (!ok) return false; } $("importAssetBackdrop").hidden = true; state.importAssetDirty = false; return true; }
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
  try { const result = await api("/api/studio/import", { method: "POST", body: JSON.stringify({ project: state.project?.path || "", kind, name: parsed.name || $("importAssetName").value.trim(), content: parsed.content, destination: $("importAssetDestination").value }) }); closeImportAssetModal(true); await refreshStudioFiles({ force: true }); const list = kind === "prompt" ? state.studioFiles.prompts : state.studioFiles.workflows; const item = (list || []).find((row) => row.id === result.item.id) || result.item; if (item) await openStudioFile(item); showToast(`${kind === "prompt" ? "Prompt" : "Workflow"} imported`); }
  catch (error) { $("importAssetHint").textContent = error.message; $("importAssetHint").classList.add("error"); $("importAssetPreview").textContent = error.message; showActionError(error.message, "Import failed"); }
}
async function exportStudioAsset() {
  if (!state.studioFile) return;
  try { const data = await api(`/api/studio/export?id=${encodeURIComponent(state.studioFile.id)}${projectQuery()}`); const name = String(data.name || (data.kind === "prompt" ? "prompt.md" : "workflow.yaml")); const ext = name.toLowerCase().split(".").pop(); const mime = ext === "md" ? "text/markdown;charset=utf-8" : (ext === "yaml" || ext === "yml" ? "application/yaml;charset=utf-8" : "text/plain;charset=utf-8"); const blob = new Blob([String(data.content ?? "")], { type: mime }); const url = URL.createObjectURL(blob); const a = document.createElement("a"); a.href = url; a.download = name; document.body.appendChild(a); a.click(); a.remove(); URL.revokeObjectURL(url); showToast(`${data.kind === "prompt" ? "Prompt" : "Workflow"} exported`); }
  catch (error) { setStudioStatus(error.message, true); showActionError(error.message, "Export failed"); }
}
async function deleteStudioAsset() {
  if (!state.studioFile || state.studioFile.readonly) return; const current = state.studioFile; const label = current.kind === "prompt" ? "Prompt" : "Workflow";
  if (!(await confirmDialog({ title: `Delete ${label}?`, message: `Delete ${current.name}?${current.kind === "prompt" ? " Deletion is blocked if any Workflow Stage still uses this Prompt." : ""}`, confirmLabel: `Delete ${label}`, danger: true }))) return;
  try { await api("/api/studio/delete", { method: "POST", body: JSON.stringify({ id: current.id, project: state.project?.path || "" }) }); clearStudioEditor(); await refreshStudioFiles({ force: true }); showToast(`${label} deleted`); }
  catch (error) { setStudioStatus(error.message, true); showActionError(error.message, `${label} deletion failed`); }
}

async function toggleWorkflowVisibility() {
  const item = state.studioFile; if (!item || item.kind !== "workflow") return;
  try {
    const updated = await api("/api/studio/visibility", { method: "POST", body: JSON.stringify({ id: item.id, project: state.project?.path || "", hidden: !item.hidden }) });
    state.studioFile = { ...item, ...updated };
    const row = (state.studioFiles.workflows || []).find((entry) => entry.id === item.id); if (row) Object.assign(row, updated);
    renderStudioFiles(); renderWorkflowPicker(); renderStudioVisibilityBadge(); updateDirtyState(); closeStudioAssetMenu();
    showToast(updated.hidden ? "Workflow hidden from Chat" : "Workflow visible in Chat");
  } catch (error) { showActionError(error.message, "Workflow visibility update failed"); }
}
function closeStudioAssetMenu() { const menu = $("studioAssetMenu"), button = $("studioAssetMenuButton"); if (!menu || !button) return; menu.hidden = true; button.setAttribute("aria-expanded", "false"); }
function toggleStudioAssetMenu() { const menu = $("studioAssetMenu"), button = $("studioAssetMenuButton"); if (!menu || !button || button.disabled) return; const open = menu.hidden; menu.hidden = !open; button.setAttribute("aria-expanded", String(open)); }
async function renameStudioAsset() {
  closeStudioAssetMenu(); const current = state.studioFile; if (!current || current.readonly || !state.studioGuard.editable) return; if (!(await confirmDiscardStudio())) return;
  const label = current.kind === "prompt" ? "Prompt" : "Workflow"; const name = await inputDialog({ title: `Rename ${label}`, message: current.kind === "prompt" ? "Referenced Prompts must be unlinked before rename." : "Rename keeps the file in the same Custom / Project scope.", label: `${label} name`, value: current.name, confirmLabel: "Rename" }); if (!name || name === current.name) return;
  try { const result = await api("/api/studio/rename", { method: "POST", body: JSON.stringify({ id: current.id, project: state.project?.path || "", name }) }); await refreshStudioFiles({ force: true }); const list = result.item.kind === "prompt" ? state.studioFiles.prompts : state.studioFiles.workflows; const item = list.find((row) => row.id === result.item.id) || result.item; await openStudioFile(item); showToast(`${label} renamed`); }
  catch (error) { setStudioStatus(error.message, true); showActionError(error.message, `${label} rename failed`); }
}
async function duplicateStudioAsset() {
  closeStudioAssetMenu(); const current = state.studioFile; if (!current || !state.studioGuard.editable) return; if (!(await confirmDiscardStudio())) return;
  const label = current.kind === "prompt" ? "Prompt" : "Workflow", destination = window.StudioSupport.duplicateDestination(current), suggestion = window.StudioSupport.duplicateName(current.name); const name = await inputDialog({ title: `Duplicate ${label}`, message: `Create an independent ${destination} copy. The source file is not modified.`, label: `${label} name`, value: suggestion, confirmLabel: "Duplicate" }); if (!name) return;
  try { const result = await api("/api/studio/duplicate", { method: "POST", body: JSON.stringify({ id: current.id, project: state.project?.path || "", name }) }); await refreshStudioFiles({ force: true }); const list = result.item.kind === "prompt" ? state.studioFiles.prompts : state.studioFiles.workflows; const item = list.find((row) => row.id === result.item.id) || result.item; await openStudioFile(item); showToast(`${label} duplicated to ${result.item.group}`); }
  catch (error) { setStudioStatus(error.message, true); showActionError(error.message, `${label} duplicate failed`); }
}


// ------------------------------ AI Workflow Builder page ------------------------------
function clearGenerateWorkflowPoll() { if (state.generateWorkflowPollStop) state.generateWorkflowPollStop(); state.generateWorkflowPollStop = null; if (state.generateWorkflowPollTimer) clearTimeout(state.generateWorkflowPollTimer); state.generateWorkflowPollTimer = 0; }
function fillGenerateWorkflowBackends() {
  const select = $("generateWorkflowBackend"); if (!select) return; select.innerHTML = "";
  const rows = [{ value: "", label: state.defaultBackend ? `Default · ${state.defaultBackend}` : "Default backend" }, ...state.backends.map((name) => ({ value: name, label: name }))];
  for (const row of rows) { const option = document.createElement("option"); option.value = row.value; option.textContent = row.label; select.appendChild(option); }
  const preferred = String(state.preferences?.builderBackend || $("backend")?.value || ""); select.value = [...select.options].some((o) => o.value === preferred) ? preferred : "";
}
async function copyWorkflowWorkspace(value) {
  const text = String(value || "").trim();
  if (!text || text === "—" || text === "Created after Generate") return;
  try {
    if (navigator.clipboard?.writeText) await navigator.clipboard.writeText(text);
    else throw new Error("Clipboard API unavailable");
  } catch (_) {
    const helper = document.createElement("textarea"); helper.value = text; helper.setAttribute("readonly", ""); helper.style.position = "fixed"; helper.style.opacity = "0"; document.body.appendChild(helper); helper.select();
    const copied = document.execCommand("copy"); helper.remove(); if (!copied) { showToast("Unable to copy temporary workspace", "error", 3200); return; }
  }
  showToast("Temporary workspace copied");
}
function bindWorkflowWorkspaceCopy(node, value) {
  if (!node) return;
  const text = String(value || "").trim(); const copyable = !!text && text !== "—" && text !== "Created after Generate";
  node.classList.toggle("workspace-copy-ready", copyable); node.tabIndex = copyable ? 0 : -1; node.setAttribute("role", copyable ? "button" : "presentation");
  node.title = copyable ? `${text} · Click to copy` : text;
  node.onclick = copyable ? () => copyWorkflowWorkspace(text) : null;
  node.onkeydown = copyable ? (event) => { if (event.key === "Enter" || event.key === " ") { event.preventDefault(); copyWorkflowWorkspace(text); } } : null;
}
function setGenerateWorkflowWorkspace(path = "", pattern = "") {
  if (pattern) state.generateWorkflowWorkspacePattern = String(pattern);
  state.generateWorkflowWorkspace = String(path || "");
  const preview = state.generateWorkflowWorkspace || state.generateWorkflowWorkspacePattern || "Created after Generate";
  if ($("generateWorkflowWorkspacePreview")) { $("generateWorkflowWorkspacePreview").textContent = preview; bindWorkflowWorkspaceCopy($("generateWorkflowWorkspacePreview"), preview); }
  for (const id of ["generateWorkflowRunningWorkspace", "generateWorkflowReadyWorkspace"]) {
    if (!$(id)) continue; const value = state.generateWorkflowWorkspace || "—"; $(id).textContent = value; bindWorkflowWorkspaceCopy($(id), value);
  }
}
function resetGenerateWorkflowState({ keepRequest = false } = {}) {
  clearGenerateWorkflowPoll(); const request = keepRequest ? (state.generateWorkflowRequestText || $("generateWorkflowRequest")?.value || "") : "";
  state.generateWorkflowDirty = false; state.generateWorkflowJobId = ""; state.generateWorkflowPhase = "idle"; state.generateWorkflowDraft = null; state.generateWorkflowPromptIndex = 0; state.generateWorkflowReviewTab = "visual"; state.generateWorkflowRequestText = request; state.generateWorkflowWorkspace = "";
  if ($("generateWorkflowRequest")) $("generateWorkflowRequest").value = request;
  if ($("generateWorkflowPreview")) $("generateWorkflowPreview").value = "";
  if ($("generateDraftPromptTextarea")) $("generateDraftPromptTextarea").value = "";
  if ($("generateWorkflowFailure")) $("generateWorkflowFailure").textContent = "";
  if ($("generateWorkflowHint")) { $("generateWorkflowHint").textContent = ""; $("generateWorkflowHint").classList.remove("error"); }
  if ($("generateDraftDirtyHint")) $("generateDraftDirtyHint").hidden = true;
  setGenerateWorkflowWorkspace("", state.generateWorkflowWorkspacePattern);
}
function showWorkflowStudioPage() {
  $("workflowGeneratorPage").hidden = true; $("workflowStudioPage").hidden = false;
  // Generator is a temporary page layered over Studio. Re-render the cached
  // catalog immediately so returning from Discard/Cancel never shows an empty
  // Workflow list while the server refresh is in flight.
  renderStudioFiles(); renderWorkflowPicker(); renderStudioPanels();
}
async function restoreWorkflowStudioAfterGenerator() {
  showWorkflowStudioPage();
  await refreshStudioFiles({ force: true });
}
function showWorkflowGeneratorPage() {
  state.view = "workflow"; $("chatView").hidden = true; $("workflowView").hidden = false; $("workflowNav").classList.add("active"); $("chatNav").classList.remove("active");
  $("workflowStudioPage").hidden = true; $("workflowGeneratorPage").hidden = false;
}
function setGenerateWorkflowPhase(phase) {
  state.generateWorkflowPhase = phase; const building = ["running", "cancelling"].includes(phase);
  $("generateWorkflowForm").hidden = phase !== "form";
  $("generateWorkflowRunning").hidden = !building;
  $("generateWorkflowReady").hidden = phase !== "ready";
  $("generateWorkflowFailed").hidden = phase !== "failed";
  $("generateWorkflowPageBadge").hidden = phase !== "ready";
  const titles = { form: ["Generate Workflow with AI", "Describe the Workflow you want. Generate creates a temporary Draft only."], running: ["Generating Workflow", "AI is building and validating a new temporary Draft."], cancelling: ["Cancelling Workflow", "Stopping the current generation and cleaning temporary runtime state."], ready: ["Review generated Workflow", "Review or edit the Draft. Save is the only action that creates a real Workflow."], failed: ["Workflow generation failed", "Nothing was added to Custom or Project."] };
  const [title, subtitle] = titles[phase] || titles.form; $("generateWorkflowPageTitle").textContent = title; $("generateWorkflowPageSubtitle").textContent = subtitle;
  $("generateWorkflowBack").disabled = phase === "cancelling";
  applyStudioGuardToDialogs();
}
function flowNameFromDraft(item) { if (typeof item === "string") return item; if (item && typeof item === "object") return String(item.stage || item.name || ""); return ""; }
function renderGeneratedDraftFlow() {
  const root = $("generateDraftFlowList"); if (!root) return; root.innerHTML = ""; const visual = state.generateWorkflowDraft?.visual || {}; const stages = new Map((visual.stages || []).map((row) => [row.name, row])); const flow = visual.flow || [];
  if (!flow.length) { const empty = document.createElement("div"); empty.className = "designer-empty-state"; empty.textContent = "No flow steps found in the validated Draft."; root.appendChild(empty); return; }
  flow.forEach((item, index) => { const name = flowNameFromDraft(item), cfg = stages.get(name) || {}; const card = document.createElement("article"); card.className = "visual-flow-card workflow-generator-flow-card"; const number = document.createElement("span"); number.className = "visual-flow-index"; number.textContent = String(index + 1); const copy = document.createElement("div"); copy.className = "visual-flow-copy"; const strong = document.createElement("strong"); strong.textContent = cfg.status || name || "Stage"; strong.title = strong.textContent; const small = document.createElement("small"); small.textContent = `${name || "Stage"} · ${cfg.type || "base"}`; copy.append(strong, small); card.append(number, copy); root.appendChild(card); });
}
function renderGeneratedDraftPrompts() {
  const root = $("generateWorkflowPromptList"), editor = $("generateDraftPromptTextarea"), label = $("generateDraftPromptName"); if (!root || !editor || !label) return; root.innerHTML = ""; const prompts = state.generateWorkflowDraft?.prompts || [];
  if (!prompts.length) { const empty = document.createElement("div"); empty.className = "designer-empty-state"; empty.textContent = "No generated Prompt files."; root.appendChild(empty); editor.value = ""; editor.disabled = true; label.textContent = "Prompt"; if ($("generateWorkflowEditPrompt")) $("generateWorkflowEditPrompt").disabled = true; if ($("generateDraftPromptTab")) $("generateDraftPromptTab").disabled = true; return; }
  if ($("generateWorkflowEditPrompt")) $("generateWorkflowEditPrompt").disabled = false; if ($("generateDraftPromptTab")) $("generateDraftPromptTab").disabled = false;
  state.generateWorkflowPromptIndex = Math.max(0, Math.min(state.generateWorkflowPromptIndex, prompts.length - 1));
  prompts.forEach((prompt, index) => { const button = document.createElement("button"); button.type = "button"; button.className = "studio-file-item designer-workflow-pill"; if (index === state.generateWorkflowPromptIndex) button.classList.add("active"); const name = document.createElement("strong"); name.textContent = prompt.name || `Prompt ${index + 1}`; const meta = document.createElement("small"); meta.textContent = "Temporary Draft"; button.append(name, meta); button.onclick = () => { state.generateWorkflowPromptIndex = index; renderGeneratedDraftPrompts(); }; root.appendChild(button); });
  const selected = prompts[state.generateWorkflowPromptIndex]; editor.disabled = false; editor.value = selected.content || ""; label.textContent = selected.name || "Prompt";
}
function setGeneratedDraftTab(tab) {
  state.generateWorkflowReviewTab = tab; const names = ["visual", "yaml", "prompt"];
  for (const name of names) { const key = name[0].toUpperCase() + name.slice(1); $(`generateDraft${key}Tab`).classList.toggle("active", name === tab); $(`generateDraft${key}Panel`).hidden = name !== tab; }
}
function focusGeneratedDraftEditor(tab) {
  setGeneratedDraftTab(tab);
  requestAnimationFrame(() => {
    const target = tab === "prompt" ? $("generateDraftPromptTextarea") : $("generateWorkflowPreview");
    if (target && !target.disabled) target.focus();
  });
}
function markGeneratedDraftDirty() {
  if (state.generateWorkflowPhase !== "ready") return; state.generateWorkflowDirty = true; $("generateDraftDirtyHint").hidden = false; $("generateWorkflowValidation").textContent = "Draft modified · validate to refresh Visual before Save"; $("generateWorkflowValidation").classList.remove("success");
}
function generatedDraftPayload() { return { workflow: $("generateWorkflowPreview").value, prompts: (state.generateWorkflowDraft?.prompts || []).map((row) => ({ name: row.name, content: row.content || "" })) }; }
function renderGeneratedDraft(data) {
  const draft = data?.draft || {}; state.generateWorkflowDraft = { workflow: draft.workflow || "", prompts: Array.isArray(draft.prompts) ? draft.prompts.map((row) => ({ name: row.name || "Prompt", content: row.content || "" })) : [], visual: draft.visual || { stages: [], flow: [] }, validation: draft.validation || "" }; state.generateWorkflowPromptIndex = 0; state.generateWorkflowDirty = false;
  $("generateWorkflowPreview").value = state.generateWorkflowDraft.workflow; $("generateDraftDirtyHint").hidden = true; $("generateWorkflowValidation").textContent = "Validation PASS · Workflow dry-run matrix completed"; $("generateWorkflowValidation").classList.add("success"); renderGeneratedDraftFlow(); renderGeneratedDraftPrompts(); setGeneratedDraftTab("visual");
}
function hydrateActiveGenerateWorkflow(data, { openPage = true } = {}) {
  if (!data?.active || !data.job_id) return false;
  resetGenerateWorkflowState(); fillGenerateWorkflowBackends();
  state.generateWorkflowJobId = String(data.job_id); state.generateWorkflowRequestText = String(data.request || "");
  $("generateWorkflowRequest").value = state.generateWorkflowRequestText;
  if ([...$("generateWorkflowBackend").options].some((option) => option.value === String(data.backend || ""))) $("generateWorkflowBackend").value = String(data.backend || "");
  setGenerateWorkflowWorkspace(data.workspace || "", data.workspace_pattern || "");
  if (openPage) showWorkflowGeneratorPage();
  const phase = String(data.state || "running");
  if (phase === "ready") { renderGeneratedDraft(data); setGenerateWorkflowPhase("ready"); return true; }
  if (phase === "failed") { $("generateWorkflowFailure").textContent = data.message || "Workflow Builder failed."; setGenerateWorkflowPhase("failed"); return true; }
  $("generateWorkflowRunningStatus").textContent = data.message || "AI is generating Workflow draft…";
  setGenerateWorkflowPhase(phase === "cancelling" ? "cancelling" : "running"); startGenerateWorkflowPoll(); return true;
}
async function restoreActiveWorkflowGenerator({ openPage = true } = {}) {
  try { const data = await api("/api/studio/generate/active"); return hydrateActiveGenerateWorkflow(data, { openPage }); }
  catch (_) { return false; }
}
async function pollGenerateWorkflow() {
  if (!state.generateWorkflowJobId) return;
  try {
    const data = await api(`/api/studio/generate/status?job_id=${encodeURIComponent(state.generateWorkflowJobId)}`);
    setGenerateWorkflowWorkspace(data.workspace || state.generateWorkflowWorkspace);
    if (data.state === "ready") { clearGenerateWorkflowPoll(); renderGeneratedDraft(data); setGenerateWorkflowPhase("ready"); await refreshStudioGuard(); return; }
    if (data.state === "cancelled") { clearGenerateWorkflowPoll(); try { await api("/api/studio/generate/discard", { method: "POST", body: JSON.stringify({ job_id: state.generateWorkflowJobId }) }); } catch (_) {} resetGenerateWorkflowState(); await restoreWorkflowStudioAfterGenerator(); showToast("Workflow generation cancelled"); await refreshStudioGuard(); return; }
    if (data.state === "failed") { clearGenerateWorkflowPoll(); $("generateWorkflowFailure").textContent = data.message || "Workflow Builder failed."; setGenerateWorkflowPhase("failed"); await refreshStudioGuard(); return; }
    if (data.state === "cancelling") setGenerateWorkflowPhase("cancelling"); else if (state.generateWorkflowPhase !== "running") setGenerateWorkflowPhase("running");
    $("generateWorkflowRunningStatus").textContent = data.message || "AI is generating Workflow draft…";
  } catch (error) { clearGenerateWorkflowPoll(); $("generateWorkflowFailure").textContent = error.message; setGenerateWorkflowPhase("failed"); }
}
function startGenerateWorkflowPoll() {
  clearGenerateWorkflowPoll();
  let stopped = false;
  const tick = async () => {
    if (stopped || !state.generateWorkflowJobId) return;
    await pollGenerateWorkflow();
    if (!stopped && state.generateWorkflowJobId && ["running", "cancelling"].includes(state.generateWorkflowPhase)) {
      state.generateWorkflowPollTimer = window.setTimeout(tick, 800);
    }
  };
  state.generateWorkflowPollStop = () => { stopped = true; };
  tick();
}
async function openGenerateWorkflowPage() {
  if (!(await confirmDiscardStudio())) return;
  fillGenerateWorkflowBackends(); showWorkflowGeneratorPage(); $("generateWorkflowHint").classList.remove("error"); $("generateWorkflowHint").textContent = "Checking Workflow Builder…";
  try {
    const active = await api("/api/studio/generate/active");
    if (hydrateActiveGenerateWorkflow(active)) return;
    resetGenerateWorkflowState(); fillGenerateWorkflowBackends(); showWorkflowGeneratorPage(); setGenerateWorkflowPhase("form");
    const info = await api("/api/studio/draft"); if (!info.available) throw new Error(info.message || "AI Workflow Builder is unavailable.");
    setGenerateWorkflowWorkspace("", info.workspace_pattern || info.workspace_root || "");
    $("generateWorkflowHint").textContent = "No Project is required; name and destination are chosen only when you Save. Only one Generator job can exist at a time; closing the page does not stop it."; setTimeout(() => $("generateWorkflowRequest").focus(), 0);
  }
  catch (error) { $("generateWorkflowHint").textContent = error.message; $("generateWorkflowHint").classList.add("error"); setGenerateWorkflowPhase("form"); showActionError(error.message, "Workflow Builder unavailable"); }
}
function closeGenerateWorkflowSaveModal() { $("generateWorkflowSaveBackdrop").hidden = true; }
async function discardGenerateWorkflowDraft({ confirm = true, returnToStudio = true } = {}) {
  if (confirm) { const ok = await confirmDialog({ title: "Discard generated Workflow?", message: "This Draft has not been saved. Discard the generated Workflow and Prompt files?", confirmLabel: "Discard Draft", danger: true }); if (!ok) return false; }
  if (state.generateWorkflowJobId) { try { await api("/api/studio/generate/discard", { method: "POST", body: JSON.stringify({ job_id: state.generateWorkflowJobId }) }); } catch (error) { showActionError(error.message, "Discard draft failed"); return false; } }
  resetGenerateWorkflowState(); if (returnToStudio) await restoreWorkflowStudioAfterGenerator(); showToast("Workflow draft discarded"); return true;
}
async function cancelGenerateWorkflow() {
  if (!state.generateWorkflowJobId) return false; const ok = await confirmDialog({ title: "Cancel Workflow generation?", message: "Stop the current AI generation and discard its temporary files?", confirmLabel: "Cancel Generation", danger: true }); if (!ok) return false;
  try { await api("/api/studio/generate/cancel", { method: "POST", body: JSON.stringify({ job_id: state.generateWorkflowJobId }) }); setGenerateWorkflowPhase("cancelling"); $("generateWorkflowRunningStatus").textContent = "Cancelling Workflow generation…"; startGenerateWorkflowPoll(); return true; }
  catch (error) { showActionError(error.message, "Cancel generation failed"); return false; }
}
async function leaveGenerateWorkflowPage() {
  if ($("workflowGeneratorPage").hidden) return true;
  if (["running", "cancelling"].includes(state.generateWorkflowPhase)) { await cancelGenerateWorkflow(); return false; }
  if (state.generateWorkflowPhase === "ready") return await discardGenerateWorkflowDraft();
  if (state.generateWorkflowPhase === "failed" && state.generateWorkflowJobId) return await discardGenerateWorkflowDraft({ confirm: false });
  const request = $("generateWorkflowRequest").value.trim(); if (request) { const ok = await confirmDialog({ title: "Discard Workflow request?", message: "Leave AI Workflow Builder and discard this unsent Prompt?", confirmLabel: "Discard Request", danger: true }); if (!ok) return false; }
  resetGenerateWorkflowState(); await restoreWorkflowStudioAfterGenerator(); return true;
}
async function confirmGenerateWorkflow() {
  const request = $("generateWorkflowRequest").value.trim(); if (!request) { $("generateWorkflowHint").textContent = "Describe the Workflow you want before Generate."; $("generateWorkflowHint").classList.add("error"); return; }
  state.generateWorkflowRequestText = request; state.generateWorkflowDirty = false; $("generateWorkflowHint").classList.remove("error"); $("generateWorkflowRunningStatus").textContent = "Starting Workflow Builder…"; setGenerateWorkflowPhase("running");
  try {
    const result = await api("/api/studio/generate", { method: "POST", body: JSON.stringify({ request, backend: $("generateWorkflowBackend").value }) });
    if (result.existing) { const active = await api("/api/studio/generate/active"); hydrateActiveGenerateWorkflow(active); return; }
    state.generateWorkflowJobId = result.job_id; setGenerateWorkflowWorkspace(result.workspace || ""); $("generateWorkflowRunningStatus").textContent = result.message || "AI is generating Workflow draft…"; startGenerateWorkflowPoll();
  }
  catch (error) { $("generateWorkflowFailure").textContent = error.message; setGenerateWorkflowPhase("failed"); showActionError(error.message, "Workflow generation failed"); }
}
async function regenerateWorkflowDraft() {
  const ok = await confirmDialog({ title: "Generate a new Draft?", message: "Discard the current generated Draft and return to the Prompt. The next Generate starts a new AI run.", confirmLabel: "New Draft", danger: true }); if (!ok) return;
  const request = state.generateWorkflowRequestText || $("generateWorkflowRequest").value; if (state.generateWorkflowJobId) { try { await api("/api/studio/generate/discard", { method: "POST", body: JSON.stringify({ job_id: state.generateWorkflowJobId }) }); } catch (error) { showActionError(error.message, "Discard draft failed"); return; } }
  resetGenerateWorkflowState({ keepRequest: true }); state.generateWorkflowRequestText = request; $("generateWorkflowRequest").value = request; fillGenerateWorkflowBackends(); setGenerateWorkflowPhase("form"); setTimeout(() => $("generateWorkflowRequest").focus(), 0);
}
async function validateGeneratedWorkflowDraft() {
  if (!state.generateWorkflowJobId || state.generateWorkflowPhase !== "ready") return; $("generateWorkflowValidate").disabled = true; $("generateWorkflowValidation").textContent = "Validating current Draft…";
  try { const result = await api("/api/studio/generate/validate", { method: "POST", body: JSON.stringify({ job_id: state.generateWorkflowJobId, ...generatedDraftPayload() }) }); renderGeneratedDraft({ draft: result.draft }); showToast("Workflow draft validation passed"); }
  catch (error) { $("generateWorkflowValidation").textContent = error.message; $("generateWorkflowValidation").classList.remove("success"); showActionError(error.message, "Draft validation failed"); }
  finally { $("generateWorkflowValidate").disabled = false; }
}
function openGenerateWorkflowSaveModal() {
  if (!state.generateWorkflowJobId || state.generateWorkflowPhase !== "ready") return; $("generateWorkflowName").value = ""; $("generateWorkflowDestination").value = "custom"; $("generateWorkflowDestination").querySelector('option[value="project"]').disabled = !state.project; $("generateWorkflowSaveHint").textContent = state.generateWorkflowDirty ? "Draft was modified. Validate & Save will revalidate the current YAML and Prompts." : "Save will revalidate this Draft before publishing."; $("generateWorkflowSaveHint").classList.remove("error"); $("generateWorkflowSaveBackdrop").hidden = false; setTimeout(() => $("generateWorkflowName").focus(), 0);
}
async function saveGenerateWorkflowDraft() {
  const name = $("generateWorkflowName").value.trim(); if (!name) { $("generateWorkflowSaveHint").textContent = "Workflow name is required."; $("generateWorkflowSaveHint").classList.add("error"); return; }
  $("generateWorkflowSaveConfirm").disabled = true; $("generateWorkflowSaveHint").textContent = "Validating current Draft and publishing…"; $("generateWorkflowSaveHint").classList.remove("error");
  try { const result = await api("/api/studio/generate/save", { method: "POST", body: JSON.stringify({ project: state.project?.path || "", job_id: state.generateWorkflowJobId, name, destination: $("generateWorkflowDestination").value, ...generatedDraftPayload() }) }); closeGenerateWorkflowSaveModal(); resetGenerateWorkflowState(); showWorkflowStudioPage(); state.studioSourceKind = "workflow"; await refreshStudioFiles({ force: true }); const item = (state.studioFiles.workflows || []).find((row) => row.id === result.item?.id || row.path === result.workflow) || result.item; if (item) await openStudioFile(item); showToast(result.message || "Workflow saved"); }
  catch (error) { $("generateWorkflowSaveHint").textContent = error.message; $("generateWorkflowSaveHint").classList.add("error"); showActionError(error.message, "Workflow save failed"); }
  finally { $("generateWorkflowSaveConfirm").disabled = false; }
}

// ------------------------------ Add Project modal ------------------------------
function openProjectModal() { $("projectPathInput").value = ""; $("projectModalHint").textContent = window.I18n?.getLanguage?.() === "en" ? "Paste a path directly, or use Browse to choose a folder." : "可直接貼上路徑，或使用 Browse 選擇資料夾。"; $("projectModalHint").classList.remove("error"); $("projectModalBackdrop").hidden = false; setTimeout(() => $("projectPathInput").focus(), 0); }
function closeProjectModal() { $("projectModalBackdrop").hidden = true; }
async function browseProject() {
  $("projectModalHint").textContent = "Opening folder picker…";
  try { const result = await api("/api/projects/pick", { method: "POST", body: "{}" }); if (!result.cancelled && result.path) { $("projectPathInput").value = result.path; $("projectModalHint").textContent = t("project.folder_selected", "Folder selected. Click Open Project to add it."); } else $("projectModalHint").textContent = t("project.folder_cancelled", "Folder selection cancelled."); }
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
$("visualModeButton").onclick = () => setStudioMode("visual"); $("yamlModeButton").onclick = () => setStudioMode("yaml"); $("yamlWorkflowSource").onclick = () => setStudioSource("workflow"); $("yamlPromptSource").onclick = () => setStudioSource("prompt"); $("studioSearchInput").oninput = () => { state.studioFilters[state.studioSourceKind] = $("studioSearchInput").value; renderStudioFiles(); }; $("studioSearchClear").onclick = () => { state.studioFilters[state.studioSourceKind] = ""; renderStudioFiles(); $("studioSearchInput").focus(); };
$("studioTextarea").addEventListener("input", () => { updateLineNumbers(); updateDirtyState(); scheduleSyntaxCheck(); }); $("studioTextarea").addEventListener("keydown", handleEditorKeydown); $("studioTextarea").addEventListener("scroll", () => { $("studioLineNumbers").scrollTop = $("studioTextarea").scrollTop; });
$("studioPromptTextarea").addEventListener("input", () => { updateDirtyState(); scheduleSyntaxCheck(); }); $("studioPromptTextarea").addEventListener("keydown", handlePromptEditorKeydown);
$("saveStudioButton").onclick = saveStudio; $("toggleWorkflowVisibilityButton").onclick = toggleWorkflowVisibility; $("reloadStudioButton").onclick = reloadStudio; $("validateStudioButton").onclick = validateStudio; $("exportStudioButton").onclick = exportStudioAsset; $("deleteStudioButton").onclick = deleteStudioAsset; $("studioAssetMenuButton").onclick = (event) => { event.stopPropagation(); toggleStudioAssetMenu(); }; $("renameStudioButton").onclick = renameStudioAsset; $("duplicateStudioButton").onclick = duplicateStudioAsset; $("importAssetButton").onclick = openImportAssetModal; $("addFlowStepButton").onclick = openAddStageModal; $("newWorkflowButton").onclick = () => state.studioSourceKind === "prompt" ? openNewPromptModal() : openNewWorkflowModal();
$("newWorkflowClose").onclick = () => closeNewWorkflowModal(); $("newWorkflowCancel").onclick = () => closeNewWorkflowModal(); $("newWorkflowConfirm").onclick = confirmNewWorkflow; $("newWorkflowBackdrop").addEventListener("click", (e) => { if (e.target === $("newWorkflowBackdrop")) closeNewWorkflowModal(); }); $("newWorkflowBackdrop").addEventListener("input", () => { state.newWorkflowDirty = true; }); $("newWorkflowName").addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); confirmNewWorkflow(); } });
$("newPromptClose").onclick = () => closeNewPromptModal(); $("newPromptCancel").onclick = () => closeNewPromptModal(); $("newPromptConfirm").onclick = confirmNewPrompt; $("newPromptBackdrop").addEventListener("click", (e) => { if (e.target === $("newPromptBackdrop")) closeNewPromptModal(); }); $("newPromptBackdrop").addEventListener("input", () => { state.newPromptDirty = true; });
$("importAssetClose").onclick = () => closeImportAssetModal(); $("importAssetCancel").onclick = () => closeImportAssetModal(); $("importAssetConfirm").onclick = confirmImportAsset; $("importAssetChooseButton").onclick = () => $("importAssetFile").click(); $("importAssetFile").onchange = readImportAssetFile; $("importAssetBackdrop").addEventListener("click", (e) => { if (e.target === $("importAssetBackdrop")) closeImportAssetModal(); }); $("importAssetBackdrop").addEventListener("input", () => { state.importAssetDirty = true; });
$("addStageClose").onclick = () => closeAddStageModal(); $("addStageCancel").onclick = () => closeAddStageModal(); $("addStageConfirm").onclick = confirmAddStage; $("addStageType").onchange = () => { state.addStageDirty = true; updateAddStageType(); }; $("addStageBackdrop").addEventListener("click", (e) => { if (e.target === $("addStageBackdrop")) closeAddStageModal(); });
$("addStageBackdrop").addEventListener("input", (e) => { if (["INPUT", "TEXTAREA", "SELECT"].includes(e.target.tagName)) state.addStageDirty = true; });
$("generateWorkflowButton").onclick = openGenerateWorkflowPage;
$("generateWorkflowBack").onclick = () => leaveGenerateWorkflowPage();
$("generateWorkflowCancel").onclick = () => leaveGenerateWorkflowPage();
$("generateWorkflowConfirm").onclick = confirmGenerateWorkflow;
$("generateWorkflowStop").onclick = cancelGenerateWorkflow;
$("generateWorkflowDiscard").onclick = () => discardGenerateWorkflowDraft();
$("generateWorkflowRegenerate").onclick = regenerateWorkflowDraft;
$("generateWorkflowValidate").onclick = validateGeneratedWorkflowDraft;
$("generateWorkflowSave").onclick = openGenerateWorkflowSaveModal;
$("generateWorkflowEditYaml").onclick = () => focusGeneratedDraftEditor("yaml");
$("generateWorkflowEditPrompt").onclick = () => focusGeneratedDraftEditor("prompt");
$("generateDraftVisualTab").onclick = () => setGeneratedDraftTab("visual"); $("generateDraftYamlTab").onclick = () => focusGeneratedDraftEditor("yaml"); $("generateDraftPromptTab").onclick = () => focusGeneratedDraftEditor("prompt");
$("generateWorkflowPreview").addEventListener("input", markGeneratedDraftDirty);
$("generateDraftPromptTextarea").addEventListener("input", () => { const prompt = state.generateWorkflowDraft?.prompts?.[state.generateWorkflowPromptIndex]; if (prompt) prompt.content = $("generateDraftPromptTextarea").value; markGeneratedDraftDirty(); });
$("generateWorkflowRequest").addEventListener("input", () => { if (state.generateWorkflowPhase === "form") state.generateWorkflowDirty = !!$("generateWorkflowRequest").value.trim(); });
$("generateWorkflowBackend").addEventListener("change", () => { if (!state.preferences) state.preferences = loadUiPreferences(); state.preferences.builderBackend = $("generateWorkflowBackend").value; saveUiPreferences(); });
$("generateWorkflowFailedCancel").onclick = () => leaveGenerateWorkflowPage();
$("generateWorkflowRetry").onclick = async () => { const request = state.generateWorkflowRequestText || $("generateWorkflowRequest").value; if (state.generateWorkflowJobId) { try { await api("/api/studio/generate/discard", { method: "POST", body: JSON.stringify({ job_id: state.generateWorkflowJobId }) }); } catch (_) {} } resetGenerateWorkflowState({ keepRequest: true }); state.generateWorkflowRequestText = request; $("generateWorkflowRequest").value = request; fillGenerateWorkflowBackends(); setGenerateWorkflowPhase("form"); };
$("generateWorkflowSaveClose").onclick = closeGenerateWorkflowSaveModal; $("generateWorkflowSaveCancel").onclick = closeGenerateWorkflowSaveModal; $("generateWorkflowSaveConfirm").onclick = saveGenerateWorkflowDraft; $("generateWorkflowSaveBackdrop").addEventListener("click", (e) => { if (e.target === $("generateWorkflowSaveBackdrop")) closeGenerateWorkflowSaveModal(); });
$("workflowDropdownButton").onclick = (event) => { event.stopPropagation(); const menu = $("workflowDropdownMenu"); menu.hidden ? openWorkflowDropdown() : closeWorkflowDropdown(); };
$("backendDropdownButton").onclick = (event) => { event.stopPropagation(); const menu = $("backendDropdownMenu"); menu.hidden ? openBackendDropdown() : closeBackendDropdown(); };
function renderEnvironmentCheck(data) {
  const root = $("environmentCheckResult"); if (!root) return; root.hidden = false; root.innerHTML = "";
  const head = document.createElement("div"); head.className = `environment-check-summary ${data.status || ""}`; head.textContent = data.status === "pass" ? "Environment ready" : data.status === "warn" ? "Environment ready with warnings" : "Environment check failed"; root.appendChild(head);
  for (const item of data.checks || []) { const row = document.createElement("div"); row.className = `environment-check-row ${item.status || ""}`; const mark = document.createElement("strong"); mark.textContent = String(item.status || "").toUpperCase(); const copy = document.createElement("span"); copy.textContent = `${item.name}: ${item.detail}`; row.append(mark, copy); root.appendChild(row); }
}
async function checkEnvironment() {
  const button = $("environmentCheckButton"), result = $("environmentCheckResult"); if (!button) return; button.disabled = true; button.textContent = t("env.checking", "Checking…"); if (result) { result.hidden = false; result.textContent = t("env.checking_detail", "Checking local environment…"); }
  try { const data = await api("/api/environment/check"); renderEnvironmentCheck(data); showToast(data.ok ? t("env.completed", "Environment check completed") : t("env.failed", "Environment check found required failures")); }
  catch (error) { if (result) { result.hidden = false; result.textContent = error.message; } showActionError(error.message, "Environment check failed"); }
  finally { button.disabled = false; button.textContent = t("env.check", "Check environment"); }
}

document.addEventListener("click", (event) => {
  const menu = $("workflowDropdownMenu"), picker = $("workflowPicker"), backendMenu = $("backendDropdownMenu"), backendPicker = $("backendPicker");
  if (!picker?.contains(event.target) && !menu?.contains(event.target)) closeWorkflowDropdown();
  if (!backendPicker?.contains(event.target) && !backendMenu?.contains(event.target)) closeBackendDropdown();
  if (!event.target.closest?.(".project-tree") && !event.target.closest?.(".project-action-menu")) closeProjectMenus();
  if (!event.target.closest?.(".studio-asset-menu-wrap")) closeStudioAssetMenu();
  if (!$("optionsPanel").hidden && !$("optionsPanel").contains(event.target) && !$("optionsButton").contains(event.target) && !backendMenu?.contains(event.target)) closeOptionsPanel();
  if (!$("themePanel").hidden && !$("themePanel").contains(event.target) && !$("themeButton").contains(event.target)) closeThemePanel();
});
function closeOptionsPanel() { closeBackendDropdown(); $("optionsPanel").hidden = true; $("optionsButton").classList.remove("active"); $("optionsButton").setAttribute("aria-expanded", "false"); }
function toggleOptionsPanel() { const open = $("optionsPanel").hidden; if (!open) return closeOptionsPanel(); $("optionsPanel").hidden = false; $("optionsButton").classList.add("active"); $("optionsButton").setAttribute("aria-expanded", "true"); }
$("optionsButton").onclick = (event) => { event.stopPropagation(); toggleOptionsPanel(); };
$("optionsCloseButton").onclick = closeOptionsPanel;
$("environmentCheckButton").onclick = checkEnvironment;
$("themeButton").onclick = toggleThemePanel;
$("themeCloseButton").onclick = closeThemePanel;
document.querySelectorAll("[data-theme-option]").forEach((button) => { button.onclick = () => applyThemePreferences(button.dataset.themeOption, document.documentElement.dataset.appearancePreference || "system", { persist: true }); });
document.querySelectorAll("[data-appearance-option]").forEach((button) => { button.onclick = () => applyThemePreferences(document.documentElement.dataset.theme || "teal", button.dataset.appearanceOption, { persist: true }); });
document.querySelectorAll("[data-language-option]").forEach((button) => { button.onclick = () => { window.I18n?.setLanguage?.(button.dataset.languageOption, { persist: true }); renderThemeControls(); renderProjects(); }; });
window.addEventListener("app-language-changed", () => { renderThemeControls(); if (state?.projects) renderProjects(); });
if (systemColorScheme) { const onSystemAppearanceChanged = () => { if ((document.documentElement.dataset.appearancePreference || "system") === "system") applyThemePreferences(document.documentElement.dataset.theme || "teal", "system"); }; if (systemColorScheme.addEventListener) systemColorScheme.addEventListener("change", onSystemAppearanceChanged); else if (systemColorScheme.addListener) systemColorScheme.addListener(onSystemAppearanceChanged); }
applyThemePreferences(document.documentElement.dataset.theme || readThemePreference(), document.documentElement.dataset.appearancePreference || readAppearancePreference());
$("sendButton").onclick = sendMessage; $("messageInput").addEventListener("input", resizeComposerInput); $("messageInput").addEventListener("keydown", (event) => { if (event.key === "Enter" && !event.shiftKey) { event.preventDefault(); sendMessage(); } });
$("clearHistoryButton").onclick = async () => {
  if (!state.project || state.runtime?.running) return;
  const ok = await confirmDialog({ title: t("history.confirm_title", "Clear chat history?"), message: t("history.confirm_message", "Delete this Project's saved chat history?"), confirmLabel: t("history.clear", "Clear history"), danger: true });
  if (!ok) return;
  try {
    await api("/api/project/history/clear", { method: "POST", body: JSON.stringify(payload()) });
    state.historyPinnedToBottom = true;
    await refreshMessages({ forceFollow: true });
    showToast(t("history.cleared", "Chat history cleared"));
  } catch (error) { showActionError(error.message, "Clear history failed"); }
};
$("messages").addEventListener("scroll", () => { state.historyPinnedToBottom = historyNearBottom($("messages")); }, { passive: true });
$("browseValidatorButton").onclick = browseValidator;
$("clearValidatorButton").onclick = () => { $("validator").value = ""; rememberValidator($("workflowSelect")?.value || "", ""); updateValidatorPicker(); };
$("errorDetailsButton").onclick = showErrorDetails;
$("studioErrorDetailsButton").onclick = showStudioErrorDetails;
$("errorDetailsClose").onclick = closeErrorDetails;
$("errorDetailsOk").onclick = closeErrorDetails;
$("errorDetailsBackdrop").onclick = (event) => { if (event.target === $("errorDetailsBackdrop")) closeErrorDetails(); };
$("errorDetailsCopy").onclick = async () => { try { await navigator.clipboard.writeText(state.errorDetailsModalText || state.lastErrorDetail || state.studioErrorDetail || ""); showToast("Error details copied"); } catch (_) { showToast("Unable to copy error details", "error"); } };

$("stopButton").onclick = async () => { try { await api("/api/project/stop", { method: "POST", body: JSON.stringify(payload()) }); showToast("Stop requested"); setTimeout(refreshRuntime, 250); } catch (error) { $("errorText").textContent = error.message; showActionError(error.message, "Stop failed"); } };
$("resumeButton").onclick = async () => { try { await api("/api/project/resume", { method: "POST", body: JSON.stringify(payload()) }); showToast("Task continued"); setTimeout(refreshRuntime, 250); } catch (error) { $("errorText").textContent = error.message; showActionError(error.message, "Continue failed"); } };
$("resetButton").onclick = async () => {
  const ok = await confirmDialog({ title: "Reset stopped task?", message: "Discard resumable Runner state? UI task history and request snapshots are kept.", confirmLabel: "Reset", danger: true }); if (!ok) return;
  try { await api("/api/project/reset", { method: "POST", body: JSON.stringify(payload()) }); state.lastStream = ""; removeLiveCard(); await refreshRuntime(); showToast("Runtime reset"); } catch (error) { $("errorText").textContent = error.message; showActionError(error.message, "Reset failed"); }
};
$("rerunButton").onclick = async () => { try { await api("/api/project/rerun", { method: "POST", body: JSON.stringify(payload()) }); showToast("Task rerun started"); setTimeout(refreshRuntime, 250); } catch (error) { $("errorText").textContent = error.message; showActionError(error.message, "Rerun failed"); } };
window.addEventListener("keydown", (event) => { if (event.key !== "Escape") return; if (!$("errorDetailsBackdrop").hidden) return closeErrorDetails(); if (!$("themePanel").hidden) return closeThemePanel(); if (!$("backendDropdownMenu").hidden) return closeBackendDropdown(); if (!$("optionsPanel").hidden) return closeOptionsPanel(); if (!$("workflowDropdownMenu").hidden) return closeWorkflowDropdown(); if (document.querySelector(".project-action-menu:not([hidden])")) return closeProjectMenus(); if (document.querySelector(".designer-step-modal-box")) return closeStageEditor(); if (!$("generateWorkflowSaveBackdrop").hidden) return closeGenerateWorkflowSaveModal(); if (!$("addStageBackdrop").hidden) return closeAddStageModal(); if (!$("importAssetBackdrop").hidden) return closeImportAssetModal(); if (!$("newPromptBackdrop").hidden) return closeNewPromptModal(); if (!$("newWorkflowBackdrop").hidden) return closeNewWorkflowModal(); if (!$("workflowGeneratorPage").hidden) { leaveGenerateWorkflowPage(); return; } if (!$("projectModalBackdrop").hidden) return closeProjectModal(); });
window.addEventListener("beforeunload", (event) => { if (state.studioDirty || state.visualDirty || state.stageEditorDirty || state.generateWorkflowDirty) { event.preventDefault(); event.returnValue = ""; } });
state.preferences = loadUiPreferences(); showEmpty(); resizeComposerInput(); if (window.ResizeObserver) new ResizeObserver(syncComposerReserve).observe($("composePanel")); window.addEventListener("resize", () => {
  syncComposerReserve(); positionWorkflowDropdown(); if (!$("backendDropdownMenu").hidden) positionUpwardDropdown($("backendDropdownMenu"), $("backendDropdownButton"), $("backendDropdownMenu").children.length, 70); if (!$("themePanel").hidden) positionThemePanel();
  const menu = document.querySelector(".project-action-menu.project-action-menu-portal:not([hidden])"), owner = menu ? projectMenuOwners.get(menu) : null;
  if (menu && owner?.anchor) positionProjectMenu(menu, owner.anchor);
}); Promise.allSettled([refreshBackends(), loadProjects()]).then(() => restoreActiveWorkflowGenerator()); refreshPromptTags(); startNonOverlappingPoll(refreshRuntime, 1200, 6000); setInterval(animateRuntimeFrame, 1000); startNonOverlappingPoll(refreshProjectStatuses, 4000, 12000); startNonOverlappingPoll(refreshStudioGuard, 2500, 10000);
document.addEventListener("visibilitychange", () => { if (!document.hidden) Promise.allSettled([refreshRuntime(), refreshProjectStatuses(), refreshStudioGuard()]); });

$("newWorkflowDestination").onchange = () => syncCustomFolderVisibility("workflow");
$("newPromptDestination").onchange = () => syncCustomFolderVisibility("prompt");
$("newWorkflowFolderToggle").onclick = () => { $("newWorkflowFolderCreateRow").hidden = !$("newWorkflowFolderCreateRow").hidden; if (!$("newWorkflowFolderCreateRow").hidden) $("newWorkflowFolderName").focus(); };
$("newPromptFolderToggle").onclick = () => { $("newPromptFolderCreateRow").hidden = !$("newPromptFolderCreateRow").hidden; if (!$("newPromptFolderCreateRow").hidden) $("newPromptFolderName").focus(); };
$("newWorkflowFolderCreate").onclick = () => createCustomFolder("workflow");
$("newPromptFolderCreate").onclick = () => createCustomFolder("prompt");
