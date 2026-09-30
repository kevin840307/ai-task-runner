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
  return (
    <div className={`wf-stage ${selected ? "selected" : ""} type-${s.type}`}>
      <Handle type="target" position={Position.Top} />
      <div className="wf-stage-head">
        <span>{String(s.type || "base")}</span>
        {s.scope === "task" && <b>↻ PER TASK</b>}
      </div>
      <strong>{String(s.label || s.name)}</strong>
      <small>{String(s.status || s.name)}</small>
      {String(s.prompt || "") && <code className="wf-prompt">{String(s.prompt)}</code>}
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
  return <div className="wf-scope"><strong>{data.label}</strong></div>;
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

function graphFromVisual(visual: Visual): { nodes: Node<StudioNodeData>[]; edges: Edge[] } {
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
      style: { width: 480, height: (last - first + 1) * gap + 36, zIndex: -10 },
      selectable: false,
      draggable: false,
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
      label: "START",
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
      label: routes.pass ? `PASS → ${passTarget}` : "PASS → next",
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
        label: `${status.toUpperCase()} → ${target}`,
        className: `result ${status}`,
        markerEnd: { type: MarkerType.ArrowClosed },
        data: { status, explicit: true, terminal: target },
      });
    }
  });

  return { nodes, edges };
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
          {!option.required && <option value="">Stage default</option>}
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
      const g = graphFromVisual(v);
      setNodes(g.nodes);
      setEdges(g.edges);
      setDirtyGraph(false);
      setMessage("");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : String(error));
    }
  }, []);

  useEffect(() => { void load(); }, [load]);

  useEffect(() => {
    if (!visual || !selected) { setDraft(null); return; }
    const s = stageByName(visual, selected);
    setDraft(s ? structuredClone(s) : null);
  }, [selected, visual]);

  const options = useMemo(() => {
    if (!draft || !catalog) return [];
    return catalog.stage_types[draft.type]?.options || [];
  }, [draft, catalog]);

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
        graph: { flow: nextVisual.flow, routes },
      }),
    });
    setVisual(result.visual);
    const g = graphFromVisual(result.visual);
    setNodes(g.nodes);
    setEdges(g.edges);
    setDirtyGraph(false);
    return result.visual;
  }, []);

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
      const g = graphFromVisual(next);
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
    const g = graphFromVisual(next);
    setNodes(g.nodes);
    setEdges(g.edges);
    setDirtyGraph(true);
  }, [visual]);

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
    const g = graphFromVisual(next);
    setNodes(g.nodes);
    setEdges(g.edges);
    setDirtyGraph(true);
  }, [visual]);

  const reorderByPosition = useCallback((_event: unknown, moved: Node<StudioNodeData>) => {
    if (!visual || moved.data.kind !== "stage") return;
    if (!visual.flow.includes(moved.id)) return;
    const ordered = nodes
      .filter((n) => n.data.kind === "stage" && visual.flow.includes(n.id))
      .map((n) => n.id === moved.id ? moved : n)
      .sort((a, b) => a.position.y - b.position.y)
      .map((n) => n.id);
    if (ordered.join("|") === visual.flow.join("|")) return;
    const next = { ...visual, flow: ordered };
    setVisual(next);
    const g = graphFromVisual(next);
    setNodes(g.nodes);
    setEdges(g.edges);
    setDirtyGraph(true);
  }, [nodes, visual]);

  async function saveStage() {
    if (!visual || !draft) return;
    setBusy(true);
    try {
      const base = dirtyGraph ? await persistGraph(visual) : visual;
      const fields = { ...draft };
      delete (fields as Record<string, unknown>).name;
      const result = await api<{ visual: Visual }>("/api/studio/stage/save", {
        method: "POST",
        body: JSON.stringify({
          id: base.id,
          project: query().project,
          stage: draft.name,
          hash: base.hash,
          fields,
        }),
      });
      setVisual(result.visual);
      const g = graphFromVisual(result.visual);
      setNodes(g.nodes);
      setEdges(g.edges);
      setMessage("Stage saved");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : String(error));
    } finally {
      setBusy(false);
    }
  }

  async function addStage(stageType = "task", position?: { x: number; y: number }) {
    if (!visual || !catalog?.stage_types?.[stageType]) return;
    const name = nextStageKey(visual, stageType);
    setBusy(true);
    try {
      const base = dirtyGraph ? await persistGraph(visual) : visual;
      const result = await api<{ visual: Visual }>("/api/studio/stage/add", {
        method: "POST",
        body: JSON.stringify({
          id: base.id,
          project: query().project,
          stage: name,
          type: stageType,
          hash: base.hash,
          add_to_flow: false,
        }),
      });
      setVisual(result.visual);
      const g = graphFromVisual(result.visual);
      if (position) {
        g.nodes = g.nodes.map((node) => node.id === name ? { ...node, position } : node);
      }
      setNodes(g.nodes);
      setEdges(g.edges);
      setSelected(name);
      setMessage(`Stage ${name} added. Connect it to START / PASS to join the flow.`);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : String(error));
    } finally {
      setBusy(false);
    }
  }

  function dragStage(event: React.DragEvent<HTMLButtonElement>, stageType: string) {
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
    if (!window.confirm(`Delete Stage "${draft.name}"? Result edges referencing it must already be removed.`)) return;
    setBusy(true);
    try {
      const base = dirtyGraph ? await persistGraph(visual) : visual;
      const result = await api<{ visual: Visual }>("/api/studio/stage/delete", {
        method: "POST",
        body: JSON.stringify({
          id: base.id,
          project: query().project,
          stage: draft.name,
          hash: base.hash,
        }),
      });
      setVisual(result.visual);
      const g = graphFromVisual(result.visual);
      setNodes(g.nodes);
      setEdges(g.edges);
      setSelected("");
      setMessage(`Stage ${draft.name} deleted`);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : String(error));
    } finally {
      setBusy(false);
    }
  }

  if (!visual) return <main className="loading">{message || "Loading Workflow Studio…"}</main>;

  return (
    <main className="studio-shell">
      <header className="studio-header">
        <div>
          <button className="ghost" onClick={() => history.back()}>← Back</button>
          <strong>{visual.name}</strong>
          <span>Linear Workflow</span>
        </div>
        <div>
          {message && <span className="message">{message}</span>}
          <button onClick={() => void load()} disabled={busy}>Reload</button>
          <button className="primary" onClick={() => void saveGraph()} disabled={busy || !dirtyGraph}>
            {busy ? "Saving…" : "Save graph"}
          </button>
        </div>
      </header>

      <section className="studio-body">
        <aside className="palette">
          <div className="palette-head">
            <strong>Stage Palette</strong>
            <small>拖到畫布，或點一下新增</small>
          </div>
          <div className="palette-list">
            {Object.keys(catalog?.stage_types || {}).map((type) => {
              const meta = STAGE_META[type] || { title: type, description: "Stage" };
              const prompt = String(defaultOption(catalog, type, "prompt") || "");
              return (
                <button
                  key={type}
                  type="button"
                  className="palette-item"
                  draggable
                  disabled={busy}
                  onDragStart={(event) => dragStage(event, type)}
                  onClick={() => void addStage(type)}
                >
                  <strong>{meta.title}</strong>
                  <span>{type}</span>
                  <small>{meta.description}</small>
                  {prompt && <code>{prompt}</code>}
                </button>
              );
            })}
          </div>
          <div className="palette-note">
            <strong>組裝方式</strong>
            <small>START 接第一個 Stage；PASS / FAIL / ERROR 都從積木下方拉線。未接入 flow 的 Stage 會保留在 YAML，但不執行。</small>
          </div>
        </aside>
        <div
          ref={canvasRef}
          className="canvas"
          onDragOver={(event) => { event.preventDefault(); event.dataTransfer.dropEffect = "copy"; }}
          onDrop={(event) => void dropStage(event)}
        >
          <ReactFlow
            nodes={nodes}
            edges={edges}
            nodeTypes={nodeTypes}
            onNodesChange={(changes) => setNodes((current) => applyNodeChanges(changes, current))}
            onEdgesChange={(changes) => setEdges((current) => applyEdgeChanges(changes, current))}
            onConnect={connect}
            onEdgesDelete={deleteEdges}
            onNodeDragStop={reorderByPosition}
            onNodeClick={(_e, n) => n.data.kind === "stage" && setSelected(n.id)}
            onNodeDoubleClick={(_e, n) => n.data.kind === "stage" && setSelected(n.id)}
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
              <div className="fields">
                <label>
                  <span>type</span>
                  <select value={draft.type} onChange={(e) => setDraft({ ...draft, type: e.target.value })}>
                    {Object.keys(catalog?.stage_types || {}).map((t) => <option key={t}>{t}</option>)}
                  </select>
                </label>
                <label><span>status</span><input value={String(draft.status || "")} onChange={(e) => setDraft({ ...draft, status: e.target.value })} /></label>
                <label><span>label</span><input value={String(draft.label || "")} onChange={(e) => setDraft({ ...draft, label: e.target.value })} /></label>
                <label>
                  <span>scope</span>
                  <select value={String(draft.scope || "")} onChange={(e) => setDraft({ ...draft, scope: e.target.value })}>
                    <option value="">Workflow</option><option value="task">Per task</option>
                  </select>
                </label>
                {options
                  .filter((o) => !["name", "type", "status", "label", "scope", "routes"].includes(o.name))
                  .map((option) => option.name === "prompt" ? (
                    <label key={option.name}>
                      <span>prompt</span>
                      <select value={String(draft.prompt || "")} onChange={(e) => setDraft({ ...draft, prompt: e.target.value })}>
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
                      onChange={(value) => setDraft({ ...draft, [option.name]: value })}
                    />
                  ))}
              </div>
              <div className="edge-help">
                <strong>Result edges</strong>
                <p>從節點下方 PASS / FAIL / ERROR Handle 拉到另一個 Stage。拉到 END 時，PASS=done；FAIL/ERROR=stop。</p>
                <code>{JSON.stringify(draft.routes || {}, null, 2)}</code>
              </div>
              <footer>
                <button className="danger" onClick={() => void deleteStage()} disabled={busy}>Delete Stage</button>
                <button className="primary" onClick={() => void saveStage()} disabled={busy}>Save Stage</button>
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
