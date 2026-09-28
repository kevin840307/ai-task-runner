# Workflow examples

These YAML files are small reference graphs for the current Runner contract.

Available examples:

- `01_default_ai.yaml` — Planning -> task-scoped Execute/Review -> AI validation.
- `02_ai_with_grill.yaml` — adds one whole-result Review/Grill gate.
- `03_file_validation.yaml` — deterministic File Validator.
- `04_mixed_with_grill.yaml` — Grill + File Validator + Final AI Validator.
- `05_grill_vote_3_choose_2.yaml` — three fresh Grill sessions, 2/3 required to pass.
- `06_custom_task_producer.yaml` — Command produces Task[]; explicit task-scoped Execute/Review.
- `11_multi_validators_anywhere.yaml` — several validation gates interleaved with ordinary Stages.

## Graph rule

One `stages.<name>` entry is one node. `flow` is only the ordered list of Stage names.

Rollback/loop is a normal result edge:

```yaml
stages:
  work:
    type: task
    scope: task

  review:
    type: review
    scope: task
    routes:
      fail: work

flow:
  - work
  - review
```

Use only `routes.pass`, `routes.fail`, and `routes.error`. Technical retry/session recovery is global Runner behavior and must not be expressed in Workflow YAML.

## Grill

Grill is not a new Stage type. It reuses `type: review`:

```yaml
grill:
  type: review
  prompt: ../../runner/workflows/grill.md
  fresh_session_on_start: true
  routes:
    fail: planning
```

If several independent opinions are required, use the ordinary Stage voting fields:

```yaml
runs: 3
required_passes: 2
fresh_session_each_run: true
```

## Task producers

`plan` is the built-in Task producer. A custom Stage can also return Task[] with:

```yaml
produces: tasks
```

The per-task SOP must then be explicit contiguous `scope: task` nodes. There are no hidden Task/Review/Repair Stages.

## Validators

`result_kind: validation` Command Stages and `type: ai_validator` are ordinary graph nodes. Any semantic FAIL loop is an explicit `routes.fail` edge.
