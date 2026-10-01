# Design

Version: 1.2.66

## Principles
1. Minimum code; no project-specific hardcoding in Runner core. Global reusable behavior is allowed.
2. Preserve current 24H behavior and YAML List stability.
3. Keep logs concise but sufficient to debug Stage/session/retry/process/validator failures.
4. Workflow does not depend on concrete plugins, backend implementations, or raw event schemas; cross-cutting behavior enters through Plugin/Hook/runtime semantic boundaries.
5. Prefer same-session continuation and send only new information, never duplicate known context.
6. Final AI validation uses independent fresh sessions; three validation runs require three different sessions.
7. Validation/structured-output failures recover in the same session first, with at most two bounded retries, then use a fresh session.
8. Only fresh/rebuilt sessions receive the complete necessary Goal, Current Task, project-state instruction, and Stage instructions.
9. Workflow topology is declarative and easy to add, move, replace, or remove Stages.
10. Delete/merge unnecessary code before adding abstraction; keep one implementation per behavior.
11. Code must be direct and maintainable: clear names, cohesive functions, explicit contracts, and few layers.
12. Remove dead/stale code, obsolete compatibility shims, and unused aliases when no supported caller needs them.
13. Full AI task prompts use stdin, never command-line argv; short backend control commands are not task prompts.
14. Folder, Python filename, class/function, and field names must describe their actual responsibility, with sensible splitting/merging.
15. Every Stage is independently executable for one attempt. It must not instantiate, call, or select another concrete Stage; composition happens only through `StageResult` and Pipeline/routing policy.

## Main flow

Bundled default: `Plan -> [Task -> Review] x TODO -> File Validator? -> AI Validator? -> PASS`

- No independent Understand Stage.
- `PlanStage` is the built-in AI Task producer and installs durable TODOs through the generic `tasks` result effect.
- Review is a local semantic gate. With configured review retries it may fail-soft/skip; final validation remains authoritative.
- The bundled CLI `mixed` workflow runs deterministic File validation before Final AI validation. Explicit/custom workflows may place multiple File/AI validation gates anywhere in top-level `flow`, including ordinary Stages after them.
- Validator FAIL follows its explicit `routes.fail` edge, typically back to Planning or Execute.
- Backward PASS/FAIL result edges are the only rollback/loop mechanism; there is no `restart_at`, Repair Stage, or hidden recovery graph.
- Built-in workflows complete only after their configured validation path passes. Explicit generic workflows may omit validators and complete when their flow ends successfully.
- A custom Workflow YAML contains only named `stages` and top-level `flow`. Task-producing Stages emit the public Task contract; explicit contiguous `scope: task` Stages define the per-task SOP. A custom flow may use Plan, another Task producer, or no tasks at all. There is no generated `next_steps`, `expand`, or hidden `foreach` topology.

## Ownership

- `assets/workflows/*.yaml` and `workflow/loader.py`: bundled/custom topology and one normalization path.
- `workflow/registry.py`: the explicit `type -> Stage class` registry plus UI/editor catalog metadata.
- `workflow/results.py`: StageResult parsing/reduction and durable task/validation effects.
- `workflow/stages/executor.py`: shared retry/session recovery, hooks, progress reporting, and project change tracking.
- `workflow/stages/*`: one-attempt Stage behavior.
- `agent/`: Qwen/OpenCode transport, session, and structured-output adapters.
- `workspace.py`: project files, policy, manifests, and protection helpers.
- `runtime/`: run state, process supervision, heartbeat, and event infrastructure.
- `plugins/`: cross-cutting optional behavior.

## Retry and recovery

- Classified transient API/network/rate-limit/service errors preserve the usable Session and use seconds-based capped exponential backoff.
- Other technical Stage errors retry the same usable Session first; after the per-session attempt budget, StageExecutor rotates only that Stage to a Fresh Session and continues with the shared recovery envelope.
- The unattended global default is `stage_retries=-1` (unlimited). A finite Stage-local `error_policy.retries` overrides it.
- A write attempt that fails after making project changes preserves those changes, rotates the Stage Session, and recovers from current project evidence rather than blindly replaying the same conversation.
- Review is intentionally fail-soft when it has a finite local `error_policy`: after retries are exhausted it skips to the next Stage. Final validation remains authoritative.
- Non-Review Stages remain fail-closed after a finite retry budget is exhausted.

## Validation modes

- AI-only CLI default: the bundled AI Validator is the configured final gate.
- File-only CLI default: the bundled File Validator is the configured final gate.
- Mixed CLI default: bundled File validation must PASS before bundled Final AI validation runs; both gates must pass.
- Explicit/custom workflows: validation Stages are ordinary top-level gates. Multiple File and AI validators may be interleaved with ordinary Stages; each validator owns its own recovery policy.
- Final AI validation runs use fresh independent sessions. `final_ai_required_passes=0` uses strict majority; an explicit value requires that many PASS results. Structured-output correction uses bounded same-session retries before configured fresh fallback.

## Prompt contract

All bundled prompts use Jinja + `StrictUndefined`. `prompts/context.py` is the only Stage template-data contract. Templates do not directly access `RunState`, `RuntimeConfig`, or arbitrary scratch objects.

Ordinary AI Stage configuration points to `prompts/stages/*.md` directly. Planning-specific computed context is owned directly by `PlanStage`; there is no prompt-builder registry. Shared prompt fragments use Jinja `{% include %}`.

## Project safety

`project/policy.py` loads `.ai-task-runner.yaml`. `project/files.py` owns project manifests/change detection/restore plus stale Safety snapshot cleanup. `project/instructions.py` owns the Runner-managed sections of QWEN.md/AGENTS.md. Safety/Git/readonly behavior is injected through plugins/hooks rather than Workflow imports.

## Durable state

`runtime/run_state.py` is the single durable task/run-state representation. State is saved after meaningful transitions. The project filesystem remains implementation truth; state stores bounded evidence/session/recovery metadata needed to resume.

## Process survivability

`runtime/process_runner.py` owns subprocess waiting, timeout, idle-after-change detection, and termination. The outer supervisor/worker recovery keeps durable state and can resume after abnormal worker disappearance.
It also mirrors the most recent bounded subprocess stdout to `<work-dir>/stream.log` for detached local live display. This file is reset per subprocess, is intentionally disposable, and never participates in resume, validation, retry, session, or routing decisions.


## Runtime scope

Each `execute()` call owns a scoped runtime. Nested YAML-list items temporarily replace the active runtime/event context and restore the parent scope on exit, so repeated programmatic runs and script items do not leak hooks/events/state into one another.


## OpenCode backend parity

Qwen and OpenCode share `BaseBackend` stdin transport, timeout/idle-timeout handling, process-tree cleanup, and stable recovery identity. Backend adapters own only transport/capability differences: Qwen uses `--resume` plus its native `-s` sandbox; OpenCode uses `--session`, JSON events, `--auto`, and `OPENCODE_CONFIG_CONTENT.permission` for planning/no-tool/review policy and Runner `--sandbox` confinement. Workflow, StageExecutor, and Pipeline must never branch on backend names.
