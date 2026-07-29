# AI Task Runner Project Guide v1.1.1

AI Task Runner is a small retry/review/validator loop around coding agents. The user provides a requirement and a validator. The agent writes the project files; the runner keeps the 24h-style loop alive.

Default CLI behavior is Qwen Code through `qwen.cmd` with unlimited task attempts and validator cycles. A normal run only needs `--project-root`, `--goal`, and `--validator`.

Long requirements should use `--goal-file <utf8-text-file>` instead of squeezing the whole prompt into one shell argument. The loaded text becomes the persisted state goal.

## Closed Loop

1. Understand the project and goal.
2. Split the goal into ordered TODO tasks.
3. Execute only the current task.
4. Ask read-only review whether that task is complete.
5. Retry the same task on model errors, invalid review JSON, no progress, or review failure.
6. Run the final Python or AI validator after all tasks are reviewed.
7. If final validation fails, keep the project changes, create focused repair task(s), and continue.

Within one process, normal model errors, timeouts, loop detection, session unavailable, review failures, validator failures, protected-file edits, and no-progress cycles are retried automatically. If one TODO repeatedly fails in the model stage without any project changes and a Python validator is configured, the runner defers that TODO to final validation so the whole run can keep moving. If the Python process, OS, machine, or power fails, use an external supervisor to restart the same command with `--resume`.

## Activity Watchdog

Execution has a default activity idle watchdog. It starts when the AI execution call starts. Project file changes and AI CLI output both refresh activity. If neither signal appears for 900 seconds, the runner stops that AI CLI call early and asks review to decide whether the current task is complete. This never marks work complete by itself; review and final validation still own completion.

## Task Prompt Shape

Runner prompt templates live under `prompts/`. `runner_support.py` loads those Markdown templates and fills runtime values such as project root, protected files, current task JSON, validator feedback, and executor output.

Each TODO execution usually reuses the same main agent session. The runner sends compact context:

- hard rules and protected-file boundaries
- original goal
- completed task titles
- recent validator feedback
- current task title, description, and acceptance criteria
- previous attempt output or diagnostic
- recovery instructions when needed

Each TODO prompt is about the current task, completion conditions, and the last failure. If repeated no-progress suggests the session is unhealthy, the runner clears the session and continues from runner state in a fresh session.

Agents may read validator files to understand expected behavior, but they must not modify validator files or hardcode validator internals. Python owns final validator execution and runner state. Validator feedback is authoritative. If fallback planning sees validator stdout with structured `[E...]` error headings, it creates one repair TODO per error; otherwise it keeps one repair TODO.

Planning is intentionally right-sized. The planning prompt asks the model to extract concrete deliverables first, always return valid JSON, and choose task count from complexity: trivial goals can be one task, small tools usually need 2-5 tasks, and broad or multi-file goals often need 6-20 verifiable tasks. If the model returns too few tasks or planning repeatedly fails, deterministic fallback can split headings, numbered items, bullet items, paragraphs, or dense sentence-level deliverables such as source files, CLI behavior, generated outputs, persistence, tests, templates, configuration, and documentation.

## Validator Output

File validators are format-free: exit code `0` is PASS, any non-zero exit is FAIL. Stdout and stderr are captured together. The state keeps bounded validator feedback at 20,000 characters, preserving both the beginning and end of long output so the first failure and final summary usually survive.

Recommended validators keep stdout compact and write full evidence under `.ai-task-runner/validator-reports/`. Stdout should be the model-facing summary: status, counts, `report_dir`, and the first actionable blocking findings. Detailed diffs, long command output, and scoring evidence should go into `summary.txt`, `errors.txt`, `warnings.txt`, and referenced `Full report:` files. Repair prompts tell the agent to read `summary.txt`, then `errors.txt`, then only the first relevant full report needed to fix the first blocking error. `docs/validator_templates/` contains copy-and-edit templates, including a large folder comparison validator that checks target config files while saving full diffs to disk and reporting config value sharing as warning-only feedback.

Install this project with `python -m pip install -e C:\Users\kevin\ai-task-runner` if validators in other project directories should import `ValidatorReport` as `from ai_task_runner_validator import ValidatorReport`.

The runner clears `<project-root>/.ai-task-runner/validator-reports/` immediately before each Python validator subprocess starts. This prevents stale detailed reports from one validation attempt being mistaken for the current failure.

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
runner_support.py                 Prompt loading, parsers, validators, protection, UI
runner_models.py                  RunState and Task models
agent.py                          Session-aware backend facade
process_control.py                Subprocess timeout and activity watchdog
api.py                            Backward-compatible API alias
models.py                         Backward-compatible model alias
version.py                        Package version used by docs and JSON events
QWEN.md                           Qwen project rule file for this repository
AGENTS.md                         OpenCode project rule file for this repository
prompts/                          Editable runner prompt templates
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

Latest local result: `124 passed, 1 skipped`.
