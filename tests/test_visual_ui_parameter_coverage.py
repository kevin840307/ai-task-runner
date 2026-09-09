from __future__ import annotations

from dataclasses import fields
from pathlib import Path

from runner.workflow.stages.base_stage import BaseStageSpec
from runner.workflow.stages.command import CommandStageSpec
from runner.workflow.stages.plan_stage import PlanStageSpec


ROOT = Path(__file__).resolve().parents[1]
APP = (ROOT / "ui" / "static" / "app.js").read_text(encoding="utf-8")


FIELD_CONTROLS = {
    "status": "stageStatus",
    "prompt": "stagePromptSelect",
    "instructions": "stageInstructions",
    "detail": "stageDetail",
    "run_state": "stageRunState",
    "mode": "stageMode",
    "actor": "stageActor",
    "allow_project_read": "stageAllowProjectRead",
    "parser": "stageParser",
    "structured_retries": "stageStructuredRetries",
    "structured_fresh_retries": "stageStructuredFreshRetries",
    "retry": "stageRetry",
    "runs": "stageRuns",
    "required_passes": "stageRequiredPasses",
    "track_changes": "stageTrackChanges",
    "tolerate_restored_changes": "stageTolerateRestored",
    "timeout": "stageTimeout",
    "session_key": "stageSessionKey",
    "fresh_session_each_run": "stageFreshEachRun",
    "fresh_session_on_start": "stageFreshOnStart",
    "skip_on_error": "stageSkipOnError",
    "produces": "stageProduces",
    "command": "stageCommand",
    "cwd": "stageCwd",
    "result_kind": "stageResultKind",
    "clean_work": "stageCleanWork",
    "min_tasks": "stageMinTasks",
    "repair_plan": "stageRepairPlan",
}

# `continuation_prompt` intentionally remains an advanced YAML-only override.
INTENTIONAL_YAML_ONLY = {"name", "continuation_prompt"}


def test_visual_ui_covers_all_common_stage_parameters_except_documented_yaml_override() -> None:
    names = {field.name for field in fields(BaseStageSpec)} - INTENTIONAL_YAML_ONLY
    missing = sorted(name for name in names if FIELD_CONTROLS.get(name, "") not in APP)
    assert not missing, f"Visual UI is missing BaseStage fields: {missing}"


def test_visual_ui_covers_command_and_plan_specific_parameters() -> None:
    names = ({field.name for field in fields(CommandStageSpec)} | {field.name for field in fields(PlanStageSpec)}) - INTENTIONAL_YAML_ONLY
    missing = sorted(name for name in names if name not in FIELD_CONTROLS or FIELD_CONTROLS[name] not in APP)
    assert not missing, f"Visual UI is missing stage-specific fields: {missing}"


def test_visual_ui_covers_current_flow_routing_parameters() -> None:
    routing = {
        "scope": "stageScope",
        "label": "stageFlowLabel",
        "restart_at": "stageRestartAt",
        "repeat": "stageRepeat",
        "max_attempts": "stageMaxAttempts",
        "on_exhausted": "stageOnExhausted",
        "fresh_after_same_failures": "stageFreshAfterSameFailures",
    }
    missing = sorted(name for name, control in routing.items() if control not in APP)
    assert not missing, f"Visual UI is missing Flow fields: {missing}"
