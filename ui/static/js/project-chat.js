function requestId() {
  if (globalThis.crypto?.randomUUID) return globalThis.crypto.randomUUID();
  return "chat-" + Date.now() + "-" + Math.random().toString(16).slice(2);
}

export function createProjectChatController({ api, inputDialog, confirmDialog, showToast, showError, autosizeTextarea, openTaskDraft, openTask, openTaskCreateMenu, onPreferencesChanged }) {
  let project = null;
  let sessions = [];
  let activeSessionId = "";
  let eventCursor = 0;
  let preferences = {};
  let agentCapabilities = [];
  let runnerCapabilities = [];
  let capabilitiesError = "";
  let runnerCapabilitiesError = "";
  let suggestionIndex = 0;
  const taskDraftsBySession = new Map();
  let queueItems = [];
  let queueBusy = false;
  let turnCancelPending = false;
  let queuePollTimer = 0;
  let settingsCatalog = { agents: [], models: [], modes: [], reasoning: [], workflows: [], features: {}, default_agent: "" };
  let settingsLoading = false;
  let editingQueueId = "";
  let editingQueueValue = "";
  let editingQueueError = "";
  let messageRows = [];
  let activeAsk = null;
  let askIndex = 0;
  let askAnswers = {};
  let askError = "";
  let preferenceAction = Promise.resolve();

  const byId = (id) => document.getElementById(id);
  const tr = (key, fallback) => window.I18n?.t?.(key, fallback) ?? fallback;
  const trf = (key, values, fallback) => window.I18n?.format?.(key, values, fallback) ?? fallback;

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

  async function refreshRunnerCapabilities() {
    const path = projectPath();
    if (!path) {
      runnerCapabilities = [];
      runnerCapabilitiesError = "";
      renderSuggestions();
      return;
    }
    runnerCapabilitiesError = "";
    try {
      const data = await api(
        "/api/chat/system-capabilities?project=" + encodeURIComponent(path),
        { timeoutMs: 15000 },
      );
      if (projectPath() !== path) return;
      runnerCapabilities = Array.isArray(data.capabilities) ? data.capabilities : [];
    } catch (error) {
      if (projectPath() !== path) return;
      runnerCapabilities = [];
      runnerCapabilitiesError = String(error?.message || "Runner capability discovery failed");
    }
    suggestionIndex = 0;
    renderSuggestions();
  }

  function preferenceValue(key, fallback = "") {
    if (key === "agent") return String(preferences.backend || preferences.agent || fallback);
    return String(preferences[key] ?? fallback);
  }

  function normalizePreferences(data = {}) {
    return {
      ...preferences,
      ...data,
      backend: String(data.agent ?? data.backend ?? preferences.backend ?? preferences.agent ?? ""),
      agent: String(data.agent ?? data.backend ?? preferences.agent ?? preferences.backend ?? ""),
      model: String(data.model ?? preferences.model ?? ""),
      mode: String(data.mode ?? preferences.mode ?? "auto"),
      reasoning: String(data.reasoning ?? preferences.reasoning ?? ""),
      workflow: String(data.workflow ?? preferences.workflow ?? ""),
    };
  }

  async function refreshSettingsCatalog({ refresh = false, agent = "", model = "" } = {}) {
    const path = projectPath();
    if (!path) {
      settingsCatalog = { agents: [], models: [], modes: [], reasoning: [], workflows: [], features: {}, default_agent: "" };
      renderSettingsControls();
      return;
    }
    const expected = path;
    const query = new URLSearchParams({ project: path });
    const selectedAgent = String(agent || preferenceValue("agent"));
    const selectedModel = String(model || preferenceValue("model"));
    if (selectedAgent) query.set("agent", selectedAgent);
    if (selectedModel) query.set("model", selectedModel);
    if (refresh) query.set("refresh", "1");
    settingsLoading = true;
    renderSettingsControls();
    try {
      const data = await api("/api/chat/settings-catalog?" + query.toString(), { timeoutMs: 30000 });
      if (projectPath() !== expected) return;
      settingsCatalog = {
        agents: Array.isArray(data.agents) ? data.agents : [],
        models: Array.isArray(data.models) ? data.models : [],
        modes: Array.isArray(data.modes) ? data.modes : [],
        reasoning: Array.isArray(data.reasoning) ? data.reasoning : [],
        workflows: Array.isArray(data.workflows) ? data.workflows : [],
        features: data.features && typeof data.features === "object" ? data.features : {},
        default_agent: String(data.default_agent || ""),
      };
    } catch (error) {
      if (projectPath() !== expected) return;
      showError?.(error.message, "Project Chat settings unavailable");
      settingsCatalog = { ...settingsCatalog, models: [], modes: [], reasoning: [] };
    } finally {
      if (projectPath() === expected) {
        settingsLoading = false;
        renderSettingsControls();
      }
    }
  }

  function addOption(select, value, label, { disabled = false } = {}) {
    const option = document.createElement("option");
    option.value = String(value ?? "");
    option.textContent = String(label ?? value ?? "");
    option.disabled = !!disabled;
    select.appendChild(option);
    return option;
  }

  function fillSelect(select, rows, saved, emptyLabel, mapper = (row) => [row, row]) {
    if (!select) return;
    select.innerHTML = "";
    addOption(select, "", emptyLabel);
    for (const row of rows) {
      const [value, label, disabled] = mapper(row);
      addOption(select, value, label, { disabled });
    }
    const values = [...select.options].map((option) => option.value);
    if (saved && !values.includes(saved)) addOption(select, saved, saved + " · unavailable", { disabled: true });
    select.value = values.includes(saved) || !saved ? saved : saved;
    select.disabled = settingsLoading || !project;
  }

  function modeRows() {
    return settingsCatalog.modes.filter((row) => row && row.supported !== false);
  }

  function renderSettingsControls() {
    const agent = byId("projectChatAgentSelect");
    const model = byId("projectChatModelSelect");
    const quick = byId("projectChatModeQuick");
    const reasoning = byId("projectChatReasoningSelect");
    const workflow = byId("projectChatWorkflowSelect");
    const savedAgent = preferenceValue("agent");
    const savedModel = preferenceValue("model");
    const savedMode = preferenceValue("mode", "auto");
    const savedReasoning = preferenceValue("reasoning");
    const savedWorkflow = preferenceValue("workflow");

    fillSelect(
      agent,
      settingsCatalog.agents,
      savedAgent,
      settingsCatalog.default_agent ? "Default · " + settingsCatalog.default_agent : "Runner default",
    );
    fillSelect(model, settingsCatalog.models, savedModel, "Agent default");
    fillSelect(
      quick,
      modeRows(),
      savedMode,
      "Mode",
      (row) => [row.id, String(row.id || "").toUpperCase(), false],
    );
    fillSelect(
      reasoning,
      settingsCatalog.reasoning,
      savedReasoning,
      "Model default",
      (row) => [row.id, row.label || row.id, false],
    );
    fillSelect(
      workflow,
      settingsCatalog.workflows,
      savedWorkflow,
      "Project default",
      (row) => [row.path, row.name + (row.scope ? " · " + row.scope : ""), false],
    );
    const selectedMode = modeRows().find((row) => row.id === savedMode);
    if (quick) {
      quick.title = selectedMode
        ? selectedMode.description + (selectedMode.unsafe ? " · Automatically approves tools." : "")
        : "Permission / approval mode";
    }
    const askCapability = byId("projectChatAskCapability");
    const askDescription = byId("projectChatAskDescription");
    const askSupported = settingsCatalog.features?.ask === true;
    if (askCapability) askCapability.textContent = settingsLoading ? "Checking…" : (askSupported ? "Native" : "Unavailable");
    if (askDescription) {
      askDescription.textContent = settingsCatalog.features?.detail || "Native Agent clarification transport";
      askDescription.title = askDescription.textContent;
    }
    const settingsButton = byId("projectChatSettingsButton");
    if (settingsButton) settingsButton.disabled = settingsLoading || !project;
  }

  function positionSettingsPopover() {
    const panel = byId("projectChatSettingsPopover");
    const button = byId("projectChatSettingsButton");
    if (!panel || !button || panel.hidden) return;
    const rect = button.getBoundingClientRect();
    const pad = 12;
    const gap = 7;
    const width = panel.getBoundingClientRect().width || 430;
    const height = panel.getBoundingClientRect().height || 420;
    const left = Math.max(pad, Math.min(window.innerWidth - width - pad, rect.right - width));
    let top = rect.bottom + gap;
    if (top + height > window.innerHeight - pad) top = Math.max(pad, rect.top - height - gap);
    panel.style.left = Math.round(left) + "px";
    panel.style.top = Math.round(top) + "px";
  }

  function closeSettingsPopover() {
    const panel = byId("projectChatSettingsPopover");
    const button = byId("projectChatSettingsButton");
    if (panel) panel.hidden = true;
    if (button) button.setAttribute("aria-expanded", "false");
  }

  function toggleSettingsPopover(event) {
    event?.stopPropagation();
    const panel = byId("projectChatSettingsPopover");
    const button = byId("projectChatSettingsButton");
    if (!panel || !button || !project) return;
    const opening = panel.hidden;
    if (!opening) return closeSettingsPopover();
    panel.hidden = false;
    button.setAttribute("aria-expanded", "true");
    renderSettingsControls();
    requestAnimationFrame(positionSettingsPopover);
  }

  function queuePreferenceAction(action) {
    const run = async () => action();
    preferenceAction = preferenceAction.then(run, run);
    return preferenceAction;
  }

  async function savePreferencePatch(patch, { refreshCatalog = false, refreshCapabilities = false } = {}) {
    const path = projectPath();
    if (!path) return;
    try {
      const data = await api("/api/project/preferences", {
        method: "POST",
        body: JSON.stringify({ project: path, ...patch }),
      });
      if (projectPath() !== path) return;
      preferences = normalizePreferences(data);
      onPreferencesChanged?.(data);
      renderPreferences();
      if (refreshCatalog) await refreshSettingsCatalog({ refresh: true });
      else renderSettingsControls();
      if (refreshCapabilities) await refreshAgentCapabilities({ refresh: true });
    } catch (error) {
      showError?.(error.message, "Project preference update failed");
      await refreshSettingsCatalog({ refresh: true }).catch(() => {});
    }
  }

  async function changeAgent(value) {
    const nextAgent = String(value || "");
    const catalogQueryAgent = nextAgent || settingsCatalog.default_agent;
    let nextMode = "auto";
    try {
      const path = projectPath();
      const query = new URLSearchParams({ project: path, agent: catalogQueryAgent, refresh: "1" });
      const data = await api("/api/chat/settings-catalog?" + query.toString(), { timeoutMs: 30000 });
      const modes = Array.isArray(data.modes) ? data.modes.filter((row) => row.supported !== false) : [];
      nextMode = modes.some((row) => row.id === "auto")
        ? "auto"
        : modes.some((row) => row.id === "read")
          ? "read"
          : String(modes[0]?.id || "auto");
    } catch (_) {}
    await savePreferencePatch(
      { agent: nextAgent, model: "", mode: nextMode, reasoning: "" },
      { refreshCatalog: true, refreshCapabilities: true },
    );
  }

  async function changeModel(value) {
    const selectedModel = String(value || "");
    const agent = preferenceValue("agent") || settingsCatalog.default_agent;
    let nextReasoning = "";
    try {
      const query = new URLSearchParams({ project: projectPath(), agent, model: selectedModel, refresh: "1" });
      const data = await api("/api/chat/settings-catalog?" + query.toString(), { timeoutMs: 30000 });
      const options = Array.isArray(data.reasoning) ? data.reasoning : [];
      const current = preferenceValue("reasoning");
      nextReasoning = options.some((row) => row.id === current)
        ? current
        : String(options.find((row) => row.default)?.id || "");
    } catch (_) {}
    await savePreferencePatch(
      { model: selectedModel, reasoning: nextReasoning },
      { refreshCatalog: true, refreshCapabilities: true },
    );
  }

  function suggestionQuery() {
    const value = String(byId("projectChatInput")?.value || "");
    if (!value || /\s/.test(value)) return null;
    const prefix = value[0];
    if (prefix !== "/" && prefix !== "@") return null;
    return { prefix, query: value.slice(1).toLowerCase() };
  }

  function visibleSuggestions() {
    const context = suggestionQuery();
    if (context === null) return [];
    const source = context.prefix === "@" ? runnerCapabilities : agentCapabilities;
    return source.filter((item) => {
      const haystack = [item.token, item.name, item.description, item.source, item.kind]
        .map((value) => String(value || "").toLowerCase()).join(" ");
      return haystack.includes(context.query);
    });
  }

  function renderSuggestions() {
    const panel = byId("projectChatSuggest");
    const list = byId("projectChatSuggestList");
    const retry = byId("projectChatSuggestRetry");
    if (!panel || !list) return;
    const context = suggestionQuery();
    if (context === null) {
      panel.hidden = true;
      return;
    }
    const isRunner = context.prefix === "@";
    const title = byId("projectChatSuggestTitle");
    const hint = title?.parentElement?.querySelector("small");
    if (title) title.textContent = isRunner ? tr("chat.runner_suggestions", "Runner Commands / Prompts") : tr("chat.agent_suggestions", "Agent Skills / Commands");
    if (hint) hint.textContent = isRunner ? tr("chat.runner_hint", "@ = AI Task Runner") : tr("chat.agent_hint", "/ = selected Agent");
    const error = isRunner ? runnerCapabilitiesError : capabilitiesError;
    panel.hidden = false;
    if (retry) {
      retry.hidden = !error || isRunner;
      retry.textContent = tr("chat.retry", "Retry");
    }
    list.innerHTML = "";
    if (error) {
      const empty = document.createElement("div");
      empty.className = "project-chat-suggest-empty";
      empty.textContent = error;
      list.appendChild(empty);
      return;
    }
    const values = visibleSuggestions();
    if (!values.length) {
      const empty = document.createElement("div");
      empty.className = "project-chat-suggest-empty";
      empty.textContent = suggestionQuery()?.prefix === "@"
        ? tr("chat.no_runner_suggestions", "No Runner Command / Prompt matches.")
        : tr("chat.no_agent_suggestions", "No Agent Skill / Command matches.");
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
      description.textContent = item.description || (
        item.kind === "skill" ? "Agent Skill"
          : item.kind === "runner_command" ? "Runner command"
          : item.kind === "prompt" ? "Prompt asset"
          : "Agent command"
      );
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

  async function refreshChatEvents() {
    const path = projectPath();
    const session = activeSessionId;
    if (!path || !session) {
      eventCursor = 0;
      return { events: [], reset_required: false };
    }
    const expectedProject = path;
    const expectedSession = session;
    const data = await api(
      "/api/chat/events?project=" + encodeURIComponent(path) +
      "&session_id=" + encodeURIComponent(session) +
      "&after=" + encodeURIComponent(String(eventCursor)),
      { timeoutMs: 15000 }
    );
    if (projectPath() !== expectedProject || activeSessionId !== expectedSession) {
      return { events: [], reset_required: false };
    }
    const rows = Array.isArray(data.events) ? data.events : [];
    eventCursor = Number(data.cursor || 0);
    const types = new Set(rows.map((item) => String(item?.type || "")));
    if (data.reset_required || types.has("message_completed") || types.has("message_delta")) {
      await refreshMessages();
    }
    if (types.has("capabilities_updated")) {
      await Promise.all([
        refreshSettingsCatalog(),
        refreshAgentCapabilities({ refresh: true }),
        refreshRunnerCapabilities(),
      ]);
    }
    return data;
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
        await refreshChatEvents();
        await Promise.all([refreshQueue(), refreshAsk()]);
      } catch (_) {}
    }, 900);
  }

  function renderTurnState() {
    const status = byId("projectChatTurnStatus");
    const stop = byId("projectChatStopButton");
    const send = byId("projectChatSendButton");
    const input = byId("projectChatInput");
    if (!queueBusy) turnCancelPending = false;
    if (status) status.hidden = !queueBusy;
    if (stop) stop.disabled = !project || !activeSessionId || !queueBusy || turnCancelPending;
    if (send) {
      send.disabled = !project;
      send.setAttribute("aria-busy", String(queueBusy));
      send.textContent = queueBusy ? tr("chat.queue", "Queue") : tr("chat.send", "Send");
      send.title = queueBusy ? tr("chat.queue_hint", "Queue for next turn (Ctrl+Q)") : tr("chat.send_hint", "Send message");
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
      if (item.queue_item_id === editingQueueId) {
        row.classList.add("editing");
        const editor = document.createElement("div");
        editor.className = "project-chat-queue-editor";
        const input = document.createElement("textarea");
        input.rows = 2;
        input.value = editingQueueValue;
        input.setAttribute("aria-label", tr("chat.queued_message", "Queued message"));
        input.oninput = () => {
          editingQueueValue = input.value;
          if (editingQueueError && input.value.trim()) {
            editingQueueError = "";
            renderQueue();
            requestAnimationFrame(() => {
              const next = byId("projectChatQueueList")?.querySelector(".project-chat-queue-item.editing textarea");
              if (next) { next.focus(); next.selectionStart = next.selectionEnd = next.value.length; }
            });
          }
        };
        input.onkeydown = (event) => {
          if (event.key === "Escape") {
            event.preventDefault();
            cancelQueueEdit();
          } else if (event.key === "Enter" && (event.ctrlKey || event.metaKey)) {
            event.preventDefault();
            void saveQueueEdit(item);
          }
        };
        editor.appendChild(input);
        if (editingQueueError) {
          const error = document.createElement("div");
          error.className = "project-chat-queue-error";
          error.textContent = editingQueueError;
          editor.appendChild(error);
        }
        const actions = document.createElement("span");
        actions.className = "project-chat-queue-actions";
        const save = document.createElement("button");
        save.type = "button";
        save.textContent = tr("chat.queue_save", "Save");
        save.onclick = () => void saveQueueEdit(item);
        const cancel = document.createElement("button");
        cancel.type = "button";
        cancel.textContent = tr("chat.queue_cancel", "Cancel");
        cancel.onclick = cancelQueueEdit;
        actions.append(save, cancel);
        row.append(editor, actions);
        requestAnimationFrame(() => input.focus());
      } else {
        const copy = document.createElement("div");
        copy.className = "project-chat-queue-copy";
        copy.textContent = String(item.content || "");
        copy.title = String(item.content || "");
        const actions = document.createElement("span");
        actions.className = "project-chat-queue-actions";
        const edit = document.createElement("button");
        edit.type = "button";
        edit.textContent = tr("chat.queue_edit", "Edit");
        edit.onclick = () => beginQueueEdit(item);
        const remove = document.createElement("button");
        remove.type = "button";
        remove.textContent = tr("chat.queue_delete", "Delete");
        remove.onclick = () => void deleteQueueItem(item);
        actions.append(edit, remove);
        row.append(copy, actions);
      }
      list.appendChild(row);
    }
  }

  function beginQueueEdit(item) {
    editingQueueId = String(item.queue_item_id || "");
    editingQueueValue = String(item.content || "");
    editingQueueError = "";
    renderQueue();
  }

  function cancelQueueEdit() {
    editingQueueId = "";
    editingQueueValue = "";
    editingQueueError = "";
    renderQueue();
  }

  async function saveQueueEdit(item) {
    const next = String(editingQueueValue || "").trim();
    if (!next) {
      editingQueueError = tr("chat.queue_empty", "Queued message cannot be empty.");
      renderQueue();
      return;
    }
    if (next === String(item.content || "").trim()) {
      cancelQueueEdit();
      return;
    }
    try {
      const data = await api("/api/chat/queue/update", {
        method: "POST",
        body: JSON.stringify({
          project: projectPath(),
          session_id: activeSessionId,
          queue_item_id: item.queue_item_id,
          message: next,
        }),
      });
      editingQueueId = "";
      editingQueueValue = "";
      editingQueueError = "";
      applyQueueState(data);
      showToast?.("Queue updated");
    } catch (error) {
      editingQueueError = String(error?.message || "Queue update failed");
      renderQueue();
      showError?.(error.message, "Queue update failed");
    }
  }

  function applyQueueState(data = {}) {
    queueItems = Array.isArray(data.items) ? data.items : [];
    if (editingQueueId && !queueItems.some((item) => item.queue_item_id === editingQueueId)) {
      editingQueueId = "";
      editingQueueValue = "";
      editingQueueError = "";
    }
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

  async function deleteQueueItem(item) {
    try {
      const data = await api("/api/chat/queue/delete", {
        method: "POST",
        body: JSON.stringify({
          project: projectPath(),
          session_id: activeSessionId,
          queue_item_id: item.queue_item_id,
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
    renderSettingsControls();
  }

  function activeSession() {
    return sessions.find((session) => session.session_id === activeSessionId) || null;
  }

  function renderSessions() {
    const select = byId("projectChatSessionSelect");
    if (select) {
      select.innerHTML = "";
      for (const session of sessions) {
        const option = document.createElement("option");
        option.value = session.session_id;
        option.textContent = session.title || "New Chat";
        option.title = option.textContent;
        select.appendChild(option);
      }
      if (activeSessionId) select.value = activeSessionId;
      select.disabled = !project || sessions.length === 0;
    }
    const current = activeSession();
    const rename = byId("renameProjectChatButton");
    const remove = byId("deleteProjectChatButton");
    if (rename) rename.disabled = !project || !current;
    if (remove) remove.disabled = !project || !current;
  }

  function activeDrafts() {
    return taskDraftsBySession.get(activeSessionId) || [];
  }

  function findTaskDraft(sessionId, draftId) {
    const rows = taskDraftsBySession.get(sessionId) || [];
    return rows.find((row) => row.draft_id === draftId) || null;
  }

  function updateTaskDraftModel(sessionId, draftId, nextDraft) {
    const rows = taskDraftsBySession.get(sessionId) || [];
    const index = rows.findIndex((row) => row.draft_id === draftId);
    if (index < 0) return false;
    const value = globalThis.structuredClone
      ? globalThis.structuredClone(nextDraft)
      : JSON.parse(JSON.stringify(nextDraft));
    const next = rows.slice();
    next[index] = { ...rows[index], draft: value };
    taskDraftsBySession.set(sessionId, next);
    return true;
  }

  function renderTaskDraftCard(entry, root) {
    const card = document.createElement("article");
    card.className = "message project-chat-message assistant project-chat-task-draft";
    card.dataset.draftId = entry.draft_id;
    card.dataset.sessionId = String(entry.session_id || activeSessionId || "");
    const draft = entry.draft || {};
    const head = document.createElement("div");
    head.className = "project-chat-task-draft-head";
    const title = document.createElement("div");
    title.innerHTML = "<small>" + tr("chat.task_draft", "TASK DRAFT") + "</small>";
    const strong = document.createElement("strong");
    strong.textContent = String(draft.title || "TaskDraft");
    title.appendChild(strong);
    const meta = document.createElement("span");
    meta.textContent = trf("chat.item_count", { count: Array.isArray(draft.items) ? draft.items.length : 0 }, (Array.isArray(draft.items) ? draft.items.length : 0) + " item(s)");
    head.append(title, meta);

    const items = document.createElement("div");
    items.className = "project-chat-task-draft-items";
    for (const [index, row] of (Array.isArray(draft.items) ? draft.items : []).entries()) {
      const item = document.createElement("div");
      item.className = "project-chat-task-draft-item";
      const label = document.createElement("strong");
      label.textContent = (index + 1) + ". " + String(row.title || "Task");
      const prompt = document.createElement("p");
      prompt.textContent = String(row.prompt || "");
      item.append(label, prompt);
      items.appendChild(item);
    }

    const actions = document.createElement("div");
    actions.className = "project-chat-task-draft-actions";
    const edit = document.createElement("button");
    edit.type = "button";
    edit.textContent = tr("chat.queue_edit", "Edit");
    edit.setAttribute("aria-label", tr("chat.edit_draft", "Edit Draft"));
    edit.onclick = () => {
      const originProject = projectPath();
      const viewSession = activeSessionId;
      const current = findTaskDraft(viewSession, entry.draft_id);
      if (!current) return;
      const ownerSession = String(current.session_id || viewSession || "");
      if (!ownerSession) return;
      openTaskDraft?.({
        project: originProject,
        draft: current.draft,
        workflows: settingsCatalog.workflows,
        returnFocus: edit,
        onSave: async (nextDraft) => {
          const data = await api("/api/chat/task-draft/update", {
            method: "POST",
            body: JSON.stringify({
              project: originProject,
              session_id: ownerSession,
              draft_id: entry.draft_id,
              draft: nextDraft,
            }),
          });
          if (!updateTaskDraftModel(viewSession, entry.draft_id, data.draft)) return;
          if (projectPath() === originProject && activeSessionId === viewSession) renderMessages();
        },
      });
    };
    const create = document.createElement("button");
    create.type = "button";
    create.className = "primary";
    create.textContent = tr("chat.create_task", "Create Task");
    create.onclick = () => void createTaskFromDraft(entry.draft_id, create);
    const dismiss = document.createElement("button");
    dismiss.type = "button";
    dismiss.textContent = tr("chat.dismiss", "Dismiss");
    dismiss.onclick = () => void dismissTaskDraft(entry.draft_id);
    actions.append(edit, create, dismiss);
    card.append(head, items, actions);
    root.appendChild(card);
  }

  function currentAskQuestion() {
    const questions = Array.isArray(activeAsk?.questions) ? activeAsk.questions : [];
    return questions[askIndex] || null;
  }

  function askAnswerValid(question) {
    if (!question) return false;
    const value = askAnswers[question.question_id];
    if (question.kind === "text") return !!String(value || "").trim();
    if (question.kind === "multi_choice") {
      const values = value && typeof value === "object" && Array.isArray(value.values) ? value.values : [];
      return values.length > 0 || !!String(value?.other || "").trim();
    }
    if (value && typeof value === "object" && "other" in value) return !!String(value.other || "").trim();
    return !!(value && typeof value === "object" && String(value.value || "").trim());
  }

  function renderAskCard(root) {
    if (!activeAsk || activeAsk.status !== "waiting") return;
    const questions = Array.isArray(activeAsk.questions) ? activeAsk.questions : [];
    const question = currentAskQuestion();
    if (!question) return;

    const card = document.createElement("article");
    card.className = "message project-chat-message assistant project-chat-ask";
    card.dataset.askId = activeAsk.ask_id;

    const head = document.createElement("div");
    head.className = "project-chat-ask-head";
    const heading = document.createElement("div");
    const badge = document.createElement("small");
    badge.textContent = "ASK";
    const title = document.createElement("strong");
    title.textContent = String(question.header || "Question");
    heading.append(badge, title);
    const progress = document.createElement("span");
    progress.textContent = String(askIndex + 1) + " / " + String(questions.length);
    head.append(heading, progress);

    const prompt = document.createElement("p");
    prompt.className = "project-chat-ask-prompt";
    prompt.textContent = String(question.prompt || "");

    const body = document.createElement("div");
    body.className = "project-chat-ask-body";
    if (question.kind === "multi_choice") {
      const selected = askAnswers[question.question_id];
      const values = Array.isArray(selected?.values) ? selected.values : [];
      for (const option of (Array.isArray(question.options) ? question.options : [])) {
        const button = document.createElement("button");
        button.type = "button";
        button.className = "project-chat-ask-option";
        button.classList.toggle("selected", values.includes(option.value));
        button.setAttribute("aria-pressed", String(values.includes(option.value)));
        const label = document.createElement("strong");
        label.textContent = String(option.label || option.value || "");
        button.appendChild(label);
        if (option.description) {
          const description = document.createElement("small");
          description.textContent = String(option.description);
          button.appendChild(description);
        }
        button.onclick = () => {
          const current = askAnswers[question.question_id];
          const nextValues = Array.isArray(current?.values) ? current.values.slice() : [];
          const index = nextValues.indexOf(option.value);
          if (index >= 0) nextValues.splice(index, 1);
          else nextValues.push(option.value);
          askAnswers = {
            ...askAnswers,
            [question.question_id]: {
              values: nextValues,
              ...(String(current?.other || "").trim() ? { other: String(current.other) } : {}),
            },
          };
          askError = "";
          renderMessages();
        };
        body.appendChild(button);
      }
      const other = document.createElement("button");
      other.type = "button";
      other.className = "project-chat-ask-option";
      other.classList.toggle("selected", !!(selected && typeof selected === "object" && "other" in selected));
      other.setAttribute("aria-pressed", String(!!(selected && typeof selected === "object" && "other" in selected)));
      other.textContent = tr("chat.ask_other", "Other / custom answer");
      other.onclick = () => {
        const current = askAnswers[question.question_id];
        askAnswers = {
          ...askAnswers,
          [question.question_id]: {
            values: Array.isArray(current?.values) ? current.values.slice() : [],
            other: String(current?.other || ""),
          },
        };
        askError = "";
        renderMessages();
      };
      body.appendChild(other);
      if (selected && typeof selected === "object" && "other" in selected) {
        const custom = document.createElement("textarea");
        custom.className = "project-chat-ask-input";
        custom.rows = 2;
        custom.placeholder = tr("chat.ask_other_placeholder", "Type another answer…");
        custom.setAttribute("aria-label", tr("chat.ask_custom_answer", "Custom answer"));
        custom.value = String(selected.other || "");
        custom.oninput = () => {
          askAnswers = {
            ...askAnswers,
            [question.question_id]: {
              values: Array.isArray(selected?.values) ? selected.values.slice() : [],
              other: custom.value,
            },
          };
          askError = "";
          const next = card.querySelector(".project-chat-ask-primary");
          if (next) next.disabled = !askAnswerValid(question);
        };
        body.appendChild(custom);
        requestAnimationFrame(() => custom.focus());
      }
    } else if (question.kind === "choice") {
      const selected = askAnswers[question.question_id];
      for (const option of (Array.isArray(question.options) ? question.options : [])) {
        const button = document.createElement("button");
        button.type = "button";
        button.className = "project-chat-ask-option";
        button.classList.toggle("selected", selected?.value === option.value);
        const label = document.createElement("strong");
        label.textContent = String(option.label || option.value || "");
        button.appendChild(label);
        if (option.description) {
          const description = document.createElement("small");
          description.textContent = String(option.description);
          button.appendChild(description);
        }
        button.onclick = () => {
          askAnswers = { ...askAnswers, [question.question_id]: { value: option.value } };
          askError = "";
          renderMessages();
        };
        body.appendChild(button);
      }
      const other = document.createElement("button");
      other.type = "button";
      other.className = "project-chat-ask-option";
      other.classList.toggle("selected", !!(selected && typeof selected === "object" && "other" in selected));
      other.textContent = tr("chat.ask_other", "Other / custom answer");
      other.onclick = () => {
        const current = askAnswers[question.question_id];
        const keep = current && typeof current === "object" && "other" in current ? String(current.other || "") : "";
        askAnswers = { ...askAnswers, [question.question_id]: { other: keep } };
        askError = "";
        renderMessages();
      };
      body.appendChild(other);
      if (selected && typeof selected === "object" && "other" in selected) {
        const custom = document.createElement("textarea");
        custom.className = "project-chat-ask-input";
        custom.rows = 2;
        custom.placeholder = tr("chat.ask_answer_placeholder", "Type your answer…");
        custom.setAttribute("aria-label", tr("chat.ask_custom_answer", "Custom answer"));
        custom.value = String(selected.other || "");
        custom.oninput = () => {
          askAnswers = { ...askAnswers, [question.question_id]: { other: custom.value } };
          askError = "";
          const next = card.querySelector(".project-chat-ask-primary");
          if (next) next.disabled = !askAnswerValid(question);
        };
        body.appendChild(custom);
        requestAnimationFrame(() => custom.focus());
      }
    } else {
      const input = document.createElement("textarea");
      input.className = "project-chat-ask-input";
      input.rows = 3;
      input.placeholder = tr("chat.ask_answer_placeholder", "Type your answer…");
      input.setAttribute("aria-label", tr("chat.ask_text_answer", "Ask text answer"));
      input.value = String(askAnswers[question.question_id] || "");
      input.oninput = () => {
        askAnswers = { ...askAnswers, [question.question_id]: input.value };
        askError = "";
        const next = card.querySelector(".project-chat-ask-primary");
        if (next) next.disabled = !askAnswerValid(question);
      };
      body.appendChild(input);
    }

    if (askError) {
      const error = document.createElement("div");
      error.className = "project-chat-ask-error";
      error.textContent = askError;
      body.appendChild(error);
    }

    const actions = document.createElement("div");
    actions.className = "project-chat-ask-actions";
    const cancel = document.createElement("button");
    cancel.type = "button";
    cancel.textContent = tr("chat.ask_cancel", "Cancel");
    cancel.onclick = () => void cancelAsk();
    const next = document.createElement("button");
    next.type = "button";
    next.className = "primary project-chat-ask-primary";
    next.textContent = askIndex + 1 === questions.length ? tr("chat.ask_submit", "Submit") : tr("chat.ask_next", "Next");
    next.disabled = !askAnswerValid(question);
    next.onclick = () => {
      if (!askAnswerValid(question)) {
        askError = tr("chat.ask_required", "Answer this question before continuing.");
        renderMessages();
        return;
      }
      if (askIndex + 1 < questions.length) {
        askIndex += 1;
        askError = "";
        renderMessages();
        return;
      }
      void submitAsk();
    };
    actions.append(cancel, next);
    card.append(head, prompt, body, actions);
    root.appendChild(card);
  }

  function applyAskState(data = {}) {
    const next = data?.ask && data.ask.status === "waiting" ? data.ask : null;
    if (next?.ask_id !== activeAsk?.ask_id) {
      askIndex = 0;
      askAnswers = {};
      askError = "";
    }
    activeAsk = next;
    renderMessages();
  }

  async function refreshAsk() {
    const path = projectPath();
    if (!path || !activeSessionId) {
      activeAsk = null;
      return renderMessages();
    }
    const expectedProject = path;
    const expectedSession = activeSessionId;
    const data = await api(
      "/api/chat/ask?project=" + encodeURIComponent(path) +
      "&session_id=" + encodeURIComponent(expectedSession),
      { timeoutMs: 15000 },
    );
    if (projectPath() !== expectedProject || activeSessionId !== expectedSession) return;
    applyAskState(data);
  }

  async function submitAsk() {
    const path = projectPath();
    const session = activeSessionId;
    const ask = activeAsk;
    if (!path || !session || !ask) return;
    try {
      const data = await api("/api/chat/ask/submit", {
        method: "POST",
        body: JSON.stringify({
          project: path,
          session_id: session,
          ask_id: ask.ask_id,
          answers: askAnswers,
          request_id: requestId(),
        }),
      });
      if (projectPath() !== path || activeSessionId !== session || activeAsk?.ask_id !== ask.ask_id) return;
      applyAskState(data);
      applyQueueState(data);
      await Promise.all([refreshMessages(), refreshQueue()]);
      showToast?.("Answer submitted");
    } catch (error) {
      askError = String(error?.message || "Ask submit failed");
      renderMessages();
      showError?.(error.message, "Ask submit failed");
    }
  }

  async function cancelAsk() {
    const path = projectPath();
    const session = activeSessionId;
    const ask = activeAsk;
    if (!path || !session || !ask) return;
    try {
      const data = await api("/api/chat/ask/cancel", {
        method: "POST",
        body: JSON.stringify({
          project: path,
          session_id: session,
          ask_id: ask.ask_id,
          request_id: requestId(),
        }),
      });
      if (projectPath() !== path || activeSessionId !== session || activeAsk?.ask_id !== ask.ask_id) return;
      applyAskState(data);
      applyQueueState(data);
      await Promise.all([refreshMessages(), refreshQueue()]);
      showToast?.("Question cancelled");
    } catch (error) {
      askError = String(error?.message || "Ask cancel failed");
      renderMessages();
      showError?.(error.message, "Ask cancel failed");
    }
  }

  function renderMessages(rows = messageRows) {
    messageRows = Array.isArray(rows) ? rows : [];
    const root = byId("projectChatMessages");
    const empty = byId("projectChatEmptyMessages");
    if (!root || !empty) return;
    root.querySelectorAll(".project-chat-message").forEach((node) => node.remove());
    const drafts = activeDrafts();
    empty.hidden = messageRows.length > 0 || drafts.length > 0 || !!activeAsk;
    for (const message of messageRows) {
      const item = document.createElement("article");
      const role = ["user", "assistant", "system"].includes(message.role) ? message.role : "assistant";
      item.className = "message project-chat-message " + role;
      const body = document.createElement("div");
      body.className = "message-body";
      body.textContent = String(message.content || "");
      item.appendChild(body);
      root.appendChild(item);
    }
    for (const draft of drafts) renderTaskDraftCard(draft, root);
    renderAskCard(root);
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
    eventCursor = 0;
    renderSessions();
    await Promise.all([refreshMessages(), refreshQueue(), refreshAsk()]);
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

  function taskCommand(text) {
    const match = String(text || "").match(/^@(task|task-single|task-list)(?:\s+([\s\S]*))?$/i);
    if (!match) return null;
    const mode = match[1].toLowerCase() === "task-single"
      ? "single"
      : match[1].toLowerCase() === "task-list"
        ? "list"
        : "auto";
    return { mode, spec: String(match[2] || "").trim(), token: "@" + match[1].toLowerCase() };
  }

  function goalCommand(text) {
    const match = String(text || "").match(/^@goal(?:\s+([\s\S]*))?$/i);
    if (!match) return null;
    return { spec: String(match[1] || "").trim() };
  }

  async function dismissTaskDraft(draftId) {
    const path = projectPath();
    const viewSession = activeSessionId;
    const entry = findTaskDraft(viewSession, draftId);
    const ownerSession = String(entry?.session_id || viewSession || "");
    if (!path || !viewSession || !ownerSession) return;
    try {
      await api("/api/chat/task-draft/dismiss", {
        method: "POST",
        body: JSON.stringify({
          project: path,
          session_id: ownerSession,
          draft_id: draftId,
        }),
      });
      const rows = (taskDraftsBySession.get(viewSession) || []).filter((row) => row.draft_id !== draftId);
      taskDraftsBySession.set(viewSession, rows);
      if (projectPath() === path && activeSessionId === viewSession) await refreshMessages();
    } catch (error) {
      showError?.(error.message, "Dismiss TaskDraft failed");
    }
  }

  async function createTaskFromDraft(draftId, returnFocus = null) {
    const path = projectPath();
    const viewSession = activeSessionId;
    if (!path || !viewSession) return;
    const entry = findTaskDraft(viewSession, draftId);
    if (!entry) {
      showError?.("TaskDraft is no longer available in this Chat.", "Create Task failed");
      return;
    }
    const ownerSession = String(entry.session_id || viewSession || "");
    if (!ownerSession) return;
    try {
      const task = await api("/api/tasks/create-from-draft", {
        method: "POST",
        body: JSON.stringify({
          project: path,
          session_id: ownerSession,
          draft_id: entry.draft_id,
          request_id: "create-" + entry.draft_id,
        }),
      });
      try {
        await api("/api/chat/task-draft/dismiss", {
          method: "POST",
          body: JSON.stringify({
            project: path,
            session_id: ownerSession,
            draft_id: entry.draft_id,
          }),
        });
      } catch (_) {}
      const rows = (taskDraftsBySession.get(viewSession) || []).filter((row) => row.draft_id !== entry.draft_id);
      taskDraftsBySession.set(viewSession, rows);
      if (projectPath() !== path || activeSessionId !== viewSession) return;
      await refreshMessages();
      showToast?.("Task created · New · " + String(task.title || task.task_id || ""));
      openTask?.(task, { returnFocus, workflows: settingsCatalog.workflows });
    } catch (error) {
      showError?.(error.message, "Create Task failed");
    }
  }

  async function openAskDemo() {
    const path = projectPath();
    const session = activeSessionId;
    if (!path || !session) return;
    const data = await api("/api/chat/ask/demo", {
      method: "POST",
      body: JSON.stringify({
        project: path,
        session_id: session,
        request_id: requestId(),
      }),
    });
    if (projectPath() !== path || activeSessionId !== session) return;
    applyAskState(data);
  }

  async function runGoal(command, returnFocus = null) {
    if (!command.spec) {
      showError?.("Usage: @goal <spec>", "Goal spec required");
      return;
    }
    const path = projectPath();
    if (!path) return;
    const task = await api("/api/tasks/goal", {
      method: "POST",
      body: JSON.stringify({
        project: path,
        spec: command.spec,
        request_id: requestId(),
      }),
    });
    if (projectPath() !== path) return;
    if (task.goal_run_started) {
      showToast?.("Goal started · Ongoing · " + String(task.title || task.task_id || ""));
    } else {
      showError?.(
        task.goal_run_error || "Task was created but Runner did not start.",
        "Goal created · Run needs attention",
      );
    }
    openTask?.(task, { returnFocus, workflows: settingsCatalog.workflows });
  }

  async function generateTaskDraft(command) {
    if (!command.spec) {
      showError?.("Usage: " + command.token + " <spec>", "TaskDraft spec required");
      return;
    }
    const path = projectPath();
    const session = activeSessionId;
    const data = await api("/api/chat/task-draft", {
      method: "POST",
      body: JSON.stringify({
        project: path,
        session_id: session,
        mode: command.mode,
        spec: command.spec,
        request_id: requestId(),
      }),
    });
    if (projectPath() !== path || activeSessionId !== session) return;
    const rows = [...activeDrafts(), data];
    taskDraftsBySession.set(session, rows);
    await refreshMessages();
  }

  async function sendMessage() {
    const input = byId("projectChatInput");
    const text = String(input?.value || "").trim();
    if (!project || !activeSessionId || !text) return;
    const command = taskCommand(text);
    const goal = goalCommand(text);
    const askDemo = /^@ask-demo\s*$/i.test(text);
    if (goal && !goal.spec) {
      showError?.("Usage: @goal <spec>", "Goal spec required");
      return;
    }
    input.value = "";
    autosizeTextarea?.(input, { minHeight: 46, maxHeight: 180 });
    panelHideSuggestions();
    if (goal) {
      try {
        await runGoal(goal, input);
      } catch (error) {
        showError?.(error.message, "Start Goal failed");
      } finally {
        input?.focus();
      }
      return;
    }
    if (askDemo) {
      try {
        await openAskDemo();
      } catch (error) {
        showError?.(error.message, "Ask demo failed");
      } finally {
        input?.focus();
      }
      return;
    }
    if (command) {
      try {
        await generateTaskDraft(command);
      } catch (error) {
        showError?.(error.message, "TaskDraft generation failed");
      } finally {
        input?.focus();
      }
      return;
    }

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
      await Promise.all([refreshMessages(), refreshAsk()]);
      if (data.status === "error" && data.error) {
        showError?.(String(data.error), "Chat turn failed");
      }
    } catch (error) {
      if (projectPath() !== expectedProject || activeSessionId !== expectedSession) return;
      await Promise.all([
        refreshMessages().catch(() => {}),
        refreshQueue().catch(() => {}),
        refreshAsk().catch(() => {}),
      ]);
      showError?.(error.message, "Chat turn failed");
    } finally {
      if (projectPath() === expectedProject && activeSessionId === expectedSession) {
        input?.focus();
      }
    }
  }

  async function cancelTurn() {
    const expectedProject = projectPath();
    const expectedSession = activeSessionId;
    if (!expectedProject || !expectedSession || !queueBusy || turnCancelPending) return;
    turnCancelPending = true;
    renderTurnState();
    try {
      const data = await api("/api/chat/turn/cancel", {
        method: "POST",
        body: JSON.stringify({
          project: expectedProject,
          session_id: expectedSession,
          request_id: requestId(),
        }),
      });
      if (projectPath() !== expectedProject || activeSessionId !== expectedSession) return;
      applyQueueState(data);
      await Promise.all([refreshMessages(), refreshQueue(), refreshAsk()]);
    } catch (error) {
      if (projectPath() !== expectedProject || activeSessionId !== expectedSession) return;
      turnCancelPending = false;
      showError?.(error.message, "Stop Chat turn failed");
    } finally {
      if (projectPath() === expectedProject && activeSessionId === expectedSession) {
        renderTurnState();
      }
    }
  }

  async function createSessionRecord({ title = "" } = {}) {
    const path = projectPath();
    if (!path) throw new Error("Project is required");
    const data = await api("/api/chat/session/create", {
      method: "POST",
      body: JSON.stringify({ project: path, title: String(title || ""), request_id: requestId() }),
    });
    sessions = Array.isArray(data.sessions) ? data.sessions : sessions;
    activeSessionId = String(data.session_id || data.active_session_id || "");
    eventCursor = 0;
    renderSessions();
    await Promise.all([refreshMessages(), refreshQueue(), refreshAsk()]);
    return activeSessionId;
  }

  async function createSession() {
    try {
      await createSessionRecord();
      showToast?.("New Chat created");
    } catch (error) {
      showError?.(error.message, "Create Chat failed");
    }
  }

  async function openMergeChat({ title = "Merge Chat", prompt = "" } = {}) {
    const sessionId = await createSessionRecord({ title });
    const input = byId("projectChatInput");
    if (!input) return sessionId;
    input.value = String(prompt || "");
    autosizeTextarea?.(input, { minHeight: 46, maxHeight: 180 });
    suggestionIndex = 0;
    renderSuggestions();
    input.focus();
    return sessionId;
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
      eventCursor = 0;
      renderSessions();
      await Promise.all([refreshMessages(), refreshQueue(), refreshAsk()]);
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
      taskDraftsBySession.delete(session.session_id);
      activeSessionId = String(data.active_session_id || data.session_id || sessions[0]?.session_id || "");
      eventCursor = 0;
      renderSessions();
      await Promise.all([refreshMessages(), refreshQueue(), refreshAsk()]);
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
    eventCursor = 0;
    queueItems = [];
    queueBusy = false;
    messageRows = [];
    activeAsk = null;
    askIndex = 0;
    askAnswers = {};
    askError = "";
    renderPreferences();
    void Promise.all([
      refreshSettingsCatalog(),
      refreshAgentCapabilities(),
      refreshRunnerCapabilities(),
    ]);
    const newChat = byId("newProjectChatButton");
    if (newChat) newChat.disabled = !project;
    const newTask = byId("projectChatNewTaskButton");
    if (newTask) newTask.disabled = !project;
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
  byId("projectChatSessionSelect")?.addEventListener("change", (event) => {
    void selectSession(event.currentTarget.value);
  });
  byId("renameProjectChatButton")?.addEventListener("click", () => {
    const session = activeSession();
    if (session) void renameSession(session);
  });
  byId("deleteProjectChatButton")?.addEventListener("click", () => {
    const session = activeSession();
    if (session) void deleteSession(session);
  });
  byId("projectChatNewTaskButton")?.addEventListener("click", (event) => {
    openTaskCreateMenu?.({
      anchor: event.currentTarget,
      project: projectPath(),
      workflows: settingsCatalog.workflows,
      workflow: preferences.workflow,
    });
  });
  byId("projectChatSettingsButton")?.addEventListener("click", toggleSettingsPopover);
  byId("projectChatSettingsClose")?.addEventListener("click", closeSettingsPopover);
  byId("projectChatAgentSelect")?.addEventListener("change", (event) => {
    const value = event.currentTarget.value;
    void queuePreferenceAction(() => changeAgent(value));
  });
  byId("projectChatModelSelect")?.addEventListener("change", (event) => {
    const value = event.currentTarget.value;
    void queuePreferenceAction(() => changeModel(value));
  });
  byId("projectChatModeQuick")?.addEventListener("change", (event) => {
    const value = event.currentTarget.value;
    void queuePreferenceAction(() => savePreferencePatch({ mode: value }));
  });
  byId("projectChatReasoningSelect")?.addEventListener("change", (event) => {
    const value = event.currentTarget.value;
    void queuePreferenceAction(() => savePreferencePatch({ reasoning: value }));
  });
  byId("projectChatWorkflowSelect")?.addEventListener("change", (event) => {
    const value = event.currentTarget.value;
    void queuePreferenceAction(() => savePreferencePatch({ workflow: value }));
  });
  document.addEventListener("click", (event) => {
    const panel = byId("projectChatSettingsPopover");
    const button = byId("projectChatSettingsButton");
    if (panel && !panel.hidden && !panel.contains(event.target) && !button?.contains(event.target)) closeSettingsPopover();
  });
  window.addEventListener("resize", positionSettingsPopover);
  byId("projectChatSendButton")?.addEventListener("click", () => void sendMessage());
  byId("projectChatStopButton")?.addEventListener("click", () => void cancelTurn());
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
    if (
      queueBusy &&
      event.ctrlKey &&
      !event.altKey &&
      !event.metaKey &&
      event.key.toLowerCase() === "q" &&
      !event.isComposing
    ) {
      if (String(event.currentTarget.value || "").trim()) {
        event.preventDefault();
        void sendMessage();
      }
      return;
    }
    if (event.key === "Enter" && !event.shiftKey && !event.isComposing) {
      event.preventDefault();
      void sendMessage();
    }
  });
  byId("projectChatSuggestRetry")?.addEventListener("click", () => void refreshAgentCapabilities({ refresh: true }));
  window.addEventListener("app-language-changed", () => {
    renderPreferences();
    renderSessions();
    renderSuggestions();
    renderQueue();
    renderTurnState();
    renderMessages();
  });

  return {
    openProject,
    clearProject,
    refreshSessions,
    refreshMessages,
    refreshQueue,
    refreshAsk,
    renderPreferences,
    openMergeChat,
    activeSessionId: () => activeSessionId,
  };
}
