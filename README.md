# AI Task Runner v1.1.1

AI Task Runner is a small automation wrapper for coding CLIs such as Qwen Code and OpenCode. You provide a project, a goal, and a validator. The runner asks the agent to split the goal into TODO tasks after bounded project inspection, inspect the files needed by each current TODO, execute one task at a time, review each task, then run the final validator. It keeps state and retries recoverable failures until the validator passes or a configured limit is reached.

## Quick Start

Default mode is the 24h Qwen runner. The common command is intentionally short:

```bat
python ai_task_runner.py ^
  --project-root C:\work\project ^
  --goal "完成需求並通過驗證" ^
  --validator C:\validators\validator.py
```

This expands to Qwen Code via `qwen.cmd`, `--agent-timeout 7200`, `--planning-timeout 600`, `--agent-idle-after-change-timeout 900`, `--validator-timeout 1200`, `--max-attempts 0`, and `--max-cycles 0`. Qwen runtime calls also get `--max-tool-calls -1` unless you provide your own value with `--agent-arg`.

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
1. Plan TODO tasks from the goal and bounded project inspection
2. For each task: inspect relevant files -> execute -> review -> retry if needed
3. Run final Python or AI validator
4. On validator failure: replace the active TODO list with focused repair task(s) and continue
```

The runner does not generate code itself. The agent writes project files. The runner owns state, retries, review orchestration, protected-file restore, validator execution, and resume.

## Reliability

Within one live runner process, these failures are automatically retried: model errors, Qwen loop detection, session unavailable, timeouts, invalid review JSON, review failure, protected-file edits, validator failure, and no-progress attempts.

If a Python validator is configured and an AI review cannot return valid review JSON, the runner can defer that task's completion judgment to the final validator instead of rerunning the same task forever. The run still stops only after the final validator passes.

When the same final validator failure repeats, repair tasks switch to a fresh agent session while still receiving the saved runner state and validator feedback. This helps a small model escape a bad prior approach without losing the 24h retry loop.

Validator feedback is passed back into the next planning prompt. After that repair plan is accepted, `state.tasks` is replaced by the new cycle TODOs instead of retaining completed TODOs from older cycles. Full history remains in `log.txt`; active state stays bounded for UI, prompts, and resume. The model, not Python prompt heuristics, decides how to split repair TODOs.

There is no separate Understand Agent or persisted understanding artifact. Planning uses one draft Planner session in two turns: first a bounded read-only Understand turn maps the outline, narrows to goal-relevant areas, reads only enough evidence to plan reliably, and stops rather than scanning the whole repository; then the same session is resumed with project tools disabled to produce TODO JSON. Each Executor later reads only the files needed by its current TODO before changing them.

Planning prompts do not pre-enumerate a `Project files:` tree. The project root remains the execution boundary; the read-enabled Understand turn discovers only the files it needs, while no-tool planning stages rely on the goal, progress, validator feedback, and bounded inspection summary already gathered. The same-session Plan prompt is intentionally slim because the session already contains the Understand context.

Planning is behavior-adaptive rather than model-size-specific. A fresh draft Planner first performs a bounded read-only Understand turn using map → select → focused deep-read, without creating TODOs. Whether that turn completes normally or is stopped by a model/tool error, a resumable session is reused once with project tools disabled to produce the plan from evidence already gathered. If the session is unavailable or that no-tool Plan turn fails, planning falls back to fresh no-tool minimal planning using the goal, runner outline, progress, constraints, validator feedback, and any successful inspection summary; retries stay in this no-tool fallback instead of restarting repository exploration. Initial planning still requires at least six concrete TODOs; repair planning may contain fewer.

Refiner and Plan Judge remain fresh no-tool quality layers. A valid draft is retained as the last usable plan: Refiner infrastructure/format errors keep the previous plan, Judge infrastructure/format errors allow the current valid plan to proceed, and repeated explicit Judge rejection is bounded before execution continues to the Final Validator loop. The Final Validator remains the only hard correctness gate. This lets stronger models stay on the happy path while weaker models automatically degrade without special model names, repository-size thresholds, or fixed exploration budgets.
For Qwen, only the first draft planner runs from the project root in `--safe-mode` with local read/list/search tools available and write/edit/shell side effects excluded. The same-session Plan turn, minimal fallback, Refiner, and Judge run without project-read tools. Runtime execution keeps the normal Qwen tool environment; runner timeouts, loop detection, no-progress recovery, and per-TODO session reset prevent one task from polluting later work.

When a task repeatedly fails in the model stage without changing project files and a Python validator is configured, the runner can defer that TODO to final validation instead of looping forever on one model failure. The run is still marked complete only after the final validator passes.

The runner and prompt templates must stay task-agnostic. Case-specific names such as a particular app, fab, workflow, generated filename, or algorithm belong only in user goals, validators, examples, smoke cases, or test fixtures. The core runner parses the fixed AI task JSON contract, but it does not interpret user prompt formats or special-case one user's project.

Structured model results use one shared parser path. The envelope is tolerant but the payload remains strict: surrounding prose, Markdown fences, and earlier unrelated JSON values are allowed, while malformed JSON, wrong schema, missing required fields, or invalid task counts still fail. Candidate extraction uses the standard JSON decoder and then each stage applies its own schema/semantic validation; the generic layer does not hardcode `tasks`, `accepted`, `passed`, or other stage fields.

When `--validator ai` is used, the final AI validator runs in a fresh session and its `missing_items` become focused repair feedback if it fails. This gives no-validator runs a closed loop, but the guarantee is only as strong as the independent AI review and the checks it chooses to run.

For Qwen, the backend uses `--output-format stream-json`. During execution, CLI stdout/stderr counts as model-call activity until the first project file change; after that, new project changes refresh activity. If the model keeps talking but stops changing files for the idle window, the runner stops that call and asks review/final validation to judge the saved files. Read-only planning, review, and AI-validation calls use the same setting to retry calls that produce no CLI output.

Qwen prompt transport is stdin-only. The full prompt is written to the child process stdin and EOF is closed after the write; the Qwen command does not carry `-p` or a prompt in argv. This avoids dual-input ambiguity and Windows command-line length limits for large planning prompts. Other backends keep their own transport contract.

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

Exit code `0` means pass. Non-zero output is saved as validator feedback and sent into the next repair cycle. Validator feedback stored in state is capped at 20,000 characters, preserving the start and end of very long logs. Agents may read validator files and expected/reference/golden fixtures to understand expected behavior, but protected paths must not be changed. Put project-relative files or folders in `<project-root>/.ai-task-runner.yaml` under `protected_paths`; the policy file protects itself, and protected changes are restored to the exact pre-call working-tree state. `--protect-file <path>` remains supported for one-off protection. Every runner child process blocks `git add`, `git commit`, and `git push`; read-only Git commands remain available, and final Git acceptance is human review.

Protected paths are normalized as roots/subtrees. If an explicitly protected root already contains another protected path, the descendant is omitted from the effective list and from prompts; the runner does not infer a new protected directory merely because all currently known children happen to be protected. Runner source protection therefore represents `runner/` as one subtree instead of listing every module separately.


Example project policy:

```yaml
protected_paths:
  - expected/
  - validation.py

instructions:
  always: |
    Never hardcode project-specific values.
    Keep changes minimal and preserve existing behavior.
  project: |
    Keep configuration data-driven and follow existing project conventions.
```

`instructions.always` is injected into every AI call, so keep it short and reserve it for rules the model must never forget. `instructions.project` is maintained in the Runner-managed `QWEN.md` / `AGENTS.md` block and is better for longer project guidance. Both fields are optional. A folder entry protects the entire subtree, including create/delete/rename operations. Paths must stay inside `project-root`.

Reusable validator templates live in `docs/validator_templates/`. They show the recommended pattern: fail with a non-zero exit code only for blocking errors, keep stdout short, and write full error, warning, and diff reports under `.ai-task-runner/validator-reports/`. `external_command_validator.py` wraps an exe, bat, jar, or CLI and copies external log folders into model-readable reports.

For large validations, stdout should be a repair summary, not the full diff. Print the status, counts, `report_dir`, and the first few actionable errors. Put large evidence in `summary.txt`, `errors.txt`, `warnings.txt`, and referenced `Full report:` files. Repair prompts tell the agent to read `summary.txt`, then `errors.txt`, then only the first relevant full report needed for the first blocking error.

Optional helper install:

```bat
python -m pip install -e C:\Users\kevin\ai-task-runner
```

Then any validator can use `from ai_task_runner_validator import ValidatorReport`. Without installing, copy `docs/validator_templates/validator_interface.py` next to the validator.

Before each Python validator run, the runner clears `<project-root>/.ai-task-runner/validator-reports/`. Treat that directory as the latest validation report area, not a history folder.

Runner progress and status events are appended as JSON lines to `<project-root>/.ai-task-runner/log.txt` for debugging long unattended runs. Model-call diagnostics live under `.ai-task-runner/debug/`: `current-prompt.txt` shows the active prompt, while `last-prompt.txt` and `last-result.txt` keep the previous completed/failed call. A bounded `history/` keeps up to 100 prompt/result pairs, 50 MB total, with each history entry capped at 2 MB (head and tail retained when truncated). History is trimmed oldest-pair-first. Debug writes are best-effort and do not participate in state, resume, validation, or project-change detection.

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
  core.py                     TaskRunner state machine, retry, resume, validation loop
  planning.py                 Understand, plan, refine, and plan-judge flow
  reviewing.py                Read-only Review and no-tool Review Finalize flow
  model_results.py            Shared JSON candidate extraction + strict stage validation
  models.py                   RunState and Task serialization
  support.py                  Protection, project snapshots, retry, validator helpers
  agent.py                    Session-aware facade over backend adapters
  debug.py                    Current/last diagnostics plus bounded model-call history
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

For a concise human/AI overview, read [docs/PROJECT_GUIDE.md](docs/PROJECT_GUIDE.md).

## Prompt Templates

Runner prompts live in `prompts/`:

- `rules.md` and `planning_rules.md`: shared hard rules
- `plan_understand.md`: bounded read-only project understanding; no TODOs yet
- `plan_finalize.md`: no-tool TODO planning from already gathered evidence
- `plan_refine.md`: fresh-session rewrite of task granularity
- `plan_judge.md`: independent semantic quality gate for the refined plan
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

- Review starts with one independent read-only call. An explicit FAIL retries the TODO. If that call errors and its session is resumable, the runner makes one same-session no-tool finalization attempt; only a second error records `review_skipped=true` and continues to the final Validator. Qwen enforces the no-tool finalization at the backend capability level.
- No project changes: Review is skipped immediately and the final Validator decides.

State records `review_skipped` and `review_skip_reason` for audit and repair planning.

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

### Small-model TODO isolation

A fresh or rebuilt Executor session receives the original goal for context and global constraints plus the current TODO, but the current TODO is the only executable scope. The goal must never be used to discover or implement later TODOs, and the remaining TODO list is not provided. Same-session retries use a short continuation prompt that does not resend the goal, task JSON, or static rules; it carries only new review/recovery feedback. Every write must be required by the current TODO deliverable or acceptance criteria; a read-only deliverable must not mutate project files, and later TODO work must not be implemented early. The Executor may return after making one coherent improvement instead of forcing the whole TODO into one model call. If a failed call changed project files, the runner immediately reviews the saved state; if two fresh sessions hit the same failure with no new project change, the TODO is deferred to final validation instead of blocking the run.

## Review Scope Isolation

Per-task Review uses an independent fresh session, is read-only, and judges only the current TODO deliverable and acceptance criteria. It inspects this TODO's accumulated changed files first, then reads only the minimum additional directly related evidence. Incomplete later TODOs or whole-project work cannot block the current TODO. Final AI Validation independently judges the complete goal.
