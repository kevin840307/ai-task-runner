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
SERVER = ROOT / "ui" / "server.py"

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
            if ('id="' + element_id + '"') not in html and ("id='" + element_id + "'") not in html:
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


def test_all_static_html_controls_have_test_traceability() -> None:
    """Every static button/input/select/textarea must have a named test reference.

    This is a minimum evidence gate, not a substitute for behavior assertions,
    dynamic React controls, cross-state E2E, or code/branch coverage metrics.
    """
    html = HTML.read_text(encoding="utf-8")
    test_paths = (BROWSER, DESIGNER, STATIC, PARITY, UI_TEST,
                  ROOT / "ui" / "tests" / "test_uncovered_modal_actions_browser.py")
    tests = "\n".join(path.read_text(encoding="utf-8") for path in test_paths)
    control_ids = re.findall(
        r"""<(?:button|input|select|textarea)\b[^>]*\bid=["']([^"']+)["']""",
        html,
        flags=re.IGNORECASE,
    )
    assert len(control_ids) == len(set(control_ids)), "Duplicate HTML control IDs"
    assert len(control_ids) >= 142, "Unexpected removal of application controls"
    unreferenced = [
        element_id for element_id in control_ids
        if re.search(
            r"(?<![A-Za-z0-9_])" + re.escape(element_id) + r"(?![A-Za-z0-9_])",
            tests,
        ) is None
    ]
    assert not unreferenced, (
        "HTML controls without test references: "
        f"{unreferenced}. Add functional browser coverage before registering the ID."
    )


def test_all_static_html_controls_have_browser_behavioral_traceability() -> None:
    """Every production form control must be owned by an executable browser test.

    Static/parity references remain useful design contracts, but they are not
    sufficient evidence for a clickable/interactive control. This gate keeps
    every button/input/select/textarea tied to one of the Chromium suites.
    """
    html = HTML.read_text(encoding="utf-8")
    browser_tests = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (
            BROWSER,
            DESIGNER,
            ROOT / "ui" / "tests" / "test_uncovered_modal_actions_browser.py",
        )
    )
    control_ids = re.findall(
        r"""<(?:button|input|select|textarea)\b[^>]*\bid=["']([^"']+)["']""",
        html,
        flags=re.IGNORECASE,
    )
    unreferenced = [
        element_id for element_id in control_ids
        if re.search(
            r"(?<![A-Za-z0-9_])" + re.escape(element_id) + r"(?![A-Za-z0-9_])",
            browser_tests,
        ) is None
    ]
    assert len(control_ids) >= 142, "Unexpected removal of application controls"
    assert not unreferenced, (
        "Static UI controls without Chromium behavioral ownership: "
        f"{unreferenced}. Add a real browser interaction test; a static reference "
        "alone is not sufficient."
    )


DYNAMIC_UI_SURFACES = {
    ROOT / "ui" / "static" / "app.js": (
        ("project-menu-button", "project-menu-button"),
        ("project-action-menu", "project-action-menu"),
        ("backend-dropdown-option", "#backendDropdownMenu"),
        ("workflow-dropdown-option", "workflow-dropdown-option"),
        ("environment-check-toggle", "environment-check-toggle"),
    ),
    ROOT / "ui" / "static" / "js" / "task-workspace.js": (
        ("taskWorkspaceContextMenu", "taskWorkspaceContextMenu"),
        ("data-task-context-action", "data-task-context-action"),
        ("taskCreateMenu", "taskCreateMenu"),
        # dataset.taskCreateKind becomes data-task-create-kind in the DOM.
        ("taskCreateKind", "data-task-create-kind"),
        ("task-workspace-move-existing", "taskWorkspaceMove"),
        ("task-workspace-workspace-option", "data-workspace-option"),
        ("taskWorkspacePublish", "taskWorkspacePublish"),
        ("taskWorkspaceCleanupWorktrees", "taskWorkspaceCleanupWorktrees"),
    ),
    ROOT / "ui" / "static" / "js" / "tasks-board.js": (
        ("tasksBoardContextMenu", "tasksBoardContextMenu"),
        ("data-tasks-context-action", "data-tasks-context-action"),
        ("data-tasks-view-mode", "data-tasks-view-mode"),
    ),
    ROOT / "ui" / "static" / "js" / "project-chat.js": (
        ("project-chat-suggest-item", "project-chat-suggest-item"),
        ("project-chat-queue-item", "project-chat-queue-item"),
        ("project-chat-task-draft", "project-chat-task-draft"),
        ("project-chat-ask", ".project-chat-ask"),
    ),
    ROOT / "ui" / "studio-src" / "src" / "main.tsx": (
        ("stage-context-menu", "stage-context-menu"),
        ("edge-context-menu", "edge-context-menu"),
        ("workflow-problems", "workflow-problems"),
        ("Dismiss Workflow problems", "Dismiss Workflow problems"),
        ("parameter-sections", "parameter-sections"),
        ("test-mode-tabs", "test-mode-tabs"),
        ("add-stage-command", "add-stage-command"),
        ("workflow-draft-recovery", "workflow-draft-recovery"),
        ("create-stage-card", "create-stage-card"),
    ),
}


def test_dynamic_ui_surfaces_have_test_traceability() -> None:
    """JS/React-created controls must remain tied to executable UI tests.

    Tokens here identify dynamic action surfaces that cannot be discovered by
    scanning static index.html alone. A token reference is only the inventory
    gate; the referenced browser tests still own the actual behavior assertion.
    """
    test_paths = (
        BROWSER,
        DESIGNER,
        PARITY,
        ROOT / "ui" / "tests" / "test_uncovered_modal_actions_browser.py",
    )
    tests = "\n".join(path.read_text(encoding="utf-8") for path in test_paths)
    missing_source = []
    missing_test = []
    for source, token_pairs in DYNAMIC_UI_SURFACES.items():
        production = source.read_text(encoding="utf-8")
        for source_token, test_token in token_pairs:
            if source_token not in production:
                missing_source.append(f"{source.relative_to(ROOT)}: {source_token}")
            if test_token not in tests:
                missing_test.append(
                    f"{source.relative_to(ROOT)}: {source_token} -> {test_token}"
                )
    assert not missing_source, f"Dynamic UI inventory drifted from production: {missing_source}"
    assert not missing_test, (
        "Dynamic UI surfaces without explicit test traceability: "
        f"{missing_test}. Add a behavioral browser assertion before updating the inventory."
    )


def _server_api_routes() -> list[str]:
    """Return every literal UI API route/prefix dispatched by Handler."""
    source = SERVER.read_text(encoding="utf-8")
    routes = set(
        re.findall(r"""parsed\.path\s*==\s*["'](\/api\/[^"']+)["']""", source)
    )
    routes.update(
        re.findall(
            r"""parsed\.path\.startswith\(["'](\/api\/[^"']+)["']\)""",
            source,
        )
    )
    for block in re.findall(r"""parsed\.path\s+in\s+\{([^}]+)\}""", source):
        routes.update(re.findall(r"""["'](\/api\/[^"']+)["']""", block))
    return sorted(routes)


def test_all_server_api_routes_have_test_traceability() -> None:
    """A new HTTP API route must arrive with a test reference in the same change.

    This is intentionally a traceability gate rather than a code-coverage claim:
    route-specific tests still own success/error semantics, while this test makes
    it impossible to add a Handler route and silently forget all test coverage.
    """
    routes = _server_api_routes()
    tests = "\n".join(
        path.read_text(encoding="utf-8")
        for path in sorted((ROOT / "ui" / "tests").glob("test_*.py"))
        if path.resolve() != Path(__file__).resolve()
    )
    assert len(routes) >= 98, "Unexpected removal of UI API routes"
    missing = [route for route in routes if route not in tests]
    assert not missing, (
        "UI API routes without explicit test traceability: "
        f"{missing}. Add a service, HTTP dispatch, or browser test for each route."
    )
