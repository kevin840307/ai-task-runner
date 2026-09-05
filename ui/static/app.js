const $ = (id) => document.getElementById(id);
const state = { projects: [], project: null, runtime: null, lastStream: "" };

async function api(path, options = {}) {
  const response = await fetch(path, { headers: { "Content-Type": "application/json" }, ...options });
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || `HTTP ${response.status}`);
  return data;
}

function payload(extra = {}) {
  return {
    project: state.project?.path || "",
    backend: $("backend").value,
    validator: $("validator").value.trim(),
    workflow: $("workflow").value.trim(),
    ...extra,
  };
}

async function loadProjects() {
  const data = await api("/api/projects");
  state.projects = data.projects || [];
  renderProjects();
  if (!state.project && state.projects.length) selectProject(state.projects[0]);
}

function renderProjects() {
  const root = $("projects"); root.innerHTML = "";
  for (const project of state.projects) {
    const row = document.createElement("button");
    row.className = "project-item" + (state.project?.path === project.path ? " active" : "");
    const main = document.createElement("span"); main.className = "project-main";
    main.innerHTML = `<span class="project-name"></span><span class="project-path"></span>`;
    main.querySelector(".project-name").textContent = project.name;
    main.querySelector(".project-path").textContent = project.path;
    const remove = document.createElement("span"); remove.className = "remove-project"; remove.textContent = "×";
    remove.onclick = async (event) => { event.stopPropagation(); await api("/api/projects/remove", { method: "POST", body: JSON.stringify({ path: project.path }) }); if (state.project?.path === project.path) state.project = null; await loadProjects(); };
    row.append(main, remove); row.onclick = () => selectProject(project); root.appendChild(row);
  }
}

async function selectProject(project) {
  state.project = project; state.lastStream = ""; renderProjects();
  $("projectName").textContent = project.name; $("projectPath").textContent = project.path;
  $("emptyState").hidden = true; $("chatShell").hidden = false; $("errorText").textContent = "";
  await Promise.all([refreshMessages(), refreshRuntime()]);
}

async function refreshMessages() {
  if (!state.project) return;
  const data = await api(`/api/project/messages?project=${encodeURIComponent(state.project.path)}`);
  const root = $("messages"); root.innerHTML = "";
  for (const message of data.messages || []) {
    const item = document.createElement("article"); item.className = `message ${message.role}`;
    const bubble = document.createElement("div"); bubble.className = "bubble";
    const role = document.createElement("span"); role.className = "role"; role.textContent = message.role === "user" ? "You" : "Agent";
    const text = document.createElement("div"); text.textContent = message.content;
    bubble.append(role, text); item.appendChild(bubble); root.appendChild(item);
  }
  root.scrollTop = root.scrollHeight;
}

async function refreshRuntime() {
  if (!state.project) return;
  try {
    const runtime = await api(`/api/project/runtime?project=${encodeURIComponent(state.project.path)}`);
    state.runtime = runtime; renderRuntime(runtime);
  } catch (error) { $("errorText").textContent = error.message; }
}

function renderRuntime(runtime) {
  const badge = $("statusBadge");
  badge.className = "badge";
  let label = "Idle";
  if (runtime.running) { label = "Running"; badge.classList.add("running"); }
  else if (runtime.last_error) { label = "Failed"; badge.classList.add("failed"); }
  else if (runtime.completed) { label = "Completed"; badge.classList.add("done"); }
  badge.textContent = label;
  $("stopButton").hidden = !runtime.running;
  $("resumeButton").hidden = runtime.running || runtime.completed || (!runtime.stage && !runtime.last_error);
  $("rerunButton").hidden = runtime.running || !hasUserMessage();
  $("sendButton").disabled = runtime.running;
  $("messageInput").disabled = runtime.running;

  const showLive = runtime.running || Boolean(runtime.stream);
  $("liveCard").hidden = !showLive;
  $("liveTitle").textContent = runtime.stage ? `Running · ${runtime.stage}` : label;
  $("progressText").textContent = runtime.total ? `${runtime.current} / ${runtime.total}` : "";
  const bits = [];
  if (runtime.task) bits.push(runtime.task);
  if (runtime.pid) bits.push(`PID ${runtime.pid}`);
  if (runtime.last_error) bits.push(runtime.last_error);
  $("liveMeta").textContent = bits.join(" · ");
  if (runtime.stream !== state.lastStream) {
    state.lastStream = runtime.stream || "";
    $("liveOutput").textContent = state.lastStream || "Waiting for output...";
    $("liveOutput").scrollTop = $("liveOutput").scrollHeight;
  }
}

function hasUserMessage() { return $("messages").querySelector(".message.user") !== null; }

async function sendMessage() {
  const text = $("messageInput").value.trim(); if (!text || !state.project) return;
  $("errorText").textContent = "";
  try {
    await api("/api/project/message", { method: "POST", body: JSON.stringify(payload({ message: text })) });
    $("messageInput").value = "";
    await refreshMessages(); setTimeout(refreshRuntime, 250);
  } catch (error) { $("errorText").textContent = error.message; }
}

$("openProject").onclick = async () => {
  try {
    const result = await api("/api/projects/pick", { method: "POST", body: "{}" });
    if (!result.cancelled) {
      await loadProjects();
      const picked = state.projects.find(p => p.path === result.path);
      if (picked) selectProject(picked);
    }
  } catch (error) {
    const path = window.prompt("Folder picker unavailable. Enter project path:");
    if (!path) return;
    try {
      const added = await api("/api/projects/add", { method: "POST", body: JSON.stringify({ path }) });
      await loadProjects();
      const picked = state.projects.find(p => p.path === added.path);
      if (picked) selectProject(picked);
    } catch (fallbackError) {
      window.alert(fallbackError.message);
    }
  }
};
$("sendButton").onclick = sendMessage;
$("messageInput").addEventListener("keydown", (event) => { if (event.key === "Enter" && !event.shiftKey) { event.preventDefault(); sendMessage(); } });
$("stopButton").onclick = async () => { await api("/api/project/stop", { method: "POST", body: JSON.stringify(payload()) }); setTimeout(refreshRuntime, 250); };
$("resumeButton").onclick = async () => { try { await api("/api/project/resume", { method: "POST", body: JSON.stringify(payload()) }); setTimeout(refreshRuntime, 250); } catch (error) { $("errorText").textContent = error.message; } };
$("rerunButton").onclick = async () => { try { await api("/api/project/rerun", { method: "POST", body: JSON.stringify(payload()) }); setTimeout(refreshRuntime, 250); } catch (error) { $("errorText").textContent = error.message; } };

loadProjects();
setInterval(refreshRuntime, 750);
