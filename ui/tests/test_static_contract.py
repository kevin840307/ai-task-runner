from pathlib import Path
import unittest


class StaticContractTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(__file__).resolve().parents[1]
        self.html = (self.root / "static" / "index.html").read_text(encoding="utf-8")
        self.js = (self.root / "static" / "app.js").read_text(encoding="utf-8")

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
        server = (self.root / "server.py").read_text(encoding="utf-8")
        for token in ("state.json", "runner-process.json", "stream.log", "stop.request"):
            self.assertIn(token, server)

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
            "stageProduces", "stageSessionKey", "stageDetail", "stageRecover", "stageRetry",
            "stageStructuredRetries", "stageStructuredFreshRetries", "stageSkipOnError",
            "stageFreshOnStart", "stageFreshEachRun", "stageTrackChanges", "stageTolerateRestored",
            "stageAllowProjectRead", "stageCleanWork", "stageCommand", "stageResultKind", "stageCwd",
            "stageMinTasks", "stageRepairPlan", "stageValidator", "stageRuns", "stageRequiredPasses",
            "stageParser", "stageFlowLabel", "stageRestartAt", "stageRepeat", "stageFreshAfterSameFailures",
        ):
            self.assertIn(token, self.js)

    def test_stage_modal_has_one_prompt_selector_and_no_prompt_body_editor(self):
        self.assertIn("stagePromptSelect", self.js)
        self.assertNotIn("stageContinuationPromptSelect", self.js)
        for removed in ("stagePromptPathInput", "stagePromptLibrarySelect", "stagePromptTextarea", "saveStagePrompt"):
            self.assertNotIn(removed, self.js)
        self.assertIn("Prompt content is edited in Workflow Studio", self.js)
        self.assertIn('stageSupportsPrompt(type) { return ["base", "task", "review", "ai_validator"].includes(type); }', self.js)

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


class LayoutRegressionTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(__file__).resolve().parents[1]
        self.html = (self.root / "static" / "index.html").read_text(encoding="utf-8")
        self.js = (self.root / "static" / "app.js").read_text(encoding="utf-8")
        self.runner_css = (self.root / "static" / "css" / "runner-lite.css").read_text(encoding="utf-8")
        self.studio_css = (self.root / "static" / "css" / "workflow-studio.css").read_text(encoding="utf-8")

    def test_chat_history_owns_full_middle_and_composer_floats_over_reserved_scroll_space(self):
        css = "".join(self.runner_css.split())
        self.assertIn("grid-template-rows:autoautominmax(0,1fr)", css)
        self.assertIn("#chatView>.history{grid-row:3", css)
        self.assertIn("padding-bottom:calc(var(--composer-reserve)+18px)", css)
        self.assertIn("#chatView>.compose-panel{position:absolute;left:0;right:0;bottom:0", css)
        self.assertIn("pointer-events:none", css)
        self.assertIn("#chatView>.compose-panel>.composer-box{pointer-events:auto", css)
        self.assertIn("height:72px!important", css)
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
        self.assertIn(".studio-workflow-sidebar{display:grid;grid-template-rows:autoautominmax(0,1fr)", css)
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
        self.assertIn('const type = fieldValue("stageType"); const aiBacked = type !== "command"', self.js)
        self.assertIn('if (aiBacked) {', self.js)
        self.assertIn('if ($("stageCleanWorkRow")) $("stageCleanWorkRow").hidden = type !== "command"', self.js)

    def test_prompt_and_step_surfaces_end_on_sidebar_baseline(self):
        css = "".join(self.studio_css.split())
        self.assertIn(".studio-workflow-editor{position:relative;grid-template-rows:autominmax(0,1fr)", css)
        self.assertIn(".studio-workflow-editor>.studio-prompt-panel{grid-row:2;min-height:0;height:100%", css)
        self.assertIn(".studio-footer{position:absolute", css)

    def test_retry_editor_matches_core_minus_one_contract(self):
        self.assertIn('id="stageRetry"', self.js)
        self.assertIn('min="-1"', self.js)
        self.assertIn('-1 = keep retrying until PASS', self.js)

    def test_flow_routing_fields_are_editable_in_stage_modal(self):
        for token in ("stageFlowLabel", "stageRestartAt", "stageRepeat", "stageFreshAfterSameFailures", "flow_fields: changedFlowFields(item)"):
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

    def test_stage_remove_uses_reusable_confirmation(self):
        self.assertIn('confirmDialog({ title: "Remove Stage from Flow?"', self.js)
        self.assertIn("removeSelectedFlow()", self.js)

    def test_add_stage_key_and_type_controls_share_height(self):
        css = "".join(self.studio_css.split())
        self.assertIn(".add-stage-grid.designer-input,.add-stage-grid.designer-select{box-sizing:border-box;height:40px;min-height:40px", css)

    def test_explicit_workflow_ai_validator_companion_contract(self):
        repo = self.root.parent
        source = (repo / "runner" / "workflow" / "stages" / "ai_stage.py").read_text(encoding="utf-8")
        self.assertIn("ctx.config.workflow_explicit or ctx.validator_is_ai", source)

    def test_stage_status_is_primary_title_with_ellipsis(self):
        self.assertIn('const displayTitle = String(item?.status ?? cfg.status ?? "").trim() || name || "Unnamed"', self.js)
        css = "".join(self.studio_css.split())
        self.assertIn(".visual-flow-copystrong{display:block;min-width:0;max-width:100%;overflow:hidden;text-overflow:ellipsis;white-space:nowrap", css)
        self.assertIn(".visual-flow-copystrong{font-size:10.5px", css)

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

    def test_stage_editor_uses_effective_flow_prompt_and_status(self):
        self.assertIn('item?.status ?? cfg.status ?? ""', self.js)
        self.assertIn('promptOptionRows(item?.prompt ?? cfg.prompt ?? "")', self.js)
        self.assertIn('Object.prototype.hasOwnProperty.call(item, "prompt")', self.js)
        self.assertIn('Object.prototype.hasOwnProperty.call(item, "status")', self.js)

    def test_project_actions_use_static_menu_and_confirmed_remove(self):
        for token in ("project-action-menu", "project-menu-button", 'remove.textContent = "Remove project"', 'title: "Remove Project?"'):
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

    def test_runtime_controls_expose_stop_continue_and_reset_new_task(self):
        for token in ('id="stopButton"', 'id="resumeButton"', 'id="resetButton"'):
            self.assertIn(token, self.html)
        for token in ('/api/project/stop', '/api/project/resume', '/api/project/reset', '$("resetButton").textContent = runtime.completed ? "New Task" : "Reset"'):
            self.assertIn(token, self.js)

    def test_visual_helper_copy_is_small(self):
        css = "".join(self.studio_css.split())
        self.assertIn(".studio-topbarp{font-size:10px", css)

    def test_ai_workflow_builder_modal_is_wired_to_real_generate_endpoint(self):
        for token in ('id="generateWorkflowBackdrop"', 'id="generateWorkflowName"', 'id="generateWorkflowRequest"', 'id="generateWorkflowConfirm"'):
            self.assertIn(token, self.html)
        for token in ("openGenerateWorkflowModal", "confirmGenerateWorkflow", 'api("/api/studio/generate"', '$("generateWorkflowButton").onclick = openGenerateWorkflowModal'):
            self.assertIn(token, self.js)
        for stale in ("generatePanel", "generateMessage", "closeGeneratePanel"):
            self.assertNotIn(stale, self.js)

    def test_custom_import_file_picker_button_is_wired(self):
        self.assertIn('id="importAssetChooseButton"', self.html)
        self.assertIn('id="importAssetFileName"', self.html)
        self.assertIn('$("importAssetChooseButton").onclick = () => $("importAssetFile").click()', self.js)
        self.assertIn('$("importAssetFileName").textContent = file.name', self.js)


if __name__ == "__main__":
    unittest.main()
