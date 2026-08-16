# Architecture

Version: 1.2.0

## Responsibility boundary
The Runner owns orchestration, state, retry/recovery, session policy, protection, model transport, prompt assembly, result parsing, validation orchestration, UI/events, and diagnostics. The Runner owns orchestration; project code owns application behavior. It must not understand application-specific workflows or business values. Project behavior belongs in the goal, project source, validator, templates, fixtures, and `.ai-task-runner.yaml`.

## Module map
- `ai_task_runner.py`: CLI adapter.
- `runner/api.py`: canonical `RunRequest` / `run()` interface for CLI, UI, skills, and Python callers.
- `runner/core.py`: state-machine/orchestration.
- `runner/planning.py`: Understand, Plan, fallback, Refiner, Judge.
- `runner/reviewing.py`: fresh current-TODO review and logical no-tool finalize (with one read-only compatibility tool retained for strict APIs).
- `runner/validation.py`: deterministic and Final AI validation orchestration.
- `runner/model_results.py`: one generic JSON-candidate extraction path plus strict stage parsers.
- `runner/prompting.py`: prompt templates/context composition.
- `runner/policy.py`: project-root policy loading.
- `runner/support.py`: shared filesystem/state/retry/protection helpers.
- `runner/debug.py`: current/last/bounded-history diagnostics.
- `runner/process_control.py`: subprocess timeout/idle/watchdog handling.
- `runner/git_guard.py`: blocks AI child-process `git add/commit/push`.
- `runner/backends/`: Qwen/OpenCode transport adapters.
- `runner/ui.py`: human terminal rendering and JSON events.

## Data flow
`RunRequest -> validate request -> load/create state -> build protected roots -> Planning -> TODO Executor -> Review -> next TODO -> deterministic Final Validator -> optional Final AI Validator -> complete or Repair Planning`.

## Session policy
- Fresh Understand: full goal/context + bounded read tools, no writes.
- Same-session Plan: only the next instruction/output contract; static context is not resent.
- Planning fallback/Judge: decision context remains self-contained enough for recovery. Judge and Rewrite reuse the Planner that produced the current plan; if the shared Agent policy resets an unusable session, the same client naturally rebuilds from the self-contained prompt.
- Fresh/rebuilt Executor: Original Goal for global context only + Current TODO as the only executable scope.
- Same-session Executor retry: short continuation with only new review/recovery feedback.
- Fresh Review: current TODO/evidence only; read-only. Review is the intentional independent session boundary.
- Same-session Review Finalize: stop inspecting and emit verdict.
- Final AI Validator: fresh independent session judging the complete goal.

## Structured output
All final structured model results go through one extractor in `runner/model_results.py`. It accepts a clean JSON response, fenced JSON, prose around JSON, or multiple top-level candidates. Each stage then validates its own schema. Malformed JSON, wrong field types, missing required fields, insufficient TODO count, or invalid semantics are rejected; the Runner does not guess or repair payload meaning.

## Protection model
Protected paths are normalized roots; protecting a directory protects its subtree. Sources include Runner source, goal/validator files, backend files, CLI `--protect-file`, and project-root `.ai-task-runner.yaml`. The policy file is automatically protected. AI mutations are compared against snapshots and restored on violation.

## Debug model
`current-prompt.txt` is written immediately before every backend model call. At the same time, `debug/history/<call-id>-prompt.txt` is persisted so an in-flight/crashed call still has its input. On completion or error, `last-prompt.txt`, `last-result.txt`, and the matching `history/<call-id>-result.txt` are written. History remains bounded (default 100 calls, 50 MiB total, 2 MiB per entry with head/tail truncation). Diagnostics are fail-soft and excluded from task progress/change semantics.

## Session continuation invariant

Within one Runner process, a logical agent role keeps one `AgentClient`; continuation mutates only its `session_id` state and never constructs a replacement client merely to resume. Fresh independent roles use empty sessions. Process-level `--resume` may reconstruct the main client from persisted state because no prior local client survives the restart.
