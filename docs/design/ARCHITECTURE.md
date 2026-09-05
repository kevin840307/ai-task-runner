# Architecture

The directory structure is intentionally the architecture map:

- `runner/api.py`, `bootstrap.py`, `task_runner.py`: canonical request/recovery boundary, dependency composition, and one-run orchestration.
- `runner/script_loader.py`, `script_runner.py`: YAML structure/file parsing and validated child-config execution.
- `runner/workflow/`: declarative workflow definitions, routing rules, result parsers, and the Stage engine.
- `runner/workflow/stages/`: Stage contracts, shared executor, generic `BaseStage`, `PlanStage`, generic `CommandStage` for all subprocess execution.
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


`CLI / Programmatic UI / Skill -> runner.api -> Bootstrap -> TaskRunner -> Workflow -> Stage -> bounded capability`

`Backends -> AI contracts`

`StageExecutor -> Project + Runtime semantic progress + generic hook contract`

`Bootstrap -> runtime plugins`

`Extension discovery -> Stage/backend registries -> Workflow validation`

Workflow code must not depend on Qwen/OpenCode implementations, concrete plugins, raw event schemas, or raw UI behavior. `runtime/progress.py` is the small semantic facade; `runtime/events.py` owns transport/schema. AI code must not depend on workflow business stages.

CLI parsing ends at `RunRequest.from_namespace()`. `runner.api.run()` owns logical retry, incomplete-return resume, unexpected runtime recovery, and the Final-Validator completion guard for every caller. The CLI adds only process-level crash isolation through `runtime/supervisor.py`; it does not own a second retry loop. `RunRequest.normalized_config()` resolves files and maps public names once; `RuntimeConfig.validate()` is the shared execution validation used by direct requests and YAML child items. There is no reverse/internal Namespace compatibility layer.

Loop-context inspection and compression is a model-error plugin. The AI client reports an error through the generic hook chain; the plugin alone reads compression configuration and optional backend context capabilities.

## UI / extension boundary

UI is an adapter, not an execution Plugin. Programmatic UI/CLI/Skill integrations may depend on `runner.api`, the owner modules for editable resources/catalog metadata, and event callbacks; Pipeline, StageExecutor, and individual Stages must never import UI code. A detached local UI may choose an even narrower boundary and import no Runner Python at all: it reads runtime visibility files from the configured work directory. A UI can therefore be removed without changing Runner execution semantics.

Installed packages may publish `ai_task_runner.extensions` entry points for runtime-independent registration such as `register_stage()` or backend registration. Discovery occurs before Workflow validation. Runtime cross-cutting Plugins use the separate `ai_task_runner.plugins` entry-point group and attach only after a Runtime exists. This prevents a Plugin from being required by Workflow core while still allowing external packages to add capabilities without editing Runner source.

`workflow.registry.stage_catalog()` is generated directly from each registered Stage `spec_class`; UI/editor code must not maintain another hardcoded Stage schema. User Python automation uses `type: command` and always executes as a subprocess through the shared Python-process helper. Arbitrary user Python is never imported into the 24H Runner process.

`workflow.loader.save_workflow()` and `prompts.loader.save_prompt()` validate against the real Runner parser/schema before using atomic replace. `expected_hash` provides optimistic concurrency protection for UI/IDE edits. These are file-resource helpers, not a second Workflow service or storage model.

Runtime visibility is separate from editable resources and execution control. `state.json` remains Runner-owned durable persistence; detached UI code may read only the stable fields it needs and must never edit the file. `stream.log` is a bounded, disposable snapshot of the most recent subprocess stdout, reset for each subprocess and updated while it runs. `log.txt` and `debug/` remain diagnostic/history surfaces. None of these visibility files is a command channel or a source of PASS/FAIL/routing truth.

`runner-process.json` is a small detached-UI runtime identity marker owned by the top-level Supervisor. It stores `supervisor_pid`, the current `worker_pid`, `started_at`, `project_root`, and `work_dir`; worker restart updates `worker_pid`, and normal Supervisor exit removes the marker. The existing `active-process` marker remains Runner-internal child/orphan cleanup state. PID metadata is never Workflow state and must not drive PASS/FAIL, retry, session, routing, or resume decisions. Runtime control stays deliberately small: a detached UI may create `stop.request` in the work directory; the Supervisor polls for it, terminates the current Worker plus owned child process, removes the request, and exits with code 130. Resume and rerun remain normal CLI launches using `--resume` and `--force-new`; there are no `resume.request` or `rerun.request` files.

At concrete Run start, normalized Workflow data, Stage prompt files, `goal_file`, and `ai_validator_prompt_file` are persisted under the Run work directory. Workflow Stage prompts remain content-addressed; Run-level goal/final-AI prompt resources use stable semantic resource names. Active Runs and later `--resume` therefore keep the same Workflow, Goal, and prompt inputs even when editable source files change or are removed. YAML List children keep independent snapshots in their own nested work directories.

## Workflow contract

`Pipeline -> StageExecutor -> Stage.run() -> StageResult -> Stage.finish() -> next Stage`

A Stage performs one attempt. `StageExecutor` owns hooks, project change tracking, retry/session escalation, exception conversion, and lifecycle events. `StageResult` contains execution facts only. `FlowNode` owns static YAML routing (`recover`, `restart_at`); Pipeline interprets both forms generically.

`workflow/builtin/*.yaml` contains only `stages` and top-level `flow`. `workflow/registry.py` is intentionally minimal: Stage behavior `type -> class` only. `workflow/loader.py` normalizes Stage instances and validation capability. `workflow/rules.py` reduces durable state; Pipeline owns resume and recovery routing. For top-level `PlanStage`, `workflow/loader.py` expands the standard `execute -> review` per-TODO SOP internally, so normal YAML does not repeat it. Explicit `scope: task` remains an advanced static SOP for non-Plan/custom task producers. `PlanStage` stores TODO content only; there is no generated-step queue, `expand`, `foreach`, or separate subflow DSL.

Each Stage instance owns exactly one attempt and can be constructed/executed independently. No Stage selects or executes another Stage. `PlanStage` is only the built-in AI Task producer. Task production is a generic Stage effect (`produces: tasks`), so Python/command/extensions can return the same Task JSON contract without Pipeline class checks. Composition and recovery stay in normalized `FlowNode` data; the standard Plan task SOP is a loader default, not AI-generated topology.

The durable state stores the completed top-level Workflow position and a semantic fingerprint. Legacy state without these fields is normalized compatibly. A resumed custom Workflow must match its saved fingerprint so reordered Stages cannot be silently skipped or repeated.

## Prompt contract

All bundled prompts use Jinja with `StrictUndefined`. Stage templates never receive `RunState`, `RuntimeConfig`, or arbitrary dictionaries directly. `prompts/context.py` exposes the stable top-level contract:

`goal`, `stage`, `task`, `tasks`, `workflow`, `validation`, `project`, `planning`, `previous`, `instructions`, `rules`, `always_instructions`.


`previous.data` exposes bounded structured facts from the immediately preceding Stage so YAML `recover` nodes can consume concrete feedback without a separate data bus or full-context replay. Oversized values are projected/truncated only for prompt transport; the original `StageResult.data` remains unchanged.

Ordinary AI stages reference a prompt path directly. Planning-specific computed context is owned by `PlanStage`; there is no separate prompt-builder registry.


## OpenCode backend parity

Qwen and OpenCode share `BaseBackend` stdin transport, timeout/idle-timeout handling, process-tree cleanup, and stable recovery identity. Backend adapters own only transport/capability differences: Qwen uses `--resume` plus its native `-s` sandbox; OpenCode uses `--session`, JSON events, `--auto`, and `OPENCODE_CONFIG_CONTENT.permission` for planning/no-tool/review policy and Runner `--sandbox` confinement. Workflow, StageExecutor, and Pipeline must never branch on backend names.
