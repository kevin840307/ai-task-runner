# 架構

目錄本身就是架構圖：

- `runner/api.py`、`bootstrap.py`、`task_runner.py`：共用 request/recovery 邊界、dependency 組裝、單次任務協調。
- `runner/script_loader.py`、`script_runner.py`：YAML 結構/檔案解析，以及經驗證的 child config 執行。
- `runner/workflow/`：Workflow 定義、路由規則、特殊 Prompt/Result adapter 與 Stage Engine。
- `runner/workflow/stages/`：Stage contract、共用 executor、`BaseStage`、`PlanStage`、隔離執行的 `PythonScriptStage`、以及 authoritative `PythonValidatorStage`。
- `runner/ai/`：AI Client、Backend contract、Session 判斷、Structured Output、AI diagnostics。
- `runner/backends/`：Qwen/OpenCode 實作與 Backend registry/configuration。
- `runner/project/`：Project snapshot/restore、policy、QWEN.md/AGENTS.md instruction file lifecycle。
- `runner/prompts/`：Strict Jinja loader、穩定 Prompt Context contract、Prompt resources。
- `runner/runtime/`：Durable state、subprocess lifecycle、worker crash supervisor、raw EventBus，以及 Workflow 使用的 semantic progress facade。
- `runner/plugins/`：Safety、Console、History、Observability、Loop context 壓縮等橫切 Plugin/Hook。
- `runner/config/`：Defaults 與唯一經驗證的 Runtime configuration contract。
- `runner/extensions.py`、`resources.py`：Workflow 驗證前的 installed extension discovery，以及共用 atomic editable-resource I/O。
- `runner/utils/`：只保留無狀態、通用的 file/text helper。

## 依賴方向

`CLI / UI / Skill -> runner.api -> Bootstrap -> TaskRunner -> Workflow -> Stage -> bounded capability`

`Backends -> AI contracts`

`StageExecutor -> Project + Runtime semantic progress + generic hook contract`

`Bootstrap -> runtime plugins`

`Extension discovery -> Stage/backend registries -> Workflow validation`

Workflow 不得直接依賴 Qwen/OpenCode、具體 Plugin、raw event schema 或 UI 行為；`runtime/progress.py` 是語意 facade，`runtime/events.py` 才負責 event transport/schema。AI subsystem 不得反向依賴 Workflow business stage。

CLI parsing 在 `RunRequest.from_namespace()` 結束。`runner.api.run()` 對所有入口統一負責 logical retry、未完成 normal return 的 resume、unexpected runtime recovery，以及 Final Validator completion guard。CLI 額外只有 `runtime/supervisor.py` 的 process-level crash isolation，不再擁有第二套 retry loop。`RunRequest.normalized_config()` 只做一次檔案解析與公開欄位映射；`RuntimeConfig.validate()` 是一般 request 與 YAML child item 共用的執行驗證。Runner 不再保留反向或內部 Namespace 相容層。

Loop context 檢查與壓縮是 model-error Plugin。AI Client 只透過通用 Hook Chain 回報錯誤；只有 Plugin 讀取壓縮設定與 Backend 的可選 context capability。

## UI / Extension 邊界

UI 是 Adapter，不是 execution Plugin。UI/CLI/Skill 只能依賴 `runner.api`、可編輯資源／catalog metadata 的 owner module 與 event callback；Pipeline、StageExecutor、Stage 不得 import UI。整包移除 UI 時，Runner execution semantics 必須完全不變。

外部 Python package 可透過 `ai_task_runner.extensions` entry point 在 Runtime 建立前註冊 `register_stage()`、Backend 等 runtime-independent capability；Discovery 發生在 Workflow validation 之前。Cross-cutting Runtime Plugin 則使用獨立的 `ai_task_runner.plugins` entry-point group，只有 Runtime 建立後才 attach。如此可擴充但不讓 Workflow Core 反向依賴 Plugin。

`workflow.registry.stage_catalog()` 直接由已註冊 Stage 的 `spec_class` 產生，UI/Tooling 不得另外 hardcode 一份 Stage schema。使用者 Python automation 使用 `type: python_script`，一律透過共用 Python process helper 在 subprocess 執行；任意使用者 Python 不會 import 進 24H Runner process。

`workflow.loader.save_workflow()`、`prompts.loader.save_prompt()` 先使用真正 Runner parser/schema 驗證，再 atomic replace；`expected_hash` 提供 UI/IDE optimistic concurrency protection。這只是共用檔案資源能力，不建立第二套 Workflow service/storage model。

Concrete Run 開始時會把 normalized Workflow、Stage Prompt、`goal_file` 與 `ai_validator_prompt_file` 持久化到該 Run work directory。Workflow Stage Prompt 維持 content-addressed；Run-level Goal／Final-AI Prompt 使用固定語意資源名稱。即使 UI/VS Code 修改或刪除來源檔，active Run 與 worker crash 後的 `--resume` 都沿用原本 Workflow／Goal／Prompt；YAML List 每個 child 在自己的 nested work directory 保存獨立 snapshot。

## Workflow 契約

`Pipeline -> StageExecutor -> Stage.run() -> StageResult -> Stage.finish() -> next Stage`

Stage 一次只做一個 attempt。Hook、Project change tracking、retry/session 升級、exception conversion、lifecycle event 統一由 `StageExecutor` 負責。`StageResult` 只包含執行 facts，也可攜帶已驗證的動態 `next_steps`；`recover`、`restart_at` 這類靜態 routing 屬於 YAML `FlowNode`，Pipeline 對兩者都只做通用解讀。

`workflow/builtin/*.yaml` 只包含 `stages` 與頂層 `flow`。`workflow/registry.py` 刻意只保留 Stage behavior 的 `type -> class`。`workflow/loader.py` 正規化 Stage instance，並依 YAML 結構自動推導 Planner 可用的 dynamic Stage catalog；`validator: file|ai` 表示 validation capability。`workflow/rules.py` 只負責 durable state reducer；Resume、recovery routing 與動態 `next_steps` 執行都由 Pipeline 擁有。`PlanStage` 會把每個 TODO 與 ordered Stage names 一起保存並回傳 concrete next-step definitions；不再有 `expand`、`foreach` 或額外 subflow DSL。

每個 Stage instance 只負責一次 attempt，且可獨立建構／執行；一般 Stage implementation 不得建立／選擇另一個 Stage，也不取得 `recover` 或 `restart_at`。`PlanStage` 是刻意的例外：它只能從 Loader 提供且已驗證的 Stage catalog 中選擇 Stage，並以資料 `next_steps` 回傳，不直接執行。Result handler 只把 facts reduce 成 durable state；組合與 recovery 留在 YAML `FlowNode`。

Durable state 會保存已完成的頂層 Workflow 位置與語意 fingerprint；缺少新欄位的舊 state 會相容 normalization。自訂 Workflow resume 時 fingerprint 必須一致，避免 Stage 調序後被靜默略過或重複。

## Prompt 契約

所有 bundled Prompt 統一使用 Jinja + `StrictUndefined`。Template 不直接取得 `RunState`、`RuntimeConfig` 或任意 dict。`prompts/context.py` 是唯一 Prompt Context 入口，固定 top-level variables：

`goal`, `stage`, `task`, `tasks`, `workflow`, `validation`, `project`, `planning`, `previous`, `instructions`, `rules`, `always_instructions`。

一般 AI Stage 直接指定 prompt path；沒有 prompt-builder registry。Planning / Repair Planning 的計算 context 直接由 `PlanStage` 管理。


## OpenCode backend parity

Qwen 與 OpenCode 共用 `BaseBackend` 的 stdin、timeout、idle-timeout、process-tree cleanup 與 stable recovery identity。Backend adapter 只擁有 transport/capability 差異：Qwen 使用 `--resume` + native `-s` sandbox；OpenCode 使用 `--session` + JSON event stream + `--auto`，並透過 `OPENCODE_CONFIG_CONTENT.permission` 套用 planning/no-tool/review 與 `--sandbox` 的 permission policy。Workflow、StageExecutor 與 Pipeline 不得依 backend 名稱分支。
