from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "ui" / "studio-src" / "src" / "main.tsx"


def test_react_studio_has_drag_palette_and_manual_result_edge_handles():
    text = SOURCE.read_text(encoding="utf-8")

    assert "Stage Palette" in text
    assert "workflowStudioUrl" in text
    assert 'view: "workflow", studio: id' in text
    assert 'back: "← Workflows"' in text
    assert "Workflow Editor" in text
    assert "history.back()" not in text
    assert "application/x-ai-stage" in text
    assert 'sourceHandle: "pass"' in text
    assert 'id="pass"' in text
    assert 'id="fail"' in text
    assert 'id="pass" style={{ left: "25%" }}' in text
    assert 'id="fail" style={{ left: "75%" }}' in text
    assert 'id="error"' not in text
    assert 'graph: graphDraft(nextVisual)' in text
    assert '"/api/studio/stage/add"' not in text  # Palette additions stay in the draft until Save.


def test_react_studio_connecting_any_result_edge_adds_disconnected_stages_to_flow():
    text = SOURCE.read_text(encoding="utf-8")

    assert "if (!nextFlow.includes(connection.source))" in text
    assert "if (connection.target !== END && !nextFlow.includes(connection.target))" in text
    assert 'if (status === "pass" || status === "handoff")' in text
    assert "A FAIL branch must not change the source Stage's implicit PASS -> next." in text
    assert "const index = nextFlow.indexOf(stage.name)" in text


def test_react_studio_has_real_stage_and_agent_ping_modes_with_backend_selection():
    text = SOURCE.read_text(encoding="utf-8")

    assert '"agent_ping"' in text
    assert "Real Stage" in text
    assert "Agent Ping" in text
    assert 'api<BackendCatalog>("/api/backends")' in text
    assert "probe_mode: testMode" in text
    assert "backend: testBackend" in text
    assert "AGENT_PING_PROMPT" in text
    assert "local -1 在測試中最多 retry 2 次" in text
    assert "test_retry_policy" in text
    assert "不使用工具、不讀專案、不修改檔案" in text


def test_react_studio_exposes_effective_prompt_instead_of_opaque_default():
    text = SOURCE.read_text(encoding="utf-8")

    assert "effectivePrompt" in text
    assert "Default —" in text
    assert "Effective:" in text
    assert 'defaultOption(catalog, stage.type, "prompt")' in text
    assert "common/execution.md" in text  # profile-first creation exposes the effective preset explicitly.


def test_workflow_builder_internal_prompts_are_not_user_assets():
    assert (ROOT / "workflow_builder" / "prompt.md").is_file()
    assert not (ROOT / "runner" / "assets" / "prompts" / "workflow" / "workflow_prompt.md").exists()
    assert not (ROOT / "runner" / "assets" / "prompts" / "workflow" / "workflow_review.md").exists()


def test_react_studio_exposes_common_stage_error_policy_controls():
    text = SOURCE.read_text(encoding="utf-8")

    assert "ERROR 重試次數" in text
    assert "Skip Review" in text
    assert "有限值耗盡後 Skip" in text
    assert "draft.error_policy?.retries" in text
    assert 'error_policy: { retries }' in text
    assert 'cleaned.error_policy || { retries: 2 }' in text
    assert 'max_failures: 3' in text
    assert "Semantic FAIL 上限（max_failures）" in text
    assert "FAIL×{Number(draft.max_failures)}" in text
    assert "下一次進入 Review 直接 PASS，不呼叫 Agent" in text
    assert 'id="error"' not in text  # ERROR is not a runtime result edge; it is only a Stage Test scenario.


def test_react_studio_has_searchable_palette_and_safe_stage_duplicate():
    text = SOURCE.read_text(encoding="utf-8")

    assert 'placeholder={tx("search_stage")}' in text
    assert "paletteQuery" in text
    assert "duplicateStage" in text
    assert "結果連線不會一起複製" in text


def test_full_designer_generated_output_has_one_source_and_build_path():
    vite = (ROOT / "ui" / "studio-src" / "vite.config.ts").read_text(encoding="utf-8")
    build_tool = (ROOT / "tool" / "build_workflow_studio.py").read_text(encoding="utf-8")
    guidelines = (ROOT / "DevFollow.txt").read_text(encoding="utf-8")

    assert '../static/workflow-studio-app' in vite
    assert 'npm", "run", "build"' in build_tool
    assert "ui/studio-src/**" in guidelines
    assert "ui/static/workflow-studio-app/**" in guidelines


def test_react_studio_keeps_stage_type_immutable_after_creation():
    text = SOURCE.read_text(encoding="utf-8")
    assert "類型（建立後固定；要更換請刪除後重新拖入）" in text
    assert '<select value={draft.type} disabled>' in text
    assert 'editDraft({ ...draft, type:' not in text


def test_react_studio_generic_inspector_keeps_unknown_catalog_options_editable():
    text = SOURCE.read_text(encoding="utf-8")
    assert 'section.id === "advanced"' in text
    assert "PARAMETER_SECTIONS.slice(0, -1)" in text
    assert "group.fields.includes(option.name)" in text


def test_react_source_tracks_session_policy_ui_contract():
    text = SOURCE.read_text(encoding="utf-8")
    assert "session_policy" in text
    assert '"fresh_session_each_run", "fresh_session_on_start"' not in text
    assert "session_key" in text


def test_react_studio_reuses_stage_nodes_for_dynamic_handoff_and_session_policy():
    text = SOURCE.read_text(encoding="utf-8")
    assert 'id="handoff"' in text
    assert '"discussion_controller"' not in text
    assert '"discussion"' not in text
    assert '"dispatch"' not in text
    assert "session_policy" in text
    assert '"fresh_session_each_run", "fresh_session_on_start"' not in text
    assert 'o.name === "session_key"' in text
    assert 'session_key: _sessionKey' in text
    assert "leaveStudio()" in text
    assert "requestConfirm" in text
    assert "autoPositions" in text
    assert "branchTargets" in text
    assert "branchColumnGap" in text
    assert "rowStartCenter" in text
    assert "cursorY" in text



def test_react_studio_keeps_canvas_cards_compact_for_editor_mode():
    text = SOURCE.read_text(encoding="utf-8")
    styles = (ROOT / "ui" / "studio-src" / "src" / "styles.css").read_text(encoding="utf-8")

    assert 'className="wf-stage-meta"' in text
    assert "未連線" in text
    assert "FAIL×{reviewMaxFailures} → 下次 Pass" in text
    assert "ERR×{errorRetries} → Skip" in text
    assert ".wf-stage.type-review, .wf-stage.type-ai_validator" in styles
    assert ".wf-stage-meta span" in styles


def test_react_studio_has_stage_specific_test_prompt_presets():
    text = SOURCE.read_text(encoding="utf-8")

    assert "STAGE_TEST_PROMPTS" in text
    assert "填入簡易測試 Prompt" in text
    assert "stageTestPrompt(draft, testScenario)" in text
    assert "只作用於本次 isolated Stage Test" in text
    assert "Stage Test API not found. Restart the local UI server" in text


def test_react_studio_opens_stage_settings_as_modal_on_double_click_and_shares_language():
    text = SOURCE.read_text(encoding="utf-8")
    styles = (ROOT / "ui" / "studio-src" / "src" / "styles.css").read_text(encoding="utf-8")

    assert "onNodeClick" in text
    assert "setSelected(n.id)" in text
    assert "onNodeDoubleClick" in text
    assert "openStageEditor(n.id)" in text
    assert "stage-editor-backdrop" in text
    assert "stage-editor-modal" in text
    assert "editorOpen" in text
    assert 'event.key === "Escape"' in text
    assert 'DESIGNER_LANGUAGE_KEY = "ai-task-runner.language"' in text
    assert '"zh-TW"' in text and '"en"' in text
    assert "changeLanguage" not in text
    assert "grid-template-columns: 220px minmax(0,1fr)" in styles


def test_stage_editor_has_fixed_height_and_compact_quick_add_palette():
    text = SOURCE.read_text(encoding="utf-8")
    styles = (ROOT / "ui" / "studio-src" / "src" / "styles.css").read_text(encoding="utf-8")

    assert 'className="stage-editor-content"' in text
    assert 'className="palette-quick-add"' in text
    assert "void addStage(type)" in text
    assert "title={meta.description}" in text
    assert "block-size: min(680px, calc(100dvh - 56px))" in styles
    assert "grid-template-rows: auto auto minmax(0,1fr) auto" in styles
    assert ".stage-editor-content { min-width: 0; min-height: 0; height: 100%; overflow: auto;" in styles
    assert ".palette-quick-add" in styles


def test_node_library_scales_with_favorites_recent_and_extensions():
    text = SOURCE.read_text(encoding="utf-8")
    styles = (ROOT / "ui" / "studio-src" / "src" / "styles.css").read_text(encoding="utf-8")

    assert 'PALETTE_PREF_KEY = "workflow-designer.palette:v1"' in text
    assert "favorites" in text
    assert "recent" in text
    assert "extensions" in text
    assert "toggleFavoriteStage" in text
    assert "togglePaletteSection" in text
    assert "rememberPaletteStage" in text
    assert "knownTypes" in text
    assert "catalogStageMeta" in text
    assert "catalogMeta?.category" in text
    assert 'palette-favorite' in text
    assert 'className="palette-section-head"' in text
    assert "palettePrefs.collapsed" in text
    assert ".palette-favorite.active" in styles
    assert ".palette-section-head:hover" in styles


def test_designer_shortcuts_context_menu_and_command_add_are_workflow_aware():
    text = SOURCE.read_text(encoding="utf-8")
    styles = (ROOT / "ui" / "studio-src" / "src" / "styles.css").read_text(encoding="utf-8")

    assert 'deleteKeyCode={null}' in text
    assert 'event.key.toLowerCase() === "c"' in text
    assert 'event.key.toLowerCase() === "v"' in text
    assert 'event.key === "Delete" || event.key === "Backspace"' in text
    assert "copyStageByName" in text
    assert "pasteStage" in text
    assert "deleteStage(selected)" in text
    assert "onNodeContextMenu" in text
    assert 'className="stage-context-menu"' in text
    assert "contextMenu.stage" in text
    assert 'className="add-stage-command-backdrop"' in text
    assert 'className="palette-command-add"' in text
    assert "addStageQuery" in text
    assert ".stage-context-menu" in styles
    assert ".add-stage-command" in styles


def test_stage_test_has_pass_fail_error_retry_prompt_scenarios():
    text = SOURCE.read_text(encoding="utf-8")
    styles = (ROOT / "ui" / "studio-src" / "src" / "styles.css").read_text(encoding="utf-8")

    assert 'type StageTestScenario = "pass" | "fail" | "error"' in text
    assert 'testScenario' in text
    assert 'test_error: "ERROR / Retry"' in text
    assert 'stageTestPrompt(draft, scenario)' in text
    assert '"error_mock"' in text
    assert "Technical ERROR is injected by the Stage Test harness" in text
    assert 'className="test-scenario-tabs"' in text
    assert ".scenario-error.active" in styles


def test_stage_editor_dialog_height_is_hard_locked_across_tabs():
    styles = (ROOT / "ui" / "studio-src" / "src" / "styles.css").read_text(encoding="utf-8")

    assert "block-size: min(680px, calc(100dvh - 56px))" in styles
    assert "min-block-size: min(680px, calc(100dvh - 56px))" in styles
    assert "max-block-size: min(680px, calc(100dvh - 56px))" in styles
    assert "grid-template-rows: auto auto minmax(0,1fr) auto" in styles
    assert ".stage-editor-content { min-width: 0; min-height: 0; height: 100%; overflow: auto;" in styles
    assert ".inspector footer { margin:" in styles
    assert "position: sticky" not in styles.split(".inspector footer", 1)[1].split("}", 1)[0]


def test_designer_reuses_interface_language_and_has_fixed_add_stage_width():
    text = SOURCE.read_text(encoding="utf-8")
    styles = (ROOT / "ui" / "studio-src" / "src" / "styles.css").read_text(encoding="utf-8")

    assert 'DESIGNER_LANGUAGE_KEY = "ai-task-runner.language"' in text
    assert "changeLanguage" not in text
    assert 'className="language-picker"' not in text
    assert 'event.key !== DESIGNER_LANGUAGE_KEY' in text
    assert 'palette-chevron' in text
    assert '{collapsed ? "›" : "⌄"}' not in text
    assert "grid-template-columns: 220px minmax(0,1fr)" in styles
    assert "width: 220px; min-width: 220px; max-width: 220px" in styles
    assert "width: 520px; max-width: calc(100vw - 32px)" in styles
    assert ".palette-chevron.collapsed" in styles


def test_designer_uses_shared_confirmation_dialog_and_thin_visible_scrollbars():
    text = SOURCE.read_text(encoding="utf-8")
    styles = (ROOT / "ui" / "studio-src" / "src" / "styles.css").read_text(encoding="utf-8")

    assert "window.confirm" not in text
    assert "DesignerConfirmDialog" in text
    assert "requestConfirm" in text
    assert 'className="designer-confirm-backdrop"' in text
    assert "捨棄未儲存變更？" in text
    assert "重新載入 Workflow？" in text
    assert "移除 Stage" in text
    assert ".designer-confirm-dialog" in styles
    assert "overflow-y: scroll" in styles
    assert "scrollbar-width: thin" in styles
    assert ".add-stage-command-list::-webkit-scrollbar { width: 6px; }" in styles
    assert ".palette::-webkit-scrollbar { width: 6px; }" in styles


def test_workflow_editor_converges_designer_and_yaml_on_one_canonical_file():
    text = SOURCE.read_text(encoding="utf-8")
    styles = (ROOT / "ui" / "studio-src" / "src" / "styles.css").read_text(encoding="utf-8")

    assert 'type WorkflowEditorView = "designer" | "yaml"' in text
    assert 'setEditorView("designer")' in text
    assert 'workflow-editor-view-switch' in text
    assert 'workflow-yaml-editor' in text
    assert '"/api/studio/save"' in text
    assert '"/api/studio/graph/save"' in text
    assert "儲存並切換視圖？" in text
    assert "Workflow Editor 只維護一份 canonical YAML" in text
    assert "editorDirty" in text
    assert ".workflow-yaml-view" in styles
    assert ".workflow-editor-view-switch" in styles


def test_workflow_settings_is_manager_and_prompt_editor_not_second_workflow_editor():
    index = (ROOT / "ui" / "static" / "index.html").read_text(encoding="utf-8")
    app = (ROOT / "ui" / "static" / "app.js").read_text(encoding="utf-8")

    assert 'id="assetPageTitle">Workflows</h1>' in index
    assert 'id="promptNav"' in index
    assert 'id="settingsNav"' not in index
    assert 'id="studioEditorModeSwitch"' in index and "hidden" in index
    assert "openWorkflowEditorItem" in app
    assert 'item.kind === "workflow" ? openWorkflowEditorItem(item) : openStudioFile(item)' in app
    assert 'assets.import_yaml' in (ROOT / "ui" / "static" / "js" / "i18n.js").read_text(encoding="utf-8")
    assert 'source: "prompt"' not in app  # URLSearchParams is built from literal source query instead.
    assert 'switchView("prompt")' in app
    assert 'state.studioSourceKind = kind' in app


def test_stage_prompt_can_open_the_shared_prompt_editor():
    text = SOURCE.read_text(encoding="utf-8")
    styles = (ROOT / "ui" / "studio-src" / "src" / "styles.css").read_text(encoding="utf-8")

    assert "promptEditorUrl" in text
    assert 'view: "prompt"' in text
    assert "Edit Prompt" in text
    assert 'className="inline-prompt-edit"' in text
    assert ".inline-prompt-edit" in styles


def test_workflow_settings_uses_full_width_workflow_manager_and_prompt_master_detail():
    app = (ROOT / "ui" / "static" / "app.js").read_text(encoding="utf-8")
    styles = (ROOT / "ui" / "static" / "css" / "workflow-studio.css").read_text(encoding="utf-8")
    i18n = (ROOT / "ui" / "static" / "js" / "i18n.js").read_text(encoding="utf-8")

    assert 'classList.toggle("workflow-manager-mode", workflowManager)' in app
    assert 'classList.toggle("prompt-manager-mode", !workflowManager)' in app
    assert 'studio-file-item-action' in app
    assert 't("studio.open_editor", "Open Editor")' in app
    assert ".studio-designer-body.workflow-manager-mode" in styles
    assert ".workflow-manager-mode .studio-workflow-main" in styles
    assert "display: none" in styles.split(".workflow-manager-mode .studio-workflow-main", 1)[1].split("}", 1)[0]
    assert ".workflow-manager-mode .studio-file-item" in styles
    assert '"studio.open_editor": "開啟 Editor"' in i18n
    assert '"studio.open_editor": "Open Editor"' in i18n


def test_workflow_editor_desktop_responsive_contract_prevents_1024_overflow():
    source_styles = (ROOT / "ui" / "studio-src" / "src" / "styles.css").read_text(encoding="utf-8")
    browser_test = (ROOT / "ui" / "tests" / "test_full_designer_browser.py").read_text(encoding="utf-8")

    assert "@media (max-width: 1180px)" in source_styles
    assert "@media (max-width: 1050px)" in source_styles
    assert ".palette { width: 180px; min-width: 180px; max-width: 180px;" in source_styles
    assert "window.innerWidth - menuWidth - 8" in SOURCE.read_text(encoding="utf-8")
    for width in ("1024", "1280", "1366", "1440", "1920"):
        assert f'"width": {width}' in browser_test
    assert "document.documentElement.scrollWidth <= window.innerWidth" in browser_test
    assert 'get_by_role("tab", name="YAML")' in browser_test


def test_stage_dialog_has_shared_yaml_source_tab():
    text = SOURCE.read_text(encoding="utf-8")
    styles = (ROOT / "ui" / "studio-src" / "src" / "styles.css").read_text(encoding="utf-8")
    server = (ROOT / "ui" / "server.py").read_text(encoding="utf-8")
    state = (ROOT / "ui" / "workflow_studio_state.py").read_text(encoding="utf-8")

    assert 'type InspectorTab = "form" | "yaml" | "routing" | "test"' in text
    assert '"/api/studio/stage/source"' in text
    assert "loadStageYaml" in text
    assert "applyStageYaml" in text
    assert 'className="stage-yaml-panel"' in text
    assert ".stage-yaml-panel textarea" in styles
    assert '"/api/studio/stage/source"' in server
    assert "def studio_stage_source(" in state
    assert "yaml.safe_load(source)" in state
    assert "Stage type is immutable" in state


def test_primary_navigation_separates_workflows_prompts_and_settings():
    index = (ROOT / "ui" / "static" / "index.html").read_text(encoding="utf-8")
    app = (ROOT / "ui" / "static" / "app.js").read_text(encoding="utf-8")
    i18n = (ROOT / "ui" / "static" / "js" / "i18n.js").read_text(encoding="utf-8")

    assert 'id="workflowNav"' in index
    assert 'id="promptNav"' in index
    assert 'id="settingsNav"' not in index
    assert 'id="studioSourceTabs"' in index and "hidden" in index.split('id="studioSourceTabs"', 1)[1].split(">", 1)[0]
    assert 'switchView("workflow")' in app
    assert 'switchView("prompt")' in app
    assert '"nav.prompts": "Prompts"' in i18n



def test_workflow_library_controls_chat_visibility_and_ralphy_default():
    index = (ROOT / "ui" / "static" / "index.html").read_text(encoding="utf-8")
    app = (ROOT / "ui" / "static" / "app.js").read_text(encoding="utf-8")
    styles = (ROOT / "ui" / "static" / "css" / "workflow-studio.css").read_text(encoding="utf-8")

    assert 'DEFAULT_WORKFLOW_NAME = "ralphy_ai_validate.yaml"' in app
    assert "workflowBasename" in app
    assert 'id="workflowContextMenu"' in index
    assert "openWorkflowContextMenu" in app
    assert "setWorkflowVisibility" in app
    assert 'assets.show_in_chat' in app
    assert 'assets.hide_from_chat' in app
    assert ".workflow-context-menu" in styles


def test_stage_editor_converges_to_form_yaml_routing_test():
    text = SOURCE.read_text(encoding="utf-8")
    styles = (ROOT / "ui" / "studio-src" / "src" / "styles.css").read_text(encoding="utf-8")

    assert 'type InspectorTab = "form" | "yaml" | "routing" | "test"' in text
    assert '(["form", "yaml", "routing", "test"] as const)' in text
    assert 'inspectorTab === "form"' in text
    assert 'className="stage-form-section"' in text
    assert 'inspectorTab === "parameters"' not in text
    assert ".stage-form-section" in styles



def test_designer_edge_delete_and_undo_keyboard_contract():
    text = SOURCE.read_text(encoding="utf-8")

    assert 'onEdgeContextMenu={(event, edge) =>' in text
    assert 'onEdgeClick={() =>' in text
    assert 'edge.data?.explicit' in text
    assert 'deleteEdges([selectedExplicitEdge])' in text
    assert 'event.key.toLowerCase() === "z"' in text
    assert "undoVisualDraft()" in text
    assert "rememberUndoSnapshot" in text
    assert "undoStackRef.current = []" in text
    assert "沒有可復原的 Workflow 修改。" in text
    assert "已復原上一個 Workflow 草稿修改。" in text
    assert 'deleteKeyCode={null}' in text  # Node deletion stays workflow-aware.
    assert 'tx("delete_connection")' in text



def test_ai_stage_profile_first_create_and_quick_shortcuts():
    text = SOURCE.read_text(encoding="utf-8")

    assert 'createAIProfile' in text
    assert '<option value="generic">Generic</option>' in text
    assert '<option value="execute">Execute</option>' in text
    assert '<option value="review">Review</option>' in text
    assert "applyAIProfileDefaults" in text
    assert "common/execution.md" in text
    assert "common/review.md" in text
    assert 'event.key === "/"' in text
    assert 'event.key === "Enter" && selected' in text
    assert 'title="Add Stage (/)"' in text


def test_stage_palette_and_generic_field_use_catalog_metadata():
    text = SOURCE.read_text(encoding="utf-8")

    assert "CatalogStageType" in text
    assert "catalogStageMeta" in text
    assert "catalogMeta?.title" in text
    assert "catalogMeta?.description" in text
    assert "catalogMeta?.category" in text
    assert "option.description" in text
    assert 'category !== "extensions"' in text
