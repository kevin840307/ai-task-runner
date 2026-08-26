# Architecture

The directory structure is intentionally the architecture map:

- `runner/api.py`, `bootstrap.py`, `task_runner.py`: public request boundary, dependency composition, and one-run orchestration.
- `runner/script_loader.py`, `script_runner.py`: YAML structure/file parsing and validated child-config execution.
- `runner/workflow/`: declarative workflow definitions, routing rules, result parsers, and the Stage engine.
- `runner/workflow/stages/`: Stage contracts, factory, shared executor, generic `BaseStage`, `PlanStage`, and `PythonValidatorStage`.
- `runner/ai/`: AI client, backend contracts, session classification, structured-output handling, and AI diagnostics.
- `runner/backends/`: Qwen/OpenCode implementations plus backend registry/configuration.
- `runner/project/`: project file snapshots/restores, project policy, and QWEN.md/AGENTS.md instruction-file lifecycle.
- `runner/prompts/`: strict Jinja loader, stable prompt context contract, and bundled prompt resources.
- `runner/runtime/`: durable run state, subprocess lifecycle, raw event delivery, and the semantic progress facade used by orchestration.
- `runner/plugins/`: optional cross-cutting hooks/observers such as safety, console, history, observability, and loop-context compression.
- `runner/config/`: defaults plus the single validated runtime configuration contract.
- `runner/utils/`: small stateless generic file/text helpers only.

## Dependency direction

The runner owns orchestration; backends, plugins, prompts, and validators provide bounded capabilities behind explicit contracts.


`API/Bootstrap -> TaskRunner -> Workflow -> Stage -> AI contracts`

`Backends -> AI contracts`

`StageExecutor -> Project + Runtime semantic progress + generic hook contract`

`Bootstrap -> backend/plugin registries`

Workflow code must not depend on Qwen/OpenCode implementations, concrete plugins, raw event schemas, or raw UI behavior. `runtime/progress.py` is the small semantic facade; `runtime/events.py` owns transport/schema. AI code must not depend on workflow business stages.

CLI parsing ends at `RunRequest.from_namespace()`. `RunRequest.normalized_config()` resolves files and maps public names once; `RuntimeConfig.validate()` is the shared execution validation used by direct requests and YAML child items. There is no reverse/internal Namespace compatibility layer.

Loop-context inspection and compression is a model-error plugin. The AI client reports an error through the generic hook chain; the plugin alone reads compression configuration and optional backend context capabilities.

## Workflow contract

`Pipeline -> StageExecutor -> Stage.run() -> StageResult -> Stage.finish() -> next Stage`

A Stage performs one attempt. `StageExecutor` owns hooks, project change tracking, retry/session escalation, exception conversion, and lifecycle events. `StageResult` contains execution facts and may carry validated generated `next_steps`. `FlowNode` owns static YAML routing (`recover`, `restart_at`); Pipeline interprets both forms generically.

`workflow/builtin/*.yaml` contains only `stages` and top-level `flow`. `workflow/registry.py` is intentionally minimal: Stage behavior `type -> class` only. `workflow/loader.py` normalizes Stage instances, derives Planner-visible dynamic Stage candidates from YAML structure, and marks `validator: file|ai` capability. `workflow/rules.py` only reduces durable state; Pipeline owns resume, recovery routing, and execution of generated `next_steps`. `PlanStage` stores each TODO with its ordered Stage names and emits concrete next-step definitions; no `expand`, `foreach`, or separate subflow DSL exists.

Each Stage instance owns exactly one attempt and can be constructed/executed independently. Ordinary Stage implementations never instantiate/select another Stage and never receive `recover` or `restart_at`. `PlanStage` is the deliberate exception that selects only validated Stage instances from the loader-provided catalog and returns them as data (`next_steps`), without directly executing them. Result handlers reduce facts into durable state; composition and recovery stay in YAML `FlowNode` data.

The durable state stores the completed top-level Workflow position and a semantic fingerprint. Legacy state without these fields is normalized compatibly. A resumed custom Workflow must match its saved fingerprint so reordered Stages cannot be silently skipped or repeated.

## Prompt contract

All bundled prompts use Jinja with `StrictUndefined`. Stage templates never receive `RunState`, `RuntimeConfig`, or arbitrary dictionaries directly. `prompts/context.py` exposes the stable top-level contract:

`goal`, `stage`, `task`, `tasks`, `workflow`, `validation`, `project`, `planning`, `previous`, `instructions`, `rules`, `always_instructions`.

Ordinary AI stages reference a prompt path directly. Planning-specific computed context is owned by `PlanStage`; there is no separate prompt-builder registry.
