# Runtime 架構

## 核心

```text
RunRequest -> WorkflowRunner -> FlowEngine -> StageExecutor -> Stage
                            \-> StateStore
```

CLI、API、YAML List、UI 全部使用同一套 runtime。

### Stage
只負責語意工作並回傳 `StageResult`。

### StageExecutor
只負責技術可靠性：
- technical retry；
- timeout；
- Same Session retry；
- Fresh Session rotation；
- transient backend/API recovery；
- safety/change tracking；
- plugin hook/event。

自訂 Stage 不應再實作自己的 retry/recovery framework。

### FlowEngine
只負責語意 navigation：
- PASS 預設下一個 Stage；
- FAIL 預設停止；
- `routes.pass` / `routes.fail`；
- Stage 結果（`tasks` / `stages`）的 durable dynamic child Workflow 展開；
- Handoff one-of-many target routing。

ERROR 不走 graph routing。

### StateStore
持久化 workflow position、已展開 child Workflow、dynamic task groups、上一個 transition evidence、主 Session ID 與 durable role Session ID。

## Dynamic child Workflow

任意 Stage 都可以回傳 `tasks` 或 `stages`，但 child Stage 結構必須由該 Stage 自己產生；Runner 不猜測 child node type。

執行語意：

```text
A -> B -> C -> D
          |
          +-> child-1 -> child-2 -> ... -> child-N
                                      |
                                      +-> D
```

child Workflow 會完整走同一套 StageExecutor / FlowEngine retry、recover、routing、resume，再回 parent 下一個 Stage。展開後的 Workflow 與 task binding 會持久化到 RunState，所以 Resume 不會只為了重建 child workflow 再跑一次 C。

`PlanStage` 是內建範例：它先解析合法 tasks，再由 PlanStage 自己產生交錯的 AI Execute -> AI Review child stages。未來特殊 Stage / plugin 可透過同一 contract 產生完全不同的 child 結構。

## Dynamic Handoff

`type: handoff` 宣告 `targets`，structured result 每次只選一個允許的 target。Handoff 本身不執行角色工作，也沒有第二套 scheduler hierarchy。

一般 AI specialist 統一使用 `base`（AI Stage）+ behavior profile；只有真正具有特殊 runtime 語意的能力才保留專用 Stage type，例如 `plan`、`ai_validator`、`command`、`handoff`。

Session policy 與 routing 解耦：
- `role`：durable Stage-owned Session；
- `main`：Runner 主 Session；
- `fresh`：每次 invocation 獨立 Session；
- `auto`：built-in/default profile 行為。

因此可用同一 Handoff graph 表達動態 specialist routing，不需要新增另一套 runtime family。

## Prompt / Session 契約

Stage template 定義語意行為。Runner 共用 control envelope 只補 retry/continue/recover 的新資訊與 bounded feedback。Same Session 已看過原始 Stage prompt 後，不重送沒有變化的完整 context。

Dynamic 一般角色共用 worker template，再由每個 Stage 的 `instructions` 定義職責；只有 protocol 真正不同才拆專用 prompt。

## UI 契約

Studio 只是 YAML 的 editor projection，不是第二套 graph schema。

- START/END：UI virtual node。
- Stage node：一個真實 YAML Stage；AI Stage 使用 `profile: generic | execute | review`。
- PASS/FAIL edge：semantic route。
- Handoff edge：allowed target。
- ERROR：只設定 retry policy。

UI backend 使用與 runtime loader 相同的 catalog/schema 驗證。

## 明確不做

不要恢復：
- Pipeline/TaskRunner compatibility runtime；
- repair/recover/restart_at/repeat/max_attempts/on_exhausted graph control；
- `routes.error`；
- Discussion / Group Chat runtime 或 UI mode；
- generic AgentMessage / scheduler framework；
- generic parallel DAG engine。

Parallel 仍是 future work。
