# 24H 運行與故障排查

版本：1.2.34

## 長時間執行行為
預設刻意允許模型長時間工作：runtime 7200 秒、planning 600 秒、validator 1200 秒、idle-after-change 900 秒。次數限制預設為 0（不以次數限制）。恢復依 error、session availability、no-progress fingerprint、Review 與 Final Validation 決定。

## 常見 Recovery
- Structured JSON/schema 不合法 -> 先在同 session 發短 JSON-only correction；仍無法收斂才依該 Stage 設定 Fresh fallback。Review 的 model error 依 review retry budget 決定是否 fail-soft skip。
- Session unavailable/expired -> 立即 rebuilt；單次 loop 等可恢復錯誤先保留目前 session，只有重複 loop／無進展達門檻才 bounded fresh rebuild，並重新提供必要 context。
- Executor crash 但已有檔案變更 -> 保留 coherent changes，再交 Review/後續 recovery。
- Review model/policy error -> 先走共用 Stage-aware same-session recovery。Readonly mutation 會由 Safety 還原並視為該 attempt failure，因此會 retry，不會把有 mutation 的 Review 靜默當成 PASS；retry budget 用盡且該 Stage 允許 skip 時才記錄 review_skipped。
- Validator FAIL -> 帶 validator feedback 進 Repair Planning。
- Validator infrastructure error -> retry，絕不 fail-open。

## Qwen 診斷
Qwen Prompt 固定 stdin-only。Qwen non-zero exit 仍可能已經輸出有用 stdout；Runner 會保存 raw result/diagnostic，由各 stage fail-soft 策略決定是否可繼續。Windows `3221226505` (`0xC0000409`) 是 process fast-fail，不是正常 success exit。

## Debug files
- `current-prompt.txt`：目前 call 的 Prompt，在送入 backend 前立即寫入。
- `last-prompt.txt`：上一筆完成或失敗 call 的 Prompt。
- `last-result.txt`：同一筆 call 的 Result/Error/parse diagnostic。
- `history/`：call 開始時先寫 prompt，完成或失敗時再寫相同 call-id 的 result。
History 上限為最近 100 calls、50 MiB 總量、單一 history entry 2 MiB；超大 entry 保留頭尾。Current/last 不受 history truncate 限制。

## Terminal UI
人類 Terminal status/detail 在 spinner render 前會壓成單行，backend error 的 `\n` 不會每次刷新都往下新增行。Raw JSON events/debug 仍保留完整內容。

## 發生問題時提供什麼
提供 state/event log、`current-prompt.txt`、`last-prompt.txt`、`last-result.txt`、相關 history pair、執行指令與畫面錯誤，通常即可還原 stage -> prompt -> model result -> parser/backend decision -> Runner recovery。

API/network/rate-limit 暫時性異常使用逐步 backoff，但不耗盡 model/task recovery 次數，並保留 current state/session；持續的模型/session 異常才走 reuse-then-rebuild。

Safety snapshot 暫存目錄使用 `ai-task-runner-readonly-*` / `ai-task-runner-protect-*`。正常 Stage 結束會立即清除；Runner 啟動時也會清除 stale abandoned snapshot，避免異常中止後長期累積。
