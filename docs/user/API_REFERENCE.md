# Python API Reference

Version: 1.2.42

## Canonical integration surface
External callers should use `runner.api.RunRequest` and `runner.api.run()`. CLI, future UI, and skills should adapt to this same request model instead of implementing another Runner flow.

`runner.api` is the only public execution import path. Obsolete package-level execution re-exports are removed rather than maintained as parallel compatibility APIs.

## RunRequest fields
`goal`, `goal_file`, `project_root`, `script`, `workflow_file`, `validator`, `validator_prompt`, `ai_validator_prompt`, `ai_validator_prompt_file`, `backend`, `command`, `sandbox`, `agent_args`, `validator_args`, `protect_files`, `validator_timeout`, `agent_timeout`, `planning_timeout`, `agent_idle_after_change_timeout`, `max_attempts`, `max_cycles`, `retry_delay`, `retry_wait`, `retry_max_wait`, `final_ai_validations`, `final_ai_required_passes`, `plugins`, `work_dir`, `resume`, `force_new`, `plan_only`, `human_output`, and `json_events`.

`RunRequest.normalized_config()` resolves request files, maps public field names, and returns a validated `RuntimeConfig`; `RunRequest.validate()` delegates to the same path. `RuntimeConfig.validate()` owns execution-setting rules such as backend support, project-relative work directory, timeout/retry ranges, AI validation quorum, and resume/force-new exclusivity. The CLI has a one-way `Namespace -> RunRequest` boundary; internal execution does not accept or recreate legacy Namespaces.

## Example
```python
from runner.api import RunRequest, run

result = run(RunRequest(
    goal_file='prompt.md',
    project_root='project',
    workflow_file='workflow.yaml',
    validator='validation.py',
    ai_validator_prompt_file='ai_validation.md',
    final_ai_validations=3,
    validator_args=['--fab', 'FAB23'],
    backend='qwen',
))
print(result.exit_code, result.completed)
```

## Events
`run(request, on_event=callback)` forwards Runner progress/status/script events to a callback. Callback exceptions are fail-soft and do not stop the run. Exhausted transient service windows and recoverable Runner failures resume available direct or YAML item state. Deterministic `ConfigurationError` / invalid public input still fails fast. `RunResult` returns `exit_code`, `state_files`, parsed `states`, and a `completed` property.

## YAML scripts
`runner.script_loader` parses the non-empty YAML array, structural fields, aliases, and referenced files. `runner.script_runner` creates each child with `dataclasses.replace()` and applies the same `RuntimeConfig.validate()` used by API/CLI execution; YAML does not maintain a second set of timeout, retry, quorum, or plugin-option rules. Each item requires exactly one of `prompt`/`goal` or `goal_file`, plus a `validator` path or `ai`. Relative `goal_file`, `ai_validator_prompt_file`, and `workflow_file` paths are resolved from the YAML file directory. Optional per-item fields include `validator_prompt`, either `ai_validator_prompt` or `ai_validator_prompt_file`, Final AI quorum aliases, `project_root`, `workflow_file`, and the generic `plugins` mapping. Relative per-item `project_root` values are resolved from the outer `--project-root`; omitting it preserves the existing shared-root behavior. Legacy plugin fields remain valid. Each item receives an isolated nested work directory and stops the sequence on first non-zero result.

`workflow_file` is normalized once into `RuntimeConfig.workflow`. It uses the same linear format documented in the User Guide. When omitted, direct requests and each YAML List item select `workflow/builtin/mixed.yaml`, `workflow/builtin/file.yaml`, or `workflow/builtin/ai.yaml` from their validator settings. An explicit parent Workflow is inherited by YAML children unless an item supplies its own `workflow_file`; `dataclasses.replace()` carries the normalized child Workflow without a second execution path.

Retry and cycle limits use one sentinel: `-1` means keep recovering until PASS, `0` disables that retry/cycle, and a positive value is a finite limit. The default `max_attempts=2` still performs at most two same-session recoveries before Fresh Session; the default `max_cycles=-1` keeps unattended validation running until PASS.

Plugin configuration is stored under `RunRequest.plugins` / `RuntimeConfig.plugins`. A configurable plugin owns its CLI arguments, YAML aliases, defaults, and validation in its plugin module; adding another plugin does not require changes to core config, YAML child construction, or workflow code.

## UI / editable resources / Stage catalog
`runner.workflow.registry.stage_catalog()` exposes registered Stage metadata directly from each Stage `spec_class`; UI/tooling must not keep a parallel hardcoded Stage schema. Installed packages may register Stage/backend types through the `ai_task_runner.extensions` entry-point group before Workflow validation. Runtime-only cross-cutting plugins use the separate `ai_task_runner.plugins` group.

UI/editor integrations call the owner modules directly: `runner.resources.read_text()` / `delete()`, `runner.workflow.loader.save_workflow()`, `runner.prompts.loader.save_prompt()`, and `runner.workflow.registry.stage_catalog()`. There is intentionally no extra tooling facade or parallel API. Workflow save uses the actual parser/schema; Prompt save validates Jinja syntax; `expected_hash` provides optimistic conflict detection and atomic replacement avoids partial files; callers that may write the same resource concurrently must serialize those mutations. These helpers edit the real files used by future Runs; they do not create a second UI Workflow store.

Concrete Runs persist `workflow.snapshot.json`, Stage prompt resources, `goal_file`, and `ai_validator_prompt_file` in their own work directory. Active Runs and later Resume use those frozen inputs even if source files change or disappear, so UI/IDE edits affect only future Runs. `runner.api.state_files()` locates direct/YAML child state without reloading Workflow configuration and is suitable for process-level supervision.

`type: python_script` is the generic user Python Stage. It executes the configured script in a subprocess via the same process runner used by validator execution; arbitrary project Python is never imported into the long-running Runner process.
