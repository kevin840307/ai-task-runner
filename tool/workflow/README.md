# Workflow examples

These files are reference YAMLs, not system workflows. Copy one into your custom workflow area and adjust only what the task needs.

- `01_default_ai.yaml` - general autonomous Plan -> per-TODO Execute/Review -> final AI validation.
- `02_ai_with_grill.yaml` - adds one independent whole-result Grill before final AI validation.
- `03_file_validation.yaml` - deterministic Python/file validator.
- `04_mixed_with_grill.yaml` - Grill + Python/file validation + final AI validation.
- `05_grill_vote_3_choose_2.yaml` - three fresh Grill sessions, 2/3 required to pass.
- `06_custom_task_producer.yaml` - custom command produces Task[] and uses explicit task-scoped stages.
- `07_minimal_plan_only.yaml` - minimal Plan workflow without a final validator.

## Generic Grill

Grill is intentionally not a new Stage type. It reuses `type: review`, the existing review parser, structured output contract, and recovery feedback pipeline.

```yaml
grill:
  type: review
  prompt: ../../runner/prompts/stages/grill.md
  fresh_session_on_start: true
  retry: 0
  recover: [repair_plan]
```

`fresh_session_on_start` makes every routed Grill invocation independent. `retry: 0` makes a technical Stage error rotate to a fresh session instead of retrying the same session first. A semantic FAIL still follows `recover`, and the existing review `missing_items` are delivered to recovery. PASS continues to the next flow node.
