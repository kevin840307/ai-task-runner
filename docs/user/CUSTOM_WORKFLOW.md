# Custom Workflow Guide

Version: 1.2.61

This guide shows the current Workflow contract. Prefer semantic Stage types and keep YAML limited to behavior that truly changes the SOP. Do not copy implementation-only fields from older examples.

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

A top-level `PlanStage` automatically runs the standard `execute -> review` SOP for every produced TODO. Keep `execute` / `review` definitions only when overriding their defaults (for example Review recovery). Explicit `scope: task` is still available for non-Plan producers or a deliberately custom per-TODO SOP.

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

## 7. YAML task-list mode

Each script item may still use a different project, validator, validator arguments, and Workflow:

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
