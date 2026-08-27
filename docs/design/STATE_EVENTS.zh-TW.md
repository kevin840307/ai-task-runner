# State 與 Events

版本：1.2.39

## State
Runner state 放在 project-relative work dir（預設 `.ai-task-runner`）。內容包含 run/cycle identity、current task index、task status/attempts/review、session id、progress/recovery metadata 與 Resume 需要的 completion state。實際 JSON 是內部 persistence format；Integration 應優先使用 Public API/Event，不要直接修改 state。

## Resume 規則
`--resume` 載入相容 state。因為程式重啟會使本機 `AIClient` 消失，只有這條路徑允許用已保存的遠端 session id 重建新 client；同一個執行程序內的 continuation 一律重用既有 client/session。`--force-new` 開新 run。Script item 各自使用 nested state dir。Executor session id 在完成 TODO 後會保留，下一個 TODO 可在 session 仍可用時沿用；只有明確 rebuild/completion 條件才清除。真正 durable source of truth 是 project files + Runner state，不是 AI chat memory。

## JSON Events
使用 `--json-events` 時輸出 JSON Lines。核心 event 含 schema/runner version、timestamp、status/detail、run id、cycle、current index、completed、task summary。Script mode 額外有 `script.item_started`、`script.item_completed`、`script.item_failed`。

## Human UI
Human UI 是同一份 state/event 的視覺化。Backend detail 的多行只在 Terminal render 前壓成單行；raw diagnostic 不會被改寫。

## State ownership
AI Agent 不可修改 Runner state。Project policy 自動 protected；Runner 自己對 debug/state 的寫入由 Runner 擁有，且不算一般 project change。

## Runtime Scope
每次 `execute()` 都有自己的 scoped runtime/event context。YAML List child item 只暫時切換 context，結束後恢復 parent，避免連續 programmatic call 與 nested batch 互相洩漏 Hook/Event/State。
