from pathlib import Path
import unittest


class StaticContractTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(__file__).resolve().parents[1]
        self.html = (self.root / "static" / "index.html").read_text(encoding="utf-8")
        self.app_js = (self.root / "static" / "app.js").read_text(encoding="utf-8")
        self.generator_js = (self.root / "static" / "js" / "workflow-generator.js").read_text(encoding="utf-8")
        self.task_workspace_js = (self.root / "static" / "js" / "task-workspace.js").read_text(encoding="utf-8")
        self.task_runtime_js = (self.root / "static" / "js" / "task-runtime-panel.js").read_text(encoding="utf-8")
        self.tasks_board_js = (self.root / "static" / "js" / "tasks-board.js").read_text(encoding="utf-8")
        self.js = self.app_js + "\n" + self.generator_js + "\n" + self.task_workspace_js + "\n" + self.task_runtime_js + "\n" + self.tasks_board_js
        self.runner_css = (self.root / "static" / "css" / "runner-lite.css").read_text(encoding="utf-8")
        self.studio_css = (self.root / "static" / "css" / "workflow-studio.css").read_text(encoding="utf-8")

    def test_task_editor_geometry_tracks_feature_prototype(self):
        feature_root = self.root.parent / "feature" / "ui-prototype"
        feature_css = (feature_root / "styles.css").read_text(encoding="utf-8")
        feature_template = (feature_root / "task-ui-templates.js").read_text(encoding="utf-8")
        production_css = (self.root / "static" / "css" / "task-workspace.css").read_text(encoding="utf-8")

        # Feature source of truth: Project / Workflow / Title share the desktop basics row,
        # Prompt + validation own one input grid, mixed validation becomes a 2-card row,
        # Workspace is secondary, and the shared task workspace route is 920px.
        for token in (
            "grid-template-columns:minmax(250px,1.45fr) minmax(175px,.92fr) minmax(140px,.72fr)",
            "grid-template-columns:minmax(0,1.34fr) minmax(245px,.86fr)",
            "grid-template-columns:repeat(2,minmax(0,1fr))",
            "min-height:118px",
            "min-height:58px",
            "padding:7px 8px",
            "width:min(920px,94vw)",
        ):
            self.assertIn(token, feature_css, token)
            self.assertIn(token, production_css, token)

        project_i = feature_template.index("task-project-field")
        workflow_i = feature_template.index("task-workflow-field")
        title_i = feature_template.index("task-title-field")
        prompt_i = feature_template.index("newTaskPromptSource")
        validation_i = feature_template.index("newTaskValidationSource")
        workspace_i = feature_template.index("workspace-selector-wrap")
        self.assertLess(project_i, workflow_i)
        self.assertLess(workflow_i, title_i)
        self.assertLess(title_i, prompt_i)
        self.assertLess(prompt_i, validation_i)
        self.assertLess(validation_i, workspace_i)

        production = self.task_workspace_js
        self.assertLess(production.index("grid.append(projectField, workflowField, titleField)"), production.index("body.appendChild(workflowCaps)"))
        self.assertLess(production.index("body.appendChild(workflowCaps)"), production.index("body.appendChild(inputGrid)"))
        self.assertLess(production.index("body.appendChild(inputGrid)"), production.index("body.appendChild(workspaceSection)"))
        self.assertIn("task-workspace-project-combobox", production)
        self.assertIn("task-workspace-project-dropdown", production)
        self.assertIn("projectEditable = state.kind === \"draft\"", production)
        self.assertIn("project-combobox", feature_template)
        self.assertIn("project-dropdown", feature_template)
        self.assertIn("Choose how this task gets its prompt", production)
        self.assertIn('source.aiMode === "default" ? "Workflow default" : "Custom prompt source"', production)
        self.assertIn("Manual path is used as-is. Upload fills this field with the managed target path immediately", production)

    def test_task_list_workspace_tracks_feature_prototype(self):
        feature_css = (self.root.parent / "feature" / "ui-prototype" / "styles.css").read_text(encoding="utf-8")
        feature_template = (self.root.parent / "feature" / "ui-prototype" / "task-ui-templates.js").read_text(encoding="utf-8")
        production_css = (self.root / "static" / "css" / "task-workspace.css").read_text(encoding="utf-8")

        for token in (
            "grid-template-columns:minmax(0,1fr) 260px",
            "gap:14px",
            "padding:14px",
            "min-height:42px",
            "border:1px dashed var(--line-strong)",
        ):
            self.assertIn(token, feature_css, token)
            self.assertIn(token, production_css, token)

        self.assertIn("plan-side-card", feature_template)
        self.assertIn("plan-add-task-footer", feature_template)
        self.assertIn("emptyTaskList", feature_template)
        self.assertIn("task-workspace-list-side-card", self.task_workspace_js)
        self.assertIn("task-workspace-add-task-footer", self.task_workspace_js)
        self.assertIn("task-workspace-empty-list-cta", self.task_workspace_js)
        self.assertIn("taskWorkspaceHeaderMoveExisting", self.task_workspace_js)
        self.assertIn("taskWorkspaceHeaderYaml", self.task_workspace_js)
        self.assertIn("taskWorkspaceHeaderCreateList", self.task_workspace_js)
        self.assertIn("/api/tasks/move-existing", self.task_workspace_js)
        self.assertIn("Only standalone New Tasks can be moved", self.task_workspace_js)
        self.assertIn("items: list ? [] : [blankItem(projectPath, defaultWorkflow)]", self.task_workspace_js)
        self.assertIn('if (state?.kind === "task" && items.length <= 1) return;', self.task_workspace_js)

    def test_ui_does_not_import_runner_core(self):
        for path in self.root.rglob("*.py"):
            if "tests" in path.parts:
                continue
            text = path.read_text(encoding="utf-8")
            self.assertNotIn("from runner", text, str(path))
            self.assertNotIn("import runner", text, str(path))

    def test_task_board_lifecycle_and_no_top_level_worktree_contract(self):
        self.assertIn('const LIFECYCLES = ["new", "ongoing", "paused", "closed"]', self.tasks_board_js)
        for suffix in ("New", "Ongoing", "Paused", "Closed"):
            self.assertIn(f'id="tasksBoard{suffix}"', self.html)
            self.assertIn(f'id="tasksBoard{suffix}Count"', self.html)
        self.assertNotIn('id="worktreeNav"', self.html)
        self.assertNotIn('id="worktreeView"', self.html)
        self.assertNotIn('data-view="worktree"', self.html)

    def test_primary_navigation_is_tasks_workflows_prompts_only(self):
        for token in ('id="chatNav"', 'id="workflowNav"', 'id="promptNav"'):
            self.assertIn(token, self.html)
        self.assertNotIn('id="settingsNav"', self.html)
        self.assertIn('id="themeButton"', self.html)
        self.assertIn('id="themePanel"', self.html)

    def test_project_chat_and_task_api_capability_surface_is_complete(self):
        server = (self.root / "server.py").read_text(encoding="utf-8")
        for endpoint in (
            "/api/chat/sessions",
            "/api/chat/session/create",
            "/api/chat/session/select",
            "/api/chat/session/rename",
            "/api/chat/session/delete",
            "/api/chat/messages",
            "/api/chat/turn",
            "/api/chat/turn/cancel",
            "/api/chat/events",
            "/api/chat/settings-catalog",
            "/api/chat/capabilities",
            "/api/chat/queue",
            "/api/chat/queue/update",
            "/api/chat/queue/delete",
            "/api/chat/ask",
            "/api/chat/ask/submit",
            "/api/chat/ask/cancel",
            "/api/chat/task-draft",
            "/api/tasks/validate-draft",
            "/api/tasks/create-from-draft",
            "/api/tasks/workspace-options",
            "/api/tasks/move-existing",
            "/api/tasks/merge",
            "/api/tasks/publish",
            "/api/tasks/cleanup",
        ):
            self.assertIn(endpoint, server)
        self.assertIn("function mergeChatPrompt", self.task_workspace_js)
        self.assertNotIn("/api/chat/queue/reorder", server)

    def test_api_errors_use_structured_contract(self):
        self.assertIn('data?.message || `HTTP ${response.status}`', self.app_js)
        self.assertIn('error.code = String(data?.code || "http_error")', self.app_js)
        self.assertIn('error.retryable = Boolean(data?.retryable)', self.app_js)
        self.assertIn('error.requestId = String(data?.request_id || "")', self.app_js)
        self.assertNotIn("data.error ||", self.app_js)

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
        self.assertIn('class="backend-picker-chevron" aria-hidden="true"></span>', self.html)
        self.assertNotIn('backend-picker-chevron" aria-hidden="true">⌄</span>', self.html)
        self.assertIn("environment-check-toggle", self.app_js)
        self.assertIn("environment-check-details", self.app_js)
        self.assertIn(".backend-picker-chevron::before", self.runner_css)

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


    def test_running_is_the_single_execution_observation_surface(self):
        self.assertNotIn('id="runHistoryButton"', self.html)
        self.assertNotIn('id="runHistoryPanel"', self.html)
        self.assertNotIn("/api/project/runs?project=", self.app_js)
        self.assertNotIn("function refreshRunHistory(", self.app_js)
        self.assertIn('class="runtime-activity"', self.app_js)
        self.assertIn("function renderRuntimeActivity(", self.app_js)
        self.assertIn("runtime.activity_summary || []", self.app_js)




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


    def test_trace_panel_is_removed_in_favor_of_running_activity(self):
        self.assertNotIn('id="runtimeTraceButton"', self.html)
        self.assertNotIn('id="runtimeTracePanel"', self.html)
        self.assertNotIn("function renderRuntimeTrace(", self.app_js)
        self.assertNotIn("runtimeGuidanceTrace", self.html)
        self.assertNotIn("/api/project/trace", self.app_js)
        self.assertIn("function renderRuntimeActivity(", self.app_js)


    def test_task_info_drawer_has_fixed_four_tab_contract(self):
        self.assertIn('for (const id of ["overview", "runtime", "output", "history"])', self.task_workspace_js)
        self.assertIn('state.kind === "task"', self.task_workspace_js)
        self.assertIn('renderTaskRuntimePanel({', self.task_workspace_js)
        self.assertIn('renderEmpty({ body, tr, titleKey: "task.no_runtime"', self.task_runtime_js)
        self.assertIn(
            'tr("task.no_runtime_copy", "Runtime data appears only after an explicit Run action.")',
            self.task_runtime_js,
        )
        self.assertIn('id="taskWorkspaceExpand"', self.task_workspace_js)
        self.assertIn('classList.toggle("expanded"', self.task_workspace_js)
        self.assertIn("export function renderTaskRuntimePanel(", self.task_runtime_js)
        self.assertIn("task?.runner_runtime", self.task_runtime_js)
        self.assertIn("Array.isArray(runtime.cli_lines)", self.task_runtime_js)
        self.assertIn("Array.isArray(task?.history)", self.task_runtime_js)
        self.assertNotIn("api(", self.task_runtime_js)
        self.assertIn('api("/api/tasks?project=" + encodeURIComponent(project)', self.task_workspace_js)
        self.assertNotIn('["overview", "steps",', self.task_workspace_js)
        self.assertNotIn('textContent = "Steps"', self.task_workspace_js)

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


def test_runtime_attention_stays_actionable_without_separate_trace_or_run_panels():
    root = Path(__file__).resolve().parents[1]
    index = (root / "static" / "index.html").read_text(encoding="utf-8")
    app = (root / "static" / "app.js").read_text(encoding="utf-8")

    for control in ("runtimeGuidance", "runtimeGuidanceWorkflow"):
        assert f'id="{control}"' in index
    for removed in ("runtimeGuidanceTrace", "runtimeTraceButton", "runHistoryButton"):
        assert removed not in index
        assert removed not in app
    assert 'id="activeRunDetails"' not in index
    assert "function renderActiveRunDetails" not in app
    assert 'recommended.includes("open_workflow")' in app
    assert '$("workflowNav")?.click()' in app
    assert "runtime.run_snapshot || {}" in app
    assert "runtime.activity_summary || []" in app


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


def test_mixed_validation_resource_pickers_have_independent_two_row_height():
    root = Path(__file__).resolve().parents[1]
    css = (root / "static" / "css" / "runner-lite.css").read_text(encoding="utf-8")

    assert ".options-validation-row" in css
    assert "gap: 8px" in css
    assert "width: auto" in css
    assert "justify-self: stretch" in css
    assert ".options-validation-row .composer-resource-picker" in css
    assert "height: auto" in css
    assert "min-height: 72px" in css
    assert "margin: 0" in css
    assert "grid-template-rows: minmax(18px, auto) minmax(32px, auto)" in css
    assert "row-gap: 6px" in css
    assert ".options-validation-row .composer-resource-picker > input" in css
    assert "position: absolute !important" in css
    assert "text-overflow: ellipsis" in css
    assert "min-width: 70px" in css
    assert "max-width: calc(100% - 78px)" in css
    assert "overflow: hidden !important" in css
    assert "#composePanel .options-button" in css
    assert "flex: 0 0 auto" in css


def test_feature_reference_sidebar_and_task_filter_geometry_stays_in_sync():
    root = Path(__file__).resolve().parents[1]
    static = root / "static"
    index = (static / "index.html").read_text(encoding="utf-8")
    projects = (static / "css" / "projects.css").read_text(encoding="utf-8")
    tasks = (static / "css" / "tasks-board.css").read_text(encoding="utf-8")
    chat = (static / "css" / "project-chat.css").read_text(encoding="utf-8")
    modal = (static / "css" / "modal.css").read_text(encoding="utf-8")
    theme = (static / "css" / "theme.css").read_text(encoding="utf-8")
    workspace = (static / "css" / "task-workspace.css").read_text(encoding="utf-8")

    assert index.index('id="openProject"') < index.index('id="chatNav"')
    assert 'class="projects-head brandrow"' in index
    assert 'class="brandmark"' in index
    assert 'class="navgroup-label" data-i18n="nav.work"' in index
    assert 'class="navgroup-label" data-i18n="nav.assets"' in index
    assert 'class="sidebar-scroll"' in index
    assert 'class="project-area"' in index
    assert 'id="projectSwitcherPath" class="project-current-path"' in index
    assert '<span class="nav-icon" aria-hidden="true">▦</span>' in index
    assert '<span class="nav-icon" aria-hidden="true">◇</span>' in index
    assert '<span class="nav-icon" aria-hidden="true">¶</span>' in index
    assert 'class="tasks-project-chevron"' in index
    assert 'class="stateful-content" id="tasksProjectFilterSummary"' in index

    assert "height:38px" in projects
    assert "min-height:36px" in projects
    assert "min-height:42px" in projects
    assert ".projects .sidebar-scroll" in projects
    assert "overflow-y:auto" in projects
    assert ".projects .project-area" in projects
    assert ".project-current-path" in projects
    assert "overflow:visible" in projects
    assert "overflow-x:visible" in projects
    assert "overflow-y:visible" in projects
    assert "height:34px" in tasks
    assert "width:145px" in tasks
    assert "width:310px" in tasks
    assert 'input[type="checkbox"]' in tasks
    assert "grid-template-columns:repeat(4,minmax(245px,1fr))" in tasks
    assert 'id="tasksRunningCount"' in index
    assert 'id="tasksRunningFilterButton"' in index
    assert 'id="tasksNewColumnButton"' in index
    assert 'class="tasks-move-rule"' in index
    assert ".tasks-running-pill" in tasks
    assert ".tasks-column-add" in tasks
    assert "width:30px" in chat
    assert "height:30px" in chat
    assert "width: min(330px, calc(100vw - 20px))" in chat
    assert "max-width: 900px" in chat
    assert ".projects .brand::before{display:none!important;content:none!important}" in projects
    assert "background:linear-gradient(to bottom,transparent,var(--bg) 25px,var(--bg) 100%)!important" in theme
    assert "width:min(760px,94vw)" in modal
    assert "grid-template-columns:170px minmax(0,1fr)" in modal
    assert "min-height:38px" in modal
    assert "height:34px" in modal
    assert ".tasks-board-card-handle" in tasks
    assert ".tasks-board-dropzone.allowed" in tasks
    assert ".tasks-board-dropzone.blocked" in tasks
    assert "grid-template-columns:90px minmax(240px,1.5fr) 72px 105px minmax(150px,1fr) 88px" in tasks
    assert ".tasks-list-table" in tasks
    assert ".tasks-board-progress-bar" in tasks
    assert ".tasks-board-tag.worktree" in tasks
    assert "tasks-list-runtime" in (static / "js" / "tasks-board.js").read_text(encoding="utf-8")
    assert "chat.project_context" in (static / "js" / "i18n.js").read_text(encoding="utf-8")
    assert "width:clamp(620px,46vw,720px)" in workspace
    assert "width:min(920px,96vw)" in workspace
    assert "height:55px" in workspace
    assert "padding:14px 16px" in workspace
    assert "width:30px;height:30px" in workspace
    assert "width:250px" in workspace
    assert ".task-create-menu-icon" in workspace
    task_workspace_js = (static / "js" / "task-workspace.js").read_text(encoding="utf-8")
    assert "task-create-menu-icon" in task_workspace_js
    assert "rect.right - width" in task_workspace_js
    assert ".task-workspace-drag-grip" in workspace
    assert 'row.draggable = policy.restructure !== false' in task_workspace_js
    assert 'event.altKey && event.key === "ArrowUp"' in task_workspace_js
    assert ".task-workspace-basics" in workspace
    assert ".task-workspace-workspace-options" in workspace
    assert ".task-workspace-workspace-option" in workspace
    assert 'card.dataset.workspaceOption = value' in task_workspace_js
    assert 'body.appendChild(inputGrid)' in task_workspace_js
    assert 'body.appendChild(workspaceSection)' in task_workspace_js
    assert 'inputGrid.append(inputPrimary, inputSupporting)' in task_workspace_js
    assert 'inputGrid.classList.add("has-mixed-validation")' in task_workspace_js
    assert 'grid.append(projectField, workflowField, titleField)' in task_workspace_js
    assert 'if (draft.items.length === 1) body.appendChild(renderDraftTitleField())' not in task_workspace_js
    assert ".task-workspace-input-grid" in workspace
    assert "grid-template-columns:minmax(0,1.34fr) minmax(245px,.86fr)" in workspace
    assert ".task-workspace-shell.workspace-route{width:min(920px,94vw);max-width:94vw}" in workspace
    assert ".task-workspace-task-primary-source textarea{min-height:118px!important}" in workspace
    assert '[["↑"' not in task_workspace_js


def test_global_settings_sidebar_uses_one_icon_and_plain_copy():
    root = Path(__file__).resolve().parents[1]
    static = root / "static"
    index = (static / "index.html").read_text(encoding="utf-8")
    projects = (static / "css" / "projects.css").read_text(encoding="utf-8")
    theme = (static / "css" / "theme.css").read_text(encoding="utf-8")

    settings = index.split('id="themeButton"', 1)[1].split("</button>", 1)[0]
    assert settings.count('class="nav-icon"') == 1
    assert 'class="global-settings-copy"' in settings

    assert ".project-nav-link span {" not in projects
    assert "body.projects-collapsed .project-nav-link span {" not in projects
    assert ".project-nav-link.active span {" not in projects
    assert "html[data-appearance] .project-nav-link span" not in theme

    assert ".global-settings-button .nav-icon" in projects
    assert "width: 24px" in projects
    assert "height: 24px" in projects
    assert ".global-settings-button .global-settings-copy strong" in projects
    assert "font-size: 11px" in projects
    assert "font-size: 7.5px" in projects
    assert "background:transparent" in theme
