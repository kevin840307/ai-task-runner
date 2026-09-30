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


def test_react_studio_reuses_stage_nodes_for_dynamic_handoff_and_discussion():
    text = SOURCE.read_text(encoding="utf-8")

    assert 'id={discussionController ? "dispatch" : "handoff"}' in text
    assert '"discussion_controller"' in text
    assert 'types: ["handoff", "discussion_controller", "discussion"]' in text
    assert '"dispatch"' in text
    assert "最多討論輪數" in text
    assert 'draft.type === "discussion_controller"' in text
    assert "draft.max_rounds" in text
    assert "stage.targets" in text
    assert "autoPositions" in text
    assert "branchTargets" in text
    assert "branchColumnGap" in text
    assert "maxBranchColumns" in text
    assert "cursorY" in text
    assert "discussion-return" in text
    assert 'title: "Discussion"' in text
    assert 'title: "Discussion Session"' in text
