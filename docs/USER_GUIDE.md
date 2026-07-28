# AI Task Runner User Guide v1.1.1

## Basic Command

```bat
python ai_task_runner.py ^
  --project-root C:\work\project ^
  --goal "完成需求並通過驗證" ^
  --validator C:\validators\validator.py
```

By default this uses Qwen Code through `qwen.cmd` and runs as an unlimited retry/cycle 24h-style loop. Add `--resume` when restarting an existing run after the Python process exited.

Resume does not require repeating `--goal` if the state already exists, but passing the same goal is fine.

Override defaults only when needed, for example `--command qwen` on non-Windows shells or `--backend opencode --command opencode.exe` for OpenCode.

Use `--goal-file` for long requirements:

```bat
python ai_task_runner.py ^
  --project-root C:\work\project ^
  --goal-file C:\work\requirements.md ^
  --validator C:\validators\validator.py
```

`--goal` and `--goal-file` are mutually exclusive. The file is read as UTF-8 text and stored in runner state as the goal.

## Python API

```python
from runner_api import RunRequest, run

result = run(RunRequest(
    goal="Build the requested feature",
    validator="ai",
    project_root=".",
))
```

## Timeouts

| Option | Default | Meaning |
| --- | ---: | --- |
| `--agent-timeout` | `7200` | Maximum seconds for one execution, review, or AI-validator model call. |
| `--planning-timeout` | `600` | Maximum seconds for one planning model call. |
| `--agent-idle-after-change-timeout` | `900` | Execution-only activity watchdog; CLI output or project file changes refresh it, `0` disables it. |
| `--validator-timeout` | `1200` | Maximum seconds for a Python validator subprocess. |

For slow local models, the default `7200` second hard timeout is intentionally high. Keep the idle watchdog enabled so a call that produces no CLI output and stops changing files can be handed to review.

## What Retries

The runner retries model errors, Qwen loop detection, session unavailable, invalid review JSON, protected-file edits, review failure, validator failure, timeouts, and no-progress attempts. With a Python validator, repeated no-change model-stage failures on one TODO are deferred to final validation instead of blocking the entire run. Final Validator must PASS before the run is marked completed.

## Validators

Use a Python validator:

```bat
python ai_task_runner.py --goal "Build X" --validator C:\validators\validator.py
```

Or use AI validation:

```bat
python ai_task_runner.py --goal "Build X" --validator ai
```

Python validators have no required output format. They receive:

```text
python validator.py --project-root <root> --state-file <state.json> [...validator args]
```

Agents may read validator files to infer expected behavior, but they must not edit validator files, runner state, runner source, or backend rule files. Protected changes are restored and retried.

Exit code `0` means PASS. Any non-zero exit code means FAIL. Stdout and stderr are captured as feedback; state keeps a bounded 20,000-character version that preserves the beginning and end of long logs, and task prompts receive a smaller focused excerpt.

For reusable validator patterns, see `docs/validator_templates/`. The folder comparison template is useful when a project generates many `.yml`, `.yaml`, `.cfg`, and `.xml` files: it prints a short summary, writes full file lists and diffs under `.ai-task-runner/validator-reports/`, and adds a warning-only config value sharing score.

`<project-root>/.ai-task-runner/validator-reports/` is cleared before every Python validator run. Write detailed reports there when stdout would be too large; the next repair task will receive the validator stdout and can read the referenced latest report files.

## YAML Batch

```yaml
- prompt: Build the first feature
  validator: validators/first.py
- prompt: Build the second feature
  validator: ai
```

YAML batch mode is supported. Each item has independent state under `.ai-task-runner/script/NNN/state.json`. With `--resume`, completed items are skipped and unfinished items continue from their saved state.

## Backend Rule Files

- Qwen Code: `QWEN.md`
- OpenCode: `AGENTS.md`

OpenCode's official project rule filename is `AGENTS.md`, not `AGENT.md`.

## Troubleshooting

- If the model made files but timed out, the runner asks review to judge the saved files.
- If review repeatedly fails for a Python-validator run after project changes, the runner can defer judgment to the final Python validator.
- If validator feedback is ambiguous, improve the validator message with expected and actual values.
- If a local model is very slow, raise `--agent-timeout`; do not disable final validation.
