# 架構

目錄本身就是架構圖：

- `runner/api.py`、`bootstrap.py`、`task_runner.py`：外部 request、dependency 組裝、單次任務協調。
- `runner/script_loader.py`、`script_runner.py`：YAML 結構/檔案解析，以及經驗證的 child config 執行。
- `runner/workflow/`：Workflow 定義、路由規則、特殊 Prompt/Result adapter 與 Stage Engine。
- `runner/workflow/stages/`：Stage contract、factory、共用 executor、`BaseStage`、`PlanStage`、`PythonValidatorStage`。
- `runner/ai/`：AI Client、Backend contract、Session 判斷、Structured Output、AI diagnostics。
- `runner/backends/`：Qwen/OpenCode 實作與 Backend registry/configuration。
- `runner/project/`：Project snapshot/restore、policy、QWEN.md/AGENTS.md instruction file lifecycle。
- `runner/prompts/`：Strict Jinja loader、穩定 Prompt Context contract、Prompt resources。
- `runner/runtime/`：Durable state、subprocess lifecycle、raw EventBus，以及 Workflow 使用的 semantic progress facade。
- `runner/plugins/`：Safety、Console、History、Observability、Loop context 壓縮等橫切 Plugin/Hook。
- `runner/config/`：Defaults 與唯一經驗證的 Runtime configuration contract。
- `runner/utils/`：只保留無狀態、通用的 file/text helper。

## 依賴方向

`API/Bootstrap -> TaskRunner -> Workflow -> Stage -> AI contracts`

`Backends -> AI contracts`

`StageExecutor -> Project + Runtime semantic progress + generic hook contract`

`Bootstrap -> backend/plugin registries`

Workflow 不得直接依賴 Qwen/OpenCode、具體 Plugin、raw event schema 或 UI 行為；`runtime/progress.py` 是語意 facade，`runtime/events.py` 才負責 event transport/schema。AI subsystem 不得反向依賴 Workflow business stage。

CLI parsing 在 `RunRequest.from_namespace()` 結束。`RunRequest.normalized_config()` 只做一次檔案解析與公開欄位映射；`RuntimeConfig.validate()` 是一般 request 與 YAML child item 共用的執行驗證。Runner 不再保留反向或內部 Namespace 相容層。

Loop context 檢查與壓縮是 model-error Plugin。AI Client 只透過通用 Hook Chain 回報錯誤；只有 Plugin 讀取壓縮設定與 Backend 的可選 context capability。

## Workflow 契約

`Pipeline -> StageExecutor -> Stage.run() -> StageResult -> Stage.finish() -> next Stage`

Stage 一次只做一個 attempt。Hook、Project change tracking、retry/session 升級、exception conversion、lifecycle event 統一由 `StageExecutor` 負責。`StageResult` 只包含執行 facts，也可攜帶已驗證的動態 `next_steps`；`recover`、`restart_at` 這類靜態 routing 屬於 YAML `FlowNode`，Pipeline 對兩者都只做通用解讀。

`workflow/mixed.yaml`、`file.yaml`、`ai.yaml` 只包含 `stages` 與頂層 `flow`。`workflow/registry.py` 刻意只保留 Stage behavior 的 `type -> class`。`workflow/loader.py` 正規化 Stage instance，並依 YAML 結構自動推導 Planner 可用的 dynamic Stage catalog；`validator: file|ai` 表示 validation capability。`workflow/rules.py` 只負責 durable state reducer；Resume、recovery routing 與動態 `next_steps` 執行都由 Pipeline 擁有。`PlanStage` 會把每個 TODO 與 ordered Stage names 一起保存並回傳 concrete next-step definitions；不再有 `expand`、`foreach` 或額外 subflow DSL。

每個 Stage instance 只負責一次 attempt，且可獨立建構／執行；一般 Stage implementation 不得建立／選擇另一個 Stage，也不取得 `recover` 或 `restart_at`。`PlanStage` 是刻意的例外：它只能從 Loader 提供且已驗證的 Stage catalog 中選擇 Stage，並以資料 `next_steps` 回傳，不直接執行。Result handler 只把 facts reduce 成 durable state；組合與 recovery 留在 YAML `FlowNode`。

Durable state 會保存已完成的頂層 Workflow 位置與語意 fingerprint；缺少新欄位的舊 state 會相容 normalization。自訂 Workflow resume 時 fingerprint 必須一致，避免 Stage 調序後被靜默略過或重複。

## Prompt 契約

所有 bundled Prompt 統一使用 Jinja + `StrictUndefined`。Template 不直接取得 `RunState`、`RuntimeConfig` 或任意 dict。`prompts/context.py` 是唯一 Prompt Context 入口，固定 top-level variables：

`goal`, `stage`, `task`, `tasks`, `workflow`, `validation`, `project`, `planning`, `previous`, `instructions`, `rules`, `always_instructions`。

一般 AI Stage 直接指定 prompt path；沒有 prompt-builder registry。Planning / Repair Planning 的計算 context 直接由 `PlanStage` 管理。
