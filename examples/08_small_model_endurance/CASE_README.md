# Small-Model Endurance Case

This case tests whether a small local model can understand one medium-sized
specification, split it into coherent Tasks, complete those Tasks over a long
run, recover from its own natural mistakes, and converge under a deterministic
validator. It does not inject artificial failures and does not need to run for
exactly 24 hours.

## Recommended sequence

From this directory:

```bat
run_plan_only.cmd
```

This creates the plan without implementation and runs `audit_plan.py`. Review:

- requirement coverage (`R01` through `R18`)
- duplicate Task titles
- Tasks containing too many requirement IDs
- Tasks with no requirement ID

Then continue the same run:

```bat
run_full.cmd
```

The launcher uses `--resume` when state already exists. The final deterministic
validator runs automatically. After completion it runs both the validator and
plan audit once more so the final result is visible even when terminal UI output
was long.

## What counts as a useful result

A strong plan normally has multiple coherent Tasks, complete R01–R18 coverage,
no duplicate titles, and no single Task that owns most of the specification.
Task count alone is not a pass/fail rule.

A strong execution result has:

- `completed: true` in `.ai-task-runner/state.json`
- validator exit code `0`
- all project unit tests passing
- finite retry attempts that eventually converge
- no manual edits to implementation files

The run may take minutes or hours depending on model size and context speed.
That is intentional: the case measures decomposition and sustained execution,
not wall-clock duration.

## Reset

```bat
reset_case.cmd
```

This removes generated implementation and runner state, but keeps the case
specification, validator, audit script, and launchers.
