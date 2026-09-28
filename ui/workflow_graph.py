from __future__ import annotations

from typing import Any


def build_workflow_graph(data: dict[str, Any]) -> dict[str, Any]:
    """Render the same minimal Stage + result-edge model used by runtime."""
    stages = data.get("stages") if isinstance(data, dict) else {}
    flow = data.get("flow") if isinstance(data, dict) else []
    stages = stages if isinstance(stages, dict) else {}
    flow = flow if isinstance(flow, list) else []

    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, str]] = []
    names: list[str] = []
    configs: dict[str, dict[str, Any]] = {}

    for item in flow:
        if isinstance(item, str):
            ref, overrides = item, {}
        elif isinstance(item, dict):
            ref = str(item.get("stage") or "")
            overrides = {k: v for k, v in item.items() if k != "stage"}
        else:
            continue
        base = stages.get(ref)
        if not ref or not isinstance(base, dict):
            continue
        cfg = {**base, **overrides}
        name = str(cfg.get("name") or ref)
        cfg["name"] = name
        names.append(name)
        configs[name] = cfg
        nodes.append({
            "id": name,
            "label": str(cfg.get("label") or name),
            "type": str(cfg.get("type") or "base"),
            "prompt": str(cfg.get("prompt") or ""),
            "virtual": False,
            "routing": {"routes": cfg.get("routes")} if cfg.get("routes") else {},
        })

    for index in range(len(names) - 1):
        source = names[index]
        routes = configs[source].get("routes")
        explicit_pass = (
            isinstance(routes, dict)
            and str(routes.get("pass") or "").strip()
        )
        if not explicit_pass:
            edges.append({
                "from": source,
                "to": names[index + 1],
                "kind": "normal",
                "label": "PASS → next",
            })

    terminals: set[str] = set()
    for name, cfg in configs.items():
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
