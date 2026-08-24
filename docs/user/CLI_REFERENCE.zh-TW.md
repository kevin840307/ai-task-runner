# CLI 完整參考

版本：1.2.33

所有 CLI option 都會映射到正式 `RunRequest`。可重複 option 每出現一次就附加一個 argv element。

| Option | 用途 | 預設 / 注意事項 |
|---|---|---|
| `--goal` | 直接給 Goal | 與 `--goal-file` 互斥 |
| `--goal-file` | UTF-8 Goal 檔 | 長需求建議使用 |
| `--project-root` | Agent 可工作的專案邊界 | `.` |
| `--script` | YAML task array；item 可用 `prompt`/`goal` 或 `goal_file` | 與 goal mode 互斥 |
| `--validator` | Python validator path 或 `ai` | 非 script mode 必填 |
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
| `--max-attempts` | Same Session 恢復上限 | `-1` 持續恢復直到 PASS，`0` 停用 Same Session retry，正數表示達該次數後切換 Fresh Session。預設：`2`。 |
| `--review-retries` | AI Review 恢復上限 | `-1` 重試直到 PASS，`0` 停用 retry，正數表示達該次數後 skip Review。預設：`1`；Final Validator 仍是最終權威。 |
| `--max-cycles` | Workflow/replan cycle 上限 | `-1` 持續驗證與修復直到 PASS，`0` 停用 replan，正數是有限終止上限。預設：`-1`。 |
| `--retry-delay` | 邏輯 task retry delay | 2 秒 |
| `--retry-wait` | model-call 初始 retry wait | 5 秒 |
| `--retry-max-wait` | model-call 最大 retry wait | 300 秒 |
| `--final-ai-validations`, `--ai-validator-count` | fresh session 的獨立 Final AI 投票數 | 1 |
| `--final-ai-required-passes` | 必要 PASS 數 | 0 = 嚴格過半；否則不可超過總票數 |
| `--work-dir` | project root 內 Runner state dir | `.ai-task-runner` |
| `--json-events` | 輸出 JSON Lines progress | 預設關閉 |
| `--resume` | Resume state | 預設關閉 |
| `--force-new` | 強制新 run | 與 resume 衝突 |
| `--plan-only` | 只規劃、保存、退出 | 預設關閉 |

## Validator command 組合
若使用 `--validator validation.py --validator-arg --fab --validator-arg FAB23`，Runner 概念上執行：
`<python> validation.py --project-root <root> --state-file <state.json> --fab FAB23`。
Runner 不會理解 `fab` 等 business semantics，只原樣轉交 argv。
