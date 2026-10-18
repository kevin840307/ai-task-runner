from __future__ import annotations

from pathlib import Path

import pytest

from ui.project_preferences import ProjectPreferences


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
    with pytest.raises(ValueError, match="reasoning"):
        preferences.update(project, {"reasoning": "ultra"})
    with pytest.raises(ValueError, match="must be an object"):
        preferences.update(project, {"validators": []})


def test_project_preferences_corruption_fails_closed(tmp_path: Path) -> None:
    project = tmp_path / "project"
    path = project / ".ai-task-runner" / "ui" / "project-preferences.json"
    path.parent.mkdir(parents=True)
    path.write_text("{broken", encoding="utf-8")

    with pytest.raises(ValueError, match="Project preferences are invalid"):
        ProjectPreferences().get(project)
