function runtimeProjection(task = {}) {
  return {
    runtime: task?.runner_runtime && typeof task.runner_runtime === "object" ? task.runner_runtime : {},
    run: task?.run && typeof task.run === "object" ? task.run : null,
  };
}

function hasRuntimeEvidence(task = {}) {
  const { runtime, run } = runtimeProjection(task);
  return !!(
    run
    || runtime.running
    || runtime.launching
    || runtime.has_state
    || runtime.resumable
    || runtime.completed
    || runtime.run_id
    || runtime.stage
    || runtime.last_error
    || runtime.console_snapshot_exists
    || (Array.isArray(runtime.cli_lines) && runtime.cli_lines.length)
    || String(runtime.stream || "").trim()
  );
}

function formatRuntimeTime(value) {
  if (!value) return "—";
  const raw = typeof value === "number" ? value * 1000 : Date.parse(String(value));
  const date = new Date(raw);
  return Number.isNaN(date.getTime()) ? String(value) : date.toLocaleString();
}

function appendRuntimeMeta(root, rows) {
  const list = document.createElement("dl");
  list.className = "task-runtime-meta";
  for (const [label, value] of rows) {
    const dt = document.createElement("dt");
    const dd = document.createElement("dd");
    dt.textContent = label;
    dd.textContent = value || "—";
    list.append(dt, dd);
  }
  root.appendChild(list);
  return list;
}

function renderEmpty({ body, tr, titleKey, titleFallback }) {
  const empty = document.createElement("section");
  empty.className = "task-workspace-empty-panel";
  const title = document.createElement("strong");
  title.textContent = tr(titleKey, titleFallback);
  const copy = document.createElement("p");
  copy.textContent = tr("task.no_runtime_copy", "Runtime data appears only after an explicit Run action.");
  empty.append(title, copy);
  body.appendChild(empty);
}

function appendRefreshError(panel, tr, refreshError) {
  if (!refreshError) return;
  const warning = document.createElement("p");
  warning.className = "task-runtime-error";
  warning.textContent = tr("task.runtime_refresh_failed", "Refresh failed") + ": " + refreshError;
  panel.appendChild(warning);
}

function renderRuntime({ body, task, tr, trf, refreshError }) {
  if (!hasRuntimeEvidence(task)) {
    renderEmpty({ body, tr, titleKey: "task.no_runtime", titleFallback: "No Runner runtime yet" });
    return;
  }
  const { runtime, run } = runtimeProjection(task);
  const panel = document.createElement("section");
  panel.id = "taskWorkspaceRuntimePanel";
  panel.className = "task-runtime-panel";

  const head = document.createElement("div");
  head.className = "task-runtime-head";
  const title = document.createElement("div");
  const titleStrong = document.createElement("strong");
  titleStrong.textContent = tr("task.runtime_title", "Runner Runtime");
  const titleSmall = document.createElement("small");
  titleSmall.textContent = runtime.run_id
    ? trf("task.runtime_run_id", { id: String(runtime.run_id) }, "Run {id}")
    : tr("task.runtime_canonical", "Canonical Task runtime projection");
  title.append(titleStrong, titleSmall);
  const badge = document.createElement("span");
  badge.className = "task-runtime-badge";
  badge.textContent = String(runtime.status || run?.phase || task.status || "idle").replaceAll("_", " ");
  head.append(title, badge);
  panel.appendChild(head);

  const total = Number(runtime.total || 0);
  const current = Number(runtime.current || 0);
  const itemCount = Array.isArray(task.items) ? task.items.length : 0;
  const completed = Number(task.completed_item_count || 0);
  const progress = total > 0
    ? String(current) + " / " + String(total)
    : String(Math.min(completed, itemCount)) + " / " + String(itemCount);
  appendRuntimeMeta(panel, [
    [tr("task.runtime_stage", "Stage"), String(runtime.stage || run?.phase || "—")],
    [tr("task.runtime_progress", "Progress"), progress],
    [tr("task.runtime_cycle", "Cycle"), runtime.cycle ? String(runtime.cycle) : "—"],
    [tr("task.runtime_task", "Task"), String(runtime.task || (run?.item_index != null ? "Item " + (Number(run.item_index) + 1) : "—"))],
    [tr("task.runtime_backend", "Backend"), String(runtime.effective_backend || runtime.backend || "—")],
    [tr("task.runtime_model", "Model"), String(runtime.effective_model || runtime.model || "—")],
    [tr("task.runtime_updated", "Last update"), formatRuntimeTime(runtime.updated_at || run?.updated_at)],
  ]);

  const previous = runtime.last_transition && typeof runtime.last_transition === "object"
    ? runtime.last_transition
    : {};
  if (previous.stage || previous.status || previous.target) {
    const transition = document.createElement("p");
    transition.className = "task-runtime-note";
    transition.textContent = [
      tr("task.runtime_transition", "Last transition") + ":",
      String(previous.stage || "—"),
      String(previous.status || "").toUpperCase(),
      previous.target ? "→ " + String(previous.target) : "",
    ].filter(Boolean).join(" ");
    panel.appendChild(transition);
  }

  const recovery = runtime.recovery && typeof runtime.recovery === "object" ? runtime.recovery : {};
  if (Object.keys(recovery).length) {
    const note = document.createElement("p");
    note.className = "task-runtime-note";
    note.textContent = [
      tr("task.runtime_recovery", "Recovery") + ":",
      recovery.status,
      recovery.retry_mode,
      recovery.reason,
      recovery.detail,
    ].filter(Boolean).map(String).join(" · ");
    panel.appendChild(note);
  }

  if (runtime.last_error || run?.error) {
    const error = document.createElement("p");
    error.className = "task-runtime-error";
    error.textContent = tr("task.runtime_error", "Last error") + ": " + String(runtime.last_error || run.error);
    panel.appendChild(error);
  }
  appendRefreshError(panel, tr, refreshError);
  body.appendChild(panel);
}

function activityText(item) {
  if (typeof item === "string") return item;
  if (!item || typeof item !== "object") return String(item || "");
  return [
    item.kind || item.type || item.role || item.stage || "",
    item.text || item.content || item.detail || item.name || item.command || "",
  ].filter(Boolean).map(String).join(" · ");
}

function renderOutput({ body, task, tr, refreshError }) {
  const { runtime } = runtimeProjection(task);
  const cliLines = Array.isArray(runtime.cli_lines) ? runtime.cli_lines.map(String).slice(-200) : [];
  const activity = Array.isArray(runtime.activity_summary)
    ? runtime.activity_summary.map(activityText).filter(Boolean).slice(-16)
    : [];
  const streamLines = String(runtime.stream || "").split(/\r?\n/).filter(Boolean).slice(-120);
  if (!cliLines.length && !activity.length && !streamLines.length && !runtime.cli_status && !runtime.cli_detail) {
    renderEmpty({ body, tr, titleKey: "task.no_output", titleFallback: "No Runner output yet" });
    return;
  }

  const panel = document.createElement("section");
  panel.id = "taskWorkspaceOutputPanel";
  panel.className = "task-runtime-panel";
  const head = document.createElement("div");
  head.className = "task-runtime-head";
  const title = document.createElement("div");
  const strong = document.createElement("strong");
  strong.textContent = tr("task.output_title", "CLI Runtime");
  const small = document.createElement("small");
  small.textContent = String(runtime.cli_detail || tr("task.output_canonical", "Same canonical Runner console snapshot"));
  title.append(strong, small);
  const badge = document.createElement("span");
  badge.className = "task-runtime-badge";
  badge.textContent = String(runtime.cli_status || runtime.status || "runtime").replaceAll("_", " ");
  head.append(title, badge);
  panel.appendChild(head);

  if (activity.length) {
    const activityPanel = document.createElement("section");
    activityPanel.className = "task-runtime-activity";
    const label = document.createElement("strong");
    label.textContent = tr("task.output_activity", "AI Activity");
    const list = document.createElement("div");
    list.id = "taskWorkspaceActivityList";
    for (const line of activity) {
      const row = document.createElement("span");
      row.textContent = line;
      list.appendChild(row);
    }
    activityPanel.append(label, list);
    panel.appendChild(activityPanel);
  }

  const output = cliLines.length ? cliLines : streamLines;
  if (output.length) {
    const pre = document.createElement("pre");
    pre.id = "taskWorkspaceCliOutput";
    pre.className = "task-runtime-console";
    pre.textContent = output.join("\n");
    panel.appendChild(pre);
  }
  appendRefreshError(panel, tr, refreshError);
  body.appendChild(panel);
}

function renderHistory({ body, task, tr, refreshError }) {
  const archived = Array.isArray(task?.history) ? task.history.filter((row) => row && typeof row === "object") : [];
  const currentRun = task?.run && typeof task.run === "object" ? task.run : null;
  const records = archived.map((row) => ({ run: row, current: false }));
  if (currentRun) records.push({ run: currentRun, current: true });
  if (!records.length) {
    renderEmpty({ body, tr, titleKey: "task.no_history", titleFallback: "No run history yet" });
    return;
  }

  const panel = document.createElement("section");
  panel.id = "taskWorkspaceHistoryPanel";
  panel.className = "task-history-panel";
  for (const entry of records.reverse()) {
    const run = entry.run;
    const row = document.createElement("article");
    row.className = "task-history-row";
    const head = document.createElement("div");
    head.className = "task-history-head";
    const title = document.createElement("strong");
    title.textContent = tr("task.history_run", "Run") + " #" + String(run.run_number || "—");
    const badge = document.createElement("span");
    badge.className = "task-runtime-badge";
    badge.textContent = entry.current
      ? tr("task.history_current", "Current")
      : String(run.lifecycle_end || tr("task.history_archived", "Archived")).replaceAll("_", " ");
    head.append(title, badge);
    row.appendChild(head);

    const itemCount = Array.isArray(task.items) ? task.items.length : 0;
    appendRuntimeMeta(row, [
      [tr("task.history_phase", "Phase"), String(run.phase || "—").replaceAll("_", " ")],
      [tr("task.history_item", "Item"), run.item_index != null ? String(Number(run.item_index) + 1) + " / " + String(itemCount) : "—"],
      [tr("task.history_started", "Started"), formatRuntimeTime(run.started_at)],
      [tr("task.history_updated", "Updated"), formatRuntimeTime(run.updated_at || run.archived_at)],
    ]);

    const merge = run?.workspace_result?.merge;
    if (merge && typeof merge === "object" && merge.status) {
      const note = document.createElement("p");
      note.className = "task-runtime-note";
      note.textContent = tr("task.history_delivery", "Delivery") + ": " + String(merge.status).replaceAll("_", " ");
      row.appendChild(note);
    }
    if (run.error) {
      const error = document.createElement("p");
      error.className = "task-runtime-error";
      error.textContent = String(run.error);
      row.appendChild(error);
    }
    panel.appendChild(row);
  }
  appendRefreshError(panel, tr, refreshError);
  body.appendChild(panel);
}

export function renderTaskRuntimePanel({ tab, body, task, tr, trf, refreshError = "" }) {
  if (!body || !task) return;
  if (tab === "runtime") return renderRuntime({ body, task, tr, trf, refreshError });
  if (tab === "output") return renderOutput({ body, task, tr, refreshError });
  if (tab === "history") return renderHistory({ body, task, tr, refreshError });
}
