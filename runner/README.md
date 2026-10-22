# Runner package map

Start here when reading the runtime.

```text
api.py / bootstrap.py
        |
workflow_runner.py
        |
workflow/flow_engine.py
   |            |             |
execution/stage_executor.py   stages/   runtime/run_state.py
        |
      agent/
```

Main folders:

- `agent/` — AI client, backend adapters, structured output.
- `workflow/` — Workflow YAML loading, graph validation, result routing, dynamic expansion, Stage execution boundary, and Stage implementations.
- `runtime/` — durable state, process execution, events, supervisor.
- `plugins/` — extension discovery and runtime hooks only.
- `assets/` — editable product assets:
  - `workflows/*.yaml`
  - `prompts/common/*.md`
  - `prompts/ralphy/*.md`
  - `prompts/workflow/<name>/*.md` for generated Workflow-owned prompts.
- `config/` — runtime defaults and RuntimeConfig.

Root modules have cross-domain ownership and are intentionally kept visible:

- `api.py` — public RunRequest/API entry.
- `bootstrap.py` — runtime/plugin/event bootstrap.
- `workflow_runner.py` — one-run composition root.
- `prompting.py` — prompt rendering, shared context, immutable protocols.
- `resources.py` — frozen Workflow/Prompt/run resources for durable resume.
- `workspace.py` — project/workspace policy, manifests, protected paths, instructions.
- `script.py` — YAML List adapter.
- `utils.py` — only small helpers reused across several domains.

Public API contract:

- `RunRequest + run()` is the canonical execution entry point used by CLI/UI callers.
- `validate_only()` is a thin Git-unaware deterministic validation-only entry point. It reuses configured Workflow `command` validation Stages through the normal `StageExecutor` / safety hooks, forces source restoration, and returns only `PASS`, `SOURCE_FAIL`, or `TECHNICAL_ERROR` semantics to the caller.
- Runner public APIs accept filesystem/project and validation configuration only. Git branch/worktree/merge queue ownership stays outside `runner/`.

Ownership rule:

> Stage defines work. `workflow/execution/stage_executor.py` owns technical retry/session recovery. FlowEngine owns semantic navigation and dynamic child insertion. StateStore owns durable progress.

Do not add compatibility folders or alternate runtimes. If a helper has one clear owner, keep it with that owner; keep a root helper only when it genuinely serves multiple domains.
