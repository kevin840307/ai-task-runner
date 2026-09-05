# 設計

Version: 1.2.61

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

內建預設：`Plan -> [Execute -> Review] x TODO -> File Validator? -> AI Validator? -> PASS`

- 沒有獨立 Understand Stage。
- `PlanStage` 是內建 AI Task Producer，透過通用 `tasks` result effect 安裝 durable TODO。
- Review 是局部 semantic gate；有設定 retry 時可 fail-soft/skip，但不能取代 Final Validator。
- File Validator 是 deterministic gate；混合驗證時一定先於 AI Validator。
- Validator FAIL 走該 Stage 設定的 recovery path，通常是 Repair Plan -> task-scoped SOP -> validators again。
- Stage 可用共用的 1-based YAML `restart_at` 覆蓋 FAIL/replan recovery；未設定時保留上述內建路由。
- 內建 Regression Workflow 只有 configured final validation path PASS 才完成；明確指定的 generic Workflow 可以沒有 Validator，flow 全部成功結束即可完成。
- 自訂 Workflow YAML 只包含命名 `stages` 與頂層 `flow`。`PlanStage` 會自動使用標準 `execute -> review` task SOP，因此一般 Plan-driven flow 只需要列 Planning 與後續頂層 gate。其他 Stage 仍可用 `produces: tasks` 產生公開 Task contract；顯式 `scope: task` 保留給進階／自訂逐 TODO SOP。Custom flow 可以使用 Plan、其他 Task Producer，或完全沒有 tasks；Runtime 不再產生 `next_steps`、`expand` 或 `foreach` topology。

## 責任

- `workflow/system/*.yaml`、`workflow/loader.py`：依 validator 選擇的內建拓樸、自訂拓樸與唯一 normalization 路徑。
- `workflow/registry.py`：明確的 `type -> Stage class` Registry，並提供 UI/editor catalog metadata；不持有 Workflow topology 或 Stage instance。
- `workflow/rules.py`：少量 `StageResult.kind` reducer 與 durable-state transition（`tasks`、`task`、`review`、`validation`、`generic`）。
- `workflow/stages/executor.py`：共用 retry/session recovery、hooks、semantic progress reporting、project change tracking。
- `workflow/stages/*`：單次 attempt 的 Stage 行為。
- `ai/`：AI interaction/session/structured output。
- `backends/`：Qwen/OpenCode transport implementation。
- `project/`：workspace files/policy/instruction files。
- `runtime/`：run state/process/event infrastructure。
- `plugins/`：可插拔橫切功能。

## Retry / Recovery

- API/network/rate-limit/service 暫時性錯誤由 `AIClient.run_with_retry()` 做 bounded exponential backoff，保留 state/session。
- 真實 Stage error 先沿用可用 Same Session retry，使用短 Stage-aware delta prompt，只補 Stage 身分、新 failure evidence 與下一步，不重送完整 Goal/Task Context。
- Same-session retry budget 用完後，StageExecutor 清除 cached session，Fresh retry。
- Fresh 後仍持續相同 failure 才回 `replan`。
- Failure fingerprint 改變時重新計數。Backend timeout 會提供穩定的語意 recovery key；sandbox/container identifier 等動態 stderr 仍保留在 diagnostics，但不參與 failure identity。
- Write attempt 只要產生實際 project changes 就視為 progress，交給 Review/Validator 判斷，不直接丟棄。
- Review skip 不代表完成；Final Validator 仍需把關。

## Validation Modes

- AI-only：AI Validator 是 configured final gate。
- File-only：File Validator 是 configured final gate。
- Mixed：File Validator PASS 後才跑 Final AI Validator，兩者都必須 PASS。
- Final AI Validator 每次 run 使用獨立 Fresh Session；`final_ai_required_passes=0` 採嚴格多數決，明確設定時則必須達到指定 PASS 數。Structured Output 格式錯誤先 bounded same-session correction，再依設定 Fresh fallback。

## Prompt Contract

所有 bundled Prompt 統一 Jinja + `StrictUndefined`。`prompts/context.py` 是唯一 Stage Template Data Contract；Template 禁止直接讀 `RunState`、`RuntimeConfig`、任意 scratch object。

一般 AI Stage 直接指定 `prompts/stages/*.md`；Planning computed context 直接由 `PlanStage` 管理，不再有 prompt-builder registry。共用 Prompt fragment 使用 Jinja `{% include %}`。

## Project Safety

`project/policy.py` 讀 `.ai-task-runner.yaml`；`project/files.py` 管 manifest/change detection/restore 與 stale Safety snapshot cleanup；`project/instructions.py` 管 QWEN.md/AGENTS.md 的 Runner-managed section。Safety/Git/Readonly 透過 Plugin/Hook 注入，Workflow 不 import 具體實作。

## Durable State

`runtime/run_state.py` 是唯一 durable task/run-state representation。重要 transition 後保存 state；project filesystem 仍是 implementation truth，state 只保留 resume 所需的 bounded evidence/session/recovery metadata。

## Process Survivability

`runtime/process_runner.py` 統一管理 subprocess wait、timeout、idle-after-change detection、termination。外層 supervisor/worker 依 durable state 支援 abnormal worker disappearance 後 resume。它也會把最近 bounded subprocess stdout mirror 到 `<work-dir>/stream.log`，供 detached local live display 使用。此檔每個 subprocess 都會重置，刻意是可丟棄資料，而且絕不參與 Resume、Validation、Retry、Session 或 routing 判斷。


## Runtime Scope

每次 `execute()` 都使用獨立 runtime scope。YAML List 子任務只暫時切換 active runtime/event context，結束後會恢復 parent scope，避免連續 programmatic run 或 script item 互相洩漏 Hook/Event/State。


## OpenCode backend parity

Qwen 與 OpenCode 共用 `BaseBackend` 的 stdin、timeout、idle-timeout、process-tree cleanup 與 stable recovery identity。Backend adapter 只擁有 transport/capability 差異：Qwen 使用 `--resume` + native `-s` sandbox；OpenCode 使用 `--session` + JSON event stream + `--auto`，並透過 `OPENCODE_CONFIG_CONTENT.permission` 套用 planning/no-tool/review 與 `--sandbox` 的 permission policy。Workflow、StageExecutor 與 Pipeline 不得依 backend 名稱分支。
