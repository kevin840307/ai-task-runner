const element = (id) => document.getElementById(id);
let currentChat = null;
let chats = [];
let projects = [];
let currentTasks = [];
let currentTask = null;
let taskFilter = "all";
let activeTab = "chat";
let workflowChoices = [];

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
function statusText(task) {
  const runtime = task.runtime || {};
  return String(runtime.status || task.last_status || "pending").replaceAll("_", " ");
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
  const writable = Boolean(currentChat?.path_available);
  element("chatText").disabled = !writable;
  element("chatSend").disabled = !writable;
  element("newTask").disabled = !writable;
  element("chatNotice").textContent = currentChat && !writable
    ? "Path unavailable · Chat and Task history remain readable; new work is disabled."
    : "Chat is read-only with project access. Use Tasks for file changes, execution, validation, and long-running work.";
  for (const button of element("chatList").querySelectorAll("button[data-id]")) {
    button.dataset.active = String(button.dataset.id === id);
  }
  await Promise.all([loadMessages(), loadTasks()]);
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
      if (message.role === "user" && currentChat.path_available) {
        const actions = document.createElement("div");
        actions.className = "chat-bubble-actions";
        const create = document.createElement("button");
        create.type = "button";
        create.textContent = "Create Task";
        create.addEventListener("click", () => openTaskModal(message.text, message.message_id || ""));
        actions.append(create);
        bubble.append(actions);
      }
      container.append(bubble);
    }
    container.scrollTop = container.scrollHeight;
  } catch (error) { report(error); }
}
async function loadChats(keepSelection = true) {
  clearError();
  const [data, taskData] = await Promise.all([request("/api/chats"), request("/api/tasks")]);
  chats = data.chats;
  const badges = taskBadgeCounts(taskData.tasks || []);
  const selectedProject = element("chatProject").value;
  const list = element("chatList");
  list.replaceChildren();
  for (const chat of chats.filter(item => !selectedProject || item.root_path === selectedProject)) {
    const button = document.createElement("button");
    button.type = "button";
    button.dataset.id = chat.chat_id;
    const badge = badges.get(chat.chat_id);
    const suffix = !chat.path_available ? " · Path unavailable"
      : badge?.attention ? ` · Needs Attention ${badge.attention}`
      : badge?.active ? ` · Running ${badge.active}` : "";
    button.textContent = chat.title + suffix;
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
function addTaskListItem(value = "", workflow = "", index = null) {
  const row = document.createElement("div");
  row.className = "task-list-item";
  const text = document.createElement("textarea");
  text.maxLength = 20000;
  text.required = true;
  text.placeholder = "Instruction / Prompt";
  text.value = value;
  const override = document.createElement("select");
  override.setAttribute("aria-label", "Workflow override");
  fillWorkflowSelect(override, {inherited: true});
  override.value = workflow;
  const controls = document.createElement("div");
  controls.className = "move-buttons";
  const up = document.createElement("button"); up.type = "button"; up.textContent = "↑"; up.title = "Move up";
  const down = document.createElement("button"); down.type = "button"; down.textContent = "↓"; down.title = "Move down";
  const duplicate = document.createElement("button"); duplicate.type = "button"; duplicate.textContent = "⧉"; duplicate.title = "Duplicate";
  const remove = document.createElement("button"); remove.type = "button"; remove.textContent = "×"; remove.title = "Remove";
  up.addEventListener("click", () => row.previousElementSibling?.before(row));
  down.addEventListener("click", () => row.nextElementSibling?.after(row));
  duplicate.addEventListener("click", () => addTaskListItem(text.value, override.value, [...row.parentElement.children].indexOf(row) + 1));
  remove.addEventListener("click", () => { if (row.parentElement.children.length > 1) row.remove(); });
  controls.append(up, down, duplicate, remove);
  row.append(text, override, controls);
  const root = element("taskListItems");
  if (index === null || index >= root.children.length) root.append(row);
  else root.insertBefore(row, root.children[index]);
  return row;
}
function setTaskType(type) {
  const sequential = type === "sequential";
  element("singleInstructionRow").hidden = sequential;
  element("taskListEditor").hidden = !sequential;
  element("taskInstruction").required = !sequential;
  element("taskRun").textContent = sequential ? "Run List" : "Run Task";
  if (sequential && !element("taskListItems").children.length) addTaskListItem();
}
async function updateMainAvailability() {
  if (!currentChat?.path_available) { element("mainAvailability").textContent = "Path unavailable"; return; }
  try {
    const runtime = await request("/api/project/runtime?project=" + encodeURIComponent(currentChat.root_path));
    element("mainAvailability").textContent = runtime.running ? "Busy" : "Available";
    element("taskRun").disabled = Boolean(runtime.running);
  } catch (_) {
    element("mainAvailability").textContent = "Unavailable";
    element("taskRun").disabled = true;
  }
}
async function openTaskModal(prefill = "", sourceMessageId = "") {
  if (!currentChat?.path_available) return;
  element("taskType").value = "single";
  setTaskType("single");
  element("taskInstruction").value = prefill;
  element("taskTitle").value = "";
  element("taskListItems").replaceChildren();
  addTaskListItem(prefill);
  element("taskForm").dataset.sourceMessageId = sourceMessageId;
  element("taskModal").hidden = false;
  await Promise.all([loadWorkflowOptions(), updateMainAvailability()]);
  element("taskInstruction").focus();
}
function closeTaskModal() {
  element("taskModal").hidden = true;
  element("taskForm").dataset.sourceMessageId = "";
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
    const progress = runtime.total ? ` · ${runtime.completed_count || 0}/${runtime.total}` : "";
    const stage = runtime.stage ? ` · ${runtime.stage}` : "";
    status.textContent = `${statusText(task)}${stage}${progress}`;
    const meta = document.createElement("small");
    meta.textContent = task.task_type === "sequential" ? "Task List" : "Task";
    button.append(title, status, meta);
    button.addEventListener("click", () => openTask(task.task_id).catch(report));
    list.append(button);
  }
}
async function loadTasks() {
  currentTasks = [];
  currentTask = null;
  element("taskDetail").hidden = true;
  if (!currentChat) { renderTasks(); return; }
  const id = currentChat.chat_id;
  const data = await request("/api/tasks?chat_id=" + encodeURIComponent(id));
  if (id !== currentChat?.chat_id) return;
  currentTasks = data.tasks || [];
  renderTasks();
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
  await openTask(currentTask.task_id);
  await loadTasks();
}
async function openTask(taskId) {
  const task = await request("/api/task?task_id=" + encodeURIComponent(taskId));
  currentTask = task;
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
  addDetailLine(root, "Workflow", task.workflow || "Runner default");
  if (task.runtime) {
    addDetailLine(root, "Stage", task.runtime.stage);
    addDetailLine(root, "Cycle", task.runtime.cycle);
    if (task.runtime.total) addDetailLine(root, "Progress", `${task.runtime.completed_count || 0}/${task.runtime.total}`);
    addDetailLine(root, "Attention", task.runtime.attention_reason);
  } else {
    addDetailLine(root, "Last error", task.last_error);
  }
  const actions = document.createElement("div");
  actions.className = "task-actions";
  const allowed = task.runtime?.actions || {};
  if (allowed.stop) actions.append(makeAction("Stop", "stop"));
  if (allowed.resume) actions.append(makeAction("Resume", "resume"));
  if (allowed.rerun) actions.append(makeAction("Rerun", "rerun", true));
  const completed = Boolean(task.runtime?.completed) || statusText(task).toLowerCase().includes("completed");
  if (completed) {
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
  if (!task.runtime?.running) {
    const remove = document.createElement("button");
    remove.type = "button";
    remove.textContent = "Delete Task";
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
  for (const execution of task.executions || []) {
    const article = document.createElement("article");
    article.textContent = `${execution.instruction || task.instruction || "Run"}\nrequest: ${execution.request_id || "pending"}${execution.run_id ? "\nrun: " + execution.run_id : ""}`;
    executionList.append(article);
  }
  for (const message of task.history || []) {
    const article = document.createElement("article");
    article.textContent = message.content || "";
    executionList.append(article);
  }
  root.append(executionList);
}

element("chatTab").addEventListener("click", () => setTab("chat"));
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
  finally { element("chatSend").disabled = !currentChat?.path_available; }
});
element("newTask").addEventListener("click", () => openTaskModal().catch(report));
element("taskType").addEventListener("change", () => setTaskType(element("taskType").value));
element("addTaskListItem").addEventListener("click", () => addTaskListItem());
element("taskCancel").addEventListener("click", closeTaskModal);
element("taskModal").addEventListener("click", event => { if (event.target === element("taskModal")) closeTaskModal(); });
element("taskForm").addEventListener("submit", async event => {
  event.preventDefault();
  if (!currentChat) return;
  const taskType = element("taskType").value;
  const instruction = element("taskInstruction").value.trim();
  const parentWorkflow = element("taskWorkflow").value;
  const items = taskType === "sequential"
    ? [...element("taskListItems").querySelectorAll(".task-list-item")].map(row => ({
        instruction: row.querySelector("textarea").value.trim(),
        workflow: row.querySelector("select").value || parentWorkflow
      }))
    : [];
  if (taskType === "single" && !instruction) return;
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
      source_message_id: element("taskForm").dataset.sourceMessageId || ""
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
Promise.all([loadProjects(), loadChats()]).catch(report);
setInterval(() => {
  if (document.hidden || !currentChat || activeTab !== "tasks") return;
  loadTasks().catch(() => {});
}, 3000);
