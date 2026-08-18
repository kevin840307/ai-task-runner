# Examples

Run all examples in order on Windows:

```bat
examples\run_examples.bat
```

Pass normal Runner options through the BAT, for example `examples\run_examples.bat --backend qwen --resume`.

The suite is intentionally small and diagnostic:

1. `01_basic_python_validator` — baseline Python hard validation.
2. `02_repair_cycle` — starter bug intended to exercise Validator FAIL → repair.
3. `03_ai_validator_voting` — AI-only final validation with 3 independent fresh-session votes.
4. `04_mixed_validation` — Python hard gate plus AI semantic majority vote.
5. `05_ai_quality_repair` — hard behavior checks plus an AI genericity/quality gate.
6. `06_yaml_driven_tool` — a small application that consumes YAML; the outer `examples.yaml` simultaneously exercises Runner YAML batch mode.
7. `07_blackbox_medium` — medium task whose validator inspects only CLI outputs, never implementation structure.

Each YAML item has its own `project_root`. Relative item roots are resolved against the outer `--project-root`. The validators and prompts live outside each writable project root; `examples.yaml` references each `prompt.md` through `goal_file`.
