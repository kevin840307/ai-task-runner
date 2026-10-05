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
        self.assertIn('$("clearHistoryButton").disabled = isRunning', self.js)
        self.assertIn('const isRunning = Boolean(actions.stop)', self.js)
        self.assertIn('if (!state.project || state.runtime?.actions?.stop) return;', self.js)

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
        self.assertIn('runtime?.view?.label || runtime?.status || "Idle"', self.app_js)
        self.assertIn('status === "recovering"', self.app_js)
        self.assertIn('status === "needs_attention"', self.app_js)
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


    def test_recent_runs_uses_existing_project_history_and_runtime_surface(self):
        self.assertIn('id="runHistoryButton"', self.html)
        self.assertIn('id="runHistoryPanel"', self.html)
        self.assertIn('id="runHistoryList"', self.html)
        self.assertIn("function refreshRunHistory(", self.app_js)
        self.assertIn("/api/project/runs?project=", self.app_js)
        self.assertIn("item.dataset.runId = String(message.run_id)", self.app_js)
        self.assertIn("setRunHistoryOpen(false)", self.app_js)




    def test_studio_action_feedback_is_inline_and_persistent(self):
        self.assertIn('id="studioStatus"', self.html)
        self.assertIn('row = $("studioStatus")', self.app_js)
        self.assertIn('row.hidden = !detail', self.app_js)
        self.assertIn('row.classList.toggle("error"', self.app_js)



    def test_icon_only_controls_have_accessible_names_and_tooltips(self):
        self.assertIn('id="newWorkflowButton" class="mini-button" type="button" title="New asset" aria-label="Create new asset"', self.html)
        self.assertIn('id="optionsCloseButton" type="button" aria-label="Close options" title="Close options"', self.html)
        self.assertIn('id="themeCloseButton" type="button" aria-label="關閉介面設定" title="Close"', self.html)
        self.assertIn('id="validationDetailsClose" class="modal-close" type="button" aria-label="Close" title="Close"', self.html)



    def test_shared_confirmation_dialog_contract_is_consistent(self):
        dialogs = (self.root / "static" / "js" / "ui-dialogs.js").read_text(encoding="utf-8")
        cancel = dialogs.index('data-dialog-cancel')
        confirm = dialogs.index('data-dialog-ok class=')
        self.assertLess(cancel, confirm)
        self.assertIn('danger ? "designer-danger-button" : "primary"', dialogs)
        self.assertIn('if (event.key === "Escape")', dialogs)
        self.assertIn('requestAnimationFrame(() => trigger.focus())', dialogs)

    def test_no_static_contract_tests_are_defined_after_main_guard(self):
        source = Path(__file__).read_text(encoding="utf-8")
        main = source.rfind('\nif __name__ == "__main__":\n')
        self.assertGreaterEqual(main, 0)
        self.assertNotIn("\n    def test_", source[main:])


    def test_prompt_draft_recovery_is_hash_gated_and_local_only(self):
        self.assertIn('PROMPT_DRAFT_PREFIX = "ai-task-runner:prompt-draft:v1:"', self.app_js)
        self.assertIn("draft.hash !== data.hash", self.app_js)
        self.assertIn('"Restore Draft"', self.app_js)
        self.assertIn('"Discard Draft"', self.app_js)
        self.assertIn("clearPromptDraft(data.id)", self.app_js)
        self.assertIn("persistPromptDraft(); scheduleSyntaxCheck()", self.app_js)


    def test_shared_dialog_icon_close_has_accessible_tooltip(self):
        dialogs = (self.root / "static" / "js" / "ui-dialogs.js").read_text(encoding="utf-8")
        self.assertIn('data-dialog-close aria-label="Close" title="Close"', dialogs)
        self.assertIn('danger ? "designer-danger-button" : "primary"', dialogs)


    def test_runtime_trace_uses_bounded_existing_runtime_evidence(self):
        self.assertIn('id="runtimeTraceButton"', self.html)
        self.assertIn('id="runtimeTracePanel"', self.html)
        self.assertIn('id="runtimeTraceList"', self.html)
        self.assertIn("function renderRuntimeTrace(", self.app_js)
        self.assertIn("runtime?.recent_transitions", self.app_js)
        self.assertIn("setRuntimeTraceOpen(false)", self.app_js)
        self.assertNotIn("/api/project/trace", self.app_js)


    def test_prompt_used_by_height_is_bounded(self):
        css = (self.root / "static" / "css" / "workflow-studio.css").read_text(encoding="utf-8")
        self.assertIn(".prompt-used-by-list", css)
        self.assertIn("max-height: 92px", css)
        self.assertIn("overflow: auto", css)


if __name__ == "__main__":
    unittest.main()


def test_main_ui_consumes_canonical_runtime_status_actions_and_dedupes_polling():
    root = Path(__file__).resolve().parents[1]
    app = (root / "static" / "app.js").read_text(encoding="utf-8")
    server = (root / "server.py").read_text(encoding="utf-8")

    overlay = app.split("function applySelectedRuntimeToProjectList", 1)[1].split("async function refreshProjectStatuses", 1)[0]
    assert 'current.runtime_status = String(runtime.status || "idle")' in overlay
    assert "runtime.last_error ? \"recovering\"" not in overlay
    assert 'runtime.actions && typeof runtime.actions === "object"' in app
    assert 'actions.run === false' in app
    assert '?exclude_runtime=' in app
    assert 'query.get("exclude_runtime", [""])[0]' in server
    assert 'if (state.view === "workflow" || state.view === "prompt") work.push(refreshStudioGuard())' in app
    assert 'if (token !== state.runtimeRefreshToken || !sameProjectPath(state.project?.path, projectPath)) return;' in app


def test_runtime_attention_stays_actionable_without_permanent_active_run_details():
    root = Path(__file__).resolve().parents[1]
    index = (root / "static" / "index.html").read_text(encoding="utf-8")
    app = (root / "static" / "app.js").read_text(encoding="utf-8")

    for control in ("runtimeGuidance", "runtimeGuidanceWorkflow", "runtimeGuidanceTrace"):
        assert f'id="{control}"' in index
    assert 'id="activeRunDetails"' not in index
    assert "function renderActiveRunDetails" not in app
    assert 'recommended.includes("open_workflow")' in app
    assert 'recommended.includes("view_trace")' in app
    assert '$("workflowNav")?.click()' in app
    assert '$("runtimeTraceButton")?.click()' in app
    # Runtime snapshot remains part of the canonical projection/signature for
    # resume/frozen-run correctness; only the space-consuming presentation is removed.
    assert "runtime.run_snapshot || {}" in app


def test_task_validation_resources_are_workflow_declared_and_not_global():
    root = Path(__file__).resolve().parents[1]
    index = (root / "static" / "index.html").read_text(encoding="utf-8")
    app = (root / "static" / "app.js").read_text(encoding="utf-8")

    assert '<div id="validationPickers" class="composer-validation-row options-validation-row" hidden>' in index
    assert '<div id="validatorPicker" class="validator-picker composer-validator-picker composer-resource-picker" hidden>' in index
    assert '<div id="aiValidatorPromptPicker" class="validator-picker composer-validator-picker composer-ai-prompt-picker composer-resource-picker" hidden>' in index
    assert "File Validator" in index
    assert "AI Validator Prompt" in index
    assert 'validationPickers.hidden = !(workflow?.requires_python_validator || workflow?.has_ai_validator)' in app
    assert 'validatorPicker.hidden = !workflow?.requires_python_validator' in app
    assert 'aiPromptPicker.hidden = !workflow?.has_ai_validator' in app
    assert 'validator: workflow?.requires_python_validator ? $("validator").value.trim() : ""' in app
    assert 'ai_validator_prompt_file: workflow?.has_ai_validator ? $("aiValidatorPrompt").value.trim() : ""' in app


def test_chat_validator_resource_pickers_share_context_aware_browse_flow():
    root = Path(__file__).resolve().parents[1]
    static = root / "static"
    app = (static / "app.js").read_text(encoding="utf-8")
    html = (static / "index.html").read_text(encoding="utf-8")
    server = (root / "server.py").read_text(encoding="utf-8")

    assert "async function browseValidationResource" in app
    assert 'project: state.project?.path || ""' in app
    assert 'current: $(inputId)?.value?.trim() || ""' in app
    assert 'kind: "python"' in app
    assert 'kind: "markdown"' in app
    assert "File Validator" in html
    assert "AI Validator Prompt" in html
    assert html.count(">Choose</button>") >= 2
    assert 'project=str(body.get("project", ""))' in server
    assert 'current=str(body.get("current", ""))' in server
    assert 'options["initialdir"] = initialdir' in server
