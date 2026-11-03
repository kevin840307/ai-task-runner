from __future__ import annotations

import subprocess
import time
from pathlib import Path
from types import SimpleNamespace

from ui.server import UIState


def _repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    (repo / "ui" / "data").mkdir(parents=True)
    (repo / "ui" / "static").mkdir(parents=True)
    builder = repo / "workflow_builder"
    builder.mkdir()
    for name in ("run.py", "validation.py", "publish.py"):
        (builder / name).write_text("# fixture\n", encoding="utf-8")
    (builder / "workflow_builder.yaml").write_text("stages: {}\nflow: []\n", encoding="utf-8")
    (builder / "prompt.md").write_text("{{ goal }}\n", encoding="utf-8")
    return repo


class _FakeProcessModule:
    DEVNULL = subprocess.DEVNULL

    def __init__(self) -> None:
        self.calls: list[tuple[list[str], dict]] = []

    def Popen(self, command, **kwargs):
        self.calls.append((list(command), dict(kwargs)))
        return SimpleNamespace(pid=424242)


def test_workflow_builder_active_cancel_stale_and_discard_lifecycle(tmp_path: Path) -> None:
    state = UIState(_repo(tmp_path))
    fake_process = _FakeProcessModule()
    state._process_module = fake_process

    started = state.studio_generate_workflow(
        "Build a small validation workflow",
        backend="qwen",
        filename="generated",
    )
    job_id = started["job_id"]
    job_root = Path(started["workspace"])

    assert started["state"] == "queued"
    assert started["filename"] == "generated.workflow.yaml"
    assert len(fake_process.calls) == 1
    command = fake_process.calls[0][0]
    assert "--project-root" in command
    assert str(job_root) in command
    assert "--backend" in command
    assert "qwen" in command

    repeated = state.studio_generate_workflow(
        "A second click must not launch another process",
        backend="qwen",
        filename="another.yaml",
    )
    assert repeated["job_id"] == job_id
    assert repeated["existing"] is True
    assert len(fake_process.calls) == 1

    active = state.studio_generate_active()
    assert active["active"] is True
    assert active["job_id"] == job_id
    assert active["request"] == "Build a small validation workflow"

    cancelling = state.studio_generate_cancel(job_id)
    assert cancelling["state"] == "cancelling"
    assert (job_root / "cancel.request").read_text(encoding="utf-8") == "cancel\n"
    assert (job_root / ".ai-task-runner" / "stop.request").read_text(encoding="utf-8") == "stop\n"

    status_path = job_root / "status.json"
    status = state._read_json(status_path)
    assert status is not None
    status["updated_at"] = time.time() - 60
    status["pid"] = 999999
    state._atomic_json(status_path, status)
    state._pid_alive = lambda pid: False

    terminal = state.studio_generate_status(job_id)
    assert terminal["state"] == "cancelled"
    assert not (job_root / ".ai-task-runner").exists()

    discarded = state.studio_generate_discard(job_id)
    assert discarded["ok"] is True
    assert not job_root.exists()
    assert state.studio_generate_active()["active"] is False


def test_workflow_builder_ready_preview_validate_and_runtime_cleanup(tmp_path: Path) -> None:
    state = UIState(_repo(tmp_path))
    job_id = "b" * 12
    job_root = state._builder_job_root(job_id)
    prompts = job_root / "draft" / "prompts"
    prompts.mkdir(parents=True)
    workflow = job_root / "draft" / "workflow.yaml"
    workflow.write_text(
        "stages:\n"
        "  execute:\n"
        "    type: base\n"
        "    prompt: common/execution.md\n"
        "flow:\n"
        "  - execute\n",
        encoding="utf-8",
    )
    (prompts / "execution.md").write_text("Do {{ goal }}\n", encoding="utf-8")
    (job_root / ".ai-task-runner").mkdir()
    state._atomic_json(
        job_root / "status.json",
        {
            "schema_version": 1,
            "job_id": job_id,
            "state": "ready",
            "message": "Draft ready",
            "created_at": time.time(),
            "updated_at": time.time(),
        },
    )
    state._builder_set_active(job_id)

    ready = state.studio_generate_status(job_id)
    assert ready["ok"] is True
    assert ready["state"] == "ready"
    assert "execute" in ready["draft"]["workflow"]
    assert ready["draft"]["prompts"] == [
        {"name": "execution.md", "content": "Do {{ goal }}\n"}
    ]
    assert ready["draft"]["visual"]["stages"][0]["name"] == "execute"
    assert ready["draft"]["visual"]["flow"] == ["execute"]
    assert not (job_root / ".ai-task-runner").exists()

    state._builder_validate_draft = lambda root, workflow_path, prompt_dir: {
        "ok": True,
        "output": "validated",
    }
    validated = state.studio_generate_validate(job_id, None, None)
    assert validated["ok"] is True
    assert validated["output"] == "validated"
    assert validated["draft"]["visual"]["flow"] == ["execute"]

    status = state._read_json(job_root / "status.json")
    assert status is not None
    assert status["message"] == "Draft validation passed"


def test_workflow_builder_rejects_invalid_job_and_running_discard(tmp_path: Path) -> None:
    state = UIState(_repo(tmp_path))

    for value in ("", "../escape", "not-hex-id"):
        try:
            state._builder_job_root(value)
        except ValueError as exc:
            assert "Invalid Workflow Builder job id" in str(exc)
        else:  # pragma: no cover
            raise AssertionError(f"invalid job id accepted: {value!r}")

    job_id = "c" * 12
    job_root = state._builder_job_root(job_id)
    job_root.mkdir(parents=True)
    state._atomic_json(
        job_root / "status.json",
        {
            "schema_version": 1,
            "job_id": job_id,
            "state": "running",
            "message": "Running",
            "created_at": time.time(),
            "updated_at": time.time(),
        },
    )

    try:
        state.studio_generate_discard(job_id)
    except ValueError as exc:
        assert "Cancel the running Workflow generation" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("running Workflow Builder job was discarded")
