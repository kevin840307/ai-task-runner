# 維運

## Reliability Ownership

StageExecutor 負責 technical retry / session recovery；FlowEngine 負責 semantic PASS/FAIL navigation。排查時先判斷問題屬於哪一邊。

### Technical ERROR

例如 timeout、backend crash、transient HTTP、model transport/session failure。

處理：

1. 適合時先用目前 Session retry 同一 Stage；
2. 連續 recoverable failure 後，只替該 Stage 切 fresh Session；
3. graph position 不變；
4. 有限 retry budget 用盡時停在目前 Stage，fail-closed。

`stage_retries=-1` 表示 technical retry 不限次。HTTP 429/502/503 依 retry delay/max-delay backoff。

### Semantic FAIL

FAIL 是有效 Stage 結果，不是 technical exception。FlowEngine 走 `routes.fail`，沒有 FAIL route 就停止。回到前面 Stage 就是 rollback/loop。

目前沒有 operational repair/recover Stage。

## Session 維運

- `main`：Runner 主 Session。
- `role`：由 Stage name 擁有的 durable Session。
- `fresh`：每次 invocation 新 Session。
- `auto`：built-in/internal profile 行為。

Reset 單一失敗 `role` 不可清掉其他 role Session；global reset 才清主 Session + 所有 durable role Session。

## Resume

Resume 從 committed state 繼續。重要 durable state 包含 workflow/task position、previous transition evidence、primary Session、per-role Sessions。

若 crash 發生在 Stage commit 之前，目前 Stage 可能重跑；已 commit 完成的 Stage 不應重複。

## Stop / Detached UI

UI 只寫正式 Runner control marker。Supervisor 停止後必須清理 process/control marker 與 child process；重新啟動使用 `--resume` 依 durable state 還原，不依賴 UI local status。

## Log / Diagnostics

建議收集：

- state.json；
- Runner event/log；
- process ownership 問題時的 runner-process/control marker；
- `stream.log`；
- current/last prompt/result；
- 相關 bounded debug history；
- 完整執行指令與畫面錯誤。

長時間無人值守必須確保 log 有 bounded/rotation。

## Release Gates

1. Ubuntu + Windows compile/pytest + Studio build。
2. deterministic dry-run/session/retry/resume matrix。
3. real-Qwen short gate：`tool\qwen_live_reliability_0_5h.bat`
4. high-density soak。
5. full 24H：`tool\qwen_live_reliability_24h.bat`

real-Qwen gate 會覆蓋 Dynamic Handoff/session policy、Review/Validator rollback、transient HTTP、disconnect、expired Session、process restart、detached UI resume、YAML List resume、custom Task producer、Final AI voting。

source 裡「有 probe」不等於實際「已 PASS」；要保留該次 summary/run directory 才能宣稱 live/24H evidence。

## 變更原則

Deterministic CI 綠燈後，不要在 real/24H gate 前做推測性大重構。只修會影響無人值守、state correctness、session isolation、process cleanup、UI/runtime contract 的可重現高價值問題。
