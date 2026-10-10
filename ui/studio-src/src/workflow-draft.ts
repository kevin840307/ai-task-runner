export type Stage = Record<string, unknown> & {
  name: string;
  type: string;
  status?: string;
  label?: string;
  routes?: Record<string, string>;
  error_policy?: { retries: number };
  max_failures?: number;
  targets?: string[];
  backend?: string;
  model?: string;
  session_policy?: string;
};

export type Visual = {
  id: string;
  name: string;
  hash: string;
  stages: Stage[];
  flow: string[];
};

export type ResultEdgeRef = {
  source: string;
  target: string;
  status: string;
};

export type DraftConnection = {
  source?: string | null;
  target?: string | null;
  sourceHandle?: string | null;
  targetHandle?: string | null;
};

export const START = "__start__";
export const END = "__end__";

export function stageByName(visual: Visual, name: string): Stage | undefined {
  return visual.stages.find((stage) => stage.name === name);
}

export function nextStageKey(visual: Visual, type: string): string {
  const base = type === "base" ? "ai_stage" : type === "ai_validator" ? "validate_ai" : type;
  const used = new Set(visual.stages.map((stage) => stage.name));
  if (!used.has(base)) return base;
  let index = 2;
  while (used.has(`${base}_${index}`)) index += 1;
  return `${base}_${index}`;
}

export function addStageToVisual(
  visual: Visual,
  stage: Stage,
  afterStage = "",
): Visual {
  const flow = [...visual.flow];
  const index = afterStage ? flow.indexOf(afterStage) : -1;
  if (index >= 0) flow.splice(index + 1, 0, stage.name);
  return { ...visual, flow, stages: [...visual.stages, stage] };
}

export function cloneStageWithoutConnections(source: Stage, name: string): Stage {
  const copy = structuredClone({ ...source, name });
  delete copy.routes;
  if (copy.type === "handoff") copy.targets = [];
  return copy;
}

export function stageReferenceSources(visual: Visual, stageName: string): string[] {
  return visual.stages
    .filter((stage) => stage.name !== stageName && (
      Object.values(stage.routes || {}).includes(stageName)
      || (stage.targets || []).includes(stageName)
    ))
    .map((stage) => stage.name);
}

export function removeStageFromVisual(visual: Visual, stageName: string): Visual {
  return {
    ...visual,
    flow: visual.flow.filter((name) => name !== stageName),
    stages: visual.stages.filter((stage) => stage.name !== stageName),
  };
}

export function disconnectResultEdges(
  visual: Visual,
  removed: ResultEdgeRef[],
): Visual {
  let stages = visual.stages;
  for (const edge of removed) {
    const status = String(edge.status || "").toLowerCase();
    if (!status) continue;
    stages = stages.map((stage) => {
      if (stage.name !== edge.source) return stage;
      if (status === "handoff") {
        return {
          ...stage,
          targets: (stage.targets || []).filter((target) => target !== edge.target),
        };
      }
      const routes = { ...(stage.routes || {}) };
      if (status === "pass") routes.pass = "stop";
      else delete routes[status];
      return { ...stage, routes };
    });
  }
  return { ...visual, stages };
}

export function applyConnectionToVisual(
  visual: Visual,
  connection: DraftConnection,
): Visual {
  if (!connection.source || !connection.target) return visual;
  const status = String(connection.sourceHandle || "pass").toLowerCase();
  if (connection.source === START) {
    if (connection.target === END) return visual;
    return {
      ...visual,
      flow: [
        connection.target,
        ...visual.flow.filter((name) => name !== connection.target),
      ],
    };
  }
  if (
    connection.source === END
    || connection.target === START
    || !["pass", "fail", "handoff"].includes(status)
    || (status === "handoff" && connection.target === END)
  ) return visual;

  const nextFlow = [...visual.flow];
  if (!nextFlow.includes(connection.source)) nextFlow.push(connection.source);
  if (connection.target !== END && !nextFlow.includes(connection.target)) {
    if (status === "pass" || status === "handoff") {
      const sourceIndex = nextFlow.indexOf(connection.source);
      const insertAt = sourceIndex >= 0 ? sourceIndex + 1 : nextFlow.length;
      nextFlow.splice(insertAt, 0, connection.target);
    } else {
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
      return {
        ...stage,
        targets: Array.from(new Set([...(stage.targets || []), target])),
      };
    }
    if (target === END) target = status === "pass" ? "done" : "stop";
    if (status === "pass" && target === nextName) delete routes.pass;
    else routes[status] = target;
    return { ...stage, routes };
  });
  return { ...visual, stages, flow: nextFlow };
}
