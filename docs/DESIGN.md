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
ai_task_runner.py      CLI parser and execute() entry
defaults.py           Shared 24h default values
runner_api.py         Public API and RunRequest validation
runner_core.py        TaskRunner state machine
runner_support.py     Prompts, parsers, validation helpers, protection
runner_models.py      Task and RunState serialization
agent.py              AgentClient session facade
process_control.py    Subprocess output reader, timeout, process-tree kill
backends/base.py      Backend interface
backends/qwen.py      Qwen stream-json command/result/error parsing
backends/opencode.py  OpenCode command/result parsing
```

## State Machine

```text
planning -> executing -> reviewing -> validating
                         ^             |
                         |             v
                     retry task <- validator_failed
```

Final Validator PASS sets `completed=true`. Validator FAIL stores `validator_output`, increments the cycle, and creates a focused repair task.

## Process Control

`process_control.py` starts each AI CLI or validator as a subprocess, captures stdout/stderr incrementally, and kills the child process tree on timeout. Qwen uses `stream-json`, so CLI output is also an activity signal.

Execution has two limits:

- hard timeout: `--agent-timeout`, default `7200`
- activity idle watchdog: `--agent-idle-after-change-timeout`, default `900`

The idle watchdog starts mattering only after project changes or CLI output. If no further activity appears, the runner stops that AI call and moves to review instead of waiting forever.

The default backend is `qwen`, and its default command is `qwen.cmd`. Users can still override either value for another shell, backend, or local installation.

## Prompt Design

Execution prompts contain only the current task, completed task titles, validator feedback, previous diagnostics, and recovery instructions. The prompt explicitly says to execute only the current task.

Planning prompts may write JSON or Markdown only under the runner work directory. Implementation files must not be changed during planning.

Review prompts are read-only. If review changes project files, the runner restores them and retries.

## Validator Handling

Python validators run as:

```text
python validator.py --project-root <root> --state-file <state.json>
```

Validator files are protected. Agents may read validator files to understand expected behavior, but must not edit them or hardcode validator internals.

When the same task makes no project changes while validator feedback is still present, the task is not accepted. When repeated no-progress suggests a bad session, the runner clears the session and retries from saved state.

Validator stdout and stderr do not need a schema. The runner stores bounded feedback, currently 20,000 characters, with head and tail preserved for long logs.

## Backend Rule Files

- Qwen Code: `QWEN.md`
- OpenCode: `AGENTS.md`

OpenCode's official project rule filename is `AGENTS.md`, not `AGENT.md`.

## Public API

```python
from runner_api import RunRequest, run

run(RunRequest(goal="Build X", validator="ai"))
```

CLI, API, and YAML script mode all share the same state machine.
