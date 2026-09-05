# User Guide

Version: 1.2.53

## Single goal
`python ai_task_runner.py --goal-file prompt.md --project-root <project> --validator validation.py`

Use `--goal "..."` for inline text. `--goal` and `--goal-file` are mutually exclusive.

## Validator arguments
Repeat `--validator-arg` once per argv element:
`--validator-arg "--fab" --validator-arg "FAB23" --validator-arg "--env" --validator-arg "PROD"`.
Do not write `--validator "validation.py --fab FAB23"`; `--validator` is a path or literal `ai`.

## Project policy
Place `.ai-task-runner.yaml` directly in `project-root`:
```yaml
protected_paths:
  - input/
  - ans/
instructions:
  always: |
    Keep changes minimal.
    Never hardcode project-specific values.
  project: |
    Reuse existing architecture and helpers.
```
Protected paths are project-relative and may name files or directories. The policy itself is automatically protected and must not be repeated in `protected_paths`. The Runner does not search parent directories for policy.

## Resume / restart
- `--resume`: continue compatible Runner state.
- `--force-new`: ignore prior run state and start a new run.
- `--resume` and `--force-new` cannot be combined.
- `--plan-only`: build/refresh TODOs, persist state, and exit before execution.

## YAML script mode
`--script tasks.yaml` runs a YAML array sequentially. Each item requires exactly one of `prompt`/`goal` or `goal_file`, plus `validator`. `goal_file` and `ai_validator_prompt_file` are UTF-8; relative paths are resolved from the YAML file directory. Optional fields include `validator_prompt`, either `ai_validator_prompt` or `ai_validator_prompt_file`, `ai_validator_count`, `ai_validator_required_passes`, `project_root`, and `workflow_file`. Relative per-item file paths, including `workflow_file`, are resolved from the script YAML directory. Relative per-item `project_root` values are resolved from the outer `--project-root`; omitting it preserves the existing shared-root behavior. Each item stores Runner-managed state under its own `<project-root>/.ai-task-runner/script/<index>`. The outer YAML orchestrator emits callback/JSON/UI events without creating another work directory. Completion and resume use each item's state path. The child runtime scope restores the parent script runtime when the item exits, preventing Plugin/Event/State context leakage across items.

```yaml
- goal_file: prompts/example-a.md
  project_root: projects/example-a
  validator: validation.py
  ai_validator_prompt_file: ai_validation.md
  ai_validator_count: 3
  workflow_file: workflows/build.yaml
```

## Workflow YAML
Without `--workflow`, Runner selects `workflow/builtin/mixed.yaml`, `workflow/builtin/file.yaml`, or `workflow/builtin/ai.yaml` from validator settings. Workflow YAML keeps only two top-level keys: `stages` defines reusable nodes and `flow` defines execution order. A flow item may override its Stage instance for that invocation. Generic AI-backed nodes use `BaseStage`; `type` defaults to `base`, so it is normally omitted.

Planning is the one intentional dynamic Stage. YAML does not declare `expand`, `foreach`, or another subflow DSL. Instead, Stage definitions outside the static top-level flow become Planner candidates automatically unless they are recovery-only, planners, or validators. `PlanStage` chooses an ordered Stage sequence for every TODO and returns it as `next_steps`.

```yaml
stages:
  planning:
    type: plan
    status: Plan
    result_handler: plan

  execute:
    status: Execute
    mode: write
    prompt: stages/execution.md
    continuation_prompt: stages/execution_continue.md
    result_handler: task

  security_review:
    status: Security review
    prompt: prompts/security_review.md

  review_task:
    status: Review
    prompt: stages/review.md
    parser: review
    result_status: completed
    result_handler: review

  validate_file:
    type: python
    validator: file
    status: Validate
    result_handler: validation

flow:
  - planning
  - validate_file
```

`continuation_prompt` is optional. It is used only when the same live session has already seen the Stage's full `prompt`; the first call and every fresh/rebuilt session still receive the complete prompt. This lets repeated builtin Execute/Review handoffs send only new TODO/evidence without adding Stage-name branches to Pipeline.

For this YAML, Planner can choose `execute`, `security_review`, and `review_task`; it cannot choose `planning` or `validate_file`. A TODO may therefore produce `steps: [execute, security_review, review_task]`. The selected Stage names are validated before execution, stored with the durable TODO, converted to `StageResult.next_steps`, and then executed by Pipeline. When a review-capable Stage exists, the plan must end each TODO with one. A crash after planning can resume from the saved TODO steps without asking the model to plan again.

The same reusable BaseStage can be invoked many times with different prompts:

```yaml
stages:
  run_prompt:
    status: Run prompt
    mode: write

  review:
    status: Review
    mode: readonly
    parser: review
    result_status: completed

  validate_file:
    type: python
    validator: file
    status: Validate
    result_handler: validation

flow:
  - stage: run_prompt
    prompt: prompts/step_a.md

  - stage: review
    prompt: prompts/review_a.md
    retry: 1
    skip: true

  - stage: run_prompt
    prompt: prompts/step_b.md

  - stage: review
    prompt: prompts/review_b.md
    skip: false

  - stage: run_prompt
    prompt: prompts/step_c.md

  - validate_file
```

`skip` is a compact alias for `skip_on_error`. `type: plan` identifies planning behavior; `type: python` identifies the Python validator; `type: base` may be written explicitly but is optional. `validator: file|ai` marks validation capability. `recover` contains static recovery Stage sequences, while `restart_at` remains FlowNode routing metadata. Dynamic planned work comes only from validated `PlanStage` `next_steps`; there is no `expand`/`foreach` YAML setting. `instructions_file` loads UTF-8 instructions relative to the Workflow YAML. Relative `prompt` paths first resolve beside the Workflow YAML when that file exists; otherwise they remain bundled prompt paths such as `stages/execution.md`. `retry` accepts `-1`, `0`, or a finite non-negative count. Final validation must remain last; when both validators exist, file validation must precede AI validation.

## Validation modes
- File validator: `--validator path/to/validation.py`.
- AI validator: `--validator ai` plus optional `--validator-prompt`.
- Mixed validation: use a file `--validator` plus `--ai-validator-prompt` or `--ai-validator-prompt-file`. The file validator is the hard gate; AI voting runs only after it passes, and both gates must pass.
- `--final-ai-validations` (alias `--ai-validator-count`) controls independent fresh-session votes. `--final-ai-required-passes 0` uses strict majority; a positive value explicitly sets the threshold.

Example: `--validator validation.py --ai-validator-prompt-file ai_validation.md --ai-validator-count 3` requires the Python validator plus at least 2 of 3 independent AI PASS votes.

## Session recovery
- Same Session is the normal first recovery path. It sends only new Stage/failure evidence and the next instruction.
- After the configured same-session retry budget (default 2), the Runner uses a Fresh Session with complete necessary context.
- Repeated identical failure after Fresh Session escalates to Replan; a different failure resets the streak.
- Final AI validation is different from normal recovery: every configured vote starts a different Fresh Session. A completed vote is retained while a later vote recovers from a model error; votes produced during an attempt rejected by safety hooks are discarded.
- Structured-output correction is bounded to at most two Same Session retries before configured Fresh fallback.

## JSON events / integration
`--json-events` emits JSON Lines. Python callers should use `runner.api.RunRequest` and `runner.api.run()`; this is the canonical integration surface for future UI/skills. Workflow uses a semantic progress facade and does not depend on raw event schema or concrete Plugin implementations.

## Backend arguments
Repeat `--agent-arg` per backend argv item. Use `--command` only to override the backend executable. `--sandbox` enables backend sandboxing when supported; Qwen receives `-s`. Full AI task prompts are always stdin-only. Qwen `/context` and `/compress-fast` are short backend control commands, not task prompts, and may use CLI control arguments.

## Protected paths from CLI
Repeat `--protect-file` for additional paths. Project policy is preferred for stable project-owned rules. If a readonly Stage attempts a write, Safety restores the change and the attempt is treated as a failure; same-session recovery sends only the new stage/failure delta.

## Debug
Inspect `<project-root>/.ai-task-runner/debug/current-prompt.txt`, `last-prompt.txt`, `last-result.txt`, and `debug/history/` when diagnosing AI behavior. Logs/events stay concise but retain Stage, session mode, retry/recovery, process exit, and validator evidence needed for 24H debugging. `log.txt` and `exception.log` rotate at 10 MB and retain one previous file; model-call history keeps its separate bounded policy.

## Timeout defaults
| Option | Default |
|---|---:|
| `--agent-timeout` | `7200` |
| `--planning-timeout` | `600` |
| `--agent-idle-after-change-timeout` | `900` |
| `--validator-timeout` | `1200` |

Resume does not require repeating `--goal` if compatible state already exists, but passing the same goal is fine. Transient API/network/rate-limit/service failures use a separate backoff window and do not consume the Stage failure budget.

## Canonical Python API
```python
from runner.api import RunRequest, run
```

## External command validator
If the real validator is an exe, bat, jar, or another CLI, use `docs/validator_templates/external_command_validator.py` as the Python wrapper. Pass the external command and log folders through repeated `--validator-arg` values. The wrapper captures stdout/stderr and copies matching log folders into `.ai-task-runner/validator-reports/external-command/`. Deterministic validators should verify observable requirements, not hidden Planner strategy or coding-style constraints absent from the Goal.

## Agent rule files
- Qwen Code: `QWEN.md`
- OpenCode: `AGENTS.md`

OpenCode's official project rule filename is `AGENTS.md`, not `AGENT.md`.

## UI-ready editing and Python Stage
Future UI/CLI integrations share `runner.api.run()` rather than calling Pipeline or StageExecutor directly. `stage_catalog()` exposes installed Stage types from their real `spec_class`; external Stage/backend registration uses `ai_task_runner.extensions`, while cross-cutting runtime Plugins use `ai_task_runner.plugins`.

Workflow and prompt editors must use `save_workflow()` / `save_prompt()` plus the `expected_hash` returned by `runner.resources.read_text()`. Saving validates first and atomically replaces the real source file. A running task uses the Workflow, Stage-prompt, Goal-file, and Final-AI-prompt snapshots stored in its own work directory, so source edits or deletion affect the next Run, not the active/resumed Run.

A user Python step is declared as `type: python` with `path` and optional `args`. It runs in a subprocess and participates in the normal StageExecutor Hook/change/recovery boundary without importing project Python into the long-running Runner process.


## OpenCode runtime contract

OpenCode sends complete AI task prompts through stdin just like Qwen; prompts are never placed in argv. Resume uses the official `--session` flag and non-interactive calls add `--auto`. Planning/no-tool/review capability is enforced by backend-owned runtime `permission` overrides through `OPENCODE_CONFIG_CONTENT`. `--sandbox` additionally denies `external_directory`. OpenCode currently has no Qwen `-s` container-sandbox equivalent, so this is permission-based confinement; Runner protected-path, Git guard, and readonly restoration remain the shared hard guards.
