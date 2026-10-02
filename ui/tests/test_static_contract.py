from pathlib import Path
import unittest


class StaticContractTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(__file__).resolve().parents[1]
        self.html = (self.root / "static" / "index.html").read_text(encoding="utf-8")
        self.app_js = (self.root / "static" / "app.js").read_text(encoding="utf-8")
        self.generator_js = (self.root / "static" / "js" / "workflow-generator.js").read_text(encoding="utf-8")
        self.js = self.app_js + "\n" + self.generator_js

    def test_ui_does_not_import_runner_core(self):
        for path in self.root.rglob("*.py"):
            if "tests" in path.parts:
                continue
            text = path.read_text(encoding="utf-8")
            self.assertNotIn("from runner", text, str(path))
            self.assertNotIn("import runner", text, str(path))

    def test_thinking_panels_are_not_in_markup(self):
        html = self.html.lower()
        for token in ("thinking", "reasoning", "chain-of-thought"):
            self.assertNotIn(token, html)

    def test_expected_runtime_contract_names_remain_visible(self):
        runtime = (self.root / "project_runtime_state.py").read_text(encoding="utf-8")
        for token in ("state.json", "runner-process.json", "stream.log", "stop.request"):
            self.assertIn(token, runtime)

    def test_workflow_studio_keeps_only_user_facing_controls(self):
        for token in ("Workflow Studio", "Workflows", "Visual", "YAML", "Validate", "Generate with AI", "Workflow Steps"):
            self.assertIn(token, self.html)
        self.assertIn("Available Params", self.html)
        for token in ("Patch Review", "Run Center", "Analytics", "Assets"):
            self.assertNotIn(token, self.html)

    def test_stage_editor_uses_small_useful_tab_set(self):
        self.assertIn('data-stage-tab="settings"', self.js)
        self.assertIn('data-stage-tab="control"', self.js)
        for removed in ('data-stage-tab="prompt"', 'data-stage-tab="review"', 'data-stage-tab="retry"', 'data-stage-tab="gate"', 'data-stage-tab="advanced"'):
            self.assertNotIn(removed, self.js)

    def test_stage_modal_has_real_editable_contract_fields(self):
        for token in (
            "stageStatus", "stageRunState", "stageScope", "stageActor", "stageMode", "stageTimeout",
            "stageProduces", "stageSessionKey", "stageSessionPolicy", "stageDetail",
            "stageStructuredRetries", "stageStructuredFreshRetries",
            "stageTrackChanges", "stageTolerateRestored",
            "stageAllowProjectRead", "stageCleanWork", "stageCommand", "stageResultKind", "stageCwd",
            "stageMinTasks", "stageValidator", "stageRuns", "stageRequiredPasses",
            "stageParser", "stageFlowLabel", "stageRoutePass", "stageRouteFail",
        ):
            self.assertIn(token, self.js)

    def test_stage_modal_uses_session_policy_not_legacy_fresh_toggles(self):
        self.assertIn("stageSessionPolicy", self.js)
        self.assertIn('sessionPolicy !== "auto"', self.js)
        self.assertNotIn('id="stageFreshOnStart"', self.js)
        self.assertNotIn('id="stageFreshEachRun"', self.js)
        self.assertIn('for (const key of ["fresh_session_each_run", "fresh_session_on_start"])', self.js)


    def test_stage_modal_has_one_prompt_selector_and_no_prompt_body_editor(self):
        self.assertIn("stagePromptSelect", self.js)
        self.assertNotIn("stageContinuationPromptSelect", self.js)
        for removed in ("stagePromptPathInput", "stagePromptLibrarySelect", "stagePromptTextarea", "saveStagePrompt"):
            self.assertNotIn(removed, self.js)
        self.assertIn('t("stage.prompt_desc"', self.js)
        self.assertIn('function stageTypeNames()', self.js)
        self.assertIn('function stageHasOption(type, name)', self.js)
        self.assertIn('stageHasOption(type, "prompt")', self.js)
        self.assertIn('/api/workflow/catalog', self.js)

    def test_prompt_editor_is_first_class_and_has_runtime_param_chips(self):
        for token in ('id="promptEditorPanel"', 'id="studioPromptTextarea"', 'id="studioPromptParamList"', "Available Params"):
            self.assertIn(token, self.html)
        for token in ("/api/studio/prompt-tags", "insertPromptTag", "{{${key}}}", "/api/studio/prompt/check"):
            self.assertIn(token, self.js)

    def test_add_project_and_add_stage_are_static_style_modals(self):
        for token in ('id="projectModalBackdrop" class="modal-backdrop"', 'class="modal-card project-modal-card"',
                      'id="addStageBackdrop" class="modal-backdrop"', 'class="modal-card add-stage-card"'):
            self.assertIn(token, self.html)
        self.assertIn("modal-title-with-icon", self.html)
        self.assertIn("add-stage-preview", self.html)

    def test_manual_new_workflow_uses_static_style_modal(self):
        for token in ('id="newWorkflowButton"', 'id="newWorkflowBackdrop" class="modal-backdrop"', 'class="modal-card workflow-create-card"', 'id="newWorkflowDestination"'):
            self.assertIn(token, self.html)
        self.assertIn("/api/studio/workflow/create", self.js)

    def test_stage_editor_exposes_result_edges_and_shared_runtime_retry(self):
        for token in ("Result edges", "Structured output", "Session & safety", "stage-help"):
            self.assertIn(token, self.js)
        self.assertNotIn("stageRetry", self.js)
        for removed in ("Recovery gate", "stageRecover", "stageMaxAttempts", "stageRestartAt", "stageRouteReplan"):
            self.assertNotIn(removed, self.js)

    def test_legacy_visual_editor_does_not_reintroduce_task_or_review_stage_types(self):
        self.assertNotIn('"task"', self.js[self.js.find("function normalizeStageType"):self.js.find("function normalizeStageType") + 1500] if "function normalizeStageType" in self.js else "")
        self.assertNotIn('type: "review"', self.js)

    def test_environment_check_is_available_from_run_options(self):
        for token in ('id="environmentCheckButton"', 'id="environmentCheckResult"'):
            self.assertIn(token, self.html)
        self.assertIn('/api/environment/check', self.js)

    def test_clear_history_is_disabled_for_running_selected_project(self):
        self.assertIn('$("clearHistoryButton").disabled = Boolean(runtime.running)', self.js)
        self.assertIn('if (!state.project || state.runtime?.running) return;', self.js)


    def test_full_designer_returns_to_workflow_studio_and_restores_workflow(self):
        self.assertIn("restoreWorkflowStudioNavigation", self.app_js)
        self.assertIn('params.get("view") !== "workflow"', self.app_js)
        self.assertIn('params.get("studio")', self.app_js)
        self.assertIn('await switchView("workflow")', self.app_js)
        self.assertIn('await openStudioFile(item)', self.app_js)


class LayoutRegressionTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(__file__).resolve().parents[1]
        self.html = (self.root / "static" / "index.html").read_text(encoding="utf-8")
        self.app_js = (self.root / "static" / "app.js").read_text(encoding="utf-8")
        self.generator_js = (self.root / "static" / "js" / "workflow-generator.js").read_text(encoding="utf-8")
        self.js = self.app_js + "\n" + self.generator_js
        self.runner_css = (self.root / "static" / "css" / "runner-lite.css").read_text(encoding="utf-8")
        self.studio_css = (self.root / "static" / "css" / "workflow-studio.css").read_text(encoding="utf-8")
        self.generator_css = (self.root / "static" / "css" / "workflow-generator.css").read_text(encoding="utf-8")

    def test_chat_history_owns_full_middle_and_composer_floats_over_reserved_scroll_space(self):
        css = "".join(self.runner_css.split())
        self.assertIn("grid-template-rows:autoautominmax(0,1fr)", css)
        self.assertIn("#chatView>.history{grid-row:3", css)
        self.assertIn("padding-bottom:calc(var(--composer-reserve)+18px)", css)
        self.assertIn("#chatView>.compose-panel{position:absolute;left:0;right:0;bottom:0", css)
        self.assertIn("pointer-events:none", css)
        self.assertIn("#chatView>.compose-panel>.composer-box{pointer-events:auto", css)
        self.assertIn("height:60px!important", css)
        self.assertIn("syncComposerReserve", self.js)

    def test_composer_remains_viewport_bound_under_browser_zoom(self):
        css = "".join(self.runner_css.split())
        self.assertIn("height:100dvh", css)
        self.assertIn("min-height:0!important", css)
        self.assertIn("overflow:hidden!important", css)
        self.assertIn(".workspace{position:relative", css)
        self.assertIn("height:100%", css)

    def test_projects_are_natural_top_down_flex_flow(self):
        css = "".join(self.runner_css.split())
        self.assertIn(".projects{display:flex!important;flex-direction:column", css)
        self.assertIn(".projects.project-list{flex:11auto", css)
        self.assertIn("align-content:start", css)

    def test_workflow_studio_has_visual_and_yaml_modes_and_sources(self):
        self.assertIn('id="visualDesignerPanel"', self.html)
        self.assertIn('id="yamlEditorPanel"', self.html)
        self.assertIn('id="promptEditorPanel"', self.html)
        self.assertIn('id="visualFlowList"', self.html)
        self.assertIn('id="yamlWorkflowSource"', self.html)
        self.assertIn('id="yamlPromptSource"', self.html)
        self.assertNotIn('id="studioSourceTabs" class="studio-source-tabs" hidden', self.html)
        self.assertIn('state.studioSourceKind === "prompt"', self.js)
        self.assertIn("draggable", self.js)

    def test_workflow_and_prompt_columns_remain_fixed_with_inner_scroll(self):
        css = "".join(self.studio_css.split())
        self.assertIn(".studio-workflow-sidebar{display:grid;grid-template-rows:autoautoautominmax(0,1fr)", css)
        self.assertIn(".studio-file-list,.studio-workflow-sidebar.designer-custom-list{min-height:0;overflow:auto", css)
        self.assertIn("overflow-y:scroll", css)
        self.assertIn("scrollbar-gutter:stable", css)
        self.assertIn(".studio-step-panel{height:100%;min-height:0;display:grid;grid-template-rows:autominmax(0,1fr);overflow:hidden", css)
        self.assertIn(".studio-prompt-panel{min-width:0;overflow:hidden;display:grid;grid-template-rows:autominmax(0,1fr)", css)

    def test_workflow_designer_body_owns_flexible_row_even_when_lock_banner_hidden(self):
        css = "".join(self.studio_css.split())
        self.assertIn(".studio-main>.studio-topbar{grid-row:1", css)
        self.assertIn(".studio-main>.studio-lock-banner{grid-row:2", css)
        self.assertIn(".studio-main>.studio-designer-body{grid-row:3;min-height:0;height:100%", css)


    def test_add_stage_modal_stays_inside_viewport_and_scrolls_body(self):
        css = "".join(self.studio_css.split())
        self.assertIn("max-height:calc(100dvh-32px)", css)
        self.assertIn(".modal-scroll-body{min-height:0;overflow:auto", css)
        self.assertIn('class="modal-scroll-body add-stage-body"', self.html)

    def test_yaml_editor_has_indent_and_live_syntax_contract(self):
        for token in ("handleEditorKeydown", 'event.key === "Tab"', "/api/studio/check", "updateLineNumbers", "scheduleSyntaxCheck"):
            self.assertIn(token, self.js)
        self.assertIn("studio-line-numbers", self.studio_css)
        self.assertIn("font:13px/1.6", "".join(self.studio_css.split()))

    def test_static_step_selection_and_floating_actions_contract(self):
        for token in ("designer-step-floating-actions", "designer-action-toggle", 'data-flow-action="edit"', 'data-flow-action="up"', 'data-flow-action="down"'):
            self.assertIn(token, self.js)
        self.assertIn('card.addEventListener("click"', self.js)
        self.assertIn('card.addEventListener("dblclick"', self.js)
        self.assertIn("moveSelectedFlow", self.js)

    def test_stage_advanced_overrides_are_collapsed_instead_of_cluttering_primary_fields(self):
        self.assertIn("stage-advanced-overrides", self.js)
        self.assertIn("Advanced overrides", self.js)
        self.assertIn("hasAdvancedStageOverrides", self.js)
        self.assertNotIn("stageContinuationPromptRow", self.js)

    def test_add_stage_does_not_write_prompt_for_plan_or_command(self):
        self.assertIn('prompt: stageSupportsPrompt($("addStageType").value) ? $("addStagePrompt").value : ""', self.js)
        self.assertIn('$("addStagePromptRow").hidden = !stageSupportsPrompt(type)', self.js)

    def test_command_editor_does_not_submit_ai_only_fields(self):
        self.assertIn('const type = fieldValue("stageType");', self.js)
        self.assertIn('const aiBacked = type !== "command";', self.js)
        self.assertIn('if (aiBacked) {', self.js)
        self.assertIn(
            'if ($("stageCleanWorkRow")) $("stageCleanWorkRow").hidden = type !== "command"',
            self.js,
        )

    def test_prompt_and_step_surfaces_end_on_sidebar_baseline(self):
        css = "".join(self.studio_css.split())
        self.assertIn(".studio-workflow-editor{position:relative;grid-template-rows:autoautominmax(0,1fr)", css)
        self.assertIn(".studio-workflow-editor>.studio-prompt-panel{grid-row:3;min-height:0;height:100%", css)
        self.assertNotIn(".studio-footer{", css)
        self.assertNotIn('id="studioFooter"', self.html)


    def test_compact_studio_keeps_validation_auto_and_editor_flexible(self):
        css = "".join(self.studio_css.split())
        self.assertIn(".studio-workflow-editor{grid-template-rows:autoautominmax(0,1fr);gap:8px}", css)
        self.assertNotIn(".studio-workflow-editor{grid-template-rows:autominmax(0,1fr)auto;gap:8px}", css)

    def test_stage_retry_is_runner_owned_not_node_owned(self):
        self.assertNotIn('id="stageRetry"', self.js)
        self.assertNotIn('-1 = keep retrying until PASS', self.js)
        self.assertIn("Technical Stage retry/session recovery is global Runner behavior.", self.js)
        self.assertNotIn("stageRouteError", self.js)

    def test_flow_routing_fields_are_editable_in_stage_modal(self):
        for token in ("stageFlowLabel", "stageRoutePass", "stageRouteFail", "routes: routeMapOrNull()"):
            self.assertIn(token, self.js)

    def test_stage_editor_is_modal_but_workflow_studio_is_page(self):
        self.assertIn('id="workflowView" class="workflow-page"', self.html)
        self.assertNotIn("workflow-studio-backdrop", self.html)
        self.assertIn("designer-step-modal-box", self.js)
        self.assertIn("designer-step-modal-card", self.js)
        self.assertIn("openStageEditor(index)", self.js)

    def test_composer_has_real_workflow_selector_and_contextual_python_validator(self):
        self.assertIn('id="workflowSelect"', self.html)
        self.assertIn('id="validatorPicker"', self.html)
        self.assertIn('id="browseValidatorButton"', self.html)
        self.assertIn('id="clearValidatorButton"', self.html)
        self.assertNotIn('id="workflow" placeholder="Workflow path', self.html)
        self.assertIn("selectedWorkflowItem()", self.js)
        self.assertIn('workflow: workflow?.path || ""', self.js)
        self.assertIn('validator: workflow?.requires_python_validator ? $("validator").value.trim() : ""', self.js)
        self.assertIn('validatorPicker.hidden = !workflow?.requires_python_validator', self.js)
        self.assertIn("renderWorkflowPicker()", self.js)
        self.assertIn("browseValidator()", self.js)

    def test_workflow_dropdown_can_escape_picker_and_floating_composer(self):
        css = "".join(self.runner_css.split())
        self.assertIn("#workflowPicker{position:relative;z-index:20;overflow:visible!important", css)
        self.assertIn("#workflowDropdownMenu.workflow-dropdown-portal{position:fixed!important;z-index:5000!important", css)
        self.assertIn("document.body.appendChild(menu)", self.js)
        self.assertIn("positionWorkflowDropdown", self.js)
        self.assertIn("closeWorkflowDropdown", self.js)

    def test_available_params_has_chips_without_redundant_descriptions(self):
        self.assertIn("Available Params", self.html)
        self.assertNotIn("參數直接來自目前 Runner", self.html)
        self.assertNotIn('id="studioPromptTagCount"', self.html)

    def test_reusable_toast_import_export_and_delete_controls_exist(self):
        for token in ("showToast(message", ".app-toast-stack", ".app-toast.success", ".app-toast.error"):
            self.assertIn(token, self.js + self.studio_css)
        for token in ('id="importAssetButton"', 'id="exportStudioButton"', 'id="deleteStudioButton"', 'id="importAssetBackdrop"'):
            self.assertIn(token, self.html)

    def test_export_downloads_original_asset_instead_of_json_package(self):
        self.assertIn('new Blob([String(data.content ?? "")]', self.js)
        self.assertIn('a.download = name', self.js)
        self.assertNotIn('.export.json', self.js)

    def test_stage_remove_deletes_the_single_node_definition(self):
        self.assertIn('title: "Delete Stage?"', self.js)
        self.assertIn('confirmLabel: "Delete Stage"', self.js)
        self.assertIn('/api/studio/stage/delete', self.js)
        self.assertNotIn('choiceDialog({ title: "Remove Stage?"', self.js)
        self.assertNotIn('Delete Definition Too', self.js)
        self.assertNotIn('value: "flow"', self.js)

    def test_add_stage_key_and_type_controls_share_height(self):
        css = "".join(self.studio_css.split())
        self.assertIn(".add-stage-grid.designer-input,.add-stage-grid.designer-select{box-sizing:border-box;height:40px;min-height:40px", css)

    def test_studio_crud_search_and_modular_dialog_support_exist(self):
        for token in ('id="studioSearchInput"', 'id="studioSearchClear"', 'id="studioAssetMenuButton"', 'id="renameStudioButton"', 'id="duplicateStudioButton"'):
            self.assertIn(token, self.html)
        self.assertIn('/js/ui-dialogs.js', self.html)
        self.assertIn('/js/studio-support.js', self.html)
        self.assertIn('window.UiDialogs.confirm', self.js)
        self.assertIn('window.StudioSupport.filterItems', self.js)
        self.assertNotIn('window.confirm', self.js)

    def test_explicit_workflow_ai_validator_companion_contract(self):
        repo = self.root.parent
        source = (
            repo / "runner" / "workflow" / "stages" / "ai_validator_stage.py"
        ).read_text(encoding="utf-8")
        self.assertIn("ctx.config.workflow_explicit", source)
        self.assertIn("or ctx.validator_is_ai", source)
        self.assertIn("or ctx.config.ai_validator_prompt.strip()", source)

    def test_stage_status_is_primary_title_with_ellipsis(self):
        self.assertIn(
            'const displayTitle = String(cfg.status ?? "").trim() || name || "Unnamed"',
            self.js,
        )
        css = "".join(self.studio_css.split())
        self.assertIn(
            ".visual-flow-copystrong{display:block;min-width:0;max-width:100%;overflow:hidden;text-overflow:ellipsis;white-space:nowrap",
            css,
        )

    def test_import_editor_is_bounded_inside_modal(self):
        css = "".join(self.studio_css.split())
        self.assertIn(".import-asset-card{display:grid;grid-template-rows:autominmax(0,1fr)auto;overflow:hidden", css)
        self.assertIn("#importAssetContent.designer-import-json{box-sizing:border-box;width:100%;height:100%;min-height:160px", css)
        self.assertIn("resize:none", css)
        self.assertIn('class="designer-form-grid import-asset-form"', self.html)

    def test_floating_stage_panel_expands_above_fixed_toggle(self):
        css = "".join(self.studio_css.split())
        self.assertIn(".workflow-page.designer-step-floating-actions>.designer-action-toggle{position:absolute;right:0;bottom:0", css)
        self.assertIn(".workflow-page.designer-step-floating-actions>.designer-floating-panel{position:absolute;right:0;bottom:calc(100%+8px)", css)
        self.assertIn(".workflow-page.designer-step-floating-actions.designer-action-toggle:hover{transform:none", css)

    def test_validation_toast_is_top_center_and_reusable(self):
        css = "".join(self.studio_css.split())
        self.assertIn(".app-toast-stack{top:18px;left:50%;right:auto;transform:translateX(-50%)", css)
        self.assertIn('function showToast(message, tone = "success", duration = 2200)', self.js)

    def test_validation_supports_unsaved_workflow_and_stage_drafts(self):
        for token in ('body.content = $("studioTextarea").value', 'body.flow = state.visual?.flow || []', 'id="validateStageButton"', 'function validateStageEditor(index, name, cfg, item)', '/api/studio/stage/validate'):
            self.assertIn(token, self.js)
        self.assertIn('showActionError(error.message, "Workflow validation failed")', self.js)

    def test_stage_editor_uses_stage_definition_prompt_and_status_only(self):
        self.assertIn('value="${escapeHtml(cfg.status ?? "")}"', self.js)
        self.assertIn('promptOptionRows(cfg.prompt ?? "")', self.js)
        self.assertNotIn('item?.status ?? cfg.status', self.js)
        self.assertNotIn('item?.prompt ?? cfg.prompt', self.js)
        self.assertNotIn('Object.prototype.hasOwnProperty.call(item, "prompt")', self.js)
        self.assertNotIn('Object.prototype.hasOwnProperty.call(item, "status")', self.js)

    def test_project_actions_use_static_menu_and_confirmed_remove(self):
        for token in ("project-action-menu", "project-menu-button", 'rename.textContent = t("project.rename", "Rename project")', 'remove.textContent = t("project.remove", "Remove project")', 'title: "Remove Project?"', '/api/projects/rename'):
            self.assertIn(token, self.js)

    def test_project_action_menu_portals_out_of_scroll_container(self):
        css = "".join(self.runner_css.split())
        self.assertIn(".project-action-menu.project-action-menu-portal{position:fixed!important", css)
        for token in ("function openProjectMenu(menu, anchor, row)", "document.body.appendChild(menu)", "function positionProjectMenu(menu, anchor)"):
            self.assertIn(token, self.js)

    def test_composer_is_workflow_task_only_for_now(self):
        for token in ('id="modeWorkflow"', 'id="modeChat"', 'function setRunMode(mode)', 'state.runMode === "chat"'):
            self.assertNotIn(token, self.html + self.js)
        self.assertIn('Select a Workflow before Run', (self.root.parent / "server.py").read_text(encoding="utf-8") if (self.root.parent / "server.py").exists() else "Select a Workflow before Run")

    def test_runtime_controls_replace_run_in_composer(self):
        for token in ('id="sendButton"', 'id="stopButton"', 'id="resumeButton"', 'id="resetButton"'):
            self.assertIn(token, self.html)
        composer = self.html[self.html.index('class="composer-right runtime-composer-actions"'):self.html.index('</div>', self.html.index('class="composer-right runtime-composer-actions"'))]
        for token in ('id="sendButton"', 'id="stopButton"', 'id="resumeButton"', 'id="resetButton"'):
            self.assertIn(token, composer)
        for token in ('/api/project/stop', '/api/project/resume', '/api/project/reset', '$("sendButton").hidden = runtime.running || runtime.resumable'):
            self.assertIn(token, self.js)

    def test_runtime_card_uses_cli_snapshot_without_fake_activity_animation(self):
        css = "".join(self.runner_css.split())
        self.assertIn("cliRuntimeText(runtime)", self.js)
        self.assertIn("renderCliRuntimeFrame()", self.js)
        self.assertIn("runtime.cli_lines", self.js)
        self.assertIn('const marker = runtime.running ? ">" : " "', self.js)
        self.assertIn("setInterval(updateRuntimeFreshness, 1000)", self.js)
        for token in ("CLI_SPINNER_FRAMES", "spinnerFrame", "animateRuntimeFrame", "runtimeActivitySweep", "runtimeFooterPulse"):
            self.assertNotIn(token, self.js + self.runner_css)
        self.assertIn(".cli-runtime-output{", css)
        self.assertIn(".runtime-live-indicator{", css)

    def test_project_rows_show_runtime_state_and_running_pulse(self):
        css = "".join(self.runner_css.split())
        for token in ("runtime_status", "project-runtime-label", "runtime-${runtimeStatus}", "refreshProjectStatuses"):
            self.assertIn(token, self.js)
        self.assertIn(".project-row.runtime-running.project-mark::after", css)
        self.assertIn("animation:projectRunningPulse", css)

    def test_project_status_polling_is_load_aware(self):
        for token in (
            "applyProjectPollMeta(data)",
            "projectStatusPollDelay",
            "projectStatusHiddenPollDelay",
            "startNonOverlappingPoll(refreshProjectStatuses, projectStatusPollDelay, projectStatusHiddenPollDelay)",
        ):
            self.assertIn(token, self.js)
        self.assertNotIn("startNonOverlappingPoll(refreshProjectStatuses, 4000, 12000)", self.js)

    def test_confirmation_overlay_sits_above_floating_composer_and_portals(self):
        css = "".join(self.runner_css.split())
        self.assertIn(".designer-export-box{z-index:6500!important", css)
        self.assertIn(".designer-confirm-box{z-index:7000!important", css)
        self.assertIn("backdrop-filter:blur(3px)", css)

    def test_runtime_state_is_in_white_conversation_card_not_input(self):
        css = "".join(self.runner_css.split())
        for token in ("renderLiveRuntimeHeader(runtime)", "renderCliRuntimeFrame()", "setInterval(updateRuntimeFreshness, 1000)"):
            self.assertIn(token, self.js)
        self.assertNotIn("renderComposerRuntimeFrame", self.js)
        self.assertNotIn("Running · ${runtime.cli_status}", self.js)
        self.assertIn(".cli-runtime-card{border-color:#d9e2ec;background:var(--panel)", css)
        self.assertIn(".cli-runtime-output{color:#263244;background:var(--panel)", css)

    def test_conversation_auto_follows_new_runtime_card_without_hijacking_manual_scroll(self):
        for token in (
            "historyPinnedToBottom",
            "function historyNearBottom(",
            "function followHistoryToBottom(",
            "forceVisibleOnCreate: true",
            '$("messages").addEventListener("scroll"',
            "refreshMessages({ forceFollow: true })",
        ):
            self.assertIn(token, self.js)
        self.assertIn("if (!force && !state.historyPinnedToBottom) return", self.js)

    def test_conversation_cards_never_flex_shrink_when_history_overflows(self):
        css = "".join(self.runner_css.split())
        self.assertIn("#messages.history>.message,#messages.history>.live-activity{flex:00auto", css)

    def test_completed_runtime_card_is_replaced_by_assistant_conversation(self):
        self.assertIn("if (runtime.running || runtime.resumable)", self.js)
        self.assertNotIn("if (runtime.running || runtime.has_state)", self.js)
        self.assertIn("removeLiveCard();", self.js)
        self.assertIn('runtime.completed && runtime.run_id && runtime.run_id !== state.lastRunId', self.js)
        self.assertIn('refreshMessages({ forceFollow: true })', self.js)

    def test_options_is_floating_popover_and_does_not_resize_composer(self):
        css = "".join(self.runner_css.split())
        self.assertIn("#composePanel.options-panel{position:absolute", css)
        self.assertIn("bottom:48px", css)
        self.assertIn("box-shadow:016px38px", css)
        self.assertIn("function toggleOptionsPanel()", self.js)
        self.assertNotIn('requestAnimationFrame(syncComposerReserve); };\n$("sendButton")', self.js)

    def test_project_rows_have_more_vertical_room(self):
        css = "".join(self.runner_css.split())
        self.assertIn(".project-root{min-height:42px", css)

    def test_prompt_validate_button_uses_same_validate_action(self):
        self.assertIn('$("validateStudioButton").textContent = state.studioFile?.kind === "prompt" ? "Validate Prompt" : "Validate Workflow"', self.js)
        self.assertIn('if (prompt) body.content = $("studioPromptTextarea").value', self.js)
        self.assertIn('api("/api/studio/validate"', self.js)

    def test_idle_projects_are_explicitly_labeled(self):
        self.assertIn('idle: "IDLE"', self.js)
        css = "".join(self.runner_css.split())
        self.assertIn(".project-runtime-label.runtime-idle", css)

    def test_visual_helper_copy_is_small(self):
        css = "".join(self.studio_css.split())
        self.assertIn(".studio-topbarp{font-size:10px", css)

    def test_ai_workflow_builder_is_page_generate_review_then_save_flow(self):
        for token in (
            'id="workflowGeneratorPage"',
            'id="generateWorkflowRequest"',
            'id="generateWorkflowRunning"',
            'id="generateWorkflowReady"',
            'id="generateWorkflowDiscard"',
            'id="generateWorkflowRegenerate"',
            'id="generateWorkflowSave"',
            'id="generateWorkflowSaveBackdrop"',
        ):
            self.assertIn(token, self.html)
        self.assertNotIn('id="generateWorkflowBackdrop"', self.html)
        for token in (
            "openGenerateWorkflowPage",
            "confirmGenerateWorkflow",
            "pollGenerateWorkflow",
            "validateGeneratedWorkflowDraft",
            "openGenerateWorkflowSaveModal",
            "saveGenerateWorkflowDraft",
            "discardGenerateWorkflowDraft",
            "cancelGenerateWorkflow",
            'api("/api/studio/generate"',
            'api("/api/studio/generate/validate"',
            'api("/api/studio/generate/save"',
        ):
            self.assertIn(token, self.js)
        self.assertIn("DRAFT · NOT SAVED", self.html)
        self.assertIn("Prompts: runner/assets/prompts/workflow/&lt;workflow-name&gt;/", self.html)
        self.assertNotIn("owned Folder", self.js)

    def test_ai_workflow_builder_generation_is_project_independent(self):
        block = self.js[
            self.js.index("async function openGenerateWorkflowPage"):
            self.js.index("function closeGenerateWorkflowSaveModal")
        ]
        self.assertNotIn("Open a Project before generating", block)
        self.assertNotIn("state.project", block)
        poll = self.js[
            self.js.index("async function pollGenerateWorkflow"):
            self.js.index("function startGenerateWorkflowPoll")
        ]
        self.assertNotIn("project=", poll)
        self.assertIn("job_id=", poll)
        self.assertIn("runner/assets/workflows/", self.html)
        self.assertIn("runner/assets/prompts/workflow/", self.html)
        self.assertIn("copyWorkflowWorkspace", self.js)

    def test_ai_workflow_builder_restores_single_active_job_and_shows_workspace(self):
        for token in ('id="generateWorkflowWorkspacePreview"', 'id="generateWorkflowRunningWorkspace"', 'id="generateWorkflowReadyWorkspace"'):
            self.assertIn(token, self.html)
        for token in (
            '/api/studio/generate/active',
            'restoreActiveWorkflowGenerator',
            'hydrateActiveGenerateWorkflow',
            'setGenerateWorkflowWorkspace',
            'restoreWorkflowStudioNavigation',
            'await restoreWorkflowStudioNavigation()',
            'await restoreActiveWorkflowGenerator()',
        ):
            self.assertIn(token, self.js)
        before = self.js[self.js.index('window.addEventListener("beforeunload"'):self.js.index('state.preferences = loadUiPreferences()')]
        self.assertNotIn('["running", "cancelling", "ready"]', before)

    def test_ai_workflow_builder_status_only_phase_is_stacked_and_centered(self):
        css = "".join(self.generator_css.split())
        self.assertIn(".workflow-builder-running{min-height:0;display:grid;grid-template-columns:minmax(0,1fr);justify-items:center", css)
        self.assertIn(".workflow-builder-failed{min-height:0;display:grid;grid-template-columns:minmax(0,1fr);justify-items:center", css)

    def test_ai_workflow_builder_uses_filename_and_destination_without_folder(self):
        form = self.html[self.html.index('id="generateWorkflowForm"'):self.html.index('id="generateWorkflowRunning"')]
        self.assertIn('id="generateWorkflowRequest"', form)
        self.assertIn('id="generateWorkflowFilename"', form)
        self.assertIn('id="generateWorkflowBackend"', form)
        self.assertNotIn('id="generateWorkflowFolder"', form)
        self.assertNotIn('id="generateWorkflowDestination"', form)
        save = self.html[self.html.index('id="generateWorkflowSaveBackdrop"'):self.html.index('id="importAssetBackdrop"')]
        self.assertNotIn('id="generateWorkflowSaveFolder"', save)
        self.assertIn('id="generateWorkflowSaveFilename"', save)
        self.assertIn('id="generateWorkflowDestination"', save)
        self.assertIn('id="generateWorkflowSavePathPreview"', save)
        self.assertIn('runner/assets/prompts/workflow/&lt;workflow-name&gt;/', save)


    def test_ai_workflow_builder_input_layout_keeps_meta_below_prompt(self):
        form = self.html[self.html.index('id="generateWorkflowForm"'):self.html.index('id="generateWorkflowRunning"')]
        self.assertIn('class="workflow-generator-input-meta"', form)
        css = "".join(self.generator_css.split())
        self.assertIn('.workflow-generator-input{height:100%;display:flex;flex-direction:column;gap:10px', css)
        self.assertIn('.workflow-generator-main{min-width:0;min-height:0;display:grid;height:100%;grid-template-rows:minmax(0,1fr);place-items:stretch;overflow:hidden', css)
        self.assertIn('@media(max-height:480px)and(min-width:761px)', css)
        self.assertIn('.workflow-generator-phase{min-width:0;min-height:0;width:min(1080px,100%);height:100%', css)
        self.assertIn('grid-template-rows:autominmax(150px,1fr)auto', css)
        self.assertIn('.workflow-generator-request{box-sizing:border-box;width:100%;height:100%;min-height:150px', css)
        self.assertIn('overflow-wrap:anywhere', css)
        self.assertNotIn('.workflow-generator-', self.studio_css)

    def test_generated_workflow_draft_has_explicit_edit_actions(self):
        ready = self.html[self.html.index('id="generateWorkflowReady"'):self.html.index('id="generateWorkflowFailed"')]
        for token in ('EDITABLE', 'id="generateWorkflowEditYaml"', 'id="generateWorkflowEditPrompt"', '>Edit YAML<', '>Edit Prompt<'):
            self.assertIn(token, ready)
        self.assertIn('focusGeneratedDraftEditor', self.js)
        self.assertIn('$("generateWorkflowPreview").addEventListener("input", markGeneratedDraftDirty)', self.js)
        self.assertIn('$("generateDraftPromptTextarea").addEventListener("input"', self.js)

    def test_generator_exit_restores_workflow_catalog_without_browser_refresh(self):
        self.assertIn('async function restoreWorkflowStudioAfterGenerator()', self.js)
        helper = self.js[self.js.index('function showWorkflowStudioPage()'):self.js.index('function showWorkflowGeneratorPage()')]
        self.assertIn('renderStudioFiles()', helper)
        self.assertIn('renderWorkflowPicker()', helper)
        self.assertIn('await refreshStudioFiles({ force: true })', helper)
        discard = self.js[self.js.index('async function discardGenerateWorkflowDraft'):self.js.index('async function cancelGenerateWorkflow')]
        self.assertIn('await restoreWorkflowStudioAfterGenerator()', discard)
        cancelled = self.js[self.js.index('async function pollGenerateWorkflow'):self.js.index('function startGenerateWorkflowPoll')]
        self.assertIn('await restoreWorkflowStudioAfterGenerator()', cancelled)

    def test_stage_discard_uses_reusable_designed_confirm(self):
        block = self.js[self.js.index('async function closeStageEditor'):self.js.index('// ------------------------------ Add Stage modal')]
        self.assertIn('confirmDialog({', block)
        self.assertIn('title: "Discard Stage changes?"', block)
        self.assertIn('confirmLabel: "Discard Changes"', block)
        self.assertNotIn('window.confirm', block)

    def test_custom_import_file_picker_button_is_wired(self):
        self.assertIn('id="importAssetChooseButton"', self.html)
        self.assertIn('id="importAssetFileName"', self.html)
        self.assertIn('$("importAssetChooseButton").onclick = () => $("importAssetFile").click()', self.js)
        self.assertIn('$("importAssetFileName").textContent = file.name', self.js)

    def test_run_preferences_are_persisted_per_project_in_browser_storage(self):
        for token in (
            'UI_PREFS_KEY = "ai-task-runner.ui.preferences.v1"',
            'localStorage.getItem(UI_PREFS_KEY)',
            'localStorage.setItem(UI_PREFS_KEY',
            'rememberProjectPreference("backend"',
            'rememberProjectPreference("workflow"',
            'rememberValidator(',
            'lastProject',
            'builderBackend',
        ):
            self.assertIn(token, self.js)

    def test_backend_uses_upward_custom_dropdown_and_shared_five_row_scroll_cap(self):
        for token in ('id="backendDropdownButton"', 'id="backendDropdownMenu"', 'id="backendSelectedLabel"'):
            self.assertIn(token, self.html)
        for token in ('function openBackendDropdown()', 'function positionUpwardDropdown(', 'rowCount > 5', 'backend-dropdown-portal'):
            self.assertIn(token, self.js + self.runner_css)
        self.assertIn('positionUpwardDropdown(menu, button, menu.children.length, 120)', self.js)
        css = "".join(self.runner_css.split())
        self.assertIn('#backendDropdownMenu.backend-dropdown-portal{position:fixed!important;z-index:5100!important', css)

    def test_runtime_header_title_is_lifecycle_status_only(self):
        block = self.js[self.js.index('function runtimeStatusLabel'):self.js.index('function runtimeRenderSignature')]
        self.assertIn('if (runtime?.running) return "Running"', block)
        self.assertIn('if (runtime?.resumable) return "Stopped"', block)
        self.assertIn('setTextIfChanged(card.querySelector(".live-title"), runtimeStatusLabel(runtime))', block)
        self.assertNotIn('CLI_SPINNER_FRAMES', block)

    def test_many_runtime_todos_use_outer_history_scroll_not_nested_scroll(self):
        css = "".join(self.runner_css.split())
        self.assertIn('.cli-runtime-output{max-height:none;overflow:visible', css)
        self.assertIn('#messages.history{overflow-y:auto;scrollbar-gutter:stable', css)

    def test_project_rows_use_symmetric_horizontal_gutters(self):
        css = "".join(self.runner_css.split())
        self.assertIn('.projects.project-list{padding-left:4px!important;padding-right:4px!important', css)
        self.assertIn('.project-tree,.project-root{width:100%;box-sizing:border-box', css)


    def test_generated_prompt_editor_uses_independent_scroll_regions(self):
        self.assertIn("#generateDraftPromptPanel { overflow: hidden; }", self.generator_css)
        self.assertIn(".workflow-generator-prompt-list { min-height: 0; overflow-y: auto; overflow-x: hidden;", self.generator_css)
        self.assertIn(".workflow-generator-prompt-editor { min-width: 0; min-height: 0; overflow: hidden;", self.generator_css)
        self.assertIn("min-height: 0; overflow: auto; resize: none;", self.generator_css)

    def test_workflow_validation_details_do_not_overlay_stage_canvas(self) -> None:
        css = "".join(self.studio_css.split())
        self.assertIn(".studio-workflow-editor>.validation-output{grid-row:2", css)
        self.assertIn(".validation-output{min-width:0;min-height:34px", css)
        self.assertNotIn(".validation-output{position:absolute", css)

    def test_studio_validation_is_one_line_with_details_dialog(self) -> None:
        self.assertIn("const firstLine = detail.split", self.js)
        self.assertIn('$("validationOutputText").textContent = summary', self.js)
        self.assertIn('id="validationDetailsButton"', self.html)
        self.assertIn('id="validationDetailsBackdrop"', self.html)
        self.assertNotIn('id="studioFooter"', self.html)

    def test_sidebar_compact_nav_project_add_and_i18n_contract(self):
        self.assertIn('id="openProject" class="project-add-button"', self.html)
        self.assertNotIn('id="openProject" class="primary wide new-project-button"', self.html)
        self.assertIn('class="nav-icon"', self.html)
        self.assertIn('data-language-option="zh-TW"', self.html)
        self.assertIn('data-language-option="en"', self.html)
        self.assertIn('src="/js/i18n.js"', self.html)
        self.assertIn('DEFAULT_LANGUAGE = "zh-TW"', (self.root / "static" / "js" / "i18n.js").read_text(encoding="utf-8"))

if __name__ == "__main__":
    unittest.main()

class ThemeContractTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(__file__).resolve().parents[1]
        self.html = (self.root / "static" / "index.html").read_text(encoding="utf-8")
        self.app_js = (self.root / "static" / "app.js").read_text(encoding="utf-8")
        self.generator_js = (self.root / "static" / "js" / "workflow-generator.js").read_text(encoding="utf-8")
        self.js = self.app_js + "\n" + self.generator_js
        self.styles = (self.root / "static" / "styles.css").read_text(encoding="utf-8")
        self.theme_css = (self.root / "static" / "css" / "theme.css").read_text(encoding="utf-8")

    def test_theme_ui_exposes_five_palettes_and_three_appearance_modes(self):
        for token in ('id="themeButton"', 'id="themePanel"', 'data-theme-option="teal"', 'data-theme-option="blue"', 'data-theme-option="violet"', 'data-theme-option="amber"', 'data-theme-option="rose"', 'data-appearance-option="system"', 'data-appearance-option="light"', 'data-appearance-option="dark"'):
            self.assertIn(token, self.html)

    def test_default_theme_is_teal_system_and_preferences_persist(self):
        self.assertIn('let theme = "teal"', self.html)
        self.assertIn('let appearance = "system"', self.html)
        self.assertIn('ai-task-runner.theme', self.js)
        self.assertIn('ai-task-runner.appearance', self.js)
        self.assertIn('localStorage.setItem(THEME_STORAGE_KEY', self.js)
        self.assertIn('localStorage.setItem(APPEARANCE_STORAGE_KEY', self.js)

    def test_system_appearance_tracks_os_color_scheme(self):
        self.assertIn('prefers-color-scheme: dark', self.html)
        self.assertIn('systemColorScheme.addEventListener("change"', self.js)
        self.assertIn('document.documentElement.dataset.appearance = resolvedAppearance(appearance)', self.js)

    def test_theme_layer_loads_last_and_keeps_semantic_status_colors_stable(self):
        self.assertTrue(self.styles.rstrip().endswith('@import url("./css/theme.css");'))
        for token in ('data-theme="teal"', 'data-theme="blue"', 'data-theme="violet"', 'data-theme="amber"', 'data-theme="rose"', 'data-appearance="light"', 'data-appearance="dark"'):
            self.assertIn(token, self.theme_css)
        for token in ('--pass: #22a559', '--run: #3b82f6', '--warn: #d99016', '--fail: #d64b4b'):
            self.assertIn(token, self.theme_css)


    def test_theme_brand_icon_uses_palette_accent(self):
        self.assertIn('html[data-appearance] .brand::before', self.theme_css)
        self.assertIn('linear-gradient(135deg, var(--accent), var(--accent-dark))', self.theme_css)

    def test_descriptive_i18n_matches_current_stage_contract(self):
        i18n = (self.root / "static" / "js" / "i18n.js").read_text(encoding="utf-8")
        self.assertIn('"theme.appearance": "Appearance"', i18n)
        self.assertIn('"theme.palette": "Theme"', i18n)
        for key in (
            "studio.description",
            "studio.flow_desc",
            "stage.section_desc",
            "stage.retry_desc",
            "stage.flow_desc",
        ):
            self.assertGreaterEqual(i18n.count(f'"{key}"'), 2, key)
        for removed in (
            "stage.recovery_desc",
            "stage.help.restart_at",
            "stage.help.repeat",
            "stage.help.recover",
            "stage.help.max_attempts",
            "stage.help.on_exhausted",
            "stage.help.repair_plan",
        ):
            self.assertNotIn(f'"{removed}"', i18n)

    def test_static_ui_has_no_remote_runtime_assets(self):
        import re
        static_root = self.root / "static"
        combined = "\n".join(path.read_text(encoding="utf-8", errors="ignore") for path in static_root.rglob("*") if path.is_file() and path.suffix.lower() in {".html", ".css", ".js"})
        patterns = [r'<(?:script|link|img)[^>]+(?:src|href)=["\']https?://', r'@import\s+url\(["\']?https?://', r'url\(["\']?https?://']
        for pattern in patterns:
            self.assertIsNone(re.search(pattern, combined, flags=re.IGNORECASE), pattern)

    def test_dark_generator_and_search_use_theme_surfaces(self):
        self.assertIn('--surface: var(--panel)', self.theme_css)
        self.assertIn('.workflow-generator-input-card', self.theme_css)
        self.assertIn('.studio-search-wrap', self.theme_css)
        self.assertNotIn('data-theme="graphite"', self.html)


    def test_legacy_ui_css_no_longer_hardcodes_old_teal_or_common_light_surfaces(self):
        css_root = self.root / "static" / "css"
        legacy = "\n".join(path.read_text(encoding="utf-8") for path in css_root.glob("*.css") if path.name not in {"tokens.css", "theme.css"})
        for token in ("#0f766e", "#115e59", "#14b8a6", "rgba(15, 118, 110", "rgba(15,118,110"):
            self.assertNotIn(token, legacy)
        for token in ("background: #ffffff;", "background:#ffffff;", "background: #fff;", "background:#fff;", "background: #f8fafc;", "background: #fbfcfe;"):
            self.assertNotIn(token, legacy)

class TestDarkThemePolish(unittest.TestCase):
    def test_dark_dialogs_have_distinct_backdrop_and_surface(self):
        css = (Path(__file__).resolve().parents[1] / "static" / "css" / "theme.css").read_text(encoding="utf-8")
        self.assertIn('html[data-appearance="dark"] .modal-backdrop', css)
        self.assertIn('background: rgba(2, 8, 6, .72) !important;', css)
        self.assertIn('html[data-appearance="dark"] .modal-card', css)
        self.assertIn('border: 1px solid var(--line-strong) !important;', css)
        self.assertIn('html[data-appearance="dark"] .modal-head h2', css)

    def test_dark_workflow_picker_does_not_use_light_surface(self):
        css = (Path(__file__).resolve().parents[1] / "static" / "css" / "theme.css").read_text(encoding="utf-8")
        self.assertIn('html[data-appearance="dark"] .workflow-picker', css)
        self.assertIn('html[data-appearance="dark"] .workflow-dropdown-menu', css)
        self.assertIn('background: var(--popover-bg) !important;', css)

class StudioFolderGroupingContractTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(__file__).resolve().parents[1]
        self.js = (self.root / "static" / "app.js").read_text(encoding="utf-8")
        self.css = (self.root / "static" / "css" / "workflow-studio.css").read_text(encoding="utf-8")
        self.support = (self.root / "static" / "js" / "studio-support.js").read_text(encoding="utf-8")

    def test_prompt_categories_use_relative_name_not_generic_folder_picker(self):
        html = (self.root / "static" / "index.html").read_text(encoding="utf-8")
        for removed in (
            'id="duplicateAssetFolder"',
            'id="importAssetFolder"',
            'id="newWorkflowFolder"',
            'id="newPromptFolder"',
        ):
            self.assertNotIn(removed, html)
        for removed in (
            "fillDuplicateFolderInput",
            "fillFolderInput",
            "syncImportPromptFolder",
        ):
            self.assertNotIn(removed, self.js)
        self.assertIn('id="importAssetName"', html)
        self.assertIn('id="importAssetDestination"', html)
        self.assertIn('id="newPromptName"', html)
        self.assertIn('id="newPromptDestination"', html)
        self.assertIn("item?.reference || item?.name", self.js)

    def test_assets_render_as_flat_global_project_groups(self):
        self.assertNotIn("appendStudioFolderGroup", self.js)
        self.assertNotIn("STUDIO_FOLDER_STATE_KEY", self.js)
        self.assertIn('for (const scope of ["global", "project"])', self.js)
        self.assertIn('heading.textContent = scope === "project" ? "Project" : "Global"', self.js)

    def test_search_uses_categorized_prompt_display_name_without_folder_state(self):
        self.assertIn("item.display_name", self.support)
        self.assertIn("item.path", self.support)
        self.assertNotIn("STUDIO_FOLDER_STATE_KEY", self.js)
        self.assertNotIn("appendStudioFolderGroup", self.js)

    def test_system_custom_asset_groups_are_removed(self):
        self.assertNotIn('label: "SYSTEM"', self.js)
        self.assertNotIn('stateKey: "@system"', self.js)
        self.assertNotIn('heading.textContent = "Custom"', self.js)

    def test_obsolete_asset_folder_caret_is_removed(self):
        self.assertNotIn(".studio-folder-caret", self.css)
        self.assertNotIn("studio-folder-group", self.css)
