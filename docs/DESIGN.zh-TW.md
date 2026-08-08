# 完整設計

Version: 1.1.1

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
5. Planning Finalize：同 session、no tools，產生至少 6 個 bounded implementation TODO。
6. Planning session/result 失敗時，使用 fresh no-tool minimal plan，重新帶 Goal、inspection summary、progress、validator feedback。
7. Refiner/Judge：fresh no-tool；異常時 fail-soft，保留最後有效 plan。二元 verdict Prompt 同時提供 FAIL/PASS 範例。
8. Executor 一次只執行一個 Current TODO。Fresh/Rebuilt session 會收到 Original Goal，但它只用於 global context；Current TODO 才是唯一 executable scope。
9. Review 使用 fresh read-only session，只審 Current TODO。若模型錯誤但 session 可續，same-session no-tool Review Finalize 直接用已取得 evidence 判斷。
10. PASS 才進下一個 TODO；semantic FAIL 留在同一 TODO，使用短 Continue Prompt，只帶新 feedback。
11. 連續 no-progress / model failure 可 rebuild session，或保留現況交給 Final Validator。
12. Deterministic Final Validator 針對完整 Goal/Project 執行。PASS 完成；FAIL 把 validator feedback 帶入 Repair Planning 再開新 cycle。Validator infrastructure error 只會 retry，不能 fail-open。
13. Optional Final AI validation 每次 fresh independent session；任何 explicit FAIL 都 veto 該 cycle，AI error 則 abstain。

## TODO 設計
Planning 至少產生 6 個具體 implementation TODO。TODO 必須 bounded、可執行，不能都是 discovery，也不能出現「implement everything / finish the project」這類 umbrella TODO。專案探索由 Planning bounded inspection 做，Executor TODO 專心實作。

## Executor scope isolation
Fresh/Rebuilt Executor 收到 Original Goal 是為了避免遺失全域限制，不代表可以執行整個 Goal。Current TODO 永遠是唯一允許執行的 scope；Later TODO 必須留給後續 Runner step。Same-session retry 不重送 Goal、Task JSON、靜態 rules。

## Retry / Recovery 原則
- 依實際 error/behavior retry，不依模型名稱或大小。
- 模型 crash 前若已有 coherent file changes，保留變更再交 Review/後續 recovery。
- Session expired/unavailable/looping 時使用 fresh rebuilt session。
- 已有足夠 evidence、只差結論時使用 same-session no-tool finalize。
- 不用過短 timeout 殺掉有進展的模型；預設允許長時間 work，idle-after-change 負責 bounded recovery。
- `max_attempts=0`、`max_cycles=0` 表示不以次數設上限。

## Validation
Python Validator 是 hard gate。Runner 固定傳 `--project-root`、`--state-file`，再把每個 `--validator-arg` 原樣附加。`validator_interface.py` 只統一 report/entry，不應放專案-specific assertion。

## Prompt 設計
Fresh/Rebuilt session context 必須自足；Same-session 只送新資訊。Planning 不再預塞完整 `Project files:` tree；可讀 stage 自己 bounded inspect，no-tool stage 使用 bounded summary。Binary verdict Prompt 同時示範 FAIL/PASS，但模型實際回答仍要求只輸出 JSON。

## Qwen transport
完整 Qwen Prompt 只寫入 subprocess stdin，之後 close EOF；不把完整 Prompt 放進 `-p` 或 argv，避免 Windows command-line 太長與雙輸入來源。Qwen stream-json event 是 backend transport protocol，與模型最終 structured result parser 分離。

## Structured result parser
全專案共用一套 JSON candidate extractor，再由各 stage 嚴格驗 schema，即「Lenient envelope, strict payload」。不使用 regex 猜 brace、不用 `ast.literal_eval`、不自動補逗號/括號、不自動轉換模型語意。

## Protected paths / Git
Policy 只從 project root 讀取。Protected directory 自動涵蓋 subtree。`.ai-task-runner.yaml` 本身自動 protected。AI child process 的 PATH guard 阻擋 `git add/commit/push`；最後 Git accept/commit/push 由人類完成。

## Debug / History
Current/last files 用於立即診斷；bounded pair history 用於完整回溯最近 call 而不讓磁碟無限成長。Terminal status/detail 只做單行化顯示；raw event/debug 仍保留真正換行與完整診斷。
