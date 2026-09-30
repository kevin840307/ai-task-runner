# Workflow Builder

Generate the smallest explicit AI Task Runner Workflow for this goal:

{{ goal }}

Use this graph contract:

```yaml
stages:
  work:
    type: base
    prompt: prompts/work.md

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
- Routing is only `routes.pass` or `routes.fail` to `next`, `done`, `stop`, or another Stage name. ERROR is never a graph edge.
- Optional `error_policy.retries` is common to every Stage; `-1` means unlimited retry. When retries are exhausted, the Runner logs the ERROR and stops at that Stage.
- Never emit recover, restart_at, repeat, max_attempts, on_exhausted, replan, repair, or execution_mode fields.
- Same Session continuation, Fresh Session recovery, API delay, watchdog, and resume are Runner-owned; do not model them as graph nodes or routes.
- Use only supported Stage types: base, task, review, plan, ai_validator, command, handoff, discussion.
- For Dynamic Handoff, use one `type: handoff` Stage with a non-empty `targets` list. Those targets are the Handoff node's multiple graph edges; do not duplicate them as `routes.pass`.
- For Discussion / Group Chat, keep each participant/moderator as a `type: discussion` Stage with a role/session_key. Use an ordinary final `review` Stage as judge; `max_rounds` may bound its FAIL route back to the first participant.
- Selecting the Workflow YAML selects the workflow family. Never emit an execution_mode or a second runtime hierarchy.
- If a Plan produces tasks, add explicit task-scoped execute/review Stages with `scope: task`; there are no hidden Plan Stages.
- Validators are ordinary nodes. Route semantic FAIL explicitly when repair is required.
- Every generated Prompt must be created under the provided Draft Prompt directory and referenced as `prompts/<filename>.md`.
- Keep generated Prompt filenames flat inside the Draft Prompt directory. Publish will move them into `assets/prompts/workflow/<workflow-name>/` and rewrite YAML references automatically.
- Shared built-in Prompt keys such as `common/review.md` may be referenced without copying them.
- Keep YAML small. Prefer Stage defaults.
- Do not edit Runner source code.
- Before finishing, read back the generated YAML/Prompts and ensure every route target and Prompt reference exists.

The external validator runs the real Workflow loader and Dry Run matrix. Keep repairing the draft until it passes.
