# Python API Reference

Version: 1.2.33

## Canonical integration surface
External callers should use `runner.api.RunRequest` and `runner.api.run()`. CLI, future UI, and skills should adapt to this same request model instead of implementing another Runner flow.

Legacy compatibility names may still exist for existing callers, but they are not the canonical API and should not be used by new integrations. Internal-only compatibility shims are removed when no production caller needs them.

## RunRequest fields
`goal`, `goal_file`, `project_root`, `script`, `validator`, `validator_prompt`, `ai_validator_prompt`, `ai_validator_prompt_file`, `backend`, `command`, `sandbox`, `agent_args`, `validator_args`, `protect_files`, `validator_timeout`, `agent_timeout`, `planning_timeout`, `agent_idle_after_change_timeout`, `max_attempts`, `max_cycles`, `retry_delay`, `retry_wait`, `retry_max_wait`, `final_ai_validations`, `final_ai_required_passes`, `plugins`, `work_dir`, `resume`, `force_new`, `plan_only`, `human_output`, and `json_events`.

`RunRequest.normalized_config()` resolves request files, maps public field names, and returns a validated `RuntimeConfig`; `RunRequest.validate()` delegates to the same path. `RuntimeConfig.validate()` owns execution-setting rules such as backend support, project-relative work directory, timeout/retry ranges, AI validation quorum, and resume/force-new exclusivity. The CLI has a one-way `Namespace -> RunRequest` boundary; internal execution does not accept or recreate legacy Namespaces.

## Example
```python
from runner.api import RunRequest, run

result = run(RunRequest(
    goal_file='prompt.md',
    project_root='project',
    validator='validation.py',
    ai_validator_prompt_file='ai_validation.md',
    final_ai_validations=3,
    validator_args=['--fab', 'FAB23'],
    backend='qwen',
))
print(result.exit_code, result.completed)
```

## Events
`run(request, on_event=callback)` forwards Runner progress/status/script events to a callback. Callback exceptions are fail-soft and do not stop the run. `RunResult` returns `exit_code`, `state_files`, parsed `states`, and a `completed` property.

## YAML scripts
`runner.script_loader` parses the non-empty YAML array, structural fields, aliases, and referenced files. `runner.script_runner` creates each child with `dataclasses.replace()` and applies the same `RuntimeConfig.validate()` used by API/CLI execution; YAML does not maintain a second set of timeout, retry, quorum, or plugin-option rules. Each item requires exactly one of `prompt`/`goal` or `goal_file`, plus a `validator` path or `ai`. Relative `goal_file` and `ai_validator_prompt_file` paths are resolved from the YAML file directory. Optional per-item fields include `validator_prompt`, either `ai_validator_prompt` or `ai_validator_prompt_file`, Final AI quorum aliases, `project_root`, and the generic `plugins` mapping. Relative per-item `project_root` values are resolved from the outer `--project-root`; omitting it preserves the existing shared-root behavior. Legacy plugin fields remain valid. Each item receives an isolated nested work directory and stops the sequence on first non-zero result.

Retry and cycle limits use one sentinel: `-1` means keep recovering until PASS, `0` disables that retry/cycle, and a positive value is a finite limit. The default `max_attempts=2` still performs at most two same-session recoveries before Fresh Session; the default `max_cycles=-1` keeps unattended validation running until PASS.

Plugin configuration is stored under `RunRequest.plugins` / `RuntimeConfig.plugins`. A configurable plugin owns its CLI arguments, YAML aliases, defaults, and validation in its plugin module; adding another plugin does not require changes to core config, YAML child construction, or workflow code.
