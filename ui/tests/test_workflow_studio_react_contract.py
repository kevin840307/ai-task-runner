from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "ui" / "studio-src" / "src" / "main.tsx"


def test_react_studio_has_drag_palette_and_manual_result_edge_handles():
    text = SOURCE.read_text(encoding="utf-8")

    assert "Stage Palette" in text
    assert "workflowStudioUrl" in text
    assert 'view: "workflow", studio: id' in text
    assert "← Workflow Studio" in text
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
    assert "common/execution.md" not in text  # comes from the runtime catalog, not duplicated UI constants


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
    assert 'stage.error_policy = { retries: 2 };' in text
    assert "stage.max_failures = 3" in text
    assert "Semantic FAIL 上限（max_failures）" in text
    assert "FAIL×{Number(draft.max_failures)}" in text
    assert '["pass", "fail", "error"]' not in text


def test_react_studio_has_searchable_palette_and_safe_stage_duplicate():
    text = SOURCE.read_text(encoding="utf-8")

    assert 'placeholder="搜尋 Stage…"' in text
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
    assert 'types: ["handoff"]' in text
    assert '"discussion_controller"' not in text
    assert '"discussion"' not in text
    assert '"dispatch"' not in text
    assert "session_policy" in text
    assert '"fresh_session_each_run", "fresh_session_on_start"' not in text
    assert 'o.name === "session_key"' in text
    assert 'session_key: _sessionKey' in text
    assert "leaveStudio()" in text
    assert 'window.confirm("捨棄未儲存的 Workflow 草稿？")' in text
    assert "autoPositions" in text
    assert "branchTargets" in text
    assert "branchColumnGap" in text
    assert "rowStartCenter" in text
    assert "cursorY" in text

