from pathlib import Path

from runner.agent.qwen import update_qwen_goal_reference
from runner.workspace import GOAL_REFERENCE_END, GOAL_REFERENCE_START


def test_goal_reference_is_added_and_replaced(tmp_path: Path):
    first = tmp_path / "first goal.md"
    second = tmp_path / "second.md"
    first.write_text("one", encoding="utf-8")
    second.write_text("two", encoding="utf-8")

    path = update_qwen_goal_reference(tmp_path, str(first))
    text = path.read_text(encoding="utf-8")
    assert first.resolve().as_posix() in text
    assert text.count(GOAL_REFERENCE_START) == 1

    update_qwen_goal_reference(tmp_path, str(second))
    text = path.read_text(encoding="utf-8")
    assert first.resolve().as_posix() not in text
    assert second.resolve().as_posix() in text
    assert text.count(GOAL_REFERENCE_START) == 1
    assert text.count(GOAL_REFERENCE_END) == 1


def test_inline_goal_removes_managed_reference(tmp_path: Path):
    goal = tmp_path / "goal.md"
    goal.write_text("goal", encoding="utf-8")
    path = update_qwen_goal_reference(tmp_path, str(goal))
    update_qwen_goal_reference(tmp_path, None)
    text = path.read_text(encoding="utf-8")
    assert GOAL_REFERENCE_START not in text
    assert "# AI Task Runner Rules" in text


def test_qwen_backend_goal_reference_hook(tmp_path):
    from runner.agent.qwen import QwenBackend

    goal = tmp_path / "goal.md"
    goal.write_text("goal", encoding="utf-8")
    import sys
    backend = QwenBackend(sys.executable, tmp_path, [])
    backend.update_goal_reference(str(goal))

    text = (tmp_path / "QWEN.md").read_text(encoding="utf-8")
    assert goal.resolve().as_posix() in text


def test_qwen_rules_use_project_relative_write_paths_and_migrate_legacy_rule(tmp_path):
    from runner.agent.qwen import ensure_qwen_rules

    legacy = tmp_path / "QWEN.md"
    legacy.write_text(
        "# AI Task Runner Rules\n"
        f"- You may write, create, rename, or delete files only under: {tmp_path}\n"
        "- Never modify runner state directly.\n",
        encoding="utf-8",
    )

    path = ensure_qwen_rules(tmp_path)
    text = path.read_text(encoding="utf-8")

    assert "use a project-relative path" in text
    assert "Never construct, encode, flatten, or use an absolute filesystem path as a filename." in text
    assert "You may write, create, rename, or delete files only under:" not in text
