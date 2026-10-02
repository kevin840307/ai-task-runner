"""Dynamic handoff Stage."""
from __future__ import annotations

from dataclasses import dataclass, field, replace

from ...agent import parse_result, require_object, require_text
from ...errors import RunnerError
from .base_stage import (
    MODE_READONLY,
    BaseStage,
    BaseStageSpec,
    SessionPolicy,
    StageContext,
)


@dataclass(frozen=True)
class HandoffStageSpec(BaseStageSpec):
    status: str = "AI 正在選擇下一個 Agent"
    run_state: str = "handoff"
    mode: str = MODE_READONLY
    actor: str = "scheduler"
    prompt: str = "common/handoff.md"
    targets: list[str] = field(default_factory=list)
    structured_retries: int = 2
    session_policy: SessionPolicy = "role"


class HandoffStage(BaseStage):
    ui_title = "Handoff"
    ui_description = "Dynamically select exactly one allowed next Stage."
    ui_category = "handoff"
    result_kind = "handoff"
    backend_mode = "review"

    def __init__(self, spec: HandoffStageSpec) -> None:
        allowed = tuple(spec.targets)

        def parse_handoff(text: str, ctx: StageContext):
            def parse(value):
                obj = require_object(value)
                target = require_text(obj.get("target"), "handoff.target")
                reason = require_text(obj.get("reason"), "handoff.reason")
                if target not in allowed:
                    raise RunnerError(
                        f"handoff.target must be one of: {', '.join(allowed)}"
                    )
                return {"target": target, "reason": reason}

            return parse_result(text, parse)

        super().__init__(replace(spec, parser=parse_handoff))

    def _with_immutable_protocol(self, prompt: str) -> str:
        allowed = ", ".join(self.spec.targets)
        base = super()._with_immutable_protocol(prompt).rstrip()
        return (
            base
            + "\n\n[RUNNER_IMMUTABLE_HANDOFF_PROTOCOL]\n"
            + "Choose exactly one next Stage from the allowed targets. "
            + "Do not execute that Stage yourself.\n"
            + f"Allowed targets: {allowed}\n"
            + 'Return exactly one JSON object and no markdown: '
            + '{"target":"stage_name","reason":"concise reason"}\n'
            + "[/RUNNER_IMMUTABLE_HANDOFF_PROTOCOL]\n"
        )


HandoffStage.spec_class = HandoffStageSpec

__all__ = ["HandoffStage", "HandoffStageSpec"]
