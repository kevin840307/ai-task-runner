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
| `--agent-idle-after-change-timeout` | `900` | Execution-only activity watchdog after project changes or CLI output; `0` disables it. |
| `--validator-timeout` | `1200` | Maximum seconds for a Python validator subprocess. |

For slow local models, the default `7200` second hard timeout is intentionally high. Keep the idle watchdog enabled so a call that stops producing CLI output and stops changing files can be handed to review.

## What Retries

The runner retries model errors, Qwen loop detection, session unavailable, invalid review JSON, protected-file edits, review failure, validator failure, timeouts, and no-progress attempts. Final Validator must PASS before the run is marked completed.

## Validators

Use a Python validator:

```bat
python ai_task_runner.py --goal "Build X" --validator C:\validators\validator.py
```

Or use AI validation:

```bat
python ai_task_runner.py --goal "Build X" --validator ai
```

Python validators receive:

```text
python validator.py --project-root <root> --state-file <state.json> [...validator args]
```

Agents may read validator files to infer expected behavior, but they must not edit validator files, runner state, runner source, or backend rule files. Protected changes are restored and retried.

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
