# 24H 運行與故障排查

版本：1.2.64

## 長時間執行行為
預設刻意允許模型長時間工作：runtime 7200 秒、planning 600 秒、validator 1200 秒、idle-after-change 900 秒。次數限制預設為 0（不以次數限制）。恢復依 error、session availability、no-progress fingerprint、Review 與 Final Validation 決定。Timeout failure 使用穩定語意 recovery key，同時保留完整 backend stderr 供 Debug，避免 sandbox/container ID 每次改變而讓 same-failure escalation 永遠重新計數。

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
### Live output
- `<work-dir>/stream.log`：給 detached local UI／現場觀察使用的最近 bounded subprocess stdout。每個新 subprocess 開始時會清空，之後隨新輸出覆寫；它不是完整 transcript，也不可用來推導 PASS/FAIL 或 routing。

- `current-prompt.txt`：目前 call 的 Prompt，在送入 backend 前立即寫入。
- `last-prompt.txt`：上一筆完成或失敗 call 的 Prompt。
- `last-result.txt`：同一筆 call 的 Result/Error/parse diagnostic。
- `history/`：call 開始時先寫 prompt，完成或失敗時再寫相同 call-id 的 result。
History 上限為最近 100 calls、50 MiB 總量、單一 history entry 2 MiB；超大 entry 保留頭尾。Current/last 不受 history truncate 限制。

## Terminal UI
人類 Terminal status/detail 在 spinner render 前會壓成單行，backend error 的 `\n` 不會每次刷新都往下新增行。Raw JSON events/debug 仍保留完整內容。

## 發生問題時提供什麼
提供 state/event log；若問題與即時輸出有關，再附 `stream.log`；另外提供 `current-prompt.txt`、`last-prompt.txt`、`last-result.txt`、相關 history pair、執行指令與畫面錯誤，通常即可還原 stage -> prompt -> model result -> parser/backend decision -> Runner recovery。

`runner-process.json` 是 detached UI 使用的最小 Runtime identity marker，由最上層 Supervisor 管理，保存 `supervisor_pid`、目前 `worker_pid`、`started_at`、`project_root`、`work_dir`；Worker restart 時更新 `worker_pid`，Supervisor 正常結束時移除。既有 `active-process` 維持 Runner 內部 child/orphan cleanup 用途。PID metadata 不屬於 Workflow state，不得影響 PASS/FAIL、Retry、Session、routing 或 Resume。要停止 detached run，只需建立空的 `.ai-task-runner/stop.request`；Supervisor 在 Worker 執行期間與 restart backoff 期間都會檢查，收到後終止 Worker / owned child process、consume request，並以 130 結束。要繼續則以 `--resume` 重新啟動；要從頭重跑則以 `--force-new` 重新啟動。

API/network/rate-limit 暫時性異常使用逐步 backoff，但不耗盡 model/task recovery 次數，並保留 current state/session；持續的模型/session 異常才走 reuse-then-rebuild。

Safety snapshot 暫存目錄使用 `ai-task-runner-readonly-*` / `ai-task-runner-protect-*`。正常 Stage 結束會立即清除；Runner 啟動時也會清除 stale abandoned snapshot，避免異常中止後長期累積。

### Worker crash 清理

Worker 異常退出後，Supervisor 會依該 Run 實際 durable state 對應的 work directory 清理 active child-process marker；YAML List 的每個 child（`.../script/NNN/active-process`）也包含在內，不只檢查 root work directory。`KeyboardInterrupt` 與 `SystemExit` 屬於控制流程訊號：Stage hook 可先做 best-effort cleanup，但不可將它們轉成可 Retry 的 Stage failure。

一般模式與 watchdog 模式的 subprocess stdout 都會 bounded，避免外部命令大量輸出時讓 Runner 記憶體無限制成長。

## Reliability 驗證
Release / 24H 信心度請先跑 deterministic test suite，再跑 opt-in live gate。`tool/workflow_dryrun.py --matrix` 會驗 happy/recovery 路徑，以及沒有 recover 的 FAIL / technical ERROR 必須 fail-closed；`tool/qwen_live_reliability.py` 再覆蓋真實 Qwen process restart、deterministic expired-session -> Fresh Session recovery、HTTP 429/502/503 與三分鐘 disconnect recovery、timeout/session recovery、YAML List resume（含 per-item runtime options）、Final AI Fresh Session voting、detached UI 的 `stop.request -> exit 130 -> --resume`，以及可選的 single-process YAML endurance burst。Windows 0.5H / 24H preset 會在同一個 CLI process 依序跑 4 / 8 個 YAML item，用來補足 wall-clock soak 對 process 累積狀態的盲點。要宣稱 24H 仍必須真的跑滿要求的 wall-clock soak 並得到 PASS `summary.json`；只通過 preflight / burst 不能等同 24H。

## Planning 有界探索與 Loop Recovery

Planning 現在把 discovery 視為「有界行為」，不再要求每個任務都先探索 Repository。Self-contained / greenfield 任務如果 Goal 已足夠，可以直接產生 Plan；既有程式碼任務則從最小的 goal-relevant entry point 開始，只在具體 evidence 指向其他檔案、module 或 project 時才擴張。某個檔案或 symbol 已確認不存在後，除非出現新 evidence，不能重複做等價搜尋。

如果 backend 回報 `consecutive_identical_tool_calls`、`turn_tool_call_cap` 等 loop signal，Planning 最多只做一次 same-session retry；同一類 loop 再發生時，Runner 會把該 Planning Stage 切到 Fresh Session，同時保留 durable workflow state。動態 turn/context stderr 會被正規化，避免因錯誤文字每次不同而重置 escalation counter。這個策略刻意只套在 Planning，不改一般 Task / Review retry 行為。

測試涵蓋：unit test 固定 `initial -> same -> fresh` retry sequence、Prompt contract test 固定 bounded discovery、`workflow_dryrun.py --matrix` 持續驗證 deterministic workflow routing/recovery，而 `qwen_live_reliability.py` 在 live probes 前會先執行 loop classification/recovery policy preflight。

### 目前無人值守安全要點

- Read-only Planning / Review / AI validation 會重用同一份 project baseline cache，不再每個 read-only stage 都完整複製專案；合法 write 只增量同步 baseline，read-only 非預期修改仍會還原。
- Windows 核心 runtime/state/resource I/O 內部使用 extended-length path；Live reliability 在真正模型 soak 前會先測 >300 字元 runtime path 與 >260 字元 read-only restore path。
- Web UI 的 launch、Studio edit、Builder、runtime、chat、project lock 已分離；Builder validation 變慢時不再序列化無關的 Project launch/runtime 操作。
- 非 loopback Web UI bind 預設拒絕，必須明確加 `--allow-remote`。UI 沒有 authentication layer，因此不建議一般情況暴露到遠端。
- Browser 的 CLI Runtime 在兩次 polling fetch 間維持靜態，不使用 spinner/pulse 假裝收到新的 Runner 活動。

