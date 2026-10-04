from __future__ import annotations

from pathlib import Path

from ui.server import UIState


def _state(tmp_path: Path) -> tuple[UIState, Path]:
    for rel in (
        "runner/assets/workflows",
        "runner/assets/prompts/common",
        "runner/config",
        "runner/agent",
        "ui/data",
        "tool",
    ):
        (tmp_path / rel).mkdir(parents=True, exist_ok=True)
    for prompt_name in ("generic.md", "execution.md", "review.md"):
        (tmp_path / "runner/assets/prompts/common" / prompt_name).write_text(
            "{{ goal }}\n", encoding="utf-8"
        )
    (tmp_path / "runner/config/defaults.py").write_text(
        "DEFAULT_BACKEND='qwen'\n", encoding="utf-8"
    )
    (tmp_path / "runner/agent/qwen.py").write_text(
        "class QwenBackend: name='qwen'\n", encoding="utf-8"
    )
    (tmp_path / "tool/workflow_dryrun.py").write_text(
        "import json; print(json.dumps({'closed': True, 'valid': True}))\n",
        encoding="utf-8",
    )
    (tmp_path / "tool/workflow_catalog.py").write_text(
        "import json; print(json.dumps({'stage_types': {'base': {'profiles': {'generic': {'defaults': {'prompt': 'common/generic.md'}}, 'execute': {'defaults': {'prompt': 'common/execution.md'}}, 'review': {'defaults': {'prompt': 'common/review.md'}}}, 'options': [{'name':'backend','type':'enum','values':['qwen'],'default':''},{'name':'model','type':'str','default':''},{'name':'session_policy','type':'enum','values':['auto','main','role','fresh'],'default':'auto'}]}}, 'node_options': {}}))\n",
        encoding="utf-8",
    )
    project = tmp_path / "project"
    project.mkdir()
    return UIState(tmp_path), project


def test_project_policy_yaml_is_not_discovered_as_workflow(tmp_path: Path) -> None:
    state, project = _state(tmp_path)
    (project / ".ai-task-runner.yaml").write_text(
        "backend: qwen\n", encoding="utf-8"
    )
    assert not [
        row
        for row in state.studio_files(project)["workflows"]
        if row["scope"] == "project"
    ]


def test_project_workflow_and_categorized_prompt_use_split_asset_roots(
    tmp_path: Path,
) -> None:
    state, project = _state(tmp_path)
    workflow = state.studio_workflow_create("regression", "project", project)
    prompt = state.studio_prompt_create("common/review", "project", project)

    workflow_path = Path(workflow["item"]["path"])
    prompt_path = Path(prompt["item"]["path"])
    assert workflow_path.relative_to(project).as_posix() == (
        ".ai-task-runner/assets/workflows/regression.workflow.yaml"
    )
    assert prompt_path.relative_to(project).as_posix() == (
        ".ai-task-runner/assets/prompts/common/review.md"
    )
    assert prompt["item"]["reference"] == "common/review.md"

    rows = state.studio_files(project)
    assert [
        Path(row["path"]).name
        for row in rows["workflows"]
        if row["scope"] == "project"
    ] == ["regression.workflow.yaml"]
    assert [
        row["reference"]
        for row in rows["prompts"]
        if row["scope"] == "project"
    ] == ["common/review.md"]
    assert workflow["item"]["readonly"] is False
    assert prompt["item"]["readonly"] is False



def test_bare_prompt_name_defaults_to_common_category(tmp_path: Path) -> None:
    state, project = _state(tmp_path)
    created = state.studio_prompt_create("review", "global", project)

    path = Path(created["item"]["path"])
    assert path.relative_to(tmp_path).as_posix() == (
        "runner/assets/prompts/common/review.md"
    )
    assert created["item"]["reference"] == "common/review.md"
    assert created["item"]["display_name"] == "common/review.md"


def test_generator_project_workflow_output_returns_asset_package_root(
    tmp_path: Path,
) -> None:
    state, project = _state(tmp_path)
    raw, folder, scope, workflow, asset_root = state._workflow_output_paths(
        project, "ignored", "main.workflow.yaml", "project"
    )
    assert raw == "main.workflow.yaml"
    assert folder == ""
    assert scope == "project"
    assert workflow.relative_to(project).as_posix() == (
        ".ai-task-runner/assets/workflows/main.workflow.yaml"
    )
    assert asset_root.relative_to(project).as_posix() == ".ai-task-runner/assets"


def test_global_and_project_assets_are_structurally_symmetric(
    tmp_path: Path,
) -> None:
    state, project = _state(tmp_path)
    global_workflow = state.studio_workflow_create("global_job", "global", project)
    global_prompt = state.studio_prompt_create("common/global_review", "global", project)
    project_workflow = state.studio_workflow_create("project_job", "project", project)
    project_prompt = state.studio_prompt_create("common/project_review", "project", project)

    assert Path(global_workflow["item"]["path"]).parent == (
        tmp_path / "runner/assets/workflows"
    ).resolve()
    assert Path(global_prompt["item"]["path"]).parent == (
        tmp_path / "runner/assets/prompts/common"
    ).resolve()
    assert Path(project_workflow["item"]["path"]).parent == (
        project / ".ai-task-runner/assets/workflows"
    ).resolve()
    assert Path(project_prompt["item"]["path"]).parent == (
        project / ".ai-task-runner/assets/prompts/common"
    ).resolve()



def test_stage_yaml_accepts_unsaved_designer_stage_draft(tmp_path: Path) -> None:
    state, project = _state(tmp_path)
    created = state.studio_workflow_create("draft_stage_yaml", "project", project)
    file_id = created["item"]["id"]

    formatted = state.studio_stage_source(
        file_id,
        "ai_stage",
        "format",
        project,
        fields={"name": "ai_stage", "type": "base", "profile": "review"},
    )

    assert formatted["ok"] is True
    assert "type: base" in formatted["source"]
    assert "profile: review" in formatted["source"]

    parsed = state.studio_stage_source(
        file_id,
        "ai_stage",
        "parse",
        project,
        fields={"name": "ai_stage", "type": "base", "profile": "review"},
        source="type: base\nprofile: review\n",
    )

    assert parsed["ok"] is True
    assert parsed["fields"]["type"] == "base"
    assert parsed["fields"]["profile"] == "review"



def test_prompt_read_exposes_workflow_stage_usages(tmp_path: Path) -> None:
    state, project = _state(tmp_path)
    prompt = state.studio_prompt_create("common/used_review", "project", project)
    workflow = state.studio_workflow_create("uses_prompt", "project", project)

    workflow_file = state.studio_read(workflow["item"]["id"], project)
    content = (
        "stages:\n"
        "  review:\n"
        "    type: base\n"
        "    profile: review\n"
        "    prompt: common/used_review.md\n"
        "flow: [review]\n"
    )
    state.studio_save(
        workflow["item"]["id"],
        content,
        workflow_file["hash"],
        project,
    )

    loaded = state.studio_read(prompt["item"]["id"], project)

    assert loaded["used_by"] == ["uses_prompt.workflow.yaml · review"]



def test_workflow_save_allows_schema_valid_non_closing_route(tmp_path: Path) -> None:
    state, project = _state(tmp_path)
    (tmp_path / "tool/workflow_dryrun.py").write_text(
        "import json\n"
        "print(json.dumps({'valid': True, 'closed': False, 'cases': [{'name': 'happy path', 'passed': False}]}))\n"
        "raise SystemExit(1)\n",
        encoding="utf-8",
    )
    created = state.studio_workflow_create("intentional_stop", "project", project)
    current = state.studio_read(created["item"]["id"], project)
    content = (
        "stages:\n"
        "  execute:\n"
        "    type: base\n"
        "    profile: execute\n"
        "    routes:\n"
        "      pass: stop\n"
        "flow: [execute]\n"
    )

    saved = state.studio_save(
        created["item"]["id"],
        content,
        current["hash"],
        project,
    )

    assert "pass: stop" in saved["content"]
    reread = state.studio_read(created["item"]["id"], project)
    assert "pass: stop" in reread["content"]



def test_studio_path_test_reuses_workflow_dryrun_from_stage(tmp_path: Path) -> None:
    state, project = _state(tmp_path)
    (tmp_path / "tool/workflow_dryrun.py").write_text(
        "import json, sys\n"
        "if '--from-stage' in sys.argv:\n"
        "    stage = sys.argv[sys.argv.index('--from-stage') + 1]\n"
        "    payload = {\n"
        "      'valid': True, 'completed': True, 'from_stage': stage, 'cycle': 1, 'stage': 'completed',\n"
        "      'transitions': [{'number': 1, 'stage': stage, 'label': None, 'status': 'pass'}],\n"
        "      'error': None\n"
        "    }\n"
        "else:\n"
        "    payload = {'valid': True, 'closed': True, 'paths_passed': 1, 'paths_total': 1}\n"
        "print(json.dumps(payload))\n",
        encoding="utf-8",
    )
    created = state.studio_workflow_create("path_test", "project", project)
    current = state.studio_read(created["item"]["id"], project)
    state.studio_save(
        created["item"]["id"],
        (
            "stages:\n"
            "  first:\n"
            "    type: base\n"
            "    profile: generic\n"
            "  second:\n"
            "    type: base\n"
            "    profile: generic\n"
            "flow: [first, second]\n"
        ),
        current["hash"],
        project,
    )

    result = state.studio_path_test(created["item"]["id"], "second", project)

    assert result["ok"] is True
    assert result["from_stage"] == "second"
    assert result["completed"] is True
    assert result["transitions"] == [
        {"number": 1, "stage": "second", "label": None, "status": "pass"}
    ]


def test_studio_path_test_rejects_unknown_stage_before_subprocess(tmp_path: Path) -> None:
    state, project = _state(tmp_path)
    created = state.studio_workflow_create("path_unknown", "project", project)

    try:
        state.studio_path_test(created["item"]["id"], "missing", project)
    except ValueError as exc:
        assert str(exc) == "Stage not found: missing"
    else:
        raise AssertionError("unknown Stage path test must fail")



def test_stage_test_cancel_handles_pending_and_active_processes(tmp_path: Path, monkeypatch) -> None:
    state, _project = _state(tmp_path)
    stopped = []

    class FakeProcess:
        pid = 12345
        def poll(self):
            return None

    fake = FakeProcess()
    monkeypatch.setattr(state, "_terminate_stage_test_process", lambda process: stopped.append(process))

    pending = state.studio_stage_test_cancel("pending-test")
    assert pending == {"ok": True, "cancelled": True, "pending": True}

    lock, processes, cancelled = state._stage_test_runtime()
    assert "pending-test" in cancelled

    with lock:
        processes["active-test"] = fake
    active = state.studio_stage_test_cancel("active-test")
    assert active == {"ok": True, "cancelled": True, "pending": False}
    assert stopped == [fake]
    assert "active-test" in cancelled


def test_stage_test_pending_cancel_is_bounded(tmp_path: Path) -> None:
    state, _project = _state(tmp_path)

    for index in range(80):
        state.studio_stage_test_cancel(f"cancel-{index}")

    _lock, _processes, cancelled = state._stage_test_runtime()
    assert len(cancelled) <= 64



def test_stage_editor_accepts_backend_model_override(tmp_path: Path) -> None:
    state, project = _state(tmp_path)
    created = state.studio_workflow_create("backend_model", "project", project)
    file_id = created["item"]["id"]

    parsed = state.studio_stage_source(
        file_id,
        "execute",
        "parse",
        project,
        fields={"name": "execute", "type": "base", "profile": "execute"},
        source=(
            "type: base\n"
            "profile: execute\n"
            "backend: qwen\n"
            "model: stage-model\n"
            "session_policy: auto\n"
        ),
    )

    assert parsed["fields"]["backend"] == "qwen"
    assert parsed["fields"]["model"] == "stage-model"


def test_stage_editor_rejects_backend_override_with_main_session(tmp_path: Path) -> None:
    state, _project = _state(tmp_path)

    import pytest
    with pytest.raises(ValueError, match="session_policy: main"):
        state._validate_stage_editor_fields({
            "type": "base",
            "profile": "execute",
            "backend": "qwen",
            "session_policy": "main",
        })
