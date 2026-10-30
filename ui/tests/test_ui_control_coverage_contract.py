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


def test_all_static_buttons_have_browser_click_ownership() -> None:
    """Every static production button must be clicked by Chromium.

    Merely asserting visibility or mentioning an ID is not enough for an
    operation control. projectModalClose is intentionally exercised through a
    parameterized close-button loop, so its indirect click is asserted here
    explicitly as the only non-literal click form.
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
    button_ids = re.findall(
        r"""<button\b[^>]*\bid=["']([^"']+)["'][^>]*>""",
        html,
        flags=re.IGNORECASE,
    )
    indirect_clicks = {
        "projectModalClose": (
            '"#projectModalCancel", "#projectModalClose"' in browser_tests
            and "page.click(close_button)" in browser_tests
        ),
    }
    missing = []
    for element_id in button_ids:
        escaped = re.escape(element_id)
        directly_clicked = (
            re.search(
                rf"""(?:page\.)?click\(["']#{escaped}["']""",
                browser_tests,
            )
            is not None
            or re.search(
                rf"""locator\(["']#{escaped}["']\)\.click\(""",
                browser_tests,
            )
            is not None
        )
        if not directly_clicked and not indirect_clicks.get(element_id, False):
            missing.append(element_id)

    assert len(button_ids) >= 102, "Unexpected removal of application buttons"
    assert not missing, (
        "Static buttons without an executable Chromium click: "
        f"{missing}. Add a real browser click and behavioral assertion."
    )


def test_all_user_editable_static_fields_have_browser_input_ownership() -> None:
    """Visible editable form fields must be changed by Chromium tests.

    Hidden native selects, readonly path mirrors, and hidden file inputs are
    operated through their visible picker controls and are intentionally
    excluded from direct fill/select ownership.
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
    controls = re.findall(
        r"""<(input|select|textarea)\b([^>]*)\bid=["']([^"']+)["']([^>]*)>""",
        html,
        flags=re.IGNORECASE,
    )
    editable: list[tuple[str, str]] = []
    for tag, before, element_id, after in controls:
        attrs = f"{before} {after}"
        hidden_proxy = (
            "aria-hidden=\"true\"" in attrs
            or " hidden" in f" {attrs}"
            or "visually-hidden-file" in attrs
            or re.search(r"""type=["']file["']""", attrs, flags=re.IGNORECASE)
        )
        if hidden_proxy or re.search(r"\breadonly\b", attrs, flags=re.IGNORECASE):
            continue
        editable.append((tag.lower(), element_id))

    missing = []
    for tag, element_id in editable:
        escaped = re.escape(element_id)
        operated = (
            re.search(
                rf"""(?:page\.)?fill\(\s*["']#{escaped}["']""",
                browser_tests,
            )
            is not None
            or re.search(
                rf"""(?:page\.)?select_option\(\s*["']#{escaped}["']""",
                browser_tests,
            )
            is not None
            or re.search(
                rf"""locator\(\s*["']#{escaped}["']\s*\)\.(?:fill|select_option|check|uncheck|press)\(""",
                browser_tests,
            )
            is not None
        )
        if not operated:
            missing.append(f"{tag}#{element_id}")

    assert len(editable) >= 34, "Unexpected removal of visible editable fields"
    assert not missing, (
        "Visible editable fields without Chromium input/select ownership: "
        f"{missing}. Add a real browser edit and behavioral assertion."
    )


DYNAMIC_UI_SURFACES = {
    ROOT / "ui" / "static" / "app.js": (
        ("project-menu-button", "project-menu-button"),
        ("project-action-menu", "project-action-menu"),
        ("backend-dropdown-option", "backend-dropdown-option"),
        ("workflow-dropdown-option", "workflow-dropdown-option"),
        ("environment-check-toggle", "environment-check-toggle"),
        ("studio-empty-action", "studio-empty-action"),
        ("designer-param-chip", "designer-param-chip"),
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
        ("task-workspace-row-more", "task-workspace-row-more"),
        ("task-workspace-row-up", "Move up"),
        ("task-workspace-row-down", "Move down"),
        ("task-workspace-row-edit", "task-workspace-row-edit"),
        ("task-workspace-move-close", "task-workspace-move-close"),
        ("task-workspace-move-option", "task-workspace-move-option"),
        ("taskSourceMode", "data-task-source-mode"),
        ("task-workspace-project-toggle", "task-workspace-project-toggle"),
        ("task-workspace-project-dropdown-option", "task-workspace-project-dropdown-option"),
        ("taskUploadField", "data-task-upload-field"),
        ("taskWorkspaceMerge", "taskWorkspaceMerge"),
        ("taskWorkspaceMergeChat", "taskWorkspaceMergeChat"),
        ("taskWorkspaceDeleteTask", "taskWorkspaceDeleteTask"),
        ("taskWorkspaceOpenList", "taskWorkspaceOpenList"),
        ("taskWorkspaceEditTask", "taskWorkspaceEditTask"),
        ("taskWorkspaceResetTask", "taskWorkspaceResetTask"),
        ("taskWorkspaceRerunTask", "taskWorkspaceRerunTask"),
        ("task-workspace-tab", 'get_by_role("button", name="Runtime"'),
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
        ("setSelected(problem.stage)", "warning_problem.click()"),
        ("parameter-sections", "parameter_tabs.nth(index).click()"),
        ("test-mode-tabs", "test-mode-tabs"),
        ("add-stage-command", "add-stage-command"),
        ("closeAddStageCommand", "add-stage-command-head"),
        ("workflow-draft-recovery", "workflow-draft-recovery"),
        ("discardWorkflowDraft", 'name="捨棄"'),
        ("restoreWorkflowDraft", 'name="還原"'),
        ("create-stage-card", "create-stage-card"),
        ("palette-quick-add", "palette-quick-add"),
        ("data-stage-type", "data-stage-type"),
        ("inline-prompt-edit", 'name="Edit Prompt"'),
        ("onClick={leaveStudio}", 'name="← Workflows"'),
        ("onClick={resetLayout}", 'name="重設排列"'),
        ("onClick={reloadStudio}", 'name="重新載入"'),
        ("saveCurrent()", ".studio-header button.primary"),
        ('switchEditorView("designer")', 'name="Designer"'),
        ('switchEditorView("yaml")', 'name="YAML"'),
        ("writeSnapPreference(next)", ".snap-toggle"),
        ("applyStageYaml", 'name="套用 YAML"'),
        ("copyStageByName(contextMenu.stage)", "copy_button.click()"),
        ("pasteStage()", "paste_button.click()"),
        ("duplicateStage(contextMenu.stage)", 'menu.locator("button").nth(4).click()'),
        ("deleteStage(contextMenu.stage)", 'delete_menu.locator("button.danger-item").click()'),
        ("confirmPendingCreate()", 'name="Create Stage"'),
        ("setEditorOpen(false)", ".modal-close-button"),
        ('setTestMode("agent_ping")', 'name="Agent Ping"'),
        ('setTestMode("mock_error")', 'name="Mock Technical Error"'),
        ("setTestScenario(scenario)", "scenario-pass"),
        ("stageTestPrompt(draft, catalog, testScenario)", ".test-input-actions"),
        ('setTestInput("")', ".test-input-actions"),
        ("testStage()", ".test-action-row > button.primary"),
        ("stopStageTest()", ".test-action-row > button.danger"),
        ("testPathFromStage()", 'name="Test path to END"'),
        ("duplicateStage()", 'get_by_title("複製目前設定，但不複製結果連線")'),
        ("deleteStage()", 'footer button.danger'),
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


DYNAMIC_ID_SOURCES = (
    ROOT / "ui" / "static" / "app.js",
    ROOT / "ui" / "static" / "js" / "task-workspace.js",
    ROOT / "ui" / "static" / "js" / "tasks-board.js",
)


def test_literal_dynamic_ui_ids_have_browser_traceability() -> None:
    """Literal IDs created by JavaScript must be visible to Chromium tests.

    Static index.html scanning cannot see controls/panels assembled at runtime.
    Prefix-only IDs such as taskWorkspaceFieldError- are excluded because the
    final DOM ID is data-dependent and the field behavior is covered through
    its owning editor controls.
    """
    browser_tests = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (
            BROWSER,
            DESIGNER,
            ROOT / "ui" / "tests" / "test_uncovered_modal_actions_browser.py",
        )
    )
    dynamic_ids: list[str] = []
    for source in DYNAMIC_ID_SOURCES:
        production = source.read_text(encoding="utf-8")
        dynamic_ids.extend(
            re.findall(r"""\.id\s*=\s*["']([^"']+)["']""", production)
        )
    dynamic_ids = sorted(
        {
            element_id
            for element_id in dynamic_ids
            if element_id and not element_id.endswith("-")
        }
    )
    missing = [
        element_id
        for element_id in dynamic_ids
        if re.search(
            r"(?<![A-Za-z0-9_])" + re.escape(element_id) + r"(?![A-Za-z0-9_])",
            browser_tests,
        ) is None
    ]
    assert len(dynamic_ids) >= 32, "Unexpected removal of runtime-created UI IDs"
    assert not missing, (
        "Runtime-created UI IDs without Chromium traceability: "
        f"{missing}. Add a browser interaction/assertion for the dynamic surface."
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
