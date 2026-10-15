const element = (id) => document.getElementById(id);
let currentChat = null;
let chats = [];
let projects = [];
let currentTasks = [];
let currentTasksMeta = {total: 0, returned: 0, has_more: false};
let taskVisibleLimit = 100;
let currentTask = null;
let taskFilter = "all";
let activeTab = "chat";
let workflowChoices = [];
let taskBackendCatalog = {backends: [], models: {}, default: ""};
let taskGoalFile = "";
const taskListRawByRow = new WeakMap();
let draggedTaskListRow = null;
let taskModalReturnFocus = null;

async function request(url, payload) {
  const options = payload === undefined ? {} : {
    method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(payload)
  };
  const response = await fetch(url, options);
  let data = {};
  try { data = await response.json(); } catch (_) {}
  if (!response.ok || data.error) throw new Error(data.error || "Request failed");
  return data;
}
function report(error) { element("chatError").textContent = error?.message || String(error); }
function clearError() { element("chatError").textContent = ""; }
function syncWorkspaceUrl() {
  const params = new URLSearchParams();
  if (currentChat?.chat_id) params.set("chat", currentChat.chat_id);
  if (activeTab !== "chat") params.set("tab", activeTab);
  if (currentTask?.task_id) params.set("task", currentTask.task_id);
  const query = params.toString();
  history.replaceState({}, "", location.pathname + (query ? "?" + query : ""));
}
function initialWorkspaceRoute() {
  const params = new URLSearchParams(location.search);
  return {
    chat: params.get("chat") || "",
    tab: params.get("tab") === "tasks" ? "tasks" : "chat",
    task: params.get("task") || "",
  };
}

function statusText(task) {
  const runtime = task.runtime || {};
  return String(runtime.status || task.last_status || "pending").replaceAll("_", " ");
}
function relativeAge(timestamp) {
  const value = Number(timestamp || 0);
  if (!value) return "";
  const seconds = Math.max(0, Math.round(Date.now() / 1000 - value));
  if (seconds < 60) return seconds + "s ago";
  if (seconds < 3600) return Math.floor(seconds / 60) + "m ago";
  if (seconds < 86400) return Math.floor(seconds / 3600) + "h ago";
  return Math.floor(seconds / 86400) + "d ago";
}

function elapsedText(task) {
  const latest = (task.executions || []).at(-1) || {};
  const started = Number(latest.started_at || 0);
  if (!started) return "";
  const active = ["running", "recovering", "launching", "stopping"].some(value => statusText(task).toLowerCase().includes(value));
  if (!active) return "";
  const seconds = Math.max(0, Math.round(Date.now() / 1000 - started));
  if (seconds < 60) return seconds + "s elapsed";
  if (seconds < 3600) return Math.floor(seconds / 60) + "m elapsed";
  return Math.floor(seconds / 3600) + "h elapsed";
}

function taskMatchesFilter(task) {
  const status = statusText(task).toLowerCase();
  if (taskFilter === "active") return ["running", "recovering", "launching", "stopping"].some(v => status.includes(v));
  if (taskFilter === "attention") return status.includes("attention") || status.includes("error") || status.includes("unavailable");
  if (taskFilter === "completed") return status.includes("completed");
  return true;
}
function setTab(tab) {
  activeTab = tab;
  const tasks = tab === "tasks";
  element("chatTab").setAttribute("aria-selected", String(!tasks));
  element("tasksTab").setAttribute("aria-selected", String(tasks));
  element("conversationPanel").hidden = tasks;
  element("tasksPanel").hidden = !tasks;
  if (tasks) loadTasks().catch(report);
  syncWorkspaceUrl();
}
function taskBadgeCounts(allTasks) {
  const map = new Map();
  for (const task of allTasks) {
    const row = map.get(task.chat_id) || {active: 0, attention: 0};
    const status = statusText(task).toLowerCase();
    if (["running", "recovering", "launching", "stopping"].some(v => status.includes(v))) row.active += 1;
    if (status.includes("attention") || status.includes("unavailable") || status.includes("error")) row.attention += 1;
    map.set(task.chat_id, row);
  }
  return map;
}
async function selectChat(id) {
  currentChat = chats.find(chat => chat.chat_id === id) || null;
  currentTask = null;
  element("chatTitle").textContent = currentChat?.title || "Select or create a Chat";
  element("chatPath").textContent = currentChat?.root_path || "";
  const writable = Boolean(currentChat?.path_available && !currentChat?.archived);
  element("chatText").disabled = !writable;
  element("chatSend").disabled = !writable;
  element("newTask").disabled = !writable || Boolean(currentChat?.archived);
  element("archiveChat").disabled = !currentChat;
  element("copyChatPath").disabled = !currentChat?.root_path;
  element("archiveChat").textContent = currentChat?.archived ? "Restore Chat" : "Archive Chat";
  element("chatNotice").textContent = currentChat && !writable
    ? "Path unavailable · Chat and Task history remain readable; new work is disabled."
    : currentChat?.archived
      ? "Archived · history is retained. Restore this Chat before starting new work."
      : "Chat is read-only with project access. Use Tasks for file changes, execution, validation, and long-running work.";
  for (const button of element("chatList").querySelectorAll("button[data-id]")) {
    button.dataset.active = String(button.dataset.id === id);
  }
  taskVisibleLimit = 100;
  await loadMessages();
  if (activeTab === "tasks") await loadTasks();
  else { currentTasks = []; currentTasksMeta = {total: 0, returned: 0, has_more: false}; renderTasks(); }
  syncWorkspaceUrl();
}
async function loadMessages() {
  const container = element("chatMessages");
  container.replaceChildren();
  if (!currentChat) return;
  const id = currentChat.chat_id;
  try {
    const result = await request("/api/chats/messages?chat_id=" + encodeURIComponent(id));
    if (id !== currentChat?.chat_id) return;
    for (const message of result.messages) {
      const bubble = document.createElement("article");
      bubble.className = "chat-bubble";
      const body = document.createElement("div");
      body.textContent = message.text;
      bubble.append(body);
      if (message.role === "user" && currentChat.path_available && !currentChat.archived) {
        const actions = document.createElement("div");
        actions.className = "chat-bubble-actions";
        const create = document.createElement("button");
        create.type = "button";
        create.textContent = "Create Task";
        create.addEventListener("click", () => openTaskModal(message.text, message.message_id || ""));
        const createList = document.createElement("button");
        createList.type = "button";
        createList.textContent = "Create Task List";
        createList.addEventListener("click", () => openSuggestedTaskList(message.text, message.message_id || ""));
        actions.append(create, createList);
        bubble.append(actions);
      }
      container.append(bubble);
    }
    container.scrollTop = container.scrollHeight;
  } catch (error) { report(error); }
}
function renderAttention(tasks) {
  const root = element("attentionList");
  root.replaceChildren();
  const attention = (tasks || []).filter(task => {
    const status = statusText(task).toLowerCase();
    return status.includes("attention") || status.includes("error") || status.includes("unavailable");
  }).slice(0, 5);
  if (!attention.length) {
    const empty = document.createElement("small");
    empty.className = "chat-meta";
    empty.textContent = "Nothing needs attention.";
    root.append(empty);
    return;
  }
  for (const task of attention) {
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = (task.title || "Task") + " · " + statusText(task);
    button.addEventListener("click", async () => {
      element("showArchivedChats").checked = true;
      await loadChats(false);
      await selectChat(task.chat_id);
      setTab("tasks");
      await openTask(task.task_id);
    });
    root.append(button);
  }
}

async function loadChats(keepSelection = true) {
  clearError();
  const [data, taskData] = await Promise.all([request("/api/chats"), request("/api/tasks?attention=1&limit=10")]);
  chats = data.chats;
  renderAttention(taskData.tasks || []);
  const badges = taskBadgeCounts(taskData.tasks || []);
  const selectedProject = element("chatProject").value;
  const list = element("chatList");
  list.replaceChildren();
  const showArchived = element("showArchivedChats").checked;
  for (const chat of chats.filter(item =>
    (!selectedProject || item.root_path === selectedProject)
    && (showArchived || !item.archived)
  )) {
    const button = document.createElement("button");
    button.type = "button";
    button.dataset.id = chat.chat_id;
    const badge = badges.get(chat.chat_id);
    const suffix = !chat.path_available ? " · Path unavailable"
      : badge?.attention ? ` · Needs Attention ${badge.attention}`
      : badge?.active ? ` · Running ${badge.active}` : "";
    button.textContent = chat.title + (chat.archived ? " · Archived" : "") + suffix;
    button.addEventListener("click", () => selectChat(chat.chat_id).catch(report));
    list.append(button);
  }
  const selectedId = keepSelection ? currentChat?.chat_id : null;
  await selectChat(selectedId && [...list.children].some(button => button.dataset.id === selectedId) ? selectedId : "");
}
async function loadProjects() {
  const data = await request("/api/projects");
  projects = data.projects || [];
  const selector = element("chatProject");
  for (const project of projects) {
    const option = document.createElement("option");
    option.value = project.path;
    option.textContent = project.name + (project.exists ? "" : " · Path unavailable");
    option.disabled = !project.exists;
    selector.append(option);
  }
}
function fillWorkflowSelect(select, { inherited = false } = {}) {
  const previous = select.value;
  select.replaceChildren();
  const fallback = document.createElement("option");
  fallback.value = "";
  fallback.textContent = inherited ? "Inherited" : "Use default Workflow";
  select.append(fallback);
  for (const workflow of workflowChoices) {
    const option = document.createElement("option");
    option.value = workflow.path;
    option.textContent = `${workflow.name} · ${workflow.group || workflow.scope || "Workflow"}`;
    select.append(option);
  }
  if (previous && ![...select.options].some(option => option.value === previous)) {
    const preserved = document.createElement("option");
    preserved.value = previous;
    preserved.textContent = "YAML override · " + previous.replaceAll("\\", "/").split("/").pop();
    select.append(preserved);
  }
  if ([...select.options].some(option => option.value === previous)) select.value = previous;
}
async function loadWorkflowOptions() {
  workflowChoices = [];
  fillWorkflowSelect(element("taskWorkflow"));
  if (!currentChat?.path_available) return;
  try {
    const data = await request("/api/studio/files?x=1&project=" + encodeURIComponent(currentChat.root_path));
    workflowChoices = (data.workflows || []).filter(item => !item.hidden);
    fillWorkflowSelect(element("taskWorkflow"));
    for (const select of element("taskListItems").querySelectorAll("select")) fillWorkflowSelect(select, {inherited: true});
  } catch (error) { report(error); }
}
function rawInstruction(raw) {
  if (!raw || typeof raw !== "object") return "";
  return String(raw.prompt || raw.goal || (raw.goal_file ? "Use file: " + raw.goal_file : ""));
}
function cloneRaw(raw) {
  return raw && typeof raw === "object" ? JSON.parse(JSON.stringify(raw)) : {};
}
function addTaskListItem(value = "", workflow = "", index = null, raw = null) {
  const row = document.createElement("div");
  row.className = "task-list-item";
  row.draggable = true;
  row.addEventListener("dragstart", () => { draggedTaskListRow = row; row.dataset.dragging = "true"; });
  row.addEventListener("dragend", () => { draggedTaskListRow = null; delete row.dataset.dragging; });
  row.addEventListener("dragover", event => event.preventDefault());
  row.addEventListener("drop", event => {
    event.preventDefault();
    if (!draggedTaskListRow || draggedTaskListRow === row) return;
    const rect = row.getBoundingClientRect();
    if (event.clientY < rect.top + rect.height / 2) row.before(draggedTaskListRow);
    else row.after(draggedTaskListRow);
  });
  const text = document.createElement("textarea");
  text.maxLength = 20000;
  text.required = true;
  text.placeholder = "Instruction / Prompt";
  const rawValue = cloneRaw(raw);
  const shown = value || rawInstruction(rawValue);
  text.value = shown;
  row.dataset.originalInstruction = shown;
  text.addEventListener("keydown", event => {
    if (event.key !== "Enter" || event.shiftKey || element("taskType").value !== "sequential") return;
    event.preventDefault();
    const next = addTaskListItem("", "", [...row.parentElement.children].indexOf(row) + 1);
    next.querySelector("textarea").focus();
  });
  const override = document.createElement("select");
  override.setAttribute("aria-label", "Workflow override");
  fillWorkflowSelect(override, {inherited: true});
  const originalWorkflow = workflow || String(rawValue.workflow_file || "");
  if (originalWorkflow && ![...override.options].some(option => option.value === originalWorkflow)) {
    const preserved = document.createElement("option");
    preserved.value = originalWorkflow;
    preserved.textContent = "YAML override · " + originalWorkflow.replaceAll("\\", "/").split("/").pop();
    override.append(preserved);
  }
  override.value = originalWorkflow;
  row.dataset.originalWorkflow = originalWorkflow;
  taskListRawByRow.set(row, rawValue);
  const controls = document.createElement("div");
  controls.className = "move-buttons";
  const up = document.createElement("button"); up.type = "button"; up.textContent = "↑"; up.title = "Move up";
  const down = document.createElement("button"); down.type = "button"; down.textContent = "↓"; down.title = "Move down";
  const file = document.createElement("button"); file.type = "button"; file.textContent = "File"; file.title = "Use goal file";
  const duplicate = document.createElement("button"); duplicate.type = "button"; duplicate.textContent = "⧉"; duplicate.title = "Duplicate";
  const remove = document.createElement("button"); remove.type = "button"; remove.textContent = "×"; remove.title = "Remove";
  file.addEventListener("click", async () => {
    if (!currentChat?.path_available) return;
    try {
      const picked = await request("/api/files/pick", {kind: "file", project: currentChat.root_path, current: ""});
      if (picked.cancelled || !picked.path) return;
      const nextRaw = cloneRaw(taskListRawByRow.get(row));
      delete nextRaw.prompt;
      delete nextRaw.goal;
      nextRaw.goal_file = picked.path;
      taskListRawByRow.set(row, nextRaw);
      text.value = "Use file: " + picked.path;
      row.dataset.originalInstruction = text.value;
    } catch (error) { report(error); }
  });
  up.addEventListener("click", () => row.previousElementSibling?.before(row));
  down.addEventListener("click", () => row.nextElementSibling?.after(row));
  duplicate.addEventListener("click", () => addTaskListItem(text.value, override.value, [...row.parentElement.children].indexOf(row) + 1, cloneRaw(taskListRawByRow.get(row))));
  remove.addEventListener("click", () => { if (row.parentElement.children.length > 1) row.remove(); });
  controls.append(up, down, file, duplicate, remove);
  row.append(text, override, controls);
  const root = element("taskListItems");
  if (index === null || index >= root.children.length) root.append(row);
  else root.insertBefore(row, root.children[index]);
  return row;
}
function taskListItemsPayload() {
  return [...element("taskListItems").querySelectorAll(".task-list-item")].map(row => {
    const text = row.querySelector("textarea").value.trim();
    const override = row.querySelector("select").value;
    const raw = cloneRaw(taskListRawByRow.get(row));
    if (Object.keys(raw).length) {
      if (text !== row.dataset.originalInstruction) {
        delete raw.goal;
        delete raw.goal_file;
        raw.prompt = text;
      }
      if (override !== row.dataset.originalWorkflow) {
        delete raw.workflow;
        delete raw.workflow_file;
        if (override) raw.workflow_file = override;
      }
    }
    return {instruction: text, workflow: override, raw};
  });
}
function renderRawTaskList(rawItems) {
  const root = element("taskListItems");
  root.replaceChildren();
  for (const raw of rawItems || []) addTaskListItem(rawInstruction(raw), String(raw?.workflow_file || ""), null, raw);
  if (!root.children.length) addTaskListItem();
}
async function refreshTaskListYaml() {
  if (!currentChat) return;
  element("taskListYamlStatus").textContent = "Validating…";
  try {
    const data = await request("/api/tasks/list/export", {
      chat_id: currentChat.chat_id,
      items: taskListItemsPayload(),
      workflow: element("taskWorkflow").value
    });
    element("taskListYaml").value = data.canonical || "";
    element("taskListYamlStatus").textContent = "Valid YAML · advanced fields preserved";
  } catch (error) {
    element("taskListYamlStatus").textContent = error.message;
    report(error);
  }
}
async function applyTaskListYaml() {
  if (!currentChat) return;
  element("taskListYamlStatus").textContent = "Validating…";
  try {
    const data = await request("/api/tasks/list/parse", {
      chat_id: currentChat.chat_id,
      content: element("taskListYaml").value,
      workflow: element("taskWorkflow").value
    });
    renderRawTaskList(data.raw || []);
    element("taskListYaml").value = data.canonical || element("taskListYaml").value;
    element("taskListYamlStatus").textContent = "Applied · visual edits will preserve untouched YAML fields";
  } catch (error) {
    element("taskListYamlStatus").textContent = error.message;
    report(error);
  }
}
function setTaskType(type) {
  const sequential = type === "sequential";
  element("singleInstructionRow").hidden = sequential;
  element("taskListEditor").hidden = !sequential;
  element("taskInstruction").required = !sequential && !taskGoalFile;
  element("taskUseFile").hidden = sequential;
  element("taskClearFile").hidden = sequential || !taskGoalFile;
  element("taskRun").textContent = sequential ? "Run List" : "Run Task";
  if (sequential && !element("taskListItems").children.length) addTaskListItem();
}
function renderTaskModels() {
  const backend = element("taskBackend").value;
  const model = element("taskModel");
  model.replaceChildren();
  const fallback = document.createElement("option");
  fallback.value = "";
  fallback.textContent = backend ? "Backend default model" : "Select Backend first";
  model.append(fallback);
  for (const value of (taskBackendCatalog.models?.[backend] || [])) {
    const option = document.createElement("option");
    option.value = String(value);
    option.textContent = String(value);
    model.append(option);
  }
  model.disabled = !backend;
}
async function loadTaskBackends() {
  const backend = element("taskBackend");
  backend.replaceChildren();
  const fallback = document.createElement("option");
  fallback.value = "";
  fallback.textContent = "Default backend";
  backend.append(fallback);
  element("taskModel").replaceChildren();
  element("taskModel").disabled = true;
  if (!currentChat?.path_available) return;
  try {
    const data = await request("/api/backends?models=1&project=" + encodeURIComponent(currentChat.root_path));
    taskBackendCatalog = {
      backends: Array.isArray(data.backends) ? data.backends : [],
      models: data.models && typeof data.models === "object" ? data.models : {},
      default: String(data.default || "")
    };
    fallback.textContent = taskBackendCatalog.default ? "Default · " + taskBackendCatalog.default : "Default backend";
    for (const name of taskBackendCatalog.backends) {
      const option = document.createElement("option");
      option.value = String(name);
      option.textContent = String(name);
      backend.append(option);
    }
    renderTaskModels();
  } catch (error) {
    taskBackendCatalog = {backends: [], models: {}, default: ""};
    report(error);
  }
}

async function loadTaskWorkspaces() {
  const select = element("taskWorkspace");
  select.replaceChildren();
  const main = document.createElement("option");
  main.value = "main";
  main.textContent = "Main";
  select.append(main);
  element("taskWorkspaceRow").hidden = true;
  if (!currentChat?.path_available) return;
  try {
    const data = await request("/api/workspaces?chat_id=" + encodeURIComponent(currentChat.chat_id));
    const mainWorkspace = (data.workspaces || []).find(workspace => workspace.is_main);
    if (mainWorkspace) {
      main.dataset.busy = String(Boolean(mainWorkspace.busy));
      main.dataset.ownerTaskId = mainWorkspace.owner_task_id || "";
      main.dataset.ownerChatId = mainWorkspace.owner_chat_id || "";
      main.textContent = mainWorkspace.busy
        ? "Main · Busy" + (mainWorkspace.owner_title ? " · " + mainWorkspace.owner_title : "")
        : "Main · Available";
    }
    if (data.git_available) {
      element("taskWorkspaceRow").hidden = false;
      const fresh = document.createElement("option");
      fresh.value = "new";
      fresh.textContent = "New Worktree · Available";
      select.append(fresh);
      for (const workspace of data.workspaces || []) {
        if (workspace.is_main) continue;
        const option = document.createElement("option");
        option.value = "existing:" + workspace.path;
        option.dataset.busy = String(Boolean(workspace.busy));
        option.dataset.ownerTaskId = workspace.owner_task_id || "";
        option.dataset.ownerChatId = workspace.owner_chat_id || "";
        option.disabled = Boolean(workspace.busy);
        option.textContent = "Existing · " + (workspace.branch || workspace.path)
          + (workspace.busy ? " · Busy" + (workspace.owner_title ? " · " + workspace.owner_title : "") : " · Available");
        select.append(option);
      }
      element("taskWorkspaceHint").textContent = "Main or an isolated Git worktree. Busy paths cannot start another Task; Task never merges branches.";
    } else {
      element("taskWorkspaceHint").textContent = main.dataset.busy === "true"
        ? "Main · Busy. Stop the owning Task first."
        : "Main · Available";
    }
  } catch (error) {
    element("taskWorkspaceHint").textContent = "Workspace discovery unavailable; backend ownership guard still applies.";
    report(error);
  }
}
function selectedTaskWorkspace() {
  const value = element("taskWorkspace").value || "main";
  if (value === "new") return {workspace_mode: "new", workspace_path: ""};
  if (value.startsWith("existing:")) return {workspace_mode: "existing", workspace_path: value.slice("existing:".length)};
  return {workspace_mode: "main", workspace_path: ""};
}

function updateSelectedWorkspaceAvailability() {
  const option = element("taskWorkspace").selectedOptions[0];
  const busy = option?.dataset.busy === "true";
  const isNew = option?.value === "new";
  element("mainAvailability").textContent = busy
    ? "Selected path · Busy"
    : isNew ? "New Worktree · Available" : "Selected path · Available";
  element("taskRun").disabled = busy;
  element("openOwningTask").hidden = !(busy && option?.dataset.ownerTaskId);
  element("openOwningTask").dataset.taskId = option?.dataset.ownerTaskId || "";
  element("openOwningTask").dataset.chatId = option?.dataset.ownerChatId || "";
  if (busy && option?.dataset.ownerTaskId) {
    element("taskWorkspaceHint").textContent = "Busy path is owned by another active Task. Open that Task or choose New Worktree.";
  }
}
async function openTaskModal(prefill = "", sourceMessageId = "") {
  if (!currentChat?.path_available || currentChat?.archived) return;
  taskModalReturnFocus = document.activeElement;
  element("taskType").value = "single";
  setTaskType("single");
  taskGoalFile = "";
  element("taskInstruction").value = prefill;
  element("taskInstruction").disabled = false;
  element("taskInstruction").required = true;
  element("taskGoalFileName").textContent = "";
  element("taskClearFile").hidden = true;
  element("taskTitle").value = "";
  element("taskListItems").replaceChildren();
  element("taskListYaml").value = "";
  element("taskListYamlStatus").textContent = "";
  element("taskListYamlPanel").hidden = true;
  element("taskListYamlToggle").setAttribute("aria-expanded", "false");
  addTaskListItem(prefill);
  element("taskForm").dataset.sourceMessageId = sourceMessageId;
  element("taskModal").hidden = false;
  await Promise.all([loadWorkflowOptions(), loadTaskBackends()]);
  await loadTaskWorkspaces();
  updateSelectedWorkspaceAvailability();
  element("taskInstruction").focus();
}
async function openSuggestedTaskList(requestText, sourceMessageId = "") {
  await openTaskModal("", sourceMessageId);
  element("taskType").value = "sequential";
  setTaskType("sequential");
  element("taskListItems").replaceChildren();
  addTaskListItem("Generating Task List preview…");
  element("taskRun").disabled = true;
  element("taskListYamlStatus").textContent = "AI is preparing an ordered preview. Nothing is running yet.";
  try {
    const data = await request("/api/chats/task-list/suggest", {
      chat_id: currentChat.chat_id,
      request: requestText
    });
    element("taskListItems").replaceChildren();
    for (const item of data.items || []) addTaskListItem(item.instruction || "");
    if (!element("taskListItems").children.length) addTaskListItem(requestText);
    element("taskListYamlStatus").textContent = "Preview ready · review/reorder before Run List.";
    await refreshTaskListYaml();
  } catch (error) {
    element("taskListItems").replaceChildren();
    addTaskListItem(requestText);
    element("taskListYamlStatus").textContent = "AI preview failed; using the source message as one item.";
    report(error);
  } finally {
    element("taskRun").disabled = false;
  }
}

function closeTaskModal() {
  element("taskModal").hidden = true;
  element("taskForm").dataset.sourceMessageId = "";
  if (taskModalReturnFocus && typeof taskModalReturnFocus.focus === "function") taskModalReturnFocus.focus();
  taskModalReturnFocus = null;
}
function renderTasks() {
  const list = element("taskList");
  list.replaceChildren();
  const visible = currentTasks.filter(taskMatchesFilter);
  element("taskCount").textContent = currentTasks.length ? `(${currentTasks.length})` : "";
  if (!visible.length) {
    const empty = document.createElement("div");
    empty.className = "task-empty";
    empty.textContent = currentTasks.length ? "No Tasks match this filter." : "No Tasks yet. Create a Task from this Chat.";
    list.append(empty);
    return;
  }
  for (const task of visible) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "task-card";
    const title = document.createElement("strong");
    title.textContent = task.title || "Task";
    const status = document.createElement("small");
    const runtime = task.runtime || {};
    const progress = task.task_type === "sequential" && runtime.script_total
      ? ` · Item ${runtime.script_index || 0}/${runtime.script_total}`
      : runtime.total ? ` · ${runtime.completed_count || 0}/${runtime.total}` : "";
    const stage = runtime.stage ? ` · ${runtime.stage}` : "";
    status.textContent = `${statusText(task)}${stage}${progress}`;
    const meta = document.createElement("small");
    const kind = task.task_type === "sequential" ? "Task List" : "Task";
    const freshness = relativeAge(task.updated_at || task.created_at);
    const elapsed = elapsedText(task);
    meta.textContent = kind + (elapsed ? " · " + elapsed : "") + (freshness ? " · " + freshness : "");
    button.append(title, status, meta);
    button.addEventListener("click", () => openTask(task.task_id).catch(report));
    list.append(button);
  }
  if (currentTasksMeta.has_more) {
    const more = document.createElement("button");
    more.type = "button";
    more.className = "history-more";
    more.textContent = `Load older Tasks (${Math.max(0, Number(currentTasksMeta.total || 0) - currentTasks.length)} remaining)`;
    more.addEventListener("click", async () => {
      taskVisibleLimit = Math.min(500, taskVisibleLimit + 100);
      await loadTasks({preserveDetail: true});
    });
    list.append(more);
  }
}
async function loadTasks({preserveDetail = false} = {}) {
  const openTaskId = preserveDetail ? currentTask?.task_id || "" : "";
  if (!preserveDetail) {
    currentTask = null;
    element("taskDetail").hidden = true;
  }
  if (!currentChat) {
    currentTasks = [];
    currentTasksMeta = {total: 0, returned: 0, has_more: false};
    renderTasks();
    return;
  }
  const id = currentChat.chat_id;
  const data = await request(
    "/api/tasks?chat_id=" + encodeURIComponent(id) + "&limit=" + encodeURIComponent(taskVisibleLimit)
  );
  if (id !== currentChat?.chat_id) return;
  currentTasks = data.tasks || [];
  currentTasksMeta = data.meta || {total: currentTasks.length, returned: currentTasks.length, has_more: false};
  renderTasks();
  if (openTaskId) {
    try { await openTask(openTaskId); }
    catch (error) { report(error); }
  }
}
function addDetailLine(root, label, value) {
  if (value === undefined || value === null || value === "") return;
  const line = document.createElement("p");
  const strong = document.createElement("strong");
  strong.textContent = label + ": ";
  line.append(strong, document.createTextNode(String(value)));
  root.append(line);
}
function makeAction(label, action, secondary = false) {
  const button = document.createElement("button");
  button.type = "button";
  button.textContent = label;
  if (secondary) button.className = "secondary";
  if (label === "Stop") button.classList.add("danger");
  button.addEventListener("click", async () => {
    clearError();
    try {
      await request("/api/tasks/action", {task_id: currentTask.task_id, action});
      await refreshOpenTask();
    } catch (error) { report(error); }
  });
  return button;
}
async function refreshOpenTask() {
  if (!currentTask) return;
  await loadTasks({preserveDetail: true});
}
async function openTask(taskId) {
  const task = await request("/api/task?task_id=" + encodeURIComponent(taskId));
  currentTask = task;
  syncWorkspaceUrl();
  const root = element("taskDetail");
  root.replaceChildren();
  root.hidden = false;
  const head = document.createElement("div");
  head.className = "task-detail-head";
  const title = document.createElement("h3");
  title.textContent = task.title || "Task";
  const state = document.createElement("strong");
  state.textContent = statusText(task);
  head.append(title, state);
  root.append(head);
  addDetailLine(root, "Workspace", task.root_path);
  addDetailLine(root, "Workspace type", task.workspace_kind || "main");
  addDetailLine(root, "Branch", task.workspace_branch);
  addDetailLine(root, "Workflow", task.workflow || "Runner default");
  if (task.runtime) {
    addDetailLine(root, "Stage", task.runtime.stage);
    addDetailLine(root, "Cycle", task.runtime.cycle);
    if (task.runtime.total) addDetailLine(root, "Progress", `${task.runtime.completed_count || 0}/${task.runtime.total}`);
    addDetailLine(root, "Attention", task.runtime.attention_reason);
  } else {
    addDetailLine(root, "Last error", task.last_error);
  }
  if (task.task_type === "sequential") {
    const latestExecution = (task.executions || []).at(-1) || {};
    const childEvidence = new Map((latestExecution.children || []).map(child => [Number(child.index), child]));
    const childDetail = document.createElement("article");
    childDetail.className = "task-detail";
    childDetail.hidden = true;
    const listTitle = document.createElement("h4");
    listTitle.textContent = "Ordered Task List";
    root.append(listTitle);
    const ordered = document.createElement("div");
    ordered.className = "task-history";
    const currentIndex = Number(task.runtime?.script_index || 0);
    const allCompleted = Boolean(task.runtime?.completed) || statusText(task).toLowerCase().includes("completed");
    (task.items || []).forEach((item, index) => {
      const row = document.createElement("article");
      const number = index + 1;
      const state = allCompleted || (currentIndex && number < currentIndex)
        ? "Completed"
        : currentIndex === number ? `${statusText(task)}${task.runtime?.stage ? " · " + task.runtime.stage : ""}`
        : "Waiting";
      row.textContent = `${number}. ${item.instruction || "Task"}\n${state}`;
      row.tabIndex = 0;
      row.setAttribute("role", "button");
      const showChild = () => {
        const evidence = childEvidence.get(number);
        childDetail.replaceChildren();
        const heading = document.createElement("strong");
        heading.textContent = "Item " + number + " evidence";
        childDetail.append(heading);
        if (!evidence) {
          addDetailLine(childDetail, "Status", "Waiting / no runtime evidence yet");
        } else {
          addDetailLine(childDetail, "Run", evidence.run_id);
          addDetailLine(childDetail, "Stage", evidence.stage);
          addDetailLine(childDetail, "Status", evidence.completed ? "Completed" : evidence.last_error ? "Needs Attention" : "In progress");
          addDetailLine(childDetail, "Error", evidence.last_error);
          if (evidence.result) {
            const output = document.createElement("pre");
            output.textContent = evidence.result;
            childDetail.append(output);
          }
        }
        childDetail.hidden = false;
      };
      row.addEventListener("click", showChild);
      row.addEventListener("keydown", event => { if (event.key === "Enter" || event.key === " ") { event.preventDefault(); showChild(); }});
      ordered.append(row);
    });
    root.append(ordered, childDetail);
  }
  const actions = document.createElement("div");
  actions.className = "task-actions";
  const allowed = task.available_actions || task.runtime?.actions || {};
  if (allowed.stop) actions.append(makeAction("Stop", "stop"));
  if (allowed.resume) actions.append(makeAction("Resume", "resume"));
  if (allowed.rerun) actions.append(makeAction("Rerun", "rerun", true));
  const completed = Boolean(task.runtime?.completed) || statusText(task).toLowerCase().includes("completed");
  if (allowed.continue || (!task.available_actions && completed)) {
    const text = document.createElement("textarea");
    text.placeholder = "Continue Task with a new instruction…";
    text.setAttribute("aria-label", "Continue Task instruction");
    const continueButton = document.createElement("button");
    continueButton.type = "button";
    continueButton.textContent = "Continue Task";
    continueButton.addEventListener("click", async () => {
      if (!text.value.trim()) return;
      try {
        await request("/api/tasks/action", {task_id: task.task_id, action: "continue", instruction: text.value.trim()});
        await refreshOpenTask();
      } catch (error) { report(error); }
    });
    root.append(text);
    actions.append(continueButton);
  }
  if (allowed.cleanup_workspace || (!task.available_actions && !task.runtime?.running && task.workspace_kind === "worktree" && task.workspace_managed && !task.workspace_removed)) {
    const cleanup = document.createElement("button");
    cleanup.type = "button";
    cleanup.textContent = "Cleanup Worktree";
    cleanup.addEventListener("click", async () => {
      if (!window.confirm("Archive Task runtime evidence and remove this worktree? The branch is kept and nothing is merged.")) return;
      try {
        await request("/api/tasks/workspace/cleanup", {task_id: task.task_id});
        await refreshOpenTask();
      } catch (error) { report(error); }
    });
    actions.append(cleanup);
  }
  if (allowed.delete !== false && !task.runtime?.running) {
    const remove = document.createElement("button");
    remove.type = "button";
    remove.textContent = "Delete Task";
    remove.className = "danger";
    remove.addEventListener("click", async () => {
      if (!window.confirm("Delete this Task record? This does not merge or modify source control.")) return;
      try {
        await request("/api/tasks/delete", {task_id: task.task_id});
        currentTask = null;
        root.hidden = true;
        await loadTasks();
        await loadChats();
      } catch (error) { report(error); }
    });
    actions.append(remove);
  }
  root.append(actions);
  const executionTitle = document.createElement("h4");
  executionTitle.textContent = "Execution history";
  root.append(executionTitle);
  const executionList = document.createElement("div");
  executionList.className = "task-history";
  const executionEntries = [
    ...(task.executions || []).map(execution => {
      const evidence = execution.evidence || {};
      const details = [
        execution.instruction || task.instruction || "Run",
        "request: " + (execution.request_id || "pending"),
        execution.run_id ? "run: " + execution.run_id : "",
        evidence.status ? "status: " + evidence.status : "",
        evidence.stage ? "stage: " + evidence.stage : "",
        evidence.last_error ? "error: " + evidence.last_error : "",
        evidence.result ? "result: " + evidence.result : "",
        evidence.stream_tail ? "output: " + evidence.stream_tail : "",
      ].filter(Boolean);
      return {kind: "execution", text: details.join("\n")};
    }),
    ...(task.history || []).map(message => ({kind: "message", text: message.content || ""}))
  ];
  let visibleHistory = 20;
  const renderHistory = () => {
    executionList.replaceChildren();
    const start = Math.max(0, executionEntries.length - visibleHistory);
    for (const entry of executionEntries.slice(start)) {
      const article = document.createElement("article");
      article.textContent = entry.text;
      executionList.append(article);
    }
    if (start > 0) {
      const more = document.createElement("button");
      more.type = "button";
      more.className = "history-more";
      more.textContent = `Load older (${start} remaining)`;
      more.addEventListener("click", () => { visibleHistory += 20; renderHistory(); });
      executionList.prepend(more);
    }
  };
  renderHistory();
  root.append(executionList);
}

element("toggleSidebar").addEventListener("click", () => {
  const shell = document.querySelector(".chat-shell");
  const collapsed = !shell.classList.contains("sidebar-collapsed");
  shell.classList.toggle("sidebar-collapsed", collapsed);
  element("toggleSidebar").setAttribute("aria-expanded", String(!collapsed));
  element("toggleSidebar").title = collapsed ? "Expand sidebar" : "Collapse sidebar";
  try { localStorage.setItem("ai-task-runner.chats.sidebar-collapsed", String(collapsed)); } catch (_) {}
});
try {
  if (localStorage.getItem("ai-task-runner.chats.sidebar-collapsed") === "true") {
    document.querySelector(".chat-shell").classList.add("sidebar-collapsed");
    element("toggleSidebar").setAttribute("aria-expanded", "false");
  }
} catch (_) {}
element("copyChatPath").addEventListener("click", async () => {
  if (!currentChat?.root_path) return;
  try {
    await navigator.clipboard.writeText(currentChat.root_path);
    element("copyChatPath").textContent = "Copied";
    setTimeout(() => { element("copyChatPath").textContent = "Copy path"; }, 1200);
  } catch (error) { report(error); }
});
element("chatTab").addEventListener("click", () => setTab("chat"));
element("archiveChat").addEventListener("click", async () => {
  if (!currentChat) return;
  try {
    const updated = await request("/api/chats/archive", {
      chat_id: currentChat.chat_id,
      archived: !currentChat.archived
    });
    currentChat = {...currentChat, ...updated};
    element("showArchivedChats").checked = Boolean(currentChat.archived) || element("showArchivedChats").checked;
    await loadChats(true);
  } catch (error) { report(error); }
});
element("showArchivedChats").addEventListener("change", () => loadChats(true).catch(report));
element("tasksTab").addEventListener("click", () => setTab("tasks"));
element("chatProject").addEventListener("change", () => { loadChats(false).catch(report); });
element("newChat").addEventListener("click", async () => {
  const root = element("chatProject").value;
  if (!root) { report(new Error("Select a project first.")); return; }
  try {
    const created = await request("/api/chats/create", {root});
    await loadChats(false);
    await selectChat(created.chat_id);
  } catch (error) { report(error); }
});
element("chatComposer").addEventListener("submit", async event => {
  event.preventDefault();
  if (!currentChat) return;
  const id = currentChat.chat_id;
  const text = element("chatText").value.trim();
  if (!text) return;
  element("chatSend").disabled = true;
  try {
    await request("/api/chats/turn", {chat_id: id, message: text});
    element("chatText").value = "";
    await loadMessages();
  } catch (error) { report(error); }
  finally { element("chatSend").disabled = !currentChat?.path_available || Boolean(currentChat?.archived); }
});
element("newTask").addEventListener("click", () => openTaskModal().catch(report));
element("taskUseFile").addEventListener("click", async () => {
  if (!currentChat?.path_available) return;
  try {
    const picked = await request("/api/files/pick", {
      kind: "file",
      project: currentChat.root_path,
      current: taskGoalFile
    });
    if (picked.cancelled || !picked.path) return;
    taskGoalFile = picked.path;
    element("taskInstruction").value = "";
    element("taskInstruction").disabled = true;
    element("taskInstruction").required = false;
    element("taskGoalFileName").textContent = picked.path;
    element("taskClearFile").hidden = false;
  } catch (error) { report(error); }
});
element("taskClearFile").addEventListener("click", () => {
  taskGoalFile = "";
  element("taskInstruction").disabled = false;
  element("taskInstruction").required = element("taskType").value === "single";
  element("taskGoalFileName").textContent = "";
  element("taskClearFile").hidden = true;
  element("taskInstruction").focus();
});
element("taskType").addEventListener("change", () => setTaskType(element("taskType").value));
element("taskBackend").addEventListener("change", renderTaskModels);
element("taskWorkspace").addEventListener("change", updateSelectedWorkspaceAvailability);
element("openOwningTask").addEventListener("click", async () => {
  const taskId = element("openOwningTask").dataset.taskId || "";
  const chatId = element("openOwningTask").dataset.chatId || "";
  closeTaskModal();
  if (chatId) {
    element("showArchivedChats").checked = true;
    await loadChats(false);
    await selectChat(chatId);
  }
  setTab("tasks");
  if (taskId) await openTask(taskId);
});
element("addTaskListItem").addEventListener("click", () => addTaskListItem());
element("taskListYamlToggle").addEventListener("click", async () => {
  const panel = element("taskListYamlPanel");
  panel.hidden = !panel.hidden;
  element("taskListYamlToggle").setAttribute("aria-expanded", String(!panel.hidden));
  if (!panel.hidden && !element("taskListYaml").value.trim()) await refreshTaskListYaml();
});
element("taskListYamlFromVisual").addEventListener("click", () => refreshTaskListYaml());
element("taskListYamlApply").addEventListener("click", () => applyTaskListYaml());
element("taskCancel").addEventListener("click", closeTaskModal);
element("taskModal").addEventListener("click", event => { if (event.target === element("taskModal")) closeTaskModal(); });
element("taskForm").addEventListener("submit", async event => {
  event.preventDefault();
  if (!currentChat) return;
  const taskType = element("taskType").value;
  const instruction = element("taskInstruction").value.trim();
  const parentWorkflow = element("taskWorkflow").value;
  const items = taskType === "sequential" ? taskListItemsPayload() : [];
  if (taskType === "single" && !instruction && !taskGoalFile) return;
  if (taskType === "sequential" && (!items.length || items.some(item => !item.instruction))) {
    report(new Error("Every Task List item needs an instruction."));
    return;
  }
  element("taskRun").disabled = true;
  try {
    const task = await request("/api/tasks/create", {
      chat_id: currentChat.chat_id,
      task_type: taskType,
      instruction,
      items,
      title: element("taskTitle").value.trim(),
      workflow: parentWorkflow,
      source_message_id: element("taskForm").dataset.sourceMessageId || "",
      goal_file: taskType === "single" ? taskGoalFile : "",
      backend: element("taskBackend").value,
      model: element("taskModel").value,
      ...selectedTaskWorkspace()
    });
    closeTaskModal();
    setTab("tasks");
    await loadTasks();
    await openTask(task.task_id);
    if (task.last_error) report(new Error(task.last_error));
  } catch (error) { report(error); }
  finally { element("taskRun").disabled = false; }
});
for (const button of document.querySelectorAll("[data-task-filter]")) {
  button.addEventListener("click", () => {
    taskFilter = button.dataset.taskFilter;
    for (const other of document.querySelectorAll("[data-task-filter]")) other.setAttribute("aria-pressed", String(other === button));
    renderTasks();
  });
}
document.addEventListener("keydown", event => { if (event.key === "Escape" && !element("taskModal").hidden) closeTaskModal(); });
(async () => {
  const route = initialWorkspaceRoute();
  await loadProjects();
  currentChat = route.chat ? {chat_id: route.chat} : null;
  if (route.chat) element("showArchivedChats").checked = true;
  await loadChats(true);
  setTab(route.tab);
  if (route.task && currentChat) {
    try { await openTask(route.task); } catch (error) { report(error); }
  }
})().catch(report);
setInterval(() => {
  if (document.hidden || !currentChat || activeTab !== "tasks") return;
  loadTasks({preserveDetail: true}).catch(() => {});
}, 3000);
