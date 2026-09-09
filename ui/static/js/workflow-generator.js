export function createWorkflowGenerator(deps) {
  const {
    state, $, api, showToast, showActionError, confirmDialog, confirmDiscardStudio,
    renderStudioFiles, renderWorkflowPicker, renderStudioPanels, refreshStudioFiles,
    applyStudioGuardToDialogs, refreshStudioGuard, openStudioFile
  } = deps;

  function clearGenerateWorkflowPoll() { if (state.generateWorkflowPollStop) state.generateWorkflowPollStop(); state.generateWorkflowPollStop = null; if (state.generateWorkflowPollTimer) clearTimeout(state.generateWorkflowPollTimer); state.generateWorkflowPollTimer = 0; }
  function fillGenerateWorkflowBackends() {
    const select = $("generateWorkflowBackend"); if (!select) return; select.innerHTML = "";
    const rows = [{ value: "", label: state.defaultBackend ? `Default · ${state.defaultBackend}` : "Default backend" }, ...state.backends.map((name) => ({ value: name, label: name }))];
    for (const row of rows) { const option = document.createElement("option"); option.value = row.value; option.textContent = row.label; select.appendChild(option); }
    const preferred = String(state.preferences?.builderBackend || $("backend")?.value || ""); select.value = [...select.options].some((o) => o.value === preferred) ? preferred : "";
  }
  async function copyWorkflowWorkspace(value) {
    const text = String(value || "").trim();
    if (!text || text === "—" || text === "Created after Generate") return;
    try {
      if (navigator.clipboard?.writeText) await navigator.clipboard.writeText(text);
      else throw new Error("Clipboard API unavailable");
    } catch (_) {
      const helper = document.createElement("textarea"); helper.value = text; helper.setAttribute("readonly", ""); helper.style.position = "fixed"; helper.style.opacity = "0"; document.body.appendChild(helper); helper.select();
      const copied = document.execCommand("copy"); helper.remove(); if (!copied) { showToast("Unable to copy temporary workspace", "error", 3200); return; }
    }
    showToast("Temporary workspace copied");
  }
  function bindWorkflowWorkspaceCopy(node, value) {
    if (!node) return;
    const text = String(value || "").trim(); const copyable = !!text && text !== "—" && text !== "Created after Generate";
    node.classList.toggle("workspace-copy-ready", copyable); node.tabIndex = copyable ? 0 : -1; node.setAttribute("role", copyable ? "button" : "presentation");
    node.title = copyable ? `${text} · Click to copy` : text;
    node.onclick = copyable ? () => copyWorkflowWorkspace(text) : null;
    node.onkeydown = copyable ? (event) => { if (event.key === "Enter" || event.key === " ") { event.preventDefault(); copyWorkflowWorkspace(text); } } : null;
  }
  function setGenerateWorkflowWorkspace(path = "", pattern = "") {
    if (pattern) state.generateWorkflowWorkspacePattern = String(pattern);
    state.generateWorkflowWorkspace = String(path || "");
    const preview = state.generateWorkflowWorkspace || state.generateWorkflowWorkspacePattern || "Created after Generate";
    if ($("generateWorkflowWorkspacePreview")) { $("generateWorkflowWorkspacePreview").textContent = preview; bindWorkflowWorkspaceCopy($("generateWorkflowWorkspacePreview"), preview); }
    for (const id of ["generateWorkflowRunningWorkspace", "generateWorkflowReadyWorkspace"]) {
      if (!$(id)) continue; const value = state.generateWorkflowWorkspace || "—"; $(id).textContent = value; bindWorkflowWorkspaceCopy($(id), value);
    }
  }
  function resetGenerateWorkflowState({ keepRequest = false } = {}) {
    clearGenerateWorkflowPoll(); const request = keepRequest ? (state.generateWorkflowRequestText || $("generateWorkflowRequest")?.value || "") : "";
    const folder = keepRequest ? ($("generateWorkflowFolder")?.value || "") : ""; const filename = keepRequest ? ($("generateWorkflowFilename")?.value || "") : "";
    state.generateWorkflowDirty = false; state.generateWorkflowJobId = ""; state.generateWorkflowPhase = "idle"; state.generateWorkflowDraft = null; state.generateWorkflowPromptIndex = 0; state.generateWorkflowReviewTab = "visual"; state.generateWorkflowRequestText = request; state.generateWorkflowWorkspace = "";
    if ($("generateWorkflowRequest")) $("generateWorkflowRequest").value = request;
    if ($("generateWorkflowFolder")) $("generateWorkflowFolder").value = folder;
    if ($("generateWorkflowFilename")) $("generateWorkflowFilename").value = filename;
    updateGenerateWorkflowTargetPreview();
    if ($("generateWorkflowPreview")) $("generateWorkflowPreview").value = "";
    if ($("generateDraftPromptTextarea")) $("generateDraftPromptTextarea").value = "";
    if ($("generateWorkflowFailure")) $("generateWorkflowFailure").textContent = "";
    if ($("generateWorkflowHint")) { $("generateWorkflowHint").textContent = ""; $("generateWorkflowHint").classList.remove("error"); }
    if ($("generateDraftDirtyHint")) $("generateDraftDirtyHint").hidden = true;
    setGenerateWorkflowWorkspace("", state.generateWorkflowWorkspacePattern);
  }
  function showWorkflowStudioPage() {
    $("workflowGeneratorPage").hidden = true; $("workflowStudioPage").hidden = false;
    // Generator is a temporary page layered over Studio. Re-render the cached
    // catalog immediately so returning from Discard/Cancel never shows an empty
    // Workflow list while the server refresh is in flight.
    renderStudioFiles(); renderWorkflowPicker(); renderStudioPanels();
  }
  async function restoreWorkflowStudioAfterGenerator() {
    showWorkflowStudioPage();
    await refreshStudioFiles({ force: true });
  }
  function showWorkflowGeneratorPage() {
    state.view = "workflow"; $("chatView").hidden = true; $("workflowView").hidden = false; $("workflowNav").classList.add("active"); $("chatNav").classList.remove("active");
    $("workflowStudioPage").hidden = true; $("workflowGeneratorPage").hidden = false;
  }
  function setGenerateWorkflowPhase(phase) {
    state.generateWorkflowPhase = phase; const building = ["running", "cancelling"].includes(phase);
    $("generateWorkflowForm").hidden = phase !== "form";
    $("generateWorkflowRunning").hidden = !building;
    $("generateWorkflowReady").hidden = phase !== "ready";
    $("generateWorkflowFailed").hidden = phase !== "failed";
    $("generateWorkflowPageBadge").hidden = phase !== "ready";
    const titles = { form: ["Generate Workflow with AI", "Describe the Workflow you want. Generate creates a temporary Draft only."], running: ["Generating Workflow", "AI is building and validating a new temporary Draft."], cancelling: ["Cancelling Workflow", "Stopping the current generation and cleaning temporary runtime state."], ready: ["Review generated Workflow", "Review or edit the Draft. Save is the only action that creates a real Workflow."], failed: ["Workflow generation failed", "Nothing was added to Custom or Project."] };
    const [title, subtitle] = titles[phase] || titles.form; $("generateWorkflowPageTitle").textContent = title; $("generateWorkflowPageSubtitle").textContent = subtitle;
    $("generateWorkflowBack").disabled = phase === "cancelling";
    applyStudioGuardToDialogs();
  }
  function flowNameFromDraft(item) { if (typeof item === "string") return item; if (item && typeof item === "object") return String(item.stage || item.name || ""); return ""; }
  function renderGeneratedDraftFlow() {
    const root = $("generateDraftFlowList"); if (!root) return; root.innerHTML = ""; const visual = state.generateWorkflowDraft?.visual || {}; const stages = new Map((visual.stages || []).map((row) => [row.name, row])); const flow = visual.flow || [];
    if (!flow.length) { const empty = document.createElement("div"); empty.className = "designer-empty-state"; empty.textContent = "No flow steps found in the validated Draft."; root.appendChild(empty); return; }
    flow.forEach((item, index) => { const name = flowNameFromDraft(item), cfg = stages.get(name) || {}; const card = document.createElement("article"); card.className = "visual-flow-card workflow-generator-flow-card"; const number = document.createElement("span"); number.className = "visual-flow-index"; number.textContent = String(index + 1); const copy = document.createElement("div"); copy.className = "visual-flow-copy"; const strong = document.createElement("strong"); strong.textContent = cfg.status || name || "Stage"; strong.title = strong.textContent; const small = document.createElement("small"); small.textContent = `${name || "Stage"} · ${cfg.type || "base"}`; copy.append(strong, small); card.append(number, copy); root.appendChild(card); });
  }
  function renderGeneratedDraftPrompts() {
    const root = $("generateWorkflowPromptList"), editor = $("generateDraftPromptTextarea"), label = $("generateDraftPromptName"); if (!root || !editor || !label) return; root.innerHTML = ""; const prompts = state.generateWorkflowDraft?.prompts || [];
    if (!prompts.length) { const empty = document.createElement("div"); empty.className = "designer-empty-state"; empty.textContent = "No generated Prompt files."; root.appendChild(empty); editor.value = ""; editor.disabled = true; label.textContent = "Prompt"; if ($("generateWorkflowEditPrompt")) $("generateWorkflowEditPrompt").disabled = true; if ($("generateDraftPromptTab")) $("generateDraftPromptTab").disabled = true; return; }
    if ($("generateWorkflowEditPrompt")) $("generateWorkflowEditPrompt").disabled = false; if ($("generateDraftPromptTab")) $("generateDraftPromptTab").disabled = false;
    state.generateWorkflowPromptIndex = Math.max(0, Math.min(state.generateWorkflowPromptIndex, prompts.length - 1));
    prompts.forEach((prompt, index) => { const button = document.createElement("button"); button.type = "button"; button.className = "studio-file-item designer-workflow-pill"; if (index === state.generateWorkflowPromptIndex) button.classList.add("active"); const name = document.createElement("strong"); name.textContent = prompt.name || `Prompt ${index + 1}`; const meta = document.createElement("small"); meta.textContent = "Temporary Draft"; button.append(name, meta); button.onclick = () => { state.generateWorkflowPromptIndex = index; renderGeneratedDraftPrompts(); }; root.appendChild(button); });
    const selected = prompts[state.generateWorkflowPromptIndex]; editor.disabled = false; editor.value = selected.content || ""; label.textContent = selected.name || "Prompt";
  }
  function setGeneratedDraftTab(tab) {
    state.generateWorkflowReviewTab = tab; const names = ["visual", "yaml", "prompt"];
    for (const name of names) { const key = name[0].toUpperCase() + name.slice(1); $(`generateDraft${key}Tab`).classList.toggle("active", name === tab); $(`generateDraft${key}Panel`).hidden = name !== tab; }
  }
  function focusGeneratedDraftEditor(tab) {
    setGeneratedDraftTab(tab);
    requestAnimationFrame(() => {
      const target = tab === "prompt" ? $("generateDraftPromptTextarea") : $("generateWorkflowPreview");
      if (target && !target.disabled) target.focus();
    });
  }
  function markGeneratedDraftDirty() {
    if (state.generateWorkflowPhase !== "ready") return; state.generateWorkflowDirty = true; $("generateDraftDirtyHint").hidden = false; $("generateWorkflowValidation").textContent = "Draft modified · validate to refresh Visual before Save"; $("generateWorkflowValidation").classList.remove("success");
  }
  function generatedDraftPayload() { return { workflow: $("generateWorkflowPreview").value, prompts: (state.generateWorkflowDraft?.prompts || []).map((row) => ({ name: row.name, content: row.content || "" })) }; }
  function renderGeneratedDraft(data) {
    const draft = data?.draft || {}; state.generateWorkflowDraft = { workflow: draft.workflow || "", prompts: Array.isArray(draft.prompts) ? draft.prompts.map((row) => ({ name: row.name || "Prompt", content: row.content || "" })) : [], visual: draft.visual || { stages: [], flow: [] }, validation: draft.validation || "" }; state.generateWorkflowPromptIndex = 0; state.generateWorkflowDirty = false;
    $("generateWorkflowPreview").value = state.generateWorkflowDraft.workflow; $("generateDraftDirtyHint").hidden = true; $("generateWorkflowValidation").textContent = "Validation PASS · Workflow dry-run matrix completed"; $("generateWorkflowValidation").classList.add("success");
    if ($("generateWorkflowReadyTarget")) { const folder = $("generateWorkflowFolder")?.value.trim() || "<folder>", filename = normalizeGeneratedWorkflowFilename($("generateWorkflowFilename")?.value) || "<filename>"; $("generateWorkflowReadyTarget").textContent = `runner/workflow/custom/${folder}/${filename}`; }
    renderGeneratedDraftFlow(); renderGeneratedDraftPrompts(); setGeneratedDraftTab("visual");
  }
  function hydrateActiveGenerateWorkflow(data, { openPage = true } = {}) {
    if (!data?.active || !data.job_id) return false;
    resetGenerateWorkflowState(); fillGenerateWorkflowBackends();
    state.generateWorkflowJobId = String(data.job_id); state.generateWorkflowRequestText = String(data.request || "");
    $("generateWorkflowRequest").value = state.generateWorkflowRequestText;
    if ($("generateWorkflowFolder")) $("generateWorkflowFolder").value = String(data.folder || "");
    if ($("generateWorkflowFilename")) $("generateWorkflowFilename").value = String(data.filename || "");
    updateGenerateWorkflowTargetPreview();
    if ([...$("generateWorkflowBackend").options].some((option) => option.value === String(data.backend || ""))) $("generateWorkflowBackend").value = String(data.backend || "");
    setGenerateWorkflowWorkspace(data.workspace || "", data.workspace_pattern || "");
    if (openPage) showWorkflowGeneratorPage();
    const phase = String(data.state || "running");
    if (phase === "ready") { renderGeneratedDraft(data); setGenerateWorkflowPhase("ready"); return true; }
    if (phase === "failed") { $("generateWorkflowFailure").textContent = data.message || "Workflow Builder failed."; setGenerateWorkflowPhase("failed"); return true; }
    $("generateWorkflowRunningStatus").textContent = data.message || "AI is generating Workflow draft…";
    setGenerateWorkflowPhase(phase === "cancelling" ? "cancelling" : "running"); startGenerateWorkflowPoll(); return true;
  }
  async function restoreActiveWorkflowGenerator({ openPage = true } = {}) {
    try { const data = await api("/api/studio/generate/active"); return hydrateActiveGenerateWorkflow(data, { openPage }); }
    catch (_) { return false; }
  }
  async function pollGenerateWorkflow() {
    if (!state.generateWorkflowJobId) return;
    try {
      const data = await api(`/api/studio/generate/status?job_id=${encodeURIComponent(state.generateWorkflowJobId)}`);
      setGenerateWorkflowWorkspace(data.workspace || state.generateWorkflowWorkspace);
      if (data.state === "ready") { clearGenerateWorkflowPoll(); renderGeneratedDraft(data); setGenerateWorkflowPhase("ready"); await refreshStudioGuard(); return; }
      if (data.state === "cancelled") { clearGenerateWorkflowPoll(); try { await api("/api/studio/generate/discard", { method: "POST", body: JSON.stringify({ job_id: state.generateWorkflowJobId }) }); } catch (_) {} resetGenerateWorkflowState(); await restoreWorkflowStudioAfterGenerator(); showToast("Workflow generation cancelled"); await refreshStudioGuard(); return; }
      if (data.state === "failed") { clearGenerateWorkflowPoll(); $("generateWorkflowFailure").textContent = data.message || "Workflow Builder failed."; setGenerateWorkflowPhase("failed"); await refreshStudioGuard(); return; }
      if (data.state === "cancelling") setGenerateWorkflowPhase("cancelling"); else if (state.generateWorkflowPhase !== "running") setGenerateWorkflowPhase("running");
      $("generateWorkflowRunningStatus").textContent = data.message || "AI is generating Workflow draft…";
    } catch (error) { clearGenerateWorkflowPoll(); $("generateWorkflowFailure").textContent = error.message; setGenerateWorkflowPhase("failed"); }
  }
  function startGenerateWorkflowPoll() {
    clearGenerateWorkflowPoll();
    let stopped = false;
    const tick = async () => {
      if (stopped || !state.generateWorkflowJobId) return;
      await pollGenerateWorkflow();
      if (!stopped && state.generateWorkflowJobId && ["running", "cancelling"].includes(state.generateWorkflowPhase)) {
        state.generateWorkflowPollTimer = window.setTimeout(tick, 800);
      }
    };
    state.generateWorkflowPollStop = () => { stopped = true; };
    tick();
  }
  function normalizeGeneratedWorkflowFilename(value) {
    let name = String(value || "").trim();
    if (!name) return "";
    if (!/\.ya?ml$/i.test(name)) name += /workflow/i.test(name) ? ".yaml" : ".workflow.yaml";
    return name;
  }
  function updateGenerateWorkflowTargetPreview() {
    const folder = ($("generateWorkflowFolder")?.value || "<folder>").trim() || "<folder>";
    const filename = normalizeGeneratedWorkflowFilename($("generateWorkflowFilename")?.value || "") || "<filename>";
    if ($("generateWorkflowTargetPreview")) $("generateWorkflowTargetPreview").textContent = `runner/workflow/custom/${folder}/${filename}`;
  }
  function updateGenerateWorkflowSavePreview() {
    const folder = ($("generateWorkflowSaveFolder")?.value || "<folder>").trim() || "<folder>";
    const filename = normalizeGeneratedWorkflowFilename($("generateWorkflowSaveFilename")?.value || "") || "<filename>";
    const destination = $("generateWorkflowDestination")?.value || "custom";
    if ($("generateWorkflowSavePathPreview")) $("generateWorkflowSavePathPreview").textContent = destination === "project" ? `<project>/${filename}` : `runner/workflow/custom/${folder}/${filename}`;
    if ($("generateWorkflowSavePromptPreview")) $("generateWorkflowSavePromptPreview").textContent = destination === "project" ? `Owned files: <project>/prompts/${folder}` : `Owned files: runner/prompts/custom/${folder}`;
  }
  async function openGenerateWorkflowPage() {
    if (!(await confirmDiscardStudio())) return;
    fillGenerateWorkflowBackends(); showWorkflowGeneratorPage(); $("generateWorkflowHint").classList.remove("error"); $("generateWorkflowHint").textContent = "Checking Workflow Builder…";
    try {
      const active = await api("/api/studio/generate/active");
      if (hydrateActiveGenerateWorkflow(active)) return;
      resetGenerateWorkflowState(); fillGenerateWorkflowBackends(); showWorkflowGeneratorPage(); setGenerateWorkflowPhase("form");
      const info = await api("/api/studio/draft"); if (!info.available) throw new Error(info.message || "AI Workflow Builder is unavailable.");
      setGenerateWorkflowWorkspace("", info.workspace_pattern || info.workspace_root || "");
      $("generateWorkflowHint").textContent = "Choose the owned Folder + Filename up front. Generation stays temporary until Validate & Save. Only one Generator job can exist at a time."; updateGenerateWorkflowTargetPreview(); setTimeout(() => $("generateWorkflowRequest").focus(), 0);
    }
    catch (error) { $("generateWorkflowHint").textContent = error.message; $("generateWorkflowHint").classList.add("error"); setGenerateWorkflowPhase("form"); showActionError(error.message, "Workflow Builder unavailable"); }
  }
  function closeGenerateWorkflowSaveModal() { $("generateWorkflowSaveBackdrop").hidden = true; }
  async function discardGenerateWorkflowDraft({ confirm = true, returnToStudio = true } = {}) {
    if (confirm) { const ok = await confirmDialog({ title: "Discard generated Workflow?", message: "This Draft has not been saved. Discard the generated Workflow and Prompt files?", confirmLabel: "Discard Draft", danger: true }); if (!ok) return false; }
    if (state.generateWorkflowJobId) { try { await api("/api/studio/generate/discard", { method: "POST", body: JSON.stringify({ job_id: state.generateWorkflowJobId }) }); } catch (error) { showActionError(error.message, "Discard draft failed"); return false; } }
    resetGenerateWorkflowState(); if (returnToStudio) await restoreWorkflowStudioAfterGenerator(); showToast("Workflow draft discarded"); return true;
  }
  async function cancelGenerateWorkflow() {
    if (!state.generateWorkflowJobId) return false; const ok = await confirmDialog({ title: "Cancel Workflow generation?", message: "Stop the current AI generation and discard its temporary files?", confirmLabel: "Cancel Generation", danger: true }); if (!ok) return false;
    try { await api("/api/studio/generate/cancel", { method: "POST", body: JSON.stringify({ job_id: state.generateWorkflowJobId }) }); setGenerateWorkflowPhase("cancelling"); $("generateWorkflowRunningStatus").textContent = "Cancelling Workflow generation…"; startGenerateWorkflowPoll(); return true; }
    catch (error) { showActionError(error.message, "Cancel generation failed"); return false; }
  }
  async function leaveGenerateWorkflowPage() {
    if ($("workflowGeneratorPage").hidden) return true;
    if (["running", "cancelling"].includes(state.generateWorkflowPhase)) { await cancelGenerateWorkflow(); return false; }
    if (state.generateWorkflowPhase === "ready") return await discardGenerateWorkflowDraft();
    if (state.generateWorkflowPhase === "failed" && state.generateWorkflowJobId) return await discardGenerateWorkflowDraft({ confirm: false });
    const request = $("generateWorkflowRequest").value.trim(); if (request) { const ok = await confirmDialog({ title: "Discard Workflow request?", message: "Leave AI Workflow Builder and discard this unsent Prompt?", confirmLabel: "Discard Request", danger: true }); if (!ok) return false; }
    resetGenerateWorkflowState(); await restoreWorkflowStudioAfterGenerator(); return true;
  }
  async function confirmGenerateWorkflow() {
    const request = $("generateWorkflowRequest").value.trim(); if (!request) { $("generateWorkflowHint").textContent = "Describe the Workflow you want before Generate."; $("generateWorkflowHint").classList.add("error"); return; }
    const folder = $("generateWorkflowFolder").value.trim(), filename = normalizeGeneratedWorkflowFilename($("generateWorkflowFilename").value);
    if (!folder || !filename) { $("generateWorkflowHint").textContent = "Folder and Filename are required before Generate."; $("generateWorkflowHint").classList.add("error"); return; }
    $("generateWorkflowFilename").value = filename; updateGenerateWorkflowTargetPreview();
    state.generateWorkflowRequestText = request; state.generateWorkflowDirty = false; $("generateWorkflowHint").classList.remove("error"); $("generateWorkflowRunningStatus").textContent = "Starting Workflow Builder…"; setGenerateWorkflowPhase("running");
    try {
      const result = await api("/api/studio/generate", { method: "POST", body: JSON.stringify({ request, backend: $("generateWorkflowBackend").value, folder, filename }) });
      if (result.existing) { const active = await api("/api/studio/generate/active"); hydrateActiveGenerateWorkflow(active); return; }
      state.generateWorkflowJobId = result.job_id; setGenerateWorkflowWorkspace(result.workspace || ""); $("generateWorkflowRunningStatus").textContent = result.message || "AI is generating Workflow draft…"; startGenerateWorkflowPoll();
    }
    catch (error) { $("generateWorkflowFailure").textContent = error.message; setGenerateWorkflowPhase("failed"); showActionError(error.message, "Workflow generation failed"); }
  }
  async function regenerateWorkflowDraft() {
    const ok = await confirmDialog({ title: "Generate a new Draft?", message: "Discard the current generated Draft and return to the Prompt. The next Generate starts a new AI run.", confirmLabel: "New Draft", danger: true }); if (!ok) return;
    const request = state.generateWorkflowRequestText || $("generateWorkflowRequest").value; if (state.generateWorkflowJobId) { try { await api("/api/studio/generate/discard", { method: "POST", body: JSON.stringify({ job_id: state.generateWorkflowJobId }) }); } catch (error) { showActionError(error.message, "Discard draft failed"); return; } }
    resetGenerateWorkflowState({ keepRequest: true }); state.generateWorkflowRequestText = request; $("generateWorkflowRequest").value = request; fillGenerateWorkflowBackends(); setGenerateWorkflowPhase("form"); setTimeout(() => $("generateWorkflowRequest").focus(), 0);
  }
  async function validateGeneratedWorkflowDraft() {
    if (!state.generateWorkflowJobId || state.generateWorkflowPhase !== "ready") return; $("generateWorkflowValidate").disabled = true; $("generateWorkflowValidation").textContent = "Validating current Draft…";
    try { const result = await api("/api/studio/generate/validate", { method: "POST", body: JSON.stringify({ job_id: state.generateWorkflowJobId, ...generatedDraftPayload() }) }); renderGeneratedDraft({ draft: result.draft }); showToast("Workflow draft validation passed"); }
    catch (error) { $("generateWorkflowValidation").textContent = error.message; $("generateWorkflowValidation").classList.remove("success"); showActionError(error.message, "Draft validation failed"); }
    finally { $("generateWorkflowValidate").disabled = false; }
  }
  function openGenerateWorkflowSaveModal() {
    if (!state.generateWorkflowJobId || state.generateWorkflowPhase !== "ready") return;
    $("generateWorkflowSaveFolder").value = $("generateWorkflowFolder").value.trim();
    $("generateWorkflowSaveFilename").value = normalizeGeneratedWorkflowFilename($("generateWorkflowFilename").value);
    $("generateWorkflowDestination").value = "custom"; $("generateWorkflowDestination").querySelector('option[value="project"]').disabled = !state.project;
    updateGenerateWorkflowSavePreview();
    $("generateWorkflowSaveHint").textContent = state.generateWorkflowDirty ? "Draft was modified. Validate & Save will revalidate the current YAML and Prompts." : "Save publishes the Draft into this owned Folder without touching common/system assets."; $("generateWorkflowSaveHint").classList.remove("error"); $("generateWorkflowSaveBackdrop").hidden = false; setTimeout(() => $("generateWorkflowSaveFolder").focus(), 0);
  }
  async function saveGenerateWorkflowDraft() {
    const folder = $("generateWorkflowSaveFolder").value.trim(), filename = normalizeGeneratedWorkflowFilename($("generateWorkflowSaveFilename").value);
    if (!folder || !filename) { $("generateWorkflowSaveHint").textContent = "Folder and Filename are required."; $("generateWorkflowSaveHint").classList.add("error"); return; }
    $("generateWorkflowSaveFilename").value = filename; updateGenerateWorkflowSavePreview();
    $("generateWorkflowSaveConfirm").disabled = true; $("generateWorkflowSaveHint").textContent = "Validating current Draft and publishing…"; $("generateWorkflowSaveHint").classList.remove("error");
    try { const result = await api("/api/studio/generate/save", { method: "POST", body: JSON.stringify({ project: state.project?.path || "", job_id: state.generateWorkflowJobId, folder, filename, destination: $("generateWorkflowDestination").value, ...generatedDraftPayload() }) }); closeGenerateWorkflowSaveModal(); resetGenerateWorkflowState(); showWorkflowStudioPage(); state.studioSourceKind = "workflow"; await refreshStudioFiles({ force: true }); const item = (state.studioFiles.workflows || []).find((row) => row.id === result.item?.id || row.path === result.workflow) || result.item; if (item) await openStudioFile(item); showToast(result.message || "Workflow saved"); }
    catch (error) { $("generateWorkflowSaveHint").textContent = error.message; $("generateWorkflowSaveHint").classList.add("error"); showActionError(error.message, "Workflow save failed"); }
    finally { $("generateWorkflowSaveConfirm").disabled = false; }
  }


  return {
    clearGenerateWorkflowPoll,
    fillGenerateWorkflowBackends,
    copyWorkflowWorkspace,
    bindWorkflowWorkspaceCopy,
    setGenerateWorkflowWorkspace,
    resetGenerateWorkflowState,
    showWorkflowStudioPage,
    restoreWorkflowStudioAfterGenerator,
    showWorkflowGeneratorPage,
    setGenerateWorkflowPhase,
    flowNameFromDraft,
    renderGeneratedDraftFlow,
    renderGeneratedDraftPrompts,
    setGeneratedDraftTab,
    focusGeneratedDraftEditor,
    markGeneratedDraftDirty,
    generatedDraftPayload,
    renderGeneratedDraft,
    hydrateActiveGenerateWorkflow,
    restoreActiveWorkflowGenerator,
    pollGenerateWorkflow,
    startGenerateWorkflowPoll,
    normalizeGeneratedWorkflowFilename,
    updateGenerateWorkflowTargetPreview,
    updateGenerateWorkflowSavePreview,
    openGenerateWorkflowPage,
    closeGenerateWorkflowSaveModal,
    discardGenerateWorkflowDraft,
    cancelGenerateWorkflow,
    leaveGenerateWorkflowPage,
    confirmGenerateWorkflow,
    regenerateWorkflowDraft,
    validateGeneratedWorkflowDraft,
    openGenerateWorkflowSaveModal,
    saveGenerateWorkflowDraft,
  };
}
