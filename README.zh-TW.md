# AI Task Runner

版本：1.2.66

AI Task Runner 是一個小型、可 Resume、適合長時間 AI Coding 任務的 Workflow Runner。

目前 Production 架構刻意維持最小：

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

只有一條 Runtime path。UI、CLI、API、YAML List、Dry Run 都不擁有第二套路由／Recovery Engine。

## 核心 Workflow Contract

Workflow 只剩：

- `stages.<name>`：一個 Stage node
- `flow`：依序執行的唯一 Stage 名稱
- 可選 `routes.pass/fail/error`：明確 result edge

例如：

```yaml
stages:
  planning:
    type: plan

  execute:
    type: task
    scope: task

  review:
    type: review
    scope: task
    routes:
      fail: execute
      error: stop

  validate_ai:
    type: ai_validator
    validator: ai
    routes:
      fail: planning

flow:
  - planning
  - execute
  - review
  - validate_ai
```

預設：

- PASS -> 下一個 Stage
- FAIL -> stop
- ERROR -> stop

Rollback / Loop 就是指向前面 Stage 的普通 result edge。

以下舊 Runtime 概念已刻意移除：

- `recover`
- `restart_at`
- `repeat`
- `max_attempts`
- `on_exhausted`
- `fresh_after_same_failures`
- `replan` StageResult
- hidden Plan Task/Review nodes
- per-Stage retry policy
- System/Custom Workflow 分流
- TaskRunner/Pipeline/LinearRouting 相容 runtime

## Stage 與 24H Reliability

Stage 是唯一 execution / agent extension unit。

內建：

- `base`
- `plan`
- `task`
- `review`
- `ai_validator`
- `command`

Stage 只做一件事並回傳 `StageResult`。Stage 不實作 retry、recover、session rotation，也不決定 Workflow 下一步。

`StageExecutor` 統一負責：

- Same Session retry
- Fresh Session rotation
- timeout
- transient backend/API retry
- changed-file tracking
- safety hooks

公開 retry contract 只保留：

```text
stage_retries = -1
retry_delay = 5
retry_max_delay = 300
```

`stage_retries=-1` 代表 technical Stage failure 可無限重試，適合 24H 無人值守。

API／服務異常使用「秒」為單位的 bounded exponential delay：

```text
retry_delay -> ... -> retry_max_delay
```

Deterministic configuration/state error fail closed。 `KeyboardInterrupt` / `SystemExit` 不會被 retry 吞掉。

每個 Session 本身仍有 bounded attempt budget；到達上限後，只 Fresh 該 Stage 的 Session，再繼續同一 logical Stage。

## Durable Resume

`StateStore` 只有一份 authoritative `state.json`。

Durable state 只保存 Resume 真正需要的資料：

- run identity / goal / project
- tasks / current task
- workflow position
- task-scope position
- AI session id
- 最新 StageResult transition
- workflow fingerprint
- completion/activity state

Technical retry counter 不形成第二套 durable recovery state machine。

目標：

```text
不中斷執行
==
任一 committed Stage boundary crash + resume
```

Worker Supervisor 與 Stage retry 分離，只負責 process-level crash / hang / stop / orphan cleanup。

## Workflow 與 Prompt Assets

Global 可編輯資產統一放：

```text
runner/workflows/
  *.yaml
  *.md
```

Project-local 使用完全相同 shape：

```text
<project>/.ai-task-runner/workflows/
  *.yaml
  *.md
```

Workflow YAML 與 Prompt Markdown 是同一層 peer assets。

沒有 System / Custom 分類，也沒有唯讀 built-in asset。

## n8n-style UI

Workflow Studio 直接編輯正式 Runtime graph：

- Stage = node
- PASS/FAIL/ERROR route = edge
- rollback / loop = edge 回前面 Stage
- technical retry / session recovery 不畫成 edge
- node 設定只放 Stage behavior
- edge 設定只放 semantic routing

Global 與 Project assets 都可以直接修改。

目前只實作：

1. **Linear Workflow with Rollback / Loop**

未來才做：

2. **Dynamic Handoff**
3. **Discussion / Group Chat**

未來兩種模式必須重用同一個 Stage、StageExecutor、StateStore、Plugin boundary、Workflow assets 與 Graph Designer，不建立第二套完整 Orchestrator。

## CLI

例如：

```bat
python ai_task_runner.py --goal-file "prompt.md" --project-root "." --validator "validation.py"
```

主要 runtime options：

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

CLI 只負責建立 RunRequest，不包含 Workflow routing behavior。

## YAML List

YAML List 只是多個 child RunRequest：

```yaml
- prompt: 修正任務 A
  validator: ai
  stage_retries: -1
  retry_delay: 5
  retry_max_delay: 300

- prompt: 修正任務 B
  project_root: ./project-b
  workflow_file: ./workflow.yaml
  validator: ai
```

每個 child 都使用完全相同的 Workflow Loader、WorkflowRunner、FlowEngine、StageExecutor、StateStore。

## Plugins

Plugin discovery 只有一個 owner：

```text
runner/plugins/registry.py
```

外部 plugin 統一使用 `ai_task_runner.plugins` entry-point group。

Plugin 可提供：

- `setup()`：process-level Stage/backend registration
- `register(runtime)`：runtime hooks
- 選擇性的 CLI/request/YAML config adapters

Workflow 不 branch 具體 Plugin。

## Dry Run

`tool/workflow_dryrun.py` 直接重用正式 Workflow Loader 與 FlowEngine，只 Mock Stage execution result。

例如：

```bat
python tool\workflow_dryrun.py runner\workflows\mixed.yaml --matrix --json
```

Dry Run 不維護第二套 Runtime。

## Real-Qwen Reliability / 24H Soak

Live reliability harness：

```text
tool/qwen_live_reliability.py
```

Windows preset：

```text
tool\qwen_live_reliability_0_5h.bat
tool\qwen_live_reliability_24h.bat
```

24H gate 會走正式 CLI/runtime path，涵蓋 Same Session/Fresh Session、API transient、YAML List、sandbox 與長時間 process/state 行為。

24H PASS 代表很高的工程信心，不是數學上的 100% 保證。

## 主要 Runtime 閱讀順序

1. `runner/workflow_runner.py`
2. `runner/workflow/flow_engine.py`
3. `runner/workflow/stages/executor.py`
4. `runner/runtime/run_state.py`

核心規則：

> Workflow 定義 Stage nodes 與 result edges；Stage 做一件事；StageExecutor 讓 Stage 穩定；FlowEngine 決定下一步；StateStore 讓進度可以 Resume。

維護中的架構與 TODO 請看 `architecture.md`、`DevFollow.txt`、`future.txt`。

## License

Zero-Clause BSD（0BSD）。
