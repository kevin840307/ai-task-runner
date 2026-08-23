from __future__ import annotations

from pathlib import Path

from runner.agent.prompts import (
    execution_prompt,
    plan_finalize_prompt,
    review_prompt,
)
from runner.engine.models import RunState, Task
from runner.engine.recovery import (
    record_execution_progress,
    should_rebuild_session,
    task_attempts_exhausted,
    validator_failure_key,
)
from runner.engine.transitions import complete_task, install_plan, prepare_repair_cycle
from runner.errors import RunnerError
from runner.workflow.model_calls import structured_call


def _state() -> RunState:
    state = RunState(run_id="r", goal="g", project_root=".")
    state.tasks = [Task(id="c01-t001", title="T", description="D", deliverable="X", acceptance_criteria=["A"])]
    return state


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


def test_recovery_policy_is_deterministic():
    task = _state().tasks[0]
    error = RunnerError("boom")
    record_execution_progress(task, error, False)
    record_execution_progress(task, error, False)
    record_execution_progress(task, error, False)
    assert should_rebuild_session(task)
    task.attempts = 3
    assert task_attempts_exhausted(task, 3)
    assert validator_failure_key(" A \n B ") == validator_failure_key("A\nB")


def test_transitions_preserve_existing_state_semantics():
    state = _state(); tasks = state.tasks
    install_plan(state, tasks, "s1")
    assert state.current == 0 and state.agent_session_id == "s1"
    complete_task(state, tasks[0], "s2")
    assert tasks[0].status == "completed" and state.current == 1 and state.agent_session_id == "s2"
    old = state.cycle
    prepare_repair_cycle(state)
    assert state.cycle == old + 1 and state.current == len(state.tasks)


def test_prompt_contract_fragments_are_emitted_once(tmp_path):
    state = _state(); task = state.tasks[0]
    p = plan_finalize_prompt("g", tmp_path, state, same_session=True)
    assert p.count('Return only valid JSON in this shape') == 1
    e = execution_prompt(state, tmp_path, [])
    assert e.count('Finish with a factual summary of changed files and checks.') == 1
    r = review_prompt(state, tmp_path, "done")
    assert r.count('"completed":true') == 1
