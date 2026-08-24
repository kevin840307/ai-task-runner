# 架構

目錄本身就是架構圖：

- `runner/api.py`、`bootstrap.py`、`task_runner.py`：外部 request、dependency 組裝、單次任務協調。
- `runner/script_loader.py`、`script_runner.py`：YAML List 讀取/驗證與逐項執行。
- `runner/workflow/`：Workflow 定義、路由規則、特殊 Prompt/Result adapter 與 Stage Engine。
- `runner/workflow/stages/`：Stage contract、factory、共用 executor、`AIStage`、`PlanStage`、`PythonValidatorStage`。
- `runner/ai/`：AI Client、Backend contract、Session 判斷、Structured Output、AI diagnostics。
- `runner/backends/`：Qwen/OpenCode 實作與 Backend registry/configuration。
- `runner/project/`：Project snapshot/restore、policy、QWEN.md/AGENTS.md instruction file lifecycle。
- `runner/prompts/`：Strict Jinja loader、穩定 Prompt Context contract、Prompt resources。
- `runner/runtime/`：Durable state、subprocess lifecycle、raw EventBus，以及 Workflow 使用的 semantic progress facade。
- `runner/plugins/`：Safety、Console、History、Observability 等橫切 Plugin/Hook。
- `runner/config/`：Runtime/default configuration。
- `runner/utils/`：只保留無狀態、通用的 file/text helper。

## 依賴方向

`API/Bootstrap -> TaskRunner -> Workflow -> Stage -> AI contracts`

`Backends -> AI contracts`

`StageExecutor -> Project + Runtime semantic progress + generic hook contract`

`Bootstrap -> backend/plugin registries`

Workflow 不得直接依賴 Qwen/OpenCode、具體 Plugin、raw event schema 或 UI 行為；`runtime/progress.py` 是語意 facade，`runtime/events.py` 才負責 event transport/schema。AI subsystem 不得反向依賴 Workflow business stage。

## Workflow 契約

`Pipeline -> StageExecutor -> Stage.run() -> StageResult -> Stage.finish() -> next Stage`

Stage 一次只做一個 attempt。Hook、Project change tracking、retry/session 升級、exception conversion、lifecycle event 統一由 `StageExecutor` 負責。`Pipeline` 只消費 declarative Stage data 與 `StageResult.next_flow/replace_remaining/complete`。

固定拓樸只放 `workflow/definitions.py`；Result routing/state transition 只放 `workflow/rules.py`。

## Prompt 契約

所有 bundled Prompt 統一使用 Jinja + `StrictUndefined`。Template 不直接取得 `RunState`、`RuntimeConfig` 或任意 dict。`prompts/context.py` 是唯一 Prompt Context 入口，固定 top-level variables：

`goal`, `stage`, `task`, `tasks`, `workflow`, `validation`, `project`, `session`, `failure`, `planning`, `previous`, `rules`, `always_instructions`。

一般 AI Stage 直接指定 prompt path；沒有 prompt-builder registry。Planning / Repair Planning 的計算 context 直接由 `PlanStage` 管理。
