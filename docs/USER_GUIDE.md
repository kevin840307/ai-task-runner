# User Guide

Version: 1.2.5

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
`--script tasks.yaml` runs a YAML array sequentially. Each item requires exactly one of `prompt`/`goal` or `goal_file`, plus `validator`. `goal_file` and `ai_validator_prompt_file` are UTF-8; relative paths are resolved from the YAML file directory. Optional fields include `validator_prompt`, either `ai_validator_prompt` or `ai_validator_prompt_file`, `ai_validator_count`, `ai_validator_required_passes`, and `project_root`. Relative per-item `project_root` values are resolved from the outer `--project-root`; omitting it preserves the existing shared-root behavior. Each script item gets an isolated work-dir state under `.ai-task-runner/script/<index>`.

```yaml
- goal_file: prompts/example-a.md
  project_root: projects/example-a
  validator: validation.py
  ai_validator_prompt_file: ai_validation.md
  ai_validator_count: 3
```

## Validation modes
- File validator: `--validator path/to/validation.py`.
- AI validator: `--validator ai` plus optional `--validator-prompt`.
- Mixed validation: use a file `--validator` plus `--ai-validator-prompt` or `--ai-validator-prompt-file`. The file validator is the hard gate; AI voting runs only after it passes, and both gates must pass.
- `--final-ai-validations` (alias `--ai-validator-count`) controls independent fresh-session votes. `--final-ai-required-passes 0` uses strict majority; a positive value explicitly sets the threshold.

Example: `--validator validation.py --ai-validator-prompt-file ai_validation.md --ai-validator-count 3` requires the Python validator plus at least 2 of 3 independent AI PASS votes.

## JSON events / integration
`--json-events` emits JSON Lines. Python callers should use `runner.api.RunRequest` and `runner.api.run()`; this is the canonical integration surface for future UI/skills.

## Backend arguments
Repeat `--agent-arg` per backend argv item. Use `--command` only to override the backend executable. Qwen full prompts are always stdin-only.

## Protected paths from CLI
Repeat `--protect-file` for additional paths. Project policy is preferred for stable project-owned rules.

## Debug
Inspect `<project-root>/.ai-task-runner/debug/current-prompt.txt`, `last-prompt.txt`, `last-result.txt`, and `debug/history/` when diagnosing model behavior.

## Timeout defaults
| Option | Default |
|---|---:|
| `--agent-timeout` | `7200` |
| `--planning-timeout` | `600` |
| `--agent-idle-after-change-timeout` | `900` |
| `--validator-timeout` | `1200` |

Resume does not require repeating `--goal` if compatible state already exists, but passing the same goal is fine.

## Canonical Python API
```python
from runner import RunRequest, run
```

## External command validator
If the real validator is an exe, bat, jar, or another CLI, use `docs/validator_templates/external_command_validator.py` as the Python wrapper. Pass the external command and log folders through repeated `--validator-arg` values. The wrapper captures stdout/stderr and copies matching log folders into `.ai-task-runner/validator-reports/external-command/`.

## Agent rule files
- Qwen Code: `QWEN.md`
- OpenCode: `AGENTS.md`

OpenCode's official project rule filename is `AGENTS.md`, not `AGENT.md`.
