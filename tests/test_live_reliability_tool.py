from __future__ import annotations

import http.client
import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from dataclasses import replace
from pathlib import Path

import pytest

from tool import qwen_live_reliability as live
from runner.workflow.loader import load_workflow

ROOT = Path(__file__).resolve().parents[1]


def settings(tmp_path: Path) -> live.Settings:
    return live.Settings(
        workspace=tmp_path,
        command="qwen",
        sandbox=False,
        run_timeout=60,
        agent_timeout=30,
        planning_timeout=30,
        pause=0,
        api_port=8080,
        soak_final_ai_every=8,
        soak_transient_api_every=4,
        soak_timeout_every=6,
        soak_yaml_every=7,
        soak_sandbox_every=7,
    )


def test_script_command_uses_canonical_yaml_entry(tmp_path: Path):
    script = tmp_path / "tasks.yaml"
    command = live.runner_command(settings(tmp_path), tmp_path, script=script, resume=True)

    assert command[command.index("--script") + 1] == str(script)
    assert "--goal-file" not in command
    assert "--validator" not in command
    assert "--resume" in command


def _option(command: list[str], name: str) -> str:
    return command[command.index(name) + 1]


def test_runner_command_inputs_select_builtin_validation_workflows(tmp_path: Path):
    project = tmp_path / "project"
    config = replace(settings(tmp_path), agent_timeout=30.0, planning_timeout=40.0)

    file_only = live.runner_command(config, project)
    assert _option(file_only, "--validator") == str(project / "validation.py")
    assert "--ai-validator-prompt" not in file_only
    assert "--validator-prompt" not in file_only
    assert "--workflow" not in file_only

    mixed = live.runner_command(config, project, final_ai=True)
    assert _option(mixed, "--validator") == str(project / "validation.py")
    assert _option(mixed, "--ai-validator-prompt") == live.case_prompt(
        live.FINAL_AI_PROMPT, "project-final-ai"
    )
    assert "--validator-prompt" not in mixed
    assert "--workflow" not in mixed

    ai_only = live.runner_command(config, project, final_ai=True, ai_only=True)
    assert _option(ai_only, "--validator") == "ai"
    assert _option(ai_only, "--validator-prompt") == live.case_prompt(
        live.FINAL_AI_PROMPT, "project-final-ai"
    )
    assert "--ai-validator-prompt" not in ai_only
    assert "--workflow" not in ai_only
    assert _option(file_only, "--agent-timeout") == "30"
    assert _option(file_only, "--planning-timeout") == "40"


def test_runner_timeout_arguments_must_be_whole_seconds():
    assert live.whole_seconds_arg(12.0) == "12"
    with pytest.raises(ValueError, match="whole seconds"):
        live.whole_seconds_arg(12.5)


def test_example_smoke_project_is_opt_in(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(sys, "argv", ["qwen_live_reliability.py"])
    assert live.arguments().example_smoke_project is None
    assert live.arguments().example_smoke_workflow is None

    monkeypatch.setattr(
        sys,
        "argv",
        ["qwen_live_reliability.py", "--example-smoke-project"],
    )
    assert live.arguments().example_smoke_project == live.DEFAULT_EXAMPLE_SMOKE_PROJECT


def test_live_reliability_defaults_to_three_minute_api_disconnect(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["qwen_live_reliability.py"])
    assert live.arguments().long_api_outage_seconds == 180


def test_live_probe_prompts_vary_from_the_first_line(tmp_path: Path):
    first = live.create_project(tmp_path, "case-001")
    second = live.create_project(tmp_path, "case-002")
    first_prompt = (first / "prompt.md").read_text(encoding="utf-8")
    second_prompt = (second / "prompt.md").read_text(encoding="utf-8")
    assert first_prompt != second_prompt
    assert first_prompt.splitlines()[0] == "Reliability case case-001. Follow only this case."
    assert second_prompt.splitlines()[0] == "Reliability case case-002. Follow only this case."


def test_example_smoke_matrix_builds_cross_product(tmp_path: Path):
    args = type("Args", (), {})()
    args.example_smoke_project = None
    args.example_smoke_workflow = None
    args.example_smoke_matrix_project = [tmp_path / "a", tmp_path / "b"]
    args.example_smoke_matrix_workflow = [tmp_path / "file.yaml", tmp_path / "mixed.yaml"]

    cases = live.example_smoke_cases(args)

    assert [(case.source, case.workflow) for case in cases] == [
        (tmp_path / "a", tmp_path / "file.yaml"),
        (tmp_path / "a", tmp_path / "mixed.yaml"),
        (tmp_path / "b", tmp_path / "file.yaml"),
        (tmp_path / "b", tmp_path / "mixed.yaml"),
    ]
    assert [case.name for case in cases] == [
        "example-smoke-a-file",
        "example-smoke-a-mixed",
        "example-smoke-b-file",
        "example-smoke-b-mixed",
    ]


def test_example_smoke_case_validation_requires_project_contract(tmp_path: Path):
    project = tmp_path / "project"
    project.mkdir()
    cases = [live.ExampleSmokeCase(project, None, "bad")]

    with pytest.raises(SystemExit, match="prompt.md and validation.py"):
        live.validate_example_smoke_cases(cases)


def test_example_smoke_case_validation_rejects_missing_workflow(tmp_path: Path):
    project = tmp_path / "project"
    project.mkdir()
    (project / "prompt.md").write_text("build\n", encoding="utf-8")
    (project / "validation.py").write_text("validate\n", encoding="utf-8")
    cases = [live.ExampleSmokeCase(project, tmp_path / "missing.yaml", "bad")]

    with pytest.raises(SystemExit, match="workflow must be an existing YAML file"):
        live.validate_example_smoke_cases(cases)


def test_transient_proxy_can_simulate_real_disconnect_and_recovery():
    class UpstreamHandler(BaseHTTPRequestHandler):
        def do_POST(self):
            body = b"{}"
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format, *args):
            pass

    upstream = ThreadingHTTPServer(("127.0.0.1", 0), UpstreamHandler)
    thread = threading.Thread(target=upstream.serve_forever, daemon=True)
    thread.start()
    try:
        with live.transient_proxy(int(upstream.server_address[1])) as control:
            control.disconnect = True
            connection = http.client.HTTPConnection("127.0.0.1", control.port, timeout=2)
            with pytest.raises((http.client.RemoteDisconnected, ConnectionResetError)):
                connection.request("POST", "/v1/chat/completions", body=b"{}")
                connection.getresponse()
            connection.close()
            assert control.failures >= 1

            control.disconnect = False
            connection = http.client.HTTPConnection("127.0.0.1", control.port, timeout=2)
            connection.request("POST", "/v1/chat/completions", body=b"{}")
            response = connection.getresponse()
            assert response.status == 200
            response.read()
            connection.close()
            assert control.successes >= 1
    finally:
        upstream.shutdown()
        upstream.server_close()
        thread.join(timeout=2)


def test_dense_coverage_requires_every_mixed_probe():
    complete = live.SoakResult(
        completed=1,
        mixed_validations=1,
        transient_recoveries=1,
        timeout_probes=1,
        yaml_runs=1,
        sandbox_runs=1,
        elapsed_seconds=1800,
    )
    live.require_dense_coverage(complete)

    with pytest.raises(RuntimeError, match="sandbox"):
        live.require_dense_coverage(
            live.SoakResult(
                completed=1,
                mixed_validations=1,
                transient_recoveries=1,
                timeout_probes=1,
                yaml_runs=1,
                elapsed_seconds=1800,
            )
        )


def test_assert_completed_supports_yaml_child_work_dir(tmp_path: Path):
    work = tmp_path / ".ai-task-runner" / "script" / "001"
    (work / "debug").mkdir(parents=True)
    (work / "state.json").write_text(
        '{"completed": true, "stage": "completed"}', encoding="utf-8"
    )
    (work / "log.txt").write_text("{}\n", encoding="utf-8")
    (work / "debug" / "last-prompt.txt").write_text("prompt", encoding="utf-8")
    (work / "debug" / "last-result.txt").write_text("result", encoding="utf-8")
    (tmp_path / "health.txt").write_text(live.EXPECTED, encoding="utf-8")

    live.assert_completed(tmp_path, 0, work_dir=".ai-task-runner/script/001")


def test_example_smoke_probe_copies_project_and_runs_regular_command(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    source = tmp_path / "source"
    source.mkdir()
    (source / "prompt.md").write_text("build\n", encoding="utf-8")
    (source / "validation.py").write_text("validate\n", encoding="utf-8")
    (source / ".ai-task-runner").mkdir()
    (source / ".ai-task-runner" / "state.json").write_text("old", encoding="utf-8")
    (source / "__pycache__").mkdir()
    (source / "__pycache__" / "x.pyc").write_text("old", encoding="utf-8")
    captured = {}

    def fake_run(command: list[str], log: Path, timeout: float, observe=None) -> int:
        captured["command"] = command
        captured["timeout"] = timeout
        project = Path(command[command.index("--project-root") + 1])
        assert not (project / ".ai-task-runner").exists()
        assert not (project / "__pycache__").exists()
        work = project / ".ai-task-runner"
        (work / "debug").mkdir(parents=True)
        (work / "state.json").write_text(
            '{"completed": true, "stage": "completed"}', encoding="utf-8"
        )
        (work / "log.txt").write_text("{}\n", encoding="utf-8")
        (work / "debug" / "last-prompt.txt").write_text("prompt", encoding="utf-8")
        (work / "debug" / "last-result.txt").write_text("result", encoding="utf-8")
        log.parent.mkdir(parents=True, exist_ok=True)
        log.write_text("", encoding="utf-8")
        return 0

    monkeypatch.setattr(live, "run_command", fake_run)

    project = live.example_smoke_probe(settings(tmp_path), tmp_path, source)

    assert project == tmp_path / "example-smoke-probe"
    assert (project / "prompt.md").is_file()
    assert (project / "validation.py").is_file()
    assert not (project / "__pycache__").exists()
    command = captured["command"]
    assert command[command.index("--goal-file") + 1] == str(project / "prompt.md")
    assert command[command.index("--validator") + 1] == str(project / "validation.py")
    assert "--script" not in command
    assert "--workflow" not in command
    assert "--ai-validator-prompt" not in command


def test_example_smoke_probe_can_run_custom_workflow(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    source = tmp_path / "source"
    source.mkdir()
    (source / "prompt.md").write_text("build\n", encoding="utf-8")
    (source / "validation.py").write_text("validate\n", encoding="utf-8")
    workflow = tmp_path / "workflow.yaml"
    workflow.write_text("stages: {}\nflow: []\n", encoding="utf-8")
    captured = {}

    def fake_run(command: list[str], log: Path, timeout: float, observe=None) -> int:
        captured["command"] = command
        project = Path(command[command.index("--project-root") + 1])
        work = project / ".ai-task-runner"
        (work / "debug").mkdir(parents=True)
        (work / "state.json").write_text(
            '{"completed": true, "stage": "completed"}', encoding="utf-8"
        )
        (work / "log.txt").write_text("{}\n", encoding="utf-8")
        (work / "debug" / "last-prompt.txt").write_text("prompt", encoding="utf-8")
        (work / "debug" / "last-result.txt").write_text("result", encoding="utf-8")
        log.parent.mkdir(parents=True, exist_ok=True)
        log.write_text("", encoding="utf-8")
        return 0

    monkeypatch.setattr(live, "run_command", fake_run)

    live.example_smoke_probe(settings(tmp_path), tmp_path, source, workflow)

    command = captured["command"]
    assert command[command.index("--workflow") + 1] == str(workflow)
    assert "--script" not in command


def test_example_smoke_probe_uses_case_name_for_copy(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    source = tmp_path / "source"
    source.mkdir()
    (source / "prompt.md").write_text("build\n", encoding="utf-8")
    (source / "validation.py").write_text("validate\n", encoding="utf-8")

    def fake_run(command: list[str], log: Path, timeout: float, observe=None) -> int:
        project = Path(command[command.index("--project-root") + 1])
        work = project / ".ai-task-runner"
        (work / "debug").mkdir(parents=True)
        (work / "state.json").write_text(
            '{"completed": true, "stage": "completed"}', encoding="utf-8"
        )
        (work / "log.txt").write_text("{}\n", encoding="utf-8")
        (work / "debug" / "last-prompt.txt").write_text("prompt", encoding="utf-8")
        (work / "debug" / "last-result.txt").write_text("result", encoding="utf-8")
        log.parent.mkdir(parents=True, exist_ok=True)
        log.write_text("", encoding="utf-8")
        return 0

    monkeypatch.setattr(live, "run_command", fake_run)

    project = live.example_smoke_probe(settings(tmp_path), tmp_path, source, name="case-a")

    assert project == tmp_path / "case-a"


@pytest.mark.parametrize(
    ("name", "hours"),
    [
        ("qwen_live_reliability_0_5h.bat", "0.5"),
        ("qwen_live_reliability_24h.bat", "24"),
    ],
)
def test_live_reliability_bat_files_run_matrix_smoke(name: str, hours: str):
    text = (ROOT / "tool" / name).read_text(encoding="utf-8")
    assert f"--hours {hours}" in text
    assert "--high-density --require-transient" in text
    assert "--example-smoke-matrix-project" in text
    assert "runner\\workflow\\builtin\\file.yaml" in text
    assert "runner\\workflow\\builtin\\mixed.yaml" in text
    assert "tool\\workflows\\skill_prompt_review_chain.yaml" in text


def _write_prompt_audit_fixture(tmp_path: Path, events: list[dict], prompts: dict[str, str]) -> Path:
    work = tmp_path / ".ai-task-runner"
    history = work / "debug" / "history"
    history.mkdir(parents=True)
    (work / "log.txt").write_text(
        "".join(json.dumps(event) + "\n" for event in events),
        encoding="utf-8",
    )
    for call_id, prompt in prompts.items():
        (history / f"{call_id}-prompt.txt").write_text(prompt, encoding="utf-8")
    return tmp_path


def test_prompt_records_correlate_stage_and_history(tmp_path: Path):
    project = _write_prompt_audit_fixture(
        tmp_path,
        [
            {"type": "runner.stage", "action": "start", "stage": "execute"},
            {"type": "model.prompt", "call_id": "c1", "session": "s1", "session_mode": "resume"},
            {"type": "runner.stage", "action": "finish", "stage": "execute", "result": "pass"},
        ],
        {"c1": "Continue the same execute stage.\nPrevious failure: x\n"},
    )

    records = live.prompt_records(project)

    assert len(records) == 1
    assert records[0].stage == "execute"
    assert records[0].session == "s1"
    assert records[0].text.startswith("Continue the same execute stage")


def test_prompt_contract_rejects_static_context_on_same_session_retry(tmp_path: Path):
    project = _write_prompt_audit_fixture(
        tmp_path,
        [
            {"type": "runner.stage", "action": "start", "stage": "execute"},
            {"type": "model.prompt", "call_id": "c1", "session": "s1", "session_mode": "resume"},
        ],
        {
            "c1": (
                "Continue the same execute stage.\n"
                "Previous failure: x\n"
                "Goal (context/global constraints only): repeated\n"
            )
        },
    )

    with pytest.raises(RuntimeError, match="resent static stage context"):
        live.assert_prompt_transport_contract(project)


def test_prompt_contract_requires_stage_instructions_on_fresh_retry(tmp_path: Path):
    project = _write_prompt_audit_fixture(
        tmp_path,
        [
            {"type": "runner.stage", "action": "start", "stage": "execute"},
            {"type": "model.prompt", "call_id": "c1", "session": "", "session_mode": "new"},
        ],
        {"c1": "Continue the same execute stage in a fresh session.\n"},
    )

    with pytest.raises(RuntimeError, match="omitted stage instructions"):
        live.assert_prompt_transport_contract(project)


@pytest.mark.parametrize(
    ("workflow", "validators"),
    [
        ("file", ["validate_file"]),
        ("ai", ["validate_ai"]),
        ("mixed", ["validate_file", "validate_ai"]),
    ],
)
def test_builtin_topology_contract(tmp_path: Path, workflow: str, validators: list[str]):
    stages = ["planning", "execute", "review", *validators]
    project = tmp_path
    work = project / ".ai-task-runner"
    work.mkdir()
    events = [
        event
        for stage in stages
        for event in (
            {"type": "runner.stage", "action": "start", "stage": stage},
            {"type": "runner.stage", "action": "finish", "stage": stage, "result": "pass"},
        )
    ]
    (work / "log.txt").write_text(
        "".join(json.dumps(event) + "\n" for event in events),
        encoding="utf-8",
    )

    live.assert_builtin_topology(project, workflow)

@pytest.mark.parametrize("content", ["READY\nREVIEW_REQUIRED", "READY\nREVIEW_REQUIRED\n"])
def test_review_repair_validator_accepts_two_logical_lines_with_optional_final_newline(
    tmp_path: Path,
    content: str,
):
    validator = tmp_path / "validation.py"
    validator.write_text(live.REVIEW_REPAIR_VALIDATOR, encoding="utf-8")
    (tmp_path / "review.txt").write_text(content, encoding="utf-8")
    state = tmp_path / "state.json"
    state.write_text("{}", encoding="utf-8")

    result = __import__("subprocess").run(
        [sys.executable, str(validator), "--project-root", str(tmp_path), "--state-file", str(state)],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    assert "VALIDATION_PASSED" in result.stdout


def test_review_repair_validator_failure_points_only_to_review_file(tmp_path: Path):
    validator = tmp_path / "validation.py"
    validator.write_text(live.REVIEW_REPAIR_VALIDATOR, encoding="utf-8")
    (tmp_path / "review.txt").write_text("READY\n", encoding="utf-8")
    state = tmp_path / "state.json"
    state.write_text("{}", encoding="utf-8")

    result = __import__("subprocess").run(
        [sys.executable, str(validator), "--project-root", str(tmp_path), "--state-file", str(state)],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 1
    assert "modify review.txt only" in result.stdout
    assert "validation.py" not in result.stdout


def test_review_repair_probe_contract_does_not_require_exact_eof_bytes():
    assert "A standard final newline is allowed." in live.REVIEW_REPAIR_PROMPT
    assert "Modify review.txt only" in live.REVIEW_REPAIR_PROMPT
    assert "splitlines()" in live.REVIEW_REPAIR_VALIDATOR


def test_review_repair_probe_uses_state_completion_and_semantic_repair_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    def fake_run(command: list[str], log: Path, timeout: float, observe=None) -> int:
        project = Path(command[command.index("--project-root") + 1])
        workflow = Path(command[command.index("--workflow") + 1])
        assert workflow == project / "workflow.yaml"
        assert workflow.read_text(encoding="utf-8") == live.REVIEW_REPAIR_WORKFLOW
        assert (project / "seed_review.py").read_text(encoding="utf-8") == live.REVIEW_REPAIR_SEED
        work = project / ".ai-task-runner"
        history = work / "debug" / "history"
        history.mkdir(parents=True)
        (work / "state.json").write_text(
            '{"completed": true, "stage": "completed"}', encoding="utf-8"
        )
        events = [
            {"type": "runner.stage", "action": "start", "stage": "review"},
            {"type": "runner.stage", "action": "finish", "stage": "review", "result": "fail"},
            {"type": "runner.stage", "action": "start", "stage": "repair"},
            {
                "type": "model.prompt",
                "call_id": "repair-1",
                "session": "execute-session",
                "session_mode": "resume",
            },
            {"type": "runner.stage", "action": "finish", "stage": "repair", "result": "pass"},
        ]
        (work / "log.txt").write_text(
            "".join(json.dumps(event) + "\n" for event in events), encoding="utf-8"
        )
        (history / "repair-1-prompt.txt").write_text(
            'Continue normal task execution in this same session.\nLatest review: {"missing_items":["REVIEW_REQUIRED"]}\n',
            encoding="utf-8",
        )
        (work / "debug" / "last-prompt.txt").write_text("prompt", encoding="utf-8")
        (work / "debug" / "last-result.txt").write_text("result", encoding="utf-8")
        (project / "review.txt").write_text("READY\nREVIEW_REQUIRED\n", encoding="utf-8")
        log.parent.mkdir(parents=True, exist_ok=True)
        log.write_text("", encoding="utf-8")
        return 0

    monkeypatch.setattr(live, "run_command", fake_run)

    live.review_repair_prompt_probe(settings(tmp_path), tmp_path)

    # This probe owns review.txt, not the generic health.txt contract.
    assert not (tmp_path / "review-repair-prompt-probe" / "health.txt").exists()


def test_review_repair_probe_uses_deterministic_seed_stage():
    assert "deterministically seeds review.txt with only READY" in live.REVIEW_REPAIR_PROMPT
    assert 'type: python' in live.REVIEW_REPAIR_WORKFLOW
    assert 'path: seed_review.py' in live.REVIEW_REPAIR_WORKFLOW
    assert 'skip_on_error: false' in live.REVIEW_REPAIR_WORKFLOW
    assert 'recover: [repair]' in live.REVIEW_REPAIR_WORKFLOW
    assert 'READY\\n' in live.REVIEW_REPAIR_SEED
    assert "intentionally write only READY" not in live.REVIEW_REPAIR_PROMPT


def test_review_repair_probe_workflow_forces_seed_before_review(tmp_path: Path):
    workflow_path = tmp_path / "workflow.yaml"
    workflow_path.write_text(live.REVIEW_REPAIR_WORKFLOW, encoding="utf-8")
    workflow = load_workflow(workflow_path)

    assert [node["name"] for node in workflow] == ["planning", "validate_file"]
    assert list(workflow[0]["planner_stages"]) == ["seed", "review"]
    assert workflow[0]["planner_stages"]["seed"]["type"] == "python"
    assert workflow[0]["planner_stages"]["review"]["recover"][0]["name"] == "repair"

    compile(live.REVIEW_REPAIR_SEED, "seed_review.py", "exec")
