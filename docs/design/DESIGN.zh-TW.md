# 設計

Version: 1.2.33

## 原則
1. 最少 Code；Runner Core 禁止 project-specific hardcode。
2. 不影響現有功能與 24H / YAML List 穩定執行。
3. Log 精簡但足夠 Debug。
4. Workflow 不依賴具體 Plugin/Event/Backend。
5. 優先 Same Session，只補新資訊。
6. Final AI Validation 使用彼此獨立的 Fresh Session。
7. 真實 Stage failure 依序 `same session -> fresh session -> replan`；暫時性 API/service error 只走 transport backoff，不消耗 Stage failure budget。
8. Fresh Session 才提供完整且必要 Context。
9. Workflow 拓樸資料化，容易新增、移動、替換 Stage。
10. 完整 AI Prompt 固定 stdin，不放 command line。

## 主流程

`Plan -> [Execute -> Review] x TODO -> Python Validator? -> AI Validator? -> PASS`

- 沒有獨立 Understand Stage。
- Plan 寫入 durable TODO list，並回傳 TODO execution groups。
- Review 是局部 semantic gate；有設定 retry 時可 fail-soft/skip，但不能取代 Final Validator。
- Python Validator 是 deterministic gate；混合驗證時一定先於 AI Validator。
- Validator FAIL 回到 `validator_repair`：Repair Plan -> TODO execution -> validators again。
- 只有設定的 final validation path PASS 才記錄完成。

## 責任

- `workflow/definitions.py`：Stage presets + 固定 `FLOWS`。
- `workflow/rules.py`：conditions、result handlers、durable-state transition、routing。
- `workflow/stages/executor.py`：共用 retry/session recovery、hooks、events、project change tracking。
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
