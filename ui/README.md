# Workflow Studio

Workflow Studio is the UI editor for the same YAML Workflow used by CLI/API/runtime. It does not own a second graph model.

## Assets

Global:

```text
runner/assets/workflows/*.yaml
runner/assets/prompts/<category>/*.md
```

Project:

```text
<project>/.ai-task-runner/assets/workflows/*.yaml
<project>/.ai-task-runner/assets/prompts/<category>/*.md
```

`.ai-task-runner.yaml` is project policy/config, never a Workflow file.

## Full Designer

The React Flow page renders:

- START / END as UI-only virtual nodes;
- one real YAML Stage per node;
- PASS / FAIL handles for ordinary Stages;
- one HANDOFF handle with multiple allowed targets for `type: handoff`;
- `scope: task` as a visual group;
- ERROR retry as a Stage setting, never an edge.

Dynamic Handoff targets are arranged horizontally by default. The canvas supports pan/zoom and every node remains draggable. Saved manual positions are browser-local UI state only and do not change YAML semantics.

## Stage parameters

The inspector is catalog-driven from `/api/workflow/catalog`.

Common parameter sections are Content, Execution, Result and Advanced. The UI does not duplicate runtime option defaults when the catalog can provide them.

Session policy:

- `role` — durable reusable Stage-owned Session;
- `main` — primary Runner Session;
- `fresh` — new Session each invocation;
- `auto` — built-in/default behavior.

When switching from `auto` to an explicit policy, Studio removes conflicting legacy session fields. `session_key` is shown only for `auto`; internal `fresh_session_each_run` / `fresh_session_on_start` controls are not exposed as normal UI settings.

## Routing

Ordinary semantic routing is only PASS/FAIL:

```yaml
routes:
  pass: some_stage
  fail: earlier_stage
```

PASS may target `done`; FAIL may target `stop`. Backward routes implement rollback/loop.

Handoff routing is stored as:

```yaml
targets:
  - implementer
  - verifier
  - final_validate
```

ERROR is configured with `error_policy.retries` or the global retry setting. There is no ERROR edge, repair/recover/restart_at/repeat/max_attempts/on_exhausted UI contract.

## Stage Test

The Test tab executes exactly one selected Stage in an isolated temporary Project using the current unsaved graph draft. It reports:

- status;
- output/structured data;
- changed files;
- resolved next target.

It does not continue running the rest of the Workflow and does not modify the real project/YAML.

## Save model

YAML is canonical. Graph Save validates the complete draft through the current Workflow schema before one atomic write. Invalid targets/options/session-policy combinations are rejected without partially modifying the file.

The React/Vite source is under `ui/studio-src`. It is the **only** place developers should edit Full Designer React code. `ui/static/workflow-studio-app` is generated output from `cd ui/studio-src && npm run build`; never hand-edit its HTML/JS/CSS. The existing Python UI server serves that generated output, so end-user machines do not need Node.js.

Full Designer navigation back to the main application must target Workflow Studio explicitly and restore the current Workflow when possible; do not use browser-history-dependent navigation.

## Runtime status

The UI reads runtime/state/control files and uses the same API/runtime ownership boundaries as CLI. It must not infer a running state from stale UI state alone. Stop/resume controls operate through the Runner control contract.

## Tests

Important coverage:

- graph save/round-trip/validation;
- Stage CRUD and asset roots;
- Handoff handles/targets/layout;
- session-policy normalization;
- Stage Test sandbox;
- browser CRUD contracts;
- static Studio source/bundle contract;
- React Studio build in CI.
