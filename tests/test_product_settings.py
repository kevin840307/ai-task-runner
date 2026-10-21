from __future__ import annotations

import pytest

from product_settings import (
    AUTO_WORKSPACE_POLICIES,
    MERGE_FAILURE_LIMIT_MAX,
    MERGE_FAILURE_LIMIT_MIN,
    GlobalSettingsStore,
)


@pytest.mark.parametrize("policy", sorted(AUTO_WORKSPACE_POLICIES))
def test_global_execution_settings_persist_each_auto_policy(tmp_path, policy: str) -> None:
    path = tmp_path / "settings.json"
    store = GlobalSettingsStore(path)

    value = store.update({
        "execution": {
            "auto_workspace_policy": policy,
            "merge_failure_limit": 7,
            "allow_concurrent_main_tasks": True,
        }
    })

    assert value["execution"] == {
        "auto_workspace_policy": policy,
        "merge_failure_limit": 7,
        "allow_concurrent_main_tasks": True,
    }
    assert GlobalSettingsStore(path).get()["execution"] == value["execution"]


@pytest.mark.parametrize("limit", [MERGE_FAILURE_LIMIT_MIN, MERGE_FAILURE_LIMIT_MAX])
def test_merge_failure_limit_accepts_only_documented_boundaries(tmp_path, limit: int) -> None:
    store = GlobalSettingsStore(tmp_path / "settings.json")
    value = store.update({"execution": {"merge_failure_limit": limit}})
    assert value["execution"]["merge_failure_limit"] == limit


@pytest.mark.parametrize(
    "limit",
    [MERGE_FAILURE_LIMIT_MIN - 1, MERGE_FAILURE_LIMIT_MAX + 1],
)
def test_merge_failure_limit_rejects_out_of_range_values(tmp_path, limit: int) -> None:
    store = GlobalSettingsStore(tmp_path / "settings.json")
    with pytest.raises(ValueError, match="between 0 and 99"):
        store.update({"execution": {"merge_failure_limit": limit}})


def test_concurrent_main_setting_requires_boolean(tmp_path) -> None:
    store = GlobalSettingsStore(tmp_path / "settings.json")
    with pytest.raises(ValueError, match="must be boolean"):
        store.update({"execution": {"allow_concurrent_main_tasks": "true"}})
