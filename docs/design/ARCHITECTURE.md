# Architecture

The directory structure is intentionally the architecture map:

- `runner/api.py`, `bootstrap.py`, `task_runner.py`: canonical request/recovery boundary, dependency composition, and one-run orchestration.
- `runner/script_loader.py`, `script_runner.py`: YAML structure/file parsing and validated child-config execution.
- `runner/workflow/`: declarative workflow definitions, routing rules, result parsers, and the Stage engine.
- `runner/workflow/stages/`: Stage contracts, shared executor, generic `BaseStage`, `PlanStage`, isolated `PythonScriptStage`, and authoritative `PythonValidatorStage`.
- `runner/ai/`: AI client, backend contracts, session classification, structured-output handling, and AI diagnostics.
- `runner/backends/`: Qwen/OpenCode implementations plus backend registry/configuration.
- `runner/project/`: project file snapshots/restores, project policy, and QWEN.md/AGENTS.md instruction-file lifecycle.
- `runner/prompts/`: strict Jinja loader, stable prompt context contract, and bundled prompt resources.
- `runner/runtime/`: durable run state, subprocess lifecycle, worker crash supervisor, raw event delivery, and the semantic progress facade used by orchestration.
- `runner/plugins/`: optional cross-cutting hooks/observers such as safety, console, history, observability, and loop-context compression.
- `runner/config/`: defaults plus the single validated runtime configuration contract.
- `runner/extensions.py`, `resources.py`: installed extension discovery before Workflow validation and shared atomic editable-resource I/O.
- `runner/utils/`: small stateless generic file/text helpers only.

## Dependency direction

The runner owns orchestration; backends, plugins, prompts, and validators provide bounded capabilities behind explicit contracts.


`CLI / UI / Skill -> runner.api -> Bootstrap -> TaskRunner -> Workflow -> Stage -> bounded capability`

`Backends -> AI contracts`

`StageExecutor -> Project + Runtime semantic progress + generic hook contract`

`Bootstrap -> runtime plugins`

`Extension discovery -> Stage/backend registries -> Workflow validation`

Workflow code must not depend on Qwen/OpenCode implementations, concrete plugins, raw event schemas, or raw UI behavior. `runtime/progress.py` is the small semantic facade; `runtime/events.py` owns transport/schema. AI code must not depend on workflow business stages.

CLI parsing ends at `RunRequest.from_namespace()`. `runner.api.run()` owns logical retry, incomplete-return resume, unexpected runtime recovery, and the Final-Validator completion guard for every caller. The CLI adds only process-level crash isolation through `runtime/supervisor.py`; it does not own a second retry loop. `RunRequest.normalized_config()` resolves files and maps public names once; `RuntimeConfig.validate()` is the shared execution validation used by direct requests and YAML child items. There is no reverse/internal Namespace compatibility layer.

Loop-context inspection and compression is a model-error plugin. The AI client reports an error through the generic hook chain; the plugin alone reads compression configuration and optional backend context capabilities.

## UI / extension boundary

UI is an adapter, not an execution Plugin. UI/CLI/Skill code may depend on `runner.api`, the owner modules for editable resources/catalog metadata, and event callbacks; Pipeline, StageExecutor, and individual Stages must never import UI code. A UI can therefore be removed without changing Runner execution semantics.

Installed packages may publish `ai_task_runner.extensions` entry points for runtime-independent registration such as `register_stage()` or backend registration. Discovery occurs before Workflow validation. Runtime cross-cutting Plugins use the separate `ai_task_runner.plugins` entry-point group and attach only after a Runtime exists. This prevents a Plugin from being required by Workflow core while still allowing external packages to add capabilities without editing Runner source.

`workflow.registry.stage_catalog()` is generated directly from each registered Stage `spec_class`; UI/editor code must not maintain another hardcoded Stage schema. User Python automation uses `type: python_script` and always executes as a subprocess through the shared Python-process helper. Arbitrary user Python is never imported into the 24H Runner process.

`workflow.loader.save_workflow()` and `prompts.loader.save_prompt()` validate against the real Runner parser/schema before using atomic replace. `expected_hash` provides optimistic concurrency protection for UI/IDE edits. These are file-resource helpers, not a second Workflow service or storage model.

At concrete Run start, normalized Workflow data, Stage prompt files, `goal_file`, and `ai_validator_prompt_file` are persisted under the Run work directory. Workflow Stage prompts remain content-addressed; Run-level goal/final-AI prompt resources use stable semantic resource names. Active Runs and later `--resume` therefore keep the same Workflow, Goal, and prompt inputs even when editable source files change or are removed. YAML List children keep independent snapshots in their own nested work directories.

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
