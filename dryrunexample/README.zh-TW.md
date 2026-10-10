# Workflow Dry Run 範例

此資料夾使用 Mock Stage 結果驗證正式 Workflow graph，不會呼叫真實 AI Agent。

`tool/workflow_dryrun.py` 直接重用正式 Workflow Loader 與 FlowEngine；只有 Stage execution result 被 Mock，因此 Dry Run 不維護第二套路由／Recovery Engine。

Windows 執行：

```bat
run_dryrun.bat
```

批次涵蓋：

1. `runner/workflows/mixed.yaml`：明確的 Planning -> task-scoped Execute/Review -> File/AI Validator。
2. `dryrunexample/workflow.yaml`：一般 FAIL result edge 回到前一個 Stage。
3. 兩者的 deterministic failure matrix。

Scenario 只改變 Mock StageResult；未指定 Stage 預設 PASS，序列用完後持續使用最後一個值。

## 自動 Failure Matrix

```bat
python ..\tool\workflow_dryrun.py ..\runner\workflows\mixed.yaml --matrix --json
```

Matrix 驗證 Happy Path、可達的 semantic FAIL result edges 與 ERROR 安全停止。Workflow 語法與 route target 一律先由正式 Loader 驗證。

Technical retry、Same Session、Fresh Session 與 API backoff 不在 Dry Run 模擬；這些屬於 StageExecutor 測試與 real-Qwen reliability harness。
