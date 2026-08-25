# 設計

Version: 1.2.33

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

內建預設：`Plan -> [Execute -> Review] x TODO -> Python Validator? -> AI Validator? -> PASS`

- 沒有獨立 Understand Stage。
- Plan 寫入 durable TODO list，並回傳 TODO execution groups。
- Review 是局部 semantic gate；有設定 retry 時可 fail-soft/skip，但不能取代 Final Validator。
- Python Validator 是 deterministic gate；混合驗證時一定先於 AI Validator。
- Validator FAIL 回到 `validator_repair`：Repair Plan -> TODO execution -> validators again。
- Stage 可用共用的 1-based YAML `restart_at` 覆蓋 FAIL/replan recovery；未設定時保留上述內建路由。
- 只有設定的 final validation path PASS 才記錄完成。
- 自訂 Workflow YAML 只包含命名 `stages` 與頂層 `flow`。Planning 會把每個 TODO 與其選定 Stage sequence 一起保存並回傳已驗證的 `next_steps`，Pipeline 執行完成後再進 final validation。可用 dynamic Stage 由 YAML 結構自動推導，不需要 `expand` 或 `foreach`。

## 責任

- `workflow/mixed.yaml`、`file.yaml`、`ai.yaml`、`workflow/loader.py`：依 validator 選擇的內建拓樸、自訂拓樸與唯一 normalization 路徑。
- `workflow/registry.py`：明確的 `type -> Stage class` Registry，並負責 semantic parser/handler/condition 解析；不持有 Workflow topology 或 Stage instance。
- `workflow/rules.py`：內部 TODO/repair subflow、conditions、result handlers、durable-state transition 與 routing。
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
- Failure fingerprint 改變時重新計數。
- Write attempt 只要產生實際 project changes 就視為 progress，交給 Review/Validator 判斷，不直接丟棄。
- Review skip 不代表完成；Final Validator 仍需把關。

## Validation Modes

- AI-only：Python Validator Stage skip，Final AI Validator 決定。
- Python-only：Python Validator 是 final configured gate，AI Stage condition skip。
- Mixed：Python Validator PASS 後才跑 Final AI Validator，兩者都必須 PASS。
- Final AI Validator 每次 run 使用獨立 Fresh Session；`final_ai_required_passes=0` 採嚴格多數決，明確設定時則必須達到指定 PASS 數。Structured Output 格式錯誤先 bounded same-session correction，再依設定 Fresh fallback。

## Prompt Contract

所有 bundled Prompt 統一 Jinja + `StrictUndefined`。`prompts/context.py` 是唯一 Stage Template Data Contract；Template 禁止直接讀 `RunState`、`RuntimeConfig`、任意 scratch object。

一般 AI Stage 直接指定 `prompts/stages/*.md`；Planning computed context 直接由 `PlanStage` 管理，不再有 prompt-builder registry。共用 Prompt fragment 使用 Jinja `{% include %}`。

## Project Safety

`project/policy.py` 讀 `.ai-task-runner.yaml`；`project/files.py` 管 manifest/change detection/restore 與 stale Safety snapshot cleanup；`project/instructions.py` 管 QWEN.md/AGENTS.md 的 Runner-managed section。Safety/Git/Readonly 透過 Plugin/Hook 注入，Workflow 不 import 具體實作。

## Durable State

`runtime/run_state.py` 是唯一 durable task/run-state representation。重要 transition 後保存 state；project filesystem 仍是 implementation truth，state 只保留 resume 所需的 bounded evidence/session/recovery metadata。

## Process Survivability

`runtime/process_runner.py` 統一管理 subprocess wait、timeout、idle-after-change detection、termination。外層 supervisor/worker 依 durable state 支援 abnormal worker disappearance 後 resume。


## Runtime Scope

每次 `execute()` 都使用獨立 runtime scope。YAML List 子任務只暫時切換 active runtime/event context，結束後會恢復 parent scope，避免連續 programmatic run 或 script item 互相洩漏 Hook/Event/State。
