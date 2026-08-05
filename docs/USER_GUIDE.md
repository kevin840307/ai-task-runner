# AI Task Runner User Guide v1.1.1

## Basic Command

```bat
python ai_task_runner.py ^
  --project-root C:\work\project ^
  --goal "完成需求並通過驗證" ^
  --validator C:\validators\validator.py
```

By default this uses Qwen Code through `qwen.cmd` and runs as an unlimited retry/cycle 24h-style loop. Add `--resume` when restarting an existing run after the Python process exited.
Qwen runtime calls also get `--max-tool-calls 40` unless you provide your own value with `--agent-arg=--max-tool-calls --agent-arg <N>`.

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
from runner import RunRequest, run

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
| `--agent-idle-after-change-timeout` | `900` | AI model-call watchdog. Execution uses CLI output until the first project change, then project changes; read-only calls retry when CLI output goes idle. `0` disables it. |
| `--validator-timeout` | `1200` | Maximum seconds for a Python validator subprocess. |

For slow local models, the default `7200` second hard timeout is intentionally high. Keep the idle watchdog enabled so a read-only call that produces no CLI output, or an execution call that keeps talking after it stopped changing files, can be retried or handed to review/final validation.

## What Retries

The runner retries model errors, Qwen loop detection, session unavailable, invalid review JSON, protected-file edits, review failure, validator failure, timeouts, and no-progress attempts. With a Python validator, repeated no-change model-stage failures on one TODO are deferred to final validation instead of blocking the entire run. Final Validator must PASS before the run is marked completed.

Planning gives the model the goal, project outline, progress, and compact retry feedback. The model extracts concrete deliverables, splits work to match actual complexity, and returns task JSON. If planning does not return valid JSON, the runner retries planning with compact feedback until the model returns the fixed task schema. Python does not split user prompts by Markdown, numbering, paragraphs, punctuation, or language-specific keywords.

## Validators

Use a Python validator:

```bat
python ai_task_runner.py --goal "Build X" --validator C:\validators\validator.py
```

Or use AI validation:

```bat
python ai_task_runner.py --goal "Build X" --validator ai
```

AI validation is useful when there is no Python validator yet. It runs in a fresh independent agent session, asks the agent to inspect files and run reasonable local checks, and expects JSON with `passed`, `reason`, `missing_items`, `checks_run`, and `suggested_checks`. If it fails, `missing_items` become focused repair feedback for the next cycle. This is weaker than a Python validator, but better than relying only on per-task review.

Python validators have no required output format. They receive:

```text
python validator.py --project-root <root> --state-file <state.json> [...validator args]
```

Agents may read validator files and expected/reference/golden fixtures to infer expected behavior, but they must not edit validator files, read-only answer fixtures, runner state, runner source, or backend rule files. Protected changes are restored and retried when they touch runner-owned files. Add `--protect-file <path>` for read-only expected files or folders that the model may inspect but must not modify.

Exit code `0` means PASS. Any non-zero exit code means FAIL. Stdout and stderr are captured as feedback; state keeps a bounded 20,000-character version that preserves the beginning and end of long logs, and task prompts receive a smaller focused excerpt.

For reusable validator patterns, see `docs/validator_templates/`. The folder comparison template is useful when a project generates many `.yml`, `.yaml`, `.cfg`, and `.xml` files: it prints a short summary, writes full file lists and diffs under `.ai-task-runner/validator-reports/`, and adds a warning-only config value sharing score.

If the real validator is an exe, bat, jar, or another CLI, use `docs/validator_templates/external_command_validator.py` as a Python wrapper. Pass the external command with repeated `--validator-arg --command ...` values and pass any external log folders with `--validator-arg --log-dir ...`. The wrapper captures stdout/stderr, copies matching log files into `.ai-task-runner/validator-reports/external-command/`, and prints compact paths so the agent knows which reports to read.

Example:

```bat
python ai_task_runner.py ^
  --project-root C:\work\project ^
  --goal-file C:\work\project\prompt.md ^
  --validator C:\Users\kevin\ai-task-runner\docs\validator_templates\external_command_validator.py ^
  --validator-arg --command --validator-arg C:\validators\check.exe ^
  --validator-arg --log-dir --validator-arg C:\validators\logs
```

Optional helper install:

```bat
python -m pip install -e C:\Users\kevin\ai-task-runner
```

After that, validators in any project can use `from ai_task_runner_validator import ValidatorReport`. Without installing, copy `docs/validator_templates/validator_interface.py` next to the validator.

`<project-root>/.ai-task-runner/validator-reports/` is cleared before every Python validator run. Write detailed reports there when stdout would be too large; the next repair task will receive the validator stdout and can read the referenced latest report files.

`<project-root>/.ai-task-runner/log.txt` stores runner progress and status events as JSON lines. It is useful when checking why an unattended run retried, changed cycles, or stopped.

For large reports, keep stdout focused on the model-facing summary: status, error/warning counts, `report_dir`, and the first few actionable errors. Put detailed diffs or long command output in files. When feedback references `report_dir` or `Full report:`, prompts instruct the agent to read `summary.txt`, then `errors.txt`, then only the first relevant detailed report before making a repair.

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

## Review error tolerance

`--review-error-retries N` controls only Review infrastructure/format errors. Every Review attempt uses a fresh independent session and each error increments persisted counters. Review PASS completes the TODO; an explicit Review FAIL always returns actionable `missing_items` to execution. In default mode, after N consecutive errors a TODO with accumulated project changes may be provisionally completed. `--strict-review` disables this skip. Final validation is always required.


## Independent Final AI validation

Use `--validator ai` together with:

```text
--final-ai-validations N
--final-ai-required-passes M
```

Each of the N validation attempts starts with a new session and independently reads the current project. `M` must be between 1 and N. Example: `N=3, M=2` accepts two PASS results plus one validator error, but any explicit FAIL blocks completion and starts a repair cycle.
