import { StrictMode, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import {
  Background,
  Controls,
  Handle,
  MarkerType,
  MiniMap,
  Position,
  ReactFlow,
  ReactFlowProvider,
  useReactFlow,
  applyEdgeChanges,
  applyNodeChanges,
  type Connection,
  type OnConnectStart,
  type OnConnectEnd,
  type Edge,
  type Node,
  type NodeProps,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import "./styles.css";
import {
  START,
  END,
  addStageToVisual,
  applyConnectionToVisual,
  cloneStageWithoutConnections,
  disconnectResultEdges,
  nextStageKey,
  removeStageFromVisual,
  stageByName,
  stageReferenceSources,
  type ResultEdgeRef,
  type Stage,
  type Visual,
} from "./workflow-draft";

type GraphProblem = {
  severity: "error" | "warning";
  message: string;
  stage?: string;
};

type CatalogOption = {
  name: string;
  type: string;
  required?: boolean;
  default?: unknown;
  values?: string[];
  description?: string;
  section?: ParameterSection;
  order?: number;
  visible?: boolean;
};

type CatalogProfile = {
  title?: string;
  description?: string;
  defaults?: Record<string, unknown>;
  test_examples?: Partial<Record<StageTestScenario, string>>;
};

type CatalogExecutionTargetConstraint = {
  paired_fields?: string[];
  session_policy_field?: string;
  incompatible_session_policies?: string[];
};

type CatalogStageType = {
  type: string;
  title?: string;
  description?: string;
  category?: string;
  profiles?: Record<string, CatalogProfile>;
  result_kind?: string;
  dynamic_output?: boolean;
  test_examples?: Partial<Record<StageTestScenario, string>>;
  constraints?: { execution_target?: CatalogExecutionTargetConstraint };
  options: CatalogOption[];
};

type Catalog = {
  stage_types: Record<string, CatalogStageType>;
  node_options?: Record<string, unknown>;
};

type BackendCatalog = {
  default: string;
  backends: string[];
  models: Record<string, string[]>;
};

type StudioFile = {
  id: string;
  kind: "workflow" | "prompt";
  name: string;
  display_name?: string;
  reference?: string;
  content?: string;
  hash?: string;
};

type StudioNodeData = {
  kind: "start" | "end" | "stage";
  label: string;
  subtitle?: string;
  stage?: Stage;
  stageTypeTitle?: string;
  dynamicOutput?: string;
};

type StageTestResult = {
  ok?: boolean;
  cancelled?: boolean;
  test_id?: string;
  stage: string;
  status: string;
  output: string;
  data?: unknown;
  next: string;
  route: string;
  kind?: string;
  changed_files?: string[];
  test_retry_limit?: number;
  test_retry_policy?: string;
  effective_backend?: string;
  effective_model?: string;
};

type PathTestResult = {
  ok: boolean;
  exit_code: number;
  from_stage: string;
  completed: boolean;
  error?: string | null;
  cycle?: number | null;
  stage?: string | null;
  transitions: Array<{ number: number; stage: string; label?: string | null; status: string }>;
};

type InspectorTab = "form" | "yaml" | "routing" | "test";
type WorkflowEditorView = "designer" | "yaml";
type StageTestMode = "stage" | "agent_ping" | "mock_error";
type ParameterSection = "content" | "execution" | "result" | "advanced";

type DesignerLanguage = "zh-TW" | "en";
const DESIGNER_LANGUAGE_KEY = "ai-task-runner.language";
const DESIGNER_I18N: Record<DesignerLanguage, Record<string, string>> = {
  "zh-TW": {
    back: "← Workflows", mode: "Workflow Editor", unsaved: "未儲存草稿", saved: "已儲存", designer_view: "Designer", yaml_view: "YAML",
    reset: "重設排列", reload: "重新載入", save: "儲存", saving: "驗證與儲存中…",
    palette: "Stage Palette", add_stage: "新增積木", drag_hint: "拖曳積木到畫布才會新增",
    search_stage: "搜尋 Stage…", custom_stage: "自訂 Stage", draft_hint: "畫布上的修改會先保留為草稿，按「儲存」後才更新 YAML。",
    stage_settings: "Stage 設定", form: "Form", basic: "基本", parameters: "參數", yaml_stage: "YAML", routing: "連線", test: "測試", apply_yaml: "套用 YAML",
    close: "關閉", duplicate: "複製積木", remove: "移除積木", draft_only: "修改先存為草稿",
    type_fixed: "類型（建立後固定；要更換請刪除後重新拖入）", display_name: "顯示名稱", run_status: "執行狀態文字",
    result_edges: "結果連線", incoming: "連到這個積木", stage_input: "Stage Input",
    fill_test: "填入簡易測試 Prompt", clear: "清除", run_stage: "執行 Real Stage", run_ping: "執行 Agent Ping", run_error: "執行 Mock ERROR",
    testing: "測試中…", stop_test: "停止測試", test_stopped: "測試已停止", no_incoming: "目前沒有連入線。",
    section_content: "內容", section_execution: "執行", section_result: "結果", section_advanced: "進階",
    extensions: "擴充 Stage", add_stage_dialog: "新增 Stage",
    copy: "複製", paste: "貼上", delete: "刪除", delete_connection: "刪除連線", test_pass: "PASS 範例", test_fail: "FAIL 範例", test_error: "Mock ERROR",
    disconnected: "未連線", fail_soft_next: "下次 Pass",
    undo_none: "沒有可復原的 Workflow 修改。", undo_done: "已復原上一個 Workflow 草稿修改。",
    redo_none: "沒有可重做的 Workflow 修改。", redo_done: "已重做上一個 Workflow 草稿修改。",
    remove_refs_first: "請先移除指向此 Stage 的結果連線。", remove_title: "移除 Stage", remove_message: "從草稿移除此 Stage？儲存 Workflow 後才會更新 YAML。", remove_confirm: "移除",
    discard_title: "捨棄未儲存變更？", discard_message: "目前 Workflow 還有未儲存的草稿。離開後這些變更會遺失。", discard_confirm: "捨棄並離開",
    reload_title: "重新載入 Workflow？", reload_message: "目前未儲存的 Workflow 草稿會被捨棄，並重新載入磁碟上的版本。", reload_confirm: "捨棄並重新載入",
    cancel: "取消", dynamic_child_note: "此 Stage 成功後會先執行它產生的 child Stages，全部完成後才回到主 Workflow 的下一個 Stage。",
    display_name_suffix: "（Stage key 不變）", no_parameters: "此積木沒有其他參數。", stage_yaml_hint: "同一份 Stage draft；type 與 key 不可在此變更。",
    route_intro: "從積木下方的大接點拉到目標積木。PASS / FAIL 是 Workflow 結果；ERROR 不建立連線。",
    review_policy_help: "Review 是 fail-soft gate：technical ERROR 由 error_policy 控制；semantic FAIL 由 max_failures 控制。允許真的 FAIL N 次；下一次進入 Review 時不呼叫 Agent，直接走 fail-soft PASS 並清零。正常 PASS 也會清零。",
    error_policy_help: "ERROR 依本積木的重試次數執行；留空沿用全域 stage_retries（預設 -1）。非 Review Stage 的有限 retry 用盡後會停在目前 Stage。",
    error_retry: "ERROR 重試次數", error_retry_skip: "ERROR 重試次數（有限值耗盡後 Skip）", inherit_global: "沿用全域設定",
    retry_exhaust_skip: "重試耗盡 → 下一個積木（Skip Review）", semantic_fail_limit: "Semantic FAIL 上限（max_failures）", unlimited: "不限制",
    semantic_fail_help: "允許連續 FAIL 此次數；下一次進入 Review 直接 PASS，不呼叫 Agent。PASS 或放行後 counter 清 0。",
    outgoing: "從這個積木出去", end_stop: "END（停止）", end_done: "END（完成）", next_default: "下一個積木（預設）", stop_default: "停止（預設）",
    test_help: "先選測試模式，再選 Real Stage 的輸入範例；Mock ERROR 只驗證 technical retry 路徑，不要求模型故意失敗。測試不會沿 Workflow 繼續執行，正式 Runtime 設定不受影響。",
    test_input_placeholder: "輸入這個積木要接收的內容", test_input_help: "依 Stage 類型提供最小合法測試內容；只作用於 isolated Stage Test，不會修改 Workflow Prompt。",
    fixed_prompt: "固定 Prompt", ping_help: "不使用工具、不讀專案、不修改檔案，只確認 agent 能正常回覆。",
    mode_label: "模式", next_label: "下一個", retry_label: "測試 Retry", retry_exhausted_skip: "Retry 用盡 → Skip",
    no_output: "（沒有文字輸出）", structured_data: "結構化資料", changed_files: "變更檔案", duplicate_hint: "複製目前設定，但不複製結果連線",
    stage_added: "Stage 已加入草稿；儲存 Workflow 後才會寫入 YAML。", stage_copied: "已複製 Stage 設定；貼上時不會複製結果連線。",
    stage_pasted: "Stage 已貼上；結果連線未複製。", stage_duplicated: "Stage 已複製；結果連線不會一起複製。", stage_removed: "Stage 已從草稿移除。",
    layout_reset_done: "已重設畫布位置；Workflow 執行順序沒有變動。", reset_layout_title: "只重設畫布位置，不變更 YAML",
    fail_soft_next_detail: "下一次進入 → 直接 PASS（不呼叫 Agent，counter 清 0）",
    draft_recovery_title: "本機草稿", draft_recovery_saved: "儲存於", draft_recovery_unchanged: "尚未寫入 Workflow",
    restore_draft: "還原", discard_draft: "捨棄",
    stage_backend_help: "Stage-level Backend 與 Model 必須一起設定；只作用於目前 Stage。", stage_model_help: "只能從所選 Backend 的可用模型清單選擇；只作用於目前 Stage。",
    stage_session_main_conflict: "Stage 覆寫 Backend / Model 時不能使用 main session。", stage_session_default: "此 Stage 覆寫 Backend / Model，Session policy 已恢復為該 Stage 預設值。"
  },
  en: {
    back: "← Workflows", mode: "Workflow Editor", unsaved: "Unsaved draft", saved: "Saved", designer_view: "Designer", yaml_view: "YAML",
    reset: "Reset layout", reload: "Reload", save: "Save", saving: "Validating & saving…",
    palette: "Stage Palette", add_stage: "Add Stage", drag_hint: "Drag a Stage onto the canvas to add it",
    search_stage: "Search Stage…", custom_stage: "Custom Stage", draft_hint: "Canvas changes stay as a draft until you Save.",
    stage_settings: "Stage Settings", form: "Form", basic: "Basic", parameters: "Parameters", yaml_stage: "YAML", routing: "Routing", test: "Test", apply_yaml: "Apply YAML",
    close: "Close", duplicate: "Duplicate", remove: "Remove", draft_only: "Changes stay in draft",
    type_fixed: "Type (fixed after creation; delete and recreate to change it)", display_name: "Display name", run_status: "Runtime status text",
    result_edges: "Result edges", incoming: "Incoming", stage_input: "Stage Input",
    fill_test: "Use sample prompt", clear: "Clear", run_stage: "Run Real Stage", run_ping: "Run Agent Ping", run_error: "Run Mock ERROR",
    testing: "Testing…", stop_test: "Stop Test", test_stopped: "Test stopped", no_incoming: "No incoming edges.",
    section_content: "Content", section_execution: "Execution", section_result: "Result", section_advanced: "Advanced",
    extensions: "Extensions", add_stage_dialog: "Add Stage",
    copy: "Copy", paste: "Paste", delete: "Delete", delete_connection: "Delete connection", test_pass: "PASS example", test_fail: "FAIL example", test_error: "Mock ERROR",
    disconnected: "Disconnected", fail_soft_next: "Next entry passes",
    undo_none: "No Workflow change to undo.", undo_done: "Undid the previous Workflow draft change.",
    redo_none: "No Workflow change to redo.", redo_done: "Redid the previous Workflow draft change.",
    remove_refs_first: "Remove result connections pointing to this Stage first.", remove_title: "Remove Stage", remove_message: "Remove this Stage from the draft? YAML changes only after you Save the Workflow.", remove_confirm: "Remove",
    discard_title: "Discard unsaved changes?", discard_message: "This Workflow has unsaved draft changes. Leaving will discard them.", discard_confirm: "Discard and leave",
    reload_title: "Reload Workflow?", reload_message: "Unsaved Workflow draft changes will be discarded and the saved version reloaded.", reload_confirm: "Discard and reload",
    cancel: "Cancel", dynamic_child_note: "After this Stage passes, its generated child Stages run to completion before the parent Workflow continues.",
    display_name_suffix: " (Stage key is unchanged)", no_parameters: "This Stage has no additional parameters.", stage_yaml_hint: "Same Stage draft; type and key cannot be changed here.",
    route_intro: "Drag the large output handle to a target Stage. PASS / FAIL are Workflow results; ERROR is not a graph edge.",
    review_policy_help: "Review is a fail-soft gate: technical ERROR uses error_policy; semantic FAIL uses max_failures. After N real FAIL verdicts, the next entry bypasses the Agent with fail-soft PASS and resets the counter. A normal PASS also resets it.",
    error_policy_help: "ERROR uses this Stage retry count; leave blank to inherit global stage_retries (default -1). A non-Review Stage stops here when a finite retry budget is exhausted.",
    error_retry: "ERROR retries", error_retry_skip: "ERROR retries (Skip after finite exhaustion)", inherit_global: "Inherit global setting",
    retry_exhaust_skip: "Retries exhausted → next Stage (Skip Review)", semantic_fail_limit: "Semantic FAIL limit (max_failures)", unlimited: "Unlimited",
    semantic_fail_help: "Allow this many consecutive FAIL verdicts; the next entry passes without calling the Agent. PASS or bypass resets the counter.",
    outgoing: "Outgoing", end_stop: "END (stop)", end_done: "END (complete)", next_default: "Next Stage (default)", stop_default: "Stop (default)",
    test_help: "Choose the test mode first, then an input example for Real Stage. Mock ERROR validates the technical retry path without asking the model to fail. The test never continues through the Workflow and does not change production Runtime settings.",
    test_input_placeholder: "Enter input for this Stage", test_input_help: "Uses minimal valid input for the Stage type. This isolated Stage Test does not modify the Workflow Prompt.",
    fixed_prompt: "Fixed Prompt", ping_help: "Uses no tools, does not read or modify the project, and only verifies agent transport.",
    mode_label: "Mode", next_label: "Next", retry_label: "Test Retry", retry_exhausted_skip: "Retries exhausted → Skip",
    no_output: "(no text output)", structured_data: "Structured data", changed_files: "Changed files", duplicate_hint: "Duplicate settings without result connections",
    stage_added: "Stage added to draft; YAML changes only after you Save.", stage_copied: "Stage settings copied; result connections are not copied.",
    stage_pasted: "Stage pasted; result connections were not copied.", stage_duplicated: "Stage duplicated; result connections were not copied.", stage_removed: "Stage removed from draft.",
    layout_reset_done: "Canvas layout reset; Workflow execution order is unchanged.", reset_layout_title: "Reset canvas positions only; do not change YAML",
    fail_soft_next_detail: "Next entry → direct PASS (no Agent call; counter resets)",
    draft_recovery_title: "Local draft", draft_recovery_saved: "Saved", draft_recovery_unchanged: "Workflow unchanged",
    restore_draft: "Restore", discard_draft: "Discard",
    stage_backend_help: "Stage backend and model must be configured together and apply only to this Stage.", stage_model_help: "Choose only from models exposed by the selected backend; the choice applies only to this Stage.",
    stage_session_main_conflict: "A Stage backend/model override cannot use the main session.", stage_session_default: "Session policy restored to this Stage default because it overrides backend/model."
  },
};
function initialDesignerLanguage(): DesignerLanguage {
  try { return localStorage.getItem(DESIGNER_LANGUAGE_KEY) === "en" ? "en" : "zh-TW"; } catch { return "zh-TW"; }
}

function designerText(key: string): string {
  const language = initialDesignerLanguage();
  return DESIGNER_I18N[language]?.[key] || DESIGNER_I18N["zh-TW"][key] || key;
}


const AGENT_PING_PROMPT = "Reply with exactly AGENT_PING_OK and nothing else. Do not use tools, do not modify files, and do not inspect the project.";

type StageTestScenario = "pass" | "fail";
type DesignerConfirmDialog = {
  title: string;
  message: string;
  confirmLabel: string;
  danger?: boolean;
  action: () => void | Promise<void>;
};
function stageTestPrompt(
  stage: Stage | null,
  catalog: Catalog | null,
  scenario: StageTestScenario = "pass",
): string {
  if (!stage) return "";
  const stageType = catalog?.stage_types?.[stage.type];
  const profile = stage.type === "base" && stage.profile
    ? stageType?.profiles?.[String(stage.profile)]
    : undefined;
  return String(
    profile?.test_examples?.[scenario]
    || stageType?.test_examples?.[scenario]
    || ""
  );
}

const PARAMETER_SECTION_ORDER: ParameterSection[] = ["content", "execution", "result", "advanced"];

async function api<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, {
    ...init,
    headers: { "Content-Type": "application/json", ...(init?.headers || {}) },
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok || data?.error) {
    if (response.status === 404 && url.includes("/api/studio/stage/test")) {
      throw new Error("Stage Test API not found. Restart the local UI server so the backend matches this Full Designer build.");
    }
    throw new Error(data?.error || response.statusText);
  }
  return data as T;
}

function query() {
  const p = new URLSearchParams(location.search);
  return { id: p.get("id") || "", project: p.get("project") || "" };
}

function endpoint(path: string) {
  const { id, project } = query();
  const p = new URLSearchParams({ id });
  if (project) p.set("project", project);
  return `${path}?${p}`;
}

function workflowStudioUrl() {
  const { id, project } = query();
  const p = new URLSearchParams({ view: "workflow", studio: id });
  if (project) p.set("project", project);
  return `/index.html?${p}`;
}

function promptEditorUrl(promptId: string) {
  const { project } = query();
  const p = new URLSearchParams({ view: "workflow", source: "prompt", studio: promptId });
  if (project) p.set("project", project);
  return `/index.html?${p}`;
}

function TerminalNode({ data }: NodeProps<Node<StudioNodeData>>) {
  const start = data.kind === "start";
  return (
    <div className={`wf-terminal ${start ? "start" : "end"}`}>
      {!start && <Handle type="target" position={Position.Top} />}
      <strong>{data.label}</strong>
      {start && <Handle type="source" position={Position.Bottom} id="pass" />}
    </div>
  );
}

function StageNode({ data, selected }: NodeProps<Node<StudioNodeData>>) {
  const s = data.stage!;
  const title = String(s.label || s.name);
  const dynamicRouter = s.type === "handoff";
  return (
    <div className={`wf-stage ${selected ? "selected" : ""} type-${s.type} ${s.type === "base" ? `profile-${String(s.profile || "generic")}` : ""}`}>
      <Handle className="stage-input" type="target" position={Position.Top} />
      <div className="wf-stage-head">
        <span className="stage-type">{data.stageTypeTitle || String(s.type || "Stage")}</span>
      </div>
      <strong title={title}>{title}</strong>
      {title !== s.name && <small title={s.name}>{s.name}</small>}
      <div className="wf-stage-meta">
        {data.subtitle === "Not connected to flow" && <span className="disconnected-chip">{designerText("disconnected")}</span>}
        {dynamicRouter && <span>{(s.targets || []).length} targets</span>}
        {data.dynamicOutput && <span className="dynamic-chip">Dynamic · {data.dynamicOutput}</span>}
      </div>
      <div className={`wf-handles ${dynamicRouter ? "single" : ""}`}>
        {dynamicRouter ? <span>HANDOFF</span> : <><span>PASS</span><span>FAIL</span></>}
      </div>
      {dynamicRouter ? (
        <Handle className="pass handoff" type="source" position={Position.Bottom}
          id="handoff" style={{ left: "50%" }} />
      ) : <>
        <Handle className="pass" type="source" position={Position.Bottom} id="pass" style={{ left: "25%" }} />
        <Handle className="fail" type="source" position={Position.Bottom} id="fail" style={{ left: "75%" }} />
      </>}
    </div>
  );
}

const nodeTypes = {
  terminal: TerminalNode,
  stage: StageNode,
};

function catalogStageMeta(catalog: Catalog | null, type: string) {
  const meta = catalog?.stage_types?.[type];
  return {
    title: String(meta?.title || type),
    description: String(meta?.description || ""),
    category: String(meta?.category || "extensions"),
  };
}

const SNAP_PREF_KEY = "workflow-designer.snap:v1";

function readSnapPreference(): boolean {
  try { return localStorage.getItem(SNAP_PREF_KEY) === "1"; } catch { return false; }
}

function writeSnapPreference(enabled: boolean): void {
  try { localStorage.setItem(SNAP_PREF_KEY, enabled ? "1" : "0"); } catch { /* local-only convenience */ }
}

function defaultOption(catalog: Catalog | null, stageType: string, name: string): unknown {
  return catalog?.stage_types?.[stageType]?.options?.find((item) => item.name === name)?.default;
}

function effectivePrompt(catalog: Catalog | null, stage: Stage): string {
  const explicit = String(stage.prompt || "").trim();
  if (explicit) return explicit;
  if (stage.type === "base") {
    const profile = String(stage.profile || "generic");
    const prompt = catalog?.stage_types?.base?.profiles?.[profile]?.defaults?.prompt;
    if (typeof prompt === "string" && prompt.trim()) return prompt.trim();
  }
  return String(defaultOption(catalog, stage.type, "prompt") || "").trim();
}

function executionTargetConstraint(
  catalog: Catalog | null,
  stage: Stage | null,
): CatalogExecutionTargetConstraint | null {
  if (!stage) return null;
  return catalog?.stage_types?.[stage.type]?.constraints?.execution_target || null;
}

function executionTargetOverrideActive(
  stage: Stage,
  constraint: CatalogExecutionTargetConstraint | null,
): boolean {
  const pair = constraint?.paired_fields || [];
  return pair.length > 0 && pair.every((field) => String(stage[field] || "").trim());
}

function applyExecutionTargetConstraint(
  stage: Stage,
  constraint: CatalogExecutionTargetConstraint | null,
  field: string,
  value: unknown,
): { stage: Stage; blocked: boolean; sessionReset: boolean } {
  if (!constraint) {
    return { stage: { ...stage, [field]: value }, blocked: false, sessionReset: false };
  }
  const pair = constraint.paired_fields || [];
  const sessionField = String(constraint.session_policy_field || "");
  const incompatible = new Set((constraint.incompatible_session_policies || []).map(String));
  const currentSession = sessionField ? String(stage[sessionField] || "") : "";
  if (
    field === sessionField
    && incompatible.has(String(value))
    && executionTargetOverrideActive(stage, constraint)
  ) {
    return { stage, blocked: true, sessionReset: false };
  }
  const next = { ...stage, [field]: value };
  if (
    pair.includes(field)
    && executionTargetOverrideActive(next, constraint)
    && sessionField
    && incompatible.has(currentSession)
  ) {
    delete next[sessionField];
    return { stage: next, blocked: false, sessionReset: true };
  }
  return { stage: next, blocked: false, sessionReset: false };
}

type CanvasPosition = { x: number; y: number };
type PendingEdgeCreate = { source: string; sourceHandle: string; position: CanvasPosition };
type CanvasLayout = Record<string, CanvasPosition>;

type WorkflowLocalDraft = {
  hash: string;
  visual: Visual;
  yamlContent: string;
  editorView: WorkflowEditorView;
  savedAt: number;
};

function workflowDraftKey(id: string): string { return `workflow-studio-draft:v1:${id}`; }

function readWorkflowDraft(id: string): WorkflowLocalDraft | null {
  try {
    const value = JSON.parse(localStorage.getItem(workflowDraftKey(id)) || "null");
    if (!value || typeof value !== "object") return null;
    if (typeof value.hash !== "string" || typeof value.yamlContent !== "string") return null;
    if (!value.visual || typeof value.visual !== "object" || value.visual.id !== id) return null;
    if (value.editorView !== "designer" && value.editorView !== "yaml") return null;
    return value as WorkflowLocalDraft;
  } catch {
    return null;
  }
}

function writeWorkflowDraft(draft: WorkflowLocalDraft): void {
  try { localStorage.setItem(workflowDraftKey(draft.visual.id), JSON.stringify(draft)); } catch { /* Draft recovery is best-effort only. */ }
}

function clearWorkflowDraft(id: string): void {
  try { localStorage.removeItem(workflowDraftKey(id)); } catch { /* Ignore unavailable browser storage. */ }
}

function layoutKey(id: string): string { return `workflow-studio-layout:v2:${id}`; }

function readLayout(id: string): CanvasLayout {
  try {
    const saved = JSON.parse(localStorage.getItem(layoutKey(id)) || "{}");
    if (!saved || typeof saved !== "object" || Array.isArray(saved)) return {};
    return Object.fromEntries(Object.entries(saved).filter((entry): entry is [string, CanvasPosition] => {
      const position = entry[1] as CanvasPosition | null;
      return position !== null && typeof position === "object" && Number.isFinite(position.x) && Number.isFinite(position.y);
    }));
  } catch { return {}; }
}

function writeLayout(id: string, layout: CanvasLayout): void {
  try { localStorage.setItem(layoutKey(id), JSON.stringify(layout)); } catch { /* Canvas remains usable without browser storage. */ }
}

function graphFromVisual(visual: Visual, catalog: Catalog | null = null, layout: CanvasLayout = {}): { nodes: Node<StudioNodeData>[]; edges: Edge[] } {
  const nodes: Node<StudioNodeData>[] = [];
  const edges: Edge[] = [];
  const mainX = 420;
  const nodeWidth = 224;
  const mainCenter = mainX + nodeWidth / 2;
  const verticalGap = 175;
  const branchColumnGap = 270;

  nodes.push({
    id: START,
    type: "terminal",
    position: { x: mainCenter - 56, y: 20 },
    data: { kind: "start", label: "START" },
    deletable: false,
  });

  const autoPositions: CanvasLayout = {};
  const branchTargets = new Set<string>();
  let cursorY = 150;

  visual.flow.forEach((name) => {
    if (branchTargets.has(name)) return;
    const stage = stageByName(visual, name);
    if (!stage) return;

    autoPositions[name] = { x: mainX, y: cursorY };

    if (stage.type === "handoff") {
      const targets = (stage.targets || []).filter((target) => Boolean(stageByName(visual, target)));
      if (!targets.length) {
        cursorY += verticalGap;
        return;
      }

      const branchTop = cursorY + verticalGap;
      const rowStartCenter = mainCenter - ((targets.length - 1) * branchColumnGap) / 2;

      targets.forEach((target, targetIndex) => {
        branchTargets.add(target);
        autoPositions[target] = {
          x: rowStartCenter + targetIndex * branchColumnGap - nodeWidth / 2,
          y: branchTop,
        };
      });

      cursorY = branchTop + verticalGap + 45;
      return;
    }

    cursorY += verticalGap;
  });

  const orderedNames = [
    ...visual.flow,
    ...visual.stages.map((s) => s.name).filter((name) => !visual.flow.includes(name)),
  ];
  orderedNames.forEach((name, index) => {
    const s = stageByName(visual, name);
    if (!s) return;
    const disconnected = !visual.flow.includes(name);
    nodes.push({
      id: name,
      type: "stage",
      position: autoPositions[name] || { x: disconnected ? mainX + 360 : mainX, y: cursorY + index * 40 },
      data: {
        kind: "stage",
        label: String(s.label || s.name),
        subtitle: disconnected ? "Not connected to flow" : String(s.status || ""),
        stage: s,
        stageTypeTitle: (() => {
          const stageMeta = catalog?.stage_types?.[s.type];
          const profile = s.type === "base" ? String(s.profile || "") : "";
          const profileTitle = profile ? stageMeta?.profiles?.[profile]?.title : "";
          return profileTitle
            ? `${String(stageMeta?.title || s.type)} · ${String(profileTitle)}`
            : String(stageMeta?.title || s.type || "Stage");
        })(),
        dynamicOutput: (() => {
          const kind = String(s.produces || catalog?.stage_types?.[s.type]?.result_kind || "");
          return kind === "tasks" || kind === "stages" ? kind : "";
        })(),
      },
      deletable: false,
      zIndex: 2,
      className: disconnected ? "disconnected" : "",
    });
  });

  nodes.push({
    id: END,
    type: "terminal",
    position: { x: mainCenter - 56, y: cursorY + 20 },
    data: { kind: "end", label: "END" },
    deletable: false,
  });

  if (visual.flow.length) {
    edges.push({
      id: "start",
      source: START,
      target: visual.flow[0],
      sourceHandle: "pass",
      deletable: false,
      markerEnd: { type: MarkerType.ArrowClosed },
    });
  }

  visual.flow.forEach((name, index) => {
    const s = stageByName(visual, name);
    if (!s) return;
    const routes = (s.routes || {}) as Record<string, string>;
    const next = visual.flow[index + 1];
    if (s.type === "handoff") {
      const status = "handoff";
      (s.targets || []).forEach((target) => {
        if (!stageByName(visual, target)) return;
        edges.push({
          id: `${name}:${status}:${target}`,
          source: name,
          sourceHandle: status,
          target,
          className: `result ${status}`,
          interactionWidth: 28,
          markerEnd: { type: MarkerType.ArrowClosed },
          data: { status, explicit: true, terminal: target },
        });
      });
      return;
    }
    const passTarget = routes.pass || (next ? "next" : "done");
    if (passTarget !== "stop") {
      const resolvedPass = passTarget === "next" ? (next || END) : passTarget === "done" ? END : passTarget;
      const passClass = routes.pass ? "result pass" : "normal pass";
      edges.push({
        id: `${name}:pass:${resolvedPass}`,
        source: name,
        sourceHandle: "pass",
        target: resolvedPass,
        className: passClass,
        deletable: true,
        interactionWidth: 28,
        markerEnd: { type: MarkerType.ArrowClosed },
        data: { status: "pass", explicit: Boolean(routes.pass), terminal: passTarget },
      });
    }
    const failTarget = routes.fail;
    if (failTarget) {
      const resolved = failTarget === "done" || failTarget === "stop" ? END : failTarget === "next" ? (next || END) : failTarget;
      edges.push({
        id: `${name}:fail:${resolved}`,
        source: name,
        sourceHandle: "fail",
        target: resolved,
        className: "result fail",
        interactionWidth: 28,
        markerEnd: { type: MarkerType.ArrowClosed },
        data: { status: "fail", explicit: true, terminal: failTarget },
      });
    }
  });

  return { nodes: nodes.map((node) => ({ ...node, position: layout[node.id] || node.position })), edges };
}

function graphDraft(visual: Visual) {
  const routes: Record<string, Record<string, string>> = {};
  visual.stages.forEach((stage) => {
    if (stage.routes && Object.keys(stage.routes).length) routes[stage.name] = stage.routes;
  });
  return { flow: visual.flow, routes, stages: visual.stages };
}

function graphProblems(visual: Visual): GraphProblem[] {
  const problems: GraphProblem[] = [];
  const names = visual.stages.map((stage) => stage.name);
  const known = new Set(names);
  const duplicates = names.filter((name, index) => names.indexOf(name) !== index);
  Array.from(new Set(duplicates)).forEach((name) => {
    problems.push({ severity: "error", stage: name, message: `Duplicate Stage key: ${name}` });
  });
  if (!visual.flow.length) {
    problems.push({ severity: "error", message: "START has no connected Stage." });
  }
  visual.flow.forEach((name) => {
    if (!known.has(name)) problems.push({ severity: "error", message: `Flow references missing Stage: ${name}` });
  });

  const adjacency = new Map<string, string[]>();
  visual.stages.forEach((stage) => {
    const targets: string[] = [];
    const index = visual.flow.indexOf(stage.name);
    const next = index >= 0 ? visual.flow[index + 1] : "";
    if (stage.type === "handoff") {
      const handoff = Array.isArray(stage.targets) ? stage.targets : [];
      if (!handoff.length) problems.push({ severity: "error", stage: stage.name, message: "Handoff has no target." });
      handoff.forEach((target) => {
        if (!known.has(target)) problems.push({ severity: "error", stage: stage.name, message: `Handoff target not found: ${target}` });
        else targets.push(target);
      });
    } else {
      const pass = String(stage.routes?.pass || (next ? "next" : "done"));
      if (pass === "next" && next) targets.push(next);
      else if (!["next", "done", "stop"].includes(pass)) {
        if (!known.has(pass)) problems.push({ severity: "error", stage: stage.name, message: `PASS target not found: ${pass}` });
        else targets.push(pass);
      }
      const fail = String(stage.routes?.fail || "");
      if (fail && !["next", "done", "stop"].includes(fail)) {
        if (!known.has(fail)) problems.push({ severity: "error", stage: stage.name, message: `FAIL target not found: ${fail}` });
        else targets.push(fail);
      } else if (fail === "next" && next) targets.push(next);
    }
    adjacency.set(stage.name, targets);
  });

  const reachable = new Set<string>();
  const queue = visual.flow[0] ? [visual.flow[0]] : [];
  while (queue.length) {
    const current = queue.shift()!;
    if (reachable.has(current) || !known.has(current)) continue;
    reachable.add(current);
    (adjacency.get(current) || []).forEach((target) => {
      if (!reachable.has(target)) queue.push(target);
    });
  }
  visual.stages.forEach((stage) => {
    if (!reachable.has(stage.name)) {
      problems.push({ severity: "warning", stage: stage.name, message: "Stage is unreachable from START." });
    }
  });
  return problems;
}

function parseInputValue(option: CatalogOption, raw: string, checked?: boolean): unknown {
  const type = option.type.toLowerCase();
  if (type === "bool" || type === "boolean") return Boolean(checked);
  if (type.includes("int")) return raw === "" ? null : Number.parseInt(raw, 10);
  if (type.includes("float")) return raw === "" ? null : Number(raw);
  if (type.includes("list")) return raw.trim() ? raw.split(",").map((v) => v.trim()).filter(Boolean) : [];
  return raw;
}

function Field({
  option,
  value,
  onChange,
}: {
  option: CatalogOption;
  value: unknown;
  onChange: (value: unknown) => void;
}) {
  const type = option.type.toLowerCase();
  if (option.values?.length || type === "enum") {
    return (
      <label>
        <span>{option.name}</span>
        <select value={String(value ?? "")} onChange={(e) => onChange(e.target.value)}>
          {!option.required && <option value="">{option.default !== undefined && option.default !== "" ? `Default — ${String(option.default)}` : "Use Stage default"}</option>}
          {(option.values || []).map((v) => <option key={v} value={v}>{v || "(empty)"}</option>)}
        </select>
        {option.description && <small className="effective-value">{option.description}</small>}
      </label>
    );
  }
  if (type === "optional_boolean") {
    return (
      <label>
        <span>{option.name}</span>
        <select value={value == null ? "" : String(Boolean(value))} onChange={(e) => {
          const raw = e.target.value;
          onChange(raw === "" ? null : raw === "true");
        }}>
          <option value="">Use Stage default</option>
          <option value="true">true</option>
          <option value="false">false</option>
        </select>
        {option.description && <small className="effective-value">{option.description}</small>}
      </label>
    );
  }
  if (type === "bool" || type === "boolean") {
    return (
      <label className="check">
        <input type="checkbox" checked={Boolean(value)} onChange={(e) => onChange(e.target.checked)} />
        <span>{option.name}</span>
        {option.description && <small className="effective-value">{option.description}</small>}
      </label>
    );
  }
  const numeric = type.includes("int") || type.includes("float");
  const multiline = ["instructions", "detail", "command"].includes(option.name);
  return (
    <label>
      <span>{option.name}</span>
      {multiline ? (
        <textarea value={String(value ?? "")} onChange={(e) => onChange(e.target.value)} rows={4} />
      ) : (
        <input
          type={numeric ? "number" : "text"}
          value={Array.isArray(value) ? value.join(", ") : String(value ?? "")}
          onChange={(e) => onChange(parseInputValue(option, e.target.value))}
        />
      )}
      {option.description && <small className="effective-value">{option.description}</small>}
      {option.default !== undefined && <small>default: {JSON.stringify(option.default)}</small>}
    </label>
  );
}

function App() {
  const canvasRef = useRef<HTMLDivElement | null>(null);
  const titleInputRef = useRef<HTMLInputElement | null>(null);
  const addStageTriggerRef = useRef<HTMLButtonElement | null>(null);
  const connectionStartRef = useRef<{ source: string; sourceHandle: string } | null>(null);
  const layoutRef = useRef<CanvasLayout>({});
  const undoStackRef = useRef<Visual[]>([]);
  const redoStackRef = useRef<Visual[]>([]);
  const graphFor = useCallback((v: Visual, c: Catalog | null) => {
    const graph = graphFromVisual(v, c, layoutRef.current);
    layoutRef.current = Object.fromEntries(graph.nodes.map((node) => [node.id, node.position]));
    return graph;
  }, []);
  const { screenToFlowPosition } = useReactFlow();
  const [visual, setVisual] = useState<Visual | null>(null);
  const [editorView, setEditorView] = useState<WorkflowEditorView>("designer");
  const [yamlContent, setYamlContent] = useState("");
  const [yamlOriginal, setYamlOriginal] = useState("");
  const [yamlError, setYamlError] = useState("");
  const [catalog, setCatalog] = useState<Catalog | null>(null);
  const [backendCatalog, setBackendCatalog] = useState<BackendCatalog>({ default: "", backends: [], models: {} });
  const [nodes, setNodes] = useState<Node<StudioNodeData>[]>([]);
  const [edges, setEdges] = useState<Edge[]>([]);
  const [selected, setSelected] = useState<string>("");
  const [dirtyGraph, setDirtyGraph] = useState(false);
  const [recoveryDraft, setRecoveryDraft] = useState<WorkflowLocalDraft | null>(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [problems, setProblems] = useState<GraphProblem[]>([]);
  const [prompts, setPrompts] = useState<StudioFile[]>([]);
  const [pendingCreate, setPendingCreate] = useState<{ type: string; position?: { x: number; y: number } } | null>(null);
  const [createPrompt, setCreatePrompt] = useState("");
  const [createAIProfile, setCreateAIProfile] = useState("generic");
  const [createCommand, setCreateCommand] = useState("");
  const [inspectorTab, setInspectorTab] = useState<InspectorTab>("form");
  const [parameterSection, setParameterSection] = useState<ParameterSection>("content");
  const [stageYaml, setStageYaml] = useState("");
  const [stageYamlError, setStageYamlError] = useState("");
  const [stageYamlLoading, setStageYamlLoading] = useState(false);
  const [testMode, setTestMode] = useState<StageTestMode>("stage");
  const [testScenario, setTestScenario] = useState<StageTestScenario>("pass");
  const [testBackend, setTestBackend] = useState("");
  const [testInput, setTestInput] = useState("");
  const [testResult, setTestResult] = useState<StageTestResult | null>(null);
  const [testError, setTestError] = useState("");
  const [testing, setTesting] = useState(false);
  const stageTestIdRef = useRef("");
  const [pathTestResult, setPathTestResult] = useState<PathTestResult | null>(null);
  const [pathTestError, setPathTestError] = useState("");
  const [pathTesting, setPathTesting] = useState(false);
  const [paletteQuery, setPaletteQuery] = useState("");
  const [snapEnabled, setSnapEnabled] = useState(readSnapPreference());
  const [addStageOpen, setAddStageOpen] = useState(false);
  const [pendingEdgeCreate, setPendingEdgeCreate] = useState<PendingEdgeCreate | null>(null);
  const [addStageQuery, setAddStageQuery] = useState("");
  const [copiedStage, setCopiedStage] = useState<Stage | null>(null);
  const [contextMenu, setContextMenu] = useState<{ x: number; y: number; stage: string } | null>(null);
  const [edgeContextMenu, setEdgeContextMenu] = useState<{ x: number; y: number; edge: Edge } | null>(null);
  const [confirmDialog, setConfirmDialog] = useState<DesignerConfirmDialog | null>(null);
  const [editorOpen, setEditorOpen] = useState(false);
  const [language, setLanguage] = useState<DesignerLanguage>(initialDesignerLanguage());
  const tx = useCallback((key: string) => DESIGNER_I18N[language]?.[key] || DESIGNER_I18N["zh-TW"][key] || key, [language]);
  const syncGraphProjection = useCallback((next: Visual, nextCatalog: Catalog | null = catalog) => {
    const graph = graphFor(next, nextCatalog);
    setNodes(graph.nodes);
    setEdges(graph.edges);
    return graph;
  }, [catalog, graphFor]);
  const anyModalOpen = addStageOpen || Boolean(pendingCreate) || Boolean(confirmDialog) || editorOpen;
  const closeAddStageCommand = useCallback(() => {
    setAddStageOpen(false);
    setPendingEdgeCreate(null);
    requestAnimationFrame(() => addStageTriggerRef.current?.focus());
  }, []);

  useEffect(() => {
    if (!anyModalOpen || addStageOpen) return;
    const trigger = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    return () => {
      if (trigger?.isConnected) requestAnimationFrame(() => trigger.focus());
    };
  }, [anyModalOpen, addStageOpen]);

  useEffect(() => {
    if (!addStageOpen && !pendingCreate && !confirmDialog && !editorOpen) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      event.preventDefault();
      event.stopPropagation();
      if (editorOpen) setEditorOpen(false);
      else if (confirmDialog) setConfirmDialog(null);
      else if (pendingCreate) { setPendingCreate(null); setPendingEdgeCreate(null); }
      else if (addStageOpen) closeAddStageCommand();
    };
    window.addEventListener("keydown", onKeyDown, true);
    return () => window.removeEventListener("keydown", onKeyDown, true);
  }, [addStageOpen, pendingCreate, confirmDialog, editorOpen, closeAddStageCommand]);
  const displayEdges = useMemo<Edge[]>(() => edges.map((edge) => {
    const related = Boolean(selected && (edge.source === selected || edge.target === selected));
    const status = String(edge.data?.status || "pass").toUpperCase();
    const color = status === "FAIL" ? "#d97706" : status === "ERROR" ? "#dc2626"
      : edge.data?.explicit ? "#2563eb" : "#64748b";
    return {
      ...edge,
      type: "smoothstep",
      className: `${edge.className || ""}${selected ? related ? " focused" : " muted" : ""}`,
      markerEnd: { type: MarkerType.ArrowClosed, color, width: 20, height: 20 },
      zIndex: 0,
    };
  }), [edges, selected]);

  const load = useCallback(async () => {
    if (!query().id) {
      setMessage("Missing Workflow id.");
      return;
    }
    try {
      const filesUrl = query().project
        ? `/api/studio/files?project=${encodeURIComponent(query().project)}`
        : "/api/studio/files";
      const [v, file, c, files, backends] = await Promise.all([
        api<Visual>(endpoint("/api/studio/visual")),
        api<StudioFile>(endpoint("/api/studio/file")),
        api<Catalog>("/api/workflow/catalog"),
        api<{ prompts?: StudioFile[] }>(filesUrl),
        api<BackendCatalog>(query().project
          ? `/api/backends?project=${encodeURIComponent(query().project)}&models=1`
          : "/api/backends?models=1"),
      ]);
      const canonicalYaml = String(file.content || "");
      const localDraft = readWorkflowDraft(v.id);
      if (localDraft && localDraft.hash !== v.hash) {
        clearWorkflowDraft(v.id);
        setRecoveryDraft(null);
      } else {
        const graphChanged = Boolean(localDraft) && JSON.stringify(graphDraft(localDraft!.visual)) !== JSON.stringify(graphDraft(v));
        const yamlChanged = Boolean(localDraft) && localDraft!.yamlContent !== canonicalYaml;
        setRecoveryDraft(localDraft && (graphChanged || yamlChanged) ? localDraft : null);
      }
      setVisual(v);
      setYamlContent(canonicalYaml);
      setYamlOriginal(canonicalYaml);
      setYamlError("");
      setCatalog(c);
      setPrompts(files.prompts || []);
      setBackendCatalog(backends);
      setTestBackend((current) => current || backends.default || backends.backends?.[0] || "");
      layoutRef.current = readLayout(v.id);
      syncGraphProjection(v, c);
      setDirtyGraph(false);
      undoStackRef.current = [];
      redoStackRef.current = [];
      setEditorView("designer");
      setMessage("");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : String(error));
    }
  }, [graphFor]);

  useEffect(() => { void load(); }, [load]);
  useEffect(() => {
    const syncLanguage = (event: StorageEvent) => {
      if (event.key !== DESIGNER_LANGUAGE_KEY) return;
      setLanguage(event.newValue === "en" ? "en" : "zh-TW");
    };
    window.addEventListener("storage", syncLanguage);
    return () => window.removeEventListener("storage", syncLanguage);
  }, []);
  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement | null;
      const typing = Boolean(target && (target.tagName === "INPUT" || target.tagName === "TEXTAREA" || target.tagName === "SELECT" || target.isContentEditable));
      if (event.key === "Escape") {
        setContextMenu(null);
        if (addStageOpen) closeAddStageCommand();
        else if (editorOpen) setEditorOpen(false);
        return;
      }
      if (typing || editorOpen || addStageOpen) return;
      if (event.key === "/") {
        event.preventDefault();
        setAddStageOpen(true);
        setAddStageQuery("");
        return;
      }
      if (event.key === "Enter" && selected) {
        event.preventDefault();
        openStageEditor(selected);
        return;
      }
      const ctrl = event.ctrlKey || event.metaKey;
      const key = event.key.toLowerCase();
      if (ctrl && (key === "y" || (key === "z" && event.shiftKey))) {
        event.preventDefault();
        redoVisualDraft();
        return;
      }
      if (ctrl && key === "z") {
        event.preventDefault();
        undoVisualDraft();
        return;
      }
      const selectedResultEdge = edges.find((edge) => edge.selected && edge.data?.status && edge.source !== START);
      if ((event.key === "Delete" || event.key === "Backspace") && selectedResultEdge) {
        event.preventDefault();
        deleteEdges([selectedResultEdge]);
        return;
      }
      if (ctrl && event.key.toLowerCase() === "c" && selected) {
        event.preventDefault();
        copyStageByName(selected);
      } else if (ctrl && event.key.toLowerCase() === "v" && copiedStage) {
        event.preventDefault();
        pasteStage();
      } else if ((event.key === "Delete" || event.key === "Backspace") && selected) {
        event.preventDefault();
        void deleteStage(selected);
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  });

  const yamlDirty = yamlContent !== yamlOriginal;
  const editorDirty = dirtyGraph || yamlDirty;

  useEffect(() => {
    if (!editorDirty) return;
    const warn = (event: BeforeUnloadEvent) => { event.preventDefault(); event.returnValue = ""; };
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [editorDirty]);

  useEffect(() => {
    if (!editorDirty || !visual) return;
    writeWorkflowDraft({
      hash: visual.hash,
      visual: structuredClone(visual),
      yamlContent,
      editorView,
      savedAt: Date.now(),
    });
  }, [editorDirty, visual, yamlContent, editorView]);

  const draft = useMemo(
    () => (visual && selected ? stageByName(visual, selected) || null : null),
    [visual, selected],
  );

  useEffect(() => {
    setInspectorTab("form");
    setParameterSection("content");
    setTestResult(null);
    setTestError("");
    setTestInput("");
    setTestScenario("pass");
    setStageYaml("");
    setStageYamlError("");
  }, [selected]);

  const options = useMemo(() => {
    if (!draft || !catalog) return [];
    return catalog.stage_types[draft.type]?.options || [];
  }, [draft, catalog]);
  const executionConstraint = executionTargetConstraint(catalog, draft);
  const executionPair = executionConstraint?.paired_fields || [];
  const backendField = executionPair[0] || "";
  const modelField = executionPair[1] || "";
  const sessionPolicyField = String(executionConstraint?.session_policy_field || "");
  const executionTargetNames = new Set([...executionPair, ...(sessionPolicyField ? [sessionPolicyField] : [])]);
  const executionTargetOptions = options.filter((o) => executionTargetNames.has(o.name));
  const backendOption = executionTargetOptions.find((o) => o.name === backendField);
  const sessionPolicyOption = executionTargetOptions.find((o) => o.name === sessionPolicyField);
  const stageBackend = backendField ? String(draft?.[backendField] || "").trim() : "";
  const savedStageModel = modelField ? String(draft?.[modelField] || "").trim() : "";
  const stageModels = stageBackend
    ? Array.from(new Set([...(backendCatalog.models?.[stageBackend] || []), ...(savedStageModel ? [savedStageModel] : [])]))
    : [];
  const parameterOptions = options.filter((o) => {
    if (o.visible === false) return false;
    if (["name", "type", "status", "label", "routes", "targets", "max_failures", "profile"].includes(o.name) || executionTargetNames.has(o.name)) return false;
    return true;
  }).sort((a, b) => Number(a.order || 0) - Number(b.order || 0));
  const parameterGroups = PARAMETER_SECTION_ORDER.map((id) => ({
    id,
    options: parameterOptions.filter((option) => (option.section || "advanced") === id),
  })).filter((section) => section.options.length);
  const visibleParameters = parameterOptions.length > 8
    ? (parameterGroups.find((section) => section.id === parameterSection) || parameterGroups[0])?.options || []
    : parameterOptions;
  async function loadStageYaml() {
    if (!draft || !visual || stageYamlLoading) return;
    setStageYamlLoading(true);
    setStageYamlError("");
    try {
      const result = await api<{ ok: boolean; source: string }>("/api/studio/stage/source", {
        method: "POST",
        body: JSON.stringify({
          id: visual.id,
          project: query().project,
          stage: draft.name,
          mode: "format",
          fields: draft,
        }),
      });
      setStageYaml(result.source || "");
    } catch (error) {
      setStageYamlError(error instanceof Error ? error.message : String(error));
    } finally {
      setStageYamlLoading(false);
    }
  }

  async function applyStageYaml() {
    if (!draft || !visual || stageYamlLoading) return;
    setStageYamlLoading(true);
    setStageYamlError("");
    try {
      const result = await api<{ ok: boolean; fields: Stage }>("/api/studio/stage/source", {
        method: "POST",
        body: JSON.stringify({
          id: visual.id,
          project: query().project,
          stage: draft.name,
          mode: "parse",
          fields: draft,
          source: stageYaml,
        }),
      });
      editDraft({ ...result.fields, name: draft.name });
      setMessage("Stage YAML applied to draft");
    } catch (error) {
      setStageYamlError(error instanceof Error ? error.message : String(error));
    } finally {
      setStageYamlLoading(false);
    }
  }

  function rememberUndoSnapshot(snapshot: Visual) {
    const clone = structuredClone(snapshot);
    const last = undoStackRef.current[undoStackRef.current.length - 1];
    if (last && JSON.stringify(last) === JSON.stringify(clone)) return;
    undoStackRef.current = [...undoStackRef.current.slice(-49), clone];
    redoStackRef.current = [];
  }

  function applyHistorySnapshot(snapshot: Visual, message: string) {
    setVisual(snapshot);
    const graph = graphFor(snapshot, catalog);
    setNodes(graph.nodes);
    setEdges(graph.edges);
    setSelected("");
    setEditorOpen(false);
    setContextMenu(null);
    setEdgeContextMenu(null);
    setDirtyGraph(true);
    setMessage(message);
  }

  function undoVisualDraft() {
    if (!visual || undoStackRef.current.length === 0) {
      setMessage(tx("undo_none"));
      return;
    }
    const previous = undoStackRef.current[undoStackRef.current.length - 1];
    undoStackRef.current = undoStackRef.current.slice(0, -1);
    redoStackRef.current = [...redoStackRef.current.slice(-49), structuredClone(visual)];
    applyHistorySnapshot(previous, tx("undo_done"));
  }

  function redoVisualDraft() {
    if (!visual || redoStackRef.current.length === 0) {
      setMessage(tx("redo_none"));
      return;
    }
    const next = redoStackRef.current[redoStackRef.current.length - 1];
    redoStackRef.current = redoStackRef.current.slice(0, -1);
    undoStackRef.current = [...undoStackRef.current.slice(-49), structuredClone(visual)];
    applyHistorySnapshot(next, tx("redo_done"));
  }

  function editDraft(next: Stage) {
    if (visual) {
      rememberUndoSnapshot(visual);
      const updated = { ...visual, stages: visual.stages.map((stage) => stage.name === next.name ? next : stage) };
      setVisual(updated);
      setNodes((current) => current.map((node) => node.id === next.name ? {
        ...node,
        data: {
          ...node.data,
          label: String(next.label || next.name),
          subtitle: String(next.status || ""),
          stage: next,
        },
      } : node));
    }
    setDirtyGraph(true);
    setTestResult(null);
    setPathTestResult(null);
    setPathTestError("");
  }

  function editDraftOption(option: CatalogOption, value: unknown) {
    if (!draft) return;
    const constrained = applyExecutionTargetConstraint(
      draft,
      executionTargetConstraint(catalog, draft),
      option.name,
      value,
    );
    if (constrained.blocked) {
      setMessage(tx("stage_session_main_conflict"));
      return;
    }
    if (constrained.sessionReset) setMessage(tx("stage_session_default"));
    editDraft(constrained.stage);
  }

  async function testStage() {
    if (!visual || !draft || testing || busy) return;
    const testId = globalThis.crypto?.randomUUID?.() || `stage-test-${Date.now()}`;
    stageTestIdRef.current = testId;
    setTesting(true);
    setTestResult(null);
    setTestError("");
    try {
      const result = await api<StageTestResult>("/api/studio/stage/test", {
        method: "POST",
        body: JSON.stringify({
          id: visual.id, project: query().project, stage: draft.name, input: testInput,
          backend: testBackend, probe_mode: testMode,
          test_scenario: testMode === "mock_error" ? "error_mock" : testMode === "stage" ? testScenario : "pass",
          graph: graphDraft(visual), test_id: testId,
        }),
      });
      if (result.cancelled) setTestError(tx("test_stopped"));
      else setTestResult(result);
    } catch (error) {
      setTestError(error instanceof Error ? error.message : String(error));
    } finally {
      if (stageTestIdRef.current === testId) stageTestIdRef.current = "";
      setTesting(false);
    }
  }

  async function stopStageTest() {
    const testId = stageTestIdRef.current;
    if (!testId || !testing) return;
    try {
      await api("/api/studio/stage/test/cancel", {
        method: "POST",
        body: JSON.stringify({ test_id: testId }),
      });
      setTestError(tx("test_stopped"));
    } catch (error) {
      setTestError(error instanceof Error ? error.message : String(error));
    }
  }

  async function testPathFromStage(stageName = draft?.name || "") {
    if (!visual || !stageName || pathTesting || busy) return;
    if (dirtyGraph) {
      setPathTestResult(null);
      setPathTestError("Save the Workflow before testing a path.");
      return;
    }
    setPathTesting(true);
    setPathTestResult(null);
    setPathTestError("");
    try {
      const result = await api<PathTestResult>("/api/studio/path/test", {
        method: "POST",
        body: JSON.stringify({
          id: visual.id,
          project: query().project,
          stage: stageName,
        }),
      });
      setPathTestResult(result);
    } catch (error) {
      setPathTestError(error instanceof Error ? error.message : String(error));
    } finally {
      setPathTesting(false);
    }
  }

  const persistGraph = useCallback(async (nextVisual: Visual): Promise<Visual> => {
    const result = await api<{ visual: Visual; file?: StudioFile }>("/api/studio/graph/save", {
      method: "POST",
      body: JSON.stringify({
        id: nextVisual.id,
        project: query().project,
        hash: nextVisual.hash,
        graph: graphDraft(nextVisual),
      }),
    });
    setVisual(result.visual);
    if (result.file?.content != null) {
      setYamlContent(String(result.file.content));
      setYamlOriginal(String(result.file.content));
    }
    syncGraphProjection(result.visual, catalog);
    setDirtyGraph(false);
    undoStackRef.current = [];
    redoStackRef.current = [];
    return result.visual;
  }, [catalog, graphFor]);

  const saveGraph = useCallback(async (nextVisual = visual): Promise<boolean> => {
    if (!nextVisual) return false;
    const structural = graphProblems(nextVisual);
    setProblems(structural);
    if (structural.some((problem) => problem.severity === "error")) {
      setMessage("Fix Workflow problems before saving.");
      return false;
    }
    setBusy(true);
    try {
      const savedVisual = await persistGraph(nextVisual);
      clearWorkflowDraft(savedVisual.id);
      setRecoveryDraft(null);
      setProblems(structural.filter((problem) => problem.severity === "warning"));
      setMessage("Workflow saved");
      return true;
    } catch (error) {
      const detail = error instanceof Error ? error.message : String(error);
      setProblems((current) => [
        ...current.filter((problem) => problem.severity === "warning"),
        { severity: "error", message: detail },
      ]);
      setMessage(detail);
      return false;
    } finally {
      setBusy(false);
    }
  }, [visual, persistGraph]);

  async function saveYaml(): Promise<boolean> {
    if (!visual || !yamlDirty) return true;
    setBusy(true);
    setYamlError("");
    try {
      const check = await api<{ ok: boolean; summary?: string; line?: number; column?: number }>("/api/studio/check", {
        method: "POST",
        body: JSON.stringify({ id: visual.id, project: query().project, content: yamlContent }),
      });
      if (!check.ok) {
        const detail = `YAML ${check.line || "?"}:${check.column || "?"} · ${check.summary || "invalid"}`;
        setYamlError(detail);
        setMessage(detail);
        return false;
      }
      const saved = await api<StudioFile>("/api/studio/save", {
        method: "POST",
        body: JSON.stringify({ id: visual.id, project: query().project, content: yamlContent, hash: visual.hash }),
      });
      const refreshed = await api<Visual>(endpoint("/api/studio/visual"));
      setYamlContent(String(saved.content || yamlContent));
      setYamlOriginal(String(saved.content || yamlContent));
      setVisual(refreshed);
      syncGraphProjection(refreshed, catalog);
      setDirtyGraph(false);
      clearWorkflowDraft(refreshed.id);
      setRecoveryDraft(null);
      setMessage("Workflow saved");
      return true;
    } catch (error) {
      const detail = error instanceof Error ? error.message : String(error);
      setYamlError(detail);
      setMessage(detail);
      return false;
    } finally {
      setBusy(false);
    }
  }

  async function saveCurrent(): Promise<boolean> {
    return editorView === "yaml" ? saveYaml() : saveGraph();
  }

  function switchEditorView(next: WorkflowEditorView) {
    if (next === editorView || busy) return;
    const apply = async () => {
      const currentDirty = editorView === "yaml" ? yamlDirty : dirtyGraph;
      if (currentDirty) {
        // Designer and YAML are two views of one canonical Workflow. Persist the
        // current draft through the normal validation/save path before reading
        // the other representation; never show a stale graph after editing YAML.
        const saved = await saveCurrent();
        if (!saved) return;
      }
      if (next === "designer" && visual) {
        const refreshed = await api<Visual>(endpoint("/api/studio/visual"));
        setVisual(refreshed);
        syncGraphProjection(refreshed, catalog);
      } else if (next === "yaml" && visual) {
        const file = await api<StudioFile>(endpoint("/api/studio/file"));
        setYamlContent(String(file.content || ""));
        setYamlOriginal(String(file.content || ""));
      }
      setEditorView(next);
      setYamlError("");
    };
    void apply();
  }

  const connect = useCallback((connection: Connection) => {
    if (!visual || !connection.source || !connection.target) return;
    const next = applyConnectionToVisual(visual, connection);
    if (next === visual) return;
    rememberUndoSnapshot(visual);
    setVisual(next);
    syncGraphProjection(next, catalog);
    setDirtyGraph(true);
  }, [visual, catalog, graphFor]);

  const deleteEdges = useCallback((removed: Edge[]) => {
    if (!visual) return;
    const semantic: ResultEdgeRef[] = removed
      .filter((edge) => edge.data?.status && edge.source !== START)
      .map((edge) => ({
        source: edge.source,
        target: edge.target,
        status: String(edge.data?.status || ""),
      }));
    if (!semantic.length) return;
    rememberUndoSnapshot(visual);
    const next = disconnectResultEdges(visual, semantic);
    setVisual(next);
    syncGraphProjection(next, catalog);
    setDirtyGraph(true);
  }, [visual, catalog, graphFor]);

  const rememberPosition = useCallback((_event: unknown, moved: Node<StudioNodeData>) => {
    if (!visual) return;
    layoutRef.current = { ...layoutRef.current, [moved.id]: moved.position };
    writeLayout(visual.id, layoutRef.current);
  }, [visual]);

  function applyAIProfileDefaults(stage: Stage, profile: string): Stage {
    const profiles = catalog?.stage_types?.base?.profiles || {};
    const previousProfile = String(stage.profile || "generic");
    const previousDefaults = profiles[previousProfile]?.defaults || {};
    const nextDefaults = profiles[profile]?.defaults || {};
    const cleaned: Stage = { ...stage, profile };

    Object.entries(previousDefaults).forEach(([key, previous]) => {
      const current = cleaned[key];
      if (JSON.stringify(current) === JSON.stringify(previous)) {
        delete cleaned[key];
      }
    });

    Object.entries(nextDefaults).forEach(([key, value]) => {
      if (cleaned[key] === undefined || cleaned[key] === "") {
        cleaned[key] = structuredClone(value);
      }
    });
    return cleaned;
  }

  async function createStage(stageType: string, position?: { x: number; y: number }, prompt = "", command = "", profile = "generic") {
    if (!visual || !catalog?.stage_types?.[stageType]) return;
    const name = nextStageKey(visual, stageType);
    let stage: Stage = { name, type: stageType };
    if (stageType === "base") stage = applyAIProfileDefaults(stage, profile);
    if (prompt) stage.prompt = prompt;
    if (command) stage.command = command;
    if (stageType === "ai_validator") stage.validator = "ai";
    let next = addStageToVisual(visual, stage);
    if (pendingEdgeCreate) {
      next = applyConnectionToVisual(next, {
        source: pendingEdgeCreate.source,
        sourceHandle: pendingEdgeCreate.sourceHandle,
        target: name,
        targetHandle: null,
      });
    }
    rememberUndoSnapshot(visual);
    setVisual(next);
    if (position) {
      layoutRef.current = { ...layoutRef.current, [name]: position };
      writeLayout(visual.id, layoutRef.current);
    }
    syncGraphProjection(next, catalog);
    setSelected(name);
    setEditorOpen(true);
    setPendingCreate(null);
    setPendingEdgeCreate(null);
    setCreatePrompt("");
    setCreateCommand("");
    setDirtyGraph(true);
    setMessage(`${tx("stage_added")} · ${name}`);
  }

  async function addStage(stageType = "base", position?: { x: number; y: number }) {
    const hasPrompt = Boolean(
      catalog?.stage_types?.[stageType]?.options?.some((option) => option.name === "prompt")
    );
    if (stageType === "base" || stageType === "command" || hasPrompt) {
      setPendingCreate({ type: stageType, position });
      setCreateAIProfile("generic");
      setCreatePrompt("");
      setCreateCommand("");
      return;
    }
    await createStage(stageType, position);
  }

  async function confirmPendingCreate() {
    if (!pendingCreate) return;
    if (pendingCreate.type === "command" && !createCommand.trim()) {
      setMessage("Command Stage requires a command.");
      return;
    }
    await createStage(pendingCreate.type, pendingCreate.position, createPrompt.trim(), createCommand.trim(), createAIProfile);
  }

  const connectStart: OnConnectStart = useCallback((_event, params) => {
    if (params.handleType !== "source" || !params.nodeId) {
      connectionStartRef.current = null;
      return;
    }
    connectionStartRef.current = {
      source: params.nodeId,
      sourceHandle: String(params.handleId || "pass"),
    };
  }, []);

  const connectEnd: OnConnectEnd = useCallback((event, state) => {
    const start = connectionStartRef.current;
    connectionStartRef.current = null;
    if (!start || state.isValid || start.source === END) return;
    const target = event.target as Element | null;
    if (target?.closest(".react-flow__handle, .react-flow__node")) return;
    const point = "changedTouches" in event
      ? event.changedTouches.item(0)
      : event;
    if (!point) return;
    const position = screenToFlowPosition({ x: point.clientX, y: point.clientY });
    setPendingEdgeCreate({ ...start, position });
    setAddStageQuery("");
    setAddStageOpen(true);
  }, [screenToFlowPosition]);

  function dragStage(event: React.DragEvent<HTMLDivElement>, stageType: string) {
    event.dataTransfer.setData("application/x-ai-stage", stageType);
    event.dataTransfer.effectAllowed = "copy";
  }

  async function dropStage(event: React.DragEvent<HTMLDivElement>) {
    event.preventDefault();
    const stageType = event.dataTransfer.getData("application/x-ai-stage");
    if (!stageType) return;
    const position = screenToFlowPosition({ x: event.clientX, y: event.clientY });
    await addStage(stageType, position);
  }

  function copyStageByName(name: string) {
    if (!visual) return;
    const source = stageByName(visual, name);
    if (!source) return;
    setCopiedStage(cloneStageWithoutConnections(source, source.name));
    setMessage(`${tx("stage_copied")} · ${name}`);
  }

  function pasteStage(position?: { x: number; y: number }) {
    if (!visual || !copiedStage) return;
    const name = nextStageKey(visual, copiedStage.type);
    const copy = cloneStageWithoutConnections(copiedStage, name);
    const next = addStageToVisual(visual, copy, selected);
    rememberUndoSnapshot(visual);
    setVisual(next);
    const sourcePosition = selected ? layoutRef.current[selected] : undefined;
    const targetPosition = position || (sourcePosition ? { x: sourcePosition.x + 260, y: sourcePosition.y + 40 } : undefined);
    if (targetPosition) {
      layoutRef.current = { ...layoutRef.current, [name]: targetPosition };
      writeLayout(visual.id, layoutRef.current);
    }
    syncGraphProjection(next, catalog);
    setSelected(name);
    setDirtyGraph(true);
    setMessage(`${tx("stage_pasted")} · ${name}`);
  }

  async function duplicateStage(name = draft?.name || selected) {
    if (!name || !visual) return;
    copyStageByName(name);
    const source = stageByName(visual, name);
    if (!source) return;
    const newName = nextStageKey(visual, source.type);
    const copy = cloneStageWithoutConnections(source, newName);
    const next = addStageToVisual(visual, copy, name);
    rememberUndoSnapshot(visual);
    setVisual(next);
    const sourcePosition = layoutRef.current[name];
    if (sourcePosition) {
      layoutRef.current = {
        ...layoutRef.current,
        [newName]: { x: sourcePosition.x + 260, y: sourcePosition.y + 40 },
      };
      writeLayout(visual.id, layoutRef.current);
    }
    syncGraphProjection(next, catalog);
    setSelected(newName);
    setDirtyGraph(true);
    setMessage(`${tx("stage_duplicated")} · ${name} → ${newName}`);
  }

  function requestConfirm(dialog: DesignerConfirmDialog) {
    setContextMenu(null);
    setConfirmDialog(dialog);
  }

  async function deleteStage(name = draft?.name || selected) {
    if (!visual || !name) return;
    if (stageReferenceSources(visual, name).length) {
      setMessage(tx("remove_refs_first"));
      return;
    }
    requestConfirm({
      title: tx("remove_title"),
      message: `${tx("remove_message")} · ${name}`,
      confirmLabel: tx("remove_confirm"),
      danger: true,
      action: () => {
        const current = visual;
        const next = removeStageFromVisual(current, name);
        rememberUndoSnapshot(current);
        setVisual(next);
        syncGraphProjection(next, catalog);
        setSelected("");
        setEditorOpen(false);
        setContextMenu(null);
        setDirtyGraph(true);
        setMessage(`${tx("stage_removed")} · ${name}`);
      },
    });
  }

  function resetLayout() {
    if (!visual) return;
    layoutRef.current = {};
    try { localStorage.removeItem(layoutKey(visual.id)); } catch { /* Ignore unavailable browser storage. */ }
    setNodes(graphFor(visual, catalog).nodes);
    setMessage(tx("layout_reset_done"));
  }

  function leaveStudio() {
    const leave = () => {
      if (visual && editorDirty) clearWorkflowDraft(visual.id);
      window.location.href = workflowStudioUrl();
    };
    if (!editorDirty) { leave(); return; }
    requestConfirm({
      title: tx("discard_title"),
      message: tx("discard_message"),
      confirmLabel: tx("discard_confirm"),
      danger: true,
      action: leave,
    });
  }

  function reloadStudio() {
    const reload = () => {
      if (visual) clearWorkflowDraft(visual.id);
      setRecoveryDraft(null);
      void load();
    };
    if (!editorDirty) { reload(); return; }
    requestConfirm({
      title: tx("reload_title"),
      message: tx("reload_message"),
      confirmLabel: tx("reload_confirm"),
      danger: true,
      action: reload,
    });
  }

  function restoreWorkflowDraft() {
    if (!visual || !recoveryDraft || recoveryDraft.hash !== visual.hash) return;
    const canonical = visual;
    const restored = structuredClone(recoveryDraft.visual);
    setVisual(restored);
    setYamlContent(recoveryDraft.yamlContent);
    setEditorView(recoveryDraft.editorView);
    setDirtyGraph(JSON.stringify(graphDraft(restored)) !== JSON.stringify(graphDraft(canonical)));
    syncGraphProjection(restored, catalog);
    setRecoveryDraft(null);
    setMessage("Recovered local unsaved draft");
  }

  function discardWorkflowDraft() {
    if (visual) clearWorkflowDraft(visual.id);
    setRecoveryDraft(null);
    setMessage("Local draft discarded");
  }

  function openStageEditor(name: string) {
    setSelected(name);
    setInspectorTab("form");
    setEditorOpen(true);
    requestAnimationFrame(() => {
      titleInputRef.current?.focus();
      titleInputRef.current?.select();
    });
  }

if (!visual) return <main className="loading">{message || "Loading Workflow Studio…"}</main>;

  return (
    <main className="studio-shell">
      <header className="studio-header">
        <div>
          <button className="ghost" onClick={leaveStudio}>{tx("back")}</button>
          <strong>{visual.name}</strong>
          <span>{tx("mode")}</span>
          <div className="workflow-editor-view-switch" role="tablist" aria-label="Workflow editor view">
            <button type="button" role="tab" aria-selected={editorView === "designer"} className={editorView === "designer" ? "active" : ""} onClick={() => switchEditorView("designer")}>{tx("designer_view")}</button>
            <button type="button" role="tab" aria-selected={editorView === "yaml"} className={editorView === "yaml" ? "active" : ""} onClick={() => switchEditorView("yaml")}>{tx("yaml_view")}</button>
          </div>
        </div>
        <div>
          {message && <span className="message">{message}</span>}
          <span className={editorDirty ? "unsaved-badge" : "saved-badge"}>{editorDirty ? tx("unsaved") : tx("saved")}</span>
          {editorView === "designer" && <button type="button" aria-pressed={snapEnabled} title="Snap nodes to a 20px grid"
            onClick={() => { const next = !snapEnabled; setSnapEnabled(next); writeSnapPreference(next); }}>Snap</button>}
          {editorView === "designer" && <button onClick={resetLayout} disabled={busy} title={tx("reset_layout_title")}>{tx("reset")}</button>}
          <button onClick={reloadStudio} disabled={busy}>{tx("reload")}</button>
          <button className="primary" onClick={() => void saveCurrent()} disabled={busy || !editorDirty}
            title={!editorDirty ? tx("saved") : busy ? tx("saving") : tx("save")}>
            {busy ? tx("saving") : tx("save")}
          </button>
        </div>
      </header>

      {recoveryDraft && <section className="workflow-draft-recovery" aria-label="Unsaved Workflow draft recovery">
        <div>
          <strong>{tx("draft_recovery_title")}</strong>
          <small>{tx("draft_recovery_saved")} {new Date(recoveryDraft.savedAt || Date.now()).toLocaleString()} · {tx("draft_recovery_unchanged")}</small>
        </div>
        <div className="workflow-draft-recovery-actions">
          <button type="button" onClick={discardWorkflowDraft}>{tx("discard_draft")}</button>
          <button type="button" className="primary" onClick={restoreWorkflowDraft}>{tx("restore_draft")}</button>
        </div>
      </section>}

      {problems.length > 0 && <section className="workflow-problems" aria-label="Workflow problems">
        <div className="workflow-problems-head">
          <strong>Problems · {problems.length}</strong>
          <button type="button" onClick={() => setProblems([])} aria-label="Dismiss Workflow problems" title="Dismiss Workflow problems">×</button>
        </div>
        <div className="workflow-problems-list">
          {problems.map((problem, index) => (
            <button type="button" key={`${problem.severity}:${problem.stage || "workflow"}:${index}`}
              className={`workflow-problem ${problem.severity}`}
              onClick={() => {
                if (!problem.stage) return;
                setSelected(problem.stage);
                setEditorOpen(false);
              }}>
              <span>{problem.severity === "error" ? "ERROR" : "WARN"}</span>
              <strong>{problem.stage || "Workflow"}</strong>
              <small>{problem.message}</small>
            </button>
          ))}
        </div>
      </section>}

      {editorView === "designer" ? <section className="studio-body">
        <aside className="palette">
          <div className="palette-head">
            <div className="palette-title-row"><span><span className="palette-eyebrow">{tx("palette")}</span><strong>{tx("add_stage")}</strong></span>
              <button ref={addStageTriggerRef} type="button" className="palette-command-add" title="Add Stage (/)" onClick={() => { setAddStageOpen(true); setAddStageQuery(""); }}>＋</button>
            </div>
            <small>{tx("drag_hint")}</small>
          </div>
          <input className="palette-search" value={paletteQuery} onChange={(e) => setPaletteQuery(e.target.value)}
            placeholder={tx("search_stage")} aria-label={tx("search_stage")} />
          {(() => {
            const q = paletteQuery.trim().toLowerCase();
            const allTypes = Object.keys(catalog?.stage_types || {});
            const matches = (type: string) => {
              if (!q) return true;
              const meta = catalogStageMeta(catalog, type);
              return [type, meta.title, meta.description].some((value) => String(value || "").toLowerCase().includes(q));
            };
            const item = (type: string, icon = "◇") => {
              const meta = catalogStageMeta(catalog, type);
              return <div key={type} className="palette-item" draggable={!busy} title={meta.description}
                onDragStart={(event) => dragStage(event, type)}>
                <span className={`palette-icon type-${type}`} aria-hidden="true">{icon}</span>
                <span className="palette-copy"><strong>{meta.title}</strong></span>
                <button type="button" className="palette-quick-add" disabled={busy}
                  aria-label={`Add ${meta.title}`} title={`Add ${meta.title}`}
                  onMouseDown={(event) => event.stopPropagation()}
                  onClick={(event) => { event.stopPropagation(); void addStage(type); }}>＋</button>
              </div>;
            };
            const stageTypes = allTypes.filter((type) => catalogStageMeta(catalog, type).category !== "extensions" && matches(type));
            const extensionTypes = allTypes.filter((type) => catalogStageMeta(catalog, type).category === "extensions" && matches(type));
            const groups = [
              ...(stageTypes.length ? [{ id: "stages", title: "Stages", types: stageTypes }] : []),
              ...(extensionTypes.length ? [{ id: "extensions", title: tx("extensions"), types: extensionTypes }] : []),
            ];
            return groups.map((group) => <div className="palette-section" key={group.id}>
              <div className="palette-section-head static">
                <span>{group.title}</span><small>{group.types.length}</small>
              </div>
              <div className="palette-list">{group.types.map((type) => item(type, "◇"))}</div>
            </div>);
          })()}
          <div className="palette-note compact"><small>{tx("drag_hint")} · ＋ / = quick add · Enter = edit · Ctrl+Z/Y = undo/redo</small></div>
        </aside>
        <div
          ref={canvasRef}
          className="canvas"
          onDragOver={(event) => { event.preventDefault(); event.dataTransfer.dropEffect = "copy"; }}
          onDrop={(event) => void dropStage(event)}
        >
          <ReactFlow
            nodes={nodes}
            edges={displayEdges}
            nodeTypes={nodeTypes}
            onNodesChange={(changes) => setNodes((current) => applyNodeChanges(changes, current))}
            onEdgesChange={(changes) => setEdges((current) => applyEdgeChanges(changes, current))}
            onConnect={connect}
            onConnectStart={connectStart}
            onConnectEnd={connectEnd}
            onEdgesDelete={deleteEdges}
            onEdgeClick={() => { setSelected(""); setContextMenu(null); setEdgeContextMenu(null); }}
            onEdgeContextMenu={(event, edge) => {
              if (!edge.data?.status || edge.source === START) return;
              event.preventDefault();
              setSelected("");
              setContextMenu(null);
              const menuWidth = 190;
              const menuHeight = 64;
              setEdgeContextMenu({
                x: Math.max(8, Math.min(event.clientX, window.innerWidth - menuWidth - 8)),
                y: Math.max(8, Math.min(event.clientY, window.innerHeight - menuHeight - 8)),
                edge,
              });
            }}
            onNodeDragStop={rememberPosition}
            onNodeClick={(_e, n) => {
              if (n.data.kind !== "stage") return;
              setSelected(n.id);
              setEdgeContextMenu(null);
            }}
            onNodeDoubleClick={(_e, n) => n.data.kind === "stage" && openStageEditor(n.id)}
            onNodeContextMenu={(event, n) => {
              if (n.data.kind !== "stage") return;
              event.preventDefault();
              setSelected(n.id);
              setEdgeContextMenu(null);
              const menuWidth = 200;
              const menuHeight = 230;
              setContextMenu({
                x: Math.max(8, Math.min(event.clientX, window.innerWidth - menuWidth - 8)),
                y: Math.max(8, Math.min(event.clientY, window.innerHeight - menuHeight - 8)),
                stage: n.id,
              });
            }}
            onPaneContextMenu={(event) => { event.preventDefault(); setContextMenu(null); setEdgeContextMenu(null); }}
            onPaneClick={() => { setSelected(""); setContextMenu(null); setEdgeContextMenu(null); }}
            connectionLineStyle={{ strokeWidth: 2.5 }}
            defaultEdgeOptions={{ interactionWidth: 24, style: { strokeWidth: 2 } }}
            fitView
            snapToGrid={snapEnabled}
            snapGrid={[20, 20]}
            minZoom={0.25}
            maxZoom={1.8}
            deleteKeyCode={null}
            proOptions={{ hideAttribution: true }}
          >
            <Background gap={22} size={1} />
            <MiniMap pannable zoomable />
            <Controls />
          </ReactFlow>
        </div>

        {addStageOpen && <div className="add-stage-command-backdrop" role="dialog" aria-modal="true" aria-label={tx("add_stage_dialog")}
          onMouseDown={(event) => { if (event.target === event.currentTarget) closeAddStageCommand(); }}>
          <div className="add-stage-command">
            <div className="add-stage-command-head"><strong>{tx("add_stage_dialog")}</strong><button type="button" onClick={closeAddStageCommand} aria-label={tx("close")} title={tx("close")}>×</button></div>
            <input autoFocus value={addStageQuery} onChange={(event) => setAddStageQuery(event.target.value)} placeholder={tx("search_stage")} />
            <div className="add-stage-command-list">
              {Object.keys(catalog?.stage_types || {}).filter((type) => {
                const q = addStageQuery.trim().toLowerCase();
                const meta = catalogStageMeta(catalog, type);
                return !q || [type, meta?.title, meta?.description].some((value) => String(value || "").toLowerCase().includes(q));
              }).map((type) => {
                const meta = catalogStageMeta(catalog, type);
                return <button type="button" key={type} data-stage-type={type} onClick={() => { setAddStageOpen(false); void addStage(type, pendingEdgeCreate?.position); }}>
                  <span className={`palette-icon type-${type}`}>◇</span>
                  <span><strong>{meta.title}</strong><small>{meta.description}</small></span><b>＋</b>
                </button>;
              })}
            </div>
          </div>
        </div>}

        {edgeContextMenu && <div className="stage-context-menu edge-context-menu" style={{ left: edgeContextMenu.x, top: edgeContextMenu.y }}
          onMouseLeave={() => setEdgeContextMenu(null)}>
          <button type="button" className="danger-item" onClick={() => {
            deleteEdges([edgeContextMenu.edge]);
            setEdgeContextMenu(null);
          }}>⌫ {tx("delete_connection")}</button>
        </div>}

        {contextMenu && <div className="stage-context-menu" style={{ left: contextMenu.x, top: contextMenu.y }}
          onMouseLeave={() => setContextMenu(null)}>
          <button type="button" onClick={() => { openStageEditor(contextMenu.stage); setContextMenu(null); }}>⚙ {tx("stage_settings")}</button>
          <button type="button" disabled={dirtyGraph || busy || pathTesting}
            title={dirtyGraph ? "Save Workflow before testing path" : "Dry-run this saved path to END"}
            onClick={() => {
              const stage = contextMenu.stage;
              setContextMenu(null);
              openStageEditor(stage);
              setInspectorTab("test");
              void testPathFromStage(stage);
            }}>▶ Test path to END</button>
          <button type="button" onClick={() => { copyStageByName(contextMenu.stage); setContextMenu(null); }}>⧉ {tx("copy")} <kbd>Ctrl+C</kbd></button>
          <button type="button" disabled={!copiedStage} onClick={() => { pasteStage(); setContextMenu(null); }}>▣ {tx("paste")} <kbd>Ctrl+V</kbd></button>
          <button type="button" onClick={() => { void duplicateStage(contextMenu.stage); setContextMenu(null); }}>⊕ {tx("duplicate")}</button>
          <hr />
          <button type="button" className="danger-item" onClick={() => { void deleteStage(contextMenu.stage); }}>⌫ {tx("delete")} <kbd>Del</kbd></button>
        </div>}

        {pendingCreate && (
          <div className="create-stage-backdrop" role="dialog" aria-modal="true" aria-label="Create Stage">
            <div className="create-stage-card">
              <div>
                <small>NEW STAGE</small>
                <h3>{catalogStageMeta(catalog, pendingCreate.type).title}</h3>
                <p>{catalogStageMeta(catalog, pendingCreate.type).description}</p>
              </div>
              {pendingCreate.type === "base" && <>
                <label>
                  <span>AI profile</span>
                  <select value={createAIProfile} onChange={(e) => {
                    const profile = e.target.value;
                    setCreateAIProfile(profile);
                    const value = catalog?.stage_types?.base?.profiles?.[profile]?.defaults?.prompt;
                    setCreatePrompt(typeof value === "string" ? value : "");
                  }}>
                    {Object.entries(catalog?.stage_types?.base?.profiles || {}).map(([value, item]) => (
                      <option key={value} value={value}>{item.title || value}</option>
                    ))}
                  </select>
                  <small className="effective-value">
                    {catalog?.stage_types?.base?.profiles?.[createAIProfile]?.description || "AI Stage behavior preset."}
                  </small>
                </label>
                <label>
                  <span>Prompt</span>
                  <select value={createPrompt} onChange={(e) => setCreatePrompt(e.target.value)}>
                    <option value="">Use profile default</option>
                    {prompts.map((p) => {
                      const ref = p.reference || p.display_name || p.name;
                      return <option key={p.id} value={ref}>{ref}</option>;
                    })}
                  </select>
                  <small className="effective-value">
                    Effective: <code>{createPrompt || String(catalog?.stage_types?.base?.profiles?.[createAIProfile]?.defaults?.prompt || "(none)")}</code>
                  </small>
                </label>
              </>}
              {pendingCreate.type !== "base" && catalog?.stage_types?.[pendingCreate.type]?.options?.some((option) => option.name === "prompt") && (
                <label>
                  <span>Prompt</span>
                  <select value={createPrompt} onChange={(e) => setCreatePrompt(e.target.value)}>
                    <option value="">Use Stage default</option>
                    {prompts.map((p) => {
                      const ref = p.reference || p.display_name || p.name;
                      return <option key={p.id} value={ref}>{ref}</option>;
                    })}
                  </select>
                  <small className="effective-value">
                    Effective: <code>{createPrompt || String(defaultOption(catalog, pendingCreate.type, "prompt") || "(none)")}</code>
                  </small>
                </label>
              )}
                            {pendingCreate.type === "command" && (
                <label>
                  <span>Command</span>
                  <textarea rows={4} value={createCommand} onChange={(e) => setCreateCommand(e.target.value)} placeholder="python tool/my_validator.py" />
                </label>
              )}
              <div className="create-stage-actions">
                <button type="button" onClick={() => { setPendingCreate(null); setPendingEdgeCreate(null); }} disabled={busy}>Cancel</button>
                <button type="button" className="primary" onClick={() => void confirmPendingCreate()} disabled={busy}>Create Stage</button>
              </div>
            </div>
          </div>
        )}
        {confirmDialog && <div className="designer-confirm-backdrop" role="dialog" aria-modal="true" aria-labelledby="designer-confirm-title"
          onMouseDown={(event) => { if (event.target === event.currentTarget) setConfirmDialog(null); }}>
          <div className="designer-confirm-dialog">
            <div className={`designer-confirm-icon ${confirmDialog.danger ? "danger" : ""}`} aria-hidden="true">{confirmDialog.danger ? "!" : "?"}</div>
            <div className="designer-confirm-copy">
              <h3 id="designer-confirm-title">{confirmDialog.title}</h3>
              <p>{confirmDialog.message}</p>
            </div>
            <div className="designer-confirm-actions">
              <button type="button" onClick={() => setConfirmDialog(null)}>{tx("cancel")}</button>
              <button type="button" className={confirmDialog.danger ? "danger-confirm" : "primary"}
                onClick={() => {
                  const action = confirmDialog.action;
                  setConfirmDialog(null);
                  void action();
                }}>{confirmDialog.confirmLabel}</button>
            </div>
          </div>
        </div>}

        {editorOpen && draft && <div className="stage-editor-backdrop" role="dialog" aria-modal="true" aria-label={tx("stage_settings")} onMouseDown={(e) => { if (e.target === e.currentTarget) setEditorOpen(false); }}>
          <aside className="inspector stage-editor-modal">
              <div className="inspector-head">
                <div><small>STAGE</small><h2>{draft.name}</h2></div>
                <div className="inspector-head-actions"><span>{draft.type}</span><button type="button" className="modal-close-button" onClick={() => setEditorOpen(false)} aria-label={tx("close")} title={tx("close")}>×</button></div>
              </div>
              <div className="inspector-tabs" role="tablist" aria-label="Stage sections">
                {(["form", "yaml", "routing", "test"] as const).map((tab) => (
                  <button key={tab} type="button" role="tab" data-inspector-tab={tab} aria-selected={inspectorTab === tab}
                    className={inspectorTab === tab ? "active" : ""} onClick={() => {
                      setInspectorTab(tab);
                      if (tab === "yaml") void loadStageYaml();
                    }}>
                    {{ form: tx("form"), yaml: tx("yaml_stage"), routing: tx("routing"), test: tx("test") }[tab]}
                  </button>
                ))}
              </div>
              <div className={`stage-editor-content ${inspectorTab === "yaml" ? "yaml-mode" : ""}`}>
              {inspectorTab === "form" && <div className="fields stage-form-panel" role="tabpanel">
                <section className="stage-form-section">
                  <div className="stage-form-section-head"><strong>{tx("basic")}</strong><small>Stage identity and behavior</small></div>
                <label>
                  <span>{tx("type_fixed")}</span>
                  <select value={draft.type} disabled>
                    {Object.keys(catalog?.stage_types || {}).map((t) => <option key={t}>{t}</option>)}
                  </select>
                </label>
                {(String(draft.produces || catalog?.stage_types?.[draft.type]?.result_kind || "") === "tasks"
                || String(draft.produces || catalog?.stage_types?.[draft.type]?.result_kind || "") === "stages") && <div className="dynamic-stage-note">
                <strong>Dynamic child Workflow</strong>
                <span>{tx("dynamic_child_note")}</span>
              </div>}
              {draft.type === "base" && <label>
                  <span>AI profile</span>
                  <select value={String(draft.profile || "generic")} onChange={(e) => editDraft(applyAIProfileDefaults(draft, e.target.value))}>
                    {Object.entries(catalog?.stage_types?.base?.profiles || {}).map(([value, item]) => (
                      <option key={value} value={value}>{item.title || value}</option>
                    ))}
                  </select>
                  <small className="effective-value">
                    {catalog?.stage_types?.base?.profiles?.[String(draft.profile || "generic")]?.description || "Choose an AI behavior preset; parameters remain editable."}
                  </small>
                </label>}
                <label><span>{tx("display_name")}{tx("display_name_suffix")}</span><input ref={titleInputRef} value={String(draft.label || "")} placeholder={draft.name} onChange={(e) => editDraft({ ...draft, label: e.target.value })} /></label>
                <label><span>{tx("run_status")}</span><input value={String(draft.status || "")} onChange={(e) => editDraft({ ...draft, status: e.target.value })} /></label>
                </section>
                {executionTargetOptions.length > 0 && <section className="stage-form-section stage-execution-target">
                  <div className="stage-form-section-head"><strong>{tx("section_execution")}</strong><small>Backend / Model / Session</small></div>
                  {backendOption && backendField && modelField && <label>
                    <span>{backendField}</span>
                    <select value={stageBackend} onChange={(event) => {
                      const backend = event.target.value;
                      let next = { ...draft };
                      if (!backend) {
                        executionPair.forEach((field) => { delete next[field]; });
                      } else {
                        const constrained = applyExecutionTargetConstraint(next, executionConstraint, backendField, backend);
                        next = constrained.stage;
                        if (!(backendCatalog.models?.[backend] || []).includes(String(next[modelField] || ""))) delete next[modelField];
                        if (constrained.sessionReset) setMessage(tx("stage_session_default"));
                      }
                      editDraft(next);
                    }}>
                      <option value="">Use global backend/model</option>
                      {(backendOption.values || backendCatalog.backends).map((value) => <option key={value} value={value}>{value}</option>)}
                    </select>
                    <small className="effective-value">{tx("stage_backend_help")}</small>
                  </label>}
                  {backendOption && backendField && modelField && <label>
                    <span>{modelField}</span>
                    <select
                      value={String(draft[modelField] || "")}
                      disabled={!stageBackend || stageModels.length === 0}
                      onChange={(event) => {
                        const constrained = applyExecutionTargetConstraint(draft, executionConstraint, modelField, event.target.value);
                        if (constrained.sessionReset) setMessage(tx("stage_session_default"));
                        editDraft(constrained.stage);
                      }}
                    >
                      <option value="">{stageBackend ? (stageModels.length ? "Select model" : "No models available") : "Select backend first"}</option>
                      {stageModels.map((value) => <option key={value} value={value}>{value}</option>)}
                    </select>
                    <small className="effective-value">{tx("stage_model_help")}</small>
                  </label>}
                  {sessionPolicyOption && <Field
                    option={sessionPolicyOption}
                    value={draft.session_policy}
                    onChange={(value) => editDraftOption(sessionPolicyOption, value)}
                  />}
                </section>}
                <section className="stage-form-section">
                  <div className="stage-form-section-head"><strong>{tx("parameters")}</strong><small>{parameterOptions.length} fields</small></div>
                {parameterOptions.length === 0 && <p className="section-empty">{tx("no_parameters")}</p>}
                {parameterOptions.length > 8 && <div className="parameter-sections" role="tablist" aria-label="Parameter sections">
                  {parameterGroups.map((section) => <button key={section.id} type="button" role="tab"
                    aria-selected={visibleParameters === section.options}
                    className={visibleParameters === section.options ? "active" : ""}
                    onClick={() => setParameterSection(section.id)}>{tx(`section_${section.id}`)}<small>{section.options.length}</small></button>)}
                </div>}
                {visibleParameters.map((option) => option.name === "prompt" ? (
                    <label key={option.name}>
                      <span>prompt</span>
                      <select value={String(draft.prompt || "")} onChange={(e) => editDraft({ ...draft, prompt: e.target.value })}>
                        <option value="">{effectivePrompt(catalog, { ...draft, prompt: "" }) ? `Default — ${effectivePrompt(catalog, { ...draft, prompt: "" })}` : "No default prompt"}</option>
                        {prompts.map((p) => {
                          const ref = p.reference || p.display_name || p.name;
                          return <option key={p.id} value={ref}>{ref}</option>;
                        })}
                      </select>
                      <small className="effective-value">Effective: <code>{effectivePrompt(catalog, draft) || "(none)"}</code></small>
                      {(() => {
                        const ref = String(draft.prompt || effectivePrompt(catalog, draft) || "").trim();
                        const item = prompts.find((prompt) => String(prompt.reference || prompt.display_name || prompt.name) === ref);
                        return item ? <button type="button" className="inline-prompt-edit"
                          onClick={() => { window.location.href = promptEditorUrl(item.id); }}>Edit Prompt</button> : null;
                      })()}
                    </label>
                  ) : (
                    <Field
                      key={option.name}
                      option={{
                        ...option,
                        description: option.description || (
                          option.name === "backend" ? tx("stage_backend_help")
                          : option.name === "model" ? tx("stage_model_help")
                          : undefined
                        ),
                      }}
                      value={draft[option.name]}
                      onChange={(value) => editDraftOption(option, value)}
                    />
                  ))}
                </section>
              </div>}
              {inspectorTab === "yaml" && <div className="stage-yaml-panel" role="tabpanel">
                <div className="stage-yaml-toolbar">
                  <div><strong>Stage YAML</strong><small>{tx("stage_yaml_hint")}</small></div>
                  <button type="button" onClick={() => void applyStageYaml()} disabled={stageYamlLoading}>{stageYamlLoading ? "…" : tx("apply_yaml")}</button>
                </div>
                {stageYamlError && <div className="stage-yaml-error">{stageYamlError}</div>}
                <textarea value={stageYaml} onChange={(event) => { setStageYaml(event.target.value); setStageYamlError(""); }}
                  spellCheck={false} autoCapitalize="off" autoComplete="off" />
              </div>}
              {inspectorTab === "routing" && <div className="edge-help" role="tabpanel">
                <strong>{tx("result_edges")}</strong>
                <p>{tx("route_intro")}</p>
                {(draft.type === "base" && draft.profile === "review")
                  ? <p>{tx("review_policy_help")}</p>
                  : <p>{tx("error_policy_help")}</p>}
                <label className="route-policy-field"><span>{(draft.type === "base" && draft.profile === "review") ? tx("error_retry_skip") : tx("error_retry")}</span><input type="number" min={-1}
                  value={draft.error_policy?.retries ?? ""} placeholder={tx("inherit_global")}
                  onChange={(event) => {
                    const raw = event.target.value;
                    if (raw === "") {
                      const { error_policy: _removed, ...rest } = draft;
                      editDraft(rest);
                    } else {
                      const retries = Number(raw);
                      if (!Number.isInteger(retries) || retries < -1) return;
                      editDraft({ ...draft, error_policy: { retries } });
                    }
                  }} /></label>
                {(draft.type === "base" && draft.profile === "review") && Number.isInteger(draft.error_policy?.retries) && Number(draft.error_policy?.retries) >= 0 &&
                  <div className="route-row error-skip-row"><span className="route-dot error" />
                    <strong>ERROR</strong><span>{tx("retry_exhaust_skip")}</span>
                  </div>}
                {(draft.type === "base" && draft.profile === "review") && <>
                  <label className="route-policy-field"><span>{tx("semantic_fail_limit")}</span><input type="number" min={1}
                    value={draft.max_failures ?? ""} placeholder={tx("unlimited")}
                    onChange={(event) => {
                      const raw = event.target.value;
                      if (raw === "") {
                        const { max_failures: _removed, ...rest } = draft;
                        editDraft(rest);
                      } else {
                        const value = Number(raw);
                        if (!Number.isInteger(value) || value <= 0) return;
                        editDraft({ ...draft, max_failures: value });
                      }
                    }} />
                    <small>{tx("semantic_fail_help")}</small>
                  </label>
                  {Number.isInteger(draft.max_failures) && Number(draft.max_failures) > 0 &&
                    <div className="route-row failure-cap-row"><span className="route-dot fail" />
                      <strong>FAIL×{Number(draft.max_failures)}</strong><span>{tx("fail_soft_next_detail")}</span>
                    </div>}
                </>}
                <div className="route-section-title">{tx("outgoing")}</div>
                {draft.type === "handoff"
                  ? edges.filter((edge) => edge.source === draft.name && edge.data?.status === "handoff").map((edge) =>
                    <div className="route-row" key={edge.id}><span className="route-dot pass" />
                      <strong>{String(edge.data?.status || "").toUpperCase()}</strong><span>{edge.target}</span>
                    </div>
                  ) : (["pass", "fail"] as const).map((status) => {
                  const edge = edges.find((item) => item.source === draft.name && item.data?.status === status);
                  const terminal = String(edge?.data?.terminal || "");
                  const target = edge?.target === END
                    ? terminal === "stop" ? tx("end_stop") : tx("end_done")
                    : edge?.target || (status === "pass" ? tx("next_default") : tx("stop_default"));
                  return <div className="route-row" key={status}><span className={`route-dot ${status}`} />
                    <strong>{status.toUpperCase()}</strong><span>{target}</span>
                  </div>;
                })}
                <div className="route-section-title">{tx("incoming")}</div>
                {edges.filter((edge) => edge.target === draft.name).length === 0 && <p>{tx("no_incoming")}</p>}
                {edges.filter((edge) => edge.target === draft.name).map((edge) => {
                  const status = String(edge.data?.status || "pass").toLowerCase();
                  return <div className="route-row" key={edge.id}><span className={`route-dot ${status}`} />
                    <strong>{status.toUpperCase()}</strong><span>{edge.source === START ? "START" : edge.source}</span>
                  </div>;
                })}
              </div>}
              {inspectorTab === "test" && <div className="stage-test" role="tabpanel">
                <p>{tx("test_help")}</p>
                <div className="test-mode-tabs" role="tablist" aria-label="Stage test mode">
                  <button type="button" role="tab" aria-selected={testMode === "stage"} className={testMode === "stage" ? "active" : ""}
                    onClick={() => { setTestMode("stage"); setTestResult(null); setTestError(""); }}>Real Stage</button>
                  <button type="button" role="tab" aria-selected={testMode === "agent_ping"} className={testMode === "agent_ping" ? "active" : ""}
                    onClick={() => { setTestMode("agent_ping"); setTestResult(null); setTestError(""); }}>Agent Ping</button>
                  <button type="button" role="tab" aria-selected={testMode === "mock_error"} className={testMode === "mock_error" ? "active" : ""}
                    onClick={() => { setTestMode("mock_error"); setTestResult(null); setTestError(""); }}>Mock Technical Error</button>
                </div>
                <label><span>{testMode === "stage" ? "Fallback Backend" : "Backend"}</span><select value={testBackend} onChange={(e) => setTestBackend(e.target.value)}>
                  {(backendCatalog.backends || []).map((name) => <option key={name} value={name}>{name}{name === backendCatalog.default ? "（default）" : ""}</option>)}
                </select></label>
                {testMode === "stage"
                  ? <label><span>{tx("stage_input")}</span>
                      <div className="test-scenario-tabs" role="group" aria-label="Stage test prompt scenario">
                        {(["pass", "fail"] as StageTestScenario[]).map((scenario) => <button type="button" key={scenario}
                          className={testScenario === scenario ? `active scenario-${scenario}` : `scenario-${scenario}`}
                          onClick={() => { setTestScenario(scenario); setTestInput(stageTestPrompt(draft, catalog, scenario)); }}>
                          {{ pass: tx("test_pass"), fail: tx("test_fail") }[scenario]}
                        </button>)}
                      </div>
                      <div className="test-input-actions">
                        <button type="button" onClick={() => setTestInput(stageTestPrompt(draft, catalog, testScenario))}>{tx("fill_test")}</button>
                        {testInput && <button type="button" onClick={() => setTestInput("")}>{tx("clear")}</button>}
                      </div>
                      <textarea value={testInput} onChange={(e) => setTestInput(e.target.value)} rows={5}
                        placeholder={stageTestPrompt(draft, catalog, testScenario) || tx("test_input_placeholder")} />
                      <small>{tx("test_input_help")}</small>
                    </label>
                  : testMode === "agent_ping"
                    ? <div className="ping-prompt"><strong>{tx("fixed_prompt")}</strong><code>{AGENT_PING_PROMPT}</code><small>{tx("ping_help")}</small></div>
                    : <div className="ping-prompt"><strong>Mock Technical Error</strong><small>{tx("test_help")}</small></div>}
                <div className="test-action-row">
                  <button type="button" className="primary" onClick={() => void testStage()}
                    disabled={testing || busy || !testBackend}>{testing ? tx("testing") : testMode === "stage" ? tx("run_stage") : testMode === "agent_ping" ? tx("run_ping") : tx("run_error")}</button>
                  {testing && <button type="button" className="danger" onClick={() => void stopStageTest()}>{tx("stop_test")}</button>}
                  <button type="button" onClick={() => void testPathFromStage()}
                    disabled={pathTesting || busy || dirtyGraph}
                    title={dirtyGraph ? "Save Workflow before testing path" : "Dry-run saved Workflow from this Stage to END"}>
                    {pathTesting ? "Testing path…" : "Test path to END"}
                  </button>
                </div>
                {testError && <p className="test-error" role="alert">{testError}</p>}
                {pathTestError && <p className="test-error" role="alert">{pathTestError}</p>}
                {testResult && <div className="test-result" aria-live="polite">
                  <div className="test-result-summary"><span className={`result-status ${testResult.status}`}>{testResult.status.toUpperCase()}</span><span>{tx("mode_label")}：<strong>{testMode === "stage" ? "Real Stage" : testMode === "agent_ping" ? "Agent Ping" : "Mock Technical Error"}</strong></span><span>Backend：<strong>{String(testResult.effective_backend || (testResult.data as Record<string, unknown> | undefined)?.backend || testBackend)}</strong></span>{Boolean(testResult.effective_model || (testResult.data as Record<string, unknown> | undefined)?.model) && <span>Model：<strong>{String(testResult.effective_model || (testResult.data as Record<string, unknown> | undefined)?.model)}</strong></span>}
                    {testMode === "stage" && <span>{tx("next_label")}：<strong>{testResult.next}</strong></span>}
                    {testMode === "stage" && testResult.test_retry_policy && <span>{tx("retry_label")}：<strong>{testResult.test_retry_policy}</strong></span>}
                    {testResult.status === "error" && testResult.route === "next" && <span className="skip-result">{tx("retry_exhausted_skip")}</span>}</div>
                  <strong>Output</strong><pre>{testResult.output || tx("no_output")}</pre>
                  {testResult.data != null && Object.keys(testResult.data as object).length > 0 && <details><summary>{tx("structured_data")}</summary><pre>{JSON.stringify(testResult.data, null, 2)}</pre></details>}
                  {!!testResult.changed_files?.length && <details><summary>{tx("changed_files")} · {testResult.changed_files.length}</summary><pre>{testResult.changed_files.join("\n")}</pre></details>}
                </div>}
                {pathTestResult && <div className="test-result path-test-result" aria-live="polite">
                  <div className="test-result-summary">
                    <span className={`result-status ${pathTestResult.completed ? "pass" : "fail"}`}>{pathTestResult.completed ? "CLOSED" : "STOPPED"}</span>
                    <span>From：<strong>{pathTestResult.from_stage}</strong></span>
                    <span>Steps：<strong>{pathTestResult.transitions.length}</strong></span>
                  </div>
                  <strong>Path</strong>
                  <pre>{pathTestResult.transitions.map((item) => `${String(item.number).padStart(3, "0")}  ${item.stage}  ${item.status.toUpperCase()}`).join("\n") || "(no transitions)"}</pre>
                  {pathTestResult.error && <p className="test-error">{pathTestResult.error}</p>}
                </div>}
              </div>}
              </div>
              <footer>
                <div className="footer-actions">
                  <button onClick={() => void duplicateStage()} disabled={busy} title={tx("duplicate_hint")}>{tx("duplicate")}</button>
                  <button className="danger" onClick={() => void deleteStage()} disabled={busy}>{tx("remove")}</button>
                </div>
                <span className="draft-hint">{tx("draft_only")}</span>
              </footer>
          </aside>
        </div>}
      </section> : <section className="workflow-yaml-view">
        <div className="workflow-yaml-toolbar">
          <div><strong>Workflow YAML</strong><small>Canonical workflow definition · Ctrl+S = Save</small></div>
          {yamlError && <span className="workflow-yaml-error">{yamlError}</span>}
        </div>
        <textarea className="workflow-yaml-editor" value={yamlContent}
          onChange={(event) => { setYamlContent(event.target.value); setYamlError(""); }}
          onKeyDown={(event) => {
            if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "s") {
              event.preventDefault();
              void saveYaml();
            }
          }}
          spellCheck={false} autoCapitalize="off" autoComplete="off" />
      </section>}
    </main>
  );
}

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <ReactFlowProvider><App /></ReactFlowProvider>
  </StrictMode>
);
