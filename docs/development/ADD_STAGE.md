# Add a Stage and show it in Flow UI

Use an existing `command` Stage for a Python script or external program. Add a new Stage type when the behavior needs its own Runner implementation. The Stage performs one unit of work and returns a `StageResult`; the shared `StageExecutor` owns technical retries, and Workflow result edges choose the next Stage.

## Working example

[`examples/12_custom_stage_plugin`](../../examples/12_custom_stage_plugin/) contains an installable `echo` Stage, its package entry point, and a Workflow YAML file. From the repository root, install both packages into the **same Python environment that starts the UI**:

```bash
python -m pip install -e .
python -m pip install -e examples/12_custom_stage_plugin --no-deps
```

The example's `pyproject.toml` declares an `ai_task_runner.plugins` entry point. The package's `setup()` calls `register_stage("echo", EchoStage)`. The Stage class exposes a dataclass `spec_class`; its fields become the type's editor options. `name` is supplied by the Workflow node and is omitted from the parameter editor.

Check discovery and validation:

```bash
python tool/workflow_catalog.py
python tool/workflow_dryrun.py examples/12_custom_stage_plugin/workflow.yaml --matrix --json
```

The catalog JSON should contain `stage_types.echo` with `status` and `prefix` options. The dry-run should report a closed Workflow. Copy the example YAML to `runner/assets/workflows/` for a shared Workflow, or to `<project>/.ai-task-runner/assets/workflows/` for a Project Workflow.

Start or restart `python ui/main.py`, then reload the browser. The UI server obtains `/api/workflow/catalog` through a Runner subprocess. The new `echo` type appears automatically under **擴充積木** in Stage Palette. Its `spec_class` fields appear in the inspector's **參數** tab. Select a Project and save the Workflow before using the **測試** tab; entering `hello` returns `Echo: hello` and next target `done` without running another Stage.

## Add your own type

1. Define a dataclass spec with `name` and the editable options. Give optional options defaults; required options must be filled before the Workflow can be saved.
2. Implement `run(ctx, previous) -> StageResult` and `finish(ctx, result) -> StageResult`. Keep routing and retry logic out of the Stage.
3. Register the class once in a plugin `setup()` using `register_stage("your_type", YourStage)`.
4. Expose that module via the package's `ai_task_runner.plugins` entry point and install it in the UI/Runner Python environment.
5. Use `type: your_type` in Workflow YAML. Restart the UI process and reload the page to refresh discovery.

The Palette groups built-in types by purpose; registered types without built-in presentation metadata appear under **擴充積木** with a generic title. The editor fields and validation still come from the Stage spec. Adding a new type does not require a Flow UI code change.

The Flow UI keeps edits in browser memory until **儲存 Workflow**. Save checks the file hash, Stage/route schema, Prompt references, and Workflow dry-run before one atomic YAML write. Reloading or leaving without saving discards the draft.

## Decide whether a new Stage type is actually needed

For ordinary AI behavior, prefer the existing `type: base`:

- `profile: generic` — custom AI prompt/instructions.
- `profile: execute` — writable execution behavior.
- `profile: review` — read-only structured review.

Create a special Stage type only when behavior needs new runtime semantics, such as Plan, AI Validator, Command, Handoff, or a plugin-specific operation. Do not create a Python Stage class merely because a Workflow needs another role or prompt.

## Producer-defined dynamic child Workflows

A special Stage may return `StageResult.kind = "tasks"` or `"stages"`.

Runner never generates a child template. The producer Stage owns the child `stages` definitions; Runner only validates, namespaces, persists, executes, recovers, and resumes them.

A `tasks` producer result must include:

- a non-empty `tasks` array;
- a non-empty `stages` array;
- at least one child binding each Task with `task_id`;
- at least one child per Task with `task_complete: true`.

Child routes and Handoff targets must stay inside the child Workflow. Use normal `next` / `done` / `stop` semantics to finish the child and return to the parent continuation; do not route directly to arbitrary parent Stages.

PlanStage is the first built-in producer: after parsing Tasks, it creates repeated `AI Stage(profile=execute) -> AI Stage(profile=review)` children. The complete child Workflow runs before the parent continues.

Every child runs through the same `runner/workflow/execution/stage_executor.py`, so custom/plugin Stages must not implement retry/recover/session machinery. AI behavior presets belong in `runner/workflow/profiles.py`; add a dedicated Stage type only when runtime semantics genuinely differ.

