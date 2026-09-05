from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

from runner.config.runtime import RuntimeConfig
from runner.runtime.process_runner import ProcessResult
from runner.runtime.run_state import RunState
from runner.workflow.registry import create_stage
from runner.workflow.stages.contracts import StageContext


def context(tmp_path: Path) -> StageContext:
    state = RunState("run", "goal", str(tmp_path))
    config = RuntimeConfig(agent_timeout=10, validator_timeout=20)
    config.validator_args = ["--extra", "yes"]
    work = tmp_path / ".work"
    work.mkdir()
    return StageContext(config=config, root=tmp_path, work=work, state=state, ai_client=SimpleNamespace(session_id=""), state_file=tmp_path / "state.json", validator_path=None, validator_is_ai=False, save_state=lambda: None, set_stage=lambda *_: None)


def test_command_supports_python_and_validator_placeholders(monkeypatch, tmp_path):
    from runner.workflow.stages import process_stage
    validator = tmp_path / "validator.py"
    validator.write_text("print('validator')", encoding="utf-8")
    ctx = context(tmp_path)
    ctx.validator_path = validator
    calls = []
    monkeypatch.setattr(process_stage, "run_process", lambda command, cwd, timeout, *a, **k: (calls.append((list(command), cwd, timeout)) or ProcessResult("OK", 0)))

    script = create_stage({"type":"command","name":"script","status":"Script","command":["{python}","tool.py"]})
    validator_stage = create_stage({"type":"command","name":"validator","status":"Validator","result_kind":"validation","command":"{python} {validator} --project-root {project_root} --state-file {state_file} {validator_args}"})
    assert script.run(ctx).status == "pass"
    assert validator_stage.run(ctx).status == "pass"
    assert calls[0][0] == [sys.executable, "tool.py"]
    assert calls[0][2] == 10
    assert calls[1][0] == [sys.executable, str(validator), "--project-root", str(tmp_path), "--state-file", str(tmp_path / "state.json"), "--extra", "yes"]
    assert calls[1][2] == 20


def test_command_validation_cleans_work_paths(monkeypatch, tmp_path):
    from runner.workflow.stages import process_stage
    ctx = context(tmp_path)
    reports = ctx.work / "validator-reports"
    reports.mkdir()
    (reports / "old.txt").write_text("old", encoding="utf-8")
    monkeypatch.setattr(process_stage, "run_process", lambda *a, **k: ProcessResult("OK", 0))
    stage = create_stage({"type":"command","name":"validate","status":"Validate","command":"fake","result_kind":"validation"})
    assert stage.run(ctx).status == "pass"
    assert not reports.exists()


def test_shared_process_runner_maps_nonzero_to_fail(monkeypatch, tmp_path):
    from runner.workflow.stages import process_stage
    ctx=context(tmp_path)
    monkeypatch.setattr(process_stage,"run_process",lambda *a,**k: ProcessResult("BROKEN",7))
    result=create_stage({"type":"command","name":"check","status":"Check","command":["fake"]}).run(ctx)
    assert result.status=="fail" and result.output=="BROKEN"


def test_command_stage_supports_project_relative_cwd(monkeypatch,tmp_path):
    from runner.workflow.stages import process_stage
    sub=tmp_path/"sub"; sub.mkdir(); ctx=context(tmp_path); seen={}
    monkeypatch.setattr(process_stage,"run_process",lambda command,cwd,timeout,*a,**k:(seen.setdefault("cwd",cwd) or ProcessResult("OK",0)))
    # setdefault returns Path, so use explicit function
    def fake(command,cwd,timeout,*a,**k): seen["cwd"]=cwd; return ProcessResult("OK",0)
    monkeypatch.setattr(process_stage,"run_process",fake)
    assert create_stage({"type":"command","name":"check","status":"Check","command":["fake"],"cwd":"sub"}).run(ctx).status=="pass"
    assert seen["cwd"]==sub


def test_command_stage_runs_real_child_process(tmp_path):
    ctx=context(tmp_path)
    result=create_stage({"type":"command","name":"real","status":"Real command","command":[sys.executable,"-c","print('REAL_OK')"]}).run(ctx)
    assert result.status=="pass" and "REAL_OK" in result.output


def test_command_string_is_supported(monkeypatch, tmp_path):
    from runner.workflow.stages import process_stage
    ctx = context(tmp_path)
    seen = {}
    def fake(command, cwd, timeout, *a, **k):
        seen["command"] = list(command)
        return ProcessResult("OK", 0)
    monkeypatch.setattr(process_stage, "run_process", fake)
    stage = create_stage({"type":"command","name":"script","status":"Run","command":"{python} tool.py --name \"hello world\""})
    assert stage.run(ctx).status == "pass"
    assert seen["command"] == [sys.executable, "tool.py", "--name", "hello world"]


def test_validation_clean_work_can_be_disabled(monkeypatch, tmp_path):
    from runner.workflow.stages import process_stage
    ctx = context(tmp_path)
    reports = ctx.work / "validator-reports"
    reports.mkdir()
    monkeypatch.setattr(process_stage, "run_process", lambda *a, **k: ProcessResult("OK", 0))
    stage = create_stage({"type":"command","name":"validate","status":"Validate","command":"fake","result_kind":"validation","clean_work":[]})
    assert stage.run(ctx).status == "pass"
    assert reports.exists()
