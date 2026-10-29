"""Traceability gate for visible application UI entrypoints.

This is a coverage *inventory*, not a claim that mentioning a selector proves
all interaction paths. Functional behavior remains asserted by the mapped
browser tests, service tests, and prototype parity suite.
"""
from __future__ import annotations

from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[2]
HTML = ROOT / "ui" / "static" / "index.html"
BROWSER = ROOT / "ui" / "tests" / "test_browser_crud_e2e.py"
DESIGNER = ROOT / "ui" / "tests" / "test_full_designer_browser.py"
STATIC = ROOT / "ui" / "tests" / "test_static_contract.py"
PARITY = ROOT / "ui" / "tests" / "test_feature_task_ui_parity.py"
UI_TEST = ROOT / "ui" / "tests" / "test_ui.py"

# Every listed entrypoint must exist in production HTML and have test-level
# references. Deliberately include distinct categories rather than inferring
# a 100%-coverage claim from the number of passing pytest functions.
ENTRYPOINTS = {
    "navigation": ("openProject", "chatNav", "workflowNav", "promptNav", "themeButton"),
    "project_chat": (
        "newProjectChatButton", "deleteProjectChatButton", "projectChatSendButton",
        "projectChatQueue", "projectChatSettingsButton",
    ),
    "task_board": (
        "tasksNewButton", "tasksBoardSearch", "tasksProjectFilterButton",
        "tasksRunningFilterButton", "tasksCurrentRuntimeButton",
    ),
    "runner_controls": ("sendButton", "stopButton", "resumeButton", "resetButton", "optionsButton"),
    "workflow_editor": (
        "newWorkflowButton", "saveStudioButton", "validateStudioButton",
        "studioSearchInput", "studioAssetMenuButton",
    ),
    "workflow_generator": (
        "generateWorkflowButton", "generateWorkflowCancel",
        "generateWorkflowRetry", "generateWorkflowConfirm",
    ),
}


def test_each_main_ui_entrypoint_is_referenced_by_a_test() -> None:
    html = HTML.read_text(encoding="utf-8")
    tests = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (BROWSER, DESIGNER, STATIC, PARITY, UI_TEST)
    )
    missing_html = []
    missing_test = []
    for group, ids in ENTRYPOINTS.items():
        for element_id in ids:
            if re.search(r'\\bid=["\\\']' + re.escape(element_id) + r'["\\\']', html) is None:
                missing_html.append(f"{group}: {element_id}")
            if re.search(r'(?<![A-Za-z0-9_])' + re.escape(element_id) + r'(?![A-Za-z0-9_])', tests) is None:
                missing_test.append(f"{group}: {element_id}")
    assert not missing_html, f"Missing production entrypoints: {missing_html}"
    assert not missing_test, (
        "UI entrypoints without an explicit test reference: "
        f"{missing_test}. Add a behavioral test, not only this inventory."
    )


def test_ui_inventory_has_unique_ids_and_all_six_surfaces() -> None:
    assert set(ENTRYPOINTS) == {
        "navigation", "project_chat", "task_board",
        "runner_controls", "workflow_editor", "workflow_generator",
    }
    ids = [element_id for group in ENTRYPOINTS.values() for element_id in group]
    assert len(ids) == len(set(ids)), "Ambiguous UI ownership in coverage inventory"
    assert len(ids) >= 25
