# Python API Reference

Version: 1.1.1

## Canonical integration surface
External callers should use `runner.api.RunRequest` and `runner.api.run()`. CLI, future UI, and skills should adapt to this same request model instead of implementing another Runner flow.

## RunRequest fields
`goal`, `goal_file`, `project_root`, `script`, `validator`, `validator_prompt`, `backend`, `command`, `agent_args`, `validator_args`, `protect_files`, `validator_timeout`, `agent_timeout`, `planning_timeout`, `agent_idle_after_change_timeout`, `max_attempts`, `max_cycles`, `retry_delay`, `retry_wait`, `retry_max_wait`, `final_ai_validations`, `final_ai_required_passes`, `work_dir`, `resume`, `force_new`, `plan_only`, `human_output`, and `json_events`.

`RunRequest.validate()` enforces mutual exclusions, required validator/goal inputs, supported backend names, project-relative work directory, list element types, timeout ranges, retry ranges, AI validation quorum, and resume/force-new exclusivity.

## Example
```python
from runner.api import RunRequest, run

result = run(RunRequest(
    goal_file='prompt.md',
    project_root='project',
    validator='validation.py',
    validator_args=['--fab', 'FAB23'],
    backend='qwen',
))
print(result.exit_code, result.completed)
```

## Events
`run(request, on_event=callback)` forwards Runner progress/status/script events to a callback. Callback exceptions are fail-soft and do not stop the run. `RunResult` returns `exit_code`, `state_files`, parsed `states`, and a `completed` property.

## YAML scripts
`runner.script_runner` accepts a non-empty YAML array. Each item requires `prompt` or `goal`, a `validator` path or `ai`, and optional `validator_prompt`. Each item receives an isolated nested work directory and stops the sequence on first non-zero result.
