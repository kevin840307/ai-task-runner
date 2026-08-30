# Workflow Dry Run 範例

此資料夾用 Mock Stage 結果驗證真正的 `workflow.yaml` routing，不會呼叫真實 AI Agent。
工具會重用正式的 Workflow Loader、Pipeline、StageResult 與 Stage finish/result handler；只有最底層 Stage 執行結果被 Mock。

Windows 執行：

```bat
run_dryrun.bat
```

批次會驗證兩種流程：

1. `runner/workflow/builtin/mixed.yaml`：包含 Plan -> 動態 Execute/Review、Review Recover、File Validator Recover，最後必須 completed。
2. `dryrunexample/workflow.yaml`：自訂 Workflow，`check` 連續 FAIL 三次，驗證 `recover`、`max_results` 後仍可進入 final 並閉環完成。

Scenario 只是測試資料，不會改變正式 Workflow 行為。未指定 Stage 預設為 `PASS`；結果序列用完後會持續使用最後一個結果。

## 自動 Failure Matrix

```bat
python ..\tool\workflow_dryrun.py ..\runner\workflow\builtin\mixed.yaml --matrix
```

Matrix 會自動測 Happy Path，並對每個具有 recover 的 Stage 各測一次 `FAIL -> recover -> closure`。Workflow 語法與參數一律先由正式 Loader/schema 驗證；非法參數會以 exit code `2` 與 `DRYRUN_ERROR` 結束。
