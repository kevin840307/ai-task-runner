# Custom Workflow Guide

Version: 1.2.63

This guide shows the current Workflow contract. Prefer semantic Stage types and keep YAML limited to behavior that truly changes the SOP. Do not copy implementation-only fields from older examples.

## Custom asset folders

Keep ownership and purpose separate: `system/` is Runner-owned and read-only; user-managed assets live under `custom/` and can be categorized further. The bundled reusable example now lives under `custom/common`. Domain-specific packages can use folders such as `custom/e2e`, `custom/regression`, or deeper nested folders.

```text
runner/workflow/
├─ system/
└─ custom/
   ├─ common/
   └─ e2e/

runner/prompts/
├─ system/ + stages/
└─ custom/
   ├─ common/
   └─ e2e/
```

Workflow Studio discovers Custom Workflow/Prompt assets recursively. Its left catalog groups Custom assets by folder with independent collapse controls; Search still searches across every folder and automatically exposes matching groups. New Workflow/Prompt dialogs can select or create a Custom subfolder.

## 1. Generic linear Workflow

A Workflow does not require Plan or a Validator. If the flow is linear, declare only the Stages you need:

```yaml
stages:
  build:
    type: task
    prompt: prompts/build.md

  smoke:
    type: command
    command: "{python} -m pytest -q"

flow:
  - build
  - smoke
```

When an explicit Workflow is supplied, `validator` may be omitted if the Workflow itself does not use a validation Stage.

## 2. Plan-driven TODO Workflow

`PlanStage` is the built-in AI Task producer. The Workflow owns how every produced TODO runs:

```yaml
stages:
  planning:
    type: plan

  execute:
    type: task

  review:
    type: review
    recover: [repair]

  repair:
    type: task

  validate_file:
    type: command
    result_kind: validation
    command: "{python} {validator} --project-root {project_root} --state-file {state_file} {validator_args}"

flow:
  - planning
  - validate_file
```

A top-level `PlanStage` automatically runs the built-in `Task -> Review -> Repair(on FAIL) -> Review` lifecycle for every produced TODO. Planning is read-only and defaults to optional filesystem inspection: the AI may read the smallest relevant evidence from any host-readable path, including outside the current Project, but is not required to inspect files before planning. `allow_project_read: false` disables those Planning read tools; the legacy option name is retained for compatibility. The built-in Plan lifecycle is YAML-independent and does not look up stages by the names `execute`, `review`, or `repair`. To customize the per-TODO SOP, declare an explicit contiguous `scope: task` block immediately after the Plan (or another task producer).

## 3. Command Stage as a Task producer

Any Stage may produce the public Task JSON contract by declaring `produces: tasks`:

```yaml
stages:
  discover_tasks:
    type: command
    command: "{python} custom_task_producer.py"
    produces: tasks

  execute:
    type: task

  review:
    type: review
    recover: [repair]

  repair:
    type: task

flow:
  - discover_tasks
  - stage: execute
    scope: task
  - stage: review
    scope: task
```

The producer writes valid JSON to stdout:

```json
{
  "tasks": [
    {
      "title": "Implement feature",
      "description": "Make the requested focused change.",
      "deliverable": "The requested behavior works.",
      "acceptance_criteria": ["Relevant verification passes."]
    }
  ]
}
```

The Runner assigns durable Task IDs. The producer must not emit Stage names or workflow topology.

A runnable schema/example pair is provided at:

- `examples/custom_workflow_latest.yaml`
- `examples/custom_task_producer.py`

## 4. Reuse one Stage with different prompts

A Stage definition can be reused many times and overridden at the flow invocation:

```yaml
stages:
  run_prompt:
    type: task

  review:
    type: review

flow:
  - stage: run_prompt
    prompt: prompts/design.md
  - stage: review
    prompt: prompts/review_design.md
  - stage: run_prompt
    prompt: prompts/implementation.md
  - stage: review
    prompt: prompts/review_implementation.md
```

## 5. Command Stage

Use `command` for user/project Python without importing it into the 24H Runner process:

```yaml
check:
  type: command
  command: "{python} stages/check.py --mode strict"
```

Use `command` for an argv-based external process:

```yaml
test:
  type: command
  command: "{python} -m pytest -q"
```

`command` is the single process execution boundary for Python scripts, File Validator execution, and arbitrary argv.

## 6. Recovery and repetition

Keep recovery declarative:

```yaml
review:
  type: review
  recover: [repair]

flow:
  - stage: review
    repeat: 3
```

`restart_at` may jump to the same or an earlier top-level Stage. `fresh_after_same_failures` is normally unnecessary for `type: review` because Review already owns the default semantic-failure threshold; specify it only when intentionally overriding that policy.

### Bounded FAIL -> recover -> retry

Every FlowNode may optionally bound semantic recovery:

```yaml
flow:
  - stage: grill
    recover: [repair_plan]
    max_attempts: 3
    on_exhausted: continue
```

`max_attempts` counts executions of that FlowNode that return a parsed semantic `FAIL`. Attempts 1..N-1 run `recover` and then retry the same FlowNode. If attempt N still FAILs, recovery is not run again. `on_exhausted: continue` advances to the next FlowNode; `on_exhausted: fail` stops. If `on_exhausted` is omitted while `max_attempts` is set, the safe default is `fail`. A PASS clears the counter. After the FlowNode has moved forward, any later restart/re-entry starts a new gate cycle at attempt 1. Technical `ERROR` results do not consume this semantic attempt budget.

Both fields are optional. If `max_attempts` is omitted, recovery behavior is exactly the legacy/current behavior with no new limit. `on_exhausted` is valid only with `max_attempts`; `max_attempts` requires `recover`, and it cannot be combined with `repeat` or `restart_at` on the same FlowNode.

> YAML FlowNode `max_attempts` is not the CLI/API `max_attempts`. The CLI/API option controls same-session backend recovery; this YAML option bounds semantic `FAIL -> recover -> retry` cycles for one FlowNode.

### Recovery / retry YAML parameter reference

| Parameter | Scope | Meaning |
| --- | --- | --- |
| `retry` | Stage execution | Technical/error retry budget inside one Stage execution. It is not semantic FAIL recovery. |
| `runs` | Stage execution | Run the same Stage multiple times in one entry, typically for independent voting. |
| `required_passes` | Stage execution | PASS votes required when `runs > 1`. |
| `recover` | FlowNode routing | Stages to execute after a semantic FAIL before re-entering the failed FlowNode. |
| `repeat` | FlowNode routing | Existing bounded-recovery behavior; kept for compatibility. Do not combine with `max_attempts`. |
| `max_attempts` | FlowNode routing | Optional number of semantic FAIL attempts in one gate cycle. Omitted = existing behavior with no new limit. |
| `on_exhausted` | FlowNode routing | `continue` or `fail` after `max_attempts` is exhausted. Default: `fail`. |
| `fresh_after_same_failures` | FlowNode/session policy | Rotate that Stage to a Fresh Session after the same semantic failure repeats N times. |
| `restart_at` | FlowNode routing | On FAIL, jump to the named same/earlier top-level Stage. |

`max_attempts` counts gate entries, not repairs. With `max_attempts: 3`, at most two recovery runs occur before the third FAIL is exhausted.

## 7. YAML task-list mode

Each script item may use a different project, validator, validator arguments, Workflow, backend/runtime timeouts/retry policy, and Final-AI quorum. Task-scoped YAML options use the same `RuntimeConfig` validation as CLI/API:

```yaml
- goal_file: projects/a/prompt.md
  project_root: projects/a
  validator: projects/a/validation.py
  validator_args: [--env, A]

- goal_file: projects/b/prompt.md
  project_root: projects/b
  workflow_file: workflows/custom.yaml
```

If an item provides an explicit `workflow_file`, `validator` is optional. If there is no explicit Workflow, a validator is required so the Runner can select the appropriate built-in File/AI/Mixed Workflow.

## 8. UI / AI-generated Workflow flow

External UI code does not need to import Runner internals. Use files plus JSON tools as the boundary:
For runtime monitoring, a detached local UI may also import no Runner modules: read the configured work directory's `state.json` for current display state and `stream.log` for the latest bounded subprocess output. Monitoring files are read-only and do not replace the execution API or Workflow validation tools.


```text
Generate/Edit YAML
    -> workflow_catalog.py
    -> production loader validation
    -> workflow_dryrun.py --json
    -> publish
```

Useful commands:

```bash
python tool/workflow_catalog.py
python tool/workflow_dryrun.py path/to/workflow.yaml --json
```

Prompt files remain Markdown and user Python Stages remain ordinary `.py` files, so an external UI can CRUD Workflow/Prompt/Python resources without importing Pipeline or StageExecutor.

### Command syntax

`command` accepts either a simple command string or an argument list. Prefer the string form for ordinary commands, for example `command: "{python} D:/validation.py --asd sss"`. Use the list form when argument boundaries or nested quoting are complex. `result_kind: validation` turns a command into an external validation gate; validation commands default to cleaning `validator-reports`, while `clean_work: []` explicitly disables that cleanup.

### Visual Editor coverage

Workflow Studio Visual mode exposes the common Stage and Flow routing controls, including `max_attempts`, `on_exhausted`, `runs`, and `required_passes`. Recovery fields are grouped and summarized as an execution Behavior instead of duplicating long help text under every field. `continuation_prompt` remains an intentional YAML-only advanced override.

## Ralphy-style: Fresh Task + required AI validation

The bundled custom workflow `runner/workflow/custom/common/ralphy_ai_validate.yaml` is a minimal two-stage loop:

```text
Ralphy Task (fresh session, write)
        ↓
AI Validator (fresh session, read-only)
        ├─ PASS → complete
        └─ FAIL → Fresh Ralphy Task → validate again
```

```yaml
stages:
  ralphy:
    type: task
    prompt: custom/common/ralphy.md
    fresh_session_on_start: true

  validate_ai:
    type: ai_validator
    validator: ai
    fresh_session_on_start: true
    runs: 1
    required_passes: 1
    recover: [ralphy]

flow:
  - ralphy
  - validate_ai
```

There is no Plan, Review, or bounded semantic recovery. A semantic FAIL from `validate_ai` routes through a fresh `ralphy` execution session and then re-enters a fresh validator session. The workflow does not complete normally until AI validation passes. Technical/API failures still use the Runner's normal retry and fail-closed policies.
