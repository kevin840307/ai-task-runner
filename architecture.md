# AI Task Runner Architecture

The runtime intentionally has one small execution model.

```text
UI / CLI / API / YAML List
            |
        RunRequest
            |
     WorkflowRunner
            |
        FlowEngine
       /         \
StageExecutor   StateStore
      |
    Stage
```

## Ownership

- **Stage**: one semantic unit of work.
- **StageExecutor**: technical reliability for one Stage: retry, timeout, Same Session retry, Fresh Session rotation, safety/change tracking and hooks.
- **FlowEngine**: semantic PASS/FAIL navigation, durable dynamic child-Workflow expansion and Dynamic Handoff target routing.
- **StateStore**: durable workflow position, task progress, primary Session and per-role Sessions.
- **WorkflowRunner**: constructs the runtime and executes the loaded Workflow.
- **UI/CLI/API/YAML List**: adapters to the same runtime; none owns execution semantics.

## Workflow semantics

A normal Stage returns PASS, FAIL or ERROR.

- PASS defaults to the next Stage.
- FAIL defaults to stop.
- `routes.pass` / `routes.fail` may target another Stage, `done` or `stop`.
- ERROR is never a graph edge. StageExecutor applies retry policy. A Review with finite local `error_policy.retries` fail-soft skips to the next Stage after exhaustion; other Stage types fail closed after finite exhaustion.
- A backward PASS/FAIL edge is the rollback/loop mechanism. There is no repair/recover Stage model.

Any Stage may return `tasks` or `stages` only when that Stage supplies the child Stage definitions. FlowEngine inserts that child Workflow immediately after the producer, runs it completely through the same StageExecutor path, then resumes the parent next Stage. Expanded definitions and task bindings are durable state; Resume does not rerun the producer merely to rebuild children.

`PlanStage` is the built-in producer example. It parses validated tasks and itself builds alternating `base/profile=execute` -> `base/profile=review` children. Runner never infers that structure for other producers.

## Dynamic Handoff

Dynamic Handoff is the only multi-agent runtime primitive.

```text
                 -> Requirements Analyst
                 -> Solution Architect
Handoff Stage    -> Implementer
                 -> Debugger
                 -> Verifier
                 -> Risk Reviewer
                 -> Final Validator
```

The Handoff Stage returns one structured allowed target. Only that Stage runs. Roles are ordinary Stages and normally route PASS back to the Handoff Stage. Discussion/review-board/triage are Workflow patterns built from the same primitive, not runtime types.

## Session lifecycle

AI Stages expose `session_policy`:

- `role`: durable reusable Session keyed by Stage name; Dynamic specialist default.
- `main`: share the Runner primary Session.
- `fresh`: new Session every invocation; use for independent validation.
- `auto`: built-in/internal behavior; only this mode may use `session_key`.

`RunState.stage_sessions` stores only durable `role` Sessions. Technical failure can rotate only the failing Stage to a fresh Session; other role Sessions remain intact.

`fresh_session_each_run` and `fresh_session_on_start` remain internal Stage implementation details and are not public Workflow YAML. `session_key` is only the advanced `session_policy: auto` cache override. New workflows should normally use `session_policy`.

## Prompt model

One core prompt per Stage behavior. Retry/recover/continue context is Runner-owned and appended by the shared control envelope; it is not maintained as separate prompt files.

Dynamic ordinary roles share `common/dynamic_worker.md` and receive role-specific `instructions`. Handoff and final validation use their own prompt contracts.

## UI

Workflow Studio edits the same YAML model used by the runtime.

- START/END are UI-only virtual nodes.
- one YAML Stage = one node.
- PASS/FAIL edges map to `routes`.
- Handoff multi-target edges map to `targets`.
- ERROR policy is edited as retry count, not as an edge.
- Stage Test executes exactly one Stage in an isolated temporary Project and reports result + next target.

## Package boundaries

Keep these domains separate:

- `runner/agent` — provider/backend clients.
- `runner/workflow` — schema, routing, Stage implementations.
- `runner/runtime` — durable/process reliability.
- `runner/plugins` — extension hooks/registration.
- `runner/assets` — editable Workflow/Prompt assets.
- `runner/config` — configuration.

Do not add another Runner/Pipeline, generic scheduler hierarchy, AgentMessage framework or parallel DAG engine without a proven requirement.

## Reliability gates

1. deterministic compile/pytest on Ubuntu + Windows + Studio build;
2. deterministic dry-run / Stage probe / resume / retry/session-policy matrix;
3. real-Qwen short reliability gate;
4. high-density soak;
5. full 24H Windows unattended soak.

A green deterministic CI does not substitute for real-Qwen or 24H evidence.
