# Project and Maintainer Guide

Version: 1.2.53

## Mandatory maintenance rules
1. Minimum code; no project-specific hardcode in generic Runner code. Never branch on sample/project names, FAB/ENV/version values, filenames, business fields, or a specific AI identity to solve one case.
2. Preserve 24H stability, including YAML List, repeated programmatic `run()`, Resume, and Supervisor recovery.
3. Logs/events must stay concise but contain enough Stage/session/retry/process/validator evidence to debug failures without dumping repeated context.
4. Workflow must not depend on concrete plugins, Qwen/OpenCode implementations, or raw event schemas. Cross-cutting behavior enters through Plugin/Hook/runtime semantic boundaries.
5. Normal recovery prefers the same session and sends only new failure evidence/next action, not context already known by that session.
6. Every Final AI validation run uses an independent fresh session; three configured runs require three different sessions.
7. Structured-output/Stage validation failures use bounded same-session recovery first, up to two retries; only then rebuild into a fresh session.
8. Fresh/rebuilt sessions receive the complete necessary Goal, Current Task, project-state instruction, and Stage instruction.
9. Workflow topology is declarative; ordinary AI Stages must be easy to add, move, replace, or remove through Stage data + prompt resources.
10. Delete/merge before adding layers. Do not introduce another service/helper/framework when the existing architecture can express the behavior clearly.
11. Readability is a requirement: clear names, cohesive functions, explicit contracts, few layers, and no hidden magic.
12. Remove dead code, stale compatibility shims, obsolete flow names, and unused aliases; keep one implementation per behavior.
13. Full AI task prompts must use stdin. Never put long prompts in command-line argv. Short backend control commands are not task prompts.
14. Folder, Python filename, class/function, and field names must describe their actual responsibility; avoid vague dumping-ground names when a precise name exists.

Core: minimum code, zero project hardcode, low coupling, pluggable, extensible, debuggable, and 24H-stable.

## Change checklist
- Can an existing shared helper/function be reused?
- Would this introduce a second parser/retry/path/snapshot/session/prompt implementation? If yes, stop and consolidate.
- Does any literal belong to one example/project rather than the Runner? Move it out.
- Is the change required by current evidence, or speculative? Remove speculative parts.
- Is the same-session prompt repeating information already in session? Replace it with a delta.
- Does a fresh/rebuilt session have enough context to continue independently? Add only what is necessary.
- Does Execute remain scoped to the Current TODO only?
- Do deterministic validators judge requirements rather than Planner strategy?
- Does the change add raw event types, concrete Plugin imports, or backend-specific branches to Workflow? Do not allow it.
- Are both English and Traditional Chinese docs plus tests updated with the real behavior?

## Public integration
Use `runner.api.RunRequest` / `runner.api.run()` as the shared entry for CLI/UI/skills. Do not build a second orchestration path for a UI or skill.

`runner/bootstrap.py` is the composition root. Backend/plugin registries compose dependencies at the boundary; Workflow must not discover concrete plugins or backends itself.

## UI / extension maintenance boundary
UI is an adapter beside CLI, not a Workflow Plugin. Pipeline, StageExecutor, Stage, AI client, and Workflow loader must not import UI code. External Stage/backend registration happens before Workflow validation through installed extensions; runtime-only plugins attach later through the Hook/Event boundary. A new external Stage must not require a Stage-name branch in Pipeline.

Editable Workflow/prompt files use the shared atomic resource functions and optimistic `expected_hash`; an active Run uses its durable Workflow/Stage-prompt/Goal/final-AI-prompt snapshot. Keep one Run per worker process for isolation rather than adding in-process global runtime concurrency solely for UI.

## Project policy
Every maintained smoke/example project root includes `.ai-task-runner.yaml`. The file itself is automatically protected. Immutable inputs/reference fixtures should be listed as protected directories/files; files that the task is expected to edit must not be protected.

Project responsibilities are centralized in:
- `runner/project/files.py`: manifest/change detection/restore/stale snapshot cleanup.
- `runner/project/policy.py`: project policy and protected paths.
- `runner/project/instructions.py`: Runner-managed QWEN.md/AGENTS.md sections.

## Current task execution contract
A fresh/rebuilt Executor receives the Current Task, Original Goal as global context, necessary validator/review feedback, and the full Stage instruction. When a normal same session already knows the same Stage prompt contract, `continuation_prompt` sends only the next TODO or newly produced Review/Validator evidence. Recovery continuations remain even smaller: Stage identity, new failure evidence, a readonly reminder when applicable, and the required next action/output contract.
When recovery needs more evidence, include only the relevant previous attempt output or diagnostic; do not broaden scope beyond the Current Task.

Do not preload future TODOs into the Execute prompt. The project filesystem is the implementation truth; Resume should preserve valid existing work rather than blindly recreating it.

## Session / recovery contract
- Initial call: full Stage prompt.
- Real failure: bounded same-session retry, default maximum two retries.
- Same session still fails: fresh session + complete necessary context.
- Same persistent failure after fresh recovery: return `replan` and create a new plan.
- Different failure fingerprint: reset the persistent-failure streak. Timeout identity must come from the backend semantic recovery key, not volatile raw stderr; keep the full stderr only for diagnostics.
- Transient API/service failure: AI transport backoff; do not consume Stage failure budget. Canonical API resumes durable state after an exhausted wait window.
- Final AI voting: every validation run starts a different fresh session.

## Validation and YAML List
Validator feedback in state is bounded to 20,000 characters with the start and end preserved. Runner sets `AI_TASK_RUNNER_WORK_DIR` for validator processes, and maintained templates write reports under its `validator-reports/` directory (falling back to `.ai-task-runner` when run standalone). External validators such as exe, bat, jar, or Java CLIs should use `docs/validator_templates/external_command_validator.py`.

Three validation modes are supported: AI-only, Python-only, and Mixed. Mixed validation always runs the Python hard gate before Final AI voting.

YAML batch mode is supported. It supports per-item `project_root`, `goal_file`, `workflow_file`, AI validation count, and required-pass threshold. Each item receives isolated nested state. Runtime scope must restore the parent after a child item finishes so hooks/events/state cannot leak across tasks.

Workflow YAML has only two top-level keys: `stages` defines reusable named nodes and `flow` defines the static top-level sequence. `recover` may contain a static recovery Stage sequence; there is no reusable-subflow, `expand`, or `foreach` DSL. The registry is only `type -> class` (`base`, `plan`, `python`, `python_script` by default). Generic AI-backed nodes default to `type: base`, so the type may be omitted. `PlanStage` is intentionally special: Loader derives its available dynamic Stage catalog from YAML structure, Plan selects ordered Stage names per TODO, and Pipeline persists/runs the resulting `next_steps`. Ordinary Stage classes remain routing-agnostic.

Use the shared 1-based `restart_at` YAML option when a top-level Stage must route logical FAIL or exhausted recovery to a current/earlier Workflow position. Keep session recovery, generated Planning children, and completion rules in their existing semantic owners; they are not arbitrary YAML topology.

## Prompt contract
All bundled Stage prompts use Jinja + `StrictUndefined`. Top-level template variables come only from `runner/prompts/context.py`; do not expose `RunState`, `RuntimeConfig`, `scratch`, or other internal objects directly.

Ordinary AI work is a `BaseStage` YAML instance; `type` defaults to `base` and is normally omitted. A genuinely new behavior requires one Stage class exposing `spec_class`, one `register_stage("type", Class)` call, and a YAML instance. Loader and Pipeline must not gain Stage-name-specific branches.

A Stage implements one independent attempt and returns facts in `StageResult`. It must not construct/call another Stage or choose concrete successors. Put state reduction in its injected result handler and put composition in generic Pipeline/routing data.

If the requirement is only conditional text/formatting, use Jinja. Only genuinely computed planning-specific context belongs in `PlanStage`.

## Plugin / event boundary
Plugins own cross-cutting concerns such as Console, Safety, History, and Observability. Workflow must never import a concrete Plugin.

Workflow uses a semantic progress API; raw event types/schema and subscriber delivery belong to runtime. Script batch orchestration publishes semantic `script.item_*` events through the same EventBus. Console output, JSON Lines, callbacks, and diagnostic logs belong only to Plugins. Do not add `publish("runner.xxx", ...)` to Workflow.

## Agent rule files
- Qwen Code: `QWEN.md`
- OpenCode: `AGENTS.md`

OpenCode's official project rule filename is `AGENTS.md`, not `AGENT.md`.

During one process, never instantiate a new `AIClient` solely to resume an existing session. Reuse the existing client. Only process-level `--resume` may reconstruct a client from persisted `ai_session_id` state.

## Documentation contract
Every human-facing maintained document must have an English `.md` version and a matching Traditional Chinese `.zh-TW.md` version that describe the same current behavior and section scope. Functional changes must update both versions together.

Prompt resources, backend instruction files (`QWEN.md` / `AGENTS.md`), and sample-project task prompts are executable/input resources rather than translated documentation and do not require duplicate language variants.
