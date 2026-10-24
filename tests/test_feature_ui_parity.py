"""Regression lock for the accepted feature Task UI CSS baseline."""
from tool.compare_feature_ui import PANELS, compare_panels


def test_feature_task_ui_css_matches_prototype() -> None:
    drift = compare_panels(PANELS)
    assert not drift, "\n".join(drift)
