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

ERROR is configured with `error_policy.retries` or the global retry setting. A Review with a finite local retry count is shown as `retry -> Skip`; other Stages remain fail-closed after finite exhaustion. There is no ERROR edge, repair/recover/restart_at/repeat/max_attempts/on_exhausted UI contract.

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


## Product workspace

Launching `python ui/main.py` opens `/chats.html`. The previous `/` workspace remains available as a compatibility/runtime surface while the product shell uses three scopes: global navigation (Chats / Library / Settings), a domain context sidebar, and main content.

### Chats

A Chat has a stable UI-owned `chat_id` and root path. Chat metadata and transcripts live under the UI data store and never enter Runner `state.json`. A Chat can be archived without deleting its Tasks or history; missing paths remain readable but cannot accept new work.

Normal Chat turns use the registered backend through a bounded, read-only project-access adapter. A fresh backend session receives bounded durable conversation context; a same-session follow-up receives only the new message. Chat does not create a Workflow run, Stage state, retry loop, or Runner control state.

### Tasks and Task Detail

Tasks have durable UI-owned identity and execution references, but their live status is always projected from the existing Runner runtime. One canonical filesystem execution path may have at most one active Task; browser disabled states are UX only and backend/runtime ownership remains authoritative.

The common New Task form keeps Type, Instruction, Workflow, and Run visible. Optional Title, Goal files, Backend/Model, and workspace isolation are secondary/advanced choices. The resolved Workflow, prompt source, Backend/Model and workspace are frozen into the existing Runner request/script inputs before execution.

Task Detail derives Stop / Resume / Rerun / Continue availability from the canonical runtime projection and current path availability. Terminal execution evidence is copied into bounded Task history before that path is reused, so an older Task never resolves to a newer `state.json`. Deleting a Task removes only its UI-owned Task record; it never performs Git integration.

### Task List

Task List is the UI adapter for the existing YAML List/script runner, not a browser scheduler. Visual items support add/remove/duplicate/reorder, goal-file inputs, inherited or per-item Workflow selection, and an advanced YAML view. Visual/YAML conversion is validated through the same `runner.script` parser used by CLI and preserves supported advanced fields.

Stop and Resume remain the existing script runtime actions. The UI only projects the current item pointer and child evidence; it never manually launches the next item.

### Library and Settings

`/library.html` is the global reusable-asset domain. It exposes Workflow and Prompt assets with explicit Global or Project scope and opens the existing Full Designer / Prompt Editor. The Task Workflow picker reuses the same catalog and visibility metadata.

`/settings.html` contains interface preferences only. Runner, Workflow, Stage and Task execution settings remain with their existing owners.

### Worktree isolation

Main remains the default Task workspace. For a Git project, the Task form may also offer New Worktree or an existing worktree. Every worktree is a separate canonical execution path and therefore a separate ownership domain.

Task-created worktree cleanup is explicit and fail-closed: active Tasks cannot be cleaned up, runtime evidence is archived first, dirty worktrees are not force-removed, and the branch is retained. Task execution never merges, rebases, cherry-picks, or resolves integration conflicts.

## Product workspace tests

Important future-workspace coverage includes:

- `tests/test_chat_turn.py`: bounded fresh/same-session read-only Chat behavior;
- `ui/tests/test_chat_index.py` and `test_chat_messages.py`: durable Chat identity/transcripts and archive/path guards;
- `ui/tests/test_task_index.py` and `test_task_workspace_state.py`: durable Task history, terminal evidence, and historical rerun;
- `tests/test_script_project_root.py`: shared YAML List parsing, inheritance and CLI compatibility;
- `ui/tests/test_task_worktree.py`: explicit non-merging worktree lifecycle;
- `ui/tests/test_future_workspace_browser.py`: Chat → Task / Task List → canonical action browser flow.
