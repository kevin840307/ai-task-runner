from collections import deque
from types import SimpleNamespace

import pytest

import runner.flow.pipeline as pipeline_module
from runner.flow.pipeline import Pipeline
from runner.flow.stages.base import StageResult


class Stage:
    mode = "readonly"
    actor = "test"
    status = "test"
    detail = ""
    retry = 0
    plan_only_stop = False

    def __init__(self, name):
        self.name = name


@pytest.fixture(autouse=True)
def stage_factory(monkeypatch):
    monkeypatch.setattr(pipeline_module, "create_stage", lambda item: Stage(item["name"]))


def item(name):
    return {"name": name}


class Executor:
    def __init__(self, results):
        self.results = iter(results)
        self.seen = []

    def run(self, stage, ctx, previous=None):
        self.seen.append(stage.name)
        return next(self.results)


def context():
    state = SimpleNamespace(completed=False)
    return SimpleNamespace(state=state, save_state=lambda: None)


def test_pipeline_runs_stage_list_in_order():
    ctx = context()
    executor = Executor([StageResult("a", "pass"), StageResult("b", "pass")])
    Pipeline(ctx, [item("a"), item("b")]).run(executor)
    assert executor.seen == ["a", "b"]


def test_pipeline_runs_nested_stage_lists_in_place():
    ctx = context()
    executor = Executor([
        StageResult("plan", "pass"),
        StageResult("execute", "pass"),
        StageResult("review", "pass"),
        StageResult("validate", "pass"),
    ])
    execute = item("execute")
    review = item("review")
    plan = item("plan")
    validate = item("validate")
    executor.results = iter([
        StageResult("plan", "pass", stages=([execute, review],)),
        StageResult("execute", "pass"),
        StageResult("review", "pass"),
        StageResult("validate", "pass"),
    ])
    Pipeline(ctx, [plan, validate]).run(executor)
    assert executor.seen == ["plan", "execute", "review", "validate"]


def test_any_stage_can_return_another_stage_list():
    ctx = context()
    repair, review = item("repair"), item("review")
    executor = Executor([
        StageResult("a", "fail", stages=(repair, review)),
        StageResult("repair", "pass"),
        StageResult("review", "pass"),
        StageResult("b", "pass"),
    ])
    Pipeline(ctx, [item("a"), item("b")]).run(executor)
    assert executor.seen == ["a", "repair", "review", "b"]


def test_replace_restarts_the_whole_remaining_flow():
    ctx = context()
    understand, plan = item("understand"), item("plan")
    executor = Executor([
        StageResult("execute", "replan", stages=(understand, plan), replace=True),
        StageResult("understand", "pass"),
        StageResult("plan", "pass"),
    ])
    Pipeline(ctx, [[item("execute"), item("stale-review")], item("stale-validator")]).run(executor)
    assert executor.seen == ["execute", "understand", "plan"]
