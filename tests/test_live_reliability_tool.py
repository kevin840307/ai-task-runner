from __future__ import annotations

import subprocess
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


def _fake_qwen_command(tmp_path: Path) -> str:
    fake = tmp_path / "fake_qwen.py"
    fake.write_text(
        "import json, os, sys\n"
        "from pathlib import Path\n"
        "args = sys.argv[1:]\n"
        "prompt = sys.stdin.buffer.read().decode('utf-8')\n"
        "resume = args[args.index('--resume') + 1] if '--resume' in args else ''\n"
        "session = resume or f'fake-session-{os.getpid()}'\n"
        "if 'Reply with exactly AGENT_PING_OK' in prompt:\n"
        "    answer = 'AGENT_PING_OK'\n"
        "elif '[RUNNER_IMMUTABLE_PLAN_PROTOCOL]' in prompt:\n"
        "    answer = json.dumps({'tasks':[{'title':'Create health probe','description':'Create health.txt exactly as required','deliverable':'health.txt','acceptance_criteria':['health.txt has exact requested text']}]})\n"
        "elif '[RUNNER_IMMUTABLE_REVIEW_PROTOCOL]' in prompt:\n"
        "    answer = json.dumps({'completed':True,'reason':'checked','missing_items':[]})\n"
        "elif '[RUNNER_IMMUTABLE_VALIDATION_PROTOCOL]' in prompt:\n"
        "    answer = json.dumps({'passed':True,'reason':'checked','missing_items':[],'checks_run':['fake deterministic check'],'suggested_checks':[]})\n"
        "else:\n"
        "    Path.cwd().joinpath('health.txt').write_text(" + repr(live.EXPECTED) + ", encoding='utf-8')\n"
        "    answer = 'completed current task'\n"
        "print(json.dumps([{'type':'system','subtype':'session_start','session_id':session},{'type':'result','subtype':'success','session_id':session,'result':answer}]))\n",
        encoding="utf-8",
    )
    return f'"{sys.executable}" "{fake}"'


def test_stage_probe_live_preflight_runs_agent_ping_and_review_with_fake_qwen(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    import runner.agent

    config = replace(settings(tmp_path), command=_fake_qwen_command(tmp_path))
    monkeypatch.setattr(live, "_discover_openai_model", lambda _port: "model-probe")
    monkeypatch.setattr(runner.agent, "default_command", lambda backend: "missing-opencode")
    monkeypatch.setattr(live.shutil, "which", lambda command: None)

    result = live.stage_probe_live_preflight(config)

    assert result == {
        "agent_ping": True,
        "real_stage_status": "pass",
        "real_stage_next": "done",
        "stage_backend": "qwen",
        "stage_model": "model-probe",
        "opencode_stage": {
            "available": False,
            "tested": False,
            "reason": "command_not_found",
        },
    }


def test_stage_probe_live_preflight_reports_installed_opencode_without_models(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    import runner.agent

    config = replace(settings(tmp_path), command=_fake_qwen_command(tmp_path))
    monkeypatch.setattr(live, "_discover_openai_model", lambda _port: "model-probe")
    monkeypatch.setattr(runner.agent, "default_command", lambda backend: "opencode-test")
    monkeypatch.setattr(runner.agent, "available_models", lambda backend, root: [])
    monkeypatch.setattr(live.shutil, "which", lambda command: "/fake/opencode")

    result = live.stage_probe_live_preflight(config)

    assert result["opencode_stage"] == {
        "available": True,
        "tested": False,
        "reason": "no_models",
    }


def test_stage_probe_live_preflight_executes_real_stage_override_with_fake_opencode(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    import runner.agent
    from runner.agent.opencode import OpenCodeBackend

    fake = tmp_path / "fake_opencode.py"
    fake.write_text(
        "import json, sys\n"
        "prompt = sys.stdin.read()\n"
        "answer = json.dumps({'completed': True, 'reason': 'checked', 'missing_items': []})\n"
        "print(json.dumps({'type':'text','sessionID':'oc-session','part':{'text':answer}}))\n",
        encoding="utf-8",
    )
    command = f'"{sys.executable}" "{fake}"'
    config = replace(settings(tmp_path), command=_fake_qwen_command(tmp_path))
    monkeypatch.setattr(live, "_discover_openai_model", lambda _port: "model-probe")
    monkeypatch.setattr(runner.agent, "default_command", lambda backend: command)
    monkeypatch.setattr(
        runner.agent,
        "available_models",
        lambda backend, root: ["provider/model-oc"],
    )
    monkeypatch.setattr(OpenCodeBackend, "default_command", command)
    monkeypatch.setattr(live.shutil, "which", lambda value: sys.executable)

    result = live.stage_probe_live_preflight(config)

    assert result["opencode_stage"] == {
        "available": True,
        "tested": True,
        "status": "pass",
        "model": "provider/model-oc",
    }


def test_script_command_uses_canonical_yaml_entry(tmp_path: Path):
    script = tmp_path / "tasks.yaml"
    command = live.runner_command(settings(tmp_path), tmp_path, script=script, resume=True)

    assert command[command.index("--script") + 1] == str(script)
    assert "--goal-file" not in command
    assert "--validator" not in command
    assert "--resume" in command
    assert "--no-ui-project-register" in command


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


def test_runner_command_uses_shared_retry_flags_only(tmp_path: Path):
    command = live.runner_command(settings(tmp_path), tmp_path)
    assert "--retry-delay" in command
    assert "--retry-max-delay" in command
    for removed in ("--execution-mode", "--retry-wait", "--retry-max-wait", "--max-attempts", "--max-cycles"):
        assert removed not in command


def test_live_runner_commands_disable_ui_project_registration(tmp_path: Path):
    project = tmp_path / "project"
    script = tmp_path / "tasks.yaml"
    workflow = tmp_path / "workflow.yaml"
    workflow.write_text(
        "stages:\n"
        "  work:\n"
        "    type: base\n"
        "    profile: generic\n"
        "flow: [work]\n",
        encoding="utf-8",
    )
    config = replace(settings(tmp_path), sandbox=True)

    commands = [
        live.runner_command(config, project),
        live.runner_command(config, project, final_ai=True),
        live.runner_command(config, project, final_ai=True, ai_only=True),
        live.runner_command(config, project, timeout_probe=True),
        live.runner_command(config, project, script=script),
        live.runner_command(config, project, workflow=workflow),
        live.runner_command(config, project, resume=True),
        live.runner_command(config, project, sandbox=False),
    ]

    assert all("--no-ui-project-register" in command for command in commands)


def test_live_builtin_final_ai_contract_matches_bundled_workflows():
    assert live.builtin_final_ai_contract("ai") == (3, 2, True)
    assert live.builtin_final_ai_contract("mixed") == (3, 2, True)


def test_live_builtin_review_error_policy_contract_matches_bundled_workflows():
    assert live.builtin_review_error_policy_contract() == {
        "file": 2,
        "ai": 2,
        "mixed": 2,
    }


def test_live_builtin_review_max_failures_contract_matches_bundled_workflows():
    assert live.builtin_review_max_failures_contract() == {
        "file": 3,
        "ai": 3,
        "mixed": 3,
    }


def test_live_builtin_review_error_policy_contract_rejects_missing_policy(
    monkeypatch: pytest.MonkeyPatch,
):
    from runner.workflow.stages import PlanStage

    monkeypatch.setattr(
        PlanStage,
        "_plan_child_stages",
        staticmethod(lambda _tasks: [{"name": "review", "type": "base", "profile": "review"}]),
    )
    with pytest.raises(RuntimeError, match="dynamic Plan Review error_policy mismatch"):
        live.builtin_review_error_policy_contract()


def test_live_builtin_readonly_safety_contract_matches_bundled_workflows():
    assert live.builtin_readonly_safety_contract() == {
        "file": {"planning": "observe", "dynamic_review": "observe"},
        "ai": {
            "planning": "observe",
            "validate_ai": "observe",
            "dynamic_review": "observe",
        },
        "mixed": {
            "planning": "observe",
            "validate_ai": "observe",
            "dynamic_review": "observe",
        },
    }


def test_live_builtin_readonly_safety_contract_rejects_missing_observe(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    bad = tmp_path / "file.yaml"
    bad.write_text(
        """
stages:
  planning:
    type: plan
    status: Plan
flow: [planning]
""",
        encoding="utf-8",
    )
    workflows = dict(live.WORKFLOWS)
    workflows["file"] = bad
    monkeypatch.setattr(live, "WORKFLOWS", workflows)

    with pytest.raises(RuntimeError, match="workflow/file planning readonly_safety mismatch"):
        live.builtin_readonly_safety_contract()


def test_builtin_workflow_probe_rejects_reused_final_ai_sessions(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    def fake_run(command: list[str], log: Path, timeout: float, observe=None) -> int:
        project = Path(command[command.index("--project-root") + 1])
        assert Path(command[command.index("--workflow") + 1]) == live.WORKFLOWS["ai"]
        work = project / ".ai-task-runner"
        history = work / "debug" / "history"
        history.mkdir(parents=True)
        (work / "state.json").write_text(
            json.dumps(
                {
                    "completed": True,
                    "stage": "completed",
                    "tasks": [{"id": "planning__g1__task-001", "title": "one", "status": "completed"}],
                    "expanded_workflow": [
                        {"name": "planning", "type": "plan"},
                        {"name": "planning__g1__task_001_execute", "type": "base", "profile": "execute"},
                        {"name": "planning__g1__task_001_review", "type": "base", "profile": "review"},
                        {"name": "validate_ai", "type": "ai_validator"},
                    ],
                }
            ),
            encoding="utf-8",
        )
        events = [
            {"type": "runner.stage", "action": "start", "stage": "planning"},
            {
                "type": "model.prompt",
                "call_id": "planning-1",
                "session": "planner",
                "session_mode": "fresh",
            },
            {"type": "runner.stage", "action": "start", "stage": "planning__g1__task_001_execute"},
            {"type": "runner.stage", "action": "start", "stage": "planning__g1__task_001_review"},
            {"type": "runner.stage", "action": "start", "stage": "validate_ai"},
            {"type": "model.result", "session": "validator-a"},
            {"type": "model.result", "session": "validator-b"},
        ]
        (work / "log.txt").write_text(
            "".join(json.dumps(event) + "\n" for event in events),
            encoding="utf-8",
        )
        (history / "planning-1-prompt.txt").write_text(
            "Plan the current goal.\n",
            encoding="utf-8",
        )
        (work / "debug" / "last-prompt.txt").write_text("prompt", encoding="utf-8")
        (work / "debug" / "last-result.txt").write_text("result", encoding="utf-8")
        (project / "health.txt").write_text(live.EXPECTED, encoding="utf-8")
        log.parent.mkdir(parents=True, exist_ok=True)
        log.write_text("", encoding="utf-8")
        return 0

    monkeypatch.setattr(live, "run_command", fake_run)

    with pytest.raises(RuntimeError, match="expected 3, got 2"):
        live.builtin_workflow_probe(settings(tmp_path), tmp_path, "ai")


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


def test_live_soak_presets_use_current_workflow_asset_paths():
    for name in ("qwen_live_reliability_0_5h.bat", "qwen_live_reliability_24h.bat"):
        text = (live.ROOT / "tool" / name).read_text(encoding="utf-8")
        assert "runner\\assets\\workflows\\file.yaml" in text
        assert "runner\\assets\\workflows\\mixed.yaml" in text
        assert "runner\\assets\\workflows\\ralphy_ai_validate.yaml" in text
        assert "runner\\workflows\\" not in text


def test_live_reliability_defaults_to_three_minute_api_disconnect(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["qwen_live_reliability.py"])
    args = live.arguments()
    assert args.long_api_outage_seconds == 180
    assert args.single_process_yaml_items == 0


def test_live_source_revision_records_head_and_tracked_dirty_state(monkeypatch):
    calls = []

    monkeypatch.setattr(live.shutil, "which", lambda command: "/usr/bin/git")

    def fake_run(command, **kwargs):
        calls.append(command)
        if command[-2:] == ["rev-parse", "HEAD"]:
            return subprocess.CompletedProcess(command, 0, stdout="a" * 40 + "\n")
        return subprocess.CompletedProcess(command, 0, stdout=" M runner/api.py\n")

    monkeypatch.setattr(live.subprocess, "run", fake_run)

    revision, dirty = live.source_revision(Path("/repo"))

    assert revision == "a" * 40
    assert dirty is True
    assert calls[0][-2:] == ["rev-parse", "HEAD"]
    assert calls[1][-2:] == ["--porcelain", "--untracked-files=no"]


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


def test_transient_proxy_can_simulate_429_and_503_statuses():
    with live.transient_proxy(1) as control:
        control.fail = True
        for status in (429, 503):
            control.status_code = status
            connection = http.client.HTTPConnection("127.0.0.1", control.port, timeout=2)
            connection.request("POST", "/v1/chat/completions", body=b"{}")
            response = connection.getresponse()
            body = response.read().decode("utf-8")
            connection.close()
            assert response.status == status
            assert f"HTTP {status}" in body
        assert control.failures == 2


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


def test_qwen_sandbox_preflight_rejects_unreachable_docker(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    config = replace(settings(tmp_path), soak_sandbox_every=7)
    monkeypatch.setattr(live.shutil, "which", lambda command: "docker")

    def fake_run(*args, **kwargs):
        return live.subprocess.CompletedProcess(
            args[0],
            1,
            stdout="failed to connect to the docker API at npipe",
        )

    monkeypatch.setattr(live.subprocess, "run", fake_run)

    with pytest.raises(RuntimeError, match="Qwen sandbox unavailable"):
        live.qwen_sandbox_preflight(config, hours=1)


def test_qwen_sandbox_preflight_skips_when_sandbox_disabled(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    config = replace(settings(tmp_path), sandbox=False, soak_sandbox_every=0)

    def fail_which(command: str):
        raise AssertionError("docker should not be checked")

    monkeypatch.setattr(live.shutil, "which", fail_which)

    live.qwen_sandbox_preflight(config)


def test_qwen_sandbox_preflight_skips_periodic_soak_when_hours_zero(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    config = replace(settings(tmp_path), sandbox=False, soak_sandbox_every=7)

    def fail_which(command: str):
        raise AssertionError("docker should not be checked for zero-hour soak")

    monkeypatch.setattr(live.shutil, "which", fail_which)

    live.qwen_sandbox_preflight(config, hours=0)


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
    workflow.write_text(
        "stages:\n"
        "  validate_file:\n"
        "    type: command\n"
        "    command: check\n"
        "flow: [validate_file]\n",
        encoding="utf-8",
    )
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
    assert command[command.index("--validator") + 1] == str(
        tmp_path / "example-smoke-probe" / "validation.py"
    )
    assert "--script" not in command


def test_example_smoke_probe_uses_ai_validator_for_ai_only_workflow(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    source = tmp_path / "source"
    source.mkdir()
    (source / "prompt.md").write_text("build\n", encoding="utf-8")
    (source / "validation.py").write_text("validate\n", encoding="utf-8")
    workflow = tmp_path / "workflow.yaml"
    workflow.write_text(
        "stages:\n"
        "  execute:\n"
        "    type: base\n"
        "    profile: execute\n"
        "  validate_ai:\n"
        "    type: ai_validator\n"
        "    validator: ai\n"
        "flow: [execute, validate_ai]\n",
        encoding="utf-8",
    )
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
    assert command[command.index("--validator") + 1] == "ai"
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
    ("name", "hours", "yaml_items"),
    [
        ("qwen_live_reliability_0_5h.bat", "0.5", "4"),
        ("qwen_live_reliability_24h.bat", "24", "8"),
    ],
)
def test_live_reliability_bat_files_run_matrix_smoke(name: str, hours: str, yaml_items: str):
    text = (ROOT / "tool" / name).read_text(encoding="utf-8")
    assert f"--hours {hours}" in text
    assert "--high-density --require-transient" in text
    assert f"--single-process-yaml-items {yaml_items}" in text
    assert "--example-smoke-matrix-project" in text
    assert "runner\\assets\\workflows\\file.yaml" in text
    assert "runner\\assets\\workflows\\mixed.yaml" in text
    assert "runner\\assets\\workflows\\ralphy_ai_validate.yaml" in text


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
        {"c1": "RUNNER_SHARED_STAGE_CONTROL\nmode: retry\nprevious_error: x\n"},
    )

    records = live.prompt_records(project)

    assert len(records) == 1
    assert records[0].stage == "execute"
    assert records[0].session == "s1"
    assert records[0].text.startswith("RUNNER_SHARED_STAGE_CONTROL")


def test_prompt_contract_rejects_static_context_on_same_session_retry(tmp_path: Path):
    project = _write_prompt_audit_fixture(
        tmp_path,
        [
            {"type": "runner.stage", "action": "start", "stage": "execute"},
            {"type": "model.prompt", "call_id": "c1", "session": "s1", "session_mode": "resume"},
        ],
        {
            "c1": (
                "RUNNER_SHARED_STAGE_CONTROL\nmode: retry\n"
                "previous_error: x\n"
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
        {"c1": "RUNNER_SHARED_STAGE_CONTROL\nmode: recover\n"},
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
    execute = "planning__g1__task_001_execute"
    review = "planning__g1__task_001_review"
    stages = ["planning", execute, review, *validators]
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
    (work / "state.json").write_text(
        json.dumps({
            "tasks": [{"title": "one", "status": "completed"}],
            "expanded_workflow": [
                {"name": "planning", "type": "plan"},
                {"name": execute, "type": "base", "profile": "execute"},
                {"name": review, "type": "base", "profile": "review"},
                *[{"name": name, "type": "command"} for name in validators],
            ],
        }),
        encoding="utf-8",
    )

    live.assert_builtin_topology(project, workflow)


def test_builtin_topology_contract_accepts_multiple_planned_todos(tmp_path: Path):
    project = tmp_path
    work = project / ".ai-task-runner"
    work.mkdir()
    dynamic = [
        name
        for index in range(1, 4)
        for name in (
            f"planning__g1__task_{index:03d}_execute",
            f"planning__g1__task_{index:03d}_review",
        )
    ]
    stages = ["planning", *dynamic, "validate_file", "validate_ai"]
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
    (work / "state.json").write_text(
        json.dumps({
            "tasks": [
                {"title": "one", "status": "completed"},
                {"title": "two", "status": "completed"},
                {"title": "three", "status": "completed"},
            ],
            "expanded_workflow": [
                {"name": "planning", "type": "plan"},
                *[
                    {"name": name, "type": "base", "profile": "review" if name.endswith("_review") else "execute"}
                    for name in dynamic
                ],
                {"name": "validate_file", "type": "command"},
                {"name": "validate_ai", "type": "ai_validator"},
            ],
        }),
        encoding="utf-8",
    )

    live.assert_builtin_topology(project, "mixed")


def test_builtin_topology_contract_rejects_uncovered_durable_todos(tmp_path: Path):
    project = tmp_path
    work = project / ".ai-task-runner"
    work.mkdir()
    stages = ["planning", "execute", "review", "validate_file", "validate_ai"]
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
    (work / "state.json").write_text(
        json.dumps(
            {
                "tasks": [
                    {"title": "one", "status": "completed"},
                    {"title": "two", "status": "completed"},
                ]
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(RuntimeError, match="durable_tasks=2"):
        live.assert_builtin_topology(project, "mixed")

@pytest.mark.parametrize("content", ["READY\nREVIEW_REQUIRED", "READY\nREVIEW_REQUIRED\n"])
def test_review_failure_routing_validator_accepts_two_logical_lines_with_optional_final_newline(
    tmp_path: Path,
    content: str,
):
    validator = tmp_path / "validation.py"
    validator.write_text(live.REVIEW_ROUTING_VALIDATOR, encoding="utf-8")
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


def test_review_failure_routing_validator_failure_points_only_to_review_file(tmp_path: Path):
    validator = tmp_path / "validation.py"
    validator.write_text(live.REVIEW_ROUTING_VALIDATOR, encoding="utf-8")
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


def test_review_failure_routing_probe_contract_does_not_require_exact_eof_bytes():
    assert "A standard final newline is allowed." in live.REVIEW_ROUTING_PROMPT
    assert "Modify review.txt only" in live.REVIEW_ROUTING_PROMPT
    assert "splitlines()" in live.REVIEW_ROUTING_VALIDATOR


def test_review_failure_routing_probe_uses_state_completion_and_semantic_routing_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    def fake_run(command: list[str], log: Path, timeout: float, observe=None) -> int:
        project = Path(command[command.index("--project-root") + 1])
        workflow = Path(command[command.index("--workflow") + 1])
        assert workflow == project / "workflow.yaml"
        assert workflow.read_text(encoding="utf-8") == live.REVIEW_ROUTING_WORKFLOW
        assert (project / "seed_review.py").read_text(encoding="utf-8") == live.REVIEW_ROUTING_SEED
        assert (project / "review_gate.py").read_text(encoding="utf-8") == live.REVIEW_ROUTING_GATE
        work = project / ".ai-task-runner"
        history = work / "debug" / "history"
        history.mkdir(parents=True)
        (work / "state.json").write_text(
            '{"completed": true, "stage": "completed"}', encoding="utf-8"
        )
        events = [
            {"type": "runner.stage", "action": "start", "stage": "review"},
            {"type": "runner.stage", "action": "finish", "stage": "review", "result": "fail"},
            {"type": "runner.stage", "action": "start", "stage": "execute"},
            {
                "type": "model.prompt",
                "call_id": "execute-2",
                "session": "execute-session",
                "session_mode": "resume",
            },
            {"type": "runner.stage", "action": "finish", "stage": "execute", "result": "pass"},
            {"type": "runner.stage", "action": "start", "stage": "review"},
            {"type": "runner.stage", "action": "finish", "stage": "review", "result": "pass"},
            {"type": "runner.stage", "action": "start", "stage": "validate_file"},
            {"type": "runner.stage", "action": "finish", "stage": "validate_file", "result": "pass"},
        ]
        (work / "log.txt").write_text(
            "".join(json.dumps(event) + "\n" for event in events), encoding="utf-8"
        )
        (history / "execute-2-prompt.txt").write_text(
            'RUNNER_SHARED_STAGE_CONTROL\nmode: continue\nfeedback:\nreview: REVIEW_REQUIRED is intentionally missing; add REVIEW_REQUIRED to review.txt\n',
            encoding="utf-8",
        )
        (work / "debug" / "last-prompt.txt").write_text("prompt", encoding="utf-8")
        (work / "debug" / "last-result.txt").write_text("result", encoding="utf-8")
        (project / "review.txt").write_text("READY\nREVIEW_REQUIRED\n", encoding="utf-8")
        log.parent.mkdir(parents=True, exist_ok=True)
        log.write_text("", encoding="utf-8")
        return 0

    monkeypatch.setattr(live, "run_command", fake_run)

    live.review_failure_routing_probe(settings(tmp_path), tmp_path)

    # This probe owns review.txt, not the generic health.txt contract.
    assert not (tmp_path / "review-failure-routing-probe" / "health.txt").exists()


def test_review_failure_routing_probe_uses_deterministic_seed_stage():
    assert "deterministically seeds review.txt with only READY" in live.REVIEW_ROUTING_PROMPT
    assert "do not inspect files, do not use" in live.REVIEW_ROUTING_EXECUTION_PROMPT
    assert 'type: command' in live.REVIEW_ROUTING_WORKFLOW
    assert 'command: "{python} seed_review.py"' in live.REVIEW_ROUTING_WORKFLOW
    assert 'routes:' in live.REVIEW_ROUTING_WORKFLOW
    assert 'fail: execute' in live.REVIEW_ROUTING_WORKFLOW
    for removed in ("skip_on_error", "restart_at", "max_attempts", "on_exhausted"):
        assert removed not in live.REVIEW_ROUTING_WORKFLOW
    assert 'READY\\n' in live.REVIEW_ROUTING_SEED
    assert "REVIEW_REQUIRED is intentionally missing" in live.REVIEW_ROUTING_GATE


def test_review_failure_routing_probe_workflow_uses_explicit_fail_edge(tmp_path: Path):
    workflow_path = tmp_path / "workflow.yaml"
    workflow_path.write_text(live.REVIEW_ROUTING_WORKFLOW, encoding="utf-8")
    workflow = load_workflow(workflow_path)

    assert [node["name"] for node in workflow] == [
        "execute", "seed", "review", "validate_file"
    ]
    assert workflow[0]["type"] == "base"
    assert workflow[0]["profile"] == "execute"
    assert workflow[1]["type"] == "command"
    assert workflow[2]["routes"] == {"fail": "execute"}
    assert workflow[3]["routes"] == {"fail": "execute"}
    assert workflow[3]["type"] == "command"
    assert all(
        key not in node
        for node in workflow
        for key in ("restart_at", "max_attempts", "on_exhausted", "recover")
    )
    assert "planning" not in {node["name"] for node in workflow}
    compile(live.REVIEW_ROUTING_SEED, "seed_review.py", "exec")
    compile(live.REVIEW_ROUTING_GATE, "review_gate.py", "exec")


def test_live_main_keeps_dynamic_session_policy_probe_enabled():
    source = (ROOT / "tool" / "qwen_live_reliability.py").read_text(encoding="utf-8")
    assert "dynamic_handoff_session_policy_probe(settings, run_root)" in source
    assert '"dynamic_handoff_session_policy_probe": probe_enabled(' in source


def test_workflow_dryrun_preflight_covers_current_graph_contracts():
    results = live.workflow_dryrun_preflight()
    assert all(item["closed"] is True for item in results)
    assert sum(int(item["paths_total"]) for item in results) >= len(results)

    workflow_names = {
        Path(str(item["workflow"])).name
        for item in results
        if not str(item["workflow"]).startswith("synthetic://")
    }
    for expected in {
        "dynamic_handoff.yaml",
        "01_default_ai.yaml",
        "02_ai_with_review_gate.yaml",
        "03_file_validation.yaml",
        "04_mixed_with_review_gate.yaml",
        "05_review_vote_3_choose_2.yaml",
        "06_custom_task_producer.yaml",
        "11_multi_validators_anywhere.yaml",
    }:
        assert expected in workflow_names

    ralphy = next(
        item for item in results
        if str(item["workflow"]).endswith("ralphy_ai_validate.yaml")
    )
    assert ralphy["features"]["task_producer"] is False
    assert ralphy["features"]["dynamic_producer"] is False

    custom = next(
        item for item in results
        if str(item["workflow"]).endswith("custom_workflow_latest.yaml")
    )
    assert custom["features"]["task_producer"] is True
    assert custom["features"]["dynamic_producer"] is True

    twelve = next(
        item for item in results
        if item["workflow"] == "synthetic://12-stage-composability"
    )
    assert twelve["features"]["stages"] == 12
    assert twelve["features"]["routes"] == 3



def test_loop_detection_contract_preflight_accepts_known_qwen_signal():
    live.loop_detection_contract_preflight()



def test_custom_dynamic_producer_probe_uses_explicit_workflow_and_requires_completed_task(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    captured = {}

    def fake_run(command: list[str], log: Path, timeout: float, observe=None) -> int:
        captured["command"] = command
        project = Path(command[command.index("--project-root") + 1])
        work = project / ".ai-task-runner"
        (work / "debug").mkdir(parents=True)
        (work / "state.json").write_text(
            json.dumps({
                "completed": True,
                "stage": "completed",
                "tasks": [{"status": "completed"}],
            }),
            encoding="utf-8",
        )
        (work / "log.txt").write_text("{}\n", encoding="utf-8")
        (work / "debug" / "last-prompt.txt").write_text("prompt", encoding="utf-8")
        (work / "debug" / "last-result.txt").write_text("result", encoding="utf-8")
        (project / "health.txt").write_text(live.EXPECTED, encoding="utf-8")
        log.parent.mkdir(parents=True, exist_ok=True)
        log.write_text("", encoding="utf-8")
        return 0

    monkeypatch.setattr(live, "run_command", fake_run)
    live.custom_dynamic_producer_probe(settings(tmp_path), tmp_path)

    command = captured["command"]
    workflow = Path(command[command.index("--workflow") + 1])
    assert workflow.name == "workflow.yaml"
    assert "produces: tasks" in workflow.read_text(encoding="utf-8")
    assert (workflow.parent / "task_producer.py").is_file()


def test_workflow_dryrun_negative_preflight_proves_invalid_and_loop_detection():
    live.workflow_dryrun_negative_preflight()


def test_stop_request_resume_probe_exercises_detached_ui_contract(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    def fake_runner_command(config, project, **kwargs):
        return [
            "resume-placeholder" if kwargs.get("resume") else "start-placeholder",
            str(project),
        ]

    class FakeProcess:
        pid = 12345

        def __init__(self, command, **options):
            self.project = Path(command[-1])
            self.work = self.project / ".ai-task-runner"
            self.work.mkdir(parents=True, exist_ok=True)
            self.returncode = None
            (self.work / "state.json").write_text(
                json.dumps({
                    "run_id": "stop-run",
                    "completed": False,
                    "stage": "execute",
                    "current": 1,
                    "cycle": 2,
                    "workflow_position": 3,
                    "ai_session_id": "session-stop",
                }),
                encoding="utf-8",
            )
            (self.work / "runner-process.json").write_text(
                json.dumps({"supervisor_pid": self.pid, "worker_pid": 2}),
                encoding="utf-8",
            )

        def poll(self):
            stop = self.work / "stop.request"
            if self.returncode is None and stop.exists():
                stop.unlink(missing_ok=True)
                (self.work / "runner-process.json").unlink(missing_ok=True)
                self.returncode = 130
            return self.returncode

        def wait(self, timeout=None):
            if self.poll() is None:
                raise subprocess.TimeoutExpired(["fake-runner"], timeout)
            return self.returncode

    def fake_run(command: list[str], log: Path, timeout: float, observe=None) -> int:
        project = Path(command[-1])
        work = project / ".ai-task-runner"
        history = work / "debug" / "history"
        history.mkdir(parents=True, exist_ok=True)
        events = [
            {"type": "runner.stage", "action": "start", "stage": "validate_file"},
            {
                "type": "runner.stage",
                "action": "finish",
                "stage": "validate_file",
                "result": "pass",
            },
        ]
        (work / "state.json").write_text(
            json.dumps({
                "completed": True,
                "stage": "completed",
                "ai_session_id": "session-stop",
            }),
            encoding="utf-8",
        )
        (work / "log.txt").write_text(
            "".join(json.dumps(event) + "\n" for event in events),
            encoding="utf-8",
        )
        (work / "debug" / "last-prompt.txt").write_text(
            "prompt", encoding="utf-8"
        )
        (work / "debug" / "last-result.txt").write_text(
            "result", encoding="utf-8"
        )
        (project / "health.txt").write_text(live.EXPECTED, encoding="utf-8")
        log.parent.mkdir(parents=True, exist_ok=True)
        log.write_text("", encoding="utf-8")
        if observe:
            observe()
        return 0

    monkeypatch.setattr(live, "runner_command", fake_runner_command)
    monkeypatch.setattr(live.subprocess, "Popen", FakeProcess)
    monkeypatch.setattr(live, "run_command", fake_run)

    live.stop_request_resume_probe(settings(tmp_path), tmp_path)


def test_session_expiry_recovery_preflight_rebuilds_fresh_session():
    live.session_expiry_recovery_preflight()


def test_session_expiry_preflight_writes_harness_log_outside_project_root(monkeypatch):
    seen = {}

    def fake_run(command, log, timeout, observe=None):
        seen["project"] = Path(command[command.index("--project-root") + 1]).resolve()
        seen["log"] = Path(log).resolve()
        seen["timeout"] = timeout
        seen["command"] = command
        raise RuntimeError("stop after path capture")

    monkeypatch.setattr(live, "run_command", fake_run)

    with pytest.raises(RuntimeError, match="stop after path capture"):
        live.session_expiry_recovery_preflight()

    assert seen["timeout"] == 60
    assert "--no-ui-project-register" in seen["command"]
    assert seen["project"] not in (seen["log"], *seen["log"].parents)


def test_yaml_list_endurance_probe_uses_one_process_and_all_child_work_dirs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    completed: list[tuple[Path, int, str]] = []

    def fake_create(parent: Path, name: str, *args, **kwargs) -> Path:
        project = parent / name
        project.mkdir(parents=True)
        (project / "validation.py").write_text("pass", encoding="utf-8")
        return project

    def fake_run(command: list[str], log: Path, timeout: float, observe=None) -> int:
        log.parent.mkdir(parents=True, exist_ok=True)
        log.write_text("".join(
            json.dumps({"type": "script.item_completed", "script_index": index}) + "\n"
            for index in range(1, 4)
        ), encoding="utf-8")
        assert "--script" in command
        assert timeout == settings(tmp_path).run_timeout * 3
        return 0

    def fake_assert(project: Path, code: int, expected_file="health.txt", expected_text=live.EXPECTED, work_dir=".ai-task-runner") -> None:
        completed.append((project, code, work_dir))

    monkeypatch.setattr(live, "create_project", fake_create)
    monkeypatch.setattr(live, "run_command", fake_run)
    monkeypatch.setattr(live, "assert_completed", fake_assert)

    live.yaml_list_endurance_probe(settings(tmp_path), tmp_path, 3)

    assert [item[2] for item in completed] == [
        ".ai-task-runner/script/001",
        ".ai-task-runner/script/002",
        ".ai-task-runner/script/003",
    ]


def test_yaml_list_resume_probe_accepts_first_item_completion_event(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    class FakeProcess:
        pid = 12345

        def __init__(self, command, **options):
            batch = Path(command[command.index("--project-root") + 1])
            item = batch / "item-1"
            (item / "health.txt").write_text(live.EXPECTED, encoding="utf-8")
            options["stdout"].write(
                json.dumps({"type": "script.item_completed", "script_index": 1})
                + "\n"
            )
            options["stdout"].flush()
            self.returncode = None

        def poll(self):
            return self.returncode

        def wait(self, timeout=None):
            self.returncode = 130
            return self.returncode

    def fake_terminate(process):
        process.returncode = 130

    def fake_run(command: list[str], log: Path, timeout: float, observe=None) -> int:
        batch = Path(command[command.index("--project-root") + 1])
        assert "--resume" in command
        for index in (1, 2):
            project = batch / f"item-{index}"
            work = project / ".ai-task-runner" / "script" / f"{index:03d}"
            (work / "debug").mkdir(parents=True, exist_ok=True)
            state = {"completed": True, "stage": "completed"}
            if index == 2:
                state["validator_output"] = json.dumps({
                    "passed": True,
                    "required_passes": 2,
                    "passes": 2,
                    "runs": [{}, {}, {}],
                })
                (project / "health.txt").write_text(live.EXPECTED, encoding="utf-8")
                (work / "log.txt").write_text(
                    "\n".join([
                        json.dumps({
                            "type": "runner.stage",
                            "action": "start",
                            "stage": "validate_ai",
                        }),
                        json.dumps({"type": "model.result", "session": "a"}),
                        json.dumps({"type": "model.result", "session": "b"}),
                        json.dumps({"type": "model.result", "session": "c"}),
                    ]) + "\n",
                    encoding="utf-8",
                )
            else:
                (work / "log.txt").write_text("{}\n", encoding="utf-8")
            (work / "state.json").write_text(json.dumps(state), encoding="utf-8")
            (work / "debug" / "last-prompt.txt").write_text("prompt", encoding="utf-8")
            (work / "debug" / "last-result.txt").write_text("result", encoding="utf-8")
        log.parent.mkdir(parents=True, exist_ok=True)
        log.write_text(
            "\n".join([
                json.dumps({"type": "script.item_completed", "script_index": 1}),
                json.dumps({"type": "script.item_completed", "script_index": 2}),
            ]) + "\n",
            encoding="utf-8",
        )
        return 0

    monkeypatch.setattr(live.subprocess, "Popen", FakeProcess)
    monkeypatch.setattr(live, "terminate", fake_terminate)
    monkeypatch.setattr(live, "run_command", fake_run)

    live.yaml_list_resume_probe(settings(tmp_path), tmp_path)


def test_yaml_list_resume_probe_reports_qwen_sandbox_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    class FakeProcess:
        pid = 12345
        returncode = 1

        def __init__(self, command, **options):
            options["stdout"].write(
                "qwen exit 1:\n"
                "failed to connect to the docker API at npipe:////./pipe/dockerDesktopLinuxEngine\n"
                "Failed to obtain sandbox image ghcr.io/qwenlm/qwen-code:0.21.0\n"
            )
            options["stdout"].flush()

        def poll(self):
            return self.returncode

        def wait(self, timeout=None):
            return self.returncode

    monkeypatch.setattr(live.subprocess, "Popen", FakeProcess)

    with pytest.raises(RuntimeError, match="Qwen sandbox unavailable"):
        live.yaml_list_resume_probe(settings(tmp_path), tmp_path)


def test_assert_state_completed_rejects_stale_runtime_marker(tmp_path: Path):
    work = tmp_path / ".ai-task-runner"
    (work / "debug").mkdir(parents=True)
    (work / "state.json").write_text('{"completed": true, "stage": "completed"}', encoding="utf-8")
    (work / "log.txt").write_text("{}\n", encoding="utf-8")
    (work / "debug" / "last-prompt.txt").write_text("prompt", encoding="utf-8")
    (work / "debug" / "last-result.txt").write_text("result", encoding="utf-8")
    (work / "runner-process.json").write_text("{}", encoding="utf-8")

    with pytest.raises(RuntimeError, match="stale runtime control files"):
        live.assert_state_completed(tmp_path, 0)

def test_api_retry_classification_preflight():
    live.api_retry_classification_preflight()

def test_task_array_recovery_preflight_covers_broken_planning_envelope():
    live.task_array_recovery_preflight()


def test_loop_detection_contract_preflight_covers_shared_retry_policy():
    live.loop_detection_contract_preflight()



def test_stage_result_mapping_preflight_guards_review_and_validator_boolean_semantics():
    live.stage_result_mapping_preflight()


def test_runtime_long_path_preflight_covers_state_resources_and_copy():
    live.runtime_long_path_preflight()


def test_readonly_long_path_preflight_covers_snapshot_reuse_and_restore():
    live.readonly_long_path_preflight()




def test_readonly_long_path_preflight_does_not_use_plain_pathlib_io():
    import inspect

    source = inspect.getsource(live.readonly_long_path_preflight)
    assert "work.mkdir(" not in source
    assert "target.write_text(" not in source
    assert "target.read_text(" not in source
    assert "io_path(work).mkdir(" in source
    assert "write_text(target," in source
    assert "read_text(target)" in source

def test_deep_preflight_root_uses_extended_length_io_helper(monkeypatch, tmp_path):
    calls = []
    class ProbePath:
        def mkdir(self, *, parents, exist_ok):
            calls.append((parents, exist_ok))
    monkeypatch.setattr("runner.utils.io_path", lambda path: ProbePath())
    root = live._deep_preflight_root(tmp_path, len(str(tmp_path)) + 80)
    assert len(str(root)) > len(str(tmp_path)) + 80
    assert calls == [(True, True)]


def test_long_path_temp_root_uses_long_path_safe_cleanup(monkeypatch, tmp_path):
    base = tmp_path / "long-temp"
    removed = []
    monkeypatch.setattr(live.tempfile, "mkdtemp", lambda prefix: str(base))
    monkeypatch.setattr("runner.utils.remove_path", lambda path: removed.append(Path(path)))
    monkeypatch.setattr(live, "_deep_preflight_root", lambda root, minimum: root / "deep")

    with live._long_path_temp_root("ai-runner-long-path-", 300) as root:
        assert root == base / "deep"

    assert removed == [base]


def test_final_validation_sessions_supports_yaml_child_work_dir(tmp_path: Path):
    work = tmp_path / ".ai-task-runner" / "script" / "002"
    work.mkdir(parents=True)
    (work / "log.txt").write_text(
        '\n'.join([
            '{"type":"runner.stage","action":"start","stage":"validate_ai"}',
            '{"type":"model.result","session":"fresh-a"}',
            '{"type":"model.result","session":"fresh-b"}',
            '{"type":"model.result","session":"fresh-c"}',
        ]) + '\n',
        encoding="utf-8",
    )
    assert live.final_validation_sessions(
        tmp_path, ".ai-task-runner/script/002"
    ) == {"fresh-a", "fresh-b", "fresh-c"}


def test_technical_artifact_safety_preflight_ignores_metadata_but_protects_source():
    live.technical_artifact_safety_preflight()



def test_runner_ownership_preflight_uses_real_cross_process_lock(tmp_path):
    live.runner_ownership_preflight(tmp_path)
    assert not (tmp_path / "ownership-preflight" / ".ai-task-runner" / "run.lock").exists()


def test_live_reliability_main_includes_24h_control_preflights():
    source = Path(live.__file__).read_text(encoding="utf-8")
    main = source[source.index("def main() -> int:"):]
    assert "runner_ownership_preflight(run_root)" in main
    assert "windows_orphan_cleanup_preflight(run_root)" in main
    assert main.index("runner_ownership_preflight(run_root)") < main.index("resume_probe(settings, run_root)")


def test_resource_snapshot_is_stdlib_only_and_reports_core_metrics(tmp_path, monkeypatch):
    monkeypatch.setattr(live, "_rss_bytes", lambda: 123456)
    monkeypatch.setattr(live, "_handle_count", lambda: 77)
    (tmp_path / "data.bin").write_bytes(b"x" * 10)
    marker = tmp_path / "nested" / "active-process.txt"
    marker.parent.mkdir()
    marker.write_text("1 2", encoding="ascii")

    sample = live.resource_snapshot(tmp_path)

    assert sample["rss_bytes"] == 123456
    assert sample["threads"] >= 1
    assert sample["handles"] == 77
    assert "run_root_bytes" not in sample
    assert sample["active_process_markers"] == 1

    final_sample = live.resource_snapshot(tmp_path, include_run_root_bytes=True)
    assert final_sample["run_root_bytes"] >= 13


def test_project_state_metrics_reports_bounded_state_structures(tmp_path):
    project = tmp_path / "project"
    work = project / ".ai-task-runner"
    history = work / "debug" / "history"
    history.mkdir(parents=True)
    state = {
        "stage_sessions": {"role": "s1"},
        "dynamic_groups": {"producer": "producer__g2"},
        "dynamic_task_groups": {"producer": ["t1", "t2"]},
        "review_failures": {"review::__run__": 2},
        "transition_history": [{"stage": "a"}, {"stage": "b"}, {"stage": "c"}],
        "expanded_workflow": [{"name": "a"}, {"name": "b"}, {"name": "c"}],
    }
    work.mkdir(parents=True, exist_ok=True)
    (work / "state.json").write_text(json.dumps(state), encoding="utf-8")
    (history / "prompt.txt").write_bytes(b"x" * 17)

    sample = live.project_state_metrics(project)

    assert sample["project_state_json_bytes"] > 0
    assert sample["project_stage_sessions"] == 1
    assert sample["project_dynamic_groups"] == 1
    assert sample["project_dynamic_task_groups"] == 1
    assert sample["project_review_failures"] == 1
    assert sample["project_transition_history"] == 3
    assert sample["project_expanded_workflow_stages"] == 3
    assert sample["project_debug_history_bytes"] == 17


def test_resource_maximum_preserves_peak_values():
    assert live._resource_maximum(
        {
            "rss_bytes": 100,
            "threads": 5,
            "handles": -1,
            "run_root_bytes": 20,
            "active_process_markers": 0,
        },
        {
            "rss_bytes": 90,
            "threads": 7,
            "handles": 40,
            "run_root_bytes": 30,
            "active_process_markers": 1,
        },
    ) == {
        "rss_bytes": 100,
        "threads": 7,
        "handles": 40,
        "run_root_bytes": 30,
        "active_process_markers": 1,
    }


def test_record_resource_snapshot_writes_jsonl(tmp_path):
    live._record_resource_snapshot(
        tmp_path,
        3,
        {
            "rss_bytes": 10,
            "threads": 2,
            "handles": -1,
            "run_root_bytes": 100,
            "active_process_markers": 0,
        },
    )

    record = json.loads(
        (tmp_path / "resource-observation.jsonl").read_text(encoding="utf-8")
    )
    assert record["run_number"] == 3
    assert record["rss_bytes"] == 10
    assert "timestamp" in record


def test_live_resume_workflow_uses_current_string_flow_contract():
    import yaml

    data = yaml.safe_load(live.RESUME_PROBE_WORKFLOW)
    assert data["flow"] == ["discover", "validate_file"]
    assert all(isinstance(item, str) for item in data["flow"])
    assert all("scope" not in stage for stage in data["stages"].values())
    assert '"name": "execute_first"' in live.RESUME_TASK_PRODUCER
    assert '"name": "pause"' in live.RESUME_TASK_PRODUCER
    assert '"name": "execute_second"' in live.RESUME_TASK_PRODUCER
    assert '"task_complete": True' in live.RESUME_TASK_PRODUCER


def test_resume_probe_runs_real_cli_process_with_fake_qwen(tmp_path: Path):
    config = replace(
        settings(tmp_path),
        command=_fake_qwen_command(tmp_path),
        run_timeout=45,
        agent_timeout=15,
        planning_timeout=15,
    )

    live.resume_probe(config, tmp_path)

    project = tmp_path / "resume-probe"
    state = live.read_state(project)
    assert state["completed"] is True
    assert (project / "health.txt").read_text(encoding="utf-8") == live.EXPECTED
    assert any(
        event.get("type") == "model.prompt"
        and event.get("session_mode") == "resume"
        for event in live.runner_events(project)
    )


def test_yaml_list_resume_runs_real_cli_process_with_fake_qwen(tmp_path: Path):
    config = replace(
        settings(tmp_path),
        command=_fake_qwen_command(tmp_path),
        run_timeout=60,
        agent_timeout=15,
        planning_timeout=15,
    )

    live.yaml_list_resume_probe(config, tmp_path, name="yaml-fast-resume")

    batch = tmp_path / "yaml-fast-resume"
    first = batch / "item-1"
    second = batch / "item-2"
    assert live.read_json(
        first / ".ai-task-runner" / "script" / "001" / "state.json"
    )["completed"] is True
    assert live.read_json(
        second / ".ai-task-runner" / "script" / "002" / "state.json"
    )["completed"] is True


def test_resume_probe_uses_deterministic_checkpoint_and_same_session_resume(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    captured = {}

    class FakeProcess:
        pid = 4321

        def __init__(self, command, **options):
            project = Path(command[command.index("--project-root") + 1])
            work = project / ".ai-task-runner"
            work.mkdir(parents=True, exist_ok=True)
            (work / "state.json").write_text(
                json.dumps({
                    "run_id": "resume-probe",
                    "goal": "goal",
                    "project_root": str(project.resolve()),
                    "completed": False,
                    "stage": "executing",
                    "workflow_position": 2,
                    "ai_session_id": "session-resume",
                    "tasks": [{
                        "id": "discover__g1__resume",
                        "title": "task",
                        "description": "task",
                        "status": "pending",
                    }],
                    "expanded_workflow": [
                        {"name": "discover", "type": "command", "produces": "tasks"},
                        {"name": "discover__g1__execute_first", "type": "base", "profile": "execute"},
                        {"name": "discover__g1__pause", "type": "command"},
                        {"name": "discover__g1__execute_second", "type": "base", "profile": "execute"},
                        {"name": "validate_file", "type": "command", "result_kind": "validation"},
                    ],
                    "dynamic_groups": {"discover": "discover__g1"},
                    "dynamic_task_groups": {"discover": ["discover__g1__resume"]},
                    "expansion_counter": 1,
                }),
                encoding="utf-8",
            )
            captured["first_command"] = command
            self.returncode = None

        def poll(self):
            return self.returncode

    def fake_terminate(process):
        process.returncode = 130

    def fake_run(command: list[str], log: Path, timeout: float, observe=None) -> int:
        project = Path(command[command.index("--project-root") + 1])
        work = project / ".ai-task-runner"
        debug = work / "debug"
        debug.mkdir(parents=True, exist_ok=True)
        (work / "state.json").write_text(
            json.dumps({
                "completed": True,
                "stage": "completed",
                "ai_session_id": "session-resume",
                "tasks": [{"status": "completed"}],
            }),
            encoding="utf-8",
        )
        (work / "log.txt").write_text(
            json.dumps({
                "type": "model.prompt",
                "session": "session-resume",
                "session_mode": "resume",
            }) + "\n",
            encoding="utf-8",
        )
        (debug / "last-prompt.txt").write_text("prompt", encoding="utf-8")
        (debug / "last-result.txt").write_text("result", encoding="utf-8")
        (project / "health.txt").write_text(live.EXPECTED, encoding="utf-8")
        log.parent.mkdir(parents=True, exist_ok=True)
        log.write_text("", encoding="utf-8")
        captured["resume_command"] = command
        if observe:
            observe()
        return 0

    monkeypatch.setattr(live.subprocess, "Popen", FakeProcess)
    monkeypatch.setattr(live, "terminate", fake_terminate)
    monkeypatch.setattr(live, "run_command", fake_run)
    monkeypatch.setattr(live.time, "sleep", lambda _: None)

    live.resume_probe(settings(tmp_path), tmp_path)

    first = captured["first_command"]
    resumed = captured["resume_command"]
    first_workflow = Path(first[first.index("--workflow") + 1])
    resumed_workflow = Path(resumed[resumed.index("--workflow") + 1])
    assert first_workflow == resumed_workflow
    text = first_workflow.read_text(encoding="utf-8")
    assert "type: plan" not in text
    assert "produces: tasks" in text
    producer = first_workflow.parent / "task_producer.py"
    assert producer.is_file()
    producer_text = producer.read_text(encoding="utf-8")
    assert '"tasks"' in producer_text
    assert '"name": "execute_first"' in producer_text
    assert '"name": "pause"' in producer_text
    assert '"name": "execute_second"' in producer_text
    assert "--resume" in resumed


def test_full_loop_executor_applies_review_feedback_from_durable_transition(tmp_path: Path):
    script = tmp_path / "full_loop_execute.py"
    state = tmp_path / "state.json"
    script.write_text(live.FULL_LOOP_EXECUTOR, encoding="utf-8")
    (tmp_path / "loop.txt").write_text("READY\n", encoding="utf-8")
    state.write_text(
        json.dumps(
            {
                "transition_previous": {
                    "stage": "review",
                    "status": "fail",
                    "output": "REVIEW_OK is intentionally missing; add REVIEW_OK to loop.txt",
                },
                "validator_output": "",
            }
        ),
        encoding="utf-8",
    )

    import subprocess

    result = subprocess.run(
        [sys.executable, str(script), "--state-file", str(state)],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert (tmp_path / "loop.txt").read_text(encoding="utf-8").splitlines() == [
        "READY",
        "REVIEW_OK",
    ]


def test_full_loop_executor_applies_validator_feedback_from_durable_state(tmp_path: Path):
    script = tmp_path / "full_loop_execute.py"
    state = tmp_path / "state.json"
    script.write_text(live.FULL_LOOP_EXECUTOR, encoding="utf-8")
    (tmp_path / "loop.txt").write_text("READY\nREVIEW_OK\n", encoding="utf-8")
    state.write_text(
        json.dumps(
            {
                "transition_previous": {
                    "stage": "validate_file",
                    "status": "fail",
                    "output": "VALIDATION_FAILED",
                },
                "validator_output": "VALIDATION_FAILED: add VALIDATOR_OK as its own logical line",
            }
        ),
        encoding="utf-8",
    )

    import subprocess

    result = subprocess.run(
        [sys.executable, str(script), "--state-file", str(state)],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert (tmp_path / "loop.txt").read_text(encoding="utf-8").splitlines() == [
        "READY",
        "REVIEW_OK",
        "VALIDATOR_OK",
    ]


def test_full_loop_workflow_uses_deterministic_rollback_and_qwen_verification(tmp_path: Path):
    workflow_path = tmp_path / "workflow.yaml"
    workflow_path.write_text(live.FULL_LOOP_WORKFLOW, encoding="utf-8")
    workflow = load_workflow(workflow_path)

    assert [node["name"] for node in workflow] == [
        "execute", "seed", "review", "review_verify", "validate_file"
    ]
    assert workflow[0]["type"] == "command"
    assert workflow[2]["type"] == "command"
    assert workflow[2]["routes"] == {"fail": "execute"}
    assert workflow[3]["type"] == "base"
    assert workflow[3]["profile"] == "review"
    assert workflow[4]["routes"] == {"fail": "execute"}
    compile(live.FULL_LOOP_EXECUTOR, "full_loop_execute.py", "exec")
    compile(live.FULL_LOOP_REVIEW_GATE, "full_loop_review_gate.py", "exec")


def test_live_reliability_main_includes_complete_closed_loop_probe():
    source = Path(live.__file__).read_text(encoding="utf-8")
    main = source[source.index("def main() -> int:"):]
    assert "complete_closed_loop_probe(settings, run_root)" in main
    assert (
        main.index("review_failure_routing_probe(settings, run_root)")
        < main.index("complete_closed_loop_probe(settings, run_root)")
        < main.index("validator_failure_routing_probe(settings, run_root)")
    )


def test_long_path_preflight_cleanup_uses_runner_remove_path():
    source = (ROOT / "tool" / "qwen_live_reliability.py").read_text(encoding="utf-8")
    start = source.index("def _long_path_temp_root")
    end = source.index("\ndef runtime_long_path_preflight", start)
    block = source[start:end]

    assert "remove_path(base)" in block
    assert "with tempfile.TemporaryDirectory" not in block
    assert "shutil.rmtree(base)" not in block


def test_semantic_live_probe_timeout_is_bounded_below_global_harness_timeout(tmp_path: Path):
    configured = settings(tmp_path)
    configured = replace(
        configured,
        run_timeout=14400,
        agent_timeout=600,
        planning_timeout=600,
    )

    assert live.semantic_probe_timeout(configured) == 3600


def test_review_probe_timeout_reports_state_and_console_tail(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    def fake_run(command: list[str], log: Path, timeout: float, observe=None) -> int:
        project = Path(command[command.index("--project-root") + 1])
        work = project / ".ai-task-runner"
        work.mkdir(parents=True, exist_ok=True)
        (work / "state.json").write_text(
            json.dumps({
                "stage": "reviewing",
                "cycle": 2,
                "workflow_position": 2,
                "transition_previous": {
                    "stage": "execute",
                    "status": "pass",
                    "output": "initial",
                },
            }),
            encoding="utf-8",
        )
        log.parent.mkdir(parents=True, exist_ok=True)
        log.write_text("last live console line\n", encoding="utf-8")
        raise RuntimeError(f"runner exceeded harness timeout: {timeout:g}s")

    monkeypatch.setattr(live, "run_command", fake_run)

    with pytest.raises(RuntimeError) as exc:
        live.review_failure_routing_probe(settings(tmp_path), tmp_path)

    message = str(exc.value)
    assert "review failure-routing probe exceeded bounded semantic timeout" in message
    assert '"stage": "reviewing"' in message
    assert '"workflow_position": 2' in message
    assert "last live console line" in message


def test_review_routing_probe_protects_control_assets():
    policy = live.REVIEW_ROUTING_POLICY

    for name in (
        "prompt.md",
        "validation.py",
        "seed_review.py",
        "review_gate.py",
        "review_execute.md",
        "workflow.yaml",
    ):
        assert f"  - {name}" in policy

    assert "Modify review.txt only" in policy


def test_review_gate_fails_once_then_passes(tmp_path: Path):
    gate = tmp_path / "review_gate.py"
    gate.write_text(live.REVIEW_ROUTING_GATE, encoding="utf-8")

    import subprocess

    first = subprocess.run(
        [sys.executable, str(gate)],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )
    assert first.returncode == 1
    assert "REVIEW_REQUIRED" in first.stdout

    second = subprocess.run(
        [sys.executable, str(gate)],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )
    assert second.returncode == 0
    assert "REVIEW_GATE_PASSED" in second.stdout




def test_runner_command_explicit_workflow_only_injects_file_validator_when_required(tmp_path: Path):
    config = settings(tmp_path)
    project = tmp_path / "project"
    project.mkdir()
    (project / "prompt.md").write_text("goal", encoding="utf-8")
    (project / "validation.py").write_text("raise SystemExit(0)\n", encoding="utf-8")

    handoff = tmp_path / "handoff.yaml"
    handoff.write_text(
        "stages:\n"
        "  coordinator:\n"
        "    type: handoff\n"
        "    targets: [role]\n"
        "  role:\n"
        "    type: base\n"
        "    profile: generic\n"
        "flow: [coordinator, role]\n",
        encoding="utf-8",
    )
    no_file_validator = live.runner_command(config, project, workflow=handoff)
    assert "--workflow" in no_file_validator
    assert "--validator" not in no_file_validator

    file_workflow = tmp_path / "file.yaml"
    file_workflow.write_text(
        "stages:\n"
        "  validate_file:\n"
        "    type: command\n"
        "    command: '{python} {validator}'\n"
        "    result_kind: validation\n"
        "flow: [validate_file]\n",
        encoding="utf-8",
    )
    with_file_validator = live.runner_command(config, project, workflow=file_workflow)
    assert with_file_validator[with_file_validator.index("--validator") + 1] == str(project / "validation.py")

    ai_workflow = tmp_path / "ai.yaml"
    ai_workflow.write_text(
        "stages:\n"
        "  validate_ai:\n"
        "    type: ai_validator\n"
        "    validator: ai\n"
        "flow: [validate_ai]\n",
        encoding="utf-8",
    )
    with_ai_validator = live.runner_command(
        config,
        project,
        workflow=ai_workflow,
        ai_only=True,
        final_ai=True,
    )
    assert with_ai_validator[with_ai_validator.index("--validator") + 1] == "ai"
    assert "--validator-prompt" in with_ai_validator



def test_dynamic_session_live_fixture_matches_current_workflow_prompt_contract(tmp_path: Path):
    project = tmp_path / "dynamic"
    project.mkdir()
    (project / "dynamic_router.md").write_text(live.DYNAMIC_SESSION_ROUTER_PROMPT, encoding="utf-8")
    (project / "dynamic_role.md").write_text(live.DYNAMIC_SESSION_ROLE_PROMPT, encoding="utf-8")
    workflow = project / "workflow.yaml"
    workflow.write_text(live.DYNAMIC_SESSION_WORKFLOW, encoding="utf-8")

    from runner.workflow.loader import load_workflow

    loaded = load_workflow(workflow)
    by_name = {item["name"]: item for item in loaded}

    assert by_name["coordinator"]["session_policy"] == "role"
    assert by_name["main_role"]["session_policy"] == "main"
    assert by_name["stable_role"]["session_policy"] == "role"
    assert by_name["stable_role"]["routes"] == {"pass": "stable_gate"}
    assert by_name["stable_gate"]["routes"] == {"fail": "stable_role", "pass": "fresh_role"}
    assert by_name["fresh_role"]["session_policy"] == "fresh"
    assert by_name["fresh_role"]["routes"] == {"pass": "final_gate"}
    assert by_name["coordinator"]["targets"] == ["main_role"]
    assert by_name["main_role"]["routes"] == {"pass": "main_gate"}
    assert by_name["main_gate"]["routes"] == {"fail": "main_role", "pass": "stable_role"}
    for name in ("coordinator", "main_role", "stable_role", "fresh_role"):
        prompt = Path(by_name[name]["prompt"])
        assert prompt.is_absolute()
        assert prompt.is_file()


def test_assert_state_completed_includes_console_tail_when_startup_failed(tmp_path: Path):
    project = tmp_path / "startup-failure"
    project.mkdir()
    log = live.console_log(project, "console.jsonl")
    log.parent.mkdir(parents=True, exist_ok=True)
    log.write_text("configuration exploded before state creation\n", encoding="utf-8")

    with pytest.raises(RuntimeError) as error:
        live.assert_state_completed(project, 1)

    message = str(error.value)
    assert "state unavailable" in message
    assert "configuration exploded before state creation" in message


def test_dynamic_session_gate_forces_two_stable_role_visits(tmp_path: Path):
    gate = tmp_path / "stable_gate.py"
    gate.write_text(
        "from pathlib import Path\n"
        "import sys\n"
        "counter = Path('stable-gate.count')\n"
        "value = int(counter.read_text(encoding='utf-8')) if counter.exists() else 0\n"
        "value += 1\n"
        "counter.write_text(str(value), encoding='utf-8')\n"
        "raise SystemExit(1 if value == 1 else 0)\n",
        encoding="utf-8",
    )

    first = subprocess.run([sys.executable, str(gate)], cwd=tmp_path, check=False)
    second = subprocess.run([sys.executable, str(gate)], cwd=tmp_path, check=False)

    assert first.returncode == 1
    assert second.returncode == 0
    assert (tmp_path / "stable-gate.count").read_text(encoding="utf-8") == "2"



def test_dynamic_session_workflow_dryrun_forces_two_stable_visits(tmp_path: Path):
    from runner.workflow.loader import load_workflow
    from tool.workflow_dryrun import Scenario, _execute, _close

    project = tmp_path / "dynamic-dryrun"
    project.mkdir()
    (project / "dynamic_router.md").write_text(live.DYNAMIC_SESSION_ROUTER_PROMPT, encoding="utf-8")
    (project / "dynamic_role.md").write_text(live.DYNAMIC_SESSION_ROLE_PROMPT, encoding="utf-8")
    workflow_file = project / "workflow.yaml"
    workflow_file.write_text(live.DYNAMIC_SESSION_WORKFLOW, encoding="utf-8")

    workflow = load_workflow(workflow_file)
    scenario = Scenario({
        "handoffs": {"coordinator": "main_role"},
        "stages": {
            "main_gate": ["fail", "pass"],
            "stable_gate": ["fail", "pass"],
        },
    })
    ctx, executor, error = _execute(workflow, scenario, 20)
    try:
        assert error == ""
        starts = [stage for _number, stage, _label, _status in executor.trace]
        assert starts == [
            "coordinator",
            "main_role",
            "main_gate",
            "main_role",
            "main_gate",
            "stable_role",
            "stable_gate",
            "stable_role",
            "stable_gate",
            "fresh_role",
            "final_gate",
        ]
        assert ctx.state.completed is True
    finally:
        _close(ctx)



def test_real_review_stage_probe_requires_pass_done_for_complete_evidence():
    source = (Path(__file__).resolve().parents[1] / "tool" / "qwen_live_reliability.py").read_text(encoding="utf-8")
    assert "REVIEW_STAGE_PROBE_OK is the complete deliverable and executor evidence." in source
    assert 'stage.get("status") != "pass"' in source
    assert 'stage.get("next") != "done"' in source
    assert 'stage.get("route") != "next"' in source



def test_dynamic_session_main_gate_forces_two_main_role_visits(tmp_path: Path):
    gate = tmp_path / "main_gate.py"
    gate.write_text(
        "from pathlib import Path\n"
        "import sys\n"
        "counter = Path('main-gate.count')\n"
        "value = int(counter.read_text(encoding='utf-8')) if counter.exists() else 0\n"
        "value += 1\n"
        "counter.write_text(str(value), encoding='utf-8')\n"
        "raise SystemExit(1 if value == 1 else 0)\n",
        encoding="utf-8",
    )

    first = subprocess.run([sys.executable, str(gate)], cwd=tmp_path, check=False)
    second = subprocess.run([sys.executable, str(gate)], cwd=tmp_path, check=False)

    assert first.returncode == 1
    assert second.returncode == 0
    assert (tmp_path / "main-gate.count").read_text(encoding="utf-8") == "2"



def test_dynamic_session_probe_accepts_completed_primary_session_cleanup():
    source = (Path(__file__).resolve().parents[1] / "tool" / "qwen_live_reliability.py").read_text(encoding="utf-8")
    assert 'len(main_results) < 2 or len(set(main_results[-2:])) != 1' in source
    assert 'completed Dynamic Handoff run unexpectedly retained the primary Runner session' in source
    assert 'state.get("ai_session_id")' in source


def test_finish_run_clears_primary_session_by_contract():
    source = (Path(__file__).resolve().parents[1] / "runner" / "workflow" / "results.py").read_text(encoding="utf-8")
    assert 'ctx.state.ai_session_id = ""' in source
    assert 'ctx.ai_client.session_id = ""' in source




def test_api_recovery_fixture_has_deterministic_outage_handshake(tmp_path: Path):
    project = live.create_project(tmp_path, "api-recovery-fixture")
    workflow, armed, active = live._prepare_api_recovery_fixture(project)

    loaded = load_workflow(workflow)
    assert [stage["name"] for stage in loaded] == [
        "warmup",
        "arm",
        "execute",
        "validate_file",
    ]
    assert loaded[0]["session_policy"] == "main"
    assert loaded[2]["session_policy"] == "main"
    assert armed == project / ".ai-task-runner" / "api-outage-armed"
    assert active == project / ".ai-task-runner" / "api-outage-active"
    assert not armed.exists()
    assert not active.exists()

    arm_source = (project / "api_outage_arm.py").read_text(encoding="utf-8")
    assert "marker.write_text" in arm_source
    assert "while not active.is_file()" in arm_source
    assert "API outage harness did not acknowledge arm marker" in arm_source


def test_api_recovery_arm_gate_blocks_until_harness_acknowledges(tmp_path: Path):
    project = live.create_project(tmp_path, "api-recovery-arm-behavior")
    _, armed, active = live._prepare_api_recovery_fixture(project)

    process = subprocess.Popen(
        [sys.executable, str(project / "api_outage_arm.py")],
        cwd=project,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    try:
        deadline = live.time.monotonic() + 5
        while not armed.is_file() and live.time.monotonic() < deadline:
            live.time.sleep(0.02)
        assert armed.is_file()
        assert process.poll() is None

        active.write_text("active\n", encoding="utf-8")
        assert process.wait(timeout=5) == 0
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=5)


def test_api_recovery_probe_acknowledges_active_outage_before_execute():
    source = (
        Path(__file__).resolve().parents[1]
        / "tool"
        / "qwen_live_reliability.py"
    ).read_text(encoding="utf-8")

    assert "outage_marker.is_file()" in source
    assert "not session_id\n                    and outage_armed" in source
    assert "workflow, outage_marker, outage_active_marker = _prepare_api_recovery_fixture(project)" in source
    assert 'outage_active_marker.write_text("active\\n", encoding="utf-8")' in source
    assert "API_RECOVERY_SHORT_OUTAGE_SECONDS = 5.0" in source


def test_api_recovery_probe_never_releases_unobserved_outage():
    source = (
        Path(__file__).resolve().parents[1]
        / "tool"
        / "qwen_live_reliability.py"
    ).read_text(encoding="utf-8")

    assert "and proxy.failures > 0" in source
    assert "and time.monotonic() >= outage_until" in source


def test_api_recovery_probe_disables_backend_internal_retry():
    source = (Path(__file__).resolve().parents[1] / "tool" / "qwen_live_reliability.py").read_text(encoding="utf-8")

    assert "qwen_test_endpoint(settings.sandbox, proxy.port, max_retries=0)" in source
    assert 'event.get("type") == "runner.recovery"' in source
    assert 'event.get("action") == "retry"' in source



def test_api_recovery_probe_collects_structured_recovery_evidence_without_requiring_it():
    source = (Path(__file__).resolve().parents[1] / "tool" / "qwen_live_reliability.py").read_text(encoding="utf-8")
    assert 'event.get("type") == "runner.recovery"' in source
    assert 'event.get("retry_mode")' in source
    assert "all_events = [*console_events, *events]" in source
    assert "Real Qwen may absorb/retry transport failures below StageExecutor" in source
    assert "API outage recovered, but no structured runner.recovery/retry event" not in source



def test_api_recovery_probe_uses_probe_owned_json_event_stream():
    source = (Path(__file__).resolve().parents[1] / "tool" / "qwen_live_reliability.py").read_text(encoding="utf-8")
    assert "console_events = jsonl_events(log)" in source
    assert "events = runner_events(project)" in source
    assert "all_events = [*console_events, *events]" in source
    assert "runner.recovery/retry" in source



def test_api_recovery_probe_records_optional_structured_recovery_evidence():
    source = (Path(__file__).resolve().parents[1] / "tool" / "qwen_live_reliability.py").read_text(encoding="utf-8")
    assert 'event.get("type") == "runner.recovery"' in source
    assert 'event.get("action") == "retry"' in source
    assert "validated after process exit" in source
    assert "Real Qwen may absorb/retry transport failures below StageExecutor" in source



def test_api_recovery_probe_final_scan_prevents_fast_recovery_race():
    source = (Path(__file__).resolve().parents[1] / "tool" / "qwen_live_reliability.py").read_text(encoding="utf-8")
    assert "console_events = jsonl_events(log)" in source
    assert "events = runner_events(project)" in source
    assert "all_events = [*console_events, *events]" in source
    assert "recovery_event_seen" not in source



def test_structured_recovery_event_accepts_stage_and_api_layers():
    assert live._structured_recovery_event({
        "type": "runner.recovery",
        "action": "retry",
        "retry": 1,
        "retry_mode": "retry",
    })
    assert live._structured_recovery_event({
        "type": "runner.retry",
        "action": "retry",
        "layer": "runner_api",
        "message": "service wait window exhausted",
    })
    assert not live._structured_recovery_event({
        "type": "runner.status",
        "action": "set",
        "status": "Recovering",
    })


def test_api_recovery_probe_accepts_both_structured_recovery_layers_when_observed():
    source = (Path(__file__).resolve().parents[1] / "tool" / "qwen_live_reliability.py").read_text(encoding="utf-8")
    assert "def _structured_recovery_event" in source
    assert 'kind == "runner.retry" and action == "retry"' in source
    assert 'kind == "runner.recovery"' in source



def test_api_recovery_probe_disables_qwen_persistent_retry():
    source = (Path(__file__).resolve().parents[1] / "tool" / "qwen_live_reliability.py").read_text(encoding="utf-8")
    assert 'probe_env["QWEN_CODE_UNATTENDED_RETRY"] = "0"' in source
    assert '"env": probe_env' in source
    assert "max_retries=0" in source



def test_recovery_backoff_observation_is_bounded_and_reports_cap(tmp_path: Path):
    first = tmp_path / "a" / ".ai-task-runner"
    second = tmp_path / "b" / ".ai-task-runner"
    first.mkdir(parents=True)
    second.mkdir(parents=True)
    (first / "log.txt").write_text(
        "\n".join([
            json.dumps({"type": "runner.recovery", "action": "retry", "wait_seconds": 2}),
            json.dumps({"type": "runner.recovery", "action": "retry", "wait_seconds": 4}),
            json.dumps({"type": "runner.status", "action": "set", "wait_seconds": 999}),
        ]) + "\n",
        encoding="utf-8",
    )
    (second / "log.txt").write_text(
        json.dumps({
            "type": "runner.recovery",
            "action": "retry",
            "wait_seconds": live.LIVE_RETRY_MAX_DELAY_SECONDS,
        }) + "\n",
        encoding="utf-8",
    )

    assert live.recovery_backoff_observation(tmp_path) == {
        "count": 3,
        "min_wait_seconds": 2.0,
        "max_wait_seconds": float(live.LIVE_RETRY_MAX_DELAY_SECONDS),
        "configured_max_seconds": live.LIVE_RETRY_MAX_DELAY_SECONDS,
        "cap_reached": True,
    }


@pytest.mark.parametrize("wait", [0, -1, live.LIVE_RETRY_MAX_DELAY_SECONDS + 1])
def test_recovery_wait_bounds_fail_closed(wait):
    with pytest.raises(RuntimeError, match="escaped configured bounds"):
        live._assert_recovery_wait_bounds([
            {
                "type": "runner.recovery",
                "action": "retry",
                "wait_seconds": wait,
            }
        ])


def test_live_runner_command_uses_central_retry_timing_constants(tmp_path: Path):
    command = live.runner_command(settings(tmp_path), tmp_path)

    assert command[command.index("--retry-delay") + 1] == str(
        live.LIVE_RETRY_DELAY_SECONDS
    )
    assert command[command.index("--retry-max-delay") + 1] == str(
        live.LIVE_RETRY_MAX_DELAY_SECONDS
    )


def test_soak_resource_bounds_ignore_expected_run_root_growth():
    live.require_resource_bounds(live.SoakResult(
        completed=50,
        resource_start={
            "rss_bytes": 100 * 1024 * 1024,
            "threads": 4,
            "handles": 100,
            "run_root_bytes": 0,
            "active_process_markers": 0,
        },
        resource_max={
            "run_root_bytes": 3 * 1024 * 1024 * 1024,
            "project_state_json_bytes": 512 * 1024,
            "project_stage_sessions": 20,
            "project_dynamic_groups": 10,
            "project_dynamic_task_groups": 10,
            "project_review_failures": 5,
            "project_transition_history": live.MAX_TRANSITION_HISTORY,
            "project_expanded_workflow_stages": 200,
            "project_debug_history_bytes": 4 * 1024 * 1024,
        },
        resource_end={
            "rss_bytes": 120 * 1024 * 1024,
            "threads": 5,
            "handles": 110,
            "run_root_bytes": 3 * 1024 * 1024 * 1024,
            "active_process_markers": 0,
        },
    ))


@pytest.mark.parametrize(
    ("maximum", "end", "expected"),
    [
        ({}, {"active_process_markers": 1}, "active process markers remain"),
        ({"project_state_json_bytes": 9 * 1024 * 1024}, {"active_process_markers": 0}, "project_state_json_bytes"),
        ({"project_stage_sessions": 2049}, {"active_process_markers": 0}, "project_stage_sessions"),
        ({"project_dynamic_groups": 2049}, {"active_process_markers": 0}, "project_dynamic_groups"),
        ({"project_review_failures": 2049}, {"active_process_markers": 0}, "project_review_failures"),
        ({"project_transition_history": live.MAX_TRANSITION_HISTORY + 1}, {"active_process_markers": 0}, "project_transition_history"),
        ({"project_expanded_workflow_stages": 4097}, {"active_process_markers": 0}, "project_expanded_workflow_stages"),
        ({"project_debug_history_bytes": 129 * 1024 * 1024}, {"active_process_markers": 0}, "project_debug_history_bytes"),
    ],
)
def test_soak_resource_bounds_fail_on_unbounded_project_state(maximum, end, expected):
    with pytest.raises(RuntimeError, match=expected):
        live.require_resource_bounds(live.SoakResult(
            resource_start={"threads": 4, "handles": 100, "rss_bytes": 100 * 1024 * 1024},
            resource_max=maximum,
            resource_end=end,
        ))


def test_soak_resource_bounds_fail_on_harness_thread_handle_or_rss_leak():
    with pytest.raises(RuntimeError) as error:
        live.require_resource_bounds(live.SoakResult(
            resource_start={"threads": 4, "handles": 100, "rss_bytes": 100 * 1024 * 1024},
            resource_max={},
            resource_end={
                "threads": 25,
                "handles": 240,
                "rss_bytes": 700 * 1024 * 1024,
                "active_process_markers": 0,
            },
        ))
    message = str(error.value)
    assert "thread count grew" in message
    assert "Windows handle count grew" in message
    assert "harness RSS grew" in message


def test_session_expiry_preflight_requires_stageexecutor_recovery_event():
    source = (Path(__file__).resolve().parents[1] / "tool" / "qwen_live_reliability.py").read_text(encoding="utf-8")
    assert 'event.get("type") == "runner.recovery"' in source
    assert 'event.get("action") == "retry"' in source
    assert '"HTTP 503" in str(event.get("error") or "")' in source
    assert "production CLI transient Stage failure emitted no runner.recovery/retry evidence" in source



def test_timeout_probe_budget_reaches_fresh_session_rotation(tmp_path: Path):
    config = settings(tmp_path)
    project = tmp_path / "timeout-project"
    project.mkdir()
    (project / "prompt.md").write_text("goal", encoding="utf-8")
    (project / "validation.py").write_text("raise SystemExit(0)\n", encoding="utf-8")

    command = live.runner_command(config, project, timeout_probe=True)

    assert command[command.index("--stage-retries") + 1] == "2"
    assert command[command.index("--agent-timeout") + 1] == "1"
    assert command[command.index("--planning-timeout") + 1] == "1"
    assert command[command.index("--retry-delay") + 1] == "0"

    from runner.config.defaults import DEFAULT_PER_SESSION_ATTEMPTS
    assert DEFAULT_PER_SESSION_ATTEMPTS == 2
    # initial attempt + retry #1 reaches the per-session cap; retry #2 is
    # therefore the Fresh Session attempt that timeout_probe expects to observe.



def test_review_failure_routing_freeze_preserves_validator_fail_route(tmp_path: Path):
    from runner.resources import freeze_workflow
    from runner.workflow.loader import load_workflow

    project = tmp_path / "project"
    project.mkdir()
    workflow_file = project / "workflow.yaml"
    workflow_file.write_text(live.REVIEW_ROUTING_WORKFLOW, encoding="utf-8")

    loaded = load_workflow(workflow_file)
    frozen = freeze_workflow(loaded, project, ".ai-task-runner")
    by_name = {item["name"]: item for item in frozen}

    assert by_name["validate_file"]["routes"] == {"fail": "execute"}
    snapshot = json.loads(
        (project / ".ai-task-runner" / "workflow.snapshot.json").read_text(encoding="utf-8")
    )
    snapshot_by_name = {item["name"]: item for item in snapshot}
    assert snapshot_by_name["validate_file"]["routes"] == {"fail": "execute"}



def test_api_recovery_polling_records_rotation_without_racy_semantic_failure():
    source = (
        Path(__file__).resolve().parents[1]
        / "tool"
        / "qwen_live_reliability.py"
    ).read_text(encoding="utf-8")

    assert "API recovery replaced the healthy session" not in source
    assert "session_rotated = True" in source
    assert "validate it once against durable Runner" in source


def test_api_rotation_contract_keeps_healthy_same_session_without_rotation():
    live._assert_controlled_api_session_rotation("session-A", False, [])


def test_api_rotation_contract_accepts_durable_fresh_when_polling_misses_rotation():
    live._assert_controlled_api_session_rotation(
        "session-A",
        False,
        [
            {
                "type": "runner.recovery",
                "action": "retry",
                "retry": 2,
                "retry_mode": "recover",
            },
            {
                "type": "runner.session",
                "action": "fresh",
                "previous_session": "session-A",
            },
        ],
    )


def test_api_rotation_contract_accepts_bounded_runner_owned_fresh_rotation():
    live._assert_controlled_api_session_rotation(
        "session-A",
        True,
        [
            {
                "type": "runner.recovery",
                "action": "retry",
                "retry": 2,
                "retry_mode": "recover",
            },
            {
                "type": "runner.session",
                "action": "fresh",
                "previous_session": "session-A",
            },
        ],
    )


@pytest.mark.parametrize(
    ("events", "message"),
    [
        (
            [{"type": "runner.recovery", "action": "retry", "retry": 2, "retry_mode": "recover"}],
            "without controlled Runner fresh-session evidence",
        ),
        (
            [{"type": "runner.session", "action": "fresh", "previous_session": "session-A"}],
            "without runner.recovery mode=recover evidence",
        ),
        (
            [
                {"type": "runner.recovery", "action": "retry", "retry": 2, "retry_mode": "recover"},
                {"type": "runner.session", "action": "fresh", "previous_session": "other"},
            ],
            "does not match the observed pre-outage session",
        ),
    ],
)
def test_api_rotation_contract_rejects_uncontrolled_session_replacement(events, message):
    with pytest.raises(RuntimeError, match=message):
        live._assert_controlled_api_session_rotation("session-A", True, events)


def test_all_api_outages_share_controlled_bounded_session_rotation_contract():
    source = (Path(__file__).resolve().parents[1] / "tool" / "qwen_live_reliability.py").read_text(encoding="utf-8")

    assert "_assert_controlled_api_session_rotation" in source
    assert "API outage replaced the session without controlled Runner fresh-session evidence" in source
    assert "runner.session" in source
    assert "mode=recover evidence" in source
    assert "short API outage unexpectedly rotated the healthy session" not in source
    assert "API recovery replaced the healthy session" not in source
    assert source.count("bounded-session recovery probe") >= 4



def test_review_failure_routing_fixture_is_contract_focused(tmp_path: Path):
    from runner.workflow.loader import load_workflow
    from tool.workflow_dryrun import Scenario, _execute, _close

    project = tmp_path / "review-routing"
    project.mkdir()
    workflow_file = project / "workflow.yaml"
    workflow_file.write_text(live.REVIEW_ROUTING_WORKFLOW, encoding="utf-8")

    loaded = load_workflow(workflow_file)
    names = [stage["name"] for stage in loaded]
    assert names == ["execute", "seed", "review", "validate_file"]
    assert all(stage["name"] != "review_verify" for stage in loaded)

    scenario = Scenario({
        "stages": {
            "execute": ["pass", "pass"],
            "seed": ["pass", "pass"],
            "review": ["fail", "pass"],
            "validate_file": "pass",
        },
    })
    ctx, executor, error = _execute(loaded, scenario, 20)
    try:
        assert error == ""
        starts = [stage for _number, stage, _label, _status in executor.trace]
        assert starts == [
            "execute", "seed", "review",
            "execute", "seed", "review",
            "validate_file",
        ]
        assert ctx.state.completed is True
    finally:
        _close(ctx)



def test_proxy_recovery_evidence_survives_final_poll_gap():
    control = type("ProxyState", (), {})()
    control.failures = 2
    control.successes = 4
    control.fail = False
    control.disconnect = False

    assert live._proxy_recovery_observed("session-A", control, 3) is True
    assert live._proxy_recovery_observed("", control, 3) is False

    control.successes = 3
    assert live._proxy_recovery_observed("session-A", control, 3) is False

    control.successes = 4
    control.disconnect = True
    assert live._proxy_recovery_observed("session-A", control, 3) is False



def test_model_discovery_uses_openai_models_endpoint():
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            assert self.path == "/v1/models"
            body = json.dumps({"data": [{"id": "model-probe"}]}).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format, *args):
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        assert live._discover_openai_model(server.server_port) == "model-probe"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)



def test_resource_snapshot_skips_full_tree_scan_by_default(tmp_path: Path, monkeypatch):
    calls = []
    monkeypatch.setattr(live, "_tree_bytes", lambda root: calls.append(Path(root)) or 123)

    sample = live.resource_snapshot(tmp_path)
    assert "run_root_bytes" not in sample
    assert calls == []

    sample = live.resource_snapshot(tmp_path, include_run_root_bytes=True)
    assert sample["run_root_bytes"] == 123
    assert calls == [tmp_path]



def test_run_command_observer_gets_final_scan_after_process_exit(tmp_path: Path):
    log = tmp_path / "run.log"
    observed = []

    code = live.run_command(
        [sys.executable, "-c", "print('done')"],
        log,
        10,
        lambda: observed.append(log.read_text(encoding="utf-8", errors="replace")),
    )

    assert code == 0
    assert observed
    assert "done" in observed[-1]



def test_relative_existing_path_accepts_filesystem_alias(tmp_path: Path):
    real_root = tmp_path / "real-root"
    work = real_root / ".ai-task-runner" / "stage-tests" / "abc"
    work.mkdir(parents=True)
    alias = tmp_path / "root-alias"
    try:
        alias.symlink_to(real_root, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("directory symlink unavailable")

    assert live.relative_existing_path(work, alias) == ".ai-task-runner/stage-tests/abc"


def test_relative_existing_path_rejects_unrelated_existing_path(tmp_path: Path):
    root = tmp_path / "root"
    other = tmp_path / "other"
    root.mkdir()
    other.mkdir()

    with pytest.raises(ValueError):
        live.relative_existing_path(other, root)



def test_live_probe_start_selector_accepts_index_and_name():
    review_index = live.PROBE_ORDER.index("review-failure-routing")

    assert live.resolve_start_probe("") == 0
    assert live.resolve_start_probe(str(review_index + 1)) == review_index
    assert live.resolve_start_probe("review-failure-routing") == review_index
    assert live.resolve_start_probe("review_failure_routing") == review_index
    assert live.probe_enabled("technical-artifact-safety", review_index) is False
    assert live.probe_enabled("review-failure-routing", review_index) is True
    assert live.probe_enabled("api-502", review_index) is True


@pytest.mark.parametrize("value", ["0", "999", "does-not-exist"])
def test_live_probe_start_selector_rejects_invalid_values(value: str):
    with pytest.raises(ValueError):
        live.resolve_start_probe(value)


def test_list_probes_exits_before_qwen_command_validation(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["qwen_live_reliability.py", "--list-probes"])
    monkeypatch.setattr(
        live.shutil,
        "which",
        lambda _command: (_ for _ in ()).throw(AssertionError("Qwen lookup should not run")),
    )

    assert live.main() == 0

    output = capsys.readouterr().out
    assert "01  ownership-lock" in output
    review_index = live.PROBE_ORDER.index("review-failure-routing") + 1
    assert f"{review_index:02d}  review-failure-routing" in output


def test_batch_gates_forward_live_probe_selector_arguments():
    root = Path(__file__).resolve().parents[1]
    for name in ("qwen_live_reliability_24h.bat", "qwen_live_reliability_0_5h.bat"):
        text = (root / "tool" / name).read_text(encoding="utf-8")
        assert "%*" in text
