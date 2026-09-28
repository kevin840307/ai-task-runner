from ui.workflow_graph import build_workflow_graph


def _edges(graph, kind):
    return {(e["from"], e["to"], e["label"]) for e in graph["edges"] if e["kind"] == kind}


def test_stage_routing_becomes_edges_and_recovery_returns():
    graph = build_workflow_graph({
        "stages": {
            "grill": {"type": "review", "recover": ["repair"], "retry": 2, "max_attempts": 3, "on_exhausted": "continue"},
            "repair": {"type": "task"},
            "validate": {"type": "ai_validator", "restart_at": "grill"},
        },
        "flow": ["grill", "validate"],
    })
    assert ("grill", "repair", "FAIL → recover") in _edges(graph, "recover")
    assert ("repair", "grill", "retry after recovery") in _edges(graph, "recovery_return")
    assert ("grill", "grill", "retry ×2") in _edges(graph, "retry")
    assert ("grill", "validate", "attempts exhausted → continue") in _edges(graph, "exhausted")
    assert ("validate", "grill", "FAIL → restart_at") in _edges(graph, "restart")


def test_recovery_sequence_returns_from_last_step():
    graph = build_workflow_graph({
        "stages": {"review": {"recover": ["repair_plan", "repair"]}, "repair_plan": {}, "repair": {}},
        "flow": ["review"],
    })
    assert ("review", "repair_plan", "FAIL → recover") in _edges(graph, "recover")
    assert ("repair_plan", "repair", "recovery next") in _edges(graph, "recovery_step")
    assert ("repair", "review", "retry after recovery") in _edges(graph, "recovery_return")


def test_on_exhausted_fail_has_terminal_edge():
    graph = build_workflow_graph({
        "stages": {"gate": {"recover": ["repair"], "max_attempts": 2, "on_exhausted": "fail"}, "repair": {}},
        "flow": ["gate"],
    })
    assert any(e["kind"] == "exhausted" and e["to"] == "__failed__:gate" for e in graph["edges"])
    assert any(n["id"] == "__failed__:gate" and n["virtual"] for n in graph["nodes"])


def test_flow_map_node_routing_includes_fresh_after_same_failures():
    graph = build_workflow_graph(
        {
            "stages": {
                "gate": {
                    "type": "review",
                    "fresh_after_same_failures": 2,
                    "recover": ["repair"],
                },
                "repair": {"type": "task"},
            },
            "flow": ["gate"],
        }
    )

    gate = next(node for node in graph["nodes"] if node["id"] == "gate")
    assert gate["routing"]["fresh_after_same_failures"] == 2


def test_flow_map_mirrors_implicit_plan_task_review_lifecycle():
    graph = build_workflow_graph(
        {
            "stages": {
                "planning": {"type": "plan"},
                "validate_ai": {"type": "ai_validator", "restart_at": "planning"},
            },
            "flow": ["planning", "validate_ai"],
        }
    )

    task = next(node for node in graph["nodes"] if node.get("runtime_stage") == "__plan_task__")
    review = next(node for node in graph["nodes"] if node.get("runtime_stage") == "__plan_review__")
    assert task["virtual"] is True and task["type"] == "task"
    assert review["virtual"] is True and review["type"] == "review"
    normal = _edges(graph, "normal")
    assert ("planning", task["id"], "next") in normal
    assert (task["id"], review["id"], "next") in normal
    assert (review["id"], "validate_ai", "next") in normal
    assert (review["id"], task["id"], "FAIL → Execute") in _edges(graph, "result")


def test_flow_map_does_not_inject_builtin_task_lifecycle_when_plan_has_explicit_task_scope():
    graph = build_workflow_graph(
        {
            "stages": {
                "planning": {"type": "plan"},
                "custom_task": {"type": "task"},
                "custom_review": {"type": "review"},
                "validate_ai": {"type": "ai_validator"},
            },
            "flow": [
                "planning",
                {"stage": "custom_task", "scope": "task"},
                {"stage": "custom_review", "scope": "task"},
                "validate_ai",
            ],
        }
    )

    assert not any(node.get("runtime_stage") == "__plan_task__" for node in graph["nodes"])
    assert not any(node.get("runtime_stage") == "__plan_review__" for node in graph["nodes"])
