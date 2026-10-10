# Workflow Builder

Generate the smallest explicit AI Task Runner Workflow for this goal:

{{ goal }}

Use this graph contract:

```yaml
stages:
  work:
    type: base
    profile: execute
    prompt: prompts/work.md

  review:
    type: base
    profile: review
    prompt: common/review.md
    error_policy:
      retries: 2
    max_failures: 3
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
- Optional `error_policy.retries` is common to every Stage; `-1` means unlimited retry.
- Never emit `scope`, `task_step`, `recover`, `restart_at`, `repeat`, `max_attempts`, `on_exhausted`, `replan`, `repair`, or `execution_mode`.
- Same Session continuation, Fresh Session recovery, API delay, watchdog, and resume are Runner-owned; do not model them as graph nodes or routes.
- General AI behavior uses `type: base` plus one profile:
  - `profile: generic` for a custom AI Stage.
  - `profile: execute` for writable execution behavior.
  - `profile: review` for read-only semantic PASS/FAIL review behavior.
- Do not emit legacy `type: task` or `type: review`.
- Special runtime behavior keeps a dedicated Stage type: `plan`, `ai_validator`, `command`, `handoff`, or a registered plugin Stage.
- A `plan` Stage is a special dynamic producer. It creates its own ordered child Workflow at runtime (currently alternating Execute -> Review for every planned task). Do not predeclare those generated Execute/Review children in YAML.
- Any special Stage may produce `tasks` or `stages` only when that Stage itself defines the child Stage structure. Runner validates and executes the producer-provided child Workflow; Runner never guesses child Stage types.
- Dynamic child Stages run to completion before the parent Workflow continues to the Stage after the producer.
- For Dynamic Handoff, use one `type: handoff` Stage with a non-empty `targets` list. It dynamically chooses exactly one next Stage per decision.
- Dynamic specialist roles remain ordinary `type: base` Stages, normally with `profile: generic` and `session_policy: role`.
- Independent final validators should normally use `session_policy: fresh`.
- For Dynamic Handoff final completion, prefer an `ai_validator` Stage with PASS -> done and FAIL -> the Handoff Stage.
- Discussion / Group Chat is not a supported runtime family or UI mode; do not generate discussion-specific Stage types or state.
- Validators are ordinary nodes. Route semantic FAIL explicitly when returning to repair/execution is required.
- Every generated Prompt must be created under the provided Draft Prompt directory and referenced as `prompts/<filename>.md`.
- Keep generated Prompt filenames flat inside the Draft Prompt directory. Publish will move them into `assets/prompts/workflow/<workflow-name>/` and rewrite YAML references automatically.
- Shared built-in Prompt keys such as `common/execution.md` and `common/review.md` may be referenced without copying them.
- Keep YAML small. Prefer Stage defaults and AI Stage profiles.
- Do not edit Runner source code.
- Before finishing, read back the generated YAML/Prompts and ensure every route target and Prompt reference exists.

The external validator runs the real Workflow loader and Dry Run matrix. Keep repairing the draft until it passes.
