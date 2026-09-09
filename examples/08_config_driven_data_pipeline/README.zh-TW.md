# 08 Config-Driven Data Pipeline

這是一個中等複雜度的 Mixed Validation 範例，用來驗證 AI Task Runner 的 Python hard gate + Final AI voting 流程。

驗證順序：

1. 先執行 Python hard validator，而且只做 black-box behavioral tests。
2. File Validator PASS 後，才啟動 3 個彼此獨立的 Fresh AI Validator Session。
3. Final AI Validation 預設採嚴格過半投票；若 YAML/CLI 明確設定 required passes，則依該門檻判斷。
4. Hard Validation 與 AI Validation 都 PASS，整個任務才算完成。

Windows 執行：

    run_example.bat --backend qwen

也可以把這個 task 加入主 `examples.yaml`，透過 YAML List 依序執行。

這個範例的 File Validator 不檢查 source architecture、file count、class/function 數量或 line count；它只驗證 Goal 明確要求的 observable behavior，避免把 Planner strategy 或實作風格變成 hidden hard gate。

YAML script 使用 root-level list，格式與 `examples/examples.yaml` 相同。每個 item 都由 Runner 建立獨立 nested state，並沿用相同 24H recovery/session/plugin contract。

`run_example.bat` 會先建立全新的暫存 repository 副本再執行，原始範例不會被修改。
