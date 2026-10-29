from pathlib import Path

import pytest

from runner.utils import path_key, remove_path, same_path


def test_atomic_resource_temp_name_does_not_repeat_long_target_name(tmp_path, monkeypatch):
    import runner.resources as resources

    seen = {}
    original_replace = resources.os.replace

    def capture(source, target):
        seen["source"] = Path(source)
        seen["target"] = Path(target)
        return original_replace(source, target)

    monkeypatch.setattr(resources.os, "replace", capture)
    target = tmp_path / ("a" * 96 + ".md")
    resources.write_text(target, "ok")

    assert same_path(seen["target"], target)
    assert same_path(seen["source"].parent, target.parent)
    assert target.name not in seen["source"].name
    assert seen["source"].name.startswith(".tmp-")


def test_path_identity_ignores_logical_spelling(tmp_path):
    nested = tmp_path / "folder"
    nested.mkdir()
    alternate = nested / ".." / "folder"

    assert path_key(nested) == path_key(alternate)
    assert same_path(nested, alternate)


def test_remove_path_deletes_short_root_with_deep_descendants(tmp_path):
    root = tmp_path / "tree"
    deep = root
    index = 0
    while len(str(deep)) <= 300:
        deep = deep / (f"segment-{index}-" + "x" * 38)
        index += 1

    from runner.utils import io_path

    io_path(deep).mkdir(parents=True, exist_ok=True)
    io_path(deep / "payload.txt").write_text("x", encoding="utf-8")

    remove_path(root)

    assert not root.exists()



def test_resource_read_write_hash_validation_and_delete_contract(tmp_path):
    import runner.resources as resources
    from runner.errors import RunnerError

    target = tmp_path / "config.txt"
    first_hash = resources.write_text(
        target,
        "first",
        validate=lambda text: None if text == "first" else (_ for _ in ()).throw(ValueError()),
    )

    text, read_hash = resources.read_text(target)
    assert text == "first"
    assert read_hash == first_hash
    assert resources.text_hash("first") == first_hash

    second_hash = resources.write_text(
        target,
        "second",
        expected_hash=first_hash,
    )
    assert second_hash != first_hash
    assert resources.read_text(target) == ("second", second_hash)

    with pytest.raises(RunnerError, match="resource changed since it was read"):
        resources.write_text(target, "third", expected_hash=first_hash)
    with pytest.raises(RunnerError, match="resource changed since it was read"):
        resources.delete(target, expected_hash=first_hash)

    resources.delete(target, expected_hash=second_hash)
    assert not target.exists()
    resources.delete(target)


def test_resource_write_validation_runs_before_file_replacement(tmp_path):
    import runner.resources as resources

    target = tmp_path / "validated.txt"
    target.write_text("stable", encoding="utf-8")

    def reject(_text):
        raise ValueError("invalid resource")

    with pytest.raises(ValueError, match="invalid resource"):
        resources.write_text(target, "bad", validate=reject)

    assert target.read_text(encoding="utf-8") == "stable"


def test_run_resource_paths_freeze_and_reload_goal_and_validator_prompt(tmp_path):
    import runner.resources as resources

    goal = tmp_path / "goal-source.txt"
    validator = tmp_path / "validator-source.txt"
    goal.write_text("goal body", encoding="utf-8")
    validator.write_text("validator body", encoding="utf-8")

    frozen_goal = resources.freeze_run_resource(
        goal,
        tmp_path,
        ".work",
        "goal",
    )
    frozen_validator = resources.freeze_run_resource(
        validator,
        tmp_path,
        ".work",
        "ai_validator_prompt",
    )

    goal_path = resources.run_resource_path(tmp_path, ".work", "goal")
    validator_path = resources.run_resource_path(
        tmp_path,
        ".work",
        "ai_validator_prompt",
    )
    assert frozen_goal == (str(goal_path.resolve()), "goal body")
    assert frozen_validator == (str(validator_path.resolve()), "validator body")
    assert resources.load_run_resource(tmp_path, ".work", "goal") == frozen_goal
    assert (
        resources.load_run_resource(tmp_path, ".work", "ai_validator_prompt")
        == frozen_validator
    )
    assert resources.freeze_run_resource(None, tmp_path, ".work", "goal") is None

    with pytest.raises(ValueError, match="unknown run resource"):
        resources.run_resource_path(tmp_path, ".work", "missing")


def test_freeze_workflow_snapshots_absolute_prompt_and_load_snapshot_validates(tmp_path):
    import runner.resources as resources

    prompt = tmp_path / "prompt.md"
    prompt.write_text("immutable prompt", encoding="utf-8")

    frozen = resources.freeze_workflow(
        [
            {
                "name": "check",
                "type": "command",
                "command": ["python", "-c", "print('ok')"],
            }
        ],
        tmp_path,
        ".work",
    )
    snapshot = resources.snapshot_path(tmp_path, ".work")
    assert snapshot.is_file()
    assert resources.load_snapshot(tmp_path, ".work") == frozen

    prompt_workflow = [
        {
            "name": "arbitrary",
            "prompt": str(prompt.resolve()),
            "nested": {"prompt": str(prompt.resolve())},
        }
    ]
    frozen_prompt_workflow = resources.freeze_workflow(
        prompt_workflow,
        tmp_path,
        ".prompt-work",
    )
    first = Path(frozen_prompt_workflow[0]["prompt"])
    second = Path(frozen_prompt_workflow[0]["nested"]["prompt"])
    assert first == second
    assert first.is_file()
    assert first.read_text(encoding="utf-8") == "immutable prompt"
    assert first.parent.name == resources.RESOURCE_DIR


def test_load_snapshot_rejects_invalid_json_and_invalid_stage(tmp_path):
    import runner.resources as resources
    from runner.errors import ConfigurationError

    snapshot = resources.snapshot_path(tmp_path, ".work")
    snapshot.parent.mkdir(parents=True)

    snapshot.write_text("{bad", encoding="utf-8")
    with pytest.raises(ConfigurationError, match="invalid workflow snapshot"):
        resources.load_snapshot(tmp_path, ".work")

    snapshot.write_text("[]", encoding="utf-8")
    with pytest.raises(ConfigurationError, match="workflow snapshot must be a non-empty list"):
        resources.load_snapshot(tmp_path, ".work")
