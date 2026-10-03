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
- 可選 `routes.pass/fail`：明確 semantic result edge

例如：

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

預設：

- PASS -> 下一個 Stage
- FAIL -> stop
- ERROR -> 由 StageExecutor 處理技術性 retry/recovery；無人值守預設為無上限（`stage_retries: -1`），並搭配 Fresh Session 輪替與 capped backoff。Review 若明確設定有限的 `error_policy.retries`，耗盡後會 fail-soft Skip 到下一個 Stage；其他 Stage 的有限 retry 用盡後仍 fail-closed。
- Review 的 semantic FAIL 與 ERROR 分開計算。`max_failures: 3` 允許真的 FAIL 3 次；第 4 次進入同一 Review Stage 時不呼叫 reviewer，直接 fail-soft PASS 並清除 durable counter。Review 真正 PASS 也會立即清 0。

Rollback / Loop 就是指向前面 Stage 的普通 result edge。

pre-v3 的相容 runtime/schema 已完全移除。現在 Workflow 只使用 Stage registry、PASS/FAIL 語意 routing、Stage-local technical retry、dynamic child Workflow 與 durable session/state 契約。

## Stage 與 24H Reliability

Stage 是唯一 execution / agent extension unit。

內建：

- `base`
- `plan`
- `ai_validator`
- `command`
- `handoff`

Stage 只做一件事並回傳 `StageResult`。Stage 不實作 retry、recover、session rotation，也不決定 Workflow 下一步。

### AI Stage Profile

一般 AI 行為統一使用一個 `base` Stage type，再用 profile 表達。Profile 預設只定義在 `runner/workflow/profiles.py`，YAML normalization、dynamic child expansion 與 Studio 共用同一份來源：

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

`profile: generic` 是中性的自訂 AI 行為；`execute` 套用可寫入執行預設；`review` 套用 read-only structured PASS/FAIL 契約。只有真正具有不同 runtime 語意的能力才保留專用 Stage type，例如 Plan、AI Validator、Command、Handoff。

### Dynamic child Workflow

任意 Stage 都可以產生 `tasks` 或 `stages`，但 child Stage definitions 必須由 producer Stage 自己提供；Runner 不推測 child Stage 類型。產生的 child Workflow 會插在 producer 後面，完整走同一套 StageExecutor / FlowEngine retry、recover、routing、resume，再回 parent 下一個 Stage。

`PlanStage` 是內建例子：它驗證 task plan 後，由 PlanStage 自己建立每個 task 的 Execute -> Review 交錯 child stages。其他特殊 Stage / plugin 也能用相同 contract 產生完全不同的 child 結構。展開後定義與 task binding 會持久化在 RunState，Resume 不會為了重建 child workflow 再跑 producer。

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
- dynamic tasks / current task binding
- workflow position
- durable expanded child Workflow / dynamic groups
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

## Runner 目錄圖

Package 直接依責任命名：

```text
runner/
  agent/       Model client、Session、Qwen/OpenCode adapter
  assets/
    workflows/ 可編輯 Workflow YAML
    prompts/
      common/   內建 Plan/AI Stage Review/Validator Prompt
      ralphy/   Ralphy Prompt
      workflow/ Workflow 生成 Prompt
  config/       Defaults 與 RuntimeConfig
  plugins/      Extension discovery、Hook、安全與 Console observer
  runtime/      Durable state、Event、Subprocess、Worker supervisor
  workflow/     Loader、Schema、Stage registry、FlowEngine、Lifecycle
  prompting.py  Prompt render/context/protocol
  workspace.py  Project policy、protected path、workspace registration
  workflow_runner.py 單次 Run 的 orchestration 入口
```

`agent/runtime/workflow/plugins` 責任不同，因此保留獨立 folder；只有沒有獨立 owner 的小 helper 才合併，避免為了少 folder 而增加耦合。

## Workflow 與 Prompt Assets

Global 可編輯資產集中在同一個 assets package，但 Workflow/Prompt 分開：

```text
runner/assets/
  workflows/
    *.yaml
  prompts/
    common/*.md
    ralphy/*.md
    workflow/*.md
```

Project-local 使用完全相同 shape：

```text
<project>/.ai-task-runner/assets/
  workflows/
    *.yaml
  prompts/
    <category>/*.md
```

Prompt reference 使用分類相對 key，例如 `common/review.md`。未來可直接增加 `regression/`、`security/` 等分類，不需要修改 Stage/runtime。

沒有 System / Custom 分類，也沒有唯讀 built-in asset。

## Workflow UI

Project Chat 仍是主要執行介面。Workflow UI 收斂成單一路徑：

- **Workflows** 是 Workflow 資產庫（搜尋、建立、Import、Rename、Duplicate、Export、Delete），點選後進入獨立 Workflow Editor。
- **Prompts** 是獨立 Prompt workspace，包含自己的資產清單與 Prompt Editor。
- Workflows 可用右鍵 **顯示於 Chat / 從 Chat 隱藏**；沿用同一份 persisted visibility，會直接控制 Project Chat 的 Workflow picker。
- `ralphy_ai_validate.yaml` 是 Chat 初始 fallback；若使用者已明確選過且該 Workflow 仍有效，會保留使用者選擇。
- **Workflow Editor** 是唯一 Workflow 編輯器，提供 `Designer | YAML`，兩者共用同一份 canonical Workflow YAML。
- Stage 設定提供 `Form | YAML | Routing | Test`；Stage YAML 由同一套 Python YAML/schema 驗證後才回寫 draft。
- Stage 只 reference Prompt file，不把 Prompt 本文塞進 Workflow YAML。
- Stage = node。
- PASS / FAIL = semantic result edge。
- rollback / loop = PASS/FAIL edge 回前面 Stage。
- Handoff = 一顆 Stage 連多個允許 target，每次決策只選一個 target。
- ERROR 只屬於 technical retry，不建立 graph edge。
- Stage Test 的 PASS / FAIL 使用真 Stage；ERROR 使用 deterministic mock technical error 驗證 retry。

Global 與 Project assets 都可直接修改；YAML 同時是 UI、CLI、Git 與 Runner 的單一真實來源。

目前支援：

1. **Linear Workflow with Rollback / Loop**
2. **Dynamic Handoff**

Dynamic Handoff 已正式支援，重用相同的 Stage、StageExecutor、StateStore、Plugin boundary、Workflow assets 與 Workflow Editor。每次由一個 Handoff Stage 從允許 target 中選擇唯一下一個 Stage。Handoff 與一般 specialist 預設使用 durable per-role Session；角色可明確選擇 `session_policy: main`、`role` 或 `fresh`，獨立 Final Validation 通常維持 `fresh`。Discussion / Group Chat 不在規劃內。

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
python tool\workflow_dryrun.py runner\assets\workflows\mixed.yaml --matrix --json
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
3. `runner/workflow/execution/stage_executor.py`
4. `runner/workflow/stages/`
5. `runner/workflow/profiles.py`
6. `runner/runtime/run_state.py`

核心規則：

> Workflow 定義 Stage nodes 與 result edges；Stage 做一件事；StageExecutor 讓 Stage 穩定；FlowEngine 決定下一步；StateStore 讓進度可以 Resume。

維護中的架構與剩餘 gate 請看 `docs/design/ARCHITECTURE.zh-TW.md` 與 `todo.txt`。

## License

Zero-Clause BSD（0BSD）。
