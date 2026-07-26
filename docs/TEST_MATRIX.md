# AI Task Runner v1.1.1 異常測試矩陣

## 結果摘要

| 類別 | 數量 | 結果 |
|---|---:|---|
| Backend | 10 | PASS |
| Examples | 5 | PASS |
| Python API／CLI／Events | 14 | PASS |
| Public contract／相容性 | 6 | PASS |
| 核心 Runner | 34 | PASS |
| v1.1.1 韌性與異常 | 30 | PASS（1 skipped） |
| 文件契約 | 5 | PASS |
| **總計** | **108** | **107 PASS／1 skipped** |

執行環境：Windows、Python 3.10.0。測試以隔離群組執行，避免長時間 subprocess 測試互相污染。Python compile 另行通過。

## 異常矩陣

| 範圍 | 已測情境 | 預期與結果 |
|---|---|---|
| Command | executable 不存在 | Fail-fast；不建立新 state，PASS |
| Force New | 新初始化失敗 | 舊 state 保持不變，PASS |
| Resume | state 不存在 | 清楚錯誤，PASS |
| Resume | JSON 損毀 | `invalid resume state`，PASS |
| Resume | project root 不一致 | 拒絕載入，PASS |
| State | current 越界、非法 status | 拒絕載入，PASS |
| 相容 State | 缺少新欄位 | 使用預設值載入，PASS |
| Session | 6 種 invalid／expired marker | 清除 Session 並恢復，PASS |
| Session | 一般網路錯誤 | 不誤判為 Session invalid，PASS |
| Retry | 1000 次暫時失敗 | 使用 loop 後恢復，PASS |
| Interrupt | KeyboardInterrupt | 不被 Retry 吞掉，PASS |
| JSON | fenced／前後文字 | 正確抽取，PASS |
| Schema | boolean 型別錯誤、空 criteria | 拒絕並 Retry，PASS |
| Agent timeout | 單次 call | 終止並產生可恢復錯誤，PASS |
| Agent timeout | 0 | 停用 timeout，PASS |
| Agent timeout | Execution／Review／AI Validator 各 timeout 一次 | 全部 Retry 後完成，PASS |
| Model call error | Execution 連續失敗 | 保存診斷並重進 Task attempt，PASS |
| Planning timeout | Qwen planning timeout／loop detection | 退回通用 Task，後續仍由 Agent 實作並驗證，PASS |
| Planned tasks | Planner 回傳兩個 Task | 依序 execute/review 每個 Task，再進 final validator，PASS |
| Validator repair | 連續相同 FAIL output | 進入 repair mode，依 validator feedback 修復並收斂，PASS |
| Validator repair planning | Validator FAIL 後 fallback planning | 產生單一 `Repair validator failure` task，不重跑原始完整 checklist，PASS |
| Validator repair review | Repair task 未修改 project 但 review 回 completed | Runner 改判未完成並 retry，PASS |
| Soak | 多輪 validator cycle | 最終 PASS，state 檔案保持有界，PASS |
| POSIX tree | 正常 child process | process group 全部終止，PASS |
| Detached pipe | detached child 持有 stdout | Runner 不永久卡在 communicate，PASS；測試後人工清除 child |
| Windows tree | `taskkill /PID /T /F` | 參數與 taskkill timeout 單元測試 PASS |
| Python Validator | timeout | 終止程序樹、保留 partial output，PASS |
| Python Validator | timeout 同時修改 protected file | 還原檔案並同時回報兩種診斷，PASS |
| Python Validator | 非零 exit | 保留 stdout 診斷，PASS |
| Validator args | 額外參數 | 正確傳遞，PASS |
| Task Review | completed=false | 重做同 Task，PASS |

## Real Qwen Smoke Cases

| Case | 驗證重點 | 最近結果 |
|---|---|---|
| `smoke/qwen_sorting_micro_pipeline` | 三段 YAML item 累積完成 bubble/insertion/selection sort；每段 execute/review/validator | 真實 Qwen PASS |
| `smoke/qwen_markdown_scoring` | Agent 產出 `docs/sorting_guide.md`；Python validator 檢查 H1/H2/table/example/bullets 並評分 | 真實 Qwen `score=94/100` PASS |
| `smoke/qwen_data_structures` | LRUCache、merge_intervals、top_k_frequent 固定行為驗證 | 真實 Qwen PASS |
| `smoke/qwen_single_prompt_todo_split` | 單一 prompt 內含編號 deliverables；fallback planning 保留為多個有序 task，逐一 execute/review 後 final validator | 真實 Qwen PASS |
| `smoke/qwen_csv_analyzer` | 單一自然語言 prompt；Agent 產生 CSV analyzer、JSON/Markdown report、README，validator 檢查輸出與多 task review state | 真實 Qwen PASS |
| `smoke/qwen_expression_evaluator` | 單一自然語言 prompt；Agent 產生安全 expression evaluator、CLI、batch JSON/Markdown、README，validator 禁用 eval/exec | 真實 Qwen PASS |
| `smoke/qwen_todo_cli` | 單一自然語言 prompt；Agent 產生 persistent todo CLI、JSON persistence、Markdown export、README，測到 timeout/loop 後 review fallback | 真實 Qwen PASS |
| Backend rules | Qwen root `QWEN.md`、OpenCode root `AGENTS.md` | PASS |
| 2026-07-26 local Qwen `qwen_simple` | 單 prompt 產生 `hello.txt`；第一次 validator FAIL 後自動 repair | 真實 Qwen PASS |
| 2026-07-26 local Qwen `qwen_sorting_min` | 單 prompt 產生排序 module；loop detection、validator FAIL 多輪 repair | 真實 Qwen PASS |
| 2026-07-26 local Qwen `qwen_markdown_scoring` | 單 prompt 分成多個 TODO 逐項 review，Python validator 評分，resume 後修復 | 真實 Qwen PASS |
| Task attempts | 正數上限 | Exit code 2，PASS |
| Validator cycles | 正數上限 | Exit code 3，PASS |
| 無限制 | attempts/cycles = 0 | 原有 re-plan／stagnation 測試持續至 PASS |
| No progress | 三次相同 fingerprint＋missing items | 第四次改變策略，PASS |
| Protected file | Task 修改 | 還原並 Retry，PASS |
| Read-only | 修改／新增／刪除／rename | 全部還原，PASS |
| Read-only excludes | build／dependency cache | 不還原 disposable artifact，PASS |
| AI Validator | 修改 project | 還原並 Retry，PASS |
| Validator FAIL | Python／AI | 保留修改、重新規劃、最終 PASS |
| YAML | 缺 validator、非 array | Fail-fast，PASS |
| YAML Resume | 已完成／未完成 item | 跳過與續跑正確，PASS |
| Events | callback exception | Runner 繼續，PASS |
| Events | JSON consumer BrokenPipe | Runner 繼續，PASS |
| State growth | output／reason／missing items | 長度與數量有界，PASS |
| Cleanup | `.tmp`、舊 readonly backup | 清理正確，PASS |

## Additional Watchdog Coverage

| Case | Scenario | Result |
|---|---|---|
| Agent idle after change | Execution writes project files then hangs before returning | Watchdog stops early, read-only review accepts completed task, PASS |

## 不可由單元／短整合測試完全證明

以下需目標環境 soak test 或外部基礎設施：

- 真實 Qwen／OpenCode 版本連續 12–24 小時
- Windows 實機 `taskkill /T /F` 對實際 CLI 子程序樹
- 主機重開後 Task Scheduler／NSSM／systemd 的 `--resume`
- OOM、磁碟滿、檔案系統損毀
- CLI 主動建立完全 detached daemon
- 任務或 Validator 本身永遠不可達成

這些限制不應描述成 Runner 能「無條件保證一定完成」。可保證的是：在程序與環境仍可運作時，可恢復異常會 Retry，且 Validator 未 PASS 不會誤標完成。
