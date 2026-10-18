from __future__ import annotations

import json
import threading
import urllib.parse
import urllib.request
from pathlib import Path

import pytest

from ui.project_preferences import ProjectPreferences
from ui.server import UIServer


def test_project_preferences_are_backend_owned_and_durable(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    preferences = ProjectPreferences()

    initial = preferences.get(project)
    assert initial["exists"] is False
    assert initial["mode"] == "auto"
    assert initial["reasoning"] == "medium"

    updated = preferences.update(
        project,
        {
            "agent": "opencode",
            "model": "provider/model",
            "mode": "read",
            "reasoning": "high",
            "workflow": "runner/assets/workflows/ralphy_ai_validate.yaml",
            "validators": {"workflow-a": "validator.py"},
            "ai_validator_prompts": {"workflow-a": "review.md"},
        },
    )
    assert updated["exists"] is True
    assert updated["agent"] == "opencode"
    assert updated["mode"] == "read"

    restarted = ProjectPreferences().get(project)
    assert restarted["agent"] == "opencode"
    assert restarted["model"] == "provider/model"
    assert restarted["reasoning"] == "high"
    assert restarted["validators"] == {"workflow-a": "validator.py"}
    assert restarted["ai_validator_prompts"] == {"workflow-a": "review.md"}


def test_project_preferences_reject_unknown_or_invalid_values(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    preferences = ProjectPreferences()

    with pytest.raises(ValueError, match="Unknown Project preference"):
        preferences.update(project, {"other": "value"})
    with pytest.raises(ValueError, match="Mode must be"):
        preferences.update(project, {"mode": "unsafe"})
    native = preferences.update(project, {"reasoning": "deep"})
    assert native["reasoning"] == "deep"
    model_default = preferences.update(project, {"reasoning": ""})
    assert model_default["reasoning"] == ""
    with pytest.raises(ValueError, match="Reasoning preference is too long"):
        preferences.update(project, {"reasoning": "x" * 121})
    with pytest.raises(ValueError, match="must be an object"):
        preferences.update(project, {"validators": []})


def test_project_preferences_corruption_fails_closed(tmp_path: Path) -> None:
    project = tmp_path / "project"
    path = project / ".ai-task-runner" / "ui" / "project-preferences.json"
    path.parent.mkdir(parents=True)
    path.write_text("{broken", encoding="utf-8")

    with pytest.raises(ValueError, match="Project preferences are invalid"):
        ProjectPreferences().get(project)



def _request_json(url: str, *, method: str = "GET", body: dict | None = None) -> dict:
    payload = None if body is None else json.dumps(body).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=payload,
        method=method,
        headers={"Content-Type": "application/json"} if payload is not None else {},
    )
    with urllib.request.urlopen(request, timeout=5) as response:
        return json.loads(response.read().decode("utf-8"))


def test_project_preferences_http_api_persists_per_project(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    project_a = repo / "a"
    project_b = repo / "b"
    (repo / "ui" / "data").mkdir(parents=True)
    project_a.mkdir()
    project_b.mkdir()

    server = UIServer(repo, "127.0.0.1", 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.port}"
    try:
        initial = _request_json(
            f"{base}/api/project/preferences?project={urllib.parse.quote(str(project_a))}"
        )
        assert initial["exists"] is False
        assert initial["reasoning"] == "medium"

        saved = _request_json(
            f"{base}/api/project/preferences",
            method="POST",
            body={
                "project": str(project_a),
                "agent": "opencode",
                "model": "provider/model-a",
                "mode": "read",
                "reasoning": "high",
                "workflow": "workflow-a.yaml",
            },
        )
        assert saved["exists"] is True
        assert saved["agent"] == "opencode"

        other = _request_json(
            f"{base}/api/project/preferences?project={urllib.parse.quote(str(project_b))}"
        )
        assert other["exists"] is False
        assert other["agent"] == ""
        assert other["workflow"] == ""

        reloaded = _request_json(
            f"{base}/api/project/preferences?project={urllib.parse.quote(str(project_a))}"
        )
        assert reloaded["agent"] == "opencode"
        assert reloaded["model"] == "provider/model-a"
        assert reloaded["mode"] == "read"
        assert reloaded["reasoning"] == "high"
        assert reloaded["workflow"] == "workflow-a.yaml"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)



def test_new_project_copies_global_defaults_once_via_http_api(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    project_a = repo / "existing"
    project_b = repo / "new-project"
    (repo / "ui" / "data").mkdir(parents=True)
    project_a.mkdir()
    project_b.mkdir()

    server = UIServer(repo, "127.0.0.1", 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.port}"
    try:
        _request_json(
            f"{base}/api/projects/add",
            method="POST",
            body={"path": str(project_a)},
        )
        server.state.project_preferences.update(
            project_a,
            {
                "agent": "qwen",
                "model": "qwen/existing",
                "mode": "auto",
                "reasoning": "medium",
                "workflow": "existing.yaml",
            },
        )

        _request_json(
            f"{base}/api/settings",
            method="POST",
            body={
                "defaults": {
                    "agent": "opencode",
                    "model": "openai/gpt-5.2",
                    "mode": "read",
                    "reasoning": "high",
                    "workflow": "new-default.yaml",
                }
            },
        )
        _request_json(
            f"{base}/api/projects/add",
            method="POST",
            body={"path": str(project_b)},
        )

        old_project = _request_json(
            f"{base}/api/project/preferences?project={urllib.parse.quote(str(project_a))}"
        )
        new_project = _request_json(
            f"{base}/api/project/preferences?project={urllib.parse.quote(str(project_b))}"
        )
        assert (
            old_project["agent"],
            old_project["model"],
            old_project["mode"],
            old_project["reasoning"],
            old_project["workflow"],
        ) == ("qwen", "qwen/existing", "auto", "medium", "existing.yaml")
        assert (
            new_project["agent"],
            new_project["model"],
            new_project["mode"],
            new_project["reasoning"],
            new_project["workflow"],
        ) == (
            "opencode",
            "openai/gpt-5.2",
            "read",
            "high",
            "new-default.yaml",
        )

        # Later Global Default changes never rewrite either existing Project.
        _request_json(
            f"{base}/api/settings",
            method="POST",
            body={
                "defaults": {
                    "agent": "qwen",
                    "model": "qwen/new-default",
                    "mode": "yolo",
                    "reasoning": "max",
                    "workflow": "later.yaml",
                }
            },
        )
        assert server.state.project_preferences.get(project_a)["model"] == "qwen/existing"
        assert server.state.project_preferences.get(project_b)["model"] == "openai/gpt-5.2"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
