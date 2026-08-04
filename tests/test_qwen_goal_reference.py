from pathlib import Path

from runner.backends.qwen import (
    GOAL_REFERENCE_END,
    GOAL_REFERENCE_START,
    update_qwen_goal_reference,
)


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
