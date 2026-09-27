from __future__ import annotations
from typing import Any


_ROUTING_KEYS = ("recover", "retry", "on_exhausted", "restart_at", "max_attempts", "repeat", "fresh_after_same_failures")


def _target_name(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, dict):
        return str(value.get("stage") or "").strip()
    return ""


def _effective_stage(name: str, stages: dict[str, Any], invocation: dict[str, Any] | None = None) -> dict[str, Any]:
    """Mirror loader semantics enough for visualization: Stage defaults + flow overrides."""
    base = stages.get(name)
    cfg = dict(base) if isinstance(base, dict) else {}
    if invocation:
        cfg.update({k: v for k, v in invocation.items() if k != "stage"})
    return cfg


def build_workflow_graph(data: dict[str, Any]) -> dict:
    """Build an explanatory graph without changing runtime semantics.

    Normal ordering comes from ``flow``. Recovery/retry/exhaustion/restart routing
    comes from the *effective Stage invocation* (Stage definition plus any explicit
    flow-item override), matching the loader instead of mixing unrelated sources.
    Recovery is rendered as a real loop: failed stage -> recovery sequence -> stage.
    """
    stages = data.get("stages") if isinstance(data, dict) else {}
    stages = stages if isinstance(stages, dict) else {}
    raw_flow = data.get("flow") if isinstance(data, dict) else []
    raw_flow = raw_flow if isinstance(raw_flow, list) else []

    nodes: dict[str, dict[str, Any]] = {}
    edges: list[dict[str, Any]] = []
    flow_nodes: list[tuple[str, dict[str, Any]]] = []

    def add_node(name: str, cfg: dict[str, Any] | None = None, *, virtual: bool = False, label: str = "") -> None:
        if not name:
            return
        cfg = cfg or _effective_stage(name, stages)
        nodes.setdefault(name, {
            "id": name,
            "label": label or name,
            "type": "terminal" if virtual else str(cfg.get("type") or "base"),
            "prompt": "" if virtual else str(cfg.get("prompt") or ""),
            "virtual": virtual,
            "routing": {key: cfg.get(key) for key in _ROUTING_KEYS if cfg.get(key) is not None},
        })

    # Flow is the sole source for the normal top-level sequence.
    for item in raw_flow:
        if isinstance(item, str):
            name, invocation = item.strip(), {}
        elif isinstance(item, dict):
            name = str(item.get("stage") or "").strip()
            invocation = item
        else:
            continue
        if not name:
            continue
        cfg = _effective_stage(name, stages, invocation)
        add_node(name, cfg)
        flow_nodes.append((name, cfg))

    # Mirror Loader's implicit Plan -> Task -> Review lifecycle for visualization.
    # These nodes are explanatory/virtual only; YAML stays compact and runtime
    # remains owned by runner.workflow.loader._expand_plan_task_flow().
    display_flow: list[str] = []
    for index, (name, cfg) in enumerate(flow_nodes):
        display_flow.append(name)
        next_is_explicit_task_scope = (
            index + 1 < len(flow_nodes)
            and str(flow_nodes[index + 1][1].get("scope") or "") == "task"
        )
        if str(cfg.get("type") or "") != "plan" or next_is_explicit_task_scope:
            continue
        task_id = f"__plan_task__:{index}:{name}"
        review_id = f"__plan_review__:{index}:{name}"
        nodes[task_id] = {
            "id": task_id,
            "label": "Execute · built-in",
            "type": "task",
            "prompt": "stages/execution.md",
            "virtual": True,
            "runtime_stage": "__plan_task__",
            "routing": {},
        }
        nodes[review_id] = {
            "id": review_id,
            "label": "Review · built-in",
            "type": "review",
            "prompt": "stages/review.md",
            "virtual": True,
            "runtime_stage": "__plan_review__",
            "routing": {"restart_at": task_id},
        }
        display_flow.extend([task_id, review_id])
        edges.append({
            "from": review_id,
            "to": task_id,
            "kind": "restart",
            "label": "FAIL → Execute",
        })

    for index in range(len(display_flow) - 1):
        edges.append({"from": display_flow[index], "to": display_flow[index + 1], "kind": "normal", "label": "next"})

    normal_successor = {flow_nodes[i][0]: flow_nodes[i + 1][0] for i in range(len(flow_nodes) - 1)}

    # Include recovery-only definitions and effective routing for every known Stage.
    effective: dict[str, dict[str, Any]] = {
        str(name): _effective_stage(str(name), stages)
        for name, value in stages.items() if isinstance(value, dict)
    }
    effective.update({name: cfg for name, cfg in flow_nodes})

    for name, cfg in list(effective.items()):
        add_node(name, cfg)

        recover = cfg.get("recover") or []
        if isinstance(recover, (str, dict)):
            recover = [recover]
        recover_names = [_target_name(item) for item in recover]
        recover_names = [target for target in recover_names if target]
        if recover_names:
            previous = name
            for pos, target in enumerate(recover_names):
                target_cfg = _effective_stage(target, stages, next((x for x in recover if _target_name(x) == target and isinstance(x, dict)), None))
                add_node(target, target_cfg)
                edges.append({
                    "from": previous,
                    "to": target,
                    "kind": "recover" if pos == 0 else "recovery_step",
                    "label": "FAIL → recover" if pos == 0 else "recovery next",
                })
                previous = target
            # Runtime continues the failed Stage after a successful recovery sequence.
            edges.append({"from": previous, "to": name, "kind": "recovery_return", "label": "retry after recovery"})

        retry = cfg.get("retry")
        if isinstance(retry, int) and not isinstance(retry, bool) and retry != 0:
            label = "retry ∞" if retry == -1 else f"retry ×{retry}"
            edges.append({"from": name, "to": name, "kind": "retry", "label": label})

        restart = cfg.get("restart_at")
        if isinstance(restart, str) and restart.strip():
            target = restart.strip()
            add_node(target)
            edges.append({"from": name, "to": target, "kind": "restart", "label": "FAIL → restart_at"})

        exhausted = cfg.get("on_exhausted")
        if exhausted == "continue":
            target = normal_successor.get(name)
            if target:
                edges.append({"from": name, "to": target, "kind": "exhausted", "label": "attempts exhausted → continue"})
        elif exhausted == "fail":
            terminal = f"__failed__:{name}"
            add_node(terminal, virtual=True, label="FAILED")
            edges.append({"from": name, "to": terminal, "kind": "exhausted", "label": "attempts exhausted → fail"})

    # Deduplicate exact edges while preserving stable order.
    seen: set[tuple[str, str, str, str]] = set()
    unique_edges = []
    for edge in edges:
        key = (edge["from"], edge["to"], edge["kind"], edge.get("label", ""))
        if key in seen:
            continue
        seen.add(key)
        unique_edges.append(edge)

    return {"nodes": list(nodes.values()), "edges": unique_edges}
