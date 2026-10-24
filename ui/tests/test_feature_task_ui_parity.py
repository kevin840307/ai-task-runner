from __future__ import annotations

from pathlib import Path

from tool.compare_feature_ui import compare_panel, declarations as _declarations


ROOT = Path(__file__).resolve().parents[2]
FEATURE_CSS = (ROOT / "feature" / "ui-prototype" / "styles.css").read_text(encoding="utf-8")
FEATURE_EDITOR_JS = (ROOT / "feature" / "ui-prototype" / "task-editor.js").read_text(encoding="utf-8")
FEATURE_WORKSPACE_JS = (ROOT / "feature" / "ui-prototype" / "task-workspace.js").read_text(encoding="utf-8")
FEATURE_TASKS_PAGE_JS = (ROOT / "feature" / "ui-prototype" / "tasks-page.js").read_text(encoding="utf-8")
FEATURE_TEMPLATES = (ROOT / "feature" / "ui-prototype" / "task-ui-templates.js").read_text(encoding="utf-8")
PROTOTYPE_HTML = (ROOT / "feature" / "ai-task-runner-ui-prototype.html").read_text(encoding="utf-8")
PRODUCTION_CSS = (ROOT / "ui" / "static" / "css" / "task-workspace.css").read_text(encoding="utf-8")
PRODUCTION_THEME = (ROOT / "ui" / "static" / "css" / "theme.css").read_text(encoding="utf-8")
PRODUCTION_JS = (ROOT / "ui" / "static" / "js" / "task-workspace.js").read_text(encoding="utf-8")
PRODUCTION_TASKS_BOARD_JS = (ROOT / "ui" / "static" / "js" / "tasks-board.js").read_text(encoding="utf-8")
PRODUCTION_TOKENS = (ROOT / "ui" / "static" / "css" / "tokens.css").read_text(encoding="utf-8")
PRODUCTION_BOOTSTRAP = (ROOT / "ui" / "static" / "js" / "ui-bootstrap.js").read_text(encoding="utf-8")
PRODUCTION_APP = (ROOT / "ui" / "static" / "app.js").read_text(encoding="utf-8")
PRODUCTION_HTML = (ROOT / "ui" / "static" / "index.html").read_text(encoding="utf-8")



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



def test_task_panels_have_no_prototype_geometry_or_motion_drift() -> None:
    drift = []
    for panel in ("task-editor", "task-list", "board"):
        drift.extend(compare_panel(panel, root=ROOT))
    assert drift == [], "\n".join(drift)




def test_task_list_selection_never_coerces_null_to_first_row() -> None:
    # null means no row selected. JavaScript Number(null) is 0, so selection
    # lookups must guard the index before reading items[].
    assert "items[Number(state.selectedListIndex)]" not in PRODUCTION_JS
    assert "Number(state?.selectedListIndex) === index" not in PRODUCTION_JS
    assert "Number(state?.listInfoIndex)" not in PRODUCTION_JS
    assert "Number.isInteger(state.selectedListIndex) ? items[state.selectedListIndex] : null" in PRODUCTION_JS
    assert "Number.isInteger(state?.selectedListIndex) && state.selectedListIndex === index" in PRODUCTION_JS
    assert "const index = state?.listInfoIndex;" in PRODUCTION_JS
def test_task_click_routing_reorder_and_popover_bounds_match_feature_contract() -> None:
    # Tasks Board/List owns the New -> Task List shortcut. Generic openTask
    # remains Info-first so create-from-draft and other entry points do not drift.
    assert "if(t.status==='new'){openPlanDialog(t.id);return}" in FEATURE_TASKS_PAGE_JS
    assert 'route: String(task?.status || "") === "new" ? "list" : "info"' in PRODUCTION_TASKS_BOARD_JS
    assert 'button.title = String(task?.status || "") === "new" ? "Open Task list" : "Open Task info"' in PRODUCTION_TASKS_BOARD_JS
    assert 'button.addEventListener("dblclick", () => openTask?.(task, {' in PRODUCTION_TASKS_BOARD_JS
    assert 'r.ondblclick=()=>openPlanDialog(r.dataset.taskrow)' in FEATURE_WORKSPACE_JS
    assert "card.oncontextmenu=e=>" in FEATURE_WORKSPACE_JS
    assert "r.oncontextmenu=e=>" in FEATURE_WORKSPACE_JS
    assert PRODUCTION_TASKS_BOARD_JS.count('button.addEventListener("contextmenu"') == 2
    for label in ("Open list", "Rename", "Info", "Delete"):
        assert label in PRODUCTION_TASKS_BOARD_JS
    assert 'function openTask(task, { returnFocus, workflows = [], prompts = [], route = "info" } = {})' in PRODUCTION_JS

    # Task List Draft retains all three reorder paths from the accepted
    # prototype: explicit arrows, drag/drop, and Alt+Arrow keyboard movement.
    assert 'data-draft-up="' in FEATURE_EDITOR_JS
    assert 'data-draft-down="' in FEATURE_EDITOR_JS
    assert 'task-workspace-row-up' in PRODUCTION_JS
    assert 'task-workspace-row-down' in PRODUCTION_JS
    assert 'event.altKey && event.key === "ArrowUp"' in PRODUCTION_JS
    assert 'event.altKey && event.key === "ArrowDown"' in PRODUCTION_JS

    # Popover edge placement uses the same reserved geometry as the prototype,
    # rather than varying with transient DOM-measured content height.
    assert "const r=anchor.getBoundingClientRect(),w=250,gap=6;" in FEATURE_EDITOR_JS
    assert "if(top+112>window.innerHeight)" in FEATURE_EDITOR_JS
    assert "const width = 250;" in PRODUCTION_JS
    assert "const height = 112;" in PRODUCTION_JS
    assert "const w=205,h=220;" in FEATURE_WORKSPACE_JS
    assert "const width = 205;" in PRODUCTION_JS
    assert "const height = 220;" in PRODUCTION_JS

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
        ".field",
        ".task-workspace-basics>.task-workspace-field",
        ("margin-top",),
    )
    _same(
        "#newTaskModal .task-basics label",
        ".task-workspace-basics .task-workspace-field>span",
        ("margin-bottom",),
    )
    _same(
        ".field label",
        ".task-workspace-basics .task-workspace-field>span",
        ("font-size", "font-weight", "text-transform", "letter-spacing"),
    )
    _same(
        ".field input",
        ".task-workspace-basics .task-workspace-field input",
        ("padding",),
    )
    _same(
        ".field select",
        ".task-workspace-basics .task-workspace-field select",
        ("padding",),
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


def test_task_upload_theme_override_preserves_feature_accent_cascade() -> None:
    feature = _declarations(FEATURE_CSS, "#newTaskModal .task-upload-btn")
    production = _declarations(
        PRODUCTION_THEME,
        "html[data-appearance] .task-workspace-shell.task-editor-route .task-workspace-upload",
    )
    for prop in ("border-color", "background", "color"):
        assert production.get(prop) == feature.get(prop), (
            prop,
            feature,
            production,
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
        ("padding", "border-bottom", "background", "margin-bottom"),
    )
    _same(
        ".source-body",
        ".task-workspace-source-body",
        ("padding", "gap"),
    )
    # New Task-specific geometry overrides the generic .source-tabs values.
    _same(
        "#newTaskModal .task-primary-source .source-tabs",
        ".task-workspace-task-primary-source .task-workspace-source-tabs",
        ("display", "grid-template-columns", "gap", "height"),
    )
    _same(
        "#newTaskModal .task-primary-source .source-tabs button",
        ".task-workspace-task-primary-source .task-workspace-source-tabs button",
        ("width", "min-width", "height", "padding", "white-space", "overflow", "text-overflow"),
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
        ".pathrow input",
        ".task-workspace-path-row input",
        ("width", "height", "padding", "border", "border-radius", "background", "color", "font-size"),
    )
    _same(
        "#newTaskModal .task-upload-btn",
        ".task-workspace-upload",
        ("border-color", "background", "color"),
    )
    _same(
        ".mini-btn",
        ".task-workspace-upload",
        ("height", "padding", "border-radius", "font-size", "font-weight"),
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
        ".task-workspace-task-primary-source .task-workspace-source-tabs",
        ("display", "width", "min-width", "box-sizing", "grid-template-columns"),
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
        "#newTaskModal .task-ai-source .source-tabs",
        ".task-workspace-task-ai-source .task-workspace-source-tabs",
        ("display", "width", "min-width", "gap", "box-sizing", "grid-template-columns", "height"),
    )
    _same(
        "#newTaskModal .task-ai-source .source-tabs button",
        ".task-workspace-task-ai-source .task-workspace-source-tabs button",
        ("width", "min-width", "height", "padding", "white-space", "overflow", "text-overflow"),
    )
    _same(
        "#newTaskModal .source-note",
        ".task-workspace-shell.task-editor-route .task-workspace-source-note",
        ("padding", "font-size", "line-height"),
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
    assert 'required.textContent = tr("task.required", "Required")' in PRODUCTION_JS
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








def test_reasoning_selector_keeps_feature_five_level_contract() -> None:
    feature_task_editor = (ROOT / "feature" / "ui-prototype" / "task-editor.js").read_text(encoding="utf-8")
    assert "const PROJECT_REASONING_LEVELS=Object.freeze(['low','medium','high','xhigh','max'])" in feature_task_editor
    project_chat = (ROOT / "ui" / "static" / "js" / "project-chat.js").read_text(encoding="utf-8")
    assert 'const FEATURE_REASONING_LEVELS = ["low", "medium", "high", "xhigh", "max"];' in project_chat
    assert 'includeEmpty: selectedAgentForReasoning !== "qwen"' in project_chat
    app = (ROOT / "ui" / "static" / "app.js").read_text(encoding="utf-8")
    assert 'const featureReasoningLevels = ["low", "medium", "high", "xhigh", "max"];' in app


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
    assert "function isNewTaskListChildEditor()" in PRODUCTION_JS
    back = PRODUCTION_JS[PRODUCTION_JS.find("async function handleBack"):PRODUCTION_JS.find("function validateSelectedSourceModes")]
    assert "if (isNewTaskListChildEditor())" in back
    assert "restoreNewTaskListChildBaseline();" in back
    assert "Discard Task changes?" in back


def test_new_task_list_child_save_matches_prototype_action_ownership() -> None:
    assert "const taskEditorSaveBeforeOverlay=document.getElementById('createTaskConfirm').onclick;" in FEATURE_WORKSPACE_JS
    assert "if(draftSaved||itemSaved){taskEditorInitialSnapshot='';leaveTaskEditorOverlay({force:true})}" in FEATURE_WORKSPACE_JS
    assert "if (isNewTaskListChildEditor()) return saveNewTaskListChild();" in PRODUCTION_JS
    child_save = PRODUCTION_JS[PRODUCTION_JS.find("async function saveNewTaskListChild"):PRODUCTION_JS.find("async function saveDraft")]
    assert 'api("/api/tasks/validate-draft"' in child_save
    assert 'api("/api/tasks/create"' not in child_save
    assert 'tr("task.create_child", "Create task")' in PRODUCTION_JS
    assert 'tr("task.save_changes", "Save changes")' in PRODUCTION_JS
    assert 'tr("task.back_list_draft", "Back to Task List Draft")' in PRODUCTION_JS



def test_new_task_list_initial_focus_matches_feature_reference() -> None:
    assert "taskListDraftTitle');input?.focus();input?.select()" in FEATURE_EDITOR_JS
    assert 'const title = byId("taskWorkspaceDraftTitle");' in PRODUCTION_JS
    assert 'title.focus({ preventScroll: true });' in PRODUCTION_JS
    assert 'title.select?.();' in PRODUCTION_JS
    assert "function renderPreservingActiveControl()" in PRODUCTION_JS
    assert PRODUCTION_JS.count("renderPreservingActiveControl();") >= 2


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
        "#planModal .plan-page-body",
        ".task-workspace-list-page",
        ("min-height", "height", "overflow"),
    )
    _same(
        ".plan-main",
        ".task-workspace-list-main",
        ("padding", "border-radius"),
    )
    _same(
        "#planModal .plan-main",
        ".task-workspace-list-main",
        ("min-height", "overflow"),
    )
    _same(
        ".plan-side",
        ".task-workspace-list-side",
        ("display", "gap", "align-content"),
    )
    _same(
        "#planModal .plan-side",
        ".task-workspace-list-side",
        ("min-height", "overflow"),
    )
    _same(
        ".plan-side-card",
        ".task-workspace-list-side-card",
        ("padding", "border-radius", "background"),
    )
    _same(
        "#planModal .plan-side-card.info-active",
        ".task-workspace-list-side-card.info-active",
        ("border-color", "background"),
    )
    _same(
        "#planModal .plan-side-card.info-active h3",
        ".task-workspace-list-side-card.info-active h3",
        ("color",),
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
        ".plan-row-compact.current",
        ".task-workspace-list-row.current",
        ("border-color", "background"),
    )
    _same(
        ".plan-row-compact.done",
        ".task-workspace-list-row.done",
        ("opacity",),
    )
    _same(
        "html[data-appearance] #planModal .plan-row-compact.current",
        "html[data-appearance] .task-workspace-list-row.current",
        ("background", "border-color"),
    )
    _same(
        "html[data-appearance] #planModal .plan-row-compact.selected",
        "html[data-appearance] .task-workspace-list-row.selected",
        ("background", "border-color"),
    )
    _same(
        ".plan-row-head>.drag-grip",
        ".task-workspace-drag-grip",
        ("width", "height", "margin", "color", "font-size", "font-weight", "line-height", "cursor", "user-select"),
    )
    _same(
        ".plan-workspace-chip",
        ".task-workspace-list-chip",
        ("padding", "border-radius", "background", "color", "font-size", "font-weight"),
    )
    _same(
        ".plan-workspace-chip.worktree",
        ".task-workspace-list-chip.worktree",
        ("background", "color", "border", "font-weight", "letter-spacing"),
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
    _same(
        ".plan-page-body",
        ".task-workspace-list-page",
        ("grid-template-columns",),
        feature_media="max-width:900px",
        production_media="max-width:900px",
    )
    _same(
        ".plan-side",
        ".task-workspace-list-side",
        ("display",),
        feature_media="max-width:900px",
        production_media="max-width:900px",
    )


def test_new_task_editor_source_note_chrome_matches_feature_reference() -> None:
    _same(
        ".source-note",
        ".task-workspace-shell.task-editor-route .task-workspace-source-note",
        ("border-radius", "background"),
    )
    _same(
        "#newTaskModal .source-note",
        ".task-workspace-shell.task-editor-route .task-workspace-source-note",
        ("padding", "font-size", "line-height"),
    )


def test_new_task_staged_upload_hint_matches_feature_reference() -> None:
    _same(
        ".file-upload-hint",
        ".task-workspace-file-upload-hint",
        ("display", "align-items", "gap", "min-width", "border", "border-radius", "background", "font-size"),
    )
    _same(
        "#newTaskModal .file-upload-hint",
        ".task-workspace-shell.task-editor-route .task-workspace-file-upload-hint",
        ("padding",),
    )
    _same(
        ".file-upload-hint strong",
        ".task-workspace-file-upload-hint strong",
        ("flex", "min-width", "overflow", "text-overflow", "white-space"),
    )
    _same(".file-upload-hint span", ".task-workspace-file-upload-hint span", ("color",))


def test_task_list_effective_row_geometry_matches_feature_reference() -> None:
    _same(
        ".plan-row-compact .plan-row-head",
        ".task-workspace-list-row:not(.task-workspace-info-row)",
        ("grid-template-columns", "column-gap", "align-items"),
    )
    _same(
        ".plan-row-num",
        ".task-workspace-list-number",
        ("width", "height", "margin", "display", "place-items", "line-height", "align-self"),
    )


def test_task_list_context_menu_matches_feature_reference() -> None:
    _same(
        ".task-context-menu",
        ".task-workspace-context-menu",
        ("position", "z-index", "width", "padding", "border", "border-radius", "background", "box-shadow"),
    )
    _same(".task-context-actions", ".task-workspace-context-actions", ("padding",))
    _same(
        ".task-context-menu button",
        ".task-workspace-context-menu button",
        ("display", "align-items", "justify-content", "width", "padding", "border", "border-radius", "background", "color", "font-size", "text-align", "cursor"),
    )
    _same(".task-context-menu button:disabled", ".task-workspace-context-menu button:disabled", ("opacity", "cursor"))
    _same(".task-context-menu .danger-item", ".task-workspace-context-menu .danger-item", ("color",))
    _same(".task-context-menu kbd", ".task-workspace-context-menu kbd", ("font", "color"))
    _same(".context-separator", ".task-workspace-context-separator", ("height", "margin", "background"))


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
