from pathlib import Path
import unittest


class StaticContractTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(__file__).resolve().parents[1]
        self.html = (self.root / "static" / "index.html").read_text(encoding="utf-8")
        self.app_js = (self.root / "static" / "app.js").read_text(encoding="utf-8")
        self.generator_js = (self.root / "static" / "js" / "workflow-generator.js").read_text(encoding="utf-8")
        self.js = self.app_js + "\n" + self.generator_js
        self.runner_css = (self.root / "static" / "css" / "runner-lite.css").read_text(encoding="utf-8")
        self.studio_css = (self.root / "static" / "css" / "workflow-studio.css").read_text(encoding="utf-8")

    def test_ui_does_not_import_runner_core(self):
        for path in self.root.rglob("*.py"):
            if "tests" in path.parts:
                continue
            text = path.read_text(encoding="utf-8")
            self.assertNotIn("from runner", text, str(path))
            self.assertNotIn("import runner", text, str(path))

    def test_primary_navigation_is_tasks_workflows_prompts_only(self):
        for token in ('id="chatNav"', 'id="workflowNav"', 'id="promptNav"'):
            self.assertIn(token, self.html)
        self.assertNotIn('id="settingsNav"', self.html)
        self.assertIn('id="themeButton"', self.html)
        self.assertIn('id="themePanel"', self.html)

    def test_workflow_library_is_management_only(self):
        for token in (
            'id="studioFileList"',
            'id="newWorkflowButton"',
            'id="importAssetButton"',
            'id="generateWorkflowButton"',
            'id="workflowContextMenu"',
            'id="workflowContextOpen"',
            'id="workflowContextVisibility"',
            'id="workflowContextRename"',
            'id="workflowContextDuplicate"',
            'id="workflowContextExport"',
            'id="workflowContextDelete"',
        ):
            self.assertIn(token, self.html)
        for legacy in (
            'id="visualDesignerPanel"',
            'id="yamlEditorPanel"',
            'id="addStageBackdrop"',
            'id="flowMapBackdrop"',
            'id="studioEditorModeSwitch"',
        ):
            self.assertNotIn(legacy, self.html)
        self.assertIn("openWorkflowEditorItem", self.app_js)

    def test_prompt_editor_remains_first_class_asset_editor(self):
        for token in (
            'id="promptEditorPanel"',
            'id="studioPromptTextarea"',
            'id="studioPromptParamList"',
            "Available Params",
        ):
            self.assertIn(token, self.html)
        for token in ("/api/studio/prompt-tags", "insertPromptTag", "/api/studio/prompt/check"):
            self.assertIn(token, self.js)

    def test_workflow_visibility_controls_chat_picker(self):
        self.assertIn('DEFAULT_WORKFLOW_NAME = "ralphy_ai_validate.yaml"', self.app_js)
        self.assertIn("setWorkflowVisibility", self.app_js)
        self.assertIn("workflowContextVisibility", self.app_js)
        self.assertIn("assets.show_in_chat", self.app_js)
        self.assertIn("assets.hide_from_chat", self.app_js)

    def test_manual_new_workflow_and_prompt_use_designed_modals(self):
        for token in (
            'id="newWorkflowBackdrop" class="modal-backdrop"',
            'class="modal-card workflow-create-card"',
            'id="newPromptBackdrop" class="modal-backdrop"',
        ):
            self.assertIn(token, self.html)
        self.assertIn("/api/studio/workflow/create", self.js)

    def test_import_export_and_crud_use_designed_controls(self):
        for token in (
            'id="importAssetButton"',
            'id="importAssetBackdrop"',
            'id="workflowContextExport"',
            'id="workflowContextDelete"',
        ):
            self.assertIn(token, self.html)
        self.assertIn("window.UiDialogs.confirm", self.js)
        self.assertNotIn("window.confirm", self.js)

    def test_environment_and_run_controls_remain_in_tasks_view(self):
        for token in (
            'id="environmentCheckButton"',
            'id="environmentCheckResult"',
            'id="workflowSelect"',
            'id="workflowDropdownButton"',
            'id="backendDropdownButton"',
            'id="clearHistoryButton"',
            'id="stopButton"',
            'id="resumeButton"',
            'id="resetButton"',
        ):
            self.assertIn(token, self.html)
        self.assertIn("/api/environment/check", self.js)

    def test_clear_history_is_disabled_while_selected_project_runs(self):
        self.assertIn('$("clearHistoryButton").disabled = Boolean(runtime.running)', self.js)
        self.assertIn('if (!state.project || state.runtime?.running) return;', self.js)

    def test_chat_history_and_floating_composer_layout_contract(self):
        css = "".join(self.runner_css.split())
        self.assertIn("grid-template-rows:autoautominmax(0,1fr)", css)
        self.assertIn("#chatView>.history{grid-row:3", css)
        self.assertIn("padding-bottom:calc(var(--composer-reserve)+18px)", css)
        self.assertIn("#chatView>.compose-panel{position:absolute;left:0;right:0;bottom:0", css)
        self.assertIn("height:100dvh", css)

    def test_workflow_library_and_prompt_workspace_scroll_internally(self):
        css = "".join(self.studio_css.split())
        self.assertIn("scrollbar-gutter:stable", css)
        self.assertIn(".studio-file-list", css)
        self.assertIn(".studio-prompt-panel", css)

    def test_generated_workflow_ui_has_dryrun_validation_path(self):
        self.assertIn("Generate with AI", self.html)
        self.assertIn("generateWorkflowValidate", self.html)
        self.assertIn("validateGeneratedWorkflowDraft", self.generator_js)
        self.assertIn("/api/studio/generate/validate", self.generator_js)

    def test_interface_language_and_theme_share_settings_panel(self):
        for token in (
            'data-language-option="zh-TW"',
            'data-language-option="en"',
            'data-theme-option="teal"',
            'data-appearance-option="system"',
        ):
            self.assertIn(token, self.html)
        self.assertIn("app-language-changed", self.app_js)


    def test_quick_win_status_and_empty_state_contract(self):
        self.assertIn('id="emptyOpenProjectButton"', self.html)
        self.assertIn('Needs Attention', self.app_js)
        self.assertIn('path.textContent = project.exists === false ? t("project.missing", "Missing") : "Ready"', self.app_js)
        self.assertIn('clear.textContent = "Clear search"', self.app_js)
        self.assertIn('create.textContent = state.studioSourceKind === "prompt" ? "Create Prompt" : "Create Workflow"', self.app_js)


    def test_prompt_editor_exposes_saved_saving_unsaved_feedback(self):
        self.assertIn('dirtyBadge.textContent = state.studioSaving ? "SAVING" : state.studioDirty ? "UNSAVED" : "SAVED"', self.app_js)
        self.assertIn('"No unsaved changes."', self.app_js)
        self.assertIn('"Save changes (Ctrl+S)."', self.app_js)


    def test_runtime_header_uses_durable_state_evidence(self):
        self.assertIn('id="runtimeHeadline"', self.html)
        self.assertIn('runtime.last_transition', self.app_js)
        self.assertIn('runtime.cycle', self.app_js)
        self.assertIn('Last ·', self.app_js)


    def test_runtime_status_vocabulary_distinguishes_recovery_and_attention(self):
        self.assertIn('return "Recovering"', self.app_js)
        self.assertIn('return "Needs Attention"', self.app_js)
        self.assertIn('recovering: "Recovering"', self.app_js)
        self.assertIn('needs_attention: "Needs Attention"', self.app_js)
        self.assertNotIn('return "Interrupted"', self.app_js)


    def test_runtime_freshness_keeps_relative_text_with_exact_tooltip(self):
        self.assertIn("new Date(state.runtimeLastChangedAt).toLocaleString()", self.app_js)
        self.assertIn('last.title = exact ? "Last update: " + exact : ""', self.app_js)
        self.assertIn('live.title = exact ? "Last update: " + exact : ""', self.app_js)


    def test_quick_win_control_hierarchy_scroll_and_long_name_contract(self):
        self.assertIn('id="sendButton" class="primary send-button"', self.html)
        self.assertIn('id="stopButton" class="action-button danger runtime-control-button"', self.html)
        self.assertIn('id="resetButton" class="action-button runtime-control-button"', self.html)
        self.assertIn('title="Save changes (Ctrl+S)"', self.html)
        self.assertIn('title="Reload saved asset"', self.html)
        self.assertIn('const previousScrollTop = root?.scrollTop || 0', self.app_js)
        self.assertIn('root.scrollTop = previousScrollTop', self.app_js)
        self.assertIn('name.title = item.name', self.app_js)
        self.assertIn('button.title = item.name', self.app_js)
        self.assertIn('"Continue or Reset the stopped task before starting another."', self.app_js)

    def test_runtime_freshness_is_relative_with_exact_timestamp_tooltip(self):
        self.assertIn('function formatFreshness(ts)', self.app_js)
        self.assertIn('new Date(state.runtimeLastChangedAt).toLocaleString()', self.app_js)
        self.assertIn('last.title = exact ? "Last update: " + exact : ""', self.app_js)


    def test_prompt_editor_shows_used_by_workflow_stage_evidence(self):
        self.assertIn('id="studioPromptUsedBy"', self.html)
        self.assertIn("function renderPromptUsage()", self.app_js)
        self.assertIn("state.studioFile?.used_by", self.app_js)


    def test_workflow_library_shows_modified_freshness(self):
        self.assertIn("const modifiedAt = Number(item.mtime || 0) * 1000", self.app_js)
        self.assertIn("Modified:", self.app_js)


if __name__ == "__main__":
    unittest.main()
