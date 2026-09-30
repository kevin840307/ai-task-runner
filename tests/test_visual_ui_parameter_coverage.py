from __future__ import annotations

from dataclasses import fields
from pathlib import Path

from runner.workflow.stages.base_stage import BaseStageSpec
from runner.workflow.stages.command import CommandStageSpec
from runner.workflow.stages import PlanStageSpec


ROOT = Path(__file__).resolve().parents[1]
APP = (ROOT / "ui" / "static" / "app.js").read_text(encoding="utf-8")

FIELD_CONTROLS = {
    "status": "stageStatus",
    "prompt": "stagePromptSelect",
    "instructions": "stageInstructions",
    "detail": "stageDetail",
    "run_state": "stageRunState",
    "mode": "stageMode",
    "readonly_safety": "stageReadonlySafety",
    "actor": "stageActor",
    "allow_project_read": "stageAllowProjectRead",
    "parser": "stageParser",
    "structured_retries": "stageStructuredRetries",
    "structured_fresh_retries": "stageStructuredFreshRetries",
    "runs": "stageRuns",
    "required_passes": "stageRequiredPasses",
    "track_changes": "stageTrackChanges",
    "tolerate_restored_changes": "stageTolerateRestored",
    "timeout": "stageTimeout",
    "session_key": "stageSessionKey",
    "session_policy": "stageSessionPolicy",
    "fresh_session_each_run": "stageFreshEachRun",
    "fresh_session_on_start": "stageFreshOnStart",
    "produces": "stageProduces",
    "command": "stageCommand",
    "cwd": "stageCwd",
    "result_kind": "stageResultKind",
    "clean_work": "stageCleanWork",
    "min_tasks": "stageMinTasks",
}

INTENTIONAL_YAML_ONLY = {"name"}


def test_visual_ui_covers_base_stage_parameters():
    names = {field.name for field in fields(BaseStageSpec)} - INTENTIONAL_YAML_ONLY
    missing = sorted(name for name in names if FIELD_CONTROLS.get(name, "") not in APP)
    assert not missing, f"Visual UI is missing BaseStage fields: {missing}"


def test_visual_ui_covers_command_and_plan_specific_parameters():
    names = (
        {field.name for field in fields(CommandStageSpec)}
        | {field.name for field in fields(PlanStageSpec)}
    ) - INTENTIONAL_YAML_ONLY
    missing = sorted(
        name
        for name in names
        if name not in FIELD_CONTROLS or FIELD_CONTROLS[name] not in APP
    )
    assert not missing, f"Visual UI is missing Stage fields: {missing}"


def test_visual_ui_covers_only_current_graph_parameters():
    routing = {
        "scope": "stageScope",
        "label": "stageFlowLabel",
        "routes.pass": "stageRoutePass",
        "routes.fail": "stageRouteFail",
    }
    missing = sorted(name for name, control in routing.items() if control not in APP)
    assert not missing, f"Visual UI is missing graph fields: {missing}"

    for removed in (
        "stageRetry",
        "stageRecover",
        "stageRestartAt",
        "stageRepeat",
        "stageMaxAttempts",
        "stageOnExhausted",
        "stageFreshAfterSameFailures",
        "stageRouteReplan",
    ):
        assert removed not in APP
