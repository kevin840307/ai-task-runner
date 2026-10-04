# Workflow Tool Examples

These YAML files are deterministic examples for the current Workflow runtime and are used by dry-run/live reliability preflight.

## Examples

- `01_default_ai.yaml` — Plan dynamically expands its own Execute -> Review child Workflow, then Final AI Validator.
- `02_ai_with_review_gate.yaml` — Plan children, then an independent fresh AI Review profile and final validation.
- `03_file_validation.yaml` — Plan children, then a command/File Validator.
- `04_mixed_with_review_gate.yaml` — Plan children + independent Review + File Validator + Final AI Validator.
- `05_review_vote_3_choose_2.yaml` — three fresh AI Review profile runs, 2/3 required to pass.
- `06_custom_task_producer.yaml` — command-backed custom Task producer whose script defines both Tasks and child Stages.
- `11_multi_validators_anywhere.yaml` — validators and ordinary Stages interleaved.

## Current Workflow contract

General AI behavior uses `type: base` with a profile:

```yaml
stages:
  execute:
    type: base
    profile: execute

  verify:
    type: base
    profile: review
    session_policy: fresh
    routes:
      fail: execute

flow:
  - execute
  - verify
```

The old `type: task`, `type: review`, and `scope` contracts are removed.

Only `routes.pass` and `routes.fail` are semantic graph edges. Technical exceptions/timeouts/API failures are owned by `StageExecutor` in `runner/workflow/execution/stage_executor.py` and use `error_policy.retries` or the global `stage_retries`.

## Dynamic child Workflows

Any producer may return `tasks` or `stages`, but the producer must provide the child Stage definitions. Runner validates, namespaces, persists, and executes those children before continuing the parent Workflow; it never infers child structure.

PlanStage currently owns the fixed Task pattern:

```text
Execute -> Review -> Execute -> Review -> ...
```

The custom producer example demonstrates that another producer can define its own child graph.

## Dynamic Handoff

```yaml
coordinator:
  type: handoff
  targets: [implementer, verifier, final_validate]
```

Each Handoff decision selects exactly one allowed target.

## Validation and testing

```powershell
python tool/workflow_dryrun.py tool/workflow/11_multi_validators_anywhere.yaml --matrix --json
tool\qwen_live_reliability_0_5h.bat
```

Run `tool\qwen_live_reliability_24h.bat` only after the short live gate passes.
