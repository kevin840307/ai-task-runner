# AI Task Runner Architecture

## Current production scope

The current production routing strategy is **Linear Workflow with rollback/loop**.
Dynamic handoff and discussion routing are future extensions only; they must reuse
this runtime instead of creating separate runners.

### execution_mode compatibility

The public `execution_mode` request/state field currently accepts only `linear`.
It is compatibility/identity metadata, not a registry for alternate Runner
implementations.

Production bootstrap always enters `WorkflowRunner`. Future Dynamic/Discussion
behavior must be introduced as RoutingStrategy behavior behind `FlowEngine`, not
through `register_execution_mode(... runner=...)` or a second runtime.

## Core runtime

```text
Chat / CLI / API
       |
       v
 Workflow/Profile
       |
       v
 WorkflowRunner
   |-- FlowEngine
   |    '-- LinearRouting
   |         '-- result edge: status -> target
   |
   |-- StageExecutor
   |    |-- technical retry
   |    |-- timeout / watchdog integration
   |    |-- same-session retry
   |    '-- fresh-session recovery
   |
   '-- StateStore
        |-- durable state
        |-- checkpoint
        '-- resume
```

The main reading path for runtime behavior should remain:

1. `runner/workflow_runner.py`
2. `runner/workflow/flow_engine.py`
3. `runner/workflow/linear_routing.py`
4. `runner/workflow/stages/executor.py`
5. `runner/runtime/run_state.py`

Compatibility modules such as `task_runner.py` and `workflow/pipeline.py` should
contain re-exports only and no new runtime behavior.

## Stage is the execution unit

Plan, Execute, Review, Validator, Command and future role-based Agents are all
Stages.

A Stage:
- receives `StageContext`
- performs one responsibility
- returns `StageResult`
- does not decide the final workflow destination
- does not directly mutate the Linear routing cursor

Future Coder/Reviewer/Architect/Moderator agents should normally be AI Stage
configurations with different role/prompt/session/tool settings, not separate
runtime frameworks.

## Reliability ownership

### StageExecutor: technical execution

`StageExecutor` owns failures of **how a Stage was executed**:

- transient AI/API/CLI failure
- same-session retry
- timeout handling
- Fresh Session escalation
- hooks and protected-path enforcement
- technical failure bookkeeping

A technical retry attempts the same logical Stage. It does not choose another
workflow Stage.

### FlowEngine: semantic workflow result

`FlowEngine` owns **what happens after a Stage produced a semantic result**.

The canonical contract is intentionally small:

- PASS -> next (implicit) or an explicit `routes.pass`
- FAIL -> `routes.fail`
- ERROR -> `routes.error` only after StageExecutor exhausts technical recovery
- REPLAN -> `routes.replan`
- `done` / `stop` are terminal targets

Example:

```yaml
review:
  type: review
  routes:
    fail: execute
```

Legacy `recover` / `restart_at` / `repeat` remain compatibility syntax while
existing workflows migrate. New simple closed loops should prefer `routes`.
`SemanticRoutingPolicy` is therefore a compatibility policy, not the preferred
new workflow model.

### LinearRouting: cursor/navigation

`LinearRouting` is the only owner of Linear cursor mutation:

- `workflow_position`
- `task_step`
- restart target
- task-block restart
- task-block completion

Reducers in `reducers.py` update semantic/task data only.

## Durable transition context

The previous Stage result needed by the next Stage is persisted in
`RunState.transition_previous`.

This is intentionally a single latest transition rather than an unbounded
history. It allows resumed execution to recover the previous Stage context
instead of always restarting with `previous=None`.

Completion clears this transition context.

The long-term correctness target is:

```text
uninterrupted run
==
kill at any committed Stage boundary + resume
```

for routing, shared-control feedback and final artifacts.

## State ownership

For now there is still one durable `RunState` and one authoritative
`state.json` commit point. Do not prematurely split persistence across files.

Fields should conceptually belong to:
- common run lifecycle
- Stage/session execution state
- Linear routing state
- semantic failure/recovery bookkeeping
- latest transition context

A later schema migration may group these fields structurally after ownership is
stable and covered by resume tests.

## UI contract

The product entry remains:

```text
select Workflow/Profile -> enter prompt -> Run
```

Do not add a separate mode selector to Chat.

The Workflow/Profile should eventually carry routing/editor metadata so the same
Graph Designer can expose the right controls automatically.

Current Linear UI concepts:
- Stage = node
- `routes` result transitions = normal workflow edges
- technical retry remains a StageExecutor property and is not a workflow edge
- Stage settings = node properties
- legacy restart/recover routing remains visible during migration

Current UI ownership:
- `ui/server.py`: composition + HTTP transport only
- `ui/project_runtime_state.py`: project lifecycle, runtime/process/chat state
- `ui/workflow_studio_state.py`: Workflow Studio assets, validation, graph/editor operations
- `ui/workflow_builder_state.py`: AI workflow generation/builder state

Do not move project/runtime or Studio implementation back into `server.py`.
Patch/tests should target the module that owns the behavior.

Future routing strategies should extend these concepts before introducing a
separate editor.

## Extension rules

When adding a new Stage:
1. Prefer configuration/spec over a new runtime class when behavior is the same.
2. Keep routing decisions out of the Stage.
3. Reuse `StageExecutor` reliability behavior.
4. Add deterministic routing tests.

When adding a future RoutingStrategy:
1. Reuse `WorkflowRunner`.
2. Reuse `StageExecutor`.
3. Reuse `StateStore`.
4. Add only strategy-specific routing state.
5. Do not copy Linear runtime code.

## Maintainability rules

- One concept has one primary owner.
- New production behavior goes into canonical modules, not compatibility shims.
- Avoid long-lived old/new dual paths.
- Prefer a few clear domain modules over many tiny manager/helper classes.
- Review production files around 500+ lines for mixed responsibilities.
- Review functions around 80+ lines for separable domain steps.
- Do not split code solely to satisfy line counts.
- Names should describe domain responsibility rather than implementation history.

## Current compatibility names

These remain temporarily to avoid breaking callers:

- `TaskRunner` -> `WorkflowRunner`
- `Pipeline` -> `FlowEngine`
- `RecoveryPolicy` -> `SemanticRoutingPolicy`
- `workflow/rules.py` -> `workflow/reducers.py`
- `workflow/recovery.py` -> `workflow/semantic_routing.py`
- `workflow/routing.py` -> `workflow/linear_routing.py`

New code should use the canonical names.
