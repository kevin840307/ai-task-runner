import { renderTaskRuntimePanel } from "./task-runtime-panel.js";

function cloneDraft(value) {
  if (globalThis.structuredClone) return globalThis.structuredClone(value);
  return JSON.parse(JSON.stringify(value));
}
function draftSignature(value) { return JSON.stringify(value || {}); }

export function createTaskWorkspaceController({ api, confirmDialog, showError, onTaskChanged, openWorkflow, openPrompts, openMergeChat }) {
  let state = null;
  let pendingUploadActions = Promise.resolve();
  let overlay = null;
  let restoreFocus = null;
  let createMenu = null;
  let createContext = null;
  let createMenuOpenedAt = -Infinity;
  let workspaceOptionsToken = 0;
  let taskProjectionToken = 0;
  const byId = (id) => document.getElementById(id);
  const tr = (key, fallback) => window.I18n?.t?.(key, fallback) ?? fallback;
  const trf = (key, values, fallback) => window.I18n?.format?.(key, values, fallback) ?? fallback;

  function ensureMounted() {
    if (overlay) return overlay;
    overlay = document.createElement("div");
    overlay.id = "taskWorkspaceOverlay";
    overlay.className = "task-workspace-overlay";
    overlay.hidden = true;
    overlay.innerHTML = `
      <section id="taskWorkspaceShell" class="task-workspace-shell" role="dialog" aria-modal="true" aria-labelledby="taskWorkspaceTitle">
        <header class="task-workspace-head">
          <button id="taskWorkspaceHeaderBack" class="task-workspace-back" type="button" aria-label="Back">←</button>
          <div class="task-workspace-heading">
            <small id="taskWorkspaceEyebrow">TASK DRAFT</small>
            <strong id="taskWorkspaceTitle">Edit Task</strong>
            <span id="taskWorkspaceMeta"></span>
          </div>
          <div id="taskWorkspaceHeaderActions" class="task-workspace-header-actions" hidden>
            <button id="taskWorkspaceHeaderOpenWorkflow" class="ghost" type="button" hidden>Open Workflow</button>
            <button id="taskWorkspaceHeaderAddTask" type="button">+ Add task</button>
            <button id="taskWorkspaceHeaderMoveExisting" class="ghost" type="button">Move existing</button>
            <button id="taskWorkspaceHeaderYaml" type="button">Edit YAML</button>
            <button id="taskWorkspaceHeaderCancel" type="button">Cancel</button>
            <button id="taskWorkspaceHeaderCreateList" class="primary" type="button">Create Task List</button>
          </div>
          <button id="taskWorkspaceExpand" class="task-workspace-expand" type="button" aria-label="Expand task workspace" aria-pressed="false" title="Expand task workspace">⤢</button>
          <button id="taskWorkspaceClose" class="task-workspace-close" type="button" aria-label="Close task workspace">×</button>
        </header>
        <main id="taskWorkspaceBody" class="task-workspace-body"></main>
        <footer class="task-workspace-foot">
          <button id="taskWorkspaceFooterBack" type="button">Back</button>
          <button id="taskWorkspaceSave" class="primary" type="button">Save draft</button>
        </footer>
      </section>`;
    document.body.appendChild(overlay);
    overlay.addEventListener("mousedown", (event) => {
      if (event.target === overlay) void requestClose();
    });
    byId("taskWorkspaceClose").addEventListener("click", () => void requestClose());
    byId("taskWorkspaceExpand").addEventListener("click", () => setWorkspaceExpanded(!byId("taskWorkspaceShell").classList.contains("expanded")));
    byId("taskWorkspaceHeaderBack").addEventListener("click", () => void handleBack());
    byId("taskWorkspaceFooterBack").addEventListener("click", () => void handleBack());
    byId("taskWorkspaceSave").addEventListener("click", () => void saveWorkspace());
    byId("taskWorkspaceHeaderOpenWorkflow").addEventListener("click", () => {
      if (state?.route !== "list" || state.kind !== "task") return;
      const items = Array.isArray(state.editDraft?.items) ? state.editDraft.items : (Array.isArray(state.task?.items) ? state.task.items : []);
      const item = items[Number(state.selectedListIndex)];
      const workflow = String(item?.workflow || "").trim();
      if (!workflow) return;
      void openWorkflow?.({ workflow, project: String(item?.project || state.task?.project || "") });
    });
    byId("taskWorkspaceHeaderAddTask").addEventListener("click", () => {
      if (state?.route !== "list") return;
      if (state.kind === "task") addTaskListItem();
      else addDraftListItem();
    });
    byId("taskWorkspaceHeaderMoveExisting").addEventListener("click", () => {
      if (state?.route === "list" && state.kind === "task") toggleMoveExisting();
    });
    byId("taskWorkspaceHeaderYaml").addEventListener("click", () => {
      if (state?.route === "list") void openYaml();
    });
    byId("taskWorkspaceHeaderCancel").addEventListener("click", () => void handleBack());
    byId("taskWorkspaceHeaderCreateList").addEventListener("click", () => void saveWorkspace());
    document.addEventListener("keydown", (event) => {
      if (!overlay || overlay.hidden || event.key !== "Escape") return;
      if (!overlay.contains(event.target)) return;
      const projectDropdown = overlay.querySelector(".task-workspace-project-dropdown:not([hidden])");
      if (projectDropdown) {
        event.preventDefault();
        event.stopPropagation();
        projectDropdown.hidden = true;
        const toggle = overlay.querySelector(".task-workspace-project-toggle");
        toggle?.setAttribute("aria-expanded", "false");
        const projectInput = overlay.querySelector("#taskWorkspaceProject");
        if (projectInput) projectInput.dataset.suppressOpenOnFocus = "true";
        projectInput?.focus({ preventScroll: true });
        return;
      }
      event.preventDefault();
      event.stopPropagation();
      void requestClose();
    }, true);
    return overlay;
  }

  function newRequestId(prefix) {
    return prefix + "-" + (globalThis.crypto?.randomUUID?.() || String(Date.now()) + "-" + Math.random().toString(16).slice(2));
  }

  function newItemId() {
    return "item-" + (globalThis.crypto?.randomUUID?.() || String(Date.now()) + "-" + Math.random().toString(16).slice(2));
  }

  async function loadProjectOptions() {
    if (!state) return;
    const owner = state;
    owner.projectOptionsLoading = true;
    try {
      const data = await api("/api/projects", { timeoutMs: 15000 });
      if (state !== owner) return;
      owner.projectOptions = Array.isArray(data?.projects) ? data.projects.slice() : [];
    } catch (error) {
      if (state !== owner) return;
      owner.projectOptions = [];
    } finally {
      if (state === owner) {
        owner.projectOptionsLoading = false;
        if (["editor", "list"].includes(state.route)) render();
      }
    }
  }

  async function loadWorkspaceOptions() {
    if (!state) return;
    const owner = state;
    const token = ++workspaceOptionsToken;
    const editorProject = String(editorDraft()?.items?.[state.index]?.project || "").trim();
    const project = String(editorProject || (state.kind === "task" ? state.task?.project : state.project) || "").trim();
    const taskId = state.kind === "task" ? String(state.task?.task_id || "").trim() : "";
    if (!project) return;
    owner.workspaceOptionsLoading = true;
    owner.workspaceOptionsError = "";
    try {
      const query = new URLSearchParams({ project });
      if (taskId) query.set("task_id", taskId);
      const data = await api("/api/tasks/workspace-options?" + query.toString(), { timeoutMs: 15000 });
      if (state !== owner || token !== workspaceOptionsToken) return;
      owner.workspaceOptions = data && typeof data === "object" ? data : null;
      owner.workspaceOptionsError = "";
    } catch (error) {
      if (state !== owner || token !== workspaceOptionsToken) return;
      owner.workspaceOptions = null;
      owner.workspaceOptionsError = String(error?.message || "Workspace availability unavailable");
    } finally {
      if (state === owner && token === workspaceOptionsToken) {
        owner.workspaceOptionsLoading = false;
        render();
      }
    }
  }

  function workspaceOption(value) {
    const rows = Array.isArray(state?.workspaceOptions?.options) ? state.workspaceOptions.options : [];
    return rows.find((row) => String(row?.value || "") === String(value || "")) || null;
  }

  function blankItem(project, workflow) {
    return {
      item_id: newItemId(),
      title: "",
      prompt: "",
      goal_file: "",
      ai_validator_prompt: "",
      ai_validator_prompt_file: "",
      workflow: String(workflow || ""),
      project: String(project || ""),
      workspace: "auto",
    };
  }

  function closeCreateMenu() {
    if (createMenu) createMenu.hidden = true;
    createContext = null;
    createMenuOpenedAt = -Infinity;
  }

  function ensureCreateMenu() {
    if (createMenu) return createMenu;
    createMenu = document.createElement("div");
    createMenu.id = "taskCreateMenu";
    createMenu.className = "task-create-menu";
    createMenu.hidden = true;
    createMenu.setAttribute("role", "menu");
    for (const [kind, iconText, label, description] of [
      ["task", "＋", "Task", "Create one Task. Opens the shared Task Editor."],
      ["list", "≡", "Task List", "Create a Task List workspace, then add Tasks inside it."],
    ]) {
      const button = document.createElement("button");
      button.type = "button";
      button.dataset.taskCreateKind = kind;
      button.setAttribute("role", "menuitem");
      const icon = document.createElement("span");
      icon.className = "task-create-menu-icon";
      icon.setAttribute("aria-hidden", "true");
      icon.textContent = iconText;
      const copy = document.createElement("span");
      copy.className = "task-create-menu-copy";
      const strong = document.createElement("strong");
      strong.textContent = label;
      const small = document.createElement("small");
      small.textContent = description;
      copy.append(strong, small);
      button.append(icon, copy);
      button.addEventListener("click", () => {
        const context = createContext;
        closeCreateMenu();
        if (!context) return;
        openNew({ ...context, list: kind === "list" });
      });
      createMenu.appendChild(button);
    }
    document.body.appendChild(createMenu);
    document.addEventListener("mousedown", (event) => {
      if (!createMenu || createMenu.hidden) return;
      if (createMenu.contains(event.target) || createContext?.anchor?.contains?.(event.target)) return;
      closeCreateMenu();
    });
    document.addEventListener("keydown", (event) => {
      if (event.key === "Escape" && createMenu && !createMenu.hidden) {
        event.preventDefault();
        event.stopPropagation();
        const anchor = createContext?.anchor;
        closeCreateMenu();
        anchor?.focus?.();
      }
    }, true);
    window.addEventListener("resize", closeCreateMenu);
    window.addEventListener("scroll", () => {
      if (!createMenu || createMenu.hidden) return;
      const now = globalThis.performance?.now?.() ?? Date.now();
      if (now - createMenuOpenedAt < 80) return;
      closeCreateMenu();
    }, true);
    return createMenu;
  }

  function openCreateMenu({ anchor, project, workflows = [], prompts = [], workflow = "" }) {
    const projectPath = String(project || "").trim();
    if (!projectPath) {
      showError?.("Select a Project before creating a Task.", "New Task unavailable");
      return;
    }
    const menu = ensureCreateMenu();
    if (!menu.hidden && createContext?.anchor === anchor) {
      closeCreateMenu();
      return;
    }
    createContext = {
      anchor,
      project: projectPath,
      workflows: Array.isArray(workflows) ? workflows.slice() : [],
      prompts: Array.isArray(prompts) ? prompts.slice() : [],
      workflow: String(workflow || ""),
      returnFocus: anchor,
    };
    menu.hidden = false;
    menu.style.visibility = "hidden";
    const rect = anchor?.getBoundingClientRect?.() || { left: 16, top: 16, bottom: 16, right: 160 };
    const width = menu.offsetWidth || 250;
    const height = menu.offsetHeight || 112;
    const gap = 6;
    const left = Math.min(window.innerWidth - width - 10, Math.max(10, rect.right - width));
    let top = rect.bottom + gap;
    if (top + height > window.innerHeight - 10) top = Math.max(10, rect.top - height - gap);
    menu.style.left = left + "px";
    menu.style.top = top + "px";
    menu.style.visibility = "";
    createMenuOpenedAt = globalThis.performance?.now?.() ?? Date.now();
  }

  function isDraftState() { return state?.kind === "draft"; }
  function editorDraft() { return state?.kind === "task" ? state.editDraft : state?.draft; }
  function yamlDirty() {
    return state?.route === "yaml" && String(state.yamlText || "") !== String(state.yamlOriginal || "");
  }

  function isDirty() {
    if (yamlDirty()) return true;
    if (isDraftState()) return draftSignature(state.draft) !== state.original;
    return state?.kind === "task"
      && !!state.editDraft
      && (state.route === "list" || state.route === "editor")
      && draftSignature(state.editDraft) !== state.editOriginal;
  }

  function draftChildEditorDirty() {
    return !!(
      isDraftState()
      && state.route === "editor"
      && state.draft.items.length > 1
      && state.draftEditorOriginal
      && draftSignature(state.draft) !== state.draftEditorOriginal
    );
  }

  async function confirmDiscardIfDirty() {
    if (!isDirty()) return true;
    const durable = state?.kind === "task";
    return !!(await confirmDialog?.({
      title: durable ? "Discard Task changes?" : "Discard TaskDraft changes?",
      message: durable
        ? "Your unsaved Task edits will be lost."
        : "Your unsaved TaskDraft edits will be lost.",
      confirmLabel: "Discard",
      danger: true,
    }));
  }

  async function confirmWorkspaceLeave() {
    if (!draftChildEditorDirty()) return confirmDiscardIfDirty();
    const discardChild = await confirmDialog?.({
      title: "Discard Task changes?",
      message: "Your unsaved Task edits will be lost.",
      confirmLabel: "Discard",
      danger: true,
    });
    if (!discardChild) return false;
    if (state.draftEditorOriginal !== state.original) {
      const discardParent = await confirmDialog?.({
        title: "Discard TaskDraft changes?",
        message: "Your unsaved TaskDraft edits will be lost.",
        confirmLabel: "Discard",
        danger: true,
      });
      if (!discardParent) return false;
    }
    return true;
  }

  async function requestClose() {
    if (!state) return closeNow();
    if (!(await confirmWorkspaceLeave())) return;
    closeNow();
  }

  function renderShellChrome() {
    const shell = byId("taskWorkspaceShell");
    const expand = byId("taskWorkspaceExpand");
    const back = byId("taskWorkspaceHeaderBack");
    const close = byId("taskWorkspaceClose");
    const expanded = !!shell?.classList.contains("expanded");
    const expandLabel = expanded
      ? tr("task.collapse_workspace", "Collapse task workspace")
      : tr("task.expand_workspace", "Expand task workspace");
    if (expand) {
      expand.textContent = expanded ? "⤡" : "⤢";
      expand.title = expandLabel;
      expand.setAttribute("aria-label", expandLabel);
      expand.setAttribute("aria-pressed", String(expanded));
    }
    if (back) back.setAttribute("aria-label", tr("task.back", "Back"));
    if (close) close.setAttribute("aria-label", tr("task.close_workspace", "Close task workspace"));
  }

  function renderHeaderActions() {
    const group = byId("taskWorkspaceHeaderActions");
    if (!group || !state) return;
    const listRoute = state.route === "list";
    const newList = listRoute && state.kind === "draft" && !!state.createOnSave && state.creationKind === "list";
    const durableList = listRoute && state.kind === "task";
    group.hidden = !(newList || durableList);

    const openWorkflowButton = byId("taskWorkspaceHeaderOpenWorkflow");
    const add = byId("taskWorkspaceHeaderAddTask");
    const move = byId("taskWorkspaceHeaderMoveExisting");
    const yaml = byId("taskWorkspaceHeaderYaml");
    const cancel = byId("taskWorkspaceHeaderCancel");
    const create = byId("taskWorkspaceHeaderCreateList");
    for (const button of [openWorkflowButton, add, move, yaml, cancel, create]) if (button) button.hidden = true;

    if (newList) {
      if (cancel) {
        cancel.hidden = false;
        cancel.textContent = tr("task.cancel", "Cancel");
      }
      if (create) {
        create.hidden = false;
        create.textContent = tr("task.create_list", "Create Task List");
        create.disabled = !Array.isArray(state.draft?.items) || state.draft.items.length === 0;
      }
      return;
    }

    if (durableList) {
      const policy = taskEditPolicy(state.task);
      const items = Array.isArray(state.editDraft?.items) ? state.editDraft.items : (Array.isArray(state.task?.items) ? state.task.items : []);
      const selected = items[Number(state.selectedListIndex)];
      const selectedWorkflow = String(selected?.workflow || "").trim();
      if (openWorkflowButton) {
        openWorkflowButton.hidden = !selectedWorkflow;
        openWorkflowButton.disabled = !selectedWorkflow;
        openWorkflowButton.textContent = tr("task.open_workflow", "Open Workflow");
      }
      if (add) {
        add.hidden = false;
        add.textContent = tr("task.add_label", "+ Add task");
        add.disabled = !policy.can_add_item;
        add.title = add.disabled ? String(policy.reason || "") : "";
      }
      if (move) {
        move.hidden = false;
        const dirty = isDirty();
        move.disabled = !policy.can_add_item || dirty;
        move.title = dirty ? "Save Task List changes before moving an existing Task" : (move.disabled ? String(policy.reason || "") : "");
      }
      if (yaml) {
        yaml.hidden = false;
        yaml.textContent = tr("task.edit_yaml", "Edit YAML");
        yaml.disabled = !policy.can_edit_yaml || items.length === 0;
        const blockedItem = Array.isArray(policy.items)
          ? policy.items.find((row) => row?.editable === false || row?.restructure === false)
          : null;
        yaml.title = yaml.disabled
          ? String(policy.reason || blockedItem?.reason || "Task List YAML is not editable in the current lifecycle state")
          : "";
      }
    }
  }

  function setWorkspaceExpanded(expanded) {
    byId("taskWorkspaceShell")?.classList.toggle("expanded", !!expanded);
    renderShellChrome();
  }

  function showNow() {
    setWorkspaceExpanded(false);
    if (overlay) {
      overlay.hidden = false;
      overlay.classList.add("open");
    }
    document.body.classList.add("task-workspace-open");
  }

  function closeNow({ restore = true } = {}) {
    setWorkspaceExpanded(false);
    if (overlay) {
      overlay.classList.remove("open");
      overlay.hidden = true;
    }
    document.body.classList.remove("task-workspace-open");
    const focus = restore ? restoreFocus : null;
    workspaceOptionsToken += 1;
    taskProjectionToken += 1;
    state = null;
    restoreFocus = null;
    requestAnimationFrame(() => {
      if (focus && document.contains(focus) && typeof focus.focus === "function") focus.focus();
    });
  }

  async function openPromptsFromWorkspace() {
    if (typeof openPrompts !== "function") return;
    if (!(await confirmWorkspaceLeave())) return;
    closeNow({ restore: false });
    await openPrompts();
  }

  function promptsButton(id = "taskWorkspaceOpenPrompts") {
    if (typeof openPrompts !== "function") return null;
    const button = document.createElement("button");
    button.id = id;
    button.type = "button";
    button.textContent = tr("task.open_prompts", "Open Prompts");
    button.onclick = () => void openPromptsFromWorkspace();
    return button;
  }

  function touchEditor() {
    if (state?.kind === "task") state.saveRequestId = "";
  }

  function fieldErrorKey(name, index = state?.index || 0) {
    return name === "draftTitle" ? "draftTitle" : String(index) + ":" + name;
  }

  function clearFieldError(name, index = state?.index || 0) {
    if (!state?.fieldErrors) return;
    delete state.fieldErrors[fieldErrorKey(name, index)];
    state.error = "";
  }

  function appendFieldError(field, control, name, index = state?.index || 0) {
    const message = String(state?.fieldErrors?.[fieldErrorKey(name, index)] || "");
    if (!message) return;
    field.classList.add("has-error");
    control.setAttribute("aria-invalid", "true");
    const error = document.createElement("small");
    error.className = "task-workspace-field-error";
    error.id = "taskWorkspaceFieldError-" + fieldErrorKey(name, index).replace(/[^A-Za-z0-9_-]/g, "-");
    error.textContent = message;
    control.setAttribute("aria-describedby", error.id);
    field.appendChild(error);
  }

  function mapFieldError(message) {
    if (!state) return false;
    const text = String(message || "").trim();
    if (!text) return false;
    const itemMatch = text.match(/Task item\s+(\d+)/i);
    const index = itemMatch ? Math.max(0, Number(itemMatch[1]) - 1) : (state.index || 0);
    let field = "";
    if (/TaskDraft title/i.test(text)) field = "draftTitle";
    else if (/Task item\s+\d+\s+title/i.test(text)) field = "title";
    else if (/Task item\s+\d+\s+(prompt|goal_file)/i.test(text)) field = /goal_file/i.test(text) ? "goal_file" : "prompt";
    else if (/AI Validator Prompt/i.test(text)) field = /file/i.test(text) ? "ai_validator_prompt_file" : "ai_validator_prompt";
    else if (/File Validator/i.test(text)) field = "validator";
    else if (/Workflow/i.test(text)) field = "workflow";
    else if (/Project/i.test(text)) field = "project";
    else if (/workspace/i.test(text)) field = "workspace";
    if (!field) {
      state.fieldErrors = {};
      return false;
    }
    state.fieldErrors = { [fieldErrorKey(field, index)]: text };
    if (field !== "draftTitle") {
      state.index = index;
      if (state.route === "list") {
        if (isDraftState()) state.draftEditorOriginal = draftSignature(state.draft);
        state.editorMode = "edit";
        state.route = "editor";
      }
    }
    return true;
  }

  function syncSingleEditorTitle(draft, item) {
    if (!draft || !item || !Array.isArray(draft.items) || draft.items.length !== 1) return;
    const explicit = String(item.title || "").trim();
    const prompt = String(item.prompt || "").trim().split(/\r?\n/)[0].trim();
    draft.title = explicit || prompt.slice(0, 72) || "New Task";
  }

  function updateItem(index, key, value) {
    const draft = editorDraft();
    const item = draft?.items?.[index];
    if (item) {
      clearFieldError(key, index);
      item[key] = value;
      if (key === "title" || key === "prompt") syncSingleEditorTitle(draft, item);
      touchEditor();
    }
  }

  function managedUploadPath(value) {
    return /(^|[\\/])\.ai-task-runner[\\/]uploads[\\/]/.test(String(value || ""));
  }

  function uploadKind(field) {
    return field === "validator" ? "validator" : field === "ai_validator_prompt_file" ? "ai-validator" : "goal";
  }

  function ensureItemId(item) {
    if (!item.item_id) item.item_id = newItemId();
    return item.item_id;
  }

  function queueUploadCancel(path) {
    const value = String(path || "").trim();
    if (!managedUploadPath(value) || !state) return;
    const project = String(state.task?.project || state.project || "");
    pendingUploadActions = pendingUploadActions
      .then(() => api("/api/tasks/upload/cancel", {
        method: "POST",
        body: JSON.stringify({
          project,
          path: value,
          request_id: newRequestId("task-upload-cancel"),
        }),
      }))
      .catch(() => {});
  }

  async function fileBase64(file) {
    const bytes = new Uint8Array(await file.arrayBuffer());
    let binary = "";
    const chunk = 0x8000;
    for (let offset = 0; offset < bytes.length; offset += chunk) {
      binary += String.fromCharCode(...bytes.subarray(offset, offset + chunk));
    }
    return btoa(binary);
  }

  function chooseUpload(field, button) {
    const draft = editorDraft();
    const item = draft?.items?.[state?.index ?? -1];
    if (!item || !state) return;
    const picker = document.createElement("input");
    picker.type = "file";
    picker.hidden = true;
    document.body.appendChild(picker);
    picker.addEventListener("change", async () => {
      const file = picker.files?.[0];
      if (!file) { picker.remove(); return; }
      const original = button.textContent;
      button.disabled = true;
      button.textContent = "Uploading…";
      try {
        const previous = String(item[field] || "");
        const data = await api("/api/tasks/upload/stage", {
          method: "POST",
          body: JSON.stringify({
            project: String(item.project || state.task?.project || state.project || ""),
            task_id: String(state.task?.task_id || ""),
            item_id: ensureItemId(item),
            kind: uploadKind(field),
            filename: file.name,
            content_base64: await fileBase64(file),
            request_id: newRequestId("task-upload-stage"),
          }),
        });
        if (previous && previous !== data.path) queueUploadCancel(previous);
        const path = String(data.path || "");
        updateItem(state.index, field, path);
        const source = sourceState(item);
        if (field === "goal_file") source.promptFile = path;
        else if (field === "ai_validator_prompt_file") source.aiFile = path;
        render();
      } catch (error) {
        state.error = String(error?.message || "Upload failed");
        state.fieldErrors = { [fieldErrorKey(field)]: state.error };
        render();
        showError?.(error.message, "Upload file failed");
      } finally {
        picker.remove();
        if (document.contains(button)) {
          button.disabled = false;
          button.textContent = original;
        }
      }
    }, { once: true });
    picker.click();
  }

  function workflowMeta(value) {
    const selected = String(value || "");
    return (Array.isArray(state?.workflows) ? state.workflows : []).find((row) => {
      const aliases = [row?.path, row?.id, row?.reference, row?.name, row?.display_name].map((entry) => String(entry || ""));
      return aliases.includes(selected);
    }) || null;
  }

  function resolveWorkflowSelection(rows, preferred = "") {
    const selected = String(preferred || "").trim();
    const values = Array.isArray(rows) ? rows : [];
    if (selected) {
      const matched = values.find((row) =>
        [row?.path, row?.id, row?.reference, row?.name, row?.display_name]
          .some((entry) => String(entry || "") === selected)
      );
      if (matched) return String(matched.path || matched.id || selected);
    }
    const fallback = values.find((row) => !row?.hidden) || values[0];
    return String(fallback?.path || fallback?.id || selected);
  }

  function workflowOptions(saved) {
    const result = [], seen = new Set();
    for (const row of (Array.isArray(state?.workflows) ? state.workflows : [])) {
      const value = String(row?.path || row?.id || "");
      if (!value || seen.has(value)) continue;
      seen.add(value);
      result.push({ value, label: String(row?.name || value) });
    }
    if (saved && !seen.has(saved)) result.unshift({ value: saved, label: saved });
    return result;
  }

  function renderDraftTitleField() {
    const wrap = document.createElement("label");
    wrap.className = "task-workspace-field";
    const label = document.createElement("span");
    label.textContent = "Task title";
    const input = document.createElement("input");
    input.id = "taskWorkspaceDraftTitle";
    const draft = editorDraft();
    input.value = String(draft?.title || "");
    input.maxLength = 240;
    input.addEventListener("input", () => {
      clearFieldError("draftTitle");
      draft.title = input.value;
      touchEditor();
    });
    wrap.append(label, input);
    appendFieldError(wrap, input, "draftTitle");
    return wrap;
  }

  function taskEditPolicy(task = state?.task) {
    const policy = task?.edit_policy;
    if (policy && typeof policy === "object" && Array.isArray(policy.items)) return policy;
    return {
      editable: false,
      reason: "Task edit policy is unavailable; reload this Task",
      completed_item_count: 0,
      current_item_index: null,
      can_rename: false,
      can_add_item: false,
      can_edit_yaml: false,
      can_delete: false,
      restart_required: false,
      items: [],
    };
  }

  function taskItemEditPolicy(index, item = null) {
    const policy = taskEditPolicy();
    const itemId = String(item?.item_id || "");
    const matched = itemId
      ? policy.items.find((row) => String(row?.item_id || "") === itemId)
      : policy.items.find((row) => Number(row?.index) === Number(index));
    if (matched) return matched;
    return policy.editable
      ? { item_id: itemId, index, state: "future", editable: true, restructure: true, reason: "" }
      : { item_id: itemId, index, state: "locked", editable: false, restructure: false, reason: policy.reason };
  }

  function moveItemTo(index, targetIndex) {
    const draft = editorDraft();
    const items = draft?.items;
    if (!Array.isArray(items) || index < 0 || index >= items.length || targetIndex < 0 || targetIndex >= items.length) return;
    const insertAt = index < targetIndex ? targetIndex - 1 : targetIndex;
    if (insertAt === index) return;
    if (state?.kind === "task") {
      const currentPolicy = taskItemEditPolicy(index, items[index]);
      const targetPolicy = taskItemEditPolicy(targetIndex, items[targetIndex]);
      if (!currentPolicy.restructure || !targetPolicy.restructure) return;
    }
    const [item] = items.splice(index, 1);
    items.splice(insertAt, 0, item);
    state.selectedListIndex = insertAt;
    touchEditor();
    render();
  }

  function moveItem(index, delta) {
    const draft = editorDraft();
    const items = draft?.items;
    const next = index + delta;
    if (!Array.isArray(items) || next < 0 || next >= items.length) return;
    if (state?.kind === "task") {
      const currentPolicy = taskItemEditPolicy(index, items[index]);
      const targetPolicy = taskItemEditPolicy(next, items[next]);
      if (!currentPolicy.restructure || !targetPolicy.restructure) return;
    }
    const [item] = items.splice(index, 1);
    items.splice(next, 0, item);
    touchEditor();
    render();
  }

  function removeItem(index) {
    const draft = editorDraft();
    const items = draft?.items;
    if (!Array.isArray(items) || !items.length) return;
    if (state?.kind === "task" && items.length <= 1) return;
    if (state?.kind === "task" && !taskItemEditPolicy(index, items[index]).restructure) return;
    items.splice(index, 1);
    state.index = Math.min(state.index, items.length - 1);
    touchEditor();
    render();
  }

  function editItem(index) {
    if (state?.kind === "task") {
      beginTaskEdit(index, "list");
      return;
    }
    state.draftEditorOriginal = draftSignature(state.draft);
    state.editorMode = "edit";
    state.route = "editor";
    state.index = index;
    render();
  }

  function taskMutationBlockedReason(task = state?.task) {
    const policy = taskEditPolicy(task);
    return policy.editable ? "" : String(policy.reason || "Task editing is unavailable");
  }

  function selectTaskListRow(index) {
    if (!state || state.route !== "list") return;
    state.selectedListIndex = Number(index);
    document.querySelectorAll(".task-workspace-list-row").forEach((row, rowIndex) => {
      const selected = rowIndex === state.selectedListIndex;
      row.classList.toggle("selected", selected);
      row.setAttribute("aria-selected", String(selected));
    });
    renderHeaderActions();
  }

  function renderTaskRows(items, { editable = false, itemPolicies = null, onEdit = null, disabledEditReason = "" } = {}) {
    const values = Array.isArray(items) ? items : [];
    const list = document.createElement("div");
    list.className = "task-workspace-list";
    let dragIndex = null;
    const clearDragState = () => {
      dragIndex = null;
      list.querySelectorAll(".task-workspace-list-row").forEach((node) => node.classList.remove("dragging", "drag-over"));
    };

    values.forEach((item, index) => {
      const row = document.createElement("article");
      row.className = "task-workspace-list-row" + (editable ? "" : " task-workspace-info-row");
      row.classList.toggle("selected", Number(state?.selectedListIndex) === index);
      row.setAttribute("aria-selected", String(Number(state?.selectedListIndex) === index));
      row.addEventListener("click", (event) => {
        if (event.target.closest("button")) return;
        selectTaskListRow(index);
      });
      const rowPolicy = Array.isArray(itemPolicies)
        ? (String(item.item_id || "")
          ? itemPolicies.find((value) => String(value?.item_id || "") === String(item.item_id || ""))
          : itemPolicies[index])
        : null;
      const policy = rowPolicy || { editable: true, restructure: true, reason: "" };
      const stateLabel = ["completed", "current", "future"].includes(String(rowPolicy?.state || ""))
        ? String(rowPolicy.state).toUpperCase()
        : "";

      if (editable) {
        const grip = document.createElement("span");
        grip.className = "task-workspace-drag-grip";
        grip.setAttribute("aria-hidden", "true");
        grip.textContent = "⋮⋮";
        row.appendChild(grip);
        row.draggable = policy.restructure !== false;
        row.tabIndex = 0;
        if (!row.draggable && policy.reason) row.title = String(policy.reason);
      }

      const number = document.createElement("span");
      number.className = "task-workspace-list-number";
      number.textContent = String(index + 1);

      const copy = document.createElement("div");
      copy.className = "task-workspace-list-copy";
      const title = document.createElement("strong");
      title.textContent = String(item.title || "Task " + (index + 1));
      const meta = document.createElement("small");
      const projectName = String(item.project || "").replace(/[\\/]+$/, "").split(/[\\/]/).filter(Boolean).pop() || String(item.project || "");
      meta.textContent = [projectName, String(item.workflow || "Workflow")].filter(Boolean).join(" · ");
      copy.append(title, meta);
      row.append(number, copy);

      if (editable) {
        row.addEventListener("dblclick", (event) => {
          if (event.target.closest("button")) return;
          selectTaskListRow(index);
          if (policy.editable !== false) editItem(index);
        });
        row.addEventListener("keydown", (event) => {
          if (event.target.closest("button, input, select, textarea")) return;
          if (event.key === "Enter" && policy.editable !== false) {
            event.preventDefault();
            editItem(index);
            return;
          }
          if (event.altKey && event.key === "ArrowUp" && index > 0) {
            event.preventDefault();
            moveItem(index, -1);
            return;
          }
          if (event.altKey && event.key === "ArrowDown" && index < values.length - 1) {
            event.preventDefault();
            moveItem(index, 1);
          }
        });
        row.addEventListener("dragstart", (event) => {
          if (event.target.closest("button") || policy.restructure === false) {
            event.preventDefault();
            return;
          }
          dragIndex = index;
          row.classList.add("dragging");
          if (event.dataTransfer) event.dataTransfer.effectAllowed = "move";
        });
        row.addEventListener("dragover", (event) => {
          if (dragIndex == null || policy.restructure === false) return;
          if (state?.kind === "task") {
            const sourcePolicy = taskItemEditPolicy(dragIndex, values[dragIndex]);
            if (!sourcePolicy.restructure || !policy.restructure) return;
          }
          event.preventDefault();
          row.classList.add("drag-over");
          if (event.dataTransfer) event.dataTransfer.dropEffect = "move";
        });
        row.addEventListener("dragleave", () => row.classList.remove("drag-over"));
        row.addEventListener("drop", (event) => {
          if (dragIndex == null) return;
          event.preventDefault();
          const source = dragIndex;
          clearDragState();
          moveItemTo(source, index);
        });
        row.addEventListener("dragend", clearDragState);

        const actions = document.createElement("div");
        actions.className = "task-workspace-list-actions";
        const workspaceChip = document.createElement("span");
        workspaceChip.className = "task-workspace-list-chip" + (String(item.workspace || "").toLowerCase() === "worktree" ? " worktree" : "");
        workspaceChip.textContent = String(item.workspace || "auto").toUpperCase();
        actions.appendChild(workspaceChip);
        if (stateLabel) {
          const stateChip = document.createElement("span");
          stateChip.className = "task-workspace-list-state " + String(rowPolicy?.state || "");
          stateChip.textContent = stateLabel;
          actions.appendChild(stateChip);
        }

        const edit = document.createElement("button");
        edit.type = "button";
        edit.className = "task-workspace-row-edit";
        edit.textContent = tr("task.edit_action", "Edit");
        edit.disabled = policy.editable === false;
        edit.title = edit.disabled ? String(policy.reason || disabledEditReason || "") : "";
        edit.onclick = () => editItem(index);

        const remove = document.createElement("button");
        remove.type = "button";
        remove.className = "danger-item";
        remove.textContent = "×";
        remove.setAttribute("aria-label", tr("task.remove", "Remove"));
        remove.disabled = (state?.kind === "task" && values.length <= 1) || policy.restructure === false;
        remove.title = remove.disabled && policy.reason ? String(policy.reason) : tr("task.remove", "Remove");
        remove.onclick = () => removeItem(index);

        actions.append(edit, remove);
        row.appendChild(actions);
      } else if (typeof onEdit === "function" || disabledEditReason) {
        row.addEventListener("dblclick", (event) => {
          if (event.target.closest("button")) return;
          selectTaskListRow(index);
          if (typeof onEdit === "function" && !disabledEditReason) onEdit(index);
        });
        const actions = document.createElement("div");
        actions.className = "task-workspace-list-actions";
        const workspaceChip = document.createElement("span");
        workspaceChip.className = "task-workspace-list-chip" + (String(item.workspace || "").toLowerCase() === "worktree" ? " worktree" : "");
        workspaceChip.textContent = String(item.workspace || "auto").toUpperCase();
        actions.appendChild(workspaceChip);
        if (stateLabel) {
          const stateChip = document.createElement("span");
          stateChip.className = "task-workspace-list-state " + String(rowPolicy?.state || "");
          stateChip.textContent = stateLabel;
          actions.appendChild(stateChip);
        }
        const edit = document.createElement("button");
        edit.type = "button";
        edit.className = "task-workspace-durable-edit";
        edit.textContent = tr("task.edit_action", "Edit");
        if (disabledEditReason) {
          edit.disabled = true;
          edit.title = disabledEditReason;
        } else {
          edit.onclick = () => onEdit(index);
        }
        actions.appendChild(edit);
        row.appendChild(actions);
      }
      list.appendChild(row);
    });
    return list;
  }
  function listInfoRow(grid, labelText, value) {
    const label = document.createElement("span");
    label.textContent = labelText;
    grid.appendChild(label);
    if (value instanceof Node) grid.appendChild(value);
    else {
      const strong = document.createElement("strong");
      strong.textContent = String(value ?? "");
      grid.appendChild(strong);
    }
  }

  function listTitleControl() {
    const draft = editorDraft();
    const wrap = document.createElement("label");
    wrap.className = "task-workspace-list-draft-control";
    const input = document.createElement("input");
    input.id = "taskWorkspaceDraftTitle";
    input.autocomplete = "off";
    input.value = String(draft?.title || "");
    input.maxLength = 240;
    input.addEventListener("input", () => {
      clearFieldError("draftTitle");
      draft.title = input.value;
      touchEditor();
      const shellTitle = byId("taskWorkspaceTitle");
      if (shellTitle) shellTitle.textContent = input.value.trim() || tr("task.new_list", "New Task List");
    });
    wrap.appendChild(input);
    appendFieldError(wrap, input, "draftTitle");
    return wrap;
  }

  function listDraftProjectControl() {
    const select = document.createElement("select");
    select.id = "taskWorkspaceListProject";
    const current = String(state.draft?.project || state.project || "");
    const rows = Array.isArray(state.projectOptions) ? state.projectOptions : [];
    const seen = new Set();
    const add = (value, label) => {
      const path = String(value || "").trim();
      if (!path || seen.has(path)) return;
      seen.add(path);
      const option = document.createElement("option");
      option.value = path;
      option.textContent = String(label || path);
      select.appendChild(option);
    };
    add(current, current);
    for (const row of rows) add(row?.path, [row?.name, row?.path].filter(Boolean).join(" · "));
    select.value = current;
    select.addEventListener("change", () => {
      state.project = select.value;
      state.draft.project = select.value;
      touchEditor();
    });
    return select;
  }

  function moveExistingEligible(task) {
    return Boolean(
      task
      && String(task.task_id || "") !== String(state?.task?.task_id || "")
      && String(task.status || "") === "new"
      && Array.isArray(task.items)
      && task.items.length === 1
      && task.edit_policy?.can_delete === true
    );
  }

  async function loadMoveExistingCandidates() {
    if (state?.kind !== "task" || !state.task) return;
    const owner = state;
    owner.moveExistingLoading = true;
    owner.moveExistingError = "";
    render();
    try {
      const data = await api("/api/tasks?project=" + encodeURIComponent(String(owner.task.project || "")), { timeoutMs: 15000 });
      if (state !== owner) return;
      owner.moveExistingCandidates = (Array.isArray(data?.tasks) ? data.tasks : []).filter(moveExistingEligible);
      if (owner.moveExistingSelected && !owner.moveExistingCandidates.some((row) => String(row.task_id) === owner.moveExistingSelected)) {
        owner.moveExistingSelected = "";
        owner.moveExistingRequestId = "";
      }
    } catch (error) {
      if (state !== owner) return;
      owner.moveExistingCandidates = [];
      owner.moveExistingError = String(error?.message || "Eligible Tasks failed to load");
    } finally {
      if (state === owner) {
        owner.moveExistingLoading = false;
        render();
      }
    }
  }

  function toggleMoveExisting() {
    if (state?.kind !== "task" || !state.task) return;
    if (isDirty()) return;
    state.moveExistingOpen = !state.moveExistingOpen;
    state.moveExistingSelected = "";
    state.moveExistingRequestId = "";
    state.moveExistingError = "";
    if (state.moveExistingOpen) {
      void loadMoveExistingCandidates();
    } else {
      render();
    }
  }

  async function moveExistingSelected() {
    if (state?.kind !== "task" || !state.task || isDirty()) return;
    const sourceTaskId = String(state.moveExistingSelected || "");
    if (!sourceTaskId || state.moveExistingBusy) return;
    if (!state.moveExistingRequestId) state.moveExistingRequestId = newRequestId("task-move-existing");
    const owner = state;
    owner.moveExistingBusy = true;
    owner.moveExistingError = "";
    render();
    try {
      const updated = await api("/api/tasks/move-existing", {
        method: "POST",
        body: JSON.stringify({
          project: owner.task.project,
          target_task_id: owner.task.task_id,
          source_task_id: sourceTaskId,
          request_id: owner.moveExistingRequestId,
          expected_updated_at: owner.task.updated_at,
        }),
      });
      if (state !== owner) return;
      owner.task = cloneDraft(updated);
      owner.editDraft = taskDraftFromRecord(owner.task);
      owner.editOriginal = draftSignature(owner.editDraft);
      owner.saveRequestId = "";
      owner.moveExistingOpen = false;
      owner.moveExistingSelected = "";
      owner.moveExistingRequestId = "";
      owner.moveExistingCandidates = [];
      owner.moveExistingError = "";
      render();
      await onTaskChanged?.();
      showToast?.("New Task moved here");
    } catch (error) {
      if (state !== owner) return;
      owner.moveExistingError = String(error?.message || "Move existing Task failed");
      render();
      showError?.(owner.moveExistingError, "Move existing Task failed");
    } finally {
      if (state === owner) {
        owner.moveExistingBusy = false;
        render();
      }
    }
  }

  function createMoveExistingChooser() {
    const chooser = document.createElement("div");
    chooser.className = "task-workspace-move-existing";
    const note = document.createElement("div");
    note.className = "task-workspace-move-note";
    const strong = document.createElement("strong");
    strong.textContent = "Move existing";
    const span = document.createElement("span");
    span.textContent = "Only standalone New Tasks can be moved. Their Board identity is retired.";
    note.append(strong, span);
    chooser.appendChild(note);

    const list = document.createElement("div");
    list.className = "task-workspace-move-options";
    if (state.moveExistingLoading) {
      const loading = document.createElement("div");
      loading.className = "task-workspace-move-empty";
      loading.textContent = "Loading eligible Tasks…";
      list.appendChild(loading);
    } else if (state.moveExistingError) {
      const error = document.createElement("div");
      error.className = "task-workspace-move-empty danger";
      error.textContent = state.moveExistingError;
      list.appendChild(error);
    } else {
      const candidates = Array.isArray(state.moveExistingCandidates) ? state.moveExistingCandidates : [];
      if (!candidates.length) {
        const empty = document.createElement("div");
        empty.className = "task-workspace-move-empty";
        empty.textContent = "No eligible New tasks. Only standalone New Tasks can be moved.";
        list.appendChild(empty);
      }
      for (const task of candidates) {
        const option = document.createElement("button");
        option.type = "button";
        option.className = "task-workspace-move-option";
        option.classList.toggle("selected", String(task.task_id || "") === String(state.moveExistingSelected || ""));
        option.dataset.moveExistingTaskId = String(task.task_id || "");
        const copy = document.createElement("div");
        const title = document.createElement("strong");
        title.textContent = String(task.title || task.task_id || "Task");
        const meta = document.createElement("small");
        meta.textContent = [String(task.task_id || ""), String(task.items?.[0]?.workflow || "")].filter(Boolean).join(" · ");
        copy.append(title, meta);
        const status = document.createElement("span");
        status.textContent = "New";
        option.append(copy, status);
        option.addEventListener("click", () => {
          state.moveExistingSelected = String(task.task_id || "");
          state.moveExistingRequestId = "";
          render();
        });
        list.appendChild(option);
      }
    }
    chooser.appendChild(list);

    const actions = document.createElement("div");
    actions.className = "task-workspace-move-actions";
    const cancel = document.createElement("button");
    cancel.type = "button";
    cancel.textContent = "Cancel";
    cancel.disabled = !!state.moveExistingBusy;
    cancel.onclick = () => {
      state.moveExistingOpen = false;
      state.moveExistingSelected = "";
      state.moveExistingRequestId = "";
      state.moveExistingError = "";
      render();
    };
    const confirm = document.createElement("button");
    confirm.type = "button";
    confirm.className = "primary";
    confirm.textContent = state.moveExistingBusy ? "Moving…" : "Move here";
    confirm.disabled = !state.moveExistingSelected || !!state.moveExistingBusy || !!state.moveExistingLoading;
    confirm.onclick = () => void moveExistingSelected();
    actions.append(cancel, confirm);
    chooser.appendChild(actions);
    return chooser;
  }

  function createTaskListTools() {
    const wrap = document.createElement("div");
    wrap.className = "task-workspace-list-tools-wrap";
    if (state?.kind === "task" && state.moveExistingOpen) {
      wrap.appendChild(createMoveExistingChooser());
    } else {
      wrap.hidden = true;
    }
    return wrap;
  }

  function createTaskListAddButton({ enabled = true, first = false, onClick, reason = "" } = {}) {
    const add = document.createElement("button");
    add.id = "taskWorkspaceAddTask";
    add.type = "button";
    add.className = first ? "task-workspace-empty-list-cta" : "task-workspace-add-task-footer";
    if (first) {
      const strong = document.createElement("strong");
      strong.textContent = tr("task.empty_list", "No tasks yet");
      const span = document.createElement("span");
      span.textContent = tr("task.add_first", "+ Add first task");
      add.append(strong, span);
    } else {
      const plus = document.createElement("span");
      plus.className = "task-workspace-add-task-plus";
      plus.textContent = "＋";
      const strong = document.createElement("strong");
      strong.textContent = tr("task.add_label", "Add task");
      add.append(plus, strong);
    }
    add.disabled = !enabled;
    add.title = !enabled ? reason : "";
    if (enabled) add.onclick = onClick;
    return add;
  }

  function buildTaskListPage({ items, editable, canAdd, canYaml, reason = "", durableTask = null } = {}) {
    if (!Number.isInteger(state?.selectedListIndex) || state.selectedListIndex < 0 || state.selectedListIndex >= (items || []).length) {
      state.selectedListIndex = null;
    }
    const page = document.createElement("div");
    page.className = "task-workspace-list-page";

    const main = document.createElement("main");
    main.className = "task-workspace-list-main";
    const intro = document.createElement("div");
    intro.className = "task-workspace-list-intro";
    const introCopy = document.createElement("div");
    const introTitle = document.createElement("strong");
    introTitle.textContent = tr("task.order", "Task order");
    const introText = document.createElement("span");
    introText.textContent = durableTask && String(durableTask.status || "") === "paused"
      ? "Paused · completed items are locked; current changes require restart."
      : tr("task.order_desc", "Tasks run top-to-bottom inside this Task List.");
    introCopy.append(introTitle, introText);
    const statePill = document.createElement("span");
    statePill.className = "task-workspace-list-state-pill";
    statePill.textContent = editable ? "Editable" : "Read-only";
    intro.append(introCopy, statePill);
    main.appendChild(intro);

    const listHost = document.createElement("div");
    listHost.className = "task-workspace-plan-list";
    if (!items.length) {
      listHost.appendChild(createTaskListAddButton({
        first: true,
        enabled: canAdd,
        onClick: state.kind === "task" ? addTaskListItem : addDraftListItem,
        reason,
      }));
    } else {
      const policy = durableTask ? taskEditPolicy(durableTask) : null;
      listHost.appendChild(renderTaskRows(items, {
        editable,
        itemPolicies: policy?.items || null,
        disabledEditReason: editable ? "" : reason,
      }));
      listHost.appendChild(createTaskListAddButton({
        enabled: canAdd,
        onClick: state.kind === "task" ? addTaskListItem : addDraftListItem,
        reason,
      }));
    }
    main.appendChild(listHost);

    const aside = document.createElement("aside");
    aside.className = "task-workspace-list-side";
    const info = document.createElement("section");
    info.className = "task-workspace-list-side-card";
    const infoTitle = document.createElement("h3");
    infoTitle.textContent = "List info";
    const kv = document.createElement("div");
    kv.className = "task-workspace-list-kv";
    if (state.kind === "draft") {
      listInfoRow(kv, "Title", listTitleControl());
      listInfoRow(kv, "Project", listDraftProjectControl());
      listInfoRow(kv, "Tasks", String(items.length));
      listInfoRow(kv, "State", "Not created");
    } else {
      const task = durableTask || {};
      const policy = taskEditPolicy(task);
      if (editable && policy.can_rename) listInfoRow(kv, "List", listTitleControl());
      else listInfoRow(kv, "List", String(task.title || ""));
      listInfoRow(kv, "Status", String(task.status || "new").toUpperCase());
      listInfoRow(kv, "Runtime", String(task.run?.phase || (task.status === "closed" ? "Completed" : "Idle")).replaceAll("_", " "));
      listInfoRow(kv, "Progress", String(task.completed_item_count || 0) + " / " + String(items.length));
    }
    info.append(infoTitle, kv, createTaskListTools({ editable, canYaml, reason }));

    const help = document.createElement("section");
    help.className = "task-workspace-list-side-card task-workspace-list-help";
    const helpTitle = document.createElement("h3");
    helpTitle.textContent = "Quick use";
    const firstHelp = document.createElement("p");
    firstHelp.innerHTML = "<strong>Click</strong> selects a task · <strong>Double-click</strong> edits it.";
    const secondHelp = document.createElement("p");
    secondHelp.innerHTML = "Drag the grip to reorder. Edit / Remove stay on the selected row.";
    help.append(helpTitle, firstHelp, secondHelp);
    aside.append(info, help);

    page.append(main, aside);
    return page;
  }

  function renderList() {
    const body = byId("taskWorkspaceBody");
    body.innerHTML = "";
    const items = Array.isArray(state.draft?.items) ? state.draft.items : [];
    body.appendChild(buildTaskListPage({
      items,
      editable: true,
      canAdd: true,
      canYaml: items.length > 0,
    }));
  }

  function currentProjectPath() {
    return String(state?.task?.project || state?.project || "").trim();
  }

  function sourceState(item) {
    if (!state) return {};
    if (!state.sourceModes) state.sourceModes = {};
    const key = ensureItemId(item);
    if (!state.sourceModes[key]) {
      const promptAsset = (state.prompts || []).some((row) => String(row?.path || "") === String(item.goal_file || ""));
      const aiAsset = (state.prompts || []).some((row) => String(row?.path || "") === String(item.ai_validator_prompt_file || ""));
      state.sourceModes[key] = {
        promptMode: item.goal_file ? (promptAsset ? "asset" : "file") : "write",
        promptText: String(item.prompt || ""),
        promptFile: String(item.goal_file || ""),
        promptAsset: promptAsset ? String(item.goal_file || "") : "",
        aiMode: item.ai_validator_prompt
          ? "write"
          : item.ai_validator_prompt_file
            ? (aiAsset ? "asset" : "file")
            : "default",
        aiText: String(item.ai_validator_prompt || ""),
        aiFile: String(item.ai_validator_prompt_file || ""),
        aiAsset: aiAsset ? String(item.ai_validator_prompt_file || "") : "",
      };
    }
    return state.sourceModes[key];
  }

  async function loadPromptAssets() {
    if (!state || (state.prompts || []).length) return;
    const project = currentProjectPath();
    if (!project) return;
    try {
      const data = await api("/api/studio/files?x=1&project=" + encodeURIComponent(project), { timeoutMs: 15000 });
      if (!state) return;
      state.prompts = Array.isArray(data?.prompts) ? data.prompts.slice() : [];
      state.sourceModes = {};
      render();
    } catch (error) {
      showError?.(error.message, "Prompt assets failed to load");
    }
  }

  function applySourceMode(item, group, mode) {
    const source = sourceState(item);
    if (group === "prompt") {
      const previous = source.promptMode;
      if (previous === "write") source.promptText = String(item.prompt || "");
      else if (previous === "file") source.promptFile = String(item.goal_file || "");
      else if (previous === "asset") source.promptAsset = String(item.goal_file || "");
      if (previous === "file" && mode !== "file" && managedUploadPath(item.goal_file)) {
        queueUploadCancel(item.goal_file);
      }
      source.promptMode = mode;
      if (mode === "write") {
        item.prompt = source.promptText;
        item.goal_file = "";
      } else {
        item.prompt = "";
        item.goal_file = mode === "asset" ? source.promptAsset : source.promptFile;
      }
      clearFieldError("prompt");
      clearFieldError("goal_file");
    } else {
      const previous = source.aiMode;
      if (previous === "write") source.aiText = String(item.ai_validator_prompt || "");
      else if (previous === "file") source.aiFile = String(item.ai_validator_prompt_file || "");
      else if (previous === "asset") source.aiAsset = String(item.ai_validator_prompt_file || "");
      if (previous === "file" && mode !== "file" && managedUploadPath(item.ai_validator_prompt_file)) {
        queueUploadCancel(item.ai_validator_prompt_file);
      }
      source.aiMode = mode;
      if (mode === "default") {
        item.ai_validator_prompt = "";
        item.ai_validator_prompt_file = "";
      } else if (mode === "write") {
        item.ai_validator_prompt = source.aiText;
        item.ai_validator_prompt_file = "";
      } else {
        item.ai_validator_prompt = "";
        item.ai_validator_prompt_file = mode === "asset" ? source.aiAsset : source.aiFile;
      }
      clearFieldError("ai_validator_prompt");
      clearFieldError("ai_validator_prompt_file");
    }
    touchEditor();
    render();
  }

  function sourceCard(labelText, detailText, group, modes, active) {
    const card = document.createElement("section");
    card.className = "task-workspace-source-card";
    card.dataset.taskSourceCard = group;
    const head = document.createElement("div");
    head.className = "task-workspace-source-head";
    const copy = document.createElement("div");
    const strong = document.createElement("strong");
    strong.textContent = labelText;
    const small = document.createElement("small");
    small.textContent = detailText;
    copy.append(strong, small);
    const tabs = document.createElement("div");
    tabs.className = "task-workspace-source-tabs";
    tabs.dataset.taskSourceGroup = group;
    for (const [value, label] of modes) {
      const button = document.createElement("button");
      button.type = "button";
      button.dataset.taskSourceMode = value;
      button.classList.toggle("active", value === active);
      button.setAttribute("aria-pressed", String(value === active));
      button.textContent = label;
      tabs.appendChild(button);
    }
    head.append(copy, tabs);
    const body = document.createElement("div");
    body.className = "task-workspace-source-body";
    card.append(head, body);
    return { card, body, tabs };
  }

  function sourceModePanel(mode) {
    const panel = document.createElement("div");
    panel.className = "task-workspace-source-mode-panel";
    panel.dataset.sourceMode = mode;
    return panel;
  }

  function sourceModePathPanel(mode, ...controls) {
    const panel = sourceModePanel(mode);
    const row = document.createElement("div");
    row.className = "task-workspace-path-row";
    row.append(...controls.filter(Boolean));
    panel.appendChild(row);
    return panel;
  }

  function sourceMiniAction(button) {
    if (button) button.classList.add("task-workspace-mini-button");
    return button;
  }

  function promptAssetSelect(id, value, onChange) {
    const select = document.createElement("select");
    select.id = id;
    const rows = Array.isArray(state?.prompts) ? state.prompts : [];
    const current = String(value || "");
    const empty = document.createElement("option");
    empty.value = "";
    empty.textContent = rows.length ? tr("task.select_prompt_asset", "Select Prompt asset") : tr("task.no_prompt_assets", "No Prompt assets loaded");
    select.appendChild(empty);
    for (const row of rows) {
      const option = document.createElement("option");
      option.value = String(row.path || "");
      option.textContent = String(row.display_name || row.name || row.path || "");
      select.appendChild(option);
    }
    if (current && ![...select.options].some((option) => option.value === current)) {
      const option = document.createElement("option");
      option.value = current;
      option.textContent = current;
      select.appendChild(option);
    }
    select.value = current;
    select.addEventListener("change", () => onChange(select.value));
    return select;
  }

  function renderEditor() {
    const body = byId("taskWorkspaceBody");
    body.innerHTML = "";
    const draft = editorDraft();
    if (!draft || !Array.isArray(draft.items) || !draft.items.length) return;
    const item = draft.items[state.index];

    const grid = document.createElement("div");
    grid.className = "task-workspace-grid task-workspace-basics";

    const projectField = document.createElement("label");
    projectField.className = "task-workspace-field task-workspace-project-field";
    const projectLabel = document.createElement("span");
    projectLabel.textContent = "Project";
    const projectCombo = document.createElement("div");
    projectCombo.className = "task-workspace-project-combobox";
    const project = document.createElement("input");
    project.id = "taskWorkspaceProject";
    project.autocomplete = "off";
    project.placeholder = "Select a project or type a path";
    project.value = String(item.project || state.project || "");
    const projectEditable = state.kind === "draft";
    project.readOnly = !projectEditable;
    project.title = projectEditable
      ? "Select a Project or type a local path"
      : "Existing Task Project is fixed by the durable Task contract";

    const projectToggle = document.createElement("button");
    projectToggle.type = "button";
    projectToggle.className = "task-workspace-project-toggle";
    projectToggle.setAttribute("aria-label", "Show all projects");
    projectToggle.setAttribute("aria-expanded", "false");
    projectToggle.disabled = !projectEditable;
    const chevron = document.createElement("span");
    chevron.className = "task-workspace-project-chevron";
    chevron.setAttribute("aria-hidden", "true");
    projectToggle.appendChild(chevron);

    const projectDropdown = document.createElement("div");
    projectDropdown.className = "task-workspace-project-dropdown";
    projectDropdown.hidden = true;

    const applyProject = (value) => {
      const next = String(value || "").trim();
      project.value = next;
      updateItem(state.index, "project", next);
      if (state.kind === "draft" && state.creationKind === "task") {
        state.project = next;
        state.draft.project = next;
      }
      state.workspaceOptions = null;
      state.workspaceOptionsError = "";
      void loadWorkspaceOptions();
    };
    const renderProjectDropdown = (filter = "") => {
      const query = String(filter || "").trim().toLowerCase();
      const rows = Array.isArray(state.projectOptions) ? state.projectOptions : [];
      projectDropdown.innerHTML = "";
      const filtered = rows.filter((row) => {
        const name = String(row?.name || "");
        const path = String(row?.path || "");
        return !query || name.toLowerCase().includes(query) || path.toLowerCase().includes(query);
      });
      if (!filtered.length) {
        const empty = document.createElement("div");
        empty.className = "task-workspace-project-dropdown-empty";
        empty.textContent = state.projectOptionsLoading ? "Loading Projects…" : "No matching Project. Type a local path.";
        projectDropdown.appendChild(empty);
        return;
      }
      for (const row of filtered) {
        const option = document.createElement("button");
        option.type = "button";
        option.className = "task-workspace-project-dropdown-option";
        const strong = document.createElement("strong");
        strong.textContent = String(row.name || row.path || "Project");
        const small = document.createElement("small");
        small.textContent = String(row.path || "");
        option.append(strong, small);
        option.addEventListener("mousedown", (event) => event.preventDefault());
        option.addEventListener("click", () => {
          applyProject(String(row.path || ""));
          projectDropdown.hidden = true;
          projectToggle.setAttribute("aria-expanded", "false");
          project.focus();
        });
        projectDropdown.appendChild(option);
      }
    };
    const setProjectDropdownOpen = (open, showAll = false) => {
      if (!projectEditable) return;
      if (open) renderProjectDropdown(showAll ? "" : project.value);
      projectDropdown.hidden = !open;
      projectToggle.setAttribute("aria-expanded", String(open));
    };

    projectToggle.addEventListener("click", (event) => {
      event.preventDefault();
      setProjectDropdownOpen(projectDropdown.hidden, true);
    });
    if (projectEditable) {
      project.addEventListener("focus", () => {
        if (project.dataset.suppressOpenOnFocus === "true") {
          delete project.dataset.suppressOpenOnFocus;
          return;
        }
        setProjectDropdownOpen(true, true);
      });
      project.addEventListener("input", () => {
        updateItem(state.index, "project", project.value);
        renderProjectDropdown(project.value);
        setProjectDropdownOpen(true);
      });
      project.addEventListener("change", () => applyProject(project.value));
      project.addEventListener("blur", () => setTimeout(() => {
        if (!projectDropdown.matches(":hover")) setProjectDropdownOpen(false);
      }, 0));
      project.addEventListener("keydown", (event) => {
        if (event.key !== "Escape" || projectDropdown.hidden) return;
        event.preventDefault();
        event.stopPropagation();
        setProjectDropdownOpen(false);
      });
    }

    projectCombo.append(project, projectToggle, projectDropdown);
    const projectHelp = document.createElement("small");
    projectHelp.className = "task-workspace-field-help";
    projectHelp.textContent = projectEditable
      ? "Current Project is used by default · type a local path to override."
      : "Project is fixed for an existing durable Task.";
    projectField.append(projectLabel, projectCombo, projectHelp);
    appendFieldError(projectField, project, "project");

    const workflowField = document.createElement("label");
    workflowField.className = "task-workspace-field task-workspace-workflow-field";
    const workflowLabel = document.createElement("span");
    workflowLabel.textContent = "Workflow";
    const workflow = document.createElement("select");
    workflow.id = "taskWorkspaceWorkflow";
    const options = workflowOptions(String(item.workflow || ""));
    for (const row of (options.length ? options : [{ value: String(item.workflow || ""), label: String(item.workflow || "Project default") }])) {
      const option = document.createElement("option");
      option.value = row.value;
      option.textContent = row.label;
      workflow.appendChild(option);
    }
    workflow.value = String(item.workflow || "");
    workflow.addEventListener("change", () => {
      updateItem(state.index, "workflow", workflow.value);
      const capability = workflowMeta(workflow.value);
      if (!capability?.requires_python_validator) updateItem(state.index, "validator", "");
      if (!capability?.has_ai_validator) {
        updateItem(state.index, "ai_validator_prompt", "");
        updateItem(state.index, "ai_validator_prompt_file", "");
        const source = sourceState(editorDraft()?.items?.[state.index] || item);
        source.aiMode = "default";
      }
      render();
    });
    workflowField.append(workflowLabel, workflow);
    appendFieldError(workflowField, workflow, "workflow");

    const titleField = document.createElement("label");
    titleField.className = "task-workspace-field task-workspace-title-field";
    const titleLabel = document.createElement("span");
    titleLabel.className = "task-workspace-field-label";
    titleLabel.append(document.createTextNode("Title "));
    const optional = document.createElement("em");
    optional.className = "task-workspace-field-optional";
    optional.textContent = "optional";
    titleLabel.appendChild(optional);
    const title = document.createElement("input");
    title.id = "taskWorkspaceItemTitle";
    title.placeholder = "Auto from prompt";
    title.value = String(item.title || "");
    title.maxLength = 240;
    title.addEventListener("input", () => updateItem(state.index, "title", title.value));
    titleField.append(titleLabel, title);
    appendFieldError(titleField, title, "title");

    grid.append(projectField, workflowField, titleField);
    body.appendChild(grid);

    const capability = workflowMeta(item.workflow);
    const workflowCaps = document.createElement("div");
    workflowCaps.id = "taskWorkspaceWorkflowCaps";
    workflowCaps.className = "task-workspace-workflow-caps";
    const addCap = (text, neutral = false) => {
      const chip = document.createElement("span");
      chip.className = "task-workspace-cap-chip" + (neutral ? " neutral" : "");
      chip.textContent = text;
      workflowCaps.appendChild(chip);
    };
    if (capability?.requires_python_validator) addCap("File Validator");
    if (capability?.has_ai_validator) addCap("AI Validator");
    if (!workflowCaps.children.length) addCap("No extra validation input", true);
    body.appendChild(workflowCaps);

    const workspaceSection = document.createElement("section");
    workspaceSection.className = "task-workspace-workspace-selector task-workspace-editor-secondary";
    const workspaceHead = document.createElement("div");
    workspaceHead.className = "task-workspace-workspace-head";
    const workspaceCopy = document.createElement("div");
    const workspaceTitle = document.createElement("strong");
    workspaceTitle.textContent = "Workspace";
    const workspaceHelp = document.createElement("small");
    workspaceHelp.textContent = "Auto / Main / isolated Worktree";
    workspaceCopy.append(workspaceTitle, workspaceHelp);
    const workspaceRecommended = document.createElement("span");
    workspaceRecommended.className = "task-workspace-workspace-recommended";
    workspaceRecommended.textContent = "Auto recommended";
    workspaceHead.append(workspaceCopy, workspaceRecommended);

    const workspace = document.createElement("select");
    workspace.id = "taskWorkspaceWorkspace";
    workspace.className = "task-workspace-workspace-native";
    workspace.setAttribute("aria-label", "Workspace");
    const loadingWorkspace = !!state.workspaceOptionsLoading;
    const workspaceProjectionMissing = !state.workspaceOptions && !loadingWorkspace;
    const workspaceRows = [
      ["auto", "Auto", "Use the global Auto workspace policy."],
      ["main", "Main", "Run against the Project target workspace when available."],
      ["worktree", "Isolated worktree", "Create an isolated branch/path for this task."],
    ];
    for (const [value, label] of workspaceRows) {
      const option = document.createElement("option");
      const availability = workspaceOption(value);
      option.value = value;
      option.textContent = label;
      option.dataset.effectiveMode = String(availability?.effective_mode || "");
      option.dataset.reason = String(availability?.reason || "");
      const failClosed = value !== "worktree" && (loadingWorkspace || workspaceProjectionMissing);
      option.disabled = failClosed || availability?.enabled === false;
      option.title = String(
        availability?.error
        || (loadingWorkspace && value !== "worktree" ? "Checking current Main availability" : "")
        || (workspaceProjectionMissing && value !== "worktree" ? state.workspaceOptionsError || "Workspace availability unavailable" : "")
      );
      workspace.appendChild(option);
    }
    workspace.value = String(item.workspace || "auto");

    const workspaceOptions = document.createElement("div");
    workspaceOptions.className = "task-workspace-workspace-options";
    for (const [value, label, description] of workspaceRows) {
      const availability = workspaceOption(value);
      const option = workspace.querySelector(`option[value="${value}"]`);
      const card = document.createElement("label");
      card.className = "task-workspace-workspace-option" + (value === "worktree" ? " worktree-option" : "");
      card.dataset.workspaceOption = value;
      card.classList.toggle("selected", workspace.value === value);
      card.classList.toggle("disabled", !!option?.disabled);

      const radio = document.createElement("input");
      radio.type = "radio";
      radio.name = "taskWorkspaceMode";
      radio.value = value;
      radio.checked = workspace.value === value;
      radio.disabled = !!option?.disabled;

      const strong = document.createElement("strong");
      strong.textContent = label;
      const small = document.createElement("small");
      small.textContent = description;
      const status = document.createElement("span");
      status.className = "task-workspace-workspace-status";
      if (loadingWorkspace && value !== "worktree") status.textContent = "Checking…";
      else if (option?.disabled) status.textContent = String(option?.title || "Unavailable");
      else if (availability?.effective_mode) {
        status.textContent = value === "auto"
          ? "Resolves to " + (availability.effective_mode === "main" ? "Main" : "Isolated worktree")
          : "Available";
      } else status.textContent = value === "worktree" ? "Always available" : "Available";

      radio.addEventListener("change", () => {
        if (!radio.checked || radio.disabled) return;
        workspace.value = value;
        updateItem(state.index, "workspace", value);
        render();
      });
      card.append(radio, strong, small, status);
      workspaceOptions.appendChild(card);
    }

    workspace.addEventListener("change", () => {
      updateItem(state.index, "workspace", workspace.value);
      render();
    });

    const selectedAvailability = workspaceOption(workspace.value);
    const availabilityNote = document.createElement("div");
    availabilityNote.id = "taskWorkspaceWorkspaceAvailability";
    availabilityNote.className = "task-workspace-workspace-preview";
    availabilityNote.classList.toggle("worktree-active", workspace.value === "worktree");
    const previewTitle = document.createElement("strong");
    previewTitle.textContent = workspace.value === "worktree" ? "WORKTREE · ISOLATED DEVELOPMENT" : "Execution preview";
    const previewCopy = document.createElement("span");
    if (loadingWorkspace) {
      previewCopy.textContent = "Checking current Workspace availability…";
    } else if (state.workspaceOptionsError) {
      previewCopy.textContent = state.workspaceOptionsError + " · Auto/Main disabled until Backend availability is known.";
    } else if (selectedAvailability?.enabled === false) {
      previewCopy.textContent = String(selectedAvailability.error || "This Workspace choice is currently unavailable.");
    } else if (selectedAvailability?.effective_mode) {
      const effective = selectedAvailability.effective_mode === "main" ? "Main" : "Isolated Worktree";
      previewCopy.textContent = workspace.value === "auto"
        ? "Auto currently resolves to " + effective + "."
        : "Current effective Workspace: " + effective + ".";
    } else {
      previewCopy.textContent = "Isolated Worktree is always safe to select.";
    }
    availabilityNote.append(previewTitle, previewCopy);
    workspaceSection.append(workspaceHead, workspace, workspaceOptions, availabilityNote);

    const source = sourceState(item);
    const promptCard = sourceCard(
      tr("task.prompt_source_title", "Task Prompt"),
      "Choose how this task gets its prompt",
      "prompt",
      [["write", tr("task.source_write", "Write")], ["file", tr("task.source_file", "File")], ["asset", tr("task.source_asset", "Asset")]],
      source.promptMode,
    );
    promptCard.tabs.querySelectorAll("button").forEach((button) => {
      button.addEventListener("click", async () => {
        const mode = button.dataset.taskSourceMode;
        if (mode === "asset" && !(state.prompts || []).length) await loadPromptAssets();
        if (!state) return;
        applySourceMode(item, "prompt", mode);
      });
    });
    if (source.promptMode === "write") {
      const prompt = document.createElement("textarea");
      prompt.id = "taskWorkspacePrompt";
      prompt.placeholder = "Describe what this task should do…";
      prompt.value = String(item.prompt || source.promptText || "");
      prompt.addEventListener("input", () => {
        source.promptText = prompt.value;
        updateItem(state.index, "prompt", prompt.value);
      });
      const panel = sourceModePanel("inline");
      panel.appendChild(prompt);
      promptCard.body.appendChild(panel);
      appendFieldError(promptCard.card, prompt, "prompt");
    } else if (source.promptMode === "file") {
      const input = document.createElement("input");
      input.id = "taskWorkspaceGoalFile";
      input.value = String(item.goal_file || source.promptFile || "");
      input.maxLength = 4096;
      input.placeholder = "Or type an existing prompt file path";
      input.addEventListener("input", () => {
        const previous = String(item.goal_file || "");
        if (previous !== input.value) queueUploadCancel(previous);
        source.promptFile = input.value;
        updateItem(state.index, "goal_file", input.value);
      });
      const row = document.createElement("div");
      row.className = "task-workspace-path-row";
      const upload = document.createElement("button");
      upload.type = "button";
      upload.className = "task-workspace-upload";
      upload.dataset.taskUploadField = "goal_file";
      upload.textContent = tr("task.upload_file", "Upload file");
      upload.addEventListener("click", () => chooseUpload("goal_file", upload));
      row.append(input, upload);
      const panel = sourceModePanel("file");
      panel.appendChild(row);
      promptCard.body.appendChild(panel);
      appendFieldError(promptCard.card, input, "goal_file");
    } else {
      const select = promptAssetSelect("taskWorkspaceGoalAsset", item.goal_file || source.promptAsset, (value) => {
        source.promptAsset = value;
        updateItem(state.index, "goal_file", value);
      });
      const prompts = sourceMiniAction(promptsButton("taskWorkspaceGoalAssetOpenPrompts"));
      promptCard.body.appendChild(sourceModePathPanel("asset", select, prompts));
      appendFieldError(promptCard.card, select, "goal_file");
    }
    promptCard.card.classList.add("task-workspace-prompt-source", "task-workspace-task-primary-source");

    const inputGrid = document.createElement("div");
    inputGrid.id = "taskWorkspaceInputGrid";
    inputGrid.className = "task-workspace-input-grid";
    const inputPrimary = document.createElement("div");
    inputPrimary.className = "task-workspace-input-primary";
    inputPrimary.appendChild(promptCard.card);
    const inputSupporting = document.createElement("div");
    inputSupporting.className = "task-workspace-input-supporting";
    inputGrid.append(inputPrimary, inputSupporting);

    const validationGrid = document.createElement("div");
    validationGrid.className = "task-workspace-validation-grid task-workspace-validation-stack";

    function pathControl(id, key, value, placeholder = "Enter file path") {
      const input = document.createElement("input");
      input.id = id;
      input.value = String(value || "");
      input.maxLength = 4096;
      input.placeholder = placeholder;
      input.addEventListener("input", () => {
        const previous = String(editorDraft()?.items?.[state.index]?.[key] || "");
        if (previous !== input.value) queueUploadCancel(previous);
        updateItem(state.index, key, input.value);
      });
      const row = document.createElement("div");
      row.className = "task-workspace-path-row";
      const upload = document.createElement("button");
      upload.type = "button";
      upload.className = "task-workspace-upload";
      upload.dataset.taskUploadField = key;
      upload.textContent = tr("task.upload_file", "Upload file");
      upload.addEventListener("click", () => chooseUpload(key, upload));
      row.append(input, upload);
      return { row, input };
    }

    if (capability?.requires_python_validator) {
      const validatorCard = sourceCard(
        tr("task.file_validator", "File Validator"),
        tr("task.file_validator_help", "Required by this workflow"),
        "validator",
        [],
        "",
      );
      validatorCard.card.classList.add("task-workspace-task-file-source");
      validatorCard.tabs.remove();
      const required = document.createElement("span");
      required.className = "task-workspace-cap-chip task-workspace-required-chip";
      required.textContent = "Required";
      validatorCard.card.querySelector(".task-workspace-source-head")?.appendChild(required);
      const control = pathControl("taskWorkspaceValidator", "validator", item.validator, "Or type an existing validator path");
      validatorCard.body.appendChild(control.row);
      const validatorNote = document.createElement("p");
      validatorNote.className = "task-workspace-source-note";
      validatorNote.textContent = "Manual path is used as-is. Upload fills this field with the managed target path immediately; Create/Save copies the uploaded bytes to that path.";
      validatorCard.body.appendChild(validatorNote);
      appendFieldError(validatorCard.card, control.input, "validator");
      validationGrid.appendChild(validatorCard.card);
    }

    if (capability?.has_ai_validator) {
      const aiCard = sourceCard(
        tr("task.ai_validation_title", "AI Validation"),
        source.aiMode === "default" ? "Workflow default" : "Custom prompt source",
        "ai",
        [["default", tr("task.source_default", "Default")], ["write", tr("task.source_write", "Write")], ["file", tr("task.source_file", "File")], ["asset", tr("task.source_asset", "Asset")]],
        source.aiMode,
      );
      aiCard.card.classList.add("task-workspace-task-ai-source");
      aiCard.tabs.querySelectorAll("button").forEach((button) => {
        button.addEventListener("click", async () => {
          const mode = button.dataset.taskSourceMode;
          if (mode === "asset" && !(state.prompts || []).length) await loadPromptAssets();
          if (!state) return;
          applySourceMode(item, "ai", mode);
        });
      });
      if (source.aiMode === "default") {
        const note = document.createElement("div");
        note.className = "task-workspace-compact-default-value";
        const strong = document.createElement("strong");
        strong.textContent = "Workflow default";
        const span = document.createElement("span");
        span.textContent = "No override prompt";
        note.append(strong, span);
        const panel = sourceModePanel("default");
        panel.appendChild(note);
        aiCard.body.appendChild(panel);
      } else if (source.aiMode === "write") {
        const textarea = document.createElement("textarea");
        textarea.id = "taskWorkspaceAiValidatorPromptText";
        textarea.placeholder = "Only add instructions that differ from the workflow default";
        textarea.value = String(item.ai_validator_prompt || source.aiText || "");
        textarea.addEventListener("input", () => {
          source.aiText = textarea.value;
          updateItem(state.index, "ai_validator_prompt", textarea.value);
        });
        const panel = sourceModePanel("inline");
        panel.appendChild(textarea);
        aiCard.body.appendChild(panel);
        appendFieldError(aiCard.card, textarea, "ai_validator_prompt");
      } else if (source.aiMode === "file") {
        const control = pathControl(
          "taskWorkspaceAiValidatorPrompt",
          "ai_validator_prompt_file",
          item.ai_validator_prompt_file || source.aiFile,
          "Or type an existing AI prompt file path",
        );
        control.input.addEventListener("input", () => { source.aiFile = control.input.value; });
        const panel = sourceModePanel("file");
        panel.appendChild(control.row);
        aiCard.body.appendChild(panel);
        appendFieldError(aiCard.card, control.input, "ai_validator_prompt_file");
      } else {
        const select = promptAssetSelect(
          "taskWorkspaceAiValidatorAsset",
          item.ai_validator_prompt_file || source.aiAsset,
          (value) => {
            source.aiAsset = value;
            updateItem(state.index, "ai_validator_prompt_file", value);
          },
        );
        const prompts = sourceMiniAction(promptsButton("taskWorkspaceAiAssetOpenPrompts"));
        aiCard.body.appendChild(sourceModePathPanel("asset", select, prompts));
        appendFieldError(aiCard.card, select, "ai_validator_prompt_file");
      }
      validationGrid.appendChild(aiCard.card);
    }
    if (validationGrid.children.length) {
      inputSupporting.appendChild(validationGrid);
      if (validationGrid.children.length > 1) inputGrid.classList.add("has-mixed-validation");
    } else {
      const empty = document.createElement("div");
      empty.className = "task-workspace-validation-empty";
      empty.textContent = "This Workflow needs no extra validator input.";
      inputSupporting.appendChild(empty);
      inputGrid.classList.add("has-no-validation");
    }
    body.appendChild(inputGrid);
    body.appendChild(workspaceSection);

    const error = document.createElement("div");
    error.id = "taskWorkspaceError";
    error.className = "task-workspace-error";
    error.hidden = !state.error;
    error.textContent = state.error || "";
    body.appendChild(error);
    const prompts = promptsButton();
    if (prompts) {
      const actions = document.createElement("div");
      actions.className = "task-workspace-info-actions";
      actions.appendChild(prompts);
      body.appendChild(actions);
    }
  }


  async function refreshTaskProjection() {
    if (state?.kind !== "task") return;
    const owner = state;
    const taskId = String(owner.task?.task_id || "");
    const project = String(owner.task?.project || "");
    if (!taskId || !project) return;
    const token = ++taskProjectionToken;
    try {
      const data = await api("/api/tasks?project=" + encodeURIComponent(project), { timeoutMs: 15000 });
      if (state !== owner || token !== taskProjectionToken) return;
      const latest = (Array.isArray(data?.tasks) ? data.tasks : []).find((row) => String(row?.task_id || "") === taskId);
      if (!latest) throw new Error("Task no longer exists");
      owner.task = cloneDraft(latest);
      owner.infoRefreshError = "";
      render();
    } catch (error) {
      if (state !== owner || token !== taskProjectionToken) return;
      owner.infoRefreshError = String(error?.message || "Task projection refresh failed");
      render();
    }
  }

  function renderTaskInfo() {
    const task = state.task || {};
    const body = byId("taskWorkspaceBody");
    body.innerHTML = "";

    const tabs = document.createElement("div");
    tabs.className = "task-workspace-tabs";
    const tabLabels = {
      overview: tr("task.tab_overview", "Overview"),
      runtime: tr("task.tab_runtime", "Runtime"),
      output: tr("task.tab_output", "Output"),
      history: tr("task.tab_history", "History"),
    };
    for (const id of ["overview", "runtime", "output", "history"]) {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "task-workspace-tab";
      button.textContent = tabLabels[id];
      button.classList.toggle("active", state.tab === id);
      button.setAttribute("aria-pressed", String(state.tab === id));
      button.onclick = () => {
        state.tab = id;
        render();
        if (id !== "overview") void refreshTaskProjection();
      };
      tabs.appendChild(button);
    }
    body.appendChild(tabs);

    if (state.tab !== "overview") {
      renderTaskRuntimePanel({
        tab: state.tab,
        body,
        task,
        tr,
        trf,
        refreshError: state.infoRefreshError || "",
      });
      return;
    }

    const overview = document.createElement("section");
    overview.className = "task-workspace-overview";
    const status = document.createElement("div");
    status.className = "task-workspace-status";
    const lifecycle = document.createElement("span");
    lifecycle.className = "task-workspace-status-pill";
    lifecycle.textContent = String(task.status || "new").toUpperCase();
    const identity = document.createElement("code");
    identity.textContent = String(task.task_id || "");
    status.append(lifecycle, identity);
    overview.appendChild(status);

    const meta = document.createElement("dl");
    meta.className = "task-workspace-meta-grid";
    for (const [label, value] of [
      [tr("task.meta_project", "Project"), String(task.project || "")],
      [tr("task.meta_type", "Type"), task.kind === "task_list" ? tr("task.type_list", "Task List") : tr("task.type_task", "Task")],
      [tr("task.meta_items", "Items"), String(Array.isArray(task.items) ? task.items.length : 0)],
    ]) {
      const dt = document.createElement("dt"); dt.textContent = label;
      const dd = document.createElement("dd"); dd.textContent = value;
      meta.append(dt, dd);
    }
    overview.appendChild(meta);

    const heading = document.createElement("div");
    heading.className = "task-workspace-intro";
    const headingTitle = document.createElement("strong");
    headingTitle.textContent = tr("task.items_title", "Tasks");
    const headingCopy = document.createElement("span");
    headingCopy.textContent = tr("task.items_canonical", "Canonical ordered items");
    heading.append(headingTitle, headingCopy);
    overview.appendChild(heading);
    overview.appendChild(renderTaskRows(task.items));

    const workspaceResult = task?.run?.workspace_result && typeof task.run.workspace_result === "object"
      ? task.run.workspace_result
      : null;
    const mergeResult = workspaceResult?.merge && typeof workspaceResult.merge === "object"
      ? workspaceResult.merge
      : null;
    if (workspaceResult?.snapshot) {
      const resultCard = document.createElement("section");
      resultCard.className = "task-workspace-result-card";
      const resultHead = document.createElement("div");
      resultHead.className = "task-workspace-result-head";
      const resultTitle = document.createElement("strong");
      resultTitle.textContent = "Workspace Result";
      const badge = document.createElement("span");
      badge.id = "taskWorkspaceWorktreeBadge";
      badge.className = "task-workspace-worktree-badge";
      badge.textContent = String(workspaceResult.effective_mode || task?.run?.workspace?.effective_mode || "worktree").toUpperCase();
      resultHead.append(resultTitle, badge);
      resultCard.appendChild(resultHead);

      const resultMeta = document.createElement("dl");
      resultMeta.className = "task-workspace-result-meta";
      const run = task?.run && typeof task.run === "object" ? task.run : {};
      const prepared = run.workspace && typeof run.workspace === "object" ? run.workspace : {};
      const mergeSource = workspaceResult?.merge_source?.workspace && typeof workspaceResult.merge_source.workspace === "object"
        ? workspaceResult.merge_source.workspace
        : {};
      const itemCount = Array.isArray(task.items) ? task.items.length : 0;
      const itemIndex = Number(run.item_index || 0);
      const runLabel = run.run_number
        ? "Run #" + String(run.run_number) + (itemCount ? " · Item " + String(Math.min(itemIndex + 1, itemCount)) + "/" + String(itemCount) : "")
        : "—";
      for (const [label, value, id] of [
        ["Project", String(task.project || ""), "taskWorkspaceResultProject"],
        ["Task Run", runLabel, "taskWorkspaceRun"],
        ["Target branch", String(mergeSource.target_branch || prepared.target_branch || ""), "taskWorkspaceTargetBranch"],
        ["Source branch", String(mergeSource.task_branch || workspaceResult.branch || prepared.task_branch || ""), "taskWorkspaceBranch"],
        ["Source path", String(mergeSource.worktree_path || workspaceResult.path || prepared.worktree_path || ""), "taskWorkspacePath"],
        ["Merge", String(mergeResult?.status || run.phase || "ready"), "taskWorkspaceMergeStatus"],
        ["Merge failures", String(Number(task.merge_failure_count || 0)), "taskWorkspaceMergeFailures"],
      ]) {
        const dt = document.createElement("dt"); dt.textContent = label;
        const dd = document.createElement("dd"); dd.id = id; dd.textContent = value || "—";
        resultMeta.append(dt, dd);
      }
      resultCard.appendChild(resultMeta);

      const fallback = workspaceResult?.delivery_fallback;
      if (fallback && typeof fallback === "object") {
        const fallbackDetail = document.createElement("p");
        fallbackDetail.id = "taskWorkspaceFallback";
        fallbackDetail.className = "task-workspace-result-detail";
        fallbackDetail.textContent = [
          "Fallback: " + String(fallback.mode || "worktree"),
          String(fallback.reason || ""),
        ].filter(Boolean).join(" · ");
        resultCard.appendChild(fallbackDetail);
      }

      const publishResult = workspaceResult?.publish && typeof workspaceResult.publish === "object"
        ? workspaceResult.publish
        : null;
      if (publishResult) {
        const publishDetail = document.createElement("p");
        publishDetail.id = "taskWorkspacePublishState";
        publishDetail.className = "task-workspace-result-detail";
        publishDetail.textContent = [
          "Publish: " + String(publishResult.status || "unknown"),
          String(publishResult.remote || "origin") + "/" + String(publishResult.branch || ""),
          String(publishResult.detail || ""),
        ].filter(Boolean).join(" · ");
        resultCard.appendChild(publishDetail);
      }

      if (Array.isArray(mergeResult?.conflict_files) && mergeResult.conflict_files.length) {
        const conflicts = document.createElement("p");
        conflicts.id = "taskWorkspaceConflicts";
        conflicts.className = "task-workspace-result-detail";
        conflicts.textContent = "Conflicts: " + mergeResult.conflict_files.join(", ");
        resultCard.appendChild(conflicts);
      } else if (mergeResult?.detail) {
        const detail = document.createElement("p");
        detail.className = "task-workspace-result-detail";
        detail.textContent = String(mergeResult.detail);
        resultCard.appendChild(detail);
      }

      const resultActions = document.createElement("div");
      resultActions.className = "task-workspace-result-actions";
      const merge = document.createElement("button");
      merge.id = "taskWorkspaceMerge";
      merge.type = "button";
      merge.textContent = "Merge";
      const mergeStatus = String(mergeResult?.status || "");
      const cleanupComplete = String(task?.workspace_cleanup?.status || "") === "cleaned";
      const mergeBlocked = new Set(["conflict", "source_fail", "technical_error", "validation_required", "waiting_target_history"]);
      merge.disabled = cleanupComplete || mergeBlocked.has(mergeStatus) || mergeStatus === "merged" || mergeStatus === "no_changes";
      merge.title = merge.disabled && mergeBlocked.has(mergeStatus)
        ? "Resolve this merge state before retrying direct Merge"
        : "";
      merge.onclick = () => void mergeTaskResult();
      resultActions.appendChild(merge);

      const publishable = !cleanupComplete
        && String(task.status || "") === "closed"
        && new Set(["merged", "no_changes", "worktree_ready"]).has(mergeStatus);
      if (publishable) {
        const publish = document.createElement("button");
        publish.id = "taskWorkspacePublish";
        publish.type = "button";
        publish.textContent = "Publish";
        publish.title = "Push this completed durable result to origin without force";
        publish.onclick = () => void publishTaskResult();
        resultActions.appendChild(publish);
      }

      if (typeof openMergeChat === "function") {
        const mergeChat = document.createElement("button");
        mergeChat.id = "taskWorkspaceMergeChat";
        mergeChat.type = "button";
        mergeChat.textContent = "Merge Chat";
        mergeChat.onclick = () => void openTaskMergeChat();
        resultActions.appendChild(mergeChat);
      }
      resultCard.appendChild(resultActions);
      overview.appendChild(resultCard);
    }

    const policy = taskEditPolicy(task);
    const lifecycleStatus = String(task.status || "new");
    const editable = !!policy.editable;
    const actions = document.createElement("div");
    actions.className = "task-workspace-info-actions";
    const restrictions = [];

    if (policy.can_cleanup) {
      const cleanup = document.createElement("button");
      cleanup.id = "taskWorkspaceCleanupWorktrees";
      cleanup.type = "button";
      cleanup.textContent = "Cleanup Worktrees";
      cleanup.title = "Explicitly remove retained Task/Recovery worktrees and local branches";
      cleanup.onclick = () => void cleanupTaskWorkspaces();
      actions.appendChild(cleanup);
    }

    const remove = document.createElement("button");
    remove.id = "taskWorkspaceDeleteTask";
    remove.type = "button";
    remove.className = "danger";
    remove.textContent = "Delete Task";
    if (policy.can_delete) {
      remove.onclick = () => void deleteTask();
    } else {
      remove.disabled = true;
      remove.title = policy.can_cleanup
        ? "Cleanup retained Task worktrees before deletion"
        : "Task cannot be deleted in its current lifecycle state";
      restrictions.push(
        policy.can_cleanup
          ? "Delete is unavailable until retained Task worktrees are explicitly cleaned up."
          : "Delete is unavailable while this Task has active or resumable lifecycle state."
      );
    }
    actions.appendChild(remove);

    const taskList = Array.isArray(task.items) && task.items.length > 1;
    const edit = document.createElement("button");
    edit.id = taskList ? "taskWorkspaceOpenList" : "taskWorkspaceEditTask";
    edit.type = "button";
    edit.textContent = taskList ? "Open Task List" : "Edit Task";
    if (taskList) {
      edit.onclick = () => beginTaskListEdit();
      edit.textContent = editable ? "Edit Task List" : "Open Task List";
      if (!editable) restrictions.push("Task List is view-only. " + taskMutationBlockedReason(task) + ".");
    } else {
      const itemPolicy = Array.isArray(policy.items) ? policy.items[0] : null;
      if (editable && itemPolicy?.editable !== false) {
        edit.onclick = () => beginTaskEdit(0, "info");
      } else {
        edit.disabled = true;
        edit.title = String(itemPolicy?.reason || taskMutationBlockedReason(task));
        restrictions.push(edit.title + ".");
      }
    }
    actions.appendChild(edit);

    if (lifecycleStatus === "paused") {
      const reset = document.createElement("button");
      reset.id = "taskWorkspaceResetTask";
      reset.type = "button";
      reset.textContent = "Reset";
      reset.onclick = () => void runTaskLifecycleAction("reset");
      actions.appendChild(reset);
    }
    if (lifecycleStatus === "paused" || lifecycleStatus === "closed") {
      const rerun = document.createElement("button");
      rerun.id = "taskWorkspaceRerunTask";
      rerun.type = "button";
      rerun.textContent = "Rerun";
      rerun.onclick = () => void runTaskLifecycleAction("rerun");
      actions.appendChild(rerun);
    }

    if (policy.restart_required) {
      restrictions.unshift("Current paused Task configuration changed. Restart the current item instead of resuming its frozen run.");
    }
    if (restrictions.length) {
      const note = document.createElement("p");
      note.className = "task-workspace-action-note";
      note.textContent = [...new Set(restrictions)].join(" ");
      overview.appendChild(note);
    }
    overview.appendChild(actions);
    body.appendChild(overview);
  }

  function taskDraftFromRecord(task) {
    return {
      title: String(task?.title || ""),
      project: String(task?.project || ""),
      items: cloneDraft(task?.items || []),
    };
  }

  function ensureTaskEditDraft() {
    const task = state?.task;
    if (!task || !taskEditPolicy(task).editable) return false;
    if (!state.editDraft) {
      state.editDraft = taskDraftFromRecord(task);
      state.editOriginal = draftSignature(state.editDraft);
      state.saveRequestId = "";
    }
    return true;
  }

  function beginTaskListEdit() {
    if (!ensureTaskEditDraft()) {
      state.route = "list";
      render();
      return;
    }
    state.editorReturn = "list";
    state.error = "";
    state.route = "list";
    render();
  }

  function addDraftListItem() {
    if (!isDraftState()) return;
    const first = state.draft.items[0] || {};
    const workflow = String(first.workflow || state.workflows?.[0]?.path || state.workflows?.[0]?.id || "");
    state.draft.items.push(blankItem(state.project, workflow));
    state.index = state.draft.items.length - 1;
    state.error = "";
    state.fieldErrors = {};
    state.draftEditorOriginal = draftSignature(state.draft);
    state.editorMode = "create";
    state.route = "editor";
    render();
  }

  function addTaskListItem() {
    if (!ensureTaskEditDraft() || !taskEditPolicy().can_add_item) return;
    const first = state.editDraft.items[0] || {};
    const workflow = String(first.workflow || state.workflows?.[0]?.path || state.workflows?.[0]?.id || "");
    state.editDraft.items.push(blankItem(state.task?.project || "", workflow));
    touchEditor();
    state.index = state.editDraft.items.length - 1;
    state.editorReturn = "list";
    state.editorMode = "create";
    state.error = "";
    state.route = "editor";
    render();
  }

  function renderDurableTaskList() {
    const task = state.task || {};
    const body = byId("taskWorkspaceBody");
    body.innerHTML = "";
    const policy = taskEditPolicy(task);
    const editable = policy.editable && ensureTaskEditDraft();
    const items = editable ? state.editDraft.items : (Array.isArray(task.items) ? task.items : []);
    const blockedReason = editable ? "" : taskMutationBlockedReason(task);
    body.appendChild(buildTaskListPage({
      items,
      editable,
      canAdd: editable && policy.can_add_item,
      canYaml: editable && policy.can_edit_yaml,
      reason: blockedReason || policy.reason || "",
      durableTask: task,
    }));

    if (policy.restart_required) {
      const note = document.createElement("p");
      note.className = "task-workspace-action-note";
      note.textContent = "Current paused Task changed · restart required before continuing.";
      body.appendChild(note);
    } else if (!editable) {
      const note = document.createElement("p");
      note.className = "task-workspace-action-note";
      note.textContent = "Task List is view-only. " + blockedReason + ".";
      body.appendChild(note);
    }
    if (state.error) {
      const error = document.createElement("div");
      error.id = "taskWorkspaceError";
      error.className = "task-workspace-error";
      error.textContent = state.error;
      body.appendChild(error);
    }
  }

  function mergeChatPrompt(task) {
    const run = task?.run && typeof task.run === "object" ? task.run : {};
    const prepared = run.workspace && typeof run.workspace === "object" ? run.workspace : {};
    const result = run.workspace_result && typeof run.workspace_result === "object" ? run.workspace_result : {};
    const merge = result.merge && typeof result.merge === "object" ? result.merge : {};
    const snapshot = result.snapshot && typeof result.snapshot === "object" ? result.snapshot : {};
    const conflicts = Array.isArray(merge.conflict_files) ? merge.conflict_files : [];
    return [
      "Help me integrate this completed AI Task Runner result into the captured Project branch.",
      "Do not restart or redo the original feature development. Preserve the latest Project changes and adapt only the completed Task result needed for integration.",
      "",
      "Task: " + String(task?.title || task?.task_id || ""),
      "Task ID: " + String(task?.task_id || ""),
      "Run: " + String(run.run_number || ""),
      "Project: " + String(task?.project || ""),
      "Target branch: " + String(prepared.target_branch || ""),
      "Task branch: " + String(result.branch || prepared.task_branch || ""),
      "Worktree: " + String(result.path || prepared.worktree_path || ""),
      "Task snapshot: " + String(snapshot.task_snapshot_sha || ""),
      "Merge status: " + String(merge.status || run.phase || ""),
      conflicts.length ? "Conflict files: " + conflicts.join(", ") : "",
      merge.detail ? "Merge detail: " + String(merge.detail) : "",
      "",
      "Inspect the latest Project state and the retained Task worktree/branch, then help resolve only this integration or merge problem safely.",
    ].filter((line) => line !== "").join("\n");
  }

  async function openTaskMergeChat() {
    const task = state?.task;
    if (!task || typeof openMergeChat !== "function") return;
    try {
      await openMergeChat({
        project: String(task.project || ""),
        title: "Merge · " + String(task.title || task.task_id || "Task"),
        prompt: mergeChatPrompt(task),
      });
      closeNow({ restore: false });
    } catch (error) {
      showError?.(error.message, "Open Merge Chat failed");
    }
  }

  async function mergeTaskResult() {
    const task = state?.task;
    if (!task) return;
    const button = byId("taskWorkspaceMerge");
    if (button?.disabled) return;
    if (button) {
      button.disabled = true;
      button.setAttribute("aria-busy", "true");
    }
    try {
      const updated = await api("/api/tasks/merge", {
        method: "POST",
        body: JSON.stringify({ project: task.project, task_id: task.task_id }),
      });
      state.task = cloneDraft(updated);
      state.error = "";
      render();
      await onTaskChanged?.();
    } catch (error) {
      showError?.(error.message, "Merge Task failed");
      render();
    }
  }

  async function publishTaskResult() {
    const task = state?.task;
    if (!task || String(task.status || "") !== "closed") return;
    const run = task.run && typeof task.run === "object" ? task.run : {};
    const result = run.workspace_result && typeof run.workspace_result === "object" ? run.workspace_result : {};
    const merge = result.merge && typeof result.merge === "object" ? result.merge : {};
    const mergeStatus = String(merge.status || run.phase || "");
    if (!["merged", "no_changes", "worktree_ready"].includes(mergeStatus)) return;
    const source = result?.merge_source?.workspace && typeof result.merge_source.workspace === "object"
      ? result.merge_source.workspace
      : {};
    const branch = ["merged", "no_changes"].includes(mergeStatus)
      ? String(source.target_branch || run?.workspace?.target_branch || "")
      : String(source.task_branch || result.branch || run?.workspace?.task_branch || "");
    const ok = await confirmDialog?.({
      title: "Publish completed result to origin?",
      message: "This runs an explicit non-force Git push only. It does not change Task merge/recovery state.",
      details: [
        { label: "Branch:", value: branch || "—" },
        { label: "Task:", value: String(task.title || task.task_id || "") },
      ],
      confirmLabel: "Publish",
    });
    if (!ok) return;

    const button = byId("taskWorkspacePublish");
    if (button) {
      button.disabled = true;
      button.setAttribute("aria-busy", "true");
    }
    try {
      const updated = await api("/api/tasks/publish", {
        method: "POST",
        body: JSON.stringify({
          project: task.project,
          task_id: task.task_id,
          request_id: newRequestId("task-publish"),
        }),
      });
      state.task = cloneDraft(updated);
      state.error = "";
      render();
      const published = updated?.run?.workspace_result?.publish;
      if (published && !["published", "already_published"].includes(String(published.status || ""))) {
        showError?.(String(published.detail || published.status || "Publish failed"), "Publish failed");
      }
      await onTaskChanged?.();
    } catch (error) {
      showError?.(error.message, "Publish failed");
      render();
    }
  }

  async function cleanupTaskWorkspaces() {
    const task = state?.task;
    const policy = taskEditPolicy(task);
    if (!task || !policy.can_cleanup) return;
    const ok = await confirmDialog?.({
      title: "Cleanup retained Task worktrees?",
      message: "This explicitly deletes only AI Task Runner-owned Task/Recovery worktrees and their local branches. Task history is preserved. Remote branches are not deleted.",
      details: [
        { label: "Task:", value: String(task.title || task.task_id || "") },
        { label: "Status:", value: String(task.status || "") },
      ],
      confirmLabel: "Cleanup Worktrees",
      danger: true,
    });
    if (!ok) return;

    const button = byId("taskWorkspaceCleanupWorktrees");
    if (button) {
      button.disabled = true;
      button.setAttribute("aria-busy", "true");
    }
    try {
      const updated = await api("/api/tasks/cleanup", {
        method: "POST",
        body: JSON.stringify({
          project: task.project,
          task_id: task.task_id,
          request_id: newRequestId("task-cleanup"),
        }),
      });
      state.task = cloneDraft(updated);
      state.error = "";
      render();
      await onTaskChanged?.();
    } catch (error) {
      showError?.(error.message, "Cleanup Worktrees failed");
      render();
    }
  }

  async function runTaskLifecycleAction(action) {
    const task = state?.task;
    if (!task || !["reset", "rerun"].includes(action)) return;
    const status = String(task.status || "");
    if (action === "reset" && status !== "paused") return;
    if (action === "rerun" && !["paused", "closed"].includes(status)) return;

    const completed = status === "closed";
    const options = action === "reset"
      ? {
          title: "Reset paused Task and move it to New?",
          message: "The current resumable run is archived and retained. Progress returns to Task 1; existing worktree/branch output is not deleted.",
          confirmLabel: "Reset & Move to New",
          danger: true,
        }
      : {
          title: completed ? "Rerun this completed Task?" : "Rerun this Task from the beginning?",
          message: completed
            ? "The completed run stays in History. A fresh Task Run/worktree starts again from Task 1."
            : "The current run is archived and retained. A fresh Task Run/worktree starts again from Task 1.",
          confirmLabel: "Rerun",
          danger: true,
        };
    const ok = await confirmDialog?.(options);
    if (!ok) return;

    const button = byId(action === "reset" ? "taskWorkspaceResetTask" : "taskWorkspaceRerunTask");
    if (button) {
      button.disabled = true;
      button.setAttribute("aria-busy", "true");
    }
    try {
      const updated = await api("/api/tasks/" + action, {
        method: "POST",
        body: JSON.stringify({
          project: task.project,
          task_id: task.task_id,
          request_id: newRequestId("task-" + action),
        }),
      });
      state.task = cloneDraft(updated);
      state.editDraft = null;
      state.editOriginal = "";
      state.saveRequestId = "";
      state.error = "";
      render();
      await onTaskChanged?.();
    } catch (error) {
      showError?.(error.message, action === "reset" ? "Reset Task failed" : "Rerun Task failed");
      render();
    }
  }

  async function deleteTask() {
    const task = state?.task;
    if (!task || !taskEditPolicy(task).can_delete) return;
    const ok = await confirmDialog?.({
      title: "Delete Task?",
      message: "This deletes the durable Task record. It does not delete Project files.",
      details: [
        { label: "Task ID:", value: String(task.task_id || "") },
        { label: "Name:", value: String(task.title || "") },
        { label: "Project:", value: String(task.project || "") },
      ],
      confirmLabel: "Delete Task",
      danger: true,
    });
    if (!ok) return;
    try {
      await api("/api/tasks/delete", {
        method: "POST",
        body: JSON.stringify({
          project: task.project,
          task_id: task.task_id,
          request_id: "task-delete-" + task.task_id,
        }),
      });
      closeNow();
      await onTaskChanged?.();
    } catch (error) {
      showError?.(error.message, "Delete Task failed");
    }
  }

  async function openYaml() {
    if (state?.kind === "task") {
      if (!ensureTaskEditDraft() || !taskEditPolicy().can_edit_yaml) return;
    }
    const draft = editorDraft();
    if (!draft) return;
    try {
      const project = state.kind === "task" ? state.task.project : state.project;
      const data = await api("/api/tasks/yaml/dump", {
        method: "POST",
        body: JSON.stringify({ project, draft }),
      });
      state.yamlText = String(data.content || "");
      state.yamlOriginal = state.yamlText;
      state.yamlReturn = "list";
      state.error = "";
      state.route = "yaml";
      render();
    } catch (error) {
      showError?.(error.message, "Open Task YAML failed");
    }
  }

  function renderYaml() {
    const body = byId("taskWorkspaceBody");
    body.innerHTML = "";
    const intro = document.createElement("div");
    intro.className = "task-workspace-intro";
    intro.innerHTML = "<strong>Task YAML</strong><span>Apply updates the same canonical items[]; Save persists from Task List.</span>";
    body.appendChild(intro);
    const field = document.createElement("label");
    field.className = "task-workspace-field task-workspace-prompt";
    const textarea = document.createElement("textarea");
    textarea.id = "taskWorkspaceYamlText";
    textarea.rows = 22;
    textarea.spellcheck = false;
    textarea.value = String(state.yamlText || "");
    textarea.addEventListener("input", () => {
      state.yamlText = textarea.value;
      state.error = "";
    });
    field.appendChild(textarea);
    body.appendChild(field);
    if (state.error) {
      const error = document.createElement("div");
      error.id = "taskWorkspaceError";
      error.className = "task-workspace-error";
      error.textContent = state.error;
      body.appendChild(error);
    }
    requestAnimationFrame(() => textarea.focus());
  }

  async function applyYaml() {
    if (state?.route !== "yaml") return;
    const project = state.kind === "task" ? state.task.project : state.project;
    const button = byId("taskWorkspaceSave");
    button.disabled = true;
    button.setAttribute("aria-busy", "true");
    try {
      const data = await api("/api/tasks/yaml/parse", {
        method: "POST",
        body: JSON.stringify({ project, content: state.yamlText }),
      });
      const parsed = cloneDraft(data.draft || data);
      if (state.kind === "task") {
        state.editDraft = parsed;
        state.sourceModes = {};
        touchEditor();
      } else {
        state.draft = parsed;
        state.sourceModes = {};
      }
      state.yamlOriginal = state.yamlText;
      state.yamlText = "";
      state.route = state.yamlReturn || "list";
      state.error = "";
      render();
    } catch (error) {
      state.error = String(error?.message || "Task YAML is invalid");
      render();
      showError?.(error.message, "Apply Task YAML failed");
    } finally {
      if (button && document.contains(button)) {
        button.disabled = false;
        button.removeAttribute("aria-busy");
      }
    }
  }

  function beginTaskEdit(index, returnRoute) {
    const task = state?.task;
    if (!task || !ensureTaskEditDraft()) return;
    const item = state.editDraft?.items?.[index];
    if (!taskItemEditPolicy(index, item).editable) return;
    state.editorReturn = returnRoute === "list" ? "list" : "info";
    state.editorMode = "edit";
    state.index = Math.max(0, Math.min(Number(index) || 0, state.editDraft.items.length - 1));
    state.saveRequestId = "";
    state.error = "";
    state.fieldErrors = {};
    state.route = "editor";
    render();
  }

  function render() {
    if (!state || !overlay) return;
    const shell = byId("taskWorkspaceShell");
    const workspaceRoute = ["editor", "list", "yaml"].includes(String(state.route || ""));
    shell?.classList.toggle("workspace-route", workspaceRoute);
    shell?.classList.toggle("task-editor-route", state.route === "editor");
    shell?.classList.toggle("task-list-route", state.route === "list");
    shell?.classList.toggle("task-yaml-route", state.route === "yaml");
    renderShellChrome();
    renderHeaderActions();
    const footer = byId("taskWorkspaceFooterBack")?.closest("footer");
    const save = byId("taskWorkspaceSave");
    const back = byId("taskWorkspaceHeaderBack");
    if (state.kind === "task") {
      const listRoute = state.route === "list";
      const editorRoute = state.route === "editor";
      const yamlRoute = state.route === "yaml";
      if (footer) footer.hidden = !(listRoute || editorRoute || yamlRoute);
      if (save) {
        const canSaveList = listRoute && taskEditPolicy(state.task).editable && !!state.editDraft;
        save.hidden = !(editorRoute || canSaveList || yamlRoute);
        save.textContent = yamlRoute
          ? tr("task.apply_yaml", "Apply YAML")
          : (canSaveList ? tr("task.save_list", "Save Task List") : tr("task.save", "Save Task"));
      }
      if (back) back.hidden = false;
      byId("taskWorkspaceEyebrow").textContent = yamlRoute
        ? tr("task.yaml", "TASK YAML")
        : (editorRoute ? tr("task.editor", "TASK EDITOR") : (listRoute ? tr("task.list", "TASK LIST") : tr("task.info", "TASK INFO")));
      const taskItems = state.editDraft?.items || state.task?.items || [];
      byId("taskWorkspaceTitle").textContent = yamlRoute
        ? "Edit task list YAML"
        : editorRoute
          ? (state.editorMode === "create" ? "New task" : "Edit task")
          : String(state.task?.title || "Task");
      byId("taskWorkspaceMeta").textContent = yamlRoute
        ? String(state.task?.task_id || "") + " · " + String(state.task?.title || "")
        : editorRoute
          ? String(state.task?.task_id || "") + " · Task " + String(state.index + 1) + " of " + String(taskItems.length)
          : listRoute
            ? [
                String(state.task?.task_id || ""),
                String(state.task?.status || "new").replace(/^./, (value) => value.toUpperCase()),
                String(taskItems.length) + " task" + (taskItems.length === 1 ? "" : "s"),
              ].filter(Boolean).join(" · ")
            : String(state.task?.task_id || "");
      if (yamlRoute) {
        byId("taskWorkspaceFooterBack").textContent = tr("task.back_list", "Back to Task List");
        renderYaml();
      } else if (editorRoute) {
        byId("taskWorkspaceFooterBack").textContent = state.editorReturn === "list" ? tr("task.back_list", "Back to Task List") : tr("task.back_info", "Back to Info");
        renderEditor();
        byId("taskWorkspaceItemTitle")?.focus();
      } else if (listRoute) {
        byId("taskWorkspaceFooterBack").textContent = tr("task.back_info", "Back to Info");
        renderDurableTaskList();
      } else {
        renderTaskInfo();
      }
      return;
    }
    if (footer) footer.hidden = false;
    const listRoute = state.route === "list";
    const yamlRoute = state.route === "yaml";
    const count = state.draft.items.length;
    const creating = !!state.createOnSave;
    const rootCreateTask = creating && state.creationKind === "task" && state.route === "editor";
    const rootCreateList = creating && state.creationKind === "list" && listRoute;
    if (back) back.hidden = rootCreateTask || rootCreateList;
    if (save) save.hidden = false;
    byId("taskWorkspaceEyebrow").textContent = yamlRoute ? tr("task.yaml", "TASK YAML") : (listRoute ? tr("task.list", "TASK LIST") : tr("task.editor", "TASK EDITOR"));
    byId("taskWorkspaceTitle").textContent = yamlRoute
      ? "Edit task list YAML"
      : listRoute
        ? String(state.draft.title || (creating ? "New Task List" : "Task List"))
        : (state.editorMode === "edit" ? "Edit task" : "New task");
    byId("taskWorkspaceMeta").textContent = yamlRoute
      ? "Same canonical items[]"
      : rootCreateList
        ? "Draft · not created yet"
        : listRoute
          ? count + " ordered task" + (count === 1 ? "" : "s")
          : rootCreateTask
            ? "New Task"
            : "Task " + (state.index + 1) + " of " + count;
    byId("taskWorkspaceFooterBack").textContent = yamlRoute
      ? tr("task.back_list", "Back to Task List")
      : (listRoute
        ? (creating ? tr("task.cancel", "Cancel") : tr("task.back_chat", "Back to Chat"))
        : (count > 1 ? tr("task.back_list", "Back to Task List") : (creating ? tr("task.cancel", "Cancel") : tr("task.back_chat", "Back to Chat"))));
    byId("taskWorkspaceSave").hidden = rootCreateList || (!yamlRoute && !listRoute && count > 1);
    byId("taskWorkspaceSave").textContent = yamlRoute
      ? "Apply YAML"
      : creating
        ? (listRoute ? tr("task.create_list", "Create Task List") : tr("task.create", "Create Task"))
        : tr("task.save_draft", "Save draft");
    byId("taskWorkspaceSave").disabled = Boolean(listRoute && creating && count === 0);
    if (yamlRoute) renderYaml(); else if (listRoute) renderList(); else renderEditor();
    if (!yamlRoute) (listRoute ? byId("taskWorkspaceDraftTitle") : byId("taskWorkspaceItemTitle"))?.focus();
  }

  async function handleBack() {
    if (!state) return;
    if (state.route === "yaml") {
      if (yamlDirty()) {
        const ok = await confirmDialog?.({
          title: "Discard unapplied YAML changes?",
          message: "YAML text that has not been applied will be lost.",
          confirmLabel: "Discard",
          danger: true,
        });
        if (!ok) return;
      }
      state.yamlText = "";
      state.yamlOriginal = "";
      state.route = state.yamlReturn || "list";
      state.error = "";
      render();
      return;
    }
    if (state.kind === "task") {
      if (state.route === "editor") {
        if (state.editorReturn === "list") {
          state.route = "list";
          state.error = "";
          render();
          return;
        }
        if (!(await confirmDiscardIfDirty())) return;
        state.editDraft = null;
        state.editOriginal = "";
        state.saveRequestId = "";
        state.route = "info";
        state.tab = "overview";
        render();
        return;
      }
      if (state.route === "list") {
        if (!(await confirmDiscardIfDirty())) return;
        state.editDraft = null;
        state.editOriginal = "";
        state.saveRequestId = "";
        state.route = "info";
        state.tab = "overview";
        render();
        return;
      }
      closeNow();
      return;
    }
    if (state.route === "editor" && state.draft.items.length > 1) {
      state.draftEditorOriginal = "";
      state.route = "list";
      render();
      return;
    }
    await requestClose();
  }

  function validateSelectedSourceModes() {
    const draft = editorDraft();
    if (!state || !draft || !Array.isArray(draft.items)) return true;
    const modes = state.sourceModes || {};
    for (let index = 0; index < draft.items.length; index += 1) {
      const item = draft.items[index];
      const source = modes[String(item?.item_id || "")];
      if (!source) continue;
      let field = "";
      let message = "";
      if (source.promptMode === "file" && !String(item.goal_file || "").trim()) {
        field = "goal_file";
        message = trf("task.goal_file_required", { index: index + 1 }, `Task item ${index + 1} goal_file is required for File mode`);
      } else if (source.promptMode === "asset" && !String(item.goal_file || "").trim()) {
        field = "goal_file";
        message = trf("task.prompt_asset_required", { index: index + 1 }, `Task item ${index + 1} Prompt asset is required for Asset mode`);
      } else if (source.aiMode === "write" && !String(item.ai_validator_prompt || "").trim()) {
        field = "ai_validator_prompt";
        message = trf("task.ai_text_required", { index: index + 1 }, `Task item ${index + 1} AI Validator Prompt text is required for Write mode`);
      } else if (source.aiMode === "file" && !String(item.ai_validator_prompt_file || "").trim()) {
        field = "ai_validator_prompt_file";
        message = trf("task.ai_file_required", { index: index + 1 }, `Task item ${index + 1} AI Validator Prompt file is required for File mode`);
      } else if (source.aiMode === "asset" && !String(item.ai_validator_prompt_file || "").trim()) {
        field = "ai_validator_prompt_file";
        message = trf("task.ai_asset_required", { index: index + 1 }, `Task item ${index + 1} AI Validator Prompt asset is required for Asset mode`);
      }
      if (!field) continue;
      state.index = index;
      state.error = message;
      state.fieldErrors = { [fieldErrorKey(field, index)]: message };
      if (state.route === "list") {
        if (isDraftState()) state.draftEditorOriginal = draftSignature(state.draft);
        state.editorMode = "edit";
        state.route = "editor";
      }
      render();
      return false;
    }
    return true;
  }

  async function saveWorkspace() {
    if (state?.route === "yaml") return applyYaml();
    if (state?.kind === "task") return saveTaskEdit();
    return saveDraft();
  }

  async function saveTaskEdit() {
    if (state?.kind !== "task" || !["list", "editor"].includes(state.route) || !state.editDraft) return;
    if (!validateSelectedSourceModes()) return;
    const button = byId("taskWorkspaceSave");
    button.disabled = true;
    button.setAttribute("aria-busy", "true");
    await pendingUploadActions;
    if (!state.saveRequestId) {
      state.saveRequestId = "task-update-" + (globalThis.crypto?.randomUUID?.() || String(Date.now()) + "-" + Math.random().toString(16).slice(2));
    }
    const returnRoute = state.route === "list"
      ? "list"
      : (state.editorReturn === "list" ? "list" : "info");
    try {
      const task = await api("/api/tasks/update", {
        method: "POST",
        body: JSON.stringify({
          project: state.task.project,
          task_id: state.task.task_id,
          draft: state.editDraft,
          request_id: state.saveRequestId,
          expected_updated_at: state.task.updated_at,
        }),
      });
      state.task = cloneDraft(task);
      state.sourceModes = {};
      state.editDraft = null;
      state.editOriginal = "";
      state.saveRequestId = "";
      state.route = returnRoute === "list" && state.task.items.length > 1 ? "list" : "info";
      if (state.route === "list" && taskEditPolicy(state.task).editable) {
        state.editDraft = taskDraftFromRecord(state.task);
        state.editOriginal = draftSignature(state.editDraft);
      }
      state.tab = "overview";
      state.error = "";
      render();
    } catch (error) {
      state.error = String(error?.message || "Task save failed");
      mapFieldError(state.error);
      render();
      showError?.(error.message, "Save Task failed");
    } finally {
      if (button && document.contains(button)) {
        button.disabled = false;
        button.removeAttribute("aria-busy");
      }
    }
  }

  async function saveDraft() {
    if (!isDraftState()) return;
    if (state.route === "list" && !state.draft.items.length) {
      state.error = "Task List must contain at least one Task";
      render();
      return;
    }
    if (!validateSelectedSourceModes()) return;
    const button = byId("taskWorkspaceSave");
    button.disabled = true;
    button.setAttribute("aria-busy", "true");
    await pendingUploadActions;
    try {
      const data = await api("/api/tasks/validate-draft", {
        method: "POST",
        body: JSON.stringify({ project: state.project, draft: state.draft }),
      });
      const normalized = cloneDraft(data.draft || data);
      if (state.createOnSave) {
        const task = await api("/api/tasks/create", {
          method: "POST",
          body: JSON.stringify({
            project: state.project,
            draft: normalized,
            request_id: state.createRequestId,
          }),
        });
        const workflows = state.workflows;
        const prompts = state.prompts;
        state = {
          kind: "task",
          task: cloneDraft(task),
          workflows,
          prompts,
          route: "info",
          tab: "overview",
          editDraft: null,
          editOriginal: "",
          editorReturn: "info",
          saveRequestId: "",
          error: "",
          yamlText: "",
          yamlOriginal: "",
          yamlReturn: "list",
        };
        onTaskChanged?.(task);
        render();
        return;
      }
      await state.onSave?.(normalized);
      state.draft = normalized;
      state.original = draftSignature(normalized);
      closeNow();
    } catch (error) {
      state.error = String(error?.message || "TaskDraft validation failed");
      const mapped = mapFieldError(state.error);
      if (!mapped && state.route === "list") {
        if (isDraftState()) state.draftEditorOriginal = draftSignature(state.draft);
        state.route = "editor";
        state.index = 0;
      }
      render();
      showError?.(error.message, "Save TaskDraft failed");
    } finally {
      if (button && document.contains(button)) {
        button.disabled = false;
        button.removeAttribute("aria-busy");
      }
    }
  }

  function openNew({ project, workflows = [], prompts = [], workflow = "", list = false, returnFocus = null }) {
    ensureMounted();
    closeCreateMenu();
    const projectPath = String(project || "").trim();
    const rows = Array.isArray(workflows) ? workflows.slice() : [];
    const defaultWorkflow = resolveWorkflowSelection(rows, workflow);
    const draft = {
      schema_version: 1,
      title: list ? "New Task List" : "New Task",
      project: projectPath,
      items: list ? [] : [blankItem(projectPath, defaultWorkflow)],
    };
    restoreFocus = returnFocus || document.activeElement;
    state = {
      kind: "draft",
      project: projectPath,
      draft,
      original: draftSignature(draft),
      workflows: rows,
      prompts: Array.isArray(prompts) ? prompts.slice() : [],
      sourceModes: {},
      onSave: null,
      createOnSave: true,
      creationKind: list ? "list" : "task",
      editorMode: list ? "" : "create",
      createRequestId: newRequestId("task-create"),
      route: list ? "list" : "editor",
      index: 0,
      error: "",
      fieldErrors: {},
      draftEditorOriginal: "",
      yamlText: "",
      yamlOriginal: "",
      yamlReturn: "list",
      workspaceOptions: null,
      workspaceOptionsLoading: true,
      workspaceOptionsError: "",
      projectOptions: [],
      projectOptionsLoading: false,
    };
    showNow();
    render();
    void loadProjectOptions();
    void loadWorkspaceOptions();
  }

  function openDraft({ project, draft, workflows = [], prompts = [], onSave, returnFocus }) {
    ensureMounted();
    const value = cloneDraft(draft || {});
    if (!Array.isArray(value.items) || !value.items.length) {
      showError?.("TaskDraft has no items", "Edit TaskDraft failed");
      return;
    }
    restoreFocus = returnFocus || document.activeElement;
    state = {
      kind: "draft",
      project: String(project || value.project || ""),
      draft: value,
      original: draftSignature(value),
      workflows: Array.isArray(workflows) ? workflows.slice() : [],
      prompts: Array.isArray(prompts) ? prompts.slice() : [],
      sourceModes: {},
      onSave,
      route: value.items.length > 1 ? "list" : "editor",
      editorMode: value.items.length > 1 ? "" : "edit",
      index: 0,
      error: "",
      fieldErrors: {},
      draftEditorOriginal: "",
      yamlText: "",
      yamlOriginal: "",
      yamlReturn: "list",
      workspaceOptions: null,
      workspaceOptionsLoading: true,
      workspaceOptionsError: "",
      projectOptions: [],
      projectOptionsLoading: false,
    };
    showNow();
    render();
    void loadProjectOptions();
    void loadWorkspaceOptions();
  }

  function openTask(task, { returnFocus, workflows = [], prompts = [] } = {}) {
    ensureMounted();
    const value = cloneDraft(task || {});
    if (!value.task_id || !Array.isArray(value.items) || !value.items.length) {
      showError?.("Task record is invalid", "Open Task failed");
      return;
    }
    restoreFocus = returnFocus || document.activeElement;
    state = {
      kind: "task",
      task: value,
      workflows: Array.isArray(workflows) ? workflows.slice() : [],
      prompts: Array.isArray(prompts) ? prompts.slice() : [],
      sourceModes: {},
      route: "info",
      tab: "overview",
      editDraft: null,
      editOriginal: "",
      editorReturn: "info",
      saveRequestId: "",
      error: "",
      fieldErrors: {},
      yamlText: "",
      yamlOriginal: "",
      yamlReturn: "list",
      workspaceOptions: null,
      workspaceOptionsLoading: true,
      workspaceOptionsError: "",
      projectOptions: [],
      projectOptionsLoading: false,
    };
    showNow();
    render();
    void loadProjectOptions();
    void loadWorkspaceOptions();
  }

  window.addEventListener("app-language-changed", () => {
    if (state && overlay && !overlay.hidden) render();
  });

  return { openDraft, openTask, openNew, openCreateMenu, close: requestClose };
}
