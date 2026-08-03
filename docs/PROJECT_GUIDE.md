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

Within one process, normal model errors, timeouts, loop detection, session unavailable, review failures, validator failures, protected-file edits, and no-progress cycles are retried automatically. If one TODO repeatedly fails in the model stage without any project changes and a Python validator is configured, the runner defers that TODO to final validation so the whole run can keep moving. If an AI review cannot produce valid review JSON while a Python validator is configured, the runner also defers that task's completion judgment to the final validator instead of rerunning the same task forever. When the same final validator failure repeats, repair tasks use a fresh agent session while keeping saved runner state and validator feedback. If the Python process, OS, machine, or power fails, use an external supervisor to restart the same command with `--resume`.

## Activity Watchdog

Execution has a default activity idle watchdog. It starts when the AI execution call starts. Project file changes and AI CLI output both refresh activity. If neither signal appears for 900 seconds, the runner stops that AI CLI call early and asks review to decide whether the current task is complete. This never marks work complete by itself; review and final validation still own completion.

## Task Prompt Shape

Runner prompt templates live under `prompts/`. `prompting.py` loads those Markdown templates and fills runtime values such as project root, protected files, current task JSON, validator feedback, and executor output.

Each TODO execution usually reuses the same main agent session. The runner sends compact context:

- hard rules and protected-file boundaries
- original goal
- completed task titles
- recent validator feedback
- current task title, description, and acceptance criteria
- previous attempt output or diagnostic
- recovery instructions when needed

Each TODO prompt is about the current task, completion conditions, and the last failure. If repeated no-progress suggests the session is unhealthy, the runner clears the session and continues from runner state in a fresh session.

Agents may read validator files and expected/reference/golden fixtures to understand expected behavior, but they must not modify validator files, read-only answer fixtures, hardcode validator internals, or create sidecar state/log/scratch files next to outside-root paths. Use `--protect-file <path>` for read-only fixture files or folders that must be restored automatically if a model edits them. Python owns final validator execution and runner state. Validator feedback is authoritative. If fallback planning sees validator stdout with structured `[E...]` error headings, it creates one repair TODO per error; otherwise it keeps one repair TODO.

Planning is intentionally right-sized. The planning prompt asks the model to extract concrete deliverables first, always return valid JSON, and choose task count from complexity: trivial goals can be one task, small tools usually need 2-5 tasks, and broad or multi-file goals often need 6-20 verifiable tasks. If the model returns too few tasks or planning repeatedly fails, deterministic fallback uses structure first: Markdown headings, numbered items, bullet items, blank-line paragraphs, and sentence fragments with file-like references. Expected-result, validation, acceptance, example, and ordering/precedence sections remain context unless they contain a distinct file deliverable. Pure constraints remain context for execution and acceptance instead of becoming standalone TODO tasks.

Runner code and prompt templates are task-agnostic by design. Generic structure such as files, commands, outputs, data contracts, validation evidence, or user-facing deliverables may guide planning. Names from one real case, such as a specific app, fab, workflow, generated filename, algorithm, or validator detail, belong only in user goals, validators, examples, smoke cases, or test fixtures.

## Validator Output

File validators are format-free: exit code `0` is PASS, any non-zero exit is FAIL. Stdout and stderr are captured together. The state keeps bounded validator feedback at 20,000 characters, preserving both the beginning and end of long output so the first failure and final summary usually survive.

Recommended validators keep stdout compact and write full evidence under `.ai-task-runner/validator-reports/`. Stdout should be the model-facing summary: status, counts, `report_dir`, and the first actionable blocking findings. Detailed diffs, long command output, and scoring evidence should go into `summary.txt`, `errors.txt`, `warnings.txt`, and referenced `Full report:` files. Repair prompts tell the agent to read `summary.txt`, then `errors.txt`, then only the first relevant full report needed to fix the first blocking error. `docs/validator_templates/` contains copy-and-edit templates, including a large folder comparison validator that checks target config files while saving full diffs to disk and reporting config value sharing as warning-only feedback.

External validators such as exe, bat, jar, or Java CLIs should be wrapped by `docs/validator_templates/external_command_validator.py`. The wrapper keeps the runner contract unchanged: the Python wrapper is still the `--validator`, the external command exit code becomes PASS/FAIL, stdout/stderr are saved, and any configured log folders are copied into `.ai-task-runner/validator-reports/external-command/` with a `logs-index.txt` file for the agent.

With `--validator ai`, the final check is a fresh read-only agent session. The AI validator prompt asks for project inspection, reasonable local checks, and JSON containing `passed`, `reason`, `missing_items`, `checks_run`, and `suggested_checks`. On failure, the runner formats `missing_items` as structured `[E...]` feedback so the next cycle can create focused repair tasks. This is a useful fallback when no Python validator exists, but a deterministic Python validator remains the stronger contract.

Install this project with `python -m pip install -e C:\Users\kevin\ai-task-runner` if validators in other project directories should import `ValidatorReport` as `from ai_task_runner_validator import ValidatorReport`.

The runner clears `<project-root>/.ai-task-runner/validator-reports/` immediately before each Python validator subprocess starts. This prevents stale detailed reports from one validation attempt being mistaken for the current failure.

Runner progress and status events are appended as JSON lines to `<project-root>/.ai-task-runner/log.txt`. Inspect this file to debug long unattended runs without relying on terminal scrollback. State writes use atomic replace with a short retry window so transient Windows file locks from editors, antivirus, backup tools, or monitoring readers do not stop a 24h run.

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
ai_task_runner_validator.py       Installable ValidatorReport helper

runner/                           Main implementation package
runner/api.py                     Public Python API and request validation
runner/core.py                    TaskRunner state machine, retry, review, resume
runner/models.py                  RunState and Task serialization
runner/support.py                 Parsers, protection, retry, validator subprocess utilities
runner/agent.py                   Session-aware backend facade
runner/agent_args.py              Backend-specific planning/runtime argument policy
runner/planning.py                TODO planning, fallback splitting, repair task derivation
runner/prompting.py               Prompt template loading and prompt builders
runner/validation.py              AI final validation helper
runner/script_runner.py           YAML batch orchestration and per-item resume setup
runner/process_control.py         Subprocess timeout and activity watchdog
runner/ui.py                      Live terminal UI and JSON progress events
runner/defaults.py                Shared default backend, command, timeout, and limit values
runner/errors.py                  RunnerError
runner/version.py                 Package version used by docs and JSON events
runner/backends/base.py           Backend interface and shared command handling
runner/backends/qwen.py           Qwen stream-json backend
runner/backends/opencode.py       OpenCode backend

prompts/                          Editable runner prompt templates
docs/                             Human and AI project documentation
docs/validator_templates/         Copyable validator templates and wrappers
examples/                         Reusable sample prompts, validators, and runners
smoke/                            Real Qwen smoke cases and validators
tests/                            Unit, API, resilience, and documentation tests

QWEN.md                           Qwen project rule file for this repository
AGENTS.md                         OpenCode project rule file for this repository
pyproject.toml                    Package metadata for runner and ValidatorReport helper
requirements*.txt                 Runtime and development dependencies
.ai-task-runner/                  Local run state, ignored by git
.qwen/                            Local Qwen state, ignored by git
.pytest_cache/                    Local pytest cache, ignored by git
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

Latest local result: `147 passed, 1 skipped`.
