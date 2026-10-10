# 自訂 Workflow

Workflow 是一條由 Stage 組成的有序 graph。CLI、API、YAML List、Studio、Dry Run、dynamic child Workflow 都使用同一套 runtime。

## 最小 AI Workflow

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

  final_validate:
    type: ai_validator
    validator: ai
    session_policy: fresh
    routes:
      fail: execute

flow:
  - execute
  - review
  - final_validate
```

`type: base` 就是一般 AI Stage，使用 profile 表達常見行為，不再維護另一套 Execute/Review Stage type：

- `profile: generic`：自訂 AI 行為。
- `profile: execute`：可寫入的執行行為，預設 Prompt 為 `common/execution.md`。
- `profile: review`：read-only 結構化 PASS/FAIL Review，預設 Prompt 為 `common/review.md`。

舊的 `type: task`、`type: review`、`scope`、`task_step` 已移除，不提供相容層。

## Routing 與技術恢復

PASS 預設走 `flow` 的下一個 Stage。語意 routing 只使用：

```yaml
routes:
  pass: another_stage
  fail: earlier_stage
```

target 也可使用 `done` 或 `stop`。

技術 ERROR 不是 graph edge。Exception、backend failure、timeout、transient API failure、partial write、Same Session retry、Fresh Session recovery、backoff 都由 `runner/workflow/execution/stage_executor.py` 負責。

```yaml
error_policy:
  retries: -1
```

AI Stage 的 `profile: review` 若設定有限 local retry，technical ERROR 耗盡後會 fail-soft 走下一個 Stage。Semantic Review FAIL 仍走 `routes.fail`；`max_failures` 可限制連續 semantic FAIL。

## 特殊 Stage type

只有真正有特殊 runtime 行為的 Stage 才保留專用 type：

- `plan`：規劃 Tasks，並由 PlanStage 自己產生 dynamic child Workflow。
- `ai_validator`：獨立 AI 驗證，可多次執行/投票。
- `command`：外部 command/Python Stage。
- `handoff`：每次動態選擇一個允許的下一個 Stage。
- 已註冊的 plugin Stage。

自訂 Python Stage 只實作工作與結果；retry/session recovery 統一由 StageExecutor 負責。

## Dynamic child Workflow

任意 Stage 都可以回傳 `tasks` 或 `stages`，但 **child Stage 結構必須由 producer Stage 自己產生**；Runner 不猜要建立哪一種 child Stage。

執行語意固定是：

```text
A -> B -> C -> D

C 回傳 tasks/stages

A -> B -> C
          -> child-1
          -> child-2
          -> ...
          -> D
```

所有 child 都走同一套 FlowEngine / StageExecutor，所以 retry、recover、routing、session policy 都相同。展開結果會持久化到 RunState，因此 Resume 會接著跑已展開的 child Workflow，不會只為了重建 child 再跑一次 C。

目前 PlanStage 會把驗證過的 Tasks 轉成：

```text
task-1 Execute -> task-1 Review
-> task-2 Execute -> task-2 Review
-> ...
```

這是 PlanStage 自己的行為，不是 Runner 的固定生成規則。未來其他特殊 Stage 可以產生完全不同的 child Workflow。

`tasks` producer 必須同時回傳 task data 與 child Stage definitions。child 使用 `task_id` 綁定 Task，且每個 Task 至少要有一個 child 設 `task_complete: true`。

```json
{
  "tasks": [
    {
      "id": "inspect",
      "title": "Inspect project",
      "description": "Inspect the project.",
      "deliverable": "Findings",
      "acceptance_criteria": ["Findings are complete."]
    }
  ],
  "stages": [
    {
      "name": "inspect_execute",
      "type": "base",
      "profile": "execute",
      "task_id": "inspect"
    },
    {
      "name": "inspect_review",
      "type": "base",
      "profile": "review",
      "task_id": "inspect",
      "task_complete": true,
      "routes": {"fail": "inspect_execute"}
    }
  ]
}
```

`stages` producer 若不需要 durable Task，可只回傳非空 `stages` array。

## Dynamic Handoff

```yaml
stages:
  coordinator:
    type: handoff
    targets: [implementer, verifier, final_validate]
    session_policy: role

  implementer:
    type: base
    profile: generic
    prompt: common/dynamic_worker.md
    instructions: Implement the smallest correct change.
    session_policy: role
    mode: write
    track_changes: true
    routes:
      pass: coordinator

  verifier:
    type: base
    profile: generic
    prompt: common/dynamic_worker.md
    instructions: Independently verify tests and evidence.
    session_policy: role
    readonly_safety: observe
    routes:
      pass: coordinator

  final_validate:
    type: ai_validator
    validator: ai
    session_policy: fresh
    routes:
      pass: done
      fail: coordinator

flow:
  - coordinator
  - implementer
  - verifier
  - final_validate
```

Handoff 只負責選擇下一個允許 target；實際角色仍然是普通 Stage。

## Session Policy

- `role`：Stage name 擁有 durable 可重用 Session。
- `main`：共用 Runner 主 Session。
- `fresh`：每次 invocation 都建立新 Session；適合獨立驗證。
- `auto`：built-in/default 行為。

連續技術失敗時，只會輪替受影響 Stage 的 Session。

## 多次執行 / 投票

```yaml
review_vote:
  type: base
  profile: review
  session_policy: fresh
  runs: 3
  required_passes: 2
```

## Command Stage

```yaml
validate_file:
  type: command
  result_kind: validation
  command: ["{python}", "validator.py", "--project-root", "{project_root}"]
  routes:
    fail: execute
```

command/plugin Stage 可宣告 `produces: tasks` 或 `produces: stages`，但輸出必須自行提供相對應的 child Workflow。

## Prompt

Prompt 使用 category-relative reference：

- `common/<name>.md`
- `ralphy/<name>.md`
- `workflow/<workflow-name>/<name>.md`

## 測試

Live 前先跑 deterministic dry-run：

```powershell
python tool/workflow_dryrun.py path/to/workflow.yaml --matrix --json
```

單一 Stage 可使用 Workflow Editor Stage Test 或 `tool/stage_probe.py`。

real backend gate：

```powershell
tool\qwen_live_reliability_0_5h.bat
```

短 gate PASS 後再跑 24H。
