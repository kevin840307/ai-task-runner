from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "ui" / "studio-src" / "src" / "main.tsx"


def test_react_studio_has_drag_palette_and_manual_result_edge_handles():
    text = SOURCE.read_text(encoding="utf-8")

    assert "Stage Palette" in text
    assert "application/x-ai-stage" in text
    assert 'sourceHandle: "pass"' in text
    assert 'id="pass"' in text
    assert 'id="fail"' in text
    assert 'id="error"' not in text
    assert 'graph: graphDraft(nextVisual)' in text
    assert '"/api/studio/stage/add"' not in text  # Palette additions stay in the draft until Save.


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
    assert "重試用盡後" not in text
    assert "draft.error_policy?.retries" in text
    assert 'error_policy: { retries }' in text
    assert '["pass", "fail", "error"]' not in text


def test_static_studio_bundle_has_no_removed_dispatch_runtime_branch():
    scripts = list((ROOT / "ui" / "static" / "workflow-studio-app" / "assets").glob("*.js"))
    assert scripts
    bundled = "\n".join(path.read_text(encoding="utf-8") for path in scripts)
    assert 've==="handoff"||ve==="dispatch"' not in bundled
    assert '"discussion_controller"' not in bundled


def test_react_studio_generic_inspector_keeps_unknown_catalog_options_editable():
    text = SOURCE.read_text(encoding="utf-8")
    assert 'section.id === "advanced"' in text
    assert "PARAMETER_SECTIONS.slice(0, -1)" in text
    assert "group.fields.includes(option.name)" in text


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
    assert "autoPositions" in text
    assert "branchTargets" in text
    assert "branchColumnGap" in text
    assert "rowStartCenter" in text
    assert "cursorY" in text

