# AI Task Runner Design v1.1.1

## Responsibilities

The agent writes project code and documents. The runner owns orchestration:

- planning TODO tasks
- executing one task at a time
- read-only review
- final validator execution
- retry and resume
- protected-file restore
- process control and activity watchdogs

## Core Modules

```text
ai_task_runner.py        CLI parser and execute() entry
runner/                  Main implementation package
runner/defaults.py       Shared 24h default values
runner/api.py            Public API and RunRequest validation
runner/core.py           TaskRunner state machine and retry orchestration
runner/agent_args.py     Backend-specific planning/runtime argument policy
runner/script_runner.py  YAML batch orchestration and per-item resume setup
runner/planning.py       TODO derivation, fallback splitting, repair task planning
runner/validation.py     Python/AI final validator execution and AI failure feedback
runner/prompting.py      Prompt template loading and prompt builders
runner/ui.py             Live terminal UI and JSON progress events
runner/support.py        Parsers, protection, retry, validator subprocess utilities
runner/models.py         Task and RunState serialization
runner/agent.py          AgentClient session facade
runner/process_control.py  Subprocess output reader, timeout, process-tree kill
runner/backends/base.py    Backend interface
runner/backends/qwen.py    Qwen stream-json command/result/error parsing
runner/backends/opencode.py OpenCode command/result parsing
prompts/                   Editable prompt templates
```

## State Machine

```text
planning -> executing -> reviewing -> validating
                         ^             |
                         |             v
                     retry task <- validator_failed
```

Final Validator PASS sets `completed=true`. Validator FAIL stores `validator_output`, increments the cycle, and creates focused repair task(s).

## Process Control

`process_control.py` starts each AI CLI or validator as a subprocess, captures stdout/stderr incrementally, and kills the child process tree on timeout. Qwen uses `stream-json`, so CLI output is also an activity signal.

Execution has two limits:

- hard timeout: `--agent-timeout`, default `7200`
- activity idle watchdog: `--agent-idle-after-change-timeout`, default `900`

The idle watchdog starts when the execution call starts. Project changes or CLI output refresh the activity timer. If no further activity appears, the runner stops that AI call and moves to review instead of waiting forever.

The default backend is `qwen`, and its default command is `qwen.cmd`. Users can still override either value for another shell, backend, or local installation.

## Prompt Design

Prompt text is stored as Markdown templates under `prompts/`. `prompting.py` loads the templates and substitutes runtime fields; Python files should not be the place to tune model wording.

`runner/core.py` calls high-level helpers instead of owning all details: `runner/planning.py` turns goals or validator feedback into tasks, `runner/validation.py` runs final validators, `runner/prompting.py` builds prompts, `runner/ui.py` renders progress, `runner/agent_args.py` owns backend argument policy, and `runner/script_runner.py` owns YAML batch item setup. These modules avoid importing `runner/core.py`, keeping dependencies one-way.

Execution prompts contain only the current task, completed task titles, validator feedback, previous diagnostics, and recovery instructions. The prompt explicitly says to execute only the current task.

Planning prompts may write JSON or Markdown only under the runner work directory. Implementation files must not be changed during planning. The planner is asked to extract deliverables first, return valid JSON even when uncertain, and right-size tasks from one trivial task to many verifiable tasks for broad multi-file work.

Review prompts are read-only. If review changes project files, the runner restores them and retries.

AI validation is also read-only and runs in a fresh session. It returns `passed`, `reason`, `missing_items`, `checks_run`, and `suggested_checks`. When it fails, the runner converts missing items into structured validator feedback so normal repair planning can continue without a Python validator.

Runner code and prompt templates must stay task-agnostic. They may contain generic orchestration rules and generic planning heuristics, but they must not special-case one user's app name, fab, workflow, generated filename, algorithm, or validator internals. Case-specific strings belong in user goals, validators, examples, smoke cases, or test fixtures only.

## Validator Handling

Python validators run as:

```text
python validator.py --project-root <root> --state-file <state.json>
```

Validator files are protected. Agents may read validator files to understand expected behavior, but must not edit them, hardcode validator internals, or create sidecar state/log/scratch files next to outside-root paths.

When the same task makes no project changes while validator feedback is still present, the task is not accepted unless completion is explicitly deferred to the Python validator. When repeated no-progress or repeated final validator failure suggests a bad session, the runner clears the session and retries from saved state. If AI review returns no valid review JSON and a Python validator is configured, the runner can mark the task as deferred to final validation instead of looping on review format failures. Validator stdout is treated as a compact summary; detailed evidence belongs under `.ai-task-runner/validator-reports/`, where repair prompts read `summary.txt`, `errors.txt`, and then the first relevant `Full report:` file.

Validator stdout and stderr do not need a schema. The runner stores bounded feedback, currently 20,000 characters, with head and tail preserved for long logs.

## Backend Rule Files

- Qwen Code: `QWEN.md`
- OpenCode: `AGENTS.md`

OpenCode's official project rule filename is `AGENTS.md`, not `AGENT.md`.

## Public API

```python
from runner import RunRequest, run

run(RunRequest(goal="Build X", validator="ai"))
```

CLI, API, and YAML script mode all share the same state machine.
