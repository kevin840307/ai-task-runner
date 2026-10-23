from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
FEATURE_CSS = (ROOT / "feature" / "ui-prototype" / "styles.css").read_text(encoding="utf-8")
PRODUCTION_CSS = (ROOT / "ui" / "static" / "css" / "task-workspace.css").read_text(encoding="utf-8")
PROTOTYPE_HTML = (ROOT / "feature" / "ai-task-runner-ui-prototype.html").read_text(encoding="utf-8")
PRODUCTION_JS = (ROOT / "ui" / "static" / "js" / "task-workspace.js").read_text(encoding="utf-8")

_RULE = re.compile(r"([^{}]+)\{([^{}]*)\}", re.S)


def _normalize(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip()).replace(" !important", "!important")


def _declarations(css: str, selector: str, *, after: str | None = None) -> dict[str, str]:
    source = css
    if after:
        assert after in source, f"missing CSS section marker: {after}"
        source = source.split(after, 1)[1]
    for match in _RULE.finditer(source):
        selectors = [_normalize(part) for part in match.group(1).split(",")]
        if _normalize(selector) not in selectors:
            continue
        result: dict[str, str] = {}
        for raw in match.group(2).split(";"):
            if ":" not in raw:
                continue
            key, value = raw.split(":", 1)
            result[key.strip()] = _normalize(value)
        return result
    raise AssertionError(f"selector not found after marker {after!r}: {selector}")


def _same(
    feature_selector: str,
    production_selector: str,
    properties: tuple[str, ...],
    *,
    feature_after: str | None = None,
    production_after: str | None = None,
) -> None:
    feature = _declarations(FEATURE_CSS, feature_selector, after=feature_after)
    production = _declarations(PRODUCTION_CSS, production_selector, after=production_after)
    for prop in properties:
        assert prop in feature, f"{feature_selector} is missing {prop}"
        assert prop in production, f"{production_selector} is missing {prop}"
        assert production[prop] == feature[prop], (
            f"{prop} drifted from feature reference: "
            f"{production_selector}={production[prop]!r}, "
            f"{feature_selector}={feature[prop]!r}"
        )


def test_task_editor_geometry_matches_feature_reference() -> None:
    feature_marker = "/* New Task editor density + input hierarchy */"
    production_marker = "/* Feature prototype parity: Task Editor is the shared 920px workspace route. */"

    _same(
        "#newTaskModal>.modal-body",
        ".task-workspace-shell.task-editor-route .task-workspace-body",
        ("padding",),
        feature_after=feature_marker,
        production_after=production_marker,
    )
    _same(
        "#newTaskModal .task-basics",
        ".task-workspace-basics",
        ("grid-template-columns", "gap"),
        feature_after=feature_marker,
        production_after=production_marker,
    )
    _same(
        "#newTaskModal .task-input-grid",
        ".task-workspace-input-grid",
        ("grid-template-columns", "gap", "margin-top"),
        feature_after=feature_marker,
        production_after=production_marker,
    )
    _same(
        "#newTaskModal .task-editor-secondary .workspace-option",
        ".task-workspace-editor-secondary .task-workspace-workspace-option",
        ("min-height", "padding"),
        feature_after=feature_marker,
        production_after=production_marker,
    )
    _same(
        "#newTaskModal>.modal-foot",
        ".task-workspace-shell.task-editor-route .task-workspace-foot",
        ("padding",),
        feature_after=feature_marker,
        production_after=production_marker,
    )

    feature_prompt = _declarations(
        FEATURE_CSS,
        "#newTaskModal .task-primary-source .primary-task-prompt",
        after=feature_marker,
    )
    production_prompt = _declarations(
        PRODUCTION_CSS,
        ".task-workspace-task-primary-source textarea",
        after=production_marker,
    )
    assert production_prompt["min-height"] == feature_prompt["min-height"]


def test_task_workspace_shell_and_header_actions_match_feature_reference() -> None:
    feature_marker = "/* Drawer */"
    production_shell_marker = "/* Feature prototype parity: Task Editor is the shared 920px workspace route. */"
    production_drawer_marker = "/* Feature Task Drawer shell parity; narrow-view full-width behavior remains responsive. */"
    production_actions_marker = "/* Feature drawer header action group: List owns actions in the shared shell. */"

    _same(
        ".drawer.workspace-route",
        ".task-workspace-shell.workspace-route",
        ("width", "max-width"),
        feature_after=feature_marker,
        production_after=production_shell_marker,
    )
    _same(
        ".drawer-back",
        ".task-workspace-back",
        ("width", "height", "border-radius", "font-size"),
        feature_after=feature_marker,
        production_after=production_drawer_marker,
    )
    _same(
        ".drawer-shell-actions .btn",
        ".task-workspace-header-actions button",
        ("height", "min-height", "padding", "font-size"),
        feature_after=feature_marker,
        production_after=production_actions_marker,
    )


def test_task_list_geometry_and_drag_feedback_match_feature_reference() -> None:
    feature_list_marker = "/* Full plan surface: same Task, deeper editing only when needed */"
    production_list_marker = "/* Feature Task List Workspace: main list + List info / Quick use side rail. */"
    feature_add_marker = "/* Task List row alignment + one stable Add task footer */"

    _same(
        ".plan-page-body",
        ".task-workspace-list-page",
        ("grid-template-columns", "gap", "padding"),
        feature_after=feature_list_marker,
        production_after=production_list_marker,
    )
    _same(
        ".plan-main",
        ".task-workspace-list-main",
        ("padding", "border-radius"),
        feature_after=feature_list_marker,
        production_after=production_list_marker,
    )
    _same(
        ".plan-add-task-footer",
        ".task-workspace-add-task-footer",
        ("width", "min-height", "gap", "margin-top", "border-radius", "font-size"),
        feature_after=feature_add_marker,
        production_after=production_list_marker,
    )
    _same(
        ".plan-row-compact.dragging",
        ".task-workspace-list-row.dragging",
        ("opacity",),
        feature_after=feature_add_marker,
    )
    _same(
        ".plan-row-compact.drag-over",
        ".task-workspace-list-row.drag-over",
        ("outline", "outline-offset"),
        feature_after=feature_add_marker,
    )


def test_task_list_action_ownership_matches_prototype_html() -> None:
    # The feature shell owns these Task List actions; production maps them to
    # the same shared drawer header rather than duplicating controls in List info.
    feature_ids = {
        "planOpenWorkflow": "taskWorkspaceHeaderOpenWorkflow",
        "planAddTask": "taskWorkspaceHeaderAddTask",
        "planAddExisting": "taskWorkspaceHeaderMoveExisting",
        "planEditYaml": "taskWorkspaceHeaderYaml",
        "cancelTaskListDraft": "taskWorkspaceHeaderCancel",
        "confirmTaskListDraft": "taskWorkspaceHeaderCreateList",
    }
    for feature_id, production_id in feature_ids.items():
        assert f'id="{feature_id}"' in PROTOTYPE_HTML
        assert f'id="{production_id}"' in PRODUCTION_JS

    assert 'className = "task-workspace-list-tools-wrap"' in PRODUCTION_JS
    assert 'wrap.hidden = true' in PRODUCTION_JS
    assert 'tools.appendChild(move)' not in PRODUCTION_JS
    assert 'tools.appendChild(yaml)' not in PRODUCTION_JS
