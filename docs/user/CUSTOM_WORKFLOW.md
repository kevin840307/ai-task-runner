# Custom Workflow

A Workflow is one ordered graph of Stages. CLI, API, YAML List, Studio, Dry Run, and dynamic child Workflows all use the same runtime.

## Minimal AI Workflow

```yaml
stages:
  execute:
    type: base
    profile: execute

  review:
    type: base
    profile: review
    error_policy:
      retries: 2
    max_failures: 3
    routes:
      fail: execute

  final_validate:
    type: ai_validator
    validator: ai
    session_policy: fresh
    routes:
      fail: execute

flow:
  - execute
  - review
  - final_validate
```

`type: base` is the general AI Stage. Choose a profile instead of a separate Execute/Review Stage type:

- `profile: generic` — custom AI behavior.
- `profile: execute` — writable execution behavior, default prompt `common/execution.md`.
- `profile: review` — read-only structured PASS/FAIL review, default prompt `common/review.md`.

The removed `type: task`, `type: review`, `scope`, and `task_step` contracts are not supported.

## Routing and technical recovery

PASS defaults to the next Stage in `flow`. Semantic navigation uses only:

```yaml
routes:
  pass: another_stage
  fail: earlier_stage
```

Targets may also be `done` or `stop`.

Technical ERROR is never a graph edge. Exceptions, backend failures, timeouts, transient API failures, partial writes, Same Session retry, Fresh Session recovery, and backoff are owned by `runner/workflow/stage_executor.py`.

```yaml
error_policy:
  retries: -1
```

A finite local retry on an AI Stage with `profile: review` is fail-soft: technical ERROR retries are exhausted, then the Workflow continues to the next Stage. Semantic Review FAIL still follows `routes.fail`; `max_failures` may cap consecutive semantic FAIL results.

## Special Stage types

Built-in special types have runtime behavior that cannot be represented by an AI profile:

- `plan` — plans Tasks and produces its own dynamic child Workflow.
- `ai_validator` — independent AI validation, optionally multiple runs/voting.
- `command` — external command/Python Stage.
- `handoff` — dynamically selects exactly one allowed next Stage.
- registered plugin Stage types.

A custom Python Stage should implement work/result behavior only. Retry/session recovery belongs to StageExecutor.

## Dynamic child Workflows

Any Stage may return `tasks` or `stages`. The producer Stage must also define the child Stage structure; Runner never guesses which child Stage types to create.

Execution semantics are always:

```text
A -> B -> C -> D

C returns tasks/stages

A -> B -> C
          -> child-1
          -> child-2
          -> ...
          -> D
```

All children run through the same FlowEngine and StageExecutor, including retry/recover/routing/session policy. Expanded definitions are persisted in RunState so Resume continues the already-expanded child Workflow without rerunning C merely to reconstruct it.

PlanStage currently converts its validated Tasks into an ordered child Workflow:

```text
task-1 Execute -> task-1 Review
-> task-2 Execute -> task-2 Review
-> ...
```

This Plan behavior belongs to PlanStage, not Runner. Another special Stage may generate a different child Workflow.

A `tasks` producer returns both validated task data and child Stage definitions. Child definitions bind to Tasks with `task_id`; at least one child for each Task must set `task_complete: true`.

```json
{
  "tasks": [
    {
      "id": "inspect",
      "title": "Inspect project",
      "description": "Inspect the project.",
      "deliverable": "Findings",
      "acceptance_criteria": ["Findings are complete."]
    }
  ],
  "stages": [
    {
      "name": "inspect_execute",
      "type": "base",
      "profile": "execute",
      "task_id": "inspect"
    },
    {
      "name": "inspect_review",
      "type": "base",
      "profile": "review",
      "task_id": "inspect",
      "task_complete": true,
      "routes": {"fail": "inspect_execute"}
    }
  ]
}
```

A `stages` producer may return only a non-empty `stages` array when no durable Task objects are needed.

## Dynamic Handoff

```yaml
stages:
  coordinator:
    type: handoff
    targets: [implementer, verifier, final_validate]
    session_policy: role

  implementer:
    type: base
    profile: generic
    prompt: common/dynamic_worker.md
    instructions: Implement the smallest correct change.
    session_policy: role
    mode: write
    track_changes: true
    routes:
      pass: coordinator

  verifier:
    type: base
    profile: generic
    prompt: common/dynamic_worker.md
    instructions: Independently verify tests and evidence.
    session_policy: role
    readonly_safety: observe
    routes:
      pass: coordinator

  final_validate:
    type: ai_validator
    validator: ai
    session_policy: fresh
    routes:
      pass: done
      fail: coordinator

flow:
  - coordinator
  - implementer
  - verifier
  - final_validate
```

The Handoff Stage only chooses the next allowed target. Target roles remain ordinary Stages.

## Session policy

AI-backed Stages expose one session policy:

- `role` — durable Session owned by the Stage name.
- `main` — share the Runner primary Session.
- `fresh` — new Session for every invocation; recommended for independent validation.
- `auto` — built-in/default behavior.

Repeated technical failure may rotate only the affected Stage to a fresh Session.

## Multiple runs / voting

```yaml
review_vote:
  type: base
  profile: review
  session_policy: fresh
  runs: 3
  required_passes: 2
```

## Command Stage

```yaml
validate_file:
  type: command
  result_kind: validation
  command: ["{python}", "validator.py", "--project-root", "{project_root}"]
  routes:
    fail: execute
```

A command/plugin Stage may declare `produces: tasks` or `produces: stages`, but its output must provide the corresponding producer-defined child Workflow.

## Prompts

Prompt references are category-relative:

- `common/<name>.md`
- `ralphy/<name>.md`
- `workflow/<workflow-name>/<name>.md`

## Testing

Before live execution:

```powershell
python tool/workflow_dryrun.py path/to/workflow.yaml --matrix --json
```

For one Stage only, use Workflow Editor Stage Test or `tool/stage_probe.py`.

Real backend proof is separate:

```powershell
tool\qwen_live_reliability_0_5h.bat
```

Run the 24H gate only after the short gate passes.
