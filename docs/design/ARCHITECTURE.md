# Architecture

The directory structure is intentionally the architecture map:

- `runner/api.py`, `bootstrap.py`, `task_runner.py`: public request boundary, dependency composition, and one-run orchestration.
- `runner/script_loader.py`, `script_runner.py`: YAML batch parsing/validation and batch execution.
- `runner/workflow/`: declarative workflow definitions, routing rules, result parsers, and the Stage engine.
- `runner/workflow/stages/`: Stage contracts, factory, shared executor, generic `AIStage`, `PlanStage`, and `PythonValidatorStage`.
- `runner/ai/`: AI client, backend contracts, session classification, structured-output handling, and AI diagnostics.
- `runner/backends/`: Qwen/OpenCode implementations plus backend registry/configuration.
- `runner/project/`: project file snapshots/restores, project policy, and QWEN.md/AGENTS.md instruction-file lifecycle.
- `runner/prompts/`: strict Jinja loader, stable prompt context contract, and bundled prompt resources.
- `runner/runtime/`: durable run state, subprocess lifecycle, and semantic event delivery.
- `runner/plugins/`: optional cross-cutting hooks/observers such as safety, console, history, and observability.
- `runner/config/`: runtime/default configuration only.
- `runner/utils/`: small stateless generic file/text helpers only.

## Dependency direction

The runner owns orchestration; backends, plugins, prompts, and validators provide bounded capabilities behind explicit contracts.


`API/Bootstrap -> TaskRunner -> Workflow -> Stage -> AI contracts`

`Backends -> AI contracts`

`StageExecutor -> Project + Runtime + generic plugin hooks`

`Bootstrap -> backend/plugin registries`

Workflow code must not depend on Qwen/OpenCode implementations, concrete plugins, or raw UI behavior. AI code must not depend on workflow business stages.

## Workflow contract

`Pipeline -> StageExecutor -> Stage.run() -> StageResult -> Stage.finish() -> next Stage`

A Stage performs one attempt. `StageExecutor` owns hooks, project change tracking, retry/session escalation, exception conversion, and lifecycle events. `Pipeline` only consumes declarative Stage data and returned `StageResult.next_flow/replace_remaining/complete` facts.

Fixed topology lives only in `workflow/definitions.py`. Routing/result transitions live in `workflow/rules.py`.

## Prompt contract

All bundled prompts use Jinja with `StrictUndefined`. Stage templates never receive `RunState`, `RuntimeConfig`, or arbitrary dictionaries directly. `prompts/context.py` exposes the stable top-level contract:

`goal`, `stage`, `task`, `tasks`, `workflow`, `validation`, `project`, `session`, `failure`, `planning`, `previous`, `rules`, `always_instructions`.

Ordinary AI stages reference a prompt path directly. Planning-specific computed context is owned by `PlanStage`; there is no separate prompt-builder registry.
