# Prompt 與 Session 契約

目前 runtime 維持小而共用的 Prompt 模型。

## 一個 Stage Prompt + 一個共用 Control Envelope

Stage template 只定義語意責任。retry / continue / recover 不維護成多份 Prompt 檔案。

實際 AI input：

```text
Stage prompt
+ 必要時由 Runner 補上的 shared control envelope
+ Stage 需要時的 immutable structured output protocol
```

shared control envelope 可以包含：
- 目前 Stage 名稱；
- continue / retry / recover mode；
- attempt；
- 是否為 Same Session；
- bounded previous error；
- bounded Review / Validator feedback；
- bounded current Task evidence。

不要重複塞入沒有變化的大量 Goal/project context。

## Initial / Same Session / Fresh Recovery

### Initial
送完整 Stage prompt。

### Same Session continue/retry
當這個 Session 已看過同一 Stage prompt contract，只補新的 control/evidence + immutable output protocol。保留有效成果，不重做沒有變化的 discovery。

### Fresh / rebuilt Session
重新送完整 Stage prompt，只在前面加短 recovery control envelope。Stage prompt 仍是角色與 Goal 語意的唯一來源。

## Dynamic Handoff Prompt

Coordinator 使用 `common/handoff.md`，只回傳一個允許的 structured target。

一般 Dynamic specialist 預設共用 `common/dynamic_worker.md`：

```text
Goal
+ Assigned responsibility（Stage instructions）
+ Handoff context
+ 共用 specialist rules
```

角色差異放在各 Stage 的 `instructions`。只有角色需要真正不同的 protocol、tool contract 或 output format 才拆專用 Prompt。

獨立 Final Validation 使用一般 AI Validator prompt，通常設定 `session_policy: fresh`。

## Session Policy

Routing 與 Session lifetime 完全解耦。

- `session_policy: role`：Stage name 擁有 durable 可重用 Session；Dynamic specialist 預設。
- `session_policy: main`：使用 Runner 主 Session。
- `session_policy: fresh`：每次 invocation 都清空/建立新 Session。
- `session_policy: auto`：built-in/default profile 行為。

`RunState.stage_sessions` 保存 durable role Session。某個 role 技術錯誤反覆失敗時，StageExecutor 可以只 reset 該角色 Session，再用 fresh Session 繼續；其他 role 不受影響。

## Read-only Stage

Review / Validator / read-only role 必須根據現有證據做 verdict，不應偷偷變成 repair / implementation agent。

Review / Validator 回 FAIL 時，FlowEngine 走設定的 semantic FAIL route。Technical ERROR 仍只由 StageExecutor 處理，不是 graph edge。

## Prompt 維護原則

- 每種 semantic Stage behavior 只維護一個核心 Prompt。
- protocol 相同時，角色差異放在 `instructions`。
- 不建立 retry/recover/continue 的多份 Prompt。
- 全域工程/安全規則放 shared rules。
- feedback 必須 bounded。
- immutable result protocol 由 Runner 擁有。
- 沒有真需求不要再建 prompt-builder hierarchy。
