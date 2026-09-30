(() => {
  "use strict";

  function esc(v) {
    return String(v ?? "").replace(/[&<>"']/g, (c) => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
  }

  function buildLayout(nodes, edges) {
    const ids = nodes.map((n) => n.id);
    const idSet = new Set(ids);
    const normal = edges.filter((e) => e.kind === "normal" && idSet.has(e.from) && idSet.has(e.to));
    const incoming = new Map(ids.map((id) => [id, 0]));
    const outgoing = new Map(ids.map((id) => [id, []]));
    normal.forEach((e) => {
      incoming.set(e.to, (incoming.get(e.to) || 0) + 1);
      outgoing.get(e.from).push(e.to);
    });

    const rank = new Map();
    const queue = ids.filter((id) => (incoming.get(id) || 0) === 0);
    if (!queue.length && ids.length) queue.push(ids[0]);
    queue.forEach((id) => rank.set(id, 0));
    const pendingIncoming = new Map(incoming);
    while (queue.length) {
      const id = queue.shift();
      const r = rank.get(id) || 0;
      for (const to of outgoing.get(id) || []) {
        rank.set(to, Math.max(rank.get(to) || 0, r + 1));
        pendingIncoming.set(to, (pendingIncoming.get(to) || 0) - 1);
        if (pendingIncoming.get(to) === 0) queue.push(to);
      }
    }

    // Recover-only / cyclic nodes: place near the first stage that references them.
    ids.forEach((id) => {
      if (rank.has(id)) return;
      const parent = edges.find((e) => e.to === id && rank.has(e.from));
      rank.set(id, parent ? (rank.get(parent.from) + 1) : Math.max(0, rank.size));
    });

    const layers = new Map();
    ids.forEach((id) => {
      const r = rank.get(id) || 0;
      if (!layers.has(r)) layers.set(r, []);
      layers.get(r).push(id);
    });

    const nodeW = 176, nodeH = 62, gapX = 58, gapY = 54, padX = 58, padY = 54;
    const maxPerLayer = Math.max(1, ...Array.from(layers.values(), (v) => v.length));
    const width = Math.max(760, padX * 2 + maxPerLayer * nodeW + (maxPerLayer - 1) * gapX);
    const maxRank = Math.max(0, ...rank.values());
    const height = Math.max(300, padY * 2 + (maxRank + 1) * nodeH + maxRank * gapY);
    const coords = new Map();

    for (let r = 0; r <= maxRank; r++) {
      const layer = layers.get(r) || [];
      const layerWidth = layer.length * nodeW + Math.max(0, layer.length - 1) * gapX;
      const startX = (width - layerWidth) / 2;
      layer.forEach((id, i) => {
        coords.set(id, {
          x: startX + i * (nodeW + gapX) + nodeW / 2,
          y: padY + r * (nodeH + gapY) + nodeH / 2,
        });
      });
    }
    return { coords, width, height, nodeW, nodeH };
  }

  function edgePath(a, b, nodeW, nodeH, kind) {
    if (a.x === b.x && a.y === b.y) {
      const x = a.x + nodeW / 2 - 7, y = a.y;
      return `M ${x} ${y - 13} C ${x + 48} ${y - 48}, ${x + 48} ${y + 48}, ${x} ${y + 13}`;
    }
    const sx = a.x, sy = a.y + nodeH / 2;
    const tx = b.x, ty = b.y - nodeH / 2;
    if (kind === "normal" && ty >= sy) {
      const midY = sy + Math.max(22, (ty - sy) / 2);
      return `M ${sx} ${sy} C ${sx} ${midY}, ${tx} ${midY}, ${tx} ${ty}`;
    }
    const dir = tx >= sx ? 1 : -1;
    const side = Math.max(52, Math.min(126, Math.abs(tx - sx) / 2 + 38));
    const routeX = sx + dir * side;
    return `M ${sx + dir * nodeW * 0.42} ${a.y} C ${routeX} ${a.y}, ${routeX} ${b.y}, ${tx - dir * nodeW * 0.42} ${b.y}`;
  }

  function renderGraph(root, graph, mode = "auto", options = {}) {
    const allNodes = Array.isArray(graph?.nodes) ? graph.nodes : [];
    const allEdges = Array.isArray(graph?.edges) ? graph.edges : [];
    const dense = allNodes.length > 20 || allEdges.length > 28;
    const effectiveMode = mode === "auto" ? (dense ? "core" : "all") : mode;
    const coreKinds = new Set(["normal", "result"]);
    const nodes = effectiveMode === "core" ? allNodes.filter((n) => !n.virtual) : allNodes;
    const nodeIds = new Set(nodes.map((n) => n.id));
    const edges = effectiveMode === "core"
      ? allEdges.filter((e) => coreKinds.has(e.kind || "normal") && nodeIds.has(e.from) && nodeIds.has(e.to))
      : allEdges;
    if (!nodes.length) {
      root.innerHTML = '<div class="flow-map-empty">No stages found.</div>';
      return;
    }

    const byId = new Map(nodes.map((n) => [n.id, n]));
    const { coords, width, height, nodeW, nodeH } = buildLayout(nodes, edges);
    const defs = `<defs>\n      <marker id="flowArrowNormal" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto"><path d="M0,0 L8,4 L0,8 Z" /></marker>\n      <marker id="flowArrowResult" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto"><path d="M0,0 L8,4 L0,8 Z" /></marker>\n    </defs>`;

    const taskScoped = nodes.filter((n) => !n.virtual && n.scope === "task" && coords.has(n.id));
    let scopeGroup = "";
    if (taskScoped.length) {
      const scopedCoords = taskScoped.map((n) => coords.get(n.id));
      const minX = Math.min(...scopedCoords.map((p) => p.x - nodeW / 2)) - 28;
      const maxX = Math.max(...scopedCoords.map((p) => p.x + nodeW / 2)) + 28;
      const minY = Math.min(...scopedCoords.map((p) => p.y - nodeH / 2)) - 42;
      const maxY = Math.max(...scopedCoords.map((p) => p.y + nodeH / 2)) + 28;
      scopeGroup = `<g class="flow-map-scope-group">
        <rect x="${minX}" y="${minY}" width="${maxX - minX}" height="${maxY - minY}" rx="18"/>
        <text x="${minX + 16}" y="${minY + 24}">↻ PER TASK</text>
      </g>`;
    }

    const lines = edges.map((e) => {
      const a = coords.get(e.from), b = coords.get(e.to);
      if (!a || !b) return "";
      const cls = e.kind === "result" ? "result" : "normal";
      const path = edgePath(a, b, nodeW, nodeH, cls);
      const marker = `flowArrow${cls[0].toUpperCase() + cls.slice(1)}`;
      return `<g class="flow-map-edge ${cls}">
        <path d="${path}" marker-end="url(#${marker})"/>
        <title>${esc(e.label || cls)}: ${esc(e.from)} → ${esc(e.to)}</title>
      </g>`;
    }).join("");

    const boxes = nodes.map((n) => {
      const c = coords.get(n.id);
      return `<g class="flow-map-node" tabindex="0" role="button" aria-label="Stage ${esc(n.id)}" data-node="${esc(n.id)}">
        <rect class="${n.virtual ? "virtual" : ""}" x="${c.x - nodeW / 2}" y="${c.y - nodeH / 2}" width="${nodeW}" height="${nodeH}" rx="12"/>
        <circle cx="${c.x - nodeW / 2 + 18}" cy="${c.y}" r="5" class="node-dot"/>
        <text x="${c.x - nodeW / 2 + 32}" y="${c.y - 5}" class="name">${esc(n.label || n.id)}</text>
        <text x="${c.x - nodeW / 2 + 32}" y="${c.y + 14}" class="type">${esc((n.type || "base") + (n.scope === "task" ? " · per task" : ""))}</text>
      </g>`;
    }).join("");

    root.innerHTML = `
      <div class="flow-map-toolbar">
        <div class="flow-map-legend" aria-label="Flow map legend">
          <span><i class="normal"></i>PASS → next</span>
          <span><i class="result"></i>Result route</span>
        </div>
        <div class="flow-map-toolbar-actions">
          <span class="flow-map-count">${effectiveMode === "core" ? "Core view · " : ""}${nodes.length} stages · ${edges.length}${effectiveMode === "core" ? ` / ${allEdges.length}` : ""} routes</span>
          ${dense ? `<button class="flow-map-density-toggle" type="button">${effectiveMode === "core" ? "Show all routes" : "Simplify routes"}</button>` : ""}
        </div>
      </div>
      <div class="flow-map-scroll" tabindex="0">
        <svg viewBox="0 0 ${width} ${height}" role="img" aria-label="Workflow stage flow map">${defs}${scopeGroup}${lines}${boxes}</svg>
      </div>
      <div id="flowMapDetails" class="flow-map-details">
        <div class="flow-map-detail-empty">Select a Stage to inspect routing.</div>
      </div>`;

    function selectNode(el) {
      root.querySelectorAll('.flow-map-node').forEach((x) => x.classList.toggle('selected', x === el));
      const n = byId.get(el.dataset.node);
      const incoming = edges.filter((e) => e.to === n.id);
      const outgoing = edges.filter((e) => e.from === n.id);
      root.querySelector('#flowMapDetails').innerHTML = `
        <div class="flow-map-detail-head"><strong>${esc(n.id)}</strong><span>${esc(n.type || "base")}</span></div>
        <div class="flow-map-detail-grid">
          <span><b>Prompt</b>${esc(n.prompt || "default")}</span>
          <span><b>Routing</b>${esc(Object.entries(n.routing || {}).map(([k,v])=>`${k}=${JSON.stringify(v)}`).join(' · ') || 'default')}</span>
          <span><b>Outgoing</b>${esc(outgoing.map((e)=>`${e.label || e.kind} → ${(byId.get(e.to)?.label || e.to)}`).join(', ') || 'none')}</span>
          <span><b>Incoming</b>${esc(incoming.map((e)=>`${e.label || e.kind} ← ${(byId.get(e.from)?.label || e.from)}`).join(', ') || 'none')}</span>
        </div>`;
      if (typeof options.onSelect === "function") options.onSelect(n.id, n);
    }

    const densityToggle = root.querySelector('.flow-map-density-toggle');
    if (densityToggle) densityToggle.addEventListener('click', () => {
      renderGraph(root, graph, effectiveMode === "core" ? "all" : "core", options);
    });

    root.querySelectorAll('.flow-map-node').forEach((el) => {
      el.addEventListener('click', () => selectNode(el));
      el.addEventListener('dblclick', () => {
        const n = byId.get(el.dataset.node);
        if (typeof options.onEdit === "function" && n) options.onEdit(n.id, n);
      });
      el.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); selectNode(el); }
      });
    });
  }

  function render(root, graph, options = {}) { renderGraph(root, graph, "auto", options); }

  window.WorkflowFlowMap = Object.freeze({ render });
})();
