const FILTER_KEY = "ai-task-runner.tasks-project-filter.v1";
const LIFECYCLES = ["new", "ongoing", "paused", "closed"];

function pathKey(value) {
  const text = String(value || "").trim().replace(/\\/g, "/").replace(/\/+$/g, "");
  return (/^[A-Za-z]:\//.test(text) || text.startsWith("//")) ? text.toLowerCase() : text;
}

export function createTasksBoardController({ api, openTask, getProjects, getCurrentProject, showError }) {
  let selected = new Set();
  let initialized = false;
  let tasks = [];
  let mode = "board";
  let search = "";
  let runningOnly = false;
  let refreshToken = 0;
  const byId = (id) => document.getElementById(id);

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

  function taskCard(task) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "tasks-board-card";
    button.dataset.taskId = String(task.task_id || "");
    const head = document.createElement("span");
    head.className = "tasks-board-card-head";
    const title = document.createElement("strong");
    title.textContent = String(task.title || task.task_id || "Task");
    const badge = document.createElement("span");
    badge.className = "tasks-board-kind";
    badge.textContent = task.kind === "task_list" ? String(task.items?.length || 0) + " tasks" : "Task";
    head.append(title, badge);
    const meta = document.createElement("small");
    meta.textContent = [String(task._project_name || ""), String(task.task_id || "")].filter(Boolean).join(" · ");
    const prompt = document.createElement("span");
    prompt.className = "tasks-board-card-prompt";
    prompt.textContent = String(task.items?.[0]?.prompt || task.items?.[0]?.goal_file || "");
    button.append(head, meta, prompt);
    button.addEventListener("click", () => openTask?.(task, { returnFocus: button }));
    return button;
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
