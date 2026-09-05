# Design

Version: 1.2.61

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

Bundled default: `Plan -> [Execute -> Review] x TODO -> File Validator? -> AI Validator? -> PASS`

- No independent Understand Stage.
- `PlanStage` is the built-in AI Task producer and installs durable TODOs through the generic `tasks` result effect.
- Review is a local semantic gate. With configured review retries it may fail-soft/skip; final validation remains authoritative.
- Python validation is deterministic and runs before AI validation when both are enabled.
- Validator FAIL runs the configured recovery path, typically Repair Plan -> task-scoped SOP -> validators again.
- A Stage may override FAIL/replan recovery with the shared 1-based `restart_at` YAML option; omitted values preserve the routes above.
- Built-in Regression workflows complete only after their configured final validation path passes. Explicit generic workflows may omit validators and complete when their flow ends successfully.
- A custom Workflow YAML contains only named `stages` and top-level `flow`. `PlanStage` automatically uses the standard `execute -> review` task SOP, so normal Plan-driven flow lists only Planning and later top-level gates. Other Stages may produce the public Task contract with `produces: tasks`; explicit `scope: task` remains available for advanced/custom per-TODO SOPs. A custom flow may use Plan, another Task producer, or no tasks at all. There is no generated `next_steps`, `expand`, or `foreach` topology.

## Ownership

- `workflow/builtin/*.yaml`, `workflow/loader.py`: validator-selected bundled topology, custom topology, and one normalization path.
- `workflow/registry.py`: the explicit `type -> Stage class` registry plus UI/editor catalog metadata; it does not own workflow topology or Stage instances.
- `workflow/rules.py`: the small `StageResult.kind` reducers and durable-state transitions (`tasks`, `task`, `review`, `validation`, `generic`).
- `workflow/stages/executor.py`: shared retry/session recovery, hooks, semantic progress reporting, and project change tracking.
- `workflow/stages/*`: one-attempt Stage behavior.
- `ai/`: AI interaction/session/structured output only.
- `backends/`: Qwen/OpenCode transport implementations only.
- `project/`: workspace files/policy/instruction files.
- `runtime/`: run state/process/event infrastructure.
- `plugins/`: cross-cutting optional behavior.

## Retry and recovery

- Transient API/network/rate-limit/service errors use bounded exponential backoff inside `AIClient.run_with_retry()` and preserve state/session.
- A real Stage error retries the same usable session first with a short stage-aware delta prompt; it does not resend the full goal/task context.
- After the configured same-session retry budget, StageExecutor clears cached sessions and retries fresh.
- The same persistent failure after fresh recovery returns `replan`.
- A different failure fingerprint resets the persistent-failure streak. Backend timeouts carry a stable semantic recovery key; volatile stderr details (for example sandbox/container identifiers) remain in diagnostics but do not change failure identity.
- A write attempt that made meaningful project changes is treated as progress and is handed to Review/Validator rather than discarded.
- Review skip does not complete the run; final validation still decides.

## Validation modes

- AI-only: the AI Validator is the configured final gate.
- File-only: the File Validator is the configured final gate.
- Mixed: file validator must PASS before Final AI Validator runs; both gates must pass.
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
