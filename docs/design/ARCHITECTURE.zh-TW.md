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
- task-scope iteration；
- Handoff one-of-many target routing。

ERROR 不走 graph routing。

### StateStore
持久化 workflow/task 位置、上一個 transition evidence、主 Session ID 與 durable role Session ID。

## Dynamic Handoff

`type: handoff` 宣告 `targets`，structured result 每次只選一個允許的 target。Handoff 本身不執行角色工作，也沒有第二套 scheduler hierarchy。

所有 specialist target 仍是普通 `base`、`review`、`task`、`ai_validator` 或 `command` Stage。

Session policy 與 routing 解耦：
- `role`：durable Stage-owned Session；
- `main`：Runner 主 Session；
- `fresh`：每次 invocation 獨立 Session；
- `auto`：built-in/default profile 行為。

因此 coding team、review board、triage、discussion 都能用同一 Handoff graph 表達，不需要新增 runtime type。

## Prompt / Session 契約

Stage template 定義語意行為。Runner 共用 control envelope 只補 retry/continue/recover 的新資訊與 bounded feedback。Same Session 已看過原始 Stage prompt 後，不重送沒有變化的完整 context。

Dynamic 一般角色共用 worker template，再由每個 Stage 的 `instructions` 定義職責；只有 protocol 真正不同才拆專用 prompt。

## UI 契約

Studio 只是 YAML 的 editor projection，不是第二套 graph schema。

- START/END：UI virtual node。
- Stage node：一個真實 YAML Stage。
- PASS/FAIL edge：semantic route。
- Handoff edge：allowed target。
- ERROR：只設定 retry policy。
- `scope: task`：visual group。

UI backend 使用與 runtime loader 相同的 catalog/schema 驗證。

## 明確不做

不要恢復：
- Pipeline/TaskRunner compatibility runtime；
- repair/recover/restart_at/repeat/max_attempts/on_exhausted graph control；
- `routes.error`；
- Discussion controller runtime；
- generic AgentMessage / scheduler framework；
- generic parallel DAG engine。

Parallel 仍是 future work。
