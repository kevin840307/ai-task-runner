# AI Task Runner

Version: 1.2.66

AI Task Runner is a small resumable workflow runner for long-running AI coding tasks.

The current production model is intentionally minimal:

```text
UI / CLI / API / YAML List
            |
         RunRequest
            |
     WorkflowRunner
            |
        FlowEngine
       /         \
StageExecutor   StateStore
      |
    Stage
```

There is one runtime path. UI, CLI, API, YAML List and Dry Run do not own separate routing/recovery engines.

## Core contract

A Workflow is only:

- `stages.<name>`: one Stage node
- `flow`: ordered unique Stage names
- optional `routes.pass/fail`: explicit semantic result edges

Example:

```yaml
stages:
  planning:
    type: plan

  validate_ai:
    type: ai_validator
    validator: ai
    routes:
      fail: planning

flow:
  - planning
  - validate_ai
```

Default routing is:

- PASS -> next Stage
- FAIL -> stop
- ERROR -> StageExecutor technical retry/recovery; the unattended default is unlimited (`stage_retries: -1`), with Fresh Session rotation and capped backoff. A Review with a finite local `error_policy.retries` is fail-soft and skips to the next Stage after retries are exhausted; other Stage types fail closed when a finite retry budget is exhausted.
- Review semantic FAIL is separate from ERROR. `max_failures: 3` allows three real FAIL verdicts; on the fourth entry to that Review Stage, Runner does not invoke the reviewer, emits fail-soft PASS, and clears the durable counter. Any real Review PASS also clears the counter.

Rollback and loop are ordinary result edges to an earlier Stage.

Pre-v3 compatibility runtime/schema paths are intentionally absent. Current Workflows use only the Stage registry, PASS/FAIL semantic routes, Stage-local technical retry policy, dynamic child Workflow expansion, and durable session/state contracts.

## Stage and reliability

Stage is the only execution/agent extension unit.

Built-in types:

- `base`
- `plan`
- `ai_validator`
- `command`
- `handoff`

A Stage does one responsibility and returns `StageResult`. It does not implement retry, recovery, session rotation or graph navigation.

### AI Stage profiles

General AI behavior is one `base` Stage type with a small behavior profile. Profile defaults are defined once in `runner/workflow/profiles.py` and are shared by YAML normalization, dynamic child expansion and Studio:

```yaml
stages:
  execute:
    type: base
    profile: execute

  review:
    type: base
    profile: review
    error_policy:
      retries: 2
    max_failures: 3
    routes:
      fail: execute
```

`profile: generic` is the neutral custom-AI behavior. `execute` applies writable execution defaults. `review` applies the structured read-only semantic PASS/FAIL contract. Dedicated Stage types are reserved for genuinely different runtime semantics such as Plan, AI Validator, Command and Handoff.

### Stage backend and model override

Every AI-backed Stage (`base`, `plan`, `handoff`, `ai_validator`) may opt into a Stage-local backend/model pair. `command` remains deterministic and has no AI backend fields.

```yaml
stages:
  final_review:
    type: base
    profile: review
    backend: qwen
    model: qwen3-coder-plus
```

The override is atomic and local:

- `backend` and `model` must either both be absent or both be set
- when both are absent, the Stage uses the normal run-level backend/model
- when both are set, only that Stage uses the selected backend/model
- the override is not inherited by Plan-generated or producer-defined child Stages
- it does not modify the global/run-level model
- a Stage backend/model pair cannot use `session_policy: main`

Workflow Studio exposes Backend and Model in the Stage **Execution** section. Model is a dropdown only: its values come from the selected Backend adapter. Qwen reads selectable ids from its configured `modelProviders` / model settings; OpenCode uses its own `opencode models` command. The Studio does not hardcode provider model names.

The selected model is passed to the chosen adapter for that Stage only. Qwen and OpenCode both encode it as their CLI `--model <id>` argument through the shared adapter contract; future backends may override `configure_model_args()` without adding Core/UI provider branches.

Real Stage Test reports the effective backend/model actually used, while its Backend selector remains only the fallback when the Stage has no local pair.


### Dynamic child Workflows

Any Stage may produce `tasks` or `stages`, but the producer Stage must supply the child Stage definitions. Runner never infers child Stage types. The produced child Workflow is inserted immediately after the producer, runs completely through the normal StageExecutor/FlowEngine reliability path, then the parent Workflow continues.

`PlanStage` is the built-in example: it validates its task plan and itself builds alternating Execute -> Review child stages for every task. Other special/plugin Stages may generate different child structures using the same contract. Expanded definitions and task bindings are persisted in RunState, so Resume continues the existing child Workflow without re-running the producer merely to reconstruct it.

`StageExecutor` owns all Stage technical reliability:

- Same Session retry
- Fresh Session rotation
- timeout handling
- transient backend/API retry
- changed-file tracking
- safety hooks

The public retry contract is intentionally small:

```text
stage_retries = -1
retry_delay = 5
retry_max_delay = 300
```

`stage_retries=-1` means unlimited technical retries for unattended operation.

Transient API/service errors use seconds-based bounded exponential delay:

```text
retry_delay -> ... -> retry_max_delay
```

Deterministic configuration/state errors fail closed. `KeyboardInterrupt` and `SystemExit` are never swallowed.

Each model session stays bounded. After the shared per-session attempt budget is exhausted, only that Stage session is rotated to Fresh Session and the same logical Stage continues.

## Durable resume

`StateStore` owns one authoritative `state.json`.

Durable state contains only what is required to resume:

- run identity / goal / project
- dynamic tasks and current task binding
- workflow position
- durable expanded child Workflow / dynamic groups
- AI session id
- latest StageResult transition
- workflow fingerprint
- completion/activity state

Technical retry counters are not a second durable recovery state machine.

Correctness target:

```text
uninterrupted run
==
crash at a committed Stage boundary + resume
```

The worker supervisor is separate from Stage retry and only owns process-level crash/hang/stop/orphan cleanup.

## Runner map

The package is intentionally organized by responsibility:

```text
runner/
  agent/       model client, sessions and Qwen/OpenCode adapters
  assets/
    workflows/ editable Workflow YAML
    prompts/
      common/   built-in Plan/AI Stage Review/Validator prompts
      ralphy/   Ralphy-specific prompts
      workflow/ Workflow-generation prompts
  config/       runtime defaults and validated RuntimeConfig
  plugins/      extension discovery, hooks, safety and console observers
  runtime/      durable state, events, subprocesses and worker supervision
  workflow/     loader, schema, Stage registry, FlowEngine and lifecycle
  prompting.py  Prompt rendering/context/protocols
  workspace.py  project policy, protected paths and workspace registration
  workflow_runner.py one-run orchestration entry
```

`agent`, `runtime`, `workflow`, and `plugins` remain separate because they own different runtime concerns. Small helper packages are avoided when one obvious module can own the behavior.

## Workflow and Prompt assets

Global editable assets use one package with separate file-type roots:

```text
runner/assets/
  workflows/
    *.yaml
  prompts/
    common/*.md
    ralphy/*.md
    workflow/*.md
```

Project-local editable assets use the same shape:

```text
<project>/.ai-task-runner/assets/
  workflows/
    *.yaml
  prompts/
    <category>/*.md
```

Prompt references are category-relative keys such as `common/review.md`. New prompt domains can be added as another category without changing Stage/runtime code.

There is no System/Custom split and no read-only built-in asset class.

## Workflow UI

Project Chat remains the primary run surface. Workflow editing is intentionally converged:

- **Workflows** is the Workflow asset library (search/create/import/rename/duplicate/export/delete) and opens the dedicated Workflow Editor.
- **Prompts** is a separate Prompt workspace with its own asset list and Prompt Editor.
- Workflows can be right-clicked to **Show in Chat / Hide from Chat**; this uses the same persisted visibility state that filters the Project Chat Workflow picker.
- `ralphy_ai_validate.yaml` is the initial Chat fallback when there is no still-valid saved Workflow selection. A valid explicit user selection is preserved.
- **Workflow Editor** is the only Workflow editor and provides `Designer | YAML` views over the same canonical Workflow YAML.
- Stage settings provide `Form | YAML | Routing | Test`; Stage YAML is parsed/validated by the same Python YAML/schema path before it updates the draft.
- Stages reference Prompt files instead of embedding Prompt bodies.
- Stage = node.
- PASS / FAIL = semantic result edges.
- rollback/loop = PASS/FAIL edge to an earlier Stage.
- Handoff = one Stage with multiple allowed target edges, selecting exactly one target per decision.
- ERROR is technical retry only and is never drawn as a graph edge.
- Stage Test supports real PASS/FAIL probes and a deterministic mocked technical ERROR probe for retry verification.

Global and Project assets are both editable. Workflow YAML remains the source of truth used by UI, CLI, Git and Runner.

Supported workflow families:

1. **Linear Workflow with Rollback / Loop**
2. **Dynamic Handoff**

Dynamic Handoff is already supported and reuses the same Stage, StageExecutor, StateStore, plugin boundary, Workflow assets and Workflow Editor. One Handoff Stage selects exactly one allowed next Stage per decision. Handoff and specialist roles default to durable per-role Sessions; a role may explicitly choose `session_policy: main`, `role`, or `fresh`, while independent final validation should normally stay `fresh`. Discussion / Group Chat is not planned.

## CLI

Example:

```bash
python ai_task_runner.py \
  --goal-file prompt.md \
  --project-root . \
  --validator validation.py
```

Important runtime options:

```text
--workflow
--backend
--stage-retries
--retry-delay
--retry-max-delay
--agent-timeout
--planning-timeout
--validator-timeout
--resume
--force-new
```

CLI is only a RunRequest adapter; it contains no Workflow routing behavior.

## YAML List

YAML List is a batch of child RunRequests.

Example:

```yaml
- prompt: Fix task A
  validator: ai
  stage_retries: -1
  retry_delay: 5
  retry_max_delay: 300

- prompt: Fix task B
  project_root: ./project-b
  workflow_file: ./workflow.yaml
  validator: ai
```

Every child uses the same Workflow loader, WorkflowRunner, FlowEngine, StageExecutor and StateStore as normal CLI/API execution.

## Plugins

Plugin discovery has one owner:

```text
runner/plugins/registry.py
```

Installed external plugins use the `ai_task_runner.plugins` entry-point group.

A plugin may expose:

- `setup()` for process-level Stage/backend registration
- `register(runtime)` for runtime hooks
- optional CLI/request/YAML config adapters

Workflow code does not branch on concrete plugins.

## Dry Run

`tool/workflow_dryrun.py` reuses the production Workflow loader and FlowEngine and only mocks Stage execution results.

Example:

```bash
python tool/workflow_dryrun.py runner/assets/workflows/mixed.yaml --matrix --json
```

Dry Run validates graph closure and safe-stop behavior without creating a second runtime.

## Real-Qwen reliability and 24H soak

The live reliability harness is:

```text
tool/qwen_live_reliability.py
```

Windows presets:

```text
tool\qwen_live_reliability_0_5h.bat
tool\qwen_live_reliability_24h.bat
```

The 24H gate covers the production CLI/runtime path, including bounded Same Session -> Fresh Session recovery, short and long HTTP 429/502/503 outages, raw disconnects, real-Qwen expired-session injection/recovery, YAML List, sandbox checks and long-running process/state behavior. Every long HTTP 429/502/503 probe fails closed unless the configured StageExecutor maximum backoff is actually observed for that probe. High-density soak rotates transient HTTP status classes and records per-status recovery counts plus bounded resource/backoff observations in the live summary.

A 24H PASS is an engineering confidence signal, not a mathematical reliability guarantee.

## Architecture ownership

Main runtime reading path:

1. `runner/workflow_runner.py`
2. `runner/workflow/flow_engine.py`
3. `runner/workflow/contracts.py`
4. `runner/workflow/execution/stage_executor.py`
5. `runner/workflow/stages/`
6. `runner/workflow/profiles.py`
7. `runner/runtime/run_state.py`

Design rule:

> Workflow defines Stage nodes and result edges. Stage performs one responsibility. StageExecutor makes one Stage reliable. FlowEngine moves through the graph. StateStore makes progress resumable.

See `docs/design/ARCHITECTURE.md` and `todo.txt` for the maintained design and remaining acceptance gates.

## License

Zero-Clause BSD (0BSD).
