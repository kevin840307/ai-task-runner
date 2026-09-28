# AI Task Runner Architecture

## Goal

Keep the runtime small enough to understand end-to-end while preserving:

- 24H unattended execution
- durable resume
- explicit closed-loop routing
- Same Session continuation and Fresh Session recovery
- custom Stages and custom Task producers
- n8n-style visual editing
- CLI / API / YAML List on the same runtime
- future Dynamic Handoff and Discussion scheduling without a second runtime

## Canonical runtime

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

There is one runtime path. UI, CLI, API, YAML List and Dry Run are adapters or callers; none owns a second routing/recovery model.

The main reading path is intentionally short:

1. `runner/workflow_runner.py`
2. `runner/workflow/flow_engine.py`
3. `runner/workflow/stages/executor.py`
4. `runner/runtime/run_state.py`

## Workflow graph

One `stages.<name>` entry is exactly one Stage node.

`flow` is only the ordered list of unique Stage names.

A Stage returns one status:

- `pass`
- `fail`
- `error`

Default routing:

- PASS -> next Stage
- FAIL -> stop
- ERROR -> stop

A Stage may override a result with `routes`:

```yaml
stages:
  execute:
    type: task
    scope: task

  review:
    type: review
    scope: task
    routes:
      fail: execute
      error: stop

flow:
  - execute
  - review
```

Targets are `next`, `done`, `stop`, or another Stage name.

Rollback/loop is just an edge to an earlier Stage. There is no separate repair/recovery object.

Removed runtime concepts must not return:

- recover
- restart_at
- repeat
- max_attempts
- on_exhausted
- replan StageResult
- hidden Plan task/review nodes
- per-Stage retry policy
- execution_mode / RoutingStrategy hierarchy

## Stage

Stage is the only execution/agent extension unit.

Built-ins:

- base
- plan
- task
- review
- ai_validator
- command

A Stage does one responsibility and returns `StageResult`. It does not own retry/session recovery or final graph navigation.

Plan is simply a Stage that produces `Task[]`. Any custom Stage may also declare:

```yaml
produces: tasks
```

Task execution is explicit in the graph with `scope: task`; there are no hidden injected Stages.

Adding a new Stage should require only:

1. its spec
2. its work/result behavior
3. `register_stage(...)`

No retry/recover/session code belongs in the Stage.

## StageExecutor

`StageExecutor` is the single owner of Stage technical reliability:

- hooks / safety
- changed-file tracking
- timeout/backend execution boundary
- Same Session retry
- Fresh Session rotation
- technical retry delay

One public retry setting:

```text
stage_retries = -1
```

`-1` means unlimited technical retries for unattended operation.

Session rule:

```text
attempt
  -> Same Session retry
  -> Fresh Session after the bounded per-session attempt budget
  -> repeat
```

Transient API/service errors remain in the current Stage and use seconds-based bounded exponential delay:

```text
retry_delay -> ... -> retry_max_delay
```

They do not create Workflow edges.

Deterministic configuration/state errors fail closed. `KeyboardInterrupt` and `SystemExit` are never swallowed.

If an attempt already changed maintained project files, the Runner does not blindly repeat it; the semantic graph/review/validator decides what happens next.

## FlowEngine

`FlowEngine` owns only semantic graph progress:

1. read the durable cursor
2. execute the current Stage through StageExecutor
3. persist the latest StageResult
4. resolve PASS/FAIL/ERROR target
5. move the cursor
6. iterate task scope when applicable
7. stop or complete

It does not own backend retry, session rotation, watchdog, subprocess cleanup, or UI behavior.

## StateStore / resume

One authoritative `state.json` stores only durable facts needed to resume:

- run identity / goal / project
- tasks and current task
- workflow position
- task-scope position
- AI session id
- latest StageResult transition
- workflow fingerprint
- completion/activity facts

Technical retry counters are attempt-local, not a second durable recovery state machine.

Correctness target:

```text
uninterrupted run
==
crash at a committed Stage boundary + resume
```

The process supervisor is separate from Stage retry. It owns only process-level reliability such as worker hard crash, hang detection, ownership lock, stop request and orphan cleanup.

## Plugins

There is one plugin discovery boundary: `runner/plugins/registry.py`.

External plugins use the `ai_task_runner.plugins` entry-point group.

A plugin may expose:

- `setup()` for process-level Stage/backend registration before validation
- `register(runtime)` for runtime hooks
- optional CLI/request/YAML config adapters

Workflow code does not branch on concrete plugins.

## Workflow / Prompt assets

Global editable assets share one flat folder:

```text
runner/workflows/
  *.yaml
  *.md
```

Project-local editable assets use the identical shape:

```text
<project>/.ai-task-runner/workflows/
  *.yaml
  *.md
```

Workflow YAML and Prompt Markdown are peer assets. Prompt references are simple relative file names where possible.

There is no System/Custom split and no read-only built-in asset class.

## n8n-style UI

There is one Graph Designer.

Current family:

1. **Linear Workflow with Rollback / Loop**
   - Stage = node
   - normal PASS = next
   - `routes.pass/fail/error` = explicit result edge
   - rollback/loop = edge to an earlier Stage
   - retry/session recovery is not drawn as an edge

Future families:

2. **Dynamic Handoff**
3. **Discussion / Group Chat**

They must reuse the same Stage, StageExecutor, StateStore, Stage registry, plugin boundary, asset layout and Graph Designer.

Do not create a second Runner or a generic mode framework now. When a real Dynamic/Discussion use case exists, add only the smallest scheduler-specific state.

## CLI / API

CLI and API only construct `RunRequest` and call the shared runtime.

They may provide:

- goal/project/workflow
- validator/backend
- timeout/retry settings
- plugin config

They must not own routing semantics.

## YAML List

YAML List is only a batch of child RunRequests.

Each item may override normal RunRequest inputs, but every child still uses the same:

- Workflow loader
- WorkflowRunner
- FlowEngine
- StageExecutor
- StateStore

YAML List has no custom routing or recovery state machine.

## Dry Run

`tool/workflow_dryrun.py` reuses the production Workflow loader and FlowEngine. It mocks only the bottom Stage execution result.

Dry Run must never maintain a second routing/recovery implementation.

## Future Dynamic Handoff

Dynamic Handoff changes scheduling only.

Conceptually:

```text
StageResult + bounded handoff intent
              |
       Dynamic Scheduler
              |
          target Stage
```

Possible additional state when actually required:

- current owner
- allowed targets
- handoff budget
- bounded handoff reason/context

Stage execution/retry/session/safety remains unchanged.

## Future Discussion / Group Chat

Discussion participants are still Stages.

Possible additional state when actually required:

- round
- active participant
- participant order
- moderator/judge
- termination condition
- bounded summary

Again, StageExecutor and StateStore stay shared.

## Maintainability rules

1. Prefer deleting concepts over compatibility.
2. One behavior has one owner.
3. One public capability has one import path.
4. UI/CLI/YAML List are adapters, not runtimes.
5. No hidden Workflow nodes.
6. No duplicate graph/retry models.
7. New Stages contain no retry/recover/session policy.
8. FlowEngine owns semantic navigation only.
9. StageExecutor owns Stage technical reliability only.
10. Future agent models reuse Stage.
11. Add abstraction only when it removes more complexity than it adds.
