# AI Task Runner v1.1.1

AI Task Runner is a small automation wrapper for coding CLIs such as Qwen Code and OpenCode. You provide a project, a goal, and a validator. The runner asks the agent to understand the project, split the goal into TODO tasks, execute one task at a time, review each task, then run the final validator. It keeps state and retries recoverable failures until the validator passes or a configured limit is reached.

## Quick Start

Default mode is the 24h Qwen runner. The common command is intentionally short:

```bat
python ai_task_runner.py ^
  --project-root C:\work\project ^
  --goal "完成需求並通過驗證" ^
  --validator C:\validators\validator.py
```

This expands to Qwen Code via `qwen.cmd`, `--agent-timeout 7200`, `--planning-timeout 600`, `--agent-idle-after-change-timeout 900`, `--validator-timeout 1200`, `--max-attempts 0`, and `--max-cycles 0`.

For long requirements, put the prompt in a UTF-8 text file:

```bat
python ai_task_runner.py ^
  --project-root C:\work\project ^
  --goal-file C:\work\requirements.md ^
  --validator C:\validators\validator.py
```

Use AI validation instead of a Python validator:

```bat
python ai_task_runner.py --goal "Update docs" --validator ai
```

AI validation uses a fresh independent agent session. It asks the agent to inspect the project, run reasonable local checks when possible, and return JSON with `passed`, `reason`, `missing_items`, `checks_run`, and `suggested_checks`. If AI validation fails, `missing_items` are converted into focused repair feedback for the next cycle. Python validators are still stronger when exact correctness matters.

## Flow

```text
1. Understand project and goal
2. Plan TODO tasks
3. For each task: execute -> review -> retry if needed
4. Run final Python or AI validator
5. On validator failure: add focused repair task(s) and continue
```

The runner does not generate code itself. The agent writes project files. The runner owns state, retries, review orchestration, protected-file restore, validator execution, and resume.

## Reliability

Within one live runner process, these failures are automatically retried: model errors, Qwen loop detection, session unavailable, timeouts, invalid review JSON, review failure, protected-file edits, validator failure, and no-progress attempts.

When validator stdout contains structured error headings such as `[E001] ...`, fallback repair planning splits them into separate TODO items. Unstructured validator output still creates one repair TODO.

Planning prompts ask the model to identify concrete deliverables first and to always return valid task JSON. Trivial goals may become one task, small tools usually become 2-5 tasks, and broad or multi-file goals often become 6-20 verifiable tasks. If model planning repeatedly fails, deterministic fallback still derives tasks from headings, numbered items, bullets, paragraphs, and dense deliverable phrases in the goal.

When a task repeatedly fails in the model stage without changing project files and a Python validator is configured, the runner can defer that TODO to final validation instead of looping forever on one model failure. The run is still marked complete only after the final validator passes.

The runner and prompt templates must stay task-agnostic. Case-specific names such as a particular app, fab, workflow, generated filename, or algorithm belong only in user goals, validators, examples, smoke cases, or test fixtures. The core runner may use generic planning heuristics, but it must not special-case one user's project.

When `--validator ai` is used, the final AI validator runs in a fresh session and its `missing_items` become focused repair feedback if it fails. This gives no-validator runs a closed loop, but the guarantee is only as strong as the independent AI review and the checks it chooses to run.

For Qwen, the backend uses `--output-format stream-json`. CLI stdout/stderr and project file changes both count as activity for the execution watchdog. The watchdog starts when the execution call starts; if there is no CLI output and no project file change for the idle window, the runner can stop the AI call and ask review/final validation to judge any saved files.

The default execution idle watchdog is:

```text
--agent-idle-after-change-timeout 900
```

Use `0` to disable it. For slow local models, the default hard timeout is already `7200` seconds per model call.

## Validators

Python validators are called as:

```text
python validator.py --project-root <root> --state-file <root>/.ai-task-runner/state.json [...validator args]
```

Exit code `0` means pass. Non-zero output is saved as validator feedback and sent into the next repair cycle. Validator feedback stored in state is capped at 20,000 characters, preserving the start and end of very long logs. Agents may read validator files to understand expected behavior, but validator files, runner state, runner source, and backend rule files are protected and restored if modified.

Reusable validator templates live in `docs/validator_templates/`. They show the recommended pattern: fail with a non-zero exit code only for blocking errors, keep stdout short, and write full error, warning, and diff reports under `.ai-task-runner/validator-reports/`. `external_command_validator.py` wraps an exe, bat, jar, or CLI and copies external log folders into model-readable reports.

For large validations, stdout should be a repair summary, not the full diff. Print the status, counts, `report_dir`, and the first few actionable errors. Put large evidence in `summary.txt`, `errors.txt`, `warnings.txt`, and referenced `Full report:` files. Repair prompts tell the agent to read `summary.txt`, then `errors.txt`, then only the first relevant full report needed for the first blocking error.

Optional helper install:

```bat
python -m pip install -e C:\Users\kevin\ai-task-runner
```

Then any validator can use `from ai_task_runner_validator import ValidatorReport`. Without installing, copy `docs/validator_templates/validator_interface.py` next to the validator.

Before each Python validator run, the runner clears `<project-root>/.ai-task-runner/validator-reports/`. Treat that directory as the latest validation report area, not a history folder.

## Rule Files

Backend project rules are created in the project root:

- Qwen Code: `QWEN.md`
- OpenCode: `AGENTS.md`

OpenCode's official project rule filename is `AGENTS.md`, not `AGENT.md`.

## YAML Batch

YAML batch mode runs a list of goals one by one. Each item has its own state file under `.ai-task-runner/script/NNN/state.json`. Re-running the same script with `--resume` skips completed items and continues unfinished items from their saved current task, validator feedback, and session state.

## Python API

```python
from runner import RunRequest, run

result = run(RunRequest(
    goal="Build the requested feature",
    validator="ai",
    project_root=".",
))
```

## Project Structure

```text
ai_task_runner.py             CLI parser and entry point
ai_task_runner_validator.py   Installable ValidatorReport helper

runner/                       Main implementation package
  api.py                      Public Python API and request validation
  core.py                     TaskRunner state machine, retry, review, resume
  models.py                   RunState and Task serialization
  support.py                  Shared parsing, protection, retry, validator helpers
  agent.py                    Session-aware facade over backend adapters
  agent_args.py               Backend-specific planning/runtime argument policy
  planning.py                 TODO planning, fallback splitting, repair tasks
  prompting.py                Prompt template loading and prompt builders
  validation.py               AI final validation helper
  script_runner.py            YAML batch orchestration and per-item resume setup
  process_control.py          Process tree, timeout, and activity watchdog handling
  ui.py                       Live terminal UI and JSON progress events
  defaults.py                 Shared 24h defaults for CLI, API, and backends
  errors.py                   RunnerError
  version.py                  Package/documentation version
  backends/
    base.py                   Backend interface and shared command handling
    qwen.py                   Qwen stream-json backend
    opencode.py               OpenCode backend

prompts/                      Editable runner prompt templates
docs/                         Human and AI documentation
  validator_templates/        Copyable validator templates and wrappers
examples/                     Small reusable sample projects
smoke/                        Real Qwen smoke cases and validators
tests/                        Unit, integration, resilience, and contract tests

QWEN.md / AGENTS.md           Project rules for Qwen Code and OpenCode
pyproject.toml                Package metadata for runner and ValidatorReport helper
requirements*.txt             Runtime and development dependencies
.ai-task-runner/              Local run state, ignored by git
.qwen/                        Local Qwen state, ignored by git
.pytest_cache/                Local pytest cache, ignored by git
```

## Current Validation

Real Qwen smoke cases completed through `ai_task_runner.py` on 2026-07-27:

- `qwen_todo_cli`: PASS after validator repair, protected state restore, and resume.
- `qwen_expression_evaluator`: PASS with 3 TODO tasks, loop detection recovery, protected state restore, review restore, and final Python validator.
- `qwen_csv_analyzer`: PASS with 3 TODO tasks and final Python validator.

Run the full suite:

```bat
python -m pytest -q
```

Latest local result: `141 passed, 1 skipped`.

For a concise human/AI overview, read [docs/PROJECT_GUIDE.md](docs/PROJECT_GUIDE.md).

## Prompt Templates

Runner prompts live in `prompts/`:

- `rules.md` and `planning_rules.md`: shared hard rules
- `plan.md`: TODO planning
- `execution.md`: current-task execution
- `review.md`: read-only task review
- `ai_validator.md`: AI final validation

Edit these files to tune model behavior. Keep the core phase phrases such as `Plan only the remaining work`, `Execute only the current task`, `Review only`, and `fresh independent session`, because integrations and tests use them to identify stages.
