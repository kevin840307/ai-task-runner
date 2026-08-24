# Architecture

The runner is built around strict execution ownership:

- `runner/flow/`: graph, pipeline loading, transition and shared retry policy. Flow decides what runs next.
- `runner/stages/`: composable Stage implementations plus `StageExecutor` and `Stage builder`.
- `runner/model/`: model/backend contracts, client/session behavior, structured model output.
- `runner/runtime/`: durable state, progress/events, subprocess execution only.
- `runner/extensions/`: optional hooks/observers such as safety, console, history, observability.
- `runner/utils/`: generic file/project/template/text/import helpers.

## Core contract

`Pipeline loop -> StageExecutor -> Stage.run() -> StageResult -> stages/replace/complete -> next Stage`

A Stage performs one attempt and returns facts only. It does not call hooks, retry itself, publish UI lifecycle events, or select another flow node.

`StageExecutor` is the single execution boundary. It owns before/after hooks, write-stage project snapshots/change detection, exception-to-result conversion, and `runner.stage` lifecycle events.

`StageExecutor retry` is shared by every Stage type. A special Stage such as `PlanStage` or `PythonValidationStage` only implements the behavior that differs from generic `GlobalStage`/`GlobalStage`.

`Stage builder` maps implementation type to Stage builder. `Pipeline` does not import or branch on concrete Stage classes or business Stage names.
