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
    assert 'id="error"' in text
    assert "Connect it to START / PASS to join the flow." in text


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
