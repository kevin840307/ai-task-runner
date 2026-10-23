const FILTER_KEY = "ai-task-runner.tasks-project-filter.v1";
const LIFECYCLES = ["new", "ongoing", "paused", "closed"];

function pathKey(value) {
  const text = String(value || "").trim().replace(/\\/g, "/").replace(/\/+$/g, "");
  return (/^[A-Za-z]:\//.test(text) || text.startsWith("//")) ? text.toLowerCase() : text;
}

export function createTasksBoardController({ api, openTask, getProjects, getCurrentProject, confirmDialog, showToast, showError }) {
  let selected = new Set();
  let initialized = false;
  let tasks = [];
  let mode = "board";
  let search = "";
  let runningOnly = false;
  let refreshToken = 0;
  let draggedTaskId = "";
  const byId = (id) => document.getElementById(id);
  const requestId = (prefix) => prefix + ":" + (globalThis.crypto?.randomUUID?.() || (Date.now() + "-" + Math.random().toString(16).slice(2)));

  function projects() {
    return (Array.isArray(getProjects?.()) ? getProjects() : []).filter((row) => row && row.exists !== false && row.path);
  }

  function projectId(row) {
    return String(row?.project_id || "");
  }

  function initializeSelection() {
    if (initialized) return;
    const rows = projects();
    const valid = new Set(rows.map(projectId).filter(Boolean));
    let restored = false;
    try {
      const raw = localStorage.getItem(FILTER_KEY);
      if (raw !== null) {
        const saved = JSON.parse(raw);
        if (Array.isArray(saved)) {
          restored = true;
          for (const id of saved) if (valid.has(String(id))) selected.add(String(id));
        }
      }
    } catch (_) {}
    if (!restored) {
      const current = getCurrentProject?.();
      const currentId = projectId(rows.find((row) => pathKey(row.path) === pathKey(current?.path)));
      if (currentId) selected.add(currentId);
      else for (const row of rows) if (projectId(row)) selected.add(projectId(row));
    }
    initialized = true;
  }

  function saveSelection() {
    try { localStorage.setItem(FILTER_KEY, JSON.stringify([...selected])); } catch (_) {}
  }

  function selectedProjects() {
    initializeSelection();
    const rows = projects();
    return rows.filter((row) => selected.has(projectId(row)));
  }

  function selectedPaths() {
    return new Set(selectedProjects().map((row) => pathKey(row.path)));
  }

  function taskMatchesProjects(task) {
    const ids = selected;
    if (task?.project_id && ids.has(String(task.project_id))) return true;
    const paths = selectedPaths();
    if (paths.has(pathKey(task?.project))) return true;
    return (Array.isArray(task?.items) ? task.items : []).some((item) => paths.has(pathKey(item?.project)));
  }

  function taskMatchesSearch(task) {
    const query = search.trim().toLowerCase();
    if (!query) return true;
    const text = [
      task?.task_id, task?.title, task?._project_name,
      ...(Array.isArray(task?.items) ? task.items.flatMap((item) => [item?.title, item?.prompt, item?.workflow]) : []),
    ].join(" ").toLowerCase();
    return text.includes(query);
  }

  function taskIsRunning(task) {
    return String(task?.status || "") === "ongoing";
  }

  function visibleTasks() {
    return tasks.filter((task) => taskMatchesProjects(task) && taskMatchesSearch(task) && (!runningOnly || taskIsRunning(task)));
  }

  function renderRunningState() {
    const scoped = tasks.filter((task) => taskMatchesProjects(task) && taskMatchesSearch(task));
    const count = scoped.filter(taskIsRunning).length;
    const badge = byId("tasksRunningCount");
    const filter = byId("tasksRunningFilterButton");
    if (badge) badge.textContent = count + " Running";
    if (filter) {
      filter.textContent = runningOnly ? "顯示全部" : "只看執行中";
      filter.classList.toggle("active", runningOnly);
      filter.setAttribute("aria-pressed", String(runningOnly));
    }
  }

  function renderFilter() {
    const rows = projects();
    const options = byId("tasksProjectFilterOptions");
    const summary = byId("tasksProjectFilterSummary");
    if (!options || !summary) return;
    const validIds = new Set(rows.map(projectId).filter(Boolean));
    let changed = false;
    for (const id of [...selected]) if (!validIds.has(id)) { selected.delete(id); changed = true; }
    if (changed) saveSelection();
    options.innerHTML = "";
    for (const row of rows) {
      const id = projectId(row);
      if (!id) continue;
      const label = document.createElement("label");
      label.className = "tasks-project-option";
      const input = document.createElement("input");
      input.type = "checkbox";
      input.checked = selected.has(id);
      input.addEventListener("change", () => {
        if (input.checked) selected.add(id); else selected.delete(id);
        saveSelection();
        renderFilter();
        void refresh();
      });
      const copy = document.createElement("span");
      const strong = document.createElement("strong");
      strong.textContent = String(row.name || row.path);
      const small = document.createElement("small");
      small.textContent = String(row.path || "");
      copy.append(strong, small);
      label.append(input, copy);
      options.appendChild(label);
    }
    const chosen = rows.filter((row) => selected.has(projectId(row)));
    summary.textContent = !chosen.length ? "None" : chosen.length === rows.length ? "All" : chosen.length === 1 ? String(chosen[0].name || "1 selected") : chosen.length + " selected";
  }

  function runtimeLabel(task) {
    const phase = String(task?.run?.phase || "");
    if (String(task?.status || "") === "ongoing") return phase ? phase.replaceAll("_", " ") : "Running";
    if (String(task?.status || "") === "paused") return phase ? phase.replaceAll("_", " ") : "Stopped";
    if (String(task?.status || "") === "closed") return "Completed";
    return "Idle";
  }

  function taskCard(task) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "tasks-board-card";
    button.dataset.taskId = String(task.task_id || "");
    button.draggable = true;

    const top = document.createElement("span");
    top.className = "tasks-board-card-top";
    const handle = document.createElement("span");
    handle.className = "tasks-board-card-handle";
    handle.textContent = "⠿";
    const title = document.createElement("strong");
    title.className = "tasks-board-card-title";
    title.textContent = String(task.title || task.task_id || "Task");
    const runtime = document.createElement("span");
    runtime.className = "tasks-board-runtime " + String(task.status || "new");
    runtime.textContent = runtimeLabel(task);
    top.append(handle, title, runtime);

    const prompt = document.createElement("span");
    prompt.className = "tasks-board-card-prompt";
    prompt.textContent = String(task.items?.[0]?.prompt || task.items?.[0]?.goal_file || "");

    const meta = document.createElement("span");
    meta.className = "tasks-board-card-meta";
    const projectTag = document.createElement("span");
    projectTag.className = "tasks-board-tag";
    projectTag.textContent = String(task._project_name || "Project");
    const kindTag = document.createElement("span");
    kindTag.className = "tasks-board-tag";
    kindTag.textContent = task.kind === "task_list" ? String(task.items?.length || 0) + " tasks" : "Task";
    meta.append(projectTag, kindTag);

    const foot = document.createElement("span");
    foot.className = "tasks-board-card-foot";
    const progress = document.createElement("span");
    progress.textContent = String(task.completed_item_count || 0) + " / " + String(task.items?.length || 0);
    const id = document.createElement("span");
    id.textContent = String(task.task_id || "");
    foot.append(progress, id);

    button.append(top, prompt, meta, foot);
    button.addEventListener("click", () => {
      if (!button.classList.contains("dragging")) openTask?.(task, { returnFocus: button });
    });
    button.addEventListener("dragstart", (event) => {
      draggedTaskId = String(task.task_id || "");
      button.classList.add("dragging");
      if (event.dataTransfer) event.dataTransfer.effectAllowed = "move";
      paintDropHints(task);
    });
    button.addEventListener("dragend", () => {
      draggedTaskId = "";
      button.classList.remove("dragging");
      clearDropHints();
    });
    return button;
  }

  function boardMoveRule(task, target) {
    const from = String(task?.status || "new");
    if (!target) return { ok: false, reason: "Unknown target" };
    if (from === target) return { ok: true, action: "none" };
    if (from === "new" && target === "ongoing") return { ok: true, action: "run" };
    if (from === "ongoing" && target === "paused") return { ok: true, action: "stop" };
    if (from === "paused" && target === "ongoing") return { ok: true, action: "resume" };
    if ((from === "paused" || from === "closed") && target === "new") return { ok: true, action: "reset" };
    return { ok: false, reason: from + " → " + target + " is not a supported production lifecycle move" };
  }

  function clearDropHints() {
    document.querySelectorAll(".tasks-board-dropzone").forEach((zone) => zone.classList.remove("over", "allowed", "blocked"));
  }

  function paintDropHints(task) {
    document.querySelectorAll(".tasks-board-column").forEach((column) => {
      const zone = column.querySelector(".tasks-board-dropzone");
      if (!zone) return;
      const rule = boardMoveRule(task, column.dataset.status);
      zone.classList.toggle("allowed", rule.ok && column.dataset.status !== String(task?.status || ""));
      zone.classList.toggle("blocked", !rule.ok);
    });
  }

  async function moveTask(task, target) {
    const rule = boardMoveRule(task, target);
    if (!rule.ok) {
      showError?.(rule.reason, "Task move blocked");
      return;
    }
    if (rule.action === "none") return;
    const project = String(task?.project || "");
    const taskId = String(task?.task_id || "");
    if (!project || !taskId) return;

    if (rule.action === "reset") {
      const confirmed = await confirmDialog?.({
        title: String(task.status || "") === "closed" ? "Move completed Task back to New?" : "Move paused Task back to New?",
        message: String(task.status || "") === "closed"
          ? "Completed run history stays available. Runtime progress resets to the beginning."
          : "The resumable execution is abandoned. Task configuration stays intact and progress resets to the beginning.",
        confirmLabel: "Move to New",
        danger: true,
      });
      if (!confirmed) return;
    }

    const endpoint = {
      run: "/api/tasks/run",
      stop: "/api/tasks/stop",
      resume: "/api/tasks/resume",
      reset: "/api/tasks/reset",
    }[rule.action];
    const body = { project, task_id: taskId };
    if (rule.action === "run" || rule.action === "reset") body.request_id = requestId("board-" + rule.action);
    try {
      await api(endpoint, { method: "POST", body: JSON.stringify(body), timeoutMs: 15000 });
      showToast?.(rule.action === "stop" ? "Stop requested" : rule.action === "resume" ? "Task resumed" : rule.action === "run" ? "Task started" : "Task moved to New");
      await refresh();
    } catch (error) {
      showError?.(error?.message || String(error), "Task move failed");
    }
  }

  function renderBoard() {
    const visible = visibleTasks();
    for (const status of LIFECYCLES) {
      const zone = byId("tasksBoard" + status[0].toUpperCase() + status.slice(1));
      const count = byId("tasksBoard" + status[0].toUpperCase() + status.slice(1) + "Count");
      if (!zone) continue;
      zone.innerHTML = "";
      const rows = visible.filter((task) => String(task.status || "new") === status);
      if (count) count.textContent = String(rows.length);
      for (const task of rows) zone.appendChild(taskCard(task));
    }
    const empty = byId("tasksBoardEmpty");
    if (empty) empty.hidden = visible.length !== 0;
  }

  function renderList() {
    const root = byId("tasksListRows");
    if (!root) return;
    root.innerHTML = "";
    for (const task of visibleTasks()) {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "tasks-list-row";
      const lifecycle = document.createElement("span");
      lifecycle.className = "tasks-list-status";
      lifecycle.textContent = String(task.status || "new").toUpperCase();
      const copy = document.createElement("span");
      copy.className = "tasks-list-copy";
      const title = document.createElement("strong");
      title.textContent = String(task.title || task.task_id || "Task");
      const meta = document.createElement("small");
      meta.textContent = [String(task._project_name || ""), String(task.task_id || ""), String(task.items?.length || 0) + " item(s)"].filter(Boolean).join(" · ");
      copy.append(title, meta);
      button.append(lifecycle, copy);
      button.addEventListener("click", () => openTask?.(task, { returnFocus: button }));
      root.appendChild(button);
    }
  }

  function render() {
    renderFilter();
    renderRunningState();
    const board = byId("tasksBoardColumns");
    const list = byId("tasksListView");
    if (board) board.hidden = mode !== "board";
    if (list) list.hidden = mode !== "list";
    document.querySelectorAll("[data-tasks-view-mode]").forEach((button) => {
      const active = button.dataset.tasksViewMode === mode;
      button.classList.toggle("active", active);
      button.setAttribute("aria-pressed", String(active));
    });
    renderBoard();
    renderList();
  }

  async function refresh() {
    initializeSelection();
    renderFilter();
    const token = ++refreshToken;
    const rows = projects();
    if (!rows.length) {
      tasks = [];
      render();
      return;
    }
    const results = await Promise.allSettled(rows.map(async (project) => {
      const data = await api("/api/tasks?project=" + encodeURIComponent(project.path), { timeoutMs: 15000 });
      return (Array.isArray(data?.tasks) ? data.tasks : []).map((task) => ({
        ...task,
        _project_id: projectId(project),
        _project_name: String(project.name || project.path),
      }));
    }));
    if (token !== refreshToken) return;
    tasks = results.flatMap((result) => result.status === "fulfilled" ? result.value : []);
    const failed = results.filter((result) => result.status === "rejected");
    if (failed.length) showError?.(failed[0].reason?.message || "Task list failed", "Task Board loading failed");
    render();
  }

  function mount() {
    const searchInput = byId("tasksBoardSearch");
    if (searchInput) searchInput.addEventListener("input", () => { search = searchInput.value; render(); });
    byId("tasksRunningFilterButton")?.addEventListener("click", () => {
      runningOnly = !runningOnly;
      render();
    });
    byId("tasksNewColumnButton")?.addEventListener("click", () => byId("tasksNewButton")?.click());
    document.querySelectorAll(".tasks-board-column").forEach((column) => {
      const zone = column.querySelector(".tasks-board-dropzone");
      if (!zone) return;
      zone.addEventListener("dragover", (event) => {
        if (!draggedTaskId) return;
        const task = tasks.find((row) => String(row.task_id || "") === draggedTaskId);
        const rule = boardMoveRule(task, column.dataset.status);
        if (rule.ok) {
          event.preventDefault();
          zone.classList.add("over");
          if (event.dataTransfer) event.dataTransfer.dropEffect = "move";
        } else if (event.dataTransfer) {
          event.dataTransfer.dropEffect = "none";
        }
      });
      zone.addEventListener("dragleave", () => zone.classList.remove("over"));
      zone.addEventListener("drop", (event) => {
        event.preventDefault();
        zone.classList.remove("over");
        const task = tasks.find((row) => String(row.task_id || "") === draggedTaskId);
        draggedTaskId = "";
        clearDropHints();
        if (task) void moveTask(task, String(column.dataset.status || ""));
      });
    });
    document.querySelectorAll("[data-tasks-view-mode]").forEach((button) => button.addEventListener("click", () => {
      mode = button.dataset.tasksViewMode === "list" ? "list" : "board";
      render();
    }));
    const trigger = byId("tasksProjectFilterButton");
    const menu = byId("tasksProjectFilterMenu");
    trigger?.addEventListener("click", (event) => {
      event.stopPropagation();
      if (!menu) return;
      menu.hidden = !menu.hidden;
      trigger.setAttribute("aria-expanded", String(!menu.hidden));
    });
    byId("tasksProjectFilterAll")?.addEventListener("click", () => {
      selected = new Set(projects().map(projectId).filter(Boolean));
      saveSelection(); renderFilter(); void refresh();
    });
    byId("tasksProjectFilterClear")?.addEventListener("click", () => {
      selected.clear();
      saveSelection(); renderFilter(); void refresh();
    });
    document.addEventListener("click", (event) => {
      if (!menu || menu.hidden) return;
      if (menu.contains(event.target) || trigger?.contains(event.target)) return;
      menu.hidden = true;
      trigger?.setAttribute("aria-expanded", "false");
    });
    document.addEventListener("keydown", (event) => {
      if (event.key !== "Escape" || !menu || menu.hidden) return;
      menu.hidden = true;
      trigger?.setAttribute("aria-expanded", "false");
      trigger?.focus();
    });
  }

  mount();
  return { refresh, render };
}
