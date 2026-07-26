# AI Task Runner Project Guide v1.1.1

AI Task Runner is a small retry/review/validator loop around coding agents. The user provides a requirement and a validator. The agent writes the project files; the runner keeps the 24h-style loop alive.

Default CLI behavior is Qwen Code through `qwen.cmd` with unlimited task attempts and validator cycles. A normal run only needs `--project-root`, `--goal`, and `--validator`.

## Closed Loop

1. Understand the project and goal.
2. Split the goal into ordered TODO tasks.
3. Execute only the current task.
4. Ask read-only review whether that task is complete.
5. Retry the same task on model errors, invalid review JSON, no progress, or review failure.
6. Run the final Python or AI validator after all tasks are reviewed.
7. If final validation fails, keep the project changes, create a `Repair validator failure` task, and continue.

Within one process, normal model errors, timeouts, loop detection, session unavailable, review failures, validator failures, protected-file edits, and no-progress cycles are retried automatically. If the Python process, OS, machine, or power fails, use an external supervisor to restart the same command with `--resume`.

## Activity Watchdog

Execution has a default activity idle watchdog. After project files change or the AI CLI writes output, if no further project file changes or CLI output are detected for 900 seconds, the runner stops that AI CLI call early and asks review to decide whether the current task is complete. This never marks work complete by itself; review and final validation still own completion.

## Task Prompt Shape

Each TODO execution usually reuses the same main agent session. The runner sends compact context:

- hard rules and protected-file boundaries
- original goal
- completed task titles
- recent validator feedback
- current task title, description, and acceptance criteria
- previous attempt output or diagnostic
- recovery instructions when needed

Each TODO prompt is about the current task, completion conditions, and the last failure. If repeated no-progress suggests the session is unhealthy, the runner clears the session and continues from runner state in a fresh session.

Agents may read validator files to understand expected behavior, but they must not modify validator files or hardcode validator internals. Python owns final validator execution and runner state. Validator feedback is authoritative, and fallback planning creates a single repair task after validator failure.

## Rule Files

Backend rule files live at the project root:

- Qwen Code: `QWEN.md`
- OpenCode: `AGENTS.md`

OpenCode's official project rule filename is `AGENTS.md`, not `AGENT.md`.

## YAML Resume

YAML batch mode is supported. Each item gets its own state file:

```text
.ai-task-runner/script/001/state.json
.ai-task-runner/script/002/state.json
```

Re-run the same script with `--resume`: completed items return immediately, unfinished items continue from their current task, validator feedback, and session state, and new items start fresh.

## Project Structure

```text
ai_task_runner.py                 CLI parser and main entry point
defaults.py                       Shared default backend, command, timeout, and limit values
runner_api.py                     Public Python API
runner_core.py                    Task planning, execution, review, validation
runner_support.py                 Prompts, parsers, validators, protection, UI
runner_models.py                  RunState and Task models
agent.py                          Session-aware backend facade
process_control.py                Subprocess timeout and activity watchdog
api.py                            Backward-compatible API alias
models.py                         Backward-compatible model alias
version.py                        Package version used by docs and JSON events
QWEN.md                           Qwen project rule file for this repository
AGENTS.md                         OpenCode project rule file for this repository
backends/base.py                  Backend interface and shared command handling
backends/qwen.py                  Qwen stream-json backend
backends/opencode.py              OpenCode backend
examples/                         Reusable sample prompts, validators, and runners
smoke/qwen_todo_cli/              Real Qwen persistent todo CLI case
smoke/qwen_expression_evaluator/  Real Qwen expression evaluator case
smoke/qwen_csv_analyzer/          Real Qwen CSV analyzer case
tests/                            Unit, API, resilience, and documentation tests
docs/                             Human and AI project documentation
```

## Real Qwen Results

2026-07-27 local Qwen runs completed through `ai_task_runner.py`:

- `qwen_todo_cli`: PASS. Covered validator repair, protected state restore, no-project-change retry, and resume.
- `qwen_expression_evaluator`: PASS. Covered 3 task planning, loop detection, protected state restore, read-only review restore, longer local-model timeout, and final Python validation.
- `qwen_csv_analyzer`: PASS. Covered 3 task planning, task-by-task review, report generation, documentation, and final Python validation.

## Test Command

```bat
python -m pytest -q
```

Latest local result: `116 passed, 1 skipped`.
