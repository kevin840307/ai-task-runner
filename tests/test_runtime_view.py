from runtime_view import build_runtime_view


def test_runtime_view_status_and_actions_matrix():
    cases = [
        ({"project_exists": True}, "idle", {"run": True, "stop": False, "resume": False}),
        ({"project_exists": True, "running": True}, "running", {"run": False, "stop": True, "resume": False}),
        ({"project_exists": True, "running": True, "last_error": "HTTP 503"}, "recovering", {"run": False, "stop": True, "resume": False}),
        ({"project_exists": True, "resumable": True}, "stopped", {"run": False, "stop": False, "resume": True}),
        ({"project_exists": True, "resumable": True, "stale": True}, "needs_attention", {"run": False, "stop": False, "resume": True}),
        ({"project_exists": True, "completed": True, "can_rerun": True}, "completed", {"run": True, "stop": False, "resume": False, "rerun": True}),
        ({"project_exists": False}, "missing", {"run": False, "stop": False, "resume": False}),
    ]
    for evidence, status, expected in cases:
        view = build_runtime_view(evidence)
        assert view["status"] == status
        for action, allowed in expected.items():
            assert view["actions"][action] is allowed


def test_runtime_view_projects_structured_recovery_and_attention():
    view = build_runtime_view({
        "project_exists": True,
        "running": True,
        "last_error": "HTTP 503 Service Unavailable",
        "recovery": {
            "retry_mode": "recover",
            "retry": 3,
            "wait_seconds": 8,
            "error": "HTTP 503 Service Unavailable",
        },
    })
    assert view["status"] == "recovering"
    assert view["needs_attention"] is False
    assert view["recovery"] == {
        "active": True,
        "mode": "recover",
        "retry": 3,
        "wait_seconds": 8.0,
        "error": "HTTP 503 Service Unavailable",
    }
    assert view["reason"] == "HTTP 503 Service Unavailable"

    stale = build_runtime_view({
        "project_exists": True,
        "resumable": True,
        "stale": True,
    })
    assert stale["status"] == "needs_attention"
    assert stale["recommended_actions"] == ["resume", "reset"]
    assert "no longer active" in stale["reason"]


def test_runtime_view_run_snapshot_uses_frozen_request_values():
    view = build_runtime_view({
        "project_exists": True,
        "running": True,
        "run_id": "run-1",
        "started_at": 10,
        "updated_at": 20,
        "workflow": "editor-current.yaml",
        "backend": "editor-backend",
        "model": "editor-model",
        "effective_backend": "stage-backend",
        "effective_model": "stage-model",
        "request": {
            "workflow": "frozen.yaml",
            "backend": "qwen",
            "model": "frozen-model",
            "validator": "validation.py",
            "readonly_safety": "observe",
        },
    })
    snapshot = view["run"]
    assert snapshot["workflow"] == "frozen.yaml"
    assert snapshot["backend"] == "qwen"
    assert snapshot["model"] == "frozen-model"
    assert snapshot["readonly_safety"] == "observe"
    assert snapshot["effective_backend"] == "stage-backend"
    assert snapshot["effective_model"] == "stage-model"


def test_runtime_view_semantic_fail_recommends_workflow():
    view = build_runtime_view({
        "project_exists": True,
        "resumable": True,
        "stale": True,
        "last_transition": {"stage": "review", "status": "fail", "target": "stop"},
    })
    assert view["status"] == "needs_attention"
    assert view["reason"] == "review returned FAIL and the Workflow did not continue."
    assert view["recommended_actions"] == ["open_workflow"]
