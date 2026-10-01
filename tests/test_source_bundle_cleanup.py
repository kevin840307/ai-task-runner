from pathlib import Path

from tool.bundle import DEFAULT_EXCLUDES, excluded, pack, read_bundle

ROOT = Path(__file__).resolve().parents[1]


def test_default_bundle_excludes_runtime_and_cache_artifacts():
    excluded_paths = [
        ".pytest_cache/v/cache/nodeids",
        "runner/__pycache__/x.cpython-313.pyc",
        "examples/demo/.ai-task-runner/state.json",
        "examples/demo/.ai-task-runner/validator-reports/file/summary.txt",
        "examples/demo/validator-reports/file/summary.txt",
        "tests/x.pyc",
    ]
    assert all(excluded(path, DEFAULT_EXCLUDES) for path in excluded_paths)


def test_pack_skips_output_when_bundle_lives_inside_source_root(tmp_path):
    (tmp_path / "source.txt").write_text("hello", encoding="utf-8")
    output = tmp_path / "project.bundle.txt"

    pack(tmp_path, output, DEFAULT_EXCLUDES)

    paths = [item["path"] for item in read_bundle(output)]
    assert paths == ["source.txt"]


def test_obsolete_multi_agent_and_grill_assets_stay_absent():
    for path in (
        "runner/assets/workflows/discussion.yaml",
        "runner/assets/prompts/common/discussion.md",
        "runner/assets/prompts/common/discussion_controller.md",
        "runner/assets/prompts/common/discussion_judge.md",
        "runner/assets/prompts/common/discussion_final_validator.md",
        "runner/assets/prompts/common/grill.md",
        "tool/workflow/02_ai_with_grill.yaml",
        "tool/workflow/04_mixed_with_grill.yaml",
        "tool/workflow/05_grill_vote_3_choose_2.yaml",
    ):
        assert not (ROOT / path).exists(), path


def test_current_review_gate_tool_workflows_exist():
    for path in (
        "tool/workflow/02_ai_with_review_gate.yaml",
        "tool/workflow/04_mixed_with_review_gate.yaml",
        "tool/workflow/05_review_vote_3_choose_2.yaml",
        "tool/workflow/11_multi_validators_anywhere.yaml",
    ):
        assert (ROOT / path).is_file(), path


def test_bundle_includes_current_core_and_deleted_compat_modules_stay_absent():
    assert not excluded("runner/workflow/flow_engine.py", DEFAULT_EXCLUDES)
    for path in (
        "runner/task_runner.py",
        "runner/workflow/pipeline.py",
        "runner/workflow/linear_routing.py",
        "runner/workflow/semantic_routing.py",
    ):
        assert not (ROOT / path).exists()
