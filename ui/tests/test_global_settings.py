from __future__ import annotations

import json
from pathlib import Path

import pytest

from product_settings import GlobalSettingsStore


def test_global_settings_defaults_and_roundtrip(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    store = GlobalSettingsStore(path)
    initial = store.get()
    assert initial["version"] == 1
    assert initial["execution"]["merge_failure_limit"] == 3
    assert initial["execution"]["allow_concurrent_main_tasks"] is False
    assert initial["interface"] == {
        "appearance": "system",
        "theme": "teal",
        "motion": "full",
    }
    assert initial["language"] == "zh-TW"
    assert initial["defaults"]["mode"] == "auto"
    assert initial["defaults"]["reasoning"] == "medium"

    updated = store.update({
        "execution": {
            "merge_failure_limit": 5,
            "allow_concurrent_main_tasks": True,
        },
        "interface": {"appearance": "dark", "theme": "violet"},
        "language": "en",
        "defaults": {
            "agent": "opencode",
            "model": "provider/model",
            "mode": "read",
            "reasoning": "high",
            "workflow": "workflow.yaml",
        },
    })
    assert updated["execution"]["auto_workspace_policy"] == "busy-worktree"
    assert updated["execution"]["merge_failure_limit"] == 5
    assert updated["interface"]["motion"] == "full"
    assert GlobalSettingsStore(path).get() == updated


def test_global_settings_validates_and_migrates_preversioned_file(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({
        "interface": {"appearance": "light", "theme": "amber"},
        "language": "en",
    }), encoding="utf-8")
    store = GlobalSettingsStore(path)
    migrated = store.get()
    assert migrated["version"] == 1
    assert migrated["interface"]["appearance"] == "light"
    assert migrated["interface"]["theme"] == "amber"
    assert migrated["interface"]["motion"] == "full"
    assert migrated["execution"]["merge_failure_limit"] == 3

    with pytest.raises(ValueError, match="Merge failure"):
        store.update({"execution": {"merge_failure_limit": -1}})
    with pytest.raises(ValueError, match="Unknown Global Settings field"):
        store.update({"other": True})
    with pytest.raises(ValueError, match="Invalid default mode"):
        store.update({"defaults": {"mode": "magic"}})


def test_global_settings_rejects_unknown_future_version(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"version": 999}), encoding="utf-8")
    with pytest.raises(ValueError, match="Unsupported Global Settings version"):
        GlobalSettingsStore(path).get()
