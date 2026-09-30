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
  scope?: string;
  routes?: Record<string, string>;
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
};

type Catalog = {
  stage_types: Record<string, { type: string; options: CatalogOption[] }>;
  node_options?: Record<string, unknown>;
};

type StudioFile = {
  id: string;
  kind: "workflow" | "prompt";
  name: string;
  display_name?: string;
  reference?: string;
};

type StudioNodeData = {
  kind: "start" | "end" | "stage" | "scope";
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
};

type InspectorTab = "settings" | "parameters" | "routing" | "test";
type ParameterSection = "content" | "execution" | "result" | "advanced";

const PARAMETER_SECTIONS: { id: ParameterSection; label: string; fields: string[] }[] = [
  { id: "content", label: "內容", fields: ["prompt", "instructions", "detail", "command", "cwd"] },
  { id: "execution", label: "執行", fields: ["run_state", "mode", "actor", "allow_project_read", "timeout", "readonly_safety", "track_changes", "tolerate_restored_changes", "clean_work"] },
  { id: "result", label: "結果", fields: ["parser", "produces", "result_kind", "runs", "required_passes", "min_tasks", "structured_retries", "structured_fresh_retries"] },
  { id: "advanced", label: "進階", fields: ["session_key", "fresh_session_each_run", "fresh_session_on_start", "ai_validator_yolo"] },
];

const START = "__start__";
const END = "__end__";

async function api<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, {
    ...init,
    headers: { "Content-Type": "application/json", ...(init?.headers || {}) },
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok || data?.error) throw new Error(data?.error || response.statusText);
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
  return (
    <div className={`wf-stage ${selected ? "selected" : ""} type-${s.type}`}>
      <Handle className="stage-input" type="target" position={Position.Top} />
      <div className="wf-stage-head">
        <span className="stage-type">{STAGE_META[s.type]?.title || String(s.type || "Stage")}</span>
        {s.scope === "task" && <b>↻ Task</b>}
      </div>
      <strong title={title}>{title}</strong>
      {title !== s.name && <small title={s.name}>{s.name}</small>}
      <div className="wf-handles">
        <span>PASS</span><span>FAIL</span><span>ERROR</span>
      </div>
      <Handle className="pass" type="source" position={Position.Bottom} id="pass" style={{ left: "24%" }} />
      <Handle className="fail" type="source" position={Position.Bottom} id="fail" style={{ left: "50%" }} />
      <Handle className="error" type="source" position={Position.Bottom} id="error" style={{ left: "76%" }} />
    </div>
  );
}

function ScopeNode({ data }: NodeProps<Node<StudioNodeData>>) {
  return <div className="wf-scope"><span className="wf-scope-handle" title="拖曳移動 Per Task 區域"><strong>{data.label}</strong><span aria-hidden="true">⠿</span></span></div>;
}

const nodeTypes = {
  terminal: TerminalNode,
  stage: StageNode,
  scope: ScopeNode,
};

function stageByName(visual: Visual, name: string) {
  return visual.stages.find((s) => s.name === name);
}

const STAGE_META: Record<string, { title: string; description: string }> = {
  plan: { title: "Plan", description: "產生 Task[] 規劃" },
  task: { title: "Execute", description: "執行目前 Task" },
  review: { title: "Review", description: "檢查完成度並回 PASS / FAIL" },
  ai_validator: { title: "AI Validator", description: "最終 AI 驗證 / 多次投票" },
  command: { title: "Command", description: "執行外部命令或驗證器" },
  base: { title: "AI Stage", description: "通用 AI Stage" },
};

const PALETTE_SECTIONS = [
  { title: "建立與執行", types: ["plan", "task", "base"], icon: "✦" },
  { title: "檢查與驗證", types: ["review", "ai_validator"], icon: "✓" },
  { title: "工具", types: ["command"], icon: "›" },
];

function defaultOption(catalog: Catalog | null, stageType: string, name: string): unknown {
  return catalog?.stage_types?.[stageType]?.options?.find((item) => item.name === name)?.default;
}

function effectivePrompt(catalog: Catalog | null, stage: Stage): string {
  const explicit = String(stage.prompt || "").trim();
  if (explicit) return explicit;
  return String(defaultOption(catalog, stage.type, "prompt") || "").trim();
}

function nextStageKey(visual: Visual, type: string): string {
  const base = type === "task" ? "execute" : type === "ai_validator" ? "validate_ai" : type;
  const used = new Set(visual.stages.map((s) => s.name));
  if (!used.has(base)) return base;
  let i = 2;
  while (used.has(`${base}_${i}`)) i += 1;
  return `${base}_${i}`;
}

type CanvasPosition = { x: number; y: number };
type CanvasLayout = Record<string, CanvasPosition>;

function layoutKey(id: string): string { return `workflow-studio-layout:${id}`; }

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
  const x = 280;
  const gap = 150;

  nodes.push({
    id: START,
    type: "terminal",
    position: { x: x + 60, y: 20 },
    data: { kind: "start", label: "START" },
    deletable: false,
  });

  const taskIndexes = visual.flow
    .map((name, i) => stageByName(visual, name)?.scope === "task" ? i : -1)
    .filter((i) => i >= 0);
  if (taskIndexes.length) {
    const first = Math.min(...taskIndexes);
    const last = Math.max(...taskIndexes);
    nodes.push({
      id: "__task_scope__",
      type: "scope",
      position: { x: x - 90, y: 120 + first * gap - 22 },
      data: { kind: "scope", label: "↻ PER TASK" },
      style: { width: 480, height: (last - first + 1) * gap + 36 },
      dragHandle: ".wf-scope-handle",
      selectable: true,
      draggable: true,
      deletable: false,
    });
  }

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
      position: { x: disconnected ? x + 320 : x, y: 150 + index * gap },
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
    position: { x: x + 60, y: 150 + Math.max(visual.flow.length, 1) * gap },
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
    const passTarget = routes.pass || (next ? "next" : "done");
    const resolvedPass = passTarget === "next" ? (next || END) : passTarget === "done" || passTarget === "stop" ? END : passTarget;
    edges.push({
      id: `${name}:pass:${resolvedPass}`,
      source: name,
      sourceHandle: "pass",
      target: resolvedPass,
      label: routes.pass ? "PASS" : undefined,
      className: routes.pass ? "result pass" : "normal pass",
      deletable: Boolean(routes.pass),
      markerEnd: { type: MarkerType.ArrowClosed },
      data: { status: "pass", explicit: Boolean(routes.pass), terminal: passTarget },
    });
    for (const status of ["fail", "error"] as const) {
      const target = routes[status];
      if (!target) continue;
      const resolved = target === "done" || target === "stop" ? END : target === "next" ? (next || END) : target;
      edges.push({
        id: `${name}:${status}:${resolved}`,
        source: name,
        sourceHandle: status,
        target: resolved,
        label: status.toUpperCase(),
        className: `result ${status}`,
        markerEnd: { type: MarkerType.ArrowClosed },
        data: { status, explicit: true, terminal: target },
      });
    }
  });

  return { nodes: nodes.map((node) => ({ ...node, position: layout[node.id] || node.position })), edges };
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
      </label>
    );
  }
  if (type === "bool" || type === "boolean") {
    return (
      <label className="check">
        <input type="checkbox" checked={Boolean(value)} onChange={(e) => onChange(e.target.checked)} />
        <span>{option.name}</span>
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
      {option.default !== undefined && <small>default: {JSON.stringify(option.default)}</small>}
    </label>
  );
}

function App() {
  const canvasRef = useRef<HTMLDivElement | null>(null);
  const titleInputRef = useRef<HTMLInputElement | null>(null);
  const layoutRef = useRef<CanvasLayout>({});
  const graphFor = useCallback((v: Visual, c: Catalog | null) => {
    const graph = graphFromVisual(v, c, layoutRef.current);
    layoutRef.current = Object.fromEntries(graph.nodes.map((node) => [node.id, node.position]));
    return graph;
  }, []);
  const { screenToFlowPosition } = useReactFlow();
  const [visual, setVisual] = useState<Visual | null>(null);
  const [catalog, setCatalog] = useState<Catalog | null>(null);
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
  const [createCommand, setCreateCommand] = useState("");
  const [inspectorTab, setInspectorTab] = useState<InspectorTab>("settings");
  const [parameterSection, setParameterSection] = useState<ParameterSection>("content");
  const [testInput, setTestInput] = useState("");
  const [testResult, setTestResult] = useState<StageTestResult | null>(null);
  const [testError, setTestError] = useState("");
  const [testing, setTesting] = useState(false);
  const displayEdges = useMemo<Edge[]>(() => edges.map((edge) => {
    const related = Boolean(selected && (edge.source === selected || edge.target === selected));
    const status = String(edge.data?.status || "pass").toUpperCase();
    const source = edge.source === START ? "START" : edge.source;
    const target = edge.target === END ? "END" : edge.target;
    const color = status === "FAIL" ? "#d97706" : status === "ERROR" ? "#dc2626"
      : edge.data?.explicit ? "#2563eb" : "#64748b";
    return {
      ...edge,
      type: "smoothstep",
      className: `${edge.className || ""}${selected ? related ? " focused" : " muted" : ""}`,
      label: related ? `${status} · ${source} → ${target}` : edge.label,
      labelBgPadding: [6, 4] as [number, number],
      labelBgBorderRadius: 6,
      labelBgStyle: { fill: "#fff", fillOpacity: 0.96 },
      labelStyle: { fill: "#334155", fontWeight: 700 },
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
      const [v, c, files] = await Promise.all([
        api<Visual>(endpoint("/api/studio/visual")),
        api<Catalog>("/api/workflow/catalog"),
        api<{ prompts?: StudioFile[] }>(filesUrl),
      ]);
      setVisual(v);
      setCatalog(c);
      setPrompts(files.prompts || []);
      layoutRef.current = readLayout(v.id);
      const g = graphFor(v, c);
      setNodes(g.nodes);
      setEdges(g.edges);
      setDirtyGraph(false);
      setMessage("");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : String(error));
    }
  }, [graphFor]);

  useEffect(() => { void load(); }, [load]);

  useEffect(() => {
    if (!dirtyGraph) return;
    const warn = (event: BeforeUnloadEvent) => { event.preventDefault(); event.returnValue = ""; };
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [dirtyGraph]);

  useEffect(() => {
    if (!visual || !selected) { setDraft(null); return; }
    const s = stageByName(visual, selected);
    setDraft(s ? structuredClone(s) : null);
  }, [selected, visual]);

  useEffect(() => {
    setInspectorTab("settings");
    setParameterSection("content");
    setTestResult(null);
    setTestError("");
    setTestInput("");
  }, [selected]);

  const options = useMemo(() => {
    if (!draft || !catalog) return [];
    return catalog.stage_types[draft.type]?.options || [];
  }, [draft, catalog]);
  const parameterOptions = options.filter((o) => !["name", "type", "status", "label", "scope", "routes"].includes(o.name));
  const parameterGroups = PARAMETER_SECTIONS.map((section) => ({
    ...section,
    options: parameterOptions.filter((option) => section.id === "advanced"
      ? !PARAMETER_SECTIONS.slice(0, -1).some((group) => group.fields.includes(option.name))
      : section.fields.includes(option.name)),
  })).filter((section) => section.options.length);
  const visibleParameters = parameterOptions.length > 8
    ? (parameterGroups.find((section) => section.id === parameterSection) || parameterGroups[0])?.options || []
    : parameterOptions;
  function editDraft(next: Stage) {
    setDraft(next);
    setVisual((current) => current && ({ ...current, stages: current.stages.map((stage) => stage.name === next.name ? next : stage) }));
    setNodes((current) => current.map((node) => node.id === next.name ? { ...node, data: { ...node.data, label: String(next.label || next.name), stage: next } } : node));
    setDirtyGraph(true);
    setTestResult(null);
  }

  async function testStage() {
    if (!visual || !draft || testing || dirtyGraph || !query().project) return;
    setTesting(true);
    setTestResult(null);
    setTestError("");
    try {
      const result = await api<StageTestResult>("/api/studio/stage/test", {
        method: "POST",
        body: JSON.stringify({ id: visual.id, project: query().project, stage: draft.name, input: testInput }),
      });
      setTestResult(result);
    } catch (error) {
      setTestError(error instanceof Error ? error.message : String(error));
    } finally {
      setTesting(false);
    }
  }

  const persistGraph = useCallback(async (nextVisual: Visual): Promise<Visual> => {
    const routes: Record<string, Record<string, string>> = {};
    nextVisual.stages.forEach((s) => {
      if (s.routes && Object.keys(s.routes).length) routes[s.name] = s.routes;
    });
    const result = await api<{ visual: Visual }>("/api/studio/graph/save", {
      method: "POST",
      body: JSON.stringify({
        id: nextVisual.id,
        project: query().project,
        hash: nextVisual.hash,
        graph: { flow: nextVisual.flow, routes, stages: nextVisual.stages },
      }),
    });
    setVisual(result.visual);
    const g = graphFor(result.visual, catalog);
    setNodes(g.nodes);
    setEdges(g.edges);
    setDirtyGraph(false);
    return result.visual;
  }, [catalog, graphFor]);

  const saveGraph = useCallback(async (nextVisual = visual) => {
    if (!nextVisual) return;
    setBusy(true);
    try {
      await persistGraph(nextVisual);
      setMessage("Workflow saved");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : String(error));
    } finally {
      setBusy(false);
    }
  }, [visual, persistGraph]);

  const connect = useCallback((connection: Connection) => {
    if (!visual || !connection.source || !connection.target) return;
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
    if (connection.source === END || connection.target === START || status === "") return;
    let nextFlow = visual.flow;
    if (status === "pass" && connection.target !== END && !visual.flow.includes(connection.target)) {
      const sourceIndex = visual.flow.indexOf(connection.source);
      const insertAt = sourceIndex >= 0 ? sourceIndex + 1 : visual.flow.length;
      nextFlow = [...visual.flow];
      nextFlow.splice(insertAt, 0, connection.target);
    }
    const stages = visual.stages.map((stage) => {
      if (stage.name !== connection.source) return stage;
      const routes = { ...(stage.routes || {}) };
      const index = visual.flow.indexOf(stage.name);
      const nextName = visual.flow[index + 1];
      let target = connection.target!;
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
    let stages = visual.stages;
    for (const edge of removed) {
      const status = String(edge.data?.status || "");
      if (!status || !edge.data?.explicit) continue;
      stages = stages.map((s) => {
        if (s.name !== edge.source) return s;
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

  async function createStage(stageType: string, position?: { x: number; y: number }, prompt = "", command = "") {
    if (!visual || !catalog?.stage_types?.[stageType]) return;
    const name = nextStageKey(visual, stageType);
    const stage: Stage = { name, type: stageType };
    if (prompt) stage.prompt = prompt;
    if (command) stage.command = command;
    if (stageType === "ai_validator") stage.validator = "ai";
    const next = { ...visual, stages: [...visual.stages, stage] };
    setVisual(next);
    if (position) {
      layoutRef.current = { ...layoutRef.current, [name]: position };
      writeLayout(visual.id, layoutRef.current);
    }
    const g = graphFor(next, catalog);
    setNodes(g.nodes);
    setEdges(g.edges);
    setSelected(name);
    setPendingCreate(null);
    setCreatePrompt("");
    setCreateCommand("");
    setDirtyGraph(true);
    setMessage(`Stage ${name} 已加入草稿。儲存 Workflow 後才會寫入 YAML。`);
  }

  async function addStage(stageType = "task", position?: { x: number; y: number }) {
    if (stageType === "base" || stageType === "command") {
      setPendingCreate({ type: stageType, position });
      setCreatePrompt(stageType === "base" ? String(defaultOption(catalog, stageType, "prompt") || "") : "");
      setCreateCommand("");
      return;
    }
    await createStage(stageType, position);
  }

  async function confirmPendingCreate() {
    if (!pendingCreate) return;
    if (pendingCreate.type === "base" && !createPrompt.trim()) {
      setMessage("Generic AI Stage requires a Prompt.");
      return;
    }
    if (pendingCreate.type === "command" && !createCommand.trim()) {
      setMessage("Command Stage requires a command.");
      return;
    }
    await createStage(pendingCreate.type, pendingCreate.position, createPrompt.trim(), createCommand.trim());
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

  async function deleteStage() {
    if (!visual || !draft) return;
    if (visual.stages.some((stage) => stage.name !== draft.name && Object.values(stage.routes || {}).includes(draft.name))) {
      setMessage(`請先移除指向 ${draft.name} 的結果連線。`);
      return;
    }
    if (!window.confirm(`從草稿移除 Stage "${draft.name}"？儲存 Workflow 後才會更新 YAML。`)) return;
    const next = { ...visual, flow: visual.flow.filter((name) => name !== draft.name), stages: visual.stages.filter((stage) => stage.name !== draft.name) };
    setVisual(next);
    const g = graphFor(next, catalog);
    setNodes(g.nodes);
    setEdges(g.edges);
    setSelected("");
    setDirtyGraph(true);
    setMessage(`Stage ${draft.name} 已從草稿移除。`);
  }

  function resetLayout() {
    if (!visual) return;
    layoutRef.current = {};
    try { localStorage.removeItem(layoutKey(visual.id)); } catch { /* Ignore unavailable browser storage. */ }
    setNodes(graphFor(visual, catalog).nodes);
    setMessage("已重設畫布位置；Workflow 執行順序沒有變動。");
  }

  function focusStageTitle(name: string) {
    setSelected(name);
    setInspectorTab("settings");
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
          <button className="ghost" onClick={() => history.back()}>← Back</button>
          <strong>{visual.name}</strong>
          <span>Workflow Studio</span>
        </div>
        <div>
          {message && <span className="message">{message}</span>}
          {dirtyGraph && <span className="unsaved-badge">未儲存草稿</span>}
          <button onClick={resetLayout} disabled={busy} title="只重設畫布位置，不變更 YAML">重設排列</button>
          <button onClick={() => { if (!dirtyGraph || window.confirm("捨棄未儲存的 Workflow 草稿？")) void load(); }} disabled={busy}>Reload</button>
          <button className="primary" onClick={() => void saveGraph()} disabled={busy || !dirtyGraph}>
            {busy ? "驗證與儲存中…" : "儲存 Workflow"}
          </button>
        </div>
      </header>

      <section className="studio-body">
        <aside className="palette">
          <div className="palette-head"><span className="palette-eyebrow">Stage Palette</span><strong>新增積木</strong><small>拖曳積木到畫布才會新增</small></div>
          {PALETTE_SECTIONS.map((section) => {
            const types = section.types.filter((type) => catalog?.stage_types?.[type]);
            if (!types.length) return null;
            return <div className="palette-section" key={section.title}>
              <div className="palette-section-head"><span>{section.title}</span><small>{types.length}</small></div>
              <div className="palette-list">{types.map((type) => {
                const meta = STAGE_META[type];
                return <div key={type} className="palette-item" draggable={!busy} title="拖曳到畫布新增積木"
                  onDragStart={(event) => dragStage(event, type)}>
                  <span className={`palette-icon type-${type}`} aria-hidden="true">{section.icon}</span>
                  <span className="palette-copy"><strong>{meta.title}</strong><small>{meta.description}</small></span>
                  <span className="palette-add" aria-hidden="true">⠿</span>
                </div>;
              })}</div>
            </div>;
          })}
          {Object.keys(catalog?.stage_types || {}).filter((type) => !PALETTE_SECTIONS.some((section) => section.types.includes(type))).length > 0 &&
            <div className="palette-section"><div className="palette-section-head"><span>擴充積木</span></div><div className="palette-list">
              {Object.keys(catalog?.stage_types || {}).filter((type) => !PALETTE_SECTIONS.some((section) => section.types.includes(type))).map((type) =>
                <div key={type} className="palette-item" draggable={!busy} title="拖曳到畫布新增積木"
                  onDragStart={(event) => dragStage(event, type)}>
                  <span className="palette-icon" aria-hidden="true">◇</span><span className="palette-copy"><strong>{type}</strong><small>自訂 Stage</small></span><span className="palette-add" aria-hidden="true">⠿</span>
                </div>)}</div></div>}
          <div className="palette-note"><small>畫布上的修改會先保留為草稿，按「儲存 Workflow」後才更新 YAML。</small></div>
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
            onNodeDragStop={rememberPosition}
            onNodeClick={(_e, n) => n.data.kind === "stage" && setSelected(n.id)}
            onNodeDoubleClick={(_e, n) => n.data.kind === "stage" && focusStageTitle(n.id)}
            onPaneClick={() => setSelected("")}
            connectionLineStyle={{ strokeWidth: 2.5 }}
            defaultEdgeOptions={{ interactionWidth: 24, style: { strokeWidth: 2 } }}
            fitView
            minZoom={0.25}
            maxZoom={1.8}
            deleteKeyCode={["Backspace", "Delete"]}
            proOptions={{ hideAttribution: true }}
          >
            <Background gap={22} size={1} />
            <MiniMap pannable zoomable />
            <Controls />
          </ReactFlow>
        </div>

        {pendingCreate && (
          <div className="create-stage-backdrop" role="dialog" aria-modal="true" aria-label="Create Stage">
            <div className="create-stage-card">
              <div>
                <small>NEW STAGE</small>
                <h3>{STAGE_META[pendingCreate.type]?.title || pendingCreate.type}</h3>
              </div>
              {pendingCreate.type === "base" && (
                <label>
                  <span>Prompt</span>
                  <select value={createPrompt} onChange={(e) => setCreatePrompt(e.target.value)}>
                    <option value="">Choose Prompt…</option>
                    {prompts.map((p) => {
                      const ref = p.reference || p.display_name || p.name;
                      return <option key={p.id} value={ref}>{ref}</option>;
                    })}
                  </select>
                </label>
              )}
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
        <aside className="inspector">
          {!draft ? (
            <div className="empty">
              <h2>Stage settings</h2>
              <p>選取一個 Stage 積木編輯。PASS / FAIL / ERROR 直接由積木 Handle 拉線。</p>
            </div>
          ) : (
            <>
              <div className="inspector-head">
                <div><small>STAGE</small><h2>{draft.name}</h2></div>
                <span>{draft.type}</span>
              </div>
              <div className="inspector-tabs" role="tablist" aria-label="Stage sections">
                {(["settings", "parameters", "routing", "test"] as const).map((tab) => (
                  <button key={tab} type="button" role="tab" aria-selected={inspectorTab === tab}
                    className={inspectorTab === tab ? "active" : ""} onClick={() => setInspectorTab(tab)}>
                    {{ settings: "基本", parameters: `參數${parameterOptions.length ? ` · ${parameterOptions.length}` : ""}`, routing: "連線", test: "測試" }[tab]}
                  </button>
                ))}
              </div>
              {inspectorTab === "settings" && <div className="fields" role="tabpanel">
                <label>
                  <span>類型</span>
                  <select value={draft.type} onChange={(e) => editDraft({ ...draft, type: e.target.value })}>
                    {Object.keys(catalog?.stage_types || {}).map((t) => <option key={t}>{t}</option>)}
                  </select>
                </label>
                <label><span>積木標題（雙擊積木可重新命名）</span><input ref={titleInputRef} value={String(draft.label || "")} placeholder={draft.name} onChange={(e) => editDraft({ ...draft, label: e.target.value })} /></label>
                <label><span>執行狀態文字</span><input value={String(draft.status || "")} onChange={(e) => editDraft({ ...draft, status: e.target.value })} /></label>
                <label>
                  <span>執行範圍</span>
                  <select value={String(draft.scope || "")} onChange={(e) => editDraft({ ...draft, scope: e.target.value })}>
                    <option value="">Workflow</option><option value="task">Per task</option>
                  </select>
                </label>
              </div>}
              {inspectorTab === "parameters" && <div className="fields" role="tabpanel">
                {parameterOptions.length === 0 && <p className="section-empty">此積木沒有其他參數。</p>}
                {parameterOptions.length > 8 && <div className="parameter-sections" role="tablist" aria-label="Parameter sections">
                  {parameterGroups.map((section) => <button key={section.id} type="button" role="tab"
                    aria-selected={visibleParameters === section.options}
                    className={visibleParameters === section.options ? "active" : ""}
                    onClick={() => setParameterSection(section.id)}>{section.label}<small>{section.options.length}</small></button>)}
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
                    </label>
                  ) : (
                    <Field
                      key={option.name}
                      option={option}
                      value={draft[option.name]}
                      onChange={(value) => editDraft({ ...draft, [option.name]: value })}
                    />
                  ))}
              </div>}
              {inspectorTab === "routing" && <div className="edge-help" role="tabpanel">
                <strong>結果連線</strong>
                <p>從積木下方的大接點拉到目標積木。連到 END 時，PASS 為完成，FAIL / ERROR 為停止。</p>
                {(["pass", "fail", "error"] as const).map((status) => (
                  <div className="route-row" key={status}><span className={`route-dot ${status}`} />
                    <strong>{status.toUpperCase()}</strong><span>{draft.routes?.[status] || (status === "pass" ? "next（預設）" : "未設定")}</span>
                  </div>
                ))}
              </div>}
              {inspectorTab === "test" && <div className="stage-test" role="tabpanel">
                <p>只執行目前積木一次，顯示結果及下一個目標；不接續執行其他積木。測試會在目前專案執行，可能修改專案檔案。</p>
                {!query().project && <p className="test-notice">請從專案內開啟此 Workflow，才能提供測試工作目錄。</p>}
                {dirtyGraph && <p className="test-notice">請先儲存 Workflow 草稿，再執行測試。</p>}
                <label><span>測試 Input</span><textarea value={testInput} onChange={(e) => setTestInput(e.target.value)} rows={5} placeholder="輸入這個積木要接收的內容" /></label>
                <button type="button" className="primary" onClick={() => void testStage()}
                  disabled={testing || busy || dirtyGraph || !query().project}>{testing ? "測試中…" : "執行單一積木"}</button>
                {testError && <p className="test-error" role="alert">{testError}</p>}
                {testResult && <div className="test-result" aria-live="polite">
                  <div className="test-result-summary"><span className={`result-status ${testResult.status}`}>{testResult.status.toUpperCase()}</span><span>下一個：<strong>{testResult.next}</strong></span></div>
                  <strong>Output</strong><pre>{testResult.output || "（沒有文字輸出）"}</pre>
                  {testResult.data != null && Object.keys(testResult.data as object).length > 0 && <details><summary>結構化資料</summary><pre>{JSON.stringify(testResult.data, null, 2)}</pre></details>}
                  {!!testResult.changed_files?.length && <details><summary>變更檔案 · {testResult.changed_files.length}</summary><pre>{testResult.changed_files.join("\n")}</pre></details>}
                </div>}
              </div>}
              <footer>
                <button className="danger" onClick={() => void deleteStage()} disabled={busy}>移除積木</button>
                <span className="draft-hint">修改先存為草稿</span>
              </footer>
            </>
          )}
        </aside>
      </section>
    </main>
  );
}

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <ReactFlowProvider><App /></ReactFlowProvider>
  </StrictMode>
);
