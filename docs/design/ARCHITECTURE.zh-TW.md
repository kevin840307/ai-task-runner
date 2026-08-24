# 架構

Runner 以清楚的 execution ownership 為核心：

- `runner/flow/`：精簡 Stage-list Pipeline 與預設 Stage 組裝；下一步由 StageResult.stages 動態產生。
- `runner/stages/`：可拼接 Stage、`StageExecutor`、`Stage builder`。
- `runner/model/`：Model/Backend 契約、client/session、structured output。
- `runner/runtime/`：durable state、progress/events、subprocess；不放 model ask 或 Hook 執行。
- `runner/extensions/`：Safety、Console、History、Observability 等可抽插 Hook/Observer。
- `runner/utils/`：純通用 file/project/template/text/import helper。

## 核心契約

`Pipeline loop -> StageExecutor -> Stage.run() -> StageResult -> stages/replace/complete -> next Stage`

Stage 每次只做一個 attempt 並回傳事實結果；Stage 不執行 Hook、不自己 Retry、不發布 UI lifecycle event，也不決定下一個 Flow node。

`StageExecutor` 是唯一執行邊界，統一負責 before/after Hook、write Stage 的 project snapshot/change detection、exception 轉 StageResult，以及既有 `runner.stage` lifecycle event。

所有 Stage 共用同一套 `StageExecutor retry`。`PlanStage`、`PythonValidationStage` 這種特殊 Stage 只寫與 `GlobalStage` / `GlobalStage` 不同的部分。

`Stage builder` 負責 implementation type 到 Stage builder 的對應；`Pipeline` 不 import concrete Stage class，也不認任何業務 Stage 名稱。
