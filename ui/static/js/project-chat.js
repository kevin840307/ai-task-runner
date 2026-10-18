function requestId() {
  if (globalThis.crypto?.randomUUID) return globalThis.crypto.randomUUID();
  return "chat-" + Date.now() + "-" + Math.random().toString(16).slice(2);
}

export function createProjectChatController({ api, inputDialog, confirmDialog, showToast, showError, autosizeTextarea }) {
  let project = null;
  let sessions = [];
  let activeSessionId = "";
  let preferences = {};
  let agentCapabilities = [];
  let capabilitiesError = "";
  let suggestionIndex = 0;
  let queueItems = [];
  let queueBusy = false;
  let queuePollTimer = 0;

  const byId = (id) => document.getElementById(id);

  function projectPath() {
    return String(project?.path || "");
  }

  async function refreshAgentCapabilities({ refresh = false } = {}) {
    const path = projectPath();
    const agent = String(preferences.backend || preferences.agent || "");
    if (!path) {
      agentCapabilities = [];
      capabilitiesError = "";
      renderSuggestions();
      return;
    }
    capabilitiesError = "";
    try {
      const query = new URLSearchParams({ project: path });
      if (agent) query.set("agent", agent);
      if (refresh) query.set("refresh", "1");
      const data = await api("/api/chat/capabilities?" + query.toString(), { timeoutMs: 35000 });
      if (projectPath() !== path) return;
      agentCapabilities = Array.isArray(data.capabilities) ? data.capabilities : [];
    } catch (error) {
      if (projectPath() !== path) return;
      agentCapabilities = [];
      capabilitiesError = String(error?.message || "Capability discovery failed");
    }
    suggestionIndex = 0;
    renderSuggestions();
  }

  function suggestionQuery() {
    const value = String(byId("projectChatInput")?.value || "");
    if (!value.startsWith("/") || /\s/.test(value)) return null;
    return value.slice(1).toLowerCase();
  }

  function visibleSuggestions() {
    const query = suggestionQuery();
    if (query === null) return [];
    return agentCapabilities.filter((item) => {
      const haystack = [item.token, item.name, item.description, item.source, item.kind]
        .map((value) => String(value || "").toLowerCase()).join(" ");
      return haystack.includes(query);
    });
  }

  function renderSuggestions() {
    const panel = byId("projectChatSuggest");
    const list = byId("projectChatSuggestList");
    const retry = byId("projectChatSuggestRetry");
    if (!panel || !list) return;
    const query = suggestionQuery();
    if (query === null) {
      panel.hidden = true;
      return;
    }
    panel.hidden = false;
    if (retry) retry.hidden = !capabilitiesError;
    list.innerHTML = "";
    if (capabilitiesError) {
      const empty = document.createElement("div");
      empty.className = "project-chat-suggest-empty";
      empty.textContent = capabilitiesError;
      list.appendChild(empty);
      return;
    }
    const values = visibleSuggestions();
    if (!values.length) {
      const empty = document.createElement("div");
      empty.className = "project-chat-suggest-empty";
      empty.textContent = "No Agent Skill / Command matches.";
      list.appendChild(empty);
      return;
    }
    suggestionIndex = Math.max(0, Math.min(suggestionIndex, values.length - 1));
    values.forEach((item, index) => {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "project-chat-suggest-item";
      button.disabled = !item.enabled || !item.user_invocable;
      button.classList.toggle("active", index === suggestionIndex);
      const copy = document.createElement("span");
      copy.className = "project-chat-suggest-copy";
      const token = document.createElement("span");
      token.className = "project-chat-suggest-token";
      token.textContent = item.token;
      const description = document.createElement("span");
      description.className = "project-chat-suggest-description";
      description.textContent = item.description || (item.kind === "skill" ? "Agent Skill" : "Agent command");
      copy.append(token, description);
      const meta = document.createElement("span");
      meta.className = "project-chat-suggest-meta";
      meta.textContent = [item.kind, item.source, item.enabled ? item.permission || "available" : item.availability || "disabled"]
        .filter(Boolean).join(" · ");
      button.append(copy, meta);
      button.onmouseenter = () => { suggestionIndex = index; renderSuggestions(); };
      button.onmousedown = (event) => event.preventDefault();
      button.onclick = () => acceptSuggestion(item);
      list.appendChild(button);
    });
    list.querySelector(".project-chat-suggest-item.active")?.scrollIntoView({ block: "nearest" });
  }

  function acceptSuggestion(item) {
    if (!item?.enabled || !item?.user_invocable) return;
    const input = byId("projectChatInput");
    if (!input) return;
    input.value = String(item.token || "") + " ";
    panelHideSuggestions();
    autosizeTextarea?.(input, { minHeight: 46, maxHeight: 180 });
    input.focus();
  }

  function panelHideSuggestions() {
    const panel = byId("projectChatSuggest");
    if (panel) panel.hidden = true;
  }

  function clearQueuePoll() {
    if (queuePollTimer) {
      clearTimeout(queuePollTimer);
      queuePollTimer = 0;
    }
  }

  function scheduleQueuePoll() {
    clearQueuePoll();
    if (!queueBusy || !project || !activeSessionId) return;
    const expectedProject = projectPath();
    const expectedSession = activeSessionId;
    queuePollTimer = setTimeout(async () => {
      queuePollTimer = 0;
      if (projectPath() !== expectedProject || activeSessionId !== expectedSession) return;
      try {
        await Promise.all([refreshMessages(), refreshQueue()]);
      } catch (_) {}
    }, 900);
  }

  function renderTurnState() {
    const status = byId("projectChatTurnStatus");
    const send = byId("projectChatSendButton");
    const input = byId("projectChatInput");
    if (status) status.hidden = !queueBusy;
    if (send) {
      send.disabled = !project;
      send.setAttribute("aria-busy", String(queueBusy));
      send.textContent = queueBusy ? "Queue" : "Send";
    }
    if (input) input.disabled = !project;
    scheduleQueuePoll();
  }

  function renderQueue() {
    const root = byId("projectChatQueue");
    const list = byId("projectChatQueueList");
    const count = byId("projectChatQueueCount");
    if (!root || !list || !count) return;
    count.textContent = String(queueItems.length);
    root.hidden = queueItems.length === 0;
    list.innerHTML = "";
    for (const item of queueItems) {
      const row = document.createElement("div");
      row.className = "project-chat-queue-item";
      const copy = document.createElement("div");
      copy.className = "project-chat-queue-copy";
      copy.textContent = String(item.content || "");
      copy.title = String(item.content || "");
      const actions = document.createElement("span");
      actions.className = "project-chat-queue-actions";
      const edit = document.createElement("button");
      edit.type = "button";
      edit.textContent = "Edit";
      edit.onclick = () => void editQueueItem(item);
      const remove = document.createElement("button");
      remove.type = "button";
      remove.textContent = "Delete";
      remove.onclick = () => void deleteQueueItem(item);
      actions.append(edit, remove);
      row.append(copy, actions);
      list.appendChild(row);
    }
  }

  function applyQueueState(data = {}) {
    queueItems = Array.isArray(data.items) ? data.items : [];
    queueBusy = !!data.busy;
    renderQueue();
    renderTurnState();
  }

  async function refreshQueue() {
    const path = projectPath();
    if (!path || !activeSessionId) {
      queueItems = [];
      queueBusy = false;
      renderQueue();
      renderTurnState();
      return;
    }
    const expectedProject = path;
    const expectedSession = activeSessionId;
    const data = await api(
      "/api/chat/queue?project=" + encodeURIComponent(path) +
      "&session_id=" + encodeURIComponent(expectedSession),
      { timeoutMs: 15000 }
    );
    if (projectPath() !== expectedProject || activeSessionId !== expectedSession) return;
    applyQueueState(data);
  }

  async function editQueueItem(item) {
    const next = await inputDialog?.({
      title: "Edit queued message",
      label: "Message",
      value: String(item.content || ""),
      confirmLabel: "Save",
    });
    if (next === null || next === undefined || String(next).trim() === String(item.content || "").trim()) return;
    try {
      const data = await api("/api/chat/queue/update", {
        method: "POST",
        body: JSON.stringify({
          project: projectPath(),
          session_id: activeSessionId,
          queue_id: item.queue_id,
          message: String(next),
        }),
      });
      applyQueueState(data);
      showToast?.("Queue updated");
    } catch (error) {
      showError?.(error.message, "Queue update failed");
      await refreshQueue().catch(() => {});
    }
  }

  async function deleteQueueItem(item) {
    try {
      const data = await api("/api/chat/queue/delete", {
        method: "POST",
        body: JSON.stringify({
          project: projectPath(),
          session_id: activeSessionId,
          queue_id: item.queue_id,
        }),
      });
      applyQueueState(data);
      showToast?.("Queued message deleted");
    } catch (error) {
      showError?.(error.message, "Queue delete failed");
      await refreshQueue().catch(() => {});
    }
  }

  function renderPreferences(next = preferences) {
    preferences = next || {};
    const root = byId("projectChatPreferences");
    if (!root) return;
    const modeHint = byId("projectChatModeHint");
    if (modeHint) modeHint.textContent = String(preferences.mode || "auto").toUpperCase();
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
    await Promise.all([refreshMessages(), refreshQueue()]);
  }

  function renderPendingUser(text) {
    const root = byId("projectChatMessages");
    const empty = byId("projectChatEmptyMessages");
    if (!root) return;
    if (empty) empty.hidden = true;
    const item = document.createElement("article");
    item.className = "message project-chat-message project-chat-pending user";
    const body = document.createElement("div");
    body.className = "message-body";
    body.textContent = text;
    item.appendChild(body);
    root.appendChild(item);
    requestAnimationFrame(() => { root.scrollTop = root.scrollHeight; });
  }

  async function sendMessage() {
    const input = byId("projectChatInput");
    const text = String(input?.value || "").trim();
    if (!project || !activeSessionId || !text) return;
    input.value = "";
    autosizeTextarea?.(input, { minHeight: 46, maxHeight: 180 });
    const expectedProject = projectPath();
    const expectedSession = activeSessionId;
    renderPendingUser(text);
    queueBusy = true;
    renderTurnState();
    try {
      const data = await api("/api/chat/turn", {
        method: "POST",
        body: JSON.stringify({
          project: expectedProject,
          session_id: expectedSession,
          message: text,
          request_id: requestId(),
        }),
      });
      if (projectPath() !== expectedProject || activeSessionId !== expectedSession) return;
      applyQueueState(data);
      await refreshMessages();
      if (data.status === "error" && data.error) {
        showError?.(String(data.error), "Chat turn failed");
      }
    } catch (error) {
      if (projectPath() !== expectedProject || activeSessionId !== expectedSession) return;
      await Promise.all([
        refreshMessages().catch(() => {}),
        refreshQueue().catch(() => {}),
      ]);
      showError?.(error.message, "Chat turn failed");
    } finally {
      if (projectPath() === expectedProject && activeSessionId === expectedSession) {
        input?.focus();
      }
    }
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
      await Promise.all([refreshMessages(), refreshQueue()]);
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
      await Promise.all([refreshMessages(), refreshQueue()]);
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
      await Promise.all([refreshMessages(), refreshQueue()]);
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
    clearQueuePoll();
    queueItems = [];
    queueBusy = false;
    renderPreferences();
    void refreshAgentCapabilities();
    const newChat = byId("newProjectChatButton");
    if (newChat) newChat.disabled = !project;
    renderQueue();
    renderTurnState();
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
  byId("projectChatSendButton")?.addEventListener("click", () => void sendMessage());
  byId("projectChatInput")?.addEventListener("input", (event) => {
    autosizeTextarea?.(event.currentTarget, { minHeight: 46, maxHeight: 180 });
    suggestionIndex = 0;
    renderSuggestions();
  });
  byId("projectChatInput")?.addEventListener("keydown", (event) => {
    const panel = byId("projectChatSuggest");
    const values = visibleSuggestions();
    if (panel && !panel.hidden && values.length) {
      if (event.key === "ArrowDown" || event.key === "ArrowUp") {
        event.preventDefault();
        const delta = event.key === "ArrowDown" ? 1 : -1;
        suggestionIndex = (suggestionIndex + delta + values.length) % values.length;
        renderSuggestions();
        return;
      }
      if ((event.key === "Enter" || event.key === "Tab") && !event.isComposing) {
        const item = values[suggestionIndex];
        if (item?.enabled && item?.user_invocable) {
          event.preventDefault();
          acceptSuggestion(item);
          return;
        }
      }
      if (event.key === "Escape") {
        event.preventDefault();
        panelHideSuggestions();
        return;
      }
    }
    if (event.key === "Enter" && !event.shiftKey && !event.isComposing) {
      event.preventDefault();
      void sendMessage();
    }
  });
  byId("projectChatSuggestRetry")?.addEventListener("click", () => void refreshAgentCapabilities({ refresh: true }));

  return {
    openProject,
    clearProject,
    refreshSessions,
    refreshMessages,
    refreshQueue,
    renderPreferences,
    activeSessionId: () => activeSessionId,
  };
}
