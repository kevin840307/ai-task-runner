# Workflow Builder

Generate the smallest explicit AI Task Runner Workflow for this goal:

{{ goal }}

Use this graph contract:

```yaml
stages:
  work:
    type: base
    prompt: work.md

  review:
    type: review
    routes:
      fail: work

flow:
  - work
  - review
```

Rules:
- One `stages.<name>` entry is exactly one graph/UI node.
- `flow` is only the ordered list of unique Stage names. Never emit flow objects or aliases.
- Routing is only `routes.pass`, `routes.fail`, or `routes.error` to `next`, `done`, `stop`, or another Stage name.
- Never emit recover, restart_at, repeat, max_attempts, on_exhausted, replan, repair, or per-Stage retry fields.
- Technical retry, Same Session continuation, Fresh Session recovery, API delay, watchdog, and resume are Runner-owned; do not model them in Workflow YAML.
- Use only supported Stage types: base, task, review, plan, ai_validator, command.
- If a Plan produces tasks, add explicit task-scoped execute/review Stages with `scope: task`; there are no hidden Plan Stages.
- Validators are ordinary nodes. Route semantic FAIL explicitly when repair is required.
- Workflow YAML and generated Prompt Markdown files publish into one flat asset folder. Prompt references must be simple Markdown file names such as `review_code.md`.
- Create every referenced Prompt file. Do not create nested Prompt folders.
- Keep YAML small. Prefer Stage defaults.
- Do not edit Runner source code.
- Before finishing, read back the generated YAML/Prompts and ensure every route target and Prompt reference exists.

The external validator runs the real Workflow loader and Dry Run matrix. Keep repairing the draft until it passes.
