function cloneDraft(value) {
  if (globalThis.structuredClone) return globalThis.structuredClone(value);
  return JSON.parse(JSON.stringify(value));
}
function draftSignature(value) { return JSON.stringify(value || {}); }

export function createTaskWorkspaceController({ api, confirmDialog, showError, onTaskChanged }) {
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
    byId("taskWorkspaceSave").addEventListener("click", () => void saveWorkspace());
    document.addEventListener("keydown", (event) => {
      if (!overlay || overlay.hidden || event.key !== "Escape") return;
      event.preventDefault();
      event.stopPropagation();
      void requestClose();
    }, true);
    return overlay;
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

  async function requestClose() {
    if (!state) return closeNow();
    if (!(await confirmDiscardIfDirty())) return;
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

  function touchEditor() {
    if (state?.kind === "task") state.saveRequestId = "";
  }

  function updateItem(index, key, value) {
    const item = editorDraft()?.items?.[index];
    if (item) {
      item[key] = value;
      touchEditor();
    }
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
      draft.title = input.value;
      touchEditor();
    });
    wrap.append(label, input);
    return wrap;
  }

  function moveItem(index, delta) {
    const draft = editorDraft();
    const items = draft?.items;
    const next = index + delta;
    if (!Array.isArray(items) || next < 0 || next >= items.length) return;
    const [item] = items.splice(index, 1);
    items.splice(next, 0, item);
    touchEditor();
    render();
  }

  function removeItem(index) {
    const draft = editorDraft();
    const items = draft?.items;
    if (!Array.isArray(items) || items.length <= 1) return;
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
    state.route = "editor";
    state.index = index;
    render();
  }

  function renderTaskRows(items, { editable = false, onEdit = null } = {}) {
    const values = Array.isArray(items) ? items : [];
    const list = document.createElement("div");
    list.className = "task-workspace-list";
    values.forEach((item, index) => {
      const row = document.createElement("article");
      row.className = "task-workspace-list-row" + (editable ? "" : " task-workspace-info-row");
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
      row.append(number, copy);
      if (editable) {
        const actions = document.createElement("div");
        actions.className = "task-workspace-list-actions";
        for (const [label, titleText, delta] of [["↑", "Move up", -1], ["↓", "Move down", 1]]) {
          const button = document.createElement("button");
          button.type = "button";
          button.textContent = label;
          button.title = titleText;
          button.disabled = delta < 0 ? index === 0 : index === values.length - 1;
          button.onclick = () => moveItem(index, delta);
          actions.appendChild(button);
        }
        const edit = document.createElement("button");
        edit.type = "button";
        edit.className = "task-workspace-row-edit";
        edit.textContent = "Edit";
        edit.onclick = () => editItem(index);
        const remove = document.createElement("button");
        remove.type = "button";
        remove.textContent = "Remove";
        remove.disabled = values.length <= 1;
        remove.onclick = () => removeItem(index);
        actions.append(edit, remove);
        row.appendChild(actions);
      } else if (typeof onEdit === "function") {
        const actions = document.createElement("div");
        actions.className = "task-workspace-list-actions";
        const edit = document.createElement("button");
        edit.type = "button";
        edit.className = "task-workspace-durable-edit";
        edit.textContent = "Edit";
        edit.onclick = () => onEdit(index);
        actions.appendChild(edit);
        row.appendChild(actions);
      }
      list.appendChild(row);
    });
    return list;
  }

  function appendYamlAction(body) {
    const actions = document.createElement("div");
    actions.className = "task-workspace-info-actions";
    const yaml = document.createElement("button");
    yaml.id = "taskWorkspaceYamlButton";
    yaml.type = "button";
    yaml.textContent = "Edit YAML";
    yaml.onclick = () => void openYaml();
    actions.appendChild(yaml);
    body.appendChild(actions);
  }

  function renderList() {
    const body = byId("taskWorkspaceBody");
    body.innerHTML = "";
    body.appendChild(renderDraftTitleField());
    const intro = document.createElement("div");
    intro.className = "task-workspace-intro";
    intro.innerHTML = "<strong>Task order</strong><span>Tasks run top-to-bottom inside this Task List.</span>";
    body.appendChild(intro);
    body.appendChild(renderTaskRows(state.draft.items, { editable: true }));
    appendYamlAction(body);
  }

  function renderEditor() {
    const body = byId("taskWorkspaceBody");
    body.innerHTML = "";
    const draft = editorDraft();
    if (!draft || !Array.isArray(draft.items) || !draft.items.length) return;
    if (draft.items.length === 1) body.appendChild(renderDraftTitleField());
    const item = draft.items[state.index];
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
        control.title = "Task stays scoped to the selected Project";
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
    overview.appendChild(renderTaskRows(task.items));

    if (String(task.status || "") === "new") {
      const actions = document.createElement("div");
      actions.className = "task-workspace-info-actions";
      const remove = document.createElement("button");
      remove.id = "taskWorkspaceDeleteTask";
      remove.type = "button";
      remove.className = "danger";
      remove.textContent = "Delete Task";
      remove.onclick = () => void deleteTask();
      actions.appendChild(remove);
      if (Array.isArray(task.items) && task.items.length > 1) {
        const openList = document.createElement("button");
        openList.id = "taskWorkspaceOpenList";
        openList.type = "button";
        openList.textContent = "Open Task List";
        openList.onclick = () => beginTaskListEdit();
        actions.appendChild(openList);
      } else {
        const edit = document.createElement("button");
        edit.id = "taskWorkspaceEditTask";
        edit.type = "button";
        edit.textContent = "Edit Task";
        edit.onclick = () => beginTaskEdit(0, "info");
        actions.appendChild(edit);
      }
      overview.appendChild(actions);
    }
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
    if (!task || String(task.status || "") !== "new") return false;
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

  function addTaskListItem() {
    if (!ensureTaskEditDraft()) return;
    const first = state.editDraft.items[0] || {};
    const workflow = String(first.workflow || state.workflows?.[0]?.path || state.workflows?.[0]?.id || "");
    state.editDraft.items.push({
      title: "",
      prompt: "",
      workflow,
      project: String(state.task?.project || ""),
      workspace: "auto",
    });
    touchEditor();
    state.index = state.editDraft.items.length - 1;
    state.editorReturn = "list";
    state.error = "";
    state.route = "editor";
    render();
  }

  function renderDurableTaskList() {
    const task = state.task || {};
    const body = byId("taskWorkspaceBody");
    body.innerHTML = "";
    const editable = String(task.status || "") === "new" && ensureTaskEditDraft();
    if (editable) body.appendChild(renderDraftTitleField());
    const intro = document.createElement("div");
    intro.className = "task-workspace-intro";
    intro.innerHTML = editable
      ? "<strong>Task order</strong><span>Add, edit, remove or reorder before Save.</span>"
      : "<strong>Task order</strong><span>Canonical ordered items</span>";
    body.appendChild(intro);
    body.appendChild(renderTaskRows(editable ? state.editDraft.items : task.items, { editable }));

    if (editable) {
      const actions = document.createElement("div");
      actions.className = "task-workspace-info-actions";
      const add = document.createElement("button");
      add.id = "taskWorkspaceAddTask";
      add.type = "button";
      add.textContent = "+ Add task";
      add.onclick = addTaskListItem;
      const yaml = document.createElement("button");
      yaml.id = "taskWorkspaceYamlButton";
      yaml.type = "button";
      yaml.textContent = "Edit YAML";
      yaml.onclick = () => void openYaml();
      actions.append(add, yaml);
      body.appendChild(actions);
    }
    if (state.error) {
      const error = document.createElement("div");
      error.id = "taskWorkspaceError";
      error.className = "task-workspace-error";
      error.textContent = state.error;
      body.appendChild(error);
    }
  }

  async function deleteTask() {
    const task = state?.task;
    if (!task || String(task.status || "") !== "new") return;
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
    if (state?.kind === "task" && !ensureTaskEditDraft()) return;
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
        touchEditor();
      } else {
        state.draft = parsed;
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
    if (!task || String(task.status || "") !== "new" || !ensureTaskEditDraft()) return;
    state.editorReturn = returnRoute === "list" ? "list" : "info";
    state.index = Math.max(0, Math.min(Number(index) || 0, state.editDraft.items.length - 1));
    state.saveRequestId = "";
    state.error = "";
    state.route = "editor";
    render();
  }

  function render() {
    if (!state || !overlay) return;
    const footer = byId("taskWorkspaceFooterBack")?.closest("footer");
    const save = byId("taskWorkspaceSave");
    const back = byId("taskWorkspaceHeaderBack");
    if (state.kind === "task") {
      const listRoute = state.route === "list";
      const editorRoute = state.route === "editor";
      const yamlRoute = state.route === "yaml";
      if (footer) footer.hidden = !(listRoute || editorRoute || yamlRoute);
      if (save) {
        const canSaveList = listRoute && String(state.task?.status || "") === "new" && !!state.editDraft;
        save.hidden = !(editorRoute || canSaveList || yamlRoute);
        save.textContent = yamlRoute ? "Apply YAML" : (canSaveList ? "Save Task List" : "Save Task");
      }
      if (back) back.hidden = false;
      byId("taskWorkspaceEyebrow").textContent = yamlRoute ? "TASK YAML" : (editorRoute ? "TASK EDITOR" : (listRoute ? "TASK LIST" : "TASK INFO"));
      byId("taskWorkspaceTitle").textContent = yamlRoute
        ? String(state.editDraft?.title || state.task?.title || "Task YAML")
        : editorRoute
          ? String(state.editDraft?.items?.[state.index]?.title || state.task?.title || "Edit Task")
          : String(state.task?.title || "Task");
      byId("taskWorkspaceMeta").textContent = yamlRoute
        ? "Same canonical items[]"
        : editorRoute
          ? "Task " + (state.index + 1) + " of " + String(state.editDraft?.items?.length || 0)
          : listRoute
            ? String((state.editDraft?.items || state.task?.items || []).length) + " ordered tasks"
            : String(state.task?.task_id || "");
      if (yamlRoute) {
        byId("taskWorkspaceFooterBack").textContent = "Back to Task List";
        renderYaml();
      } else if (editorRoute) {
        byId("taskWorkspaceFooterBack").textContent = state.editorReturn === "list" ? "Back to Task List" : "Back to Info";
        renderEditor();
        requestAnimationFrame(() => byId("taskWorkspaceItemTitle")?.focus());
      } else if (listRoute) {
        byId("taskWorkspaceFooterBack").textContent = "Back to Info";
        renderDurableTaskList();
      } else {
        renderTaskInfo();
      }
      return;
    }
    if (footer) footer.hidden = false;
    if (back) back.hidden = false;
    if (save) save.hidden = false;
    const listRoute = state.route === "list";
    const yamlRoute = state.route === "yaml";
    const count = state.draft.items.length;
    byId("taskWorkspaceEyebrow").textContent = yamlRoute ? "TASK YAML" : (listRoute ? "TASK LIST" : "TASK EDITOR");
    byId("taskWorkspaceTitle").textContent = yamlRoute
      ? String(state.draft.title || "Task YAML")
      : listRoute
        ? String(state.draft.title || "Task List")
        : String(state.draft.items[state.index]?.title || state.draft.title || "Edit Task");
    byId("taskWorkspaceMeta").textContent = yamlRoute
      ? "Same canonical items[]"
      : listRoute
        ? count + " ordered task" + (count === 1 ? "" : "s")
        : "Task " + (state.index + 1) + " of " + count;
    byId("taskWorkspaceFooterBack").textContent = yamlRoute ? "Back to Task List" : (listRoute ? "Back to Chat" : (count > 1 ? "Back to Task List" : "Back to Chat"));
    byId("taskWorkspaceSave").hidden = !yamlRoute && !listRoute && count > 1;
    byId("taskWorkspaceSave").textContent = yamlRoute ? "Apply YAML" : "Save draft";
    if (yamlRoute) renderYaml(); else if (listRoute) renderList(); else renderEditor();
    if (!yamlRoute) requestAnimationFrame(() => (listRoute ? byId("taskWorkspaceDraftTitle") : byId("taskWorkspaceItemTitle"))?.focus());
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
      state.route = "list";
      render();
      return;
    }
    await requestClose();
  }

  async function saveWorkspace() {
    if (state?.route === "yaml") return applyYaml();
    if (state?.kind === "task") return saveTaskEdit();
    return saveDraft();
  }

  async function saveTaskEdit() {
    if (state?.kind !== "task" || !["list", "editor"].includes(state.route) || !state.editDraft) return;
    const button = byId("taskWorkspaceSave");
    button.disabled = true;
    button.setAttribute("aria-busy", "true");
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
      state.editDraft = null;
      state.editOriginal = "";
      state.saveRequestId = "";
      state.route = returnRoute === "list" && state.task.items.length > 1 ? "list" : "info";
      if (state.route === "list" && String(state.task.status || "") === "new") {
        state.editDraft = taskDraftFromRecord(state.task);
        state.editOriginal = draftSignature(state.editDraft);
      }
      state.tab = "overview";
      state.error = "";
      render();
    } catch (error) {
      state.error = String(error?.message || "Task save failed");
      render();
      const errorNode = byId("taskWorkspaceError");
      if (errorNode) {
        errorNode.hidden = false;
        errorNode.textContent = state.error;
      }
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
      yamlText: "",
      yamlOriginal: "",
      yamlReturn: "list",
    };
    overlay.hidden = false;
    render();
  }

  function openTask(task, { returnFocus, workflows = [] } = {}) {
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
    overlay.hidden = false;
    render();
  }

  return { openDraft, openTask, close: requestClose };
}
