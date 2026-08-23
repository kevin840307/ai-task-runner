# 完整設計

Version: 1.2.18

## 目標
1. AI 長時間執行時，即使模型/CLI 異常也盡量保留有價值的專案變更。
2. Deterministic validation 永遠是最終 hard gate。
3. 小/中/大模型都用「實際行為與錯誤」恢復，不用 model-name/model-size hardcode。
4. Runner 必須 generic、精簡、可讀、可 Resume、安全。

## 完整流程
1. 驗證 request 與 project root。
2. 載入或建立 Runner state。
3. 建立 normalized protected roots。
4. Planning Understand：fresh session，bounded read-only inspection。
5. Planning 直接沿用主 `AgentClient` 與 session。Core 在 Planning 暫時套用 `--yolo` + bounded read-only Qwen args，進 TODO 前恢復 runtime `--yolo` args；Finalize/Judge/Rewrite 同 session 用短 Prompt，fresh/rebuilt 才補完整 context。
6. Planning output 失敗時，只要 session 仍可用就先沿用同一 planning session 重試；只有 session invalid 或重複嘗試仍無法恢復時，才清 session，使用同一 planner client 以 fresh full-context Prompt 重建。
7. Judge 沿用同一 planning client/session 審查有效 plan；context 不足時可 bounded read-only inspect。只有被拒絕才在同 session 重寫並再次 Judge；quality gate 本身無法產生可用 verdict 時 fail-soft 保留最後有效 plan。二元 verdict Prompt 同時提供 FAIL/PASS 範例。
8. Executor 一次只執行一個 Current TODO。TODO 完成後保留 Executor session；下一個 TODO 以短 Prompt 只送新的 TODO spec 與 scope 提醒。只有 Fresh/Rebuilt session 才重新帶 Original Goal 作為 global context。
9. Review 使用 fresh read-only session，只審 Current TODO。若模型錯誤但 session 可續，same-session Review Finalize 直接用已取得 evidence 判斷。
10. PASS 才進下一個 TODO；下一個 TODO resume 同一 Executor session。Semantic FAIL 留在同一 TODO，使用短 Continue Prompt，只帶新 feedback。
11. 連續 no-progress / model failure 不會提前完成 TODO 或跳 Final Validator；先沿用同 session 修復，持續無進展才 rebuild，Current TODO 仍保持 pending。Final Validator 永遠是該 cycle 所有 TODO 結束後的最後一步。
12. Deterministic Final Validator 針對完整 Goal/Project 執行。PASS 完成；FAIL 把 validator feedback 帶入 Repair Planning 再開新 cycle。Validator infrastructure error 只會 retry，不能 fail-open。
13. Optional Final AI validation 每票使用 fresh independent session，預設採嚴格過半投票。File validator 仍是 hard gate；混合驗證時只有 hard gate PASS 才跑 AI 投票，且兩邊都必須 PASS。AI call error 視為 abstain。

## TODO 設計
Planning 至少產生 6 個具體 implementation TODO。TODO 必須 bounded、可執行，不能都是 discovery，也不能出現「implement everything / finish the project」這類 umbrella TODO。專案探索由 Planning bounded inspection 做，Executor TODO 專心實作。

## Executor scope isolation
Fresh/Rebuilt Executor 收到 Original Goal 是為了避免遺失全域限制，不代表可以執行整個 Goal。Current TODO 永遠是唯一允許執行的 scope；Later TODO 必須留給後續 Runner step。跨 TODO resume 只送新的 TODO spec；同 TODO retry 不重送 Goal、Task JSON、靜態 rules。

## Retry / Recovery 原則
- 依實際 error/behavior retry，不依模型名稱或大小。
- 模型 crash 前若已有 coherent file changes，保留變更再交 Review/後續 recovery。
- Session expired/unavailable 時立即 fresh rebuilt；單次 loop 等可恢復錯誤先沿用 session，只有重複 loop／no-progress 達門檻才 fresh rebuilt。
- 執行中的 continuation 全專案採單一規則：保留同一個 `AgentClient` 與其 session，禁止只為 resume 舊 session 而建立新 client。Planning Finalize 重用 Understand planner；Review Finalize 重用 Reviewer；Executor retry 與後續 TODO 都持續重用主 Executor client，直到 Runner 因 session 無效或重複停滯而主動清空 session。只有程式重啟後的 `--resume` 可用 state 中 session id 建立新 client，因為舊 Python client 已不存在。
- 不用過短 timeout 殺掉有進展的模型；預設允許長時間 work，idle-after-change 負責 bounded recovery。
- `max_attempts`、`max_cycles` 是恢復策略升級門檻，不是終止上限。`0` 代表關閉對應的次數門檻；可恢復錯誤仍會在 retry、fresh session、replan 間持續循環。

## Validation
Python Validator 是 hard gate。Runner 固定傳 `--project-root`、`--state-file`，再把每個 `--validator-arg` 原樣附加。`validator_interface.py` 只統一 report/entry，不應放專案-specific assertion。

## Prompt 設計
Fresh/Rebuilt session context 必須自足；Same-session 只送新資訊。Structured output / schema 不合法視為「模型正常回覆但格式錯誤」，先用同 session 發一次簡短 JSON-only correction，再依 stage fallback/rebuild。Planning 不再預塞完整 `Project files:` tree；所有 planning step 共用 bounded read-only tool policy，需要證據時才 inspect，context 已足夠時不再探索。Binary verdict Prompt 同時示範 FAIL/PASS，但模型實際回答仍要求只輸出 JSON。

## Qwen transport
完整 Qwen Prompt 只寫入 subprocess stdin，之後 close EOF；不把完整 Prompt 放進 `-p` 或 argv，避免 Windows command-line 太長與雙輸入來源。Qwen stream-json event 是 backend transport protocol，與模型最終 structured result parser 分離。

## Structured result parser
全專案共用一套 JSON candidate extractor，再由各 stage 嚴格驗 schema，即「Lenient envelope, strict payload」。不使用 regex 猜 brace、不用 `ast.literal_eval`、不自動補逗號/括號、不自動轉換模型語意。

## Protected paths / Git
Policy 只從 project root 讀取。Protected directory 自動涵蓋 subtree。`.ai-task-runner.yaml` 本身自動 protected。AI child process 的 PATH guard 阻擋 `git add/commit/push`；最後 Git accept/commit/push 由人類完成。

## Debug / History
Current/last files 用於立即診斷；bounded pair history 用於完整回溯最近 call 而不讓磁碟無限成長。Terminal status/detail 只做單行化顯示；raw event/debug 仍保留真正換行與完整診斷。

## 相容性清理
Internal helper 維持單一 canonical 名稱與 signature；已無用途的內部 alias、無效 compatibility parameter 應直接移除，不永久累積。可能被外部 Python caller 使用的 compatibility alias，除非明確做 public breaking change，否則先保留；新程式一律使用 `RunRequest`、`AgentClient`、`RunState`、`AgentBackend` canonical 名稱。

恢復策略集中處理：可恢復的 runtime outcome 只會映射成 `ADVANCE`、`RETRY`、`REPLAN`。任務恢復依序升級 `same session -> fresh session -> replan`；Validator FAIL 保留專案成果後重新規劃。可恢復的 workflow 錯誤不會產生終止 exit code，只有 Final Validator PASS 才宣告完成。

Execution Loop 統一使用 `Outcome -> Transition`：Execute、Review、Planning recovery、Final Validator 只回報 `pass / fail / error`、是否有進展、是否已有可用成果，再由單一 policy 決定 `ADVANCE`、`RETRY(same|fresh)` 或 `REPLAN`。Review 明確 FAIL 與 Reviewer ERROR 保持不同：FAIL 必須重試 TODO；Reviewer 本身反覆異常才允許 fail-soft `review_skipped`，最後仍由 Final Validator hard gate 把關。
