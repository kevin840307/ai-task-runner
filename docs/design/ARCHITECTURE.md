# Runtime Architecture

## Core graph

```text
RunRequest -> WorkflowRunner -> FlowEngine -> StageExecutor -> Stage
                            \-> StateStore
```

There is one runtime for CLI, API, YAML List and UI.

### Stage
Owns semantic work and returns `StageResult`.

### Stage module ownership

```text
runner/workflow/
  contracts.py            shared Stage protocol/context/result types
  stages/
    base_stage.py         generic AI-backed Stage + profile behavior
    plan_stage.py         Plan special Stage
    ai_validator_stage.py AI validation special Stage
    command_stage.py      deterministic external command Stage
    handoff_stage.py      dynamic handoff special Stage
  execution/
    stage_executor.py     shared retry/session/recovery execution boundary
```

A plugin or new special Stage depends on `workflow/contracts.py` and its own behavior. It must not own retry/session/recovery policy. Non-AI Stages do not depend on `BaseStage`.

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
- durable dynamic child-Workflow expansion for Stage results (`tasks` / `stages`);
- one-of-many Handoff target routing;
- Review fail-soft continuation after a finite local technical retry policy is exhausted.

ERROR never becomes a graph edge. Review skip is a Stage-type policy that resolves to the ordinary next Stage; other finite ERROR exhaustion remains fail-closed.

### StateStore
Persists committed workflow position, expanded child Workflow, dynamic task groups, previous transition evidence, primary Session ID and durable per-role Session IDs.

## Dynamic child Workflows

Any Stage may return `tasks` or `stages` when that Stage itself defines the child Stage structure. Runner never infers child node types.

Execution is parent-flow insertion semantics:

```text
A -> B -> C -> D
          |
          +-> child-1 -> child-2 -> ... -> child-N
                                      |
                                      +-> D
```

The complete child Workflow executes through the same StageExecutor/FlowEngine reliability path before the parent continues. Expanded definitions and task bindings are durable RunState, so Resume continues the already-expanded child Workflow without re-running C merely to reconstruct it.

`PlanStage` is the built-in example: it parses validated tasks and itself creates alternating AI Execute -> AI Review child stages. Future special/plugin Stages may produce completely different child structures through the same expansion contract.

## Dynamic Handoff

`type: handoff` advertises `targets`. Its structured result selects exactly one allowed target. It does not execute target work and does not own a scheduler hierarchy.

All ordinary AI specialists are `base` (AI Stage) nodes with a behavior profile. Profile defaults live only in `runner/workflow/profiles.py`; YAML normalization, dynamic expansion and Studio consume that same catalog. Only genuinely special runtime semantics use dedicated Stage types such as `plan`, `ai_validator`, `command` and `handoff`.

Session policy is independent from routing:
- `role` = durable Stage-owned Session;
- `main` = primary Runner Session;
- `fresh` = isolated invocation;
- `auto` = built-in/default profile behavior.

This separation lets the same Handoff graph express dynamic specialist routing without adding another runtime family.

## Prompt/session contract

Stage templates define semantic behavior. Runner-owned shared control text carries only new retry/continue/recover information and bounded feedback. A Same Session continuation does not resend unchanged full context after the Stage prompt is already known to that Session.

Dynamic roles share one worker template plus per-Stage `instructions`; dedicated prompts are reserved for materially different protocols.

## UI contract

Studio is an editor projection of YAML, not a second graph schema.

- START/END: virtual only.
- Stage node: one real YAML Stage. AI Stage uses `profile: generic | execute | review`.
- PASS/FAIL edge: semantic route.
- Handoff edge: allowed target.
- ERROR: retry policy only.

The backend validates the same catalog/schema used by runtime loading.

## Explicit non-goals

Do not restore any pre-v3 compatibility runtime/schema. ERROR remains an execution concern rather than a graph edge. Discussion / Group Chat, generic AgentMessage/scheduler frameworks and generic parallel DAG execution are also outside the current runtime.

Parallel read-only/write-isolated execution remains future work.
