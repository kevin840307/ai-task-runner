from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
FEATURE_CSS = (ROOT / "feature" / "ui-prototype" / "styles.css").read_text(encoding="utf-8")
FEATURE_EDITOR_JS = (ROOT / "feature" / "ui-prototype" / "task-editor.js").read_text(encoding="utf-8")
FEATURE_TEMPLATES = (ROOT / "feature" / "ui-prototype" / "task-ui-templates.js").read_text(encoding="utf-8")
PROTOTYPE_HTML = (ROOT / "feature" / "ai-task-runner-ui-prototype.html").read_text(encoding="utf-8")
PRODUCTION_CSS = (ROOT / "ui" / "static" / "css" / "task-workspace.css").read_text(encoding="utf-8")
PRODUCTION_JS = (ROOT / "ui" / "static" / "js" / "task-workspace.js").read_text(encoding="utf-8")
PRODUCTION_TOKENS = (ROOT / "ui" / "static" / "css" / "tokens.css").read_text(encoding="utf-8")
PRODUCTION_BOOTSTRAP = (ROOT / "ui" / "static" / "js" / "ui-bootstrap.js").read_text(encoding="utf-8")
PRODUCTION_APP = (ROOT / "ui" / "static" / "app.js").read_text(encoding="utf-8")
PRODUCTION_HTML = (ROOT / "ui" / "static" / "index.html").read_text(encoding="utf-8")


def _normalize(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip()).replace(" !important", "!important")


@dataclass(frozen=True)
class _Rule:
    media: str | None
    selectors: tuple[str, ...]
    declarations: dict[str, str]


def _matching_brace(source: str, open_index: int) -> int:
    depth = 1
    quote: str | None = None
    index = open_index + 1
    while index < len(source):
        char = source[index]
        if quote:
            if char == "\\":
                index += 2
                continue
            if char == quote:
                quote = None
        elif char in {"'", '"'}:
            quote = char
        elif source.startswith("/*", index):
            end = source.find("*/", index + 2)
            index = len(source) if end < 0 else end + 2
            continue
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return index
        index += 1
    raise AssertionError("unbalanced CSS braces")


def _rules(source: str, *, media: str | None = None) -> list[_Rule]:
    result: list[_Rule] = []
    index = 0
    while index < len(source):
        if source.startswith("/*", index):
            end = source.find("*/", index + 2)
            index = len(source) if end < 0 else end + 2
            continue
        if source[index].isspace():
            index += 1
            continue

        open_index = source.find("{", index)
        if open_index < 0:
            break
        semicolon = source.find(";", index, open_index)
        if semicolon >= 0:
            index = semicolon + 1
            continue

        header = source[index:open_index].strip()
        close_index = _matching_brace(source, open_index)
        body = source[open_index + 1 : close_index]

        if header.startswith("@media"):
            query = _normalize(header[len("@media") :])
            result.extend(_rules(body, media=query))
        elif not header.startswith("@"):
            declarations: dict[str, str] = {}
            for raw in body.split(";"):
                if ":" not in raw:
                    continue
                key, value = raw.split(":", 1)
                declarations[key.strip()] = _normalize(value)
            selectors = tuple(_normalize(part) for part in header.split(","))
            result.append(_Rule(media=media, selectors=selectors, declarations=declarations))
        index = close_index + 1
    return result


def _declarations(
    css: str,
    selector: str,
    *,
    media_contains: str | None = None,
) -> dict[str, str]:
    wanted = _normalize(selector)
    result: dict[str, str] = {}
    found = False
    for rule in _rules(css):
        if media_contains is None:
            if rule.media is not None:
                continue
        elif rule.media is None or _normalize(media_contains) not in _normalize(rule.media):
            continue
        if wanted not in rule.selectors:
            continue
        found = True
        result.update(rule.declarations)
    assert found, f"selector not found ({media_contains or 'base'}): {selector}"
    return result


def _same(
    feature_selector: str,
    production_selector: str,
    properties: tuple[str, ...],
    *,
    feature_media: str | None = None,
    production_media: str | None = None,
) -> None:
    feature = _declarations(FEATURE_CSS, feature_selector, media_contains=feature_media)
    production = _declarations(PRODUCTION_CSS, production_selector, media_contains=production_media)
    for prop in properties:
        assert prop in feature, f"{feature_selector} is missing {prop}"
        assert prop in production, f"{production_selector} is missing {prop}"
        assert production[prop] == feature[prop], (
            f"{prop} drifted from feature reference: "
            f"{production_selector}={production[prop]!r}, "
            f"{feature_selector}={feature[prop]!r}"
        )


def test_first_paint_loader_matches_feature_prototype_contract() -> None:
    feature_loader = _declarations(FEATURE_CSS, ".app-bootstrap-loader")
    production_loader = _declarations(PRODUCTION_TOKENS, ".app-bootstrap-loader")
    for prop in ("position", "inset", "z-index", "display", "place-items", "opacity", "visibility"):
        assert production_loader.get(prop) == feature_loader.get(prop), (prop, feature_loader, production_loader)

    feature_card = _declarations(FEATURE_CSS, ".app-bootstrap-card")
    production_card = _declarations(PRODUCTION_TOKENS, ".app-bootstrap-card")
    for prop in ("display", "grid-template-columns", "gap", "align-items", "min-width", "padding", "border-radius"):
        assert production_card.get(prop) == feature_card.get(prop), (prop, feature_card, production_card)

    feature_spinner = _declarations(FEATURE_CSS, ".app-bootstrap-spinner")
    production_spinner = _declarations(PRODUCTION_TOKENS, ".app-bootstrap-spinner")
    for prop in ("width", "height", "border-radius", "animation"):
        assert production_spinner.get(prop) == feature_spinner.get(prop), (prop, feature_spinner, production_spinner)

    assert 'id="appBootstrapLoader"' in PRODUCTION_HTML
    assert 'class="app-bootstrap-spinner"' in PRODUCTION_HTML
    assert 'root.classList.add("ui-booting")' in PRODUCTION_BOOTSTRAP
    assert 'root.classList.add("ui-ready")' in PRODUCTION_BOOTSTRAP
    assert 'window.setTimeout(finish, 1800)' in PRODUCTION_BOOTSTRAP
    assert 'window.UiBootstrap?.finish?.()' in PRODUCTION_APP




def test_first_paint_language_is_persisted_before_loader_reveal() -> None:
    assert 'const LANGUAGE_KEY = "ai-task-runner.ui.language.v1"' in PRODUCTION_BOOTSTRAP
    assert 'root.lang = bootstrapLanguage === "en" ? "en" : "zh-Hant"' in PRODUCTION_BOOTSTRAP
    i18n = (ROOT / "ui" / "static" / "js" / "i18n.js").read_text(encoding="utf-8")
    assert 'localStorage.setItem(LANGUAGE_KEY, language)' in i18n
    assert 'data-bootstrap-language="zh-TW"' in PRODUCTION_HTML
    assert 'data-bootstrap-language="en"' in PRODUCTION_HTML

def test_new_task_editor_base_geometry_matches_final_feature_cascade() -> None:
    _same(
        "#newTaskModal>.modal-body",
        ".task-workspace-shell.task-editor-route .task-workspace-body",
        ("padding",),
    )
    _same(
        "#newTaskModal .task-basics",
        ".task-workspace-basics",
        ("grid-template-columns", "gap"),
    )
    _same(
        "#newTaskModal .task-input-grid",
        ".task-workspace-input-grid",
        ("grid-template-columns", "gap", "margin-top"),
    )
    _same(
        "#newTaskModal .task-editor-secondary .workspace-option",
        ".task-workspace-editor-secondary .task-workspace-workspace-option",
        ("min-height", "padding"),
    )
    _same(
        "#newTaskModal>.modal-foot",
        ".task-workspace-shell.task-editor-route .task-workspace-foot",
        ("padding",),
    )
    _same(
        ".drawer.workspace-route",
        ".task-workspace-shell.workspace-route",
        ("width", "max-width"),
    )


def test_new_task_source_cards_match_final_feature_cascade() -> None:
    _same(
        ".source-card",
        ".task-workspace-source-card",
        ("border", "border-radius", "background", "overflow"),
    )
    _same(
        ".source-head",
        ".task-workspace-source-head",
        ("padding", "border-bottom", "background"),
    )
    _same(
        ".source-body",
        ".task-workspace-source-body",
        ("padding",),
    )
    # New Task-specific geometry overrides the generic .source-tabs values.
    _same(
        "#newTaskModal .task-primary-source .source-tabs",
        ".task-workspace-source-tabs",
        ("gap", "height"),
    )
    _same(
        "#newTaskModal .task-primary-source .source-tabs button",
        ".task-workspace-source-tabs button",
        ("height", "padding"),
    )
    _same(
        ".source-tabs button",
        ".task-workspace-source-tabs button",
        ("font-size",),
    )
    _same(
        "#newTaskModal .task-primary-source .task-source-mode-panel>textarea",
        ".task-workspace-task-primary-source textarea",
        ("min-height",),
    )
    _same(
        "#newTaskModal .task-ai-source .task-source-mode-panel>textarea",
        ".task-workspace-task-ai-source textarea",
        ("min-height",),
    )
    _same(
        ".workspace-selector-wrap",
        ".task-workspace-workspace-selector",
        ("margin-top", "padding", "border-radius", "background"),
    )
    _same(
        ".workspace-option",
        ".task-workspace-workspace-option",
        ("border-radius", "background"),
    )




def test_new_task_source_mode_typography_and_motion_match_feature_reference() -> None:
    _same(
        "#newTaskModal .task-source-mode-panel",
        ".task-workspace-source-mode-panel",
        ("width", "min-width", "box-sizing", "display", "flex-direction", "gap"),
    )
    _same(
        ".validation-stack",
        ".task-workspace-validation-stack",
        ("display", "grid-template-columns"),
    )
    _same(
        "#newTaskModal .task-input-grid:has(#newTaskValidationSource .validation-stack .source-card:nth-child(2)) #newTaskValidationSource .source-card",
        ".task-workspace-input-grid.has-mixed-validation .task-workspace-validation-stack>.task-workspace-source-card",
        ("height",),
    )
    _same(
        "#newTaskModal .task-input-grid:has(#newTaskValidationSource .validation-stack .source-card:nth-child(2)) .task-file-source>.source-head",
        ".task-workspace-input-grid.has-mixed-validation .task-workspace-task-file-source>.task-workspace-source-head",
        ("grid-template-rows",),
    )
    _same(
        "#newTaskModal .task-input-grid:has(#newTaskValidationSource .validation-stack .source-card:nth-child(2)) .task-file-source>.source-head>div:first-child",
        ".task-workspace-input-grid.has-mixed-validation .task-workspace-task-file-source>.task-workspace-source-head>div:first-child",
        ("min-height",),
    )
    _same(
        "#newTaskModal .task-input-grid:has(#newTaskValidationSource .validation-stack .source-card:nth-child(2)) .task-primary-source",
        ".task-workspace-input-grid.has-mixed-validation .task-workspace-task-primary-source",
        ("width",),
    )
    _same(
        "#newTaskModal .task-primary-source .source-tabs",
        ".task-workspace-source-tabs",
        ("display", "width", "min-width", "box-sizing"),
    )
    _same(
        ".source-head small",
        ".task-workspace-source-head small",
        ("margin-left", "font-size"),
    )
    _same(
        ".field input",
        ".task-workspace-basics .task-workspace-field input",
        ("font-size",),
    )
    _same(
        ".source-body textarea",
        ".task-workspace-shell.task-editor-route .task-workspace-source-body textarea",
        ("padding", "resize"),
    )
    _same(
        "#newTaskModal .task-primary-source>.source-body",
        ".task-workspace-task-primary-source>.task-workspace-source-body",
        ("display", "min-width"),
    )
    _same(
        "#newTaskModal .source-note",
        ".task-workspace-shell.task-editor-route .task-workspace-source-note",
        ("min-height", "padding", "font-size", "line-height"),
    )
    _same(
        ".workspace-recommended",
        ".task-workspace-workspace-recommended",
        ("padding", "font-size", "font-weight"),
    )
    _same(
        ".workspace-preview",
        ".task-workspace-workspace-preview",
        ("background",),
    )
    _same(
        ".workspace-preview strong",
        ".task-workspace-workspace-preview strong",
        ("color",),
    )
    _same(
        ".drawer",
        ".task-workspace-shell",
        ("transform", "transition"),
    )
    _same(
        ".overlay.open .drawer",
        ".task-workspace-overlay.open .task-workspace-shell",
        ("transform",),
    )

def test_new_task_responsive_geometry_matches_feature_reference() -> None:
    _same(
        "#newTaskModal .task-basics",
        ".task-workspace-basics",
        ("grid-template-columns",),
        feature_media="max-width:820px",
        production_media="max-width:820px",
    )
    _same(
        "#newTaskModal .task-title-field",
        ".task-workspace-title-field",
        ("grid-column",),
        feature_media="max-width:820px",
        production_media="max-width:820px",
    )
    _same(
        "#newTaskModal .task-input-grid",
        ".task-workspace-input-grid",
        ("grid-template-columns",),
        feature_media="max-width:820px",
        production_media="max-width:820px",
    )
    _same(
        ".workspace-options",
        ".task-workspace-workspace-options",
        ("grid-template-columns",),
        feature_media="max-width:900px",
        production_media="max-width:900px",
    )
    _same(
        ".workspace-option",
        ".task-workspace-workspace-option",
        ("min-height",),
        feature_media="max-width:900px",
        production_media="max-width:900px",
    )
    _same(
        "#newTaskModal .task-basics",
        ".task-workspace-basics",
        ("grid-template-columns",),
        feature_media="max-width:620px",
        production_media="max-width:620px",
    )
    _same(
        "#newTaskModal .task-input-grid:has(#newTaskValidationSource .validation-stack .source-card:nth-child(2)) #newTaskValidationSource .validation-stack",
        ".task-workspace-input-grid.has-mixed-validation .task-workspace-validation-stack",
        ("grid-template-columns",),
        feature_media="max-width:620px",
        production_media="max-width:620px",
    )


def test_new_task_runtime_structure_matches_final_feature_override() -> None:
    # task-editor.js intentionally reassigns renderNewTaskSources. The last
    # assignment is canonical: Prompt=3 tabs, AI=4 tabs, File Validator=Required.
    feature_final = FEATURE_EDITOR_JS[FEATURE_EDITOR_JS.rfind("renderNewTaskSources=function") :]
    assert "sourceTabs(newTaskDraft.goalMode,[['inline','Write'],['file','File'],['asset','Asset']]" in feature_final
    assert "sourceTabs(newTaskDraft.aiMode,[['default','Default'],['inline','Write'],['file','File'],['asset','Asset']]" in feature_final
    assert "title:'File Validator'" in feature_final
    assert "control:'<span class=\"cap-chip\">Required</span>'" in feature_final

    assert '[["write", tr("task.source_write", "Write")], ["file", tr("task.source_file", "File")], ["asset", tr("task.source_asset", "Asset")]]' in PRODUCTION_JS
    assert '[["default", tr("task.source_default", "Default")], ["write", tr("task.source_write", "Write")], ["file", tr("task.source_file", "File")], ["asset", tr("task.source_asset", "Asset")]]' in PRODUCTION_JS
    assert 'required.textContent = "Required"' in PRODUCTION_JS
    assert 'grid.append(projectField, workflowField, titleField)' in PRODUCTION_JS
    assert 'grid.append(workflowField);\n    body.appendChild(grid);' not in PRODUCTION_JS
    assert 'className = "task-workspace-source-mode-panel"' in PRODUCTION_JS
    assert 'prompt.rows = 10' not in PRODUCTION_JS
    assert 'textarea.rows = 6' not in PRODUCTION_JS
    assert 'overlay.classList.add("open")' in PRODUCTION_JS
    assert 'overlay.classList.remove("open")' in PRODUCTION_JS
    assert 'workspaceCloseTimer' not in PRODUCTION_JS
    assert 'overlay.hidden = true' in PRODUCTION_JS
    assert 'if (now - createMenuOpenedAt < 80) return' in PRODUCTION_JS
    assert 'render();\n        void loadWorkspaceOptions();\n        return;' in PRODUCTION_JS
    assert 'body.appendChild(inputGrid)' in PRODUCTION_JS
    assert 'body.appendChild(workspaceSection)' in PRODUCTION_JS






def test_chat_mode_geometry_matches_feature_reference() -> None:
    production_chat_css = (ROOT / "ui" / "static" / "css" / "project-chat.css").read_text(encoding="utf-8")
    feature = _declarations(FEATURE_CSS, ".composer-mode-quick")
    production = _declarations(production_chat_css, ".project-chat-mode-quick")
    for prop in (
        "display", "align-items", "gap", "height", "padding", "border",
        "border-radius", "background", "color", "font-size", "font-weight",
        "letter-spacing", "text-transform",
    ):
        assert production.get(prop) == feature.get(prop), (prop, feature, production)

    feature_select = _declarations(FEATURE_CSS, ".composer-mode-quick select")
    production_select = _declarations(production_chat_css, ".project-chat-mode-quick select")
    for prop in (
        "min-width", "height", "padding", "border", "background", "color",
        "font-size", "font-weight", "text-transform", "letter-spacing", "outline",
    ):
        assert production_select.get(prop) == feature_select.get(prop), (prop, feature_select, production_select)


def test_chat_quick_mode_matches_prototype_single_mode_control() -> None:
    project_chat = (ROOT / "ui" / "static" / "js" / "project-chat.js").read_text(encoding="utf-8")
    assert '{ includeEmpty: false, preserveSaved: true }' in project_chat
    assert 'savedMode,\n      "Mode",' not in project_chat


def test_new_task_list_child_back_is_owned_by_parent_route() -> None:
    assert 'state.editorReturn = "list";' in PRODUCTION_JS
    assert 'state.route === "editor" && state.editorReturn === "list"' in PRODUCTION_JS
    assert 'state.draft.items.length > 1' not in PRODUCTION_JS[PRODUCTION_JS.find("async function handleBack"):PRODUCTION_JS.find("function validateSelectedSourceModes")]



def test_task_workspace_dynamic_copy_is_language_owned() -> None:
    i18n = (ROOT / "ui" / "static" / "js" / "i18n.js").read_text(encoding="utf-8")
    for key in (
        "task.project_placeholder",
        "task.workspace_recommended",
        "task.prompt_placeholder",
        "task.quick_use_drag",
        "task.move_existing",
        "task.workspace_result",
    ):
        assert f'"{key}"' in i18n
        assert f'tr("{key}"' in PRODUCTION_JS or f'trf("{key}"' in PRODUCTION_JS

    assert "syncCreateMenuCopy();" in PRODUCTION_JS
    assert 'project.placeholder = "Select a project or type a path"' not in PRODUCTION_JS
    assert 'workspaceRecommended.textContent = "Auto recommended"' not in PRODUCTION_JS
    assert 'prompt.placeholder = "Describe what this task should do…"' not in PRODUCTION_JS



def test_every_task_list_to_editor_path_preserves_list_return_route() -> None:
    edit_item = PRODUCTION_JS[PRODUCTION_JS.find("function editItem"):PRODUCTION_JS.find("function taskMutationBlockedReason")]
    assert 'state.editorReturn = "list";' in edit_item

    mapping = PRODUCTION_JS[PRODUCTION_JS.find("function mapFieldError"):PRODUCTION_JS.find("function syncSingleEditorTitle")]
    assert 'state.editorReturn = "list";' in mapping

    validation = PRODUCTION_JS[PRODUCTION_JS.find("function validateSelectedSourceModes"):PRODUCTION_JS.find("async function saveWorkspace")]
    assert 'state.editorReturn = "list";' in validation

def test_task_workspace_shell_and_header_actions_match_feature_reference() -> None:
    _same(
        ".drawer-back",
        ".task-workspace-back",
        ("width", "height", "border-radius", "font-size"),
    )
    _same(
        ".drawer-shell-actions .btn",
        ".task-workspace-header-actions button",
        ("height", "min-height", "padding", "font-size"),
    )


def test_new_task_list_geometry_matches_feature_reference() -> None:
    _same(
        ".plan-page-body",
        ".task-workspace-list-page",
        ("grid-template-columns", "gap", "padding"),
    )
    _same(
        ".plan-main",
        ".task-workspace-list-main",
        ("padding", "border-radius"),
    )
    _same(
        ".plan-side",
        ".task-workspace-list-side",
        ("display", "gap", "align-content"),
    )
    _same(
        ".plan-side-card",
        ".task-workspace-list-side-card",
        ("padding", "border-radius", "background"),
    )
    _same(
        ".plan-add-task-footer",
        ".task-workspace-add-task-footer",
        ("width", "min-height", "gap", "margin-top", "border-radius", "font-size"),
    )
    _same(
        ".plan-row-compact[draggable=\"true\"]",
        ".task-workspace-list-row[draggable=\"true\"]",
        ("cursor",),
    )
    _same(
        ".draft-plan-row",
        ".task-workspace-list-row[draggable=\"true\"]",
        ("transition",),
    )
    _same(
        ".plan-row-compact.dragging",
        ".task-workspace-list-row.dragging",
        ("opacity",),
    )
    _same(
        ".plan-row-compact.drag-over",
        ".task-workspace-list-row.drag-over",
        ("outline", "outline-offset"),
    )
    _same(
        ".plan-row-head>.drag-grip",
        ".task-workspace-drag-grip",
        ("width", "height", "font-size"),
    )
    _same(
        ".plan-workspace-chip",
        ".task-workspace-list-chip",
        ("font-size", "font-weight"),
    )
    _same(
        ".plan-page-body",
        ".task-workspace-list-page",
        ("grid-template-columns",),
        feature_media="max-width:960px",
        production_media="max-width:960px",
    )
    _same(
        ".plan-side",
        ".task-workspace-list-side",
        ("grid-template-columns",),
        feature_media="max-width:960px",
        production_media="max-width:960px",
    )


def test_task_list_action_ownership_matches_prototype_html() -> None:
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

    assert "Task order" in FEATURE_TEMPLATES
    assert "Right-click or <strong>⋯</strong> for Info / Workflow / Remove." in FEATURE_TEMPLATES
    assert 'className = "task-workspace-list-tools-wrap"' in PRODUCTION_JS
    assert 'wrap.hidden = true' in PRODUCTION_JS
    assert 'tools.appendChild(move)' not in PRODUCTION_JS
    assert 'tools.appendChild(yaml)' not in PRODUCTION_JS
