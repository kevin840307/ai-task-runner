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
8. `08_config_driven_data_pipeline` — mixed-validation data pipeline with black-box behavioral checks.
9. `09_config_environment_auditor` — mixed-validation config auditor covering multiple file formats and clean reruns.

Each YAML item has its own `project_root`. Relative item roots are resolved against the outer `--project-root`. Each project keeps `prompt.md`, Python `validation.py`, and optional `ai_validation.md` inside its root but lists them in `.ai-task-runner.yaml` `protected_paths`; the policy file itself is automatically protected. `examples.yaml` references the prompt and AI validation files through `goal_file` and `ai_validator_prompt_file`.
All Python example validators use the shared `ai_task_runner_validator.ValidatorReport` contract. Functional failures are reported through `ValidatorReport.error()`, JSON outputs use `parse_json()` where applicable, and full reports are written under each project's `.ai-task-runner/validator-reports/`.

Workflow schema examples live under `workflows/`. `workflows/skill_prompt_review_chain.yaml` shows one reusable prompt Stage combined with prompts that begin with user-authored `/skill...` directives and reusable Review invocations, while `workflow_multi_prompt.yaml` is kept as the original compact multi-prompt example.

Validation-mode workflow example: `validation_modes.yaml` shows the automatic built-in mapping:

- Python file validator only selects `runner/workflow/builtin/file.yaml`.
- `validator: ai` selects `runner/workflow/builtin/ai.yaml`.
- Python file validator plus `ai_validator_prompt` or `ai_validator_prompt_file` selects `runner/workflow/builtin/mixed.yaml`.
