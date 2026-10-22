from __future__ import annotations

import base64
import json
import subprocess
import threading
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from ui.server import UIServer
from tool.task_draft_contract import (
    TASK_DRAFT_AGENT_TIMEOUT_SECONDS,
    TASK_DRAFT_ERROR_CHARS,
    TASK_DRAFT_WRAPPER_GRACE_SECONDS,
)
from ui.task_draft_service import TaskDraftService
from ui.task_service import TaskService
from ui.task_upload_service import TaskUploadService


def _json_request(url: str, *, method: str = "GET", body: dict | None = None) -> dict:
    data = None if body is None else json.dumps(body).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={"Content-Type": "application/json"} if data is not None else {},
    )
    with urllib.request.urlopen(request, timeout=5) as response:
        return json.loads(response.read().decode("utf-8"))


def test_task_draft_tool_uses_shared_timeout_and_bounded_errors(
    tmp_path: Path,
    monkeypatch,
) -> None:
    repo = tmp_path / "repo"
    project = repo / "project"
    project.mkdir(parents=True)
    captured: dict[str, object] = {}

    class Completed:
        returncode = 0
        stdout = json.dumps({
            "draft": {
                "title": "Generated",
                "items": [{"title": "One", "prompt": "Do one"}],
            }
        })
        stderr = ""

    def fake_run(command, **kwargs):
        captured["command"] = list(command)
        captured["timeout"] = kwargs.get("timeout")
        return Completed()

    monkeypatch.setattr("ui.task_draft_service.subprocess.run", fake_run)
    service = TaskDraftService(repo)
    result = service._run_tool(
        project=project,
        backend="qwen",
        model="model-a",
        reasoning="high",
        draft_mode="single",
        spec="generate one task",
    )
    assert result["draft"]["title"] == "Generated"
    assert captured["timeout"] == (
        TASK_DRAFT_AGENT_TIMEOUT_SECONDS + TASK_DRAFT_WRAPPER_GRACE_SECONDS
    )

    class Failed:
        returncode = 1
        stdout = ""
        stderr = ("x" * (TASK_DRAFT_ERROR_CHARS + 200)) + "TAIL"

    monkeypatch.setattr(
        "ui.task_draft_service.subprocess.run",
        lambda *args, **kwargs: Failed(),
    )
    with pytest.raises(ValueError) as exc_info:
        service._run_tool(
            project=project,
            backend="qwen",
            model="",
            reasoning="",
            draft_mode="single",
            spec="fail with large stderr",
        )
    detail = str(exc_info.value)
    assert len(detail) == TASK_DRAFT_ERROR_CHARS
    assert detail.endswith("TAIL")


def test_task_draft_tool_timeout_is_fail_closed(tmp_path: Path, monkeypatch) -> None:
    repo = tmp_path / "repo"
    project = repo / "project"
    project.mkdir(parents=True)

    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired(
            cmd="task-draft-agent",
            timeout=kwargs.get("timeout", 0),
        )

    monkeypatch.setattr("ui.task_draft_service.subprocess.run", timeout)
    service = TaskDraftService(repo)
    with pytest.raises(ValueError, match="TaskDraft generation failed"):
        service._run_tool(
            project=project,
            backend="qwen",
            model="",
            reasoning="",
            draft_mode="single",
            spec="timeout",
        )


def test_missing_project_fails_before_task_draft_agent_or_task_validation(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    missing = repo / "missing-project"
    calls = 0

    def fake_runner(**kwargs):
        nonlocal calls
        calls += 1
        return {
            "draft": {
                "title": "Should not run",
                "items": [{"title": "One", "prompt": "Do one"}],
            }
        }

    drafts = TaskDraftService(repo, runner=fake_runner)
    with pytest.raises(ValueError, match="Selected Project does not exist"):
        drafts.generate(
            missing,
            spec="do not invoke agent",
            draft_mode="single",
            backend="qwen",
            workflow="workflow.yaml",
            request_id="missing-project-draft",
        )
    assert calls == 0

    tasks = TaskService()
    with pytest.raises(ValueError, match="Selected Project does not exist"):
        tasks.validate(
            missing,
            {
                "title": "Missing project",
                "items": [{
                    "title": "One",
                    "prompt": "Do one",
                    "workflow": "workflow.yaml",
                    "project": str(missing),
                    "workspace": "auto",
                }],
            },
        )


def test_task_draft_is_transient_structured_and_mode_checked(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    project = repo / "project"
    project.mkdir(parents=True)
    calls: list[dict] = []

    def fake_runner(**kwargs):
        calls.append(dict(kwargs))
        return {
            "draft": {
                "title": "Draft title",
                "items": [
                    {"title": "First", "prompt": "Do first"},
                    {"title": "Second", "prompt": "Do second"},
                ],
            }
        }

    service = TaskDraftService(repo, runner=fake_runner)
    value = service.generate(
        project,
        spec="split this work",
        draft_mode="list",
        backend="opencode",
        model="openai/gpt-5.2",
        reasoning="deep",
        workflow="workflow.yaml",
        request_id="draft-request-1",
    )
    assert value["mode"] == "list"
    assert value["draft"]["project"] == str(project.resolve())
    assert [row["workspace"] for row in value["draft"]["items"]] == ["auto", "auto"]
    assert [row["workflow"] for row in value["draft"]["items"]] == ["workflow.yaml", "workflow.yaml"]
    assert all("validator" not in row for row in value["draft"]["items"])
    assert all("ai_validator_prompt_file" not in row for row in value["draft"]["items"])
    assert calls[0]["draft_mode"] == "list"
    assert not (project / ".ai-task-runner" / "ui" / "tasks.json").exists()

    duplicate = service.generate(
        project,
        spec="different text",
        draft_mode="list",
        backend="opencode",
        request_id="draft-request-1",
    )
    assert duplicate["duplicate"] is True
    assert duplicate["draft_id"] == value["draft_id"]

@pytest.mark.parametrize("count", [1, 2])
def test_task_draft_auto_deterministically_accepts_single_or_list(
    tmp_path: Path,
    count: int,
) -> None:
    repo = tmp_path / "repo"
    project = repo / "project"
    project.mkdir(parents=True)

    service = TaskDraftService(
        repo,
        runner=lambda **kwargs: {
            "draft": {
                "title": "Auto draft",
                "items": [
                    {"title": f"Item {index + 1}", "prompt": f"Do {index + 1}"}
                    for index in range(count)
                ],
            }
        },
    )
    value = service.generate(
        project,
        spec=f"auto-{count}",
        draft_mode="auto",
        backend="qwen",
        workflow="workflow.yaml",
        request_id=f"auto-{count}",
    )
    assert value["mode"] == "auto"
    assert len(value["draft"]["items"]) == count


def test_task_draft_spec_boundaries_preserve_text_and_fail_closed(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    project = repo / "project"
    project.mkdir(parents=True)
    calls: list[dict] = []

    def fake_runner(**kwargs):
        calls.append(dict(kwargs))
        return {
            "draft": {
                "title": "Boundary draft",
                "items": [
                    {"title": "First", "prompt": "Do first"},
                    {"title": "Second", "prompt": "Do second"},
                ],
            }
        }

    service = TaskDraftService(repo, runner=fake_runner)
    spec = 'Implement safely:\n- keep Queue FIFO\n- preserve @task /review ✓ and "quoted" text'
    value = service.generate(
        project,
        spec=spec,
        draft_mode="list",
        backend="qwen",
        workflow="workflow.yaml",
        request_id="boundary-multiline",
    )
    assert value["spec"] == spec
    assert calls[0]["spec"] == spec
    assert [item["title"] for item in value["draft"]["items"]] == ["First", "Second"]
    assert [item["workspace"] for item in value["draft"]["items"]] == ["auto", "auto"]

    with pytest.raises(ValueError, match="TaskDraft spec is required"):
        service.generate(
            project,
            spec=" \n\t ",
            draft_mode="auto",
            backend="qwen",
            request_id="boundary-empty",
        )
    with pytest.raises(ValueError, match="TaskDraft spec is too long"):
        service.generate(
            project,
            spec="x" * 24001,
            draft_mode="auto",
            backend="qwen",
            request_id="boundary-long",
        )
    with pytest.raises(ValueError, match="Unsupported TaskDraft mode"):
        service.generate(
            project,
            spec="valid",
            draft_mode="parallel",
            backend="qwen",
            request_id="boundary-mode",
        )

    invalid = TaskDraftService(
        repo,
        runner=lambda **kwargs: {
            "draft": {
                "title": "Invalid generated draft",
                "items": [{"title": "A", "prompt": "   "}],
            }
        },
    )
    with pytest.raises(ValueError, match="TaskDraft item 1 prompt is required"):
        invalid.generate(
            project,
            spec="schema validation",
            draft_mode="single",
            backend="qwen",
            workflow="workflow.yaml",
            request_id="boundary-schema",
        )


def test_generated_task_draft_includes_only_required_validation_overrides(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    project = repo / "project"
    project.mkdir(parents=True)

    def requirements(_project: Path, workflow: str) -> dict:
        return {
            "requires_python_validator": workflow in {"file.workflow.yaml", "mixed.workflow.yaml"},
            "has_ai_validator": workflow in {"ai.workflow.yaml", "mixed.workflow.yaml"},
        }

    service = TaskDraftService(
        repo,
        workflow_requirements=requirements,
        runner=lambda **kwargs: {
            "draft": {
                "title": "Draft",
                "items": [{
                    "title": "A",
                    "prompt": "Do A",
                    "validator": "validate.py",
                    "ai_validator_prompt_file": "review.md",
                }],
            }
        },
    )

    expected = {
        "plain.workflow.yaml": set(),
        "file.workflow.yaml": {"validator"},
        "ai.workflow.yaml": {"ai_validator_prompt_file"},
        "mixed.workflow.yaml": {"validator", "ai_validator_prompt_file"},
    }
    for index, (workflow, optional_keys) in enumerate(expected.items(), start=1):
        value = service.generate(
            project,
            spec=f"case {index}",
            draft_mode="single",
            backend="qwen",
            workflow=workflow,
            request_id=f"capability-{index}",
        )
        item = value["draft"]["items"][0]
        present = {
            key for key in ("validator", "ai_validator_prompt_file")
            if key in item
        }
        assert present == optional_keys
        if "validator" in optional_keys:
            assert item["validator"] == "validate.py"
        if "ai_validator_prompt_file" in optional_keys:
            assert item["ai_validator_prompt_file"] == "review.md"


def test_task_draft_edit_is_backend_owned_and_session_scoped(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    project = repo / "project"
    project.mkdir(parents=True)
    service = TaskDraftService(
        repo,
        runner=lambda **kwargs: {
            "draft": {
                "title": "Draft",
                "items": [{"title": "A", "prompt": "Original", "workflow": "workflow.yaml"}],
            }
        },
    )
    value = service.generate(
        project,
        spec="edit me",
        draft_mode="single",
        backend="qwen",
        workflow="workflow.yaml",
        request_id="draft-edit-1",
        session_id="session-a",
    )
    edited = json.loads(json.dumps(value["draft"]))
    edited["items"][0]["prompt"] = "Backend canonical edit"
    updated = service.update(
        project,
        value["draft_id"],
        edited,
        session_id="session-a",
    )
    assert updated["draft"]["items"][0]["prompt"] == "Backend canonical edit"
    assert service.get(
        project,
        value["draft_id"],
        session_id="session-a",
    )["draft"]["items"][0]["prompt"] == "Backend canonical edit"

    with pytest.raises(ValueError, match="no longer available"):
        service.get(project, value["draft_id"], session_id="session-b")
    dismissed = service.dismiss(project, value["draft_id"], session_id="session-a")
    assert dismissed["dismissed"] is True
    assert dismissed["duplicate"] is False
    with pytest.raises(ValueError, match="no longer available"):
        service.get(project, value["draft_id"], session_id="session-a")


    single = TaskDraftService(
        repo,
        runner=lambda **kwargs: {
            "draft": {
                "title": "Bad single",
                "items": [
                    {"title": "A", "prompt": "A"},
                    {"title": "B", "prompt": "B"},
                ],
            }
        },
    )
    with pytest.raises(ValueError, match="exactly one"):
        single.generate(
            project,
            spec="one",
            draft_mode="single",
            backend="qwen",
            request_id="bad-single",
        )


def test_task_draft_discard_session_removes_only_that_chat_cache(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    project = repo / "project"
    project.mkdir(parents=True)
    service = TaskDraftService(
        repo,
        runner=lambda **kwargs: {
            "draft": {
                "title": "Draft",
                "items": [{"title": "A", "prompt": "Do it"}],
            }
        },
    )
    first = service.generate(
        project,
        spec="first",
        draft_mode="single",
        backend="qwen",
        workflow="workflow.yaml",
        request_id="request-a",
        session_id="session-a",
    )
    second = service.generate(
        project,
        spec="second",
        draft_mode="single",
        backend="qwen",
        workflow="workflow.yaml",
        request_id="request-b",
        session_id="session-b",
    )

    removed = service.discard_session(project, "session-a")
    assert removed["drafts_removed"] == 1
    assert removed["requests_removed"] == 1
    with pytest.raises(ValueError, match="no longer available"):
        service.get(project, first["draft_id"], session_id="session-a")
    assert service.get(project, second["draft_id"], session_id="session-b")["draft_id"] == second["draft_id"]

    regenerated = service.generate(
        project,
        spec="first again",
        draft_mode="single",
        backend="qwen",
        workflow="workflow.yaml",
        request_id="request-a",
        session_id="session-a",
    )
    assert regenerated["duplicate"] is False
    assert regenerated["draft_id"] != first["draft_id"]


def test_task_service_creates_only_after_explicit_create_and_is_idempotent(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    service = TaskService()
    draft = {
        "title": "Task List",
        "project": str(project),
        "items": [
            {
                "title": "A",
                "prompt": "Do A",
                "workflow": "workflow.yaml",
                "project": str(project),
                "workspace": "auto",
            },
            {
                "title": "B",
                "prompt": "Do B",
                "workflow": "workflow.yaml",
                "project": str(project),
                "workspace": "main",
            },
        ],
    }

    created = service.create(project, draft, request_id="create-1")
    assert created["status"] == "new"
    assert created["kind"] == "task_list"
    assert created["run_count"] == 0
    assert created["merge_failure_count"] == 0
    assert "runtime" not in created

    restarted = TaskService()
    listed = restarted.list(project)["tasks"]
    assert [row["task_id"] for row in listed] == [created["task_id"]]
    duplicate = restarted.create(project, draft, request_id="create-1")
    assert duplicate["duplicate"] is True
    assert duplicate["task_id"] == created["task_id"]


def test_task_prompt_sources_and_ai_default_follow_runner_resource_contract(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()

    def requirements(_project: Path, workflow: str) -> dict:
        return {
            "exists": workflow in {"mixed.yaml", "plain.yaml"},
            "requires_python_validator": workflow == "mixed.yaml",
            "has_ai_validator": workflow == "mixed.yaml",
        }

    service = TaskService(workflow_requirements=requirements)
    file_prompt = {
        "title": "File prompt",
        "items": [{
            "title": "Child",
            "prompt": "",
            "goal_file": str(project / "goal.md"),
            "workflow": "mixed.yaml",
            "project": str(project),
            "workspace": "auto",
            "validator": str(project / "validate.py"),
            "ai_validator_prompt": "",
            "ai_validator_prompt_file": "",
        }],
    }
    validated = service.validate(project, file_prompt)["draft"]
    assert validated["items"][0]["prompt"] == ""
    assert validated["items"][0]["goal_file"].endswith("goal.md")
    assert validated["items"][0]["ai_validator_prompt"] == ""
    assert validated["items"][0]["ai_validator_prompt_file"] == ""

    inline_ai = json.loads(json.dumps(file_prompt))
    inline_ai["items"][0]["ai_validator_prompt"] = "Check the merged result carefully."
    validated_inline = service.validate(project, inline_ai)["draft"]
    assert validated_inline["items"][0]["ai_validator_prompt"] == "Check the merged result carefully."

    both_prompt_sources = json.loads(json.dumps(file_prompt))
    both_prompt_sources["items"][0]["prompt"] = "inline"
    with pytest.raises(ValueError, match="prompt and goal_file cannot both be set"):
        service.validate(project, both_prompt_sources)

    missing_prompt = json.loads(json.dumps(file_prompt))
    missing_prompt["items"][0]["goal_file"] = ""
    with pytest.raises(ValueError, match="prompt or goal_file is required"):
        service.validate(project, missing_prompt)

    both_ai_sources = json.loads(json.dumps(inline_ai))
    both_ai_sources["items"][0]["ai_validator_prompt_file"] = str(project / "ai.md")
    with pytest.raises(ValueError, match="AI Validator Prompt text and file cannot both be set"):
        service.validate(project, both_ai_sources)

    no_ai_workflow = json.loads(json.dumps(file_prompt))
    no_ai_workflow["items"][0].update({
        "prompt": "plain",
        "goal_file": "",
        "workflow": "plain.yaml",
        "validator": "",
        "ai_validator_prompt": "custom",
    })
    with pytest.raises(ValueError, match="requires an AI validation Workflow"):
        service.validate(project, no_ai_workflow)


def test_task_upload_materializes_before_task_commit_and_is_fail_closed(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    uploads = TaskUploadService()
    service = TaskService(uploads=uploads)
    item_id = "item-upload-1"
    staged = uploads.stage(
        project,
        item_id=item_id,
        kind="validator",
        filename="validate.py",
        content_base64=base64.b64encode(b"print('ok')\n").decode("ascii"),
    )
    draft = {
        "title": "Upload task",
        "items": [{
            "item_id": item_id,
            "title": "A",
            "prompt": "Do A",
            "workflow": "workflow.yaml",
            "project": str(project),
            "workspace": "auto",
            "validator": staged["path"],
        }],
    }
    created = service.create(project, draft, request_id="upload-create")
    assert created["items"][0]["item_id"] == item_id
    assert created["items"][0]["validator"] == staged["path"]
    assert Path(staged["path"]).read_bytes() == b"print('ok')\n"
    assert uploads.staged_exists(project, staged["path"]) is False

    goal_staged = uploads.stage(
        project,
        item_id="item-goal-upload",
        kind="goal",
        filename="goal.md",
        content_base64=base64.b64encode(b"uploaded goal\n").decode("ascii"),
    )
    goal_draft = json.loads(json.dumps(draft))
    goal_draft["title"] = "Goal upload task"
    goal_draft["items"][0].update({
        "item_id": "item-goal-upload",
        "prompt": "",
        "goal_file": goal_staged["path"],
        "validator": "",
    })
    goal_created = service.create(project, goal_draft, request_id="goal-upload-create")
    assert goal_created["items"][0]["prompt"] == ""
    assert goal_created["items"][0]["goal_file"] == goal_staged["path"]
    assert Path(goal_staged["path"]).read_bytes() == b"uploaded goal\n"
    assert uploads.staged_exists(project, goal_staged["path"]) is False

    failed = uploads.stage(
        project,
        item_id="item-upload-fail",
        kind="validator",
        filename="broken.py",
        content_base64=base64.b64encode(b"broken").decode("ascii"),
    )
    bad_draft = json.loads(json.dumps(draft))
    bad_draft["title"] = "Fail closed"
    bad_draft["items"][0]["item_id"] = "item-upload-fail"
    bad_draft["items"][0]["validator"] = failed["path"]
    original_copy = uploads._atomic_copy
    uploads._atomic_copy = lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("copy blocked"))
    try:
        with pytest.raises(ValueError, match="materialize"):
            service.create(project, bad_draft, request_id="upload-fail")
    finally:
        uploads._atomic_copy = original_copy
    assert [row["title"] for row in service.list(project)["tasks"]] == ["Upload task", "Goal upload task"]
    assert uploads.staged_exists(project, failed["path"]) is True


def test_task_upload_http_stage_and_cancel(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    project = repo / "project"
    (repo / "ui" / "data").mkdir(parents=True)
    (repo / "ui" / "static").mkdir(parents=True)
    project.mkdir()

    server = UIServer(repo, "127.0.0.1", 0)
    server.state.add_project(str(project))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.port}"
    try:
        staged = _json_request(
            f"{base}/api/tasks/upload/stage",
            method="POST",
            body={
                "project": str(project),
                "item_id": "item-http-upload",
                "kind": "ai-validator",
                "filename": "review.md",
                "content_base64": base64.b64encode(b"review me").decode("ascii"),
                "request_id": "upload-stage-1",
            },
        )
        assert ".ai-task-runner" in staged["path"]
        assert server.state.task_uploads.staged_exists(project, staged["path"]) is True
        cancelled = _json_request(
            f"{base}/api/tasks/upload/cancel",
            method="POST",
            body={
                "project": str(project),
                "path": staged["path"],
                "request_id": "upload-cancel-1",
            },
        )
        assert cancelled["cancelled"] is True
        assert server.state.task_uploads.staged_exists(project, staged["path"]) is False

        bad_request = urllib.request.Request(
            f"{base}/api/tasks/upload/stage",
            data=json.dumps({
                "project": str(project),
                "item_id": "item-http-upload",
                "kind": "unsupported",
                "filename": "review.md",
                "content_base64": base64.b64encode(b"review me").decode("ascii"),
                "request_id": "upload-error-1",
            }).encode("utf-8"),
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        with pytest.raises(urllib.error.HTTPError) as exc_info:
            urllib.request.urlopen(bad_request, timeout=5)
        payload = json.loads(exc_info.value.read().decode("utf-8"))
        assert payload["request_id"] == "upload-error-1"
        assert payload["code"] == "invalid_request"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_task_validation_fails_closed_for_missing_workflow(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    project = repo / "project"
    project.mkdir(parents=True)

    def requirements(_project: Path, workflow: str) -> dict:
        return {
            "exists": workflow == "valid.workflow.yaml",
            "requires_python_validator": False,
            "has_ai_validator": False,
        }

    generated = TaskDraftService(
        repo,
        workflow_requirements=requirements,
        runner=lambda **kwargs: {
            "draft": {"title": "Draft", "items": [{"title": "A", "prompt": "Do A"}]},
        },
    )
    with pytest.raises(ValueError, match="Selected Workflow does not exist"):
        generated.generate(
            project,
            spec="missing workflow",
            draft_mode="single",
            backend="qwen",
            workflow="missing.workflow.yaml",
            request_id="missing-generated-workflow",
        )

    service = TaskService(workflow_requirements=requirements)
    draft = {
        "title": "Missing workflow",
        "items": [{
            "title": "A",
            "prompt": "Do A",
            "workflow": "missing.workflow.yaml",
            "project": str(project),
            "workspace": "auto",
        }],
    }
    with pytest.raises(ValueError, match="Workflow does not exist"):
        service.validate(project, draft)

    draft["items"][0]["workflow"] = "valid.workflow.yaml"
    assert service.validate(project, draft)["draft"]["items"][0]["workflow"] == "valid.workflow.yaml"

def test_task_service_enforces_workflow_capability_inputs(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()

    def requirements(_project: Path, workflow: str) -> dict:
        return {
            "requires_python_validator": workflow == "mixed.workflow.yaml",
            "has_ai_validator": workflow == "mixed.workflow.yaml",
        }

    service = TaskService(workflow_requirements=requirements)
    draft = {
        "title": "Capability task",
        "items": [{
            "title": "A",
            "prompt": "Do A",
            "workflow": "mixed.workflow.yaml",
            "project": str(project),
            "workspace": "auto",
        }],
    }

    with pytest.raises(ValueError, match="File Validator is required"):
        service.validate(project, draft)

    draft["items"][0]["validator"] = str(project / "validate.py")
    default_ai = service.validate(project, draft)["draft"]
    assert default_ai["items"][0]["ai_validator_prompt"] == ""
    assert default_ai["items"][0]["ai_validator_prompt_file"] == ""

    draft["items"][0]["ai_validator_prompt_file"] = str(project / "review.md")
    validated = service.validate(project, draft)["draft"]
    assert validated["items"][0]["validator"].endswith("validate.py")
    assert validated["items"][0]["ai_validator_prompt_file"].endswith("review.md")

    plain = json.loads(json.dumps(draft))
    plain["items"][0]["workflow"] = "plain.workflow.yaml"
    plain["items"][0]["validator"] = ""
    plain["items"][0]["ai_validator_prompt_file"] = ""
    assert service.validate(project, plain)["draft"]["items"][0]["validator"] == ""


def test_task_yaml_roundtrip_uses_canonical_draft_validation_and_preserves_ids(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    service = TaskService()
    draft = {
        "title": "YAML list",
        "items": [
            {"item_id": "keep-a", "title": "A", "prompt": "A\nline 2", "workflow": "workflow.yaml", "project": str(project), "workspace": "auto"},
            {"item_id": "keep-b", "title": "B", "prompt": "B", "workflow": "workflow.yaml", "project": str(project), "workspace": "main"},
        ],
    }

    dumped = service.dump_yaml(project, draft)
    assert "title: YAML list" in dumped["content"]
    assert "item_id: keep-a" in dumped["content"]
    parsed = service.parse_yaml(project, dumped["content"])["draft"]
    assert parsed["title"] == "YAML list"
    assert [item["item_id"] for item in parsed["items"]] == ["keep-a", "keep-b"]
    assert parsed["items"][0]["prompt"] == "A\nline 2"

    with pytest.raises(ValueError, match="invalid"):
        service.parse_yaml(project, "title: [")
    with pytest.raises(ValueError, match="at least one"):
        service.parse_yaml(project, "title: Empty\nitems: []\n")
    with pytest.raises(ValueError, match="workspace policy"):
        service.parse_yaml(
            project,
            "title: Bad\nitems:\n  - title: A\n    prompt: A\n    workflow: workflow.yaml\n    workspace: magic\n",
        )


def test_task_service_updates_new_task_idempotently_and_preserves_item_identity(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    service = TaskService()
    base = {
        "title": "List",
        "items": [
            {"title": "A", "prompt": "A", "workflow": "workflow.yaml", "project": str(project), "workspace": "auto"},
            {"title": "B", "prompt": "B", "workflow": "workflow.yaml", "project": str(project), "workspace": "main"},
        ],
    }
    created = service.create(project, base, request_id="create-update")
    first_id, second_id = [item["item_id"] for item in created["items"]]
    edited = {
        "title": "Reordered",
        "items": [
            {**created["items"][1], "prompt": "B edited"},
            {**created["items"][0], "prompt": "A edited"},
        ],
    }

    updated = service.update(
        project,
        created["task_id"],
        edited,
        request_id="update-1",
        expected_updated_at=created["updated_at"],
    )
    assert updated["duplicate"] is False
    assert updated["title"] == "Reordered"
    assert [item["item_id"] for item in updated["items"]] == [second_id, first_id]
    assert [item["prompt"] for item in updated["items"]] == ["B edited", "A edited"]

    duplicate = TaskService().update(
        project,
        created["task_id"],
        edited,
        request_id="update-1",
        expected_updated_at=created["updated_at"],
    )
    assert duplicate["duplicate"] is True
    assert duplicate["updated_at"] == updated["updated_at"]


def test_task_service_paused_edit_policy_locks_completed_prefix_and_restarts_current(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    service = TaskService()
    draft = {
        "title": "Paused list",
        "items": [
            {"title": "Done", "prompt": "Done prompt", "workflow": "workflow.yaml", "project": str(project), "workspace": "auto"},
            {"title": "Current", "prompt": "Current prompt", "workflow": "workflow.yaml", "project": str(project), "workspace": "main"},
            {"title": "Future A", "prompt": "Future A", "workflow": "workflow.yaml", "project": str(project), "workspace": "auto"},
            {"title": "Future B", "prompt": "Future B", "workflow": "workflow.yaml", "project": str(project), "workspace": "worktree"},
        ],
    }
    created = service.create(project, draft, request_id="paused-create")
    state_path = service._state_path(project)
    raw = json.loads(state_path.read_text(encoding="utf-8"))
    raw["tasks"][0]["status"] = "paused"
    raw["tasks"][0]["completed_item_count"] = 1
    state_path.write_text(json.dumps(raw), encoding="utf-8")

    paused = service.get(project, created["task_id"])
    policy = paused["edit_policy"]
    assert policy["editable"] is True
    assert policy["completed_item_count"] == 1
    assert policy["current_item_index"] == 1
    assert policy["can_add_item"] is True
    assert policy["can_edit_yaml"] is False
    assert [row["state"] for row in policy["items"]] == [
        "completed", "current", "future", "future",
    ]
    assert policy["items"][0]["editable"] is False
    assert policy["items"][1]["editable"] is True
    assert policy["items"][1]["restructure"] is False
    assert policy["items"][2]["restructure"] is True

    completed_changed = {
        "title": paused["title"],
        "items": json.loads(json.dumps(paused["items"])),
    }
    completed_changed["items"][0]["prompt"] = "rewrite completed history"
    with pytest.raises(ValueError, match="Completed Task items cannot be modified"):
        service.update(
            project,
            paused["task_id"],
            completed_changed,
            request_id="paused-change-completed",
            expected_updated_at=paused["updated_at"],
        )

    current_removed = {
        "title": paused["title"],
        "items": [paused["items"][0], paused["items"][2], paused["items"][3]],
    }
    with pytest.raises(ValueError, match="Current paused Task item cannot be moved or removed"):
        service.update(
            project,
            paused["task_id"],
            current_removed,
            request_id="paused-remove-current",
            expected_updated_at=paused["updated_at"],
        )

    allowed = {
        "title": "Paused list renamed",
        "items": [
            paused["items"][0],
            {**paused["items"][1], "prompt": "Current prompt edited"},
            paused["items"][3],
            paused["items"][2],
            {
                "title": "Future C",
                "prompt": "Future C",
                "workflow": "workflow.yaml",
                "project": str(project),
                "workspace": "auto",
            },
        ],
    }
    updated = service.update(
        project,
        paused["task_id"],
        allowed,
        request_id="paused-allowed",
        expected_updated_at=paused["updated_at"],
    )
    assert updated["status"] == "paused"
    assert updated["restart_required"] is True
    assert updated["edit_policy"]["restart_required"] is True
    assert updated["items"][0]["item_id"] == paused["items"][0]["item_id"]
    assert updated["items"][1]["item_id"] == paused["items"][1]["item_id"]
    assert [row["title"] for row in updated["items"][2:4]] == ["Future B", "Future A"]
    assert updated["items"][4]["item_id"].startswith(paused["task_id"] + "-item-")


def test_task_service_update_rejects_stale_or_non_new_task(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    service = TaskService()
    draft = {
        "title": "One",
        "items": [
            {"title": "A", "prompt": "A", "workflow": "workflow.yaml", "project": str(project), "workspace": "auto"},
        ],
    }
    created = service.create(project, draft, request_id="create-stale")

    with pytest.raises(ValueError, match="changed since"):
        service.update(
            project,
            created["task_id"],
            draft,
            request_id="stale-update",
            expected_updated_at=created["updated_at"] - 1,
        )

    state_path = service._state_path(project)
    raw = json.loads(state_path.read_text(encoding="utf-8"))
    raw["tasks"][0]["status"] = "ongoing"
    state_path.write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(ValueError, match="must be New or Paused"):
        service.update(
            project,
            created["task_id"],
            draft,
            request_id="ongoing-update",
            expected_updated_at=created["updated_at"],
        )


def test_task_service_delete_is_idempotent_and_blocks_non_new(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    service = TaskService()
    draft = {
        "title": "Delete me",
        "items": [
            {"title": "A", "prompt": "A", "workflow": "workflow.yaml", "project": str(project), "workspace": "auto"},
        ],
    }
    created = service.create(project, draft, request_id="delete-create")
    deleted = service.delete(project, created["task_id"], request_id="delete-1")
    assert deleted == {"task_id": created["task_id"], "deleted": True, "duplicate": False}
    assert service.list(project)["tasks"] == []
    duplicate = TaskService().delete(project, created["task_id"], request_id="delete-1")
    assert duplicate == {"task_id": created["task_id"], "deleted": True, "duplicate": True}

    blocked = service.create(project, draft, request_id="delete-blocked-create")
    path = service._state_path(project)
    raw = json.loads(path.read_text(encoding="utf-8"))
    raw["tasks"][0]["status"] = "ongoing"
    path.write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(ValueError, match="Only New Tasks"):
        service.delete(project, blocked["task_id"], request_id="delete-blocked")
    assert service.get(project, blocked["task_id"])["status"] == "ongoing"


def test_task_service_rejects_invalid_project_items_and_workspace(tmp_path: Path) -> None:
    project = tmp_path / "project"
    other = tmp_path / "other"
    project.mkdir()
    other.mkdir()
    service = TaskService()
    item = {
        "title": "A",
        "prompt": "Do A",
        "workflow": "workflow.yaml",
        "project": str(project),
        "workspace": "auto",
    }
    with pytest.raises(ValueError, match="selected Project"):
        service.create(
            project,
            {"title": "Bad", "items": [{**item, "project": str(other)}]},
            request_id="mismatch",
        )
    with pytest.raises(ValueError, match="at least one"):
        service.create(project, {"title": "Empty", "items": []}, request_id="empty")
    with pytest.raises(ValueError, match="workspace policy"):
        service.create(
            project,
            {"title": "Bad", "items": [{**item, "workspace": "magic"}]},
            request_id="workspace",
        )


def test_task_lifecycle_http_routes_delegate_to_task_run_service(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    project = repo / "project"
    (repo / "ui" / "data").mkdir(parents=True)
    (repo / "ui" / "static").mkdir(parents=True)
    project.mkdir()
    server = UIServer(repo, "127.0.0.1", 0)
    calls: list[tuple[str, Path, str, str]] = []

    def reset(project_path: Path, task_id: str, *, request_id: str):
        calls.append(("reset", project_path, task_id, request_id))
        return {"task_id": task_id, "status": "new"}

    def rerun(project_path: Path, task_id: str, *, request_id: str):
        calls.append(("rerun", project_path, task_id, request_id))
        return {"task_id": task_id, "status": "ongoing"}

    def publish(project_path: Path, task_id: str, *, request_id: str):
        calls.append(("publish", project_path, task_id, request_id))
        return {"task_id": task_id, "status": "closed", "publish": "published"}

    server.state.task_runs.reset = reset
    server.state.task_runs.rerun = rerun
    server.state.task_runs.publish = publish
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.port}"
    try:
        reset_value = _json_request(
            f"{base}/api/tasks/reset",
            method="POST",
            body={
                "project": str(project),
                "task_id": "task-" + "a" * 32,
                "request_id": "http-task-reset",
            },
        )
        rerun_value = _json_request(
            f"{base}/api/tasks/rerun",
            method="POST",
            body={
                "project": str(project),
                "task_id": "task-" + "b" * 32,
                "request_id": "http-task-rerun",
            },
        )
        publish_value = _json_request(
            f"{base}/api/tasks/publish",
            method="POST",
            body={
                "project": str(project),
                "task_id": "task-" + "c" * 32,
                "request_id": "http-task-publish",
            },
        )
        assert reset_value["status"] == "new"
        assert rerun_value["status"] == "ongoing"
        assert publish_value["publish"] == "published"
        assert calls == [
            ("reset", project.resolve(), "task-" + "a" * 32, "http-task-reset"),
            ("rerun", project.resolve(), "task-" + "b" * 32, "http-task-rerun"),
            ("publish", project.resolve(), "task-" + "c" * 32, "http-task-publish"),
        ]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_task_draft_and_create_http_contract_are_separate(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    project = repo / "project"
    (repo / "ui" / "data").mkdir(parents=True)
    (repo / "ui" / "static").mkdir(parents=True)
    project.mkdir()
    workflow_root = repo / "runner" / "assets" / "workflows"
    workflow_root.mkdir(parents=True)
    (workflow_root / "workflow.yaml").write_text("stages: {}\nflow: []\n", encoding="utf-8")

    server = UIServer(repo, "127.0.0.1", 0)
    registered = server.state.add_project(str(project))
    server.state.project_preferences.update(project, {
        "agent": "qwen",
        "workflow": "workflow.yaml",
    })
    server.state.task_drafts = TaskDraftService(
        repo,
        runner=lambda **kwargs: {
            "draft": {
                "title": "Generated",
                "items": [{"title": "Only", "prompt": "Do it"}],
            }
        },
    )
    session_id = server.state.chat_service.sessions(project)["active_session_id"]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.port}"
    try:
        generated = _json_request(
            f"{base}/api/chat/task-draft",
            method="POST",
            body={
                "project": str(project),
                "session_id": session_id,
                "mode": "single",
                "spec": "make one task",
                "request_id": "http-draft-1",
            },
        )
        assert generated["draft"]["items"][0]["workflow"] == "workflow.yaml"
        assert generated["session_id"] == session_id
        assert "task_id" not in generated
        assert server.state.tasks.list(project)["tasks"] == []
        runtime_root = project / ".ai-task-runner"
        assert not (runtime_root / "state.json").exists()
        assert not (runtime_root / "runner-process.json").exists()
        assert not (runtime_root / "stop.request").exists()
        assert not (runtime_root / "ui" / "tasks.json").exists()
        assert not (runtime_root / "ui" / "messages.jsonl").exists()

        edited_transient = json.loads(json.dumps(generated["draft"]))
        edited_transient["items"][0]["prompt"] = "Edited transient draft"
        transient = _json_request(
            f"{base}/api/chat/task-draft/update",
            method="POST",
            body={
                "project": str(project),
                "session_id": session_id,
                "draft_id": generated["draft_id"],
                "draft": edited_transient,
            },
        )
        assert transient["draft"]["items"][0]["prompt"] == "Edited transient draft"
        assert server.state.tasks.list(project)["tasks"] == []
        assert not (runtime_root / "state.json").exists()
        assert not (runtime_root / "runner-process.json").exists()

        validated = _json_request(
            f"{base}/api/tasks/validate-draft",
            method="POST",
            body={
                "project": str(project),
                "draft": generated["draft"],
            },
        )
        assert validated["draft"]["items"][0]["prompt"] == "Do it"
        assert server.state.tasks.list(project)["tasks"] == []

        created = _json_request(
            f"{base}/api/tasks/create-from-draft",
            method="POST",
            body={
                "project": str(project),
                "session_id": session_id,
                "draft_id": generated["draft_id"],
                "request_id": "http-create-1",
            },
        )
        assert created["status"] == "new"
        assert created["project_id"] == registered["project_id"]
        assert created["items"][0]["prompt"] == "Edited transient draft"
        assert server.state.tasks.list(project)["tasks"][0]["task_id"] == created["task_id"]

        repeated_create = _json_request(
            f"{base}/api/tasks/create-from-draft",
            method="POST",
            body={
                "project": str(project),
                "session_id": session_id,
                "draft_id": generated["draft_id"],
                "request_id": "http-create-1",
            },
        )
        assert repeated_create["duplicate"] is True
        assert repeated_create["task_id"] == created["task_id"]
        assert len(server.state.tasks.list(project)["tasks"]) == 1

        dismissed = _json_request(
            f"{base}/api/chat/task-draft/dismiss",
            method="POST",
            body={
                "project": str(project),
                "session_id": session_id,
                "draft_id": generated["draft_id"],
            },
        )
        assert dismissed["dismissed"] is True

        dumped = _json_request(
            f"{base}/api/tasks/yaml/dump",
            method="POST",
            body={"project": str(project), "draft": created},
        )
        parsed_yaml = _json_request(
            f"{base}/api/tasks/yaml/parse",
            method="POST",
            body={"project": str(project), "content": dumped["content"]},
        )
        assert parsed_yaml["draft"]["items"][0]["item_id"] == created["items"][0]["item_id"]

        updated_draft = json.loads(json.dumps(generated["draft"]))
        updated_draft["title"] = "Updated over HTTP"
        updated_draft["items"][0]["item_id"] = created["items"][0]["item_id"]
        updated_draft["items"][0]["prompt"] = "Edited through API"
        updated = _json_request(
            f"{base}/api/tasks/update",
            method="POST",
            body={
                "project": str(project),
                "task_id": created["task_id"],
                "draft": updated_draft,
                "request_id": "http-update-1",
                "expected_updated_at": created["updated_at"],
            },
        )
        assert updated["title"] == "Updated over HTTP"
        assert updated["items"][0]["prompt"] == "Edited through API"
        assert updated["items"][0]["item_id"] == created["items"][0]["item_id"]

        task_state_path = server.state.tasks._state_path(project)
        raw_task_state = json.loads(task_state_path.read_text(encoding="utf-8"))
        raw_task_state["tasks"][0]["status"] = "paused"
        raw_task_state["tasks"][0]["completed_item_count"] = 0
        task_state_path.write_text(json.dumps(raw_task_state), encoding="utf-8")
        paused = server.state.tasks.get(project, created["task_id"])
        paused_draft = {
            "title": paused["title"],
            "items": json.loads(json.dumps(paused["items"])),
        }
        paused_draft["items"][0]["prompt"] = "Paused API edit"
        paused_updated = _json_request(
            f"{base}/api/tasks/update",
            method="POST",
            body={
                "project": str(project),
                "task_id": created["task_id"],
                "draft": paused_draft,
                "request_id": "http-paused-update-1",
                "expected_updated_at": paused["updated_at"],
            },
        )
        assert paused_updated["status"] == "paused"
        assert paused_updated["restart_required"] is True
        assert paused_updated["edit_policy"]["current_item_index"] == 0
        assert paused_updated["edit_policy"]["items"][0]["editable"] is True

        raw_task_state = json.loads(task_state_path.read_text(encoding="utf-8"))
        raw_task_state["tasks"][0]["status"] = "new"
        raw_task_state["tasks"][0]["restart_required"] = False
        task_state_path.write_text(json.dumps(raw_task_state), encoding="utf-8")

        deleted = _json_request(
            f"{base}/api/tasks/delete",
            method="POST",
            body={
                "project": str(project),
                "task_id": created["task_id"],
                "request_id": "http-delete-1",
            },
        )
        assert deleted["deleted"] is True
        assert server.state.tasks.list(project)["tasks"] == []
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
