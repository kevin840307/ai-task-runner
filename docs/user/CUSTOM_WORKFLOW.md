# Custom Workflow

A Workflow is a YAML graph of Stages. The runtime has one execution model for CLI, API, YAML List and Studio.

## Minimal shape

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

Default PASS moves to the next Stage in `flow`. Override semantic navigation only with:

```yaml
routes:
  pass: another_stage
  fail: earlier_stage
```

Targets may also be `done` or `stop`.

Technical ERROR is not a graph edge. Exceptions, backend failures, timeouts and transient API errors are handled by `StageExecutor`. Configure only retry count when needed:

```yaml
error_policy:
  retries: -1   # unlimited technical retry
```

For a `review` Stage only, a finite local `error_policy.retries` is also the fail-soft contract: once those technical retries are exhausted, Review is skipped and the Workflow continues to the next Stage. Keep an authoritative Validator after such a Review. Other Stage types fail closed when a finite retry budget is exhausted.

Do not use `routes.error`, repair/recover/restart_at/repeat/max_attempts/on_exhausted; they are not part of the current runtime contract.

## Stage types

Built-in types:

- `plan` — produce Task[].
- `task` — execute the current Task.
- `review` — read-only structured completion verdict.
- `ai_validator` — independent AI validation, optionally multiple runs/voting.
- `base` — generic AI-backed Stage.
- `handoff` — dynamically select exactly one allowed next Stage.
- `command` — external command/Python tool Stage.

A custom Python Stage should implement work/result behavior only. Retry/session recovery belongs to StageExecutor.

## Dynamic Handoff

```yaml
stages:
  coordinator:
    type: handoff
    targets: [implementer, verifier, final_validate]
    session_policy: role

  implementer:
    type: base
    prompt: common/dynamic_worker.md
    instructions: Implement the smallest correct change.
    session_policy: role
    mode: write
    track_changes: true
    routes:
      pass: coordinator

  verifier:
    type: base
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

The Handoff Stage only chooses the next target. Roles remain ordinary Stages. Discussion/review-board/triage patterns should be expressed with this same primitive instead of adding another runtime family.

## Session policy

AI-backed Stages expose one explicit policy:

- `role`: durable Session owned by the Stage name; reusable across later handoffs and process resume. This is the Dynamic specialist default.
- `main`: share the Runner primary Session.
- `fresh`: new Session for every invocation. Use for independent validation.
- `auto`: built-in/internal default behavior. Only `auto` may use `session_key`.

Repeated technical failure may rotate the affected role to a fresh Session. Other role Sessions remain intact.

## Multiple runs / voting

Structured AI Stages can run multiple independent calls:

```yaml
review_vote:
  type: review
  session_policy: fresh
  runs: 3
  required_passes: 2
```

## Task scope

Stages with `scope: task` must form one contiguous block. They execute once per current Task. Validation Stages cannot be task-scoped.

## Command Stage

```yaml
validate_file:
  type: command
  result_kind: validation
  command: ["{python}", "validator.py", "--project-root", "{project_root}"]
  routes:
    fail: execute
```

Use `produces: tasks` when a custom command/Python Stage produces Task[] instead of using PlanStage.

## Prompts

Prompt references are category-relative:

- `common/<name>.md`
- `ralphy/<name>.md`
- `workflow/<workflow-name>/<name>.md`

Dynamic ordinary roles normally share `common/dynamic_worker.md`; role-specific behavior belongs in `instructions`. Use a dedicated prompt only when a role truly needs a different protocol/tool contract.

## Testing

Before live execution:

```powershell
python tool/workflow_dryrun.py path/to/workflow.yaml --matrix --json
```

For one Stage only, use Workflow Studio Stage Test or `tool/stage_probe.py`.

Real backend proof is separate from deterministic CI:

```powershell
tool\qwen_live_reliability_0_5h.bat
```

Run the 24H gate only after the short live gate passes.
