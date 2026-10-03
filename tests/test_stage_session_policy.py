from pathlib import Path
from types import SimpleNamespace

from runner.config.runtime import RuntimeConfig
from runner.runtime.run_state import RunState, StateStore
from runner.errors import RunnerError
from runner.workflow.stages.base_stage import BaseStage, BaseStageSpec, StageContext, StageResult
from runner.workflow.execution import StageExecutor


def context(tmp_path: Path) -> StageContext:
    state = RunState("run", "goal", str(tmp_path))
    return StageContext(
        config=RuntimeConfig(stage_retries=0),
        root=tmp_path,
        work=tmp_path / ".work",
        state=state,
        ai_client=SimpleNamespace(session_id="main-session"),
        state_file=tmp_path / ".work" / "state.json",
        validator_path=None,
        validator_is_ai=False,
        save_state=lambda: None,
        set_stage=lambda stage, detail="": None,
    )


class RecordingStage(BaseStage):
    def __init__(self, spec):
        super().__init__(spec)
        self.seen = []

    def _run_once(self, ctx, previous, client):
        self.seen.append(str(getattr(client, "session_id", "")))
        client.session_id = f"session-{len(self.seen)}"
        self._persist_session(ctx, client)
        return StageResult(self.name, "pass", output="ok")


def test_main_session_policy_reuses_primary_client(tmp_path):
    ctx = context(tmp_path)
    stage = BaseStage(BaseStageSpec(name="worker", prompt="unused", session_policy="main"))

    assert stage._client(ctx) is ctx.ai_client


def test_main_session_policy_persists_and_reuses_primary_session(tmp_path):
    ctx = context(tmp_path)
    ctx.ai_client.session_id = ""
    stage = RecordingStage(BaseStageSpec(
        name="worker",
        prompt="unused",
        session_policy="main",
    ))

    first = stage.run(ctx)
    assert first.status == "pass"
    assert ctx.state.ai_session_id == "session-1"
    stage.finish(ctx, first)

    second = stage.run(ctx)
    assert second.status == "pass"
    assert stage.seen == ["", "session-1"]
    assert ctx.state.ai_session_id == "session-2"
    assert ctx.state.stage_sessions == {}


def test_role_session_state_store_round_trip_survives_resume(tmp_path):
    work = tmp_path / ".work"
    store = StateStore(tmp_path, work)
    state = RunState("run", "goal", str(tmp_path))
    state.stage_sessions = {
        "implementer": "role-implementer-session",
        "verifier": "role-verifier-session",
    }
    store.save(state)

    resumed = store.load_or_create("", resume=True, force_new=False)

    assert resumed.stage_sessions == state.stage_sessions


def test_role_session_policy_restores_and_persists_durable_stage_session(tmp_path, monkeypatch):
    ctx = context(tmp_path)
    ctx.state.stage_sessions["worker"] = "role-resume"
    created = []

    def fake_create(*args, session_id="", **kwargs):
        client = SimpleNamespace(session_id=session_id)
        created.append(client)
        return client

    monkeypatch.setattr("runner.workflow.stages.base_stage.create_ai_client", fake_create)
    stage = BaseStage(BaseStageSpec(
        name="worker",
        prompt="unused",
        session_policy="role",
    ))

    client = stage._client(ctx)
    assert client.session_id == "role-resume"
    client.session_id = "role-updated"
    stage._persist_session(ctx, client)

    assert ctx.state.stage_sessions == {"worker": "role-updated"}
    assert stage._client(ctx) is client
    assert len(created) == 1


def test_plan_and_ai_validator_use_fresh_session_policy_by_default():
    from runner.workflow.stages import AIValidatorStageSpec, PlanStageSpec

    assert PlanStageSpec(name="plan").session_policy == "fresh"
    assert AIValidatorStageSpec(name="validate").session_policy == "fresh"


def test_fresh_session_policy_clears_session_on_every_stage_invocation(tmp_path, monkeypatch):
    ctx = context(tmp_path)

    def fake_create(*args, **kwargs):
        return SimpleNamespace(session_id="stale-session")

    monkeypatch.setattr("runner.workflow.stages.base_stage.create_ai_client", fake_create)
    stage = RecordingStage(BaseStageSpec(
        name="worker",
        prompt="unused",
        session_policy="fresh",
    ))

    first = stage.run(ctx)
    assert first.status == "pass"
    stage.finish(ctx, first)
    second = stage.run(ctx)
    assert second.status == "pass"

    assert stage.seen == ["", ""]
    assert ctx.state.stage_sessions == {}


def test_role_session_reset_clears_only_that_durable_role(tmp_path, monkeypatch):
    ctx = context(tmp_path)
    ctx.state.stage_sessions = {"worker": "role-a", "other": "role-b"}

    def fake_create(*args, session_id="", **kwargs):
        return SimpleNamespace(session_id=session_id)

    monkeypatch.setattr("runner.workflow.stages.base_stage.create_ai_client", fake_create)
    stage = BaseStage(BaseStageSpec(
        name="worker",
        prompt="unused",
        session_policy="role",
    ))

    assert stage.reset_session(ctx) == "role-a"
    assert ctx.state.stage_sessions == {"other": "role-b"}


def test_global_session_reset_clears_main_and_all_role_sessions(tmp_path):
    ctx = context(tmp_path)
    ctx.ai_client.session_id = "main-live"
    ctx.state.ai_session_id = "main-live"
    ctx.state.stage_sessions = {"worker": "role-a", "other": "role-b"}
    ctx.scratch["stage_session:worker"] = SimpleNamespace(session_id="role-a")
    ctx.scratch["prompt_contracts"] = {
        "worker": ("common/execution.md", "role-a")
    }

    ctx.reset_sessions()

    assert ctx.ai_client.session_id == ""
    assert ctx.scratch["stage_session:worker"].session_id == ""
    assert ctx.state.ai_session_id == ""
    assert ctx.state.stage_sessions == {}
    assert "prompt_contracts" not in ctx.scratch


class NoopHooks:
    def before(self, action):
        return []

    def after(self, action, tokens):
        return []

    def change_detector(self, action, tokens, fallback):
        return fallback()


class RecoveringRoleStage(BaseStage):
    def __init__(self, spec):
        super().__init__(spec)
        self.calls = []

    def run(self, ctx, previous=None):
        client = self._client(ctx)
        self.calls.append(str(getattr(client, "session_id", "")))
        if len(self.calls) <= 2:
            raise RunnerError(f"role failure {len(self.calls)}")
        if not client.session_id:
            client.session_id = "role-after-recovery"
        self._persist_session(ctx, client)
        return StageResult(self.name, "pass", output="recovered")


def test_role_session_technical_failure_rotates_only_that_role_session(tmp_path, monkeypatch):
    ctx = context(tmp_path)
    ctx.config.stage_retries = -1
    ctx.state.stage_sessions = {"worker": "role-before-error", "other": "other-role"}

    def fake_create(*args, session_id="", **kwargs):
        return SimpleNamespace(session_id=session_id)

    monkeypatch.setattr("runner.workflow.stages.base_stage.create_ai_client", fake_create)
    stage = RecoveringRoleStage(BaseStageSpec(
        name="worker",
        prompt="unused",
        session_policy="role",
    ))

    result = StageExecutor(NoopHooks()).run(stage, ctx)

    assert result.status == "pass"
    assert stage.calls == ["role-before-error", "role-before-error", ""]
    assert ctx.state.stage_sessions == {
        "worker": "role-after-recovery",
        "other": "other-role",
    }


class RecoveringFreshStage(BaseStage):
    def __init__(self, spec):
        super().__init__(spec)
        self.calls = []
        self.created = 0

    def _run_once(self, ctx, previous, client):
        if not client.session_id:
            self.created += 1
            client.session_id = f"fresh-session-{self.created}"
        self.calls.append(client.session_id)
        if len(self.calls) <= 2:
            raise RunnerError(f"fresh failure {len(self.calls)}")
        return StageResult(self.name, "pass", output="recovered")


def test_fresh_policy_retries_same_invocation_before_rotating_session(tmp_path, monkeypatch):
    ctx = context(tmp_path)
    ctx.config.stage_retries = -1

    def fake_create(*args, session_id="", **kwargs):
        return SimpleNamespace(session_id=session_id)

    monkeypatch.setattr("runner.workflow.stages.base_stage.create_ai_client", fake_create)
    stage = RecoveringFreshStage(BaseStageSpec(
        name="worker",
        prompt="unused",
        session_policy="fresh",
    ))

    result = StageExecutor(NoopHooks()).run(stage, ctx)

    assert result.status == "pass"
    assert stage.calls == [
        "fresh-session-1",
        "fresh-session-1",
        "fresh-session-2",
    ]
    assert ctx.state.stage_sessions == {}
