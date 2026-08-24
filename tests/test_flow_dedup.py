from runner.errors import RunnerError
from runner.ai.structured_output import structured_call
from runner.workflow.stages.executor import StageExecutor


def test_structured_call_reuses_same_ask_for_correction():
    prompts = []
    responses = iter(["bad", '{"ok":true}'])
    def ask(prompt):
        prompts.append(prompt)
        return next(responses)
    def parse(raw):
        if not raw.startswith("{"):
            raise RunnerError("bad json")
        return raw
    assert structured_call("start", parse, ask) == '{"ok":true}'
    assert len(prompts) == 2


def test_failure_fingerprint_is_normalized_and_deterministic():
    class Stage:
        name = "execute"
    class Task:
        id = "t1"
    class Context:
        task = Task()
    first = StageExecutor._failure_key(Stage(), Context(), RunnerError(" A \n B "))
    second = StageExecutor._failure_key(Stage(), Context(), RunnerError("A\nB"))
    assert first == second


def test_public_max_limits_remain_accepted_for_compatibility():
    from runner.api import RunRequest
    config = RunRequest(goal="g", validator="ai", max_attempts=7, max_cycles=4).to_runtime_config()
    assert config.same_session_retries == 7
    assert config.max_cycles == 4
