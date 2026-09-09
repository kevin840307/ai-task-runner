# Workflow Dry Run 範例

此資料夾用 Mock Stage 結果驗證真正的 `workflow.yaml` routing，不會呼叫真實 AI Agent。
工具會重用正式的 Workflow Loader、Pipeline、StageResult 與 Stage finish 與 result reducer；只有最底層 Stage 執行結果被 Mock。

Windows 執行：

```bat
run_dryrun.bat
```

批次會驗證兩種流程：

1. `runner/workflow/system/mixed.yaml`：包含 Plan -> 內建 Task/Review/Repair lifecycle、File Validator Recover，最後必須 completed。
2. `dryrunexample/workflow.yaml`：自訂 Workflow，`check` 連續 FAIL 三次，驗證 `recover`、`repeat` 後仍可進入 final 並閉環完成。

Scenario 只是測試資料，不會改變正式 Workflow 行為。未指定 Stage 預設為 `PASS`；結果序列用完後會持續使用最後一個結果。

## 自動 Failure Matrix

```bat
python ..\tool\workflow_dryrun.py ..\runner\workflow\system\mixed.yaml --matrix
```

Matrix 會自動測 Happy Path，並對每個具有 recover 的 Stage 各測一次 `FAIL -> recover -> closure`。Workflow 語法與參數一律先由正式 Loader/schema 驗證；非法參數會以 exit code `2` 與 `DRYRUN_ERROR` 結束。

### 目前可靠性涵蓋

`workflow_dryrun.py --matrix` 不呼叫模型，專注驗證 deterministic workflow topology、task lifecycle closure、recover/restart/repeat/max-attempt routing、fresh-session semantic threshold，以及 ERROR fail-closed 路徑。Backend/tool-loop retry policy 刻意不在 dry-run 內 mock；它由 Runner unit test 與 `qwen_live_reliability.py` 的 loop-policy preflight 驗證，讓 dry-run 維持 deterministic 與低耦合。

