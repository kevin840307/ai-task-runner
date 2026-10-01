# User Guide

## Run one task

Use CLI, API, UI or YAML List; all paths execute the same Workflow runtime.

Typical CLI:

```powershell
python ai_task_runner.py --goal-file prompt.md --project-root . --validator ai
```

Select a Workflow with `--workflow` when needed. Workflow YAML, not a separate execution-mode flag, selects Linear or Dynamic Handoff behavior.

## Runtime model

A Workflow is a list of Stages.

- PASS normally advances to the next Stage.
- FAIL normally stops unless `routes.fail` points somewhere else.
- PASS/FAIL may route backward to implement rollback/loop.
- ERROR is technical failure only; StageExecutor retries/rebuilds the Session. Review with a finite local `error_policy.retries` is fail-soft and skips to the next Stage after exhaustion; other Stage types stop at the current Stage when a finite retry policy is exhausted.
- There is no repair/recover/restart_at/repeat/max_attempts/on_exhausted graph model.

## Plan and task scope

`type: plan` produces Task[]. Per-task work is explicit YAML using one contiguous `scope: task` block:

```yaml
stages:
  planning:
    type: plan

  execute:
    type: task
    scope: task

  review:
    type: review
    scope: task
    routes:
      fail: execute

flow: [planning, execute, review]
```

A custom `command` or Python Stage can use `produces: tasks`, so PlanStage is not mandatory.

## Validation

File validation is normally a `command` Stage with `result_kind: validation`. AI validation uses `type: ai_validator`, `validator: ai`.

Validators are ordinary top-level Stages and can appear before or after other Stages. They cannot use `scope: task`.

Independent final AI validation should normally use:

```yaml
session_policy: fresh
```

Multiple runs/voting:

```yaml
runs: 3
required_passes: 2
```

## Dynamic Handoff

Dynamic Handoff is the only multi-agent runtime primitive.

```yaml
coordinator:
  type: handoff
  targets: [requirements, architect, implementer, verifier, final_validate]
  session_policy: role
```

The coordinator chooses exactly one target per decision. Specialist roles remain ordinary Stages and typically route PASS back to the coordinator.

Built-in Dynamic specialists default to `session_policy: role`; final validation is `fresh`.

### Session policies

- `role`: one durable reusable Session per Stage name; survives process resume.
- `main`: use the primary Runner Session.
- `fresh`: clear/start a Session every invocation.
- `auto`: built-in/internal default behavior; only `auto` can use `session_key`.

If a role Session repeatedly fails technically, StageExecutor may rotate only that role to a new Session. Other role Sessions remain untouched.

## Retry and technical failure

Global default:

```text
stage_retries = -1
retry_delay = 5
retry_max_delay = 300
```

A Stage may override only the retry count:

```yaml
error_policy:
  retries: 2   # Review: retry twice, then fail-soft Skip to next Stage
```

HTTP 429/502/503 and other classified transient backend errors use delay/backoff without moving graph position.

## YAML List

`--script tasks.yaml` runs multiple items sequentially. Each child keeps durable state under its own script child work directory and uses the same WorkflowRunner/FlowEngine/StageExecutor/StateStore runtime.

Per-item overrides may include Workflow selection, backend/agent/validator args, project root, timeouts, retry settings, max_cycles/skip_on_max_cycles and final-AI quorum. Batch ownership options such as resume/work-dir remain outer-run concerns.

## max_cycles

`max_cycles` bounds semantic backward graph cycles. `-1` means unlimited. In YAML List, `skip_on_max_cycles` may allow the batch to continue to the next item after a child reaches the cycle limit.

Dynamic role -> coordinator returns are backward graph routes, so a finite `max_cycles` also bounds how many Handoff loops can occur. Leave it `-1` for intentionally open-ended Dynamic work.

## Read-only safety

Read-only Stages such as Review/validation can use `readonly_safety: observe`. Safety/change tracking is owned by StageExecutor/hooks, not by routing.

## Protected files

Use project policy and/or `--protect-file` for paths that AI work must not modify. Runtime technical artifacts under known cache/build/test-output locations are filtered separately from real source/project files.

## Resume and diagnostics

Committed progress is stored in `.ai-task-runner` runtime state. Resume restores workflow position, task position, previous transition evidence, primary Session ID and durable role Session IDs.

Useful diagnostics include:

- runtime state;
- Runner events/log;
- `stream.log` for current subprocess output;
- `debug/current-prompt.txt`;
- `debug/last-prompt.txt`;
- `debug/last-result.txt`;
- bounded debug history.

## Workflow Studio

Studio edits the same YAML. Full Designer supports PASS/FAIL/Handoff edges, Stage parameters, Dynamic target layout and single-Stage Test.

ERROR is not an edge. Session policy is edited as `auto/main/role/fresh`; Studio prevents conflicting `session_key` combinations.

## Deterministic and live testing

Deterministic:

```powershell
python -m pytest -q
python tool/workflow_dryrun.py runner/assets/workflows/dynamic_handoff.yaml --matrix --json
```

Short real-Qwen gate:

```powershell
tool\qwen_live_reliability_0_5h.bat
```

Full acceptance after the short gate:

```powershell
tool\qwen_live_reliability_24h.bat
```

A green deterministic CI does not prove the real backend or 24H soak.
