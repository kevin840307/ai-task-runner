"""Minimal external Stage registered through the Runner plugin boundary."""

from dataclasses import dataclass

from runner.workflow.registry import register_stage
from runner.workflow.stages import StageContext, StageResult


@dataclass(frozen=True)
class EchoSpec:
    name: str
    status: str = "Echo input"
    prefix: str = "Echo: "


class EchoStage:
    spec_class = EchoSpec
    result_kind = "generic"
    mode = "readonly"
    actor = "echo"
    detail = ""
    run_state = ""
    track_changes = False
    tolerate_restored_changes = False
    fresh_session_on_start = False

    def __init__(self, spec: EchoSpec) -> None:
        self.spec = spec
        self.name = spec.name
        self.status = spec.status

    def run(self, ctx: StageContext, previous: StageResult | None = None) -> StageResult:
        input_text = previous.output if previous is not None else ctx.config.goal
        return StageResult(self.name, "pass", output=f"{self.spec.prefix}{input_text}")

    def finish(self, ctx: StageContext, result: StageResult) -> StageResult:
        return result


def setup() -> None:
    register_stage("echo", EchoStage)
