# CLI 完整參考

版本：1.2.66

所有 CLI option 都會映射到正式 `RunRequest`。可重複 option 每出現一次就附加一個 argv element。

| Option | 用途 | 預設 / 注意事項 |
|---|---|---|
| `--goal` | 直接給 Goal | 與 `--goal-file` 互斥 |
| `--goal-file` | UTF-8 Goal 檔 | 長需求建議使用 |
| `--project-root` | Agent 可工作的專案邊界 | `.` |
| `--script` | YAML task array；item 可用 `prompt`/`goal` 或 `goal_file` | 與 goal mode 互斥 |
| `--workflow` | 線性 Workflow YAML | 省略時依 validator 參數選擇 Mixed、File-only 或 AI-only |
| `--validator` | file validator path 或 `ai` | 除了 script mode 或明確指定 `--workflow` 之外必填 |
| `--validator-prompt` | `--validator ai` 的 Final AI 額外指示 | 空字串 |
| `--ai-validator-prompt` | file validator PASS 後追加的 Final AI 驗證指示 | 空字串/關閉 |
| `--ai-validator-prompt-file` | AI 驗證 Prompt UTF-8 檔案；與 `--ai-validator-prompt` 二選一 | 空/關閉 |
| `--backend` | `qwen` / `opencode` | `qwen` |
| `--command` | 覆寫 backend executable | backend default |
| `--sandbox` | 讓 Agent 呼叫使用 backend sandbox | 預設關閉；Qwen 加入 `-s` |
| `--agent-arg` | backend 額外一個 argv | 可重複 |
| `--validator-arg` | validator 額外一個 argv | 可重複 |
| `--protect-file` | 額外 protected file/directory | 可重複 |
| `--validator-timeout` | validator timeout 秒數 | 1200，必須 >0 |
| `--agent-timeout` | runtime AI call timeout | 7200；0=停用 |
| `--planning-timeout` | Planning AI call timeout | 600；0=停用 |
| `--agent-idle-after-change-timeout` | 變更/輸出停止後 idle timeout | 900；0=停用 |
| `--watchdog-interval` | Worker watchdog heartbeat 間隔 | 必須 >0 |
| `--worker-hang-timeout` | Worker 無活動判定 hang 的秒數 | 必須 >=0 |
| `--stage-retries` | technical Stage ERROR retry 次數 | `-1` 無限恢復並在 bounded same-session 後切 Fresh Session |
| `--max-cycles` | Workflow backward-cycle 上限 | `-1` 無限；非負整數為上限 |
| `--skip-on-max-cycles` | YAML List item 達 max_cycles 時 skip 並繼續下一 item | 預設關閉；direct run 仍以 cycle exhaustion 結束 |
| `--retry-delay` | technical failure retry delay | 5 秒 |
| `--retry-max-delay` | transient service backoff 最大 delay | 300 秒 |
| `--final-ai-validations`, `--ai-validator-count` | fresh session 的獨立 Final AI 投票數 | 1 |
| `--final-ai-required-passes` | 必要 PASS 數 | 0 = 嚴格過半；否則不可超過總票數 |
| `--ai-validator-yolo` | 允許 Final AI validation 執行 command/build/test/coverage 檢查與暫時驗證腳本 | run-level 預設關閉；bundled AI/mixed workflow 會在 stage 明確設定 |
| `--readonly-safety` | Read-only Stage 變更處理：`restore` 或 `observe` | 預設 `restore`；`observe` 只回報一般 read-only 變更、不復原，但 protected paths 仍會復原 |
| `--work-dir` | project root 內 Runner state dir | `.ai-task-runner` |

Work directory 也包含顯示／診斷用途的檔案。`stream.log` 是給 detached local UI／live inspection 使用的最近 bounded subprocess output；每個 subprocess 會重置，且不屬於 CLI control 或 Resume semantics。
| `--json-events` | 輸出 JSON Lines progress | 預設關閉 |
| `--resume` | Resume state | 預設關閉 |
| `--force-new` | 強制新 run | 與 resume 衝突 |

## Validator command 組合
若使用 `--validator validation.py --validator-arg --fab --validator-arg FAB23`，Runner 概念上執行：
`<python> validation.py --project-root <root> --state-file <state.json> --fab FAB23`。
Runner 不會理解 `fab` 等 business semantics，只原樣轉交 argv。
