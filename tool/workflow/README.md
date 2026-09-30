# Workflow Tool Examples

These YAML files are deterministic examples for the current Workflow runtime. They are also used by dry-run/live reliability preflight.

## Examples

- `01_default_ai.yaml` — Plan -> Task -> Review -> Final AI Validator.
- `02_ai_with_review_gate.yaml` — adds an independent fresh Review gate before final validation.
- `03_file_validation.yaml` — Task flow plus a command/File Validator.
- `04_mixed_with_review_gate.yaml` — independent Review + File Validator + Final AI Validator.
- `05_review_vote_3_choose_2.yaml` — three fresh Review runs, 2/3 required to pass.
- `06_custom_task_producer.yaml` — command-backed custom Task producer; PlanStage is not required.
- `11_multi_validators_anywhere.yaml` — validators and ordinary Stages interleaved to prove validation is not terminal-only.

## Current Workflow contract

A Workflow is only Stages plus semantic result routing:

```yaml
stages:
  execute:
    type: task
    routes:
      fail: execute

  verify:
    type: review
    session_policy: fresh
    routes:
      fail: execute

flow:
  - execute
  - verify
```

Only `routes.pass` and `routes.fail` are graph edges. Technical exceptions/timeouts/API failures are owned by `StageExecutor` and use `error_policy.retries` or the global `stage_retries`; there is no `routes.error`, repair Stage, recover edge, restart_at, repeat, max_attempts, or on_exhausted graph contract.

Dynamic Handoff uses one Handoff Stage with multiple allowed targets:

```yaml
coordinator:
  type: handoff
  targets: [implementer, verifier, final_validate]
```

The Handoff Stage chooses exactly one target per decision. Target roles remain ordinary Stages.

## Session policy

AI-backed Stages may use:

- `session_policy: role` — durable reusable Session owned by that Stage name; default for Dynamic specialist roles.
- `session_policy: main` — share the Runner primary Session.
- `session_policy: fresh` — start a new Session for every invocation; recommended for independent final validation.
- `session_policy: auto` — internal/default Stage behavior. `session_key` is valid only with `auto`.

If a reusable role Session repeatedly fails technically, StageExecutor may rotate only that Stage to a fresh Session and persist the new Session after recovery.

## Validation and testing

Run one workflow deterministically:

```powershell
python tool/workflow_dryrun.py tool/workflow/11_multi_validators_anywhere.yaml --matrix --json
```

The real-Qwen reliability tool runs representative dry-run preflight before live model probes:

```powershell
tool\qwen_live_reliability_0_5h.bat
```

Use `tool\qwen_live_reliability_24h.bat` only after the short live gate passes.
