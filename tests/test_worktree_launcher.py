import subprocess
from pathlib import Path

import pytest
import yaml

from tool import worktree_launcher as launcher


def write_config(tmp_path: Path, data: dict) -> Path:
    path = tmp_path / "launcher.yaml"
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    return path


def write_tasks(path: Path, count: int) -> None:
    path.write_text(
        yaml.safe_dump([
            {"prompt": f"task {index}", "validator": "ai", "project_root": "old-root"}
            for index in range(1, count + 1)
        ], sort_keys=False),
        encoding="utf-8",
    )


def test_config_splits_one_task_yaml_by_concurrency(tmp_path):
    repo = tmp_path / "TestProject"
    repo.mkdir()
    write_tasks(repo / "xxxxx.yaml", 7)
    config = write_config(tmp_path, {
        "repo": str(repo),
        "worktree_root": str(tmp_path),
        "concurrency": 5,
        "base_branch": "main",
        "task_yaml": "xxxxx.yaml",
    })

    loaded = launcher.load_config(config)

    assert loaded.concurrency == 5
    assert loaded.base_branch == "main"
    assert [job.name for job in loaded.jobs] == ["xxxxx_1", "xxxxx_2", "xxxxx_3", "xxxxx_4", "xxxxx_5"]
    assert [job.branch for job in loaded.jobs] == ["ai/xxxxx_1", "ai/xxxxx_2", "ai/xxxxx_3", "ai/xxxxx_4", "ai/xxxxx_5"]
    assert [job.worktree.name for job in loaded.jobs] == ["TestProject_1", "TestProject_2", "TestProject_3", "TestProject_4", "TestProject_5"]
    assert [len(job.task_items) for job in loaded.jobs] == [2, 2, 1, 1, 1]
    assert [job.task_yaml.name for job in loaded.jobs] == ["xxxxx_1.yaml", "xxxxx_2.yaml", "xxxxx_3.yaml", "xxxxx_4.yaml", "xxxxx_5.yaml"]


def test_config_creates_only_non_empty_worktrees_when_tasks_are_fewer_than_concurrency(tmp_path):
    repo = tmp_path / "TestProject"
    repo.mkdir()
    write_tasks(repo / "xxxxx.yaml", 2)
    config = write_config(tmp_path, {
        "repo": str(repo),
        "worktree_root": str(tmp_path),
        "concurrency": 5,
        "task_yaml": "xxxxx.yaml",
    })

    loaded = launcher.load_config(config)

    assert len(loaded.jobs) == 2
    assert [job.worktree.name for job in loaded.jobs] == ["TestProject_1", "TestProject_2"]


def test_materialize_task_yaml_rewrites_project_root_and_script_paths(tmp_path):
    repo = tmp_path / "TestProject"
    source_dir = repo / "tasks"
    source_dir.mkdir(parents=True)
    source = source_dir / "xxxxx.yaml"
    source.write_text(
        yaml.safe_dump([{
            "prompt": "x",
            "goal_file": "goal.md",
            "ai_validator_prompt_file": "validate.md",
            "workflow_file": "workflow.yaml",
            "validator": "ai",
            "project_root": "old-root",
        }], sort_keys=False),
        encoding="utf-8",
    )
    worktree = tmp_path / "TestProject_1"
    job = launcher.Job(
        name="xxxxx_1",
        branch="ai/xxxxx_1",
        worktree=worktree,
        source_task_yaml=source,
        task_yaml=worktree / ".ai-task-runner" / "launcher" / "scripts" / "xxxxx_1.yaml",
        task_items=({"prompt": "x", "goal_file": "goal.md", "ai_validator_prompt_file": "validate.md", "workflow_file": "workflow.yaml", "validator": "ai", "project_root": "old-root"},),
    )

    launcher.materialize_task_yaml(job)

    data = yaml.safe_load(job.task_yaml.read_text(encoding="utf-8"))
    assert data[0]["project_root"] == str(worktree)
    assert data[0]["goal_file"] == str((source_dir / "goal.md").resolve())
    assert data[0]["ai_validator_prompt_file"] == str((source_dir / "validate.md").resolve())
    assert data[0]["workflow_file"] == str((source_dir / "workflow.yaml").resolve())
    assert source.is_file()


def test_prepare_and_force_clean_emit_safe_git_commands(tmp_path, monkeypatch):
    repo = tmp_path / "TestProject"
    repo.mkdir()
    source = repo / "xxxxx.yaml"
    write_tasks(source, 1)
    runner = tmp_path / "ai_task_runner.py"
    runner.write_text("runner", encoding="utf-8")
    config = launcher.LaunchConfig(
        repo=repo,
        runner=runner,
        base_branch="main",
        concurrency=1,
        start_jitter_seconds=(0, 0),
        jobs=(launcher.Job("xxxxx_1", "ai/xxxxx_1", tmp_path / "TestProject_1", source, tmp_path / "TestProject_1" / ".ai-task-runner" / "launcher" / "scripts" / "xxxxx_1.yaml", ({"prompt": "x", "validator": "ai"},)),),
    )
    calls = []
    monkeypatch.setattr(launcher, "ensure_git_repo", lambda repo: None)
    monkeypatch.setattr(launcher, "_run", lambda command, **kwargs: calls.append((command, kwargs)) or subprocess.CompletedProcess(command, 0, "", ""))

    launcher.prepare(config)
    config.jobs[0].worktree.mkdir(exist_ok=True)
    launcher.clean(config, delete_branches=True, force=True)

    assert calls[0][0] == ["git", "worktree", "add", "-b", "ai/xxxxx_1", str(config.jobs[0].worktree), "main"]
    assert calls[1][0] == ["git", "worktree", "remove", "--force", str(config.jobs[0].worktree)]
    assert calls[2][0] == ["git", "branch", "-D", "ai/xxxxx_1"]


def test_runner_command_uses_worktree_project_root_and_generated_script(tmp_path):
    worktree = tmp_path / "TestProject_1"
    task = worktree / ".ai-task-runner" / "launcher" / "scripts" / "xxxxx_1.yaml"
    task.parent.mkdir(parents=True)
    task.write_text("- prompt: x\n  validator: ai\n", encoding="utf-8")
    runner = tmp_path / "runner.py"
    runner.write_text("runner", encoding="utf-8")
    config = launcher.LaunchConfig(
        repo=tmp_path / "TestProject",
        runner=runner,
        base_branch="HEAD",
        concurrency=1,
        start_jitter_seconds=(0, 0),
        jobs=(launcher.Job("xxxxx_1", "ai/xxxxx_1", worktree, tmp_path / "TestProject" / "xxxxx.yaml", task, ({"prompt": "x", "validator": "ai"},)),),
    )

    command = launcher.runner_command(config, config.jobs[0])

    assert command[command.index("--project-root") + 1] == str(worktree)
    assert command[command.index("--script") + 1] == str(task)


def test_unsupported_old_multi_mode_fields_fail_fast(tmp_path):
    repo = tmp_path / "TestProject"
    repo.mkdir()
    write_tasks(repo / "xxxxx.yaml", 1)
    config = write_config(tmp_path, {
        "repo": str(repo),
        "worktree_root": str(tmp_path),
        "concurrency": 1,
        "task_yaml": "xxxxx.yaml",
        "task_yamls": ["other.yaml"],
    })

    with pytest.raises(launcher.LauncherError, match="unsupported config field"):
        launcher.load_config(config)


def test_prepare_rejects_existing_wrong_worktree_branch(tmp_path, monkeypatch):
    repo = tmp_path / "TestProject"; repo.mkdir()
    source = repo / "xxxxx.yaml"; write_tasks(source, 1)
    worktree = tmp_path / "TestProject_1"; worktree.mkdir()
    runner = tmp_path / "runner.py"; runner.write_text("runner", encoding="utf-8")
    config = launcher.LaunchConfig(
        repo=repo, runner=runner, base_branch="main", concurrency=1, start_jitter_seconds=(0, 0),
        jobs=(launcher.Job("xxxxx_1", "ai/xxxxx_1", worktree, source, worktree / ".ai-task-runner/launcher/scripts/xxxxx_1.yaml", ({"prompt":"x","validator":"ai"},)),),
    )
    monkeypatch.setattr(launcher, "ensure_git_repo", lambda repo: None)
    monkeypatch.setattr(launcher, "verify_existing_worktree", lambda config, job: (_ for _ in ()).throw(launcher.LauncherError("branch mismatch")))
    with pytest.raises(launcher.LauncherError, match="branch mismatch"):
        launcher.prepare(config)


def test_clean_includes_stale_numbered_worktrees(tmp_path, monkeypatch):
    repo = tmp_path / "TestProject"; repo.mkdir()
    source = repo / "xxxxx.yaml"; write_tasks(source, 1)
    current = tmp_path / "TestProject_1"; stale = tmp_path / "TestProject_3"
    current.mkdir(); stale.mkdir()
    runner = tmp_path / "runner.py"; runner.write_text("runner", encoding="utf-8")
    config = launcher.LaunchConfig(
        repo=repo, runner=runner, base_branch="main", concurrency=1, start_jitter_seconds=(0, 0),
        jobs=(launcher.Job("xxxxx_1", "ai/xxxxx_1", current, source, current / ".ai-task-runner/launcher/scripts/xxxxx_1.yaml", ({"prompt":"x","validator":"ai"},)),),
        worktree_root=tmp_path, job_stem="xxxxx",
    )
    calls=[]
    monkeypatch.setattr(launcher, "ensure_git_repo", lambda repo: None)
    monkeypatch.setattr(launcher, "_run", lambda command, **kwargs: calls.append(command) or subprocess.CompletedProcess(command,0,"",""))
    launcher.clean(config, delete_branches=True, force=True)
    removed = [cmd[-1] for cmd in calls if cmd[:3] == ["git","worktree","remove"] or cmd[:4] == ["git","worktree","remove","--force"]]
    assert str(current) in removed
    assert str(stale) in removed
    assert ["git", "branch", "-D", "ai/xxxxx_3"] in calls
