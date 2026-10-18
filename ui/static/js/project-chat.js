function requestId() {
  if (globalThis.crypto?.randomUUID) return globalThis.crypto.randomUUID();
  return "chat-" + Date.now() + "-" + Math.random().toString(16).slice(2);
}

export function createProjectChatController({ api, inputDialog, confirmDialog, showToast, showError }) {
  let project = null;
  let sessions = [];
  let activeSessionId = "";
  let preferences = {};

  const byId = (id) => document.getElementById(id);

  function projectPath() {
    return String(project?.path || "");
  }

  function renderPreferences(next = preferences) {
    preferences = next || {};
    const root = byId("projectChatPreferences");
    if (!root) return;
    root.innerHTML = "";
    const items = [
      ["Agent", preferences.backend || preferences.agent || "Default"],
      ["Model", preferences.model || "Default"],
      ["Mode", preferences.mode || "auto"],
      ["Reasoning", preferences.reasoning || "medium"],
      ["Workflow", preferences.workflow ? String(preferences.workflow).split(/[\\/]/).pop() : "Default"],
    ];
    for (const [label, value] of items) {
      const item = document.createElement("span");
      item.className = "project-chat-pref";
      const key = document.createElement("small");
      key.textContent = label;
      const text = document.createElement("strong");
      text.textContent = String(value || "Default");
      text.title = String(value || "Default");
      item.append(key, text);
      root.appendChild(item);
    }
  }

  function renderSessions() {
    const root = byId("projectChatSessionList");
    if (!root) return;
    root.innerHTML = "";
    for (const session of sessions) {
      const row = document.createElement("div");
      row.className = "project-chat-session-row";
      if (session.session_id === activeSessionId) row.classList.add("active");

      const open = document.createElement("button");
      open.type = "button";
      open.className = "project-chat-session-open";
      open.textContent = session.title || "New Chat";
      open.title = session.title || "New Chat";
      open.onclick = () => void selectSession(session.session_id);

      const actions = document.createElement("span");
      actions.className = "project-chat-session-actions";
      const rename = document.createElement("button");
      rename.type = "button";
      rename.textContent = "Rename";
      rename.title = "Rename Chat";
      rename.onclick = (event) => {
        event.stopPropagation();
        void renameSession(session);
      };
      const remove = document.createElement("button");
      remove.type = "button";
      remove.textContent = "×";
      remove.title = "Delete Chat";
      remove.setAttribute("aria-label", "Delete Chat");
      remove.onclick = (event) => {
        event.stopPropagation();
        void deleteSession(session);
      };
      actions.append(rename, remove);
      row.append(open, actions);
      root.appendChild(row);
    }
  }

  function renderMessages(rows = []) {
    const root = byId("projectChatMessages");
    const empty = byId("projectChatEmptyMessages");
    if (!root || !empty) return;
    root.querySelectorAll(".project-chat-message").forEach((node) => node.remove());
    empty.hidden = rows.length > 0;
    for (const message of rows) {
      const item = document.createElement("article");
      const role = ["user", "assistant", "system"].includes(message.role) ? message.role : "assistant";
      item.className = "message project-chat-message " + role;
      const body = document.createElement("div");
      body.className = "message-body";
      body.textContent = String(message.content || "");
      item.appendChild(body);
      root.appendChild(item);
    }
    requestAnimationFrame(() => { root.scrollTop = root.scrollHeight; });
  }

  async function refreshMessages() {
    const path = projectPath();
    if (!path || !activeSessionId) return renderMessages([]);
    const expectedProject = path;
    const expectedSession = activeSessionId;
    const data = await api(
      "/api/chat/messages?project=" + encodeURIComponent(path) +
      "&session_id=" + encodeURIComponent(expectedSession),
      { timeoutMs: 15000 }
    );
    if (projectPath() !== expectedProject || activeSessionId !== expectedSession) return;
    renderMessages(Array.isArray(data.messages) ? data.messages : []);
  }

  async function refreshSessions() {
    const path = projectPath();
    if (!path) return;
    const expected = path;
    const data = await api("/api/chat/sessions?project=" + encodeURIComponent(path), { timeoutMs: 15000 });
    if (projectPath() !== expected) return;
    sessions = Array.isArray(data.sessions) ? data.sessions : [];
    activeSessionId = String(data.active_session_id || data.session_id || sessions[0]?.session_id || "");
    renderSessions();
    await refreshMessages();
  }

  async function createSession() {
    const path = projectPath();
    if (!path) return;
    try {
      const data = await api("/api/chat/session/create", {
        method: "POST",
        body: JSON.stringify({ project: path, request_id: requestId() }),
      });
      sessions = Array.isArray(data.sessions) ? data.sessions : sessions;
      activeSessionId = String(data.session_id || data.active_session_id || "");
      renderSessions();
      await refreshMessages();
      showToast?.("New Chat created");
    } catch (error) {
      showError?.(error.message, "Create Chat failed");
    }
  }

  async function selectSession(sessionId) {
    const path = projectPath();
    if (!path || !sessionId || sessionId === activeSessionId) return;
    try {
      const data = await api("/api/chat/session/select", {
        method: "POST",
        body: JSON.stringify({ project: path, session_id: sessionId }),
      });
      sessions = Array.isArray(data.sessions) ? data.sessions : sessions;
      activeSessionId = String(data.active_session_id || sessionId);
      renderSessions();
      await refreshMessages();
    } catch (error) {
      showError?.(error.message, "Open Chat failed");
    }
  }

  async function renameSession(session) {
    const title = await inputDialog?.({
      title: "Rename Chat",
      label: "Chat name",
      value: session.title || "New Chat",
      confirmLabel: "Rename",
    });
    if (!title || title === session.title) return;
    try {
      const data = await api("/api/chat/session/rename", {
        method: "POST",
        body: JSON.stringify({ project: projectPath(), session_id: session.session_id, title }),
      });
      sessions = Array.isArray(data.sessions) ? data.sessions : sessions;
      renderSessions();
      showToast?.("Chat renamed");
    } catch (error) {
      showError?.(error.message, "Rename Chat failed");
    }
  }

  async function deleteSession(session) {
    const ok = await confirmDialog?.({
      title: "Delete Chat?",
      message: "Delete this Chat session and its saved messages?",
      confirmLabel: "Delete Chat",
      danger: true,
    });
    if (!ok) return;
    try {
      const data = await api("/api/chat/session/delete", {
        method: "POST",
        body: JSON.stringify({ project: projectPath(), session_id: session.session_id }),
      });
      sessions = Array.isArray(data.sessions) ? data.sessions : [];
      activeSessionId = String(data.active_session_id || data.session_id || sessions[0]?.session_id || "");
      renderSessions();
      await refreshMessages();
      showToast?.("Chat deleted");
    } catch (error) {
      showError?.(error.message, "Delete Chat failed");
    }
  }

  async function openProject(nextProject, nextPreferences = {}) {
    project = nextProject || null;
    preferences = nextPreferences || {};
    const name = byId("projectChatName");
    const path = byId("projectChatPath");
    if (name) name.textContent = project?.name || "Select a project";
    if (path) path.textContent = project?.path || "Open a local project folder to begin.";
    renderPreferences();
    const newChat = byId("newProjectChatButton");
    if (newChat) newChat.disabled = !project;
    if (!project) {
      sessions = [];
      activeSessionId = "";
      renderSessions();
      renderMessages([]);
      return;
    }
    await refreshSessions();
  }

  function clearProject() {
    return openProject(null, {});
  }

  byId("newProjectChatButton")?.addEventListener("click", () => void createSession());

  return {
    openProject,
    clearProject,
    refreshSessions,
    refreshMessages,
    renderPreferences,
    activeSessionId: () => activeSessionId,
  };
}
