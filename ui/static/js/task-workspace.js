function cloneDraft(value) {
  if (globalThis.structuredClone) return globalThis.structuredClone(value);
  return JSON.parse(JSON.stringify(value));
}
function draftSignature(value) { return JSON.stringify(value || {}); }

export function createTaskWorkspaceController({ api, confirmDialog, showError }) {
  let state = null;
  let overlay = null;
  let restoreFocus = null;
  const byId = (id) => document.getElementById(id);

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
          <button id="taskWorkspaceClose" class="task-workspace-close" type="button" aria-label="Close Task Editor">×</button>
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
    byId("taskWorkspaceHeaderBack").addEventListener("click", () => void handleBack());
    byId("taskWorkspaceFooterBack").addEventListener("click", () => void handleBack());
    byId("taskWorkspaceSave").addEventListener("click", () => void saveDraft());
    document.addEventListener("keydown", (event) => {
      if (!overlay || overlay.hidden || event.key !== "Escape") return;
      event.preventDefault();
      event.stopPropagation();
      void requestClose();
    }, true);
    return overlay;
  }

  function isDraftState() { return state?.kind === "draft"; }
  function isDirty() { return isDraftState() && draftSignature(state.draft) !== state.original; }

  async function requestClose() {
    if (!state) return closeNow();
    if (isDirty()) {
      const ok = await confirmDialog?.({
        title: "Discard TaskDraft changes?",
        message: "Your unsaved TaskDraft edits will be lost.",
        confirmLabel: "Discard",
        danger: true,
      });
      if (!ok) return;
    }
    closeNow();
  }

  function closeNow() {
    if (overlay) overlay.hidden = true;
    const focus = restoreFocus;
    state = null;
    restoreFocus = null;
    requestAnimationFrame(() => {
      if (focus && document.contains(focus) && typeof focus.focus === "function") focus.focus();
    });
  }

  function updateItem(index, key, value) {
    const item = state?.draft?.items?.[index];
    if (item) item[key] = value;
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
    input.value = String(state.draft.title || "");
    input.maxLength = 240;
    input.addEventListener("input", () => { state.draft.title = input.value; });
    wrap.append(label, input);
    return wrap;
  }

  function moveItem(index, delta) {
    const next = index + delta;
    if (!state || next < 0 || next >= state.draft.items.length) return;
    const [item] = state.draft.items.splice(index, 1);
    state.draft.items.splice(next, 0, item);
    render();
  }

  function renderList() {
    const body = byId("taskWorkspaceBody");
    body.innerHTML = "";
    body.appendChild(renderDraftTitleField());
    const intro = document.createElement("div");
    intro.className = "task-workspace-intro";
    intro.innerHTML = "<strong>Task order</strong><span>Tasks run top-to-bottom inside this Task List.</span>";
    body.appendChild(intro);
    const list = document.createElement("div");
    list.className = "task-workspace-list";
    state.draft.items.forEach((item, index) => {
      const row = document.createElement("article");
      row.className = "task-workspace-list-row";
      const number = document.createElement("span");
      number.className = "task-workspace-list-number";
      number.textContent = String(index + 1);
      const copy = document.createElement("div");
      copy.className = "task-workspace-list-copy";
      const title = document.createElement("strong");
      title.textContent = String(item.title || "Task " + (index + 1));
      const meta = document.createElement("small");
      meta.textContent = [String(item.workflow || "Workflow"), String(item.workspace || "auto").toUpperCase()].join(" · ");
      const prompt = document.createElement("p");
      prompt.textContent = String(item.prompt || "");
      copy.append(title, meta, prompt);
      const actions = document.createElement("div");
      actions.className = "task-workspace-list-actions";
      for (const [label, titleText, delta] of [["↑", "Move up", -1], ["↓", "Move down", 1]]) {
        const button = document.createElement("button");
        button.type = "button";
        button.textContent = label;
        button.title = titleText;
        button.disabled = delta < 0 ? index === 0 : index === state.draft.items.length - 1;
        button.onclick = () => moveItem(index, delta);
        actions.appendChild(button);
      }
      const edit = document.createElement("button");
      edit.type = "button";
      edit.className = "task-workspace-row-edit";
      edit.textContent = "Edit";
      edit.onclick = () => { state.route = "editor"; state.index = index; render(); };
      const remove = document.createElement("button");
      remove.type = "button";
      remove.textContent = "Remove";
      remove.disabled = state.draft.items.length <= 1;
      remove.onclick = () => {
        if (state.draft.items.length <= 1) return;
        state.draft.items.splice(index, 1);
        state.index = Math.min(state.index, state.draft.items.length - 1);
        render();
      };
      actions.append(edit, remove);
      row.append(number, copy, actions);
      list.appendChild(row);
    });
    body.appendChild(list);
  }

  function renderEditor() {
    const body = byId("taskWorkspaceBody");
    body.innerHTML = "";
    if (state.draft.items.length === 1) body.appendChild(renderDraftTitleField());
    const item = state.draft.items[state.index];
    const grid = document.createElement("div");
    grid.className = "task-workspace-grid";

    const fields = [
      ["Item title", "taskWorkspaceItemTitle", "input", String(item.title || "")],
      ["Project", "taskWorkspaceProject", "input", String(item.project || state.project || "")],
    ];
    for (const [labelText, id, kind, value] of fields) {
      const field = document.createElement("label");
      field.className = "task-workspace-field";
      const label = document.createElement("span");
      label.textContent = labelText;
      const control = document.createElement(kind);
      control.id = id;
      control.value = value;
      if (id === "taskWorkspaceProject") {
        control.readOnly = true;
        control.title = "TaskDraft stays scoped to the selected Project";
      } else {
        control.maxLength = 240;
        control.addEventListener("input", () => updateItem(state.index, "title", control.value));
      }
      field.append(label, control);
      grid.appendChild(field);
    }

    const workflowField = document.createElement("label");
    workflowField.className = "task-workspace-field";
    workflowField.innerHTML = "<span>Workflow</span>";
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
    workflow.addEventListener("change", () => updateItem(state.index, "workflow", workflow.value));
    workflowField.appendChild(workflow);

    const workspaceField = document.createElement("label");
    workspaceField.className = "task-workspace-field";
    workspaceField.innerHTML = "<span>Workspace</span>";
    const workspace = document.createElement("select");
    workspace.id = "taskWorkspaceWorkspace";
    for (const [value, label] of [["auto", "Auto"], ["main", "Main"], ["worktree", "Isolated Worktree"]]) {
      const option = document.createElement("option");
      option.value = value;
      option.textContent = label;
      workspace.appendChild(option);
    }
    workspace.value = String(item.workspace || "auto");
    workspace.addEventListener("change", () => updateItem(state.index, "workspace", workspace.value));
    workspaceField.appendChild(workspace);
    grid.append(workflowField, workspaceField);
    body.appendChild(grid);

    const promptField = document.createElement("label");
    promptField.className = "task-workspace-field task-workspace-prompt";
    promptField.innerHTML = "<span>Task prompt</span>";
    const prompt = document.createElement("textarea");
    prompt.id = "taskWorkspacePrompt";
    prompt.rows = 10;
    prompt.value = String(item.prompt || "");
    prompt.addEventListener("input", () => updateItem(state.index, "prompt", prompt.value));
    promptField.appendChild(prompt);
    body.appendChild(promptField);

    const error = document.createElement("div");
    error.id = "taskWorkspaceError";
    error.className = "task-workspace-error";
    error.hidden = !state.error;
    error.textContent = state.error || "";
    body.appendChild(error);
  }

  function renderTaskInfo() {
    const task = state.task || {};
    const body = byId("taskWorkspaceBody");
    body.innerHTML = "";

    const tabs = document.createElement("div");
    tabs.className = "task-workspace-tabs";
    for (const id of ["overview", "runtime", "output", "history"]) {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "task-workspace-tab";
      button.textContent = id.charAt(0).toUpperCase() + id.slice(1);
      button.classList.toggle("active", state.tab === id);
      button.setAttribute("aria-pressed", String(state.tab === id));
      button.onclick = () => { state.tab = id; render(); };
      tabs.appendChild(button);
    }
    body.appendChild(tabs);

    if (state.tab !== "overview") {
      const empty = document.createElement("section");
      empty.className = "task-workspace-empty-panel";
      const title = document.createElement("strong");
      title.textContent = state.tab === "runtime"
        ? "No Runner runtime yet"
        : state.tab === "output"
          ? "No Runner output yet"
          : "No run history yet";
      const copy = document.createElement("p");
      copy.textContent = "This Task is New. Runtime data appears only after an explicit Run action.";
      empty.append(title, copy);
      body.appendChild(empty);
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
      ["Project", String(task.project || "")],
      ["Type", task.kind === "task_list" ? "Task List" : "Task"],
      ["Items", String(Array.isArray(task.items) ? task.items.length : 0)],
    ]) {
      const dt = document.createElement("dt"); dt.textContent = label;
      const dd = document.createElement("dd"); dd.textContent = value;
      meta.append(dt, dd);
    }
    overview.appendChild(meta);

    const heading = document.createElement("div");
    heading.className = "task-workspace-intro";
    heading.innerHTML = "<strong>Tasks</strong><span>Canonical ordered items</span>";
    overview.appendChild(heading);

    const list = document.createElement("div");
    list.className = "task-workspace-list";
    (Array.isArray(task.items) ? task.items : []).forEach((item, index) => {
      const row = document.createElement("article");
      row.className = "task-workspace-list-row task-workspace-info-row";
      const number = document.createElement("span");
      number.className = "task-workspace-list-number";
      number.textContent = String(index + 1);
      const copy = document.createElement("div");
      copy.className = "task-workspace-list-copy";
      const title = document.createElement("strong");
      title.textContent = String(item.title || "Task " + (index + 1));
      const detail = document.createElement("small");
      detail.textContent = [String(item.workflow || "Workflow"), String(item.workspace || "auto").toUpperCase()].join(" · ");
      const prompt = document.createElement("p");
      prompt.textContent = String(item.prompt || "");
      copy.append(title, detail, prompt);
      row.append(number, copy);
      list.appendChild(row);
    });
    overview.appendChild(list);
    body.appendChild(overview);
  }

  function render() {
    if (!state || !overlay) return;
    const footer = byId("taskWorkspaceFooterBack")?.closest("footer");
    const save = byId("taskWorkspaceSave");
    const back = byId("taskWorkspaceHeaderBack");
    if (state.kind === "task") {
      if (footer) footer.hidden = true;
      if (back) back.hidden = false;
      byId("taskWorkspaceEyebrow").textContent = "TASK INFO";
      byId("taskWorkspaceTitle").textContent = String(state.task?.title || "Task");
      byId("taskWorkspaceMeta").textContent = String(state.task?.task_id || "");
      renderTaskInfo();
      return;
    }
    if (footer) footer.hidden = false;
    if (back) back.hidden = false;
    if (save) save.hidden = false;
    const listRoute = state.route === "list";
    const count = state.draft.items.length;
    byId("taskWorkspaceEyebrow").textContent = listRoute ? "TASK LIST" : "TASK EDITOR";
    byId("taskWorkspaceTitle").textContent = listRoute
      ? String(state.draft.title || "Task List")
      : String(state.draft.items[state.index]?.title || state.draft.title || "Edit Task");
    byId("taskWorkspaceMeta").textContent = listRoute
      ? count + " ordered task" + (count === 1 ? "" : "s")
      : "Task " + (state.index + 1) + " of " + count;
    byId("taskWorkspaceFooterBack").textContent = listRoute ? "Back to Chat" : (count > 1 ? "Back to Task List" : "Back to Chat");
    byId("taskWorkspaceSave").hidden = !listRoute && count > 1;
    if (listRoute) renderList(); else renderEditor();
    requestAnimationFrame(() => (listRoute ? byId("taskWorkspaceDraftTitle") : byId("taskWorkspaceItemTitle"))?.focus());
  }

  async function handleBack() {
    if (!state) return;
    if (state.kind === "task") {
      closeNow();
      return;
    }
    if (state.route === "editor" && state.draft.items.length > 1) {
      state.route = "list";
      render();
      return;
    }
    await requestClose();
  }

  async function saveDraft() {
    if (!isDraftState()) return;
    const button = byId("taskWorkspaceSave");
    button.disabled = true;
    button.setAttribute("aria-busy", "true");
    try {
      const data = await api("/api/tasks/validate-draft", {
        method: "POST",
        body: JSON.stringify({ project: state.project, draft: state.draft }),
      });
      const normalized = cloneDraft(data.draft || data);
      await state.onSave?.(normalized);
      state.draft = normalized;
      state.original = draftSignature(normalized);
      closeNow();
    } catch (error) {
      state.error = String(error?.message || "TaskDraft validation failed");
      if (state.route === "list") { state.route = "editor"; state.index = 0; }
      render();
      const errorNode = byId("taskWorkspaceError");
      if (errorNode) { errorNode.hidden = false; errorNode.textContent = state.error; }
      showError?.(error.message, "Save TaskDraft failed");
    } finally {
      if (button && document.contains(button)) {
        button.disabled = false;
        button.removeAttribute("aria-busy");
      }
    }
  }

  function openDraft({ project, draft, workflows = [], onSave, returnFocus }) {
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
      onSave,
      route: value.items.length > 1 ? "list" : "editor",
      index: 0,
      error: "",
    };
    overlay.hidden = false;
    render();
  }

  function openTask(task, { returnFocus } = {}) {
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
      tab: "overview",
    };
    overlay.hidden = false;
    render();
  }

  return { openDraft, openTask, close: requestClose };
}
