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

This expands to Qwen Code via `qwen.cmd`, `--agent-timeout 7200`, `--planning-timeout 600`, `--agent-idle-after-change-timeout 900`, `--validator-timeout 1200`, `--max-attempts 0`, and `--max-cycles 0`. Qwen runtime calls also get `--max-tool-calls 40` unless you provide your own value with `--agent-arg`.

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

If a Python validator is configured and an AI review cannot return valid review JSON, the runner can defer that task's completion judgment to the final validator instead of rerunning the same task forever. The run still stops only after the final validator passes.

When the same final validator failure repeats, repair tasks switch to a fresh agent session while still receiving the saved runner state and validator feedback. This helps a small model escape a bad prior approach without losing the 24h retry loop.

Validator feedback is passed back into the next planning prompt. The model, not Python prompt heuristics, decides how to split repair TODOs.

Planning prompts give the model the goal, project outline, progress, and compact retry feedback. The model identifies concrete deliverables, splits work to match actual complexity, and returns valid task JSON. If planning fails to return valid JSON, the runner retries planning with compact feedback until the model returns the fixed task schema.
For Qwen, planning uses `--safe-mode` and excludes tools so planning cannot get stuck exploring files before returning TODO JSON. The planning prompt includes a breadth-first project outline so top-level structure stays visible even when a project has many fixture or output files. Runtime execution keeps the normal Qwen tool environment, with a default tool-call cap to prevent one task from running forever while repeatedly using tools.

When a task repeatedly fails in the model stage without changing project files and a Python validator is configured, the runner can defer that TODO to final validation instead of looping forever on one model failure. The run is still marked complete only after the final validator passes.

The runner and prompt templates must stay task-agnostic. Case-specific names such as a particular app, fab, workflow, generated filename, or algorithm belong only in user goals, validators, examples, smoke cases, or test fixtures. The core runner parses the fixed AI task JSON contract, but it does not interpret user prompt formats or special-case one user's project.

When `--validator ai` is used, the final AI validator runs in a fresh session and its `missing_items` become focused repair feedback if it fails. This gives no-validator runs a closed loop, but the guarantee is only as strong as the independent AI review and the checks it chooses to run.

For Qwen, the backend uses `--output-format stream-json`. During execution, CLI stdout/stderr counts as model-call activity until the first project file change; after that, new project changes refresh activity. If the model keeps talking but stops changing files for the idle window, the runner stops that call and asks review/final validation to judge the saved files. Read-only planning, review, and AI-validation calls use the same setting to retry calls that produce no CLI output.

The default model-call idle watchdog is:

```text
--agent-idle-after-change-timeout 900
```

Use `0` to disable it. For slow local models, the default hard timeout is already `7200` seconds per model call.

## Validators

Python validators are called as:

```text
python validator.py --project-root <root> --state-file <root>/.ai-task-runner/state.json [...validator args]
```

Exit code `0` means pass. Non-zero output is saved as validator feedback and sent into the next repair cycle. Validator feedback stored in state is capped at 20,000 characters, preserving the start and end of very long logs. Agents may read validator files and expected/reference/golden fixtures to understand expected behavior, but validator files, runner state, runner source, backend rule files, and read-only answer fixtures must not be changed. Use `--protect-file <path>` for any read-only expected file or folder; protected paths are restored if the model edits them.

Reusable validator templates live in `docs/validator_templates/`. They show the recommended pattern: fail with a non-zero exit code only for blocking errors, keep stdout short, and write full error, warning, and diff reports under `.ai-task-runner/validator-reports/`. `external_command_validator.py` wraps an exe, bat, jar, or CLI and copies external log folders into model-readable reports.

For large validations, stdout should be a repair summary, not the full diff. Print the status, counts, `report_dir`, and the first few actionable errors. Put large evidence in `summary.txt`, `errors.txt`, `warnings.txt`, and referenced `Full report:` files. Repair prompts tell the agent to read `summary.txt`, then `errors.txt`, then only the first relevant full report needed for the first blocking error.

Optional helper install:

```bat
python -m pip install -e C:\Users\kevin\ai-task-runner
```

Then any validator can use `from ai_task_runner_validator import ValidatorReport`. Without installing, copy `docs/validator_templates/validator_interface.py` next to the validator.

Before each Python validator run, the runner clears `<project-root>/.ai-task-runner/validator-reports/`. Treat that directory as the latest validation report area, not a history folder.

Runner progress and status events are appended as JSON lines to `<project-root>/.ai-task-runner/log.txt` for debugging long unattended runs.

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

Latest local result: `138 passed, 1 skipped`.

For a concise human/AI overview, read [docs/PROJECT_GUIDE.md](docs/PROJECT_GUIDE.md).

## Prompt Templates

Runner prompts live in `prompts/`:

- `rules.md` and `planning_rules.md`: shared hard rules
- `plan.md`: TODO planning
- `plan_refine.md`: second-pass AI refinement for task granularity
- `execution.md`: current-task execution
- `review.md`: read-only task review
- `ai_validator.md`: AI final validation

Edit these files to tune model behavior. Keep the required JSON response shapes and phase intent clear; wording can be adjusted without changing runner state or retry behavior.

## Model failure diagnostics

Task retry status includes the backend exit code, elapsed seconds, command mode
(`new` or `resume`), the parsed event that supplied the session ID, and a compact
combined stderr/stdout tail. These fields are diagnostic only and do not change
retry or completion behavior.

## Review error policy

The normal flow remains `TODO execution -> AI Review -> final Validator`. A parsed Review FAIL is never skipped: its `missing_items` return to the same TODO. Only Review call, timeout, loop, parse, or schema errors use this policy.

- Default: `--review-error-retries 3`. After that many consecutive Review errors, a successful executor result with project file changes is provisionally accepted with `review_skipped=true`; the final Validator remains authoritative.
- Strict: add `--strict-review`. Review errors never skip a TODO. Every error batch rebuilds only the Review session and retries without rerunning the successful executor.
- No project changes: Review errors are never skipped, even in default mode.

State records `review_skipped`, `review_skip_reason`, `review_error_attempts`, and `review_session_rebuilds` for audit and repair planning.

## Multiple independent Final AI validations

When `--validator ai` is used, Final AI validation can require multiple independent verdicts:

```bat
python ai_task_runner.py ... --validator ai --final-ai-validations 3 --final-ai-required-passes 2
```

- Every validation uses a brand-new model session.
- The default remains `1` validation and `1` required PASS.
- A model call or JSON error is an abstention; it does not count as PASS or FAIL.
- Any explicit FAIL with blocking findings fails the cycle immediately and enters repair planning.
- The run passes only after the configured number of independent PASS results is reached.
- Final AI checks both original requirements and concrete high-impact safety, destructive, reliability, portability, security, and regression defects. Style preferences and speculative concerns do not block PASS.
