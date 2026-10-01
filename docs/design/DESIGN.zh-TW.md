# 設計

Version: 1.2.66

## 原則
1. 最少 Code；Runner Core 禁止 project-specific hardcode，Global 通用行為不算 hardcode。
2. 不影響現有 24H 穩定執行，包含 YAML List。
3. Log/Event 精簡但必須足夠 Debug Stage、Session、Retry、Process、Validator 問題。
4. Workflow 不依賴具體 Plugin、Backend implementation 或 raw event schema；橫切行為只透過 Plugin/Hook/runtime semantic boundary 接入。
5. 正常流程優先 Same Session，只補新資訊，不重複 Session 已知 Context。
6. Final AI Validation 每次使用獨立 Fresh Session；設定 3 次就必須是 3 個不同 Session。
7. Validation/Structured Output 異常先 Same Session bounded recovery，最多 Retry 2 次；仍失敗才 Fresh Session。
8. 只有 Fresh/Rebuilt Session 才提供完整且必要的 Goal、Current Task、Project-state instruction 與 Stage instructions。
9. Workflow topology 必須資料化，容易新增、移動、替換或移除 Stage。
10. 能刪/合併就先瘦身，不為了抽象再增加不必要 layer；同一行為只保留一份 implementation。
11. 程式碼必須直觀、容易維護：命名清楚、function cohesive、contract 明確、layer 少。
12. 移除 dead/stale code、無需求的 compatibility shim、舊流程名稱與 unused alias。
13. 完整 AI task Prompt 固定 stdin，不放 command-line argv；短 backend control command 不屬於 task Prompt。
14. Folder、Python filename、class/function/field 命名必須符合真實責任，拆分/合併要合理。
15. 每個 Stage 都必須能獨立執行一次 attempt，不得建立、呼叫或選擇下一個具體 Stage；串接只能透過 `StageResult` 與 Pipeline/routing policy。

## 主流程

內建預設：`Plan -> [Task -> Review] x TODO -> File Validator? -> AI Validator? -> PASS`

- 沒有獨立 Understand Stage。
- `PlanStage` 是內建 AI Task Producer，透過通用 `tasks` result effect 安裝 durable TODO。
- Review 是局部 semantic gate；有設定 retry 時可 fail-soft/skip，但不能取代 Final Validator。
- 內建 CLI `mixed` Workflow 會先跑 deterministic File Validator，再跑 Final AI Validator。明確指定的 custom Workflow 可在 top-level `flow` 任意位置放置多個 File / AI Validator，Validator 後也可繼續一般 Stage。
- Validator FAIL 只依顯式 `routes.fail` edge 回到 Planning、Execute 或其他指定 Stage。
- Backward PASS/FAIL edge 是唯一 rollback/loop 機制；沒有 `restart_at`、Repair Stage 或 hidden recovery graph。
- 內建 Workflow 只有 configured validation path PASS 才完成；明確指定的 generic Workflow 可以沒有 Validator，flow 成功走完即可完成。
- 自訂 Workflow YAML 只包含命名 `stages` 與頂層 `flow`。Task Producer 以公開 Task contract 產生 durable TODO；連續的 `scope: task` Stage 定義逐 TODO SOP。Custom flow 可以使用 Plan、其他 Task Producer，或完全沒有 tasks；Runtime 不產生 `next_steps`、`expand` 或 hidden `foreach` topology。

## 責任

- `assets/workflows/*.yaml` 與 `workflow/loader.py`：內建／自訂 topology 與唯一 normalization path。
- `workflow/registry.py`：明確的 `type -> Stage class` Registry 與 UI/editor catalog metadata。
- `workflow/results.py`：StageResult parsing/reduction 與 durable task/validation effect。
- `workflow/stages/executor.py`：共用 retry/session recovery、hooks、progress reporting、project change tracking。
- `workflow/stages/*`：單次 attempt 的 Stage 行為。
- `agent/`：Qwen/OpenCode transport、Session 與 structured-output adapter。
- `workspace.py`：project files、policy、manifest/change detection 與 protection helper。
- `runtime/`：run state、process supervisor、heartbeat 與 event infrastructure。
- `plugins/`：可插拔橫切功能。

## Retry / Recovery

- Classified API/network/rate-limit/service transient error 會保留可用 Session，使用秒級 capped exponential backoff。
- 其他 technical Stage error 先在 Same Session retry；達到 per-session attempt budget 後，只輪替失敗的 Stage 到 Fresh Session，並用共用 recovery envelope 繼續。
- 無人值守全域預設是 `stage_retries=-1`。Stage 可用 local `error_policy.retries` 明確覆寫。
- Write Stage 若已落盤部分變更後發生 technical ERROR，保留目前 project evidence、輪替該 Stage Session，再從現況 recover，不盲目重播相同行為。
- Review 若有有限 local `error_policy`，technical ERROR retry 用盡後 fail-soft Skip 到下一 Stage；Final Validator 仍是 authoritative gate。
- Review semantic FAIL 使用獨立、只允許 Review 使用的 `max_failures`。`max_failures=3` 會保留 3 次真正 FAIL；第 4 次進入 Review 時不執行 reviewer，直接 fail-soft PASS，清除 durable 的 per-Review/per-Task counter，再走 PASS route。真正 Review PASS 也會清 0。
- 非 Review Stage 的有限 retry 用盡後維持 fail-closed。

## Validation Modes

- AI-only CLI 預設：內建 AI Validator 是 configured final gate。
- File-only CLI 預設：內建 File Validator 是 configured final gate。
- Mixed CLI 預設：內建 File Validator PASS 後才跑內建 Final AI Validator，兩者都必須 PASS。
- 明確指定／custom Workflow：Validation Stage 是一般 top-level gate；可交錯放置多個 File / AI Validator，每個 Validator 可擁有自己的 recovery policy。
- Final AI Validator 每次 run 使用獨立 Fresh Session；`final_ai_required_passes=0` 採嚴格多數決，明確設定時則必須達到指定 PASS 數。Structured Output 格式錯誤先 bounded same-session correction，再依設定 Fresh fallback。

## Prompt Contract

所有 bundled Prompt 統一使用 Jinja + `StrictUndefined`。`runner/prompting.py` 負責 Stage template-data contract 與 rendering helper；Template 禁止直接讀 `RunState`、`RuntimeConfig` 或任意 scratch object。

Bundled Stage Prompt 位於 `runner/assets/prompts/<category>/*.md`。每種 Stage behavior 只維護一份核心 Prompt；retry/continue/recover context 由 Runner 共用 control envelope 動態附加，不再維護平行 Prompt 檔。

## Project Safety

`runner/workspace.py` 統一負責 project manifest/change detection、protected-path policy、reusable snapshot 與 `.ai-task-runner.yaml` 相關 project-level workspace helper。Safety/Git/Readonly 透過 Plugin/Hook boundary 注入，Workflow 不 import 具體實作。

## Durable State

`runtime/run_state.py` 是唯一 durable task/run-state representation。重要 transition 後保存 state；project filesystem 仍是 implementation truth，state 只保留 resume 所需的 bounded evidence/session/recovery metadata。

## Process Survivability

`runtime/process_runner.py` 統一管理 subprocess wait、timeout、idle-after-change detection、termination。外層 supervisor/worker 依 durable state 支援 abnormal worker disappearance 後 resume。它也會把最近 bounded subprocess stdout mirror 到 `<work-dir>/stream.log`，供 detached local live display 使用。此檔每個 subprocess 都會重置，刻意是可丟棄資料，而且絕不參與 Resume、Validation、Retry、Session 或 routing 判斷。


## Runtime Scope

每次 `execute()` 都使用獨立 runtime scope。YAML List 子任務只暫時切換 active runtime/event context，結束後會恢復 parent scope，避免連續 programmatic run 或 script item 互相洩漏 Hook/Event/State。


## OpenCode backend parity

Qwen 與 OpenCode 共用 `BaseBackend` 的 stdin、timeout、idle-timeout、process-tree cleanup 與 stable recovery identity。Backend adapter 只擁有 transport/capability 差異：Qwen 使用 `--resume` + native `-s` sandbox；OpenCode 使用 `--session` + JSON event stream + `--auto`，並透過 `OPENCODE_CONFIG_CONTENT.permission` 套用 planning/no-tool/review 與 `--sandbox` 的 permission policy。Workflow、StageExecutor 與 FlowEngine 不得依 backend 名稱分支。
