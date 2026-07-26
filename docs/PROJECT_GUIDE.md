# AI Task Runner v1.1.1 Project Guide

This document is for humans and coding agents. It explains what the project is, how the loop works, and where important files live.

## Purpose

AI Task Runner is a small automation wrapper around coding agents such as Qwen Code and OpenCode. The user provides a requirement and a validator. The runner asks the agent to understand and split the work, executes one task at a time, asks the agent to review that task, then runs a final validator. It keeps state and retries until the validator passes or a configured limit is reached.

The runner does not implement task-specific deliverables. The external agent writes project files. The runner only orchestrates, monitors, retries, reviews, validates, and resumes.

## 24h Loop

1. Prepare backend project rules such as `QWEN.md` or `AGENTS.md`.
2. Plan remaining work into ordered tasks.
3. Execute only the current task in the existing main session.
4. Review the current task in read-only mode.
5. Move to the next task only when review returns `completed=true`.
6. Run the final Python or AI validator after all tasks are reviewed.
7. If validation fails, record feedback, re-plan remaining work, and continue.
8. Persist state in `.ai-task-runner/state.json` so `--resume` can continue.

Within one process, normal model errors, timeouts, loop detection, review failures, validator failures, protected-file edits, and no-progress cycles are retried automatically. If the Python process, OS, machine, or power fails, use an external supervisor to restart the same command with `--resume`.

Execution also has a default file-change idle watchdog. After project files change, if no further project file changes are detected for 900 seconds, the runner stops that AI CLI call early and asks read-only review to decide whether the current task is complete. This does not mark work complete by itself; review and final validation still own completion.

For Qwen, the runner defaults to `--yolo` and excludes Qwen todo, subagent, skill, and computer-use tools. This keeps implementation work in normal file and shell tools and avoids desktop-control loops during long runs.

## Task Prompt Shape

Each TODO execution reuses the same main agent session. The runner sends a compact prompt containing:
- hard rules and protected-file boundaries
- the original goal
- completed task titles
- recent validator feedback
- the current task title, description, and acceptance criteria
- previous attempt output or diagnostic when present
- recovery instructions when needed

Task execution prompts do not expose validator file paths or validator source. Python runs final validators after review and sends only validator feedback into later cycles. This keeps agents from hardcoding to validator internals. When validator feedback is present, execution and review treat it as authoritative. Fallback planning creates a single `Repair validator failure` task instead of replaying the original full checklist.
- recovery instructions when no progress repeats

The execution prompt explicitly says to execute only the current task and not start later tasks. Review prompts are read-only. Final validator prompts run after every task is reviewed.

## YAML Resume

YAML batch mode is supported. Each YAML item gets its own state file and main session:

```text
.ai-task-runner/script/001/state.json
.ai-task-runner/script/002/state.json
```

When `--resume` is used, items with existing state resume from their own state/session. Completed items return immediately because `completed=true`; unfinished items continue from their saved task, validator, and session state. Items without state start fresh.

## Project Structure

```text
ai_task_runner.py                 CLI entry point
runner_api.py                     Canonical Python API: RunRequest, run
runner_core.py                    TaskRunner, YAML batch flow, retry/review/validation loop
runner_models.py                  Serializable RunState and Task models
runner_support.py                 Prompts, parsing, validators, file protection, UI/events
agent.py                          Session-aware facade over backend implementations
process_control.py                Timeout and process-tree control
version.py                        Package version

backends/
  base.py                         Backend interface and shared command execution
  qwen.py                         Qwen CLI command, JSON decoding, root QWEN.md rules
  opencode.py                     OpenCode CLI command, JSON decoding, root AGENTS.md rules
  __init__.py                     Backend registry

docs/
  DESIGN.md                       Architecture and operating model
  USER_GUIDE.md                   CLI/API usage guide
  TEST_MATRIX.md                  Test and real-smoke coverage
  PROJECT_GUIDE.md                Human/AI project overview

examples/
  01_simple_marker/               Minimal deterministic validator example
  02_sorting_algorithms/          Code-generation example
  03_csv_summary_cli/             CLI and output validation example
  04_ai_validator_docs/           AI validator example
  05_yaml_release_pipeline/       YAML release pipeline example
  06_yaml_data_migration_pipeline/YAML migration pipeline example

smoke/
  qwen_csv_analyzer/              Real Qwen single-prompt CSV tool case
  qwen_expression_evaluator/      Real Qwen single-prompt evaluator case
  qwen_todo_cli/                  Real Qwen single-prompt todo CLI case
  qwen_single_prompt_todo_split/  Real Qwen single-prompt todo split case
  qwen_sorting_micro_pipeline/    Real Qwen YAML sorting pipeline case
  qwen_markdown_scoring/          Real Qwen Markdown scoring case
  qwen_data_structures/           Real Qwen data-structures case

tests/
  test_backends.py                Backend command/rules behavior
  test_runner.py                  Core runner behavior
  test_resilience_matrix.py       Retry, timeout, protected-file, validator edge cases
  test_integration_api.py         Public API and JSON event integration
  test_public_contract.py         Compatibility and exported API contract
  test_documentation.py           Documentation contract
  test_examples.py                Example starter-state checks
  *_agent.py                      Fake agent CLIs used by tests
```

## Backend Rule Files

Qwen Code uses `QWEN.md` in the project root for project instructions. OpenCode uses `AGENTS.md` in the project root. The runner creates or extends these files in the target project and protects them during a run so the task agent cannot rewrite the orchestration rules.

## Validation Contract

Python validators receive:

```text
python validator.py --project-root <root> --state-file <state.json> [...validator args]
```

Exit code `0` means pass. Any non-zero exit code means fail and feeds stdout/stderr back into the next cycle. Validators may inspect generated files and runner state, but task agents must not modify validator files or runner state.

## Current Confidence

The current test suite passes on Windows with Python 3.10.0:

```text
107 passed, 1 skipped
```

Real Qwen smoke cases have passed for CSV analyzer, expression evaluator, todo CLI, Markdown scoring, data structures, sorting pipeline, and single-prompt todo splitting. On 2026-07-26, local Qwen was also re-run through `ai_task_runner.py` for `qwen_simple`, `qwen_sorting_min`, and `qwen_markdown_scoring`; those runs covered loop detection retry, validator repair, TODO-by-TODO review, protected-file restore, and resume.
