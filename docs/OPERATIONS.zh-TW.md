# 24H 運行與故障排查

版本：1.1.1

## 長時間執行行為
預設刻意允許模型長時間工作：runtime 7200 秒、planning 600 秒、validator 1200 秒、idle-after-change 900 秒。次數限制預設為 0（不以次數限制）。恢復依 error、session availability、no-progress fingerprint、Review 與 Final Validation 決定。

## 常見 Recovery
- Planning JSON/schema/task count 不合法 -> retry/fallback，能保留時保留最後 valid plan。
- Session unavailable/expired/loop detection -> Fresh rebuilt session，重新提供必要 context。
- Executor crash 但已有檔案變更 -> 保留 coherent changes，再交 Review/後續 recovery。
- Review model error 但 session 可 resume -> no-tool Review Finalize。
- Validator FAIL -> 帶 validator feedback 進 Repair Planning。
- Validator infrastructure error -> retry，絕不 fail-open。

## Qwen 診斷
Qwen Prompt 固定 stdin-only。Qwen non-zero exit 仍可能已經輸出有用 stdout；Runner 會保存 raw result/diagnostic，由各 stage fail-soft 策略決定是否可繼續。Windows `3221226505` (`0xC0000409`) 是 process fast-fail，不是正常 success exit。

## Debug files
- `current-prompt.txt`：目前 call 的 Prompt，call 開始時更新。
- `last-prompt.txt`：上一筆完成 call 的 Prompt。
- `last-result.txt`：同一筆 call 的 Result/Error/parse diagnostic。
- `history/`：最近 Prompt/Result 成對歷史。
History 上限為最近 100 calls、50 MiB 總量、單一 history entry 2 MiB；超大 entry 保留頭尾。Current/last 不受 history truncate 限制。

## Terminal UI
人類 Terminal status/detail 在 spinner render 前會壓成單行，backend error 的 `\n` 不會每次刷新都往下新增行。Raw JSON events/debug 仍保留完整內容。

## 發生問題時提供什麼
提供 state/event log、`current-prompt.txt`、`last-prompt.txt`、`last-result.txt`、相關 history pair、執行指令與畫面錯誤，通常即可還原 stage -> prompt -> model result -> parser/backend decision -> Runner recovery。
