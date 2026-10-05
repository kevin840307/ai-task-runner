import { autosizeTextarea, setControlLocked, createLatestActionGate } from "./js/ui-lifecycle.js";
import { createWorkflowGenerator } from "./js/workflow-generator.js";
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
function rememberAiValidatorPrompt(workflow, value) { if (!state.project || !workflow) return; const prefs = currentProjectPreferences(); prefs.aiValidatorPrompts = prefs.aiValidatorPrompts && typeof prefs.aiValidatorPrompts === "object" ? prefs.aiValidatorPrompts : {}; prefs.aiValidatorPrompts[workflow] = value; saveUiPreferences(); }
const state = {
  projects: [], project: null, runtime: null, lastStream: "", lastRunId: "", historyPinnedToBottom: true, runHistoryOpen: false, runtimeTraceOpen: false,
  backends: [], defaultBackend: "", workflowCatalog: { stage_types: {}, node_options: {} }, preferences: null, validatorWorkflowPath: "", aiValidatorPromptWorkflowPath: "",
  view: "chat",
  studioFiles: { workflows: [], prompts: [] }, studioFile: null,
  studioFilters: { workflow: "", prompt: "" },
  studioOriginal: "", studioHash: "", studioDirty: false,
  studioGuard: { editable: true, active_projects: [] }, studioSourceKind: "workflow",
  promptTags: [], newWorkflowDirty: false, newPromptDirty: false, importAssetDirty: false,
  generateWorkflowDirty: false, generateWorkflowJobId: "", generateWorkflowPhase: "idle", generateWorkflowPollTimer: 0,
  generateWorkflowDraft: null, generateWorkflowPromptIndex: 0, generateWorkflowReviewTab: "visual", generateWorkflowRequestText: "",
  generateWorkflowWorkspace: "", generateWorkflowWorkspacePattern: "",
  syntaxTimer: 0,
  lastRuntimeSignature: "", runtimeLastChangedAt: 0, runtimeStartedAt: 0, runtimeStoppedAt: 0, lastErrorDetail: "", studioErrorDetail: "", errorDetailsModalText: "", validationDetail: "", validationSummary: "", runtimeRefreshPromise: null, runtimeRefreshProject: "", runtimeRefreshToken: 0, projectRefreshPromise: null, projectPollMs: 8000, studioGuardRefreshPromise: null,
  studioFileCache: new Map(), studioOpenToken: 0, studioCatalogKey: "", studioCatalogLoadedAt: 0, studioFilesRefreshPromise: null, studioFilesRefreshKey: "", studioCatalogLoading: false, projectSwitching: false, removingProjectPath: "", projectListLoading: false, projectListLoadingLabel: "", studioSaving: false, studioValidating: false,
  runLaunching: false, fullDesignerAvailable: null,
};
const runActionGate = createLatestActionGate();

const THEME_STORAGE_KEY = "ai-task-runner.theme";
const APPEARANCE_STORAGE_KEY = "ai-task-runner.appearance";
const MOTION_STORAGE_KEY = "ai-task-runner.motion";
const THEME_VALUES = new Set(["teal", "blue", "violet", "amber", "rose"]);
const APPEARANCE_VALUES = new Set(["system", "light", "dark"]);
const MOTION_VALUES = new Set(["full", "system", "reduced"]);
const systemColorScheme = window.matchMedia ? window.matchMedia("(prefers-color-scheme: dark)") : null;
function readThemePreference() { try { const value = localStorage.getItem(THEME_STORAGE_KEY); return THEME_VALUES.has(value) ? value : "teal"; } catch (_) { return "teal"; } }
function readAppearancePreference() { try { const value = localStorage.getItem(APPEARANCE_STORAGE_KEY); return APPEARANCE_VALUES.has(value) ? value : "system"; } catch (_) { return "system"; } }
function readMotionPreference() { try { const value = localStorage.getItem(MOTION_STORAGE_KEY); return MOTION_VALUES.has(value) ? value : "full"; } catch (_) { return "full"; } }
function applyMotionPreference(value = readMotionPreference(), { persist = false } = {}) {
  const motion = MOTION_VALUES.has(value) ? value : "full";
  document.documentElement.dataset.motion = motion;
  if (persist) { try { localStorage.setItem(MOTION_STORAGE_KEY, motion); } catch (_) {} }
  renderThemeControls();
}
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
  const motion = document.documentElement.dataset.motion || "full";
  document.querySelectorAll("[data-motion-option]").forEach((button) => { const active = button.dataset.motionOption === motion; button.classList.toggle("active", active); button.setAttribute("aria-pressed", String(active)); });
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
  const { timeoutMs = 0, ...fetchOptions } = options;
  const controller = timeoutMs > 0 ? new AbortController() : null;
  const timer = controller ? window.setTimeout(() => controller.abort(), timeoutMs) : 0;
  try {
    const response = await fetch(path, {
      headers: { "Content-Type": "application/json" },
      ...fetchOptions,
      ...(controller ? { signal: controller.signal } : {}),
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || `HTTP ${response.status}`);
    return data;
  } catch (error) {
    if (controller?.signal.aborted) throw new Error(`Request timed out after ${timeoutMs} ms`);
    throw error;
  } finally {
    if (timer) window.clearTimeout(timer);
  }
}
function selectedWorkflowItem() { const value = $("workflowSelect")?.value || ""; return (state.studioFiles.workflows || []).find((item) => item.path === value) || null; }
function payload(extra = {}) {
  const workflow = selectedWorkflowItem();
  return {
    project: state.project?.path || "",
    backend: $("backend").value,
    validator: workflow?.requires_python_validator ? $("validator").value.trim() : "",
    ai_validator_prompt_file: workflow?.has_ai_validator ? $("aiValidatorPrompt").value.trim() : "",
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
  const detail = String(message || fallback).trim() || fallback;
  const useful = detail.includes("\n") || detail.length > 180;
  state.lastErrorDetail = useful ? detail : "";
  for (const id of ["errorDetailsButton"]) { const button = $(id); if (button) button.hidden = !state.lastErrorDetail; }
}
function openErrorDetailsModal(detail) {
  const text = String(detail || "").trim(); if (!text) return;
  state.errorDetailsModalText = text; $("errorDetailsContent").textContent = text; $("errorDetailsBackdrop").hidden = false;
}
function showErrorDetails() { openErrorDetailsModal(state.lastErrorDetail); }
function closeErrorDetails() { $("errorDetailsBackdrop").hidden = true; state.errorDetailsModalText = ""; }
function openValidationDetails() {
  const detail = String(state.validationDetail || "").trim(); if (!detail) return;
  $("validationDetailsSummary").textContent = state.validationSummary || errorSummary(detail, "Validation failed");
  $("validationDetailsContent").textContent = detail;
  $("validationDetailsBackdrop").hidden = false;
}
function closeValidationDetails() { $("validationDetailsBackdrop").hidden = true; }
function showActionError(message, fallback = "Action failed") {
  const summary = errorSummary(message, fallback); rememberErrorDetail(message, fallback); showToast(summary, "error", 3200);
}
async function withButtonBusy(button, busyLabel, action) {
  if (!button || button.disabled) return undefined;
  const original = button.textContent; button.disabled = true; button.setAttribute("aria-busy", "true");
  if (busyLabel) button.textContent = busyLabel;
  try { return await action(); }
  finally { button.disabled = false; button.removeAttribute("aria-busy"); if (busyLabel) button.textContent = original; }
}
const confirmDialog = (options) => window.UiDialogs.confirm(options);
const inputDialog = (options) => window.UiDialogs.input(options);
const choiceDialog = (options) => window.UiDialogs.choice(options);

function syncComposerReserve() {
  const panel = $("composePanel");
  const chat = $("chatView");
  if (!panel || !chat || panel.hidden) return;
  // Composer is a real grid row, so history receives the remaining height and
  // remains independently scrollable. Keep the measured height only for
  // scroll-padding/follow-to-bottom behavior; never viewport-fix the composer.
  const reserve = Math.ceil(panel.getBoundingClientRect().height + 12);
  chat.style.setProperty("--composer-reserve", `${reserve}px`);
}

function setViewLoading(viewId, loading, label = "Loading…") {
  const view = $(viewId); if (!view) return;
  view.classList.toggle("view-loading", !!loading);
  view.toggleAttribute("aria-busy", !!loading);
  if (loading) view.dataset.loadingLabel = label; else delete view.dataset.loadingLabel;
}
function setStudioContentLoading(loading, label = "Loading workflow…") {
  const editor = $("studioEditor"); if (!editor) return;
  editor.classList.toggle("content-loading", !!loading);
  editor.toggleAttribute("aria-busy", !!loading);
  if (loading) editor.dataset.loadingLabel = label; else delete editor.dataset.loadingLabel;
}
function setProjectListLoading(loading, label = "Updating projects…") {
  state.projectListLoading = !!loading;
  state.projectListLoadingLabel = loading ? label : "";
  const root = $("projectList"); if (!root) return;
  root.classList.toggle("list-loading", !!loading);
  root.toggleAttribute("aria-busy", !!loading);
  if (loading) root.dataset.loadingLabel = label; else delete root.dataset.loadingLabel;
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
  const data = await api("/api/projects", { timeoutMs: 15000 }); applyProjectPollMeta(data); state.projects = uniqueProjects(data.projects || []); renderProjects();
  if (!state.project && state.projects.length) {
    const saved = state.preferences?.lastProject || "";
    const first = state.projects.find((p) => sameProjectPath(p.path, saved) && p.exists !== false) || state.projects.find((p) => p.exists !== false);
    if (first) await selectProject(first);
  }
}

function resolvedPollDelay(value) { return typeof value === "function" ? value() : value; }
function pollDelay(visibleDelay, hiddenDelay) {
  const base = Number(document.hidden ? resolvedPollDelay(hiddenDelay) : resolvedPollDelay(visibleDelay)) || 1000;
  const jitter = Math.min(2000, Math.max(250, base * 0.2));
  return Math.round(base + Math.random() * jitter);
}
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

function applyProjectPollMeta(data) {
  const interval = Number(data?.meta?.suggested_poll_ms || 0);
  if (Number.isFinite(interval) && interval > 0) state.projectPollMs = Math.min(20000, Math.max(8000, interval));
}
function projectStatusPollDelay() { return state.projectPollMs || 8000; }
function projectStatusHiddenPollDelay() { return Math.max(12000, (state.projectPollMs || 8000) * 2); }
function projectPathKey(path) {
  const value = String(path || "").trim().replace(/\\/g, "/").replace(/\/+$/g, "");
  return (/^[A-Za-z]:\//.test(value) || value.startsWith("//")) ? value.toLowerCase() : value;
}
function sameProjectPath(left, right) { return projectPathKey(left) === projectPathKey(right); }
function uniqueProjects(projects) {
  const seen = new Set(), result = [];
  for (const project of projects || []) {
    const key = projectPathKey(project?.path);
    if (!key || seen.has(key)) continue;
    seen.add(key); result.push(project);
  }
  return result;
}
function projectRuntimeSignature(projects) { return uniqueProjects(projects || []).map((p) => `${projectPathKey(p.path)}:${p.name || ""}:${p.runtime_status || "idle"}:${p.runtime_stage || ""}:${p.runtime_completed_count || 0}:${p.runtime_total || 0}:${p.exists !== false}`).join("|"); }
function applySelectedRuntimeToProjectList(projects) {
  if (!state.project || !state.runtime) return projects;
  const current = projects.find((p) => sameProjectPath(p.path, state.project.path));
  if (!current) return projects;
  const runtime = state.runtime;
  current.runtime_status = String(runtime.status || "idle");
  current.runtime_stage = String(runtime.cli_status || runtime.stage || "");
  current.runtime_completed_count = Number(runtime.completed_count || 0);
  current.runtime_total = Number(runtime.total || 0);
  return projects;
}
async function refreshProjectStatuses() {
  if (state.projectRefreshPromise) return state.projectRefreshPromise;
  state.projectRefreshPromise = (async () => {
    try {
      const exclude = state.project?.path && state.runtime ? "?exclude_runtime=" + encodeURIComponent(state.project.path) : "";
      const data = await api("/api/projects" + exclude, { timeoutMs: 15000 }), next = applySelectedRuntimeToProjectList(uniqueProjects(data.projects || []));
      applyProjectPollMeta(data);
      if (projectRuntimeSignature(next) === projectRuntimeSignature(state.projects)) return;
      state.projects = next;
      if (state.project) state.project = next.find((p) => sameProjectPath(p.path, state.project.path)) || state.project;
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
const PROJECT_RUNTIME_LABELS = { running: "Running", recovering: "Recovering", completed: "Completed", needs_attention: "Needs Attention", stopped: "Stopped", idle: "Idle", missing: "Missing" };
function projectRuntimeStatus(project) { return project.exists === false ? "missing" : (project.runtime_status || "idle"); }
function projectRowSignature(project) {
  return JSON.stringify([
    project.path, project.name, project.exists !== false, projectRuntimeStatus(project), project.runtime_stage || "",
    project.runtime_completed_count || 0, project.runtime_total || 0, sameProjectPath(state.project?.path, project.path),
    sameProjectPath(state.removingProjectPath, project.path), !!state.projectSwitching, state.projectSwitching && sameProjectPath(state.project?.path, project.path),
  ]);
}
function syncProjectListLoadingState(root) {
  root.classList.toggle("list-loading", !!state.projectListLoading);
  root.toggleAttribute("aria-busy", !!state.projectListLoading);
  if (state.projectListLoading) root.dataset.loadingLabel = state.projectListLoadingLabel || "Updating projects…"; else delete root.dataset.loadingLabel;
}
function createProjectRow(project) {
  const runtimeStatus = projectRuntimeStatus(project);
  const removing = sameProjectPath(state.removingProjectPath, project.path);
  const opening = state.projectSwitching && sameProjectPath(state.project?.path, project.path);
  const row = document.createElement("div"); row.className = `project-tree project-row runtime-${runtimeStatus}`;
  row.dataset.projectPath = project.path;
  row.dataset.projectKey = projectPathKey(project.path);
  row.dataset.renderSignature = projectRowSignature(project);
  if (removing || opening) row.classList.add("project-busy");
  if (sameProjectPath(state.project?.path, project.path)) row.classList.add("active");
  if (project.exists === false) row.classList.add("missing");
  const button = document.createElement("button"); button.className = "project-root"; button.type = "button";
  const mark = document.createElement("span"); mark.className = `project-mark runtime-${runtimeStatus}`; mark.title = runtimeStatus === "running" ? "Running" : runtimeStatus.charAt(0).toUpperCase() + runtimeStatus.slice(1);
  const copy = document.createElement("span"); copy.className = "project-copy";
  const nameLine = document.createElement("span"); nameLine.className = "project-name-line";
  const name = document.createElement("strong"); name.textContent = project.name;
  nameLine.appendChild(name);
  if (removing || opening) { const status = document.createElement("span"); status.className = "project-runtime-label runtime-busy"; status.textContent = removing ? "REMOVING" : "OPENING"; nameLine.appendChild(status); }
  else if (PROJECT_RUNTIME_LABELS[runtimeStatus]) { const status = document.createElement("span"); status.className = `project-runtime-label runtime-${runtimeStatus}`; status.textContent = PROJECT_RUNTIME_LABELS[runtimeStatus]; nameLine.appendChild(status); }
  const path = document.createElement("small");
  if (removing || opening) { path.textContent = removing ? "Removing from UI…" : "Loading project…"; path.className = "project-runtime-detail"; path.title = project.path; }
  else if (runtimeStatus === "running") {
    const stage = String(project.runtime_stage || "").trim() || "Working";
    const progress = project.runtime_total ? `${project.runtime_completed_count || 0}/${project.runtime_total}` : "";
    path.textContent = `${stage}${progress ? ` · ${progress}` : ""}`;
    path.className = "project-runtime-detail";
    path.title = project.path;
  } else {
    path.textContent = project.exists === false ? t("project.missing", "Missing") : "Ready";
    path.title = project.path;
  }
  copy.append(nameLine, path); button.append(mark, copy); button.disabled = removing || state.projectSwitching; button.onclick = () => project.exists === false ? null : selectProject(project);

  const menuButton = document.createElement("button"); menuButton.className = "project-menu-button"; menuButton.type = "button"; menuButton.title = t("project.actions", "Project actions"); menuButton.setAttribute("aria-label", `${t("project.actions", "Project actions")} · ${project.name}`); menuButton.innerHTML = "<span aria-hidden=\"true\"></span>"; menuButton.disabled = removing || state.projectSwitching;
  const menu = document.createElement("div"); menu.className = "project-action-menu"; menu.hidden = true;
  const rename = document.createElement("button"); rename.type = "button"; rename.textContent = t("project.rename", "Rename project");
  const remove = document.createElement("button"); remove.type = "button"; remove.className = "danger-text"; remove.textContent = t("project.remove", "Remove project");
  menu.append(rename, remove);
  menuButton.onclick = (event) => {
    event.stopPropagation(); const open = menu.hidden;
    if (open) openProjectMenu(menu, menuButton, row); else closeProjectMenus();
  };
  remove.onclick = async (event) => {
    event.stopPropagation();
    if (!(await confirmDiscardStudio())) return;
    const ok = await confirmDialog({ title: "Remove Project?", message: `Remove ${project.name} from this UI? Project files are not deleted.`, confirmLabel: "Remove Project", danger: true });
    if (!ok) return;
    closeProjectMenus(); state.removingProjectPath = project.path; setProjectListLoading(true, "Removing project…"); renderProjects();
    try {
      await api("/api/projects/remove", { method: "POST", body: JSON.stringify({ path: project.path }) });
      setProjectListLoading(true, "Refreshing projects…");
      if (sameProjectPath(state.project?.path, project.path)) { state.project = null; showEmpty(); }
      await loadProjects();
      showToast("Project removed");
    }
    catch (error) { showAppError(error.message); showActionError(error.message, "Remove Project failed"); }
    finally { if (sameProjectPath(state.removingProjectPath, project.path)) state.removingProjectPath = ""; setProjectListLoading(false); renderProjects(); }
  };
  rename.onclick = async (event) => {
    event.stopPropagation(); closeProjectMenus();
    const name = await inputDialog({ title: t("project.rename_title", "Rename Project"), message: project.path, label: t("project.rename_label", "Display name"), value: project.name, confirmLabel: t("project.rename_confirm", "Rename") });
    if (!name || name === project.name) return;
    try {
      const updated = await api("/api/projects/rename", { method: "POST", body: JSON.stringify({ path: project.path, name }) });
      const current = state.projects.find((item) => sameProjectPath(item.path, project.path));
      if (current) current.name = updated.name;
      if (sameProjectPath(state.project?.path, project.path)) { state.project = { ...state.project, name: updated.name }; $("projectName").textContent = updated.name; }
      renderProjects(); showToast(t("project.renamed", "Project renamed"));
    } catch (error) { showActionError(error.message, "Rename Project failed"); }
  };
  row.append(button, menuButton, menu);
  return row;
}
function renderProjects() {
  const root = $("projectList");
  const previousScrollTop = root.scrollTop;
  closeProjectMenus(); root.onscroll = () => closeProjectMenus(); syncProjectListLoadingState(root);
  const existing = new Map(), staleRows = [];
  for (const row of root.querySelectorAll(".project-row[data-project-path]")) {
    const key = row.dataset.projectKey || projectPathKey(row.dataset.projectPath);
    if (!key || existing.has(key)) staleRows.push(row);
    else existing.set(key, row);
  }
  const fragment = document.createDocumentFragment();
  const seen = new Set();
  const projects = uniqueProjects(state.projects);
  if (projects.length !== state.projects.length) state.projects = projects;
  for (const project of projects) {
    const key = projectPathKey(project.path);
    const signature = projectRowSignature(project);
    const current = existing.get(key);
    seen.add(key);
    if (current?.dataset.renderSignature === signature) {
      fragment.appendChild(current);
    } else {
      current?.remove();
      fragment.appendChild(createProjectRow(project));
    }
  }
  for (const row of staleRows) row.remove();
  for (const [key, row] of existing) if (!seen.has(key)) row.remove();
  root.appendChild(fragment);
  if (root.scrollTop !== previousScrollTop) root.scrollTop = previousScrollTop;
}
function showAppError(message) { rememberErrorDetail(message, "Error"); if (state.view === "workflow") setStudioStatus(message, true); else $("errorText").textContent = errorSummary(message, "Error"); }
function showEmpty() {
  setRunHistoryOpen(false);
  setRuntimeTraceOpen(false);
  $("projectName").textContent = "Select a project"; $("projectPath").textContent = "Open a local project folder to begin."; if ($("runtimeHeadline")) $("runtimeHeadline").hidden = true;
  $("summary").hidden = true; $("messages").hidden = true; $("composePanel").hidden = true; $("emptyState").hidden = false;
}
async function selectProject(project) {
  if (!project || state.projectSwitching) return;
  state.lastRuntimeSignature = "";
  const changingProject = !sameProjectPath(state.project?.path, project.path);
  if (changingProject && state.runLaunching) {
    runActionGate.invalidate();
    state.runLaunching = false;
    $("sendButton")?.removeAttribute("aria-busy");
    renderRunConfigurationLock();
  }
  if (changingProject && state.studioFile?.scope === "project") {
    if (state.studioDirty && !(await confirmDiscardStudio())) return;
    clearStudioEditor();
  }
  if ((state.view === "workflow" || state.view === "prompt") && !(await switchView("chat"))) return;
  state.projectSwitching = true;
  setViewLoading("chatView", true, "Opening project…");
  if (changingProject) {
    state.studioFiles = { workflows: [], prompts: [] };
    state.studioCatalogKey = "";
    state.studioCatalogLoadedAt = 0;
    state.validatorWorkflowPath = "";
    state.aiValidatorPromptWorkflowPath = "";
  }
  setRunHistoryOpen(false);
  setRuntimeTraceOpen(false);
  state.project = project; state.runtime = null; state.lastStream = ""; state.runtimeStartedAt = 0; state.runtimeStoppedAt = 0; state.historyPinnedToBottom = true; state.validatorWorkflowPath = ""; $("clearHistoryButton").disabled = true;
  if (!state.preferences) state.preferences = loadUiPreferences(); state.preferences.lastProject = project.path; saveUiPreferences();
  if ($("workflowSelect")) $("workflowSelect").innerHTML = ""; renderProjects(); renderBackendPicker();
  $("projectName").textContent = project.name; $("projectPath").textContent = project.path; $("emptyState").hidden = true;
  $("summary").hidden = false; $("messages").hidden = false; $("composePanel").hidden = false; $("errorText").textContent = ""; requestAnimationFrame(syncComposerReserve);
  try {
    await Promise.all([refreshMessages({ projectPath: project.path }), refreshRuntime({ projectPath: project.path })]);
    refreshStudioFiles({ force: true, projectPath: project.path });
  } catch (error) { showActionError(error.message, "Project loading failed"); }
  finally { setViewLoading("chatView", false); state.projectSwitching = false; renderProjects(); }
}

function formatRunDuration(seconds) {
  const total = Math.max(0, Math.floor(Number(seconds) || 0));
  if (total < 60) return `${total}s`;
  const minutes = Math.floor(total / 60);
  if (minutes < 60) return `${minutes}m ${total % 60}s`;
  const hours = Math.floor(minutes / 60);
  return `${hours}h ${minutes % 60}m`;
}
function runHistoryStatusLabel(status) {
  return ({
    running: "Running",
    recovering: "Recovering",
    completed: "Completed",
    stopped: "Stopped",
    needs_attention: "Needs Attention",
  })[status] || String(status || "Unknown");
}
async function refreshRunHistory({ projectPath = state.project?.path || "" } = {}) {
  const root = $("runHistoryList");
  if (!root || !projectPath) return;
  try {
    const data = await api(`/api/project/runs?project=${encodeURIComponent(projectPath)}`, { timeoutMs: 15000 });
    if (!sameProjectPath(state.project?.path, projectPath)) return;
    root.innerHTML = "";
    const runs = Array.isArray(data.runs) ? data.runs : [];
    if (!runs.length) {
      const empty = document.createElement("div");
      empty.className = "run-history-empty";
      empty.textContent = "No runs yet.";
      root.appendChild(empty);
      return;
    }
    for (const run of runs) {
      const row = document.createElement("button");
      row.type = "button";
      row.className = `run-history-row status-${run.status || "unknown"}`;
      row.dataset.runId = String(run.run_id || "");

      const copy = document.createElement("span");
      copy.className = "run-history-copy";
      const prompt = document.createElement("strong");
      prompt.textContent = String(run.prompt || "Run");
      prompt.title = String(run.prompt || "Run");
      const meta = document.createElement("small");
      const updated = Number(run.updated_at || 0) * 1000;
      meta.textContent = [
        runHistoryStatusLabel(run.status),
        formatRunDuration(run.duration),
        updated ? formatFreshness(updated) : "",
      ].filter(Boolean).join(" · ");
      if (updated) meta.title = `Updated: ${new Date(updated).toLocaleString()}`;
      copy.append(prompt, meta);

      const badge = document.createElement("span");
      badge.className = "run-history-status";
      badge.textContent = runHistoryStatusLabel(run.status);
      row.append(copy, badge);
      row.onclick = () => {
        const runId = String(run.run_id || "");
        const target = [...document.querySelectorAll("#messages .message[data-run-id]")]
          .find((node) => node.dataset.runId === runId);
        if (!target) return;
        target.scrollIntoView({ block: "center", behavior: "smooth" });
        target.classList.add("run-history-focus");
        setTimeout(() => target.classList.remove("run-history-focus"), 1200);
      };
      root.appendChild(row);
    }
  } catch (error) {
    root.innerHTML = "";
    const failed = document.createElement("div");
    failed.className = "run-history-empty error";
    failed.textContent = errorSummary(error.message, "Unable to load run history");
    root.appendChild(failed);
  }
}
function setRunHistoryOpen(open) {
  state.runHistoryOpen = Boolean(open && state.project);
  if (state.runHistoryOpen) setRuntimeTraceOpen(false);
  const panel = $("runHistoryPanel");
  const button = $("runHistoryButton");
  if (panel) panel.hidden = !state.runHistoryOpen;
  if (button) button.setAttribute("aria-expanded", String(state.runHistoryOpen));
  if (state.runHistoryOpen) void refreshRunHistory();
}
function renderRuntimeTrace(runtime = state.runtime) {
  const button = $("runtimeTraceButton");
  const root = $("runtimeTraceList");
  if (!button || !root) return;
  const items = Array.isArray(runtime?.recent_transitions) ? runtime.recent_transitions : [];
  button.hidden = items.length === 0;
  if (!items.length) {
    root.innerHTML = "";
    setRuntimeTraceOpen(false);
    return;
  }
  root.innerHTML = "";
  for (const item of [...items].reverse()) {
    const row = document.createElement("div");
    row.className = `runtime-trace-row status-${item.status || "unknown"}`;
    const route = document.createElement("strong");
    route.textContent = `${item.stage || "stage"} ${String(item.status || "").toUpperCase()} → ${item.target || "stop"}`;
    route.title = route.textContent;
    const meta = document.createElement("small");
    const timestamp = Number(item.timestamp || 0) * 1000;
    meta.textContent = [
      Number(item.cycle || 0) > 0 ? `Cycle ${item.cycle}` : "",
      item.kind ? String(item.kind) : "",
      timestamp ? formatFreshness(timestamp) : "",
    ].filter(Boolean).join(" · ");
    if (timestamp) meta.title = new Date(timestamp).toLocaleString();
    row.append(route, meta);
    root.appendChild(row);
  }
}
function setRuntimeTraceOpen(open) {
  state.runtimeTraceOpen = Boolean(open && state.project);
  if (state.runtimeTraceOpen && state.runHistoryOpen) {
    state.runHistoryOpen = false;
    if ($("runHistoryPanel")) $("runHistoryPanel").hidden = true;
    $("runHistoryButton")?.setAttribute("aria-expanded", "false");
  }
  const panel = $("runtimeTracePanel");
  const button = $("runtimeTraceButton");
  if (panel) panel.hidden = !state.runtimeTraceOpen;
  if (button) button.setAttribute("aria-expanded", String(state.runtimeTraceOpen));
}

async function refreshMessages({ forceFollow = false, projectPath = state.project?.path || "" } = {}) {
  if (!projectPath) return;
  const root = $("messages");
  const shouldFollow = forceFollow || state.historyPinnedToBottom || historyNearBottom(root);
  const data = await api(`/api/project/messages?project=${encodeURIComponent(projectPath)}`, { timeoutMs: 15000 });
  if (!sameProjectPath(state.project?.path, projectPath)) return;
  const input = root.querySelector(".runtime-input-card");
  const live = root.querySelector(".live-activity"); root.innerHTML = "";
  for (const message of data.messages || []) {
    const item = document.createElement("article"); item.className = `message ${message.role}`; item.dataset.role = message.role || "assistant"; if (message.run_id) item.dataset.runId = String(message.run_id);
    const body = document.createElement("div"); body.className = "message-body"; body.textContent = message.content || ""; item.appendChild(body); root.appendChild(item);
  }
  if (input) root.appendChild(input);
  if (live) root.appendChild(live);
  if (shouldFollow) { state.historyPinnedToBottom = true; followHistoryToBottom(true); }
}
function ensureLiveCard({ forceVisibleOnCreate = false } = {}) {
  const root = $("messages");
  let card = root.querySelector(".live-activity"); if (card) return card;
  card = document.createElement("article"); card.className = "live-activity cli-runtime-card";
  card.innerHTML = `<div class="live-activity-head"><span class="live-dot" aria-hidden="true"></span><strong class="live-title">CLI Runtime</strong><small class="live-progress">same runtime state</small><small class="live-updated">Last update —</small></div><pre class="cli-runtime-output"></pre><div class="cli-runtime-footer"><span class="runtime-live-indicator">Running</span><span>Elapsed <strong class="cli-runtime-elapsed">00:00:00</strong></span></div>`;
  root.appendChild(card);
  if (forceVisibleOnCreate) { state.historyPinnedToBottom = true; followHistoryToBottom(true); }
  return card;
}
function removeLiveCard() { $("messages")?.querySelector(".live-activity")?.remove(); }
function cliRuntimeText(runtime) {
  const marker = runtime?.actions?.stop ? ">" : " ";
  const lines = Array.isArray(runtime.cli_lines) && runtime.cli_lines.length
    ? runtime.cli_lines
    : [`AI Task Runner  Cycle 1  Progress ${runtime.completed_count || 0}/${runtime.total || 0}`, "", `  {spinner} ${runtime.cli_status || runtime.stage || "準備中"}`];
  return lines.map((line) => String(line).replaceAll("{spinner}", marker)).join("\n");
}
function setTextIfChanged(node, value) { if (node && node.textContent !== value) node.textContent = value; }
function renderCliRuntimeFrame() {
  const runtime = state.runtime, output = $("messages")?.querySelector(".cli-runtime-output");
  if (!runtime || !output) return;
  setTextIfChanged(output, cliRuntimeText(runtime));
}
function runtimeStatusLabel(runtime) {
  return String(runtime?.view?.label || runtime?.status || "Idle")
    .replaceAll("_", " ")
    .replace(/\b\w/g, (value) => value.toUpperCase());
}
function runtimeScriptLabel(runtime) {
  const index = Number(runtime?.script_index || 0), total = Number(runtime?.script_total || 0);
  return runtime?.script_mode && index && total ? `Script ${index}/${total}` : "";
}
function runtimeProgressLabel(runtime) {
  const script = runtimeScriptLabel(runtime);
  const todo = runtime?.total ? `${runtime.completed_count || 0}/${runtime.total} TODO` : "";
  return [script, todo].filter(Boolean).join(" · ") || (runtime?.console_snapshot_exists ? "CLI synced" : "State fallback");
}
function ensureRuntimeInputCard() {
  const root = $("messages");
  let card = root?.querySelector(".runtime-input-card");
  if (card || !root) return card;
  card = document.createElement("article");
  card.className = "runtime-input-card";
  card.innerHTML = `<details><summary><span>Input prompt</span><strong class="runtime-input-label">Runtime input</strong></summary><pre class="runtime-input-prompt"></pre></details>`;
  const live = root.querySelector(".live-activity");
  if (live) root.insertBefore(card, live); else root.appendChild(card);
  return card;
}
function removeRuntimeInputCard() { $("messages")?.querySelector(".runtime-input-card")?.remove(); }
function renderRuntimeInput(runtime) {
  const text = String(runtime?.input_prompt || "").trim();
  if (!text) { removeRuntimeInputCard(); return; }
  const card = ensureRuntimeInputCard();
  if (!card) return;
  setTextIfChanged(card.querySelector(".runtime-input-label"), runtimeScriptLabel(runtime) || "Runtime input");
  setTextIfChanged(card.querySelector(".runtime-input-prompt"), text);
}
function renderLiveRuntimeHeader(runtime) {
  const card = $("messages")?.querySelector(".live-activity"); if (!card || !runtime) return;
  setTextIfChanged(card.querySelector(".live-title"), runtimeStatusLabel(runtime));
  setTextIfChanged(card.querySelector(".live-progress"), runtimeProgressLabel(runtime)); updateRuntimeFreshness();
}
function renderRuntimeGuidance(runtime) {
  const root = $("runtimeGuidance");
  if (!root) return;
  const status = String(runtime?.status || "");
  const reason = String(runtime?.attention_reason || runtime?.view?.reason || "").trim();
  const recovery = runtime?.recovery && typeof runtime.recovery === "object" ? runtime.recovery : {};
  const show = Boolean(reason && ["recovering", "needs_attention", "stopped"].includes(status));
  root.hidden = !show;
  root.classList.toggle("recovering", status === "recovering");
  root.classList.toggle("needs-attention", status === "needs_attention");
  if (!show) return;
  setTextIfChanged($("runtimeGuidanceTitle"), runtimeStatusLabel(runtime));
  setTextIfChanged($("runtimeGuidanceReason"), reason);
  const recommended = Array.isArray(runtime?.recommended_actions) ? runtime.recommended_actions : [];
  const retry = status === "recovering" && recovery.retry
    ? [recovery.mode || "retry", "#" + recovery.retry, recovery.wait_seconds ? recovery.wait_seconds + "s" : ""].filter(Boolean).join(" · ")
    : "";
  setTextIfChanged($("runtimeGuidanceActions"), retry || (recommended.length ? "Recommended: " + recommended.join(" / ") : ""));
  const workflowButton = $("runtimeGuidanceWorkflow");
  const traceButton = $("runtimeGuidanceTrace");
  if (workflowButton) {
    workflowButton.hidden = !recommended.includes("open_workflow");
    workflowButton.onclick = () => $("workflowNav")?.click();
  }
  if (traceButton) {
    traceButton.hidden = !recommended.includes("view_trace");
    traceButton.onclick = () => $("runtimeTraceButton")?.click();
  }
}
function runtimeRenderSignature(runtime) {
  if (!runtime) return "";
  return JSON.stringify([
    runtime.status || "", runtime.actions || {}, runtime.recovery || {},
    runtime.attention_reason || "", runtime.recommended_actions || [],
    runtime.run_snapshot || {}, runtime.run_id || "", runtime.cli_status || "",
    runtime.stage || "", runtime.cycle || 1, runtime.workflow_position || 0,
    runtime.last_transition || {}, runtime.completed_count || 0, runtime.total || 0,
    runtime.task || "", runtime.cli_detail || "", runtime.console_snapshot_exists || false,
    runtime.cli_lines || [], runtime.script_mode || false, runtime.script_index || 0,
    runtime.script_total || 0, runtime.script_status || "", runtime.input_prompt || ""
  ]);
}
async function refreshRuntime({ projectPath = state.project?.path || "", force = false } = {}) {
  if (!projectPath) return;
  const projectKey = projectPathKey(projectPath);
  if (!force && state.runtimeRefreshPromise && state.runtimeRefreshProject === projectKey) return state.runtimeRefreshPromise;
  const token = ++state.runtimeRefreshToken;
  const request = (async () => {
    try {
      const runtime = await api(`/api/project/runtime?project=${encodeURIComponent(projectPath)}`, { timeoutMs: 15000 });
      if (token !== state.runtimeRefreshToken || !sameProjectPath(state.project?.path, projectPath)) return;
      state.runtime = runtime;
      const signature = runtimeRenderSignature(runtime);
      if (signature !== state.lastRuntimeSignature) { state.lastRuntimeSignature = signature; state.runtimeLastChangedAt = Date.now(); renderRuntime(runtime); }
    } catch (error) { if (token === state.runtimeRefreshToken && sameProjectPath(state.project?.path, projectPath)) setTextIfChanged($("errorText"), error.message); }
  })();
  state.runtimeRefreshPromise = request; state.runtimeRefreshProject = projectKey;
  try { return await request; }
  finally { if (state.runtimeRefreshPromise === request) { state.runtimeRefreshPromise = null; state.runtimeRefreshProject = ""; } }
}

function formatFreshness(ts) {
  if (!ts) return "—"; const seconds = Math.max(0, Math.floor((Date.now() - ts) / 1000));
  if (seconds < 5) return "just now"; if (seconds < 60) return `${seconds}s ago`; const minutes = Math.floor(seconds / 60); if (minutes < 60) return `${minutes}m ago`; return `${Math.floor(minutes / 60)}h ago`;
}
function formatElapsed(seconds) {
  const total = Math.max(0, Math.floor(Number(seconds) || 0));
  const h = String(Math.floor(total / 3600)).padStart(2, "0");
  const m = String(Math.floor((total % 3600) / 60)).padStart(2, "0");
  const s = String(total % 60).padStart(2, "0");
  return `${h}:${m}:${s}`;
}
function runtimeElapsedSeconds() {
  if (!state.runtimeStartedAt) return 0;
  const end = state.runtime?.actions?.stop ? Date.now() : (state.runtimeStoppedAt || Date.now());
  return Math.max(0, end / 1000 - state.runtimeStartedAt);
}
function updateRuntimeElapsed() {
  const text = state.runtimeStartedAt ? formatElapsed(runtimeElapsedSeconds()) : "—";
  setTextIfChanged($("elapsedTimeText"), text);
  const live = $("messages")?.querySelector(".cli-runtime-elapsed");
  setTextIfChanged(live, state.runtimeStartedAt ? text : "00:00:00");
  const indicator = $("messages")?.querySelector(".runtime-live-indicator");
  if (indicator) indicator.textContent = state.runtime?.actions?.stop ? "Running" : runtimeStatusLabel(state.runtime);
}
function updateRuntimeFreshness() {
  const text = formatFreshness(state.runtimeLastChangedAt);
  const exact = state.runtimeLastChangedAt ? new Date(state.runtimeLastChangedAt).toLocaleString() : "";
  const last = $("lastUpdateText");
  setTextIfChanged(last, text);
  if (last) last.title = exact ? "Last update: " + exact : "";
  const live = $("messages")?.querySelector(".live-updated");
  setTextIfChanged(live, `Last update ${text}`);
  if (live) live.title = exact ? "Last update: " + exact : "";
  const stale = Boolean(state.runtime?.actions?.stop && state.runtimeLastChangedAt && Date.now() - state.runtimeLastChangedAt > 30000);
  last?.classList.toggle("stale", stale);
  updateRuntimeElapsed();
}
function runConfigurationLocked() {
  const actions = state.runtime?.actions;
  const runtimeBlocksNew = Boolean(actions && actions.run === false);
  return Boolean(state.runLaunching || runtimeBlocksNew || state.studioCatalogLoading);
}
function renderRunConfigurationLock() {
  const locked = runConfigurationLocked();
  const reason = locked ? "Current task configuration is locked until Reset or completion." : "";
  for (const id of ["workflowDropdownButton", "backendDropdownButton"]) setControlLocked($(id), locked, reason);
  const select = $("workflowSelect"); if (select) select.disabled = locked;
  $("workflowPicker")?.classList.toggle("configuration-locked", locked);
  $("validatorPicker")?.classList.toggle("configuration-locked", locked);
  $("aiValidatorPromptPicker")?.classList.toggle("configuration-locked", locked);
  if ($("runConfigLockNote")) $("runConfigLockNote").hidden = !locked;
  if (locked) { closeWorkflowDropdown(); closeBackendDropdown(); }
  renderValidationCapability();
}

function renderRuntime(runtime) {
  const startedAt = Number(runtime.started_at || 0);
  const actions = runtime.actions && typeof runtime.actions === "object" ? runtime.actions : {};
  const status = String(runtime.status || "idle");
  const isRunning = Boolean(actions.stop);
  const isResumable = Boolean(actions.resume);
  if (status === "idle" && !runtime.has_state) {
    state.runtimeStartedAt = 0; state.runtimeStoppedAt = 0;
  } else if (isRunning && startedAt) {
    if (state.runtimeStartedAt !== startedAt) { state.runtimeStartedAt = startedAt; state.runtimeStoppedAt = 0; }
  } else if (!isRunning && state.runtimeStartedAt && !state.runtimeStoppedAt) {
    state.runtimeStoppedAt = Date.now();
  }
  updateRuntimeFreshness();
  const badge = $("statusBadge");
  badge.className = "runtime-badge";
  const label = runtimeStatusLabel(runtime);
  if (status === "recovering") badge.classList.add("recovering");
  else if (status === "running") badge.classList.add("running");
  else if (status === "needs_attention") badge.classList.add("needs-attention");
  else if (status === "stopped") badge.classList.add("failed");
  else if (status === "completed") badge.classList.add("completed");

  const baseStage = String(runtime.cli_status || runtime.stage || "").trim();
  const scriptStage = runtimeScriptLabel(runtime);
  const runtimeStage = scriptStage ? scriptStage + (baseStage ? " · " + baseStage : "") : baseStage;
  const runtimeProgress = runtimeProgressLabel(runtime);
  const badgeDetail = isRunning && (runtimeStage || runtimeProgress)
    ? " · " + (runtimeStage || "Working") + (runtimeProgress ? " · " + runtimeProgress : "")
    : "";
  setTextIfChanged(badge, label + badgeDetail);
  setTextIfChanged($("currentStage"), runtimeStage || label);
  setTextIfChanged($("progressText"), runtimeProgress || "—");
  setTextIfChanged($("currentTask"), runtime.task || runtime.attention_reason || runtime.cli_detail || "Waiting");

  const headline = $("runtimeHeadline");
  if (headline) {
    const transition = runtime.last_transition && typeof runtime.last_transition === "object" ? runtime.last_transition : {};
    const transitionText = transition.stage && transition.status ? transition.stage + " " + String(transition.status).toUpperCase() : "";
    const parts = [
      runtimeStage || label,
      Number(runtime.cycle || 0) > 1 ? "Cycle " + runtime.cycle : "",
      runtimeProgress,
      transitionText ? "Last · " + transitionText : "",
    ].filter(Boolean);
    headline.textContent = parts.join(" · ");
    headline.hidden = parts.length === 0;
  }

  renderRuntimeInput(runtime);
  renderRuntimeTrace(runtime);
  renderRuntimeGuidance(runtime);

  $("clearHistoryButton").disabled = isRunning;
  $("clearHistoryButton").title = isRunning ? "Stop the active task before clearing this chat history" : "Clear chat history";
  $("sendButton").hidden = actions.run === false;
  $("stopButton").hidden = !actions.stop;
  $("resumeButton").hidden = !actions.resume;
  $("resetButton").hidden = !actions.reset;
  $("rerunButton").hidden = !actions.rerun;

  const blockNew = actions.run === false || state.runLaunching || state.studioCatalogLoading;
  const blockTyping = actions.run === false || state.runLaunching;
  $("sendButton").disabled = blockNew;
  $("sendButton").title = actions.run === false
    ? (isRunning ? "A task is already running." : "Continue or Reset the stopped task before starting another.")
    : state.runLaunching ? "Task launch is already in progress."
      : state.studioCatalogLoading ? "Workflow catalog is still loading." : "Run task";
  $("messageInput").disabled = blockTyping;
  renderRunConfigurationLock();
  $("messageInput").placeholder = "描述要完成的功能或修復內容...";

  if (isRunning || isResumable) {
    const card = ensureLiveCard({ forceVisibleOnCreate: true });
    card.classList.toggle("running", isRunning);
    renderLiveRuntimeHeader(runtime);
    renderCliRuntimeFrame();
    followHistoryToBottom();
  } else removeLiveCard();

  const current = state.projects.find((p) => sameProjectPath(p.path, state.project?.path));
  if (current) {
    const nextStatus = status;
    const nextStage = String(runtime.cli_status || runtime.stage || "");
    const nextCompleted = Number(runtime.completed_count || 0);
    const nextTotal = Number(runtime.total || 0);
    const changed = current.runtime_status !== nextStatus
      || current.runtime_stage !== nextStage
      || Number(current.runtime_completed_count || 0) !== nextCompleted
      || Number(current.runtime_total || 0) !== nextTotal;
    current.runtime_status = nextStatus;
    current.runtime_stage = nextStage;
    current.runtime_completed_count = nextCompleted;
    current.runtime_total = nextTotal;
    if (changed) renderProjects();
  }

  if (status === "completed" && runtime.run_id && runtime.run_id !== state.lastRunId) {
    state.lastRunId = runtime.run_id;
    state.historyPinnedToBottom = true;
    refreshMessages({ forceFollow: true });
    if (state.runHistoryOpen) void refreshRunHistory();
  }
}
function hasUserMessage() { return $("messages")?.querySelector(".message.user") !== null; }
function resizeComposerInput() { const ta = $("messageInput"); if (!ta) return; autosizeTextarea(ta, { minHeight: 46, maxHeight: 210 }); syncComposerReserve(); }
async function sendMessage() {
  const text = $("messageInput").value.trim(); if (!text || !state.project || runConfigurationLocked()) return; $("errorText").textContent = "";
  const actionToken = runActionGate.begin();
  state.runLaunching = true; state.historyPinnedToBottom = true;
  $("sendButton")?.setAttribute("aria-busy", "true");
  renderRunConfigurationLock(); renderRuntime(state.runtime || {});
  try {
    await api("/api/project/message", { method: "POST", body: JSON.stringify(payload({ message: text })) });
    if (!runActionGate.isCurrent(actionToken)) return;
    $("messageInput").value = ""; resizeComposerInput(); await refreshMessages({ forceFollow: true });
    if (state.runtimeRefreshPromise) { try { await state.runtimeRefreshPromise; } catch (_) {} }
    await refreshRuntime(); showToast("Task started");
  } catch (error) {
    if (!runActionGate.isCurrent(actionToken)) return;
    $("errorText").textContent = error.message; showActionError(error.message, "Task start failed");
  } finally {
    if (runActionGate.isCurrent(actionToken)) { state.runLaunching = false; $("sendButton")?.removeAttribute("aria-busy"); renderRunConfigurationLock(); if (state.runtime) renderRuntime(state.runtime); }
  }
}

async function refreshBackends() {
  try { const data = await api("/api/backends", { timeoutMs: 15000 }); state.backends = Array.isArray(data.backends) ? data.backends : []; state.defaultBackend = String(data.default || ""); renderBackendPicker(); }
  catch (_) { state.backends = []; state.defaultBackend = ""; renderBackendPicker(); }
}
async function refreshWorkflowCatalog() {
  try {
    const data = await api("/api/workflow/catalog", { timeoutMs: 15000 });
    state.workflowCatalog = data && typeof data === "object" ? data : { stage_types: {}, node_options: {} };
    const add = $("addStageType");
    if (add) {
      const selected = add.value || "task";
      add.innerHTML = stageTypesOptions(selected);
      if (![...add.options].some((o) => o.value === selected)) add.value = add.options[0]?.value || "";
    }
  } catch (_) {
    state.workflowCatalog = { stage_types: {}, node_options: {} };
  }
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
    button.onclick = () => { if (runConfigurationLocked()) return; select.value = row.value; rememberProjectPreference("backend", row.value); closeBackendDropdown(); renderBackendPickerSelection(); }; menu.appendChild(button);
  }
  select.value = [...select.options].some((o) => o.value === saved) ? saved : "";
  renderBackendPickerSelection(); renderRunConfigurationLock();
}
function renderBackendPickerSelection() {
  const select = $("backend"), label = $("backendSelectedLabel"); if (!select || !label) return; label.textContent = select.options[select.selectedIndex]?.textContent || "Default backend";
  document.querySelectorAll("#backendDropdownMenu .backend-dropdown-option").forEach((button, index) => { const active = select.options[index]?.value === select.value; button.classList.toggle("active", active); button.setAttribute("aria-selected", String(active)); });
}

// ------------------------------ Workflow picker ------------------------------
async function refreshStudioFiles({ force = false, projectPath = state.project?.path || "" } = {}) {
  const key = projectPath || "@global";
  const fresh = state.studioCatalogKey === key && state.studioCatalogLoadedAt && (Date.now() - state.studioCatalogLoadedAt) < 8000;
  if (!force && fresh) { renderStudioFiles(); renderWorkflowPicker(); return state.studioFiles; }
  if (state.studioFilesRefreshPromise && state.studioFilesRefreshKey === key) return state.studioFilesRefreshPromise;
  const query = projectPath ? `&project=${encodeURIComponent(projectPath)}` : "";
  state.studioCatalogLoading = true; renderWorkflowPicker(); renderRunConfigurationLock();
  const request = (async () => {
    try {
      const data = await api(`/api/studio/files?x=1${query}`, { timeoutMs: 15000 });
      if (!sameProjectPath(state.project?.path || "", projectPath)) return state.studioFiles;
      state.studioFiles = data; state.studioGuard = data.guard || { editable: true, active_projects: [] };
      state.studioCatalogKey = key; state.studioCatalogLoadedAt = Date.now();
      renderStudioGuard(); renderStudioFiles(); renderWorkflowPicker(); fillAddStagePromptOptions(); refreshPromptTags();
      return data;
    } catch (error) { if (sameProjectPath(state.project?.path || "", projectPath)) setStudioStatus(error.message, true); return state.studioFiles; }
  })();
  state.studioFilesRefreshPromise = request; state.studioFilesRefreshKey = key;
  try { return await request; }
  finally { if (state.studioFilesRefreshPromise === request) { state.studioFilesRefreshPromise = null; state.studioFilesRefreshKey = ""; state.studioCatalogLoading = false; renderWorkflowPicker(); renderRunConfigurationLock(); } }
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

const DEFAULT_WORKFLOW_NAME = "ralphy_ai_validate.yaml";
function workflowBasename(value) { return String(value || "").replaceAll("\\", "/").split("/").filter(Boolean).pop() || ""; }
function renderWorkflowPicker() {
  const select = $("workflowSelect"), menu = $("workflowDropdownMenu"), label = $("workflowSelectedLabel"); if (!select || !menu || !label) return;
  const previous = select.value; const saved = String(currentProjectPreferences().workflow || ""); select.innerHTML = ""; menu.innerHTML = "";
  const rows = (state.studioFiles.workflows || []).filter((item) => !item.hidden).map((item) => ({ value: item.path, label: item.name, meta: `${item.group || item.scope}${item.requires_python_validator ? " · Python validation" : ""}${item.has_ai_validator ? " · AI validation" : ""}`, scope: item.scope }));
  for (const row of rows) {
    const option = document.createElement("option"); option.value = row.value; option.textContent = row.label; select.appendChild(option);
    const button = document.createElement("button"); button.type = "button"; button.className = "workflow-dropdown-option"; button.setAttribute("role", "option");
    button.innerHTML = `<span class="workflow-option-main"><strong></strong><small></small></span><span class="workflow-option-badge"></span>`;
    button.querySelector("strong").textContent = row.label; button.querySelector("small").textContent = row.meta; button.querySelector(".workflow-option-badge").textContent = String(row.scope || "global").toUpperCase();
    button.onclick = () => { select.value = row.value; label.textContent = row.label; rememberProjectPreference("workflow", row.value); closeWorkflowDropdown(); renderWorkflowPickerSelection(); };
    menu.appendChild(button);
  }
  if ([...select.options].some((option) => option.value === saved)) select.value = saved;
  else {
    const preferred = [...select.options].find((option) => workflowBasename(option.value) === DEFAULT_WORKFLOW_NAME || option.textContent === DEFAULT_WORKFLOW_NAME);
    if (preferred) select.value = preferred.value;
    else if ([...select.options].some((option) => option.value === previous)) select.value = previous;
    else if (select.options.length) select.selectedIndex = 0;
  }
  if (select.value) rememberProjectPreference("workflow", select.value);
  label.textContent = state.studioCatalogLoading ? "Loading workflows..." : (select.options[select.selectedIndex]?.textContent || "No workflow");
  renderWorkflowPickerSelection();
}
function renderWorkflowPickerSelection() {
  const value = $("workflowSelect")?.value || "";
  document.querySelectorAll("#workflowDropdownMenu .workflow-dropdown-option").forEach((button, index) => { const active = $("workflowSelect")?.options[index]?.value === value; button.classList.toggle("active", active); button.setAttribute("aria-selected", String(active)); });
  const workflow = selectedWorkflowItem();
  const input = $("validator"), aiPromptInput = $("aiValidatorPrompt");
  if (input && state.validatorWorkflowPath !== value) {
    const validators = currentProjectPreferences().validators || {};
    input.value = workflow?.requires_python_validator ? String(validators[value] || "") : "";
    state.validatorWorkflowPath = value;
  }
  if (aiPromptInput && state.aiValidatorPromptWorkflowPath !== value) {
    const prompts = currentProjectPreferences().aiValidatorPrompts || {};
    aiPromptInput.value = workflow?.has_ai_validator ? String(prompts[value] || "") : "";
    state.aiValidatorPromptWorkflowPath = value;
  }
  updateValidatorPicker();
  updateAiValidatorPromptPicker();
  renderRunConfigurationLock();
  syncComposerReserve();
}
function resourceFileName(value, fallback) {
  const text = String(value || "").trim(); if (!text) return fallback;
  return text.replaceAll("\\", "/").split("/").filter(Boolean).pop() || fallback;
}
function updateValidatorPicker() {
  const input = $("validator"), clear = $("clearValidatorButton"), name = $("validatorResourceName"), picker = $("validatorPicker"); if (!input) return;
  const supported = Boolean(selectedWorkflowItem()?.requires_python_validator);
  const value = input.value.trim();
  input.title = value;
  if (clear) clear.hidden = !supported || !value;
  if (name) name.textContent = supported ? resourceFileName(value, "未選擇") : "此 Workflow 未使用";
  if (picker) {
    picker.classList.toggle("has-resource", supported && !!value);
    picker.classList.toggle("resource-unavailable", !supported);
  }
}
function updateAiValidatorPromptPicker() {
  const input = $("aiValidatorPrompt"), clear = $("clearAiValidatorPromptButton"), name = $("aiValidatorPromptResourceName"), picker = $("aiValidatorPromptPicker"); if (!input) return;
  const supported = Boolean(selectedWorkflowItem()?.has_ai_validator);
  const value = input.value.trim();
  input.title = value;
  if (clear) clear.hidden = !supported || !value;
  if (name) name.textContent = supported ? resourceFileName(value, "預設 Prompt") : "此 Workflow 未使用";
  if (picker) {
    picker.classList.toggle("has-resource", supported && !!value);
    picker.classList.toggle("resource-unavailable", !supported);
  }
}
function renderValidationCapability() {
  const workflow = selectedWorkflowItem();
  const locked = runConfigurationLocked();
  const fileSupported = Boolean(workflow?.requires_python_validator);
  const promptSupported = Boolean(workflow?.has_ai_validator);
  const lockReason = "Current task configuration is locked until Reset or completion.";
  const capability = [
    ["browseValidatorButton", fileSupported, "Selected Workflow does not use a File Validator."],
    ["clearValidatorButton", fileSupported, "Selected Workflow does not use a File Validator."],
    ["browseAiValidatorPromptButton", promptSupported, "Selected Workflow does not use an AI Validator Prompt."],
    ["clearAiValidatorPromptButton", promptSupported, "Selected Workflow does not use an AI Validator Prompt."],
  ];
  for (const [id, supported, unsupportedReason] of capability) {
    const control = $(id);
    if (!control) continue;
    control.disabled = locked || !supported;
    control.setAttribute("aria-disabled", String(locked || !supported));
    control.title = locked ? lockReason : (!supported ? unsupportedReason : "");
  }
}
async function browseValidator() {
  const button = $("browseValidatorButton"); if (!button || runConfigurationLocked()) return; const original = button.textContent; button.disabled = true; button.textContent = "…";
  try { const result = await api("/api/files/pick", { method: "POST", body: JSON.stringify({ kind: "python" }) }); if (!result.cancelled && result.path) { $("validator").value = result.path; rememberValidator($("workflowSelect")?.value || "", result.path); updateValidatorPicker(); showToast("Python validator selected"); } }
  catch (error) { showToast(error.message, "error", 3200); }
  finally { button.textContent = original; renderRunConfigurationLock(); }
}

// ------------------------------ Workflow Studio ------------------------------
async function browseAiValidatorPrompt() {
  const button = $("browseAiValidatorPromptButton"); if (!button || runConfigurationLocked()) return; const original = button.textContent; button.disabled = true; button.textContent = "…";
  try { const result = await api("/api/files/pick", { method: "POST", body: JSON.stringify({ kind: "markdown" }) }); if (!result.cancelled && result.path) { $("aiValidatorPrompt").value = result.path; rememberAiValidatorPrompt($("workflowSelect")?.value || "", result.path); updateAiValidatorPromptPicker(); showToast("AI validation prompt selected"); } }
  catch (error) { showActionError(error.message, "AI prompt selection failed"); }
  finally { button.disabled = false; button.textContent = original; }
}

async function switchView(view) {
  if (view === "workflow" || view === "prompt") {
    const kind = view === "prompt" ? "prompt" : "workflow";
    state.view = view;
    state.studioSourceKind = kind;
    $("chatView").hidden = true;
    $("workflowView").hidden = false;
    $("chatNav").classList.remove("active");
    $("workflowNav").classList.toggle("active", kind === "workflow");
    $("promptNav").classList.toggle("active", kind === "prompt");
    renderStudioFiles(); renderWorkflowPicker();
    setViewLoading("workflowView", true, kind === "prompt" ? "Loading prompts…" : "Loading workflows…");
    try { await Promise.all([refreshStudioFiles(), refreshStudioGuard()]); }
    catch (error) { showActionError(error.message, kind === "prompt" ? "Prompt loading failed" : "Workflow loading failed"); }
    finally { setViewLoading("workflowView", false); }
    return true;
  }
  if ((state.view === "workflow" || state.view === "prompt") && !$("workflowGeneratorPage").hidden) { if (!(await leaveGenerateWorkflowPage())) return false; }
  // Global Workflow Studio keeps its main draft when navigating to Project Tasks.
  // Only modal-local drafts need confirmation because closing those dialogs would destroy them.
  if (!$("newWorkflowBackdrop").hidden && !(await closeNewWorkflowModal())) return false;
  state.view = "chat"; $("workflowView").hidden = true; $("chatView").hidden = false; $("chatNav").classList.add("active"); $("workflowNav").classList.remove("active"); $("promptNav").classList.remove("active");
  return true;
}
function visibleStudioFiles() { return state.studioSourceKind === "prompt" ? (state.studioFiles.prompts || []) : (state.studioFiles.workflows || []); }
function studioSearchQuery() { return state.studioFilters?.[state.studioSourceKind] || ""; }
function filteredStudioFiles() { return window.StudioSupport.filterItems(visibleStudioFiles(), studioSearchQuery()); }
function syncStudioSearch() { const input = $("studioSearchInput"), clear = $("studioSearchClear"); if (!input) return; input.value = studioSearchQuery(); input.placeholder = state.studioSourceKind === "prompt" ? "Search prompts..." : "Search workflows..."; if (clear) clear.hidden = !input.value; }
function appendStudioItem(root, item) {
  const button = document.createElement("button");
  button.type = "button";
  button.className = "studio-file-item designer-workflow-pill";
  if (state.studioFile?.id === item.id) button.classList.add("active");
  const top = document.createElement("span");
  top.className = "studio-file-item-top";
  const name = document.createElement("strong");
  name.textContent = item.name;
  name.title = item.name;
  button.title = item.name;
  const scope = document.createElement("span");
  scope.className = `studio-list-scope ${item.scope || "global"}`;
  scope.textContent = String(item.scope || "global").toUpperCase();
  top.append(name, scope);
  const metaNode = document.createElement("small");
  const assetState =
    item.kind === "workflow" && item.hidden
      ? t("assets.hidden_from_chat", "Hidden from Chat")
      : item.kind === "prompt"
        ? "Prompt"
        : t("assets.visible_in_chat", "Visible in Chat");
  const modifiedAt = Number(item.mtime || 0) * 1000;
  metaNode.textContent = modifiedAt ? `${assetState} · ${formatFreshness(modifiedAt)}` : assetState;
  if (modifiedAt) metaNode.title = `Modified: ${new Date(modifiedAt).toLocaleString()}`;
  if (item.kind === "workflow" && item.hidden) metaNode.classList.add("hidden-state");
  button.append(top, metaNode);
  if (item.kind === "workflow") {
    const action = document.createElement("span");
    action.className = "studio-file-item-action";
    action.textContent = `${t("studio.open_editor", "Open Editor")} →`;
    button.appendChild(action);
  }
  button.onclick = () => void openAssetItem(item);
  if (item.kind === "workflow") {
    button.oncontextmenu = (event) => {
      event.preventDefault();
      openWorkflowContextMenu(item, event.clientX, event.clientY);
    };
  }
  root.appendChild(button);
}
function closeWorkflowContextMenu() {
  const menu = $("workflowContextMenu");
  if (!menu) return;
  menu.hidden = true;
  delete menu.dataset.workflowId;
}
function workflowContextItem() {
  const id = $("workflowContextMenu")?.dataset.workflowId || "";
  return (state.studioFiles.workflows || []).find((item) => item.id === id) || null;
}
function openWorkflowContextMenu(item, x, y) {
  const menu = $("workflowContextMenu");
  if (!menu || !item) return;
  menu.dataset.workflowId = item.id;
  $("workflowContextOpen").textContent = t("studio.open_editor", "Open Editor");
  $("workflowContextVisibility").textContent = item.hidden
    ? t("assets.show_in_chat", "Show in Chat")
    : t("assets.hide_from_chat", "Hide from Chat");
  $("workflowContextRename").disabled = !!item.readonly || !state.studioGuard.editable;
  $("workflowContextDuplicate").disabled = !state.studioGuard.editable;
  $("workflowContextDelete").disabled = !!item.readonly || item.deletable === false || !state.studioGuard.editable;
  menu.hidden = false;
  menu.style.left = "0px";
  menu.style.top = "0px";
  const rect = menu.getBoundingClientRect();
  const left = Math.max(8, Math.min(x, window.innerWidth - rect.width - 8));
  const top = Math.max(8, Math.min(y, window.innerHeight - rect.height - 8));
  menu.style.left = `${left}px`;
  menu.style.top = `${top}px`;
}

async function renameWorkflowItem(item) {
  if (!item || item.kind !== "workflow" || item.readonly || !state.studioGuard.editable) return;
  closeWorkflowContextMenu();
  const name = await inputDialog({
    title: "Rename Workflow",
    message: "Rename keeps the Workflow in the same Global / Project asset root.",
    label: "Workflow name",
    value: item.name,
    confirmLabel: "Rename",
  });
  if (!name || name === item.name) return;
  try {
    await api("/api/studio/rename", { method: "POST", body: JSON.stringify({ id: item.id, project: state.project?.path || "", name }) });
    await refreshStudioFiles({ force: true });
    showToast("Workflow renamed");
  } catch (error) { showActionError(error.message, "Workflow rename failed"); }
}

async function duplicateWorkflowItem(item) {
  if (!item || item.kind !== "workflow" || !state.studioGuard.editable) return;
  closeWorkflowContextMenu();
  const name = await inputDialog({
    title: "Duplicate Workflow",
    message: "Create an independent copy in the same asset root.",
    label: "Workflow name",
    value: window.StudioSupport.duplicateName(item.name),
    confirmLabel: "Duplicate",
  });
  if (!name) return;
  try {
    await api("/api/studio/duplicate", { method: "POST", body: JSON.stringify({ id: item.id, project: state.project?.path || "", name }) });
    await refreshStudioFiles({ force: true });
    showToast("Workflow duplicated");
  } catch (error) { showActionError(error.message, "Workflow duplicate failed"); }
}

async function exportWorkflowItem(item) {
  if (!item || item.kind !== "workflow") return;
  closeWorkflowContextMenu();
  try {
    const data = await api(`/api/studio/export?id=${encodeURIComponent(item.id)}${projectQuery()}`);
    const name = String(data.name || item.name || "workflow.yaml");
    const blob = new Blob([String(data.content ?? "")], { type: "text/yaml;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url; link.download = name; document.body.appendChild(link); link.click(); link.remove();
    URL.revokeObjectURL(url);
    showToast("Workflow exported");
  } catch (error) { showActionError(error.message, "Workflow export failed"); }
}

async function deleteWorkflowItem(item) {
  if (!item || item.kind !== "workflow" || item.readonly || item.deletable === false || !state.studioGuard.editable) return;
  closeWorkflowContextMenu();
  const ok = await confirmDialog({
    title: "Delete Workflow?",
    message: `Delete ${item.name}? This removes the Workflow asset but does not modify project source files.`,
    confirmLabel: "Delete Workflow",
    danger: true,
  });
  if (!ok) return;
  try {
    await api("/api/studio/delete", { method: "POST", body: JSON.stringify({ id: item.id, project: state.project?.path || "" }) });
    await refreshStudioFiles({ force: true });
    renderWorkflowPicker();
    showToast("Workflow deleted");
  } catch (error) { showActionError(error.message, "Workflow deletion failed"); }
}

function renderStudioFiles() {
  const root = $("studioFileList");
  const previousScrollTop = root?.scrollTop || 0;
  const isPrompt = state.studioSourceKind === "prompt";
  if ($("assetPageTitle")) $("assetPageTitle").textContent = isPrompt ? t("assets.prompts_title", "Prompts") : t("assets.workflows_title", "Workflows");
  if ($("assetPageDescription")) $("assetPageDescription").textContent = isPrompt
    ? t("assets.prompts_desc", "Manage reusable Prompt assets used by Workflow Stages.")
    : t("assets.workflows_desc", "Manage Workflows available to Project Chat.");
  $("generateWorkflowButton").hidden = isPrompt;

  const body = document.querySelector(".studio-designer-body");
  const workflowManager = state.studioSourceKind === "workflow";
  body?.classList.toggle("workflow-manager-mode", workflowManager);
  body?.classList.toggle("prompt-manager-mode", !workflowManager);
  root.innerHTML = "";
  $("studioListTitle").textContent =
    state.studioSourceKind === "prompt" ? "Prompts" : "Workflows";
  $("newWorkflowButton").hidden = false;
  $("newWorkflowButton").title =
    state.studioSourceKind === "prompt" ? "New prompt" : "New workflow";
  syncStudioSearch();

  const items = filteredStudioFiles();
  for (const scope of ["global", "project"]) {
    const rows = items.filter((item) => item.scope === scope);
    if (!rows.length) continue;
    const heading = document.createElement("div");
    heading.className = "studio-file-group";
    heading.textContent = scope === "project" ? "Project" : "Global";
    root.appendChild(heading);
    rows.forEach((item) => appendStudioItem(root, item));
  }

  if (!root.querySelector(".studio-file-item")) {
    const empty = document.createElement("div");
    empty.className = "studio-list-empty";
    const noun = state.studioSourceKind === "prompt" ? "prompts" : "workflows";
    if (studioSearchQuery()) {
      const text = document.createElement("span");
      text.textContent = `No matching ${noun}`;
      const clear = document.createElement("button");
      clear.type = "button";
      clear.className = "studio-empty-action";
      clear.textContent = "Clear search";
      clear.onclick = () => {
        state.studioFilters[state.studioSourceKind] = "";
        syncStudioSearch();
        renderStudioFiles();
        $("studioSearchInput")?.focus();
      };
      empty.append(text, clear);
    } else {
      const text = document.createElement("span");
      text.textContent = `No ${noun} yet`;
      const create = document.createElement("button");
      create.type = "button";
      create.className = "studio-empty-action";
      create.textContent = state.studioSourceKind === "prompt" ? "Create Prompt" : "Create Workflow";
      create.onclick = () => state.studioSourceKind === "prompt" ? openNewPromptModal() : openNewWorkflowModal();
      empty.append(text, create);
    }
    root.appendChild(empty);
  }
  if (root && root.scrollTop !== previousScrollTop) root.scrollTop = previousScrollTop;
}
function clearStudioEditor() {
  closeStudioAssetMenu();
  state.studioFile = null; state.studioOriginal = ""; state.studioHash = ""; state.studioDirty = false;
  $("studioEditor").hidden = true; $("studioEmpty").hidden = false; $("validationOutput").hidden = true; state.studioErrorDetail = ""; state.validationDetail = ""; state.validationSummary = ""; renderStudioVisibilityBadge(); $("studioPromptTextarea").value = ""; updateDirtyState(); renderStudioPanels();
}
function studioCacheVersion(item) { return String(item?.version || ""); }
// Hidden Workflows remain editable in Studio but are omitted from the Tasks selector.
function renderStudioVisibilityBadge() {
  const scopeBadge = $("studioScopeBadge"), item = state.studioFile;
  if (!scopeBadge) return;
  const scope = String(item?.scope || "").toLowerCase();
  scopeBadge.hidden = !item;
  scopeBadge.className = `studio-scope-badge ${scope || "global"}`;
  scopeBadge.textContent = scope === "project" ? "PROJECT" : "GLOBAL";
}
const PROMPT_DRAFT_PREFIX = "ai-task-runner:prompt-draft:v1:";
function promptDraftKey(id) { return PROMPT_DRAFT_PREFIX + String(id || ""); }
function readPromptDraft(id) {
  if (!id) return null;
  try {
    const value = JSON.parse(localStorage.getItem(promptDraftKey(id)) || "null");
    return value && typeof value === "object" ? value : null;
  } catch (_) { return null; }
}
function clearPromptDraft(id) {
  if (!id) return;
  try { localStorage.removeItem(promptDraftKey(id)); } catch (_) {}
}
function persistPromptDraft() {
  if (!state.studioFile || state.studioFile.kind !== "prompt") return;
  if (!state.studioDirty) return clearPromptDraft(state.studioFile.id);
  try {
    localStorage.setItem(promptDraftKey(state.studioFile.id), JSON.stringify({
      hash: state.studioHash,
      content: currentEditorContent(),
      savedAt: Date.now(),
    }));
  } catch (_) {}
}
async function maybeRestorePromptDraft(data) {
  const draft = readPromptDraft(data?.id);
  if (!draft) return;
  if (draft.hash !== data.hash) {
    clearPromptDraft(data.id);
    return;
  }
  const content = typeof draft.content === "string" ? draft.content : "";
  if (!content || content === data.content) {
    clearPromptDraft(data.id);
    return;
  }
  const choice = await choiceDialog({
    title: "Restore unsaved Prompt draft?",
    message: "A local draft from this saved version was found.",
    choices: [
      { label: "Restore Draft", value: "restore", primary: true },
      { label: "Discard Draft", value: "discard", danger: true },
    ],
  });
  if (choice === "restore") {
    $("studioPromptTextarea").value = content;
    updateDirtyState();
    scheduleSyntaxCheck();
    setStudioStatus("Restored unsaved local draft.");
  } else if (choice === "discard") {
    clearPromptDraft(data.id);
  }
}
function invalidateStudioFileCache(id = "") { if (id) state.studioFileCache.delete(id); else state.studioFileCache.clear(); }
function applyStudioLoaded(data, _visual, item, cached = false) {
  state.studioFile = data; state.studioOriginal = data.content; state.studioHash = data.hash; state.studioDirty = false; renderPromptUsage();
  state.studioGuard = data.guard || state.studioGuard;
  $("studioEmpty").hidden = true; $("studioEditor").hidden = false; $("studioFileName").textContent = data.name; $("studioFilePath").textContent = `${data.scope} · ${data.path}`; $("studioKindLabel").textContent = "Prompt"; $("validationOutput").hidden = true; state.validationDetail = ""; state.validationSummary = ""; renderStudioVisibilityBadge();
  $("studioPromptTextarea").value = data.content;
  renderStudioGuard(); renderStudioFiles(); renderStudioPanels(); renderPromptTags(); updateDirtyState(); scheduleSyntaxCheck(); setStudioStatus(cached ? "" : "");
}
async function openStudioFile(item) {
  closeStudioAssetMenu();
  if (state.studioFile?.id === item.id && !state.studioDirty) return;
  if (state.studioFile?.id !== item.id && !(await confirmDiscardStudio())) return;
  const token = ++state.studioOpenToken;
  if (item.kind !== "prompt") return openWorkflowEditorItem(item);
  const cached = state.studioFileCache.get(item.id);
  if (cached && cached.version === studioCacheVersion(item) && (Date.now() - Number(cached.loadedAt || 0)) < 15000) {
    applyStudioLoaded(cached.data, null, item, true);
    await maybeRestorePromptDraft(cached.data);
    refreshPromptTags();
    return;
  }
  state.studioFile = { ...item, content: "", hash: "" }; renderPromptUsage();
  $("studioPromptTextarea").value = "";
  $("studioEmpty").hidden = true; $("studioEditor").hidden = false; $("studioFileName").textContent = item.name; $("studioFilePath").textContent = `${item.scope} · ${item.path}`; $("studioKindLabel").textContent = "Prompt"; renderStudioVisibilityBadge();
  renderStudioFiles(); renderStudioPanels(); setStudioStatus("Loading…");
  setStudioContentLoading(true, "Loading prompt…");
  try {
    const data = await api(`/api/studio/file?id=${encodeURIComponent(item.id)}${projectQuery()}`);
    if (token !== state.studioOpenToken) return;
    state.studioFileCache.set(item.id, { version: studioCacheVersion(item), loadedAt: Date.now(), data });
    applyStudioLoaded(data, null, item);
    await maybeRestorePromptDraft(data);
    await refreshPromptTags();
  } catch (error) { if (token === state.studioOpenToken) setStudioStatus(error.message, true); }
  finally { if (token === state.studioOpenToken) setStudioContentLoading(false); }
}
function openWorkflowEditorItem(item) {
  if (!item || item.kind !== "workflow") return;
  const params = new URLSearchParams({ id: item.id });
  if (state.project?.path) params.set("project", state.project.path);
  window.location.href = `/workflow-studio-app/index.html?${params}`;
}

async function openAssetItem(item) {
  if (!item) return;
  if (item.kind === "workflow") {
    openWorkflowEditorItem(item);
    return;
  }
  await openStudioFile(item);
}

async function restoreWorkflowStudioNavigation() {
  const params = new URLSearchParams(window.location.search);
  if (params.get("view") !== "workflow") return;

  const projectPath = params.get("project") || "";
  if (projectPath) {
    const project = state.projects.find((item) => sameProjectPath(item.path, projectPath));
    if (project && !sameProjectPath(state.project?.path, project.path)) await selectProject(project);
  }

  const source = params.get("source") === "prompt" ? "prompt" : "workflow";
  await switchView(source);
  await refreshStudioFiles({ force: true });
  renderStudioFiles();
  const studioId = params.get("studio") || "";
  if (studioId && source === "prompt") {
    const item = (state.studioFiles.prompts || []).find((row) => row.id === studioId);
    if (item) await openAssetItem(item);
  }
  window.history.replaceState({}, "", window.location.pathname);
}

function renderStudioPanels() {
  const panel = $("promptEditorPanel");
  if (panel) panel.hidden = state.studioFile?.kind !== "prompt";
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
function renderPromptUsage() {
  const root = $("studioPromptUsedBy");
  if (!root) return;
  root.innerHTML = "";
  const usages = Array.isArray(state.studioFile?.used_by) ? state.studioFile.used_by : [];
  if (!usages.length) {
    const empty = document.createElement("span");
    empty.className = "prompt-used-by-empty";
    empty.textContent = "Not referenced by any Workflow Stage.";
    root.appendChild(empty);
    return;
  }
  usages.forEach((usage) => {
    const chip = document.createElement("span");
    chip.className = "prompt-used-by-chip";
    chip.textContent = String(usage);
    chip.title = String(usage);
    root.appendChild(chip);
  });
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

function handlePromptEditorKeydown(event) { if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "s") { event.preventDefault(); saveStudio(); } }
function currentEditorContent() { return state.studioFile?.kind === "prompt" ? $("studioPromptTextarea").value : ""; }
function scheduleSyntaxCheck() {
  clearTimeout(state.syntaxTimer);
  const badge = $("syntaxBadge");
  if (!state.studioFile) { if (badge) badge.hidden = true; promptDiagnostics(null); return; }
  if (badge) badge.hidden = true;
  state.syntaxTimer = setTimeout(checkPromptSyntax, 320);
}
function updateDirtyState() {
  state.studioDirty = !!state.studioFile && currentEditorContent() !== state.studioOriginal;
  const dirtyBadge = $("dirtyBadge");
  if (dirtyBadge) {
    dirtyBadge.hidden = !state.studioFile;
    dirtyBadge.textContent = state.studioSaving ? "SAVING" : state.studioDirty ? "UNSAVED" : "SAVED";
    dirtyBadge.classList.toggle("warning", state.studioDirty && !state.studioSaving);
    dirtyBadge.classList.toggle("success", !state.studioDirty && !state.studioSaving);
  }
  const locked = !state.studioGuard.editable || !!state.studioFile?.readonly;
  $("studioPromptTextarea").readOnly = locked;
  renderPromptTags();
  $("saveStudioButton").disabled = locked || !state.studioDirty;
  $("saveStudioButton").title = locked
    ? "Stop the active Runtime or open an editable asset before saving."
    : !state.studioDirty ? "No unsaved changes." : "Save changes (Ctrl+S).";
  $("validateStudioButton").hidden = !state.studioFile;
  $("validateStudioButton").disabled = !state.studioFile;
  $("validateStudioButton").textContent = "Validate Prompt";
  $("newWorkflowButton").disabled = !state.studioGuard.editable;
  $("importAssetButton").disabled = !state.studioGuard.editable;
  $("importAssetButton").textContent = state.studioSourceKind === "workflow" ? "Import YAML" : "Import Prompt";
  $("exportStudioButton").textContent = "Export";
  $("exportStudioButton").disabled = !state.studioFile;
  $("deleteStudioButton").hidden = !state.studioFile || !!state.studioFile.readonly;
  $("deleteStudioButton").disabled = !state.studioGuard.editable || !state.studioFile?.deletable;
  $("studioAssetMenuButton").disabled = !state.studioFile;
  $("renameStudioButton").disabled = !state.studioGuard.editable || !state.studioFile || !!state.studioFile.readonly;
  $("duplicateStudioButton").disabled = !state.studioGuard.editable || !state.studioFile;
}
function renderStudioGuard() {
  const guard = state.studioGuard || { editable: true, active_projects: [] }, badge = $("studioLockBadge"), banner = $("studioLockBanner");
  const active = guard.active_projects || [];
  badge.className = "runtime-badge";
  if (active.length) {
    badge.textContent = "Next run";
    badge.classList.add("running");
    const names = active.map((p) => `${p.name}${p.pid ? ` (PID ${p.pid})` : ""}`).join(", ");
    banner.textContent = `Active Run uses a frozen Workflow/Prompt snapshot. Edits here apply only to the next Run · ${names || "active project"}`;
    banner.hidden = false;
  } else if (guard.editable) {
    badge.textContent = "Editable";
    badge.classList.add("completed");
    banner.hidden = true;
  } else {
    badge.textContent = "Read only";
    badge.classList.add("interrupted");
    banner.textContent = guard.reason || "Workflow editing is unavailable.";
    banner.hidden = false;
  }
  updateDirtyState(); applyStudioGuardToDialogs();
}
function applyStudioGuardToDialogs() {
  const locked = !state.studioGuard.editable;
  if (!$("newWorkflowBackdrop").hidden) {
    $("newWorkflowBackdrop").querySelectorAll('input, select').forEach((node) => { node.disabled = locked; });
    $("newWorkflowConfirm").disabled = locked;
  }
  if (!$("workflowGeneratorPage").hidden) {
    const building = ["running", "cancelling"].includes(state.generateWorkflowPhase);
    $("generateWorkflowRequest").disabled = building || state.generateWorkflowPhase !== "form";
    $("generateWorkflowBackend").disabled = building || state.generateWorkflowPhase !== "form";
    $("generateWorkflowConfirm").disabled = building;
    $("generateWorkflowSave").disabled = state.generateWorkflowPhase !== "ready" || locked;
    $("generateWorkflowValidate").disabled = state.generateWorkflowPhase !== "ready";
  }
}
async function refreshStudioGuard() {
  if (state.view !== "workflow") return;
  if (state.studioGuardRefreshPromise) return state.studioGuardRefreshPromise;
  state.studioGuardRefreshPromise = (async () => {
    try { state.studioGuard = await api("/api/studio/guard", { timeoutMs: 15000 }); renderStudioGuard(); } catch (_) {}
    finally { state.studioGuardRefreshPromise = null; }
  })();
  return state.studioGuardRefreshPromise;
}
async function saveStudio() {
  if (!state.studioFile || state.studioFile.kind !== "prompt" || !state.studioGuard.editable || state.studioSaving || !state.studioDirty) return;
  const button = $("saveStudioButton"), originalLabel = button?.textContent || "Save";
  state.studioSaving = true;
  updateDirtyState();
  if (button) { button.disabled = true; button.setAttribute("aria-busy", "true"); button.textContent = "Saving…"; }
  try {
    const content = $("studioPromptTextarea").value;
    const check = await api("/api/studio/prompt/check", { method: "POST", body: JSON.stringify({ id: state.studioFile.id, project: state.project?.path || "", content }) });
    promptDiagnostics(check);
    if (!check.ok) { setStudioStatus(check.summary, true); showActionError(check.summary, "Prompt save failed"); return; }
    const data = await api("/api/studio/save", { method: "POST", body: JSON.stringify({ id: state.studioFile.id, project: state.project?.path || "", content, hash: state.studioHash }) });
    state.studioFile = data; state.studioOriginal = data.content; state.studioHash = data.hash; state.studioDirty = false; clearPromptDraft(data.id);
    $("studioPromptTextarea").value = data.content;
    updateDirtyState(); scheduleSyntaxCheck(); setStudioStatus(""); showToast("Prompt saved");
  } catch (error) { setStudioStatus(error.message, true); showActionError(error.message, "Prompt save failed"); }
  finally { state.studioSaving = false; if (button) { button.removeAttribute("aria-busy"); button.textContent = originalLabel; } updateDirtyState(); }
}

async function reloadStudio() {
  if (!state.studioFile || state.studioFile.kind !== "prompt" || !(await confirmDiscardStudio())) return;
  invalidateStudioFileCache(state.studioFile.id);
  await openStudioFile(state.studioFile);
}

async function validateStudio() {
  if (!state.studioFile || state.studioFile.kind !== "prompt" || state.studioValidating) return;
  const body = { id: state.studioFile.id, project: state.project?.path || "", content: $("studioPromptTextarea").value };
  const button = $("validateStudioButton");
  state.studioValidating = true;
  if (button) { button.disabled = true; button.setAttribute("aria-busy", "true"); button.textContent = "Validating…"; }
  try {
    const result = await api("/api/studio/validate", { method: "POST", body: JSON.stringify(body) });
    promptDiagnostics(result);
    if (result.ok) {
      state.validationDetail = ""; state.validationSummary = ""; $("validationOutput").hidden = true; setStudioStatus(""); showToast("Prompt validation passed");
    } else {
      const detail = String(result.output || result.summary || "Prompt validation failed").trim();
      const summary = errorSummary(detail, "Prompt validation failed");
      state.validationDetail = detail; state.validationSummary = summary;
      $("validationOutputText").textContent = summary; $("validationOutputText").title = detail; $("validationOutput").hidden = false;
      setStudioStatus(detail, true); showToast("Prompt validation failed", "error", 3200);
    }
  } catch (error) { setStudioStatus(error.message, true); showActionError(error.message, "Prompt validation failed"); }
  finally { state.studioValidating = false; if (button) { button.removeAttribute("aria-busy"); button.textContent = "Validate Prompt"; button.disabled = !state.studioFile; } }
}

function setStudioStatus(text, error = false) {
  const detail = String(text || "").trim();
  state.studioErrorDetail = error ? detail : "";
  const row = $("studioStatus");
  if (!row) return;
  row.textContent = detail ? errorSummary(detail, error ? "Action failed" : "") : "";
  row.title = detail;
  row.hidden = !detail;
  row.classList.toggle("error", Boolean(error && detail));
  if (error && detail) rememberErrorDetail(detail, "Studio action failed");
}
async function confirmDiscardStudio() {
  if (!state.studioDirty) return true;
  const id = state.studioFile?.id || "";
  const discard = await confirmDialog({ title: "Discard unsaved Prompt changes?", message: "Leaving this Prompt will discard the unsaved Prompt draft.", confirmLabel: "Discard Changes", danger: true });
  if (discard) clearPromptDraft(id);
  return discard;
}

// ------------------------------ New Workflow / Prompt / Import / Export ------------------------------
function openNewWorkflowModal() {
  if (!state.studioGuard.editable) return setStudioStatus("Stop active Runtime before creating Workflow.", true);
  state.newWorkflowDirty = false;
  $("newWorkflowName").value = "";
  $("newWorkflowDestination").value = "global";
  $("newWorkflowDestination").querySelector('option[value="project"]').disabled = !state.project;
  $("newWorkflowHint").textContent = "";
  $("newWorkflowHint").classList.remove("error");
  $("newWorkflowBackdrop").hidden = false;
  setTimeout(() => $("newWorkflowName").focus(), 0);
}
async function closeNewWorkflowModal(force = false) {
  if ($("newWorkflowBackdrop").hidden) return true;
  if (!force && state.newWorkflowDirty) {
    const ok = await confirmDialog({ title: "Discard new Workflow?", message: "Discard this unsaved Workflow draft?", confirmLabel: "Discard Workflow", danger: true });
    if (!ok) return false;
  }
  $("newWorkflowBackdrop").hidden = true;
  state.newWorkflowDirty = false;
  return true;
}
async function confirmNewWorkflow() {
  const name = $("newWorkflowName").value.trim();
  if (!name) {
    $("newWorkflowHint").textContent = "Workflow name is required.";
    $("newWorkflowHint").classList.add("error");
    return;
  }
  try {
    const result = await api("/api/studio/workflow/create", {
      method: "POST",
      body: JSON.stringify({
        project: state.project?.path || "",
        name,
        destination: $("newWorkflowDestination").value,
      }),
    });
    await closeNewWorkflowModal(true);
    state.studioSourceKind = "workflow";
    await refreshStudioFiles({ force: true });
    const item = (state.studioFiles.workflows || []).find((row) => row.id === result.item.id) || result.item;
    if (item) openWorkflowEditorItem(item);
    showToast(`Workflow ${result.file.name} created`);
  } catch (error) {
    $("newWorkflowHint").textContent = error.message;
    $("newWorkflowHint").classList.add("error");
    showActionError(error.message, "Workflow creation failed");
  }
}
function openNewPromptModal() {
  if (!state.studioGuard.editable) return setStudioStatus("Stop active Runtime before creating Prompt.", true);
  state.newPromptDirty = false;
  $("newPromptName").value = "";
  $("newPromptDestination").value = "global";
  $("newPromptDestination").querySelector('option[value="project"]').disabled = !state.project;
  $("newPromptHint").textContent = "";
  $("newPromptHint").classList.remove("error");
  $("newPromptBackdrop").hidden = false;
  setTimeout(() => $("newPromptName").focus(), 0);
}
async function closeNewPromptModal(force = false) {
  if ($("newPromptBackdrop").hidden) return true;
  if (!force && state.newPromptDirty) {
    const ok = await confirmDialog({ title: "Discard new Prompt?", message: "Discard this unsaved Prompt draft?", confirmLabel: "Discard Prompt", danger: true });
    if (!ok) return false;
  }
  $("newPromptBackdrop").hidden = true;
  state.newPromptDirty = false;
  return true;
}
async function confirmNewPrompt() {
  const name = $("newPromptName").value.trim();
  if (!name) {
    $("newPromptHint").textContent = "Prompt name is required.";
    $("newPromptHint").classList.add("error");
    return;
  }
  try {
    const result = await api("/api/studio/prompt/create", {
      method: "POST",
      body: JSON.stringify({
        project: state.project?.path || "",
        name,
        destination: $("newPromptDestination").value,
      }),
    });
    await closeNewPromptModal(true);
    state.studioSourceKind = "prompt";
    await refreshStudioFiles({ force: true });
    const item = (state.studioFiles.prompts || []).find((row) => row.id === result.item.id) || result.item;
    if (item) await openAssetItem(item);
    showToast(`Prompt ${result.file.name} created`);
  } catch (error) {
    $("newPromptHint").textContent = error.message;
    $("newPromptHint").classList.add("error");
    showActionError(error.message, "Prompt creation failed");
  }
}
function openImportAssetModal() {
  if (!state.studioGuard.editable) return showActionError("Stop active Runtime before importing.", "Import unavailable");
  state.importAssetDirty = false;
  const kind = state.studioSourceKind === "workflow" ? "workflow" : "prompt";
  $("importAssetTitle").textContent = `Import ${kind === "workflow" ? "Workflow" : "Prompt"}`;
  $("importAssetDescription").textContent = "Import one editable Global or Project asset.";
  $("importAssetName").value = "";
  $("importAssetContent").value = "";
  $("importAssetFile").value = "";
  $("importAssetFileName").textContent = "No file selected";
  $("importAssetFile").accept = kind === "workflow" ? ".yaml,.yml,text/yaml,text/plain" : ".md,text/markdown,text/plain";
  $("importAssetDestination").value = "global";
  $("importAssetDestination").querySelector('option[value="project"]').disabled = !state.project;
  $("importAssetHint").textContent = "";
  $("importAssetHint").classList.remove("error");
  $("importAssetPreview").textContent = "Choose a file or paste content.";
  $("importAssetBackdrop").hidden = false;
}
async function closeImportAssetModal(force = false) {
  if ($("importAssetBackdrop").hidden) return true;
  if (!force && state.importAssetDirty) {
    const ok = await confirmDialog({ title: "Discard import?", message: "Discard the selected import?", confirmLabel: "Discard Import", danger: true });
    if (!ok) return false;
  }
  $("importAssetBackdrop").hidden = true;
  state.importAssetDirty = false;
  return true;
}
function parseImportedText(text, fallbackName) {
  const trimmed = String(text || "").trim();
  if (!trimmed) return { name: fallbackName || "", content: "" };
  try {
    const parsed = JSON.parse(trimmed);
    if (parsed && typeof parsed === "object" && ["workflow", "prompt"].includes(parsed.kind) && typeof parsed.content === "string") {
      return { name: parsed.name || fallbackName || "", content: parsed.content, kind: parsed.kind };
    }
  } catch (_) {}
  return { name: fallbackName || "", content: text };
}
async function readImportAssetFile() {
  const file = $("importAssetFile").files?.[0];
  if (!file) return;
  const text = await file.text();
  const parsed = parseImportedText(text, file.name);
  $("importAssetFileName").textContent = file.name;
  $("importAssetName").value = parsed.name || file.name;
  $("importAssetContent").value = parsed.content;
  state.importAssetDirty = true;
  $("importAssetPreview").textContent = `${(parsed.content || "").split("\n").length} lines ready to validate.`;
}
async function confirmImportAsset() {
  const kind = state.studioSourceKind === "workflow" ? "workflow" : "prompt";
  const parsed = parseImportedText($("importAssetContent").value, $("importAssetName").value.trim());
  if (!parsed.content?.trim()) {
    $("importAssetHint").textContent = "Import content is empty.";
    $("importAssetHint").classList.add("error");
    return;
  }
  try {
    const result = await api("/api/studio/import", {
      method: "POST",
      body: JSON.stringify({
        project: state.project?.path || "",
        kind,
        name: parsed.name || $("importAssetName").value.trim(),
        content: parsed.content,
        destination: $("importAssetDestination").value,
      }),
    });
    await closeImportAssetModal(true);
    await refreshStudioFiles({ force: true });
    const list = kind === "workflow" ? state.studioFiles.workflows : state.studioFiles.prompts;
    const item = (list || []).find((row) => row.id === result.item.id) || result.item;
    if (item) await openAssetItem(item);
    showToast(`${kind === "workflow" ? "Workflow" : "Prompt"} imported`);
  } catch (error) {
    $("importAssetHint").textContent = error.message;
    $("importAssetHint").classList.add("error");
    showActionError(error.message, "Import failed");
  }
}

async function exportStudioAsset() {
  if (!state.studioFile) return;
  const button = $("exportStudioButton");
  await withButtonBusy(button, "Exporting…", async () => {
    try {
      const data = await api(`/api/studio/export?id=${encodeURIComponent(state.studioFile.id)}${projectQuery()}`); const name = String(data.name || "export.dat"); let blob;
      const ext = name.toLowerCase().split(".").pop(); const mime = ext === "md" ? "text/markdown;charset=utf-8" : "text/plain;charset=utf-8"; blob = new Blob([String(data.content ?? "")], { type: mime });
      const url = URL.createObjectURL(blob); const a = document.createElement("a"); a.href = url; a.download = name; document.body.appendChild(a); a.click(); a.remove(); URL.revokeObjectURL(url);
      showToast(`${data.kind === "workflow" ? "Workflow" : "Prompt"} exported`);
    } catch (error) { showActionError(error.message, "Export failed"); }
  });
}

async function deleteStudioAsset() {
  if (!state.studioFile || state.studioFile.readonly) return; const current = state.studioFile; const label = current.kind === "prompt" ? "Prompt" : "Workflow";
  if (!(await confirmDialog({ title: `Delete ${label}?`, message: `Delete ${current.name}?${current.kind === "prompt" ? " Deletion is blocked if any Workflow Stage still uses this Prompt." : ""}`, confirmLabel: `Delete ${label}`, danger: true }))) return;
  const button = $("deleteStudioButton");
  await withButtonBusy(button, "Deleting…", async () => {
    try { closeStudioAssetMenu(); await api("/api/studio/delete", { method: "POST", body: JSON.stringify({ id: current.id, project: state.project?.path || "" }) }); clearStudioEditor(); await refreshStudioFiles({ force: true }); showToast(`${label} deleted`); }
    catch (error) { setStudioStatus(error.message, true); showActionError(error.message, `${label} deletion failed`); }
  });
}


async function setWorkflowVisibility(item, hidden) {
  if (!item || item.kind !== "workflow") return;
  try {
    const updated = await api("/api/studio/visibility", { method: "POST", body: JSON.stringify({ id: item.id, project: state.project?.path || "", hidden }) });
    if (state.studioFile?.id === item.id) state.studioFile = { ...state.studioFile, ...updated };
    const row = (state.studioFiles.workflows || []).find((entry) => entry.id === item.id); if (row) Object.assign(row, updated);
    renderStudioFiles(); renderWorkflowPicker(); renderStudioVisibilityBadge(); updateDirtyState(); closeStudioAssetMenu(); closeWorkflowContextMenu();
    showToast(updated.hidden ? t("assets.hidden_from_chat", "Workflow hidden from Chat") : t("assets.visible_in_chat", "Workflow visible in Chat"));
  } catch (error) { showActionError(error.message, "Workflow visibility update failed"); }
}
async function toggleWorkflowVisibility() {
  const item = state.studioFile; if (!item || item.kind !== "workflow") return;
  await setWorkflowVisibility(item, !item.hidden);
}
function closeStudioAssetMenu() { const menu = $("studioAssetMenu"), button = $("studioAssetMenuButton"); if (!menu || !button) return; menu.hidden = true; button.setAttribute("aria-expanded", "false"); }
function toggleStudioAssetMenu() { const menu = $("studioAssetMenu"), button = $("studioAssetMenuButton"); if (!menu || !button || button.disabled) return; const open = menu.hidden; menu.hidden = !open; button.setAttribute("aria-expanded", String(open)); }
async function renameStudioAsset() {
  closeStudioAssetMenu(); const current = state.studioFile; if (!current || current.readonly || !state.studioGuard.editable) return; if (!(await confirmDiscardStudio())) return;
  const label = current.kind === "prompt" ? "Prompt" : "Workflow"; const name = await inputDialog({ title: `Rename ${label}`, message: current.kind === "prompt" ? "Referenced Prompts must be unlinked before rename." : "Rename keeps the file in the same Global / Project scope.", label: `${label} name`, value: current.name, confirmLabel: "Rename" }); if (!name || name === current.name) return;
  try { const result = await api("/api/studio/rename", { method: "POST", body: JSON.stringify({ id: current.id, project: state.project?.path || "", name }) }); await refreshStudioFiles({ force: true }); const list = result.item.kind === "prompt" ? state.studioFiles.prompts : state.studioFiles.workflows; const item = list.find((row) => row.id === result.item.id) || result.item; await openAssetItem(item); showToast(`${label} renamed`); }
  catch (error) { setStudioStatus(error.message, true); showActionError(error.message, `${label} rename failed`); }
}
async function duplicateStudioAsset() {
  closeStudioAssetMenu();
  const current = state.studioFile;
  if (!current || !state.studioGuard.editable) return;
  if (!(await confirmDiscardStudio())) return;
  const label = current.kind === "prompt" ? "Prompt" : "Workflow";
  $("duplicateAssetTitle").textContent = `Duplicate ${label}`;
  $("duplicateAssetIcon").textContent = label[0];
  $("duplicateAssetIcon").className = `modal-title-icon ${current.kind}`;
  $("duplicateAssetDescription").textContent = `Create an independent ${window.StudioSupport.duplicateDestination(current)} copy in the same asset root.`;
  $("duplicateAssetName").value = window.StudioSupport.duplicateName(current.name);
  $("duplicateAssetHint").textContent = "";
  $("duplicateAssetHint").classList.remove("error");
  $("duplicateAssetBackdrop").hidden = false;
  setTimeout(() => $("duplicateAssetName").focus(), 0);
}

function closeDuplicateAssetModal() { $("duplicateAssetBackdrop").hidden = true; }
async function confirmDuplicateAsset() {
  const current = state.studioFile; if (!current) return closeDuplicateAssetModal(); const label = current.kind === "prompt" ? "Prompt" : "Workflow"; const name = $("duplicateAssetName").value.trim(); if (!name) { $("duplicateAssetHint").textContent = `${label} name is required.`; $("duplicateAssetHint").classList.add("error"); return; }
  const button = $("duplicateAssetConfirm"); await withButtonBusy(button, "Duplicating…", async () => {
    try { const result = await api("/api/studio/duplicate", { method: "POST", body: JSON.stringify({ id: current.id, project: state.project?.path || "", name }) }); closeDuplicateAssetModal(); await refreshStudioFiles({ force: true }); const list = result.item.kind === "prompt" ? state.studioFiles.prompts : state.studioFiles.workflows; const item = list.find((row) => row.id === result.item.id) || result.item; await openAssetItem(item); showToast(`${label} duplicated · ${result.item.display_name || result.item.name}`); }
    catch (error) { $("duplicateAssetHint").textContent = error.message; $("duplicateAssetHint").classList.add("error"); showActionError(error.message, `${label} duplicate failed`); }
  });
}


// ------------------------------ AI Workflow Builder page ------------------------------
const {
  clearGenerateWorkflowPoll,
  fillGenerateWorkflowBackends,
  copyWorkflowWorkspace,
  bindWorkflowWorkspaceCopy,
  setGenerateWorkflowWorkspace,
  resetGenerateWorkflowState,
  showWorkflowStudioPage,
  restoreWorkflowStudioAfterGenerator,
  showWorkflowGeneratorPage,
  setGenerateWorkflowPhase,
  flowNameFromDraft,
  renderGeneratedDraftFlow,
  renderGeneratedDraftPrompts,
  setGeneratedDraftTab,
  focusGeneratedDraftEditor,
  markGeneratedDraftDirty,
  generatedDraftPayload,
  renderGeneratedDraft,
  hydrateActiveGenerateWorkflow,
  restoreActiveWorkflowGenerator,
  pollGenerateWorkflow,
  startGenerateWorkflowPoll,
  normalizeGeneratedWorkflowFilename,
  updateGenerateWorkflowTargetPreview,
  updateGenerateWorkflowSavePreview,
  openGenerateWorkflowPage,
  closeGenerateWorkflowSaveModal,
  discardGenerateWorkflowDraft,
  cancelGenerateWorkflow,
  leaveGenerateWorkflowPage,
  confirmGenerateWorkflow,
  regenerateWorkflowDraft,
  validateGeneratedWorkflowDraft,
  openGenerateWorkflowSaveModal,
  saveGenerateWorkflowDraft,
 } = createWorkflowGenerator({
  state, $, api, showToast, showActionError, confirmDialog, confirmDiscardStudio,
  renderStudioFiles, renderWorkflowPicker, renderStudioPanels, refreshStudioFiles,
  applyStudioGuardToDialogs, refreshStudioGuard, openStudioFile,
});

// ------------------------------ Add Project modal ------------------------------
function openProjectModal() { $("projectPathInput").value = ""; $("projectModalHint").textContent = window.I18n?.getLanguage?.() === "en" ? "Paste a path directly, or use Browse to choose a folder." : "可直接貼上路徑，或使用 Browse 選擇資料夾。"; $("projectModalHint").classList.remove("error"); $("projectModalBackdrop").hidden = false; setTimeout(() => $("projectPathInput").focus(), 0); }
function closeProjectModal() { $("projectModalBackdrop").hidden = true; }
async function browseProject() {
  $("projectModalHint").textContent = "Opening folder picker…";
  await withButtonBusy($("browseProjectButton"), "Opening…", async () => {
    try { const result = await api("/api/projects/pick", { method: "POST", body: "{}" }); if (!result.cancelled && result.path) { $("projectPathInput").value = result.path; $("projectModalHint").textContent = t("project.folder_selected", "Folder selected. Click Open Project to add it."); } else $("projectModalHint").textContent = t("project.folder_cancelled", "Folder selection cancelled."); }
    catch (error) { $("projectModalHint").textContent = `${error.message} · You can still paste the folder path.`; $("projectModalHint").classList.add("error"); }
  });
}
async function confirmProjectModal() {
  const path = $("projectPathInput").value.trim(); if (!path) { $("projectModalHint").textContent = "Project path is required."; $("projectModalHint").classList.add("error"); return; }
  await withButtonBusy($("projectModalConfirm"), "Adding…", async () => {
    setProjectListLoading(true, "Adding project…");
    $("projectModalHint").textContent = "Adding project…";
    $("projectModalHint").classList.remove("error");
    try {
      const added = await api("/api/projects/add", { method: "POST", body: JSON.stringify({ path }) });
      closeProjectModal();
      setProjectListLoading(true, "Refreshing projects…");
      await loadProjects();
      const picked = state.projects.find((p) => sameProjectPath(p.path, added.path));
      if (picked && !sameProjectPath(state.project?.path, picked.path)) {
        setProjectListLoading(true, "Opening project…");
        await selectProject(picked);
      }
      showToast("Project added");
    }
    catch (error) { $("projectModalHint").textContent = error.message; $("projectModalHint").classList.add("error"); showActionError(error.message, "Add Project failed"); }
    finally { setProjectListLoading(false); }
  });
}

// ------------------------------ handlers ------------------------------
$("openProject").onclick = openProjectModal;
$("emptyOpenProjectButton").onclick = openProjectModal;
$("projectModalClose").onclick = closeProjectModal; $("projectModalCancel").onclick = closeProjectModal; $("projectModalConfirm").onclick = confirmProjectModal; $("browseProjectButton").onclick = browseProject; $("projectModalBackdrop").addEventListener("click", (e) => { if (e.target === $("projectModalBackdrop")) closeProjectModal(); });
$("projectPathInput").addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); confirmProjectModal(); } });
$("chatNav").onclick = () => switchView("chat");
$("workflowNav").onclick = () => switchView("workflow");
$("promptNav").onclick = () => switchView("prompt");
$("studioSearchInput").oninput = () => { state.studioFilters[state.studioSourceKind] = $("studioSearchInput").value; renderStudioFiles(); }; $("studioSearchClear").onclick = () => { state.studioFilters[state.studioSourceKind] = ""; renderStudioFiles(); $("studioSearchInput").focus(); };
$("studioPromptTextarea").addEventListener("input", () => { updateDirtyState(); persistPromptDraft(); scheduleSyntaxCheck(); }); $("studioPromptTextarea").addEventListener("keydown", handlePromptEditorKeydown);
$("workflowContextOpen").onclick = () => { const item = workflowContextItem(); closeWorkflowContextMenu(); if (item) openWorkflowEditorItem(item); };
$("workflowContextVisibility").onclick = () => { const item = workflowContextItem(); if (item) void setWorkflowVisibility(item, !item.hidden); };
$("workflowContextRename").onclick = () => { const item = workflowContextItem(); if (item) void renameWorkflowItem(item); };
$("workflowContextDuplicate").onclick = () => { const item = workflowContextItem(); if (item) void duplicateWorkflowItem(item); };
$("workflowContextExport").onclick = () => { const item = workflowContextItem(); if (item) void exportWorkflowItem(item); };
$("workflowContextDelete").onclick = () => { const item = workflowContextItem(); if (item) void deleteWorkflowItem(item); };
$("saveStudioButton").onclick = saveStudio; $("reloadStudioButton").onclick = reloadStudio; $("validateStudioButton").onclick = validateStudio; $("exportStudioButton").onclick = exportStudioAsset; $("deleteStudioButton").onclick = deleteStudioAsset; $("studioAssetMenuButton").onclick = (event) => { event.stopPropagation(); toggleStudioAssetMenu(); }; $("renameStudioButton").onclick = renameStudioAsset; $("duplicateStudioButton").onclick = duplicateStudioAsset; $("importAssetButton").onclick = openImportAssetModal; $("newWorkflowButton").onclick = () => state.studioSourceKind === "prompt" ? openNewPromptModal() : openNewWorkflowModal();
$("newWorkflowClose").onclick = () => closeNewWorkflowModal(); $("newWorkflowCancel").onclick = () => closeNewWorkflowModal(); $("newWorkflowConfirm").onclick = confirmNewWorkflow; $("newWorkflowBackdrop").addEventListener("click", (e) => { if (e.target === $("newWorkflowBackdrop")) closeNewWorkflowModal(); }); $("newWorkflowBackdrop").addEventListener("input", () => { state.newWorkflowDirty = true; }); $("newWorkflowName").addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); confirmNewWorkflow(); } });
$("newPromptClose").onclick = () => closeNewPromptModal(); $("newPromptCancel").onclick = () => closeNewPromptModal(); $("newPromptConfirm").onclick = confirmNewPrompt; $("newPromptBackdrop").addEventListener("click", (e) => { if (e.target === $("newPromptBackdrop")) closeNewPromptModal(); }); $("newPromptBackdrop").addEventListener("input", () => { state.newPromptDirty = true; });
$("duplicateAssetClose").onclick = closeDuplicateAssetModal; $("duplicateAssetCancel").onclick = closeDuplicateAssetModal; $("duplicateAssetConfirm").onclick = confirmDuplicateAsset; $("duplicateAssetBackdrop").addEventListener("click", (e) => { if (e.target === $("duplicateAssetBackdrop")) closeDuplicateAssetModal(); });
$("importAssetClose").onclick = () => closeImportAssetModal(); $("importAssetCancel").onclick = () => closeImportAssetModal(); $("importAssetConfirm").onclick = confirmImportAsset; $("importAssetChooseButton").onclick = () => $("importAssetFile").click(); $("importAssetFile").onchange = readImportAssetFile; $("importAssetBackdrop").addEventListener("click", (e) => { if (e.target === $("importAssetBackdrop")) closeImportAssetModal(); }); $("importAssetBackdrop").addEventListener("input", () => { state.importAssetDirty = true; });
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
$("generateWorkflowFilename")?.addEventListener("input", updateGenerateWorkflowTargetPreview);
$("generateWorkflowSaveFilename")?.addEventListener("input", updateGenerateWorkflowSavePreview);
$("generateWorkflowDestination")?.addEventListener("change", updateGenerateWorkflowSavePreview);
$("generateWorkflowFailedCancel").onclick = () => leaveGenerateWorkflowPage();
$("generateWorkflowRetry").onclick = async () => { const request = state.generateWorkflowRequestText || $("generateWorkflowRequest").value; if (state.generateWorkflowJobId) { try { await api("/api/studio/generate/discard", { method: "POST", body: JSON.stringify({ job_id: state.generateWorkflowJobId }) }); } catch (_) {} } resetGenerateWorkflowState({ keepRequest: true }); state.generateWorkflowRequestText = request; $("generateWorkflowRequest").value = request; fillGenerateWorkflowBackends(); setGenerateWorkflowPhase("form"); };
$("generateWorkflowSaveClose").onclick = closeGenerateWorkflowSaveModal; $("generateWorkflowSaveCancel").onclick = closeGenerateWorkflowSaveModal; $("generateWorkflowSaveConfirm").onclick = saveGenerateWorkflowDraft; $("generateWorkflowSaveBackdrop").addEventListener("click", (e) => { if (e.target === $("generateWorkflowSaveBackdrop")) closeGenerateWorkflowSaveModal(); });
$("workflowDropdownButton").onclick = (event) => { event.stopPropagation(); if (runConfigurationLocked()) return; const menu = $("workflowDropdownMenu"); menu.hidden ? openWorkflowDropdown() : closeWorkflowDropdown(); };
$("backendDropdownButton").onclick = (event) => { event.stopPropagation(); if (runConfigurationLocked()) return; const menu = $("backendDropdownMenu"); menu.hidden ? openBackendDropdown() : closeBackendDropdown(); };
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
  if (!event.target.closest?.("#workflowContextMenu")) closeWorkflowContextMenu();
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
document.querySelectorAll("[data-motion-option]").forEach((button) => { button.onclick = () => applyMotionPreference(button.dataset.motionOption, { persist: true }); });
document.querySelectorAll("[data-language-option]").forEach((button) => { button.onclick = () => { window.I18n?.setLanguage?.(button.dataset.languageOption, { persist: true }); renderThemeControls(); renderProjects(); }; });
window.addEventListener("app-language-changed", () => { renderThemeControls(); if (state?.projects) renderProjects(); });
if (systemColorScheme) { const onSystemAppearanceChanged = () => { if ((document.documentElement.dataset.appearancePreference || "system") === "system") applyThemePreferences(document.documentElement.dataset.theme || "teal", "system"); }; if (systemColorScheme.addEventListener) systemColorScheme.addEventListener("change", onSystemAppearanceChanged); else if (systemColorScheme.addListener) systemColorScheme.addListener(onSystemAppearanceChanged); }
applyThemePreferences(document.documentElement.dataset.theme || readThemePreference(), document.documentElement.dataset.appearancePreference || readAppearancePreference()); applyMotionPreference(document.documentElement.dataset.motion || readMotionPreference());
$("sendButton").onclick = sendMessage;
$("messageInput").addEventListener("input", resizeComposerInput); $("messageInput").addEventListener("keydown", (event) => { if (event.key === "Enter" && !event.shiftKey) { event.preventDefault(); sendMessage(); } });
$("runtimeTraceButton").onclick = () => setRuntimeTraceOpen(!state.runtimeTraceOpen);
$("runtimeTraceClose").onclick = () => setRuntimeTraceOpen(false);
$("runHistoryButton").onclick = () => setRunHistoryOpen(!state.runHistoryOpen);
$("runHistoryClose").onclick = () => setRunHistoryOpen(false);
$("clearHistoryButton").onclick = async () => {
  if (!state.project || state.runtime?.actions?.stop) return;
  const resetStopped = Boolean(state.runtime?.actions?.reset && state.runtime?.actions?.resume);
  const message = resetStopped
    ? "Delete this Project's saved chat history and discard the stopped/resumable task so a new task can be entered?"
    : t("history.confirm_message", "Delete this Project's saved chat history?");
  const ok = await confirmDialog({ title: t("history.confirm_title", "Clear chat history?"), message, confirmLabel: t("history.clear", "Clear history"), danger: true });
  if (!ok) return;
  try {
    await api("/api/project/history/clear", { method: "POST", body: JSON.stringify(payload({ reset_stopped: resetStopped })) });
    state.historyPinnedToBottom = true; state.lastStream = "";
    removeLiveCard();
    await refreshMessages({ forceFollow: true });
    await refreshRuntime({ force: true });
    if (state.runHistoryOpen) await refreshRunHistory();
    showToast(resetStopped ? "Chat history and stopped task cleared" : t("history.cleared", "Chat history cleared"));
  } catch (error) { showActionError(error.message, "Clear history failed"); }
};
$("messages").addEventListener("scroll", () => { state.historyPinnedToBottom = historyNearBottom($("messages")); }, { passive: true });
$("browseValidatorButton").onclick = browseValidator;
$("clearValidatorButton").onclick = () => { if (runConfigurationLocked()) return; $("validator").value = ""; rememberValidator($("workflowSelect")?.value || "", ""); updateValidatorPicker(); };
$("browseAiValidatorPromptButton").onclick = browseAiValidatorPrompt;
$("clearAiValidatorPromptButton").onclick = () => { if (runConfigurationLocked()) return; $("aiValidatorPrompt").value = ""; rememberAiValidatorPrompt($("workflowSelect")?.value || "", ""); updateAiValidatorPromptPicker(); };
$("errorDetailsButton").onclick = showErrorDetails;
$("validationDetailsButton").onclick = openValidationDetails;
$("validationDetailsClose").onclick = closeValidationDetails;
$("validationDetailsOk").onclick = closeValidationDetails;
$("validationDetailsBackdrop").onclick = (event) => { if (event.target === $("validationDetailsBackdrop")) closeValidationDetails(); };
$("validationDetailsCopy").onclick = async () => { try { await navigator.clipboard.writeText(state.validationDetail || ""); showToast("Validation details copied"); } catch (_) { showToast("Unable to copy validation details", "error"); } };
$("errorDetailsClose").onclick = closeErrorDetails;
$("errorDetailsOk").onclick = closeErrorDetails;
$("errorDetailsBackdrop").onclick = (event) => { if (event.target === $("errorDetailsBackdrop")) closeErrorDetails(); };
$("errorDetailsCopy").onclick = async () => { try { await navigator.clipboard.writeText(state.errorDetailsModalText || state.lastErrorDetail || state.studioErrorDetail || ""); showToast("Error details copied"); } catch (_) { showToast("Unable to copy error details", "error"); } };

$("stopButton").onclick = async () => { await withButtonBusy($("stopButton"), "Stopping…", async () => { try { await api("/api/project/stop", { method: "POST", body: JSON.stringify(payload()) }); showToast("Stop requested"); setTimeout(refreshRuntime, 250); } catch (error) { $("errorText").textContent = error.message; showActionError(error.message, "Stop failed"); } }); };
$("resumeButton").onclick = async () => { await withButtonBusy($("resumeButton"), "Continuing…", async () => { try { await api("/api/project/resume", { method: "POST", body: JSON.stringify(payload()) }); showToast("Task continued"); setTimeout(refreshRuntime, 250); } catch (error) { $("errorText").textContent = error.message; showActionError(error.message, "Continue failed"); } }); };
$("resetButton").onclick = async () => {
  const ok = await confirmDialog({ title: "Reset stopped task?", message: "Discard resumable Runner state? UI task history and request snapshots are kept.", confirmLabel: "Reset", danger: true }); if (!ok) return;
  try { await api("/api/project/reset", { method: "POST", body: JSON.stringify(payload()) }); state.lastStream = ""; removeLiveCard(); await refreshRuntime({ force: true }); showToast("Runtime reset"); } catch (error) { $("errorText").textContent = error.message; showActionError(error.message, "Reset failed"); }
};
$("rerunButton").onclick = async () => { await withButtonBusy($("rerunButton"), "Rerunning…", async () => { try { await api("/api/project/rerun", { method: "POST", body: JSON.stringify(payload()) }); showToast("Task rerun started"); setTimeout(refreshRuntime, 250); } catch (error) { $("errorText").textContent = error.message; showActionError(error.message, "Rerun failed"); } }); };
window.addEventListener("keydown", (event) => { if (event.key !== "Escape") return; if (!$("validationDetailsBackdrop").hidden) return closeValidationDetails(); if (!$("workflowContextMenu").hidden) return closeWorkflowContextMenu(); if (!$("errorDetailsBackdrop").hidden) return closeErrorDetails(); if (!$("themePanel").hidden) return closeThemePanel(); if (!$("backendDropdownMenu").hidden) return closeBackendDropdown(); if (!$("optionsPanel").hidden) return closeOptionsPanel(); if (!$("workflowDropdownMenu").hidden) return closeWorkflowDropdown(); if (document.querySelector(".project-action-menu:not([hidden])")) return closeProjectMenus(); if (!$("generateWorkflowSaveBackdrop").hidden) return closeGenerateWorkflowSaveModal(); if (!$("importAssetBackdrop").hidden) return closeImportAssetModal(); if (!$("newPromptBackdrop").hidden) return closeNewPromptModal(); if (!$("newWorkflowBackdrop").hidden) return closeNewWorkflowModal(); if (!$("workflowGeneratorPage").hidden) { leaveGenerateWorkflowPage(); return; } if (!$("projectModalBackdrop").hidden) return closeProjectModal(); });
window.addEventListener("beforeunload", (event) => { if (state.studioDirty || state.generateWorkflowDirty) { event.preventDefault(); event.returnValue = ""; } });
state.preferences = loadUiPreferences(); showEmpty(); resizeComposerInput(); renderRunConfigurationLock(); if (window.ResizeObserver) {
  const composerObserver = new ResizeObserver(syncComposerReserve);
  composerObserver.observe($("composePanel"));
  composerObserver.observe(document.querySelector(".workspace"));
}
window.addEventListener("resize", () => {
  syncComposerReserve(); positionWorkflowDropdown(); if (!$("backendDropdownMenu").hidden) positionUpwardDropdown($("backendDropdownMenu"), $("backendDropdownButton"), $("backendDropdownMenu").children.length, 70); if (!$("themePanel").hidden) positionThemePanel();
  const menu = document.querySelector(".project-action-menu.project-action-menu-portal:not([hidden])"), owner = menu ? projectMenuOwners.get(menu) : null;
  if (menu && owner?.anchor) positionProjectMenu(menu, owner.anchor);
}); Promise.allSettled([refreshBackends(), refreshWorkflowCatalog(), loadProjects()]).then(async () => {
  await restoreWorkflowStudioNavigation();
  await restoreActiveWorkflowGenerator();
}); refreshPromptTags(); startNonOverlappingPoll(refreshRuntime, 1200, 6000); setInterval(updateRuntimeFreshness, 1000); startNonOverlappingPoll(refreshProjectStatuses, projectStatusPollDelay, projectStatusHiddenPollDelay); startNonOverlappingPoll(refreshStudioGuard, 2500, 10000);
document.addEventListener("visibilitychange", () => {
  if (document.hidden) return;
  const work = [refreshRuntime(), refreshProjectStatuses()];
  if (state.view === "workflow" || state.view === "prompt") work.push(refreshStudioGuard());
  Promise.allSettled(work);
});

