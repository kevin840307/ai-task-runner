# Protection and Safety Model

Version: 1.2.62

## Project root
The project root is the task workspace boundary. Project policy is read only from `<project-root>/.ai-task-runner.yaml`; parent directories are not searched.

## Protected paths
`protected_paths` entries are project-relative files or directories. Directory entries protect the whole subtree. Paths are normalized and descendant entries are collapsed when a protected parent already exists. Absolute paths and `..` escapes are rejected. The policy file itself is always protected automatically. External Python-validator projects should also protect `ai_task_runner_validator.py`; source-mode runs may place this shared helper beside `validation.py`.

Protected-path snapshots detect modification, deletion, creation under protected directory roots, and restore violations. CLI `--protect-file` can add ad-hoc protection; project policy is preferred for stable rules.

On Windows, Safety filesystem I/O uses extended-length paths internally, so deep protected/readonly trees are not silently skipped when their absolute paths exceed the traditional `MAX_PATH` limit. Logical Project paths and policy syntax stay unchanged.

## What to protect
Protect immutable inputs, answer/reference fixtures, validator helpers located inside project root, and any files the agent may read but must not change. Do not protect source/output files the task is expected to modify.

## Runner source and validator
Runner source/backend files and configured goal/validator files are added to protection by the orchestrator. Validators should remain external to model control or explicitly protected if they live inside the writable project root.

## Git
AI child-process PATH guard blocks `git add`, `git commit`, and `git push`. Other Git reads/diagnostics are allowed. This is a guardrail, not an OS sandbox; human review owns staging/commit/push.

## Backend capability limits
Qwen Planning is read-only and may use bounded filesystem read tools only when the current planning step needs evidence. Those reads may target any path readable by the host account, including paths outside the current Project; write/edit/shell remain excluded. OpenCode Planning applies the same intent by allowing read/glob/grep/LSP plus external-directory reads while denying all other tools. `allow_project_read` is retained as the backward-compatible YAML/API option name; for `PlanStage` it means readonly filesystem inspection and defaults to `true`. Set it to `false` to disable Planning reads. Review and final AI validation keep their existing read-only review policy. Runtime excludes unrelated agent/skill/computer-use tools. These capability policies supplement filesystem protection.
