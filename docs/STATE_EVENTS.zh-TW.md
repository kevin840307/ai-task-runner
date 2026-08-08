# State 與 Events

版本：1.1.1

## State
Runner state 放在 project-relative work dir（預設 `.ai-task-runner`）。內容包含 run/cycle identity、current task index、task status/attempts/review、session id、progress/recovery metadata 與 Resume 需要的 completion state。實際 JSON 是內部 persistence format；Integration 應優先使用 Public API/Event，不要直接修改 state。

## Resume 規則
`--resume` 載入相容 state；`--force-new` 開新 run。Script item 各自使用 nested state dir。Task 完成後 agent session id 可能清空；真正 durable source of truth 是 project files + Runner state，不是模型 chat memory。

## JSON Events
使用 `--json-events` 時輸出 JSON Lines。核心 event 含 schema/runner version、timestamp、status/detail、run id、cycle、current index、completed、task summary。Script mode 額外有 `script.item_started`、`script.item_completed`、`script.item_failed`。

## Human UI
Human UI 是同一份 state/event 的視覺化。Backend detail 的多行只在 Terminal render 前壓成單行；raw diagnostic 不會被改寫。

## State ownership
AI Agent 不可修改 Runner state。Project policy 自動 protected；Runner 自己對 debug/state 的寫入由 Runner 擁有，且不算一般 project change。
