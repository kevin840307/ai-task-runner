# 系統架構

版本：1.1.1

## 責任邊界
Runner 只負責 orchestration、state、retry/recovery、session policy、保護、模型傳輸、Prompt 組裝、result parsing、validation orchestration、UI/events 與 diagnostics。Runner 不應理解應用程式 workflow、FAB、ENV、版本或 business value。專案需求應存在 Goal、專案程式碼、Validator、Template、Fixture 與 `.ai-task-runner.yaml`。

## 模組
- `ai_task_runner.py`：CLI adapter。
- `runner/api.py`：CLI/UI/Skill/Python 共用的 `RunRequest` / `run()` 正式入口。
- `runner/core.py`：狀態機與主流程。
- `runner/planning.py`：Understand、Plan、fallback、Refiner、Judge。
- `runner/reviewing.py`：Current TODO Review 與 no-tool finalize。
- `runner/validation.py`：Deterministic / Final AI validation orchestration。
- `runner/model_results.py`：唯一通用 JSON candidate extraction + 各 stage 嚴格 parser。
- `runner/prompting.py`：Prompt/context 組裝。
- `runner/policy.py`：project-root policy。
- `runner/support.py`：共用 state/filesystem/retry/protection helper。
- `runner/debug.py`：current/last/history diagnostics。
- `runner/process_control.py`：subprocess timeout/idle/watchdog。
- `runner/git_guard.py`：阻擋 AI child process 的 `git add/commit/push`。
- `runner/backends/`：Qwen/OpenCode transport。
- `runner/ui.py`：Terminal UI 與 JSON events。

## 資料流
`RunRequest -> request validation -> state -> protected roots -> Planning -> TODO Executor -> Review -> 下一個 TODO -> Deterministic Final Validator -> optional Final AI Validator -> 完成或 Repair Planning`。

## Session 規則
- Fresh Understand：完整 Goal/context + bounded read tools，禁止寫入。
- Same-session Plan：只送下一步與輸出契約，不重送靜態 context。
- Fresh fallback/Refiner/Judge：no-tool，但 context 必須自足。
- Fresh/Rebuilt Executor：Original Goal 只提供 global context；Current TODO 是唯一 executable scope。
- Same-session Executor retry：短 Continue Prompt，只帶最新 Review/recovery feedback。
- Fresh Review：只看 Current TODO/evidence，read-only。
- Same-session Review Finalize：停止查詢，直接輸出 verdict。
- Final AI Validator：fresh independent session，驗完整 Goal。

## Structured output
所有模型最終 structured result 都走 `runner/model_results.py` 同一套 extractor。允許乾淨 JSON、Markdown fence、前後自然語言、或多個 top-level JSON candidate；之後由各 stage 嚴格驗 schema。JSON 壞掉、欄位型別錯、必要欄位缺少、TODO 數不足或語意不合法都必須 FAIL，Runner 不猜、不補、不偷偷修 payload。

## 保護模型
Protected path 會正規化成 root；保護資料夾即保護 subtree。來源包含 Runner source、goal/validator、backend files、CLI `--protect-file` 與 project-root `.ai-task-runner.yaml`。Policy 本身自動保護。AI 違規修改會依 snapshot 偵測並還原。

## Debug
`current-prompt.txt` 是正在執行的 call；`last-prompt.txt` / `last-result.txt` 是上一筆完成或失敗的 call；`debug/history/` 成對保存 bounded history，預設最近 100 calls、50 MiB、單筆 history entry 2 MiB（保留頭尾）。Debug failure 為 fail-soft，且不影響 changed-files/progress/validation/resume。

## Session continuation 不變量

同一個 Runner 程序內，每個 logical agent role 維持同一個 `AgentClient`；continuation 只沿用其 `session_id` 狀態，不得只為 resume 而建立替代 client。Fresh 獨立角色使用空 session。程式重啟後的 `--resume` 因舊本機 client 已不存在，才可從持久化 state 重建主 client。
