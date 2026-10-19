from __future__ import annotations

import json
import threading
import urllib.request
from pathlib import Path

import pytest

from ui.server import UIServer
from ui.task_draft_service import TaskDraftService
from ui.task_service import TaskService


def _json_request(url: str, *, method: str = "GET", body: dict | None = None) -> dict:
    data = None if body is None else json.dumps(body).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={"Content-Type": "application/json"} if data is not None else {},
    )
    with urllib.request.urlopen(request, timeout=5) as response:
        return json.loads(response.read().decode("utf-8"))


def test_task_draft_is_transient_structured_and_mode_checked(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    project = repo / "project"
    project.mkdir(parents=True)
    calls: list[dict] = []

    def fake_runner(**kwargs):
        calls.append(dict(kwargs))
        return {
            "draft": {
                "title": "Draft title",
                "items": [
                    {"title": "First", "prompt": "Do first"},
                    {"title": "Second", "prompt": "Do second"},
                ],
            }
        }

    service = TaskDraftService(repo, runner=fake_runner)
    value = service.generate(
        project,
        spec="split this work",
        draft_mode="list",
        backend="opencode",
        model="openai/gpt-5.2",
        reasoning="deep",
        workflow="workflow.yaml",
        request_id="draft-request-1",
    )
    assert value["mode"] == "list"
    assert value["draft"]["project"] == str(project.resolve())
    assert [row["workspace"] for row in value["draft"]["items"]] == ["auto", "auto"]
    assert [row["workflow"] for row in value["draft"]["items"]] == ["workflow.yaml", "workflow.yaml"]
    assert calls[0]["draft_mode"] == "list"
    assert not (project / ".ai-task-runner" / "ui" / "tasks.json").exists()

    duplicate = service.generate(
        project,
        spec="different text",
        draft_mode="list",
        backend="opencode",
        request_id="draft-request-1",
    )
    assert duplicate["duplicate"] is True
    assert duplicate["draft_id"] == value["draft_id"]

    single = TaskDraftService(
        repo,
        runner=lambda **kwargs: {
            "draft": {
                "title": "Bad single",
                "items": [
                    {"title": "A", "prompt": "A"},
                    {"title": "B", "prompt": "B"},
                ],
            }
        },
    )
    with pytest.raises(ValueError, match="exactly one"):
        single.generate(
            project,
            spec="one",
            draft_mode="single",
            backend="qwen",
            request_id="bad-single",
        )


def test_task_service_creates_only_after_explicit_create_and_is_idempotent(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    service = TaskService()
    draft = {
        "title": "Task List",
        "project": str(project),
        "items": [
            {
                "title": "A",
                "prompt": "Do A",
                "workflow": "workflow.yaml",
                "project": str(project),
                "workspace": "auto",
            },
            {
                "title": "B",
                "prompt": "Do B",
                "workflow": "workflow.yaml",
                "project": str(project),
                "workspace": "main",
            },
        ],
    }

    created = service.create(project, draft, request_id="create-1")
    assert created["status"] == "new"
    assert created["kind"] == "task_list"
    assert created["run_count"] == 0
    assert created["merge_failure_count"] == 0
    assert "runtime" not in created

    restarted = TaskService()
    listed = restarted.list(project)["tasks"]
    assert [row["task_id"] for row in listed] == [created["task_id"]]
    duplicate = restarted.create(project, draft, request_id="create-1")
    assert duplicate["duplicate"] is True
    assert duplicate["task_id"] == created["task_id"]


def test_task_service_updates_new_task_idempotently_and_preserves_item_identity(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    service = TaskService()
    base = {
        "title": "List",
        "items": [
            {"title": "A", "prompt": "A", "workflow": "workflow.yaml", "project": str(project), "workspace": "auto"},
            {"title": "B", "prompt": "B", "workflow": "workflow.yaml", "project": str(project), "workspace": "main"},
        ],
    }
    created = service.create(project, base, request_id="create-update")
    first_id, second_id = [item["item_id"] for item in created["items"]]
    edited = {
        "title": "Reordered",
        "items": [
            {**created["items"][1], "prompt": "B edited"},
            {**created["items"][0], "prompt": "A edited"},
        ],
    }

    updated = service.update(
        project,
        created["task_id"],
        edited,
        request_id="update-1",
        expected_updated_at=created["updated_at"],
    )
    assert updated["duplicate"] is False
    assert updated["title"] == "Reordered"
    assert [item["item_id"] for item in updated["items"]] == [second_id, first_id]
    assert [item["prompt"] for item in updated["items"]] == ["B edited", "A edited"]

    duplicate = TaskService().update(
        project,
        created["task_id"],
        edited,
        request_id="update-1",
        expected_updated_at=created["updated_at"],
    )
    assert duplicate["duplicate"] is True
    assert duplicate["updated_at"] == updated["updated_at"]


def test_task_service_update_rejects_stale_or_non_new_task(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    service = TaskService()
    draft = {
        "title": "One",
        "items": [
            {"title": "A", "prompt": "A", "workflow": "workflow.yaml", "project": str(project), "workspace": "auto"},
        ],
    }
    created = service.create(project, draft, request_id="create-stale")

    with pytest.raises(ValueError, match="changed since"):
        service.update(
            project,
            created["task_id"],
            draft,
            request_id="stale-update",
            expected_updated_at=created["updated_at"] - 1,
        )

    state_path = service._state_path(project)
    raw = json.loads(state_path.read_text(encoding="utf-8"))
    raw["tasks"][0]["status"] = "ongoing"
    state_path.write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(ValueError, match="must be New"):
        service.update(
            project,
            created["task_id"],
            draft,
            request_id="ongoing-update",
            expected_updated_at=created["updated_at"],
        )


def test_task_service_rejects_invalid_project_items_and_workspace(tmp_path: Path) -> None:
    project = tmp_path / "project"
    other = tmp_path / "other"
    project.mkdir()
    other.mkdir()
    service = TaskService()
    item = {
        "title": "A",
        "prompt": "Do A",
        "workflow": "workflow.yaml",
        "project": str(project),
        "workspace": "auto",
    }
    with pytest.raises(ValueError, match="selected Project"):
        service.create(
            project,
            {"title": "Bad", "items": [{**item, "project": str(other)}]},
            request_id="mismatch",
        )
    with pytest.raises(ValueError, match="at least one"):
        service.create(project, {"title": "Empty", "items": []}, request_id="empty")
    with pytest.raises(ValueError, match="workspace policy"):
        service.create(
            project,
            {"title": "Bad", "items": [{**item, "workspace": "magic"}]},
            request_id="workspace",
        )


def test_task_draft_and_create_http_contract_are_separate(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    project = repo / "project"
    (repo / "ui" / "data").mkdir(parents=True)
    (repo / "ui" / "static").mkdir(parents=True)
    project.mkdir()

    server = UIServer(repo, "127.0.0.1", 0)
    registered = server.state.add_project(str(project))
    server.state.project_preferences.update(project, {
        "agent": "qwen",
        "workflow": "workflow.yaml",
    })
    server.state.task_drafts = TaskDraftService(
        repo,
        runner=lambda **kwargs: {
            "draft": {
                "title": "Generated",
                "items": [{"title": "Only", "prompt": "Do it"}],
            }
        },
    )
    session_id = server.state.chat_service.sessions(project)["active_session_id"]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.port}"
    try:
        generated = _json_request(
            f"{base}/api/chat/task-draft",
            method="POST",
            body={
                "project": str(project),
                "session_id": session_id,
                "mode": "single",
                "spec": "make one task",
                "request_id": "http-draft-1",
            },
        )
        assert generated["draft"]["items"][0]["workflow"] == "workflow.yaml"
        assert server.state.tasks.list(project)["tasks"] == []

        validated = _json_request(
            f"{base}/api/tasks/validate-draft",
            method="POST",
            body={
                "project": str(project),
                "draft": generated["draft"],
            },
        )
        assert validated["draft"]["items"][0]["prompt"] == "Do it"
        assert server.state.tasks.list(project)["tasks"] == []

        created = _json_request(
            f"{base}/api/tasks/create",
            method="POST",
            body={
                "project": str(project),
                "draft": generated["draft"],
                "request_id": "http-create-1",
            },
        )
        assert created["status"] == "new"
        assert created["project_id"] == registered["project_id"]
        assert server.state.tasks.list(project)["tasks"][0]["task_id"] == created["task_id"]

        updated_draft = json.loads(json.dumps(generated["draft"]))
        updated_draft["title"] = "Updated over HTTP"
        updated_draft["items"][0]["item_id"] = created["items"][0]["item_id"]
        updated_draft["items"][0]["prompt"] = "Edited through API"
        updated = _json_request(
            f"{base}/api/tasks/update",
            method="POST",
            body={
                "project": str(project),
                "task_id": created["task_id"],
                "draft": updated_draft,
                "request_id": "http-update-1",
                "expected_updated_at": created["updated_at"],
            },
        )
        assert updated["title"] == "Updated over HTTP"
        assert updated["items"][0]["prompt"] == "Edited through API"
        assert updated["items"][0]["item_id"] == created["items"][0]["item_id"]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
