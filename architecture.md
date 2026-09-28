# AI Task Runner Architecture

## Goal

Keep the runtime small enough to understand end-to-end while still supporting:

- 24H unattended execution
- durable resume
- semantic closed loops
- custom Stages
- Plan/custom task producers
- n8n-style visual Stage wiring
- CLI execution
- YAML List batch execution
- future dynamic or parallel agent scheduling

The core runtime is intentionally small:

```text
                     Workflow Graph
                         │
          ┌──────────────┼──────────────┐
          │              │              │
       n8n UI           CLI          YAML List
          │              │              │
          └──────────────┴──────────────┘
                         │
                  same RunRequest
                         │
                  WorkflowRunner
                         │
                  FlowEngine
                   /       \
                  /         \
         StageExecutor     StateStore
               │
             Stage
```

UI, CLI and YAML List are adapters only. They must not own routing/runtime logic.

## Workflow model

A Workflow contains Stage nodes and result edges.

Each `stages.<name>` entry is exactly one graph node. `flow` is only the ordered list of those unique Stage names; there is no separate invocation/template override layer.

A Stage returns exactly one status:

- `pass`
- `fail`
- `error`

Routing rules:

- PASS defaults to the next Stage.
- FAIL defaults to stop.
- ERROR defaults to stop.
- `routes` may override a result with `next`, `done`, `stop`, or another Stage.

Example:

```yaml
stages:
  execute:
    type: task

  review:
    type: review
    routes:
      fail: execute

flow:
  - execute
  - review
```

There is no separate runtime concept for:
- repair
- recover
- restart_at
- repeat
- max_attempts
- on_exhausted
- replan
- execution_mode

## n8n-style UI contract

The product has one Graph Designer and three Workflow families:

1. **Linear Workflow with Rollback / Loop** - current production family.
2. **Dynamic Handoff** - future.
3. **Discussion / Group Chat** - future.

"Workflow family" is UI/asset semantics, not a public `execution_mode` switch
and not a reason to create three Runner implementations.

Today every executable Workflow is Linear. When Dynamic/Discussion is actually
implemented, add only the smallest Workflow metadata and scheduler state that
the real use case requires.

The Graph Designer edits the same Workflow asset used by CLI/runtime.

UI concepts:

- Stage = node
- normal flow order = PASS -> next
- `routes` = explicit result edge
- node panel = Stage properties
- edge editor = pass/fail/error target
- task scope = node invocation property
- technical retry is not drawn as an edge

The UI should support:
- drag Stage from catalog
- connect nodes
- edit Stage parameters
- edit result edges
- delete node/edge
- save only after real loader/schema validation
- load System/Custom/Project workflows through one format

The UI must not invent a second graph model.

### Linear Workflow with Rollback / Loop

Current implementation.

The graph is explicit Stage nodes plus result edges:

- PASS -> next
- FAIL -> another Stage / stop
- ERROR -> another Stage / stop

A rollback/loop is simply an edge back to an earlier Stage. There is no separate
Recovery object.

### Dynamic Handoff

Future UI family.

The same Stage nodes remain. The editor may additionally show:

- allowed handoff targets
- role/ownership metadata
- current runtime owner
- bounded handoff reason/context

Dynamic handoff must reuse StageExecutor and StateStore. Do not create another
agent runtime.

### Discussion / Group Chat

Future UI family.

Participants are still Stages. The same editor may additionally show:

- participant membership/order
- moderator/judge Stage
- round/termination settings
- bounded discussion summary

Discussion must reuse the same Stage execution/session/safety runtime. Do not
create a separate chat orchestrator unless a proven requirement cannot be
expressed by a small scheduler.

## CLI contract

CLI selects:
- project
- prompt/goal
- workflow
- validator/backend/runtime overrides

CLI then creates one `RunRequest` and uses the same runtime as UI/API.

There is no mode selector.

Example shape:

```text
ai_task_runner.py
  --goal ...
  --workflow workflow.yaml
  --stage-retries -1
```

CLI flags must map directly to RuntimeConfig or Workflow inputs. No CLI-only
routing semantics.

## YAML List contract

YAML List is batch input only.

Each item becomes one child RunRequest/RuntimeConfig and runs the same
WorkflowRunner.

```text
YAML List
   |
item 1 -> WorkflowRunner
item 2 -> WorkflowRunner
item 3 -> WorkflowRunner
```

YAML List owns:
- item ordering
- per-item prompt/project/workflow/runtime overrides
- child work directory

It does not own:
- routing
- retry state machine
- recovery policy
- completion shortcuts

## FlowEngine

FlowEngine owns only Workflow progress:

1. read current Stage from durable cursor
2. execute Stage
3. persist latest StageResult
4. resolve result target
5. move cursor
6. repeat until done or stop

It also owns the minimal task-scope iterator used by Plan/custom task producers.

It does not own:
- backend retry
- session recovery
- watchdog
- file protection
- subprocess policy
- UI behavior

## StageExecutor

StageExecutor owns technical reliability:

- hooks/safety
- changed-file tracking
- timeout/backend execution
- same-session retry
- Fresh Session rotation
- unlimited technical recovery by default

Default unattended behavior:

```text
Stage attempt
   |
same-session retry
   |
Fresh Session
   |
same-session retry
   |
Fresh Session
   |
...
```

`stage_retries=-1` means continue technical recovery.

Deterministic configuration/state failures fail closed.
Transient service/backend failures may escape to the outer supervisor, which
resumes durable state.

Technical retry is never a Workflow edge.

## Stage

Stage is the only execution/agent extension unit.

Built-ins:
- Base AI Stage
- Plan Stage
- Task Stage
- Review Stage
- AI Validator Stage
- Command Stage

Custom behavior uses `register_stage()`.

Plan is simply a Stage that produces `Task[]`.
Any custom Stage may also declare:

```yaml
produces: tasks
```

The same task-scoped Workflow executes those tasks.

No hidden Plan nodes are injected.

## Durable state

State contains only facts required to resume useful work:

- run identity / goal / project
- tasks + current task
- workflow position
- task-scope position
- AI session id
- latest StageResult transition
- workflow fingerprint
- runtime status / activity timestamps
- completion state

Retry/recovery counters are attempt-local, not a second durable state machine.

Correctness target:

```text
uninterrupted run
==
crash at committed Stage boundary + resume
```

## Future dynamic agents

Do not add a mode framework now.

When Dynamic Handoff is required, reuse:
- Stage
- StageExecutor
- StateStore
- Workflow assets
- UI Stage catalog
- safety/session/backend infrastructure

Only scheduling changes.

Conceptually:

```text
StageResult / bounded handoff intent
            |
     Dynamic Scheduler
            |
        next Stage
```

The scheduler should remain small and must not duplicate StageExecutor.

The same Graph Designer should represent available Stage roles and allowed
handoff targets.

## Future Discussion / Group Chat

Discussion is a scheduling policy over Stage participants, not a new execution
unit.

Conceptually:

```text
Stage A -> Stage B -> Stage C
          discussion round
                |
          moderator/judge
                |
          next round / done
```

Only discussion-specific scheduling state should be added when implemented.
Stage execution remains unchanged.

## Future parallel agents

Parallel agents also reuse Stage.

Default rules:
- multiple read-only Stages may run concurrently
- only one writer owns a project/worktree
- parallel writers require isolated worktrees
- merge/reconcile is explicit
- parallel scheduling must not duplicate retry/session/runtime code

The UI may later show parallel branches, but the node type remains Stage.

## Maintainability rules

1. Prefer deleting concepts over compatibility.
2. One behavior has one owner.
3. UI/CLI/YAML List are adapters, never runtimes.
4. No hidden Workflow nodes.
5. No duplicate graph/routing models.
6. No compatibility aliases for removed APIs.
7. Keep FlowEngine focused on scheduling/cursor state.
8. Keep StageExecutor focused on reliable Stage execution.
9. Future agent models must reuse Stage.
10. A new abstraction must remove more code/complexity than it adds.
