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
- Use only supported Stage types: base, task, review, plan, ai_validator, command, handoff, discussion_controller, discussion.
- For Dynamic Handoff, use one `type: handoff` Stage with a non-empty `targets` list. It dynamically chooses exactly one next Stage per decision; do not add discussion round/session state to it.
- For Dynamic Handoff final completion, prefer an ordinary `ai_validator` Stage with PASS -> done and FAIL -> the Handoff Stage.
- For Discussion / Group Chat, use one `type: discussion_controller` Stage with `targets`, `round_end`, and `max_rounds`. Each participant/moderator remains a `type: discussion` Stage with its own `session_key`, `controller`, and PASS -> controller. The judge remains an ordinary review Stage with PASS -> a separate ordinary `ai_validator` Stage and FAIL -> controller. Final AI Validator PASS -> done and FAIL -> controller. Keep the final validator outside the controller's targets and use `common/discussion_final_validator.md` so the fresh validator receives bounded discussion history.
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
