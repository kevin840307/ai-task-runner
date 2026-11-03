from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from ui.server import UIServer


@pytest.fixture()
def http_server(tmp_path: Path):
    repo = tmp_path / "repo"
    project = repo / "project"
    (repo / "ui" / "data").mkdir(parents=True)
    (repo / "ui" / "static").mkdir(parents=True)
    project.mkdir()
    server = UIServer(repo, "127.0.0.1", 0)
    server.state.add_project(str(project))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server, project
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def _json_request(url: str, *, body: dict) -> dict:
    request = urllib.request.Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=3) as response:
            assert response.status == 200
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:  # pragma: no cover - failure diagnostic
        payload = exc.read().decode("utf-8", errors="replace")
        pytest.fail(f"HTTP {exc.code}: {payload}")


def test_real_http_handler_success_dispatch_for_task_chat_and_studio_actions(
    http_server,
) -> None:
    server, project = http_server
    calls: list[tuple] = []

    server.state.task_runs.start = lambda path, task_id, *, request_id: (
        calls.append(("run", path, task_id, request_id))
        or {"action": "run", "task_id": task_id}
    )
    server.state.task_runs.stop = lambda path, task_id: (
        calls.append(("stop", path, task_id))
        or {"action": "stop", "task_id": task_id}
    )
    server.state.task_runs.resume = lambda path, task_id: (
        calls.append(("resume", path, task_id))
        or {"action": "resume", "task_id": task_id}
    )
    server.state.chat_agent.drain = lambda path, service, *, session_id: (
        calls.append(("drain", path, service is server.state.chat_service, session_id))
        or {"session_id": session_id, "status": "idle", "items": []}
    )

    def stage_save(file_id, stage, fields, expected_hash, selected_project, *, validate_only=False):
        calls.append(
            (
                "stage-validate",
                file_id,
                stage,
                fields,
                expected_hash,
                selected_project,
                validate_only,
            )
        )
        return {"valid": True, "stage": stage}

    def visual_save(file_id, flow, expected_hash, selected_project):
        calls.append(
            ("visual-save", file_id, flow, expected_hash, selected_project)
        )
        return {"saved": True, "flow": flow}

    server.state.studio_stage_save = stage_save
    server.state.studio_visual_save = visual_save

    base = f"http://127.0.0.1:{server.port}"
    task_id = "task-" + "1" * 32
    common = {"project": str(project), "task_id": task_id}

    run = _json_request(
        f"{base}/api/tasks/run",
        body={**common, "request_id": "http-run-1"},
    )
    stop = _json_request(f"{base}/api/tasks/stop", body=common)
    resume = _json_request(f"{base}/api/tasks/resume", body=common)
    drain = _json_request(
        f"{base}/api/chat/queue/drain",
        body={"project": str(project), "session_id": "session-1"},
    )
    validated = _json_request(
        f"{base}/api/studio/stage/validate",
        body={
            "project": str(project),
            "id": "workflow-id",
            "stage": "execute",
            "fields": {"prompt": "common/execution.md"},
            "hash": "hash-1",
        },
    )
    visual = _json_request(
        f"{base}/api/studio/visual/save",
        body={
            "project": str(project),
            "id": "workflow-id",
            "flow": ["execute"],
            "hash": "hash-2",
        },
    )

    assert run == {"action": "run", "task_id": task_id}
    assert stop == {"action": "stop", "task_id": task_id}
    assert resume == {"action": "resume", "task_id": task_id}
    assert drain["status"] == "idle"
    assert validated == {"valid": True, "stage": "execute"}
    assert visual == {"saved": True, "flow": ["execute"]}

    assert calls == [
        ("run", project.resolve(), task_id, "http-run-1"),
        ("stop", project.resolve(), task_id),
        ("resume", project.resolve(), task_id),
        ("drain", project.resolve(), True, "session-1"),
        (
            "stage-validate",
            "workflow-id",
            "execute",
            {"prompt": "common/execution.md"},
            "hash-1",
            project.resolve(),
            True,
        ),
        (
            "visual-save",
            "workflow-id",
            ["execute"],
            "hash-2",
            project.resolve(),
        ),
    ]
