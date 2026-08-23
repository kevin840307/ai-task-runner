from types import SimpleNamespace

from runner.workflow.flow import FlowDefinition, default_flow


class S:
    def __init__(self, name): self.name = name


def test_linear_flow_builds_default_advance_routes():
    a, b, c = S("a"), S("b"), S("c")
    flow = FlowDefinition.linear(a, b, c)
    ctx = SimpleNamespace()
    assert flow.entry(ctx) == "a"
    assert flow.next("a", "advance", ctx) == "b"
    assert flow.next("b", "advance", ctx) == "c"
    assert flow.next("c", "advance", ctx) is None
    assert flow.next("b", "retry", ctx) == "b"
    assert flow.next("b", "replan", ctx) == "a"


def test_graph_routes_can_override_linear_edges_and_resolve_dynamically():
    p, e, r, v = (S(name) for name in ("planning", "execute", "review", "validate"))
    flow = default_flow(p, e, r, v)
    state = SimpleNamespace(tasks=[SimpleNamespace(status="pending")], current=0, stage="executing", completed=False)
    ctx = SimpleNamespace(state=state)

    assert flow.entry(ctx) == "execute"
    assert flow.next("execute", "advance", ctx) == "review"
    assert flow.next("review", "retry", ctx) == "execute"

    state.current = 1
    state.tasks[0].status = "completed"
    assert flow.next("review", "advance", ctx) == "validate"
    assert flow.next("validate", "replan", ctx) == "planning"


def test_flow_rejects_unknown_nodes():
    flow = FlowDefinition.linear(S("a"), S("b"))
    try:
        flow.route("a", "advance", "missing")
    except ValueError as error:
        assert "unknown flow target" in str(error)
    else:
        raise AssertionError("unknown graph target must be rejected")
