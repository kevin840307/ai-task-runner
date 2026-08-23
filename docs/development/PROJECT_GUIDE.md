# Project and Maintainer Guide

Version: 1.2.21

## Mandatory maintenance rules
1. No project-specific hardcode in generic Runner code. Never branch on sample project names, FAB/ENV/version values, filenames, business fields, or a specific model identity to solve one case.
2. One behavior, one shared implementation. All equivalent paths must call the same helper/function instead of copying logic.
3. Minimum code. Prefer deleting/merging code over introducing another service/helper layer when the existing architecture can express the behavior.
4. Readability is a requirement: clear names, short cohesive functions, explicit contracts, few layers, no clever hidden behavior.
5. Preserve unrelated behavior. Scope every production change to the demonstrated need.
6. Keep Runner content-agnostic. Project rules belong in policy/prompts/validators/project source.

## Change checklist
- Can an existing shared helper be reused?
- Would this introduce a second parser/retry/path/snapshot/session implementation? If yes, stop and consolidate.
- Does any literal belong to one example/project rather than the Runner? Move it out.
- Is the change required by current evidence, or speculative? Remove speculative parts.
- Is the same-session prompt repeating information already in session? Remove it.
- Does a fresh/rebuilt session have enough context to continue independently? Add only missing context.
- Does Executor scope remain Current TODO only?
- Do deterministic validators still judge requirements rather than Planner strategy?
- Are docs and tests updated with the real behavior?

## Public integration
Use `runner.api.RunRequest` / `runner.api.run()` as the shared entry for CLI/UI/skills. Do not build a second orchestration path for a UI or skill.

## Project policy
Every maintained smoke/example project root includes `.ai-task-runner.yaml`. The file itself is automatically protected. Immutable inputs/reference fixtures should be listed as protected directories/files; files that the task is expected to edit must not be protected.

## Current task execution contract
A fresh/rebuilt Executor receives the current task, Original Goal as global context only, and any relevant validator/review feedback. A same-session continuation receives only new feedback. When recovery needs it, include the previous attempt output or diagnostic without expanding scope beyond the current task.

## Validation and batch mode
Validator feedback in state is bounded to 20,000 characters with the start and end preserved. External validators such as exe, bat, jar, or Java CLIs should use `docs/validator_templates/external_command_validator.py`; configured log folders are copied into `.ai-task-runner/validator-reports/external-command/`.

YAML batch mode is supported. Each item gets its own nested state directory under the configured work directory.

## Agent rule files
- Qwen Code: `QWEN.md`
- OpenCode: `AGENTS.md`

OpenCode's official project rule filename is `AGENTS.md`, not `AGENT.md`.

- Session rule: during one process, never instantiate a new `AgentClient` solely to resume an existing session. Reuse the existing client. Only process-level `--resume` may reconstruct a client from persisted session state.
