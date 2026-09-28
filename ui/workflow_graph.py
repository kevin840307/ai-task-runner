from __future__ import annotations

from typing import Any


def build_workflow_graph(data: dict[str, Any]) -> dict[str, Any]:
    """Render the same one-Stage-one-node graph used by runtime."""
    stages = data.get("stages") if isinstance(data, dict) else {}
    flow = data.get("flow") if isinstance(data, dict) else []
    stages = stages if isinstance(stages, dict) else {}
    flow = flow if isinstance(flow, list) else []

    names = [item for item in flow if isinstance(item, str) and item in stages]
    nodes = []
    edges: list[dict[str, str]] = []

    for name in names:
        cfg = stages.get(name) if isinstance(stages.get(name), dict) else {}
        nodes.append({
            "id": name,
            "label": str(cfg.get("label") or name),
            "type": str(cfg.get("type") or "base"),
            "prompt": str(cfg.get("prompt") or ""),
            "virtual": False,
            "routing": {"routes": cfg.get("routes")} if cfg.get("routes") else {},
        })

    for index in range(len(names) - 1):
        edges.append({
            "from": names[index],
            "to": names[index + 1],
            "kind": "normal",
            "label": "PASS → next",
        })

    terminals: set[str] = set()
    for name in names:
        cfg = stages.get(name) if isinstance(stages.get(name), dict) else {}
        routes = cfg.get("routes")
        if not isinstance(routes, dict):
            continue
        for status, raw_target in routes.items():
            target = str(raw_target)
            if target == "next":
                continue
            if target in {"done", "stop"}:
                terminal = f"__{target}__:{name}"
                if terminal not in terminals:
                    terminals.add(terminal)
                    nodes.append({
                        "id": terminal,
                        "label": target.upper(),
                        "type": "terminal",
                        "prompt": "",
                        "virtual": True,
                        "routing": {},
                    })
                target = terminal
            edges.append({
                "from": name,
                "to": target,
                "kind": "result",
                "label": f"{str(status).upper()} → {raw_target}",
            })

    return {"nodes": nodes, "edges": edges}
