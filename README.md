# AI Task Runner

Version: 1.2.61

Example launchers are isolated by default: `examples\run_examples.bat` and every `examples\*/run_example.bat` copy only the selected example (or the examples set for `--all`) into a fresh `<repo>\.example_runs\...` workspace before running, so canonical fixtures remain unchanged between tests.


Runtime completion rule: a normal internal return is not treated as completion unless persisted state confirms both `completed=true` with `stage=completed`. Regression workflows still end at their configured validator gate; explicit generic workflows may complete without a validator when every FlowNode succeeds. In the built-in regression profiles, completion still means **Final Validator PASS**. The canonical `runner.api.run()` resumes unfinished state automatically; the CLI only adds worker-process crash isolation. Recoverable task failures escalate by repeated identical progress evidence (same session -> fresh session -> replan), not by total attempt count.

The runner owns orchestration; backends, plugins, prompts, and validators provide bounded capabilities behind explicit contracts.

A small reusable Python orchestrator for long-running AI coding tasks. It separates AI work from deterministic validation, keeps resumable state, isolates the current TODO, and tolerates model/CLI failures without embedding project-specific logic in the Runner.

## Key properties
- Bounded structured Stage handoff: recover prompts can use `previous.data` (for example `reason` / `missing_items`) without replaying unbounded prior context.
- Qwen and OpenCode backends; full task prompts for both backends are stdin-only, with backend-owned session/permission handling.
- Declarative Planning: Plan produces the durable TODO list directly; planning failures use the shared same-session -> fresh-session -> replan recovery path, with no independent Understand/Judge Stage.
- TODO execution runs Execute -> Review for each task. Same-task failures prefer the same session and rebuild only when needed; timeout recovery uses a stable semantic failure key so volatile backend output such as sandbox/container IDs cannot reset the failure streak; Review uses an independent read-only client/session.
- Bundled Execute/Review prompts use bounded `continuation_prompt` handoffs after the same session has already seen the full Stage contract, so later TODOs/repair evidence do not resend Goal/rules; first and fresh/rebuilt calls still receive complete necessary context.
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

The runner uses a small YAML-driven flow pipeline. `StageExecutor` owns shared retry, Hook, semantic progress reporting, and exception handling. Each Stage performs one job and returns only `StageResult` facts/effects. `FlowNode` owns static YAML routing such as `recover`, `restart_at`, and `scope`. `PlanStage` is the built-in Task producer and automatically enters the standard `execute -> review` per-TODO SOP, so normal Plan-driven YAML does not repeat those flow nodes. Other Stages may still declare `produces: tasks`; advanced/custom producers can use an explicit contiguous `scope: task` block when they need a custom per-TODO SOP.

Cross-cutting features stay outside the flow: status events feed UI/logging/diagnostics, while Git restrictions, protected files, read-only enforcement, and optional loop-context compression register as plugins. Core stages and the AI client do not import those concrete plugins.


## Stage execution architecture

`YAML FlowNode -> StageExecutor -> Stage.run() -> StageResult -> recovery / next FlowNode`

Unified execution rules:
- API/service failures use exponential backoff inside the AI client for one configured wait window (default 1 hour) and do not count as Stage failures. If a window is exhausted, canonical `runner.api.run()` resumes durable direct/YAML state and opens another window until the task passes.
- Real failures retry in the same session using a short stage-aware continuation prompt containing only the stage identity, new failure evidence, and required next action; after the configured retry count (default 2), StageExecutor starts a fresh session.
- Repeated identical failures in the fresh session return `replan`, causing the default flow to start a fresh planning session and generate a new plan. A Stage may set the shared 1-based YAML `restart_at` option to restart from a specific current/earlier top-level Stage instead. Different failures reset the failure streak.
- A write attempt that changed project files counts as progress and is handed to the next review/validation Stage instead of being retried as a failure.
- Review may skip after its retry budget is exhausted; the skip is recorded and Final Validator remains the completion gate.
- Task producers store only durable TODO content (`title`, `description`, `deliverable`, `acceptance_criteria`). `PlanStage` is one built-in producer; `command` or future Stage types can opt into the same effect with `produces: tasks`. For Plan-driven flows, the loader expands the standard `execute -> review` task SOP internally and `workflow_position` remains the durable execution cursor. Explicit `scope: task` is reserved for advanced/custom task producers or custom per-TODO SOPs.


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

A FlowNode may override `fresh_after_same_failures: N`. Only repeated, successfully parsed semantic `FAIL` results count. When the same failure fingerprint reaches N, Runner drops only that Stage's AI session, runs the existing `recover`, then re-runs the Stage with its full prompt in a fresh session. Backend/API/parser/timeout errors do not count and different semantic failures reset the count. `ReviewStage` owns the semantic default `2` whenever it has recovery; other Stage types remain opt-in. This keeps builtin YAML small while preserving an explicit override when a Workflow needs a different threshold.

## Workflow Dry Run

Use `tool/workflow_dryrun.py` to validate whether a `workflow.yaml` can reach closure without calling a real agent. The tool reuses the production Workflow Loader, Pipeline, StageResult, and Stage finish and result reducers, and mocks only the bottom-level Stage execution result, so it does not create a second workflow engine.

```bat
python tool\workflow_dryrun.py runner\workflow\builtin\mixed.yaml --scenario dryrunexample\builtin_mixed_scenario.yaml
dryrunexample\run_dryrun.bat
```

`dryrunexample/` covers a builtin workflow plus a concise semantic custom workflow with `task`, `review`, recover, and `repeat`. Dry Run is an external tool; removing it and its examples does not change Runner Core behavior.
Auto failure matrix:

```bat
python tool\workflow_dryrun.py runner\workflow\builtin\mixed.yaml --matrix
python tool\workflow_dryrun.py runner\workflow\builtin\mixed.yaml --matrix --json

`--matrix` now generates deterministic routing cases for the Workflow's actual `recover`, `repeat`, and `restart_at` features and reports detected task-producer/task-scope/review/validation features. `--matrix --json` is suitable for CI, UI, and reliability gates.
```

`--matrix` runs the happy path plus one deterministic `FAIL -> recover -> closure` case for every recoverable Stage that the real normalized workflow exposes. Invalid workflow options are rejected by the production Workflow Loader/schema before simulation; Dry Run does not maintain a duplicate validation schema.

For external UI/AI editors, `python tool/workflow_catalog.py` emits the data-only Stage/flow schema as JSON, and `python tool/workflow_dryrun.py workflow.yaml --json` emits a machine-readable closure result. The UI can therefore CRUD YAML/MD/PY without importing Runner Core.



### Command-backed Stages
`command` is the single child-process Stage for Python scripts, validators, and arbitrary argv. It shares one boundary for cwd, timeout, output capture, process-tree cleanup, and exit-code semantics.
