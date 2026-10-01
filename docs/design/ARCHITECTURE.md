# Runtime Architecture

## Core graph

```text
RunRequest -> WorkflowRunner -> FlowEngine -> StageExecutor -> Stage
                            \-> StateStore
```

There is one runtime for CLI, API, YAML List and UI.

### Stage
Owns semantic work and returns `StageResult`.

### StageExecutor
Owns technical reliability only:
- technical retry;
- timeout;
- Same Session retry;
- Fresh Session rotation;
- transient backend/API recovery;
- safety/change tracking;
- plugin hooks/events.

A custom Stage must not implement its own retry/recovery framework.

### FlowEngine
Owns semantic navigation only:
- PASS -> next by default;
- FAIL -> stop by default;
- explicit `routes.pass` / `routes.fail`;
- task-scope iteration;
- one-of-many Handoff target routing;
- Review fail-soft continuation after a finite local technical retry policy is exhausted.

ERROR never becomes a graph edge. Review skip is a Stage-type policy that resolves to the ordinary next Stage; other finite ERROR exhaustion remains fail-closed.

### StateStore
Persists committed workflow position, task position, previous transition evidence, primary Session ID and durable per-role Session IDs.

## Dynamic Handoff

`type: handoff` advertises `targets`. Its structured result selects exactly one allowed target. It does not execute target work and does not own a scheduler hierarchy.

All specialist targets remain normal `base`, `review`, `task`, `ai_validator` or `command` Stages.

Session policy is independent from routing:
- `role` = durable Stage-owned Session;
- `main` = primary Runner Session;
- `fresh` = isolated invocation;
- `auto` = built-in/default profile behavior.

This separation lets the same Handoff graph express coding teams, review boards, triage or discussion without adding runtime types.

## Prompt/session contract

Stage templates define semantic behavior. Runner-owned shared control text carries only new retry/continue/recover information and bounded feedback. A Same Session continuation does not resend unchanged full context after the Stage prompt is already known to that Session.

Dynamic roles share one worker template plus per-Stage `instructions`; dedicated prompts are reserved for materially different protocols.

## UI contract

Studio is an editor projection of YAML, not a second graph schema.

- START/END: virtual only.
- Stage node: one real YAML Stage.
- PASS/FAIL edge: semantic route.
- Handoff edge: allowed target.
- ERROR: retry policy only.
- `scope: task`: visual group.

The backend validates the same catalog/schema used by runtime loading.

## Explicit non-goals

Do not restore:
- Pipeline/TaskRunner compatibility runtimes;
- repair/recover/restart_at/repeat/max_attempts/on_exhausted graph controls;
- `routes.error`;
- separate Discussion controller runtime;
- generic AgentMessage or scheduler framework;
- generic parallel DAG execution.

Parallel read-only/write-isolated execution remains future work.
