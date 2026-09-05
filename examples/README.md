# Examples

Run all examples in order on Windows:

```bat
examples\run_examples.bat
```

Pass normal Runner options through the BAT, for example `examples\run_examples.bat --backend qwen --resume`.

Every BAT launcher copies only the selected example into a fresh workspace under `<repo>\.example_runs\...`; `--all` copies the examples set only. Runner source stays in the original repository, and the canonical `examples/` tree is never used as the writable project. The temporary workspace path is printed before and after execution and is kept for debugging; rerunning always creates a new clean copy.
Set `AI_TASK_RUNNER_EXAMPLE_TEMP` to override the base directory; otherwise `.example_runs/` under the repository root is used.

Run one example directly, for example:

```bat
examples\01_basic_command_validator\run_example.bat --backend qwen
examples\11_regression_workflow_demo\run_example.bat --backend qwen
```

The suite is intentionally small and diagnostic:

1. `01_basic_command_validator` — baseline Python hard validation.
2. `02_repair_cycle` — starter bug intended to exercise Validator FAIL → repair.
3. `03_ai_validator_voting` — AI-only final validation with 3 independent fresh-session votes.
4. `04_mixed_validation` — Python hard gate plus AI semantic majority vote.
5. `05_ai_quality_repair` — hard behavior checks plus an AI genericity/quality gate.
6. `06_yaml_driven_tool` — a small application that consumes YAML; the outer `examples.yaml` simultaneously exercises Runner YAML batch mode.
7. `07_blackbox_medium` — medium task whose validator inspects only CLI outputs, never implementation structure.
8. `08_config_driven_data_pipeline` — mixed-validation data pipeline with black-box behavioral checks.
9. `09_config_environment_auditor` — mixed-validation config auditor covering multiple file formats and clean reruns.
10. `10_skill_prompt_review_workflow` — runnable custom workflow example that reuses one prompt Stage for `/skill...` prompts, review gates, and a final file validator.
11. `11_regression_workflow_demo` — six-action Regression workflow with shared Review/Grill/Fix skills, bounded recovery feedback, continuation prompts, and 5-agent fresh-session final validation.

Each YAML item has its own `project_root`. Relative item roots are resolved against the outer `--project-root`. Each project keeps `prompt.md`, Python `validation.py`, and optional `ai_validation.md` inside its root but lists them in `.ai-task-runner.yaml` `protected_paths`; the policy file itself is automatically protected. `examples.yaml` references the prompt and AI validation files through `goal_file` and `ai_validator_prompt_file`.
All Python example validators use the shared `ai_task_runner_validator.ValidatorReport` contract. Functional failures are reported through `ValidatorReport.error()`, JSON outputs use `parse_json()` where applicable, and full reports are written under each project's `.ai-task-runner/validator-reports/`.

Workflow schema examples live in the folder that owns them. `workflow_multi_prompt.yaml` is the original compact multi-prompt example. The Qwen live reliability custom workflow lives at `../tool/workflows/skill_prompt_review_chain.yaml`; `10_skill_prompt_review_workflow` runs that workflow against a real project and validator.

Validation-mode workflow example: `validation_modes.yaml` shows the automatic built-in mapping:

- Python file validator only selects `runner/workflow/builtin/file.yaml`.
- `validator: ai` selects `runner/workflow/builtin/ai.yaml`.
- Python file validator plus `ai_validator_prompt` or `ai_validator_prompt_file` selects `runner/workflow/builtin/mixed.yaml`.

## Current custom Workflow examples

Use the current semantic Stage types instead of older low-level fields such as `run_state`, `actor`, `mode`, `result_handler`, or `retry_attr` unless a real override is required.

- `workflow_multi_prompt.yaml`: reuses `type: task` and `type: review` with different prompts.
- `custom_workflow_latest.yaml`: latest generic custom Workflow. A a `command` Stage produces `Task[]`, the task-scoped SOP executes/reviews them, and a final `command` Stage runs without requiring Plan or a Validator.
- `custom_task_producer.py`: Task JSON producer used by the custom Workflow.
- `../tool/workflows/skill_prompt_review_chain.yaml`: real multi-prompt + Review + File Validator workflow.

For the full contract and more examples, see `docs/user/CUSTOM_WORKFLOW.md`.
