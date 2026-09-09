from pathlib import Path
from types import SimpleNamespace

import pytest

from runner.config.runtime import RuntimeConfig
from runner.errors import RunnerError
from runner.runtime.run_state import RunState
from runner.workflow.registry import create_stage
from runner.workflow.stages.contracts import StageContext


def _ctx(tmp_path: Path):
    work = tmp_path / ".work"; work.mkdir()
    return StageContext(config=RuntimeConfig(), root=tmp_path, work=work, state=RunState("r","g",str(tmp_path)), ai_client=SimpleNamespace(session_id=""), state_file=tmp_path/"state.json", validator_path=None, validator_is_ai=False, save_state=lambda:None, set_stage=lambda *_:None)


def test_command_clean_work_rejects_escape(tmp_path):
    stage=create_stage({"type":"command","name":"x","status":"x","command":["echo","x"],"clean_work":["../outside"]})
    with pytest.raises(RunnerError, match="escapes work directory"):
        stage.run(_ctx(tmp_path))


def test_basic_command_validator_example_exists():
    project=Path("examples/01_basic_command_validator/project")
    assert (project/"validation.py").is_file()
