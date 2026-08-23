# 系統架構

版本：1.2.21

## 責任邊界
Runner 只負責 orchestration、state、retry/recovery、session policy、保護、模型傳輸、Prompt 組裝、result parsing、validation orchestration、UI/events 與 diagnostics。Runner 不應理解應用程式 workflow、FAB、ENV、版本或 business value。專案需求應存在 Goal、專案程式碼、Validator、Template、Fixture 與 `.ai-task-runner.yaml`。

## Package 分區
- `ai_task_runner.py`：CLI adapter。
- `runner/api.py`：CLI/UI/Skill/Python 共用的 `RunRequest` / `run()` 正式入口。
- `runner/engine/core.py`：狀態機與主流程。
- `runner/workflow/`：Planning、Review、AI/File Validation，以及決策階段共用的唯讀 structured-call 邊界。
- `runner/agent/`：AgentClient/Factory、stage arguments、Prompt、模型 retry、structured results 與 diagnostics。
- `runner/backends/`：可替換的 Qwen/OpenCode transport 與 backend-specific argument policy。
- `runner/safety/`：project policy、protected/read-only guard 與 child-process Git publication guard。
- `runner/engine/state_store.py`：state 載入、原子儲存與外部備份恢復。
- `runner/runtime/process_control.py`：subprocess timeout/idle/watchdog。
- `runner/script_runner.py`：YAML batch orchestration。
- `runner/app/ui.py`：Terminal UI 與 JSON events。
- 每項功能只保留一個正式 module path，不再發佈過時的頂層相容模組。

依賴方向固定為 `api -> core -> workflow -> agent/safety -> backends/process/state`，底層不得反向 import `core` 或 workflow stage。

## 資料流
`RunRequest -> request validation -> state -> protected roots -> Planning -> TODO Executor -> Review -> 下一個 TODO -> Deterministic Final Validator -> optional Final AI Validator -> 完成或 Repair Planning`。

## Session 規則
- Fresh Understand：完整 Goal/context + bounded read tools，禁止寫入。
- Same-session Plan：只送下一步與輸出契約，不重送靜態 context。
- Planning fallback/Judge：decision context 必須足以支援 recovery。Judge 與 Rewrite 沿用產生目前 plan 的 Planner；若共用 Agent policy 判定 session 不可用並 reset，同一 client 才以自足 Prompt fresh 重建。
- Fresh/Rebuilt Executor：Original Goal 只提供 global context；Current TODO 是唯一 executable scope。
- Executor 跨 TODO 維持同 session：下一個 TODO 只送短 next-TODO Prompt；retry／Review 修正只送新增 feedback 的 Continue Prompt。
- Fresh Review：只看 Current TODO/evidence，read-only；Review 是刻意的獨立 session 邊界。
- Same-session Review Finalize：停止查詢，直接輸出 verdict。
- Final AI Validator：fresh independent session，驗完整 Goal。

## Structured output
所有模型最終 structured result 都走 `runner/agent/results.py` 同一套 extractor。允許乾淨 JSON、Markdown fence、前後自然語言、或多個 top-level JSON candidate；之後由各 stage 嚴格驗 schema。JSON 壞掉、欄位型別錯、必要欄位缺少、TODO 數不足或語意不合法都必須 FAIL，Runner 不猜、不補、不偷偷修 payload。

## 保護模型
Protected path 會正規化成 root；保護資料夾即保護 subtree。來源包含 Runner source、goal/validator、backend files、CLI `--protect-file` 與 project-root `.ai-task-runner.yaml`。Policy 本身自動保護。AI 違規修改會依 snapshot 偵測並還原。

## Debug
每次模型 backend call 前會立即寫入 `current-prompt.txt`，同時先保存 `debug/history/<call-id>-prompt.txt`，因此即使 call 卡住或程序中止也能留下輸入。完成或失敗後再寫 `last-prompt.txt`、`last-result.txt` 與相同 call-id 的 `history/<call-id>-result.txt`。History 仍採 bounded rotation（預設最近 100 calls、50 MiB、單筆 entry 2 MiB，保留頭尾）。Debug failure 為 fail-soft，且不影響 changed-files/progress/validation/resume。

## Session continuation 不變量

同一個 Runner 程序內，每個 logical agent role 維持同一個 `AgentClient`；continuation 只沿用其 `session_id` 狀態，不得只為 resume 而建立替代 client。Fresh 獨立角色使用空 session。程式重啟後的 `--resume` 因舊本機 client 已不存在，才可從持久化 state 重建主 client。
