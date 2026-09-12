# AI Task Runner

Version: 1.2.66

Example launchers are isolated by default: `examples\run_examples.bat` and every `examples\*/run_example.bat` copy only the selected example (or the examples set for `--all`) into a fresh `<repo>\.example_runs\...` workspace before running, so canonical fixtures remain unchanged between tests.


Runtime completion rule: a normal internal return is not treated as completion unless persisted state confirms both `completed=true` with `stage=completed`. Regression workflows still end at their configured validator gate; explicit generic workflows may complete without a validator when every FlowNode succeeds. In the built-in regression profiles, completion still means **Final Validator PASS**. The canonical `runner.api.run()` resumes unfinished state automatically; the CLI only adds worker-process crash isolation. Recoverable task failures escalate by repeated identical progress evidence (same session -> fresh session -> replan), not by total attempt count.

The runner owns orchestration; backends, plugins, prompts, and validators provide bounded capabilities behind explicit contracts.

A small reusable Python orchestrator for long-running AI coding tasks. It separates AI work from deterministic validation, keeps resumable state, isolates the current TODO, and tolerates model/CLI failures without embedding project-specific logic in the Runner.

## Key properties
- Bounded structured Stage handoff: recover prompts can use `previous.data` (for example `reason` / `missing_items`) without replaying unbounded prior context.
- Qwen and OpenCode backends; full task prompts for both backends are stdin-only, with backend-owned session/permission handling.
- Declarative Planning: Plan produces the durable TODO list directly; planning failures use the shared same-session -> fresh-session -> replan recovery path, with no independent Understand/Judge Stage.
- TODO execution runs the built-in Task -> Review lifecycle for each task. Same-task failures prefer the same session and rebuild only when needed; timeout recovery uses a stable semantic failure key so volatile backend output such as sandbox/container IDs cannot reset the failure streak; Review uses an independent read-only client/session.
- Bundled Task/Review prompts use bounded `continuation_prompt` handoffs after the same session has already seen the full Stage contract, so later TODOs/repair evidence do not resend Goal/rules; first and fresh/rebuilt calls still receive complete necessary context.
- Deterministic final validator as the hard correctness gate; optional fresh-session Final AI voting can be used alone or after the hard gate.
- Retry/resume, session rebuild, no-progress recovery, protected paths, Git write guard, JSONL events, one canonical Python/CLI/UI API boundary, linear Workflow YAML, and YAML script mode with optional per-item `project_root`, `goal_file`, and `workflow_file`.
- Worker crash/interrupt cleanup follows each durable Run work directory, including YAML List children, so orphan AI/sandbox processes are not left behind; all subprocess stdout paths are bounded, and `KeyboardInterrupt`/`SystemExit` never enter Stage retry/recovery.
- Resume treats a valid project `state.json` as authoritative and uses the temp backup only when the primary state is missing or invalid, preventing stale-backup rollback after a crash window.
- UI-ready extension boundary: owner-module editor/catalog APIs (`runner.resources`, `runner.workflow.loader` / `registry`, `runner.prompts.loader`), installed Stage/backend registration before Workflow validation, external runtime Plugins, atomic Workflow/Prompt editing, and per-Run Workflow/Stage-prompt/goal/final-AI-prompt snapshots.
- Detached local UI may stay fully outside Runner imports: read the project work directory for runtime visibility (`state.json` for current durable status, `runner-process.json` for the active Supervisor/Worker PID identity, `stream.log` for the latest bounded subprocess output, and `log.txt` / `debug/` for diagnostics). `stream.log` and `runner-process.json` are visibility/control metadata only and never decide Workflow semantics. A detached UI may request a graceful runtime stop by creating `.ai-task-runner/stop.request`; the Supervisor consumes it, terminates the current Worker/owned child process, and exits with code 130. Resume/rerun are not request files: launch the CLI again with `--resume` or `--force-new`.
- Generic `command` Stage owns all subprocess execution, including user/project Python and deterministic file validation.
- Shared AI-result parser: lenient JSON envelope, strict stage payload/schema.
- Bounded debug history with current/last prompt-result files.
- Project policy in `<project-root>/.ai-task-runner.yaml`; the policy file protects itself automatically.

## Quick start
```bat
python ai_task_runner.py --goal-file "prompt.md" --project-root "." --validator "validation.py"
```

Validator-specific arguments are repeatable:
```bat
python ai_task_runner.py --goal-file "prompt.md" --project-root "." --validator "validation.py" --validator-arg "--fab" --validator-arg "FAB23"
```
The Runner invokes the validator as `python validation.py --project-root <root> --state-file <state> --fab FAB23`. Do not combine validator arguments into the `--validator` path string.

Mixed hard + AI validation:
```bat
python ai_task_runner.py --goal-file "prompt.md" --project-root "." --validator "validation.py" --ai-validator-prompt-file "ai_validation.md" --ai-validator-count 3
```
The file validator must PASS first; then 3 fresh AI sessions vote independently. Strict majority is the default; `--ai-validator-required-passes` can require an explicit threshold such as 3/3.

## Documentation map
- [Full documentation index](docs/INDEX.md) / [中文索引](docs/INDEX.zh-TW.md)
- [繁體中文首頁](README.zh-TW.md)
- [Design](docs/design/DESIGN.md) / [設計](docs/design/DESIGN.zh-TW.md)
- [Architecture](docs/design/ARCHITECTURE.md) / [架構](docs/design/ARCHITECTURE.zh-TW.md)
- [User Guide](docs/user/USER_GUIDE.md) / [使用指南](docs/user/USER_GUIDE.zh-TW.md)
- [CLI Reference](docs/user/CLI_REFERENCE.md) / [CLI 參考](docs/user/CLI_REFERENCE.zh-TW.md)
- [Python API Reference](docs/user/API_REFERENCE.md) / [API 中文](docs/user/API_REFERENCE.zh-TW.md)
- [Prompt / Session Contract](docs/design/PROMPT_SESSION.md) / [Prompt / Session 中文](docs/design/PROMPT_SESSION.zh-TW.md)
- [State / Events](docs/design/STATE_EVENTS.md) / [State / Events 中文](docs/design/STATE_EVENTS.zh-TW.md)
- [Protection / Safety](docs/operations/SECURITY_PROTECTION.md) / [保護與安全](docs/operations/SECURITY_PROTECTION.zh-TW.md)
- [Operations](docs/operations/OPERATIONS.md) / [24H 運行與故障排查](docs/operations/OPERATIONS.zh-TW.md)
- [Project / Maintainer Guide](docs/development/PROJECT_GUIDE.md) / [專案 / 維護者指南](docs/development/PROJECT_GUIDE.zh-TW.md)
- [Test Matrix](docs/development/TEST_MATRIX.md) / [測試矩陣](docs/development/TEST_MATRIX.zh-TW.md)
- [Validator templates](docs/validator_templates/README.md) / [Validator 範本](docs/validator_templates/README.zh-TW.md)
- [Examples](examples/README.md) / [範例](examples/README.zh-TW.md)
- [Smoke](smoke/README.md) / [Smoke 測試](smoke/README.zh-TW.md)

## Development contract
See `AGENTS.md` and `QWEN.md`. The core rules are: no project-specific hardcode, one shared implementation for the same behavior, minimum production code, high readability, and no duplicated generic logic.

## Validator feedback and external validators
Validator feedback stored in state is capped at 20,000 characters, preserving both the beginning and end of long logs. Reusable validator templates live in `docs/validator_templates/`. `external_command_validator.py` wraps an exe, bat, jar, or other CLI and can copy external log folders into `.ai-task-runner/validator-reports/external-command/`.

## Agent rule files
- Qwen Code: `QWEN.md`
- OpenCode: `AGENTS.md`

OpenCode's official project rule filename is `AGENTS.md`, not `AGENT.md`.

### Optional Loop context compression
Disabled by default. Enable only for Loop Detection recovery:
`--loop-context-compress --loop-context-compress-threshold 50`
The threshold is a context-usage percentage (0-100). If the backend cannot report current context usage, compression is skipped. Qwen uses its session `/compress-fast` capability; normal retries and transient API errors do not trigger it.

YAML task items may also set `loop_context_compress: true` and `loop_context_compress_threshold: 50`.

## Flow engine architecture

The runner uses a small YAML-driven flow pipeline. `StageExecutor` owns shared retry, Hook, semantic progress reporting, and exception handling. Each Stage performs one job and returns only `StageResult` facts/effects. `FlowNode` owns static YAML routing such as `recover`, `restart_at`, and `scope`. `PlanStage` is the built-in Task producer and automatically enters the built-in `Task -> Review -> Repair(on FAIL) -> Review` per-TODO lifecycle, so normal Plan-driven YAML does not repeat those flow nodes. Other Stages may still declare `produces: tasks`; advanced/custom producers can use an explicit contiguous `scope: task` block when they need a custom per-TODO SOP. `task` / `review` profiles may also be reused as ordinary top-level linear Stages when a custom Prompt does not depend on TODO data; in that mode they do not mutate durable TODO state.

Cross-cutting features stay outside the flow: status events feed UI/logging/diagnostics, while Git restrictions, protected files, read-only enforcement, and optional loop-context compression register as plugins. Core stages and the AI client do not import those concrete plugins.


## Stage execution architecture

`YAML FlowNode -> StageExecutor -> Stage.run() -> StageResult -> recovery / next FlowNode`

Unified execution rules:
- API/service failures use exponential backoff inside the AI client for one configured wait window (default 1 hour) and do not count as Stage failures. If a window is exhausted, canonical `runner.api.run()` resumes durable direct/YAML state and opens another window until the task passes.
- Real failures retry in the same session using a short stage-aware continuation prompt containing only the stage identity, new failure evidence, and required next action; after the configured retry count (default 2), StageExecutor starts a fresh session.
- Repeated identical failures in the fresh session return `replan`, causing the default flow to start a fresh planning session and generate a new plan. A Stage may set the shared 1-based YAML `restart_at` option to restart from a specific current/earlier top-level Stage instead. Different failures reset the failure streak.
- A write attempt that changed project files counts as progress and is handed to the next review/validation Stage instead of being retried as a failure.
- Review may skip after its retry budget is exhausted; the skip is recorded and Final Validator remains the completion gate.
- Task producers store only durable TODO content (`title`, `description`, `deliverable`, `acceptance_criteria`). `PlanStage` is one built-in producer; `command` or future Stage types can opt into the same effect with `produces: tasks`. For Plan-driven flows, the loader expands the built-in `Task -> Review -> Repair(on FAIL) -> Review` task lifecycle internally and `workflow_position` remains the durable execution cursor. Explicit `scope: task` is reserved for advanced/custom task producers or custom per-TODO SOPs.


Stages perform one attempt only. `StageExecutor` owns hooks/semantic progress/change tracking; retry and routing stay in Flow. Generic `BaseStage` instances are reusable, while special behavior uses dedicated semantic AI stages such as `PlanStage`; subprocess work uses `CommandStage`.

Normal AI work is declarative: YAML contains only `stages` and `flow`. `stages` defines reusable nodes; `flow` composes them and may override fields such as `prompt`, `retry`, or `skip` per invocation. Generic AI-backed nodes use `BaseStage`; `type` defaults to `base`, so it is normally omitted. `type` is written only for specialized behavior such as `plan`, `task`, `review`, `ai_validator`, `command`, or a custom Stage class.

```yaml
stages:
  security_check:
    status: Security review
    prompt: stages/workflow_prompt.md
    instructions_file: prompts/security_check.md

flow:
  - security_check
```

A genuinely new behavior adds one Stage class exposing `spec_class`, then one `register_stage("type", StageClass)` entry. The registry is only `type -> class`; retry, prompt, recovery, validation capability, and composition belong to YAML. Planning-specific computed context remains owned by `PlanStage`. Prompt variables are centralized by `runner/prompts/context.py`; templates use Jinja `StrictUndefined` and must not read runtime internals directly.


### Flow labels

`status` belongs to the reusable Stage definition. An optional FlowNode `label` names the concrete work for that occurrence without changing Stage behavior:

```yaml
stages:
  run_prompt:
    type: task
    status: AI running skill

flow:
  - stage: run_prompt
    label: Project Documentation
    prompt: skills/project_documentation.md
```

Runner events keep `status=AI running skill` and expose `label=Project Documentation`; console/UI detail uses the label. Omitting `label` preserves the existing behavior.


### Repeated semantic-failure escape

A FlowNode may override `fresh_after_same_failures: N`. Only repeated, successfully parsed semantic `FAIL` results count. When the same failure fingerprint reaches N, Runner drops only that Stage's AI session, runs the existing `recover`, then re-runs the Stage with its full prompt in a fresh session. Backend/API/parser/timeout errors do not count and different semantic failures reset the count. `ReviewStage` owns the semantic default `2` whenever it has recovery; other Stage types remain opt-in. This keeps system YAML small while preserving an explicit override when a Workflow needs a different threshold.

A FlowNode may also opt into bounded semantic recovery with `max_attempts: N` plus `on_exhausted: continue|fail`. Only parsed semantic FAILs count. Attempts before N run `recover` and retry the same FlowNode; the Nth FAIL does not run recovery again and follows `on_exhausted`. PASS clears the counter, and after forward progress any later re-entry starts again at 1. Omitting `max_attempts` preserves the existing unbounded/current recovery behavior. This YAML field is separate from the CLI/API `max_attempts` used for same-session backend recovery.

## Workflow Dry Run

Use `tool/workflow_dryrun.py` to validate whether a `workflow.yaml` can reach closure without calling a real agent. The tool reuses the production Workflow Loader, Pipeline, StageResult, and Stage finish and result reducers, and mocks only the bottom-level Stage execution result, so it does not create a second workflow engine.

```bat
python tool\workflow_dryrun.py runner\workflow\system\mixed.yaml --scenario dryrunexample\system_mixed_scenario.yaml
dryrunexample\run_dryrun.bat
```

`dryrunexample/` covers a system workflow plus a concise semantic custom workflow with `task`, `review`, recover, and `repeat`. Dry Run is an external tool; removing it and its examples does not change Runner Core behavior.
Auto failure matrix:

```bat
python tool\workflow_dryrun.py runner\workflow\system\mixed.yaml --matrix
python tool\workflow_dryrun.py runner\workflow\system\mixed.yaml --matrix --json
```

`--matrix` generates deterministic happy, semantic-failure, and technical-error cases for the Workflow's real `recover`, `repeat`, `restart_at`, and `fresh_after_same_failures` routing. Recoverable FAIL paths must converge; FAIL without recovery and technical ERROR paths must stop safely instead of accidentally entering semantic repair. Recovery-stage ERROR is also exercised through its reachable parent-failure path. For semantic-failure session rotation it verifies that the configured fresh-session threshold actually fires. The JSON contract reports each case's expected/completed outcome plus task-producer/task-scope/review/validation features and is suitable for CI, UI Save/Import gates, Workflow Builder publication, and reliability preflight. Invalid Workflow options still fail through the production Workflow Loader/schema before simulation; Dry Run does not maintain a duplicate schema.

For external UI/AI editors, `python tool/workflow_catalog.py` emits the data-only Stage/flow schema as JSON, and `python tool/workflow_dryrun.py workflow.yaml --json` emits a machine-readable closure result. The UI can therefore CRUD YAML/MD/PY without importing Runner Core.



### Command-backed Stages
`command` is the single child-process Stage for Python scripts, validators, and arbitrary argv. It shares one boundary for cwd, timeout, output capture, process-tree cleanup, and exit-code semantics.

## Local UI

A lightweight GPT-style local UI is available as a separate entry point:

```bash
python ui/main.py
```

The UI does not import Runner Core. It launches the existing CLI with hidden-console flags on Windows and reads the Project `.ai-task-runner` runtime files. The current UI is Workflow-task oriented rather than a general chat client: Run/Stop/Continue/Reset/Rerun operate on one Project task history. Workflow Studio exposes immutable **System** assets under `runner/workflow/system` / `runner/prompts/system|stages`, editable **Custom** assets under `runner/workflow/custom/**` / `runner/prompts/custom/**`, Project-local assets, and an AI Workflow Builder. Custom assets are organized by folder (for example `custom/common`, `custom/e2e`) and the Studio renders those folders as collapsible groups while keeping global Search available. All Workflow writes/imports/generation are validated before publication.
Runner `ConsoleObserver` also writes `.ai-task-runner/console-view.json` from the same semantic `LiveUI` state used by the CLI. The browser renders that shared Cycle/Progress/status/TODO view (with a durable-state fallback), so Plan-produced TODOs and CLI task markers stay aligned across CMD and Web UI; the runtime view is intentionally static between polling updates, so delayed polling cannot be mistaken for a frozen animation. Project rows expose live RUN/IDLE/DONE/INT/STOP state without opening each Project.

The Workflow Builder is self-contained under `workflow_builder/` (`workflow_builder.yaml`, `prompt.md`, `validation.py`, `run.py`, `publish.py`) and can be called from CLI/other integrations without importing or changing Runner Core. UI uses a dedicated Prompt + owned **Folder + Filename** → status-only generation → editable Draft review → explicit Save flow. Folder/Filename are chosen before Generate and restored with the single active job; no Workflow asset exists before validated publication. Save revalidates and publishes into the chosen owned folder. The System workflow file is only a compatibility mirror for the unchanged named-workflow registry.

Workflow Generator jobs are UI-owned and Project-independent. The UI keeps exactly one active generation under `ui/data/workflow-builder/active.json`; refreshing or reopening the browser restores that same generating/ready job. The Generator shows its temporary workspace path. Generated YAML and Prompts are editable while still a Draft, and only Save publishes a real Workflow. Cancel/Discard returns to a freshly rendered Workflow catalog without requiring a browser refresh.

## License

This project is released under the **Zero-Clause BSD (0BSD) License**. You may use, copy, modify, distribute, and use it commercially without fee. See `LICENSE` for the full terms and warranty disclaimer.

### Local environment check

Use **Run options → Check environment** in the UI, or run `python tool/environment_check.py`. The check is side-effect free and reports required Python/Runner prerequisites plus optional Qwen/OpenCode PATH availability.

### UI themes

The local UI defaults to **Teal + System** and also provides Deep Blue, Violet, Amber, and Rose palettes with System/Light/Dark appearance modes. Theme preferences are presentation-only and do not affect Runner, Workflow, recovery, or backend behavior.

### UI navigation and Workflow visibility

- **Workflows** is a global page. Clicking a Project in the sidebar selects that Project and opens its **Tasks** view directly.
- Leaving the global Workflow Studio for Tasks keeps the current global Workflow draft in memory; destructive operations still keep the existing unsaved-change guards.
- Workflow Studio **More → Hide from Tasks / Show in Tasks** controls whether a Workflow appears in the Tasks Workflow selector. This is UI metadata stored locally in `ui/data/workflow_visibility.json`; it does not change Runner Workflow YAML, CLI behavior, or dry-run semantics.

### Project Workflow storage

Project-owned Workflows are discovered only below `<project>/.ai-task-runner/workflows/`. Each Workflow package owns one folder with separate `workflow/` and `prompts/` subfolders, for example `<project>/.ai-task-runner/workflows/regression/workflow/regression.workflow.yaml` and `<project>/.ai-task-runner/workflows/regression/prompts/review.md`. The project policy file `.ai-task-runner.yaml` remains Runner configuration only and is never treated as a Workflow discovery marker.

## Planning bounded discovery and loop recovery

Planning now treats discovery as a bounded activity rather than a prerequisite for every task. Self-contained/greenfield work may plan immediately; existing-code work starts from the smallest goal-relevant entry point and expands only from concrete evidence. A confirmed missing file/symbol is not searched repeatedly without new evidence.

For backend loop signals such as `consecutive_identical_tool_calls` or `turn_tool_call_cap`, Planning gets at most one same-session retry. If the same loop class repeats, Runner rotates that Planning Stage to a fresh session while preserving durable workflow state. Dynamic backend turn/context text is normalized so the escalation counter cannot be reset by noisy stderr. This policy is intentionally Planning-specific; normal task/review retry semantics are unchanged.

Validation coverage: unit tests lock the retry sequence (`initial -> same -> fresh`), prompt-contract tests lock bounded discovery, `workflow_dryrun.py --matrix` continues to validate deterministic workflow routing/recovery, and `qwen_live_reliability.py` includes the loop classification/recovery policy preflight before live probes. The live gate also verifies expired-session recovery into a Fresh Session, real HTTP `429` / `502` / `503` and disconnect recovery through the Qwen endpoint proxy, YAML List restart/resume with item-level validator/quorum options, and an opt-in single-process YAML endurance burst. The 24H preset keeps the wall-clock soak as the primary endurance signal; the burst complements it by checking same-process state/resource accumulation.
