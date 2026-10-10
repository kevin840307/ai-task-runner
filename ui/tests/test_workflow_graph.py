from ui.workflow_graph import build_workflow_graph


def _edges(graph, kind):
    return {
        (edge["from"], edge["to"], edge["label"])
        for edge in graph["edges"]
        if edge["kind"] == kind
    }


def test_graph_renders_stage_nodes_normal_flow_and_result_edges():
    graph = build_workflow_graph({
        "stages": {
            "execute": {"type": "base", "profile": "execute"},
            "review": {
                "type": "base",
                "profile": "review",
                "routes": {"fail": "execute"},
            },
            "validate": {"type": "ai_validator", "routes": {"fail": "execute"}},
        },
        "flow": ["execute", "review", "validate"],
    })

    assert [node["id"] for node in graph["nodes"] if not node["virtual"]] == [
        "execute", "review", "validate"
    ]
    assert ("execute", "review", "PASS → next") in _edges(graph, "normal")
    assert ("review", "validate", "PASS → next") in _edges(graph, "normal")
    assert ("review", "execute", "FAIL → execute") in _edges(graph, "result")
    assert ("validate", "execute", "FAIL → execute") in _edges(graph, "result")


def test_graph_uses_stage_definition_as_node_identity():
    graph = build_workflow_graph({
        "stages": {
            "first": {"type": "base", "profile": "execute", "label": "First"},
            "second": {
                "type": "base",
                "profile": "review",
                "label": "Second",
                "routes": {"fail": "first"},
            },
        },
        "flow": ["first", "second"],
    })

    assert [node["id"] for node in graph["nodes"]] == ["first", "second"]
    assert [node["label"] for node in graph["nodes"]] == ["First", "Second"]
    assert ("first", "second", "PASS → next") in _edges(graph, "normal")
    assert ("second", "first", "FAIL → first") in _edges(graph, "result")


def test_graph_renders_done_and_stop_as_terminal_nodes():
    graph = build_workflow_graph({
        "stages": {
            "gate": {
                "type": "base",
                "profile": "review",
                "routes": {"pass": "done", "fail": "stop"},
            },
        },
        "flow": ["gate"],
    })

    assert any(node["id"] == "__done__:gate" and node["virtual"] for node in graph["nodes"])
    assert any(node["id"] == "__stop__:gate" and node["virtual"] for node in graph["nodes"])
    assert ("gate", "__done__:gate", "PASS → done") in _edges(graph, "result")
    assert ("gate", "__stop__:gate", "FAIL → stop") in _edges(graph, "result")


def test_graph_renders_only_declared_static_stages_for_dynamic_plan():
    graph = build_workflow_graph({
        "stages": {
            "planning": {"type": "plan"},
            "validate": {"type": "ai_validator"},
        },
        "flow": ["planning", "validate"],
    })

    ids = {node["id"] for node in graph["nodes"]}
    assert ids == {"planning", "validate"}
    assert all(edge["kind"] in {"normal", "result"} for edge in graph["edges"])

    by_id = {node["id"]: node for node in graph["nodes"]}
    assert by_id["planning"]["type"] == "plan"
    assert "scope" not in by_id["planning"]
