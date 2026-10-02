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
  type Edge,
  type Node,
  type NodeProps,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import "./styles.css";

type Stage = Record<string, unknown> & {
  name: string;
  type: string;
  status?: string;
  label?: string;
  routes?: Record<string, string>;
  error_policy?: { retries: number };
  max_failures?: number;
  targets?: string[];
};

type Visual = {
  id: string;
  name: string;
  hash: string;
  stages: Stage[];
  flow: string[];
};

type CatalogOption = {
  name: string;
  type: string;
  required?: boolean;
  default?: unknown;
  values?: string[];
  description?: string;
};

type CatalogProfile = {
  title?: string;
  description?: string;
  defaults?: Record<string, unknown>;
};

type CatalogStageType = {
  type: string;
  title?: string;
  description?: string;
  category?: string;
  profiles?: Record<string, CatalogProfile>;
  options: CatalogOption[];
};

type Catalog = {
  stage_types: Record<string, CatalogStageType>;
  node_options?: Record<string, unknown>;
};

type BackendCatalog = {
  default: string;
  backends: string[];
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
};

type StageTestResult = {
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
};

type InspectorTab = "form" | "yaml" | "routing" | "test";
type WorkflowEditorView = "designer" | "yaml";
type StageTestMode = "stage" | "agent_ping";
type ParameterSection = "content" | "execution" | "result" | "advanced";

type DesignerLanguage = "zh-TW" | "en";
const DESIGNER_LANGUAGE_KEY = "ai-task-runner.language";
const DESIGNER_I18N: Record<DesignerLanguage, Record<string, string>> = {
  "zh-TW": {
    back: "← Workflows", mode: "Workflow Editor", unsaved: "未儲存草稿", designer_view: "Designer", yaml_view: "YAML",
    reset: "重設排列", reload: "重新載入", save: "儲存", saving: "驗證與儲存中…",
    palette: "Stage Palette", add_stage: "新增積木", drag_hint: "拖曳積木到畫布才會新增",
    search_stage: "搜尋 Stage…", custom_stage: "自訂 Stage", draft_hint: "畫布上的修改會先保留為草稿，按「儲存」後才更新 YAML。",
    stage_settings: "Stage 設定", form: "Form", basic: "基本", parameters: "參數", yaml_stage: "YAML", routing: "連線", test: "測試", apply_yaml: "套用 YAML",
    close: "關閉", duplicate: "複製積木", remove: "移除積木", draft_only: "修改先存為草稿",
    type_fixed: "類型（建立後固定；要更換請刪除後重新拖入）", display_name: "顯示名稱", run_status: "執行狀態文字",
    result_edges: "結果連線", incoming: "連到這個積木", stage_input: "Stage Input",
    fill_test: "填入簡易測試 Prompt", clear: "清除", run_stage: "執行 Real Stage", run_ping: "執行 Agent Ping",
    testing: "測試中…", no_incoming: "目前沒有連入線。",
    section_content: "內容", section_execution: "執行", section_result: "結果", section_advanced: "進階",
    favorites: "收藏", recent: "最近使用", extensions: "擴充 Stage", add_stage_dialog: "新增 Stage",
    copy: "複製", paste: "貼上", delete: "刪除", delete_connection: "刪除連線", test_pass: "PASS", test_fail: "FAIL", test_error: "ERROR / Retry",
    group_build: "建立與執行", group_validate: "檢查與驗證", group_handoff: "協作", group_tools: "工具"
  },
  en: {
    back: "← Workflows", mode: "Workflow Editor", unsaved: "Unsaved draft", designer_view: "Designer", yaml_view: "YAML",
    reset: "Reset layout", reload: "Reload", save: "Save", saving: "Validating & saving…",
    palette: "Stage Palette", add_stage: "Add Stage", drag_hint: "Drag a Stage onto the canvas to add it",
    search_stage: "Search Stage…", custom_stage: "Custom Stage", draft_hint: "Canvas changes stay as a draft until you Save.",
    stage_settings: "Stage Settings", form: "Form", basic: "Basic", parameters: "Parameters", yaml_stage: "YAML", routing: "Routing", test: "Test", apply_yaml: "Apply YAML",
    close: "Close", duplicate: "Duplicate", remove: "Remove", draft_only: "Changes stay in draft",
    type_fixed: "Type (fixed after creation; delete and recreate to change it)", display_name: "Display name", run_status: "Runtime status text",
    result_edges: "Result edges", incoming: "Incoming", stage_input: "Stage Input",
    fill_test: "Use sample prompt", clear: "Clear", run_stage: "Run Real Stage", run_ping: "Run Agent Ping",
    testing: "Testing…", no_incoming: "No incoming edges.",
    section_content: "Content", section_execution: "Execution", section_result: "Result", section_advanced: "Advanced",
    favorites: "Favorites", recent: "Recent", extensions: "Extensions", add_stage_dialog: "Add Stage",
    copy: "Copy", paste: "Paste", delete: "Delete", delete_connection: "Delete connection", test_pass: "PASS", test_fail: "FAIL", test_error: "ERROR / Retry",
    group_build: "Build & Execute", group_validate: "Review & Validate", group_handoff: "Collaboration", group_tools: "Tools"
  },
};
function initialDesignerLanguage(): DesignerLanguage {
  try { return localStorage.getItem(DESIGNER_LANGUAGE_KEY) === "en" ? "en" : "zh-TW"; } catch { return "zh-TW"; }
}


const AGENT_PING_PROMPT = "Reply with exactly AGENT_PING_OK and nothing else. Do not use tools, do not modify files, and do not inspect the project.";

type StageTestScenario = "pass" | "fail" | "error";
type DesignerConfirmDialog = {
  title: string;
  message: string;
  confirmLabel: string;
  danger?: boolean;
  action: () => void | Promise<void>;
};
const STAGE_TEST_PROMPTS: Record<string, Record<StageTestScenario, string>> = {
  plan: {
    pass: "Create a short, concrete implementation plan with 2-3 verifiable tasks for adding a simple health-check feature. Return valid structured output.",
    fail: "Create a plan that intentionally leaves one acceptance criterion unresolved, so downstream review can identify a concrete missing item. Return valid structured output.",
    error: "Technical ERROR is injected by the Stage Test harness; the model is not asked to fail.",
  },
  task: {
    pass: "Create a small file named stage_test.txt containing exactly STAGE_TEST_OK. Keep the change limited to this isolated Stage test.",
    fail: "Do not satisfy the isolated task acceptance criterion. Explain what remains incomplete without pretending it is finished.",
    error: "Technical ERROR is injected by the Stage Test harness before the real Stage runs.",
  },
  review: {
    pass: "Treat the isolated task evidence as complete and return the normal Review PASS contract with no missing items.",
    fail: "Treat one concrete acceptance criterion as unsatisfied and return the normal Review FAIL contract with one actionable missing item.",
    error: "Technical ERROR is injected by the Stage Test harness; retry then executes the real Review Stage.",
  },
  ai_validator: {
    pass: "Validate the isolated evidence as complete and return the normal validator PASS contract.",
    fail: "Validate the isolated evidence as incomplete and return the normal validator FAIL contract with one concrete missing item.",
    error: "Technical ERROR is injected by the Stage Test harness; retry then executes the real validator.",
  },
  handoff: {
    pass: "Choose one valid allowed target for this isolated test and return a valid handoff decision.",
    fail: "Return a valid handoff decision that explains why no preferred route is suitable, while still respecting the allowed-target contract.",
    error: "Technical ERROR is injected by the Stage Test harness; retry then executes the real Handoff Stage.",
  },
  base: {
    pass: "Reply with a concise confirmation that this isolated AI Stage test ran successfully.",
    fail: "Reply that the isolated test condition is not satisfied and give one concrete reason.",
    error: "Technical ERROR is injected by the Stage Test harness; retry then executes the real AI Stage.",
  },
};

function stageTestPrompt(stage: Stage | null, scenario: StageTestScenario = "pass"): string {
  if (!stage) return "";
  return STAGE_TEST_PROMPTS[stage.type]?.[scenario]
    || STAGE_TEST_PROMPTS.base[scenario];
}


const PARAMETER_SECTIONS: { id: ParameterSection; label: string; fields: string[] }[] = [
  { id: "content", label: "內容", fields: ["prompt", "instructions", "detail", "command", "cwd"] },
  { id: "execution", label: "執行", fields: ["run_state", "mode", "actor", "session_policy", "allow_project_read", "timeout", "readonly_safety", "track_changes", "tolerate_restored_changes", "clean_work"] },
  { id: "result", label: "結果", fields: ["parser", "produces", "result_kind", "runs", "required_passes", "min_tasks", "structured_retries", "structured_fresh_retries"] },
  { id: "advanced", label: "進階", fields: ["session_key", "ai_validator_yolo"] },
];

const START = "__start__";
const END = "__end__";

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
  const p = new URLSearchParams({ view: "prompt", studio: promptId });
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
  const errorRetries = s.error_policy?.retries;
  const reviewSemantic = s.type === "base" && s.profile === "review";
  const reviewErrorSkip = reviewSemantic && Number.isInteger(errorRetries) && Number(errorRetries) >= 0;
  const reviewMaxFailures = reviewSemantic && Number.isInteger(s.max_failures) ? Number(s.max_failures) : 0;
  return (
    <div className={`wf-stage ${selected ? "selected" : ""} type-${s.type}`}>
      <Handle className="stage-input" type="target" position={Position.Top} />
      <div className="wf-stage-head">
        <span className="stage-type">{s.type === "base" && s.profile ? `AI · ${String(s.profile)}` : (STAGE_META[s.type]?.title || String(s.type || "Stage"))}</span>
      </div>
      <strong title={title}>{title}</strong>
      {title !== s.name && <small title={s.name}>{s.name}</small>}
      <div className="wf-stage-meta">
        {data.subtitle === "Not connected to flow" && <span className="disconnected-chip">未連線</span>}
        {reviewErrorSkip && <span>ERR×{errorRetries} → Skip</span>}
        {reviewMaxFailures > 0 && <span>FAIL×{reviewMaxFailures} → 下次 Pass</span>}
        {dynamicRouter && <span>{(s.targets || []).length} targets</span>}
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

function stageByName(visual: Visual, name: string) {
  return visual.stages.find((s) => s.name === name);
}

const STAGE_META: Record<string, { title: string; description: string }> = {
  plan: { title: "Plan", description: "產生 Task[] 規劃" },
  ai_validator: { title: "AI Validator", description: "最終 AI 驗證 / 多次投票" },
  handoff: { title: "Handoff", description: "動態選擇下一個 Stage" },
  command: { title: "Command", description: "執行外部命令或驗證器" },
  base: { title: "AI Stage", description: "通用 AI Stage" },
};

const PALETTE_SECTIONS = [
  { id: "build", types: ["plan", "base"], icon: "✦" },
  { id: "validate", types: ["ai_validator"], icon: "✓" },
  { id: "handoff", types: ["handoff"], icon: "↔" },
  { id: "tools", types: ["command"], icon: "›" },
];
function catalogStageMeta(catalog: Catalog | null, type: string) {
  const catalogMeta = catalog?.stage_types?.[type];
  const fallback = STAGE_META[type];
  return {
    title: String(catalogMeta?.title || fallback?.title || type),
    description: String(catalogMeta?.description || fallback?.description || ""),
    category: String(catalogMeta?.category || (PALETTE_SECTIONS.find((section) => section.types.includes(type))?.id ?? "extensions")),
  };
}

const PALETTE_PREF_KEY = "workflow-designer.palette:v1";
type PalettePrefs = { favorites: string[]; recent: string[]; collapsed: string[] };

function readPalettePrefs(): PalettePrefs {
  try {
    const raw = JSON.parse(localStorage.getItem(PALETTE_PREF_KEY) || "{}");
    return {
      favorites: Array.isArray(raw.favorites) ? raw.favorites.filter((v: unknown) => typeof v === "string") : [],
      recent: Array.isArray(raw.recent) ? raw.recent.filter((v: unknown) => typeof v === "string").slice(0, 5) : [],
      collapsed: Array.isArray(raw.collapsed) ? raw.collapsed.filter((v: unknown) => typeof v === "string") : [],
    };
  } catch {
    return { favorites: [], recent: [], collapsed: [] };
  }
}

function writePalettePrefs(prefs: PalettePrefs): void {
  try { localStorage.setItem(PALETTE_PREF_KEY, JSON.stringify(prefs)); } catch { /* local-only convenience */ }
}

function defaultOption(catalog: Catalog | null, stageType: string, name: string): unknown {
  return catalog?.stage_types?.[stageType]?.options?.find((item) => item.name === name)?.default;
}

function effectivePrompt(catalog: Catalog | null, stage: Stage): string {
  const explicit = String(stage.prompt || "").trim();
  if (explicit) return explicit;
  if (stage.type === "base") {
    const profile = String(stage.profile || "generic");
    const profilePrompt = catalog?.stage_types?.base?.profiles?.[profile]?.defaults?.prompt;
    if (typeof profilePrompt === "string" && profilePrompt.trim()) return profilePrompt.trim();
  }
  return String(defaultOption(catalog, stage.type, "prompt") || "").trim();
}

function nextStageKey(visual: Visual, type: string): string {
  const base = type === "base" ? "ai_stage" : type === "ai_validator" ? "validate_ai" : type;
  const used = new Set(visual.stages.map((s) => s.name));
  if (!used.has(base)) return base;
  let i = 2;
  while (used.has(`${base}_${i}`)) i += 1;
  return `${base}_${i}`;
}

type CanvasPosition = { x: number; y: number };
type CanvasLayout = Record<string, CanvasPosition>;

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
      },
      deletable: false,
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
          markerEnd: { type: MarkerType.ArrowClosed },
          data: { status, explicit: true, terminal: target },
        });
      });
      return;
    }
    const passTarget = routes.pass || (next ? "next" : "done");
    const resolvedPass = passTarget === "next" ? (next || END) : passTarget === "done" || passTarget === "stop" ? END : passTarget;
    const passClass = routes.pass ? "result pass" : "normal pass";
    edges.push({
      id: `${name}:pass:${resolvedPass}`,
      source: name,
      sourceHandle: "pass",
      target: resolvedPass,
      className: passClass,
      deletable: Boolean(routes.pass),
      markerEnd: { type: MarkerType.ArrowClosed },
      data: { status: "pass", explicit: Boolean(routes.pass), terminal: passTarget },
    });
    const failTarget = routes.fail;
    if (failTarget) {
      const resolved = failTarget === "done" || failTarget === "stop" ? END : failTarget === "next" ? (next || END) : failTarget;
      edges.push({
        id: `${name}:fail:${resolved}`,
        source: name,
        sourceHandle: "fail",
        target: resolved,
        className: "result fail",
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
  const layoutRef = useRef<CanvasLayout>({});
  const undoStackRef = useRef<Visual[]>([]);
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
  const [backendCatalog, setBackendCatalog] = useState<BackendCatalog>({ default: "", backends: [] });
  const [nodes, setNodes] = useState<Node<StudioNodeData>[]>([]);
  const [edges, setEdges] = useState<Edge[]>([]);
  const [selected, setSelected] = useState<string>("");
  const [draft, setDraft] = useState<Stage | null>(null);
  const [dirtyGraph, setDirtyGraph] = useState(false);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
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
  const [paletteQuery, setPaletteQuery] = useState("");
  const [palettePrefs, setPalettePrefs] = useState<PalettePrefs>(readPalettePrefs());
  const [addStageOpen, setAddStageOpen] = useState(false);
  const [addStageQuery, setAddStageQuery] = useState("");
  const [copiedStage, setCopiedStage] = useState<Stage | null>(null);
  const [contextMenu, setContextMenu] = useState<{ x: number; y: number; stage: string } | null>(null);
  const [edgeContextMenu, setEdgeContextMenu] = useState<{ x: number; y: number; edge: Edge } | null>(null);
  const [confirmDialog, setConfirmDialog] = useState<DesignerConfirmDialog | null>(null);
  const [editorOpen, setEditorOpen] = useState(false);
  const [language, setLanguage] = useState<DesignerLanguage>(initialDesignerLanguage());
  const tx = useCallback((key: string) => DESIGNER_I18N[language]?.[key] || DESIGNER_I18N["zh-TW"][key] || key, [language]);
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
        api<BackendCatalog>("/api/backends"),
      ]);
      setVisual(v);
      setYamlContent(String(file.content || ""));
      setYamlOriginal(String(file.content || ""));
      setYamlError("");
      setCatalog(c);
      setPrompts(files.prompts || []);
      setBackendCatalog(backends);
      setTestBackend((current) => current || backends.default || backends.backends?.[0] || "");
      layoutRef.current = readLayout(v.id);
      const g = graphFor(v, c);
      setNodes(g.nodes);
      setEdges(g.edges);
      setDirtyGraph(false);
      undoStackRef.current = [];
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
        if (addStageOpen) setAddStageOpen(false);
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
      if (ctrl && event.key.toLowerCase() === "z") {
        event.preventDefault();
        undoVisualDraft();
        return;
      }
      const selectedExplicitEdge = edges.find((edge) => edge.selected && edge.data?.explicit);
      if ((event.key === "Delete" || event.key === "Backspace") && selectedExplicitEdge) {
        event.preventDefault();
        deleteEdges([selectedExplicitEdge]);
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
    if (!visual || !selected) { setDraft(null); return; }
    const s = stageByName(visual, selected);
    setDraft(s ? structuredClone(s) : null);
  }, [selected, visual]);

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
  const parameterOptions = options.filter((o) => {
    if (["name", "type", "status", "label", "routes", "targets", "max_failures", "profile"].includes(o.name)) return false;
    if (o.name === "session_key" && String(draft?.session_policy || "auto") !== "auto") return false;
    return true;
  });
  const parameterGroups = PARAMETER_SECTIONS.map((section) => ({
    ...section,
    options: parameterOptions.filter((option) => section.id === "advanced"
      ? !PARAMETER_SECTIONS.slice(0, -1).some((group) => group.fields.includes(option.name))
      : section.fields.includes(option.name)),
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
  }

  function undoVisualDraft() {
    if (!visual || undoStackRef.current.length === 0) {
      setMessage("沒有可復原的 Workflow 修改。");
      return;
    }
    const previous = undoStackRef.current[undoStackRef.current.length - 1];
    undoStackRef.current = undoStackRef.current.slice(0, -1);
    setVisual(previous);
    const graph = graphFor(previous, catalog);
    setNodes(graph.nodes);
    setEdges(graph.edges);
    setSelected("");
    setDraft(null);
    setEditorOpen(false);
    setContextMenu(null);
    setEdgeContextMenu(null);
    setDirtyGraph(true);
    setMessage("已復原上一個 Workflow 草稿修改。");
  }

  function editDraft(next: Stage) {
    setDraft(next);
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
  }

  async function testStage() {
    if (!visual || !draft || testing || busy) return;
    setTesting(true);
    setTestResult(null);
    setTestError("");
    try {
      const result = await api<StageTestResult>("/api/studio/stage/test", {
        method: "POST",
        body: JSON.stringify({
          id: visual.id, project: query().project, stage: draft.name, input: testInput,
          backend: testBackend, probe_mode: testMode,
          test_scenario: testMode === "stage" ? (testScenario === "error" ? "error_mock" : testScenario) : "pass",
          graph: graphDraft(visual),
        }),
      });
      setTestResult(result);
    } catch (error) {
      setTestError(error instanceof Error ? error.message : String(error));
    } finally {
      setTesting(false);
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
    const g = graphFor(result.visual, catalog);
    setNodes(g.nodes);
    setEdges(g.edges);
    setDirtyGraph(false);
    undoStackRef.current = [];
    return result.visual;
  }, [catalog, graphFor]);

  const saveGraph = useCallback(async (nextVisual = visual): Promise<boolean> => {
    if (!nextVisual) return false;
    setBusy(true);
    try {
      await persistGraph(nextVisual);
      setMessage("Workflow saved");
      return true;
    } catch (error) {
      setMessage(error instanceof Error ? error.message : String(error));
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
      const g = graphFor(refreshed, catalog);
      setNodes(g.nodes);
      setEdges(g.edges);
      setDirtyGraph(false);
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
    if (next === editorView) return;
    const currentDirty = editorView === "yaml" ? yamlDirty : dirtyGraph;
    const apply = async () => {
      if (currentDirty) {
        const saved = await saveCurrent();
        if (!saved) return;
      }
      if (next === "designer" && visual) {
        const refreshed = await api<Visual>(endpoint("/api/studio/visual"));
        setVisual(refreshed);
        const g = graphFor(refreshed, catalog);
        setNodes(g.nodes);
        setEdges(g.edges);
      } else if (next === "yaml" && visual) {
        const file = await api<StudioFile>(endpoint("/api/studio/file"));
        setYamlContent(String(file.content || ""));
        setYamlOriginal(String(file.content || ""));
      }
      setEditorView(next);
      setYamlError("");
    };
    if (!currentDirty) { void apply(); return; }
    requestConfirm({
      title: "儲存並切換視圖？",
      message: "Workflow Editor 只維護一份 canonical YAML。先儲存目前修改，再切換 Designer / YAML，避免兩份草稿分岔。",
      confirmLabel: "儲存並切換",
      action: apply,
    });
  }

  const connect = useCallback((connection: Connection) => {
    if (!visual || !connection.source || !connection.target) return;
    rememberUndoSnapshot(visual);
    const status = String(connection.sourceHandle || "pass").toLowerCase();
    if (connection.source === START) {
      if (connection.target === END) return;
      const flow = [connection.target, ...visual.flow.filter((x) => x !== connection.target)];
      const next = { ...visual, flow };
      setVisual(next);
      const g = graphFor(next, catalog);
      setNodes(g.nodes);
      setEdges(g.edges);
      setDirtyGraph(true);
      return;
    }
    if (connection.source === END || connection.target === START || !["pass", "fail", "handoff"].includes(status)) return;
    if (status === "handoff" && connection.target === END) return;
    let nextFlow = [...visual.flow];
    if (!nextFlow.includes(connection.source)) {
      nextFlow.push(connection.source);
    }
    if (connection.target !== END && !nextFlow.includes(connection.target)) {
      if (status === "pass" || status === "handoff") {
        const sourceIndex = nextFlow.indexOf(connection.source);
        const insertAt = sourceIndex >= 0 ? sourceIndex + 1 : nextFlow.length;
        nextFlow.splice(insertAt, 0, connection.target);
      } else {
        // A FAIL branch must not change the source Stage's implicit PASS -> next.
        nextFlow.push(connection.target);
      }
    }
    const stages = visual.stages.map((stage) => {
      if (stage.name !== connection.source) return stage;
      const routes = { ...(stage.routes || {}) };
      const index = nextFlow.indexOf(stage.name);
      const nextName = nextFlow[index + 1];
      let target = connection.target!;
      if (status === "handoff") {
        const targets = Array.from(new Set([...(stage.targets || []), target]));
        return { ...stage, targets };
      }
      if (target === END) target = status === "pass" ? "done" : "stop";
      if (status === "pass" && target === nextName) delete routes.pass;
      else routes[status] = target;
      return { ...stage, routes };
    });
    const next = { ...visual, stages, flow: nextFlow };
    setVisual(next);
    const g = graphFor(next, catalog);
    setNodes(g.nodes);
    setEdges(g.edges);
    setDirtyGraph(true);
  }, [visual, catalog, graphFor]);

  const deleteEdges = useCallback((removed: Edge[]) => {
    if (!visual) return;
    const explicit = removed.filter((edge) => edge.data?.explicit);
    if (!explicit.length) return;
    rememberUndoSnapshot(visual);
    let stages = visual.stages;
    removed = explicit;
    for (const edge of removed) {
      const status = String(edge.data?.status || "");
      if (!status || !edge.data?.explicit) continue;
      stages = stages.map((s) => {
        if (s.name !== edge.source) return s;
        if (status === "handoff") {
          return { ...s, targets: (s.targets || []).filter((target) => target !== edge.target) };
        }
        const routes = { ...(s.routes || {}) };
        delete routes[status];
        return { ...s, routes };
      });
    }
    const next = { ...visual, stages };
    setVisual(next);
    const g = graphFor(next, catalog);
    setNodes(g.nodes);
    setEdges(g.edges);
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

    ["prompt", "status", "max_failures", "error_policy"].forEach((key) => {
      const current = cleaned[key];
      const previous = previousDefaults[key];
      if (previous !== undefined && JSON.stringify(current) === JSON.stringify(previous)) {
        delete cleaned[key];
      }
    });

    if (profile !== "review") delete cleaned.max_failures;
    ["prompt", "status", "max_failures", "error_policy"].forEach((key) => {
      const value = nextDefaults[key];
      if (value !== undefined && (cleaned[key] === undefined || cleaned[key] === "")) {
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
    const next = { ...visual, stages: [...visual.stages, stage] };
    rememberUndoSnapshot(visual);
    setVisual(next);
    if (position) {
      layoutRef.current = { ...layoutRef.current, [name]: position };
      writeLayout(visual.id, layoutRef.current);
    }
    const g = graphFor(next, catalog);
    setNodes(g.nodes);
    setEdges(g.edges);
    setSelected(name);
    setEditorOpen(true);
    setPendingCreate(null);
    setCreatePrompt("");
    setCreateCommand("");
    setDirtyGraph(true);
    setMessage(`Stage ${name} 已加入草稿。儲存 Workflow 後才會寫入 YAML。`);
  }

  function rememberPaletteStage(stageType: string) {
    setPalettePrefs((current) => {
      const next = { ...current, recent: [stageType, ...current.recent.filter((item) => item !== stageType)].slice(0, 5) };
      writePalettePrefs(next);
      return next;
    });
  }

  function toggleFavoriteStage(stageType: string) {
    setPalettePrefs((current) => {
      const favorites = current.favorites.includes(stageType)
        ? current.favorites.filter((item) => item !== stageType)
        : [stageType, ...current.favorites];
      const next = { ...current, favorites };
      writePalettePrefs(next);
      return next;
    });
  }

  function togglePaletteSection(sectionId: string) {
    setPalettePrefs((current) => {
      const collapsed = current.collapsed.includes(sectionId)
        ? current.collapsed.filter((item) => item !== sectionId)
        : [...current.collapsed, sectionId];
      const next = { ...current, collapsed };
      writePalettePrefs(next);
      return next;
    });
  }

  async function addStage(stageType = "base", position?: { x: number; y: number }) {
    rememberPaletteStage(stageType);
    if (stageType === "base" || stageType === "command") {
      setPendingCreate({ type: stageType, position });
      setCreateAIProfile("generic");
      setCreatePrompt(stageType === "base" ? String(defaultOption(catalog, stageType, "prompt") || "") : "");
      setCreateCommand("");
      return;
    }
    await createStage(stageType, position);
  }

  async function confirmPendingCreate() {
    if (!pendingCreate) return;
    if (pendingCreate.type === "base" && createAIProfile === "generic" && !createPrompt.trim()) {
      setMessage("Generic AI Stage requires a Prompt.");
      return;
    }
    if (pendingCreate.type === "command" && !createCommand.trim()) {
      setMessage("Command Stage requires a command.");
      return;
    }
    await createStage(pendingCreate.type, pendingCreate.position, createPrompt.trim(), createCommand.trim(), createAIProfile);
  }

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
    const copy = structuredClone(source);
    delete copy.routes;
    if (copy.type === "handoff") copy.targets = [];
    setCopiedStage(copy);
    setMessage(`已複製 Stage ${name} 設定；貼上時不會複製結果連線。`);
  }

  function pasteStage(position?: { x: number; y: number }) {
    if (!visual || !copiedStage) return;
    const name = nextStageKey(visual, copiedStage.type);
    const copy: Stage = structuredClone({ ...copiedStage, name });
    delete copy.routes;
    if (copy.type === "handoff") copy.targets = [];
    const sourceIndex = selected ? visual.flow.indexOf(selected) : -1;
    const flow = [...visual.flow];
    if (sourceIndex >= 0) flow.splice(sourceIndex + 1, 0, name);
    const next = { ...visual, flow, stages: [...visual.stages, copy] };
    rememberUndoSnapshot(visual);
    setVisual(next);
    const sourcePosition = selected ? layoutRef.current[selected] : undefined;
    const targetPosition = position || (sourcePosition ? { x: sourcePosition.x + 260, y: sourcePosition.y + 40 } : undefined);
    if (targetPosition) {
      layoutRef.current = { ...layoutRef.current, [name]: targetPosition };
      writeLayout(visual.id, layoutRef.current);
    }
    const g = graphFor(next, catalog);
    setNodes(g.nodes);
    setEdges(g.edges);
    setSelected(name);
    setDirtyGraph(true);
    setMessage(`Stage 已貼上為 ${name}；結果連線未複製。`);
  }

  async function duplicateStage(name = draft?.name || selected) {
    if (!name || !visual) return;
    copyStageByName(name);
    const source = stageByName(visual, name);
    if (!source) return;
    const stageCopy = structuredClone(source);
    delete stageCopy.routes;
    if (stageCopy.type === "handoff") stageCopy.targets = [];
    const newName = nextStageKey(visual, stageCopy.type);
    const copy: Stage = { ...stageCopy, name: newName };
    const sourceIndex = visual.flow.indexOf(name);
    const flow = [...visual.flow];
    if (sourceIndex >= 0) flow.splice(sourceIndex + 1, 0, newName);
    const next = { ...visual, flow, stages: [...visual.stages, copy] };
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
    const g = graphFor(next, catalog);
    setNodes(g.nodes);
    setEdges(g.edges);
    setSelected(newName);
    setDirtyGraph(true);
    setMessage(`Stage ${name} 已複製為 ${newName}；結果連線不會一起複製。`);
  }

  function requestConfirm(dialog: DesignerConfirmDialog) {
    setContextMenu(null);
    setConfirmDialog(dialog);
  }

  async function deleteStage(name = draft?.name || selected) {
    if (!visual || !name) return;
    if (visual.stages.some((stage) => stage.name !== name && (
      Object.values(stage.routes || {}).includes(name) || (stage.targets || []).includes(name)
    ))) {
      setMessage(`請先移除指向 ${name} 的結果連線。`);
      return;
    }
    requestConfirm({
      title: "移除 Stage",
      message: `從草稿移除 Stage "${name}"？儲存 Workflow 後才會更新 YAML。`,
      confirmLabel: "移除",
      danger: true,
      action: () => {
        const current = visual;
        const next = { ...current, flow: current.flow.filter((item) => item !== name), stages: current.stages.filter((stage) => stage.name !== name) };
        rememberUndoSnapshot(current);
        setVisual(next);
        const g = graphFor(next, catalog);
        setNodes(g.nodes);
        setEdges(g.edges);
        setSelected("");
        setEditorOpen(false);
        setContextMenu(null);
        setDirtyGraph(true);
        setMessage(`Stage ${name} 已從草稿移除。`);
      },
    });
  }

  function resetLayout() {
    if (!visual) return;
    layoutRef.current = {};
    try { localStorage.removeItem(layoutKey(visual.id)); } catch { /* Ignore unavailable browser storage. */ }
    setNodes(graphFor(visual, catalog).nodes);
    setMessage("已重設畫布位置；Workflow 執行順序沒有變動。");
  }

  function leaveStudio() {
    const leave = () => { window.location.href = workflowStudioUrl(); };
    if (!editorDirty) { leave(); return; }
    requestConfirm({
      title: "捨棄未儲存變更？",
      message: "目前 Workflow 還有未儲存的草稿。離開後這些變更會遺失。",
      confirmLabel: "捨棄並離開",
      danger: true,
      action: leave,
    });
  }

  function reloadStudio() {
    if (!editorDirty) { void load(); return; }
    requestConfirm({
      title: "重新載入 Workflow？",
      message: "目前未儲存的 Workflow 草稿會被捨棄，並重新載入磁碟上的版本。",
      confirmLabel: "捨棄並重新載入",
      danger: true,
      action: () => { void load(); },
    });
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
          {editorDirty && <span className="unsaved-badge">{tx("unsaved")}</span>}
          {editorView === "designer" && <button onClick={resetLayout} disabled={busy} title="只重設畫布位置，不變更 YAML">{tx("reset")}</button>}
          <button onClick={reloadStudio} disabled={busy}>{tx("reload")}</button>
          <button className="primary" onClick={() => void saveCurrent()} disabled={busy || !editorDirty}>
            {busy ? tx("saving") : tx("save")}
          </button>
        </div>
      </header>

      {editorView === "designer" ? <section className="studio-body">
        <aside className="palette">
          <div className="palette-head">
            <div className="palette-title-row"><span><span className="palette-eyebrow">{tx("palette")}</span><strong>{tx("add_stage")}</strong></span>
              <button type="button" className="palette-command-add" title="Add Stage (/)" onClick={() => { setAddStageOpen(true); setAddStageQuery(""); }}>＋</button>
            </div>
            <small>{tx("drag_hint")}</small>
          </div>
          <input className="palette-search" value={paletteQuery} onChange={(e) => setPaletteQuery(e.target.value)}
            placeholder={tx("search_stage")} aria-label={tx("search_stage")} />
          {(() => {
            const q = paletteQuery.trim().toLowerCase();
            const allTypes = Object.keys(catalog?.stage_types || {});
            const knownTypes = new Set(allTypes.filter((type) => catalogStageMeta(catalog, type).category !== "extensions"));
            const matches = (type: string) => {
              if (!q) return true;
              const meta = catalogStageMeta(catalog, type);
              return [type, meta?.title, meta?.description].some((value) => String(value || "").toLowerCase().includes(q));
            };
            const item = (type: string, icon = "◇") => {
              const meta = catalogStageMeta(catalog, type);
              const favorite = palettePrefs.favorites.includes(type);
              return <div key={type} className="palette-item" draggable={!busy} title={meta.description}
                onDragStart={(event) => dragStage(event, type)}>
                <span className={`palette-icon type-${type}`} aria-hidden="true">{icon}</span>
                <span className="palette-copy"><strong>{meta.title}</strong></span>
                <button type="button" className={`palette-favorite ${favorite ? "active" : ""}`} disabled={busy}
                  aria-label={favorite ? `Unfavorite ${meta.title}` : `Favorite ${meta.title}`}
                  title={favorite ? "Remove favorite" : "Favorite"}
                  onMouseDown={(event) => event.stopPropagation()}
                  onClick={(event) => { event.stopPropagation(); toggleFavoriteStage(type); }}>{favorite ? "★" : "☆"}</button>
                <button type="button" className="palette-quick-add" disabled={busy}
                  aria-label={`Add ${meta.title}`} title={`Add ${meta.title}`}
                  onMouseDown={(event) => event.stopPropagation()}
                  onClick={(event) => { event.stopPropagation(); void addStage(type); }}>＋</button>
              </div>;
            };
            const groups: { id: string; title: string; icon: string; types: string[] }[] = [];
            const favoriteTypes = palettePrefs.favorites.filter((type) => allTypes.includes(type) && matches(type));
            if (favoriteTypes.length) groups.push({ id: "favorites", title: tx("favorites"), icon: "★", types: favoriteTypes });
            const recentTypes = palettePrefs.recent.filter((type) => allTypes.includes(type) && !favoriteTypes.includes(type) && matches(type));
            if (recentTypes.length) groups.push({ id: "recent", title: tx("recent"), icon: "↺", types: recentTypes });
            PALETTE_SECTIONS.forEach((section) => {
              const types = allTypes.filter((type) => catalogStageMeta(catalog, type).category === section.id && matches(type));
              if (types.length) groups.push({ id: section.id, title: tx(`group_${section.id}`), icon: section.icon, types });
            });
            const customCategories = Array.from(new Set(allTypes.map((type) => catalogStageMeta(catalog, type).category)
              .filter((category) => category && category !== "extensions" && !PALETTE_SECTIONS.some((section) => section.id === category))));
            customCategories.forEach((category) => {
              const types = allTypes.filter((type) => catalogStageMeta(catalog, type).category === category && matches(type));
              if (types.length) groups.push({ id: `plugin:${category}`, title: category, icon: "◇", types });
            });
            const extensionTypes = allTypes.filter((type) => !knownTypes.has(type) && matches(type));
            if (extensionTypes.length) groups.push({ id: "extensions", title: tx("extensions"), icon: "◇", types: extensionTypes });
            return groups.map((group) => {
              const collapsed = !q && palettePrefs.collapsed.includes(group.id);
              return <div className="palette-section" key={group.id}>
                <button type="button" className="palette-section-head" onClick={() => togglePaletteSection(group.id)}
                  aria-expanded={!collapsed}>
                  <span><i className={`palette-chevron ${collapsed ? "collapsed" : "expanded"}`} aria-hidden="true" />{group.title}</span><small>{group.types.length}</small>
                </button>
                {!collapsed && <div className="palette-list">{group.types.map((type) => item(type, group.icon))}</div>}
              </div>;
            });
          })()}
          <div className="palette-note compact"><small>{tx("drag_hint")} · ＋ / = quick add · Enter = edit selected</small></div>
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
            onEdgesDelete={deleteEdges}
            onEdgeClick={() => { setSelected(""); setContextMenu(null); setEdgeContextMenu(null); }}
            onEdgeContextMenu={(event, edge) => {
              if (!edge.data?.explicit) return;
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
          onMouseDown={(event) => { if (event.target === event.currentTarget) setAddStageOpen(false); }}>
          <div className="add-stage-command">
            <div className="add-stage-command-head"><strong>{tx("add_stage_dialog")}</strong><button type="button" onClick={() => setAddStageOpen(false)}>×</button></div>
            <input autoFocus value={addStageQuery} onChange={(event) => setAddStageQuery(event.target.value)} placeholder={tx("search_stage")} />
            <div className="add-stage-command-list">
              {Object.keys(catalog?.stage_types || {}).filter((type) => {
                const q = addStageQuery.trim().toLowerCase();
                const meta = catalogStageMeta(catalog, type);
                return !q || [type, meta?.title, meta?.description].some((value) => String(value || "").toLowerCase().includes(q));
              }).map((type) => {
                const meta = catalogStageMeta(catalog, type);
                return <button type="button" key={type} onClick={() => { setAddStageOpen(false); void addStage(type); }}>
                  <span className={`palette-icon type-${type}`}>{PALETTE_SECTIONS.find((section) => section.id === catalogStageMeta(catalog, type).category)?.icon || "◇"}</span>
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
              {pendingCreate.type === "command" && (
                <label>
                  <span>Command</span>
                  <textarea rows={4} value={createCommand} onChange={(e) => setCreateCommand(e.target.value)} placeholder="python tool/my_validator.py" />
                </label>
              )}
              <div className="create-stage-actions">
                <button type="button" onClick={() => setPendingCreate(null)} disabled={busy}>Cancel</button>
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
              <button type="button" onClick={() => setConfirmDialog(null)}>取消</button>
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
                <div className="inspector-head-actions"><span>{draft.type}</span><button type="button" className="modal-close-button" onClick={() => setEditorOpen(false)} aria-label={tx("close")}>×</button></div>
              </div>
              <div className="inspector-tabs" role="tablist" aria-label="Stage sections">
                {(["form", "yaml", "routing", "test"] as const).map((tab) => (
                  <button key={tab} type="button" role="tab" aria-selected={inspectorTab === tab}
                    className={inspectorTab === tab ? "active" : ""} onClick={() => {
                      setInspectorTab(tab);
                      if (tab === "yaml") void loadStageYaml();
                    }}>
                    {{ form: tx("form"), yaml: tx("yaml_stage"), routing: tx("routing"), test: tx("test") }[tab]}
                  </button>
                ))}
              </div>
              <div className="stage-editor-content">
              {inspectorTab === "form" && <div className="fields stage-form-panel" role="tabpanel">
                <section className="stage-form-section">
                  <div className="stage-form-section-head"><strong>{tx("basic")}</strong><small>Stage identity and behavior</small></div>
                <label>
                  <span>{tx("type_fixed")}</span>
                  <select value={draft.type} disabled>
                    {Object.keys(catalog?.stage_types || {}).map((t) => <option key={t}>{t}</option>)}
                  </select>
                </label>
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
                <label><span>{tx("display_name")}（Stage key 不變）</span><input ref={titleInputRef} value={String(draft.label || "")} placeholder={draft.name} onChange={(e) => editDraft({ ...draft, label: e.target.value })} /></label>
                <label><span>{tx("run_status")}</span><input value={String(draft.status || "")} onChange={(e) => editDraft({ ...draft, status: e.target.value })} /></label>
                </section>
                <section className="stage-form-section">
                  <div className="stage-form-section-head"><strong>{tx("parameters")}</strong><small>{parameterOptions.length} fields</small></div>
                {parameterOptions.length === 0 && <p className="section-empty">此積木沒有其他參數。</p>}
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
                      option={option}
                      value={draft[option.name]}
                      onChange={(value) => {
                        if (option.name === "session_policy" && String(value || "auto") !== "auto") {
                          const { session_key: _sessionKey, ...rest } = draft;
                          editDraft({ ...rest, session_policy: value });
                          return;
                        }
                        editDraft({ ...draft, [option.name]: value });
                      }}
                    />
                  ))}
                </section>
              </div>}
              {inspectorTab === "yaml" && <div className="stage-yaml-panel" role="tabpanel">
                <div className="stage-yaml-toolbar">
                  <div><strong>Stage YAML</strong><small>同一份 Stage draft；type 與 key 不可在此變更。</small></div>
                  <button type="button" onClick={() => void applyStageYaml()} disabled={stageYamlLoading}>{stageYamlLoading ? "…" : tx("apply_yaml")}</button>
                </div>
                {stageYamlError && <div className="stage-yaml-error">{stageYamlError}</div>}
                <textarea value={stageYaml} onChange={(event) => { setStageYaml(event.target.value); setStageYamlError(""); }}
                  spellCheck={false} autoCapitalize="off" autoComplete="off" />
              </div>}
              {inspectorTab === "routing" && <div className="edge-help" role="tabpanel">
                <strong>{tx("result_edges")}</strong>
                <p>從積木下方的大接點拉到目標積木。PASS / FAIL 是 Workflow 結果；ERROR 不建立連線。</p>
                {(draft.type === "base" && draft.profile === "review")
                  ? <p>Review 是 fail-soft gate：technical ERROR 由 error_policy 控制；semantic FAIL 由 max_failures 控制。允許真的 FAIL N 次；下一次進入 Review 時不呼叫 Agent，直接走 fail-soft PASS 並清零。正常 PASS 也會清零。</p>
                  : <p>ERROR 依本積木的重試次數執行；留空沿用全域 stage_retries（預設 -1）。非 Review Stage 的有限 retry 用盡後會停在目前 Stage。</p>}
                <label className="route-policy-field"><span>{(draft.type === "base" && draft.profile === "review") ? "ERROR 重試次數（有限值耗盡後 Skip）" : "ERROR 重試次數"}</span><input type="number" min={-1}
                  value={draft.error_policy?.retries ?? ""} placeholder="沿用全域設定"
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
                    <strong>ERROR</strong><span>重試耗盡 → 下一個積木（Skip Review）</span>
                  </div>}
                {(draft.type === "base" && draft.profile === "review") && <>
                  <label className="route-policy-field"><span>Semantic FAIL 上限（max_failures）</span><input type="number" min={1}
                    value={draft.max_failures ?? ""} placeholder="不限制"
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
                    <small>允許連續 FAIL 此次數；下一次進入 Review 直接 PASS，不呼叫 Agent。PASS 或放行後 counter 清 0。</small>
                  </label>
                  {Number.isInteger(draft.max_failures) && Number(draft.max_failures) > 0 &&
                    <div className="route-row failure-cap-row"><span className="route-dot fail" />
                      <strong>FAIL×{Number(draft.max_failures)}</strong><span>下一次進入 → 直接 PASS（不呼叫 Agent，counter 清 0）</span>
                    </div>}
                </>}
                <div className="route-section-title">從這個積木出去</div>
                {draft.type === "handoff"
                  ? edges.filter((edge) => edge.source === draft.name && edge.data?.status === "handoff").map((edge) =>
                    <div className="route-row" key={edge.id}><span className="route-dot pass" />
                      <strong>{String(edge.data?.status || "").toUpperCase()}</strong><span>{edge.target}</span>
                    </div>
                  ) : (["pass", "fail"] as const).map((status) => {
                  const edge = edges.find((item) => item.source === draft.name && item.data?.status === status);
                  const terminal = String(edge?.data?.terminal || "");
                  const target = edge?.target === END
                    ? terminal === "stop" ? "END（停止）" : "END（完成）"
                    : edge?.target || (status === "pass" ? "下一個積木（預設）" : "停止（預設）");
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
                <p>測試只停留在目前積木/agent，不會沿 Workflow 繼續執行。Real Stage 使用目前草稿的 Prompt、Parser、Session Policy 與 local Error Policy；為避免測試掛死，local -1 在測試中最多 retry 2 次，未設定 local policy 則只做單次 attempt。正式 Runtime 的全域 stage_retries 不受影響。Agent Ping 只驗證 backend/agent transport。</p>
                <div className="test-mode-tabs" role="tablist" aria-label="Stage test mode">
                  <button type="button" role="tab" aria-selected={testMode === "stage"} className={testMode === "stage" ? "active" : ""}
                    onClick={() => { setTestMode("stage"); setTestResult(null); setTestError(""); }}>Real Stage</button>
                  <button type="button" role="tab" aria-selected={testMode === "agent_ping"} className={testMode === "agent_ping" ? "active" : ""}
                    onClick={() => { setTestMode("agent_ping"); setTestResult(null); setTestError(""); }}>Agent Ping</button>
                </div>
                <label><span>Backend</span><select value={testBackend} onChange={(e) => setTestBackend(e.target.value)}>
                  {(backendCatalog.backends || []).map((name) => <option key={name} value={name}>{name}{name === backendCatalog.default ? "（default）" : ""}</option>)}
                </select></label>
                {testMode === "stage"
                  ? <label><span>{tx("stage_input")}</span>
                      <div className="test-scenario-tabs" role="group" aria-label="Stage test prompt scenario">
                        {(["pass", "fail", "error"] as StageTestScenario[]).map((scenario) => <button type="button" key={scenario}
                          className={testScenario === scenario ? `active scenario-${scenario}` : `scenario-${scenario}`}
                          onClick={() => { setTestScenario(scenario); setTestInput(stageTestPrompt(draft, scenario)); }}>
                          {{ pass: tx("test_pass"), fail: tx("test_fail"), error: tx("test_error") }[scenario]}
                        </button>)}
                      </div>
                      <div className="test-input-actions">
                        <button type="button" onClick={() => setTestInput(stageTestPrompt(draft, testScenario))}>{tx("fill_test")}</button>
                        {testInput && <button type="button" onClick={() => setTestInput("")}>{tx("clear")}</button>}
                      </div>
                      <textarea value={testInput} onChange={(e) => setTestInput(e.target.value)} rows={5}
                        placeholder={stageTestPrompt(draft, testScenario) || "輸入這個積木要接收的內容"} />
                      <small>依 Stage 類型提供最小合法測試內容；只作用於本次 isolated Stage Test，不會修改 Workflow Prompt。</small>
                    </label>
                  : <div className="ping-prompt"><strong>固定 Prompt</strong><code>{AGENT_PING_PROMPT}</code><small>不使用工具、不讀專案、不修改檔案，只確認 agent 能正常回覆。</small></div>}
                <button type="button" className="primary" onClick={() => void testStage()}
                  disabled={testing || busy || !testBackend}>{testing ? tx("testing") : testMode === "stage" ? tx("run_stage") : tx("run_ping")}</button>
                {testError && <p className="test-error" role="alert">{testError}</p>}
                {testResult && <div className="test-result" aria-live="polite">
                  <div className="test-result-summary"><span className={`result-status ${testResult.status}`}>{testResult.status.toUpperCase()}</span><span>模式：<strong>{testMode === "stage" ? "Real Stage" : "Agent Ping"}</strong></span><span>Backend：<strong>{testBackend}</strong></span>
                    {testMode === "stage" && <span>下一個：<strong>{testResult.next}</strong></span>}
                    {testMode === "stage" && testResult.test_retry_policy && <span>測試 Retry：<strong>{testResult.test_retry_policy}</strong></span>}
                    {testResult.status === "error" && testResult.route === "next" && <span className="skip-result">Retry 用盡 → Skip</span>}</div>
                  <strong>Output</strong><pre>{testResult.output || "（沒有文字輸出）"}</pre>
                  {testResult.data != null && Object.keys(testResult.data as object).length > 0 && <details><summary>結構化資料</summary><pre>{JSON.stringify(testResult.data, null, 2)}</pre></details>}
                  {!!testResult.changed_files?.length && <details><summary>變更檔案 · {testResult.changed_files.length}</summary><pre>{testResult.changed_files.join("\n")}</pre></details>}
                </div>}
              </div>}
              </div>
              <footer>
                <div className="footer-actions">
                  <button onClick={() => void duplicateStage()} disabled={busy} title="複製目前設定，但不複製結果連線">{tx("duplicate")}</button>
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
